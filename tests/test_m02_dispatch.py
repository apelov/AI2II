"""M02 dispatch tests. Each runs the orchestrator as a subprocess in a temporary repository
with fake agent commands (never a real agent CLI). A stub `sandbox-exec` that drops the profile
stands in for Seatbelt, so the flow tests also run where Seatbelt cannot be nested; the
confinement test uses the real thing and skips when it cannot be applied."""

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

import yaml

_spec = importlib.util.spec_from_file_location(
    "flow_repo", Path(__file__).resolve().parent / "flow_repo.py"
)
_flow = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("flow_repo", _flow)
_spec.loader.exec_module(_flow)
Repo, REAL_ROOT = _flow.Repo, _flow.REAL_ROOT

AGENT = r"""
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
    os.makedirs(os.path.dirname(os.path.join(wt, rel)) or ".", exist_ok=True)
    open(os.path.join(wt, rel), "w").write(text)

if extra and extra[0].startswith("prompt="):
    open(extra[0][7:], "w").write(open(prompt_file).read())
    extra = extra[1:]

if mode == "fail":
    sys.exit(3)
if mode == "hang":
    import time; time.sleep(60)
if mode == "silent":
    sys.exit(0)
if mode == "marker_fail":
    write("marker.txt", "x")
    git("add", "-A"); git("commit", "-q", "-m", "marker")
    write("untracked.txt", "x")
    bg(extra[0])
    sys.exit(1)
if mode == "late_writer":                        # succeeds, leaves a writer behind
    write("tests/test_ok.py", "def test_ok():\n    assert True\n")
    write(f"{rec}/build.md", "Status: COMPLETE\n")
    git("add", "-A"); git("commit", "-q", "-m", "build")
    subprocess.Popen(["sh", "-c", f"sleep 1; echo late > {wt}/late.txt; echo late > {extra[0]}"])
    sys.exit(0)
if mode == "build":
    if os.path.exists("marker.txt") or os.path.exists("untracked.txt"):
        sys.exit(5)
    write("src/m01.py", "def double(x):\n    return x * 2\n")
    write("tests/test_ok.py", "def test_ok():\n    assert True\n")
    write(f"{rec}/build.md", "Status: COMPLETE\n")
    git("add", "-A"); git("commit", "-q", "-m", "build")
    sys.exit(0)
if mode == "verify":
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    cv = [l.split(": ", 1)[1] for l in open(prompt_file) if l.startswith("Criteria version: ")][0].strip()
    import yaml
    doc = {
        "milestone": m, "attempt": n, "commit": head, "criteria_version": cv,
        "verifier": {"role": "verifier", "family": "f", "model": "x"}, "verdict": "BLOCKED",
        "acceptance": {"AC1": {"result": "BLOCKED"}, "AC2": {"result": "BLOCKED"}},
        "validity": {}, "findings": [], "claim_audit": [], "required_fixes": [],
    }
    write(f"{rec}/verification.yaml", yaml.safe_dump(doc))
    git("add", "-A"); git("commit", "-q", "-m", "verification")
    sys.exit(0)
if mode == "confined":                           # extra: main, outside, state_dir
    main, outside, state_dir = extra
    results = []
    for target in (main + "/MAIN.txt", main + "/.git/hooks/pre-commit", main + "/.git/config",
                   outside, state_dir + "/ok.txt", wt + "/inside.txt"):
        try:
            if target.endswith("/.git/config"):
                open(target, "a").write("# x\n")
            else:
                open(target, "w").write("x")
            results.append(f"{target} WROTE")
        except OSError:
            results.append(f"{target} DENIED")
    write(f"{rec}/build.md", "\n".join(results) + "\n")
    git("add", "-A"); git("commit", "-q", "-m", "build")
    sys.exit(0)
sys.exit(2)
"""

STUB = '#!/bin/sh\nshift 2\nexec "$@"\n'


def seatbelt_works() -> bool:
    if not shutil.which("sandbox-exec"):
        return False
    res = subprocess.run(
        ["sandbox-exec", "-p", "(version 1)(allow default)", "true"],
        capture_output=True,
        check=False,
    )
    return res.returncode == 0


