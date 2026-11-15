"""Adversarial client: register, then never ACK the CON 5.03 informative response.

Draft Section 4.2 requires the informative response to be a Confirmable separate response;
RFC 7252 Section 4.2 then requires the server to retransmit it (same Message ID) with
exponential back-off until it is acknowledged, up to MAX_RETRANSMIT (4) times.

Prints every 5.03 copy with its arrival time. Exit 0 only if at least --min-retx
retransmissions with the same Message ID arrive within --wait seconds; exit 1 otherwise.
Standard library only.
"""

import argparse
import itertools
import os
import random
import socket
import struct
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=5683)
ap.add_argument("--resource", default="mult")
ap.add_argument("--wait", type=float, default=50.0)
ap.add_argument("--min-retx", type=int, default=1)
args = ap.parse_args()


def log(msg):
    print(msg, flush=True)


token, mid = os.urandom(8), random.randrange(0x10000)
path = args.resource.encode()
# CON GET, Observe(6)=0 (empty), Uri-Path(11)=resource: deltas 6 then 5
req = bytes([0x40 | len(token), 0x01]) + struct.pack("!H", mid) + token
req += bytes([0x60]) + bytes([0x50 | len(path)]) + path

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", 0))
s.sendto(req, (args.host, args.port))
t0 = time.monotonic()
log(f"[REGISTER] token={token.hex()} mid={mid}; will never ACK the 5.03")

copies = []  # (time, mid)
while time.monotonic() - t0 < args.wait:
    s.settimeout(max(0.1, args.wait - (time.monotonic() - t0)))
    try:
        raw, src = s.recvfrom(2048)
    except TimeoutError:
        break
    if len(raw) < 4:
        continue
    mtype, code, rmid = (raw[0] >> 4) & 3, raw[1], struct.unpack("!H", raw[2:4])[0]
    tkl = raw[0] & 0x0F
    t = time.monotonic() - t0
    if mtype == 2 and code == 0:
        log(f"[{t:6.2f}s] empty ACK mid={rmid} (registration acknowledged)")
        continue
    if code == 0xA3 and raw[4 : 4 + tkl] == token:
        copies.append((t, rmid))
        kind = "first" if len(copies) == 1 else f"copy {len(copies)}"
        log(f"[{t:6.2f}s] CON 5.03 mid={rmid} ({kind}); not ACKing")
    else:
        log(
            f"[{t:6.2f}s] other datagram type={mtype} code={code >> 5}.{code & 31:02d} mid={rmid}"
        )

if not copies:
    log("[RESULT] no 5.03 received at all")
    sys.exit(1)
first_mid = copies[0][1]
retx = [c for c in copies[1:] if c[1] == first_mid]
other = [c for c in copies[1:] if c[1] != first_mid]
gaps = [round(b[0] - a[0], 2) for a, b in itertools.pairwise(copies)]
log(
    f"[RESULT] 5.03 copies={len(copies)} retransmissions(same mid)={len(retx)} other-mid={len(other)} gaps_s={gaps}"
)
sys.exit(0 if len(retx) >= args.min_retx else 1)
