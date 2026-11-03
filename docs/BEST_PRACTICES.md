# AI2II Best Practices & Continuous Improvement Log

This document captures patterns, tools, and improvements discovered during use of the AI2II orchestrator. Each entry represents a lesson learned that feeds back into the tooling.

---

## 📋 Improvement Categories

| Type | Description | Examples |
|------|-------------|----------|
| **pattern** | Reusable prompting/steering pattern for agents | "Mutant injection for protocol edge cases" |
| **tool** | New tool or script that extends orchestrator | `orchestrator.py interop`, mutant generator |
| **prompt** | Improved role prompt template in AGENTS.md | "Add explicit negative test requirements" |
| **workflow** | Process improvement in milestone lifecycle | "Add pre-commit hook for criteria_version" |
| **metric** | New measurement for workflow effectiveness | "Escaped defect rate by model family" |

---

## 🔄 Continuous Improvement Loop

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Run Milestone  │────▶│  Capture Issues  │────▶│  Record in       │
│  (builder/      │     │  & Patterns      │     │  improvements/   │
│   verifier)     │     │                  │     │                  │
└─────────────────┘     └──────────────────┘     └────────┬─────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Update         │◀────│  Generalize to   │◀────│  Review at       │
│  Tooling/       │     │  Reusable Asset  │     │  Milestone Review│
│  Prompts/Docs   │     │  (pattern/tool)  │     │  (G2 gate)       │
└─────────────────┘     └──────────────────┘     └──────────────────┘
```

**Trigger points for improvement capture:**
1. **After each milestone** - builder/verifier retro captures patterns
2. **After each escalation** - architect records classification lessons
3. **After interop runs** - cross-impl failures → new test patterns
4. **After model benchmark** - model performance → assignment updates

---

## 📚 Captured Best Practices (Living Document)

### Pattern: Mutant Injection for Protocol Verification
**Context**: M03 test-validity requirement (§24.9)
**Problem**: Tests that pass at base commit give false confidence
**Solution**: Verifier *must* demonstrate test fails on:
- Base commit (pre-implementation), OR
- Minimal mutant (e.g., invert condition, ignore exit code, truncate buffer)

**Template** (added to AGENTS.md verifier prompt):
```text
For each criterion, provide a validity case:
  fails_on: base             # test fails on pre-implementation commit
  fails_on: mutant:<name>    # minimal deliberate break, saved as acceptance/Mxx/mutants/<name>.patch
```

**Mutant Library** (reusable across protocols):
| Mutant | Description | Applies To |
|--------|-------------|------------|
| `ignore_exit_code` | Builder ignores subprocess return code | Build systems |
| `invert_condition` | `if x > 0` → `if x <= 0` | Boundary checks |
| `truncate_buffer` | Read N-1 bytes instead of N | Buffer parsing |
| `skip_validation` | Remove `validate()` call | Protocol parsers |
| `wrong_constant` | Change magic number/version byte | Wire format |

---

### Pattern: Specification-Driven Test Generation
**Context**: Goal 2 (draft-only → implementation)
**Problem**: Verifier writes tests from draft alone; builder implements from draft alone
**Solution**: Both use *same* draft sections as source of truth

**Prompt template for verifier**:
```text
PASS 1: Read draft Section {N}.{M}. For each requirement:
  - Write test that would FAIL if requirement not met
  - Name test: test_{section}_{requirement}_{positive|negative|edge}
  - Include mutant injection point
```

**Prompt template for builder**:
```text
Implement draft Section {N}.{M}. Requirements:
  - {requirement_1}
  - {requirement_2}
  ...
Run: ./orchestrator.py run-tests Mxx NN acceptance
```

**Result**: Tests and implementation derive from same source → traceability

---

### Tool: Interop Matrix Runner (`orchestrator.py interop`)
**Context**: Goal 4 (run interop between implementations)
**Evolution**:
1. v1: Pairwise test execution, manual comparison
2. v2: Automated result comparison (JSON diff of test outputs)
3. v3: Docker-based isolation, parallel execution, CI integration
4. v4: Conformance badge generation (SVG for README)

**Usage**:
```bash
# Pairwise interop between 3 implementations
./orchestrator.py interop M03 ./impl-rust ./impl-go ./impl-python \
  --matrix pairwise --output interop-M03

# Smoke test against reference implementation
./orchestrator.py interop M03 ./impl-rust ./impl-go ./impl-python \
  --matrix smoke --output interop-M03-smoke
```

---

### Tool: Model Configuration & Benchmarking (`orchestrator.py models`)
**Context**: "Enable use of different models" + diversity policy
**Features**:
- `models.yaml` - declarative model registry (provider, model, tier, command)
- `orchestrator.py models add/remove/list` - CLI management
- `orchestrator.py models test --name <model>` - smoke test model
- `orchestrator.py models benchmark --role <role>` - compare models for role

**Diversity enforcement** (from workflow.yaml):
```yaml
diversity:
  verifier_differs_from_builder: family   # family | model | session
  reviewer_differs_from_architect: family
