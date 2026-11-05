# 24. AI Engineering Workflow (v2)

The infrastructure itself MUST be developed using a structured multi-agent engineering process.

The goal is not autonomous coding. The goal is:

> **Independent implementation and independent verification, enforced by tooling, with the repository — not an AI conversation — as the single source of project state.**

The same workflow may later be offered to Hackathon participants. That is a reason to keep it clean, not a reason to generalise it now (see 24.18).

---

## 24.1 Invariants

These are the non-negotiable properties of the workflow. Everything else in this section exists to make them hold.

| # | Invariant | Enforced by |
|---|-----------|-------------|
| I1 | A milestone is never verified in the same session/context that built it. | Orchestrator (24.3) |
| I2 | Acceptance criteria are fixed and approved before implementation begins, and are versioned. | Spec hash in state (24.6) |
| I3 | A builder cannot change acceptance criteria or verifier-owned tests. | Path ownership check (24.3) |
| I4 | Only a verifier verdict, confirmed by an orchestrator-run test execution, can move a milestone to `VERIFIED`. | Orchestrator |
| I5 | Every verdict is bound to an exact commit and an exact criteria version. Changing either invalidates it. | Orchestrator (24.13) |
| I6 | A milestone is `COMPLETE` only after its acceptance tests pass on the **integrated** main branch. | Orchestrator (24.14) |
| I7 | Every loop is bounded. Exhausted bounds go to a human, never silently onward. | Limits in `workflow.yaml` |
| I8 | A fresh agent session can resume the project from repository files alone. | Repository layout (24.2), resumption drill (24.17) |

Wherever this document says MUST, the rule is checked mechanically. Where it says SHOULD, it is policy that the orchestrator records but does not block.

---

## 24.2 Roles and repository layout

### Roles

| Role | Does | Writes (only) |
|------|------|---------------|
| **Architect** | Baseline, design, milestone decomposition, arbitration of escalations not involving its own artifacts | `BASELINE.md`, `DESIGN.md`, `milestones/*/spec.yaml` (while in `DRAFT`), `escalations/*` |
| **Reviewer** | Independent review of design and milestone plan | `reviews/*` |
| **Builder** | Implements one milestone | source tree, builder tests, `milestones/Mxx/attempts/NN/build.md` |
| **Verifier** | Attempts to falsify one milestone | `acceptance/Mxx/**`, `milestones/Mxx/attempts/NN/verification.yaml` |
| **Human** | Approves gates (24.11), resolves escalations the architect cannot neutrally judge | `approvals/*` |
| **Orchestrator** | Deterministic program, not an LLM. Dispatches agents, runs tests, owns all state transitions | `milestones/*/state.yaml`, `runs/**`, `metrics/**` |

Reviewer and Verifier MUST NOT be the same session as the agent whose work they assess. They SHOULD be a different model family (24.15).

### Layout

```text
AGENTS.md                      role prompts, versioned (24.16)
BASELINE.md                    Phase 0 snapshot; written once, then frozen
DESIGN.md
workflow.yaml                  committed: roles, limits, policies (24.15)
agents.local.yaml              NOT committed: maps roles to commands

milestones/
  M03/
    spec.yaml                  objective, deps, acceptance criteria
    state.yaml                 written ONLY by the orchestrator
    attempts/
      01/
        build.md
        verification.yaml
      02/ ...
acceptance/
  M03/                         verifier-owned acceptance tests
runs/
  M03/01/<sha>/                orchestrator-captured logs of test runs
reviews/                       design and milestone-plan reviews
escalations/                   E001.md ...
approvals/                     human sign-offs
metrics/                       per-milestone metrics (24.17)
```

There is **one state file per milestone**, so parallel milestones never contend for a shared file. Project-level status is a view that the orchestrator derives (`orchestrator status`). It is never a hand-edited file.

---

## 24.3 The orchestrator

The orchestrator is the enforcement point. Keep it small: it is a CLI plus checks, not a platform.

Responsibilities:

1. **Dispatch.** Selects the next eligible `(role, milestone)`, renders the role prompt from `AGENTS.md`, and invokes the configured command in a fresh session and isolated worktree.
2. **Path ownership.** After each agent run, it diffs the worktree against the start commit. Any change outside the role's allowed paths (24.2) rejects the run. In particular, a builder diff touching `acceptance/**` or `spec.yaml` is rejected.
3. **Test execution.** It runs the acceptance and builder test suites itself and stores the logs under `runs/`. Reports cite those logs. Prose "evidence" without a log reference is not evidence.
4. **State transitions.** It applies 24.7. Agents *recommend* verdicts; the orchestrator *applies* them only when the preconditions hold.
5. **Invalidation.** It applies 24.13 when a spec, commit, or dependency changes.
6. **Limits and metrics.** It counts attempts, escalations and cost; enforces limits; and writes `metrics/`.

