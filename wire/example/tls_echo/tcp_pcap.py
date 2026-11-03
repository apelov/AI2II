"""Minimal stdlib reader for TCP/IPv4 payloads in a classic pcap file (example checkers only)."""

import struct
from pathlib import Path
from typing import NamedTuple

LINK_HEADER = {
    0: 4,
    1: 14,
    101: 0,
    108: 4,
}  # NULL/loopback, Ethernet, raw IP, OpenBSD loopback


class Segment(NamedTuple):
    src: str
    sport: int
    dst: str
    dport: int
    payload: bytes


def segments(path: str) -> list[Segment]:
    data = Path(path).read_bytes()
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        end = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        end = ">"
    else:
        raise ValueError("not a pcap file")
    skip = LINK_HEADER[struct.unpack(end + "I", data[20:24])[0]]
    out = []
    pos = 24
    while pos + 16 <= len(data):
        incl = struct.unpack(end + "I", data[pos + 8 : pos + 12])[0]
        pkt = data[pos + 16 : pos + 16 + incl]
        pos += 16 + incl
        ip = pkt[skip:]
        if len(ip) < 40 or ip[0] >> 4 != 4 or ip[9] != 6:
            continue
        ihl = (ip[0] & 15) * 4
        sport, dport = struct.unpack("!HH", ip[ihl : ihl + 4])
        thl = (ip[ihl + 12] >> 4) * 4
        total = struct.unpack("!H", ip[2:4])[0]
        payload = ip[ihl + thl : total]
        src = ".".join(str(b) for b in ip[12:16])
        dst = ".".join(str(b) for b in ip[16:20])
        out.append(Segment(src, sport, dst, dport, payload))
    return out
