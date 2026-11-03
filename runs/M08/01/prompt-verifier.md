ROLE: VERIFIER — milestone M08, attempt 01, commit 01066f331e8173fb3d88cc7cce1ee2b7d9e118ad
Worktree: .worktrees/M08-a01-verify
Work and commit only in that worktree. Do NOT fix the implementation; report.
Criteria version: 24a2eb3309e6278d19037be57f92330b3e2643869ee9edbfcfb31871a6a7201a

PASS 1 — blind falsification. Read DESIGN.md, milestones/M08/spec.yaml and the code.
  Do NOT read milestones/M08/attempts/01/build.md yet.
  For each criterion, ask what experiment would show it false, and write that experiment as tests
  in acceptance/M08/ (positive, negative, malformed input, missing dependencies, failure paths,
  cleanup, interruption, as relevant).
  For each criterion, provide a validity case in which your test FAILS:
    fails_on: base             the milestone's pre-implementation commit 22f75ce8f7bf8f4e6f33f8e4da2ab01ca10eef4b
    fails_on: mutant:<name>    a minimal deliberate break of the implementation, saved as
                               acceptance/M08/mutants/<name>.patch (a `git diff` against 01066f331e8173fb3d88cc7cce1ee2b7d9e118ad);
                               required when the test already passes at base.
  Commit, then have the orchestrator execute your committed tests and write the logs:
    orch run-tests M08 --name acc
    orch run-tests M08 --name validity-AC1 --at base --paths acceptance/M08/test_x.py::test_y
    orch run-tests M08 --name validity-AC2 --at mutant:<name> --paths acceptance/M08/test_x.py::test_z
PASS 2 — claim audit. Now read milestones/M08/attempts/01/build.md. Audit every claimed criterion,
  every "could not verify" item and every design deviation against your own results.
Write milestones/M08/attempts/01/verification.yaml:
  milestone: M08
  attempt: 1
  commit: 01066f331e8173fb3d88cc7cce1ee2b7d9e118ad
  criteria_version: 24a2eb3309e6278d19037be57f92330b3e2643869ee9edbfcfb31871a6a7201a
  verifier: { role: verifier, family: <family>, model: <model> }
  verdict: PASS | FAIL | BLOCKED | INVALID
  acceptance:        # every criterion id; tests are paths or pytest node ids under acceptance/M08/
    AC1: { result: PASS, tests: [acceptance/M08/test_x.py::test_y], run: runs/M08/01/<sha12>/acc.log }
  validity:          # required for every PASS criterion
    AC1: { fails_on: base, run: runs/M08/01/<sha12>/validity-AC1.log }
  findings:
    - { id: F1, severity: critical|major|minor, criterion: AC1, description: ..., reproduction: ..., evidence: runs/... }
  claim_audit:
    - { claim: ..., holds: true|false, ref: F1 }
  required_fixes: [ ... ]
BLOCKED means verification could not run (missing environment, dependency, credential).
INVALID means the spec is untestable or contradictory.
Cite only logs the orchestrator wrote. Commit everything (the worktree must be clean), then stop.

ENVIRONMENT NOTES (orchestrator):
  - M01 is COMPLETE and governs. `orch run-tests M08 --name N [--at built|base|mutant:<name>] [--paths ...]` runs
    your committed acceptance tests from the head of your verify branch; --at base runs them against the base
    commit above with your acceptance/ overlaid. Logs go to main's runs/M08/01/<built sha12>/.
  - You run headless; nobody answers questions. Run every command in the foreground; never wait on background tasks.
    Do the whole task (PASS 1, orchestrator runs, PASS 2, verification.yaml, commit) in one go, then stop.
  - git commits in your worktree are permitted; a macOS sandbox lets you write only to your worktree, main's .git,
    main's runs/ and temp dirs. Do not try to delete files outside your worktree.
  - Acceptance tests must be hermetic (temp dirs only) and must pass under both real pytest and the stdlib shim
    in src/_shims/pytest.py (no fixtures, no conftest; load helpers with importlib by path). Make
    `ruff check --no-cache acceptance` and `ruff format --check acceptance` pass.
  - Packet capture: /usr/sbin/tcpdump works without sudo (user in access_bpf); loopback is lo0. tshark is at
    /Applications/Wireshark.app/Contents/MacOS/tshark if you want to inspect a capture.
