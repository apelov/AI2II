# M08 attempt 01 build report

- Milestone: M08
- Attempt: 01
- Base commit: 22f75ce8f7bf8f4e6f33f8e4da2ab01ca10eef4b
- Status: COMPLETE

## Files added / modified
- Added `wire/` (`__init__`, `__main__` CLI, `manifest`, `run`, `checkers`, `capture`, `proc`, `bundle`).
- Added the example experiment `wire/example/udp_echo/` (`interop.yaml`, UDP echo server and client, `build.py`,
  `ready.py`, `check_capture.py` (observes_capture), `check_vector.py`, stdlib pcap reader `udp_pcap.py`,
  `make_negatives.py`, committed `negatives/*.pcap` and `vectors/*.bin`). The example's server and client listen
  and send on port 47321; tests copy it, change the port and regenerate the negatives.
- Modified `orchestrator.py`: removed `cmd_interop`, `run_interop_test`, `generate_interop_report`,
  `build_interop_matrix`, the `interop` subparser and dispatch entry, and the helpers only they used
  (`discover_implementations`, `detect_language`, `detect_test_command`).
- Added `tests/test_wire.py`.

## Tests added
`tests/test_wire.py`: example PASS and bundle layout, verify-bundle mutations, validate-checkers (real and
accept-all checker), manifest validation (11 cases, checks nothing ran), mute server, hanging peer with child,
SIGINT, ENV (second check failing, build marker), BLOCKED (stale binary + failing build, missing binary, bad
interface, zero packets, dirty experiment), accepting checkers (observes_capture, vector, failing checker),
`orch interop` removal and the AST import walk.
Capture tests skip themselves if the loopback interface is not capturable.

## Acceptance criteria believed satisfied
- AC1: test_example_pass_and_bundle_integrity
- AC2: test_validate_checkers
- AC3: test_example_pass_and_bundle_integrity (broken(...) cases)
- AC4: test_server_that_never_answers_fails, test_hanging_peer_with_child_is_killed_within_timeout,
  test_sigint_yields_interrupted_and_leaves_nothing
- AC5: test_env_check_failure_is_env_and_nothing_runs
- AC6: test_blocked_cases
- AC7: test_checkers_that_accept_negatives_fail_the_cell (the two-cell case is not tested by me)
- AC8: test_manifest_validation_exits_2_before_anything_runs (most listed cases; not duplicate cell/checker names,
  missing family on a checker, missing server)
- AC9: test_example_pass_and_bundle_integrity (hashes, commit, dirty), test_blocked_cases (dirty)
- AC10: test_example_pass_and_bundle_integrity (inputs/ copied and listed), test_checkers_that_accept_negatives_fail_the_cell
- AC11: test_orch_interop_removed_and_no_cross_imports

## Could NOT verify
- Behaviour on Linux (`lo` interface, DLT_EN10MB captures): code handles the linktype in the example checker but
  only macOS was exercised.
- Running as a user that cannot capture: the capture tests skip; the BLOCKED path is covered only through a
  nonexistent interface.
- The two-cell "cell B never PASS" scenario of AC7 end to end.

## Known limitations
- `validate-checkers` runs only the negatives that replace `{capture}`. Negatives that replace an input need a
  real capture and are run by every `wire run` (DESIGN 24.20 step 9) instead.
- A checker that fails its normal run skips its negatives (the cell is FAIL anyway).
- Checkers are skipped when a peer failed or the capture is empty; no checker logs exist for such bundles.
- Verdict precedence: interrupted > peer failure/timeout (FAIL) > empty capture (BLOCKED) > checkers. So a peer
  that fails and also records no packets is FAIL, not BLOCKED.
- The experiment directory must be clean in git, so the `--out` directory must not be inside it, and build
  outputs inside it must be git-ignored (the example ignores `bin/`). Children run with
  PYTHONDONTWRITEBYTECODE=1 for the same reason.
- Zero packets are detected from tcpdump's "N packets captured" line, not by reading the pcap.
- Only the cell's own peers' binaries are deleted and rebuilt.
- A server stopped by the runner records its real exit code (e.g. -15); only a server that exits non-zero by
  itself before the stop is a failure.
- The bundle directory must not exist or must be empty (else exit 2).
- `verify-bundle` treats a missing `verdict.json` or one not listed in SHA256SUMS as not ok.

## Design deviations
None intended. Extras beyond DESIGN 24.20's bundle list: `capture.log` (tcpdump stderr), `build/<peer>.log`,
`envcheck/<name>.log`, and `capture_pid`/`capture_packets` in env.json. Command placeholders are also expanded in
peer and env-check commands (`{bundle}` is used by the example's ready command).

## Unexpected findings
- The sandbox forbids `ps`, so tests check process liveness by pid.
- Running a checker with cwd in the experiment directory wrote `__pycache__` there and made it dirty, hence
  PYTHONDONTWRITEBYTECODE for all children.
