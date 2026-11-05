"""M10: loopback resolution, broken-echo example, and wire summarize."""

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("wire_helpers", HERE / "test_wire.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)


def run_cell(manifest: Path, out: Path, cell: str = "echo"):
    return H.wire("run", str(manifest), "--cell", cell, "--out", str(out))


def make(tmp: Path) -> Path:
    """The unmodified example (interface: loopback), committed, on a free port."""
    m = H.make_exp(tmp, edits=[])
    text = m.read_text().replace(f"interface: {H.IFACE}", "interface: loopback")
    m.write_text(text)
    subprocess.run(["git", "commit", "-qam", "loopback"], cwd=m.parent, check=True)
    return m


def test_loopback_resolves_and_echo_passes():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        r = run_cell(make(tmp), tmp / "out")
        assert r.returncode == 0, r.stdout + r.stderr
        env = json.loads((tmp / "out" / "echo" / "env.json").read_text())
        assert env["capture_interface"] == H.IFACE


def test_unresolvable_loopback_is_blocked_before_any_peer():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make(tmp)
        code = (
            "import platform, sys; platform.system = lambda: 'Plan9'; "
            "from wire.__main__ import main; sys.exit(main(sys.argv[1:]))"
        )
        r = subprocess.run(
            [sys.executable, "-c", code, "run", str(m), "--cell", "echo"]
            + ["--out", str(tmp / "out")],
            cwd=H.ROOT,
            env=H.ENV,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode == 3, r.stdout + r.stderr
        reason = H.verdict_of(tmp / "out")["reason"]
        assert "loopback" in reason and "Plan9" in reason
        assert not list((tmp / "out" / "echo").glob("echo-*.log"))


def test_broken_echo_fails_with_checker_log():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        r = run_cell(make(tmp), tmp / "out", "echo-broken")
        assert r.returncode == 1, r.stdout + r.stderr
        v = H.verdict_of(tmp / "out", "echo-broken")
        assert "echo-client" in v["reason"]
        b = tmp / "out" / "echo-broken"
        assert (b / "capture.pcap").stat().st_size > 24
        assert (
            "no request with a matching echo"
            in (b / "checker-observes-echo.log").read_text()
        )
        assert v["checkers"]["observes-echo"] != 0


def test_summarize():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        empty = tmp / "empty"
        empty.mkdir()
        assert H.wire("summarize", str(empty)).returncode == 2
        m = make(tmp)
        run_cell(m, tmp / "runs" / "a", "echo")
        run_cell(m, tmp / "runs" / "b" / "deep", "echo-broken")
        bad = tmp / "runs" / "d"
        bad.mkdir()
        (bad / "verdict.json").write_text("{not json")
        r = H.wire("summarize", str(tmp / "runs"), "--json")
        assert r.returncode == 0, r.stderr
        recs = {Path(x["bundle"]).name: x for x in json.loads(r.stdout)}
        assert recs["echo"]["verdict"] == "PASS" and recs["echo"]["verified"]
        assert recs["echo-broken"]["verdict"] == "FAIL"
        assert recs["echo-broken"]["peers"]["echo-client"]["commit"]
        assert recs["d"]["verdict"] is None and recs["d"]["error"]
        text = H.wire("summarize", str(tmp / "runs")).stdout
        assert "PASS" in text and "FAIL" in text


def test_summarize_flags_edited_verdict():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        run_cell(make(tmp), tmp / "runs" / "a", "echo-broken")
        v = tmp / "runs" / "a" / "echo-broken" / "verdict.json"
        v.write_text(v.read_text().replace('"FAIL"', '"PASS"', 1))
        rec = json.loads(H.wire("summarize", str(tmp / "runs"), "--json").stdout)[0]
        assert rec["verified"] is False and rec["verdict"] is None
        assert rec["claimed"]["verdict"] == "PASS"
        assert "UNVERIFIED(PASS)" in H.wire("summarize", str(tmp / "runs")).stdout
