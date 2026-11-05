"""Hermetic tests for wire/ secured-protocol support (M09): every experiment is a throwaway git repo."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "wire" / "example" / "tls_echo"
IFACE = "lo0" if sys.platform == "darwin" else "lo"
ENV = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
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


def wire(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "wire", *args],
        cwd=ROOT,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
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


def make_exp(tmp: Path, edits=(), files=None) -> Path:
    """Copy the TLS example, give it a free port, apply (old, new) manifest edits, git-commit it."""
    exp = tmp / "exp"
    copy_tracked(EXAMPLE, exp)
    port = free_port()
    text = (exp / "interop.yaml").read_text()
    for old, new in edits:
        assert old in text, old
        text = text.replace(old, new)
    text = text.replace("47443", str(port)).replace(
        "interface: loopback", f"interface: {IFACE}"
    )
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
    subprocess.run(["git", "init", "-q"], cwd=exp, check=True)
    subprocess.run(["git", "add", "-A"], cwd=exp, check=True)
    subprocess.run([*GIT, "commit", "-qm", "x"], cwd=exp, check=True)
    return exp / "interop.yaml"


def run_cell(manifest: Path, out: Path):
    return wire("run", str(manifest), "--cell", "echo", "--out", str(out))


def verdict_of(out: Path) -> dict:
    return json.loads((out / "echo" / "verdict.json").read_text())


def need_tools() -> None:
    for tool in ("tcpdump", "editcap", "tshark"):
        assert shutil.which(tool), f"{tool} is required on PATH"
    p = subprocess.Popen(
        ["tcpdump", "-i", IFACE, "-w", os.devnull],
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
    )
    try:
        time.sleep(1)
        assert p.poll() is None, "capture interface not capturable by this user"
    finally:
        if p.poll() is None:
            p.terminate()
        p.wait()


def run_with(edits=(), files=None):
    """Run the echo cell of an edited example in a fresh temp dir; return (result, out, tmp-keeper)."""
    need_tools()
    t = tempfile.TemporaryDirectory()
    tmp = Path(t.name)
    r = run_cell(make_exp(tmp, edits, files), tmp / "out")
    return r, tmp / "out", t


def reason_of(out: Path) -> str:
    return verdict_of(out)["reason"]


def test_tls_example_passes_with_both_views() -> None:
    r, out, t = run_with()
    with t:
        assert r.returncode == 0, r.stdout + r.stderr
        b = out / "echo"
        assert verdict_of(out)["verdict"] == "PASS"
        assert verdict_of(out)["contains_secrets"] is True
        for name in ("capture.pcap", "capture-decrypted.pcapng", "decrypt.log"):
            assert (b / name).is_file(), name
        assert (b / "capture-decrypted.pcapng").stat().st_size > 0
        for key in ("client.keys", "server.keys"):
            assert (b / "secrets" / key).stat().st_size > 0
        assert b"tls-example-payload" not in (b / "capture.pcap").read_bytes()
        shown = subprocess.run(
            [
                "tshark",
                "-r",
                str(b / "capture-decrypted.pcapng"),
                "-T",
                "fields",
                "-e",
                "data.data",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        assert b"tls-example-payload".hex() in shown.replace(":", "")
        sums = (b / "SHA256SUMS").read_text()
        for name in (
            "capture.pcap",
            "capture-decrypted.pcapng",
            "decrypt.log",
            "secrets/client.keys",
            "secrets/server.keys",
        ):
            assert f"  {name}\n" in sums, name
        env = json.loads((b / "env.json").read_text())
        server_env = env["peers"]["tls-server"]["env"]["SSLKEYLOGFILE"]
        client_env = env["peers"]["tls-client"]["env"]["SSLKEYLOGFILE"]
        assert Path(server_env).resolve() == (b / "secrets" / "server.keys").resolve()
        assert server_env != client_env
        assert Path(env["decrypt"]["executable"]).is_absolute()
        assert len(env["decrypt"]["sha256"]) == 64
        assert wire("verify-bundle", str(b)).returncode == 0

        def broken(mutate) -> int:
            copy = out.parent / "copy"
            shutil.copytree(b, copy)
            mutate(copy)
            rc = wire("verify-bundle", str(copy)).returncode
            shutil.rmtree(copy)
            return rc

        def touch(rel: str):
            def f(c: Path) -> None:
                with open(c / rel, "ab") as fh:
                    fh.write(b"x")

            return f

        assert broken(touch("secrets/client.keys")) == 1
        assert broken(touch("capture-decrypted.pcapng")) == 1
        assert broken(touch("decrypt.log")) == 1
        assert broken(lambda c: (c / "secrets" / "server.keys").unlink()) == 1
        assert broken(lambda c: (c / "decrypt.log").unlink()) == 1
        assert broken(lambda c: (c / "secrets" / "extra").write_text("k")) == 1


def test_missing_or_empty_secret_is_blocked_and_nothing_downstream_runs() -> None:
    for client_start in (
        CLIENT_ENV.replace("SSLKEYLOGFILE", "UNRELATED"),
        CLIENT_ENV.replace("{secrets}/client.keys", "{secrets}/other.keys"),
    ):
        r, out, t = run_with([(CLIENT_ENV, client_start)])
        with t:
            assert r.returncode == 3, r.stdout + r.stderr
            assert "client.keys" in reason_of(out)
            b = out / "echo"
            assert not (b / "decrypt.log").exists()
            assert not (b / "checker-observes-tls.log").exists()
    # an empty secret
    files = {
        "empty_client.py": "import os, sys\nopen(sys.argv[1], 'w').close()\nos.execv(sys.executable, [sys.executable, 'src/tls_client.py', *sys.argv[2:]])\n"
    }
    start = "start: python3 src/tls_client.py --port"
    r, out, t = run_with(
        [
            (CLIENT_ENV, 'env: {UNRELATED: "x"}'),
            (start, "start: python3 empty_client.py {secrets}/client.keys --port"),
        ],
        files,
    )
    with t:
        assert r.returncode == 3 and "client.keys" in reason_of(out), r.stdout
        assert not (out / "echo" / "decrypt.log").exists()


def test_symlinked_secret_is_blocked() -> None:
    files = {
        "link_client.py": (
            "import os, sys, tempfile\n"
            "target = tempfile.mkstemp()[1]\n"
            "os.symlink(target, sys.argv[1])\n"
            "os.environ['SSLKEYLOGFILE'] = target\n"
            "os.execv(sys.executable, [sys.executable, 'src/tls_client.py', *sys.argv[2:]])\n"
        )
    }
    start = "start: python3 src/tls_client.py --port"
    r, out, t = run_with(
        [(start, "start: python3 link_client.py {secrets}/client.keys --port")], files
    )
    with t:
        assert r.returncode == 3, r.stdout + r.stderr
        assert "symlink" in reason_of(out) and "client.keys" in reason_of(out)
        assert not (out / "echo" / "decrypt.log").exists()


def test_decrypt_failures_fail_the_cell_and_keep_the_capture() -> None:
    for command in (
        'python3 -c "import sys; sys.exit(1)"',
        'python3 -c "pass"',
        "python3 -c \"import sys; open(sys.argv[1], 'w').close()\" {decrypted}",
    ):
        r, out, t = run_with([(DECRYPT_BLOCK.split("command: ")[1].strip(), command)])
        with t:
            assert r.returncode == 1, r.stdout + r.stderr
            assert reason_of(out) == "decrypt failed"
            b = out / "echo"
            assert (b / "capture.pcap").is_file()
            assert "  capture.pcap\n" in (b / "SHA256SUMS").read_text()
            assert not (b / "checker-observes-tls.log").exists()


def swap_checker(command: str, name: str, body: str):
    old = "command: python3 check_decrypted.py --port 47443 {decrypted} {inputs}/vectors/payload.bin"
    return [(old, f"command: {command}")], {name: body}


def test_decrypted_checker_mutants_are_rejected() -> None:
    exists_only = "import sys\nfrom pathlib import Path\nsys.exit(0 if Path(sys.argv[1]).is_file() else 1)\n"
    key_only = "import sys\nfrom pathlib import Path\nsys.exit(0 if Path(sys.argv[1]).read_text().strip() else 1)\n"
    for command, name, body in (
        ("python3 mutant_exists.py {decrypted}", "mutant_exists.py", exists_only),
        ("python3 mutant_keys.py {secrets}/client.keys", "mutant_keys.py", key_only),
    ):
        edits, files = swap_checker(command, name, body)
        r, out, t = run_with(edits, files)
        with t:
            assert r.returncode == 1, r.stdout + r.stderr
            assert reason_of(out) == "checker accepts negative: decrypted-payload"
    # a real decrypted view of a wrong payload and altered keys are already negatives of the example


def test_raw_capture_checker_accepting_cleartext_fails() -> None:
    raw = (
        "import sys\nsys.path.insert(0, '.')\nfrom tcp_pcap import segments\n"
        "segs = segments(sys.argv[1])\n"
        "sys.exit(0 if any(s.payload for s in segs) else 1)\n"
    )
    edits = [
        (
            "command: python3 check_capture.py --port 47443 {capture}",
            "command: python3 raw.py {capture}",
        )
    ]
    r, out, t = run_with(edits, {"raw.py": raw})
    with t:
        assert r.returncode == 1, r.stdout + r.stderr
        assert reason_of(out) == "checker accepts negative: observes-tls"


def test_scratch_decrypt_never_modifies_the_canonical_view() -> None:
    r, out, t = run_with()
    with t:
        assert r.returncode == 0
        b = out / "echo"
        assert (b / "capture-decrypted.pcapng").is_file()
        log = (b / "checker-decrypted-payload.log").read_text()
        assert "replaces {secrets}/client.keys" in log and "replaces {decrypted}" in log
        sums = dict(
            reversed(line.split("  ", 1))
            for line in (b / "SHA256SUMS").read_text().splitlines()
        )
        digest = subprocess.run(
            ["shasum", "-a", "256", str(b / "capture-decrypted.pcapng")],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()[0]
        assert sums["capture-decrypted.pcapng"] == digest


def test_decrypt_executable_hash_follows_the_executable() -> None:
    need_tools()
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        wrapper = tmp / "dec.sh"
        wrapper.write_text('#!/bin/sh\nexec editcap "$@"\n')
        wrapper.chmod(0o755)
        edits = [("command: editcap -F", f"command: {wrapper} -F")]
        manifest = make_exp(tmp, edits)
        digests = []
        for n in (1, 2):
            r = run_cell(manifest, tmp / f"out{n}")
            assert r.returncode == 0, r.stdout + r.stderr
            env = json.loads((tmp / f"out{n}" / "echo" / "env.json").read_text())
            assert env["decrypt"]["executable"] == str(wrapper)
            digests.append(env["decrypt"]["sha256"])
            wrapper.write_text('#!/bin/sh\n# changed\nexec editcap "$@"\n')
        assert digests[0] != digests[1]


def test_manifest_validation_exits_2_before_anything_runs() -> None:
    cases = {
        "no observes_decrypted in cell": (
            [
                (
                    "checkers: [observes-tls, decrypted-payload]",
                    "checkers: [observes-tls]",
                )
            ],
            "observes_decrypted",
        ),
        "no secrets negative": ([(SECRET_NEG, "")], "observes_decrypted checker needs"),
        "no decrypted negative": (
            [(DECRYPTED_NEG, "")],
            "observes_decrypted checker needs",
        ),
        "undeclared secret": (
            [
                (
                    'replaces: "{secrets}/client.keys"}',
                    'replaces: "{secrets}/nope.keys"}',
                )
            ],
            "undeclared secret",
        ),
        "secret path traversal": (
            [("secrets: [client.keys]", "secrets: [../capture.pcap]")],
            "invalid secret name",
        ),
        "secret absolute": (
            [("secrets: [client.keys]", "secrets: [/etc/passwd]")],
            "invalid secret name",
        ),
        "secret separator": (
            [("secrets: [client.keys]", "secrets: [a/b]")],
            "invalid secret name",
        ),
        "secret dot": (
            [("secrets: [client.keys]", 'secrets: ["."]')],
            "invalid secret name",
        ),
        "secret dotdot": (
            [("secrets: [client.keys]", 'secrets: [".."]')],
            "invalid secret name",
        ),
        "secret charset": (
            [("secrets: [client.keys]", 'secrets: ["a b"]')],
            "invalid secret name",
        ),
        "secret duplicate": (
            [("secrets: [client.keys]", "secrets: [server.keys]")],
            "declared twice",
        ),
        "observes_decrypted not bool": (
            [("observes_decrypted: true", 'observes_decrypted: "yes"')],
            "boolean",
        ),
        "decrypt without command": ([(DECRYPT_BLOCK, "decrypt: {}\n")], "decrypt"),
        "decrypt empty command": (
            [(DECRYPT_BLOCK, 'decrypt:\n  command: ""\n')],
            "decrypt",
        ),
        "no asserts encrypted": ([(", asserts: encrypted", "")], "asserts: encrypted"),
        "bad asserts value": ([("asserts: encrypted", "asserts: plain")], "asserts"),
        "decrypted without decrypt": ([(DECRYPT_BLOCK, "")], "no decrypt"),
        "env list": ([(SERVER_ENV, "env: [A]")], "mapping of strings"),
        "env non-string": ([(SERVER_ENV, "env: {A: 1}")], "mapping of strings"),
    }
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for label, (edits, needle) in cases.items():
            case = tmp / "case"
            case.mkdir()
            manifest = make_exp(case, edits)
            out = case / "out"
            r = run_cell(manifest, out)
            assert r.returncode == 2, (label, r.stdout, r.stderr)
            assert needle in r.stderr, (label, r.stderr)
            assert not out.exists(), label
            shutil.rmtree(case)


def test_wire_source_has_no_protocol_knowledge() -> None:
    names = ("editcap", "tshark", "sslkeylogfile", "tls", "dtls", "quic", "oscore")
    for path in (ROOT / "wire").rglob("*.py"):
        if "example" in path.relative_to(ROOT / "wire").parts:
            continue
        text = path.read_text().lower()
        for name in names:
            assert name not in text, (path, name)