**Bootstrap.** The orchestrator is itself part of the infrastructure, so it cannot be used to build its own first version. Until milestone `M01 — orchestrator minimum` is `COMPLETE`, a human performs the orchestrator's duties by hand, using the same file layout and the same rules. `M01` must deliver at least dispatch-free checks: path ownership, test execution with captured logs, and state transitions. Agent dispatch automation can come in a later milestone.

**Governing and subject orchestrator** (added 2026-11-02, E011, G3). The orchestrator that *governs* is always main's `./orch`. Gates, verdicts, `run-tests`, ownership checks and state transitions are executed only by that copy. A builder may change `orchestrator.py` in its own worktree, like any other source file. That *subject* copy governs nothing until it is `VERIFIED` and integrated (24.14). Three rules enforce this (MUST):
1. Dispatch copies nothing back to main. `finish-build` and `finish-verify` read the attempt record (`build.md`, `verification.yaml`) from the attempt branch; code, acceptance tests and records reach main only through `integrate` (amended 2026-11-03, reviews/milestones-05.md, G1).
2. The `orch` wrapper (protected) locates the main worktree via git and always executes **main's** `orchestrator.py`, from wherever it is invoked. That includes an attempt worktree, as the M01 interface allows. State commands additionally require main to be on branch `main`. An attempt's own `orchestrator.py` is only ever executed by that attempt's tests.
3. A builder change to `orchestrator.py` leaves main's `orchestrator.py` byte-identical, and the verdict is computed by main's copy (regression test, E011).

A builder can never change the rules, the gate, the wrapper or the test harness configuration: `orch`, `DESIGN.md`, `BASELINE.md`, `AGENTS.md`, `workflow.yaml`, `scripts/**` (including `scripts/verify_gate.sh`), `.git/**`, `.worktrees/**`, `pytest.ini`, `conftest.py` and `pyproject.toml`.

---

## 24.4 Phase 0 — Baseline

The architect inspects the repository, documentation, code, tests, prior decisions, relevant specifications, available implementations, and tooling. It MUST NOT implement anything.

Output: `BASELINE.md`, containing:

- current repository state;
- components known to work (with how that was established);
- components known to be broken;
- external dependencies;
- assumptions;
- open questions.

`BASELINE.md` is a snapshot and is frozen after Phase 1 begins. Current state lives in `milestones/*/state.yaml`.

---

## 24.5 Phase 1 — Design

The architect produces `DESIGN.md`:

1. problem statement;
2. goals and non-goals;
3. architecture and major abstractions;
4. repository structure;
5. data/result model;
6. execution lifecycle;
7. security assumptions;
8. external dependencies;
9. alternatives considered and features deliberately rejected;
10. open design questions.

The architect MUST challenge its own design for unnecessary abstraction, premature generalisation, unnecessary dependencies, and protocol-specific assumptions leaking into generic infrastructure. It records the result in a short "self-challenge" subsection.

**Design review.** A Reviewer, independent of the architect, writes `reviews/design-NN.md`. The review asks the same questions plus: *Which goal is not served by any component? Which component serves no goal? What is the riskiest assumption, and how would we find out early that it is wrong?* The outcome is `APPROVED` or `CHANGES_REQUESTED`, iterated up to `limits.design_review_rounds`.

**Gate G1 (human):** design approval. Recorded in `approvals/`.

---

## 24.6 Phase 2 — Milestones

The architect decomposes the approved design into milestones forming an explicit dependency DAG. Each milestone MUST be independently implementable and independently verifiable.

`milestones/M03/spec.yaml`:

```yaml
id: M03
title: Implementation descriptor and peer preparation
objective: >
  Allow an implementation to be obtained, pinned and built reproducibly.
depends_on: [M01, M02]
inputs: [project descriptor, implementation descriptor]
deliverables:
  - implementation loader
  - Git acquisition
  - revision pinning
  - build command execution
acceptance:                      # each criterion has a stable id
  AC1: a clean repository can be obtained from a local and a remote source
  AC2: the checked-out commit equals the requested revision; mismatch is an error
  AC3: a successful build is reported READY with the build log attached
  AC4: a failed build (non-zero exit) is reported FAILED, never READY
  AC5: a missing repository or invalid revision is reported as an error, never PASS
out_of_scope: [Docker, remote execution]
size_hint: S | M | L             # L requires justification; prefer splitting
```

When a spec is approved, the orchestrator records `criteria_version = sha256(spec.yaml)` in `state.yaml`. After approval, `spec.yaml` can change only through change control (24.13).

**Milestone review.** A Reviewer writes `reviews/milestones-NN.md` answering:

- Can every milestone be verified independently?
- Is every acceptance criterion falsifiable, i.e. is there a concrete observation that would show it false?
- Are the dependencies correct and the DAG acyclic?
- Is any milestone too large (`L` without justification)?
- Is anything speculative, i.e. not traceable to a goal in `DESIGN.md`?
- Are negative cases missing?
- Could a milestone appear successful without delivering the claimed capability?

