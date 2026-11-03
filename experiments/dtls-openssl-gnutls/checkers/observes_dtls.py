#!/usr/bin/env python3
"""observes_dtls.py: Independent evidence checker for DTLS 1.2 wire captures (RFC 6347 / RFC 5246).

Usage: python3 checkers/observes_dtls.py <capture>

Exits 0 only if the raw capture shows a complete DTLS 1.2 exchange between two loopback endpoints:
- Handshake in both directions (ClientHello, ServerHello, ChangeCipherSpec / Finished as required by RFC)
- Encrypted application data records in both directions (client -> server and server -> client)
- Payload bytes do NOT appear in clear in any UDP payload
Port-agnostic (usable for all cells).
Outputs one PASS/FAIL line per check with the relevant RFC 6347 / 5246 sections.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_tshark() -> str:
    candidates = [
        shutil.which("tshark"),
        "/Applications/Wireshark.app/Contents/MacOS/tshark",
        "/usr/local/bin/tshark",
        "/opt/homebrew/bin/tshark",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return "tshark"


def is_loopback(ip: str) -> bool:
    if not ip:
        return False
    ip = ip.strip()
    if ip.startswith("127."):
        return True
    if ip in ("::1", "0:0:0:0:0:0:0:1"):
        return True
    if ip.startswith("::ffff:127."):
        return True
    return False


def load_target_payloads() -> list[bytes]:
    payloads = [b"AI2II-DTLS-PAYLOAD"]
    search_paths = [
        Path(__file__).resolve().parent.parent / "vectors" / "payload.bin",
        Path("vectors/payload.bin"),
    ]
    for p in search_paths:
        if p.is_file():
            try:
                b = p.read_bytes()
                if b and b not in payloads:
                    payloads.append(b)
                b_strip = b.strip()
                if b_strip and b_strip not in payloads:
                    payloads.append(b_strip)
            except OSError:
                pass
    return payloads


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: observes_dtls.py <capture>", file=sys.stderr)
        return 2

    capture_path = Path(sys.argv[1])
    if not capture_path.is_file():
        print(f"FAIL: RFC 6347 Section 4.1.1 - Capture file not found: {capture_path}")
        return 1

    tshark = find_tshark()
    cmd = [
        tshark,
        "-r",
        str(capture_path),
        "-T",
        "fields",
        "-e",
        "frame.number",
        "-e",
        "ip.src",
        "-e",
        "ip.dst",
        "-e",
        "ipv6.src",
        "-e",
        "ipv6.dst",
        "-e",
        "udp.srcport",
        "-e",
        "udp.dstport",
        "-e",
        "dtls.record.content_type",
        "-e",
        "dtls.record.version",
        "-e",
        "dtls.record.epoch",
        "-e",
        "dtls.handshake.type",
        "-e",
        "dtls.handshake.version",
        "-e",
        "udp.payload",
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"FAIL: RFC 6347 Section 4.1.1 - Failed to run tshark: {e}")
        return 1

    if proc.returncode != 0:
        print(f"FAIL: RFC 6347 Section 4.1.1 - tshark dissection failed on capture: {proc.stderr.strip()}")
        return 1

    raw_lines = [l.split("\t") for l in proc.stdout.splitlines() if l.strip()]
    if not raw_lines:
        print("FAIL: RFC 6347 Section 4.1.1 - No UDP packets found in capture")
        return 1

    # Endpoints identification: find client endpoint (sends ClientHello: handshake type 1) and server endpoint
    client_endpoint = None
    server_endpoint = None
    for parts in raw_lines:
        if len(parts) < 8:
            continue
        src_ip = parts[1] or parts[3]
        dst_ip = parts[2] or parts[4]
        sport = parts[5]
        dport = parts[6]
        htypes = [x.strip() for x in parts[10].split(",") if x.strip()]
        if "1" in htypes and client_endpoint is None:
            client_endpoint = (src_ip, sport)
            server_endpoint = (dst_ip, dport)
            break

    # State tracking for checks
    client_hello_seen = False
    server_hello_dtls12_seen = False
    client_ccs_seen = False
    client_finished_seen = False
    server_ccs_seen = False
    server_finished_seen = False
    client_appdata_seen = False
    server_appdata_seen = False
    cleartext_leak_detected = False

    payload_targets = load_target_payloads()

    for parts in raw_lines:
        if len(parts) < 8:
            continue
        src_ip = parts[1] or parts[3]
        dst_ip = parts[2] or parts[4]
        sport = parts[5]
        dport = parts[6]
        src_ep = (src_ip, sport)
        dst_ep = (dst_ip, dport)

        ctypes = [int(x) for x in parts[7].split(",") if x.isdigit()]
        epochs = [int(x) for x in parts[9].split(",") if x.isdigit()]
        htypes = [int(x) for x in parts[10].split(",") if x.isdigit()]
        hvers = [x.lower() for x in parts[11].split(",") if x]
        raw_udp_hex = parts[12] if len(parts) > 12 else ""

        # Check for cleartext payload leakage in any UDP payload
        if raw_udp_hex:
            try:
                udp_bytes = bytes.fromhex(raw_udp_hex)
                for target in payload_targets:
                    if target in udp_bytes:
                        cleartext_leak_detected = True
                        break
            except ValueError:
                pass

        if client_endpoint and src_ep == client_endpoint and dst_ep == server_endpoint:
            if 1 in htypes:
                client_hello_seen = True
            if 20 in ctypes:
                client_ccs_seen = True
            for c, ep in zip(ctypes, epochs):
                if c == 22 and ep >= 1:
                    client_finished_seen = True
                if c == 23 and ep >= 1:
                    client_appdata_seen = True

        if server_endpoint and src_ep == server_endpoint and dst_ep == client_endpoint:
            if 2 in htypes and any(v in ("0xfefd", "0xfe,0xfd") for v in hvers):
                server_hello_dtls12_seen = True
            if 20 in ctypes:
                server_ccs_seen = True
            for c, ep in zip(ctypes, epochs):
                if c == 22 and ep >= 1:
                    server_finished_seen = True
                if c == 23 and ep >= 1:
                    server_appdata_seen = True

    checks_passed = True

    # Check 1: Loopback endpoints
    if (
        client_endpoint is not None
        and server_endpoint is not None
        and is_loopback(client_endpoint[0])
        and is_loopback(server_endpoint[0])
    ):
        print(
            f"PASS: RFC 6347 Section 4.1.1 - DTLS exchange between loopback endpoints "
            f"({client_endpoint[0]}:{client_endpoint[1]} <-> {server_endpoint[0]}:{server_endpoint[1]})"
        )
    else:
        print("FAIL: RFC 6347 Section 4.1.1 - No DTLS exchange between two loopback endpoints observed")
        checks_passed = False

    # Check 2: ClientHello
    if client_hello_seen:
        print("PASS: RFC 6347 Section 4.2.1 / RFC 5246 Section 7.4.1.2 - ClientHello observed (client -> server)")
    else:
        print("FAIL: RFC 6347 Section 4.2.1 / RFC 5246 Section 7.4.1.2 - ClientHello handshake message not observed")
        checks_passed = False

    # Check 3: ServerHello negotiating DTLS 1.2
    if server_hello_dtls12_seen:
        print("PASS: RFC 6347 Section 4.2.1 / RFC 5246 Section 7.4.1.3 - ServerHello negotiating DTLS 1.2 ({254, 253}) observed (server -> client)")
    else:
        print("FAIL: RFC 6347 Section 4.2.1 / RFC 5246 Section 7.4.1.3 - ServerHello negotiating DTLS 1.2 ({254, 253}) not observed")
        checks_passed = False

    # Check 4: Client ChangeCipherSpec and Finished
    if client_ccs_seen and client_finished_seen:
        print("PASS: RFC 6347 Sections 4.1, 4.2.5, 4.2.6 / RFC 5246 Sections 7.1, 7.4.9 - Client ChangeCipherSpec and Finished observed (client -> server)")
    else:
        missing = []
        if not client_ccs_seen:
            missing.append("ChangeCipherSpec")
        if not client_finished_seen:
            missing.append("Finished")
        print(f"FAIL: RFC 6347 Sections 4.1, 4.2.5, 4.2.6 / RFC 5246 Sections 7.1, 7.4.9 - Client {' and '.join(missing)} not observed")
        checks_passed = False

    # Check 5: Server ChangeCipherSpec and Finished
    if server_ccs_seen and server_finished_seen:
        print("PASS: RFC 6347 Sections 4.1, 4.2.5, 4.2.6 / RFC 5246 Sections 7.1, 7.4.9 - Server ChangeCipherSpec and Finished observed (server -> client)")
    else:
        missing = []
        if not server_ccs_seen:
            missing.append("ChangeCipherSpec")
        if not server_finished_seen:
            missing.append("Finished")
        print(f"FAIL: RFC 6347 Sections 4.1, 4.2.5, 4.2.6 / RFC 5246 Sections 7.1, 7.4.9 - Server {' and '.join(missing)} not observed")
        checks_passed = False

    # Check 6: Encrypted Application Data in both directions
    if client_appdata_seen and server_appdata_seen:
        print("PASS: RFC 6347 Section 4.1 / RFC 5246 Section 10 - Encrypted application data observed in both directions")
    else:
        missing_dirs = []
        if not client_appdata_seen:
            missing_dirs.append("client -> server")
        if not server_appdata_seen:
            missing_dirs.append("server -> client")
        print(f"FAIL: RFC 6347 Section 4.1 / RFC 5246 Section 10 - Encrypted application data missing in: {', '.join(missing_dirs)}")
        checks_passed = False

    # Check 7: Record payload protection (no cleartext payload in UDP)
    if not cleartext_leak_detected:
        print("PASS: RFC 6347 Section 4.1.2 / RFC 5246 Section 6.2.3 - Record payload protection: payload bytes not observed in clear")
    else:
        print("FAIL: RFC 6347 Section 4.1.2 / RFC 5246 Section 6.2.3 - Cleartext payload bytes observed in UDP payload")
        checks_passed = False

    return 0 if checks_passed else 1


if __name__ == "__main__":
    sys.exit(main())
