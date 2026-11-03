"""Acceptance tests for M02: Agent dispatch and git worktree isolation.

Approved criteria: AC1 to AC10 in milestones/M02/spec.yaml.
Hermetic: executes against isolated temporary repositories under tempfile.
Compatible with both real pytest and src/_shims/pytest.py (no fixtures).
"""

import hashlib
import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

SPEC = """id: {id}
title: {id} test milestone
objective: test
depends_on: {deps}
inputs: []
deliverables: []
acceptance:
  AC1: doubling works for 2
  AC2: doubling works for 3
out_of_scope: []
size_hint: S
"""

SRC_OK = "def double(x):\n    return x * 2\n"
BUILDER_TEST = (
    "import sys\nfrom pathlib import Path\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
    "from m01 import double\n\n\ndef test_double():\n    assert double(2) == 4\n"
)
ACC_TEST = (
    "import sys\nfrom pathlib import Path\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))\n"
    "from m01 import double\n\n\ndef test_double_two():\n    assert double(2) == 4\n\n\n"
    "def test_double_three():\n    assert double(3) == 6\n"
)

AGENT_CODE = r"""
import os, subprocess, sys, textwrap
mode, prompt_file = sys.argv[1], sys.argv[2]
extra = sys.argv[3:]
wt = os.getcwd()
name = os.path.basename(wt)                     # e.g. M01-a01-build
m, rest = name.split("-a")
n = int(rest.split("-")[0])
rec = f"milestones/{m}/attempts/{n:02d}"

def git(*a):
    subprocess.run(["git", *a], check=True, capture_output=True)

def bg(path, delay=0.0):
    subprocess.Popen(
        ["sh", "-c", f"sleep {delay}; while true; do echo x >> {path}; sleep 0.1; done"],
        start_new_session=False,
    )

def write(rel, text):
    p = os.path.join(wt, rel)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)

if extra and extra[0].startswith("prompt="):
    prompt_save = extra[0][7:]
    with open(prompt_file, encoding="utf-8") as pf:
        write(prompt_save, pf.read())
    extra = extra[1:]

if mode == "fail":
    sys.exit(3)
if mode == "hang":
    import time
    time.sleep(60)
if mode == "silent":
    sys.exit(0)
if mode == "marker_fail":
    write("marker.txt", "x")
    git("add", "-A"); git("commit", "-q", "-m", "marker")
    write("untracked.txt", "x")
    if extra:
        bg(extra[0])
    sys.exit(1)
if mode == "late_writer":
    write("tests/test_ok.py", "def test_ok():\n    assert True\n")
    write(f"{rec}/build.md", "Status: COMPLETE\n")
    git("add", "-A"); git("commit", "-q", "-m", "build")
    late_target = extra[0] if extra else f"{wt}/late.txt"
    subprocess.Popen(["sh", "-c", f"sleep 1; echo late > {wt}/late.txt; echo late > {late_target}"])
    sys.exit(0)
if mode == "build":
    if os.path.exists("marker.txt") or os.path.exists("untracked.txt"):
        sys.exit(5)
    write("src/m01.py", "def double(x):\n    return x * 2\n")
    write("tests/test_ok.py", "def test_ok():\n    assert True\n")
    write(f"{rec}/build.md", "Status: COMPLETE\n")
    if "touch_orchestrator" in extra:
        write("orchestrator.py", "# agent modified\n")
    git("add", "-A"); git("commit", "-q", "-m", "build")
    sys.exit(0)
if mode == "verify":
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    cv = ""
    if os.path.exists(prompt_file):
        for line in open(prompt_file, encoding="utf-8"):
            if line.startswith("Criteria version: "):
                cv = line.split(": ", 1)[1].strip()
                break
    import yaml
    verdict = extra[0] if extra and extra[0] in ("PASS", "FAIL", "BLOCKED") else "BLOCKED"
    doc = {
        "milestone": m, "attempt": n, "commit": head, "criteria_version": cv,
        "verifier": {"role": "verifier", "family": "f", "model": "x"}, "verdict": verdict,
        "acceptance": {"AC1": {"result": verdict}, "AC2": {"result": verdict}},
        "validity": {}, "findings": [], "claim_audit": [], "required_fixes": [],
    }
    write(f"{rec}/verification.yaml", yaml.safe_dump(doc, sort_keys=False))
    if "touch_acceptance" in extra:
        write(f"acceptance/{m}/rogue.py", "# rogue\n")
    git("add", "-A"); git("commit", "-q", "-m", "verification")
    sys.exit(0)
if mode == "confined":
    main, outside, state_dir = extra[:3]
    results = []
    for target in (
        main + "/MAIN.txt",
        main + "/.git/hooks/pre-commit",
        main + "/.git/config",
        outside,
        state_dir + "/ok.txt",
        wt + "/inside.txt",
    ):
        try:
            if target.endswith("/.git/config"):
                with open(target, "a", encoding="utf-8") as f:
                    f.write("# x\n")
            else:
                with open(target, "w", encoding="utf-8") as f:
                    f.write("x")
            results.append(f"{target} WROTE")
        except OSError:
            results.append(f"{target} DENIED")
    write(f"{rec}/build.md", "\n".join(results) + "\n")
    git("add", "-A"); git("commit", "-q", "-m", "build")
    sys.exit(0)
sys.exit(2)
"""