**Gate G2 (human):** milestone plan approval. Only approved milestones enter the lifecycle.

---

## 24.7 Milestone lifecycle

```text
          DRAFT ──review──▶ REVIEWED ──G2──▶ APPROVED
                                                │ all deps COMPLETE
                                                ▼
     ┌──────────────────────────────────────▶ READY
     │                                          │
     │                                          ▼
     │                      ┌─────────────▶ BUILDING ──▶ BUILT ──▶ VERIFYING
     │                      │                                         │
     │                   REWORK ◀──────────── FAIL ───────────────────┤
     │                      ▲                                         │
     │                      │                 BLOCKED ◀─ BLOCKED ─────┤
     │                      │                    │                    │
     │   (unblocked) ◀──────┼────────────────────┘                    │
     │                      │                                         │
     │                      │              ESCALATED ◀── INVALID ─────┤
     │                      │                 │       (or limit hit)  │
     │                      ├──── resolved ───┤                       │
     │                      │                 └──▶ DRAFT (spec change)│
     │                      │                                         ▼
     │                      └────── integration fails ──────────── VERIFIED
     │                                                                │
     │                                                       merge + re-run
     │                                                       acceptance on main
     │                                                                ▼
     └────────────── invalidated (24.13) ──── STALE ◀──────────── COMPLETE
```

Transition rules (all applied by the orchestrator):

| From | To | Precondition |
|------|----|--------------|
| `APPROVED` | `READY` | every `depends_on` milestone is `COMPLETE` |
| `READY` / `REWORK` | `BUILDING` | builder dispatched; attempt counter incremented |
| `BUILDING` | `BUILT` | `build.md` present; path-ownership check passed; builder tests pass in an orchestrator run |
| `BUILT` | `VERIFYING` | verifier dispatched in a fresh session |
| `VERIFYING` | `VERIFIED` | verdict `PASS`; test-validity check passed (24.9); orchestrator run of `acceptance/Mxx` passes at the verified commit |
| `VERIFYING` | `REWORK` | verdict `FAIL` and `attempts < limits.max_attempts` |
| `VERIFYING` | `BLOCKED` | verdict `BLOCKED` (verification could not run: missing environment, dependency, credential) |
| `VERIFYING` | `ESCALATED` | verdict `INVALID` (spec untestable or contradictory), or `attempts == limits.max_attempts` |
| `VERIFIED` | `COMPLETE` | merged to main; acceptance suites of this **and all previously `COMPLETE` milestones** pass on the merge commit |
| `VERIFIED` | `REWORK` | integration run fails |
| `COMPLETE` / `VERIFIED` | `STALE` | invalidated (24.13) |
| `STALE` | `VERIFYING` | re-verification dispatched |
| `BLOCKED` | `READY` | blocker resolved (human or architect records the resolution) |
| `ESCALATED` | `REWORK` / `DRAFT` / `BLOCKED` | escalation resolved (24.12) |

`BLOCKED` and `INVALID` are never `PASS`. There is no transition from `BUILT` to anything except `VERIFYING`.

---

## 24.8 Build

The builder receives the following, rendered by the orchestrator from `AGENTS.md`:

- `DESIGN.md` and the relevant protocol specification;
- `milestones/Mxx/spec.yaml`;
- the code of `COMPLETE` dependencies;
- on rework: the previous `verification.yaml` and the `runs/` logs it cites.

The builder implements **only** this milestone and writes `attempts/NN/build.md`:

```text
Milestone: M03            Attempt: 02           Base commit: <sha>
Status: COMPLETE | PARTIAL
Files added / modified:
Tests added:
Acceptance criteria believed satisfied (by id, with test names):
Could NOT verify (and why):
Known limitations:
Design deviations (each requires architect sign-off before VERIFIED):
Unexpected findings:
```

The builder MUST list what it could not verify. It MUST NOT edit `acceptance/**` or `spec.yaml`, and the orchestrator rejects the run if it does. If it believes a verifier test or a criterion is wrong, it says so in `build.md`. That statement is an input to escalation, not a licence to edit.

---

## 24.9 Verification

The verifier runs in a fresh session, in its own worktree at the builder's commit, and verifies in **two passes**.

**Pass 1 — blind falsification.** Inputs: `spec.yaml`, `DESIGN.md`, the protocol specification, and the code. Not the build report.

For each acceptance criterion, the verifier asks: *What experiment would show this criterion is false?* It writes those experiments as tests in `acceptance/Mxx/`, covering as relevant:

- positive cases;
- negative cases;
- malformed input;
- missing dependencies;
- failure paths;
- cleanup;
- interruption.

**Pass 2 — claim audit.** The verifier then reads `build.md` and checks:

- each claimed criterion against its own results;
- each "could not verify" item;
- each design deviation.

**Test-validity check (MUST).** A passing test is evidence only if it is able to fail. For each criterion, at least one acceptance test MUST be shown to fail against either:

