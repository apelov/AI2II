"""Acceptance tests for M01: Orchestrator minimum.

Approved criteria: AC1 to AC11 in milestones/M01/spec.yaml.
Hermetic: executes against isolated temporary repositories under tempfile.
Compatible with both real pytest and src/_shims/pytest.py (no fixtures).
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

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


class Repo:
    def __init__(self, milestones: dict[str, list[str]] | None = None) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="ai2ii-m01-acc-")).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "human@example.invalid")
        self.git("config", "user.name", "human")
        shutil.copy2(REPO_ROOT / "orchestrator.py", self.root / "orchestrator.py")
        shutil.copy2(REPO_ROOT / "workflow.yaml", self.root / "workflow.yaml")
        shutil.copy2(REPO_ROOT / "AGENTS.md", self.root / "AGENTS.md")
        if (REPO_ROOT / "src").exists():
            shutil.copytree(REPO_ROOT / "src", self.root / "src")
        for m, deps in (milestones or {"M01": []}).items():
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

    def orch(self, *args: str) -> tuple[int, str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("AI2II_")}
        res = subprocess.run(
            [sys.executable, str(self.root / "orchestrator.py"), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        return res.returncode, res.stdout, res.stderr

    def ok(self, *args: str) -> str:
        rc, out, err = self.orch(*args)
        assert rc == 0, f"orch {args} -> {rc}\n{out}\n{err}"
        return out

    def state(self, m: str = "M01") -> dict:
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
        self.ok("approve-gate", "G2", m)
        self.commit(f"review and G2 for {m}")
        self.ok("review", m, f"reviews/{m}.md")
        self.ok("approve", m, f"approvals/G2-{m}.md")
        self.ok("refresh")

    def start_build(self, m: str = "M01", session: str = "b1") -> Path:
        self.ok(
            "start-build", m, "--agent", "a", "--family", "f1", "--session", session
        )
        return self.worktree(m, "build", self.state(m)["attempt"])

    def good_build(self, wt: Path, m: str = "M01", n: int = 1) -> None:
        (wt / "src").mkdir(exist_ok=True)
        (wt / "src" / "m01.py").write_text(SRC_OK)
        (wt / "tests").mkdir(exist_ok=True)
        (wt / "tests" / "test_m01.py").write_text(BUILDER_TEST)
        att = wt / "milestones" / m / "attempts" / f"{n:02d}"
        att.mkdir(parents=True, exist_ok=True)
        (att / "build.md").write_text("Status: COMPLETE\n")
        self.commit("build", cwd=wt)

    def built(self, m: str = "M01") -> None:
        wt = self.start_build(m)
        self.good_build(wt, m, self.state(m)["attempt"])
        self.ok("finish-build", m)

    def start_verify(self, m: str = "M01", session: str = "v1") -> Path:
        self.ok(
            "start-verify", m, "--agent", "v", "--family", "f2", "--session", session
        )
        return self.worktree(m, "verify", self.state(m)["attempt"])

    def verifier_tests(self, vwt: Path, m: str = "M01") -> None:
        acc = vwt / "acceptance" / m
        acc.mkdir(parents=True, exist_ok=True)
        (acc / "test_m01.py").write_text(ACC_TEST)
        (acc / "mutants").mkdir(exist_ok=True)
        (vwt / "src" / "m01.py").write_text(SRC_OK.replace("x * 2", "x * 3"))
        patch = self.git("diff", "--", "src/m01.py", cwd=vwt)
        self.git("checkout", "--", "src/m01.py", cwd=vwt)
        (acc / "mutants" / "triple.patch").write_text(patch + "\n")
        self.commit("acceptance", cwd=vwt)

    def verification_doc(self, m: str = "M01", verdict: str = "PASS") -> dict:
        st = self.state(m)
        a = st["attempts"][-1]
        run = f"runs/{m}/{a['n']:02d}/{a['built'][:12]}"
        node = f"acceptance/{m}/test_m01.py::"
        return {
            "milestone": m,
            "attempt": a["n"],
            "commit": a["built"],
            "criteria_version": st["criteria_version"],
            "verifier": {"role": "verifier", "family": "f2", "model": "x"},
            "verdict": verdict,
            "acceptance": {
                "AC1": {
                    "result": "PASS",
                    "tests": [node + "test_double_two"],
                    "run": f"{run}/acc.log",
                },
                "AC2": {
                    "result": "PASS",
                    "tests": [node + "test_double_three"],
                    "run": f"{run}/acc.log",
                },
            },
            "validity": {
                "AC1": {"fails_on": "base", "run": f"{run}/validity-AC1.log"},
                "AC2": {"fails_on": "mutant:triple", "run": f"{run}/validity-AC2.log"},
            },
            "findings": [],
            "claim_audit": [],
            "required_fixes": [],
        }

    def write_verification(self, vwt: Path, doc: dict, m: str = "M01") -> None:
        d = vwt / "milestones" / m / "attempts" / f"{doc['attempt']:02d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "verification.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
        self.commit("verification", cwd=vwt)

    def verifying(self, m: str = "M01") -> Path:
        self.built(m)
        vwt = self.start_verify(m)
        self.verifier_tests(vwt, m)
        self.ok("run-tests", m, "--name", "acc")
        node = f"acceptance/{m}/test_m01.py::"
        rc, _, _ = self.orch(
            "run-tests",
            m,
            "--name",
            "validity-AC1",
            "--at",
            "base",
            "--paths",
            node + "test_double_two",
        )
        assert rc == 1
        rc, _, _ = self.orch(
            "run-tests",
            m,
            "--name",
            "validity-AC2",
            "--at",
            "mutant:triple",
            "--paths",
            node + "test_double_three",
        )
        assert rc == 1
        return vwt


def with_repo(fn):
    def wrapper() -> None:
        r = Repo({"M01": [], "M02": ["M01"], "M03": []})
        try:
            fn(r)
        finally:
            r.cleanup()

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def authors(r: Repo, m: str) -> set[str]:
    return set(
        r.git("log", "--format=%an", "--", f"milestones/{m}/state.yaml").splitlines()
    )


# --- AC1 ---


@with_repo
def test_ac1_builder_ownership_rejection(repo: Repo) -> None:
    """AC1: finish-build rejects builder commits touching protected paths; milestone stays BUILDING."""
    repo.approve("M01")
    for bad_path in (
        "acceptance/M01/test_x.py",
        "milestones/M01/spec.yaml",
        "milestones/M01/state.yaml",
        "workflow.yaml",
        "orch",
    ):
        r = Repo()
        try:
            r.approve("M01")
            wt = r.start_build("M01")
            r.good_build(wt, "M01", 1)
            target = wt / bad_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("unauthorized modification\n")
            r.commit("unauthorized edit", cwd=wt)

            rc, _, err = r.orch("finish-build", "M01")
            assert rc == 1, f"finish-build should reject modification to {bad_path}"
            assert bad_path in err
            assert r.status("M01") == "BUILDING"
        finally:
            r.cleanup()


# --- AC2 ---


@with_repo
def test_ac2_finish_build_preconditions_and_success(repo: Repo) -> None:
    """AC2: finish-build requires clean tree, build.md committed, and passing builder tests."""
    repo.approve("M01")
    wt = repo.start_build("M01")

    # Missing build.md
    (wt / "src").mkdir(exist_ok=True)
    (wt / "src" / "m01.py").write_text(SRC_OK)
    (wt / "tests").mkdir(exist_ok=True)
    (wt / "tests" / "test_m01.py").write_text(BUILDER_TEST)
    repo.commit("no build.md", cwd=wt)
    rc, _, err = repo.orch("finish-build", "M01")
    assert rc == 1 and "build.md" in err
    assert repo.status("M01") == "BUILDING"

    # Dirty worktree
    att = wt / "milestones" / "M01" / "attempts" / "01"
    att.mkdir(parents=True, exist_ok=True)
    (att / "build.md").write_text("Status: COMPLETE\n")
    repo.commit("add build.md", cwd=wt)
    (wt / "untracked.txt").write_text("dirty")
    rc, _, err = repo.orch("finish-build", "M01")
    assert rc == 1 and "clean" in err
    assert repo.status("M01") == "BUILDING"
    (wt / "untracked.txt").unlink()

    # Failing builder tests
    (wt / "src" / "m01.py").write_text("def double(x):\n    return x + 999\n")
    repo.commit("broken test", cwd=wt)
    rc, _, _ = repo.orch("finish-build", "M01")
    assert rc == 1
    assert repo.status("M01") == "BUILDING"

    # Clean + build.md + passing tests -> BUILT
    (wt / "src" / "m01.py").write_text(SRC_OK)
    repo.commit("fixed test", cwd=wt)
    repo.ok("finish-build", "M01")
    assert repo.status("M01") == "BUILT"
    assert repo.state("M01")["attempts"][0]["built"] == repo.git(
        "rev-parse", "HEAD", cwd=wt
    )


# --- AC3 ---


@with_repo
def test_ac3_captured_test_logs(repo: Repo) -> None:
    """AC3: Every test execution logs command, commit, and exit status under runs/Mxx/NN/<sha>/."""
    repo.approve("M01")
    repo.built("M01")
    st = repo.state("M01")
    built_sha = st["attempts"][0]["built"]
    build_log = repo.root / "runs" / "M01" / "01" / built_sha[:12] / "build.log"
    assert build_log.exists(), f"Log missing: {build_log}"
    content = build_log.read_text(encoding="utf-8")
    assert "# command: " in content
    assert f"# commit: {built_sha}" in content
    assert "# exit: 0" in content

    # Test run-tests logging with non-zero exit
    vwt = repo.start_verify("M01")
    repo.verifier_tests(vwt, "M01")
    rc, _, _ = repo.orch(
        "run-tests",
        "M01",
        "--name",
        "val-check",
        "--at",
        "mutant:triple",
        "--paths",
        "acceptance/M01/test_m01.py::test_double_three",
    )
    assert rc == 1
    val_log = repo.root / "runs" / "M01" / "01" / built_sha[:12] / "val-check.log"
    assert val_log.exists()
    val_content = val_log.read_text(encoding="utf-8")
    assert "# command: " in val_content
    assert "# exit: 1" in val_content


# --- AC4 ---


@with_repo
def test_ac4_preconditions_enforced_and_state_unchanged(repo: Repo) -> None:
    """AC4: Commands whose preconditions do not hold exit non-zero and leave state.yaml unchanged."""
    repo.approve("M01")
    repo.approve("M02")  # depends on M01, M01 is only READY
    before_m01 = repo.state_bytes("M01")
    before_m02 = repo.state_bytes("M02")

    # finish-verify on READY milestone
    assert repo.orch("finish-verify", "M01")[0] == 1
    # start-build while dependency is not COMPLETE
    assert (
        repo.orch(
            "start-build", "M02", "--agent", "a", "--family", "f", "--session", "s2"
        )[0]
        == 1
    )
    # finish-build on READY milestone
    assert repo.orch("finish-build", "M01")[0] == 1
    # integrate on READY milestone
    assert repo.orch("integrate", "M01")[0] == 1
    assert repo.state_bytes("M01") == before_m01
    assert repo.state_bytes("M02") == before_m02

    # approve with approval naming wrong spec hash
    bad_h = "000000000000"
    (repo.root / "approvals" / "bad.md").write_text(
        f"G2 M01 {bad_h}\nDecision: APPROVED\n"
    )
    repo.commit("bad approval")
    before_m01 = repo.state_bytes("M01")
    assert repo.orch("approve", "M01", "approvals/bad.md")[0] == 1
    assert repo.state_bytes("M01") == before_m01

    # start-verify with builder session id
    repo.built("M01")
    before_built = repo.state_bytes("M01")
    rc, _, err = repo.orch(
        "start-verify", "M01", "--agent", "v", "--family", "f", "--session", "b1"
    )
    assert rc == 1 and "session" in err
    assert repo.state_bytes("M01") == before_built


# --- AC5 ---


@with_repo
def test_ac5_finish_verify_rejects_malformed_verdicts(repo: Repo) -> None:
    """AC5: finish-verify rejects verification.yaml with missing criteria, bad hashes, missing runs."""
    repo.approve("M01")
    vwt = repo.verifying("M01")
    before = repo.state_bytes("M01")

    bad_mutations = [
        (lambda d: d["acceptance"].pop("AC2"), "AC2"),
        (lambda d: d.update(commit="deadbeefdeadbeef"), "commit"),
        (lambda d: d.update(criteria_version="0" * 64), "criteria_version"),
        (
            lambda d: d["acceptance"]["AC1"].update(run="runs/M01/01/nope/acc.log"),
            "AC1",
        ),
        (lambda d: d["validity"].pop("AC1"), "validity"),
        (lambda d: d["validity"]["AC2"].update(run="runs/M01/01/nope/val.log"), "AC2"),
        (lambda d: d.update(verdict="INVALID_VERDICT_NAME"), "verdict"),
    ]

    for mutate, needle in bad_mutations:
        doc = repo.verification_doc("M01")
        mutate(doc)
        repo.write_verification(vwt, doc, "M01")
        rc, _, err = repo.orch("finish-verify", "M01")
        assert rc == 1 and needle in err, f"Expected {needle} in error, got {err}"
        assert repo.state_bytes("M01") == before
        assert repo.status("M01") == "VERIFYING"


# --- AC6 ---


@with_repo
def test_ac6_pass_verdict_requires_validity_and_acceptance(repo: Repo) -> None:
    """AC6: PASS yields VERIFIED only if orchestrator acceptance run passes and validity fails."""
    # 1. Clean PASS scenario
    repo.approve("M01")
    vwt = repo.verifying("M01")
    repo.write_verification(vwt, repo.verification_doc("M01"), "M01")
    repo.ok("finish-verify", "M01")
    assert repo.status("M01") == "VERIFIED"

    # 2. Acceptance suite failure stays VERIFYING
    r_fail = Repo()
    try:
        r_fail.approve("M01")
        v_fail = r_fail.verifying("M01")
        (v_fail / "acceptance" / "M01" / "test_m01.py").write_text(
            ACC_TEST + "\n\ndef test_broken():\n    assert False\n"
        )
        r_fail.commit("failing test added", cwd=v_fail)
        r_fail.write_verification(v_fail, r_fail.verification_doc("M01"), "M01")
        rc, _, err = r_fail.orch("finish-verify", "M01")
        assert rc == 1 and "final-acc.log" in err
        assert r_fail.status("M01") == "VERIFYING"
    finally:
        r_fail.cleanup()

    # 3. Validity check does not fail stays VERIFYING
    r_val = Repo()
    try:
        r_val.approve("M01")
        v_val = r_val.verifying("M01")
        (v_val / "acceptance" / "M01" / "mutants" / "noop.patch").write_text("")
        r_val.commit("noop mutant", cwd=v_val)
        doc = r_val.verification_doc("M01")
        doc["validity"]["AC2"]["fails_on"] = "mutant:noop"
        r_val.write_verification(v_val, doc, "M01")
        rc, _, err = r_val.orch("finish-verify", "M01")
        assert rc == 1 and "AC2" in err
        assert r_val.status("M01") == "VERIFYING"
    finally:
        r_val.cleanup()

    # 4. Verifier tampering with source tree is rejected
    r_tamper = Repo()
    try:
        r_tamper.approve("M01")
        v_tamper = r_tamper.verifying("M01")
        (v_tamper / "src" / "m01.py").write_text("def double(x):\n    return 4\n")
        r_tamper.commit("tamper with src", cwd=v_tamper)
        r_tamper.write_verification(v_tamper, r_tamper.verification_doc("M01"), "M01")
        rc, _, err = r_tamper.orch("finish-verify", "M01")
        assert rc == 1 and "src/m01.py" in err
        assert r_tamper.status("M01") == "VERIFYING"
    finally:
        r_tamper.cleanup()


# --- AC7 ---


@with_repo
def test_ac7_fail_verdict_rework_escalation_g4(repo: Repo) -> None:
    """AC7: FAIL yields REWORK below max_attempts; ESCALATED with E001 at max_attempts; requires G4."""
    repo.approve("M01")

    def fail_doc(r: Repo) -> dict:
        doc = r.verification_doc("M01", verdict="FAIL")
        doc["acceptance"] = {"AC1": {"result": "FAIL"}, "AC2": {"result": "FAIL"}}
        doc["validity"] = {}
        return doc

    vwt = repo.verifying("M01")
    repo.write_verification(vwt, fail_doc(repo), "M01")
    repo.ok("finish-verify", "M01")
    assert repo.status("M01") == "REWORK"

    # attempts 2 and 3
    for n in (2, 3):
        wt = repo.start_build("M01", session=f"b{n}")
        assert repo.state("M01")["attempt"] == n
        att = wt / "milestones" / "M01" / "attempts" / f"{n:02d}"
        att.mkdir(parents=True, exist_ok=True)
        (att / "build.md").write_text("Status: COMPLETE\n")
        repo.commit(f"build {n}", cwd=wt)
        repo.ok("finish-build", "M01")
        v = repo.start_verify("M01", session=f"v{n}")
        repo.write_verification(v, fail_doc(repo), "M01")
        repo.ok("finish-verify", "M01")

    assert repo.status("M01") == "ESCALATED"
    esc = repo.state("M01")["escalations"][0]
    assert esc["id"] == "E001" and esc["gate"] == "G4"
    assert (repo.root / "escalations" / "E001.md").exists()

    # Resolution refused without committed G4 approval
    args = [
        "resolve",
        "M01",
        "--outcome",
        "REWORK",
        "--classification",
        "IMPLEMENTATION",
        "--note",
        "approved retry",
    ]
    assert repo.orch(*args)[0] == 1
    (repo.root / "approvals").mkdir(exist_ok=True)
    (repo.root / "approvals" / "G4-E001.md").write_text("G4 E001\nDecision: APPROVED\n")
    assert repo.orch(*args, "--approval", "approvals/G4-E001.md")[0] == 1
    repo.commit("G4 approved")
    repo.ok(*args, "--approval", "approvals/G4-E001.md")
    assert repo.status("M01") == "REWORK"


# --- AC8 ---


@with_repo
def test_ac8_spec_change_returns_draft_and_cascades_stale(repo: Repo) -> None:
    """AC8: Changing approved spec returns milestone to DRAFT; invalidation cascades STALE."""
    repo.approve("M01")
    vwt = repo.verifying("M01")
    repo.write_verification(vwt, repo.verification_doc("M01"), "M01")
    repo.ok("finish-verify", "M01")
    repo.ok("integrate", "M01")
    assert repo.status("M01") == "COMPLETE"

    # M02 complete dependent
    repo.approve("M02")
    st2 = repo.state("M02")
    st2["status"] = "COMPLETE"
    (repo.root / "milestones" / "M02" / "state.yaml").write_text(yaml.safe_dump(st2))
    repo.commit("M02 complete")

    # Invalidate M01 -> STALE cascades to M02 -> STALE
    repo.ok("invalidate", "M01", "--to", "STALE", "--reason", "upstream flaw")
    assert repo.status("M01") == "STALE"
    assert repo.status("M02") == "STALE"

    # Spec edit on approved milestone M03 returns it to DRAFT
    repo.approve("M03")
    spec3 = repo.root / "milestones" / "M03" / "spec.yaml"
    spec3.write_text(spec3.read_text() + "# spec update\n")
    repo.commit("edit M03 spec")
    repo.ok("refresh")
    assert repo.status("M03") == "DRAFT"
    assert repo.state("M03")["criteria_version"] is None


# --- AC9 ---


@with_repo
def test_ac9_integration_lifecycle_and_conflict_reversal(repo: Repo) -> None:
    """AC9: integrate merges VERIFIED milestone into main; failure restores main to pre-merge commit."""
    repo.approve("M01")
    repo.built("M01")
    vwt = repo.start_verify("M01")
    acc = vwt / "acceptance" / "M01"
    acc.mkdir(parents=True, exist_ok=True)
    (acc / "test_m01.py").write_text(
        ACC_TEST.replace(
            "def test_double_two():\n",
            "def test_double_two():\n"
            "    assert not (Path(__file__).resolve().parents[2] / 'FAIL_INTEGRATE').exists()\n",
        )
    )
    (acc / "mutants").mkdir(exist_ok=True)
    (vwt / "src" / "m01.py").write_text(SRC_OK.replace("x * 2", "x * 3"))
    patch = repo.git("diff", "--", "src/m01.py", cwd=vwt)
    repo.git("checkout", "--", "src/m01.py", cwd=vwt)
    (acc / "mutants" / "triple.patch").write_text(patch + "\n")
    repo.commit("acceptance", cwd=vwt)

    repo.ok("run-tests", "M01", "--name", "acc")
    node = "acceptance/M01/test_m01.py::"
    rc, _, _ = repo.orch(
        "run-tests",
        "M01",
        "--name",
        "validity-AC1",
        "--at",
        "base",
        "--paths",
        node + "test_double_two",
    )
    assert rc == 1
    rc, _, _ = repo.orch(
        "run-tests",
        "M01",
        "--name",
        "validity-AC2",
        "--at",
        "mutant:triple",
        "--paths",
        node + "test_double_three",
    )
    assert rc == 1

    repo.write_verification(vwt, repo.verification_doc("M01"), "M01")
    repo.ok("finish-verify", "M01")
    assert repo.status("M01") == "VERIFIED"

    # Pre-integration commit on main: adds trigger that causes post-merge acceptance suite to fail
    (repo.root / "FAIL_INTEGRATE").write_text("trigger post-merge failure\n")
    pre = repo.commit("main commit with FAIL_INTEGRATE")

    rc, _, err = repo.orch("integrate", "M01")
    assert rc == 1 and "restored" in err
    assert repo.status("M01") == "REWORK"
    assert repo.git("status", "--porcelain") == ""
    head = repo.git("rev-parse", "HEAD")
    # Main must be restored to pre-merge commit; merged files must not remain
    assert repo.git("rev-parse", f"{head}~1") == pre
    assert not (repo.root / "src" / "m01.py").exists()


# --- AC10 ---


@with_repo
def test_ac10_state_persists_across_processes_and_author_orchestrator(
    repo: Repo,
) -> None:
    """AC10: State survives process exit; reproduced by status --json; state commits authored 'orchestrator'."""
    repo.approve("M01")
    repo.verifying("M01")
    rows = json.loads(repo.ok("status", "--json"))
    m01_row = next(r for r in rows if r["id"] == "M01")
    assert m01_row["status"] == "VERIFYING"
    assert authors(repo, "M01") == {"orchestrator"}
    assert repo.git("status", "--porcelain") == ""


# --- AC11 ---


@with_repo
def test_ac11_concurrent_finish_build_preserves_state(repo: Repo) -> None:
    """AC11: Concurrent finish-build across worktrees serialises without state or index corruption."""
    d = repo.root / "milestones" / "M04"
    d.mkdir(parents=True)
    (d / "spec.yaml").write_text(SPEC.format(id="M04", deps=[]))
    repo.commit("add M04")

    for m in ("M01", "M03", "M04"):
        repo.approve(m)
    wts = {m: repo.start_build(m, session=f"b_{m}") for m in ("M01", "M03", "M04")}
    for m, wt in wts.items():
        repo.good_build(wt, m, 1)

    procs = [
        subprocess.Popen(
            [sys.executable, str(repo.root / "orchestrator.py"), "finish-build", m],
            cwd=repo.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for m in ("M01", "M03", "M04")
    ]
    results = [p.communicate() for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0], results

    for m in ("M01", "M03", "M04"):
        assert repo.status(m) == "BUILT"
        assert authors(repo, m) == {"orchestrator"}
    assert repo.git("status", "--porcelain") == ""

    rows = {r["id"]: r["status"] for r in json.loads(repo.ok("status", "--json"))}
    for m in ("M01", "M03", "M04"):
        assert rows[m] == "BUILT"
