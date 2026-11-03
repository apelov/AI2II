# Build report

- Milestone: M09
- Attempt: 01
- Base commit: c74bd65407b80908a4d5b4d3d19749decf372975
- Status: COMPLETE

## Files added / modified

Modified: `wire/bundle.py` (layout constants), `wire/manifest.py` (peer `env`/`secrets`, experiment `decrypt`,
checker `observes_decrypted`, negative `asserts`, placeholders `{secrets}`/`{decrypted}`, all AC6 validation),
`wire/proc.py` (per-child env), `wire/checkers.py` (secrets/decrypted negatives, scratch decrypt re-run),
`wire/run.py` (secrets dir, secret check, decrypt step, env.json decrypt record, `contains_secrets`).

Added: `wire/decrypt.py` (runs the experiment's decrypt command, resolves its executable);
`wire/example/tls_echo/` (manifest, TLS echo server/client, test certificate, checkers, negatives, vectors);
`tests/test_wire_secured.py`.

## Tests added

`tests/test_wire_secured.py`: `test_tls_example_passes_with_both_views`,
`test_missing_or_empty_secret_is_blocked_and_nothing_downstream_runs`, `test_symlinked_secret_is_blocked`,
`test_decrypt_failures_fail_the_cell_and_keep_the_capture`, `test_decrypted_checker_mutants_are_rejected`,
`test_raw_capture_checker_accepting_cleartext_fails`, `test_scratch_decrypt_never_modifies_the_canonical_view`,
`test_decrypt_executable_hash_follows_the_executable`, `test_manifest_validation_exits_2_before_anything_runs`,
`test_wire_source_has_no_protocol_knowledge`.

## Acceptance criteria believed satisfied

- AC1: test_tls_example_passes_with_both_views
- AC2: test_missing_or_empty_secret_is_blocked_and_nothing_downstream_runs
- AC3: test_decrypt_failures_fail_the_cell_and_keep_the_capture
- AC4: test_decrypted_checker_mutants_are_rejected, test_scratch_decrypt_never_modifies_the_canonical_view
  (the example's own altered-keys and other-payload negatives run in every PASS)
- AC5: test_raw_capture_checker_accepting_cleartext_fails (and the example's `asserts: encrypted` negative)
- AC6: test_manifest_validation_exits_2_before_anything_runs (19 cases)
- AC7: partly, in test_tls_example_passes_with_both_views (per-peer env in env.json, distinct values, bundle path)
- AC8: test_symlinked_secret_is_blocked, test_decrypt_executable_hash_follows_the_executable, tamper cases in the PASS test
- AC9: existing tests/test_wire.py unchanged and passing; M08 acceptance suite not run by me (acceptance/** is not mine)
- AC10: test_wire_source_has_no_protocol_knowledge

## Could NOT verify

- That peers' env is absent from other peers' processes beyond inspection of `proc.spawn` (env is passed per
  child, never put in the runner's own environment); no test spawns a peer that dumps its environment.
- The M08 acceptance suite (acceptance/M08) was not run by me.
- Behaviour on Linux (`lo`); only macOS `lo0` was exercised.

## Known limitations

- The decrypt executable is hashed when the decrypt step runs; a cell that stops earlier has no `decrypt` record in env.json.
- If the scratch decrypt re-run for a wrong-secrets negative fails, the checker still runs on whatever it left
  (usually nothing), which counts as rejection.
- `validate-checkers` skips observes_decrypted checkers (no peers, so no decrypted view).
- An `observes_decrypted` checker, or any use of `{decrypted}`, in an experiment with no `decrypt` is a manifest error.
- The `asserts: encrypted` requirement applies to every observes_capture checker of a cell in an experiment with `decrypt`.
- `{secrets}`/`{decrypted}` are expanded in every manifest command, not only where DESIGN lists them.
- The example commits a throwaway private key (`src/test_key.pem`), by the test-keys-only rule.

## Design deviations

None.

## Unexpected findings

- tshark exposes the decrypted bytes as `data.data` (the `tls.app_data` field keeps the ciphertext), so the
  example checker reads `data.data` on frames that have `tls.app_data`.
- DESIGN 24.21 does not say whether an undeclared-but-written file in `secrets/` blocks; it only makes
  `contains_secrets` true and puts the file in SHA256SUMS.
