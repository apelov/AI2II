"""Temporary governed repository for M01 tests.

Every test builds its own repository under the system temp dir, copies the orchestrator under
test into it and drives it as a subprocess. Nothing touches the real repository or any
user-level state.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REAL_ROOT = Path(__file__).resolve().parent.parent

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
        self.root = Path(tempfile.mkdtemp(prefix="ai2ii-flow-")).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "human@example.invalid")
        self.git("config", "user.name", "human")
        shutil.copy2(REAL_ROOT / "orchestrator.py", self.root / "orchestrator.py")
        shutil.copy2(REAL_ROOT / "workflow.yaml", self.root / "workflow.yaml")
        shutil.copy2(REAL_ROOT / "AGENTS.md", self.root / "AGENTS.md")
        shutil.copytree(REAL_ROOT / "src", self.root / "src")
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

    # --- plumbing
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

    # --- lifecycle helpers
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
        """Reach VERIFYING with committed acceptance tests and the orchestrator run logs."""
        self.built(m)
        vwt = self.start_verify(m)
        self.verifier_tests(vwt, m)
        self.ok("run-tests", m, "--name", "acc")
        node = f"acceptance/{m}/test_m01.py::"
        rc, _, _ = self.orch(
            "run-tests", m, "--name", "validity-AC1", "--at", "base",
            "--paths", node + "test_double_two",
        )  # fmt: skip
        assert rc == 1
        rc, _, _ = self.orch(
            "run-tests", m, "--name", "validity-AC2", "--at", "mutant:triple",
            "--paths", node + "test_double_three",
        )  # fmt: skip
        assert rc == 1
        return vwt


def with_repo(fn):
    """Run ``fn(repo)`` in a fresh temporary repository (works without pytest fixtures)."""

    def wrapper() -> None:
        r = Repo({"M01": [], "M02": ["M01"], "M03": []})
        try:
            fn(r)
        finally:
            r.cleanup()

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper
