ROLE: BUILDER — milestone M01, attempt 01, base commit 67a47956cef9548e56d82848be8fbfeae93b22de548e56d82848be8fbfeae93b22de
Worktree: .worktrees/M01-a01-build-corr
Work and commit only in that worktree.
Read: AGENTS.md, DESIGN.md, milestones/M01/spec.yaml, and the code of COMPLETE dependencies.

Implement ONLY this milestone.
You may write: the source tree, your own tests under tests/, milestones/M01/attempts/01/build.md.
You may NOT write: acceptance/**, spec.yaml, state.yaml, or any other role's paths. Such changes are rejected.
Builder tests must pass with: python3 -m pytest -q -p no:cacheprovider tests
The orchestrator re-runs them itself; your own run is not evidence.
Write milestones/M01/attempts/01/build.md containing:
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

CORRECTIVE RUN within attempt 01 (escalation E012, human decision approvals/G3-E012.md).
Previous runs of attempt 01 were rejected or incomplete (milestones/M01/state.yaml history). You start
fresh from the base commit above. That tree already contains an orchestrator written by hand outside
the milestone flow. Treat it as pre-existing code: reuse, change or replace it as needed. Its existing
tests are NOT evidence that any criterion holds.

Your target is the 11 APPROVED acceptance criteria in milestones/M01/spec.yaml (criteria_version
4846a491a8c1...), including its `interface` section. Known gaps, found by inspection only; confirm each one yourself:
  G1. Approved interface missing: start-build, finish-build, start-verify, finish-verify, integrate,
      invalidate, unblock, resolve, review, approve, refresh are replaced by generic transition/dispatch/verify.
      Provide the approved commands with the approved arguments. Existing commands may stay.
  G2. AC4: REVIEWED->APPROVED does not require approvals/G2-<id>.md naming the current spec hash;
      DRAFT->REVIEWED does not require a review file; `approve-gate` does not bind the spec hash and crashes
      with a ValueError traceback on a non-numeric G3/G4 target (it must fail cleanly, non-zero).
  G3. criteria_version: DESIGN 24.6 says sha256 of spec.yaml. compute_criteria_version hashes a normalized
      subset that omits `interface` and `size_hint`, so `./orch show M01` reports 40fc01815d36 while
      state.yaml holds 4846a491a8c1 (the file hash). A non-DRAFT spec whose hash differs from criteria_version
      is not detected (AC8).
  G4. AC9: there is no `integrate` command (merge + run acceptance of this and every COMPLETE milestone on the
      merge commit + restore main on failure + REWORK).
  G5. AC10/AC11: state must survive process exit and every state.yaml change must be a git commit authored
      "orchestrator" in the MAIN repository. Two concurrent finishes must not corrupt either state.yaml.
      Check DESIGN.md for where state lives. If the current external store contradicts DESIGN, follow DESIGN
      and report it under Design deviations / Unexpected findings. Do not invent architecture.
  G6. Test hermeticity: the current test suite writes into the real repository (runs/, metrics/M94.yaml,
      milestone dirs M90/M99, M00_DONE) and appends fake human_approval events to the real journal under
      ~/.local/state/ai2ii. Every test must use temporary repositories and state; after
      `python3 -m pytest -q -p no:cacheprovider tests` the worktree must show no changes (`git status --porcelain` empty).
      Your sandbox denies writes outside this worktree and the temp dirs, so non-hermetic tests will fail here.

Boundary rules (DESIGN.md 24.3, "Governing and subject orchestrator", E011):
  - You MAY edit orchestrator.py and src/. You may NOT edit `orch`, workflow.yaml, DESIGN.md, AGENTS.md,
    scripts/**, conftest.py, pytest.ini, pyproject.toml, acceptance/**, milestones/** (except your build.md).
  - The `orch` wrapper always executes MAIN's orchestrator.py, not yours. To test YOUR code, import it
    in-process or run `python3 <this worktree>/orchestrator.py ...` against a temporary repository. Never
    rely on `./orch` to exercise your changes.
  - Never run orchestrator state commands against the real repository.
  - acceptance/M01/ currently tests an older, weakened spec. It belongs to the verifier. If it conflicts with
    the approved criteria, report that in build.md; do not edit it. Builder tests (tests/) are the gate.

Also run `ruff check orchestrator.py tests src/_shims` and `ruff format --check orchestrator.py tests src/_shims`
before committing; both must pass.

ORCHESTRATOR FEEDBACK: your run (commit 61188176b12d) was REJECTED (runs/M01/01/61188176b12d/gate.log in the main
repository). You are continuing on the same branch and worktree; fix forward with new commits.

1. Builder tests FAILED in the orchestrator run (runs/M01/01/61188176b12d/build-corr.log): the orchestrator puts
   src/_shims first on PYTHONPATH, so "python3 -m pytest" is the stdlib shim in src/_shims/pytest.py, not real pytest.
   The shim loads each test file by path and does NOT add tests/ to sys.path, so "from flow_repo import ..." fails.
   It also has no fixtures (no tmp_path, monkeypatch, capsys) and limited parametrize support; read src/_shims/pytest.py.
   Make every builder test pass under BOTH: reproduce the gate with
       PYTHONPATH=src/_shims python3 -m pytest -q -p no:cacheprovider tests
   and also run it with real pytest. Do not edit src/_shims/pytest.py to get around this; your tests must adapt
   (for example, load the helper with importlib from Path(__file__).parent).
2. You deleted tests/test_e011_boundary.py. Those are the E011 regression tests required by G3-E011 and DESIGN.md 24.3
   rule 3; they may not be dropped. Restore equivalent coverage, adapted to your code, for at least:
   builder may change orchestrator.py; orch/workflow.yaml/DESIGN.md/AGENTS.md/scripts/conftest.py/pytest.ini/
   pyproject.toml/acceptance/spec.yaml are rejected; copy-back is the attempt record only (builder) and never code
   (verifier); ./orch from an attempt worktree executes MAIN's orchestrator.py (temp repo + worktree); every
   {orch} command in a rendered verifier prompt parses with your argument parser; only run logs under main's runs/
   are citable in a verdict; state commands refuse in the main worktree when it is off branch main.
3. Removed out-of-scope commands (audit, escalate, transition, verify) are noted in the gate log; keep them listed
   under Design deviations in build.md so the architect and human can decide. Do not restore them in this run.
Update build.md (same file) to describe this run, then commit; the worktree must be clean.
