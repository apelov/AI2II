"""Env check: the CoAP multicast group 224.0.1.187 must route via lo0, so one lo0 capture sees all traffic.

Fix (human, needs sudo): sudo route add -host 224.0.1.187 -interface lo0
"""

import subprocess
import sys

out = subprocess.run(
    ["route", "-n", "get", "224.0.1.187"], capture_output=True, text=True, check=False
).stdout
iface = next((ln.split(":", 1)[1].strip() for ln in out.splitlines() if "interface:" in ln), "")
print(f"224.0.1.187 routes via {iface or '?'}")
sys.exit(0 if iface == "lo0" else 1)
