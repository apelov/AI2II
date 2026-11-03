"""Process helpers: every child runs in its own process group so it can be stopped as a group."""

import os
import signal
import subprocess
import time
from pathlib import Path


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Children must not write bytecode into the (clean) experiment directory."""
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **(extra or {})}


def spawn(
    argv: list[str],
    cwd: Path,
    log: Path | None,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    """Start argv in a new session with stdout and stderr in `log` (None: discarded).

    `env` holds variables for this child only, on top of the runner's environment.
    """
    if log is None:
        return subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=_env(env),
        )
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as f:
        return subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=_env(env),
        )


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def kill_group(proc: subprocess.Popen[bytes], grace: float = 2.0) -> None:
    """Stop proc and every process left in its group; reap proc."""
    pgid = proc.pid
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 10.0)):
        proc.poll()
        if not _group_alive(pgid):
            break
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            break
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            proc.poll()
            if not _group_alive(pgid):
                break
            time.sleep(0.02)
    proc.wait()


def run(
    argv: list[str], cwd: Path, timeout: float, log: Path | None
) -> tuple[int, bool]:
    """Run to completion. Returns (exit code, timed_out). A command that cannot start exits 127."""
    try:
        proc = spawn(argv, cwd, log)
    except OSError as e:
        if log is not None:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "ab") as f:
                f.write(f"cannot execute {argv!r}: {e}\n".encode())
        return 127, False
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        kill_group(proc)
    return proc.returncode, timed_out