STUB = '#!/bin/sh\nshift 2\nexec "$@"\n'


class Repo:
    """Isolated governed repository for M02 acceptance testing."""

    def __init__(self, milestones: dict[str, list[str]] | None = None) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="ai2ii-m02-acc-repo-")).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "human@example.invalid")
        self.git("config", "user.name", "human")
        shutil.copy2(REPO_ROOT / "orchestrator.py", self.root / "orchestrator.py")
        shutil.copy2(REPO_ROOT / "workflow.yaml", self.root / "workflow.yaml")
        shutil.copy2(REPO_ROOT / "AGENTS.md", self.root / "AGENTS.md")
        if (REPO_ROOT / "orch").exists():
            shutil.copy2(REPO_ROOT / "orch", self.root / "orch")
            (self.root / "orch").chmod(0o755)
        if (REPO_ROOT / "src").exists():
            shutil.copytree(REPO_ROOT / "src", self.root / "src")
        for m, deps in (milestones or {"M01": [], "M02": ["M01"], "M03": []}).items():
            d = self.root / "milestones" / m
            d.mkdir(parents=True)
            (d / "spec.yaml").write_text(SPEC.format(id=m, deps=deps))
        self.commit("init")

    def cleanup(self) -> None:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        shutil.rmtree(self.root, ignore_errors=True)

    def git(self, *args: str, cwd: Path | None = None) -> str:
        res = subprocess.run(
            ["git", *args],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"git {args}: {res.stderr}"
        return res.stdout.strip()

    def commit(self, msg: str, cwd: Path | None = None) -> str:
        self.git("add", "-A", cwd=cwd)
        self.git("commit", "-q", "-m", msg, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def state(self, m: str = "M01") -> dict[str, Any]:
        return yaml.safe_load((self.root / "milestones" / m / "state.yaml").read_text())

    def status(self, m: str = "M01") -> str:
        return self.state(m)["status"]

    def state_bytes(self, m: str = "M01") -> bytes:
        return (self.root / "milestones" / m / "state.yaml").read_bytes()

    def spec_hash(self, m: str = "M01") -> str:
        return hashlib.sha256(
            (self.root / "milestones" / m / "spec.yaml").read_bytes()
        ).hexdigest()

    def worktree(self, m: str, kind: str, n: int = 1) -> Path:
        return self.root / ".worktrees" / f"{m}-a{n:02d}-{kind}"

    def approve(self, m: str = "M01") -> None:
        h = self.spec_hash(m)[:12]
        (self.root / "reviews").mkdir(exist_ok=True)
        (self.root / "reviews" / f"{m}.md").write_text(
            f"Review of {m}\nspec {h}\n\nOutcome: APPROVED\n"
        )
        self.orch_ok("approve-gate", "G2", m)
        self.commit(f"review and G2 for {m}")
        self.orch_ok("review", m, f"reviews/{m}.md")
        self.orch_ok("approve", m, f"approvals/G2-{m}.md")
        self.orch_ok("refresh")

    def orch_ok(self, *args: str) -> str:
        env = {k: v for k, v in os.environ.items() if not k.startswith("AI2II_")}
        res = subprocess.run(
            [sys.executable, str(self.root / "orchestrator.py"), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert res.returncode == 0, (
            f"orch {args} -> {res.returncode}\n{res.stdout}\n{res.stderr}"
        )
        return res.stdout


class Env:
    """Governed test environment with fake agent harnesses and optional Seatbelt stub."""

    def __init__(
        self, milestones: dict[str, list[str]] | None = None, stub: bool = True
    ) -> None:
        self.repo = Repo(milestones or {"M01": [], "M02": ["M01"], "M03": []})
        self.tmp = Path(tempfile.mkdtemp(prefix="ai2ii-m02-acc-env-")).resolve()
        (self.tmp / "agent.py").write_text(AGENT_CODE, encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("AI2II_")}
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        if stub:
            bindir = self.tmp / "bin"
            bindir.mkdir()
            (bindir / "sandbox-exec").write_text(STUB, encoding="utf-8")
            (bindir / "sandbox-exec").chmod(0o755)
            self.env["PATH"] = f"{bindir}{os.pathsep}{self.env['PATH']}"

    def cleanup(self) -> None:
        self.repo.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def agents(
        self, role: str, *specs: tuple[str, str, str, str, dict[str, Any]]
    ) -> None:
        """specs: (name, family, mode, extra_arg, extra_config)."""
        agents, names = {}, []
        for name, family, mode, extra, cfg in specs:
            cmd = f"{sys.executable} {self.tmp}/agent.py {mode} {{prompt_file}} {extra}"
            agents[name] = {
                "family": family,
                "model": f"{name}-model",
                "command": cmd,
                **cfg,
            }
            names.append(name)
        path = self.repo.root / "agents.local.yaml"
        cur = (
            yaml.safe_load(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"agents": {}, "assign": {}}
        )
        cur.setdefault("agents", {}).update(agents)
        cur.setdefault("assign", {})[role] = names
        path.write_text(yaml.safe_dump(cur, sort_keys=False), encoding="utf-8")
        self.repo.commit(f"configure agents for {role}")

    def popen(self, *args: str) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, str(self.repo.root / "orchestrator.py"), *args],
            cwd=self.repo.root,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def orch(self, *args: str) -> tuple[int, str, str]:
        p = self.popen(*args)
        out, err = p.communicate()
        return p.returncode, out, err

    def ok(self, *args: str) -> str:
        rc, out, err = self.orch(*args)
        assert rc == 0, f"orch {args} -> {rc}\n{out}\n{err}"
        return out

    def attempt(self, m: str = "M01") -> dict[str, Any]:
        return self.repo.state(m)["attempts"][-1]

    def meta(self, role: str, m: str = "M01", n: int = 1) -> dict[str, Any]:
        f = (
            self.repo.root
            / "milestones"
            / m
            / "attempts"
            / f"{n:02d}"
            / f"{role}_metadata.yaml"
        )
        return yaml.safe_load(f.read_text(encoding="utf-8"))


def with_env(fn=None, *, stub: bool = True):
    def deco(target_fn):
        def wrapper() -> None:
            e = Env(stub=stub)
            try:
                target_fn(e)
            finally:
                e.cleanup()

        wrapper.__name__ = target_fn.__name__
        wrapper.__doc__ = target_fn.__doc__
        return wrapper

    return deco(fn) if fn else deco


# ==============================================================================
# AC1: Builder & verifier dispatch lifecycle integration
# ==============================================================================


@with_env
def test_ac1_builder_and_verifier_dispatch(e: Env) -> None:
    """AC1: Builder dispatch from READY/REWORK performs start-build; verifier from BUILT performs start-verify."""
    e.repo.approve("M01")
    e.agents("builder", ("b1", "fa", "build", "", {}))
    e.agents("verifier", ("v1", "fb", "verify", "BLOCKED", {}))

    # Builder dispatch from READY
    e.ok("dispatch", "M01", "builder")
    st = e.repo.state("M01")
    assert st["status"] == "BUILDING"
    assert st["attempt"] == 1
    a1 = st["attempts"][-1]
    assert a1["branch"] == "m/M01/a01-build"
    assert a1["worktree"] == ".worktrees/M01-a01-build"
    assert (e.repo.root / a1["worktree"]).is_dir()

    # finish-build uses this attempt worktree unchanged and succeeds
    e.ok("finish-build", "M01")
    assert e.repo.status("M01") == "BUILT"

    # Verifier dispatch from BUILT
    e.ok("dispatch", "M01", "verifier")
    st = e.repo.state("M01")
    assert st["status"] == "VERIFYING"
    assert st["attempt"] == 1
    a1_v = st["attempts"][-1]
    assert a1_v["verify_branch"] == "m/M01/a01-verify"
    assert a1_v["verify_worktree"] == ".worktrees/M01-a01-verify"
    assert (e.repo.root / a1_v["verify_worktree"]).is_dir()

    # finish-verify uses this unchanged and succeeds
    e.ok("finish-verify", "M01")
    assert e.repo.status("M01") == "BLOCKED"

    # Unblock and trigger REWORK via fail verdict on attempt 2
    e.ok("unblock", "M01", "--note", "unblocked")
    assert e.repo.status("M01") == "READY"
    e.ok("dispatch", "M01", "builder")
    e.ok("finish-build", "M01")
    assert e.repo.status("M01") == "BUILT"

    e.agents("verifier", ("v2", "fc", "verify", "FAIL", {}))
    e.ok("dispatch", "M01", "verifier")
    e.ok("finish-verify", "M01")
    assert e.repo.status("M01") == "REWORK"

    # Builder dispatch from REWORK starts attempt 3
    e.ok("dispatch", "M01", "builder")
    st = e.repo.state("M01")
    assert st["status"] == "BUILDING"
    assert st["attempt"] == 3
    a3 = st["attempts"][-1]
    assert a3["branch"] == "m/M01/a03-build"
    assert a3["worktree"] == ".worktrees/M01-a03-build"
    e.ok("finish-build", "M01")
    assert e.repo.status("M01") == "BUILT"


# ==============================================================================
# AC2: Main working tree isolation
# ==============================================================================


@with_env
def test_ac2_dispatch_leaves_main_clean(e: Env) -> None:
    """AC2: Dispatch writes nothing into main's working tree except orchestrator commits of state, metadata, runs."""
    e.repo.approve("M01")
    orch_before = (e.repo.root / "orchestrator.py").read_bytes()

    # Builder modifies orchestrator.py, writes src, tests, build.md
    e.agents("builder", ("b1", "fa", "build", "touch_orchestrator", {}))
    head_before = e.repo.git("rev-parse", "HEAD")
    e.ok("dispatch", "M01", "builder")

    # Main working tree is clean and orchestrator.py in main is byte-identical
    assert (e.repo.root / "orchestrator.py").read_bytes() == orch_before
    assert not (e.repo.root / "src" / "m01.py").exists()
    assert not (e.repo.root / "tests" / "test_ok.py").exists()
    assert not (
        e.repo.root / "milestones" / "M01" / "attempts" / "01" / "build.md"
    ).exists()
    assert e.repo.git("status", "--porcelain") == ""

    # Committed changes in main must only be from author orchestrator
    for line in e.repo.git(
        "log", "--format=%an:%s", f"{head_before}..HEAD"
    ).splitlines():
        assert line.startswith("orchestrator:")

    # Attempt branch holds the changes
    wt = e.repo.worktree("M01", "build", 1)
    assert (wt / "milestones" / "M01" / "attempts" / "01" / "build.md").exists()
    assert (
        (wt / "orchestrator.py")
        .read_text(encoding="utf-8")
        .startswith("# agent modified")
    )

    e.ok("finish-build", "M01")

    # Verifier dispatch touches acceptance/ and verification.yaml
    e.agents("verifier", ("v1", "fb", "verify", "BLOCKED touch_acceptance", {}))
    e.ok("dispatch", "M01", "verifier")

    assert not (e.repo.root / "acceptance" / "M01" / "rogue.py").exists()
    assert not (
        e.repo.root / "milestones" / "M01" / "attempts" / "01" / "verification.yaml"
    ).exists()
    assert e.repo.git("status", "--porcelain") == ""

    vwt = e.repo.worktree("M01", "verify", 1)
    assert (vwt / "acceptance" / "M01" / "rogue.py").exists()
    assert (
        vwt / "milestones" / "M01" / "attempts" / "01" / "verification.yaml"
    ).exists()


# ==============================================================================
# AC3: Uncommitted record is treated as no-record failure
# ==============================================================================


@with_env
def test_ac3_no_record_committed_fails_dispatch(e: Env) -> None:
    """AC3: Agent exit 0 without committed record causes non-zero exit and result 'no-record'."""
    e.repo.approve("M01")

    # Builder exits 0 without writing build.md
    e.agents("builder", ("b1", "fa", "silent", "", {}))
    rc, _, _ = e.orch("dispatch", "M01", "builder")
    assert rc != 0
    assert e.repo.status("M01") == "BUILDING"
    meta = e.meta("builder", "M01", 1)
    assert meta["result"] == "no-record"

    # Verifier exits 0 without writing verification.yaml on M03
    e.repo.approve("M03")
    e.agents("builder", ("b2", "fb", "build", "", {}))
    e.ok("dispatch", "M03", "builder")
    e.ok("finish-build", "M03")
    assert e.repo.status("M03") == "BUILT"

    e.agents("verifier", ("v1", "fc", "silent", "", {}))
    rc, _, _ = e.orch("dispatch", "M03", "verifier")
    assert rc != 0
    assert e.repo.status("M03") == "VERIFYING"
    vmeta = e.meta("verifier", "M03", 1)
    assert vmeta["result"] == "no-record"


# ==============================================================================
# AC4: Rendered prompt completeness and orchestrator command CLI parsing
# ==============================================================================


@with_env
def test_ac4_rendered_prompt_completeness_and_cli_parsing(e: Env) -> None:
    """AC4: Rendered prompt has no placeholders, has absolute worktree path, base sha, criteria_version, valid orch commands."""
    e.repo.approve("M01")
    bprompt_path = e.tmp / "builder_prompt.txt"
    vprompt_path = e.tmp / "verifier_prompt.txt"

    e.agents("builder", ("b1", "fa", "build", f"prompt={bprompt_path}", {}))
    e.agents("verifier", ("v1", "fb", "verify", f"prompt={vprompt_path}", {}))

    e.ok("dispatch", "M01", "builder")
    e.ok("finish-build", "M01")
    e.ok("dispatch", "M01", "verifier")

    spec = importlib.util.spec_from_file_location(
        "orch_mod", e.repo.root / "orchestrator.py"
    )
    assert spec is not None and spec.loader is not None
    orch_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(orch_mod)
    parser = orch_mod.build_parser()

    att = e.attempt("M01")
    root_str = str(e.repo.root)

    for role, path in (("builder", bprompt_path), ("verifier", vprompt_path)):
        text = path.read_text(encoding="utf-8")
        # No unresolved template placeholders
        assert not re.search(r"\{[A-Za-z_]\w*\}", text), (
            f"Unresolved placeholder in {role} prompt"
        )

        # Absolute worktree path
        kind = "build" if role == "builder" else "verify"
        expected_wt = str(e.repo.root / ".worktrees" / f"M01-a01-{kind}")
        assert expected_wt in text

        # Full base commit
        assert att["base"] in text
        assert len(att["base"]) == 40

        # Commands invoking main's orch by absolute path and parsing with orch parser
        for line in text.splitlines():
            line_str = line.strip()
            if f"{root_str}/orch " in line_str:
                cmd_part = line_str.split(f"{root_str}/orch", 1)[1]
                argv = [tok for tok in shlex.split(cmd_part) if not tok.startswith("#")]
                _, unknown = parser.parse_known_args(argv)
                assert unknown == [], f"Unknown argument in prompt command: {line_str}"

    vtext = vprompt_path.read_text(encoding="utf-8")
    assert f"commit {att['built']}" in vtext
    assert len(att["built"]) == 40
    assert e.repo.spec_hash("M01") in vtext


# ==============================================================================
# AC5: Process group termination and worktree reset on failure
# ==============================================================================


@with_env
def test_ac5_process_group_cleanup_and_worktree_reset(e: Env) -> None:
    """AC5: Candidate failure terminates process group, resets worktree to base; delayed writer killed."""
    e.repo.approve("M01")
    bg_file = e.tmp / "bg_writer.txt"

    # Candidate 1 commits marker, creates untracked file, leaves background writer, fails
    # Candidate 2 builds clean
    e.agents(
        "builder",
        ("b1", "fa", "marker_fail", str(bg_file), {}),
        ("b2", "fb", "build", "", {}),
    )
    e.ok("dispatch", "M01", "builder")

    wt = e.repo.worktree("M01", "build")
    # Worktree clean of marker.txt and untracked.txt
    assert not (wt / "marker.txt").exists()
    assert not (wt / "untracked.txt").exists()
    commit_log = e.repo.git("log", "--format=%s", cwd=wt).splitlines()
    assert "marker" not in commit_log

    # Background child must be killed
    size_before = bg_file.stat().st_size if bg_file.exists() else 0
    time.sleep(0.5)
    size_after = bg_file.stat().st_size if bg_file.exists() else 0
    assert size_before == size_after, (
        "Background writer continued writing after candidate exited"
    )

    e.ok("finish-build", "M01")

    # Successful candidate leaving delayed writer is also terminated
    late_file = e.tmp / "late_writer.txt"
    e.agents("verifier", ("v1", "fc", "late_writer", str(late_file), {}))
    # late_writer writes build.md and exits 0, but for verifier it will be no-record since no verification.yaml
    # Let's test late_writer on a builder attempt in M03
    e.repo.approve("M03")
    e.agents("builder", ("b_late", "fa", "late_writer", str(late_file), {}))
    e.ok("dispatch", "M03", "builder")
    time.sleep(1.5)

    wt3 = e.repo.worktree("M03", "build")
    assert not late_file.exists()
    assert not (wt3 / "late.txt").exists()
    assert e.repo.git("status", "--porcelain", cwd=wt3) == ""


# ==============================================================================
# AC6: Failure recording, empty candidates refusal, all candidates failed
# ==============================================================================


@with_env
def test_ac6_failure_modes_and_empty_candidates(e: Env) -> None:
    """AC6: Failed candidates recorded as failure|timeout|no-record; no candidates refuses before start; all fail stays in BUILDING at base."""
    e.repo.approve("M01")

    # 1. No candidate configured refuses before start-build, state unchanged
    state_before = e.repo.state_bytes("M01")
    rc, _, err = e.orch("dispatch", "M01", "builder")
    assert rc != 0
    assert "no agent configured" in err
    assert e.repo.state_bytes("M01") == state_before
    assert not e.repo.worktree("M01", "build").exists()

    # 2. Three candidates failing with timeout, failure, no-record
    e.agents(
        "builder",
        ("b_timeout", "fa", "hang", "", {"timeout_seconds": 1}),
        ("b_fail", "fb", "fail", "", {}),
        ("b_norecord", "fc", "silent", "", {}),
    )
    rc, _, _ = e.orch("dispatch", "M01", "builder")
    assert rc != 0

    st = e.repo.state("M01")
    assert st["status"] == "BUILDING"
    meta = e.meta("builder", "M01", 1)
    results = [c["result"] for c in meta["candidates"]]
    assert results == ["timeout", "failure", "no-record"]

    history_notes = " ".join(h["note"] for h in st["history"])
    assert "candidate b_timeout timeout" in history_notes
    assert "candidate b_fail failure" in history_notes
    assert "candidate b_norecord no-record" in history_notes

    wt = e.repo.worktree("M01", "build")
    assert e.repo.git("rev-parse", "HEAD", cwd=wt) == st["attempts"][-1]["base"]
    assert e.repo.git("status", "--porcelain", cwd=wt) == ""


# ==============================================================================
# AC7: Metadata records all candidates, retained candidate identity
# ==============================================================================


@with_env
def test_ac7_metadata_and_retained_candidate_identity(e: Env) -> None:
    """AC7: Metadata records all candidates tried; retained candidate identity is saved in state.yaml."""
    e.repo.approve("M01")

    e.agents(
        "builder",
        ("b_fail", "fa", "fail", "", {}),
        ("b_win", "fb", "build", "", {}),
    )
    e.ok("dispatch", "M01", "builder")

    meta = e.meta("builder", "M01", 1)
    assert len(meta["candidates"]) == 2
    assert meta["candidates"][0]["agent"] == "b_fail"
    assert meta["candidates"][0]["result"] == "failure"
    assert meta["candidates"][1]["agent"] == "b_win"
    assert meta["candidates"][1]["result"] == "success"

    # State records the retained candidate
    a = e.attempt("M01")
    assert a["builder"]["agent"] == "b_win"
    assert a["builder"]["family"] == "fb"

    # Finish build succeeds
    e.ok("finish-build", "M01")
    assert e.repo.status("M01") == "BUILT"

    # Verifier: first candidate fails, second of different family succeeds
    e.agents(
        "verifier",
        ("v_fail", "fb", "fail", "", {}),
        ("v_win", "fc", "verify", "BLOCKED", {}),
    )
    e.ok("dispatch", "M01", "verifier")

    vmeta = e.meta("verifier", "M01", 1)
    assert len(vmeta["candidates"]) == 2
    assert vmeta["candidates"][0]["agent"] == "v_fail"
    assert vmeta["candidates"][1]["agent"] == "v_win"

    a_v = e.attempt("M01")
    assert a_v["verifier"]["agent"] == "v_win"
    assert a_v["verifier"]["family"] == "fc"

    # Finish verify checks family diversity against builder fb -> succeeds
    e.ok("finish-verify", "M01")
    assert e.repo.status("M01") == "BLOCKED"


# ==============================================================================
# AC8: Seatbelt confinement of agent process
# ==============================================================================


def test_ac8_seatbelt_profile_and_confinement() -> None:
    """AC8: Seatbelt profile allows only worktree/tmp/git/statedirs; execution strictly denies unauthorized paths."""
    spec = importlib.util.spec_from_file_location(
        "orch_mod", REPO_ROOT / "orchestrator.py"
    )
    assert spec is not None and spec.loader is not None
    orch_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(orch_mod)

    # 1. Profile structure unit checks
    tmp_root = Path(tempfile.mkdtemp(prefix="ai2ii-m02-sb-")).resolve()
    try:
        wt = tmp_root / "wt"
        admin = tmp_root / "git_admin"
        common = tmp_root / "common_git"
        att_tmp = tmp_root / "att_tmp"
        for d in (wt, admin, common, att_tmp):
            d.mkdir(parents=True)

        profile = orch_mod._build_seatbelt_profile(
            wt, admin, common, att_tmp, ["/home/user/.state", "/home/user/.state.json*"]
        )

        assert profile.index("(deny file-write*)") < profile.index("(allow file-write*")
        allow_part = profile.split("(allow file-write*", 1)[1].split(
            "(deny file-read*"
        )[0]

        for p in (
            wt,
            admin,
            common / "objects",
            common / "refs",
            common / "logs",
            att_tmp,
        ):
            assert f'(subpath "{p}")' in allow_part
        assert '(subpath "/home/user/.state")' in allow_part
        assert r'(regex #"^/home/user/\.state\.json[^/]*$")' in allow_part

        for forbidden in ("/tmp", "/private/tmp", "hooks", "config", str(tmp_root)):
            assert f'"{forbidden}"' not in allow_part
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    # 2. Live execution confinement under real Seatbelt (stub=False)
    # Dispatches a fake builder agent (shell script).
    # MUST FAIL if Seatbelt cannot be applied (nested sandboxes) rather than silently skipping.
    env = Env(stub=False)
    outside = Path("/private/tmp") / f"ai2ii-outside-test-{os.getpid()}.txt"
    try:
        env.repo.approve("M01")
        state_dir = env.tmp / "agent_state"
        state_dir.mkdir()

        main_root = str(env.repo.root)
        outside_path = str(outside)
        state_path = str(state_dir)
        wt_path = str(env.repo.worktree("M01", "build"))

        # Fake builder agent implemented as a shell script
        agent_sh = env.tmp / "agent_builder.sh"
        agent_sh.write_text(
            f"""#!/usr/bin/env bash
set -u
REC="milestones/M01/attempts/01"
mkdir -p "$REC"
OUT=""

for target in "{main_root}/MAIN.txt" "{main_root}/.git/hooks/pre-commit" "{main_root}/.git/config" "{outside_path}" "{state_path}/ok.txt" "{wt_path}/inside.txt"; do
    if [ "$target" = "{main_root}/.git/config" ]; then
        if printf "# probe\\n" >> "$target" 2>/dev/null; then
            OUT="${{OUT}}${{target}} WROTE"$'\n'
        else
            OUT="${{OUT}}${{target}} DENIED"$'\n'
        fi
    else
        if printf "probe\\n" > "$target" 2>/dev/null; then
            OUT="${{OUT}}${{target}} WROTE"$'\n'
        else
            OUT="${{OUT}}${{target}} DENIED"$'\n'
        fi
    fi
done

printf "Status: COMPLETE\\n%s" "$OUT" > "$REC/build.md"
mkdir -p tests
printf "def test_ok():\\n    assert True\\n" > tests/test_ok.py
git add -A
git commit -q -m "builder report"
exit 0
""",
            encoding="utf-8",
        )
        agent_sh.chmod(0o755)

        # Register shell script builder agent with declared state_dirs
        agents_path = env.repo.root / "agents.local.yaml"
        cfg = {
            "agents": {
                "sh_builder": {
                    "family": "test_fam",
                    "model": "sh_model",
                    "command": f"bash {agent_sh} {{prompt_file}}",
                    "state_dirs": [state_path],
                }
            },
            "assign": {"builder": ["sh_builder"]},
        }
        agents_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
        env.repo.commit("configure sh_builder agent")

        hooks_before = sorted(
            p.name for p in (env.repo.root / ".git" / "hooks").iterdir()
        )
        config_before = (env.repo.root / ".git" / "config").read_bytes()

        rc, out, err = env.orch("dispatch", "M01", "builder")
        assert rc == 0, (
            f"Seatbelt execution failed (nested sandbox or confinement failure): {out}\n{err}"
        )

        wt_build = env.repo.worktree("M01", "build")
        build_md = (
            wt_build / "milestones" / "M01" / "attempts" / "01" / "build.md"
        ).read_text(encoding="utf-8")
        results = dict(
            line.rsplit(" ", 1) for line in build_md.splitlines() if " " in line
        )

        assert results[f"{main_root}/MAIN.txt"] == "DENIED"
        assert results[f"{main_root}/.git/hooks/pre-commit"] == "DENIED"
        assert results[f"{main_root}/.git/config"] == "DENIED"
        assert results[outside_path] == "DENIED"
        assert results[f"{state_path}/ok.txt"] == "WROTE"
        assert results[f"{wt_path}/inside.txt"] == "WROTE"

        assert not outside.exists()
        assert not (env.repo.root / "MAIN.txt").exists()
        assert (
            sorted(p.name for p in (env.repo.root / ".git" / "hooks").iterdir())
            == hooks_before
        )
        assert (env.repo.root / ".git" / "config").read_bytes() == config_before
        assert env.repo.git("status", "--porcelain") == ""
    finally:
        outside.unlink(missing_ok=True)
        env.cleanup()


# ==============================================================================
# AC9: Concurrent builder dispatches for different milestones
# ==============================================================================


@with_env
def test_ac9_concurrent_builder_dispatches(e: Env) -> None:
    """AC9: Two concurrent builder dispatches use separate worktrees and leave both state.yaml files valid."""
    e.repo.approve("M01")
    e.repo.approve("M03")
    e.agents("builder", ("b1", "fa", "build", "", {}))

    p1 = e.popen("dispatch", "M01", "builder")
    p3 = e.popen("dispatch", "M03", "builder")

    out1, err1 = p1.communicate()
    out3, err3 = p3.communicate()

    assert p1.returncode == 0, f"M01 dispatch failed: {out1}\n{err1}"
    assert p3.returncode == 0, f"M03 dispatch failed: {out3}\n{err3}"

    for m in ("M01", "M03"):
        assert e.repo.status(m) == "BUILDING"
        assert e.repo.worktree(m, "build").is_dir()
        assert e.meta("builder", m)["result"] == "success"

    assert e.repo.worktree("M01", "build") != e.repo.worktree("M03", "build")
    assert e.repo.git("status", "--porcelain") == ""

    e.ok("finish-build", "M01")
    e.ok("finish-build", "M03")
    assert e.repo.status("M01") == "BUILT"
    assert e.repo.status("M03") == "BUILT"


# ==============================================================================
# AC10: Milestone status precondition refusals
# ==============================================================================


@with_env
def test_ac10_dispatch_status_preconditions(e: Env) -> None:
    """AC10: Dispatch refuses when milestone status does not allow the role."""
    e.agents("builder", ("b1", "fa", "build", "", {}))
    e.agents("verifier", ("v1", "fb", "verify", "BLOCKED", {}))

    # 1. In DRAFT: neither builder nor verifier
    for role in ("builder", "verifier"):
        rc, _, _ = e.orch("dispatch", "M01", role)
        assert rc != 0
        assert not e.repo.worktree("M01", "build").exists()
        assert not e.repo.worktree("M01", "verify").exists()

    # 2. In READY: verifier refused, builder allowed
    e.repo.approve("M01")
    before_ready = e.repo.state_bytes("M01")
    rc, _, err = e.orch("dispatch", "M01", "verifier")
    assert rc != 0
    assert "BUILT" in err
    assert e.repo.state_bytes("M01") == before_ready
    assert not e.repo.worktree("M01", "verify").exists()

    # Dispatch builder -> BUILDING
    e.ok("dispatch", "M01", "builder")

    # 3. In BUILDING: both builder and verifier refused
    before_building = e.repo.state_bytes("M01")
    for role in ("builder", "verifier"):
        rc, _, _ = e.orch("dispatch", "M01", role)
        assert rc != 0
        assert e.repo.state_bytes("M01") == before_building

    # Finish build -> BUILT
    e.ok("finish-build", "M01")

    # 4. In BUILT: builder refused, verifier allowed
    before_built = e.repo.state_bytes("M01")
    rc, _, _ = e.orch("dispatch", "M01", "builder")
    assert rc != 0
    assert e.repo.state_bytes("M01") == before_built

    # Dispatch verifier -> VERIFYING
    e.ok("dispatch", "M01", "verifier")

    # 5. In VERIFYING: both builder and verifier refused
    before_verifying = e.repo.state_bytes("M01")
    for role in ("builder", "verifier"):
        rc, _, _ = e.orch("dispatch", "M01", role)
        assert rc != 0
        assert e.repo.state_bytes("M01") == before_verifying
