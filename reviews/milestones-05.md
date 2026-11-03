# Milestone review 05

Reviewed `milestones/M02/spec.yaml`, SHA-256 **57fba7c936e7** from `./orch show M02`. I did not write the spec. M01 is COMPLETE. M02 depends only on M01, so the DAG is acyclic and M02 can be built and tested independently. Its `M` size needs no `L` justification. Dispatch, prompts, fallback and confinement trace to DESIGN.md 24.3 and 24.14–24.16. The criteria have observable positive and negative cases.

## Disposition of review 04

1. **Acceptance copy-back: partly resolved.** AC2 now keeps acceptance tests and source on the verifier branch; M01's `run-tests` reads that branch and overlays its acceptance files for base runs (`orchestrator.py:2752–2775`). But AC2 and the objective say dispatch copies *nothing* into main, whereas DESIGN.md 24.3 rule 1 says it copies *only the attempt record* back. The integrated M01 `finish-build` and `finish-verify` read the committed records from their attempt branches (`orchestrator.py:2695–2710`, `2935–2954`), so the no-copy design may be workable. The spec and governing design still contradict each other. Resolve the rule in DESIGN.md or make this spec conform before approval.
2. **Lifecycle: resolved for the normal path.** AC1 now requires M01 `start-build`/`start-verify` and a successful matching finish; AC6 defines the all-failed state after the start transition and keeps no-candidate refusal before it. M01 supplies the recorded branch, worktree and base.
3. **Missing record: resolved.** AC3 rejects an uncommitted or absent record after exit 0 for both roles.
4. **Sandbox: resolved at the specification level.** AC8 requires Seatbelt on dispatch, narrows the Git metadata exception, and tests writes to main, Git configuration/hooks and unrelated `/private/tmp`.
5. **Fallback isolation: partly resolved.** AC5 resets failed candidates to the recorded base and tests a background writer. It does not require cleanup of a child left by a *successful* candidate; see finding 2 below.

## New findings

1. **Fallback leaves M01's agent identity stale (AC1, AC6, AC7).** `start-build` and `start-verify` persist the first candidate's agent, family, model and session in `state.yaml` (`orchestrator.py:2648–2692`, `2725–2749`). AC5 reuses that attempt for fallback, but no criterion requires updating those fields to the candidate whose commit and record are retained. A first candidate can fail, a second can succeed, and `finish-build`/`finish-verify` can pass while state attributes the work to the first. For verification, this also makes the recorded builder/verifier diversity and session provenance wrong. Require state and attempt metadata to identify the successful candidate, retain failed-candidate history separately, and test two candidates with distinct families and sessions followed by the finish command.
2. **Successful agent descendants can outlive dispatch (AC5, AC8).** AC5 terminates the process group only *when a candidate fails*. A CLI can exit 0 after committing its record while leaving a background child that writes into its still-retained worktree. Dispatch can then report success and `finish-build` may inspect a branch that changes beneath it. Require process-group cleanup after every candidate, including success, before accepting its commit; test an exit-0 agent that leaves a delayed writer and assert no later write and a clean worktree.

These gaps permit a successful dispatch with incorrect provenance or unstable output. AC2's conflict also needs an explicit design resolution; a milestone spec cannot silently override a MUST rule. No speculative deliverable or missing `L` justification was found.

Outcome: CHANGES_REQUESTED
