"""tcpdump capture control. wire never decodes packets; it only counts what tcpdump reports."""

import platform
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

from . import proc

START_TIMEOUT_S = 10.0
STOP_TIMEOUT_S = 5.0
FLUSH_DELAY_S = 0.5


class CaptureError(Exception):
    """The capture could not be started."""


LOOPBACK = {
    "Darwin": "lo0",
    "Linux": "lo",
    "FreeBSD": "lo0",
    "OpenBSD": "lo0",
    "NetBSD": "lo0",
}


def resolve_interface(name: str) -> str:
    """Map the word 'loopback' to this host's loopback interface; any other name is used as written."""
    if name != "loopback":
        return name
    system = platform.system()
    if system not in LOOPBACK:
        raise CaptureError(
            f"cannot resolve capture interface 'loopback' on OS {system!r}"
        )
    return LOOPBACK[system]


def tcpdump() -> str:
    return shutil.which("tcpdump") or "/usr/sbin/tcpdump"


def start(interface: str, filt: str, pcap: Path, log: Path) -> subprocess.Popen[bytes]:
    argv = [tcpdump(), "-i", interface, "-n", "-U", "--immediate-mode", "-w", str(pcap)]
    if filt:
        argv += ["--", filt]
    try:
        p = proc.spawn(argv, pcap.parent, log)
    except OSError as e:
        raise CaptureError(f"cannot execute tcpdump: {e}") from e
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if "listening on" in log.read_text(errors="replace"):
            return p
        if p.poll() is not None:
            break
        time.sleep(0.05)
    proc.kill_group(p)
    tail = log.read_text(errors="replace").strip().splitlines()[-1:]
    raise CaptureError(f"capture did not start: {tail[0] if tail else 'no output'}")


def stop(p: subprocess.Popen[bytes], log: Path) -> int | None:
    """Stop tcpdump and return the number of packets it reports capturing (None: unknown)."""
    time.sleep(FLUSH_DELAY_S)
    p.send_signal(signal.SIGINT)
    try:
        p.wait(timeout=STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        pass
    proc.kill_group(p)
    found = re.search(r"(\d+) packets? captured", log.read_text(errors="replace"))
    return int(found.group(1)) if found else None
