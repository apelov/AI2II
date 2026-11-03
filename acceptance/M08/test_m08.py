"""Acceptance tests for M08: Wire evidence bundles and checked test vectors.

Approved criteria: AC1 to AC11 in milestones/M08/spec.yaml.
Hermetic: executes against isolated temporary repositories under tempfile.
Compatible with both real pytest and src/_shims/pytest.py (no fixtures).
"""

import ast
import hashlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / "wire" / "example" / "udp_echo"
IFACE = "lo0" if sys.platform == "darwin" else "lo"
ENV = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
GIT_AUTHOR = [
    "git",
    "-c",
    "user.email=verifier@ai2ii.invalid",
    "-c",
    "user.name=verifier",
]


def wire(*args: str, **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "wire", *args],
        cwd=REPO_ROOT,
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


def make_exp(
    tmp: Path,
    edits: list[tuple[str, str]] | tuple[()] = (),
    files: dict[str, str] | None = None,
    commit: bool = True,
) -> Path:
    """Copy example experiment, configure port/iface, apply edits, and commit."""
    exp = tmp / "exp"
    shutil.copytree(EXAMPLE, exp)
    port = free_port()
    text = (exp / "interop.yaml").read_text(encoding="utf-8")
    text = text.replace("47321", str(port))
    text = text.replace("lo0", IFACE)
    for old, new in edits:
        assert old in text, f"edit target {old!r} not in manifest"
        text = text.replace(old, new)
    (exp / "interop.yaml").write_text(text, encoding="utf-8")
    for rel_path, content in (files or {}).items():
        dest = exp / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
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
        capture_output=True,
    )
    if commit:
        subprocess.run(["git", "init", "-q"], cwd=exp, check=True)
        subprocess.run(["git", "add", "-A"], cwd=exp, check=True)
        subprocess.run([*GIT_AUTHOR, "commit", "-qm", "init"], cwd=exp, check=True)
    return exp / "interop.yaml"


def verdict_of(out: Path, cell: str = "echo") -> dict:
    return json.loads((out / cell / "verdict.json").read_text(encoding="utf-8"))


def alive(pid: int) -> bool:
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        time.sleep(0.02)
    return True


def read_pids(path: Path) -> list[int]:
    return [int(x) for x in path.read_text(encoding="utf-8").split()]


def spawner_script(pidfile: Path) -> str:
    return (
        "import os, subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        f"open({str(pidfile)!r}, 'w').write(f'{{os.getpid()}} {{c.pid}}')\n"
        "time.sleep(300)\n"
    )


def parse_udp_pcap(path: Path) -> list[tuple[str, int, str, int, bytes]]:
    """Parse UDP IPv4 datagrams from classic pcap: (src, sport, dst, dport, payload)."""
    data = path.read_bytes()
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        end = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        end = ">"
    else:
        raise ValueError("not a classic pcap file")
    linktype = struct.unpack(end + "I", data[20:24])[0]
    skip = {0: 4, 1: 14, 101: 0, 108: 4}.get(linktype, 4)
    out = []
    pos = 24
    while pos + 16 <= len(data):
        incl = struct.unpack(end + "I", data[pos + 8 : pos + 12])[0]
        pkt = data[pos + 16 : pos + 16 + incl]
        pos += 16 + incl
        ip = pkt[skip:]
        if len(ip) < 28 or ip[0] >> 4 != 4 or ip[9] != 17:
            continue
        ihl = (ip[0] & 15) * 4
        sport, dport, length = struct.unpack("!HHH", ip[ihl : ihl + 6])
        payload = ip[ihl + 8 : ihl + length]
        src = ".".join(str(b) for b in ip[12:16])
        dst = ".".join(str(b) for b in ip[16:20])
        out.append((src, sport, dst, dport, payload))
    return out


# =============================================================================
# AC1: Example experiment run, packet capture, bundle contents, and checker
# =============================================================================