- the milestone's base commit (pre-implementation); or
- a mutant supplied by the verifier: a minimal deliberate break, such as ignoring the build exit status. This is required whenever the test would already pass at the base commit.

The orchestrator runs these checks and logs them in `runs/`. A criterion without a demonstrated failing case cannot be `PASS`.

The verifier MUST NOT fix the implementation. It reports.

---

## 24.10 Verification verdict

`attempts/NN/verification.yaml`:

```yaml
milestone: M03
attempt: 2
commit: 9f1c2ab                  # exact commit verified
criteria_version: 3e7a…          # must equal state.yaml
verifier: { role: verifier, family: anthropic, model: sonnet }
verdict: FAIL                    # PASS | FAIL | BLOCKED | INVALID

acceptance:
  AC1: { result: PASS, tests: [acceptance/M03/test_obtain.py], run: runs/M03/02/9f1c2ab/acc.log }
  AC4: { result: FAIL, tests: [acceptance/M03/test_build_fail.py], run: runs/M03/02/9f1c2ab/acc.log }
  # ... every criterion id must appear

validity:
  AC4: { fails_on: mutant:ignore_exit_status, run: runs/M03/02/9f1c2ab/validity.log }

findings:
  - id: F1
    severity: major              # critical | major | minor
    criterion: AC4
    description: build.sh exit status is ignored; implementation reported READY after compilation failure.
    reproduction: acceptance/M03/test_build_fail.py::test_nonzero_exit
    evidence: runs/M03/02/9f1c2ab/acc.log

claim_audit:
  - claim: "AC4 satisfied"
    holds: false
    ref: F1

required_fixes:
  - propagate build process exit status (F1)
```

The orchestrator rejects a verdict file if any of the following hold:

- a criterion id is missing;
- `commit` or `criteria_version` does not match the current state;
- a cited `run` log does not exist;
- `PASS` is claimed for a criterion with no validity entry.

---

## 24.11 Rework loop, limits, and human gates

On `FAIL`, the builder gets the verification report and its logs, and fixes the code. A *new* verifier session re-runs both passes. Retained `acceptance/Mxx` tests are re-run as regression tests. The builder can never declare a finding resolved. Only a subsequent verifier `PASS` plus the orchestrator run does that.

Limits, in `workflow.yaml`:

```yaml
limits:
  max_attempts: 3                # build/verify cycles per milestone before escalation
  max_escalations: 2             # per milestone before mandatory human decision
  design_review_rounds: 3
  budget_per_milestone_usd: 25   # orchestrator stops dispatch when exceeded
```

Human gates:

