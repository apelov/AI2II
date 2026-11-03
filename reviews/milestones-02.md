# Milestone review 02

Reviewed M08 spec hash **d7d37cb1546b**, from `./orch show M08`. I did not write the spec.

M08 still has the single dependency M01, so its displayed DAG is acyclic. `M` is plausible; no `L` justification is needed. Its runner, capture, bundle, checker, and old-command removal trace to DESIGN.md 24.20. M08 can be built and verified independently after M01 is COMPLETE, subject to a capturable interface for its positive example. The revised criteria are mostly concrete experiments.

## Round 1 findings

- **AC1/AC6/AC7/AC10 wire exchange — partly resolved.** New AC1 requires both observed directions and an echo of the exact payload; AC2 supplies unrelated-traffic and missing-direction negatives; AC10 ties a positive vector to captured bytes. But AC1 and AC7 still allow `wire run` to report PASS when `validate-checkers` would reject the checker. Design 24.20 has the same gap. A permissive checker and unrelated nonempty capture can still produce a green cell if the validity command is not run.
- **AC2 bundle completeness — resolved by AC3.** The new AC3 rejects unlisted, missing, duplicate, malformed, and modified entries and an invalid verdict. DESIGN.md now limits `verify-bundle`'s claim to integrity and layout.
- **AC3 timeout and cleanup — resolved by AC4.** The example client's response condition is explicit, and AC4 tests a silent server, a hanging peer with a child, SIGINT, and process-group/capture cleanup.
- **AC4/AC5 preflight and build negatives — resolved by AC5/AC6.** The revised criteria cover a later failing env check, nonzero build despite a stale binary, missing output, capture startup failure, and zero-packet capture.
- **AC7/AC8 fail-closed manifest — largely resolved by AC8.** The listed malformed cases now include missing/empty family, duplicate names, undefined peer, missing negatives, bad negative paths/replacements, and fewer than two capture negatives. AC8 makes these fail before work starts. The spec should also require a valid `observes_capture` boolean and at least one checker *applicable to the selected cell*, since the manifest has a global checker list and no cell-to-checker binding.
- **AC9 binary provenance — resolved for the stated example.** AC9 ties the recorded hash to the bytes executed and changes the hash only when binary bytes change; AC6 handles failed and missing builds. The exact command path used remains testable.
- **AC11 import/controller boundary — partly resolved.** The AST check is stronger than grep for common import forms. The controller boundary is now explicitly assigned to E011 bootstrap, so excluding it from M08 is reasonable only after that prerequisite is implemented and regression-tested. Current `orchestrator.py` still copies builder code into the invoking workspace (`1078-1085`), so the out-of-scope line is a future dependency claim, not delivered evidence.

## New acceptance gap

Require `wire run` to refuse PASS when checker validity has not passed for the exact manifest/checker inputs used by that run. A minimal acceptance experiment substitutes an always-pass `observes_capture` checker, records unrelated nonempty UDP, invokes **only** `wire run`, and asserts a non-PASS outcome. AC2 alone tests `validate-checkers`; it does not close this false-success path. If validation is deliberately a separate gate, the bundle needs a verifiable reference to its successful result and the milestone objective should say where that gate is enforced.

The proposed global `checkers` list also lacks a rule identifying which checker applies to each cell. A checker can accept its own expected exchange while ignoring another cell's traffic; the latter could pass with an unrelated nonempty capture. Bind capture checkers to cells or require every selected checker to validate each selected cell, and test a two-cell manifest where only one cell's expected exchange occurs.

Outcome: CHANGES_REQUESTED
