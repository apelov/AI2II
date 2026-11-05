"""Hermetic tests for wire/: every experiment is a throwaway git repo under the system temp dir."""

import ast
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "wire" / "example" / "udp_echo"
IFACE = "lo0" if sys.platform == "darwin" else "lo"
ENV = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def wire(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "wire", *args],
        cwd=ROOT,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,
        **kw,
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def copy_tracked(src: Path, dst: Path) -> None:
    """Copy only the git-tracked files of an example (build output such as bin/ stays behind)."""
    names = subprocess.run(
        ["git", "ls-files", "-z", "."],
        cwd=src,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    for name in filter(None, names):
        (dst / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / name, dst / name)


def make_exp(tmp: Path, edits=(), files=None, commit=True) -> Path:
    """Copy the example, give it a free port, apply (old, new) manifest edits, git-commit it."""
    exp = tmp / "exp"
    copy_tracked(EXAMPLE, exp)
    port = free_port()
    text = (exp / "interop.yaml").read_text().replace("47321", str(port))
    text = text.replace("interface: loopback", f"interface: {IFACE}")
    for old, new in edits:
        assert old in text, old
        text = text.replace(old, new)
    (exp / "interop.yaml").write_text(text)
    for name, content in (files or {}).items():
        (exp / name).parent.mkdir(parents=True, exist_ok=True)
        (exp / name).write_text(content)
    subprocess.run(
        [
            sys.executable,
            "make_negatives.py",
            "--port",
            str(port),
            "--out",
            "negatives",
        ],
        cwd=exp,
        env=ENV,
        check=True,
    )
    if commit:
        subprocess.run(["git", "init", "-q"], cwd=exp, check=True)
        subprocess.run(["git", "add", "-A"], cwd=exp, check=True)
        subprocess.run([*GIT, "commit", "-qm", "x"], cwd=exp, check=True)
    return exp / "interop.yaml"


def verdict_of(out: Path, cell: str = "echo") -> dict:
    return json.loads((out / cell / "verdict.json").read_text())


def can_capture() -> bool:
    p = subprocess.Popen(
        ["tcpdump", "-i", IFACE, "-w", os.devnull],
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and p.poll() is None:
            time.sleep(0.1)
            if p.poll() is None:
                return True
        return False
    finally:
        if p.poll() is None:
            p.terminate()
        p.wait()


def need_capture() -> None:
    # The gate forbids skips (scripts/verify_gate.sh): a capture test that cannot capture fails loudly.
    assert can_capture(), (
        "capture interface not capturable by this user (needs access_bpf or root)"
    )


def alive(pid: int) -> bool:
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        time.sleep(0.02)
    return True


def read_pids(path: Path) -> list[int]:
    return [int(x) for x in path.read_text().split()]


def spawner(pidfile: Path) -> str:
    """Peer script: spawns a long-lived child, records both pids, then hangs."""
    return (
        "import os, subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        f"open({str(pidfile)!r}, 'w').write(f'{{os.getpid()}} {{c.pid}}')\n"
        "time.sleep(300)\n"
    )


def run_cell(manifest: Path, out: Path, cell: str = "echo"):
    return wire("run", str(manifest), "--cell", cell, "--out", str(out))


def test_example_pass_and_bundle_integrity() -> None:
    need_capture()
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        out = tmp / "out"
        r = run_cell(make_exp(tmp), out)
        assert r.returncode == 0, r.stdout + r.stderr
        b = out / "echo"
        for name in (
            "capture.pcap",
            "echo-server.log",
            "echo-client.log",
            "env.json",
            "checker-observes-echo.log",
            "checker-vector.log",
            "verdict.json",
            "SHA256SUMS",
        ):
            assert (b / name).is_file(), name
        assert verdict_of(out)["verdict"] == "PASS"
        assert (b / "inputs" / "vectors" / "payload.bin").is_file()
        env = json.loads((b / "env.json").read_text())
        assert (
            env["experiment"]["dirty"] is False
            and len(env["experiment"]["commit"]) == 40
        )
        for path, digest in env["peers"]["echo-server"]["binaries"].items():
            assert (
                subprocess.run(
                    ["shasum", "-a", "256", path],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.split()[0]
                == digest
            )
        assert "vectors/payload.bin" in env["checker_inputs"]
        assert wire("verify-bundle", str(b)).returncode == 0

        def broken(mutate) -> int:
            copy = tmp / "copy"
            shutil.copytree(b, copy)
            mutate(copy)
            rc = wire("verify-bundle", str(copy)).returncode
            shutil.rmtree(copy)
            return rc

        def flip(c: Path) -> None:
            data = bytearray((c / "capture.pcap").read_bytes())
            data[-1] ^= 1
            (c / "capture.pcap").write_bytes(bytes(data))

        def bad_verdict(c: Path) -> None:
            v = json.loads((c / "verdict.json").read_text())
            v["verdict"] = "MAYBE"
            (c / "verdict.json").write_text(json.dumps(v))

        def dup(c: Path) -> None:
            line = (c / "SHA256SUMS").read_text().splitlines()[0]
            with open(c / "SHA256SUMS", "a") as f:
                f.write(line + "\n")

        def malformed(c: Path) -> None:
            with open(c / "SHA256SUMS", "a") as f:
                f.write("nothex  file\n")

        assert broken(flip) == 1
        assert broken(lambda c: (c / "echo-client.log").unlink()) == 1
        assert broken(lambda c: (c / "extra.txt").write_text("x")) == 1
        assert broken(dup) == 1
        assert broken(malformed) == 1
        assert broken(bad_verdict) == 1
        # sums rewritten after the verdict edit still fail on the verdict value
        v = tmp / "v"
        shutil.copytree(b, v)
        bad_verdict(v)
        sys.path.insert(0, str(ROOT))
        from wire import bundle as bundle_mod

        bundle_mod.write_sums(v)
        assert wire("verify-bundle", str(v)).returncode == 1


def test_validate_checkers() -> None:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make_exp(tmp)
        assert wire("validate-checkers", str(m)).returncode == 0
        (tmp / "b").mkdir()
        always = make_exp(
            tmp / "b",
            edits=[("check_capture.py --port", "accept_any.py --port")],
            files={"accept_any.py": "import sys\nsys.exit(0)\n"},
        )
        r = wire("validate-checkers", str(always))
        assert r.returncode == 1 and "observes-echo" in r.stdout, r.stdout


def test_manifest_validation_exits_2_before_anything_runs() -> None:
    cases = {
        "checker family equals peer": [
            (
                "family: example-checker\n    observes_capture: true",
                "family: example-server\n    observes_capture: true",
            )
        ],
        "empty family": [("family: example-client", 'family: ""')],
        "duplicate peer": [("name: echo-client", "name: echo-server")],
        "undefined peer": [("clients: [echo-client]", "clients: [nobody]")],
        "observes not bool": [
            ("observes_capture: true", "observes_capture: yes-please")
        ],
        "no observes checker": [
            ("checkers: [observes-echo, vector]", "checkers: [vector]")
        ],
        "client is server": [("clients: [echo-client]", "clients: [echo-server]")],
        "client twice": [
            ("clients: [echo-client]", "clients: [echo-client, echo-client]")
        ],
        "bad replaces": [
            ("replaces: vectors/payload.bin", "replaces: vectors/other.bin")
        ],
        "missing negative input": [("negatives/no_echo.pcap", "negatives/gone.pcap")],
        "one capture negative": [
            ('      - {input: negatives/no_echo.pcap, replaces: "{capture}"}\n', "")
        ],
    }
    for label, edits in cases.items():
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            marker = tmp / "env-ran"
            edits = [
                *edits,
                ('command: python3 -c "import sys"', f"command: touch {marker}"),
            ]
            m = make_exp(tmp, edits)
            r = run_cell(m, tmp / "out")
            assert r.returncode == 2, (label, r.stdout, r.stderr)
            assert not marker.exists() and not (tmp / "out").exists(), label


def test_server_that_never_answers_fails() -> None:
    need_capture()
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mute = (
            (EXAMPLE / "src" / "udp_echo_server.py")
            .read_text()
            .replace("sock.sendto(data, peer)", "pass")
        )
        m = make_exp(
            tmp,
            edits=[("--payload-file", "--timeout 1 --payload-file")],
            files={"src/udp_echo_server.py": mute},
        )
        r = run_cell(m, tmp / "out")
        assert r.returncode == 1, r.stdout
        assert verdict_of(tmp / "out")["verdict"] == "FAIL"


def test_hanging_peer_with_child_is_killed_within_timeout() -> None:
    need_capture()
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        pids = tmp / "pids"
        m = make_exp(
            tmp,
            edits=[
                ("timeout_s: 20", "timeout_s: 3"),
                ("python3 bin/udp_echo_client.py --port", "python3 hang.py --port"),
            ],
            files={"hang.py": spawner(pids)},
        )
        t0 = time.monotonic()
        r = run_cell(m, tmp / "out")
        assert time.monotonic() - t0 < 3 + 10
        assert r.returncode == 1, r.stdout
        v = verdict_of(tmp / "out")
        assert v["verdict"] == "FAIL" and v["peers"]["echo-client"]["timed_out"] is True
        assert not any(alive(p) for p in read_pids(pids))
        env = json.loads((tmp / "out" / "echo" / "env.json").read_text())
        assert not alive(env["capture_pid"])


def test_sigint_yields_interrupted_and_leaves_nothing() -> None:
    need_capture()
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        pids = tmp / "pids"
        m = make_exp(
            tmp,
            edits=[
                ("timeout_s: 20", "timeout_s: 60"),
                ("python3 bin/udp_echo_client.py --port", "python3 hang.py --port"),
            ],
            files={"hang.py": spawner(pids)},
        )
        cmd = [sys.executable, "-m", "wire", "run", str(m), "--cell", "echo"]
        p = subprocess.Popen(
            [*cmd, "--out", str(tmp / "out")],
            cwd=ROOT,
            env=ENV,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not pids.exists():
            time.sleep(0.1)
        assert pids.exists()
        time.sleep(0.5)
        p.send_signal(signal.SIGINT)
        out, _ = p.communicate(timeout=30)
        assert p.returncode == 1, out
        v = verdict_of(tmp / "out")
        assert v["verdict"] == "FAIL" and v["reason"] == "interrupted"
        assert not any(alive(x) for x in read_pids(pids))
        env = json.loads((tmp / "out" / "echo" / "env.json").read_text())
        assert not alive(env["capture_pid"])
        assert wire("verify-bundle", str(tmp / "out" / "echo")).returncode == 0


def test_env_check_failure_is_env_and_nothing_runs() -> None:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        built = tmp / "built"
        m = make_exp(
            tmp,
            edits=[
                ("build: python3 build.py", f"build: touch {built}"),
                (
                    '    command: python3 -c "import sys"',
                    '    command: python3 -c "import sys"\n  - name: second\n    command: python3 -c "import sys; sys.exit(3)"',
                ),
            ],
        )
        r = run_cell(m, tmp / "out")
        assert r.returncode == 4, r.stdout + r.stderr
        assert verdict_of(tmp / "out")["verdict"] == "ENV"
        assert (
            not built.exists() and not (tmp / "out" / "echo" / "capture.pcap").exists()
        )


def test_blocked_cases() -> None:
    need_capture()
    # build fails although a stale binary exists
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make_exp(
            tmp,
            edits=[
                (
                    "build: python3 build.py",
                    "build: python3 -c 'import sys; sys.exit(5)'",
                )
            ],
        )
        stale = m.parent / "bin" / "udp_echo_server.py"
        stale.parent.mkdir()
        stale.write_text("stale")
        r = run_cell(m, tmp / "out")
        assert r.returncode == 3 and not stale.exists(), r.stdout
    # binary missing after a build that exits 0
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make_exp(tmp, edits=[("build: python3 build.py", "build: python3 -c pass")])
        assert run_cell(m, tmp / "out").returncode == 3
    # capture cannot start
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make_exp(tmp, edits=[(f"interface: {IFACE}", "interface: nonexistent9")])
        assert run_cell(m, tmp / "out").returncode == 3
        assert verdict_of(tmp / "out")["verdict"] == "BLOCKED"
    # zero packets captured
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make_exp(tmp, edits=[("filter: udp port", "filter: udp port 9 and port")])
        r = run_cell(m, tmp / "out")
        assert r.returncode == 3 and "no packets" in verdict_of(tmp / "out")["reason"]
    # dirty experiment directory (unrelated edited script)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make_exp(tmp)
        (m.parent / "check_capture.py").write_text("import sys\nsys.exit(0)\n")
        r = run_cell(m, tmp / "out")
        assert r.returncode == 3 and verdict_of(tmp / "out")["verdict"] == "BLOCKED"
        assert not (tmp / "out" / "echo" / "capture.pcap").exists()


def test_checkers_that_accept_negatives_fail_the_cell() -> None:
    need_capture()
    accept_all = "import sys\nsys.exit(0)\n"
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make_exp(
            tmp,
            edits=[("check_capture.py --port", "accept_any.py --port")],
            files={"accept_any.py": accept_all},
        )
        r = run_cell(m, tmp / "out")
        v = verdict_of(tmp / "out")
        assert (
            r.returncode == 1
            and v["verdict"] == "FAIL"
            and "observes-echo" in v["reason"]
        )
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make_exp(
            tmp,
            edits=[("check_vector.py --port", "accept_any.py --port")],
            files={"accept_any.py": accept_all},
        )
        v = verdict_of(tmp / "out") if run_cell(m, tmp / "out").returncode == 1 else {}
        assert v["verdict"] == "FAIL" and "vector" in v["reason"]
    with tempfile.TemporaryDirectory() as t:  # a checker exiting non-zero
        tmp = Path(t)
        m = make_exp(
            tmp,
            edits=[("check_vector.py --port", "fail.py --port")],
            files={"fail.py": "import sys\nsys.exit(1)\n"},
        )
        v = verdict_of(tmp / "out") if run_cell(m, tmp / "out").returncode == 1 else {}
        assert v["verdict"] == "FAIL" and "checker failed: vector" in v["reason"]


def test_orch_interop_removed_and_no_cross_imports() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "orchestrator.py"), "interop", "M08", "x"],
        capture_output=True,
        text=True,
        check=False,
        env=ENV,
    )
    assert r.returncode == 2

    def imported(path: Path) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
            elif isinstance(node, ast.Call):
                f = node.func
                if (isinstance(f, ast.Name) and f.id == "__import__") or (
                    isinstance(f, ast.Attribute) and f.attr == "import_module"
                ):
                    arg = node.args[0] if node.args else None
                    names.add(
                        arg.value if isinstance(arg, ast.Constant) else "?dynamic"
                    )
        return names

    for f in (ROOT / "wire").rglob("*.py"):
        assert not any(n.split(".")[0] == "orchestrator" for n in imported(f)), f
    assert not any(
        n.split(".")[0] == "wire" for n in imported(ROOT / "orchestrator.py")
    )
