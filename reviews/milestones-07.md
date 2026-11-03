# Milestone review 07

Reviewed `milestones/M02/spec.yaml`, SHA-256 **9e51bba8b5c9** from `./orch show M02`. I did not write the spec. M01 is COMPLETE. M02 depends only on M01, so the DAG is acyclic and dispatch can be implemented and verified independently. Its `M` size needs no `L` justification. Dispatch, fallback, prompt rendering and confinement trace to DESIGN.md 24.3 and 24.14–24.16; no speculative deliverable or unnecessary dependency was found.

## Disposition of review 05

- The amended DESIGN.md 24.3 rule 1 now agrees with the spec: dispatch leaves attempt records on the attempt branch for M01's finish commands to read. The amendment remains subject to human G1, but under the amended rule there is no spec conflict.
- AC7 now requires the retained candidate's agent, family, model and session in `state.yaml`, records every failed candidate separately, and tests distinct candidate families and sessions through the finish command and verifier diversity check.
- AC5 now terminates the whole process group after every candidate, including success, before inspecting its branch. It tests a successful candidate's delayed writer and requires no later write and a clean worktree.
- The previously resolved lifecycle, missing-record, sandbox and failed-candidate reset cases remain explicit in AC1, AC3, AC5, AC6 and AC8.

AC1–AC10 are falsifiable through state, branch contents, logs, process cleanup and exit status. They include absent candidates, invalid states, missing records, failed fallback, delayed writes and prohibited filesystem writes. The stated success paths require a committed attempt record and a matching finish command; the reviewed gaps no longer allow dispatch to appear successful without its claimed capability.

Outcome: APPROVED
