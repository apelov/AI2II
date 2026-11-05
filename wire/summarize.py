"""Summarise every evidence bundle under a directory. Reads files only; runs nothing."""

import json
import os
from pathlib import Path
from typing import Any

from . import bundle as bundle_mod

_CLAIMED = ("verdict", "reason", "experiment", "cell", "experiment_commit", "peers")


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
