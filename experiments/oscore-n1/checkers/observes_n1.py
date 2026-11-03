#!/usr/bin/env python3
"""observes_n1 checker: verifies CoAP Observe multicast notifications for cell N1.

Specification: draft-ietf-core-observe-multicast-notifications-15
Cell N1 profile: nosec, server at 127.0.0.1:5683 with resource /mult,
3 sequential clients, group notifications to 224.0.1.187:56830 with >= 3 notifs per client.

Author family: google
Model: gemini-3.8-flash-high

Usage:
    python3 checkers/observes_n1.py <capture.pcap>
"""

import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple, Optional

# Supported link types in classic pcap
LINK_HEADER = {
    0: 4,     # DLT_NULL / loopback (BSD/macOS AF_INET = 2)
    1: 14,    # DLT_EN10MB (Ethernet)
    12: 0,    # DLT_RAW (Raw IP)
    101: 0,   # DLT_RAW (Raw IP)
    108: 4,   # OpenBSD loopback
    113: 16,  # DLT_LINUX_SLL
    276: 20,  # DLT_LINUX_SLL2
}


class Datagram(NamedTuple):
    src: str
    sport: int
    dst: str
    dport: int
    payload: bytes


def read_pcap_classic(path: Path) -> list[Datagram]:
    """Parse UDP IPv4 datagrams from classic pcap using pure Python stdlib."""
    data = path.read_bytes()
    if len(data) < 24:
        raise ValueError("File too short to be a valid pcap")
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        end = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        end = ">"
    else:
        raise ValueError("Invalid pcap magic header")

    linktype = struct.unpack(end + "I", data[20:24])[0]
    if linktype not in LINK_HEADER:
        raise ValueError(f"Unsupported pcap link-layer header type: {linktype}")

    skip = LINK_HEADER[linktype]
    out = []
    pos = 24
    while pos + 16 <= len(data):
        incl = struct.unpack(end + "I", data[pos + 8 : pos + 12])[0]
        pkt = data[pos + 16 : pos + 16 + incl]
        pos += 16 + incl
        if len(pkt) <= skip:
            continue
        ip = pkt[skip:]
        if len(ip) < 20:
            continue
        ip_ver = ip[0] >> 4
        if ip_ver != 4:
            continue
        ihl = (ip[0] & 0x0F) * 4
        proto = ip[9]
        if proto != 17:  # UDP
            continue
        if len(ip) < ihl + 8:
            continue
        sport, dport, length = struct.unpack("!HHH", ip[ihl : ihl + 6])
        if len(ip) < ihl + length:
            continue
        payload = ip[ihl + 8 : ihl + length]
        src = ".".join(str(b) for b in ip[12:16])
        dst = ".".join(str(b) for b in ip[16:20])
        out.append(Datagram(src, sport, dst, dport, payload))
    return out


def read_pcap_tshark(path: Path) -> list[Datagram]:
    """Fallback reader using tshark human-written dissectors."""
    tshark_bin = shutil.which("tshark") or "/Applications/Wireshark.app/Contents/MacOS/tshark"
    cmd = [
        tshark_bin,
        "-r",
        str(path),
        "-T",
        "fields",
        "-e",
        "ip.src",
        "-e",
        "udp.srcport",
        "-e",
        "ip.dst",
        "-e",
        "udp.dstport",
        "-e",
        "udp.payload",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"tshark error (exit {proc.returncode}): {proc.stderr.strip()}")
    out = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 5 or not parts[4]:
            continue
        src = parts[0]
        sport = int(parts[1])
        dst = parts[2]
        dport = int(parts[3])
        payload = bytes.fromhex(parts[4])
        out.append(Datagram(src, sport, dst, dport, payload))
    return out


def read_datagrams(path_str: str) -> list[Datagram]:
    """Read UDP datagrams from pcap with classic pcap parser and tshark fallback."""
    p = Path(path_str)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {path_str}")
    try:
        return read_pcap_classic(p)
    except Exception:
        return read_pcap_tshark(p)


