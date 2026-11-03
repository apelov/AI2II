# Cell N1 Evidence Checker: `observes-n1`

## Authorship & Model Independence
- **Author Family:** `google`
- **Model:** `gemini-3.8-flash-high`
- **Checker File:** [`checkers/observes_n1.py`](observes_n1.py)
- **Specification:** [`draft-ietf-core-observe-multicast-notifications-15`](file://<coap-repo>/docs/secure/draft-ietf-core-observe-multicast-notifications-15.txt)
- **Experiment Profile:** Cell `N1` (nosec profile, CoAP server on `127.0.0.1:5683`, 3 sequential clients, multicast notifications to `224.0.1.187:56830`)

In accordance with AI2II DESIGN.md 24.20 (and lesson L4), this checker was authored independently by family `google` without reading or importing the peer implementation's code or tools under `~/Code/CoAP/src` or `~/Code/CoAP/tools`.

---

## Wire Checks and Draft Section References

The checker performs 7 distinct falsifiable checks across the captured wire datagrams:

### CHECK 1: Capture File Readability (`pcap_readable`)
- **Requirement:** Input file must be a valid, readable packet capture containing UDP datagrams.
- **Implementation:** Uses a pure Python standard library classic pcap parser (`DLT_NULL`, `DLT_EN10MB`, `DLT_RAW`, `DLT_LINUX_SLL/2`) with fallback to `tshark` human-written dissectors.
- **Verdict:** Fails immediately with exit code 1 if the capture cannot be read, is corrupted, or contains zero UDP datagrams.

### CHECK 2: Client Observe Registrations (`client_registrations`)
- **Draft Reference:** Section 4.1 & RFC 7641 Section 2
- **Requirement:** At least 3 sequential client Observe registration requests for resource `/mult` on server `127.0.0.1:5683`.
- **Wire Assertions:**
  - CoAP Code: `GET` (1, `0.01`).
  - CoAP Type: Confirmable (`CON`, 0).
  - Observe Option (`6`): value `0` (registration).
  - Uri-Path Option (`11`): value `mult`.
  - Token: present (length 1–8 bytes).
  - At least 3 distinct client registration exchanges must be observed.

### CHECK 3: Server Informative Response (`server_informative_response`)
- **Draft Reference:** Section 4.2 & RFC 7252 Section 5.2.2 & RFC 7641
- **Requirement:** For each registered client, the server MUST send an informative response message.
- **Wire Assertions:**
  - Response Code: `5.03 Service Unavailable` (`163`, `0xa3`).
  - Message Type: `Confirmable` (`CON`, 0) sent as a separate response.
  - Token: MUST match the client's registration request token.
  - Observe Option (`6`): **MUST NOT** be included (RFC 7641 / Section 4.2).
  - Content-Format Option (`12`): present (`application/informative-response+cbor`, Section 4.2 / Section 15.2).

### CHECK 4: Transport Information Payload (`informative_tp_info`)
- **Draft Reference:** Section 4.2, Section 4.2.1, Section 4.2.1.1 & Section 11
- **Requirement:** The informative response payload is a CBOR map containing transport-specific information (`tp_info`).
- **Wire Assertions:**
  - Payload decodes as a valid CBOR map containing key `0` (`tp_info`).
  - `tp_info` is an array `[tpi_server, tpi_client, tpi_token]`:
    - `tpi_server`: CRI-no-local with CRI scheme `-1` (`"coap"`) and server authority (`127.0.0.1[:5683]`).
    - `tpi_client`: CRI-no-local with CRI scheme `-1` (`"coap"`), destination multicast IP `224.0.1.187`, and port `56830`.
    - `tpi_token`: non-empty CBOR byte string specifying phantom request Token `T` for multicast notifications.

### CHECK 5: Multicast Notifications Addressing & Format (`multicast_notifications`)
- **Draft Reference:** Section 4.3 & Section 4.4
- **Requirement:** Server emits group notifications to `224.0.1.187:56830` from `127.0.0.1:5683`.
- **Wire Assertions:**
  - Message Type: `Non-confirmable` (`NON`, 1) per Section 4.3 and Section 4.4.
  - Code: `2.05 Content` (69).
  - Token: MUST match the group Token `T` (`tpi_token`) announced in `tp_info`.
  - Observe Option (`6`): MUST be present on each notification.
  - Count: at least 3 multicast notifications observed.

### CHECK 6: Monotonically Increasing Observe Values (`increasing_observe_values`)
- **Draft Reference:** Section 4.3 & RFC 7641 Section 3.4 / 4.4
- **Requirement:** Observe sequence numbers track resource state updates and must strictly increase across successive notifications.
- **Wire Assertions:**
  - For each sequential notification $i$, $\text{Observe}_i > \text{Observe}_{i-1}$.

### CHECK 7: Notification Count per Client Phase (`notification_count`)
- **Cell Specification:** Cell N1 nosec profile: 3 clients run sequentially, each expected to observe at least 3 notifications.
- **Wire Assertions:**
  - For each of the 3 client registration phases, at least 3 multicast notifications are sent following the registration and informative response.

---

## Negative Captures

The checker declares 5 capture negatives in `checkers/negatives/`. A correct checker MUST reject each one (exit code non-zero):

1. **`unrelated.pcap`**:
   - **Generation:** Synthesized classic pcap via Python standard library `struct` packing UDP datagrams between arbitrary ports `40001` and `40002` with non-CoAP payload.
   - **Assertion Tested:** Verifies that unrelated UDP traffic is rejected by CHECK 2 (`observed 0 client Observe registration requests`).

2. **`no_multicast.pcap`**:
   - **Generation:** Generated from the development capture using `tshark`:
     ```sh
     tshark -r dev.pcap -Y "not (ip.dst == 224.0.1.187)" -w no_multicast.pcap
     ```
   - **Assertion Tested:** Contains client registrations and server informative responses, but all multicast notifications are stripped. Rejected by CHECK 5 (`observed 0 multicast notifications`).

3. **`no_server_response.pcap`**:
   - **Generation:** Generated from the development capture using `tshark`:
     ```sh
     tshark -r dev.pcap -Y "not (coap.code == 163)" -w no_server_response.pcap
     ```
   - **Assertion Tested:** Contains client registrations and multicast notifications, but the server never sends the required 5.03 informative responses. Rejected by CHECK 3 (`no 5.03 informative response observed for client`).

4. **`fewer_clients.pcap`**:
   - **Generation:** Generated from the development capture using `editcap`:
     ```sh
     editcap -r dev.pcap fewer_clients.pcap 1-7
     ```
   - **Assertion Tested:** Truncated to only 1 client registration and 3 notifications instead of 3 clients. Rejected by CHECK 2 (`observed only 1 client Observe registration requests (expected 3)`).

5. **`observe_not_increasing.pcap`**:
   - **Generation:** Generated from the development capture by transposing notification packets 5 and 6, creating an Observe value inversion (`2 -> 1`).
   - **Assertion Tested:** Rejected by CHECK 6 (`Observe sequence numbers not strictly increasing: 2 -> 1`).

All negatives are validated automatically via:
```sh
PYTHONPATH=. python3 -m wire validate-checkers interop.yaml
```

---

## Limitations (What the Checker Does NOT Check)

1. **OSCORE Cryptographic Protection:**
   - Cell N1 is explicitly the `nosec` profile. This checker does not verify OSCORE options, Partial IVs, Key IDs, or AEAD authentication tags (which apply to OSCORE group communication cells).
2. **Client-Side Host Reception:**
   - The checker is an `observes_capture` wire checker. It verifies that packets are correctly transmitted over the wire/interface (`lo0`), but cannot inspect host OS multicast socket filtering or internal peer memory.
3. **Application Payload Semantics:**
   - The checker asserts CoAP 2.05 Content responses with non-empty payloads, but does not enforce arbitrary application data models beyond draft requirements.
4. **Network Impairment Resilience:**
   - The test assumes an in-order loopback capture without synthetic retransmissions or packet loss.
