"""Adversarial server: answer one Observe registration with a malformed informative response,
then send notifications to the group anyway, and see whether the client accepts them.

Draft Section 5.2: "If any of the expected fields in the informative response are absent,
malformed, or invalid, the client MAY try sending a new registration request ... If the client
chooses not to, then the client SHOULD explicitly withdraw from the group observation."
A client that prints notifications after a malformed informative response has not withdrawn.

Each --variant breaks one thing; the notifications that follow use GOOD_TOKEN, sent from
127.0.0.1:5683 to 224.0.1.187:56830, i.e. where a client that ignored the error would listen.
Reuses the encoders of ../py-server/mn_server.py. Standard library only.
"""

import argparse
import importlib.util
import os
import socket
import time

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "mn_server", os.path.join(here, "..", "py-server", "mn_server.py")
)
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

GOOD_TOKEN = bytes.fromhex("11223344")
SRV = ("127.0.0.1", 5683)
GRP = ("224.0.1.187", 56830)


def ph_req(path=b"mult"):
    return srv.transport_independent(
        srv.GET, [(srv.OPT_OBSERVE, b""), (srv.OPT_URI_PATH, path)], b""
    )


def last_notif():
    return srv.transport_independent(
        srv.C_2_05, [(srv.OPT_OBSERVE, b""), (srv.OPT_CONTENT_FORMAT, b"")], b"0"
    )


def good_tp():
    return [srv.cri(*SRV), srv.cri(*GRP), GOOD_TOKEN]


def payload(variant):
    """Returns (payload bytes, description). Each variant violates one rule."""
    enc = srv.cbor_encode
    good = {0: good_tp(), 1: ph_req(), 2: last_notif()}
    if variant == "good":
        return enc(good), "well-formed (control)"
    if variant == "stray-cancel":
        return (
            enc(good),
            "well-formed, but after notification 1 a 5.03 cancellation with ANOTHER token goes to the group",
        )
    if variant == "no-tp-info":
        return enc(
            {1: ph_req(), 2: last_notif()}
        ), "tp_info (key 0) absent; 4.2: MUST be included"
    if variant == "not-cbor":
        return b"hello, not CBOR", "payload is not CBOR"
    if variant == "truncated":
        p = enc(good)
        return p[: len(p) // 2], "CBOR cut in half"
    if variant == "unicast-group":
        tp = good_tp()
        tp[1] = srv.cri("127.0.0.1", 56830)
        return enc({**good, 0: tp}), "tpi_client is 127.0.0.1, not a multicast address"
    if variant == "bad-scheme":
        tp = good_tp()
        tp[0][0] = -2  # "coaps"
        tp[1][0] = -2
        return enc(
            {**good, 0: tp}
        ), "scheme-id -2 (coaps) instead of -1 (coap) for CoAP over UDP"
    if variant == "empty-token":
        tp = good_tp()
        tp[2] = b""
        return enc({**good, 0: tp}), "tpi_token is an empty byte string"
    if variant == "long-token":
        tp = good_tp()
        tp[2] = bytes(range(1, 10))
        return enc({**good, 0: tp}), "tpi_token is 9 bytes; CoAP tokens are 0..8 bytes"
    if variant == "token-not-bstr":
        tp = good_tp()
        tp[2] = 0x11223344
        return enc({**good, 0: tp}), "tpi_token is an integer, not a byte string"
    if variant == "token-mismatch":
        tp = good_tp()
        tp[2] = bytes.fromhex("aabbccdd")
        return enc(
            {**good, 0: tp}
        ), "tpi_token is aabbccdd but notifications carry 11223344 (5.3: Token T)"
    if variant == "source-mismatch":
        tp = good_tp()
        tp[0] = srv.cri("127.0.0.1", 5699)
        return (
            enc({**good, 0: tp}),
            "tpi_server says 127.0.0.1:5699; notifications come from :5683 (4.3, 5.2 step 1)",
        )
    if variant == "ph-req-mismatch":
        return enc(
            {**good, 1: ph_req(b"other")}
        ), "ph_req targets /other, the client registered /mult (5.2 step 3)"
    if variant == "tp-info-short":
        return enc({**good, 0: good_tp()[:2]}), "tp_info has no tpi_token (2 elements)"
    raise SystemExit(f"unknown variant {variant}")


VARIANTS = [
    "good",
    "stray-cancel",
    "no-tp-info",
    "not-cbor",
    "truncated",
    "unicast-group",
    "bad-scheme",
    "empty-token",
    "long-token",
    "token-not-bstr",
    "token-mismatch",
    "source-mismatch",
    "ph-req-mismatch",
    "tp-info-short",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=VARIANTS)
    ap.add_argument("--notifs", type=int, default=3)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument(
        "--wait",
        type=float,
        default=15.0,
        help="max seconds to wait for a registration",
    )
    args = ap.parse_args()

    body, what = payload(args.variant)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(SRV)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(SRV[0]))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    print(f"Listening; variant={args.variant}: {what}", flush=True)

    s.settimeout(args.wait)
    try:
        raw, client = s.recvfrom(2048)
    except TimeoutError:
        raise SystemExit("no registration received")
    req = srv.Msg(raw)
    print(
        f"[REGISTER] from {client[0]}:{client[1]} token={req.token.hex()}", flush=True
    )
    s.sendto(srv.build(srv.ACK, 0, req.mid), client)
    mid = 1000
    s.sendto(
        srv.build(
            srv.CON,
            srv.C_5_03,
            mid,
            req.token,
            [(srv.OPT_CONTENT_FORMAT, b"\x0c")],
            body,
        ),
        client,
    )
    print(f"[INFORMATIVE] sent ({len(body)} bytes payload)", flush=True)

    s.settimeout(0.2)
    for n in range(1, args.notifs + 1):
        end = time.monotonic() + args.interval
        while time.monotonic() < end:  # drain ACK / RST / re-registrations
            try:
                raw, src = s.recvfrom(2048)
                m = srv.Msg(raw)
                kind = {0: "CON", 1: "NON", 2: "ACK", 3: "RST"}[m.type]
                print(
                    f"[RECV] {kind} code={m.code >> 5}.{m.code & 31:02d} from {src[0]}:{src[1]}",
                    flush=True,
                )
            except (TimeoutError, ValueError):
                pass
        opts = [(srv.OPT_OBSERVE, srv.uint_bytes(n)), (srv.OPT_CONTENT_FORMAT, b"")]
        s.sendto(
            srv.build(srv.NON, srv.C_2_05, mid + n, GOOD_TOKEN, opts, str(n).encode()),
            GRP,
        )
        print(
            f"[NOTIFY] Observe={n} token={GOOD_TOKEN.hex()} -> {GRP[0]}:{GRP[1]}",
            flush=True,
        )
        if args.variant == "stray-cancel" and n == 1:
            other = bytes.fromhex("aabbccdd")
            s.sendto(srv.build(srv.NON, srv.C_5_03, 2000, other), GRP)
            print(
                f"[STRAY] NON 5.03 token={other.hex()} (not T) -> {GRP[0]}:{GRP[1]}",
                flush=True,
            )
    print("[DONE]", flush=True)


if __name__ == "__main__":
    main()
