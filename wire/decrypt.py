"""The experiment-supplied decrypt step (DESIGN.md 24.21): wire/ runs the command, it never decodes anything."""

import os
import shutil
from pathlib import Path

from . import proc
from .manifest import Manifest, expand

DECRYPT_TIMEOUT_S = 120.0


def executable(argv0: str, cwd: Path) -> Path | None:
    """Absolute path of a command's executable (through PATH when it has no separator)."""
    if os.sep in argv0:
        path = Path(os.path.abspath(cwd / argv0))
    else:
        found = shutil.which(argv0)
        path = Path(os.path.abspath(found)) if found else None
    return path if path is not None and path.is_file() else None


def run(
    m: Manifest,
    bundle: Path,
    capture: Path,
    inputs: Path,
    secrets: Path,
    decrypted: Path,
    log: Path,
) -> bool:
    """Run the decrypt command; True only if it exits 0 within the timeout and leaves a non-empty `decrypted`."""
    assert m.decrypt is not None
    argv = expand(m.decrypt["command"], bundle, capture, inputs, secrets, decrypted)
    rc, timed_out = proc.run(argv, m.root, DECRYPT_TIMEOUT_S, log)
    return (
        rc == 0
        and not timed_out
        and decrypted.is_file()
        and decrypted.stat().st_size > 0
    )
