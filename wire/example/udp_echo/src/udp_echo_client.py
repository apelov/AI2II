"""UDP echo client: exit 0 only if the exact payload it sent comes back from the server."""

import argparse
import socket
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--payload-file", required=True)
ap.add_argument("--timeout", type=float, default=3.0)
args = ap.parse_args()
payload = Path(args.payload_file).read_bytes()
server = ("127.0.0.1", args.port)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(args.timeout)
sock.sendto(payload, server)
try:
    data, peer = sock.recvfrom(65535)
except TimeoutError:
    print("no echo received", file=sys.stderr)
    sys.exit(1)
if peer != server or data != payload:
    print(f"unexpected reply from {peer}: {data!r}", file=sys.stderr)
    sys.exit(1)
print("echo ok")
