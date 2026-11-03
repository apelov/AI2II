ROLE: BUILDER — milestone M09, attempt 01, base commit c74bd65407b80908a4d5b4d3d19749decf372975
Worktree: .worktrees/M09-a01-build
Work and commit only in that worktree.
Read: AGENTS.md, DESIGN.md, milestones/M09/spec.yaml, and the code of COMPLETE dependencies.

Implement ONLY this milestone.
You may write: the source tree, your own tests under tests/, milestones/M09/attempts/01/build.md.
You may NOT write: acceptance/**, spec.yaml, state.yaml, or any other role's paths. Such changes are rejected.
Builder tests must pass with: python3 -m pytest -q -p no:cacheprovider tests
The orchestrator re-runs them itself; your own run is not evidence.
Write milestones/M09/attempts/01/build.md containing:
  Milestone / Attempt / Base commit / Status: COMPLETE | PARTIAL
  Files added / modified
  Tests added
  Acceptance criteria believed satisfied (by id, with test names)
  Could NOT verify (and why)
  Known limitations
  Design deviations (each requires architect sign-off before VERIFIED)
  Unexpected findings
If you believe a criterion or acceptance test is wrong, say so in build.md; do not edit it.
Commit all work (the worktree must be clean), then stop.
ENVIRONMENT NOTES (orchestrator):
  - M01 is COMPLETE; its orchestrator.py is the dependency code to read. M09 is built through M01's manual
    lifecycle: when you are done, the orchestrator runs `finish-build M08`, which checks ownership against the
    base commit, requires your committed build.md, and re-runs the builder tests itself.
  - The orchestrator runs builder tests with src/_shims first on PYTHONPATH, so `python3 -m pytest` is the stdlib
    shim in src/_shims/pytest.py (no fixtures, no conftest, test dir not on sys.path). Reproduce the gate with
        PYTHONPATH=src/_shims python3 -m pytest -q -p no:cacheprovider tests
    and also run real pytest. Both must pass. Do not edit src/_shims/pytest.py.
  - Tests must be hermetic: temp dirs only; `git status --porcelain` empty after the run.
  - Packet capture: /usr/sbin/tcpdump works without sudo here (user is in access_bpf); loopback is lo0.
    tshark is at /Applications/Wireshark.app/Contents/MacOS/tshark but wire/ itself must not parse pcaps
    (DESIGN 24.20); example checkers may be stdlib Python reading pcap bytes.
  - You run inside a macOS sandbox that only permits writes to this worktree and temp dirs.
  - Run `ruff check` and `ruff format --check` on orchestrator.py, wire, tests and src/_shims before committing.
  - M08 (wire/) is COMPLETE: read wire/ and acceptance/M08/ first; M09 extends it. The M08 acceptance suite must
    keep passing unchanged (AC9).
  - Wireshark 4.6.9 tools: /Applications/Wireshark.app/Contents/MacOS/{tshark,editcap}. They may appear only in the
    example experiment, never in wire/ itself (AC10). The example's env checks must require them.
  - Python ssl: SSLKEYLOGFILE is honoured by ssl.create_default_context(); a bare SSLContext(PROTOCOL_TLS_SERVER) does
    not log keys unless keylog_filename is set. openssl CLI is available for a self-signed test certificate.
