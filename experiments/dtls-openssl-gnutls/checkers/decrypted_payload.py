#!/usr/bin/env python3
"""decrypted_payload.py: Independent evidence checker for decrypted DTLS captures (DESIGN.md 24.21).

Usage: python3 checkers/decrypted_payload.py <decrypted.pcapng> <payload.bin>

Exits 0 only if:
- DTLS handshake completed (both client and server Finished messages successfully decrypted)
- Decrypted application data contains the payload in BOTH directions (request and echo)
Outputs PASS/FAIL lines with the relevant RFC 6347 / 5246 sections.
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


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: decrypted_payload.py <decrypted.pcapng> <payload.bin>",
            file=sys.stderr,
        )
        return 2

    pcapng_path = Path(sys.argv[1])
    payload_path = Path(sys.argv[2])

    if not pcapng_path.is_file():
        print(f"FAIL: RFC 6347 Section 4.1 - Decrypted pcapng file not found: {pcapng_path}")
        return 1

    if not payload_path.is_file():
        print(f"FAIL: Payload vector file not found: {payload_path}")
        return 1

    try:
        payload_bytes = payload_path.read_bytes()
    except OSError as e:
        print(f"FAIL: Cannot read payload vector file: {e}")
        return 1

    if not payload_bytes:
        print("FAIL: Payload vector file is empty")
        return 1

    payload_hex = payload_bytes.hex().lower()
    payload_strip_hex = payload_bytes.strip().hex().lower()

    tshark = find_tshark()
    cmd = [
        tshark,
        "-r",
        str(pcapng_path),
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
        "dtls.handshake.type",
        "-e",
        "dtls.app_data",
        "-e",
        "data.data",
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"FAIL: RFC 6347 Section 4.1 - Failed to run tshark: {e}")
        return 1

    if proc.returncode != 0:
        print(f"FAIL: RFC 6347 Section 4.1 - tshark failed on decrypted capture: {proc.stderr.strip()}")
        return 1

    raw_lines = [l.split("\t") for l in proc.stdout.splitlines() if l.strip()]
    if not raw_lines:
        print("FAIL: RFC 6347 Section 4.1 - No UDP packets found in decrypted capture")
        return 1

    # Identify client and server endpoints from handshake
    client_endpoint = None
    server_endpoint = None
    for parts in raw_lines:
        if len(parts) < 8:
            continue
        src_ip = parts[1] or parts[3]
        dst_ip = parts[2] or parts[4]
        sport = parts[5]
        dport = parts[6]
        htypes = [x.strip() for x in parts[7].split(",") if x.strip()]
        if "1" in htypes and client_endpoint is None:
            client_endpoint = (src_ip, sport)
            server_endpoint = (dst_ip, dport)
            break

    client_finished_decrypted = False
    server_finished_decrypted = False
    saw_request_payload = False
    saw_echo_payload = False

    for parts in raw_lines:
        if len(parts) < 8:
            continue
        src_ip = parts[1] or parts[3]
        dst_ip = parts[2] or parts[4]
        sport = parts[5]
        dport = parts[6]
        src_ep = (src_ip, sport)
        dst_ep = (dst_ip, dport)

        htypes = [x.strip() for x in parts[7].split(",") if x.strip()]
        app_data = parts[8] if len(parts) > 8 else ""
        data_hex = (
            parts[9].replace(":", "").replace(" ", "").lower()
            if len(parts) > 9
            else ""
        )

        # Finished handshake message type 20
        if "20" in htypes:
            if client_endpoint and src_ep == client_endpoint:
                client_finished_decrypted = True
            elif server_endpoint and src_ep == server_endpoint:
                server_finished_decrypted = True

        # Decrypted application data check
        if app_data and data_hex:
            has_payload = (payload_hex in data_hex) or (
                payload_strip_hex and payload_strip_hex in data_hex
            )
            if has_payload:
                if client_endpoint and src_ep == client_endpoint and dst_ep == server_endpoint:
                    saw_request_payload = True
                elif server_endpoint and src_ep == server_endpoint and dst_ep == client_endpoint:
                    saw_echo_payload = True
                elif client_endpoint is None:
                    # Fallback if endpoints could not be disambiguated by ClientHello
                    saw_request_payload = True

    checks_passed = True

    # Check 1: Handshake completion (Finished messages decrypted)
    if client_finished_decrypted and server_finished_decrypted:
        print(
            "PASS: RFC 6347 Section 4.2.6 / RFC 5246 Section 7.4.9 - "
            "DTLS handshake completed (both client and server Finished decrypted)"
        )
    else:
        missing_fin = []
        if not client_finished_decrypted:
            missing_fin.append("client Finished")
        if not server_finished_decrypted:
            missing_fin.append("server Finished")
        print(
            f"FAIL: RFC 6347 Section 4.2.6 / RFC 5246 Section 7.4.9 - "
            f"DTLS handshake not completed ({', '.join(missing_fin)} not decrypted)"
        )
        checks_passed = False

    # Check 2: Request payload
    if saw_request_payload:
        print(
            "PASS: RFC 6347 Section 4.1 / RFC 5246 Section 10 - "
            "Expected payload decrypted in application data (request: client -> server)"
        )
    else:
        print(
            "FAIL: RFC 6347 Section 4.1 / RFC 5246 Section 10 - "
            "Expected payload not found in decrypted application data (request: client -> server)"
        )
        checks_passed = False

    # Check 3: Echo payload
    if saw_echo_payload:
        print(
            "PASS: RFC 6347 Section 4.1 / RFC 5246 Section 10 - "
            "Expected payload decrypted in application data (echo: server -> client)"
        )
    else:
        print(
            "FAIL: RFC 6347 Section 4.1 / RFC 5246 Section 10 - "
            "Expected payload not found in decrypted application data (echo: server -> client)"
        )
        checks_passed = False

    return 0 if checks_passed else 1


if __name__ == "__main__":
    sys.exit(main())
