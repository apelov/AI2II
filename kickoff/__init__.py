"""kickoff: start an AI2II project by asking what it is for, then write its rails.

Kept apart from `wire` (protocol infrastructure) as DESIGN.md 24.18 requires; it only writes
files that `wire` and the agents read.

The rails are files the agents read on their own: AGENTS.md (the contract), CLAUDE.md and
GEMINI.md (pointers to it), PROJECT.md (the answers), interop.yaml (a skeleton the runner
will refuse until a real checker exists), PROVENANCE.yaml and RESULTS.md.
"""

import datetime
import sys
from pathlib import Path
from typing import Any

import yaml

MODES = ("interop", "build", "both")
ROLES = ("server", "client")
FAMILIES = "anthropic, openai, google, nvidia, mistral, meta, human, unknown"

# The single list of questions: interactive prompts and the --questions template use it.
QUESTIONS: list[tuple[str, str]] = [
    ("goal", "What do you want to achieve here? (one or two sentences)"),
    ("success", "If it works, what one-sentence result will you report?"),
    ("out_of_scope", "What is explicitly out of scope?"),
    (
        "spec",
        "Which document is the protocol authority? (draft name and version, or RFC)",
    ),
    (
        "mode",
        "Mode: interop (existing implementations), build (agents write one), or both",
    ),
    (
        "checker_family",
        (
            f"Which model family writes the checker? ({FAMILIES}); "
            "it must differ from every implementation under test"
        ),
    ),
    (
        "reviewer",
        "Who reviews the work? (model and tool; it must be able to run commands)",
    ),
    (
        "not_live",
        (
            "Will any result rest on recorded, simulated, mocked or partner-attested "
            "data? List it, or write 'none'"
        ),
    ),
]
PEER_QUESTIONS: list[tuple[str, str]] = [
    ("path", "  directory of its code, relative to the project"),
    ("role", "  role: server or client"),
    ("family", f"  model family that wrote it ({FAMILIES})"),
    ("under_test", "  under test? (y/n)"),
]
FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "PROJECT.md",
    "interop.yaml",
    "PROVENANCE.yaml",
    "RESULTS.md",
)


class InitError(Exception):
    pass


def questions_template() -> str:
    lines = [
        "# Answers for `python3 -m kickoff DIR --answers FILE`.",
        "# Agents: ask the human every question; do not guess the answers.",
        "",
    ]
    for key, q in QUESTIONS:
        lines += [f"# {q}", f"{key}: ''", ""]
    lines += [
        "# One entry per implementation. family: " + FAMILIES,
        "peers:",
        "  - name: impl-a",
        "    path: impl-a",
        "    role: server",
        "    family: unknown",
        "    under_test: true",
        "",
    ]
    return "\n".join(lines)


def ask_interactive(read=input) -> dict[str, Any]:
    print(
        "AI2II project start. Answer in plain words; Enter on an empty peer name ends the list.\n"
    )
    answers: dict[str, Any] = {key: read(f"{q}\n> ").strip() for key, q in QUESTIONS}
    peers = []
    while name := read("Implementation name (empty when done)\n> ").strip():
        peer: dict[str, Any] = {"name": name}
        for key, q in PEER_QUESTIONS:
            peer[key] = read(f"{q}\n> ").strip()
        peer["under_test"] = peer["under_test"].lower().startswith("y")
        peers.append(peer)
    answers["peers"] = peers
    return answers


def validate(a: dict[str, Any]) -> list[str]:
    """Return warnings; raise InitError for answers that would make the rails wrong."""
    if not isinstance(a, dict):
        raise InitError("answers must be a mapping")
    missing = [k for k, _ in QUESTIONS if not str(a.get(k) or "").strip()]
    if missing:
        raise InitError("unanswered: " + ", ".join(missing))
    if a["mode"] not in MODES:
        raise InitError(f"mode must be one of {', '.join(MODES)}")
    peers = a.get("peers")
    if not isinstance(peers, list) or not peers:
        raise InitError("at least one implementation (peers) is required")
    names = set()
    for p in peers:
        if not isinstance(p, dict) or not all(
            str(p.get(k) or "").strip() for k in ("name", "path", "role", "family")
        ):
            raise InitError("each peer needs name, path, role and family")
        if p["role"] not in ROLES:
            raise InitError(f"peer {p['name']}: role must be server or client")
        if p["name"] in names:
            raise InitError(f"duplicate peer name: {p['name']}")
        names.add(p["name"])
        if p.get("under_test") is True and p["family"] == a["checker_family"]:
            raise InitError(
                f"checker family {a['checker_family']} equals the family of "
                f"implementation under test {p['name']}; pick another checker family"
            )
    warnings = []
    if "unknown" in [a["checker_family"]] + [
        p["family"] for p in peers if p.get("under_test")
    ]:
        warnings.append(
            "a model family is 'unknown': checker independence cannot be demonstrated"
        )
    families = {
        p["family"] for p in peers if p.get("under_test") and p["family"] != "human"
    }
    if len(peers) > 1 and len(families) == 1:
        warnings.append(
            f"every implementation under test comes from {families.pop()}: "
            "the interop result shows less than two independent implementations would"
        )
    if not any(p["role"] == "server" for p in peers):
        warnings.append("no server peer: interop.yaml gets no cell until you add one")
    return warnings


