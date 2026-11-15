"""Python client for CoAP Observe multicast notifications (nosec profile).

Written from draft-ietf-core-observe-multicast-notifications-15, Section 5 (client side),
and RFC 7252 / RFC 7641, not from the C implementation. Standard library only.

One run = one client:
  1. send a CON GET with Observe=0 to coap://HOST:PORT/RESOURCE           (draft 5.1)
  2. accept the 5.03 informative response, ACK it, decode tp_info,
     rebuild the phantom request, use last_notif as Observe baseline        (draft 5.2)
  3. join GRP_ADDR:GRP_PORT, accept notifications from SRV with token T,
     reorder by Observe (RFC 7641 3.4)                                       (draft 5.3)
Prints one "[NOTIFICATION] observe=<n> payload=<text>" line per fresh notification.
Exit 0 only after --notifs fresh notifications; 1 on any protocol error or timeout.
"""

import argparse
import ipaddress
import os
import random
import socket
import struct
import sys
import time

CON, NON, ACK, RST = 0, 1, 2, 3
GET = 0x01
CODE_5_03 = (5 << 5) | 3
OPT_OBSERVE, OPT_URI_PATH, OPT_CONTENT_FORMAT = 6, 11, 12
COAP_SCHEME_ID = -1  # CRI scheme-id for "coap" (draft 4.2.1)
DEFAULT_PORT = 5683


def log(msg):
    print(msg, flush=True)


def fail(msg):
    log(f"[ERROR] {msg}")
    sys.exit(1)


# ---------------------------------------------------------------- CoAP (RFC 7252)


def _nibble(v):
    """Returns (4-bit nibble, extended bytes) for an option delta or length (RFC 7252 3.1)."""
    if v < 13:
        return v, b""
    if v < 269:
        return 13, bytes([v - 13])
    return 14, struct.pack("!H", v - 269)


def encode_options(options):
    """options: list of (number, bytes); returns the serialized option sequence."""
    out, prev = bytearray(), 0
    for num, val in sorted(options, key=lambda o: o[0]):
        d, d_ext = _nibble(num - prev)
        n, n_ext = _nibble(len(val))
        prev = num
        out.append((d << 4) | n)
        out += d_ext + n_ext + val
    return bytes(out)


def decode_options(data):
    """Parses options (+ optional 0xFF payload marker). Returns (options, payload)."""
    options, i, num = [], 0, 0
    while i < len(data):
        if data[i] == 0xFF:
            if i + 1 == len(data):
                raise ValueError("payload marker followed by empty payload")
            return options, data[i + 1 :]
        d, n = data[i] >> 4, data[i] & 0x0F
        i += 1

        def ext(v):
            nonlocal i
            if v == 13:
                v = data[i] + 13
                i += 1
            elif v == 14:
                v = struct.unpack("!H", data[i : i + 2])[0] + 269
                i += 2
            elif v == 15:
                raise ValueError("reserved option nibble 15")
            return v

        d, n = ext(d), ext(n)
        num += d
        if i + n > len(data):
            raise ValueError("option runs past end of message")
        options.append((num, data[i : i + n]))
        i += n
    return options, b""


def uint_bytes(v):
    return v.to_bytes((v.bit_length() + 7) // 8, "big") if v else b""


def opt_uint(val):
    return int.from_bytes(val, "big") if val else 0


class Msg:
    def __init__(self, raw):
        if len(raw) < 4:
            raise ValueError("shorter than CoAP header")
        b0 = raw[0]
        self.version, self.type, tkl = b0 >> 6, (b0 >> 4) & 3, b0 & 0x0F
        if self.version != 1 or tkl > 8:
            raise ValueError("bad CoAP version or token length")
        self.code = raw[1]
        self.mid = struct.unpack("!H", raw[2:4])[0]
        self.token = raw[4 : 4 + tkl]
        self.options, self.payload = decode_options(raw[4 + tkl :])

    def opt(self, num):
        return [v for n, v in self.options if n == num]

    def code_str(self):
        return f"{self.code >> 5}.{self.code & 0x1F:02d}"


def build(mtype, code, mid, token=b"", options=(), payload=b""):
    head = bytes([(1 << 6) | (mtype << 4) | len(token), code]) + struct.pack("!H", mid)
    body = encode_options(list(options))
    if payload:
        body += b"\xff" + payload
    return head + token + body


# ---------------------------------------------------------------- CBOR (RFC 8949, subset)


def cbor_decode(data):
    value, end = _cbor_item(data, 0)
    if end != len(data):
        raise ValueError(f"{len(data) - end} trailing bytes after CBOR item")
    return value


def _cbor_item(data, i):
    if i >= len(data):
        raise ValueError("truncated CBOR")
    ib = data[i]
    major, info = ib >> 5, ib & 0x1F
    i += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if i + size > len(data):
            raise ValueError("truncated CBOR argument")
        arg = int.from_bytes(data[i : i + size], "big")
        i += size
    else:
        raise ValueError(f"unsupported CBOR additional info {info}")
    if major == 0:
        return arg, i
    if major == 1:
        return -1 - arg, i
    if major in (2, 3):
        if i + arg > len(data):
            raise ValueError("truncated CBOR string")
        s = data[i : i + arg]
        return (bytes(s) if major == 2 else s.decode("utf-8")), i + arg
    if major == 4:
        out = []
        for _ in range(arg):
            v, i = _cbor_item(data, i)
            out.append(v)
        return out, i
    if major == 5:
        out = {}
        for _ in range(arg):
            k, i = _cbor_item(data, i)
            v, i = _cbor_item(data, i)
            out[k] = v
        return out, i
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], i
    raise ValueError(f"unsupported CBOR major type {major}")


