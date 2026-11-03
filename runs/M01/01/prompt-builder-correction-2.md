ROLE: BUILDER — milestone M01, attempt 01, base commit f8fdbbca7632527f93732f1ec0a9594dfeb9118a
Worktree: .worktrees/M01-a01-build
Work and commit only in that worktree.
Read: AGENTS.md, DESIGN.md, milestones/M01/spec.yaml, and the code of COMPLETE dependencies.
Previous attempts: none (first attempt).
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

ORCHESTRATOR FEEDBACK — your corrective run (commit b7d0b54) was REJECTED again
(runs/M01/01/b7d0b54680a2/gate.log in the main repository). Fix forward on this branch.

1. Ownership violation: milestones/M01/state.yaml exists on this branch but not at the base commit.
   Remove it: `git rm milestones/M01/state.yaml` and commit. The base..HEAD diff must not touch it.
2. Root cause, which you must fix in the code:
   - ./orch writes and commits state into the worktree it is invoked from. It must locate the MAIN
     repository (`git rev-parse --path-format=absolute --git-common-dir`, then its parent directory)
     and write state.yaml, metrics/, runs/ and their commits there, with the main worktree on branch
     `main`, whatever worktree ./orch is invoked from.
   - Your tests ran ./orch against this real repository and created ~30 "orchestrator: update M01
     state" commits on this branch. Running them again in the gate added 3 more. Tests must be hermetic:
     every test creates its own temporary git repository (pytest tmp_path, `git init -b main`, copies
     workflow.yaml and AGENTS.md, defines a dummy milestone such as M00) and runs ./orch there.
     After `python3 -m pytest -q -p no:cacheprovider tests`, `git status` and `git log` of THIS repository
     must be unchanged. Check that yourself before committing.
   - Never run ./orch in this repository.
3. build.md lists AC6, AC7, AC9 and dependency-STALE propagation as not verified end to end. With a dummy
   milestone in a temporary repository you can drive the full lifecycle (review, approve, start-build,
   finish-build, start-verify, run-tests --at base / --at mutant:<name>, finish-verify, integrate) and the
   negative cases (FAIL -> REWORK -> ESCALATED at max_attempts, integration failure restoring main,
   invalidate -> dependents STALE). Add those builder tests.
Update milestones/M01/attempts/01/build.md, commit everything (clean worktree), then stop.
