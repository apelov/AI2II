ORCHESTRATOR REVIEW of your PASS (verification.yaml at 277c58f/7f928ee). Fix up before finish-verify; same role,
worktree and rules. Do NOT change the implementation; only acceptance/M02/** and verification.yaml. Foreground
commands only. No "Co-Authored-By" trailers.

1. AC8 is not falsified: test_ac8_seatbelt_profile_and_confinement only inspects the profile text. AC8 claims writes
   into main's working tree, .git/hooks, .git/config and an unrelated /private/tmp path each FAIL, and that main is
   unchanged. Add a live test: dispatch a fake builder agent (a shell script) that attempts each of those writes plus a
   write inside its worktree and its declared state dir, records the outcome in its committed build.md, and assert the
   outcomes and that main is unchanged. When Seatbelt cannot be applied (your own sandbox), the test must FAIL, never
   skip or return. Your own run of it will fail inside your sandbox; that is expected. The orchestrator's re-run at
   finish-verify runs outside any sandbox and is the evidence; say so in verification.yaml.
2. Validity is "fails_on: base" for every criterion; at base the M02 dispatch rework does not exist, so that says
   nothing about whether your tests catch a broken M02. Add minimal mutants of the implementation (git diff against
   the built commit, saved under acceptance/M02/mutants/) under which your test FAILS, and switch validity to them,
   at least for:
     AC2  dispatch copies a changed source file or build.md into main.
     AC3  an agent that exits 0 without a committed record is reported as success.
     AC5  (a) the process group is not killed after a SUCCESSFUL candidate; (b) the worktree is not reset to base
          between candidates (see _kill_group / killpg near orchestrator.py:142-209).
     AC6  dispatch with no candidate configured still calls start-build (state changes).
     AC7  after fallback, state.yaml keeps the FIRST (failed) candidate's identity.
     AC8  the agent runs without sandbox-exec (or the profile allows main's working tree).
     AC10 builder dispatch accepted from BUILDING.
   Keep base validity only where no meaningful mutant exists, and say why.
Commit, have the governing orch run acc and each changed validity case (--at mutant:<name>), update verification.yaml
(cite the new logs; record anything you could not falsify as a finding), commit, leave the worktree clean, then stop.
