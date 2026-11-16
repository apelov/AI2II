"""Run every bad_server.py variant against a client and tabulate what the client did.

Usage (from experiments/oscore-n1):
  python3 adversarial/run_matrix.py --client c     # ./coap/coap_client (build it first)
  python3 adversarial/run_matrix.py --client py    # py-client/mn_client.py

For each variant: start bad_server.py, start the client, wait, stop both, and count the
"[NOTIFICATION]" lines the client printed. A client that is correct per draft Section 5.2
accepts notifications only for the "good" control. Logs go to --logs/<client>-<variant>.log.
"""

import argparse
import importlib.util
import os
import signal
import subprocess
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "bad_server", os.path.join(here, "bad_server.py")
)
bad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bad)

ap = argparse.ArgumentParser()
ap.add_argument("--client", choices=["c", "py"], required=True)
ap.add_argument("--logs", required=True)
ap.add_argument("--variants", nargs="*", default=bad.VARIANTS)
args = ap.parse_args()
os.makedirs(args.logs, exist_ok=True)

root = os.path.dirname(here)
if args.client == "c":
    cmd, cwd = (
        ["./coap_client", "-h", "127.0.0.1", "-p", "5683", "-r", "mult"],
        os.path.join(root, "coap"),
    )
else:
    cmd, cwd = (
        [sys.executable, "mn_client.py", "--notifs", "3", "--timeout", "14"],
        os.path.join(root, "py-client"),
    )

rows = []
for v in args.variants:
    log_path = os.path.join(args.logs, f"{args.client}-{v}.log")
    with open(log_path, "w") as log:
        server = subprocess.Popen(
            [sys.executable, os.path.join(here, "bad_server.py"), "--variant", v],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(0.5)
        client = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        try:
            out, _ = client.communicate(timeout=14)
            stopped = False
        except subprocess.TimeoutExpired:
            client.send_signal(signal.SIGINT)
            try:
                out, _ = client.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                client.kill()
                out, _ = client.communicate()
            stopped = True
        server.kill()
        srv_out, _ = server.communicate()
        log.write("===== server\n" + srv_out + "\n===== client\n" + out)
    rc = client.returncode
    notifs = sum("[NOTIFICATION]" in line for line in out.splitlines())
    if rc is not None and rc < 0 and not stopped:
        status = f"CRASH (signal {-rc})"
    elif stopped:
        status = "still running (stopped by harness)"
    else:
        status = f"exited {rc}"
    rows.append((v, status, notifs))
    print(f"{v:16} {status:36} notifications accepted: {notifs}", flush=True)

bad_accept = [r for r in rows if r[0] != "good" and r[2] > 0]
good = [r for r in rows if r[0] == "good"]
print(f"\ncontrol 'good' accepted {good[0][2] if good else '?'} notification(s)")
print(
    f"malformed variants where notifications were accepted: {[r[0] for r in bad_accept] or 'none'}"
)
