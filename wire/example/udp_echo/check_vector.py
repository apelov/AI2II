"""vector checker: the test vector is the payload of a request to the server in the capture.

Usage: check_vector.py --port N <capture.pcap> <vector>.
"""

import argparse
import sys
from pathlib import Path

from udp_pcap import datagrams

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("pcap")
ap.add_argument("vector")
args = ap.parse_args()
vector = Path(args.vector).read_bytes()
try:
    pkts = datagrams(args.pcap)
except (OSError, ValueError, KeyError) as e:
    print(f"unreadable capture: {e}")
    sys.exit(1)
if any(p.dport == args.port and p.payload == vector for p in pkts):
    print("vector observed in capture")
    sys.exit(0)
print("vector not observed in capture")
sys.exit(1)
