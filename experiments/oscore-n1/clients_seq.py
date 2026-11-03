"""Client-side peer for nosec cell N1: run N C clients one after another.

Mirrors ~/Code/CoAP/run_secure_cell.sh: only one nosec C client can hold the multicast
port 56830, so each client runs until it has printed NOTIFS "[NOTIFICATION]" lines
(or a deadline), then is stopped with SIGINT and reaped before the next starts.
Exit 0 only if every client received NOTIFS notifications. Run with cwd = the CoAP repo.
"""

import argparse
import signal
import subprocess
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--clients", type=int, default=3)
ap.add_argument("--notifs", type=int, default=3)
ap.add_argument("--host", default="127.0.0.1")
args = ap.parse_args()

wait_s = 20 + args.notifs * 10 + 15
ok = True
for k in range(1, args.clients + 1):
    print(f"[driver] client{k}: start", flush=True)
    p = subprocess.Popen(
        ["./coap_client", "-h", args.host, "-p", "5683", "-r", "mult"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    seen, deadline = 0, time.monotonic() + wait_s
    assert p.stdout is not None
    for line in p.stdout:
        sys.stdout.write(f"[client{k}] {line}")
        if "[NOTIFICATION]" in line:
            seen += 1
        if seen >= args.notifs or time.monotonic() >= deadline:
            break
    p.send_signal(signal.SIGINT)
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    print(f"[driver] client{k}: {seen}/{args.notifs} notifications", flush=True)
    ok = ok and seen >= args.notifs
sys.exit(0 if ok else 1)
