"""Env check: coap/ must be a checkout of the public implementation at the pinned commit.

Pinned: https://github.com/apelov/coap-multicast-notifications commit 9b7d288 (nosec sources
identical to the development commit 288cd27 used earlier; see README.md).
"""

import subprocess
import sys

PIN = "9b7d288"
head = subprocess.run(
    ["git", "-C", "coap", "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True, check=False
).stdout.strip()
print(f"coap/ at {head or '?'}, pinned {PIN}")
sys.exit(0 if head == PIN else 1)