# ---------------------------------------------------------------- draft 4.2.1: CRI


def parse_cri(cri, what):
    """CRI-no-local = [scheme-id, authority]; authority = [?userinfo, host, ?port].
    Returns (ip_string, port_or_None). Only host-ip is accepted (no DNS here)."""
    if not isinstance(cri, list) or len(cri) != 2:
        raise ValueError(f"{what}: CRI must be [scheme-id, authority]")
    scheme, auth = cri
    if scheme != COAP_SCHEME_ID:
        raise ValueError(f"{what}: scheme-id {scheme!r} is not coap (-1)")
    if not isinstance(auth, list) or not auth:
        raise ValueError(f"{what}: authority must be a non-empty array")
    if auth[0] is False:  # userinfo is encoded as false, tstr
        auth = auth[2:]
    if not auth:
        raise ValueError(f"{what}: authority has no host")
    host, port = auth[0], (auth[1] if len(auth) > 1 else None)
    if not isinstance(host, bytes) or len(host) not in (4, 16):
        raise ValueError(
            f"{what}: host must be a host-ip (4 or 16 bytes), got {host!r}"
        )
    if port is not None and not (isinstance(port, int) and 0 <= port <= 65535):
        raise ValueError(f"{what}: bad port {port!r}")
    return str(ipaddress.ip_address(host)), port


# ---------------------------------------------------------------- RFC 7641 3.4


def is_fresher(v_new, v_old, t_new, t_old):
    return (
        (v_old < v_new and v_new - v_old < 2**23)
        or (v_old > v_new and v_old - v_new > 2**23)
        or t_new > t_old + 128
    )