def load_orchestrator():
    spec = importlib.util.spec_from_file_location(
        "orch_under_test", REAL_ROOT / "orchestrator.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Env:
    """A governed repository plus fake agents."""

    def __init__(self, milestones=None, stub=True) -> None:
        self.repo = Repo(milestones or {"M01": [], "M02": ["M01"], "M03": []})
        self.tmp = Path(tempfile.mkdtemp(prefix="ai2ii-agents-")).resolve()
        (self.tmp / "agent.py").write_text(AGENT)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("AI2II_")}
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        if stub:
            bindir = self.tmp / "bin"
            bindir.mkdir()
            (bindir / "sandbox-exec").write_text(STUB)
            (bindir / "sandbox-exec").chmod(0o755)
            self.env["PATH"] = f"{bindir}{os.pathsep}{self.env['PATH']}"

    def cleanup(self) -> None:
        self.repo.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def agents(self, role: str, *specs) -> None:
        """specs: (name, family, mode, extra args, extra config)."""
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
            yaml.safe_load(path.read_text())
            if path.exists()
            else {"agents": {}, "assign": {}}
        )
        cur["agents"].update(agents)
        cur["assign"][role] = names
        path.write_text(yaml.safe_dump(cur))
        self.repo.commit(f"agents for {role}")

    def popen(self, *args):
        return subprocess.Popen(
            [sys.executable, str(self.repo.root / "orchestrator.py"), *args],
            cwd=self.repo.root,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def orch(self, *args):
        p = self.popen(*args)
        out, err = p.communicate()
        return p.returncode, out, err

    def ok(self, *args) -> str:
        rc, out, err = self.orch(*args)
        assert rc == 0, f"orch {args} -> {rc}\n{out}\n{err}"
        return out

    def attempt(self, m="M01") -> dict:
        return self.repo.state(m)["attempts"][-1]

    def meta(self, role, m="M01", n=1) -> dict:
        f = (
            self.repo.root
            / "milestones"
            / m
            / "attempts"
            / f"{n:02d}"
            / f"{role}_metadata.yaml"
        )
        return yaml.safe_load(f.read_text())

    def tracked_main_files(self) -> dict[str, bytes]:
        out = {}
        for rel in self.repo.git("ls-files").splitlines():
            out[rel] = (self.repo.root / rel).read_bytes()
        return out


def with_env(fn=None, *, stub=True):
    def deco(fn):
        def wrapper() -> None:
            e = Env(stub=stub)
            try:
                fn(e)
            finally:
                e.cleanup()

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return deco(fn) if fn else deco


def ready(e: Env, m="M01") -> None:
    e.repo.approve(m)


# --- AC1, AC2, AC4, AC7: builder and verifier dispatch ---


@with_env
def test_builder_then_verifier_dispatch_reuse_m01_lifecycle(e: Env) -> None:
    ready(e)
    e.agents("builder", ("b1", "fa", "build", f"prompt={e.tmp}/bprompt.txt", {}))
    e.agents("verifier", ("v1", "fb", "verify", f"prompt={e.tmp}/vprompt.txt", {}))
    before = e.tracked_main_files()
    e.ok("dispatch", "M01", "builder")
    st = e.repo.state()
    a = st["attempts"][-1]
    assert st["status"] == "BUILDING"
    assert (
        a["branch"] == "m/M01/a01-build" and a["worktree"] == ".worktrees/M01-a01-build"
    )
    assert a["builder"]["agent"] == "b1" and a["builder"]["family"] == "fa"
    # dispatch copied nothing into main
    assert e.repo.git("status", "--porcelain") == ""
    after = e.tracked_main_files()
    for rel, data in before.items():
        if rel != "milestones/M01/state.yaml":
            assert after[rel] == data, rel
    assert not (e.repo.root / "src" / "m01.py").exists()
    assert not (e.repo.root / "milestones/M01/attempts/01/build.md").exists()
    e.ok("finish-build", "M01")
    assert e.repo.status() == "BUILT"
    assert not e.repo.state()["history"][-1]["note"].startswith("builder candidate")

    e.ok("dispatch", "M01", "verifier")
    a = e.attempt()
    assert e.repo.status() == "VERIFYING"
    assert a["verify_branch"] == "m/M01/a01-verify"
    assert (
        a["verifier"]["family"] == "fb"
        and a["verifier"]["session"] != a["builder"]["session"]
    )
    assert not (e.repo.root / "milestones/M01/attempts/01/verification.yaml").exists()
    e.ok("finish-verify", "M01")
    assert e.repo.status() == "BLOCKED"
    # only the orchestrator committed to main after setup
    paths = set(
        e.repo.git("log", "--format=", "--name-only", "--author=orchestrator").split()
    )
    assert not any(
        p.startswith(("src/", "acceptance/")) or p == "orchestrator.py" for p in paths
    )


@with_env
def test_rendered_prompts_are_complete_and_parse(e: Env) -> None:
    ready(e)
    e.agents("builder", ("b1", "fa", "build", f"prompt={e.tmp}/bprompt.txt", {}))
    e.agents("verifier", ("v1", "fb", "verify", f"prompt={e.tmp}/vprompt.txt", {}))
    e.ok("dispatch", "M01", "builder")
    e.ok("finish-build", "M01")
    e.ok("dispatch", "M01", "verifier")
    orch = load_orchestrator()
    parser = orch.build_parser()
    a = e.attempt()
    root = e.repo.root
    for role, text in (("b", (e.tmp / "bprompt.txt").read_text()),
                       ("v", (e.tmp / "vprompt.txt").read_text())):  # fmt: skip
        assert not re.search(r"\{[A-Za-z_]\w*\}", text), role
        assert role == "b" or e.repo.spec_hash() in text
        assert (
            str(root / ".worktrees" / f"M01-a01-{'build' if role == 'b' else 'verify'}")
            in text
        )
        assert a["base"] in text
        for ln in text.splitlines():
            if f"{root}/orch " in ln:
                argv = [
                    x
                    for x in shlex.split(ln.split(f"{root}/orch", 1)[1])
                    if not x.startswith("#")
                ]
                _, unknown = parser.parse_known_args(argv)
                assert unknown == [], ln
    v = (e.tmp / "vprompt.txt").read_text()
    assert f"commit {a['built']}" in v  # the built commit
    assert f"pre-implementation commit {a['base']}" in v
    assert a["built"] != a["base"]
    assert f"{root}/orch run-tests M01" in v


# --- AC3, AC6, AC10: failures and refusals ---


@with_env
def test_exit_zero_without_record_is_no_record(e: Env) -> None:
    ready(e)
    e.agents("builder", ("b1", "fa", "silent", "", {}))
    rc, _, _ = e.orch("dispatch", "M01", "builder")
    assert rc != 0
    assert e.meta("builder")["result"] == "no-record"
    assert e.repo.status() == "BUILDING"


@with_env
def test_silent_verifier_is_no_record(e: Env) -> None:
    ready(e)
    e.repo.built("M01")
    e.agents("verifier", ("v1", "fb", "silent", "", {}))
    rc, _, _ = e.orch("dispatch", "M01", "verifier")
    assert rc != 0
    assert e.meta("verifier")["result"] == "no-record"
    assert e.repo.status() == "VERIFYING"


@with_env
def test_all_candidates_fail_leaves_building_at_base(e: Env) -> None:
    ready(e)
    e.agents(
        "builder",
        ("b1", "fa", "hang", "", {"timeout_seconds": 1}),
        ("b2", "fb", "fail", "", {}),
        ("b3", "fc", "silent", "", {}),
    )
    rc, _, _ = e.orch("dispatch", "M01", "builder")
    assert rc != 0
    st = e.repo.state()
    assert st["status"] == "BUILDING"
    meta = e.meta("builder")
    assert [c["result"] for c in meta["candidates"]] == [
        "timeout",
        "failure",
        "no-record",
    ]
    notes = " ".join(h["note"] for h in st["history"])
    for name, result in (("b1", "timeout"), ("b2", "failure"), ("b3", "no-record")):
        assert f"candidate {name} {result}" in notes
    wt = e.repo.worktree("M01", "build")
    assert e.repo.git("rev-parse", "HEAD", cwd=wt) == st["attempts"][-1]["base"]
    assert e.repo.git("status", "--porcelain", "--ignored", cwd=wt) == ""


@with_env
def test_no_candidate_leaves_state_unchanged(e: Env) -> None:
    ready(e)
    before = e.repo.state_bytes()
    rc, _, err = e.orch("dispatch", "M01", "builder")
    assert rc != 0 and "no agent configured" in err
    assert e.repo.state_bytes() == before
    assert not e.repo.worktree("M01", "build").exists()


@with_env
def test_role_status_mismatch_is_refused(e: Env) -> None:
    e.agents("builder", ("b1", "fa", "build", "", {}))
    e.agents("verifier", ("v1", "fb", "verify", "", {}))
    # DRAFT milestone: neither role
    for role in ("builder", "verifier"):
        rc, _, _ = e.orch("dispatch", "M01", role)
        assert rc != 0
    ready(e)
    before = e.repo.state_bytes()
    rc, _, err = e.orch("dispatch", "M01", "verifier")  # READY: verifier needs BUILT
    assert rc != 0 and "BUILT" in err
    assert e.repo.state_bytes() == before
    assert not e.repo.worktree("M01", "verify").exists()
    e.repo.built("M01")
    before = e.repo.state_bytes()
    rc, _, err = e.orch(
        "dispatch", "M01", "builder"
    )  # BUILT: builder needs READY/REWORK
    assert rc != 0
    assert e.repo.state_bytes() == before
    assert not e.repo.worktree("M01", "build", 2).exists()


# --- AC5, AC7: fallback, reset, process groups ---


@with_env
def test_fallback_resets_worktree_kills_group_and_records_winner(e: Env) -> None:
    ready(e)
    bgfile = e.tmp / "bg.txt"
    e.agents(
        "builder",
        ("b1", "fa", "marker_fail", str(bgfile), {}),
        ("b2", "fb", "build", "", {}),
    )
    e.ok("dispatch", "M01", "builder")
    assert [c["result"] for c in e.meta("builder")["candidates"]] == [
        "failure",
        "success",
    ]
    a = e.attempt()
    assert a["builder"]["agent"] == "b2" and a["builder"]["family"] == "fb"
    wt = e.repo.worktree("M01", "build")
    assert not (wt / "marker.txt").exists() and not (wt / "untracked.txt").exists()
    log = e.repo.git("log", "--format=%s", cwd=wt).splitlines()
    assert "marker" not in log
    size = bgfile.stat().st_size if bgfile.exists() else 0
    time.sleep(0.6)
    assert (
        bgfile.stat().st_size if bgfile.exists() else 0
    ) == size  # nothing writes any more
    e.ok("finish-build", "M01")
    assert e.repo.status() == "BUILT"
    # the failed candidate is in history and metadata only
    assert "candidate b1 failure" in " ".join(
        h["note"] for h in e.repo.state()["history"]
    )
    assert e.attempt()["builder"]["agent"] == "b2"


@with_env
def test_verifier_fallback_identity_is_retained_candidate(e: Env) -> None:
    ready(e)
    e.repo.built("M01")  # builder family f1, session b1
    e.agents("verifier", ("v1", "f1", "fail", "", {}), ("v2", "f2", "verify", "", {}))
    e.ok("dispatch", "M01", "verifier")
    v = e.attempt()["verifier"]
    assert v["agent"] == "v2" and v["family"] == "f2" and v["model"] == "v2-model"
    notes = [h["note"] for h in e.repo.state()["history"]]
    assert any("v1 failure" in n for n in notes)
    assert not any("same family as builder" in n for n in notes[-2:])
    e.ok("finish-verify", "M01")
    # a same-family fallback is called out
    assert [c["agent"] for c in e.meta("verifier")["candidates"]] == ["v1", "v2"]


@with_env
def test_successful_candidate_leaves_no_writer_and_clean_worktree(e: Env) -> None:
    ready(e)
    late = e.tmp / "late.txt"
    e.agents("builder", ("b1", "fa", "late_writer", str(late), {}))
    e.ok("dispatch", "M01", "builder")
    time.sleep(1.5)
    wt = e.repo.worktree("M01", "build")
    assert not late.exists() and not (wt / "late.txt").exists()
    assert e.repo.git("status", "--porcelain", cwd=wt) == ""
    e.ok("finish-build", "M01")


# --- AC9: concurrency ---


@with_env
def test_concurrent_dispatch_for_different_milestones(e: Env) -> None:
    ready(e, "M01")
    ready(e, "M03")
    e.agents("builder", ("b1", "fa", "build", "", {}))
    p1, p3 = (
        e.popen("dispatch", "M01", "builder"),
        e.popen("dispatch", "M03", "builder"),
    )
    for p in (p1, p3):
        out, err = p.communicate()
        assert p.returncode == 0, out + err
    for m in ("M01", "M03"):
        assert e.repo.status(m) == "BUILDING"
        assert e.repo.worktree(m, "build").is_dir()
        assert e.meta("builder", m)["result"] == "success"
    assert e.repo.worktree("M01", "build") != e.repo.worktree("M03", "build")
    assert e.repo.git("status", "--porcelain") == ""
    e.ok("finish-build", "M01")
    e.ok("finish-build", "M03")


# --- AC8: Seatbelt ---


def test_seatbelt_profile_allows_only_the_declared_write_set() -> None:
    orch = load_orchestrator()
    root = Path(tempfile.mkdtemp(prefix="ai2ii-prof-")).resolve()
    try:
        wt, common, tmp = root / "wt", root / "main" / ".git", root / "tmp"
        admin = common / "worktrees" / "wt"
        for d in (wt, admin, tmp):
            d.mkdir(parents=True)
        profile = orch._build_seatbelt_profile(
            wt, admin, common, tmp, ["/home/u/.claude", "/home/u/.claude.json*"]
        )
        assert profile.index("(deny file-write*)") < profile.index("(allow file-write*")
        allowed = profile.split("(allow file-write*", 1)[1].split("(deny file-read*")[0]
        for p in (wt, admin, common / "objects", common / "refs", common / "logs", tmp):
            assert f'(subpath "{p}")' in allowed
        assert '(subpath "/home/u/.claude")' in allowed
        assert r'(regex #"^/home/u/\.claude\.json[^/]*$")' in allowed
        for bad in ("/tmp", "/private/tmp", "hooks", "config", str(root / "main")):
            assert f'"{bad}"' not in allowed
        assert f'(subpath "{common}")' not in allowed
    finally:
        shutil.rmtree(root, ignore_errors=True)


@with_env(stub=False)
def test_agent_is_confined_by_seatbelt(e: Env) -> None:
    if not seatbelt_works():
        print("SKIP: Seatbelt cannot be applied here")
        return
    ready(e)
    outside = Path("/private/tmp") / f"ai2ii-outside-{os.getpid()}.txt"
    state_dir = e.tmp / "state"
    state_dir.mkdir()
    extra = f"{e.repo.root} {outside} {state_dir}"
    e.agents(
        "builder", ("b1", "fa", "confined", extra, {"state_dirs": [str(state_dir)]})
    )
    try:
        before_hooks = sorted(
            p.name for p in (e.repo.root / ".git" / "hooks").iterdir()
        )
        config = (e.repo.root / ".git" / "config").read_bytes()
        e.ok("dispatch", "M01", "builder")
        report = e.repo.git(
            "show", "m/M01/a01-build:milestones/M01/attempts/01/build.md"
        )
        lines = dict(ln.rsplit(" ", 1) for ln in report.splitlines())
        assert lines[f"{e.repo.root}/MAIN.txt"] == "DENIED"
        assert lines[f"{e.repo.root}/.git/hooks/pre-commit"] == "DENIED"
        assert lines[f"{e.repo.root}/.git/config"] == "DENIED"
        assert lines[str(outside)] == "DENIED"
        assert lines[f"{state_dir}/ok.txt"] == "WROTE"
        assert lines[f"{e.repo.worktree('M01', 'build')}/inside.txt"] == "WROTE"
        assert not outside.exists() and not (e.repo.root / "MAIN.txt").exists()
        assert (
            sorted(p.name for p in (e.repo.root / ".git" / "hooks").iterdir())
            == before_hooks
        )
        assert (e.repo.root / ".git" / "config").read_bytes() == config
    finally:
        outside.unlink(missing_ok=True)
