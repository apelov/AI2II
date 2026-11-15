# Hackathon result: oscore-n1, cells N1-py and N1-pyserver (Python port, both directions)

IETF 127 Hackathon, 14–15 November 2026, project AI2II. Remote participant.

## Experiment

- **Name:** oscore-n1-nosec, cells `N1-py` (C server, Python clients) and `N1-pyserver`
  (Python server, C clients)
- **Team / contact:** Jenny Yen, https://github.com/YENCHUNYU (remote participant)
- **Draft(s) and revision(s):** draft-ietf-core-observe-multicast-notifications-15 (nosec profile; Group OSCORE not used);
  RFC 7252, RFC 7641
- **Experiment directory and commit:** `experiments/oscore-n1/`. Python client and cell `N1-py`:
  commit `2012909c24c8`, bundle in `b694ef030a2b`. Python server and cell `N1-pyserver`: commit
  `c8d0380`, bundle in `0616667`.

What was done: both sides of the draft (Section 4, server; Section 5, client) were ported to Python
with an AI coding agent and each was tested against the existing C implementation of the other
side, under packet capture, with the existing independent checker.

## Implementations (peers)

| Peer | Implementation and version | Repository and commit | Written by (model family or human) | Under test |
|---|---|---|---|---|
| `c-server` | C server on libcoap 4.3.5b (Homebrew), `make -B -f Makefile.vienna` | https://github.com/apelov/coap-multicast-notifications @ `9b7d288` | anthropic (Claude) | yes |
| `c-clients` | C client, same build; `clients_seq.py` runs 3 clients in sequence | same @ `9b7d288` | anthropic (Claude) | yes |
| `py-clients` | `py-client/mn_client.py`, Python 3.13.14 standard library only; `run_clients.py` runs 3 clients in sequence | this repository, `experiments/oscore-n1/py-client/` @ `2012909` | anthropic (Claude Code, Claude Opus 5.5), human-directed | yes |
| `py-server` | `py-server/mn_server.py`, Python 3.13.14 standard library only | this repository, `experiments/oscore-n1/py-server/` @ `c8d0380` | anthropic (Claude Code, Claude Opus 5.5), human-directed | yes |

Both Python peers were written from the draft text and from the wire behaviour seen in the N1
capture, **not** by translating `src/client.c` or `src/server.c`.

**Python client** (Sections 5.1–5.3, 4.2.1): CON GET with Observe 0; empty-ACK / separate-response
handling; ACK of the CON 5.03; CBOR decoding of the informative response; `tpi_server` / `tpi_client`
CRI parsing with default port 5683; `tpi_token`; comparison of `ph_req` with its own registration
(5.2 step 3); `last_notif` as the Observe baseline (steps 5–6); joining the group; filtering
notifications by server address and token T; RFC 7641 Section 3.4 reordering. It exits 0 only after
the requested number of fresh notifications and exits 1 on any malformed field or timeout (checked
by hand against a closed port: exit 1).

**Python server** (Sections 4.1–4.4): starts the group observation on the first registration with a
phantom request and a **random** Token T per run (4 bytes); stores INIT_NOTIF and replaces it with each
sent notification; answers each registration with an empty ACK and then a CON 5.03 without Observe,
retransmitted until ACKed (RFC 7252 4.2); payload `{0: tp_info, 1: ph_req, 2: last_notif,
3: next_not_before}`, with the default port omitted from `tpi_server`; NON 2.05 notifications with
Observe and Token T from SRV_ADDR:SRV_PORT to GRP_ADDR:GRP_PORT every 5 s (refuses an interval
below 3 s, Section 4.4); refuses link-local or unspecified server addresses (4.2). Before the wire
run it was also checked by hand against the Python client (PASS, 3/3 notifications).

## Checkers

| Checker | Written by (model family or human) | What it asserts (spec sections) | Negatives |
|---|---|---|---|
| `observes-n1` (`checkers/observes_n1.py`, unchanged) | google (gemini-3.8-flash-high) | 3 Observe registrations (4.1, RFC 7641 §2); CON 5.03 informative response without Observe, with Content-Format (4.2); `tp_info` CRIs and token (4.2.1.1); NON 2.05 multicast notifications with token T (4.3, 4.4); strictly increasing Observe (RFC 7641 §3.4); ≥3 notifications per client phase | 5: `unrelated`, `no_multicast`, `no_server_response`, `fewer_clients`, `observe_not_increasing` — all rejected in both runs |

The checker family (google) differs from every implementation under test (anthropic).

## Results

