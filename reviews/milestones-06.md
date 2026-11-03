# Milestone review 06

Reviewed `milestones/M08/spec.yaml`, SHA-256 **8ee75145224a** from `./orch show M08`. I did not write the spec. M08 depends only on COMPLETE M01, giving an acyclic DAG. The wire package can be built in an M01 attempt worktree and verified through M01's `start-build`, `finish-build`, `start-verify`, `run-tests`, `finish-verify` and `integrate` commands. Its `M` size needs no `L` justification. The package boundary, bundle, checker validity and replacement of `orch interop` trace to DESIGN.md 24.18 and 24.20; no speculative deliverable was found.

## Disposition of review 03

- **Every selected checker:** resolved. AC7 now requires `wire run` to FAIL and name a vector checker that accepts one declared negative even when the capture checker passes its controls. This tests the design's every-checker, every-negative rule without relying on a separate validation command.
- **Checker code provenance:** resolved for a PASS verdict. AC9 blocks a dirty or untracked experiment directory, so its recorded commit can identify the checker code, including a script that is not a declared vector input.
- The previous round's capture, bundle-integrity, timeout, preflight, build, manifest and binary-provenance cases remain explicit in AC1–AC10.

## Findings

1. **A cell need not contain two peers (AC8).** DESIGN.md 24.20 defines a cell with a server and clients, and M08 claims concurrent two-peer interop. AC8 rejects undefined peer names but does not reject an empty `clients` list, a missing server, or a server also named as its own client. Such a manifest can pass validation; a server emitting packets and a checker tailored to them can produce PASS without an exchange between independent peers. Require at least one defined client distinct from the server, with no duplicate client names, before any env check or process starts. Test those malformed cells and assert exit 2 with no side effects.
2. **The E011 prerequisite is overstated (out_of_scope; DESIGN.md 24.3).** The spec says the governing/subject controller boundary was delivered and regression-tested by the E011 bootstrap commit. M01's wrapper runs main's `orchestrator.py`, and its lifecycle finish commands read attempt-branch records; those paths support M08. But integrated `cmd_dispatch` still uses its older copy-back path, whose verifier selection includes `acceptance/<id>/**` (`orchestrator.py:770–785`), contrary to DESIGN.md 24.3 rule 1. `tests/test_governance_helpers.py` even expects that selection. Because M08 can proceed through M01's manual lifecycle, it need not depend on M02. State that supported route explicitly and remove the claim that the entire dispatch boundary is already enforced, or make the boundary true before M08 relies on automated dispatch.

AC1–AC7 and AC9–AC11 are otherwise falsifiable against the named outputs and failure modes. The missing cell-shape negatives allow apparent interop success without the claimed two-peer capability; the dispatch claim obscures a governing-code risk in the integrated M01 baseline.

Outcome: CHANGES_REQUESTED
