# DTLS 1.2 Evidence Checkers

Independent evidence checkers for DTLS 1.2 wire captures and decrypted views (DESIGN.md 24.20 and 24.21).

- **Author Family:** `google`
- **Model:** Gemini 3.8 Flash (High)

---

## Checkers Overview

### 1. `observes_dtls.py` (Raw Capture Checker)

Usage:
```bash
python3 checkers/observes_dtls.py <capture>
```

Asserts that the capture demonstrates a complete, genuine DTLS 1.2 session between loopback endpoints without leaking plaintext on the wire. Port-agnostic across cells.

Each check evaluates an explicit normative property and outputs one `PASS` or `FAIL` line:

1. **Loopback Transport Mapping (RFC 6347 Section 4.1.1):**
   Verifies that the exchange takes place entirely over loopback addresses (`127.0.0.0/8` or `::1`). Identifies the client endpoint (origin of `ClientHello`) and server endpoint.
2. **ClientHello Handshake Message (RFC 6347 Section 4.2.1 / RFC 5246 Section 7.4.1.2):**
   Verifies that the client initiates the handshake with a `ClientHello` message (handshake type 1, record type 22).
3. **ServerHello Negotiating DTLS 1.2 (RFC 6347 Section 4.2.1 / RFC 5246 Section 7.4.1.3):**
   Verifies that the server responds with `ServerHello` (handshake type 2, record type 22) negotiating protocol version DTLS 1.2 (`{254, 253}` / `0xfefd`).
4. **Client ChangeCipherSpec & Finished (RFC 6347 Sections 4.1, 4.2.5, 4.2.6 / RFC 5246 Sections 7.1, 7.4.9):**
   Verifies that the client transmits a `ChangeCipherSpec` record (type 20, epoch 0) followed by an encrypted `Finished` handshake record (type 22, epoch >= 1).
5. **Server ChangeCipherSpec & Finished (RFC 6347 Sections 4.1, 4.2.5, 4.2.6 / RFC 5246 Sections 7.1, 7.4.9):**
   Verifies that the server transmits a `ChangeCipherSpec` record (type 20, epoch 0) followed by an encrypted `Finished` handshake record (type 22, epoch >= 1).
6. **Encrypted Application Data in Both Directions (RFC 6347 Section 4.1 / RFC 5246 Section 10):**
   Verifies that encrypted application data records (record type 23, epoch >= 1) are exchanged in both directions: client -> server (request) and server -> client (echo).
7. **Record Payload Protection (RFC 6347 Section 4.1.2 / RFC 5246 Section 6.2.3):**
   Verifies that the test vector payload bytes do NOT appear in clear in any UDP datagram payload across the entire capture.

---

### 2. `decrypted_payload.py` (Decrypted View Checker)

Usage:
```bash
python3 checkers/decrypted_payload.py <decrypted.pcapng> <payload.bin>
```

Asserts that self-decrypting pcapng views (produced by key injection via `editcap`) decode into valid application data carrying the expected payload vector in both directions, and that the cryptographic handshake was verified:

1. **DTLS Handshake Completed (RFC 6347 Section 4.2.6 / RFC 5246 Section 7.4.9):**
   Verifies that both client and server `Finished` handshake messages (handshake type 20) are successfully decrypted using the session secrets. Because `Finished` is encrypted under the negotiated security parameters, successful dissection is proof of key validity and integrity.
2. **Request Payload Decrypted (RFC 6347 Section 4.1 / RFC 5246 Section 10):**
   Verifies that decrypted application data (`data.data` on `dtls.app_data`) from client to server contains the test vector payload bytes from `<payload.bin>`.
3. **Echo Payload Decrypted (RFC 6347 Section 4.1 / RFC 5246 Section 10):**
   Verifies that decrypted application data (`data.data` on `dtls.app_data`) from server to client contains the test vector payload bytes from `<payload.bin>`.

---

## Negative Test Vectors (`checkers/negatives/`)

All negative cases are validated to ensure checkers fail closed on invalid, incomplete, or corrupted traffic:

- **`unrelated.pcap`**:
  Synthetic loopback UDP datagrams between ports 40001 and 40002 carrying non-DTLS payload (`"unrelated"`). Rejects with failure on DTLS framing and handshake.
- **`one_direction.pcap`**:
  Filtered from `A-gnutls-srv-openssl-cli.pcap` retaining only client-to-server traffic (`udp.dstport == 47555`). Rejects with failure on missing server handshake messages and server application data.
- **`cleartext.pcap`**:
  Direct copy of `A-cleartext.pcap` (plain UDP echo without DTLS). Rejects with `asserts: encrypted` failure due to missing DTLS framing and cleartext payload leakage in UDP payloads.
- **`openssl-client.keys.altered`**:
  Altered SSLKEYLOGFILE derived from `A-client.keys` with the first hex character of the master secret modified. Injected into `A-gnutls-srv-openssl-cli.pcap` with `editcap`, decryption fails; `Finished` (type 20) and application data are not decrypted.
- **`gnutls-client.keys.altered`**:
  Altered SSLKEYLOGFILE derived from `B-client.keys` with the first hex character of the master secret modified. Injected into `B-openssl-srv-gnutls-cli.pcap` with `editcap`, decryption fails; `Finished` (type 20) and application data are not decrypted.
- **`other_payload.pcapng`**:
  Self-decrypting pcapng created by injecting `Aother-client.keys` into `A-other-payload.pcap` via `editcap`. Decrypts valid application data, but the payload is `"SOMETHING-ELSE-ENTIRELY\n"`, failing matching against `vectors/payload.bin`.

---

## Limitations

- **Protocol Scope:** Specifically validates DTLS version 1.2 (`0xfefd` / `{254, 253}`) over UDP. Does not validate DTLS 1.0 or DTLS 1.3.
- **Environment:** Requires loopback endpoints (`127.0.0.0/8` or `::1`).
- **Dependencies:** Relies on `tshark` (Wireshark 4.x recommended) available in `PATH` or at `/Applications/Wireshark.app/Contents/MacOS/tshark`.
