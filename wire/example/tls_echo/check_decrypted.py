"""observes_decrypted checker: tshark shows the vector as decrypted application data inside TLS, both ways.

Usage: check_decrypted.py --port N <decrypted.pcapng> <vector>. Reads {decrypted} through tshark with
no extra options, so it depends on the secrets embedded in that file.
"""

import argparse
import subprocess
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("decrypted")
ap.add_argument("vector")
args = ap.parse_args()
vector = Path(args.vector).read_bytes().hex()
try:
    r = subprocess.run(
        ["tshark", "-r", args.decrypted, "-Y", "tls.app_data and data.data", "-T", "fields",
         "-e", "tcp.srcport", "-e", "tcp.dstport", "-e", "data.data"],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
except (OSError, subprocess.SubprocessError) as e:
    print(f"cannot run tshark: {e}")
    sys.exit(1)
if r.returncode != 0:
    print(f"tshark failed: {r.stderr.strip()}")
    sys.exit(1)
seen = set()
for line in r.stdout.splitlines():
    cols = line.split("\t")
    if len(cols) == 3 and vector in cols[2].replace(":", "").lower():
        sport, dport = int(cols[0]), int(cols[1])
        if dport == args.port:
            seen.add("to-server")
        if sport == args.port:
            seen.add("to-client")
if seen != {"to-server", "to-client"}:
    print(f"vector not decrypted in both directions (saw: {sorted(seen)})")
    sys.exit(1)
print("vector observed in decrypted TLS application data, both directions")