| Cell | Verdict | Bundle path | Reason (for FAIL / BLOCKED / ENV) |
|---|---|---|---|
| N1-py | PASS | `runs/wire/oscore-n1/N1-py-20261115T002754Z/N1-py` | — (all peers exited 0, capture non-empty, every checker passed and rejected its negatives) |
| N1-pyserver | PASS | `runs/wire/oscore-n1/N1-pyserver-20261115T013032Z/N1-pyserver` | — (same) |

`python3 -m wire verify-bundle` prints `OK` for both bundles.
Host: macOS 27.2 (Apple Silicon), loopback `lo0`, tcpdump 4.99.1, Python 3.13.14.

**What each PASS shows.** `observes-n1` asserts mostly server behaviour: check 2 is about the
clients' registrations, checks 3–7 about the server's messages.

- In **N1-pyserver**, checks 3–7 assert the **Python server's** messages on the wire (5.03 informative
  responses, `tp_info` with the random token `0x39326226`, nine NON notifications, increasing
  Observe 1 → 9, three per client phase), and the C clients each report 3/3 notifications.
- In **N1-py**, the checker sees the Python client only through its registrations (check 2). That the
  Python client decoded `tp_info`, joined the group and accepted the notifications is evidenced by its
  own exit 0 and its log (`py-clients.log`: three clients, three `[NOTIFICATION]` lines each), not by
  the checker. The client exits 1 on any failed step.

The original cell `N1` (C server, C clients) was also re-run on this host as a setup check: PASS.
That bundle was not kept (it reproduces the existing `N1-20261103T200141Z`). Its binary hashes
differ from those in `experiments/oscore-n1/README.md` (`coap_server` `34f2ec00…` vs `8c1732a8…`),
as expected with a different libcoap version (4.3.5b) and toolchain.

## Findings

No FAIL in this experiment: both Python peers interoperated with the C peers on the first wire run.
Points of interoperability that the runs did exercise:

- The C client accepted an informative response with an extra optional parameter
  (`next_not_before`, key 3) that the C server does not send.
- The C client and the checker took the group token from `tp_info` rather than assuming the C
  server's fixed value: the Python server's random token was accepted by both.

## Feedback on the draft

1. **Content-Format of the informative response is `TBD` (Section 15.2).** This is the normal state
   before IANA assignment, not an error in the draft. In practice each implementation must pick a
   placeholder: the C server sends `12`, the C client accepts `12` or `120`; the Python server sends
   `12` (configurable) and the Python client logs the value without enforcing one. Suggestion: state a
   suggested value for experimentation (e.g. "TBD (suggested: 12)"), or consider early allocation, so
   that independent implementations agree during interop testing.

## Observations on the AI-assisted workflow

- The client (≈400 lines) and the server (≈400 lines) were each written in one pass from the draft;
  both passed lint after minor fixes and interoperated on the first wire run. Human role: choosing the
  task, approving each step, running and reading the results, deciding what to claim in this report.
- Most of the time went into host setup on a clean macOS machine, not into the protocol: Python 3.11+
  (the default `python3` was 3.10), PyYAML, capture permission (Wireshark's ChmodBPF had to be
  installed separately), a leftover Intel Homebrew whose `git` and `pkg-config` could not run on
  Apple Silicon, `libcoap`/`libcbor` for the C peers, and the multicast route on `lo0`.
- Independence is limited: the C implementation and both Python peers come from the same model family
  (anthropic). Writing the Python peers from the draft rather than from the C code reduces, but does
  not remove, the risk of shared misreadings. Only the checker is from another family.

## Not verified

- **Group OSCORE** (secured profile, Section 9): only the nosec profile was tested.
- **Python server ↔ Python client** under capture: only checked by hand, no bundle.
- **Error paths on the wire**: malformed or missing `tp_info`, `ph_req` that differs from the
  registration, retransmission of the 5.03 when the ACK is lost, cancellation (Sections 4.5, 5.4),
  multicast error responses. Both Python peers have code for some of these, but no cell exercises them.
- **Not implemented in the Python server:** cancellation (4.5), the observer-counter estimation and
  Feedback-Divider (Section 8), `ending`, IPv6, more than one resource.
- **`last_notif` as reordering baseline**: both servers send `last_notif`; the case where a stale
  notification arrives after the baseline was not produced.
- **Host-name CRIs, CRIs with userinfo, non-default `tpi_server` port.**
- **Other hosts**: only macOS 27.2 on Apple Silicon; not run on Linux.
- **An independent implementation from another model family** (or a human) to test against.