def parse_coap(data: bytes) -> Optional[dict[str, Any]]:
    """Parse a CoAP packet according to RFC 7252 Section 3."""
    if len(data) < 4:
        return None
    ver = (data[0] >> 6) & 0x03
    if ver != 1:  # CoAP version 1 (RFC 7252 Section 3)
        return None
    mtype = (data[0] >> 4) & 0x03
    tkl = data[0] & 0x0F
    code = data[1]
    mid = (data[2] << 8) | data[3]
    if len(data) < 4 + tkl:
        return None
    token = data[4 : 4 + tkl]
    pos = 4 + tkl
    cur_opt = 0
    options: list[tuple[int, bytes]] = []
    payload = b""
    while pos < len(data):
        if data[pos] == 0xFF:
            payload = data[pos + 1 :]
            break
        b = data[pos]
        pos += 1
        delta = (b >> 4) & 0x0F
        length = b & 0x0F
        if delta == 13:
            if pos >= len(data):
                return None
            delta = 13 + data[pos]
            pos += 1
        elif delta == 14:
            if pos + 1 >= len(data):
                return None
            delta = 269 + ((data[pos] << 8) | data[pos + 1])
            pos += 2
        elif delta == 15:
            return None

        if length == 13:
            if pos >= len(data):
                return None
            length = 13 + data[pos]
            pos += 1
        elif length == 14:
            if pos + 1 >= len(data):
                return None
            length = 269 + ((data[pos] << 8) | data[pos + 1])
            pos += 2
        elif length == 15:
            return None

        if pos + length > len(data):
            return None
        cur_opt += delta
        val = data[pos : pos + length]
        pos += length
        options.append((cur_opt, val))

    return {
        "ver": ver,
        "type": mtype,
        "code": code,
        "mid": mid,
        "token": token,
        "options": options,
        "payload": payload,
    }


