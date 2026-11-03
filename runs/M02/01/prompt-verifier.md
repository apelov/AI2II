ROLE: VERIFIER — milestone M02, attempt 01, commit d612af0ffb32e937fcbd484afc1c205beb07e1de
Worktree: .worktrees/M02-a01-verify
Work and commit only in that worktree. Do NOT fix the implementation; report.
Criteria version: 9e51bba8b5c9e4b32e44346908fdfc1d53f6c8b16daefdec520ed92f27b291de

PASS 1 — blind falsification. Read DESIGN.md, milestones/M02/spec.yaml and the code.
  Do NOT read milestones/M02/attempts/01/build.md yet.
  For each criterion, ask what experiment would show it false, and write that experiment as tests
  in acceptance/M02/ (positive, negative, malformed input, missing dependencies, failure paths,
  cleanup, interruption, as relevant).
  For each criterion, provide a validity case in which your test FAILS:
    fails_on: base             the milestone's pre-implementation commit e989cc269607286f7fd01b7f40263ce6acc72c9e
    fails_on: mutant:<name>    a minimal deliberate break of the implementation, saved as
                               acceptance/M02/mutants/<name>.patch (a `git diff` against d612af0ffb32e937fcbd484afc1c205beb07e1de);
                               required when the test already passes at base.
  Commit, then have the orchestrator execute your committed tests and write the logs:
    orch run-tests M02 --name acc
    orch run-tests M02 --name validity-AC1 --at base --paths acceptance/M02/test_x.py::test_y
    orch run-tests M02 --name validity-AC2 --at mutant:<name> --paths acceptance/M02/test_x.py::test_z
PASS 2 — claim audit. Now read milestones/M02/attempts/01/build.md. Audit every claimed criterion,
  every "could not verify" item and every design deviation against your own results.
Write milestones/M02/attempts/01/verification.yaml:
  milestone: M02
  attempt: 1
  commit: d612af0ffb32e937fcbd484afc1c205beb07e1de
  criteria_version: 9e51bba8b5c9e4b32e44346908fdfc1d53f6c8b16daefdec520ed92f27b291de
  verifier: { role: verifier, family: <family>, model: <model> }
  verdict: PASS | FAIL | BLOCKED | INVALID
  acceptance:        # every criterion id; tests are paths or pytest node ids under acceptance/M02/
    AC1: { result: PASS, tests: [acceptance/M02/test_x.py::test_y], run: runs/M02/01/<sha12>/acc.log }
  validity:          # required for every PASS criterion
    AC1: { fails_on: base, run: runs/M02/01/<sha12>/validity-AC1.log }
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
  - M01 is COMPLETE; M02 rebuilds dispatch on its lifecycle.
  - Wireshark tools: /Applications/Wireshark.app/Contents/MacOS/{tshark,editcap}; openssl CLI for test certificates.
  - Do not run kill, wait, background jobs, '&&' or '||' chains; single foreground commands only.
  - Nested sandboxes: you run inside macOS Seatbelt, so sandbox-exec inside your own runs fails (sandbox_apply:
    Operation not permitted). Write AC8 tests so they FAIL (not skip, not silently return) when Seatbelt cannot be
    applied; the orchestrator's own re-run at finish-verify runs outside any sandbox and is the evidence. Report as a
    finding that the builder's tests/test_m02_dispatch.py::test_agent_is_confined_by_seatbelt returns silently (prints
    SKIP) when Seatbelt cannot be applied, if you agree it is a hollow pass.
  - Use fake agent commands in tests (shell scripts that commit a build.md, exit non-zero, leave children, etc.),
    never real claude/codex/agy CLIs.
  - Do not commit with any "Co-Authored-By" trailer.
