# Milestone review 03

Reviewed M08 spec hash **3f60f66e25b0**, from `./orch show M08`. I did not write the spec.

M08 depends only on M01, so its DAG is acyclic. Its package, capture, bundle, checker and old-command removal trace to DESIGN.md 24.20; I find no speculative deliverable. `M` is plausible, so no `L` justification is required. It can be built and verified independently after M01 is COMPLETE, subject to an interface that permits capture. AC1-AC11 are mostly falsifiable experiments, with the gaps below.

## Round 2 findings

- **AC1/AC7 false wire PASS — resolved for the named case.** AC7 invokes only `wire run` with an always-pass capture checker and requires FAIL naming that checker. DESIGN.md 24.20 now makes validity part of every run. AC1 still requires the actual request and echo in the example capture.
- **AC3 bundle completeness — resolved.** It rejects modified, deleted, extra, duplicate and malformed entries and an invalid verdict, matching the limited integrity/layout claim.
- **AC4 timeout and cleanup — resolved.** It covers a silent server, hanging child and SIGINT, with process and capture cleanup.
- **AC5/AC6 preflight and build negatives — resolved.** The later env-check failure, stale binary, missing binary, capture-start failure and zero-packet case are explicit.
- **AC8 manifest validation — resolved for the round 2 omissions.** It now rejects non-boolean `observes_capture`, undefined cell checkers and cells without their own capture checker, before any work starts.
- **AC9 binary provenance — resolved for the stated binary claim.** It compares recorded hashes with executed bytes and requires a changed hash only when bytes change. Its new checker-source provenance claim has a separate gap below.
- **AC11 controller boundary — partly resolved.** Leaving that boundary to E011 is a reasonable division only if E011 is implemented and regression-tested before M08 is built. Present dispatch still copies builder code to its invoking workspace (`orchestrator.py:1078-1085`), and the prompt renderer still directs verifier commands to the attempt's `orchestrator.py` (`655-675`). Thus the prerequisite is not yet delivered.
- **Selected-cell checker binding — resolved.** Each cell now lists checkers, and AC7 tests that cell B's capture checker rejects cell A's exchange.

## New acceptance gaps

AC7 exercises an always-pass `observes_capture` checker, but DESIGN.md 24.20 requires **every** selected checker to reject **every** declared negative before PASS. An implementation could validate only the capture checker and report PASS while a selected vector checker accepts its flipped-vector negative. Add a two-checker cell where the capture checker passes its controls but the vector checker accepts one declared negative; `wire run` must FAIL and name the vector checker. This is a concrete false-success path despite the revised PASS rule.

AC9 records the experiment commit and dirty flag and hashes of declared inputs and negatives, but it does not identify the checker command's code when that code is neither an input nor cleanly committed. A changed `checker.py` in a dirty experiment directory can produce a different verdict with the same recorded commit and input hashes. Require and test provenance for the executed checker code, or narrow AC9's claim to the fields it actually proves.

Outcome: CHANGES_REQUESTED
