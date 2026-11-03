# M02 build, attempt 01

- Milestone: M02
- Attempt: 01
- Base commit: e989cc269607286f7fd01b7f40263ce6acc72c9e
- Status: COMPLETE (AC8 confinement could not be exercised here; see below)

## Files added / modified

- `orchestrator.py` (modified):
  - `cmd_dispatch` rewritten on top of M01: under the repo lock it checks status (builder READY/REWORK, verifier BUILT), candidates and `sandbox-exec`, then calls `cmd_start_build` / `cmd_start_verify` for the first candidate. Candidates run outside the lock. Each candidate's metadata, log and history/state update is committed by the orchestrator under the lock, in one commit. Nothing is copied into main.
  - Removed `create_worktree`, `destroy_worktree`, `get_worktree_changed_files`, `copy_back_paths`, `get_agent_command` (dead after the rewrite; the pre-M01 flat state keys are gone).
  - `render_role_prompt`: absolute worktree, `{sha}` is the commit worked on (the built commit for a verifier), `{base}` is the attempt's pre-implementation base, the full `criteria_version`, and a `ValueError` on any unresolved placeholder. New keyword-only args `commit`, `worktree`. The signature stays compatible with the M06/M07 callers.
  - `run_agent_in_worktree`: always `sandbox-exec`, no opt-out. New `_build_seatbelt_profile`: writes denied by default, then allowed only for the worktree, its git admin dir, common `.git/{objects,refs,logs}`, a per-attempt `TMPDIR` and the agent's `state_dirs`. `/private/tmp` and `/tmp` are no longer writable. `/dev` is writable.
  - `run_process_with_group_timeout`: the whole process group is SIGKILLed (and polled until empty) in a `finally`, on every exit path.
  - `record_attempt_metadata`: appends to a `candidates` list in `<role>_metadata.yaml` (top level still mirrors the latest record, so M06/M07 tests are unaffected). New `metrics=False` option; returns the path.
  - `governed` now uses a shared `_main_lock()` context manager, which dispatch also uses.
- `tests/test_m02_dispatch.py` (added), `tests/test_governance_helpers.py` (modified: removed the test of the deleted `copy_back_paths`).
- `agents.local.yaml` keys read by dispatch: `command`, `family`, `model`, `state_dirs` (list; `~` expanded; entries containing `*` become a regex rule, e.g. `~/.claude.json*`), `timeout_seconds` (default 3600).

## Tests added (tests/test_m02_dispatch.py)

All use fake agent commands. A stub `sandbox-exec` stands in for Seatbelt in the flow tests. The real confinement test skips when Seatbelt cannot be applied.

- `test_builder_then_verifier_dispatch_reuse_m01_lifecycle`
- `test_rendered_prompts_are_complete_and_parse`
- `test_exit_zero_without_record_is_no_record`
- `test_silent_verifier_is_no_record`
- `test_all_candidates_fail_leaves_building_at_base`
- `test_no_candidate_leaves_state_unchanged`
- `test_role_status_mismatch_is_refused`
- `test_fallback_resets_worktree_kills_group_and_records_winner`
- `test_verifier_fallback_identity_is_retained_candidate`
- `test_successful_candidate_leaves_no_writer_and_clean_worktree`
- `test_concurrent_dispatch_for_different_milestones`
- `test_seatbelt_profile_allows_only_the_declared_write_set`
- `test_agent_is_confined_by_seatbelt`

## Acceptance criteria believed satisfied

