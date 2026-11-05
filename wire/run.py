"""Run one interop cell and write its evidence bundle (DESIGN.md 24.20)."""

import json
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import bundle as bundle_mod
from . import capture, checkers, decrypt, proc
from .manifest import Manifest, expand, substitute

ENV_CHECK_TIMEOUT_S = 60.0
BUILD_TIMEOUT_S = 600.0
READY_POLL_S = 0.2
EXIT_CODES = {"PASS": 0, "FAIL": 1, "BLOCKED": 3, "ENV": 4}


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(path: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_state(path: Path) -> tuple[str | None, bool | None]:
    """(HEAD commit, dirty) of the work tree at path; dirty counts untracked files under path."""
    commit = _git(path, "rev-parse", "HEAD")
    status = _git(path, "status", "--porcelain", "--", ".")
    if commit is None or status is None:
        return None, None
    return commit, bool(status)


def _tool(argv: list[str]) -> str:
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return (
        (r.stdout + r.stderr).strip().splitlines()[0]
        if (r.stdout + r.stderr).strip()
        else ""
    )


def _raise_interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


class _Cell:
    def __init__(self, m: Manifest, name: str, out: Path) -> None:
        self.m = m
        self.cell = m.cells[name]
        self.bundle = out / name
        self.pcap = self.bundle / "capture.pcap"
        self.secrets = self.bundle / bundle_mod.SECRETS_DIR
        self.decrypted = self.bundle / bundle_mod.DECRYPTED
        self.peer_names = [self.cell["server"], *self.cell["clients"]]
        self.running: list[subprocess.Popen[bytes]] = []
        self.env: dict[str, Any] = {
            "cell": name,
            "manifest_sha256": m.sha256,
            "env_checks": {},
            "peers": {},
            "checker_inputs": {},
        }
        self.peers: dict[str, dict[str, Any]] = {
            p: {
                "exit": None,
                "timed_out": False,
                "binaries": {},
                "commit": None,
                "dirty": None,
            }
            for p in self.peer_names
        }
        self.checker_exits: dict[str, int] = {}

    def argv(self, command: str) -> list[str]:
        return expand(command, self.bundle, self.pcap, self.bundle / "inputs")

    def execute(self) -> tuple[str, str]:
        m = self.m
        for chk in m.env_checks:
            log = self.bundle / "envcheck" / f"{chk['name']}.log"
            rc, _ = proc.run(
                self.argv(chk["command"]), m.root, ENV_CHECK_TIMEOUT_S, log
            )
            self.env["env_checks"][chk["name"]] = rc
            if rc != 0:
                return "ENV", f"env check failed: {chk['name']}"

        try:
            interface = capture.resolve_interface(m.capture["interface"])
        except capture.CaptureError as e:
            return "BLOCKED", str(e)
        self.env["capture_interface"] = interface

        commit, dirty = git_state(m.root)
        self.env["experiment"] = {"path": str(m.root), "commit": commit, "dirty": dirty}
        if commit is None or dirty is None:
            return "BLOCKED", "experiment directory is not a git work tree"
        if dirty:
            return (
                "BLOCKED",
                "experiment directory has uncommitted or untracked changes",
            )

        self.env["checker_inputs"] = checkers.stage_inputs(
            m, self.cell["checkers"], self.bundle / "inputs"
        )

        if m.secured:
            self.secrets.mkdir()

        for name in self.peer_names:
            p = m.peers[name]
            for b in p["binaries"]:
                (p["path"] / b).unlink(missing_ok=True)
            pcommit, pdirty = git_state(p["path"])
            self.peers[name].update(commit=pcommit, dirty=pdirty)
            self.env["peers"][name] = {
                "path": str(p["path"]),
                "commit": pcommit,
                "dirty": pdirty,
                "build_exit": None,
                "binaries": {},
            }
        for name in self.peer_names:
            p = m.peers[name]
            rec = self.env["peers"][name]
            if p["build"]:
                rc, _ = proc.run(
                    self.argv(p["build"]),
                    p["path"],
                    BUILD_TIMEOUT_S,
                    self.bundle / "build" / f"{name}.log",
                )
                rec["build_exit"] = rc
                if rc != 0:
                    return "BLOCKED", f"build failed: {name}"
            for b in p["binaries"]:
                path = p["path"] / b
                if not path.is_file():
                    return (
                        "BLOCKED",
                        f"declared binary missing after build: {name}: {b}",
                    )
                rec["binaries"][str(path)] = bundle_mod.sha256_file(path)
            self.peers[name]["binaries"] = dict(rec["binaries"])

        try:
            cap = capture.start(
                interface,
                m.capture["filter"],
                self.pcap,
                self.bundle / "capture.log",
            )
        except capture.CaptureError as e:
            return "BLOCKED", str(e)
        self.running.append(cap)
        self.env["capture_pid"] = cap.pid

        failure = self.run_peers()
        packets = capture.stop(cap, self.bundle / "capture.log")
        self.env["capture_packets"] = packets
        if failure:
            if (
                packets
            ):  # keep the checkers' view of the wire next to the peer's failure
                self.run_checkers()
            return "FAIL", failure
        if not packets:
            return "BLOCKED", "capture recorded no packets"
        blocked = self.check_secrets()
        if blocked:
            return "BLOCKED", blocked
        if m.decrypt is not None and not self.decrypt_step():
            return "FAIL", "decrypt failed"
        return self.run_checkers()

    def check_secrets(self) -> str | None:
        """BLOCKED reason when a secret declared by a peer of this cell is not a non-empty regular file."""
        for name in self.peer_names:
            for secret in self.m.peers[name]["secrets"]:
                path = self.secrets / secret
                if path.is_symlink():
                    return f"declared secret is a symlink: {secret} (peer {name})"
                if not path.is_file() or path.stat().st_size == 0:
                    return f"declared secret missing or empty: {secret} (peer {name})"
        return None

    def decrypt_step(self) -> bool:
        assert self.m.decrypt is not None
        command = self.m.decrypt["command"]
        exe = decrypt.executable(self.argv(command)[0], self.m.root)
        self.env["decrypt"] = {
            "command": command,
            "executable": str(exe) if exe else None,
            "sha256": bundle_mod.sha256_file(exe) if exe else None,
        }
        return decrypt.run(
            self.m,
            self.bundle,
            self.pcap,
            self.bundle / "inputs",
            self.secrets,
            self.decrypted,
            self.bundle / bundle_mod.DECRYPT_LOG,
        )

    def spawn_peer(self, name: str) -> subprocess.Popen[bytes] | None:
        p = self.m.peers[name]
        peer_env = {
            k: substitute(v, self.bundle, self.pcap, self.bundle / "inputs")
            for k, v in p["env"].items()
        }
        self.env["peers"][name]["env"] = peer_env
        try:
            proc_ = proc.spawn(
                self.argv(p["start"]),
                p["path"],
                self.bundle / f"{name}.log",
                peer_env,
            )
        except OSError as e:
            with open(self.bundle / f"{name}.log", "ab") as f:
                f.write(f"cannot execute: {e}\n".encode())
            self.peers[name]["exit"] = 127
            return None
        self.running.append(proc_)
        return proc_

    def run_peers(self) -> str | None:
        """Start server then clients, wait, stop by process group. Returns a failure reason."""
        server_name = self.cell["server"]
        server = self.spawn_peer(server_name)
        if server is None:
            return f"peer failed to start: {server_name}"
        ready = self.m.peers[server_name]["ready"]
        if ready:
            deadline = time.monotonic() + ready["timeout_s"]
            while True:
                rc, _ = proc.run(
                    self.argv(ready["command"]),
                    self.m.peers[server_name]["path"],
                    30.0,
                    None,
                )
                if rc == 0:
                    break
                if server.poll() is not None or time.monotonic() >= deadline:
                    self.stop_peer(server_name, server)
                    return f"server not ready: {server_name}"
                time.sleep(READY_POLL_S)

        clients: dict[str, subprocess.Popen[bytes]] = {}
        for name in self.cell["clients"]:
            c = self.spawn_peer(name)
            if c is None:
                break
            clients[name] = c
        deadline = time.monotonic() + self.cell["timeout_s"]
        while (
            len(clients) == len(self.cell["clients"])
            and any(c.poll() is None for c in clients.values())
            and server.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)

        reasons = []
        server_self_exit = server.poll()
        for name, c in clients.items():
            self.stop_peer(name, c)
        self.stop_peer(server_name, server)
        if server_self_exit not in (None, 0):
            reasons.append(f"peer failed: {server_name}")
        for name in self.cell["clients"]:
            rec = self.peers[name]
            if rec["exit"] != 0:
                reasons.append(
                    f"peer {'timed out' if rec['timed_out'] else 'failed'}: {name}"
                )
        return "; ".join(reasons) or None

    def stop_peer(self, name: str, p: subprocess.Popen[bytes]) -> None:
        rec = self.peers[name]
        rec["timed_out"] = p.poll() is None and name != self.cell["server"]
        proc.kill_group(p)
        rec["exit"] = p.returncode

    def run_checkers(self) -> tuple[str, str]:
        failed, accepting = [], []
        inputs = self.bundle / "inputs"
        for name in self.cell["checkers"]:
            log = self.bundle / f"checker-{name}.log"
            rc = checkers.run_checker(self.m, name, self.bundle, self.pcap, inputs, log)
            self.checker_exits[name] = rc
            if rc != 0:
                failed.append(name)
            elif checkers.accepted_negatives(
                self.m, name, self.bundle, self.pcap, inputs, log
            ):
                accepting.append(name)
        if failed:
            return "FAIL", f"checker failed: {', '.join(failed)}"
        if accepting:
            return "FAIL", f"checker accepts negative: {', '.join(accepting)}"
        return (
            "PASS",
            "all peers exited 0, capture non-empty, every checker passed and rejected its negatives",
        )

    def kill_all(self) -> None:
        for p in self.running:
            proc.kill_group(p)


def run_cell(m: Manifest, cell: str, out: Path) -> tuple[str, str, Path]:
    c = _Cell(m, cell, out)
    if c.bundle.exists() and any(c.bundle.iterdir()):
        raise FileExistsError(f"bundle directory is not empty: {c.bundle}")
    c.bundle.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGINT, _raise_interrupt)
    signal.signal(signal.SIGTERM, _raise_interrupt)
    started = _utc()
    try:
        verdict, reason = c.execute()
    except KeyboardInterrupt:
        verdict, reason = "FAIL", "interrupted"
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        c.kill_all()
    ended = _utc()
    c.env.update(
        started_at=started,
        ended_at=ended,
        tools={
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "git": _tool(["git", "--version"]),
            "tcpdump": _tool([capture.tcpdump(), "--version"]),
        },
        interfaces=_tool_lines([capture.tcpdump(), "-D"]),
    )
    (c.bundle / "env.json").write_text(
        json.dumps(c.env, indent=2) + "\n", encoding="utf-8"
    )
    result = {
        "cell": cell,
        "verdict": verdict,
        "reason": reason,
        "peers": c.peers,
        "checkers": c.checker_exits,
        "contains_secrets": c.secrets.is_dir()
        and any(f.is_file() for f in c.secrets.rglob("*")),
        "started_at": started,
        "ended_at": ended,
    }
    (c.bundle / "verdict.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    bundle_mod.write_sums(c.bundle)
    return verdict, reason, c.bundle


def _tool_lines(argv: list[str]) -> list[str]:
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return r.stdout.strip().splitlines()