def test_ac1_example_pass_and_bundle_contents() -> None:
    """AC1: Example experiment exits 0, writes full evidence bundle, capture in both directions."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        manifest = make_exp(tmp)
        out = tmp / "out"
        r = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert r.returncode == 0, f"wire run failed: {r.stdout}\n{r.stderr}"

        b = out / "echo"
        required_files = (
            "capture.pcap",
            "echo-server.log",
            "echo-client.log",
            "env.json",
            "checker-observes-echo.log",
            "checker-vector.log",
            "verdict.json",
            "SHA256SUMS",
        )
        for name in required_files:
            assert (b / name).is_file(), f"missing bundle file: {name}"

        # Verify verdict.json
        v = verdict_of(out, "echo")
        assert v["verdict"] == "PASS"
        assert v["cell"] == "echo"
        assert v["peers"]["echo-server"]["exit"] in (0, -signal.SIGTERM, -15)
        assert v["peers"]["echo-client"]["exit"] == 0

        # Parse capture.pcap and assert UDP packets in both directions
        pcap_path = b / "capture.pcap"
        pkts = parse_udp_pcap(pcap_path)
        assert len(pkts) >= 2, f"expected >= 2 datagrams in capture, got {len(pkts)}"

        expected_payload = (manifest.parent / "vectors" / "payload.bin").read_bytes()
        reqs = [
            p
            for p in pkts
            if p[2] == "127.0.0.1" and p[4] == expected_payload  # dst is 127.0.0.1
        ]
        reps = [
            p
            for p in pkts
            if p[0] == "127.0.0.1" and p[4] == expected_payload  # src is 127.0.0.1
        ]
        assert reqs, "no request datagram found in capture.pcap"
        assert reps, "no echo reply datagram found in capture.pcap"

        # Verify client log indicates success and observes checker log asserts request and echo
        client_log = (b / "echo-client.log").read_text(encoding="utf-8")
        assert "echo ok" in client_log

        obs_log = (b / "checker-observes-echo.log").read_text(encoding="utf-8")
        assert "request and echo" in obs_log and "observed" in obs_log

        # Verify bundle self-check passes
        vb = wire("verify-bundle", str(b))
        assert vb.returncode == 0, f"verify-bundle failed: {vb.stdout}"


# =============================================================================
# AC2: validate-checkers with capture negatives
# =============================================================================


def test_ac2_validate_checkers_falsification() -> None:
    """AC2: validate-checkers exits 1 when checker accepts negatives; exits 0 on valid checker."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        # Real checker on example exits 0
        m = make_exp(tmp)
        r0 = wire("validate-checkers", str(m))
        assert r0.returncode == 0, (
            f"validate-checkers on valid example failed: {r0.stdout}"
        )

        # Substituted checker accepting any non-empty pcap exits 1 naming the checker
        always = make_exp(
            tmp / "exp_always",
            edits=[("check_capture.py --port", "accept_any.py --port")],
            files={"accept_any.py": "import sys\nsys.exit(0)\n"},
        )
        r1 = wire("validate-checkers", str(always))
        assert r1.returncode == 1
        assert "observes-echo" in r1.stdout

        # Substituted checker accepting unrelated traffic exits 1 naming the checker
        unrelated_checker = (
            "import sys\n"
            "from pathlib import Path\n"
            "pcap = Path(sys.argv[-1])\n"
            "if 'unrelated' in str(pcap):\n"
            "    sys.exit(0)\n"
            "sys.exit(1)\n"
        )
        bad_unrelated = make_exp(
            tmp / "exp_unrel",
            edits=[("check_capture.py --port", "check_unrel.py --port")],
            files={"check_unrel.py": unrelated_checker},
        )
        r2 = wire("validate-checkers", str(bad_unrelated))
        assert r2.returncode == 1
        assert "observes-echo" in r2.stdout

        # Substituted checker accepting no_echo pcap exits 1 naming the checker
        no_echo_checker = (
            "import sys\n"
            "from pathlib import Path\n"
            "pcap = Path(sys.argv[-1])\n"
            "if 'no_echo' in str(pcap):\n"
            "    sys.exit(0)\n"
            "sys.exit(1)\n"
        )
        bad_no_echo = make_exp(
            tmp / "exp_no_echo",
            edits=[("check_capture.py --port", "check_no_echo.py --port")],
            files={"check_no_echo.py": no_echo_checker},
        )
        r3 = wire("validate-checkers", str(bad_no_echo))
        assert r3.returncode == 1
        assert "observes-echo" in r3.stdout


