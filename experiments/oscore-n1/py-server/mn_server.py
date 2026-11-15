"""Python server for CoAP Observe multicast notifications (nosec profile).

Written from draft-ietf-core-observe-multicast-notifications-15, Section 4 (server side),
and RFC 7252 / RFC 7641, not from the C implementation. Standard library only.

  - On the first Observe registration for RESOURCE, start a group observation (4.1):
    phantom request GET+Observe(0)+Uri-Path, a fresh random Token T, INIT_NOTIF stored.
  - Every registration gets an empty ACK, then a CON 5.03 informative response without
    Observe (4.2), retransmitted until ACKed (RFC 7252 4.2). Payload: CBOR map with
    tp_info [tpi_server, tpi_client, tpi_token] (4.2.1.1), ph_req and last_notif (4.2.2).
  - Every --interval seconds (>= 3, 4.4) the resource changes and a NON 2.05 notification
    with Observe and Token T goes from SRV_ADDR:SRV_PORT to GRP_ADDR:GRP_PORT (4.3).
  - A plain GET (no Observe) gets a piggybacked 2.05; unknown paths 4.04; other methods 4.05.
Prints "Listening on ..." once ready. Stops on SIGINT/SIGTERM.
"""

import argparse
import ipaddress
import os
import random
import select
import signal
import socket
import struct
import sys
import time

CON, NON, ACK, RST = 0, 1, 2, 3
GET = 0x01
OPT_OBSERVE, OPT_URI_PATH, OPT_CONTENT_FORMAT = 6, 11, 12


def code(c, d):
    return (c << 5) | d


C_2_05, C_4_04, C_4_05, C_5_03 = code(2, 5), code(4, 4), code(4, 5), code(5, 3)
COAP_SCHEME_ID = -1  # CRI scheme-id for "coap" (draft 4.2.1)
DEFAULT_PORT = 5683
ACK_TIMEOUT, MAX_RETRANSMIT = 2.0, 4  # RFC 7252 4.8


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- CoAP (RFC 7252)


def _nibble(v):
    if v < 13:
        return v, b""
    if v < 269:
        return 13, bytes([v - 13])
    return 14, struct.pack("!H", v - 269)


def encode_options(options):
    out, prev = bytearray(), 0
    for num, val in sorted(options, key=lambda o: o[0]):
        d, d_ext = _nibble(num - prev)
        n, n_ext = _nibble(len(val))
        prev = num
        out.append((d << 4) | n)
        out += d_ext + n_ext + val
    return bytes(out)


def decode_options(data):
    options, i, num = [], 0, 0
    while i < len(data):
        if data[i] == 0xFF:
            if i + 1 == len(data):
                raise ValueError("payload marker followed by empty payload")
            return options, data[i + 1 :]
        d, n = data[i] >> 4, data[i] & 0x0F
        i += 1
        vals = []
        for v in (d, n):
            if v == 13:
                v = data[i] + 13
                i += 1
            elif v == 14:
                v = struct.unpack("!H", data[i : i + 2])[0] + 269
                i += 2
            elif v == 15:
                raise ValueError("reserved option nibble 15")
            vals.append(v)
        num += vals[0]
        if i + vals[1] > len(data):
            raise ValueError("option runs past end of message")
        options.append((num, data[i : i + vals[1]]))
        i += vals[1]
    return options, b""


