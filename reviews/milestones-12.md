# Milestone review 12

Reviewed `milestones/M10/spec.yaml`, hash **c967e2117dcd** from `./orch show M10`, against DESIGN.md 24.20–24.21 and the findings in reviews/milestones-11.md. I did not write the spec. This review is not an orchestrator run log.

M10 depends on COMPLETE M09, whose existing chain is M09 → M08 → M01. The DAG is acyclic, and M10 can be implemented and verified after those dependencies. Its S size needs no L justification. The loopback alias, post-failure checker run, summary, and clean-build guidance trace to DESIGN.md 24.20. The broken UDP cell and tracked-file test copies directly support the specified first-run and explanatory-FAIL goal; they are not speculative infrastructure.

All five milestones-11 findings are resolved:

1. AC4 now requires a captured one-byte corruption, a rejecting checker log, a failing-client reason, and a control run with an unchanged echo that passes. The deliverables and design explicitly require checkers to run on non-empty captures after a peer failure. A client exit alone cannot satisfy AC4.
2. The `change_control` field assigns the approved M08 fixture compatibility edit to the orchestrator operator before the build; AC7 requires M08 to pass with only that edit and M09 unchanged. This keeps acceptance-file changes outside builder ownership.
3. AC2 uses fresh committed repositories for both Linux cases and requires the hardcoded-`lo0` BLOCKED reason to name capture or interface, excluding a dirty-experiment failure. It lists git and the other container prerequisites.
4. AC5 defines discovery at different depths, visible unverified text and JSON claims, and a null verdict plus error for missing or malformed `verdict.json`. It also checks empty input and that summary starts no subprocess.
5. AC6 targets the tracked-file-copy failure after example build output is present. It expressly excludes proof of clean intermediate builds for compiled experiments.

AC1–AC7 are falsifiable through platform runs, injected failures, bundle tampering, and regression suites. Negative cases cover unsupported interface resolution, hardcoded `lo0` on Linux, a corrupted exchange, tampered or malformed bundles, and empty summary input. The remaining platform and fixture work is verification effort; the criteria cannot appear successful while the claimed portability, explanatory FAIL, and trustworthy comparison capabilities are absent.

Outcome: APPROVED
