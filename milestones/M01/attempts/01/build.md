Milestone: M01            Attempt: 01 (corrective run, E012)           Base commit: 67a47956cef9548e56d82848be8fbfeae93b22de
Status: COMPLETE

## Files added / modified
- `orchestrator.py` (modified, large): new governed core replacing the generic state machine.
  - State: `milestones/<id>/state.yaml` in the MAIN repository (DESIGN 24.2/24.3), committed as `orchestrator` on branch `main`
    for every change; atomic write; one repository-wide `flock` (`<git-common-dir>/ai2ii-orch.lock`) held for the whole command.
  - Commands: `refresh review approve start-build finish-build start-verify run-tests finish-verify integrate invalidate unblock resolve`
    with the approved arguments; `status [--json]`, `show <id> [--json]`; `approve-gate` rewritten; `init-milestone` kept.
  - `criteria_version` / `show` spec hash = sha256 of the `spec.yaml` file (DESIGN 24.6).
  - Fixed a latent ownership bug: `lstrip("./")` stripped leading dots, so `.git/**` and `.worktrees/**` were matched as `git/**` / `worktrees/**`.
  - Removed: the external digest store and journal under `~/.local/state/ai2ii` (`get_external_state_dir`, `journal_event`,
    `is_state_authorized`, ...), `transition`, `verify`, `escalate`, `audit`, the old `run_tests`/validity/verdict code.
- `tests/flow_repo.py`, `tests/test_m01_flow.py`, `tests/test_governance_helpers.py` (added).
- `tests/test_m01_builder.py` (deleted; non-hermetic, tested removed behaviour). `tests/test_e011_boundary.py` is NOT kept as a file: its E011 coverage lives in `tests/test_governance_helpers.py` and `tests/test_m01_flow.py` (see below).

## Corrective run 2 (gate feedback on 61188176b12d)
- Tests now pass under the stdlib shim (`PYTHONPATH=src/_shims python3 -m pytest -q -p no:cacheprovider tests`, 37 passed) and under real pytest.
  No fixtures/parametrize/conftest: `flow_repo.with_repo` decorator builds and cleans a temp repo; `flow_repo` is loaded by path with importlib; the former parametrized test is a loop.
- E011 regression coverage restored (`tests/test_governance_helpers.py`, `tests/test_m01_flow.py`): builder may change `orchestrator.py`; `orch`/workflow.yaml/DESIGN.md/AGENTS.md/scripts/conftest.py/pytest.ini/pyproject.toml/acceptance/spec.yaml rejected
  (test_ownership_allows_source_and_blocks_protected_paths covers orch, workflow.yaml, DESIGN.md, AGENTS.md, conftest.py, pytest.ini, pyproject.toml, scripts, acceptance, spec.yaml);
  copy-back is attempt record only for builder and never code for verifier (test_copy_back_is_attempt_record_for_builder_and_never_code_for_verifier);
  `orch` from an attempt worktree runs MAIN's orchestrator (test_orch_wrapper_runs_mains_orchestrator_from_a_worktree);
  every `{orch}` command in a rendered verifier prompt parses (test_rendered_verifier_prompt_commands_parse);
  only run logs under main's `runs/` are citable (test_only_files_under_mains_runs_are_citable);
  state commands refuse off branch main and outside the main worktree (test_state_commands_require_main_branch, test_state_commands_refuse_outside_main_worktree).

## Tests added
`tests/test_m01_flow.py` (37 tests, each in its own temporary git repository with a copy of `orchestrator.py`), `tests/test_governance_helpers.py` (5).
After `python3 -m pytest -q -p no:cacheprovider tests` the worktree shows no changes beyond my commits (checked with `git status --porcelain`); no write to `~/.local/state`.
`ruff check` and `ruff format --check` on `orchestrator.py tests src/_shims` pass.

