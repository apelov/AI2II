"""Independent M10 experiments in temporary, committed example repositories."""

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UDP = ROOT / "wire/example/udp_echo"
TLS = ROOT / "wire/example/tls_echo"
ENV = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}


def command(*args, cwd=ROOT, env=ENV):
    return subprocess.run(
        args, cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def wire(*args):
    return command(sys.executable, "-m", "wire", *map(str, args))


def tracked_copy(src, dst):
    names = command("git", "ls-files", "-z", ".", cwd=src).stdout.split("\0")
    assert names and names[0]
    for name in filter(None, names):
        target = dst / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / name, target)


def example(tmp, src=UDP, edits=()):
    dst = tmp / "example"
    tracked_copy(src, dst)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    manifest = dst / "interop.yaml"
    content = manifest.read_text().replace("47321", str(port))
    for old, new in edits:
        assert old in content, old
        content = content.replace(old, new)
    manifest.write_text(content)
    if src == UDP:
        r = command(
            sys.executable,
            "make_negatives.py",
            "--port",
            str(port),
            "--out",
            "negatives",
            cwd=dst,
        )
        assert r.returncode == 0, r.stdout + r.stderr
    assert command("git", "init", "-q", cwd=dst).returncode == 0
    assert command("git", "add", "-A", cwd=dst).returncode == 0
    r = command(
        "git",
        "-c",
        "user.email=v@example.invalid",
        "-c",
        "user.name=verifier",
        "commit",
        "-qm",
        "example",
        cwd=dst,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return manifest


def run(manifest, out, cell="echo"):
    return wire("run", manifest, "--cell", cell, "--out", out)


def bundle(out, cell="echo"):
    return out / cell


def verdict(out, cell="echo"):
    return json.loads((bundle(out, cell) / "verdict.json").read_text())


def test_ac1_macos_loopback_capture_and_pass():
    assert sys.platform == "darwin", "AC1 requires macOS"
    assert "interface: loopback" in (UDP / "interop.yaml").read_text()
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        out = tmp / "out"
        r = run(example(tmp), out)
        assert r.returncode == 0, r.stdout + r.stderr
        assert verdict(out)["verdict"] == "PASS"
        assert (
            json.loads((bundle(out) / "env.json").read_text())["capture_interface"]
            == "lo0"
        )


def test_ac2_linux_container_pass_and_hardcoded_lo0_blocked():
    assert shutil.which("docker"), "AC2 requires Docker"
    assert (
        command("docker", "image", "inspect", "debian-wire-test:latest").returncode == 0
    ), "Debian wire image missing"
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        example(tmp)
        script = (
            "set -eu; cd /work/example; "
            "PYTHONPATH=/repo python3 -m wire run interop.yaml --cell echo --out /work/pass; "
            "PYTHONPATH=/repo python3 -m wire verify-bundle /work/pass/echo; "
            "sed -i 's/interface: loopback/interface: lo0/' interop.yaml; "
            "git add interop.yaml; git -c user.email=v@example.invalid -c user.name=v commit -qm lo0; "
            "set +e; PYTHONPATH=/repo python3 -m wire run interop.yaml --cell echo --out /work/blocked; "
            "test $? -eq 3"
        )
        r = command(
            "docker",
            "run",
            "--rm",
            "--network",
            "host",
            "--cap-add",
            "NET_RAW",
            "--cap-add",
            "NET_ADMIN",
            "-v",
            f"{tmp}:/work",
            "-v",
            f"{ROOT}:/repo:ro",
            "debian-wire-test:latest",
            "sh",
            "-c",
            script,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert (
            json.loads((tmp / "pass/echo/env.json").read_text())["capture_interface"]
            == "lo"
        )
        assert verdict(tmp / "pass")["verdict"] == "PASS"
        assert verdict(tmp / "blocked")["verdict"] == "BLOCKED"
        reason = verdict(tmp / "blocked")["reason"].lower()
        assert "capture" in reason or "interface" in reason, reason
        assert str(tmp / "example") not in reason


def test_ac3_unknown_os_blocks_before_peer_start():
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        manifest = example(tmp)
        code = "import platform,sys; platform.system=lambda:'Plan9'; from wire.__main__ import main; sys.exit(main(sys.argv[1:]))"
        out = tmp / "out"
        r = command(
            sys.executable,
            "-c",
            code,
            "run",
            str(manifest),
            "--cell",
            "echo",
            "--out",
            str(out),
        )
        assert r.returncode == 3, r.stdout + r.stderr
        assert verdict(out)["verdict"] == "BLOCKED"
        assert (
            "interface" in verdict(out)["reason"]
            and "loopback" in verdict(out)["reason"]
        )
        assert not list(bundle(out).glob("echo-*.log"))


def test_ac4_corruption_causes_failure_and_checker_observes_pcap():
    assert "echo-broken" in (UDP / "interop.yaml").read_text()
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        manifest = example(tmp)
        out = tmp / "out"
        r = run(manifest, out, "echo-broken")
        assert r.returncode == 1, r.stdout + r.stderr
        v = verdict(out, "echo-broken")
        assert v["verdict"] == "FAIL" and "echo-client" in v["reason"]
        b = bundle(out, "echo-broken")
        assert (b / "capture.pcap").stat().st_size > 24
        assert v["checkers"]["observes-echo"] != 0
        assert "matching echo" in (b / "checker-observes-echo.log").read_text()
        spec = importlib.util.spec_from_file_location("udp_pcap", UDP / "udp_pcap.py")
        pcap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pcap)
        packets = pcap.datagrams(str(b / "capture.pcap"))
        requests = [
            p
            for p in packets
            if p.dport == int(manifest.read_text().split("--port ")[1].split()[0])
        ]
        assert requests
        replies = [
            p
            for p in packets
            if p.sport == requests[0].dport and p.dport == requests[0].sport
        ]
        assert replies
        assert len(replies[0].payload) == len(requests[0].payload)
        assert sum(a != b for a, b in zip(requests[0].payload, replies[0].payload)) == 1
        # Replacing the faulting server with the ordinary one in the same cell layout must pass.
        text = manifest.read_text().replace(" --corrupt", "")
        manifest.write_text(text)
        assert (
            command("git", "add", "interop.yaml", cwd=manifest.parent).returncode == 0
        )
        assert (
            command(
                "git",
                "-c",
                "user.email=v@example.invalid",
                "-c",
                "user.name=v",
                "commit",
                "-qm",
                "repair",
                cwd=manifest.parent,
            ).returncode
            == 0
        )
        repaired = run(manifest, tmp / "repaired", "echo-broken")
        assert repaired.returncode == 0, repaired.stdout + repaired.stderr


def test_ac5_summary_integrity_missing_and_empty():
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        assert wire("summarize", tmp).returncode == 2
        manifest = example(tmp)
        root = tmp / "many"
        assert run(manifest, root / "a").returncode == 0
        assert run(manifest, root / "b/deep", "echo-broken").returncode == 1
        env_manifest = manifest.read_text().replace(
            'python3 -c "import sys"', 'python3 -c "import sys; sys.exit(1)"'
        )
        manifest.write_text(env_manifest)
        assert (
            command("git", "add", "interop.yaml", cwd=manifest.parent).returncode == 0
        )
        assert (
            command(
                "git",
                "-c",
                "user.email=v@example.invalid",
                "-c",
                "user.name=v",
                "commit",
                "-qm",
                "env",
                cwd=manifest.parent,
            ).returncode
            == 0
        )
        assert run(manifest, root / "c").returncode == 4
        text = manifest.read_text().replace(
            'python3 -c "import sys; sys.exit(1)"', 'python3 -c "import sys"'
        )
        text = text.replace("interface: loopback", "interface: m10-no-such-interface")
        manifest.write_text(text)
        assert (
            command("git", "add", "interop.yaml", cwd=manifest.parent).returncode == 0
        )
        assert (
            command(
                "git",
                "-c",
                "user.email=v@example.invalid",
                "-c",
                "user.name=v",
                "commit",
                "-qm",
                "blocked",
                cwd=manifest.parent,
            ).returncode
            == 0
        )
        assert run(manifest, root / "d").returncode == 3
        missing = root / "missing"
        missing.mkdir()
        (missing / "SHA256SUMS").write_text("")
        malformed = root / "malformed"
        malformed.mkdir()
        (malformed / "verdict.json").write_text("{")
        records = json.loads(wire("summarize", root, "--json").stdout)
        vals = {Path(x["bundle"]).parent.name: x for x in records if x["verdict"]}
        assert {x["verdict"] for x in vals.values()} == {
            "PASS",
            "FAIL",
            "ENV",
            "BLOCKED",
        }
        assert all(
            x["verified"] and "peers" in x and "experiment_commit" in x
            for x in vals.values()
        )
        assert sum(x["verdict"] is None and bool(x.get("error")) for x in records) == 2
        pass_verdict = root / "a/echo/verdict.json"
        obj = json.loads(pass_verdict.read_text())
        obj["verdict"] = "FAIL"
        pass_verdict.write_text(json.dumps(obj))
        recs = json.loads(wire("summarize", root, "--json").stdout)
        edited = next(x for x in recs if x["bundle"] == str(root / "a/echo"))
        assert edited["verified"] is False and edited["claimed"]["verdict"] == "FAIL"
        assert "UNVERIFIED(FAIL)" in wire("summarize", root).stdout
        from wire import summarize

        original_run, original_popen = subprocess.run, subprocess.Popen
        try:
            subprocess.run = lambda *a, **kw: (_ for _ in ()).throw(
                AssertionError("summarize started a subprocess")
            )
            subprocess.Popen = subprocess.run
            assert len(summarize.summarize(root)) == 6
        finally:
            subprocess.run, subprocess.Popen = original_run, original_popen


def test_ac6_builder_copies_ignore_untracked_build_output():
    for source in (UDP, TLS):
        assert "interface: loopback" in (source / "interop.yaml").read_text()
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        sandbox = tmp / "repo"
        tracked_copy(ROOT, sandbox)
        assert command("git", "init", "-q", cwd=sandbox).returncode == 0
        assert command("git", "add", "-A", cwd=sandbox).returncode == 0
        assert (
            command(
                "git",
                "-c",
                "user.email=v@example.invalid",
                "-c",
                "user.name=v",
                "commit",
                "-qm",
                "snapshot",
                cwd=sandbox,
            ).returncode
            == 0
        )
        for source in (
            sandbox / "wire/example/udp_echo",
            sandbox / "wire/example/tls_echo",
        ):
            marker = source / "bin" / "m10_untracked_marker"
            marker.parent.mkdir(exist_ok=True)
            marker.write_text("stale build output")
        for module_name, example_dir in (
            ("test_wire", "udp_echo"),
            ("test_wire_secured", "tls_echo"),
        ):
            path = sandbox / "tests" / f"{module_name}.py"
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            copied = tmp / f"copied-{example_dir}"
            module.copy_tracked(sandbox / "wire/example" / example_dir, copied)
            assert not (copied / "bin/m10_untracked_marker").exists()
        r = command(
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests",
            cwd=sandbox,
            env={**ENV, "PYTHONPATH": str(sandbox / "src/_shims")},
        )
        assert r.returncode == 0, r.stdout + r.stderr
        for source in (
            sandbox / "wire/example/udp_echo",
            sandbox / "wire/example/tls_echo",
        ):
            (source / "bin/m10_untracked_marker").unlink()
        assert command("git", "status", "--porcelain", cwd=sandbox).stdout == ""


def test_ac7_prior_acceptance_suites_and_change_control():
    m08 = (ROOT / "acceptance/M08/test_m08.py").read_text()
    assert 'text.replace("interface: loopback", f"interface: {IFACE}")' in m08
    for path in ("acceptance/M08/test_m08.py", "acceptance/M09/test_m09.py"):
        r = command(
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            path,
            env={**ENV, "PYTHONPATH": str(ROOT / "src/_shims")},
        )
        assert r.returncode == 0, r.stdout + r.stderr
