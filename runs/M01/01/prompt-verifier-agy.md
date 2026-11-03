ROLE: VERIFIER — milestone M01, attempt 01, commit ebfa283626c0a8de170846b17cb123a69c901190
Worktree: .worktrees/M01-a01-verify
Work and commit only in that worktree. Do NOT fix the implementation; report.
Criteria version: 4846a491a8c1a23c5fe97c1ddab33f679d585817b7139ed05be76c1538c6a222

PASS 1 — blind falsification. Read DESIGN.md, milestones/M01/spec.yaml and the code.
  Do NOT read milestones/M01/attempts/01/build.md yet.
  For each criterion, ask what experiment would show it false, and write that experiment as tests
  in acceptance/M01/ (positive, negative, malformed input, missing dependencies, failure paths,
  cleanup, interruption, as relevant).
  For each criterion, provide a validity case in which your test FAILS:
    fails_on: base             (run it with --at <that sha>) the milestone's pre-implementation commit 67a47956cef9548e56d82848be8fbfeae93b22de
    fails_on: mutant:<name>    a minimal deliberate break of the implementation, saved as
                               acceptance/M01/mutants/<name>.patch (a `git diff` against ebfa283626c0a8de170846b17cb123a69c901190);
                               required when the test already passes at base.
  Commit, then have the orchestrator execute your committed tests and write the logs:
    orch run-tests M01 --name acc
    orch run-tests M01 --name validity-AC1 --at 67a47956cef9548e56d82848be8fbfeae93b22de --paths acceptance/M01/test_x.py::test_y
    orch run-tests M01 --name validity-AC2 --at mutant:<name> --paths acceptance/M01/test_x.py::test_z
PASS 2 — claim audit. Now read milestones/M01/attempts/01/build.md. Audit every claimed criterion,
  every "could not verify" item and every design deviation against your own results.
Write milestones/M01/attempts/01/verification.yaml:
  milestone: M01
  attempt: 1
  commit: ebfa283626c0a8de170846b17cb123a69c901190
  criteria_version: 4846a491a8c1a23c5fe97c1ddab33f679d585817b7139ed05be76c1538c6a222
  verifier: { role: verifier, family: <family>, model: <model> }
  verdict: PASS | FAIL | BLOCKED | INVALID
  acceptance:        # every criterion id; tests are paths or pytest node ids under acceptance/M01/
    AC1: { result: PASS, tests: [acceptance/M01/test_x.py::test_y], run: runs/M01/01/<sha12>/acc.log }
  validity:          # required for every PASS criterion
    AC1: { fails_on: base, run: runs/M01/01/<sha12>/validity-AC1.log }
  findings:
    - { id: F1, severity: critical|major|minor, criterion: AC1, description: ..., reproduction: ..., evidence: runs/... }
  claim_audit:
    - { claim: ..., holds: true|false, ref: F1 }
  required_fixes: [ ... ]
BLOCKED means verification could not run (missing environment, dependency, credential).
INVALID means the spec is untestable or contradictory.
Cite only logs the orchestrator wrote. Commit everything (the worktree must be clean), then stop.

BOOTSTRAP NOTES (escalation E012, approvals/G3-E012.md; read before starting):
  - The governing ./orch (the absolute path above) is MAIN's pre-attempt orchestrator, not the code under test
    (E012 point 5, accepted for bootstrap). It executes your committed acceptance tests against your worktree's
    HEAD (the implementation plus your tests) and writes logs under main's runs/. Its own `show M01` hash
    (40fc01815d36) is a known defect; the approved criteria_version is the full sha256 above.
  - For "fails_on: base", run with --at <the base sha above> explicitly; do not use the word "base"
    (main's orchestrator would resolve it to the wrong commit).
  - The existing acceptance/M01/ was written against an older, weakened spec that is NOT approved. Judge it
    against the APPROVED 11 criteria in milestones/M01/spec.yaml; replace or delete what does not fit.
  - Exercise the implementation in-process or as `python3 <worktree>/orchestrator.py ...` against temporary
    repositories. Never run state commands against the real repository. The `orch` wrapper always runs main's code.
  - Acceptance tests must be hermetic (temporary repos and state, nothing written to the real tree) and must run
    under both real pytest and the stdlib shim in src/_shims/pytest.py (no fixtures, no conftest).
  - You run headless; nobody will answer questions. Do the whole task in one go and stop.
  - git commits in your worktree are permitted (an external macOS sandbox lets you write only to your worktree,
    main's .git, main's runs/ and temp dirs).
  - Real pytest is at /opt/anaconda3/bin/python3 -m pytest; the orchestrator's own runs are the evidence.
