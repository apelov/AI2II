"""Write the capture negatives for the observes_capture checker (stdlib; DLT_NULL pcap files).

Usage: make_negatives.py --port N --out DIR. The negatives are committed; rerun only if the port changes.
"""

import argparse
import struct
from pathlib import Path


def packet(sport: int, dport: int, payload: bytes) -> bytes:
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(udp),
        0,
        0,
        64,
        17,
        0,
        bytes([127, 0, 0, 1]),
        bytes([127, 0, 0, 1]),
    )
    return struct.pack("<I", 2) + ip + udp


def pcap(packets: list[bytes]) -> bytes:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 0)
    for n, p in enumerate(packets):
        out += struct.pack("<IIII", 1, n, len(p), len(p)) + p
    return out


ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--out", required=True)
args = ap.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
payload = b"example-vector-payload"
(out / "unrelated.pcap").write_bytes(
    pcap([packet(40001, 40002, b"unrelated"), packet(40002, 40001, b"unrelated")])
)
(out / "no_echo.pcap").write_bytes(pcap([packet(40003, args.port, payload)]))