# ---------------------------------------------------------------- client


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--resource", default="mult")
    ap.add_argument("--notifs", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    deadline = time.monotonic() + args.timeout
    server = (args.host, args.port)
    uni = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uni.bind(("0.0.0.0", 0))

    # 5.1: registration request
    token, mid = os.urandom(8), random.randrange(0x10000)
    reg_opts = [(OPT_OBSERVE, b"")] + [
        (OPT_URI_PATH, s.encode()) for s in args.resource.split("/") if s
    ]
    reg_ti = bytes([GET]) + encode_options(
        reg_opts
    )  # transport-independent part (draft 4.2.2)
    reg = build(CON, GET, mid, token, reg_opts)
    log(
        f"[REGISTER] GET coap://{args.host}:{args.port}/{args.resource} Observe=0 token={token.hex()}"
    )

    # Retransmit the CON per RFC 7252 4.2 until any matching reply arrives.
    resp, tries, wait = None, 0, 2.0
    while resp is None:
        if tries > 4 or time.monotonic() > deadline:
            fail("no reply to the registration request")
        uni.sendto(reg, server)
        tries += 1
        uni.settimeout(wait)
        wait *= 2
        acked = False
        while True:
            try:
                raw, src = uni.recvfrom(2048)
            except TimeoutError:
                break
            try:
                m = Msg(raw)
            except ValueError as e:
                log(f"[WARN] ignoring malformed datagram from {src}: {e}")
                continue
            if m.type == ACK and m.mid == mid and m.code == 0:
                acked = True  # empty ACK: separate response follows (RFC 7252 5.2.2)
                uni.settimeout(max(1.0, deadline - time.monotonic()))
                continue
            if m.token == token:
                if m.type == CON:
                    uni.sendto(build(ACK, 0, m.mid), src)
                resp = m
                break
        if acked and resp is None:
            fail("registration ACKed but no separate response arrived")

    log(f"[RESPONSE] {resp.code_str()} type={resp.type} token={resp.token.hex()}")
    if resp.code != CODE_5_03:
        fail(f"expected a 5.03 informative response (draft 4.2), got {resp.code_str()}")
    if resp.opt(OPT_OBSERVE):
        fail("informative response carries an Observe option (draft 4.2: MUST NOT)")
    cf = resp.opt(OPT_CONTENT_FORMAT)
    if not cf:
        fail("informative response has no Content-Format option")
    # The draft leaves this Content-Format ID as TBD (Section 15.2): log it, do not enforce a value.
    log(
        f"[INFO] informative response Content-Format={opt_uint(cf[0])} (draft 15.2: ID is TBD)"
    )

    # 5.2: process the informative response
    try:
        info = cbor_decode(resp.payload)
        if not isinstance(info, dict) or 0 not in info:
            raise ValueError("payload is not a CBOR map with 'tp_info' (key 0)")
        tp = info[0]
        if not isinstance(tp, list) or len(tp) < 3:
            raise ValueError("tp_info must be [tpi_server, tpi_client, tpi_token]")
        srv_ip, srv_port = parse_cri(tp[0], "tpi_server")
        grp_ip, grp_port = parse_cri(tp[1], "tpi_client")
        tok_t = tp[2]
        if not isinstance(tok_t, bytes) or not 1 <= len(tok_t) <= 8:
            raise ValueError(f"tpi_token must be a 1..8 byte string, got {tok_t!r}")
    except ValueError as e:
        fail(f"malformed informative response: {e}")
    srv_port = srv_port if srv_port is not None else DEFAULT_PORT  # 5.2 step 1
    grp_port = grp_port if grp_port is not None else DEFAULT_PORT
    if not ipaddress.ip_address(grp_ip).is_multicast:
        fail(f"tpi_client address {grp_ip} is not a multicast address")
    log(
        f"[TP_INFO] server={srv_ip}:{srv_port} group={grp_ip}:{grp_port} token_T={tok_t.hex()}"
    )

    # Step 2/3: phantom request; compare ph_req with our own registration.
    ph_req = info.get(1)
    if ph_req is not None:
        if not isinstance(ph_req, bytes):
            fail("ph_req is not a byte string")
        if ph_req != reg_ti:
            fail(
                f"ph_req {ph_req.hex()} differs from our registration {reg_ti.hex()} (draft 5.2 step 3)"
            )
        log("[INFO] ph_req matches our registration request")

    # Step 5/6: last_notif gives the Observe baseline.
    last_obs, last_t = None, time.monotonic()
    ln = info.get(2)
    if ln is not None:
        try:
            if not isinstance(ln, bytes) or not ln:
                raise ValueError("not a non-empty byte string")
            opts, payload = decode_options(ln[1:])
            obs = [v for n, v in opts if n == OPT_OBSERVE]
            if obs:
                last_obs = opt_uint(obs[0])
            log(
                f"[LAST_NOTIF] code={ln[0] >> 5}.{ln[0] & 0x1F:02d} observe={last_obs} payload={payload!r}"
            )
        except (ValueError, IndexError) as e:
            fail(f"malformed last_notif: {e}")

    # 5.3: join the group and receive notifications for token T from SRV.
    mc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        mc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    mc.bind(("0.0.0.0", grp_port))
    iface = srv_ip if ipaddress.ip_address(srv_ip).is_loopback else "0.0.0.0"
    mreq = socket.inet_aton(grp_ip) + socket.inet_aton(iface)
    mc.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    log(f"[JOIN] {grp_ip}:{grp_port} on interface {iface}")

    seen = 0
    while seen < args.notifs:
        left = deadline - time.monotonic()
        if left <= 0:
            fail(f"timeout: {seen}/{args.notifs} notifications")
        mc.settimeout(left)
        try:
            raw, src = mc.recvfrom(2048)
        except TimeoutError:
            continue
        try:
            m = Msg(raw)
        except ValueError as e:
            log(f"[WARN] ignoring malformed datagram from {src}: {e}")
            continue
        if src != (srv_ip, srv_port) or m.token != tok_t:
            log(
                f"[WARN] ignoring datagram from {src[0]}:{src[1]} token={m.token.hex()}"
            )
            continue
        if m.code >> 5 != 2:
            fail(f"group observation ended with {m.code_str()} (draft 4.5)")
        obs = m.opt(OPT_OBSERVE)
        if not obs:
            log("[WARN] notification without Observe option, ignored")
            continue
        v, now = opt_uint(obs[0]), time.monotonic()
        if last_obs is not None and not is_fresher(v, last_obs, now, last_t):
            log(f"[STALE] observe={v} (latest {last_obs}), ignored per RFC 7641 3.4")
            continue
        last_obs, last_t = v, now
        seen += 1
        text = m.payload.decode("utf-8", "replace")
        log(
            f"[NOTIFICATION] observe={v} type={'NON' if m.type == NON else m.type} payload={text}"
        )

    log(f"[DONE] {seen}/{args.notifs} notifications")
    return 0


if __name__ == "__main__":
    sys.exit(main())