def uint_bytes(v):
    return v.to_bytes((v.bit_length() + 7) // 8, "big") if v else b""


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


def build(mtype, c, mid, token=b"", options=(), payload=b""):
    head = bytes([(1 << 6) | (mtype << 4) | len(token), c]) + struct.pack("!H", mid)
    return head + token + transport_independent(None, options, payload)


def transport_independent(c, options, payload):
    """Draft 4.2.2: [Code byte] + options + (0xff + payload if non-empty).
    With c=None, returns only options + payload (used by build())."""
    body = encode_options(list(options))
    if payload:
        body += b"\xff" + payload
    return body if c is None else bytes([c]) + body


# ---------------------------------------------------------------- CBOR (RFC 8949, subset)


def _cbor_head(major, arg):
    if arg < 24:
        return bytes([(major << 5) | arg])
    for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if arg < 1 << (8 * size):
            return bytes([(major << 5) | info]) + arg.to_bytes(size, "big")
    raise ValueError("CBOR argument too large")


def cbor_encode(v):
    if isinstance(v, bool) or v is None:
        return bytes([{False: 0xF4, True: 0xF5, None: 0xF6}[v]])
    if isinstance(v, int):
        return _cbor_head(0, v) if v >= 0 else _cbor_head(1, -1 - v)
    if isinstance(v, bytes):
        return _cbor_head(2, len(v)) + v
    if isinstance(v, str):
        b = v.encode()
        return _cbor_head(3, len(b)) + b
    if isinstance(v, list):
        return _cbor_head(4, len(v)) + b"".join(cbor_encode(x) for x in v)
    if isinstance(v, dict):
        return _cbor_head(5, len(v)) + b"".join(
            cbor_encode(k) + cbor_encode(x) for k, x in v.items()
        )
    raise TypeError(f"cannot CBOR-encode {type(v).__name__}")


def cri(ip, port):
    """CRI-no-local [scheme-id, [host-ip, ?port]]; port omitted when it is the default (4.2.1.1)."""
    auth = [ipaddress.ip_address(ip).packed]
    if port != DEFAULT_PORT:
        auth.append(port)
    return [COAP_SCHEME_ID, auth]


# ---------------------------------------------------------------- server


class Server:
    def __init__(self, args):
        self.args = args
        self.path = [s.encode() for s in args.resource.split("/") if s]
        srv, grp = ipaddress.ip_address(args.addr), ipaddress.ip_address(args.group)
        if srv.version != 4 or grp.version != 4:
            sys.exit("only IPv4 is implemented")
        if srv.is_link_local or srv.is_unspecified:  # 4.2: MUST NOT be link-local
            sys.exit(f"server address {srv} must be a concrete, non link-local address")
        if not grp.is_multicast:
            sys.exit(f"group address {grp} is not multicast")
        if (
            args.interval < 3
        ):  # 4.4: SHOULD NOT send more than one notification every 3 s
            sys.exit("--interval must be >= 3 seconds (draft Section 4.4)")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(
            (args.addr, args.port)
        )  # SRV_ADDR:SRV_PORT for responses AND notifications (4.3)
        self.sock.setsockopt(
            socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(args.addr)
        )
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        self.mid = random.randrange(0x10000)
        self.state = 0  # the resource representation is this counter, as text
        self.group = None  # set when the group observation starts
        self.pending = {}  # mid -> [datagram, dest, next_time, timeout, retransmits]
        self.seen = {}  # (src, mid) -> reply datagram, for CON deduplication (RFC 7252 4.5)
        self.observers = 0  # observer counter (Section 4)

    def next_mid(self):
        self.mid = (self.mid + 1) & 0xFFFF
        return self.mid

    def representation(self):
        return str(self.state).encode()

    # ---- 4.1: start the group observation
    def start_group(self):
        token = os.urandom(self.args.token_len)
        ph_opts = [(OPT_OBSERVE, b"")] + [(OPT_URI_PATH, s) for s in self.path]
        self.group = {
            "token": token,
            "ph_req": transport_independent(GET, ph_opts, b""),
            "observe": 0,
        }
        self.group["last_notif"] = (
            self.notif_ti()
        )  # INIT_NOTIF, stored and not sent (step 6)
        self.group["last_time"] = time.monotonic()
        self.group["next_send"] = time.monotonic() + self.args.interval
        log(
            f"[GROUP] started: phantom GET /{self.args.resource} Observe=0, token T={token.hex()}, "
            f"notifications {self.args.addr}:{self.args.port} -> {self.args.group}:{self.args.group_port}"
        )

    def notif_opts(self):
        return [
            (OPT_OBSERVE, uint_bytes(self.group["observe"])),
            (OPT_CONTENT_FORMAT, b""),
        ]

    def notif_ti(self):
        return transport_independent(C_2_05, self.notif_opts(), self.representation())

    # ---- 4.2: informative response
    def informative_payload(self):
        a = self.args
        g = self.group
        return cbor_encode(
            {
                0: [cri(a.addr, a.port), cri(a.group, a.group_port), g["token"]],
                1: g["ph_req"],
                2: g["last_notif"],
                3: max(0, int(g["next_send"] - time.monotonic())),
            }
        )

    def send_informative(self, req, src):
        if self.group is None:
            self.start_group()
        self.observers += 1
        mid = self.next_mid()
        dgram = build(
            CON,
            C_5_03,
            mid,
            req.token,
            [(OPT_CONTENT_FORMAT, uint_bytes(self.args.content_format))],
            self.informative_payload(),
        )
        self.sock.sendto(dgram, src)
        timeout = ACK_TIMEOUT * random.uniform(1.0, 1.5)
        self.pending[mid] = [dgram, src, time.monotonic() + timeout, timeout, 0]
        log(
            f"[INFORMATIVE] CON 5.03 to {src[0]}:{src[1]} token={req.token.hex()} mid={mid} "
            f"(observers={self.observers})"
        )

    # ---- 4.3: multicast notification
    def send_notification(self):
        g = self.group
        self.state += 1
        g["observe"] = (g["observe"] + 1) & 0xFFFFFF
        dgram = build(
            NON,
            C_2_05,
            self.next_mid(),
            g["token"],
            self.notif_opts(),
            self.representation(),
        )
        self.sock.sendto(dgram, (self.args.group, self.args.group_port))
        g["last_notif"] = self.notif_ti()  # replaces INIT_NOTIF (4.1 step 6, 4.3)
        g["last_time"] = time.monotonic()
        g["next_send"] = time.monotonic() + self.args.interval
        log(
            f"[NOTIFY] NON 2.05 Observe={g['observe']} state={self.state} -> {self.args.group}:{self.args.group_port}"
        )

    # ---- request handling
    def handle(self, raw, src):
        try:
            m = Msg(raw)
        except ValueError as e:
            log(f"[WARN] malformed datagram from {src[0]}:{src[1]}: {e}")
            return
        if m.type == ACK or m.type == RST:
            if m.mid in self.pending and self.pending[m.mid][1] == src:
                del self.pending[m.mid]
                log(
                    f"[{'ACK' if m.type == ACK else 'RST'}] from {src[0]}:{src[1]} mid={m.mid}"
                )
            return
        if m.code == 0:  # empty CON = ping (RFC 7252 4.3)
            if m.type == CON:
                self.sock.sendto(build(RST, 0, m.mid), src)
            return
        if m.code >> 5 != 0:  # a response sent to us: ignore
            return
        if (
            m.type == CON and (src, m.mid) in self.seen
        ):  # duplicate: repeat the ACK only
            self.sock.sendto(self.seen[(src, m.mid)], src)
            return

        path = m.opt(OPT_URI_PATH)
        obs = m.opt(OPT_OBSERVE)
        if path != self.path:
            self.reply(m, src, C_4_04)
        elif m.code != GET:
            self.reply(m, src, C_4_05)
        elif obs and int.from_bytes(obs[0], "big") == 0:
            log(f"[REGISTER] {src[0]}:{src[1]} token={m.token.hex()} mid={m.mid}")
            ack = build(
                ACK, 0, m.mid
            )  # empty ACK: the 5.03 is a separate response (4.2)
            if m.type == CON:
                self.sock.sendto(ack, src)
                self.seen[(src, m.mid)] = ack
            self.send_informative(m, src)
        else:  # plain GET or deregistration: current representation
            self.reply(
                m, src, C_2_05, [(OPT_CONTENT_FORMAT, b"")], self.representation()
            )

    def reply(self, m, src, c, options=(), payload=b""):
        if m.type == CON:
            dgram = build(ACK, c, m.mid, m.token, options, payload)
            self.seen[(src, m.mid)] = dgram
        else:
            dgram = build(NON, c, self.next_mid(), m.token, options, payload)
        self.sock.sendto(dgram, src)

    def retransmit(self, now):
        for mid, p in list(self.pending.items()):
            dgram, dest, due, timeout, n = p
            if now < due:
                continue
            if n >= MAX_RETRANSMIT:
                del self.pending[mid]
                log(f"[GIVEUP] no ACK for mid={mid} from {dest[0]}:{dest[1]}")
                continue
            self.sock.sendto(dgram, dest)
            p[2:] = [now + timeout * 2, timeout * 2, n + 1]
            log(
                f"[RETRANSMIT] mid={mid} to {dest[0]}:{dest[1]} ({n + 1}/{MAX_RETRANSMIT})"
            )

    def run(self):
        stop = []
        for s in (signal.SIGINT, signal.SIGTERM):
            signal.signal(s, lambda *_: stop.append(1))
        log(
            f"Listening on coap://{self.args.addr}:{self.args.port}/{self.args.resource}"
        )
        while not stop:
            now = time.monotonic()
            deadlines = [p[2] for p in self.pending.values()]
            if self.group:
                deadlines.append(self.group["next_send"])
            wait = max(0.0, min(deadlines) - now) if deadlines else 1.0
            try:
                ready, _, _ = select.select([self.sock], [], [], min(wait, 1.0))
            except InterruptedError:
                continue
            if ready:
                raw, src = self.sock.recvfrom(2048)
                self.handle(raw, src)
            now = time.monotonic()
            self.retransmit(now)
            if self.group and now >= self.group["next_send"]:
                self.send_notification()
        log(f"Server stopped (observers={self.observers}, state={self.state}).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", default="127.0.0.1", help="SRV_ADDR")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="SRV_PORT")
    ap.add_argument("--resource", default="mult")
    ap.add_argument("--group", default="224.0.1.187", help="GRP_ADDR")
    ap.add_argument("--group-port", type=int, default=56830, help="GRP_PORT")
    ap.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between notifications (>= 3)",
    )
    ap.add_argument(
        "--token-len", type=int, default=4, choices=range(1, 9), metavar="1..8"
    )
    # Draft 15.2 leaves the Content-Format ID as TBD; 12 is the placeholder the C peers use.
    ap.add_argument("--content-format", type=int, default=12)
    Server(ap.parse_args()).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