def _agents_md(a: dict[str, Any], today: str) -> str:
    impls = "\n".join(
        f"- `{p['name']}` ({p['role']}, `{p['path']}/`): written by {p['family']}"
        f"{', under test' if p.get('under_test') else ''}"
        for p in a["peers"]
    )
    build = ""
    if a["mode"] in ("build", "both"):
        build = (
            "\n## Building with agents\n\n"
            "- Each work package names the files it owns and one verify command.\n"
            "- Whoever accepts a package re-runs its verify command on the target system. "
            "A builder's report, exit code or summary is not evidence; agents have exited 0 "
            "after writing nothing.\n"
            "- One package, one commit, with the verify output in the commit message.\n"
            "- For large builds use the AI2II orchestrator (`./orch`, AI2II `AGENTS.md`).\n"
        )
    return f"""# AGENTS.md: contract for this project (AI2II)

Generated by `python3 -m kickoff` on {today}. Every agent and human working here follows it.
`CLAUDE.md` and `GEMINI.md` point here.

**If this is your first action in this repository:** read `PROJECT.md`, then this file, then
state the goal back to the human in one sentence and wait for confirmation before changing
anything.

## The project

- Goal: {a["goal"]}
- Protocol authority: {a["spec"]}
- Mode: {a["mode"]}
- Checker written by: {a["checker_family"]} (from the spec and the wire only)
- Reviewer: {a["reviewer"]}

Implementations:
{impls}

## Rules

1. `{a["spec"]}` is the only protocol authority. Where it is silent or ambiguous, add an Open
   Issue to `PROJECT.md`. Do not invent behaviour and do not copy it from another implementation.
2. Implementations stay independent: never copy code between implementation directories.
   Shared material is the spec, test vectors, the checker and `interop.yaml`.
3. The checker comes from {a["checker_family"]}, is written from the spec and the wire only,
   and must reject its negatives: `python3 -m wire validate-checkers interop.yaml`.
4. No interop result without a bundle from `python3 -m wire run` at a clean commit.
   Exit codes, logs and "tests pass" are not interop evidence.
5. Every result carries one claim class (below). Never add up results of different classes,
   and never call anything live unless it ran against the live system inside that bundle.
6. When you create or substantially change an artifact, update its entry in `PROVENANCE.yaml`.
7. A review finding needs the command that was run and its output. Triage goes in `RESULTS.md`.
8. Bundle results in `RESULTS.md` are generated: `python3 -m wire summarize runs/wire --update
   RESULTS.md`, and `--check RESULTS.md` must pass before anything is published. README and
   slides quote that block; never type a count or PASS from memory.
   A cell whose peer replays recordings, runs on a simulated clock or answers from fixed
   responses declares `claim_class` in `interop.yaml`.
9. List what you could not verify. Stop after the assigned task.
{build}
## Claim classes

| Class | Meaning |
|---|---|
| observed-on-wire | in a bundle's capture and checked by the independent checker |
| replayed-recording | recorded earlier and replayed into a capture |
| simulated | run against a simulator or a fake clock |
| mocked | fixed responses in code; says nothing about the peer |
| partner-attested | reported by another party; this repository only hashes it |
| not-run | planned, not executed |

## Commands

`wire` comes from AI2II: vendor its `wire/` directory or put an AI2II checkout on `PYTHONPATH`.

```sh
python3 -m wire validate-checkers interop.yaml
python3 -m wire run interop.yaml --cell CELL --out runs/wire/$(date -u +%Y%m%dT%H%M%SZ)
python3 -m wire verify-bundle runs/wire/<UTC>/CELL
python3 -m wire summarize runs/wire
```
"""


def _project_md(a: dict[str, Any], warnings: list[str], today: str) -> str:
    warn = "".join(f"- {w}\n" for w in warnings) or "- none\n"
    return (
        f"""# {a["_name"]}

Started {today} with `python3 -m kickoff`. Change these answers only with the human's agreement.

| Question | Answer |
|---|---|
"""
        + "".join(f"| {q} | {str(a[k]).replace('|', '/')} |\n" for k, q in QUESTIONS)
        + f"""
## Independence warnings

{warn}
## Open Issues

Questions the spec does not answer. Do not resolve them in code.

## Decision log

| Date | Decision | Decided by | Why |
|---|---|---|---|
"""
    )


