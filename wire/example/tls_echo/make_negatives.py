"""Write the synthetic capture negatives (stdlib; DLT_NULL pcap files). Committed; rerun only if the port changes.

Usage: make_negatives.py --port N --out DIR. Writes unrelated.pcap, one_direction.pcap, cleartext.pcap.

The two decrypted-view negatives come from real runs and are committed as they are:
  other_payload.pcapng  capture-decrypted.pcapng of a run whose client sent vectors/other_payload.bin
  client.keys.altered   secrets/client.keys of a run with the first hex digit of every secret changed
"""

import argparse
import struct
from pathlib import Path


def segment(sport: int, dport: int, payload: bytes) -> bytes:
    tcp = (
        struct.pack("!HHIIBBHHH", sport, dport, 1, 1, 5 << 4, 0x18, 65535, 0, 0)
        + payload
    )
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(tcp),
        0,
        0,
        64,
        6,
        0,
        bytes([127, 0, 0, 1]),
        bytes([127, 0, 0, 1]),
    )
    return struct.pack("<I", 2) + ip + tcp


def record(kind: int, body: bytes) -> bytes:
    return bytes([kind, 3, 3]) + struct.pack("!H", len(body)) + body


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
c, s = 40001, args.port
hello_c, hello_s = record(22, b"\x01" + bytes(40)), record(22, b"\x02" + bytes(40))
app_c, app_s = record(23, bytes(range(30))), record(23, bytes(range(30, 60)))
tls = [
    segment(c, s, hello_c),
    segment(s, c, hello_s),
    segment(c, s, app_c),
    segment(s, c, app_s),
]
(out / "unrelated.pcap").write_bytes(
    pcap([segment(40002, 40003, b"unrelated"), segment(40003, 40002, b"unrelated")])
)
(out / "one_direction.pcap").write_bytes(pcap([tls[0], tls[2]]))
payload = b"tls-example-payload-7f3a9c1e5b"
(out / "cleartext.pcap").write_bytes(
    pcap([segment(c, s, payload), segment(s, c, payload)])
)
