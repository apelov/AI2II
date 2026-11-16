# AI2II improvement plan (revised)

16 Nov 2026. Revised after a critical review of the first version, which was too large, ignored
`DESIGN.md` 24.17-24.18, and ranked work by how cheap it was rather than by what went wrong.

Inputs: `POST-HACKATHON-ANALYSIS.md` (WIMSE, SCHC-VXLAN, the `oscore-n1` PR). That evidence is
thin: three projects, two run by the same person, analysed by the sessions that did the work, and
one known only from its PR description. Everything below is a hypothesis to test, not a finding.

## 1. Principles for this plan

1. **Thin layer first.** What worked at the hackathon was a contract, an independent checker, a
   bundle and cross-model review. The heavy machinery cost more than it returned. Add nothing
   that a two-day project cannot carry.
2. **A rule is either checked or it is advice.** `DESIGN.md` says a MUST is checked mechanically.
   New rules must come with the check, or be written as SHOULD.
3. **Keep workflow and infrastructure apart** (`DESIGN.md` 24.18). `wire` runs evidence;
   project-start and process tooling live elsewhere. `kickoff` was moved out of `wire` for this
   reason.
4. **Measure before extending.** Use the 24.17 metrics (escaped defects, same-family versus
   cross-family verification) and a trial before building more.

## 2. Audiences

The goals pull in different directions, so name who each change serves.

| Audience | Needs |
|---|---|
| Hackathon newcomer | one start step, a first bundle in an hour, no orchestrator |
| Project lead running agents | rails the agents actually read, separation between implementations, honest reporting |
| Working group and draft authors | an interop matrix, vectors, a dissector, a list of spec ambiguities |

## 3. Goals

| # | Goal | Measured by |
|---|---|---|
| G1 | No published claim overstates the evidence | count of claims later corrected (WIMSE: the live-testnet count, the case totals, the partner mapping) |
| G2 | Interop failures turn into fixes or spec Open Issues | share of FAILs that end as a fix in one implementation or an Open Issue sent to the authors |
| G3 | Independence is enforced by separation, not declared | for each pair: separate repository or directory, separate session, no read access to the other's code |
| G4 | A newcomer can start alone | time from clone to first valid bundle; did they need to ask the team |
| G5 | Partners agree with how they are described | every partner confirms its rows before publication |

G5 is new. The WIMSE corrections were mostly social: a wrong affiliation, a repository linked
without permission, mocked cases counted as live.

## 4. What to do now

Each item has an effort estimate, a test of whether it worked, and a condition to stop.

### 4.1 Trial `kickoff` on a real project (first)

Start the next new project with `kickoff` and the generated `AGENTS.md`. Not a finished
project: preparing a trial on WIMSE showed that `kickoff`'s questions ("what do you want to
achieve?") make no sense for a project whose goal and results are already written down (see 4.5). Record whether agents state the goal back, use claim classes, write provenance and
keep implementations apart, without being reminded.

- Effort: one project.
- Worked if: agents follow the rails unprompted in most sessions.
- Stop if: they ignore them; then the problem is not the template, and more template will not fix
  it. Look at hooks that inject the rules into every session instead.

### 4.2 One generated results file with a claim class per case

`wire summarize` already reads every bundle. Extend it to write `RESULTS.md` (or a table embedded
in it) from the verdicts, with a claim class per row, and add a check that fails when the file
differs from what `summarize` would generate. This replaces hand-written counts, and it replaces
the idea of linting prose for "PASS" and "live", which would be brittle.

**Done** (16 Nov): optional `claim_class` per cell (`observed-on-wire` by default,
`replayed-recording`, `simulated`, `mocked`), copied into `verdict.json`;
`wire summarize DIR --update RESULTS.md` writes the block, `--check RESULTS.md` fails on a hand
edit or a stale block; bundles older than the change show as `unlabelled`. Results without a
bundle (partner-attested, not run) go in a hand table outside the block, as `kickoff`'s
`RESULTS.md` shows.

- Limit: the class is per cell. A cell that mixes classes, like WIMSE's `chain` cell (wire traffic
  plus replayed sandbox outcomes), must be split into cells to be labelled honestly.

### 4.3 The black-box pair, enforced by separation

The practice that worked best was two implementations developed separately and treated as black
boxes. Make it structural rather than a rule agents are asked to follow:

- each implementation in its own repository, or a directory its agent cannot read outside of;
- each agent session given only the spec, the vectors and its own code;
- the checker and dissector built from the spec in a context that has no implementation source.

Interop agreement is not proof of correctness: two implementations can share a misreading of the
spec. So the shared vectors must be written from the spec by someone other than either
implementer, and disagreements are settled by the spec, not by majority.

- Effort: documentation plus a `kickoff` question about where each implementation lives.
- Worked if: in the next project, neither implementation's history shows access to the other.

### 4.4 Partner confirmation before publication

A short step in the runbook and `RESULTS.md`: each named partner confirms their row, affiliation
and credit, and whether their material may be relicensed or linked. Nothing is published until
they have.

- Effort: documentation only.

### 4.5 `kickoff` for an existing project

`kickoff` only fits the first minute of a new project. For a project that already exists it
should read what is there (drafts named in the docs, implementations and families in
`interop.yaml`, existing results) and ask the human only to confirm or correct, then add the rails
without touching the project's files. It already keeps an existing `interop.yaml`.

- Effort: small to medium.
- Worked if: running it on WIMSE asks only confirmation questions, and surfaces contradictions in
  the repository (WIMSE's `interop.yaml` and `SCENARIOS_AND_AUTHORS.md` disagree on who wrote the
  chain peers) instead of asking what the project is for.

## 5. Deferred, with the trigger that would bring each back

| Item | Why deferred | Bring back when |
|---|---|---|
| Intents beyond three | Seven intents added questions without evidence they help. Three cover the hackathon: draft, implement, interop | a trial shows a fourth case does not fit |
| `wire matrix` runner | a shell loop over cells plus 4.2 gives the table | a project has more than about ten cells |
| Per-link captures | needed only with multi-node topologies | the topology work starts |
| Docker topology and link profiles | unproven on macOS; poor fit for TAP, bridge and throughput work like SCHC-VXLAN; prior art not reviewed | prior art is reviewed (QUIC interop runner, containerlab, ns-3/Mininet style tools) and a project needs it |
| Multi-host cells | the largest real gap, but needs a design for merging captures and clocks | a partner interop session is planned |
| Structured event logs | they make the implementation emit a format, which breaks the black-box rule and excludes existing code; they are also self-reported by the peer under test | only as an optional, declared artifact, preferably in an existing format such as qlog |
| Spec traceability matrix | valuable for the WG, but costly to keep up to date | a draft is close to WGLC |
| Tool-readiness smoke test | cheap and useful (SCHC lost most time here), but outside `wire` | next time agents from several vendors are used; put it in `kickoff` |
| CI for contributed bundles | useful for PRs like `oscore-n1` | a second external contribution arrives |
| Docker in `DESIGN.md` | reversing "out of scope" is a design decision | the two Docker checks above are done |

## 6. What this plan does not claim

- That the black-box pair is the best pattern in general. It worked in one project.
- That `kickoff` changes agent behaviour. It has not been tried.
- That any of this is ready for other projects. `DESIGN.md` 24.18 says to evaluate the 24.17
  criteria first; that evaluation has not been done and should come before wider promotion.
