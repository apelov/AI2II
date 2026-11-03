ORCHESTRATOR REVIEW of your PASS (verification.yaml at ac41152). Fix up before finish-verify; same role, worktree and
rules. Do NOT change the implementation; only acceptance/M09/** and verification.yaml. Foreground commands only.

Validity for AC1-AC8 is "fails_on: base", but at base the M09 features do not exist, so those runs fail for a trivial
reason and say nothing about whether your tests detect a broken M09 runner. For the security-relevant criteria, add
minimal mutants of the implementation (git diff against the built commit, saved under acceptance/M09/mutants/) under
which your test FAILS, and switch validity to them:
  AC2: check_secrets (wire/run.py:190) accepts a missing/empty/symlinked secret.
  AC3: a failed or empty decrypt step is not turned into FAIL.
  AC4: the runner skips (a) the "{secrets}/<file>" negatives' scratch decrypt re-run, and separately (b) the
       "{decrypted}" replacement negatives (see accepted_negatives, wire/checkers.py:47). One mutant per hole.
  AC5: the "asserts: encrypted" negative is not run.
  AC6: manifest validation accepts a traversing secret name (e.g. ../capture.pcap).
  AC8: env.json does not record the decrypt executable hash, or contains_secrets is always false.
Keep base validity for AC1 and AC7 if no meaningful mutant exists, and say so. Commit, have the governing orch run
acc and every validity case you changed (use --at mutant:<name>), update verification.yaml (cite the new logs; record
honestly anything you could not falsify as a finding), commit, leave the worktree clean, then stop.
