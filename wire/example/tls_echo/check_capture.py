"""observes_capture checker: the capture holds a TLS session with the server on 127.0.0.1:N.

Usage: check_capture.py --port N <capture.pcap>. Exit 0 only if, in the byte streams to and from the
server, the client side opens with a ClientHello record, the server side with a ServerHello record,
and both sides then carry TLS application-data records. Cleartext TCP fails the record framing.
"""

import argparse
import sys

from tcp_pcap import segments

HANDSHAKE, APPLICATION = 22, 23


def records(stream: bytes) -> list[tuple[int, bytes]] | None:
    """Parse TLS records; None if the stream is not framed as TLS."""
    out, pos = [], 0
    while pos < len(stream):
        if (
            len(stream) - pos < 5
            or stream[pos] not in range(20, 25)
            or stream[pos + 1] != 3
        ):
            return None
        length = int.from_bytes(stream[pos + 3 : pos + 5], "big")
        out.append((stream[pos], stream[pos + 5 : pos + 5 + length]))
        pos += 5 + length
    return out


ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("pcap")
args = ap.parse_args()
try:
    segs = segments(args.pcap)
except (OSError, ValueError, KeyError) as e:
    print(f"unreadable capture: {e}")
    sys.exit(1)
host = "127.0.0.1"
to_server = b"".join(s.payload for s in segs if (s.dst, s.dport) == (host, args.port))
to_client = b"".join(s.payload for s in segs if (s.src, s.sport) == (host, args.port))
up, down = records(to_server), records(to_client)
if not up or not down:
    print("a direction of the exchange is missing or is not TLS-framed")
    sys.exit(1)
ok = (
    up[0][0] == HANDSHAKE
    and up[0][1][:1] == b"\x01"
    and down[0][0] == HANDSHAKE
    and down[0][1][:1] == b"\x02"
    and any(t == APPLICATION for t, _ in up)
    and any(t == APPLICATION for t, _ in down)
)
if not ok:
    print("no ClientHello/ServerHello followed by application data in both directions")
    sys.exit(1)
print("TLS handshake and application data observed in both directions")