# =============================================================================
# AC3: verify-bundle tamper detection
# =============================================================================


def test_ac3_verify_bundle_tamper_detection() -> None:
    """AC3: verify-bundle exits 0 on untouched bundle, exits 1 on mutation, deletion, addition, malformed sums, bad verdict."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        manifest = make_exp(tmp)
        out = tmp / "out"
        assert (
            wire("run", str(manifest), "--cell", "echo", "--out", str(out)).returncode
            == 0
        )
        bundle = out / "echo"
        assert wire("verify-bundle", str(bundle)).returncode == 0

        def mutate_bundle(mutator) -> int:
            copy = tmp / f"copy_{time.monotonic_ns()}"
            shutil.copytree(bundle, copy)
            try:
                mutator(copy)
                return wire("verify-bundle", str(copy)).returncode
            finally:
                shutil.rmtree(copy, ignore_errors=True)

        # 1 byte flipped in capture.pcap
        def flip_byte(c: Path) -> None:
            raw = bytearray((c / "capture.pcap").read_bytes())
            raw[-1] ^= 0x01
            (c / "capture.pcap").write_bytes(bytes(raw))

        assert mutate_bundle(flip_byte) == 1

        # Listed file deleted
        assert (
            mutate_bundle(lambda c: (c / "echo-client.log").unlink(missing_ok=False))
            == 1
        )

        # Unlisted file added
        assert mutate_bundle(lambda c: (c / "extra.bin").write_text("extra")) == 1

        # SHA256SUMS duplicate entry
        def add_duplicate(c: Path) -> None:
            first_line = (c / "SHA256SUMS").read_text().splitlines()[0]
            with open(c / "SHA256SUMS", "a") as f:
                f.write(first_line + "\n")

        assert mutate_bundle(add_duplicate) == 1

        # SHA256SUMS malformed entry
        def add_malformed(c: Path) -> None:
            with open(c / "SHA256SUMS", "a") as f:
                f.write("not-a-sha256-hash  filename.txt\n")

        assert mutate_bundle(add_malformed) == 1

        # verdict.json invalid verdict value
        def set_bad_verdict(c: Path) -> None:
            v = json.loads((c / "verdict.json").read_text())
            v["verdict"] = "INVALID_VERDICT"
            (c / "verdict.json").write_text(json.dumps(v))

        assert mutate_bundle(set_bad_verdict) == 1


# =============================================================================
# AC4: Peer failures, timeouts, SIGINT, and process group cleanup
# =============================================================================


def test_ac4_peer_failure_timeout_sigint_and_cleanup() -> None:
    """AC4: Server non-response yields FAIL; hanging peer with child terminated within timeout+10s; SIGINT yields interrupted."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        # 1. Server that never answers yields verdict FAIL (exit 1)
        mute_server = (
            (EXAMPLE / "src" / "udp_echo_server.py")
            .read_text(encoding="utf-8")
            .replace("sock.sendto(data, peer)", "pass")
        )
        m_mute = make_exp(
            tmp / "exp_mute",
            edits=[("--payload-file", "--timeout 1.0 --payload-file")],
            files={"src/udp_echo_server.py": mute_server},
        )
        out_mute = tmp / "out_mute"
        r_mute = wire("run", str(m_mute), "--cell", "echo", "--out", str(out_mute))
        assert r_mute.returncode == 1
        assert verdict_of(out_mute)["verdict"] == "FAIL"

        # 2. Hanging peer that spawned child process is terminated within cell timeout + 10s
        pids_file = tmp / "pids.txt"
        m_hang = make_exp(
            tmp / "exp_hang",
            edits=[
                ("timeout_s: 20", "timeout_s: 2"),
                ("python3 bin/udp_echo_client.py --port", "python3 hang.py --port"),
            ],
            files={"hang.py": spawner_script(pids_file)},
        )
        out_hang = tmp / "out_hang"
        t_start = time.monotonic()
        r_hang = wire("run", str(m_hang), "--cell", "echo", "--out", str(out_hang))
        duration = time.monotonic() - t_start
        assert duration < 2 + 10, (
            f"hanging cell took {duration}s, expected < 12s (timeout+10s)"
        )
        assert r_hang.returncode == 1
        v_hang = verdict_of(out_hang)
        assert v_hang["verdict"] == "FAIL"
        assert v_hang["peers"]["echo-client"]["timed_out"] is True
        # Verify no process from child or parent survives
        child_pids = read_pids(pids_file)
        assert not any(alive(p) for p in child_pids), f"pids still alive: {child_pids}"
        env_hang = json.loads(
            (out_hang / "echo" / "env.json").read_text(encoding="utf-8")
        )
        assert not alive(env_hang["capture_pid"]), "capture pid still alive"

        # 3. SIGINT delivered mid-cell yields FAIL with reason 'interrupted' and cleans up
        sig_pids = tmp / "sig_pids.txt"
        m_sig = make_exp(
            tmp / "exp_sig",
            edits=[
                ("timeout_s: 20", "timeout_s: 60"),
                ("python3 bin/udp_echo_client.py --port", "python3 hang.py --port"),
            ],
            files={"hang.py": spawner_script(sig_pids)},
        )
        out_sig = tmp / "out_sig"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "wire",
                "run",
                str(m_sig),
                "--cell",
                "echo",
                "--out",
                str(out_sig),
            ],
            cwd=REPO_ROOT,
            env=ENV,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not sig_pids.exists():
            time.sleep(0.05)
        assert sig_pids.exists(), "hanging process did not start"
        time.sleep(0.3)
        proc.send_signal(signal.SIGINT)
        proc_out, _ = proc.communicate(timeout=15)
        assert proc.returncode == 1, proc_out
        v_sig = verdict_of(out_sig)
        assert v_sig["verdict"] == "FAIL"
        assert v_sig["reason"] == "interrupted"
        interrupted_pids = read_pids(sig_pids)
        assert not any(alive(x) for x in interrupted_pids), (
            f"pids left alive after SIGINT: {interrupted_pids}"
        )
        env_sig = json.loads(
            (out_sig / "echo" / "env.json").read_text(encoding="utf-8")
        )
        assert not alive(env_sig["capture_pid"]), "capture pid alive after SIGINT"


