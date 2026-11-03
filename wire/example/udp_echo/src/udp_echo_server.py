"""UDP echo server: send every datagram back to its sender."""

import argparse
import socket

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
args = ap.parse_args()
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", args.port))
print(f"listening on 127.0.0.1:{args.port}", flush=True)
while True:
    data, peer = sock.recvfrom(65535)
    sock.sendto(data, peer)
