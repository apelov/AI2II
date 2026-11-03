"""Server adapter: OpenSSL s_server over DTLS 1.2, echoing each received line back.

s_server prints application data it receives on stdout and sends its stdin to the peer
(-rev is TLS-only), so this adapter feeds received lines back. Prints READY once accepting.
"""

import argparse
import subprocess
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--bin", required=True)
ap.add_argument("--port", type=int, required=True)
a = ap.parse_args()
p = subprocess.Popen(
    [a.bin, "s_server", "-dtls1_2", "-accept", str(a.port), "-cert", "certs/cert.pem",
     "-key", "certs/key.pem", "-quiet"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
)
print("READY", flush=True)
for line in p.stdout:
    sys.stdout.write(line.decode(errors="replace"))
    sys.stdout.flush()
    if line.strip():
        p.stdin.write(line)
        p.stdin.flush()
