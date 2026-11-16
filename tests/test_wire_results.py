"""Claim classes on cells, and the generated results block (wire summarize --update/--check)."""

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("wire_helpers", HERE / "test_wire.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)

MOCKED = (
    "server: echo-server-broken\n",
    "server: echo-server-broken\n    claim_class: mocked\n",
)


def make(tmp: Path, edits) -> Path:
    m = H.make_exp(tmp, edits=edits)
    text = m.read_text().replace(f"interface: {H.IFACE}", "interface: loopback")
    m.write_text(text)
    subprocess.run(["git", "commit", "-qam", "loopback"], cwd=m.parent, check=True)
    return m


def test_claim_class_reaches_verdict_and_results_block():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make(tmp, [MOCKED])
        runs = tmp / "runs"
        for cell in ("echo", "echo-broken"):
            H.wire("run", str(m), "--cell", cell, "--out", str(runs / cell))
        v = json.loads(
            (runs / "echo-broken" / "echo-broken" / "verdict.json").read_text()
        )
        assert v["claim_class"] == "mocked"

        block = H.wire("summarize", str(runs), "--markdown").stdout
        assert "| observed-on-wire | PASS | exp | echo |" in block
        assert "| mocked | FAIL | exp | echo-broken |" in block
        assert "- mocked: 1 FAIL" in block and "- observed-on-wire: 1 PASS" in block

        results = tmp / "RESULTS.md"
        results.write_text("# Results\n\nHand-written notes stay.\n")
        assert H.wire("summarize", str(runs), "--update", str(results)).returncode == 0
        assert results.read_text().startswith("# Results\n\nHand-written notes stay.\n")
        r = H.wire("summarize", str(runs), "--check", str(results))
        assert r.returncode == 0, r.stdout

        results.write_text(
            results.read_text().replace("| mocked | FAIL", "| observed-on-wire | PASS")
        )
        r = H.wire("summarize", str(runs), "--check", str(results))
        assert r.returncode == 1 and "differs from the bundles" in r.stdout

        assert H.wire("summarize", str(runs), "--update", str(results)).returncode == 0
        assert H.wire("summarize", str(runs), "--check", str(results)).returncode == 0


def test_check_fails_without_a_generated_block():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make(tmp, [])
        runs = tmp / "runs"
        H.wire("run", str(m), "--cell", "echo", "--out", str(runs / "a"))
        results = tmp / "RESULTS.md"
        results.write_text("92/92 PASS\n")
        r = H.wire("summarize", str(runs), "--check", str(results))
        assert r.returncode == 1 and "no generated results block" in r.stdout


def test_unknown_claim_class_is_a_manifest_error():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        m = make(
            tmp, [(MOCKED[0], "server: echo-server-broken\n    claim_class: live\n")]
        )
        r = H.wire("validate-checkers", str(m))
        assert r.returncode == 2 and "claim_class" in r.stderr