# =============================================================================
# AC5: Failing env checks yield ENV (exit 4), no peer build/start/capture runs
# =============================================================================


def test_ac5_failing_env_checks_yield_env() -> None:
    """AC5: Failing env check yields ENV (exit 4); no peer build, start, or capture runs."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        marker_build = tmp / "marker_build"
        marker_start = tmp / "marker_start"
        m = make_exp(
            tmp,
            edits=[
                (
                    '    command: python3 -c "import sys"',
                    '    command: python3 -c "import sys"\n  - name: second-check\n    command: python3 -c "import sys; sys.exit(7)"',
                ),
                (
                    "build: python3 build.py",
                    f"build: python3 -c \"import pathlib; pathlib.Path('{marker_build}').touch()\"",
                ),
                (
                    "bin/udp_echo_server.py --port",
                    f"bin/udp_echo_server.py --port 47321 & python3 -c \"import pathlib; pathlib.Path('{marker_start}').touch()\" #",
                ),
            ],
        )
        out = tmp / "out"
        r = wire("run", str(m), "--cell", "echo", "--out", str(out))
        assert r.returncode == 4, f"expected exit 4, got {r.returncode}: {r.stdout}"
        v = verdict_of(out)
        assert v["verdict"] == "ENV"
        assert "env check failed: second-check" in v["reason"]
        assert not marker_build.exists(), "build ran despite failed env check"
        assert not marker_start.exists(), "start ran despite failed env check"
        assert not (out / "echo" / "capture.pcap").exists(), "capture ran"

        # Peer that fails when all env checks pass never yields ENV
        m_peer_fail = make_exp(
            tmp / "exp_peer_fail",
            edits=[
                (
                    "build: python3 build.py",
                    'build: python3 -c "import sys; sys.exit(1)"',
                )
            ],
        )
        out_pf = tmp / "out_pf"
        r_pf = wire("run", str(m_peer_fail), "--cell", "echo", "--out", str(out_pf))
        assert r_pf.returncode != 4
        assert verdict_of(out_pf)["verdict"] != "ENV"


# =============================================================================
# AC6: BLOCKED (exit 3) on build failure, missing binary, capture failure, zero packets
# =============================================================================


def test_ac6_build_failure_missing_binary_capture_failure_blocked() -> None:
    """AC6: BLOCKED (exit 3) on failed build (stale binary deleted), missing binary, bad iface, zero packets."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        # 1. Peer build fails, stale binary exists beforehand (stale binary is deleted and absent afterwards)
        m_bld = make_exp(
            tmp / "exp_bld",
            edits=[
                (
                    "build: python3 build.py",
                    'build: python3 -c "import sys; sys.exit(9)"',
                )
            ],
        )
        stale_bin = m_bld.parent / "bin" / "udp_echo_server.py"
        stale_bin.parent.mkdir(exist_ok=True)
        stale_bin.write_text("stale pre-existing binary")
        out_bld = tmp / "out_bld"
        r_bld = wire("run", str(m_bld), "--cell", "echo", "--out", str(out_bld))
        assert r_bld.returncode == 3
        assert verdict_of(out_bld)["verdict"] == "BLOCKED"
        assert not stale_bin.exists(), "stale binary was not deleted before build"

        # 2. Declared binary missing after build exiting 0
        m_miss = make_exp(
            tmp / "exp_miss",
            edits=[("build: python3 build.py", 'build: python3 -c "pass"')],
        )
        out_miss = tmp / "out_miss"
        r_miss = wire("run", str(m_miss), "--cell", "echo", "--out", str(out_miss))
        assert r_miss.returncode == 3
        assert verdict_of(out_miss)["verdict"] == "BLOCKED"

        # 3. Capture cannot start (nonexistent interface)
        m_cap = make_exp(
            tmp / "exp_cap",
            edits=[(f"interface: {IFACE}", "interface: non_existent_dev_42")],
        )
        out_cap = tmp / "out_cap"
        r_cap = wire("run", str(m_cap), "--cell", "echo", "--out", str(out_cap))
        assert r_cap.returncode == 3
        assert verdict_of(out_cap)["verdict"] == "BLOCKED"

        # 4. Capture records zero packets
        m_zero = make_exp(
            tmp / "exp_zero",
            edits=[("filter: udp port", "filter: udp port 59999 and not port")],
        )
        out_zero = tmp / "out_zero"
        r_zero = wire("run", str(m_zero), "--cell", "echo", "--out", str(out_zero))
        assert r_zero.returncode == 3
        v_zero = verdict_of(out_zero)
        assert v_zero["verdict"] == "BLOCKED"
        assert "no packets" in v_zero["reason"]


