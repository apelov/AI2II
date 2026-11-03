"""TLS echo client: exit 0 only if the exact payload it sent over TLS comes back."""

import argparse
import socket
import ssl
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--payload-file", required=True)
args = ap.parse_args()
payload = Path(args.payload_file).read_bytes()
# create_default_context honours SSLKEYLOGFILE from the environment.
ctx = ssl.create_default_context(
    cafile=Path(__file__).resolve().parent / "test_cert.pem"
)
try:
    with (
        socket.create_connection(("127.0.0.1", args.port), timeout=5) as raw,
        ctx.wrap_socket(raw, server_hostname="localhost") as tls,
    ):
        tls.sendall(payload)
        data = b""
        while len(data) < len(payload):
            chunk = tls.recv(65535)
            if not chunk:
                break
            data += chunk
except (OSError, ssl.SSLError) as e:
    print(f"tls echo failed: {e}", file=sys.stderr)
    sys.exit(1)
if data != payload:
    print(f"unexpected echo: {data!r}", file=sys.stderr)
    sys.exit(1)
print("tls echo ok")
