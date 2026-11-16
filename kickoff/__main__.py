"""CLI: python3 -m kickoff DIR | --answers FILE | --questions."""

import argparse
import sys
from pathlib import Path

from . import InitError, init, questions_template


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kickoff",
        description="Start an AI2II project: ask what it is for and write its rails",
    )
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--answers", help="answers file (from --questions), for agents")
    ap.add_argument(
        "--questions", action="store_true", help="print the answers template"
    )
    ap.add_argument(
        "--force", action="store_true", help="overwrite existing rail files"
    )
    args = ap.parse_args(argv)
    if args.questions:
        print(questions_template())
        return 0
    if not args.dir:
        print("kickoff: error: needs DIR (or --questions)", file=sys.stderr)
        return 2
    try:
        return init(Path(args.dir), args.answers, args.force)
    except InitError as e:
        print(f"kickoff: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