- AC1: `test_builder_then_verifier_dispatch_reuse_m01_lifecycle`
- AC2: same test, plus main byte-identical for tracked files.
- AC3: `test_exit_zero_without_record_is_no_record`, `test_silent_verifier_is_no_record`
- AC4: `test_rendered_prompts_are_complete_and_parse`
- AC5: `test_fallback_resets_worktree_kills_group_and_records_winner`, `test_successful_candidate_leaves_no_writer_and_clean_worktree`
- AC6: `test_all_candidates_fail_leaves_building_at_base`, `test_no_candidate_leaves_state_unchanged`
- AC7: `test_verifier_fallback_identity_is_retained_candidate`, `test_fallback_resets_worktree_kills_group_and_records_winner`
- AC8: profile content only, via `test_seatbelt_profile_allows_only_the_declared_write_set`. Live enforcement is in `test_agent_is_confined_by_seatbelt` (see below).
- AC9: `test_concurrent_dispatch_for_different_milestones`
- AC10: `test_role_status_mismatch_is_refused`

## Could NOT verify

- **AC8 live enforcement.** The build sandbox forbids nested `sandbox-exec` (`sandbox_apply: Operation not permitted`), so `test_agent_is_confined_by_seatbelt` skipped here. The profile is unit-tested as text only. It has never been applied to a real agent, so a missing allowance (for example something git needs while committing in a worktree) would only show up on a real macOS run. The verifier or orchestrator should run that test outside a nested sandbox.
- Real agent CLIs (claude, codex, agy) were not run, per the instructions. Their `state_dirs` entries are the operator's to declare in `agents.local.yaml`.
- Real `pytest` on the full suite: 68 passed and 1 failed (`test_m01_flow.py::test_start_verify_refuses_builder_session`, git "failed to insert into database" on a temp repo). It passed on immediate rerun, so it looks like sandbox flakiness in M01 code I did not touch. The shim run passed 69/69.

## Known limitations

- Refs are allowed broadly (`.git/refs`, `.git/logs`), as the spec lists them, not only the attempt branch's ref. A confined agent could move another branch ref, though it still cannot touch main's working tree, hooks or config.
- On success, dispatch discards uncommitted or untracked leftovers in the worktree (`reset --hard` + `clean -fdx`, recorded in the dispatch log) so `finish-*` sees a clean tree. Work that was not committed is lost.
- Success needs the record file in the commit at the attempt branch head, and the worktree HEAD must be that branch head. Ownership is left to `finish-build` / `finish-verify`; dispatch no longer checks it or runs the old AST test-weakening check.
- If `render_role_prompt` fails after `start-*` (a template bug), the milestone is left BUILDING/VERIFYING with no candidate run.
- An interrupted dispatch (Ctrl-C) leaves the state at the first candidate's identity and the attempt open; there is no resume command.
- Default agent timeout is 3600 s (per-agent `timeout_seconds` overrides it). The old default was 600 s.

## Design deviations (need architect sign-off)

1. Dispatch calls `record_attempt_metadata(..., metrics=False)`, so it does not write `metrics/Mxx.yaml`. AC2 lists only state.yaml, attempt metadata and runs/ logs as permitted writes in main, while M06 expects metrics per attempt. The function still writes metrics by default; who calls it with metrics on is unresolved.
2. `<role>_metadata.yaml` holds a `candidates` list plus the latest record at the top level, to satisfy both "every candidate" (AC7) and the existing M06/M07 readers.
3. `timeout_seconds` and `state_dirs` are per-agent keys in `agents.local.yaml`. `state_dirs` entries may contain `*`.

## Unexpected findings

- AC7 mentions "finish-verify's family-diversity check", but M01's `finish-verify` has none. The only diversity logic is the "same family as builder" note in `start-verify`. Dispatch repeats that note in history when a fallback verifier shares the builder's family. `verification.yaml`'s `verifier.family` is never compared with `state.yaml` either.
- The environment note says the orchestrator runs `finish-build M08`; this is milestone M02. I assumed a typo.
- `acceptance/M02/test_m02.py` (pre-M01) calls `create_worktree` / `destroy_worktree`, which are removed here. It is verifier-owned and I did not touch it. It will fail until the verifier replaces it.
- `AGENTS.md`'s builder prompt contains no criteria_version; only the verifier template does.
