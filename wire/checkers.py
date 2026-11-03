"""Checker execution: normal runs, and the validity runs over each declared negative."""

import shutil
import tempfile
from pathlib import Path

from . import decrypt, proc
from .bundle import DECRYPTED as DECRYPTED_FILE
from .bundle import SECRETS_DIR, sha256_file
from .manifest import CAPTURE, DECRYPTED, SECRETS, Manifest, expand

CHECKER_TIMEOUT_S = 60.0


def stage_inputs(m: Manifest, names: list[str], dest: Path) -> dict[str, str]:
    """Copy the inputs and negative inputs of the named checkers into dest; return {path: sha256}."""
    hashes: dict[str, str] = {}
    for name in names:
        k = m.checkers[name]
        rels = k["inputs"] + [n["input"] for n in k["negatives"]]
        for rel in rels:
            target = dest / rel
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(m.root / rel, target)
            hashes[rel] = sha256_file(target)
    return hashes


def run_checker(
    m: Manifest,
    name: str,
    bundle: Path,
    capture: Path,
    inputs: Path,
    log: Path,
    secrets: Path | None = None,
    decrypted: Path | None = None,
) -> int:
    argv = expand(
        m.checkers[name]["command"], bundle, capture, inputs, secrets, decrypted
    )
    rc, timed_out = proc.run(argv, m.root, CHECKER_TIMEOUT_S, log)
    return 1 if timed_out and rc == 0 else rc


def accepted_negatives(
    m: Manifest,
    name: str,
    bundle: Path,
    capture: Path | None,
    inputs: Path,
    log: Path,
) -> list[str]:
    """Run the checker once per negative; return the negatives it exits 0 on.

    Without a capture (validate-checkers) only the negatives that replace the capture of a checker
    that does not read the decrypted view can run. A negative replacing "{secrets}/<file>" re-runs the
    decrypt step with the replacement into a scratch location; one replacing "{decrypted}" substitutes
    the view. Neither touches the bundle's own files.
    """
    accepted = []
    for neg in m.checkers[name]["negatives"]:
        repl = neg["replaces"]
        if capture is None and (
            repl != CAPTURE or m.checkers[name]["observes_decrypted"]
        ):
            continue
        with tempfile.TemporaryDirectory(prefix="wire-neg-") as tmp:
            scratch = Path(tmp)
            view = scratch / "inputs"
            shutil.copytree(inputs, view)
            cap, secrets, decrypted = capture, None, None
            with open(log, "ab") as f:
                f.write(f"--- negative: {neg['input']} replaces {repl}\n".encode())
            if repl == CAPTURE:
                cap = view / neg["input"]
            elif repl == DECRYPTED:
                decrypted = view / neg["input"]
            elif repl.startswith(SECRETS + "/"):
                assert capture is not None
                secrets = scratch / SECRETS_DIR
                if (bundle / SECRETS_DIR).is_dir():
                    shutil.copytree(bundle / SECRETS_DIR, secrets)
                secrets.mkdir(exist_ok=True)
                shutil.copyfile(view / neg["input"], secrets / repl[len(SECRETS) + 1 :])
                decrypted = scratch / DECRYPTED_FILE
                # The checker runs on whatever this leaves, even when the step fails.
                decrypt.run(m, bundle, capture, view, secrets, decrypted, log)
            else:
                assert capture is not None
                shutil.copyfile(view / neg["input"], view / repl)
            rc = run_checker(m, name, bundle, cap, view, log, secrets, decrypted)
        if rc == 0:
            accepted.append(neg["input"])
    return accepted


def validate(m: Manifest) -> list[tuple[str, list[str]]]:
    """Run every checker's capture negatives; return [(checker, accepted negatives)] that failed."""
    out: list[tuple[str, list[str]]] = []
    with tempfile.TemporaryDirectory(prefix="wire-validate-") as tmp:
        root = Path(tmp)
        inputs = root / "inputs"
        stage_inputs(m, list(m.checkers), inputs)
        for name in m.checkers:
            acc = accepted_negatives(m, name, root, None, inputs, root / f"{name}.log")
            if acc:
                out.append((name, acc))
    return out
