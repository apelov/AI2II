"""Summarise every evidence bundle under a directory. Reads files only; runs nothing."""

import json
import os
from pathlib import Path
from typing import Any

from . import bundle as bundle_mod

_CLAIMED = (
    "verdict",
    "reason",
    "experiment",
    "cell",
    "claim_class",
    "experiment_commit",
    "peers",
)
BEGIN = "<!-- wire summarize: generated from the bundles; do not edit -->"
END = "<!-- wire summarize: end -->"


def find_bundles(root: Path) -> list[Path]:
    found = []
    for dirpath, _dirs, files in os.walk(root):
        if "verdict.json" in files or bundle_mod.SUMS in files:
            found.append(Path(dirpath))
    return sorted(found)


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _peers(verdict: dict[str, Any]) -> dict[str, Any]:
    out = {}
    peers = verdict.get("peers")
    for name, rec in (peers if isinstance(peers, dict) else {}).items():
        rec = rec if isinstance(rec, dict) else {}
        out[name] = {"commit": rec.get("commit"), "dirty": rec.get("dirty")}
    return out


def record(path: Path) -> dict[str, Any]:
    verdict = _load(path / "verdict.json")
    env = _load(path / "env.json") or {}
    rec: dict[str, Any] = {"bundle": str(path), "verified": False}
    if verdict is None:
        rec.update(
            verdict=None,
            reason=None,
            experiment=None,
            cell=None,
            claim_class=None,
            experiment_commit=None,
            peers={},
            error="verdict.json is missing or malformed",
        )
        return rec
    experiment = env.get("experiment")
    experiment = experiment if isinstance(experiment, dict) else {}
    fields = {
        "verdict": verdict.get("verdict"),
        "reason": verdict.get("reason"),
        "experiment": experiment.get("path"),
        "cell": verdict.get("cell"),
        "claim_class": verdict.get("claim_class") or "unlabelled",
        "experiment_commit": experiment.get("commit"),
        "peers": _peers(verdict),
    }
    if bundle_mod.verify(path):
        rec["claimed"] = fields
        rec.update(dict.fromkeys(_CLAIMED), peers={})
        return rec
    rec.update(fields, verified=True)
    return rec


def summarize(root: Path) -> list[dict[str, Any]]:
    return [record(b) for b in find_bundles(root)]


def row(rec: dict[str, Any]) -> str:
    shown = rec if rec["verified"] else rec.get("claimed", rec)
    verdict = shown["verdict"]
    if rec["verified"]:
        label = verdict
    elif "claimed" in rec:
        label = f"UNVERIFIED({verdict})"
    else:
        label = "-"
    peers = ", ".join(
        f"{n}@{(p['commit'] or '?')[:12]}{'*' if p['dirty'] else ''}"
        for n, p in shown["peers"].items()
    )
    parts = [
        label,
        str(shown["experiment"] or "-"),
        str(shown["cell"] or "-"),
        str((shown["experiment_commit"] or "-")[:12]),
        peers or "-",
        str(shown["reason"] or rec.get("error") or ""),
        rec["bundle"],
    ]
    return "\t".join(parts)


def _label(rec: dict[str, Any]) -> str:
    shown = rec if rec["verified"] else rec.get("claimed", rec)
    if rec["verified"]:
        return str(shown["verdict"])
    if "claimed" in rec:
        return f"UNVERIFIED({shown['verdict']})"
    return "-"


def markdown(records: list[dict[str, Any]], root: Path) -> str:
    """The results block: one row per bundle, totals per claim class, never summed across."""
    lines = [
        BEGIN,
        "",
        "| Claim class | Verdict | Experiment | Cell | Commit | Bundle |",
        "|---|---|---|---|---|---|",
    ]
    totals: dict[str, dict[str, int]] = {}
    for rec in records:
        shown = rec if rec["verified"] else rec.get("claimed", rec)
        klass = str(shown.get("claim_class") or "unlabelled")
        label = _label(rec)
        exp = Path(str(shown["experiment"])).name if shown["experiment"] else "-"
        bundle = Path(rec["bundle"]).relative_to(root).as_posix()
        commit = str(shown["experiment_commit"] or "-")[:12]
        lines.append(
            f"| {klass} | {label} | {exp} | {shown['cell'] or '-'} | {commit} | {bundle} |"
        )
        per = totals.setdefault(klass, {})
        per[label] = per.get(label, 0) + 1
    lines += ["", "Totals by claim class (not added across classes):", ""]
    for klass in sorted(totals):
        counts = ", ".join(f"{n} {v}" for v, n in sorted(totals[klass].items()))
        lines.append(f"- {klass}: {counts}")
    lines += ["", END]
    return "\n".join(lines) + "\n"


def _block(text: str) -> tuple[int, int] | None:
    start = text.find(BEGIN)
    end = text.find(END, start)
    if start < 0 or end < 0:
        return None
    return start, end + len(END) + (
        1 if text[end + len(END) : end + len(END) + 1] == "\n" else 0
    )


def check(path: Path, generated: str) -> str | None:
    """None if the file holds exactly the generated block, else the problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"cannot read {path}: {e}"
    span = _block(text)
    if span is None:
        return f"{path} has no generated results block"
    if text[span[0] : span[1]] != generated:
        return (
            f"{path}: results block differs from the bundles (edited by hand, or stale)"
        )
    return None


def update(path: Path, generated: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    span = _block(text)
    if span is None:
        text = text + ("\n" if text and not text.endswith("\n") else "") + generated
    else:
        text = text[: span[0]] + generated + text[span[1] :]
    path.write_text(text, encoding="utf-8")
