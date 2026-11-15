"""Client-side peer for cell N1-py: run N Python clients (mn_client.py) one after another.

Same shape as ../clients_seq.py for the C clients, so the existing N1 checker applies:
each client registers, receives --notifs notifications and exits by itself.
Exit 0 only if every client exited 0.
"""

import argparse
import os
import subprocess
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--clients", type=int, default=3)
ap.add_argument("--notifs", type=int, default=3)
ap.add_argument("--host", default="127.0.0.1")
args = ap.parse_args()

client = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mn_client.py")
timeout = 20 + args.notifs * 10 + 15
ok = True
for k in range(1, args.clients + 1):
    print(f"[driver] client{k}: start", flush=True)
    p = subprocess.Popen(
        [
            sys.executable,
            client,
            "--host",
            args.host,
            "--notifs",
            str(args.notifs),
            "--timeout",
            str(timeout),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert p.stdout is not None
    for line in p.stdout:
        sys.stdout.write(f"[client{k}] {line}")
    rc = p.wait()
    print(f"[driver] client{k}: exit {rc}", flush=True)
    ok = ok and rc == 0
sys.exit(0 if ok else 1)
