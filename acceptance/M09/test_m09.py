"""Acceptance tests for milestone M09: Secured protocols in wire bundles.

All tests are hermetic and run against temporary repositories.
Compatible with both real pytest and src/_shims/pytest.py (no fixtures).
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / "wire" / "example" / "tls_echo"
M08_EXAMPLE = REPO_ROOT / "wire" / "example" / "udp_echo"
IFACE = "lo0" if sys.platform == "darwin" else "lo"
ENV = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
GIT = ["git", "-c", "user.email=v@ai2ii.invalid", "-c", "user.name=verifier"]

SECRET_NEG = '      - {input: negatives/client.keys.altered, replaces: "{secrets}/client.keys"}\n'
DECRYPTED_NEG = (
    '      - {input: negatives/other_payload.pcapng, replaces: "{decrypted}"}\n'
)
DECRYPT_BLOCK = (
    "decrypt:\n  command: editcap -F pcapng --inject-secrets "
    "tls,{secrets}/client.keys {capture} {decrypted}\n"
)
CLIENT_ENV = 'env: {SSLKEYLOGFILE: "{secrets}/client.keys"}'
SERVER_ENV = 'env: {SSLKEYLOGFILE: "{secrets}/server.keys"}'


def wire(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "wire", *args],
        cwd=REPO_ROOT,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def need_tools() -> None:
    for tool in ("tcpdump", "editcap", "tshark"):
        assert shutil.which(tool), f"required tool missing: {tool}"
    p = subprocess.Popen(
        ["tcpdump", "-i", IFACE, "-w", os.devnull],
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
    )
    try:
        time.sleep(0.5)
        assert p.poll() is None, "capture interface not capturable by current user"
    finally:
        if p.poll() is None:
            p.terminate()
        p.wait()


def make_exp(
    tmp: Path,
    edits: list[tuple[str, str]] | tuple[()] = (),
    files: dict[str, str] | None = None,
) -> Path:
    """Copy the TLS example, customize port/iface, apply edits, and commit."""
    exp = tmp / "exp"
    shutil.copytree(EXAMPLE, exp, ignore=shutil.ignore_patterns("__pycache__"))
    port = free_port()
    text = (exp / "interop.yaml").read_text(encoding="utf-8")
    for old, new in edits:
        assert old in text, f"replacement target {old!r} not found in manifest"
        text = text.replace(old, new)
    text = text.replace("47443", str(port)).replace("lo0", IFACE)
    (exp / "interop.yaml").write_text(text, encoding="utf-8")
    for name, content in (files or {}).items():
        target = exp / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
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
    subprocess.run(["git", "init", "-q"], cwd=exp, check=True)
    subprocess.run(["git", "add", "-A"], cwd=exp, check=True)
    subprocess.run([*GIT, "commit", "-qm", "initial commit"], cwd=exp, check=True)
    return exp / "interop.yaml"


def test_ac1_tls_example_passes_and_bundle_artifacts() -> None:
    """AC1: TLS example run exits 0, PASS, encrypted capture, secrets, decrypted view, log, sums, contains_secrets."""
    need_tools()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(tmp)
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 0, (
            f"run failed ({res.returncode}): {res.stderr}\n{res.stdout}"
        )

        bundle = out / "echo"
        v_data = json.loads((bundle / "verdict.json").read_text(encoding="utf-8"))
        assert v_data["verdict"] == "PASS"
        assert v_data["contains_secrets"] is True

        # capture.pcap must exist and NOT contain the payload in cleartext
        cap = bundle / "capture.pcap"
        assert cap.is_file() and cap.stat().st_size > 0
        raw_cap = cap.read_bytes()
        assert b"tls-example-payload" not in raw_cap

        # secrets/ must contain non-empty key logs
        for k in ("client.keys", "server.keys"):
            kpath = bundle / "secrets" / k
            assert kpath.is_file(), f"missing secret file {k}"
            assert kpath.stat().st_size > 0, f"empty secret file {k}"

        # capture-decrypted.pcapng must exist and tshark must show payload in application data
        dec = bundle / "capture-decrypted.pcapng"
        assert dec.is_file() and dec.stat().st_size > 0
        tshark_out = subprocess.run(
            ["tshark", "-r", str(dec), "-T", "fields", "-e", "data.data"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        payload_hex = b"tls-example-payload".hex()
        assert payload_hex in tshark_out.replace(":", "").lower()

        # decrypt.log must exist
        assert (bundle / "decrypt.log").is_file()

        # SHA256SUMS must list all artifacts
        sums = (bundle / "SHA256SUMS").read_text(encoding="utf-8")
        for expected in (
            "  capture.pcap\n",
            "  capture-decrypted.pcapng\n",
            "  decrypt.log\n",
            "  secrets/client.keys\n",
            "  secrets/server.keys\n",
            "  verdict.json\n",
        ):
            assert expected in sums, f"missing {expected.strip()} in SHA256SUMS"

        # verify-bundle must confirm integrity
        v_res = wire("verify-bundle", str(bundle))
        assert v_res.returncode == 0, f"verify-bundle failed: {v_res.stdout}"


def test_ac2_peer_missing_or_empty_secret_yields_blocked() -> None:
    """AC2: A peer declaring a secret but not writing it (or writing it empty) yields BLOCKED (exit 3)."""
    need_tools()
    # Case 1: secret file not written
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(
            tmp,
            edits=[(CLIENT_ENV, 'env: {SSLKEYLOGFILE: "{secrets}/unwritten.keys"}')],
        )
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 3, (
            f"expected BLOCKED (3), got {res.returncode}: {res.stdout}"
        )
        v_data = json.loads((out / "echo" / "verdict.json").read_text(encoding="utf-8"))
        assert v_data["verdict"] == "BLOCKED"
        assert "client.keys" in v_data["reason"]
        assert not (out / "echo" / "decrypt.log").exists()
        assert not (out / "echo" / "checker-observes-tls.log").exists()

    # Case 2: secret file written empty
    empty_script = (
        "import os, sys\n"
        "open(sys.argv[1], 'w').close()\n"
        "os.execv(sys.executable, [sys.executable, 'src/tls_client.py', *sys.argv[2:]])\n"
    )
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(
            tmp,
            edits=[
                (CLIENT_ENV, 'env: {DUMMY: "1"}'),
                (
                    "start: python3 src/tls_client.py --port",
                    "start: python3 empty_client.py {secrets}/client.keys --port",
                ),
            ],
            files={"empty_client.py": empty_script},
        )
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 3, (
            f"expected BLOCKED (3), got {res.returncode}: {res.stdout}"
        )
        v_data = json.loads((out / "echo" / "verdict.json").read_text(encoding="utf-8"))
        assert v_data["verdict"] == "BLOCKED"
        assert "client.keys" in v_data["reason"]
        assert not (out / "echo" / "decrypt.log").exists()
        assert not (out / "echo" / "checker-observes-tls.log").exists()


def test_ac3_decrypt_step_failure_yields_fail_keeping_capture() -> None:
    """AC3: Decrypt command exiting non-zero or leaving {decrypted} missing/empty yields FAIL (exit 1)."""
    need_tools()
    failures = (
        ('python3 -c "import sys; sys.exit(1)"', "non-zero exit"),
        ('python3 -c "pass"', "missing output"),
        (
            "python3 -c \"import sys; open(sys.argv[1], 'w').close()\" {decrypted}",
            "zero bytes output",
        ),
    )
    for cmd, desc in failures:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            manifest = make_exp(
                tmp,
                edits=[(DECRYPT_BLOCK.split("command: ")[1].strip(), cmd)],
            )
            out = tmp / "out"
            res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
            assert res.returncode == 1, (
                f"expected FAIL (1) for {desc}, got {res.returncode}: {res.stdout}"
            )
            v_data = json.loads(
                (out / "echo" / "verdict.json").read_text(encoding="utf-8")
            )
            assert v_data["verdict"] == "FAIL"
            assert v_data["reason"] == "decrypt failed"
            cap = out / "echo" / "capture.pcap"
            assert cap.is_file() and cap.stat().st_size > 0
            sums = (out / "echo" / "SHA256SUMS").read_text(encoding="utf-8")
            assert "  capture.pcap\n" in sums
            assert not (out / "echo" / "checker-observes-tls.log").exists()


def test_ac4_observes_decrypted_negatives_and_scratch_rerun() -> None:
    """AC4: Negatives replace secrets and decrypted view; mutant checkers fail with reason 'checker accepts negative'."""
    need_tools()
    # Part 1: Normal run verifies scratch re-run does not modify capture-decrypted.pcapng
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(tmp)
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 0
        bundle = out / "echo"
        dec = bundle / "capture-decrypted.pcapng"
        assert dec.is_file()
        log = (bundle / "checker-decrypted-payload.log").read_text(encoding="utf-8")
        assert "replaces {secrets}/client.keys" in log
        assert "replaces {decrypted}" in log
        sums = (bundle / "SHA256SUMS").read_text(encoding="utf-8")
        h_cmd = subprocess.run(
            ["shasum", "-a", "256", str(dec)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()[0]
        assert f"{h_cmd}  capture-decrypted.pcapng\n" in sums

    # Part 2: Mutant checker that only tests {decrypted} exists
    exists_body = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.exit(0 if Path(sys.argv[1]).is_file() else 1)\n"
    )
    old_cmd = "command: python3 check_decrypted.py --port 47443 {decrypted} {inputs}/vectors/payload.bin"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(
            tmp,
            edits=[(old_cmd, "command: python3 mutant_exists.py {decrypted}")],
            files={"mutant_exists.py": exists_body},
        )
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 1, f"expected FAIL, got {res.returncode}: {res.stdout}"
        v_data = json.loads((out / "echo" / "verdict.json").read_text(encoding="utf-8"))
        assert v_data["verdict"] == "FAIL"
        assert v_data["reason"] == "checker accepts negative: decrypted-payload"

    # Part 3: Mutant checker that only inspects key file in secrets/ and never reads {decrypted}
    keys_body = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.exit(0 if Path(sys.argv[1]).read_text().strip() else 1)\n"
    )
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(
            tmp,
            edits=[(old_cmd, "command: python3 mutant_keys.py {secrets}/client.keys")],
            files={"mutant_keys.py": keys_body},
        )
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 1, f"expected FAIL, got {res.returncode}: {res.stdout}"
        v_data = json.loads((out / "echo" / "verdict.json").read_text(encoding="utf-8"))
        assert v_data["verdict"] == "FAIL"
        assert v_data["reason"] == "checker accepts negative: decrypted-payload"


def test_ac5_observes_capture_asserts_encrypted_negative() -> None:
    """AC5: observes_capture checker rejects asserts: encrypted; raw checker accepting it makes cell FAIL."""
    need_tools()
    # 1. Normal run: observes-tls checker passes and rejects cleartext.pcap
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(tmp)
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 0
        bundle = out / "echo"
        log = (bundle / "checker-observes-tls.log").read_text(encoding="utf-8")
        assert "negative: negatives/cleartext.pcap replaces {capture}" in log

    # 2. Raw checker: finds the bidirectional TCP exchange on port, so accepts cleartext.pcap
    # but rejects unrelated and one_direction.
    raw_checker = (
        "import argparse, sys\n"
        "sys.path.insert(0, '.')\n"
        "from tcp_pcap import segments\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.add_argument('--port', type=int, required=True)\n"
        "ap.add_argument('pcap')\n"
        "args = ap.parse_args()\n"
        "segs = segments(args.pcap)\n"
        "host = '127.0.0.1'\n"
        "up = any((s.dst, s.dport) == (host, args.port) and s.payload for s in segs)\n"
        "down = any((s.src, s.sport) == (host, args.port) and s.payload for s in segs)\n"
        "sys.exit(0 if (up and down) else 1)\n"
    )
    old_cmd = "command: python3 check_capture.py --port 47443 {capture}"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(
            tmp,
            edits=[(old_cmd, "command: python3 raw.py --port 47443 {capture}")],
            files={"raw.py": raw_checker},
        )
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 1, f"expected FAIL, got {res.returncode}: {res.stdout}"
        v_data = json.loads((out / "echo" / "verdict.json").read_text(encoding="utf-8"))
        assert v_data["verdict"] == "FAIL"
        assert v_data["reason"] == "checker accepts negative: observes-tls"
        log = (out / "echo" / "checker-observes-tls.log").read_text(encoding="utf-8")
        assert "negative: negatives/cleartext.pcap replaces {capture}" in log


def test_ac6_manifest_validation_rejects_invalid_configs() -> None:
    """AC6: Manifest validation exits 2 before any env check, build, start or capture on malformed configurations."""
    cases = {
        "cell lacks observes_decrypted checker": (
            [
                (
                    "checkers: [observes-tls, decrypted-payload]",
                    "checkers: [observes-tls]",
                )
            ],
            "observes_decrypted",
        ),
        "observes_decrypted lacks secret negative": (
            [(SECRET_NEG, "")],
            "observes_decrypted checker needs",
        ),
        "observes_decrypted lacks decrypted negative": (
            [(DECRYPTED_NEG, "")],
            "observes_decrypted checker needs",
        ),
        "negative replaces undeclared secret": (
            [
                (
                    'replaces: "{secrets}/client.keys"}',
                    'replaces: "{secrets}/unseen.keys"}',
                )
            ],
            "undeclared secret",
        ),
        "secret name path traversal": (
            [("secrets: [client.keys]", "secrets: [../capture.pcap]")],
            "invalid secret name",
        ),
        "secret name absolute": (
            [("secrets: [client.keys]", "secrets: [/var/tmp/key]")],
            "invalid secret name",
        ),
        "secret name with path separator": (
            [("secrets: [client.keys]", "secrets: [sub/key]")],
            "invalid secret name",
        ),
        "secret name is dot": (
            [("secrets: [client.keys]", 'secrets: ["."]')],
            "invalid secret name",
        ),
        "secret name is dotdot": (
            [("secrets: [client.keys]", 'secrets: [".."]')],
            "invalid secret name",
        ),
        "secret name invalid chars": (
            [("secrets: [client.keys]", 'secrets: ["key file"]')],
            "invalid secret name",
        ),
        "secret declared twice across peers": (
            [("secrets: [client.keys]", "secrets: [server.keys]")],
            "declared twice",
        ),
        "observes_decrypted is not boolean": (
            [("observes_decrypted: true", 'observes_decrypted: "yes"')],
            "boolean",
        ),
        "decrypt present but empty mapping": (
            [(DECRYPT_BLOCK, "decrypt: {}\n")],
            "decrypt",
        ),
        "decrypt command is empty string": (
            [(DECRYPT_BLOCK, 'decrypt:\n  command: ""\n')],
            "decrypt",
        ),
        "observes_capture checker has no asserts: encrypted negative": (
            [(", asserts: encrypted", "")],
            "asserts: encrypted",
        ),
        "asserts has value other than encrypted": (
            [("asserts: encrypted", "asserts: plaintext")],
            "asserts",
        ),
        "decrypted used without experiment decrypt": (
            [(DECRYPT_BLOCK, "")],
            "no decrypt",
        ),
        "peer env is not a mapping": (
            [(SERVER_ENV, "env: [VAR]")],
            "mapping of strings",
        ),
        "peer env values are not strings": (
            [(SERVER_ENV, "env: {PORT: 47443}")],
            "mapping of strings",
        ),
    }

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, (edits, needle) in cases.items():
            case_dir = tmp / f"case_{abs(hash(name))}"
            case_dir.mkdir()
            manifest = make_exp(case_dir, edits=edits)
            out = case_dir / "out"
            res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
            assert res.returncode == 2, (
                f"case {name} expected exit 2, got {res.returncode}: {res.stderr}\n{res.stdout}"
            )
            assert needle in res.stderr, (
                f"case {name} expected {needle!r} in stderr, got: {res.stderr}"
            )
            assert not out.exists(), (
                f"case {name} created output dir before validation finished"
            )


def test_ac7_peer_env_and_secrets_expansion() -> None:
    """AC7: Peer env variables present with {secrets} expanded, absent from other peers; {secrets} exists before build."""
    need_tools()
    server_check = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "s_var = os.environ.get('SRV_SECRET')\n"
        "assert s_var and Path(s_var).is_absolute() and Path(s_var).is_dir(), s_var\n"
        "assert 'CLI_SECRET' not in os.environ, 'client env leaked to server'\n"
    )
    client_check = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "c_var = os.environ.get('CLI_SECRET')\n"
        "assert c_var and Path(c_var).is_absolute() and Path(c_var).is_dir(), c_var\n"
        "assert 'SRV_SECRET' not in os.environ, 'server env leaked to client'\n"
    )
    # We prepend environment assertions to the server and client start commands
    files = {
        "check_server.py": server_check,
        "check_client.py": client_check,
    }
    edits = [
        (
            SERVER_ENV,
            'env: {SSLKEYLOGFILE: "{secrets}/server.keys", SRV_SECRET: "{secrets}"}',
        ),
        (
            CLIENT_ENV,
            'env: {SSLKEYLOGFILE: "{secrets}/client.keys", CLI_SECRET: "{secrets}"}',
        ),
        (
            "start: python3 src/tls_server.py --port",
            "start: python3 -c \"import check_server; import runpy; runpy.run_path('src/tls_server.py')\" --port",
        ),
        (
            "start: python3 src/tls_client.py --port",
            "start: python3 -c \"import check_client; import runpy; runpy.run_path('src/tls_client.py')\" --port",
        ),
        (
            "name: tls-server\n    path: .",
            "name: tls-server\n    path: .\n    build: python3 -c \"from pathlib import Path; assert Path('{secrets}').is_dir()\"",
        ),
    ]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(tmp, edits=edits, files=files)
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 0, f"run failed: {res.stderr}\n{res.stdout}"
        v_data = json.loads((out / "echo" / "verdict.json").read_text(encoding="utf-8"))
        assert v_data["verdict"] == "PASS"


def test_ac8_secret_symlink_env_json_and_bundle_integrity() -> None:
    """AC8: Symlinked secret yields BLOCKED; env.json records decrypt sha256; verify-bundle checks integrity."""
    need_tools()
    # 1. Symlink secret yields BLOCKED
    symlink_script = (
        "import os, sys, tempfile\n"
        "tgt = tempfile.mkstemp()[1]\n"
        "os.symlink(tgt, sys.argv[1])\n"
        "os.environ['SSLKEYLOGFILE'] = tgt\n"
        "os.execv(sys.executable, [sys.executable, 'src/tls_client.py', *sys.argv[2:]])\n"
    )
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(
            tmp,
            edits=[
                (
                    "start: python3 src/tls_client.py --port",
                    "start: python3 link_client.py {secrets}/client.keys --port",
                )
            ],
            files={"link_client.py": symlink_script},
        )
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 3, (
            f"expected BLOCKED, got {res.returncode}: {res.stdout}"
        )
        v_data = json.loads((out / "echo" / "verdict.json").read_text(encoding="utf-8"))
        assert v_data["verdict"] == "BLOCKED"
        assert "symlink" in v_data["reason"]
        assert "client.keys" in v_data["reason"]

    # 2. env.json records decrypt executable absolute path and sha256; modifying binary changes sha256
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        wrapper = tmp / "dec_wrap.sh"
        wrapper.write_text('#!/bin/sh\nexec editcap "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        manifest = make_exp(
            tmp,
            edits=[("command: editcap -F", f"command: {wrapper} -F")],
        )
        res1 = wire("run", str(manifest), "--cell", "echo", "--out", str(tmp / "out1"))
        assert res1.returncode == 0, f"run 1 failed: {res1.stderr}"
        env1 = json.loads(
            (tmp / "out1" / "echo" / "env.json").read_text(encoding="utf-8")
        )
        assert env1["decrypt"]["executable"] == str(wrapper)
        sha1 = env1["decrypt"]["sha256"]
        assert len(sha1) == 64

        # Modify wrapper bytes without changing manifest or secrets
        wrapper.write_text(
            '#!/bin/sh\n# altered\nexec editcap "$@"\n', encoding="utf-8"
        )
        res2 = wire("run", str(manifest), "--cell", "echo", "--out", str(tmp / "out2"))
        assert res2.returncode == 0, f"run 2 failed: {res2.stderr}"
        env2 = json.loads(
            (tmp / "out2" / "echo" / "env.json").read_text(encoding="utf-8")
        )
        sha2 = env2["decrypt"]["sha256"]
        assert sha1 != sha2

    # 3. verify-bundle exits 1 on tamper
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        manifest = make_exp(tmp)
        out = tmp / "out"
        res = wire("run", str(manifest), "--cell", "echo", "--out", str(out))
        assert res.returncode == 0
        bundle = out / "echo"

        def tamper_test(mutator: Callable[[Path], None]) -> None:
            c = tmp / "copy"
            shutil.copytree(bundle, c)
            mutator(c)
            rc = wire("verify-bundle", str(c)).returncode
            shutil.rmtree(c)
            assert rc == 1

        tamper_test(lambda b: (b / "secrets" / "client.keys").write_bytes(b"bad"))
        tamper_test(lambda b: (b / "capture-decrypted.pcapng").write_bytes(b"bad"))
        tamper_test(lambda b: (b / "decrypt.log").write_bytes(b"bad"))
        tamper_test(lambda b: (b / "secrets" / "server.keys").unlink())
        tamper_test(lambda b: (b / "decrypt.log").unlink())
        tamper_test(lambda b: (b / "secrets" / "unlisted.key").write_text("x"))


def test_ac9_m08_compatibility_and_unsecured_bundle() -> None:
    """AC9: Unsecured experiment has no secrets/, capture-decrypted.pcapng, decrypt.log; contains_secrets is false; M08 passes."""
    need_tools()
    # 1. Run M08 acceptance suite unchanged
    m08_res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "acceptance/M08/test_m08.py",
        ],
        cwd=REPO_ROOT,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    assert m08_res.returncode == 0, (
        f"M08 acceptance suite failed:\n{m08_res.stdout}\n{m08_res.stderr}"
    )

    # 2. Run un-secured experiment (udp_echo example)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        exp = tmp / "exp"
        shutil.copytree(M08_EXAMPLE, exp, ignore=shutil.ignore_patterns("__pycache__"))
        port = free_port()
        text = (exp / "interop.yaml").read_text(encoding="utf-8")
        text = text.replace("47443", str(port)).replace("lo0", IFACE)
        (exp / "interop.yaml").write_text(text, encoding="utf-8")
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
        subprocess.run(["git", "init", "-q"], cwd=exp, check=True)
        subprocess.run(["git", "add", "-A"], cwd=exp, check=True)
        subprocess.run([*GIT, "commit", "-qm", "initial"], cwd=exp, check=True)

        out = tmp / "out"
        res = wire(
            "run", str(exp / "interop.yaml"), "--cell", "echo", "--out", str(out)
        )
        assert res.returncode == 0, (
            f"unsecured run failed ({res.returncode}): {res.stderr}\n{res.stdout}"
        )
        bundle = out / "echo"
        v_data = json.loads((bundle / "verdict.json").read_text(encoding="utf-8"))
        assert v_data["verdict"] == "PASS"
        assert v_data["contains_secrets"] is False
        assert not (bundle / "secrets").exists(), (
            "unsecured bundle must not contain secrets/"
        )
        assert not (bundle / "capture-decrypted.pcapng").exists(), (
            "unsecured bundle must not contain capture-decrypted.pcapng"
        )
        assert not (bundle / "decrypt.log").exists(), (
            "unsecured bundle must not contain decrypt.log"
        )


def test_ac10_no_protocol_knowledge_in_wire() -> None:
    """AC10: wire/ contains no protocol knowledge (no references to editcap, tshark, SSLKEYLOGFILE, etc.)."""
    terms = ("editcap", "tshark", "sslkeylogfile", "tls", "dtls", "quic", "oscore")
    wire_dir = REPO_ROOT / "wire"
    assert wire_dir.is_dir()

    # Exclude wire/example/
    for py_file in wire_dir.rglob("*.py"):
        if "example" in py_file.relative_to(wire_dir).parts:
            continue
        content = py_file.read_text(encoding="utf-8").lower()
        for term in terms:
            assert term not in content, (
                f"wire module {py_file} contains protocol term {term!r}"
            )

    # Confirm those terms DO appear in example
    example_text = " ".join(
        p.read_text(encoding="utf-8").lower()
        for p in (wire_dir / "example").rglob("*")
        if p.is_file() and not p.name.endswith((".pcap", ".pcapng", ".pem"))
    )
    for term in ("editcap", "tshark", "sslkeylogfile", "tls"):
        assert term in example_text, (
            f"expected term {term!r} to appear in example experiment"
        )
