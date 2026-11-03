"""Bundle integrity: SHA256SUMS writing and verification (layout and integrity only)."""

import hashlib
import json
import re
from pathlib import Path

SUMS = "SHA256SUMS"
SECRETS_DIR = "secrets"
DECRYPTED = "capture-decrypted.pcapng"
DECRYPT_LOG = "decrypt.log"
VERDICTS = ("PASS", "FAIL", "BLOCKED", "ENV")
_LINE = re.compile(r"^([0-9a-f]{64})  (\S.*)$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(bundle: Path) -> list[str]:
    return sorted(
        p.relative_to(bundle).as_posix()
        for p in bundle.rglob("*")
        if p.is_file() and p.relative_to(bundle).as_posix() != SUMS
    )


def write_sums(bundle: Path) -> None:
    lines = [f"{sha256_file(bundle / rel)}  {rel}\n" for rel in _files(bundle)]
    (bundle / SUMS).write_text("".join(lines), encoding="utf-8")


def verify(bundle: Path) -> list[str]:
    """Return the problems found; an empty list means the bundle is intact."""
    problems: list[str] = []
    sums = bundle / SUMS
    if not bundle.is_dir() or not sums.is_file():
        return [f"{SUMS} missing in {bundle}"]
    listed: dict[str, str] = {}
    for n, line in enumerate(sums.read_text(encoding="utf-8").split("\n")[:-1], 1):
        m = _LINE.match(line)
        rel = m.group(2) if m else ""
        parts = rel.split("/")
        if not m or rel.startswith("/") or "" in parts or ".." in parts or rel == SUMS:
            problems.append(f"{SUMS} line {n}: malformed entry")
        elif rel in listed:
            problems.append(f"{SUMS} line {n}: duplicate entry {rel}")
        else:
            listed[rel] = m.group(1)
    for rel, digest in listed.items():
        path = bundle / rel
        if not path.is_file():
            problems.append(f"listed file missing: {rel}")
        elif sha256_file(path) != digest:
            problems.append(f"hash mismatch: {rel}")
    for rel in _files(bundle):
        if rel not in listed:
            problems.append(f"unlisted file: {rel}")
    try:
        verdict = json.loads((bundle / "verdict.json").read_text(encoding="utf-8"))
        value = verdict.get("verdict") if isinstance(verdict, dict) else None
    except (OSError, ValueError):
        value = None
    if value not in VERDICTS:
        problems.append(f"verdict.json: verdict is not one of {', '.join(VERDICTS)}")
    if "verdict.json" not in listed:
        problems.append("verdict.json is not listed")
    return problems
