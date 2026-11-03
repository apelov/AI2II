# BASELINE — Phase 0 snapshot (DESIGN.md 24.4)

Snapshot taken 2026-10-08. Frozen once Phase 1 begins; current state lives in
`milestones/*/state.yaml`.

## Repository state

- New repository. Inputs: `DESIGN.md` (frozen design: AI Engineering Workflow v2,
  section 24) and `PLAN.md` (bootstrap plan derived from it and from the external
  bootstrap instructions).
- No product code. The protocol experimentation infrastructure that this workflow
  will build has no design document in this repository yet.

## Known to work

Nothing yet. No component has been verified.

## Known broken

None.

## External dependencies

- git ≥ 2.31 (worktrees, `--path-format`), Python 3.12, PyYAML, pytest.
- Agent CLIs present on the bootstrap machine: `claude`, `claude-or` (Claude Code via
  OpenRouter), `codex`, `agy`, `pi`. None are required by M01.

## Assumptions

- A single machine and a single local clone; no remote is pushed to by tooling.
- Agents run as local processes in git worktrees under `.worktrees/`.
- Until M01 is COMPLETE, a human performs orchestrator duties by hand using the same
  file layout and rules (DESIGN.md 24.3).

## Open questions (provisional answers pending G1)

| ID | Question | Provisional answer |
|----|----------|--------------------|
| OD1 | Build the TUI the bootstrap instructions ask for? | Deferred: DESIGN.md 24.19 rules out a GUI or service. `./orch status --json` keeps the option open. |
| OD2 | Role → command mapping (`agents.local.yaml`) | Deferred to the dispatch milestone; M01 records declared agent/family/model/session only. |
| OD3 | "Project/implementation descriptor" inputs | Dropped: they belong to DESIGN.md's example milestone, not to the infrastructure plan. |
| OD4 | Orchestrator language/toolchain | Python 3.12 + PyYAML + stdlib; pytest for tests. |
| OD5 | How is cost measured for `budget_per_milestone_usd`? | Open. Limit recorded, not enforced; metrics report `cost_usd: null`. |
| OD6 | Product design for the protocol experimentation infrastructure | Open. Needed before product milestones can be decomposed. |
| OD7 | PLAN.md §6 milestones M02–M07 | To be re-decomposed in Phase D: M01 now covers verdict validation and integration (PLAN.md placed parts in M03/M05). |
