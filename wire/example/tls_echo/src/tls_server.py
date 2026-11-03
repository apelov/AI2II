"""TLS echo server on loopback: echo every connection's bytes back. Test certificate only."""

import argparse
import os
import socket
import ssl
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
args = ap.parse_args()
here = Path(__file__).resolve().parent
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(here / "test_cert.pem", here / "test_key.pem")
if os.environ.get("SSLKEYLOGFILE"):
    ctx.keylog_filename = os.environ["SSLKEYLOGFILE"]
listener = socket.create_server(("127.0.0.1", args.port))
print(f"listening on 127.0.0.1:{args.port}", flush=True)
while True:
    conn, _ = listener.accept()
    try:
        with ctx.wrap_socket(conn, server_side=True) as tls:
            while data := tls.recv(65535):
                tls.sendall(data)
    except (ssl.SSLError, OSError) as e:
        print(f"connection error: {e}", flush=True)
