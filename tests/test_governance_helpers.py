"""Hermetic unit tests: ownership matching, wrapper (E011) and rendered prompts."""

import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import orchestrator as orch

REAL_ROOT = Path(__file__).resolve().parent.parent


def test_ownership_allows_source_and_blocks_protected_paths() -> None:
    assert orch.check_ownership("builder", "M01", 1, ["orchestrator.py", "src/x.py"])[0]
    for path in (
        "orch",
        "workflow.yaml",
        "DESIGN.md",
        "AGENTS.md",
        "conftest.py",
        "pytest.ini",
        "pyproject.toml",
        "scripts/verify_gate.sh",
        "acceptance/M01/test_x.py",
        "milestones/M01/spec.yaml",
        "milestones/M01/state.yaml",
        "runs/M01/01/x/build.log",
        "src/../../acceptance/M01/x.py",
        "/etc/passwd",
    ):
        ok, bad = orch.check_ownership("builder", "M01", 1, [path])
        assert not ok and bad == [path], path


def test_leading_dots_are_not_stripped_from_protected_paths() -> None:
    for path in (".git/hooks/pre-commit", ".worktrees/x", "./.git/config"):
        assert not orch.check_ownership("builder", "M01", 1, [path])[0], path
    assert orch.check_ownership("builder", "M01", 1, [".gitignore", "./src/a.py"])[0]
    assert orch.check_ownership(
        "builder", "M01", 2, ["milestones/M01/attempts/02/build.md"]
    )[0]
    assert not orch.check_ownership(
        "builder", "M01", 2, ["milestones/M01/attempts/01/build.md"]
    )[0]


def test_verifier_owns_only_its_acceptance_and_verdict() -> None:
    ok = ["acceptance/M01/test_a.py", "milestones/M01/attempts/01/verification.yaml"]
    assert orch.check_ownership("verifier", "M01", 1, ok)[0]
    for path in ("src/x.py", "acceptance/M02/test_a.py", "orchestrator.py"):
        assert not orch.check_ownership("verifier", "M01", 1, [path])[0], path


def test_orch_wrapper_runs_mains_orchestrator_from_a_worktree() -> None:
    repo = Path(tempfile.mkdtemp(prefix="ai2ii-e011-")).resolve()
    wt = repo.parent / (repo.name + "-wt")

    def git(cwd: Path, *a: str) -> None:
        subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True)

    try:
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "t@example.invalid")
        git(repo, "config", "user.name", "t")
        shutil.copy2(REAL_ROOT / "orch", repo / "orch")
        shutil.copy2(REAL_ROOT / "orchestrator.py", repo / "orchestrator.py")
        shutil.copytree(REAL_ROOT / "src", repo / "src")
        (repo / "milestones").mkdir()
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "init")
        git(repo, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
        subject = wt / "orchestrator.py"
        subject.write_text(
            'print("SUBJECT_COPY_EXECUTED")\n' + subject.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        res = subprocess.run(
            [str(wt / "orch"), "--help"],
            cwd=wt,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, res.stderr
        assert "SUBJECT_COPY_EXECUTED" not in res.stdout
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt)],
            cwd=repo,
            capture_output=True,
            check=False,
        )
        shutil.rmtree(wt, ignore_errors=True)
        shutil.rmtree(repo, ignore_errors=True)


def test_rendered_verifier_prompt_commands_parse() -> None:
    prompt, _ = orch.render_role_prompt("verifier", "M01", 1, "0" * 40)
    main_orch = str(orch.REPO_ROOT / "orch")
    parser = orch.build_parser()
    commands = [
        ln.split(main_orch, 1)[1] for ln in prompt.splitlines() if main_orch in ln
    ]
    assert commands
    for cmd in commands:
        argv = [a for a in shlex.split(cmd) if not a.startswith("#")]
        _, unknown = parser.parse_known_args(argv)
        assert unknown == [], f"invalid CLI in rendered prompt: {cmd!r}"


def test_copy_back_is_attempt_record_for_builder_and_never_code_for_verifier() -> None:
    changed = [
        "orchestrator.py",
        "src/x.py",
        "tests/test_x.py",
        "acceptance/M01/test_a.py",
        "milestones/M01/attempts/02/build.md",
        "milestones/M01/attempts/02/verification.yaml",
    ]
    assert orch.copy_back_paths("builder", "M01", 2, changed) == [
        "milestones/M01/attempts/02/build.md"
    ]
    assert orch.copy_back_paths("verifier", "M01", 2, changed) == [
        "acceptance/M01/test_a.py",
        "milestones/M01/attempts/02/verification.yaml",
    ]


def test_only_files_under_mains_runs_are_citable() -> None:
    root = Path(tempfile.mkdtemp(prefix="ai2ii-runs-")).resolve()
    saved = (orch.MILESTONES_DIR, orch.RUNS_DIR)
    try:
        (root / "milestones").mkdir()
        (root / "runs" / "M01").mkdir(parents=True)
        (root / "runs" / "M01" / "acc.log").write_text("# exit: 0\n")
        (root / "elsewhere.log").write_text("# exit: 0\n")
        orch.MILESTONES_DIR, orch.RUNS_DIR = root / "milestones", root / "runs"
        assert orch._is_run_log("M01", "runs/M01/acc.log")
        assert not orch._is_run_log("M01", "elsewhere.log")
        assert not orch._is_run_log("M01", "runs/M01/../../elsewhere.log")
        assert not orch._is_run_log("M01", str(root / "runs" / "M01" / "acc.log"))
        assert not orch._is_run_log("M01", "runs/M01/missing.log")
        assert not orch._is_run_log("M02", "runs/M01/acc.log")
    finally:
        orch.MILESTONES_DIR, orch.RUNS_DIR = saved
        shutil.rmtree(root, ignore_errors=True)
