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

ORCHESTRATOR FEEDBACK — your previous run (commit 757f3bc) was REJECTED by the mechanical gate
(runs/M01/01/757f3bc87e7e/gate.log in the main repository):
1. Ownership violation: acceptance/M01/test_m01_acceptance.py. acceptance/** belongs to the verifier.
   Remove it in a new commit. Move any tests you want to keep to tests/ (builder tests).
2. Ownership violation: milestones/M01/state.yaml. Restore it to exactly its content at the base
   commit (git checkout f8fdbbca7632527f93732f1ec0a9594dfeb9118a -- milestones/M01/state.yaml), and never
   write it from tests: tests must create their own temporary git repositories (tmp_path) and run ./orch there.
3. Your build.md reports gaps against milestones/M01/spec.yaml. The spec's interface section is the contract;
   close these or report them as PARTIAL:
   - every state.yaml/metrics change must be a git commit authored "orchestrator" (AC10);
   - finish-build <id> and finish-verify <id> take no extra arguments: the orchestrator knows the
     worktrees from state.yaml (spec interface);
   - run-tests --at base and --at mutant:<name> must really execute in a temporary worktree at the base
     commit / with acceptance/<id>/mutants/<name>.patch applied, and finish-verify must re-run the
     acceptance suite and every validity case itself (AC6);
   - integrate must merge, run all COMPLETE suites, and restore main on failure (AC9).
4. Builder tests: 4 tests do not exercise AC1–AC11. Add end-to-end tests that drive ./orch in a temporary
   repository through a full lifecycle and the negative cases.
Update milestones/M01/attempts/01/build.md, commit everything (clean worktree), then stop.
