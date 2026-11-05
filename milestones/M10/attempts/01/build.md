# M10 attempt 01 build report

Milestone: M10
Attempt: 01
Base commit: 5ef02fae38681e3fc17d86cbb66bf288a31cdcc6
Status: COMPLETE

## Files added / modified
- added: wire/summarize.py, tests/test_wire_m10.py
- modified: wire/capture.py (resolve_interface), wire/run.py (resolve before any build/peer; env.json key capture_interface; checkers run on non-empty capture after peer failure), wire/__main__.py (summarize), wire/example/udp_echo (loopback, echo-broken cell, server --corrupt), wire/example/tls_echo/interop.yaml (loopback), tests/test_wire.py and tests/test_wire_secured.py (copy only git-tracked files; map loopback to platform interface)

## Tests added
tests/test_wire_m10.py: test_loopback_resolves_and_echo_passes, test_unresolvable_loopback_is_blocked_before_any_peer, test_broken_echo_fails_with_checker_log, test_summarize, test_summarize_flags_edited_verdict.

## Acceptance criteria believed satisfied
- AC1 (macOS lo0 resolved, echo PASS): test_loopback_resolves_and_echo_passes
- AC3: test_unresolvable_loopback_is_blocked_before_any_peer (simulated by patching platform.system)
- AC4: test_broken_echo_fails_with_checker_log
- AC5: test_summarize, test_summarize_flags_edited_verdict
- AC6: copy_tracked in tests/test_wire.py and test_wire_secured.py
- AC7: acceptance/M08 and M09 pass locally (21 passed)
- AC2: by construction (Linux maps to lo; a hardcoded lo0 fails at tcpdump start with a message naming the interface -> BLOCKED); not run

## Could NOT verify
- AC2: no Linux container available in this sandbox.
- The unit run showed one pre-existing SKIP line (Seatbelt cannot be applied) from earlier tests, not from M10.

## Known limitations
- summarize shows the experiment as its recorded path (env.json experiment.path), since the manifest name is not stored in the bundle.
- Interface map covers Darwin, Linux, FreeBSD, OpenBSD, NetBSD; others BLOCKED.
- On peer failure the decrypt step is not run, so checkers that need the decrypted capture will fail there; the verdict is FAIL regardless.

## Design deviations
None.

## Unexpected findings
Heredocs failed in the sandbox (no temp file); edits were made with python -c and the editor tools.