```

**Model assignment strategy**:
| Role | Tier | Preferred Families | Fallback |
|------|------|-------------------|----------|
| Architect | high | anthropic | human |
| Reviewer | high | anthropic, openai | human |
| Builder | standard | openai, anthropic, local | human |
| Verifier | standard | anthropic, openai, local | human |

**Benchmark dimensions** (run quarterly):
| Dimension | Measurement | Target |
|-----------|-------------|--------|
| Correctness | % acceptance tests pass | >95% |
| Completeness | % criteria covered | 100% |
| Token efficiency | tokens per criterion | <50k |
| Diversity yield | defects found by cross-family vs same-family | >2x |

---

### Pattern: Structured Feedback to Draft Authors (Goal C)
**Context**: Hackathon deliverable C
**Template** (auto-generated from verification.yaml):
```markdown
## Draft Feedback: {draft_name}

### Ambiguities Found
{from verifier "could not verify" items + escalations}

### Test Vectors Contributed
- Positive: {count} | Negative: {count} | Edge: {count}
- Location: acceptance/Mxx/test_{criterion}.py

### Implementation Decisions Requiring Clarification
- [ ] Section {N}: {specific_question}
- [ ] Appendix {X}: {specific_question}

### Bugs in Reference Implementation
- [ ] {file}:{line} - {description} (found by mutant: {mutant_name})
- [ ] {file}:{line} - {description} (found by interop: {other_impl})

### Conformance Test Results
- Implementations tested: {list}
- Interop matrix: {link_to_report}
- All pass: {yes/no}
```

---

### Workflow: Pre-Commit Hook for Criteria Versioning
**Context**: Invariant I2 (criteria fixed before implementation)
**Problem**: Developers accidentally modify spec.yaml during implementation
**Solution**: Git pre-commit hook that checks criteria_version

```bash
# .git/hooks/pre-commit
#!/bin/bash
# Reject commits that change spec.yaml without updating criteria_version
if git diff --cached --name-only | grep -q "spec.yaml"; then
    echo "ERROR: spec.yaml modified. Update criteria_version in state.yaml first."
    echo "Run: ./orchestrator.py invalidate --files milestones/Mxx/spec.yaml"
    exit 1
fi
```

---

### Metric: Escaped Defect Tracking (24.17.4)
**Context**: Workflow success criteria
**Definition**: Defect attributed to milestone Mxx but found *after* COMPLETE
**Measurement**:
```yaml
# In metrics/Mxx.yaml
escaped_defects:
  - id: ED-001
    milestone: M03
    found_during: M05_integration
    severity: major
    description: "Interop failure with Go impl - nonce reuse not detected"
    root_cause: "Verifier mutant didn't cover cross-session nonce reuse"
    fix: "Added mutant: reuse_nonce_across_sessions"
```

**Dashboard query** (run at project end):
```bash
# Escaped defect rate by model family
./orchestrator.py audit --escaped-by-family
```

---

## 📁 Improvement Storage

```
improvements/
├── improvements_log.yaml          # All improvements (append-only)
├── edcef573_pattern.yaml          # Individual improvement files
├── a1b2c3d4_tool.yaml
├── ...
└── tags_index.yaml                # Tag → improvement IDs mapping
```

**Improvement schema**:
```yaml
id: "edcef573"           # Short UUID
type: "pattern"          # pattern | tool | prompt | workflow | metric
description: "..."       # One-sentence summary
context: "M03..."        # Where discovered
author: "claude-opus"    # Who discovered it
tags: ["network", "retry"]
timestamp: "2026-10-14T22:15:00Z"
status: "proposed"       # proposed | adopted | rejected | superseded
adopted_in: "M04"        # Milestone where adopted
supersedes: "a1b2c3d4"   # If replaces previous
```

---

## 🎯 How to Use This in Practice

### During Hackathon (or any sprint):

1. **Morning standup**: Review `improvements/` for relevant patterns
2. **During work**: When you hit friction, run:
   ```bash
   ./orchestrator.py improve pattern "Description" --context "M03 builder" --tags "tag1,tag2"
   ```
3. **End of day**: Review new improvements, adopt obvious ones
4. **Milestone review (G2)**: Architect reviews improvements log, promotes to tooling/docs
5. **Project end**: Publish `BEST_PRACTICES.md` as reusable artifact

### For Model Evolution:

```bash
# Add new model
./orchestrator.py models add \
  --name claude-opus-4 \
  --provider anthropic \
  --model claude-opus-4-1-20250805 \
  --tier high \
  --role architect \
  --command "claude -p --model opus {prompt_file}"

# Benchmark for verifier role
./orchestrator.py models benchmark --role verifier

# Test specific model
./orchestrator.py models test --name local-qwen
```

---

## 📈 Metrics to Track Over Time

| Metric | Source | Target |
|--------|--------|--------|
| Improvements captured per milestone | `improvements/` count | ≥3 |
| Adoption rate | `status: adopted` / total | >50% |
| Time to adopt | `adopted_in` - `timestamp` | <2 milestones |
| Model diversity yield | `metrics/*.yaml` | cross-family > same-family |
| Interop pass rate | `orchestrator.py interop` | 100% for COMPLETE milestones |
| Feedback reports submitted | Draft author responses | ≥1 per draft |

---

*This document is itself an output of the improvement loop. Update it whenever you capture a new pattern.*