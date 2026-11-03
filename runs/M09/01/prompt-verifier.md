ROLE: VERIFIER — milestone M09, attempt 01, commit 49adba644d071c1795cb800c136cf196af57d240
Worktree: .worktrees/M09-a01-verify
Work and commit only in that worktree. Do NOT fix the implementation; report.
Criteria version: 680a0eb1f0ff1fa94aae4bfcb780e246083e65c1cd50ca4d20a3876afe1eb73d

PASS 1 — blind falsification. Read DESIGN.md, milestones/M09/spec.yaml and the code.
  Do NOT read milestones/M09/attempts/01/build.md yet.
  For each criterion, ask what experiment would show it false, and write that experiment as tests
  in acceptance/M09/ (positive, negative, malformed input, missing dependencies, failure paths,
  cleanup, interruption, as relevant).
  For each criterion, provide a validity case in which your test FAILS:
    fails_on: base             the milestone's pre-implementation commit c74bd65407b80908a4d5b4d3d19749decf372975
    fails_on: mutant:<name>    a minimal deliberate break of the implementation, saved as
                               acceptance/M09/mutants/<name>.patch (a `git diff` against 49adba644d071c1795cb800c136cf196af57d240);
                               required when the test already passes at base.
  Commit, then have the orchestrator execute your committed tests and write the logs:
    orch run-tests M09 --name acc
    orch run-tests M09 --name validity-AC1 --at base --paths acceptance/M09/test_x.py::test_y
    orch run-tests M09 --name validity-AC2 --at mutant:<name> --paths acceptance/M09/test_x.py::test_z
PASS 2 — claim audit. Now read milestones/M09/attempts/01/build.md. Audit every claimed criterion,
  every "could not verify" item and every design deviation against your own results.
Write milestones/M09/attempts/01/verification.yaml:
  milestone: M09
  attempt: 1
  commit: 49adba644d071c1795cb800c136cf196af57d240
  criteria_version: 680a0eb1f0ff1fa94aae4bfcb780e246083e65c1cd50ca4d20a3876afe1eb73d
  verifier: { role: verifier, family: <family>, model: <model> }
  verdict: PASS | FAIL | BLOCKED | INVALID
  acceptance:        # every criterion id; tests are paths or pytest node ids under acceptance/M09/
    AC1: { result: PASS, tests: [acceptance/M09/test_x.py::test_y], run: runs/M09/01/<sha12>/acc.log }
  validity:          # required for every PASS criterion
    AC1: { fails_on: base, run: runs/M09/01/<sha12>/validity-AC1.log }
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
  - M08 (wire/) is COMPLETE; M09 extends it. AC9 requires the M08 acceptance suite to pass unchanged: include it.
  - Wireshark tools: /Applications/Wireshark.app/Contents/MacOS/{tshark,editcap}; openssl CLI for test certificates.
  - Do not run kill, wait, background jobs, '&&' or '||' chains; single foreground commands only.