## Acceptance criteria believed satisfied (my own tests, not evidence)
- AC1: test_finish_build_rejects_protected_paths, test_finish_build_rejects_dot_prefixed_protected_path
- AC2: test_finish_build_requires_clean_tree_and_build_md, test_failing_builder_test_keeps_building_and_logs, test_finish_build_succeeds_and_logs_success
- AC3: test_failing_builder_test_keeps_building_and_logs, test_run_tests_logs_and_validity_modes (header `# command:`, `# commit:`, `# exit:`; path `runs/<id>/<NN>/<sha12>/<name>.log`)
- AC4: test_approve_needs_review_and_hash_bound_approval, test_uncommitted_approval_is_refused, test_preconditions_leave_state_unchanged, test_start_verify_refuses_builder_session, test_approve_gate_fails_cleanly_on_bad_target
- AC5: test_finish_verify_rejects_bad_verdict_files (8 cases), test_verifier_cannot_touch_implementation
- AC6: test_full_lifecycle_to_complete, test_pass_needs_validity_case_that_really_fails, test_pass_needs_acceptance_suite_to_pass
- AC7: test_fail_gives_rework_then_escalation_then_needs_g4, test_invalid_verdict_escalates_to_g3, test_blocked_verdict_and_unblock
- AC8: test_spec_change_returns_to_draft_and_invalidate_cascades, test_invalidating_complete_dependency_stales_complete_dependents
- AC9: test_full_lifecycle_to_complete, test_integration_conflict_restores_main_and_reworks, test_integration_suite_failure_restores_main
- AC10: test_full_lifecycle_to_complete (fresh `status --json`, all state.yaml commits authored `orchestrator`, main clean), test_state_commands_require_main_branch
- AC11: test_concurrent_finishes_do_not_corrupt_state (two `finish-build` processes at once)

## Could NOT verify
- Not run against the real repository (forbidden); all evidence is from temporary repositories. `./orch` (the wrapper) was exercised only for "runs main's orchestrator from a worktree".
- `scripts/verify_gate.sh` was not run (it may write to the repository). I only ran `validate`, `check-ownership`, `status`, `show` read-only against the real tree.
- `dispatch`, `seal`, `goldfish`, `doctor`, `interop`, `models`, `improve`, `context` were not exercised by new tests; they still import and parse.
- Behaviour with a hostile builder beyond the ownership cases tested (e.g. git hooks, submodules, symlink tricks beyond the existing `check_ownership` logic).

## Known limitations
- `STALE -> VERIFYING` (re-verification) is not implemented: `start-verify` accepts BUILT only. A STALE milestone can go to DRAFT via `invalidate --to DRAFT`.
- `dispatch` (out of scope for M01) still writes the old flat state keys (`base_commit`, `built_commit`, `worktree`) and does not create the `attempts` record that `finish-build` needs. It is legacy and should not be mixed with the new commands until a later milestone rewires it.
- `audit` and `escalate` commands were removed (audit depended on the external digest store; `escalate` opened files outside the lifecycle). Out of scope for M01.
- Rework attempt N+1 starts from the previous attempt's verify branch head (code + acceptance tests kept), not from main. "fails_on: base" uses attempt 01's base. `extra_attempts` (already present in M01's state.yaml) grants one more attempt when a `max_attempts` escalation is resolved to REWORK.
- A failed `run-tests` exits 1 (mirrors the tests' pass/fail); preconditions also exit 1.
- Validity "fails_on base" accepts pytest exit 1, 2 or 4 (a collection error because the module does not exist at base also yields 4 when a node id is given); mutants require exit 1. Test files must exist in the verified commit.
- `run-tests`, `finish-*` and `integrate` create and commit log files under `runs/` in main as `orchestrator`.
- Review/approval files are matched textually: review last non-empty line `Outcome: APPROVED` plus id and spec hash[:12]; approval needs the gate token(s), id, and `Decision: APPROVED` (also matches `**Human Decision:** APPROVED`).

## Design deviations (need architect sign-off)
Out-of-scope commands REMOVED relative to the pre-existing orchestrator, listed for architect/human decision (not restored in this run): `audit`, `escalate`, `transition`, `verify`.
Otherwise none intended. Points where DESIGN left room, decided by me: (1) state store is the repo (the old external digest store contradicted DESIGN 24.2/I8 and was removed); (2) rework base chaining described above; (3) `extra_attempts` use; (4) G4 also required when `len(escalations) >= max_escalations`; G3 additionally for MILESTONE_SPEC/ARCHITECTURE classifications.

## Unexpected findings
- `check_ownership`/`glob_to_regex` used `lstrip("./")`, silently turning `.git/**` into `git/**` (fixed, tested).
- The old test suite wrote `M90/M99` dirs, `runs/`, `metrics/M94.yaml`, `M00_DONE` and journal events into the real tree (G6); the new suite does not.
- `acceptance/M01/test_m01.py` tests the older, weakened spec: it calls `transition`, `invalidate --files`, and the old state schema, which no longer exist. It will fail against this implementation by design; the verifier must replace it. I did not edit it.
- `HANDOFF.md` still documents `./orch transition` and `./orch audit`; not edited (not my path).
- pytest returns exit 4 (not 2) for an unimportable test module when an explicit node id is given.
