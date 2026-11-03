ORCHESTRATOR REVIEW of your PASS (runs/M01/01/bf7f92fe64d5/gate.log in the main repo). Human decision: fix up
before VERIFIED. You stay in the same role, worktree and rules as your original prompt. Do NOT change the
implementation (orchestrator.py, tests/, src/); only acceptance/M01/** and verification.yaml. Run every command
in the foreground; never wait on background tasks.
1. acceptance/M01/test_m01.py fails `ruff check --no-cache acceptance` (F841 unused `h`, line 388) and
   `ruff format --check acceptance`. Make both pass (ruff format acceptance/M01 is fine).
2. AC11 validity is weak: mutant ac11_corrupt_state injects a corrupt write instead of breaking the concurrency
   protection. Replace it with a minimal mutant that removes the serialisation (e.g. make _repo_lock and/or
   the state-file lock at orchestrator.py:2023/2105 a no-op), and make the AC11 test strong enough to fail under
   that mutant (for example more concurrent finishes, or interleaving that loses an update). If no test you can
   write fails under a lock-removal mutant, say so as a finding instead of keeping the contrived mutant.
3. AC9 validity covers only the REWORK status. Add an assertion that main is restored to its pre-merge commit
   after a failed integration, and a mutant that skips the restore (see cmd_integrate, orchestrator.py:3037-3098),
   under which the test fails.
4. Commit, then have the governing orch (absolute path in the original prompt) re-run: acc, validity-AC9 and
   validity-AC11 (with your new mutants). Update verification.yaml (cite the new logs; record any findings
   honestly, including anything you could not falsify) and commit. The worktree must be clean. Then stop.
