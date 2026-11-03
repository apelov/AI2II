"""CLI: python3 -m wire {run,verify-bundle,validate-checkers}."""

import argparse
import sys
from pathlib import Path

from . import bundle, checkers, run
from .manifest import ManifestError, load


def _run(args: argparse.Namespace) -> int:
    m = load(args.manifest)
    if args.cell not in m.cells:
        raise ManifestError(f"unknown cell: {args.cell}")
    try:
        verdict, reason, path = run.run_cell(m, args.cell, Path(args.out).resolve())
    except FileExistsError as e:
        raise ManifestError(str(e)) from e
    print(f"{verdict}: {args.cell}: {reason}\nbundle: {path}")
    return run.EXIT_CODES[verdict]


def _verify(args: argparse.Namespace) -> int:
    problems = bundle.verify(Path(args.bundle))
    for p in problems:
        print(f"NOT OK: {p}")
    if not problems:
        print("OK")
    return 1 if problems else 0


def _validate(args: argparse.Namespace) -> int:
    bad = checkers.validate(load(args.manifest))
    for name, negatives in bad:
        print(f"checker accepts negative: {name} ({', '.join(negatives)})")
    if not bad:
        print("OK: every checker rejects its capture negatives")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wire", description="Wire evidence bundles")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="run one cell and write its evidence bundle")
    p.add_argument("manifest")
    p.add_argument("--cell", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=_run)
    p = sub.add_parser("verify-bundle", help="re-check SHA256SUMS and layout")
    p.add_argument("bundle")
    p.set_defaults(fn=_verify)
    p = sub.add_parser(
        "validate-checkers", help="prove each checker rejects its capture negatives"
    )
    p.add_argument("manifest")
    p.set_defaults(fn=_validate)
    args = ap.parse_args(argv)
    try:
        return int(args.fn(args))
    except ManifestError as e:
        print(f"wire: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