def _interop(a: dict[str, Any]) -> str:
    peers = [
        {
            "name": p["name"],
            "path": p["path"],
            "family": p["family"],
            "under_test": bool(p.get("under_test")),
            "start": f"TODO: start {p['name']}; a client exits 0 only if the exchange completed",
        }
        for p in a["peers"]
    ]
    clients = [p["name"] for p in a["peers"] if p["role"] == "client"]
    cells = [
        {
            "name": f"{p['name']}-serves",
            "server": p["name"],
            "clients": clients,
            "checkers": ["observes-exchange"],
            "claim_class": "observed-on-wire",
            "timeout_s": 60,
        }
        for p in a["peers"]
        if p["role"] == "server"
    ]
    doc = {
        "experiment": a["_name"],
        "peers": peers,
        "capture": {"interface": "loopback", "filter": "TODO: e.g. udp port 5683"},
        "cells": cells,
        "checkers": [
            {
                "name": "observes-exchange",
                "family": a["checker_family"],
                "observes_capture": True,
                "command": "python3 checkers/check.py {capture}",
                "inputs": [],
                "negatives": [
                    {
                        "input": "checkers/negatives/unrelated.pcap",
                        "replaces": "{capture}",
                    },
                    {
                        "input": "checkers/negatives/one_direction.pcap",
                        "replaces": "{capture}",
                    },
                ],
            }
        ],
    }
    return (
        "# Skeleton from `python3 -m kickoff`. `wire` refuses it until the TODOs are\n"
        "# replaced and the checker and its negatives exist (docs/HACKATHON.md sections 1-2).\n"
        + yaml.safe_dump(doc, sort_keys=False, default_flow_style=None, width=1000)
    )


def _provenance(a: dict[str, Any]) -> str:
    blank = {
        "model": "",
        "tool_access": "",
        "prompt": "",
        "transcript_sha256": "",
        "reviewed_by": "",
    }
    arts = [
        {"path": f"{p['path']}/", "written_by": p["family"], **blank}
        for p in a["peers"]
    ]
    arts.append({"path": "checkers/", "written_by": a["checker_family"], **blank})
    return (
        "# Who wrote what. One entry per artifact; fill model, tool access and the prompt\n"
        "# (or a file holding it). The checker family must differ from every peer under test.\n"
        + yaml.safe_dump(
            {"artifacts": arts}, sort_keys=False, default_flow_style=None, width=1000
        )
    )


def _results_md(a: dict[str, Any]) -> str:
    return f"""# Results: {a["_name"]}

Claim classes are defined in `AGENTS.md`; results of different classes are never added together.

## Bundle results (generated)

Run `python3 -m wire summarize runs/wire --update RESULTS.md` after every run; it replaces the
block between its markers. `python3 -m wire summarize runs/wire --check RESULTS.md` fails if the
block was edited by hand or is stale.

## Results without a bundle

Partner-attested results, and anything else that is not a `wire` bundle. Name the source.

| Result | Claim class | Source | Confirmed by |
|---|---|---|---|

## Not run

## Review findings and triage

| Finding | Reviewer | Command and output | Accepted? | Why | Status |
|---|---|---|---|---|---|
"""


def render(
    a: dict[str, Any], name: str, today: str
) -> tuple[dict[str, str], list[str]]:
    warnings = validate(a)
    a = {**a, "_name": name}
    pointer = (
        "Read `AGENTS.md` before doing anything: it is the contract for this project.\n"
    )
    files = {
        "AGENTS.md": _agents_md(a, today),
        "CLAUDE.md": pointer,
        "GEMINI.md": pointer,
        "PROJECT.md": _project_md(a, warnings, today),
        "interop.yaml": _interop(a),
        "PROVENANCE.yaml": _provenance(a),
        "RESULTS.md": _results_md(a),
    }
    return files, warnings


def init(target: Path, answers_file: str | None, force: bool) -> int:
    if answers_file:
        try:
            answers = yaml.safe_load(Path(answers_file).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as e:
            raise InitError(f"cannot read answers: {e}") from e
    elif sys.stdin.isatty():
        answers = ask_interactive()
    else:
        raise InitError(
            "no answers and no terminal. Run `python3 -m kickoff --questions > answers.yaml`, "
            "ask the human every question, then `python3 -m kickoff DIR --answers answers.yaml`"
        )
    # A project's real interop.yaml is its experiment, not a rail: never replace it.
    keep_manifest = (target / "interop.yaml").exists()
    existing = [f for f in FILES if f != "interop.yaml" and (target / f).exists()]
    if existing and not force:
        raise InitError(
            f"{target} already has {', '.join(existing)}; use --force to overwrite"
        )
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    files, warnings = render(answers, target.resolve().name, today)
    if keep_manifest:
        del files["interop.yaml"]
        print("kept the existing interop.yaml (kickoff never replaces it)")
    target.mkdir(parents=True, exist_ok=True)
    for fname, text in files.items():
        (target / fname).write_text(text, encoding="utf-8")
    for w in warnings:
        print(f"warning: {w}")
    print(f"wrote {', '.join(files)} in {target}")
    print("next: commit them, then have every agent start by reading AGENTS.md")
    return 0