| Gate | When |
|------|------|
| G1 | design approval |
| G2 | milestone plan approval |
| G3 | any escalation where the suspected fault lies in `DESIGN.md` or a milestone spec (the architect's own artifacts) |
| G4 | any exhausted limit (attempts, escalations, budget) |
| G5 | release of the integrated system |

The orchestrator does not proceed past an open gate.

---

## 24.12 Escalation

The orchestrator opens `escalations/ENNN.md` when any of these occur:

- the verdict is `INVALID`;
- `max_attempts` is reached;
- the builder disputes a verifier test or criterion in `build.md`;
- the builder reports a design deviation;
- a fix requires an architecture change.

The escalation file contains the spec, the last build and verification reports, the logs, and both sides' positions. Then:

- **If the dispute concerns implementation or verification only**, the architect arbitrates.
- **If it may concern `DESIGN.md` or a milestone spec**, the architect *proposes* a resolution, and a human decides (G3). The architect does not judge its own artifacts.

The resolution records exactly one classification:

```text
IMPLEMENTATION | VERIFICATION | MILESTONE_SPEC | ARCHITECTURE |
EXTERNAL_DEPENDENCY | PROTOCOL_SPEC | UNKNOWN
```

It also records exactly one outcome:

- `REWORK`, with guidance to the builder or a correction to a verifier test (the verifier applies it, not the builder);
- `DRAFT`, which triggers spec change control (24.13);
- `BLOCKED`, for an external dependency or a protocol-spec issue, with an owner and an exit condition.

---

## 24.13 Change control and invalidation

Verdicts are only as valid as their inputs. The orchestrator applies these rules:

| Change | Effect |
|--------|--------|
| `spec.yaml` of Mxx changes | Mxx → `DRAFT`; re-review required; new `criteria_version` |
| `DESIGN.md` changes | architect lists affected milestones in the change commit; those → `DRAFT` or `STALE`; G3 approves the list |
| code owned by a `COMPLETE` milestone changes (in a later milestone) | that milestone's acceptance suite must still pass on main; otherwise the later milestone fails integration |
| a dependency of Mxx becomes `STALE` | Mxx becomes `STALE` |

`STALE` milestones are re-verified before anything that depends on them proceeds.

---

## 24.14 Parallelism and integration

- Milestones whose dependencies are all `COMPLETE` may run concurrently. Each build and each verification runs in its own git worktree, created by the orchestrator.
- Integration is serialised. The orchestrator merges one `VERIFIED` milestone at a time into main. It then runs that milestone's acceptance suite **and the suites of every `COMPLETE` milestone** on the merge commit.
- A merge conflict or failing suite sends the milestone back to `REWORK`, with the integration log as the verification report.
- Requiring dependencies to be `COMPLETE` (integrated), rather than merely `VERIFIED`, before `READY` is deliberate. Builders always start from a known-good main.

---

## 24.15 Agent configuration

Project semantics depend on **roles**, never on vendors. There is exactly one configuration schema, split into committed policy and local mapping.

`workflow.yaml` (committed):

```yaml
roles:
  architect: { tier: high }
  reviewer:  { tier: high }
  builder:   { tier: standard }
  verifier:  { tier: standard }   # raise to high for security-sensitive milestones via spec.yaml
diversity:
  verifier_differs_from_builder: family   # SHOULD; values: family | model | session
  reviewer_differs_from_architect: family
limits: { ... }                           # 24.11
```

`agents.local.yaml` (not committed; one per participant):

```yaml
agents:
  claude-opus:  { family: anthropic, tier: high,     command: "claude -p --model opus {prompt_file}" }
  codex:        { family: openai,    tier: standard, command: "codex exec {prompt_file}" }
  sonnet:       { family: anthropic, tier: standard, command: "claude -p --model sonnet {prompt_file}" }
  local-qwen:   { family: local,     tier: standard, command: "aider --model ... {prompt_file}" }
  human:        { family: human,     tier: high,     command: "scripts/human-task.sh {prompt_file}" }
assign:
  architect: [claude-opus]
  reviewer:  [codex]
  builder:   [codex, sonnet]
  verifier:  [sonnet, codex]
```

Adapter contract: the command is run in the worktree with `{prompt_file}` substituted. It must exit when done. Its output is the files it writes. Anything satisfying this contract qualifies, including pi, Aider, a local model, a shell script, a human, or a future agent.

The orchestrator picks, per milestone, a verifier satisfying the `diversity` policy. If none is available, it falls back to `session` diversity. Session diversity is the minimum and is always required by I1. The diversity actually achieved is recorded in `metrics/`.

---

## 24.16 Role prompts (`AGENTS.md`)

`AGENTS.md` holds one versioned prompt template per role. The orchestrator renders them and records the template version used in each attempt's metrics. Templates state, at minimum:

**Builder**

```text
ROLE: BUILDER — milestone {id}, attempt {n}, base commit {sha}
Read: DESIGN.md, milestones/{id}/spec.yaml, {previous verification report if rework}
Implement ONLY this milestone.
You may write: source tree, your own tests, milestones/{id}/attempts/{n}/build.md.
You may NOT write: acceptance/**, spec.yaml, state.yaml. Such changes will be rejected.
If you believe a criterion or acceptance test is wrong, say so in build.md.
List everything you could not verify.
```

**Verifier**

```text
ROLE: VERIFIER — milestone {id}, attempt {n}, commit {sha}
PASS 1: Read DESIGN.md, spec.yaml, the protocol spec, and the code. Do NOT read build.md yet.
  For each criterion, write tests in acceptance/{id}/ that would show it false.
  For each criterion, provide a validity case (base commit or mutant) where your test fails.
PASS 2: Read build.md. Audit every claim, every "could not verify", every deviation.
Do not fix the implementation.
Write milestones/{id}/attempts/{n}/verification.yaml per the schema. Cite run logs.
```

---

## 24.17 Measuring whether the workflow works

The workflow is itself an experiment. Its success criteria are falsifiable.

**Recorded per milestone** (`metrics/Mxx.yaml`, written by the orchestrator):

- attempts;
- escalations, with their classifications;
- defects found by the verifier, by severity;
- **escaped defects**: defects attributed to this milestone but found later, during integration, by a later milestone, or in use;
- cost;
- wall time;
- builder and verifier families;
- prompt template versions.

**Success criteria for adopting this workflow** (evaluated at the end of the infrastructure project):

1. **Traceability.** Every `COMPLETE` milestone has a `PASS` verdict at its merged commit, validity cases for every criterion, and orchestrator logs. Checked by `orchestrator audit`.
2. **Enforcement.** Zero merged changes that violate path ownership. Zero state transitions not made by the orchestrator.
3. **Resumability.** A *resumption drill* passes at least twice during the project. The drill kills an in-progress milestone mid-build and mid-verification, starts a fresh session with a different model, and has it continue to a correct verdict using only the repository.
4. **Verification yield.** Verifiers find defects in a meaningful share of first attempts, and the share of defects that escape is low. If verifiers almost never find defects while defects do escape, verification is ineffective, and the prompts or diversity policy must be revised before the workflow is offered to others.
5. **Diversity signal.** Report escaped-defect rates for same-family vs cross-family verification. This is reported, not gated. It is the evidence base for recommending provider diversity to participants.

---

## 24.18 Reuse

Keep the **engineering workflow** (orchestrator, roles, file layout, `AGENTS.md`) conceptually and physically separate from the **protocol experimentation infrastructure**. In practice this means a separate directory or package, and no imports from the infrastructure into the workflow.

Do **not** build Hackathon-facing packaging, templates, or documentation for the workflow during this project. After the infrastructure project completes and the 24.17 criteria have been evaluated, extract the workflow based on what was actually used. The target usage remains:

```text
Internet-Draft → architect → design + milestone DAG → (builder ⇄ verifier)* → integration → interop evidence
```

---

## 24.19 Deliberately out of scope

- Autonomous operation without human gates.
- A GUI or service for the orchestrator. A CLI and files are sufficient.
- Automatic model selection by cost or performance. Assignment is static configuration; metrics inform humans who change it.
- Simultaneous multiple verifiers per milestone. Revisit only if 24.17(4) shows single-verifier yield is insufficient.

---

## 24.20 Wire evidence and test vectors

Added 2026-11-02 (architect proposal; human decision G1). **Exception to 24.18:** the human decided that wire-level evidence is needed for the IETF Hackathon before the infrastructure project ends. The rest of 24.18 still holds. The code lives in a separate package, `wire/`, which never imports `orchestrator.py`, and `orchestrator.py` never imports it.

**Why.** An interop claim is only worth the bytes behind it. Experience from the OSCORE multicast-notifications work (`~/Code/CoAP`, 26-cell matrix) showed five failure modes that unit tests and prose reports did not catch:
- L1: unit tests passed while end-to-end failed.
- L2: stale or vanished binaries gave hollow PASS results.
- L3: agents relabelled real bugs as "environment".
- L4: one model wrote both the implementation and its verifier.
- L5: the host topology broke the protocol's address assumptions.

**Experiment manifest** `interop.yaml`, owned by the experiment, not by AI2II:

```yaml
experiment: <name>
env_checks:   [{name, command}]                  # run first; any non-zero exit -> verdict ENV, nothing else runs
peers:        [{name, path, family, under_test: bool, build, binaries: [paths], start, ready: {command, timeout_s}}]
              # a client peer MUST exit non-zero when its expected exchange does not complete
capture:      {interface, filter}                # tcpdump; failure to capture -> BLOCKED
cells:        [{name, server: <peer>, clients: [<peer>...], checkers: [<checker>...], timeout_s}]
checkers:     [{name, family, observes_capture: bool, command, inputs: [paths], negatives: [{input: <path>, replaces: <path>}]}]
              # every cell lists its checkers; >= 1 of them has observes_capture: true and asserts that cell's exchange
              # in the captured bytes (the capture filter alone is not evidence)
```

Commands are argv strings (shlex-split, no shell) with the placeholders `{bundle}`, `{capture}` and `{inputs}`. Test vectors are checker inputs: they are copied into the bundle and hashed with it.

**Cell run.** The steps run in this order:
1. Env checks.
2. Delete every declared binary, then build every peer of the cell. The build must exit 0 and every declared binary must then exist; it is hashed and recorded with the build exit status. Because binaries are deleted first, a stale binary can never survive a failed build.
3. Start the capture.
4. Start the server, then wait for its readiness command.
5. Start the clients and wait for them, bounded by `timeout_s`.
6. Stop everything by process group.
7. Stop the capture.
8. Run each of the cell's checkers over the bundle.
9. Run each of those checkers once per declared negative (the validity check below). A checker that exits 0 on any negative makes the cell FAIL with reason `checker accepts negative: <name>`. Validity is therefore part of every run, never a separate step that can be skipped.

**Bundle** `<out>/<cell>/`:
- `capture.pcap`
- `<peer>.log` (stdout and stderr, per peer)
- `env.json` (peer commits and dirty flags, binary SHA-256, the manifest's SHA-256, the git commit and dirty flag of the experiment directory holding the checkers, the SHA-256 of each checker input and negative, tool versions, interface list, start and end UTC)
- `checker-<name>.log`
- `inputs/`
- `verdict.json`
- `SHA256SUMS` over every other file in the bundle. `verify-bundle` rejects modified, missing, unlisted or duplicate entries, and a `verdict.json` that is not one of the four verdicts. It proves integrity and layout only, not that the verdict is right.

**Verdict**, exactly one:

| Verdict | Only when |
|---|---|
| `ENV` | a declared env check failed (no peer was started) |
| `BLOCKED` | the experiment directory holding the manifest and checkers has uncommitted or untracked changes (so its commit identifies the checker code that ran), a peer build exited non-zero or did not produce a declared binary, or the capture could not start or recorded no packets |
| `FAIL` | anything else that is not PASS: a peer exited non-zero or timed out, a checker failed, or the run was interrupted |
| `PASS` | the experiment directory holding the manifest and checkers is clean in git, all peers exited 0 within the timeout, the capture is non-empty, every one of the cell's checkers exited 0 (including at least one `observes_capture` checker), and every one of them exited non-zero on every one of its negatives |

An agent or a human cannot assign `ENV` after peers have run (L3). A missing artifact is never PASS (L1, L2).

**Checker validity** (24.9, applied to wire evidence). Every `wire run` performs it (step 9). `wire validate-checkers` performs it alone, without peers, so authors can check their negatives early. Each checker runs once per declared negative, with `negative.input` substituted for `negative.replaces`. A checker that still exits 0 on any negative is rejected. Each `observes_capture` checker MUST declare at least two capture negatives: unrelated traffic, and the expected exchange with one direction removed. Both show that it checks the exchange, not merely that the capture is non-empty. One failing negative cannot prove a checker checks the claimed property. Negatives are the experiment's statement of what the checker distinguishes, and reviewers judge whether they suffice.

**Independence (L4)** is a *declared-policy* check, not proof of authorship. A checker whose declared `family` equals that of any `under_test` peer is rejected before anything runs. So is a missing or empty `family`. `env.json` pins the experiment directory's commit, and PASS requires that directory to be clean. So the checker code that produced a verdict is exactly that commit's, and can be traced through that repository's history. Whether that history shows who wrote it is outside `wire/`.

**Manifest validation** fails closed (exit 2) before any env check, build, start or capture. It rejects:
- duplicate peer, cell or checker names;
- a cell naming an undefined peer;
- a missing `family`, or an `observes_capture` that is not a boolean;
- a checker with no negatives;
- a negative whose `input` does not exist or whose `replaces` is not one of the checker's inputs or `{capture}`;
- a cell naming an undefined checker, or a cell with no `observes_capture` checker of its own.

**Not in scope:** pcap parsing or protocol knowledge in `wire/`. Decoding is the job of experiment checkers (tshark, Wireshark dissectors, independent verifiers). Also out of scope: multi-host orchestration and Wireshark dissector authoring.

**Replaces** the sequential `orch interop` command, which runs each peer's own tests and exchanges no packets between peers. It is removed from `orchestrator.py`.

**Self-challenge.**
- Is `cells` premature generality? No: the first real user already has 26 cells.
- Is `family` on checkers speculative? No: it is L4, observed.
- Are protocol terms leaking? The manifest has none; interface and filter are generic packet-capture terms.
- Does tcpdump add a dependency? It ships with macOS and most Linux distributions, but capture privileges vary, so a capture that cannot start is BLOCKED and never PASS. tshark is not required by `wire/`.
- What is the riskiest assumption? (a) That a green cell means the claimed exchange happened. Reviewer design-01 showed that unrelated traffic plus permissive checkers could pass, hence `observes_capture` and the two mandatory capture negatives. (b) That loopback is representative (L5). Env checks are mandatory, and the first OSCORE trial must run on the intended Hackathon interface before the runbook is published.

**Portability and summaries** (added 2026-11-04, G1, milestone M10).
- `capture.interface` may be the word `loopback`. The runner resolves it to the host's loopback interface (`lo0` on macOS and the BSDs, `lo` on Linux) before the capture starts, and records the resolved name in `env.json`. An interface that cannot be resolved makes the cell BLOCKED. The bundled examples use `loopback`. **First run** means the UDP-echo example (`./demo.sh`) on a macOS or Linux host with the documented prerequisites: Python 3.11+ with PyYAML, git, and tcpdump with capture permission. On such a host it needs no edits. A missing prerequisite must produce a verdict or message that names it, never a PASS.
- When a peer fails but the capture is non-empty, the runner still runs the cell's checkers on the capture and keeps their logs. The verdict stays FAIL with the peer's reason, so the checker log shows what the wire contained.
- `wire summarize <dir>` reads every bundle under a directory and prints one row per cell: experiment, cell, verdict, reason, experiment commit, and each peer's commit and dirty flag. With `--json` it prints a list of these records. It reads the bundles only and runs nothing. It finds bundles as directories containing `verdict.json` or `SHA256SUMS`, at any depth. For a bundle that fails `verify-bundle`, the verdict, reason and commits are untrusted claims: the text output shows the verdict as `UNVERIFIED(<claimed verdict>)`, and the JSON record has `verified: false` with the claimed fields under `claimed`. A missing or malformed `verdict.json` gives `verdict: null` and an `error` field.
- Build commands should force a clean build. The runner deletes declared binaries, not intermediate build products, and a binary linked from stale objects is a hollow PASS (seen in the first OSCORE N1 bundle). This is a rule for experiment authors; the runner cannot detect it.

## 24.21 Secured protocols: exported keys and decrypted captures

Added 2026-11-03 (architect proposal; human decision G1). Extends 24.20. Same package `wire/`, same independence from `orchestrator.py`.

**Why.** Many Hackathon protocols are secured (TLS, DTLS, QUIC, Matter, OSCORE). A capture of a secured exchange proves that packets flowed, but not what they carried. Reviewers need both views: the encrypted trace as it was on the wire, and a decrypted view they can open themselves. The keys must come from the implementation under test, never from a guess.

**Mechanism.** It is protocol-neutral: `wire/` knows environment variables, files and commands, never a cipher suite or key format.
- **Peer secrets.** A peer may declare `env: {VAR: value}` and `secrets: [<file name>]`. A secret name is a plain file name (`[A-Za-z0-9._-]+`, not `.` or `..`, no path separator), unique across all peers. Anything else fails manifest validation, so a secret can never point outside `secrets/` or at another bundle artifact. Before peers start, the runner creates `{bundle}/secrets/`. The `{secrets}` placeholder is valid in a peer's `env`, `start` and `ready`. Example: `env: {SSLKEYLOGFILE: "{secrets}/client.keys"}` for TLS, DTLS and QUIC stacks that support the key log format. For OSCORE, a context dump written by the peer. After the peers stop, every declared secret must exist as a non-empty regular file (not a symlink). Otherwise the verdict is BLOCKED and decryption does not run.
- **Decrypt step.** It is optional, at experiment level: `decrypt: {command}`. It runs after the capture stops (24.20 step 7) and before the checkers. It must write `{decrypted}` (`{bundle}/capture-decrypted.pcapng`). The command belongs to the experiment, for example `editcap --inject-secrets tls,{secrets}/client.keys {capture} {decrypted}`, giving a self-decrypting pcapng, or `tshark -U "OSI layer 7"` for exported cleartext PDUs. A decrypt command that exits non-zero, or leaves `{decrypted}` missing or empty, makes the cell FAIL (`decrypt failed`). Its output goes to `decrypt.log`. `env.json` records the decrypt command's executable, resolved through `PATH` to an absolute path, with its SHA-256. A script it runs from the experiment directory is pinned by that directory's commit (24.20).
- **Two views, both kept.** `capture.pcap` is never modified. `capture-decrypted.pcapng`, `decrypt.log` and `secrets/` join the bundle and `SHA256SUMS`.
- **Checkers.** A checker may set `observes_decrypted: true` and use `{decrypted}`.

In an experiment with `decrypt`, validation requires every cell to have:
- an `observes_capture` checker, as in 24.20, with at least one negative marked `asserts: encrypted`. That negative is a capture of the same exchange in cleartext, which the checker must reject. This proves that security was actually on, on the wire.
- an `observes_decrypted` checker with two kinds of negative:
  - one that `replaces: "{secrets}/<file>"` with wrong secrets. For that negative the runner re-runs the decrypt step with the replacement file into a scratch location, then runs the checker on that result. The canonical `capture-decrypted.pcapng` is never touched.
  - one that `replaces: "{decrypted}"` with a decrypted view of a different or altered exchange, while the real secrets stay in place.
  
  The checker must exit non-zero on both. The first shows that its success depends on the right keys. The second shows that it reads the decrypted traffic, not merely the key material.

**Verdict additions** to the 24.20 table:
- BLOCKED: a declared secret file is missing or empty.
- FAIL: the decrypt step failed.
- PASS additionally requires every `observes_decrypted` checker to pass and to reject its negatives.

**`verdict.json`** gains `contains_secrets: true` when `secrets/` is non-empty.

**Key handling.** Bundles with secrets are self-decrypting by design. Experiments use test keys only. `contains_secrets` lets tooling and reviewers refuse to publish such bundles outside the lab. `wire/` cannot tell test keys from real ones, so this is a declared rule, not an enforced one.

**Not in scope:**
- Protocol-specific decryption in `wire/`.
- Rewriting the original packets into valid cleartext packets. No general tool exists; an experiment may ship one as its decrypt command.
- Decoding Group OSCORE. Stock Wireshark is not assumed to support it (unverified), so such experiments ship an independent decoder as their decrypt command or checker (24.20 independence rule).

**Self-challenge.**
- Does `env` on peers generalise prematurely? No. Key logging in TLS stacks is driven by an environment variable (`SSLKEYLOGFILE`), and argv strings without a shell cannot set one.
- Is the `asserts: encrypted` marker protocol leakage? No. It states what a negative is for, not how to recognise encryption.
- What is the riskiest assumption? That the decrypted view reflects the wire. Mitigations:
  - the raw capture is kept;
  - an `observes_capture` checker must still pass on it;
  - the decrypt executable is hashed, the experiment's scripts are pinned by its commit, and the secrets are in `SHA256SUMS`;
  - the wrong-secrets and replaced-view negatives together show that the decrypted checker depends on real decryption of this exchange.
- Second risk: secrets leaking through shared bundles. Mitigation: `contains_secrets` and the test-keys-only rule.