def decode_cbor(data: bytes, pos: int = 0) -> tuple[Any, int]:
    """Decode CBOR data item per RFC 8949 (stdlib self-contained implementation)."""
    if pos >= len(data):
        raise ValueError("Unexpected EOF in CBOR data")
    b = data[pos]
    pos += 1
    major = b >> 5
    info = b & 0x1F
    if info < 24:
        val = info
    elif info == 24:
        if pos >= len(data):
            raise ValueError("Unexpected EOF in CBOR uint8")
        val = data[pos]
        pos += 1
    elif info == 25:
        if pos + 1 >= len(data):
            raise ValueError("Unexpected EOF in CBOR uint16")
        val = (data[pos] << 8) | data[pos + 1]
        pos += 2
    elif info == 26:
        if pos + 3 >= len(data):
            raise ValueError("Unexpected EOF in CBOR uint32")
        val = int.from_bytes(data[pos : pos + 4], "big")
        pos += 4
    elif info == 27:
        if pos + 7 >= len(data):
            raise ValueError("Unexpected EOF in CBOR uint64")
        val = int.from_bytes(data[pos : pos + 8], "big")
        pos += 8
    else:
        raise ValueError(f"Unsupported CBOR additional info {info}")

    if major == 0:  # unsigned integer
        return val, pos
    elif major == 1:  # negative integer: -1 - val
        return -1 - val, pos
    elif major == 2:  # byte string
        if pos + val > len(data):
            raise ValueError("Unexpected EOF in CBOR bstr")
        return data[pos : pos + val], pos + val
    elif major == 3:  # text string
        if pos + val > len(data):
            raise ValueError("Unexpected EOF in CBOR tstr")
        return data[pos : pos + val].decode("utf-8", errors="replace"), pos + val
    elif major == 4:  # array
        arr = []
        for _ in range(val):
            elem, pos = decode_cbor(data, pos)
            arr.append(elem)
        return arr, pos
    elif major == 5:  # map
        m: dict[Any, Any] = {}
        for _ in range(val):
            k, pos = decode_cbor(data, pos)
            v, pos = decode_cbor(data, pos)
            m[k] = v
        return m, pos
    elif major == 6:  # semantic tag
        return decode_cbor(data, pos)
    elif major == 7:  # simple / float
        if val == 20:
            return False, pos
        if val == 21:
            return True, pos
        if val == 22:
            return None, pos
        return val, pos
    raise ValueError(f"Unknown CBOR major type {major}")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <capture.pcap>")
        return 2

    capture_path = sys.argv[1]

    # CHECK 1: Pcap file readability and datagram extraction
    try:
        dg_list = read_datagrams(capture_path)
    except Exception as e:
        print(f"CHECK 1 [pcap_readable]: FAIL - cannot read capture '{capture_path}': {e}")
        return 1

    if not dg_list:
        print(f"CHECK 1 [pcap_readable]: FAIL - capture '{capture_path}' contains no UDP datagrams")
        return 1

    print(f"CHECK 1 [pcap_readable]: PASS - read {len(dg_list)} UDP datagrams from capture")

    packets = []
    for d in dg_list:
        coap = parse_coap(d.payload)
        packets.append((d, coap))

    # CHECK 2: Client Observe registration requests
    # Draft Section 4.1 & RFC 7641 Section 2:
    # Clients initiate observation by sending a GET request for the resource (/mult)
    # with an Observe Option with value 0 (registration).
    # Server is at 127.0.0.1:5683.
    # In Cell N1, 3 clients run sequentially and register.
    registrations = []
    for idx, (d, coap) in enumerate(packets):
        if not coap:
            continue
        if (d.dst, d.dport) != ("127.0.0.1", 5683):
            continue
        # Type: Confirmable (0), Code: GET (1)
        if coap["type"] != 0 or coap["code"] != 1:
            continue
        opts = dict(coap["options"])
        # Observe Option (6) with value 0 (b"" or b"\x00")
        has_observe_reg = (6 in opts) and (opts[6] in (b"", b"\x00"))
        # Uri-Path Option (11) matching "mult"
        has_uri_mult = (11 in opts) and (opts[11] == b"mult")
        if has_observe_reg and has_uri_mult:
            registrations.append({
                "idx": idx,
                "client_src": (d.src, d.sport),
                "token": coap["token"],
                "mid": coap["mid"],
            })

    if len(registrations) < 3:
        print(
            f"CHECK 2 [client_registrations]: FAIL - observed only {len(registrations)} "
            f"client Observe registration requests for /mult (expected 3 per draft Section 4.1)"
        )
        return 1
    print(
        f"CHECK 2 [client_registrations]: PASS - observed {len(registrations)} "
        f"client Observe registration requests for /mult (draft Section 4.1, RFC 7641 Section 2)"
    )

    # CHECK 3 & CHECK 4: Server Informative Responses & Transport-Specific Content (tp_info)
    # Draft Section 4.2 (Informative Response):
    # "The server sends to each of such clients an informative response message,
    # encoded as a unicast response with response code 5.03 (Service Unavailable).
    # As per [RFC7641], such a response does not include an Observe Option.
    # The response MUST be a Confirmable message sent as a separate response (see Section 5.2.2 of [RFC7252])...
    # The Content-Format of the informative response is set to 'application/informative-response+cbor'...
    # The payload of the informative response is a CBOR map..."
    #
    # Draft Section 4.2.1 & 4.2.1.1 (UDP Transport-Specific Information):
    # Parameter 'tp_info' (key 0) conveys:
    # [ tpi_server: CRI-no-local, tpi_client: CRI-no-local, tpi_token: bstr ]
    # where tpi_server specifies server source (127.0.0.1),
    # tpi_client specifies multicast destination (224.0.1.187:56830),
    # and tpi_token specifies the Token T for group notifications.
    group_tokens = []
    for reg_idx, reg in enumerate(registrations):
        client_src = reg["client_src"]
        client_token = reg["token"]
        found_resp = None
        for idx in range(reg["idx"] + 1, len(packets)):
            d, coap = packets[idx]
            if not coap:
                continue
            if (d.src, d.sport) == ("127.0.0.1", 5683) and (d.dst, d.dport) == client_src:
                if coap["code"] == 163:  # 5.03 Service Unavailable (0xa3)
                    found_resp = (idx, d, coap)
                    break

        if not found_resp:
            print(
                f"CHECK 3 [server_informative_response]: FAIL - no 5.03 informative response "
                f"observed for client {reg_idx + 1} at {client_src} (draft Section 4.2)"
            )
            return 1

        resp_idx, d, coap = found_resp

        # Response MUST be Confirmable separate response (draft Section 4.2, RFC 7252 Section 5.2.2)
        if coap["type"] != 0:
            print(
                f"CHECK 3 [server_informative_response]: FAIL - 5.03 response for client {reg_idx + 1} "
                f"is type {coap['type']}, MUST be Confirmable (0) (draft Section 4.2)"
            )
            return 1

        # Token MUST match client request token (RFC 7252 Section 5.2.2)
        if coap["token"] != client_token:
            print(
                f"CHECK 3 [server_informative_response]: FAIL - response token {coap['token'].hex()} "
                f"does not match client {reg_idx + 1} request token {client_token.hex()}"
            )
            return 1

        opts = dict(coap["options"])
        # As per RFC 7641 and draft Section 4.2, MUST NOT include Observe option
        if 6 in opts:
            print(
                f"CHECK 3 [server_informative_response]: FAIL - 5.03 response for client {reg_idx + 1} "
                f"erroneously includes Observe Option (forbidden by draft Section 4.2)"
            )
            return 1

        # MUST include Content-Format Option 12 (draft Section 4.2 / Section 15.2)
        if 12 not in opts:
            print(
                f"CHECK 3 [server_informative_response]: FAIL - 5.03 response for client {reg_idx + 1} "
                f"lacks Content-Format option (draft Section 4.2)"
            )
            return 1

        # CHECK 4: Validate CBOR payload and tp_info structure (draft Section 4.2.1.1, Section 11)
        try:
            cbor_map, _ = decode_cbor(coap["payload"])
        except Exception as e:
            print(
                f"CHECK 4 [informative_tp_info]: FAIL - client {reg_idx + 1} response payload "
                f"is not valid CBOR: {e} (draft Section 4.2)"
            )
            return 1

        if not isinstance(cbor_map, dict) or 0 not in cbor_map:
            print(
                f"CHECK 4 [informative_tp_info]: FAIL - client {reg_idx + 1} CBOR payload "
                f"missing mandatory 'tp_info' (key 0) (draft Section 4.2, Section 11)"
            )
            return 1

        tp_info = cbor_map[0]
        if not isinstance(tp_info, list) or len(tp_info) < 3:
            print(
                f"CHECK 4 [informative_tp_info]: FAIL - client {reg_idx + 1} 'tp_info' "
                f"is not a 3-element list [tpi_server, tpi_client, tpi_token] (draft Section 4.2.1.1)"
            )
            return 1

        tpi_server, tpi_client, tpi_token = tp_info[0], tp_info[1], tp_info[2]
        # Validate tpi_client: destination multicast group 224.0.1.187:56830
        if not isinstance(tpi_client, list) or len(tpi_client) < 2:
            print(
                f"CHECK 4 [informative_tp_info]: FAIL - client {reg_idx + 1} 'tpi_client' "
                f"invalid CRI structure (draft Section 4.2.1)"
            )
            return 1
        client_auth = tpi_client[1]
        raw_grp_ip = client_auth[0]
        grp_ip = ".".join(str(b) for b in raw_grp_ip) if isinstance(raw_grp_ip, bytes) else str(raw_grp_ip)
        grp_port = client_auth[1] if len(client_auth) > 1 else 5683

        if (grp_ip, grp_port) != ("224.0.1.187", 56830):
            print(
                f"CHECK 4 [informative_tp_info]: FAIL - 'tpi_client' destination ({grp_ip}:{grp_port}) "
                f"does not match expected 224.0.1.187:56830 (draft Section 4.2.1.1)"
            )
            return 1

        if not isinstance(tpi_token, bytes) or len(tpi_token) == 0:
            print(
                f"CHECK 4 [informative_tp_info]: FAIL - client {reg_idx + 1} 'tpi_token' "
                f"is missing or empty byte string (draft Section 4.2.1.1)"
            )
            return 1

        group_tokens.append(tpi_token)
        reg["resp_idx"] = resp_idx
        reg["group_token"] = tpi_token

    print(
        "CHECK 3 [server_informative_response]: PASS - server returned CON 5.03 separate responses "
        "without Observe option for all 3 clients (draft Section 4.2, RFC 7252 Section 5.2.2)"
    )
    expected_token = group_tokens[0]
    print(
        f"CHECK 4 [informative_tp_info]: PASS - all informative responses include valid tp_info "
        f"(multicast 224.0.1.187:56830, token 0x{expected_token.hex()}) (draft Section 4.2.1.1)"
    )

    # CHECK 5: Multicast Notifications Addressing, Type, and Token
    # Draft Section 4.3 (Notifications) & Section 4.4 (Congestion Control):
    # "Given an ongoing group observation for a target resource, the server sends multicast
    # notifications intended to all the clients taking part in the group observation.
    # In particular, each such multicast notification is formatted as follows:
    # * It MUST be a Non-confirmable message.
    # * It MUST include an Observe Option, as per [RFC7641].
    # * It MUST have the same Token value T of the phantom registration request that started
    #   the group observation.
    # * It MUST be sent from the same IP address SRV_ADDR and port number SRV_PORT...
    # * It MUST be sent to the IP multicast address GRP_ADDR and port number GRP_PORT."
    notifs = []
    for idx, (d, coap) in enumerate(packets):
        if not coap:
            continue
        if (d.dst, d.dport) == ("224.0.1.187", 56830) and (d.src, d.sport) == ("127.0.0.1", 5683):
            # Must be Non-confirmable (Type 1)
            if coap["type"] != 1:
                print(
                    f"CHECK 5 [multicast_notifications]: FAIL - notification at packet {idx + 1} "
                    f"is type {coap['type']}, MUST be Non-confirmable (1) (draft Section 4.3, 4.4)"
                )
                return 1

            # Token MUST match phantom registration request token T (from informative response tp_info)
            if coap["token"] != expected_token:
                print(
                    f"CHECK 5 [multicast_notifications]: FAIL - notification at packet {idx + 1} "
                    f"token 0x{coap['token'].hex()} does not match group token 0x{expected_token.hex()} "
                    f"(draft Section 4.3)"
                )
                return 1

            opts = dict(coap["options"])
            # MUST include Observe Option (6)
            if 6 not in opts:
                print(
                    f"CHECK 5 [multicast_notifications]: FAIL - notification at packet {idx + 1} "
                    f"lacks Observe Option (draft Section 4.3, RFC 7641)"
                )
                return 1

            obs_raw = opts[6]
            obs_val = int.from_bytes(obs_raw, "big") if obs_raw else 0
            notifs.append({"idx": idx, "obs": obs_val, "mid": coap["mid"]})

    if len(notifs) < 3:
        print(
            f"CHECK 5 [multicast_notifications]: FAIL - observed only {len(notifs)} "
            f"multicast notifications (expected at least 3) (draft Section 4.3)"
        )
        return 1

    print(
        f"CHECK 5 [multicast_notifications]: PASS - observed {len(notifs)} NON multicast notifications "
        f"to 224.0.1.187:56830 with matching group token 0x{expected_token.hex()} (draft Section 4.3, 4.4)"
    )

    # CHECK 6: Monotonically increasing Observe sequence numbers
    # RFC 7641 Section 3.4 & 4.4, Draft Section 4.3:
    # Observe sequence numbers indicate the sequence of state updates and MUST strictly increase
    # across sequential notifications in this experiment.
    obs_vals = [n["obs"] for n in notifs]
    for i in range(1, len(obs_vals)):
        if obs_vals[i] <= obs_vals[i - 1]:
            print(
                f"CHECK 6 [increasing_observe_values]: FAIL - Observe sequence numbers not strictly "
                f"increasing: {obs_vals[i - 1]} -> {obs_vals[i]} (RFC 7641 Section 3.4, draft Section 4.3)"
            )
            return 1

    print(
        f"CHECK 6 [increasing_observe_values]: PASS - Observe sequence numbers are strictly increasing "
        f"({obs_vals[0]} -> {obs_vals[-1]}) (RFC 7641 Section 3.4, draft Section 4.3)"
    )

    # CHECK 7: Notification count per client
    # Cell N1 profile specification:
    # "three clients run one after another; each registers for multicast notifications;
    #  each client is expected to receive at least 3 notifications."
    for reg_idx, reg in enumerate(registrations):
        start_idx = reg["resp_idx"]
        next_reg_idx = (
            registrations[reg_idx + 1]["idx"] if reg_idx + 1 < len(registrations) else len(packets)
        )
        client_notifs = [n for n in notifs if start_idx < n["idx"] < next_reg_idx]
        if len(client_notifs) < 3:
            print(
                f"CHECK 7 [notification_count]: FAIL - client {reg_idx + 1} observed only "
                f"{len(client_notifs)} notifications (minimum 3 required for cell N1)"
            )
            return 1

    print(
        f"CHECK 7 [notification_count]: PASS - each of the 3 clients observed at least 3 notifications "
        f"(total {len(notifs)} notifications across 3 client phases)"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
