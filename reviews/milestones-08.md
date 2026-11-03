# Milestone review 08

Reviewed `milestones/M08/spec.yaml`, SHA-256 **24a2eb3309e6** from `./orch show M08`. I did not write the spec. M08 depends only on COMPLETE M01, so the DAG is acyclic and it can be built and verified through M01's manual lifecycle without M02. Its `M` size needs no `L` justification. The separate `wire/` package, evidence bundle, checker validity and removal of `orch interop` trace to DESIGN.md 24.18 and 24.20; no speculative deliverable was found.

## Disposition of review 06

- AC8 now rejects cells with no server, no client, a client equal to its server, or repeated clients before any env check or process starts. This closes the route to PASS without distinct peers.
- `out_of_scope` now identifies M01's manual lifecycle as the supported build and verification route and excludes M02 dispatch. It no longer claims that the integrated baseline already enforces the full dispatch boundary.
- AC7 still requires every selected checker to reject every declared negative during `wire run`; AC9 still binds checker code to a clean experiment commit.

AC1–AC11 give observable PASS, FAIL, BLOCKED, ENV and manifest-error cases, including malformed cells, missing or stale binaries, unrelated traffic, weak checkers, tampered bundles, timeouts and interruption cleanup. A passing example requires captured traffic in both directions, successful peers and valid checkers, so the reviewed gaps no longer permit apparent two-peer success without the claimed exchange.

Outcome: APPROVED
