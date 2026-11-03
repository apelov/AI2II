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
