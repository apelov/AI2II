"""observes_capture checker: the captured bytes hold the request and its echo.

Usage: check_capture.py --port N <capture.pcap>. Exit 0 only if the capture contains a datagram to
127.0.0.1:N and, in the opposite direction, a datagram from 127.0.0.1:N with the same payload.
"""

import argparse
import sys

from udp_pcap import datagrams

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("pcap")
args = ap.parse_args()
try:
    pkts = datagrams(args.pcap)
except (OSError, ValueError, KeyError) as e:
    print(f"unreadable capture: {e}")
    sys.exit(1)
host = "127.0.0.1"
for req in pkts:
    if (req.dst, req.dport) != (host, args.port) or not req.payload:
        continue
    for rep in pkts:
        if (
            (rep.src, rep.sport) == (host, args.port)
            and (rep.dst, rep.dport) == (req.src, req.sport)
            and rep.payload == req.payload
        ):
            print(f"request and echo of {len(req.payload)} bytes observed")
            sys.exit(0)
print("no request with a matching echo in the capture")
sys.exit(1)
