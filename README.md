# AI2II — AI-assisted IETF protocol implementation and interop

AI2II is a workflow and toolset for building protocol implementations with AI agents
**without trusting the agents' claims**. Implementation and verification are done by
independent agents (different model families), a deterministic orchestrator owns every
state change and runs every test itself, and interop claims are backed by wire-level
evidence bundles that anyone can re-check.

Prepared for the **IETF 127 Hackathon, San Francisco, 14–15 November 2026** (champions: Alexander Pelov, Ivaylo Petrov). Participants: start with [`docs/HACKATHON.md`](docs/HACKATHON.md).

## What do you want to achieve?

| I want to… | Start here |
|---|---|
| **See it work in one command** | `./demo.sh`: runs an example under capture, verifies the bundle and explains it |
| **Take part in the Hackathon** | [`docs/HACKATHON.md`](docs/HACKATHON.md): the runbook, from setup to a shareable bundle |
| **Understand a bundle file by file** | [`docs/BUNDLE.md`](docs/BUNDLE.md) |
| **Report Hackathon results** | [`docs/SUBMISSION.md`](docs/SUBMISSION.md) |
| **Show that my implementation really interoperates**: a capture of the exchange, not just "tests pass" | [Quick start: wire evidence](#quick-start-wire-evidence): write an `interop.yaml` for your peers, run `python3 -m wire run`, share the bundle |
| **See inside a secured protocol** (TLS, DTLS, QUIC, …): the encrypted trace *and* a decrypted one | Peers export their keys; the bundle gets `capture-decrypted.pcapng` next to `capture.pcap`. See `wire/example/tls_echo/` and DESIGN.md 24.21 |
| **Check someone else's interop claim** | `python3 -m wire verify-bundle <bundle>`, then open `capture.pcap` in Wireshark and read `verdict.json` and the checker logs. Try it on `runs/wire/oscore-n1/` |
| **Have AI agents implement a protocol (or a milestone) without trusting their claims** | [Quick start: orchestrator](#quick-start-orchestrator), `AGENTS.md` (role prompts) and DESIGN.md section 24 (the workflow) |
| **Get an independent checker for my implementation** | A checker must come from a different model family than the code it checks, and must reject declared negative inputs. See `experiments/oscore-n1/checkers/` for a worked example |
| **See how this was built and verified** | `milestones/*/attempts/` (build reports, verdicts), `reviews/`, `runs/` (logs the orchestrator wrote) |

## What is here

| Path | What it is |
|---|---|
| `orch`, `orchestrator.py` | The orchestrator (milestone M01): lifecycle commands, path-ownership checks, orchestrator-run tests with logs, verdict validation, integration with rollback. |
| `wire/` | Wire evidence (M08) and secured-protocol support (M09): runs interop cells under packet capture and writes a self-verifying bundle. |
| `AGENTS.md` | Contract and role prompts for architect, reviewer, builder, verifier. |
| `DESIGN.md` | The design; sections 24.20 (wire evidence) and 24.21 (secured protocols) describe `wire/`. |
| `workflow.yaml` | Policy: roles, diversity rules, limits, path ownership. |
| `milestones/` | Specs and orchestrator-written state for each milestone; `attempts/` hold build reports and verification records. |
| `reviews/`, `approvals/`, `escalations/` | Independent reviews, human gate decisions, escalations. |
| `runs/` | Orchestrator-run test logs (validity runs included) and wire evidence bundles. |
| `experiments/oscore-n1/` | First real experiment: cell N1 of the CoAP multicast-notifications interop matrix. |
| `tests/`, `acceptance/` | Builder tests and independent acceptance tests (with mutants) per milestone. |

## Status

| Milestone | State |
|---|---|
| M01 Orchestrator minimum | COMPLETE |
| M08 Wire evidence bundles and checked test vectors | COMPLETE |
| M09 Secured protocols: exported keys and decrypted captures | COMPLETE |
| M02 Agent dispatch (sandboxed agents, fallback, prompt rendering) | COMPLETE |
| M10 Portability (loopback on macOS and Linux), `wire summarize`, deliberately broken example | COMPLETE |
| M03–M07 | DRAFT |

Each COMPLETE milestone was built by one model family and verified by another, with
acceptance tests that are shown to fail on the pre-implementation code or under deliberate
mutants of the implementation. The records under `milestones/*/attempts/`, `reviews/` and
`runs/` name the model family of each role: that provenance is how the independence rule is
checked. Commit hashes cited in those records refer to the development repository; this
public repository starts from a fresh history.

## Quick start: wire evidence

Requirements: macOS or Linux, Python 3.11+ with PyYAML, `tcpdump` with capture permission
(macOS: membership in `access_bpf`). Wireshark (`tshark`, `editcap`) is needed only by
experiments that use it.

```sh
./demo.sh                      # one command: run, verify, explain (macOS and Linux)
python3 -m wire validate-checkers wire/example/udp_echo/interop.yaml
python3 -m wire run wire/example/udp_echo/interop.yaml --cell echo --out /tmp/echo
python3 -m wire verify-bundle /tmp/echo/echo
```

A bundle holds `capture.pcap`, one log per peer and checker, `env.json` (commits, binary
SHA-256, tool versions), `verdict.json` (exactly one of PASS / FAIL / BLOCKED / ENV) and
`SHA256SUMS`. Every checker must reject its declared negative inputs in every run, and a
checker may not come from the same model family as the implementation under test.

For secured protocols (TLS, DTLS, QUIC, ...), peers export their keys (for example via
`SSLKEYLOGFILE`) and the bundle additionally holds `capture-decrypted.pcapng`, which opens
decrypted in Wireshark. See `wire/example/tls_echo/` and DESIGN.md 24.21. Example keys are
throwaway test keys; never run experiments with real keys.

## Quick start: orchestrator

```sh
./orch status
./orch show M08
./scripts/verify_gate.sh          # lint, test hygiene, DAG and ownership checks, unit tests
```

## Evidence included

`runs/wire/oscore-n1/` holds two bundles of the CoAP multicast-notifications cell N1
(C server, three C clients): an `ENV` bundle (the multicast route env check failed, nothing
ran) and a `PASS` bundle with the capture, peer logs and an independent checker's results.
Re-check them with `python3 -m wire verify-bundle <bundle>`. See `experiments/oscore-n1/README.md`.

`runs/wire/dtls-openssl-gnutls/` holds two PASS bundles of DTLS 1.2 interop between two
independent stacks, OpenSSL 3.6 and GnuTLS 3.8, one per direction. Each has the encrypted
`capture.pcap` and a self-decrypting `capture-decrypted.pcapng` built from the clients'
exported session keys (test keys; `contains_secrets: true`). The checkers come from a
different model family than the peer adapters and reject a cleartext capture, wrong keys and
a substituted decrypted view. See `experiments/dtls-openssl-gnutls/`.

## License

BSD-3-Clause, see `LICENSE`.