# =============================================================================
# AC7: Checker failure, validity on negatives, two-cell manifest
# =============================================================================


def test_ac7_checkers_failing_or_accepting_negatives_yield_fail() -> None:
    """AC7: Non-zero checker exits yield FAIL; checker accepting negative yields FAIL; cell B rejects cell A traffic."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        # 1. Checker exiting non-zero turns cell into FAIL with reason naming that checker
        m_fail = make_exp(
            tmp / "exp_fail",
            edits=[("check_vector.py --port", "fail_vector.py --port")],
            files={"fail_vector.py": "import sys\nsys.exit(2)\n"},
        )
        out_fail = tmp / "out_fail"
        r_fail = wire("run", str(m_fail), "--cell", "echo", "--out", str(out_fail))
        assert r_fail.returncode == 1
        v_fail = verdict_of(out_fail)
        assert v_fail["verdict"] == "FAIL"
        assert "vector" in v_fail["reason"]

        # 2. Always-pass observes_capture checker substituted and unrelated traffic: wire run alone yields FAIL naming checker
        m_accept = make_exp(
            tmp / "exp_accept",
            edits=[("check_capture.py --port", "always_pass.py --port")],
            files={"always_pass.py": "import sys\nsys.exit(0)\n"},
        )
        out_accept = tmp / "out_accept"
        r_accept = wire(
            "run", str(m_accept), "--cell", "echo", "--out", str(out_accept)
        )
        assert r_accept.returncode == 1
        v_accept = verdict_of(out_accept)
        assert v_accept["verdict"] == "FAIL"
        assert "observes-echo" in v_accept["reason"]
        assert "checker accepts negative" in v_accept["reason"]

        # 3. Vector checker accepting a declared negative yields FAIL naming vector checker
        vector_accepts_neg = (
            "import sys\n"
            "from pathlib import Path\n"
            "# Always accept vectors (including negative flipped payload)\n"
            "sys.exit(0)\n"
        )
        m_vec_neg = make_exp(
            tmp / "exp_vec_neg",
            edits=[("check_vector.py --port", "vec_acc.py --port")],
            files={"vec_acc.py": vector_accepts_neg},
        )
        out_vec_neg = tmp / "out_vec_neg"
        r_vec_neg = wire(
            "run", str(m_vec_neg), "--cell", "echo", "--out", str(out_vec_neg)
        )
        assert r_vec_neg.returncode == 1
        v_vec_neg = verdict_of(out_vec_neg)
        assert v_vec_neg["verdict"] == "FAIL"
        assert "vector" in v_vec_neg["reason"]
        assert "checker accepts negative" in v_vec_neg["reason"]

        # 4. Two-cell manifest where only cell A's exchange occurs while cell B runs: cell B is never PASS
        # Define cell B with checker expecting different port
        port_b = free_port()
        two_cells_manifest = (
            "experiment: two-cells\n"
            "env_checks: []\n"
            "peers:\n"
            "  - name: echo-server\n"
            "    path: .\n"
            "    family: server-fam\n"
            "    under_test: true\n"
            "    build: python3 build.py\n"
            "    binaries: [bin/udp_echo_server.py]\n"
            "    start: python3 bin/udp_echo_server.py --port 47321\n"
            "    ready: {command: 'python3 ready.py {bundle}/echo-server.log', timeout_s: 10}\n"
            "  - name: echo-client\n"
            "    path: .\n"
            "    family: client-fam\n"
            "    under_test: true\n"
            "    build: python3 build.py\n"
            "    binaries: [bin/udp_echo_client.py]\n"
            "    start: python3 bin/udp_echo_client.py --port 47321 --payload-file vectors/payload.bin\n"
            f"capture: {{interface: {IFACE}, filter: udp}}\n"
            "cells:\n"
            "  - name: cell-a\n"
            "    server: echo-server\n"
            "    clients: [echo-client]\n"
            "    checkers: [observes-a]\n"
            "    timeout_s: 10\n"
            "  - name: cell-b\n"
            "    server: echo-server\n"
            "    clients: [echo-client]\n"
            "    checkers: [observes-b]\n"
            "    timeout_s: 10\n"
            "checkers:\n"
            "  - name: observes-a\n"
            "    family: chk-fam\n"
            "    observes_capture: true\n"
            "    command: python3 check_capture.py --port 47321 {capture}\n"
            "    inputs: []\n"
            "    negatives:\n"
            '      - {input: negatives/unrelated.pcap, replaces: "{capture}"}\n'
            '      - {input: negatives/no_echo.pcap, replaces: "{capture}"}\n'
            "  - name: observes-b\n"
            "    family: chk-fam\n"
            "    observes_capture: true\n"
            f"    command: python3 check_capture.py --port {port_b} {{capture}}\n"
            "    inputs: []\n"
            "    negatives:\n"
            '      - {input: negatives/unrelated.pcap, replaces: "{capture}"}\n'
            '      - {input: negatives/no_echo.pcap, replaces: "{capture}"}\n'
        )
        exp_two = tmp / "exp_two"
        shutil.copytree(EXAMPLE, exp_two)
        (exp_two / "interop.yaml").write_text(two_cells_manifest, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=exp_two, check=True)
        subprocess.run(["git", "add", "-A"], cwd=exp_two, check=True)
        subprocess.run(
            [*GIT_AUTHOR, "commit", "-qm", "two cells"], cwd=exp_two, check=True
        )

        out_two = tmp / "out_two"
        r_cell_b = wire(
            "run",
            str(exp_two / "interop.yaml"),
            "--cell",
            "cell-b",
            "--out",
            str(out_two),
        )
        assert r_cell_b.returncode == 1
        assert verdict_of(out_two, "cell-b")["verdict"] == "FAIL"


# =============================================================================
# AC8: Manifest validation exits 2 before any env check, build, start or capture
# =============================================================================


def test_ac8_manifest_validation_rejects_malformed_inputs() -> None:
    """AC8: Manifest validation exits 2 before any execution for all invalid manifest conditions."""
    validation_cases = {
        "checker family equals peer": [
            ("family: example-checker", "family: example-server")
        ],
        "missing peer family": [("family: example-client", 'family: ""')],
        "duplicate peer": [("name: echo-client", "name: echo-server")],
        "undefined peer": [("clients: [echo-client]", "clients: [unknown_peer]")],
        "observes not bool": [
            ("observes_capture: true", 'observes_capture: "not_a_bool"')
        ],
        "cell without observes_capture": [
            ("checkers: [observes-echo, vector]", "checkers: [vector]")
        ],
        "checker with no negatives": [
            (
                (
                    "    negatives:\n"
                    '      - {input: negatives/unrelated.pcap, replaces: "{capture}"}\n'
                    '      - {input: negatives/no_echo.pcap, replaces: "{capture}"}'
                ),
                "    negatives: []",
            )
        ],
        "observes_capture with < 2 capture negatives": [
            (
                '      - {input: negatives/unrelated.pcap, replaces: "{capture}"}\n',
                "",
            )
        ],
        "negative input does not exist": [
            ("negatives/unrelated.pcap", "negatives/nonexistent_file.pcap")
        ],
        "negative replaces invalid": [
            ("replaces: vectors/payload.bin", "replaces: vectors/wrong_name.bin")
        ],
        "cell with client equal to server": [
            ("clients: [echo-client]", "clients: [echo-server]")
        ],
        "cell naming same client twice": [
            ("clients: [echo-client]", "clients: [echo-client, echo-client]")
        ],
    }

    for name, edits in validation_cases.items():
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            marker = tmp / "marker_env_executed"
            combined_edits = [
                *edits,
                (
                    'command: python3 -c "import sys"',
                    f"command: python3 -c \"import pathlib; pathlib.Path('{marker}').touch()\"",
                ),
            ]
            manifest = make_exp(tmp, edits=combined_edits)
            out = tmp / "out"
            r = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
            assert r.returncode == 2, (
                f"case {name!r} expected exit 2, got {r.returncode}: {r.stdout}\n{r.stderr}"
            )
            assert not marker.exists(), (
                f"case {name!r} executed env check before manifest validation"
            )
            assert not out.exists(), f"case {name!r} created out directory"


# =============================================================================
# AC9: env.json records, binary hashing, clean experiment directory
# =============================================================================


def test_ac9_env_json_records_integrity_and_dirty_blocked() -> None:
    """AC9: env.json records git state, binary hashes, dirty experiment dir yields BLOCKED, hash changes on build change."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        manifest = make_exp(tmp)
        out = tmp / "out"
        r = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert r.returncode == 0
        bundle = out / "echo"
        env = json.loads((bundle / "env.json").read_text(encoding="utf-8"))

        # Verify manifest sha256
        actual_manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
        assert env["manifest_sha256"] == actual_manifest_sha

        # Verify experiment git state
        assert env["experiment"]["dirty"] is False
        assert len(env["experiment"]["commit"]) == 40

        # Verify peers git state and binary sha256
        server_binaries = env["peers"]["echo-server"]["binaries"]
        assert len(server_binaries) == 1
        for bin_path_str, expected_hash in server_binaries.items():
            actual_hash = hashlib.sha256(Path(bin_path_str).read_bytes()).hexdigest()
            assert actual_hash == expected_hash

        # Verify checker inputs and negatives are hashed
        assert "vectors/payload.bin" in env["checker_inputs"]
        assert "negatives/unrelated.pcap" in env["checker_inputs"]
        assert "negatives/no_echo.pcap" in env["checker_inputs"]

        # Dirty experiment directory (untracked file) yields BLOCKED (exit 3)
        (manifest.parent / "untracked_script.py").write_text("print('dirty')")
        out_dirty = tmp / "out_dirty"
        r_dirty = wire("run", str(manifest), "--cell", "echo", "--out", str(out_dirty))
        assert r_dirty.returncode == 3
        v_dirty = verdict_of(out_dirty)
        assert v_dirty["verdict"] == "BLOCKED"
        assert "uncommitted or untracked" in v_dirty["reason"]

        # Build that changes binary bytes changes the recorded hash
        (manifest.parent / "untracked_script.py").unlink()
        server_src = manifest.parent / "src" / "udp_echo_server.py"
        server_src.write_text(server_src.read_text() + "\n# modification\n")
        subprocess.run(["git", "add", "-A"], cwd=manifest.parent, check=True)
        subprocess.run(
            [*GIT_AUTHOR, "commit", "-qm", "modify server"],
            cwd=manifest.parent,
            check=True,
        )

        out_modified = tmp / "out_modified"
        r_mod = wire("run", str(manifest), "--cell", "echo", "--out", str(out_modified))
        assert r_mod.returncode == 0
        env_mod = json.loads(
            (out_modified / "echo" / "env.json").read_text(encoding="utf-8")
        )
        mod_hash = next(iter(env_mod["peers"]["echo-server"]["binaries"].values()))
        assert mod_hash != next(iter(server_binaries.values()))


