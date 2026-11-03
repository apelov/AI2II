ROLE: BUILDER — milestone M02, attempt 01, base commit e989cc269607286f7fd01b7f40263ce6acc72c9e
Worktree: .worktrees/M02-a01-build
Work and commit only in that worktree.
Read: AGENTS.md, DESIGN.md, milestones/M02/spec.yaml, and the code of COMPLETE dependencies.

Implement ONLY this milestone.
You may write: the source tree, your own tests under tests/, milestones/M02/attempts/01/build.md.
You may NOT write: acceptance/**, spec.yaml, state.yaml, or any other role's paths. Such changes are rejected.
Builder tests must pass with: python3 -m pytest -q -p no:cacheprovider tests
The orchestrator re-runs them itself; your own run is not evidence.
Write milestones/M02/attempts/01/build.md containing:
  Milestone / Attempt / Base commit / Status: COMPLETE | PARTIAL
  Files added / modified
  Tests added
  Acceptance criteria believed satisfied (by id, with test names)
  Could NOT verify (and why)
  Known limitations
  Design deviations (each requires architect sign-off before VERIFIED)
  Unexpected findings
If you believe a criterion or acceptance test is wrong, say so in build.md; do not edit it.
Commit all work (the worktree must be clean), then stop.
ENVIRONMENT NOTES (orchestrator):
  - M01 is COMPLETE; its orchestrator.py is the dependency code to read. M02 is built through M01's manual
    lifecycle: when you are done, the orchestrator runs `finish-build M08`, which checks ownership against the
    base commit, requires your committed build.md, and re-runs the builder tests itself.
  - The orchestrator runs builder tests with src/_shims first on PYTHONPATH, so `python3 -m pytest` is the stdlib
    shim in src/_shims/pytest.py (no fixtures, no conftest, test dir not on sys.path). Reproduce the gate with
        PYTHONPATH=src/_shims python3 -m pytest -q -p no:cacheprovider tests
    and also run real pytest. Both must pass. Do not edit src/_shims/pytest.py.
  - Tests must be hermetic: temp dirs only; `git status --porcelain` empty after the run.
  - You run inside a macOS sandbox that only permits writes to this worktree and temp dirs.
  - Run `ruff check` and `ruff format --check` on orchestrator.py, wire, tests and src/_shims before committing.
  - Known defects in the current dispatch path that M02 must fix (they are covered by its criteria):
    render_role_prompt renders "Worktree: .worktrees/<id-lower>-attempt-NN" instead of the attempt's real absolute
    worktree, renders the built commit where the verifier prompt says "pre-implementation commit", and truncates
    criteria_version to 12 characters (AC4); cmd_dispatch still uses the pre-M01 flat state keys and copy-back
    (AC1, AC2); run_agent_in_worktree defaults to no Seatbelt (AC8). The orchestrator operator has been working
    around these by hand; see runs/M08/01/prompt-*.md for the corrected output.
  - Agent CLIs that dispatch must be able to run: claude (writes ~/.claude, ~/.claude.json*), codex (~/.codex),
    agy (~/.gemini, ~/Library/Application Support/Antigravity). Tests must use fake agent commands, never real CLIs.
  - Do not commit with any "Co-Authored-By" trailer.
