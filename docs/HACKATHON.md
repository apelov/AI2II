# AI2II at the IETF 127 Hackathon — runbook

San Francisco, 14–15 November 2026. Project AI2II, champions Alexander Pelov and Ivaylo Petrov.

The goal at the table: every interop claim comes with a **bundle** anyone can re-check —
the capture, the logs, the exact binaries, and a verdict from a checker that did not come
from the same AI model family as the code it checks.

## 0. Before you sit down (15 minutes)

```sh
git clone https://github.com/apelov/AI2II && cd AI2II
python3 -c "import yaml"                      # PyYAML present
python3 -m wire run wire/example/udp_echo/interop.yaml --cell echo --out /tmp/echo
python3 -m wire verify-bundle /tmp/echo/echo  # prints OK
```

If the example gives `BLOCKED` with a capture reason, fix capture permission first (macOS: membership in group `access_bpf`, installed with Wireshark's ChmodBPF; Linux: root or `CAP_NET_RAW` on tcpdump); nothing
else will work without it. Wireshark (`tshark`, `editcap`) is needed for secured protocols.

## 1. Describe your experiment

Make a directory for it, committed in git (a PASS requires that directory to be clean, so
the checker code that produced a verdict is pinned by its commit). Put the implementations
under it (subdirectories, or git-ignored checkouts) and write `interop.yaml`:

```yaml
experiment: my-protocol
env_checks:                        # host prerequisites; a failure gives ENV and nothing runs
  - name: tool
    command: mytool --version
peers:
  - name: server-a                 # one implementation
    path: impl-a                   # cwd for build/start/ready, inside the experiment dir
    family: openai                 # model family that wrote this code (or human)
    under_test: true
    build: make server             # binaries are deleted first, rebuilt, then SHA-256 hashed
    binaries: [server]
    start: ./server --port 5683
    ready: {command: "grep -q listening {bundle}/server-a.log", timeout_s: 15}
  - name: client-b                 # another implementation
    path: impl-b
    family: google
    under_test: true
    start: ./client --port 5683    # MUST exit 0 only if the exchange completed
capture: {interface: lo0, filter: udp port 5683}
cells:
  - {name: a-serves-b, server: server-a, clients: [client-b], checkers: [observes-exchange], timeout_s: 60}
checkers:
  - name: observes-exchange
    family: anthropic              # MUST differ from every under_test peer's family
    observes_capture: true
    command: python3 checkers/check.py {capture}
    inputs: []
    negatives:                     # captures the checker MUST reject, every run
      - {input: checkers/negatives/unrelated.pcap, replaces: "{capture}"}
      - {input: checkers/negatives/one_direction.pcap, replaces: "{capture}"}
```

Make `build` force a **clean** build (`make -B`, `cargo build` after `cargo clean`, ...): the
runner deletes the declared binaries, not intermediate objects, and a binary linked from stale
`.o` files is a hollow PASS (it happened to our first OSCORE bundle).

Commands are argv strings without a shell (no pipes or `&&`; use `env:` for variables).
Clients of a cell start together; if they must run in sequence, make one client peer a
small driver script (see `experiments/oscore-n1/clients_seq.py`). One cell per
(server, clients) pairing; run both directions as two cells.

## 2. Get an independent checker

Ask an agent of a **different model family** than every implementation under test to write
the checker from the draft and the wire only — not from either implementation's code.
Worked example: `experiments/oscore-n1/checkers/` (the prompt rules are in its README).

The checker prints one line per check with the draft section it enforces, and exits
non-zero on any failure. It needs at least two capture negatives: unrelated traffic, and the
exchange with one direction (or the essential message) removed. Build negatives from a real
capture with `editcap`/`tshark`. Then:

```sh
python3 -m wire validate-checkers my-experiment/interop.yaml   # OK: every checker rejects its negatives
```

"The server must refuse a bad token" is peer behaviour, not a checker negative: add a cell
with an adversarial client that exits 0 only if the refusal happened, and a checker that
asserts the refusal on the wire.

## 3. Run and read the verdict

```sh
git -C my-experiment status --short          # must be empty
python3 -m wire run my-experiment/interop.yaml --cell a-serves-b --out runs/wire/my-experiment/$(date -u +%Y%m%dT%H%M%SZ)
```

| Verdict | Exit | Meaning | What to do |
|---|---|---|---|
| PASS | 0 | peers exited 0, capture non-empty, every checker passed and rejected every negative | share the bundle |
| FAIL | 1 | a peer failed or timed out, a checker failed, or a checker accepted a negative | read `verdict.json` reason, then the peer and checker logs — this is a real finding |
| BLOCKED | 3 | experiment dir dirty, build failed or produced no binary, capture empty or impossible, secret file missing | fix the setup; not a protocol result |
| ENV | 4 | a declared env check failed; nothing ran | fix the host (route, tool, permission) |
| (2) | 2 | manifest error, checked before anything runs | fix `interop.yaml` |

ENV is only possible from a declared env check, so a protocol bug can never be relabelled
as "environment".

## 4. Secured protocols (TLS, DTLS, QUIC, mTLS, ...)

Peers export their session keys and the bundle gets a decrypted view next to the raw one:

```yaml
peers:
  - name: client-b
    env: {SSLKEYLOGFILE: "{secrets}/client.keys"}
    secrets: [client.keys]
decrypt:
  command: editcap -F pcapng --inject-secrets tls,{secrets}/client.keys {capture} {decrypted}
```

`capture-decrypted.pcapng` opens decrypted in Wireshark with no setup. A raw checker must
reject a cleartext capture of the same exchange (`asserts: encrypted`), and a decrypted
checker must reject both wrong keys and a substituted decrypted view. Template:
`wire/example/tls_echo/`. Key logging: Python `ssl.create_default_context()` honours
`SSLKEYLOGFILE`; Go needs `tls.Config.KeyLogWriter`; Node `--tls-keylog=<file>`;
OpenSSL `s_client/s_server -keylogfile`. OSCORE has no standard key log: peers dump their
security context and the experiment supplies its own decoder.

**Test keys only.** Bundles with secrets decrypt themselves; `verdict.json` says
`contains_secrets: true`.

## 5. Share

```sh
python3 -m wire verify-bundle <bundle>      # OK = files intact and listed in SHA256SUMS
```

Commit the bundle (or attach it to the Hackathon results) together with the experiment
commit. Reviewers re-run `verify-bundle`, open `capture.pcap` (or the decrypted view) in
Wireshark, and read `verdict.json`, `env.json` and `checker-*.log`.

## 6. Building an implementation with agents (optional)

To have AI agents build a feature without trusting their claims, use the orchestrator:
write a milestone spec with falsifiable acceptance criteria, have it reviewed by another
model family, approve it (`./orch approve-gate G2 <id>`), then
`./orch start-build` → builder agent → `./orch finish-build` → `./orch start-verify` →
verifier agent of another family → `./orch finish-verify` → `./orch integrate`. The
orchestrator runs every test itself and rejects a PASS whose tests cannot fail.
See `AGENTS.md` and DESIGN.md section 24.

## Candidate experiments

- CoAP multicast notifications / OSCORE (draft-ietf-core-observe-multicast-notifications): cell N1 done, `experiments/oscore-n1/`.
- ICMPv6-SEC.
- CORECONF / SCHC (draft-ietf-schc-8824-update).
- WIMSE / RICH workload-identity interop (candidate, under discussion).

## Known limits

Single host, one capture interface per cell, clients of a cell start together, commands
without a shell. A checker's model family is declared, not proven.
