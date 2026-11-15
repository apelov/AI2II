# Hackathon result: oscore-n1, cell N1-py (Python client port)

IETF 127 Hackathon, 14–15 November 2026, project AI2II. Remote participant.

## Experiment

- **Name:** oscore-n1-nosec, cell `N1-py`: C server and a new Python client
- **Team / contact:** Jenny Yen, https://github.com/YENCHUNYU (remote participant)
- **Draft(s) and revision(s):** draft-ietf-core-observe-multicast-notifications-15 (nosec profile; Group OSCORE not used);
  RFC 7252, RFC 7641
- **Experiment directory and commit:** `experiments/oscore-n1/`, experiment commit `2012909c24c8`
  (Python client and cell `N1-py`); bundle committed in `b694ef030a2b`

What was done: the client side of the draft (Section 5) was ported to Python with an AI coding
agent and tested against the existing C server under packet capture, with the existing
independent checker.

## Implementations (peers)

| Peer | Implementation and version | Repository and commit | Written by (model family or human) | Under test |
|---|---|---|---|---|
| `c-server` | C server on libcoap 4.3.5b (Homebrew), `make -B -f Makefile.vienna` | https://github.com/apelov/coap-multicast-notifications @ `9b7d288` | anthropic (Claude) | yes |
| `py-clients` | `py-client/mn_client.py`, Python 3.13.14 standard library only; `run_clients.py` runs 3 clients in sequence | this repository, `experiments/oscore-n1/py-client/` @ `2012909` | anthropic (Claude Code, Claude Opus 5.5), human-directed | yes |

The Python client was written from the draft text (Section 5.1–5.3, 4.2.1 for the CRI format)
and from the wire behaviour seen in the N1 capture, **not** by translating `src/client.c`. It
implements: CON GET with Observe 0; empty-ACK / separate-response handling; ACK of the CON 5.03;
CBOR decoding of the informative response; `tpi_server` / `tpi_client` CRI parsing with default
port 5683; `tpi_token`; comparison of `ph_req` with its own registration (Section 5.2 step 3);
`last_notif` as the Observe baseline (step 5–6); joining the group; filtering notifications by
server address and token T; RFC 7641 Section 3.4 reordering. It exits 0 only after the requested
number of fresh notifications and exits 1 on any malformed field or timeout (checked by hand against
a closed port: exit 1).

## Checkers

| Checker | Written by (model family or human) | What it asserts (spec sections) | Negatives |
|---|---|---|---|
| `observes-n1` (`checkers/observes_n1.py`, unchanged) | google (gemini-3.8-flash-high) | 3 Observe registrations (4.1, RFC 7641 §2); CON 5.03 informative response without Observe, with Content-Format (4.2); `tp_info` CRIs and token (4.2.1.1); NON 2.05 multicast notifications with token T (4.3, 4.4); strictly increasing Observe (RFC 7641 §3.4); ≥3 notifications per client phase | 5: `unrelated`, `no_multicast`, `no_server_response`, `fewer_clients`, `observe_not_increasing` — all rejected in this run |

The checker family (google) differs from both implementations under test (anthropic).

## Results

| Cell | Verdict | Bundle path | Reason (for FAIL / BLOCKED / ENV) |
|---|---|---|---|
| N1-py | PASS | `runs/wire/oscore-n1/N1-py-20261115T002754Z/N1-py` | — (all peers exited 0, capture non-empty, every checker passed and rejected its negatives) |

`python3 -m wire verify-bundle runs/wire/oscore-n1/N1-py-20261115T002754Z/N1-py` prints `OK`.
Host: macOS 27.2 (Apple Silicon), loopback `lo0`, tcpdump 4.99.1, Python 3.13.14.

**What this PASS shows about the Python client.** In cell N1-py, `observes-n1` checks the client's
wire behaviour only through its Observe registrations (check 2); checks 3–7 assert the C server's
messages. That the Python client decoded `tp_info`, joined the group and accepted the notifications
is evidenced by its own exit 0 and its log (`py-clients.log`: three clients, three
`[NOTIFICATION]` lines each), not by the checker. The client exits 1 on any failed step.

The original cell `N1` (C server, C clients) was also re-run on this host as a setup check: PASS.
That bundle was not kept (it reproduces the existing `N1-20261103T200141Z`). Its binary hashes
differ from those in `experiments/oscore-n1/README.md` (`coap_server` `34f2ec00…` vs `8c1732a8…`),
as expected with a different libcoap version (4.3.5b) and toolchain.

## Findings

No FAIL in this experiment: the Python client and the C server interoperated on the first run.

## Feedback on the draft

1. **Content-Format of the informative response is `TBD` (Section 15.2).** This is the normal state
   before IANA assignment, not an error in the draft. In practice each implementation must pick a
   placeholder: the C server sends `12`, the C client accepts `12` or `120`; the Python client logs
   the value and does not enforce one. Suggestion: state a suggested value for experimentation
   (e.g. "TBD (suggested: 12)"), or consider early allocation, so that independent implementations
   agree during interop testing.

## Observations on the AI-assisted workflow

- The client (≈400 lines) was written in one pass from the draft; it passed lint after one fix and
  interoperated on the first wire run. Human role: choosing the task, approving each step, running
  and reading the results.
- Most of the time went into host setup on a clean macOS machine, not into the protocol: Python 3.11+
  (the default `python3` was 3.10), PyYAML, capture permission (Wireshark's ChmodBPF had to be
  installed separately), a leftover Intel Homebrew whose `git` and `pkg-config` could not run on
  Apple Silicon, `libcoap`/`libcbor` for the C peers, and the multicast route on `lo0`.
- Independence is limited: the C implementation and the Python client both come from the same
  model family (anthropic). Writing the client from the draft rather than from the C code reduces,
  but does not remove, the risk of shared misreadings. Only the checker is from another family.

## Not verified

- **The other direction** (Python server → C clients): no Python server was written.
- **Group OSCORE** (secured profile, Section 9): only the nosec profile was tested.
- **Client error paths on the wire**: malformed or missing `tp_info`, `ph_req` that differs from the
  registration, cancellation (Sections 4.5, 5.4), multicast error responses. The client has code for
  several of these, but no cell exercises them.
- **`last_notif` as reordering baseline**: the C server sends `last_notif` with Observe 0; the case
  where a stale notification arrives after the baseline was not produced.
- **Rough counting / Feedback-Divider** (Section 8), IPv6 groups, host-name CRIs, CRIs with userinfo.
- **Other hosts**: only macOS 27.2 on Apple Silicon; not run on Linux.
- **An independent implementation from another model family** (or a human) to test against.