# =============================================================================
# AC10: Test vector copied into inputs/ and checked
# =============================================================================


def test_ac10_vector_checking_and_bundle_inputs() -> None:
    """AC10: Vector copied to bundle inputs/ and listed in SHA256SUMS; vector checker passes on vector and fails on flipped byte."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        manifest = make_exp(tmp)
        out = tmp / "out"
        r = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert r.returncode == 0
        bundle = out / "echo"

        # Check input copied into inputs/
        vector_dest = bundle / "inputs" / "vectors" / "payload.bin"
        assert vector_dest.is_file()

        # Check covered by SHA256SUMS
        sums_text = (bundle / "SHA256SUMS").read_text(encoding="utf-8")
        assert "inputs/vectors/payload.bin" in sums_text

        # Run example's vector checker directly
        checker_script = manifest.parent / "check_vector.py"
        # Parse port from manifest
        port_line = next(
            ln
            for ln in manifest.read_text().splitlines()
            if "bin/udp_echo_server.py --port" in ln
        )
        port = port_line.split("--port")[-1].strip()

        # Passes on example vector
        r_vec_ok = subprocess.run(
            [
                sys.executable,
                str(checker_script),
                "--port",
                port,
                str(bundle / "capture.pcap"),
                str(vector_dest),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert r_vec_ok.returncode == 0, (
            f"check_vector failed on matching vector: {r_vec_ok.stdout}\n{r_vec_ok.stderr}"
        )

        # Fails on vector with one byte flipped
        flipped_vec = manifest.parent / "vectors" / "payload_flipped.bin"
        r_vec_flip = subprocess.run(
            [
                sys.executable,
                str(checker_script),
                "--port",
                port,
                str(bundle / "capture.pcap"),
                str(flipped_vec),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert r_vec_flip.returncode != 0, "check_vector succeeded on flipped vector"


# =============================================================================
# AC11: ./orch interop removed and no cross imports between wire and orchestrator
# =============================================================================


def test_ac11_orch_interop_removed_and_no_cross_imports() -> None:
    """AC11: ./orch interop exits 2 (usage error); AST scan verifies zero imports between wire/ and orchestrator.py."""
    # 1. orch interop exits 2
    r = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "orchestrator.py"),
            "interop",
            "M08",
            "dummy_path",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=ENV,
    )
    assert r.returncode == 2, (
        f"expected exit 2 for orch interop, got {r.returncode}: {r.stdout}\n{r.stderr}"
    )

    # 2. AST inspection helper
    def get_imported_modules(path: Path) -> set[str]:
        imported: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                func = node.func
                if (
                    (
                        (isinstance(func, ast.Name) and func.id == "__import__")
                        or (
                            isinstance(func, ast.Attribute)
                            and func.attr == "import_module"
                        )
                    )
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    imported.add(str(node.args[0].value).split(".")[0])
        return imported

    wire_dir = REPO_ROOT / "wire"
    wire_py_files = list(wire_dir.rglob("*.py"))
    assert wire_py_files, "no python files found under wire/"

    for py_file in wire_py_files:
        imports = get_imported_modules(py_file)
        assert "orchestrator" not in imports, (
            f"{py_file} imports orchestrator: {imports}"
        )

    orch_imports = get_imported_modules(REPO_ROOT / "orchestrator.py")
    assert "wire" not in orch_imports, f"orchestrator.py imports wire: {orch_imports}"
