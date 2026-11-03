ROLE: BUILDER — milestone M08, attempt 01, base commit 22f75ce8f7bf8f4e6f33f8e4da2ab01ca10eef4b
Worktree: .worktrees/M08-a01-build
Work and commit only in that worktree.
Read: AGENTS.md, DESIGN.md, milestones/M08/spec.yaml, and the code of COMPLETE dependencies.

Implement ONLY this milestone.
You may write: the source tree, your own tests under tests/, milestones/M08/attempts/01/build.md.
You may NOT write: acceptance/**, spec.yaml, state.yaml, or any other role's paths. Such changes are rejected.
Builder tests must pass with: python3 -m pytest -q -p no:cacheprovider tests
The orchestrator re-runs them itself; your own run is not evidence.
Write milestones/M08/attempts/01/build.md containing:
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
  - M01 is COMPLETE; its orchestrator.py is the dependency code to read. M08 is built through M01's manual
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
