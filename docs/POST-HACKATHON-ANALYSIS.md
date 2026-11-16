# AI2II post-hackathon analysis (IETF 127): three projects, one process

Scope: the 14-15 Nov 2026 work on three projects that used the AI2II approach (the third, an external contribution, is in section 5):

- **WIMSE** (`apelov/IETF127-Hackathon-AI2II-WIMSE`, pushed at `0f3f9af`): WIMSE/OAuth agent call-chain interop. Analysis: `POST_HACKATHON_ANALYSIS.md` in that repo.
- **SCHC-VXLAN** (`apelov/SCHC-VXLAN-Fragmentation`, branch `impl-c-dev` at `fc7dfd7`): a SCHC No-ACK profile over VXLAN, with C and Rust implementations. Analysis: `docs/POST-HACKATHON-ANALYSIS.md` in that repo.

Method: the two per-project analyses above, the PR description of the third project (`apelov/AI2II` PR #1, read but its code and bundles not re-run), written by their orchestrating sessions, plus a diff of `wire/`. The AI2II orchestrator session was not consulted and `DESIGN.md` was not re-read for this document, so statements about the orchestrator come from those two analyses only.

## 1. What each project actually used

| AI2II part | WIMSE | SCHC-VXLAN |
|---|---|---|
| `wire/` evidence bundle, L4 checker rule | **Used.** Vendored; identical to `AI2II/wire/` apart from `example/` (no divergence) | Not used. Shared vectors plus `check_vectors.py` and a Lua dissector played the checker role |
| Orchestrator, milestones, human gates | Not used | Not used. The `agentwork` sealed pipeline (a different template) built the first draft only |
| Multi-model delegation | Nemotron, Opus, Gemini, Mistral as reviewers; Claude and others as builders | Opus, Fable, Sonnet, Codex, Gemini, Mistral as workers and reviewers |
| Verification target | Loopback pcap; part simulated or mocked | Real lab: C and Rust over a 1280-byte underlay, 530-730 Mbit/s |

Finding: in both projects the value came from a thin layer (a contract, an independent checker, cross-model review). The orchestrating machinery was unused in one and cost more than it returned in the other.

## 2. What worked in both

1. **A contract fixed before the code.** WIMSE: scenarios plus `interop.yaml` cells. SCHC: draft, `wire-vectors.json`, `check_vectors.py`. Disagreements became checkable instead of arguable.
2. **A checker the implementers do not own.** WIMSE: tshark-based `observes_*.py` that must fail its negative mutants. SCHC: a Lua dissector written from the draft only. Both located real faults by decoding bytes.
3. **Cross-model review that executed something.** Opus (WIMSE) re-dissected the pcap and verified crypto itself; Mistral Vibe flipped bytes in WIMSE and found a real destroyed-state defect in the SCHC C code. Fable found 3 blockers in the SCHC draft. Reviews that only read text produced the noise.
4. **Small packages with a one-line verify command**, validated by the orchestrator on the real target.
5. **A review → triage → fix loop** with commits tied to findings.

## 3. What hurt in both

1. **Independence was declared, not kept or shown.**
   - WIMSE: all three checkers say `family: nvidia` in `interop.yaml`, but nothing shows that family wrote `observes_chain.py` or `observes_p1_p8.py`; the runner compares declared strings.
   - SCHC: both implementations ended Claude-family (C finished by Sonnet, Rust by Andrii with Claude). The argument survives only because the vectors and dissector are independent.
2. **Delegated results were not trustworthy until re-run.** SCHC: Codex exited 0 after writing no code; a sub-agent reported fuzz runs it had not checked. WIMSE: a non-executing reviewer produced about one real finding per four false ones, and "7/7 live testnet" was reported where two cases were fixed mocks.
3. **Claims drifted from evidence.** WIMSE: hand-kept counts (85/92/"32/32"), a bundle pinned to an older commit than HEAD, a stale README. SCHC: stale paths after a file move.
4. **Model and tool churn with no written policy.** Limits and eligibility errors forced switches mid-stream (SCHC); reviewers of mixed capability were used without a protocol (WIMSE).
5. **No provenance record.** Which model wrote or reviewed what is in commit messages (SCHC) or prose tables (WIMSE), with no prompts or transcripts, so independence cannot be audited.
6. **No CI.** The only gates were scripts run by hand (`reproduce.sh`) or builds on one Mac. Linux issues (GCC warnings, checksum offload) were caught late, in the lab.
7. **No threat or hazard register** carried across reviews; findings were lost between rounds (WIMSE: Mistral F1, Opus A9, B7, C1-C7 still open).

## 4. Where the projects differ, and what each teaches the other

- **SCHC verified on the real target; WIMSE mostly did not.** SCHC's namespace test and lab bring-up separated its bugs from interop bugs. WIMSE's evidence was loopback, replayed recordings, partner traces and mocks, summed as one pass count. The fix is to say what each result is (section 7, item 2), not to run everything live.
- **SCHC kept a frozen contract with explicit Open Issues; WIMSE had no decision log or traceability.** WIMSE should adopt Open Issues and a human-owned decision log; the P1-P8 matrix would give it the traceability SCHC got from the draft.
- **WIMSE had a reproducible, hash-checked bundle; SCHC had none.** SCHC results were recorded by hand. A `wire` bundle per interop run would make them reproducible.
- **SCHC wrote a handoff file at milestones (`HANDOFF.md`).** WIMSE's equivalent (`VERIFY.md`) went stale. The handoff should be generated from verdicts.
- **Safety habits on shared hardware (read-only first, revert timer, runtime-only changes)** exist only in SCHC. Worth writing down once for any lab-touching experiment.

## 5. Third data point: an external contributor on `oscore-n1`

Chun-Yu Yen (Jenny) worked alone during the event (commits of 14 Nov), without contact with the team, and opened PR #1 on `apelov/AI2II`, merged on 16 Nov. She wrote a Python client and server for CoAP Observe multicast notifications (nosec profile of `draft-ietf-core-observe-multicast-notifications-15`) from the draft text, then ran two `wire` cells against the existing C implementation: `N1-py` (C server, Python clients) and `N1-pyserver` (Python server, C clients). Both are reported PASS with all 7 `observes-n1` checks and all 5 negatives rejected, with `verify-bundle` OK. She also ran exploratory adversarial tests (no bundle) and reports 7 issues in the C client, plus 4 points of draft feedback. All of this is from her PR description.

What it adds:

- **Good practice worth copying.** `RESULT.md` has a section "What each PASS shows"; exploratory runs are labelled as having no bundle and no independent checker; the family limit is stated outright (all implementations anthropic, checker google); and Linux and Group OSCORE are listed as not tested. This is the claim-class discipline recommended in section 7, done by hand.
- **Same independence gap as the other two projects.** Every implementation under test is from one family, so only the checker is independent.
- **A checker coverage gap.** `observes-n1` mostly asserts server behaviour (checks 3-7). In `N1-py` the Python client is therefore checked only by its own exit code and log, and `N1-pyserver` is where the checker really tests the Python code. A PASS says something different about each peer, and the verdict does not say which.
- **Onboarding, not tooling, was the barrier.** She could not connect with the team during the event and completed the work alone; the runbook, the submission template and the clean-machine test were enough for that.
- **Adversarial testing found more than the conformance cells.** The 7 C-client issues came from the exploratory runs, which have no evidence bundle. This supports giving negative-peer tests a bundle form.

## 6. Template or usage? Both, and mostly usage

AI2II has rails: a worker contract with roles (`AGENTS.md`), a gated build flow (`./orch`) that runs
tests itself, the `wire` runner and a runbook. The projects mostly did not use them, and the reason
is visible in the repositories:

- **The agents never saw the rails.** Agents follow the `AGENTS.md`/`CLAUDE.md` in their working
  directory and the prompts they are given. WIMSE had neither file; its work packages followed a
  different template that is not even in the repository, and `wire/` arrived as code with no rules.
  SCHC-VXLAN had an `AGENTS.md`, from the separate `agentwork` template. The AI2II rails lived in a
  sibling repository.
- **Nothing told the human or the agent where to start.** The runbook began with installing and
  describing an experiment; there was no step that asks what the project is for, who builds, who
  checks and what counts as success. `HACKATHON.md` labelled the agent-build path "optional".
- **When the rails were in front of the worker, they were used.** Jenny worked alone from
  `HACKATHON.md` and `SUBMISSION.md`, and her result is the most disciplined of the three.

So the template has real gaps (no scaffold, advisory rules, all-or-nothing orchestrator, no claim
classes or provenance), but the larger failure was how it was started: by not putting the rails in
the agents' context, and not deciding goal, roles and success criteria at the beginning.

**Fix, implemented (first version):** `python3 -m kickoff DIR` is now the first step. It is a separate package, not part of `wire`, following DESIGN.md 24.18. It has not yet been tried on a real project, so whether agents follow what it writes is untested. It asks the goal, success
statement, scope, protocol authority, mode, implementations and their model families, checker
family, reviewer, and any non-live data. It refuses a checker from an implementation's family, warns
when every implementation comes from one family, and writes `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`,
`PROJECT.md`, an `interop.yaml` skeleton, `PROVENANCE.yaml` and `RESULTS.md` into the project. Agents
without a terminal run `kickoff --questions`, ask the human, and pass `--answers`
(`docs/KICKOFF.md` has the prompt to paste). It is the first row of the README and step 0b of the
runbook.

**Still advisory:** the rules in the generated `AGENTS.md` are not enforced by any tool yet. The
next step is a check that fails when a document claims PASS, live or a count that no `verdict.json`
supports (section 7, item 1).

## 7. Keep, drop, add

**Keep**
- Contract-first; explicit Open Issues; shared vectors with an executable checker.
- Independent checker or dissector, and mandatory negative mutants.
- Cross-model review, restricted to reviewers that can run commands.
- Hashed evidence bundles and `reproduce.sh`.
- A namespace or loopback integration test before any lab.

**Drop or demote**
- The sealed multi-agent pipeline for prose and early drafts (SCHC measured the cost). Keep it only for large, stable code builds.
- Rungs and automatic escalation, goldfish audit beyond `owns`/`inputs` validation, and sealed design files (use a design log).
- Four overlapping hand-written summary documents (WIMSE); generate one from verdicts.
- Non-executing reviewers as a gate.

**Add (ordered by return)**
1. **Claims generated from verdicts, plus a drift gate.** Every number or PASS in docs and slides comes from verdict files; the gate fails when a bundle's commit differs from HEAD.
2. **A claim class on every case:** `observed-on-wire | replayed-recording | simulated | mocked | partner-attested | not-run`. Reports print the breakdown, never one pass count.
3. **Checker honesty tests.** Each checker exits non-zero when its target is unreachable and fails its own mutants. Enforced in CI.
4. **A provenance record per artifact:** model, tool access, prompt reference, transcript hash. Make the L4 check compare author and checker from that record instead of declared strings.
5. **Session-start tool-readiness check and a written model-routing policy** (who builds, who reviews, who validates, fallback order). From SCHC.
6. **Reviewer protocol:** every finding carries a reproducible command and its output; triage (accepted, rejected, why) is a committed file feeding a findings register with owner and status.
7. **Linux CI:** build with sanitizers, vectors, checkers on committed captures, negative mutants.
8. **Shared receiver or scenario scripts** next to the vectors (order, loss, duplicates, deadlines), not byte vectors alone. From SCHC.
9. **A results template** (setup, versions, counters, captures, conclusion, corrections) and a **performance checklist** (throughput, daemon CPU time, kernel drops) before blaming a peer. From SCHC.
10. **A per-cell coverage statement:** for each peer, which checks actually observe it on the wire and which rest on exit codes or logs. From the `oscore-n1` PR.
11. **A bundle form for adversarial runs** (misbehaving peers, no independent checker) so error-path findings are reproducible and labelled.
12. **Seal late:** only after an independent design review, otherwise use a light plan and checklist.

## 8. Concrete changes to this repository

Done: `kickoff` and `docs/KICKOFF.md` (section 6). The rest are proposals.

- `wire/`: add an optional `claim_class` field per case to the verdict schema, and a `verify-bundle --fresh` mode that fails when `verdict.json` commits differ from HEAD.
- `wire/` L4 check: read author family from a provenance file instead of `interop.yaml` strings.
- An enforcement check (CI or pre-commit, usable from a Claude Code hook): fail when README, RESULTS or slides state a PASS, "live" or a count that no `verdict.json` supports.
- `kickoff`: add a tool-readiness smoke test per model CLI (auth, model id, sandbox can write, exit code reflects failure), and record the answers' routing in `PROVENANCE.yaml` automatically.
- `docs/BEST_PRACTICES.md`: add the patterns "claims from verdicts", "mocks must be labelled", and "reviewer must execute".
- Done by `kickoff`: the start step and model routing (runbook step 0b), claim classes in the generated `AGENTS.md`, a results template and a review-triage table in `RESULTS.md`, a decision log and Open Issues in `PROJECT.md`.

## 9. Conclusion

All three projects reached working results quickly, and all would have been stronger with less ceremony and more evidence discipline. AI2II's core idea held up three times: a contract, an independent checker that must fail its negatives, and review by another model.

Its weak spots were the same in all three and sit outside the checker: independence nobody could verify, delegated claims nobody re-ran, and documents that drifted from the evidence. The cheapest improvements are generated claims, per-case claim classes, and provenance records.
