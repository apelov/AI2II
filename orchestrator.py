#!/usr/bin/env python3
"""
Orchestrator CLI for AI2II multi-agent engineering workflow.
Implements deterministic orchestration with hardened primitives ported from agentwork:
- fcntl-locked atomic state persistence and external tamper-evident state journal
- Topological DAG validation, sealing (harness-manifest.json), and Goldfish static spec audit
- 1-hop AST symbol context extraction
- Worktree-aware macOS Seatbelt / Linux Bubblewrap sandbox confinement
- Process-group timeout cleanup
- AST test-weakening inspection
- Sound glob-to-regex ownership checking with symlink and traversal rejection
- Fail-closed verification.yaml validation, isolated negative-control test validity, and transactional merge
"""

import argparse
import ast
import contextlib
import fcntl
import functools
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.resolve()
if str(REPO_ROOT / "src" / "_shims") not in sys.path:
    sys.path.append(str(REPO_ROOT / "src" / "_shims"))

import yaml

# Ignore SIGPIPE so closing pipes never crashes the controller mid-transaction
if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
WORKFLOW_YAML = REPO_ROOT / "workflow.yaml"
AGENTS_MD = REPO_ROOT / "AGENTS.md"
DESIGN_MD = REPO_ROOT / "DESIGN.md"
MILESTONES_DIR = REPO_ROOT / "milestones"
ACCEPTANCE_DIR = REPO_ROOT / "acceptance"
RUNS_DIR = REPO_ROOT / "runs"
METRICS_DIR = REPO_ROOT / "metrics"
REVIEWS_DIR = REPO_ROOT / "reviews"
ESCALATIONS_DIR = REPO_ROOT / "escalations"
APPROVALS_DIR = REPO_ROOT / "approvals"
SCRIPTS_DIR = REPO_ROOT / "scripts"
WORKTREES_DIR = REPO_ROOT / ".worktrees"
MODELS_FILE = REPO_ROOT / "models.yaml"
IMPROVEMENTS_DIR = REPO_ROOT / "improvements"
MANIFEST_FILE = METRICS_DIR / "harness-manifest.json"

# State machine from DESIGN.md 24.7
STATES = [
    "DRAFT",
    "REVIEWED",
    "APPROVED",
    "READY",
    "BUILDING",
    "BUILT",
    "VERIFYING",
    "VERIFIED",
    "REWORK",
    "BLOCKED",
    "ESCALATED",
    "COMPLETE",
    "STALE",
]

TRANSITIONS = {
    ("DRAFT", "REVIEWED"): "milestone spec reviewed by independent reviewer",
    (
        "REVIEWED",
        "APPROVED",
    ): "human G2 gate approval recorded; criteria_version locked",
    ("APPROVED", "READY"): "all depends_on milestones are COMPLETE",
    ("READY", "BUILDING"): "builder dispatched; attempt counter incremented",
    ("REWORK", "BUILDING"): "builder dispatched; attempt counter incremented",
    (
        "BUILDING",
        "BUILT",
    ): "build.md present; path-ownership check passed; builder tests pass in orchestrator run",
    ("BUILT", "VERIFYING"): "verifier dispatched in a fresh session",
    (
        "VERIFYING",
        "VERIFIED",
    ): "verdict PASS; test-validity check passed; orchestrator run of acceptance passes at verified commit",
    ("VERIFYING", "REWORK"): "verdict FAIL and attempts < max_attempts",
    ("VERIFYING", "BLOCKED"): "verdict BLOCKED (verification could not run)",
    ("VERIFYING", "ESCALATED"): "verdict INVALID or attempts == max_attempts",
    (
        "VERIFIED",
        "COMPLETE",
    ): "merged to main; acceptance suites of this AND all COMPLETE milestones pass on merge commit",
    ("VERIFIED", "REWORK"): "integration run fails",
    ("COMPLETE", "STALE"): "invalidated (24.13)",
    ("VERIFIED", "STALE"): "invalidated (24.13)",
    ("STALE", "VERIFYING"): "re-verification dispatched",
    ("BLOCKED", "READY"): "blocker resolved (human or architect records resolution)",
    ("ESCALATED", "REWORK"): "escalation resolved (24.12)",
    ("ESCALATED", "DRAFT"): "escalation resolved (spec change)",
    ("ESCALATED", "BLOCKED"): "escalation resolved (external dependency)",
}

VALID_TRANSITIONS = dict(TRANSITIONS)

# Built-in protected paths that neither builder nor verifier may modify
# orchestrator.py is deliberately absent: it is subject code a builder may change in its
# worktree; main's copy alone governs (DESIGN.md 24.3, E011). The orch wrapper is protected.
PROTECTED_PATTERNS = [
    "orch",
    "scripts/**",
    "DESIGN.md",
    "BASELINE.md",
    "AGENTS.md",
    "workflow.yaml",
    ".git/**",
    ".worktrees/**",
    "pytest.ini",
    "conftest.py",
    "pyproject.toml",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _repo_root() -> Path:
    """Return active repository root derived from MILESTONES_DIR parent."""
    return MILESTONES_DIR.parent.resolve()


def _kill_group(pgid: int) -> None:
    """SIGKILL a process group and wait (bounded) until no member is left."""
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            return
        time.sleep(0.02)


def run_process_with_group_timeout(
    cmd: list[str],
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str] | None = None,
    stdout_handle: Any | None = None,
) -> tuple[int, str, str]:
    """Run subprocess in its own process group; the whole group is killed when it ends
    (normally, on timeout or on interrupt), so no descendant outlives the call."""
    if stdout_handle is not None:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=stdout_handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            rc = proc.wait(timeout=timeout_sec)
            return rc, "", ""
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                time.sleep(0.2)
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.wait()
            raise
        except KeyboardInterrupt:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
            raise
        finally:
            _kill_group(proc.pid)
    else:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout_sec)
            return proc.returncode, out or "", err or ""
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                time.sleep(0.2)
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.communicate()
            raise
        except KeyboardInterrupt:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
            raise
        finally:
            _kill_group(proc.pid)


# === GLOB & AST HELPERS PORTED FROM AGENTWORK ===


def glob_to_regex(pat: str) -> re.Pattern:
    """Convert path glob to regex where * does not cross / and ** crosses / (from verify_gate.sh)."""
    pat = _strip_dot_slash(pat.strip())
    if pat == "**":
        return re.compile(r"^.*$")
    if pat.endswith("/**"):
        base = re.escape(pat[:-3].rstrip("/"))
        return re.compile(rf"^{base}(/.*)?$")
    i, n = 0, len(pat)
    res = ["^"]
    while i < n:
        c = pat[i]
        if c == "*":
            if i + 1 < n and pat[i + 1] == "*":
                if i + 2 < n and pat[i + 2] == "/":
                    res.append("(.*/)?")
                    i += 3
                    continue
                res.append(".*")
                i += 2
                continue
            else:
                res.append("[^/]*")
        elif c == "?":
            res.append("[^/]")
        else:
            res.append(re.escape(c))
        i += 1
    res.append("$")
    return re.compile("".join(res))


def _segment_matches(s1: str, s2: str) -> bool:
    """Check whether two single-directory glob segments can match a common filename."""
    r1 = re.compile(
        "^"
        + "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in s1)
        + "$"
    )
    r2 = re.compile(
        "^"
        + "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in s2)
        + "$"
    )
    if s1 == s2 or s1 == "*" or s2 == "*":
        return True
    p1_lit = re.split(r"[\*\?]", s1)[0]
    p2_lit = re.split(r"[\*\?]", s2)[0]
    if (
        p1_lit
        and p2_lit
        and not (p1_lit.startswith(p2_lit) or p2_lit.startswith(p1_lit))
    ):
        return False
    suf1 = re.split(r"[\*\?]", s1)[-1]
    suf2 = re.split(r"[\*\?]", s2)[-1]
    if suf1 and suf2 and not (suf1.endswith(suf2) or suf2.endswith(suf1)):
        return False
    prefix = p1_lit if len(p1_lit) >= len(p2_lit) else p2_lit
    suffix = suf1 if len(suf1) >= len(suf2) else suf2
    for mid in ("", "x", "test_x", "_"):
        sample = f"{prefix}{mid}{suffix}"
        if r1.match(sample) and r2.match(sample):
            return True
    return False


def globs_overlap(pat1: str, pat2: str) -> bool:
    """Sound segment-wise glob intersection check handling ** and * (ported from pipeline.py)."""
    segs1 = [s for s in _strip_dot_slash(pat1.strip()).rstrip("/").split("/") if s]
    segs2 = [s for s in _strip_dot_slash(pat2.strip()).rstrip("/").split("/") if s]
    memo: dict[tuple[int, int], bool] = {}

    def match(i: int, j: int) -> bool:
        if (i, j) in memo:
            return memo[(i, j)]
        if i == len(segs1) and j == len(segs2):
            return True
        if i < len(segs1) and segs1[i] == "**":
            res = match(i + 1, j) or (j < len(segs2) and match(i, j + 1))
            memo[(i, j)] = res
            return res
        if j < len(segs2) and segs2[j] == "**":
            res = match(i, j + 1) or (i < len(segs1) and match(i + 1, j))
            memo[(i, j)] = res
            return res
        if i == len(segs1) or j == len(segs2):
            memo[(i, j)] = False
            return False
        if _segment_matches(segs1[i], segs2[j]):
            res = match(i + 1, j + 1)
            memo[(i, j)] = res
            return res
        memo[(i, j)] = False
        return False

    return match(0, 0)


def check_ast_test_weakening(
    target_dir: Path, changed_files: list[str]
) -> tuple[bool, list[str]]:
    """Inspect Python test files for syntax errors, skip/xfail decorators, or empty stubs (ported from verify_gate.sh)."""
    errors: list[str] = []
    for f in changed_files:
        f_clean = f.strip()
        if not f_clean.endswith(".py"):
            continue
        base_name = os.path.basename(f_clean).lower()
        is_test = f_clean.startswith(("tests/", "acceptance/")) or bool(
            re.match(r"^(test_.*|.*_test)\.py$", base_name)
        )
        if not is_test:
            continue
        tf = target_dir / f_clean
        if not tf.is_file():
            continue
        try:
            source = tf.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(tf))
        except (OSError, SyntaxError, ValueError) as e:
            errors.append(f"Failed to parse Python test file '{f_clean}': {e}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if func_str in ("pytest.skip", "unittest.skip"):
                    errors.append(f"Test file '{f_clean}' calls {func_str}().")
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "pytestmark":
                        val_str = (
                            ast.unparse(node.value) if hasattr(ast, "unparse") else ""
                        )
                        if "skip" in val_str or "xfail" in val_str:
                            errors.append(
                                f"Test file '{f_clean}' sets pytestmark skip/xfail ({val_str})."
                            )
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and node.name.startswith("test_"):
                stmts = [
                    s
                    for s in node.body
                    if not (
                        isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                    )
                ]
                if not stmts or (len(stmts) == 1 and isinstance(stmts[0], ast.Pass)):
                    errors.append(
                        f"Test function '{node.name}' in '{f_clean}' is an empty stub."
                    )
                for dec in node.decorator_list:
                    dec_target = dec.func if isinstance(dec, ast.Call) else dec
                    dec_str = ast.unparse(dec_target) if hasattr(ast, "unparse") else ""
                    if re.search(r"\b(skip|skipif|xfail)\b", dec_str):
                        errors.append(
                            f"Test function '{node.name}' in '{f_clean}' uses a skip/xfail decorator ({dec_str})."
                        )
    return len(errors) == 0, errors


# === WORKTREE & SANDBOX MANAGEMENT ===


def load_agents_local() -> dict[str, Any]:
    """Load agents.local.yaml if it exists."""
    agents_file = _repo_root() / "agents.local.yaml"
    if not agents_file.exists():
        return {"agents": {}, "assign": {}}
    with open(agents_file, encoding="utf-8") as f:
        return yaml.safe_load(f) or {"agents": {}, "assign": {}}


def get_prompt_version(role: str) -> int:
    """Extract the version number from AGENTS.md for a role (supports both '(vN)' heading and '--- version: N ---')."""
    agents_path = _repo_root() / "AGENTS.md"
    if not agents_path.exists():
        agents_path = AGENTS_MD
    content = agents_path.read_text(encoding="utf-8")

    # Match heading like: ## Role: builder (v1) or ## Role: builder
    heading_match = re.search(
        rf"^##\s+Role:\s+{re.escape(role)}(?:\s+\(v(\d+)\))?\s*$", content, re.MULTILINE
    )
    if not heading_match:
        return 0

    if heading_match.group(1):
        try:
            return int(heading_match.group(1))
        except ValueError:
            pass

    start = heading_match.start()
    code_start = content.find("```text", start)
    if code_start == -1:
        return 0
    code_end = content.find("```", code_start + 7)
    block = content[code_start : code_end if code_end != -1 else len(content)]

    m_ver = re.search(r"---\s*version:\s*(\d+)\s*---", block)
    if m_ver:
        return int(m_ver.group(1))
    return 1


def render_role_prompt(
    role: str,
    milestone: str,
    attempt: int,
    base_commit: str,
    previous_verification: str | None = None,
    *,
    commit: str | None = None,
    worktree: Path | None = None,
) -> tuple[str, int]:
    """Render the role prompt from AGENTS.md with every placeholder resolved.

    base_commit is the attempt's pre-implementation commit ({base}); commit is the commit the
    role works on ({sha}, defaults to base_commit: builders start there, verifiers get the
    built commit). worktree defaults to the attempt's conventional absolute path.
    Returns (prompt, version)."""
    agents_path = _repo_root() / "AGENTS.md"
    if not agents_path.exists():
        agents_path = AGENTS_MD
    content = agents_path.read_text(encoding="utf-8")

    heading_match = re.search(
        rf"^##\s+Role:\s+{re.escape(role)}(?:\s+\(v\d+\))?\s*$", content, re.MULTILINE
    )
    if not heading_match:
        raise ValueError(f"Role {role} not found in AGENTS.md")

    start = heading_match.start()
    code_start = content.find("```text", start)
    code_end = content.find("```", code_start + 7)
    prompt_template = content[code_start + 7 : code_end].strip()
    # Strip optional inline version marker line so rendered prompt stays clean
    prompt_template = re.sub(r"^---\s*version:\s*\d+\s*---\s*\n?", "", prompt_template)

    version = get_prompt_version(role)

    criteria_version = load_state(milestone).get("criteria_version") or ""
    if not criteria_version:
        try:
            criteria_version = spec_hash(milestone)
        except (OSError, yaml.YAMLError, KeyError, ValueError):
            criteria_version = "unversioned"

    if worktree is None:
        kind = "build" if role == "builder" else "verify"
        worktree = _repo_root() / ".worktrees" / f"{milestone}-a{attempt:02d}-{kind}"

    workflow = load_workflow()
    values = {
        "id": milestone,
        "n": f"{attempt:02d}",
        "n_int": str(attempt),
        "sha": commit or base_commit,
        "base": base_commit,
        "criteria_version": criteria_version,
        "worktree": str(worktree),
        "builder_tests": workflow.get("commands", {}).get("builder_tests", ""),
        "orch": str(_repo_root() / "orch"),
        "previous": "\0previous\0",  # filled last: report text may itself contain braces
    }
    prompt = prompt_template
    for key, value in values.items():
        prompt = prompt.replace("{" + key + "}", value)
    unresolved = sorted(set(re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", prompt)))
    if unresolved:
        raise ValueError(f"unresolved placeholders in {role} prompt: {unresolved}")

    report = (
        f"Previous verification report:\n{previous_verification}\n"
        if previous_verification
        else ""
    )
    return prompt.replace("\0previous\0", report), version


def get_agent_candidates(role: str) -> list[tuple[str, dict[str, Any]]]:
    """Return ordered list of (agent_name, agent_config) candidates for role from agents.local.yaml or models.yaml."""
    agents_local = load_agents_local()
    assign = agents_local.get("assign", {})
    agents = agents_local.get("agents", {})

    candidates: list[tuple[str, dict[str, Any]]] = []
    for agent_name in assign.get(role, []):
        if agent_name in agents and agents[agent_name].get("command"):
            candidates.append((agent_name, agents[agent_name]))

    if not candidates:
        models_cfg = load_models_config()
        m_assign = models_cfg.get("assignments", {})
        models = models_cfg.get("models", {})
        for m_name in m_assign.get(role, []):
            if m_name in models and models[m_name].get("command"):
                info = models[m_name]
                candidates.append(
                    (
                        m_name,
                        {
                            "family": info.get("provider", "unknown"),
                            "model": info.get("model", m_name),
                            "tier": info.get("tier", "standard"),
                            "command": info["command"],
                        },
                    )
                )
    return candidates


DEFAULT_AGENT_TIMEOUT = 3600


def _sbpl(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _build_seatbelt_profile(
    worktree: Path,
    git_dir: Path,
    common_dir: Path,
    attempt_tmp: Path,
    state_dirs: list[str],
) -> str:
    """Seatbelt profile: deny all writes, then allow only the attempt worktree, the git
    metadata needed to commit in it (objects, refs, logs, its admin dir), the per-attempt
    TMPDIR and the agent's declared state directories. .git/hooks and .git/config stay denied."""
    allowed = [
        worktree,
        git_dir,
        common_dir / "objects",
        common_dir / "refs",
        common_dir / "logs",
        attempt_tmp,
    ]
    rules = [f"  (subpath {_sbpl(str(p.resolve()))})" for p in allowed]
    rules.append('  (subpath "/dev")')
    for entry in state_dirs:
        if (
            "*" in entry
        ):  # e.g. ~/.claude.json* (lock and temp files next to a state file)
            rx = re.escape(entry).replace(r"\*", "[^/]*")
            rules.append(f'  (regex #"^{rx}$")')
        else:
            rules.append(f"  (subpath {_sbpl(entry)})")
    home = str(Path.home().resolve())
    denied = [f"{home}/.ssh", f"{home}/.aws", f"{home}/.config/gh"]
    return (
        "(version 1)\n(allow default)\n(deny file-write*)\n(allow file-write*\n"
        + "\n".join(rules)
        + ")\n(deny file-read*\n"
        + "\n".join(f"  (subpath {_sbpl(p)})" for p in denied)
        + ")\n"
    )


def _git_path(wt: Path, what: str) -> Path:
    return Path(_git("rev-parse", "--path-format=absolute", what, cwd=wt).strip())


def run_agent_in_worktree(
    worktree_path: str,
    prompt: str,
    agent_command: str,
    log_handle: Any,
    timeout_sec: int = DEFAULT_AGENT_TIMEOUT,
    state_dirs: list[str] | None = None,
) -> int:
    """Run an agent under Seatbelt in its worktree, output to log_handle. Always sandboxed;
    the whole process group is killed when the agent exits. Raises TimeoutExpired."""
    wt = Path(worktree_path).resolve()
    attempt_tmp = Path(tempfile.mkdtemp(prefix="ai2ii-attempt-")).resolve()
    try:
        prompt_file = attempt_tmp / "prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        cmd_str = agent_command.replace("{prompt_file}", shlex.quote(str(prompt_file)))
        env = os.environ.copy()
        env["GIT_OPTIONAL_LOCKS"] = "0"
        env["TMPDIR"] = str(attempt_tmp)
        profile = _build_seatbelt_profile(
            wt,
            _git_path(wt, "--git-dir"),
            _git_path(wt, "--git-common-dir"),
            attempt_tmp,
            state_dirs or [],
        )
        rc, _, _ = run_process_with_group_timeout(
            ["sandbox-exec", "-p", profile, "bash", "-c", cmd_str],
            cwd=wt,
            timeout_sec=timeout_sec,
            env=env,
            stdout_handle=log_handle,
        )
        return rc
    finally:
        shutil.rmtree(attempt_tmp, ignore_errors=True)


def record_attempt_metadata(
    milestone: str,
    attempt: int,
    role: str,
    agent: str,
    model: str,
    result: str,
    commit: str,
    duration: float,
    prompt_version: int | None = None,
    family: str | None = None,
    metrics: bool = True,
) -> Path:
    """Append a candidate record to <role>_metadata.yaml (top level mirrors the latest record,
    `candidates` lists all) and, unless metrics=False, update metrics/<milestone>.yaml."""
    attempts_dir = MILESTONES_DIR / milestone / "attempts" / f"{attempt:02d}"
    attempts_dir.mkdir(parents=True, exist_ok=True)

    if prompt_version is None:
        try:
            prompt_version = get_prompt_version(role)
        except (OSError, ValueError):
            prompt_version = 1

    metadata_file = attempts_dir / f"{role}_metadata.yaml"
    previous: list[Any] = []
    if metadata_file.exists():
        old = yaml.safe_load(metadata_file.read_text(encoding="utf-8")) or {}
        previous = list(old.get("candidates") or [])
    record = {
        "milestone": milestone,
        "attempt": attempt,
        "role": role,
        "agent": agent,
        "family": family or model,
        "model": model,
        "prompt_version": prompt_version,
        "result": result,
        "commit": commit,
        "duration_seconds": round(duration, 3),
        "timestamp": _utc_now(),
    }
    metadata_file.write_text(
        yaml.safe_dump({**record, "candidates": [*previous, record]}, sort_keys=False),
        encoding="utf-8",
    )

    if metrics:
        # Also update metrics/<milestone>.yaml (DESIGN.md 24.17)
        try:
            METRICS_DIR.mkdir(parents=True, exist_ok=True)
            m_file = METRICS_DIR / f"{milestone}.yaml"
            m_data: dict[str, Any] = {}
            if m_file.exists():
                m_data = yaml.safe_load(m_file.read_text(encoding="utf-8")) or {}
            m_data["milestone"] = milestone
            m_data["attempts"] = max(int(m_data.get("attempts", 0)), attempt)
            m_data["cost_usd"] = None
            m_data["wall_time_seconds"] = round(
                float(m_data.get("wall_time_seconds", 0.0)) + duration, 3
            )
            m_data.setdefault("families", {})[role] = family or model
            m_data.setdefault("prompt_versions", {})[role] = prompt_version
            m_file.write_text(yaml.safe_dump(m_data, sort_keys=False), encoding="utf-8")
        except (OSError, yaml.YAMLError, ValueError) as exc:
            _ = exc
    return metadata_file


# --- dispatch (DESIGN.md 24.3) ---


@contextlib.contextmanager
def _main_lock() -> Any:
    """Main worktree on main, serialised on the repository lock."""
    refusal = _require_main_branch()
    if refusal:
        raise Refused(refusal.removeprefix("Refused: "))
    with _repo_lock():
        yield


def _identity(name: str, info: dict[str, Any]) -> dict[str, str]:
    return {
        "agent": name,
        "family": str(info.get("family") or "unknown"),
        "model": str(info.get("model") or ""),
        "session": f"dispatch-{uuid.uuid4().hex[:12]}",
    }


def _set_identity(m: str, role: str, ident: dict[str, str]) -> None:
    """Make `ident` the recorded builder/verifier of the current attempt (fallback candidate)."""
    st = load_state(m)
    a = _cur(st)
    a[role] = dict(ident)
    note = f"{role} is now {ident['agent']} (fallback candidate)"
    if role == "verifier" and ident["family"] == a["builder"].get("family"):
        note += " (same family as builder: SHOULD differ, 24.15)"
    _set_status(st, st["status"], note)
    save_state(m, st, f"orchestrator: {m} {role} -> {ident['agent']}")


def _reset_worktree(wt: Path, branch: str, base: str) -> None:
    """Back to the recorded base: branch on base, nothing untracked or ignored."""
    _git("checkout", "-q", "-f", "-B", branch, base, cwd=wt)
    _git("clean", "-q", "-f", "-d", "-x", cwd=wt)


def _run_candidate(
    wt: Path,
    branch: str,
    base: str,
    record: str,
    prompt: str,
    info: dict[str, Any],
    log: Path,
) -> tuple[str, str]:
    """Run one candidate to completion. Returns (result, head): result is success | failure |
    timeout | no-record. On anything but success the worktree is reset to base."""
    log.parent.mkdir(parents=True, exist_ok=True)
    state_dirs = [os.path.expanduser(str(d)) for d in info.get("state_dirs") or []]
    with open(log, "w", encoding="utf-8") as f:
        f.write(f"# command: {info['command']}\n")
        f.flush()
        try:
            rc = run_agent_in_worktree(
                str(wt),
                prompt,
                info["command"],
                f,
                int(info.get("timeout_seconds") or DEFAULT_AGENT_TIMEOUT),
                state_dirs,
            )
            result = "success" if rc == 0 else "failure"
        except subprocess.TimeoutExpired:
            rc, result = 124, "timeout"
        f.write(f"\n# exit: {rc}\n")
        head = _git("rev-parse", "HEAD", cwd=wt, check=False).strip()
        if result == "success" and not (
            head
            and head
            == _git("rev-parse", f"refs/heads/{branch}", cwd=wt, check=False).strip()
            and _git_ok("cat-file", "-e", f"{head}:{record}", cwd=wt)
        ):
            result = "no-record"
            f.write(f"# no committed {record} on {branch}\n")
        if result == "success":
            leftovers = _git("status", "--porcelain", "--ignored", cwd=wt).strip()
            if leftovers:
                f.write(f"# discarded uncommitted leftovers:\n{leftovers}\n")
                _git("reset", "-q", "--hard", "HEAD", cwd=wt)
                _git("clean", "-q", "-f", "-d", "-x", cwd=wt)
    if result != "success":
        _reset_worktree(wt, branch, base)
    return result, head


def cmd_dispatch(args: Any) -> int:
    """start-build / start-verify, run the configured candidates under Seatbelt with
    fallback, and leave the attempt ready for finish-build / finish-verify (DESIGN.md 24.3).
    Attempt records stay on the attempt branch; main only gets state, metadata and run logs."""
    m, role = args.milestone, args.role
    with _main_lock():
        st = _require_milestone(m)
        _require_status(
            st, m, *(("READY", "REWORK") if role == "builder" else ("BUILT",))
        )
        candidates = get_agent_candidates(role)
        if not candidates:
            raise Refused(f"no agent configured for role {role}")
        if not shutil.which("sandbox-exec"):
            raise Refused("sandbox-exec not found: dispatch always runs under Seatbelt")
        ident = _identity(*candidates[0])
        (cmd_start_build if role == "builder" else cmd_start_verify)(
            argparse.Namespace(milestone=m, **ident)
        )
        st = load_state(m)
        a = _cur(st)
        if role == "builder":
            branch, rel, base = a["branch"], a["worktree"], a["base"]
            record_name = "build.md"
        else:
            branch, rel, base = a["verify_branch"], a["verify_worktree"], a["built"]
            record_name = "verification.yaml"
        n, wt = a["n"], _repo_root() / rel
        record = f"milestones/{m}/attempts/{_nn(n)}/{record_name}"
        previous = None
        prev = (
            st["attempts"][-2]
            if role == "builder" and len(st["attempts"]) > 1
            else None
        )
        if prev and prev.get("verify_branch"):
            previous = _git(
                "show",
                f"{prev['verify_branch']}:milestones/{m}/attempts/{_nn(prev['n'])}/verification.yaml",
                check=False,
            )
        prompt, version = render_role_prompt(
            role, m, n, a["base"], previous or None,
            commit=a["built"] if role == "verifier" else None, worktree=wt,
        )  # fmt: skip

    for idx, (name, info) in enumerate(candidates):
        if idx:
            ident = _identity(name, info)
            with _main_lock():
                _set_identity(m, role, ident)
        log = _run_dir(m, n, a["base"]) / f"dispatch-{role}-{idx + 1:02d}-{name}.log"
        t0 = time.monotonic()
        result, head = _run_candidate(wt, branch, base, record, prompt, info, log)
        duration = time.monotonic() - t0
        with _main_lock():
            meta = record_attempt_metadata(
                m, n, role, name, ident["model"], result, head, duration,
                prompt_version=version, family=ident["family"], metrics=False,
            )  # fmt: skip
            st = load_state(m)
            if result != "success":
                _set_status(
                    st, st["status"], f"{role} candidate {name} {result} ({_rel(log)})"
                )
            save_state(
                m, st, f"orchestrator: {m} dispatch {role} {name} {result}", [meta, log]
            )
        print(f"{m}: {role} candidate {name}: {result}")
        if result == "success":
            print(
                f"{m}: attempt {_nn(n)} ready for finish-{'build' if role == 'builder' else 'verify'}"
            )
            return 0
    print(
        f"dispatch failed: every {role} candidate failed; {m} stays {st['status']}",
        file=sys.stderr,
    )
    return 1


# === STATE, SPEC, AND OWNERSHIP PRIMITIVES ===


def load_workflow() -> dict[str, Any]:
    wf_path = _repo_root() / "workflow.yaml"
    if not wf_path.exists():
        wf_path = WORKFLOW_YAML
    with open(wf_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_spec(milestone: str) -> dict[str, Any]:
    spec_file = MILESTONES_DIR / milestone / "spec.yaml"
    with open(spec_file, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_git_sha(cwd: Path | None = None) -> str:
    target = cwd or _repo_root()
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=target,
        check=False,
    )
    return result.stdout.strip()[:12]


def is_valid_git_commit(rev: str, cwd: Path | None = None) -> bool:
    if not rev or not isinstance(rev, str):
        return False
    target = cwd or _repo_root()
    res = subprocess.run(
        ["git", "rev-parse", "--verify", f"{rev}^{{commit}}"],
        cwd=target,
        capture_output=True,
        text=True,
        check=False,
    )
    return res.returncode == 0


def get_git_diff(start_sha: str) -> str:
    """Return newline-separated changed and untracked files since start_sha. Fails closed on invalid start_sha."""
    root = _repo_root()
    if not is_valid_git_commit(start_sha, cwd=root):
        raise ValueError(f"Invalid git base revision: {start_sha}")

    files: set[str] = set()
    diff_res = subprocess.run(
        ["git", "diff", start_sha, "--name-only"],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    if diff_res.returncode != 0:
        raise ValueError(f"git diff failed for {start_sha}: {diff_res.stderr.strip()}")
    for line in diff_res.stdout.splitlines():
        if line.strip() and not line.strip().endswith(".state.lock"):
            files.add(line.strip())

    untracked_res = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    if untracked_res.returncode == 0:
        for line in untracked_res.stdout.splitlines():
            if line.strip() and not line.strip().endswith(".state.lock"):
                files.add(line.strip())

    return "\n".join(sorted(files))


def _matches_ownership_rules(
    path_str: str, rules: list[dict[str, str]], milestone: str, attempt: int
) -> bool:
    for p_pat in PROTECTED_PATTERNS:
        if glob_to_regex(p_pat).match(path_str):
            return False

    for rule in rules:
        if "allow" in rule:
            action = "allow"
            pattern = rule["allow"]
        elif "deny" in rule:
            action = "deny"
            pattern = rule["deny"]
        else:
            continue
        pattern = pattern.replace("{id}", milestone).replace("{n}", f"{attempt:02d}")
        if glob_to_regex(pattern).match(path_str):
            return action == "allow"
    return False


def check_ownership(
    role: str,
    milestone: str,
    attempt: int,
    changed_files: list[str],
    root_dir: Path | None = None,
) -> tuple[bool, list[str]]:
    """Check if changed files are allowed for the role, rejecting traversal ('..'), absolute paths, and symlink escapes."""
    workflow = load_workflow()
    ownership = workflow.get("ownership", {}).get(role, [])
    base_root = (root_dir or _repo_root()).resolve()

    violations: list[str] = []

    for raw_path in changed_files:
        if not raw_path or not raw_path.strip():
            continue
        file_path = raw_path.strip()
        if file_path.endswith(".state.lock"):
            continue

        # Reject absolute paths and '..' traversal segments immediately
        parts = Path(file_path).parts
        if file_path.startswith("/") or ".." in parts:
            violations.append(file_path)
            continue

        norm_path = _strip_dot_slash(file_path)
        if not _matches_ownership_rules(norm_path, ownership, milestone, attempt):
            violations.append(file_path)
            continue

        # Check symlink / resolved path escape on disk if present
        candidate = base_root / norm_path
        if candidate.exists() or candidate.is_symlink():
            try:
                resolved = candidate.resolve()
                try:
                    rel_resolved = str(resolved.relative_to(base_root))
                except ValueError:
                    # Symlink points outside repository root
                    violations.append(file_path)
                    continue
                if rel_resolved != norm_path and not _matches_ownership_rules(
                    rel_resolved, ownership, milestone, attempt
                ):
                    violations.append(file_path)
                    continue
            except OSError:
                violations.append(file_path)
                continue

    return len(violations) == 0, violations


# === TEST EXECUTION & VALIDITY ===


def _build_test_command(template: str, paths: list[str] | None = None) -> list[str]:
    """Build argv list from workflow command template, replacing {paths} and using current Python interpreter."""
    tokens = shlex.split(template)
    if tokens and tokens[0] in ("python3", "python"):
        tokens[0] = sys.executable

    resolved_paths = [str(p) for p in (paths or []) if str(p).strip()]
    final_cmd: list[str] = []
    replaced = False
    for tok in tokens:
        if tok == "{paths}":
            final_cmd.extend(resolved_paths)
            replaced = True
        else:
            final_cmd.append(tok)

    if not replaced and resolved_paths:
        final_cmd.extend(resolved_paths)
    return final_cmd


# === ESCALATION HANDLING & HUMAN GATES (M04) ===

ESCALATION_CLASSIFICATIONS = [
    "IMPLEMENTATION",
    "VERIFICATION",
    "MILESTONE_SPEC",
    "ARCHITECTURE",
    "EXTERNAL_DEPENDENCY",
    "PROTOCOL_SPEC",
    "UNKNOWN",
]

ESCALATION_OUTCOMES = ["REWORK", "DRAFT", "BLOCKED"]


# === TRANSITION PRECONDITIONS ===


# === DAG VALIDATION, SEALING, GOLDFISH & CONTEXT (PORTED FROM AGENTWORK) ===


def load_all_milestones() -> dict[str, dict[str, Any]]:
    milestones: dict[str, dict[str, Any]] = {}
    if not MILESTONES_DIR.exists():
        return milestones
    for spec_file in sorted(MILESTONES_DIR.glob("M*/spec.yaml")):
        mid = spec_file.parent.name
        spec = load_spec(mid)
        spec["id"] = spec.get("id", mid)
        spec["_file"] = str(spec_file.relative_to(_repo_root()))
        milestones[mid] = spec
    return milestones


def validate_dag_internal() -> list[str]:
    """Validate milestone DAG for missing dependencies, cycles, and empty acceptance criteria."""
    milestones = load_all_milestones()
    errors: list[str] = []

    for mid, spec in milestones.items():
        if not spec.get("acceptance"):
            errors.append(f"Milestone {mid} has no acceptance criteria")
        for dep in spec.get("depends_on", []):
            if dep not in milestones:
                errors.append(f"Milestone {mid} depends on unknown milestone {dep}")

    visited: dict[str, int] = {}

    def dfs(curr: str, path: list[str]) -> None:
        visited[curr] = 1
        for dep in milestones.get(curr, {}).get("depends_on", []):
            if dep in path:
                errors.append(
                    f"Cycle detected in milestone DAG: {' -> '.join(path + [dep])}"
                )
            elif dep in milestones and visited.get(dep) != 2:
                dfs(dep, path + [dep])
        visited[curr] = 2

    for mid in milestones:
        if visited.get(mid) != 2:
            dfs(mid, [mid])

    return errors


def compute_current_manifest() -> dict[str, Any]:
    """Compute topological SHA-256 manifest across DESIGN.md, workflow.yaml, AGENTS.md, verify_gate.sh, and milestone specs."""
    root = _repo_root()
    design_p = root / "DESIGN.md"
    wf_p = root / "workflow.yaml"
    ag_p = root / "AGENTS.md"
    gate_p = root / "scripts" / "verify_gate.sh"

    design_hash = (
        hashlib.sha256(design_p.read_bytes()).hexdigest() if design_p.exists() else ""
    )
    policy_hash = hashlib.sha256(wf_p.read_bytes()).hexdigest() if wf_p.exists() else ""
    agents_hash = hashlib.sha256(ag_p.read_bytes()).hexdigest() if ag_p.exists() else ""
    gate_hash = (
        hashlib.sha256(gate_p.read_bytes()).hexdigest() if gate_p.exists() else ""
    )

    milestones = load_all_milestones()
    manifest: dict[str, Any] = {
        "version": "2.0",
        "design_hash": design_hash,
        "policy_hash": policy_hash,
        "agents_hash": agents_hash,
        "gate_hash": gate_hash,
        "milestones": {},
    }

    memo_digests: dict[str, str] = {}

    def get_milestone_digest(mid: str, stack: set[str] | None = None) -> str:
        if mid in memo_digests:
            return memo_digests[mid]
        if stack is None:
            stack = set()
        if mid in stack or mid not in milestones:
            return ""
        stack.add(mid)
        spec = milestones[mid]
        spec_digest = spec_hash(mid)

        h = hashlib.sha256()
        h.update(policy_hash.encode())
        h.update(design_hash.encode())
        h.update(agents_hash.encode())
        h.update(gate_hash.encode())
        h.update(spec_digest.encode())
        for dep in sorted(spec.get("depends_on", [])):
            dep_digest = get_milestone_digest(dep, stack)
            h.update(f"{dep}:{dep_digest}".encode())

        digest = h.hexdigest()
        memo_digests[mid] = digest
        manifest["milestones"][mid] = {
            "file": spec.get("_file", f"milestones/{mid}/spec.yaml"),
            "criteria_version": spec_digest,
            "digest": digest,
            "depends_on": list(spec.get("depends_on", [])),
        }
        return digest

    for mid in sorted(milestones.keys()):
        get_milestone_digest(mid)

    return manifest


def cmd_validate(args: Any) -> int:
    """Validate milestone DAG and specifications."""
    errors = validate_dag_internal()
    if errors:
        print("DAG validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("DAG validation PASSED cleanly.")
    return 0


def cmd_seal(args: Any) -> int:
    """Validate DAG, compute topological digests, and write harness-manifest.json."""
    errors = validate_dag_internal()
    if errors:
        print("ERROR: Cannot seal an invalid milestone DAG:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = compute_current_manifest()
    manifest["sealed_at"] = time.time()
    generation = 1
    if MANIFEST_FILE.exists():
        try:
            old = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
            generation = int(old.get("generation", 1)) + 1
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _ = exc
    manifest["generation"] = generation
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        f"Sealed {len(manifest['milestones'])} milestones (generation {generation}) to {MANIFEST_FILE}"
    )
    return 0


def cmd_goldfish(args: Any) -> int:
    """Run static specification & boundary audit across all milestones (ported from agentwork)."""
    milestones = load_all_milestones()
    findings: list[dict[str, str]] = []

    for mid, spec in sorted(milestones.items()):
        raw_text = (MILESTONES_DIR / mid / "spec.yaml").read_text(encoding="utf-8")
        ambiguous = re.findall(r"\b(TBD|TODO|FIXME)\b", raw_text)
        state = load_state(mid)
        if ambiguous and state.get("status") not in ("DRAFT",):
            findings.append(
                {
                    "persona": "Ambiguity-Goldfish",
                    "severity": "ERROR",
                    "milestone": mid,
                    "issue": f"Non-DRAFT spec contains unresolved placeholders: {sorted(set(ambiguous))}",
                }
            )
        if spec.get("size_hint") == "L" and not spec.get("size_justification"):
            findings.append(
                {
                    "persona": "Scope-Goldfish",
                    "severity": "ERROR",
                    "milestone": mid,
                    "issue": "Milestone has size_hint: L without size_justification (DESIGN.md 24.6).",
                }
            )

    err_count = sum(1 for f in findings if f["severity"] == "ERROR")
    if getattr(args, "json", False):
        print(json.dumps({"findings": findings, "error_count": err_count}, indent=2))
        return 1 if err_count > 0 else 0

    print(f"=== Running Goldfish Spec Audit across {len(milestones)} milestones ===")
    if not findings:
        print("  GOLDFISH AUDIT PASSED: No ambiguity or scope defects found.")
        return 0
    for f in findings:
        print(f"  [{f['severity']}] ({f['persona']}) {f['milestone']}: {f['issue']}")
    return 1 if err_count > 0 else 0


def extract_file_symbols(file_path: Path) -> tuple[list[str], list[str]]:
    """Extract public signatures and imported modules from a source file (ported from agentwork)."""
    signatures: list[str] = []
    imports: list[str] = []
    if not file_path.exists() or not file_path.is_file():
        return signatures, imports
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return signatures, imports

    if file_path.suffix == ".py":
        try:
            tree = ast.parse(text, filename=str(file_path))
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for n in node.names:
                        imports.append(n.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not node.name.startswith("_"):
                        args_str = (
                            ast.unparse(node.args) if hasattr(ast, "unparse") else "..."
                        )
                        ret_str = (
                            f" -> {ast.unparse(node.returns)}"
                            if getattr(node, "returns", None)
                            and hasattr(ast, "unparse")
                            else ""
                        )
                        prefix = (
                            "async def "
                            if isinstance(node, ast.AsyncFunctionDef)
                            else "def "
                        )
                        signatures.append(f"{prefix}{node.name}({args_str}){ret_str}")
                elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                    bases = (
                        [ast.unparse(b) for b in node.bases]
                        if hasattr(ast, "unparse")
                        else []
                    )
                    base_str = f"({', '.join(bases)})" if bases else ""
                    signatures.append(f"class {node.name}{base_str}:")
        except (SyntaxError, ValueError) as exc:
            _ = exc
    return signatures, imports


def cmd_context(args: Any) -> int:
    """Compile deterministic context and 1-hop AST symbol signatures for a milestone (ported from agentwork)."""
    mid = args.milestone.upper()
    spec = load_spec(mid)
    root = _repo_root()
    symbols: dict[str, list[str]] = {}
    for inp in spec.get("inputs", []):
        p = root / str(inp).split()[0]
        if p.is_file():
            sigs, _ = extract_file_symbols(p)
            if sigs:
                symbols[str(p.relative_to(root))] = sigs

    payload = {
        "milestone": mid,
        "depends_on": spec.get("depends_on", []),
        "inputs": spec.get("inputs", []),
        "deliverables": spec.get("deliverables", []),
        "symbols": symbols,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(f"=== Context for {mid} ===")
        print(f"Depends on: {', '.join(payload['depends_on']) or 'None'}")
        print(f"Inputs:     {', '.join(str(x) for x in payload['inputs']) or 'None'}")
        if symbols:
            print("Symbols:")
            for f_rel, sigs in symbols.items():
                print(f"  [{f_rel}] ({len(sigs)} public symbols)")
    return 0


def cmd_doctor(args: Any) -> int:
    """Run system and sandbox diagnostics (ported from agentwork)."""
    print("=== AI2II Orchestrator Doctor ===")
    errors: list[str] = []
    for binary in ("git", "python3"):
        if shutil.which(binary):
            print(f"  [OK] {binary} found")
        else:
            errors.append(f"Missing binary: {binary}")

    if shutil.which("sandbox-exec"):
        print("  [OK] macOS Seatbelt (sandbox-exec) available")
    elif shutil.which("bwrap"):
        print("  [OK] Linux Bubblewrap (bwrap) available")
    else:
        print(
            "  [WARN] No OS sandbox binary (sandbox-exec/bwrap) found; worktree-only isolation active"
        )

    dag_errs = validate_dag_internal()
    if dag_errs:
        errors.extend(dag_errs)
    else:
        print("  [OK] Milestone DAG valid")

    return 1 if errors else 0


# === CLI COMMAND HANDLERS ===


def cmd_check_ownership(args: Any) -> int:
    """Check path ownership for a role (fails closed on invalid git ref)."""
    if args.files:
        changed = [f for f in args.files if f]
    else:
        try:
            changed = [f for f in get_git_diff(args.base).splitlines() if f]
        except ValueError as e:
            print(f"Path ownership: FAILED ({e})")
            return 1

    ok, violations = check_ownership(args.role, args.milestone, args.attempt, changed)
    if ok:
        print("Path ownership: PASSED")
        return 0
    else:
        print("Path ownership: FAILED")
        for v in violations:
            print(f"  VIOLATION: {v}")
        return 1


# === MODELS COMMAND ===


def load_models_config() -> dict[str, Any]:
    """Load models configuration."""
    if not MODELS_FILE.exists():
        return {"models": {}, "assignments": {}}
    with open(MODELS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {"models": {}, "assignments": {}}


def save_models_config(config: dict[str, Any]) -> None:
    """Save models configuration."""
    with open(MODELS_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f)


def cmd_models(args: Any) -> int:
    """Manage model configurations."""
    config = load_models_config()

    if args.action == "list":
        print("Configured Models:")
        print("=" * 60)
        for name, model in config.get("models", {}).items():
            print(f"\n  {name}:")
            print(f"    Provider: {model.get('provider', 'unknown')}")
            print(f"    Model:    {model.get('model', 'unknown')}")
            print(f"    Tier:     {model.get('tier', 'standard')}")
            print(f"    Command:  {model.get('command', 'N/A')}")

        print("\nRole Assignments:")
        for role, models in config.get("assignments", {}).items():
            print(f"  {role}: {', '.join(models) if models else 'unassigned'}")
        return 0

    elif args.action == "add":
        if not all([args.name, args.provider, args.model, args.command]):
            print("Error: --name, --provider, --model, and --command required for add")
            return 1

        config.setdefault("models", {})[args.name] = {
            "provider": args.provider,
            "model": args.model,
            "tier": args.tier or "standard",
            "command": args.command,
        }

        if args.role:
            config.setdefault("assignments", {}).setdefault(args.role, [])
            if args.name not in config["assignments"][args.role]:
                config["assignments"][args.role].append(args.name)

        save_models_config(config)
        print(f"Added model: {args.name}")
        return 0

    elif args.action == "remove":
        if not args.name:
            print("Error: --name required for remove")
            return 1

        if args.name in config.get("models", {}):
            del config["models"][args.name]

        for models in config.get("assignments", {}).values():
            if args.name in models:
                models.remove(args.name)

        save_models_config(config)
        print(f"Removed model: {args.name}")
        return 0

    elif args.action == "test":
        if not args.name or args.name not in config.get("models", {}):
            print(f"Error: Model '{args.name}' not found")
            return 1

        model = config["models"][args.name]
        prompt = "Reply with exactly: MODEL_TEST_OK"
        fd, tmp_prompt = tempfile.mkstemp(prefix="model_test_", suffix=".txt")
        prompt_file = Path(tmp_prompt)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(prompt)

            cmd_str = model["command"].replace("{prompt_file}", str(prompt_file))
            print(f"Testing model: {args.name}")
            print(f"Command: {cmd_str}")

            rc, stdout, stderr = run_process_with_group_timeout(
                ["bash", "-c", cmd_str],
                cwd=_repo_root(),
                timeout_sec=60,
            )
            print(f"Exit code: {rc}")
            print(f"Stdout: {stdout.strip()}")
            if stderr:
                print(f"Stderr: {stderr.strip()}")
            success = (rc == 0) and ("MODEL_TEST_OK" in stdout)
            print(f"Test: {'PASSED' if success else 'FAILED'}")
            return 0 if success else 1
        except subprocess.TimeoutExpired:
            print("Test: TIMEOUT")
            return 1
        finally:
            prompt_file.unlink(missing_ok=True)

    elif args.action == "benchmark":
        if not args.role:
            print("Error: --role required for benchmark")
            return 1

        assignments = config.get("assignments", {}).get(args.role, [])
        if not assignments:
            print(f"No models assigned to role: {args.role}")
            return 1

        print(
            f"Configured model inventory for role: {args.role} ({len(assignments)} assigned)"
        )
        for name in assignments:
            model = config.get("models", {}).get(name)
            if model:
                print(
                    f"  {name}: {model['provider']}/{model['model']} ({model['tier']})"
                )
        return 0

    return 1


# === IMPROVE COMMAND ===


def cmd_improve(args: Any) -> int:
    """Capture orchestrator improvement / best practice with atomic log update."""
    IMPROVEMENTS_DIR.mkdir(parents=True, exist_ok=True)

    improvement = {
        "id": str(uuid.uuid4())[:8],
        "type": args.type,
        "description": args.description,
        "context": args.context or "",
        "author": args.author or "unknown",
        "tags": args.tags or [],
        "timestamp": _utc_now(),
        "status": "proposed",
    }

    imp_file = IMPROVEMENTS_DIR / f"{improvement['id']}_{args.type}.yaml"
    with open(imp_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(improvement, f)

    log_file = IMPROVEMENTS_DIR / "improvements_log.yaml"
    lock_file = IMPROVEMENTS_DIR / ".improvements.lock"
    lock_file.touch(exist_ok=True)
    with open(lock_file, "r+", encoding="utf-8") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            log = []
            if log_file.exists():
                with open(log_file, encoding="utf-8") as f:
                    log = yaml.safe_load(f) or []
            log.append(improvement)
            with open(log_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(log, f)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)

    print(f"Recorded improvement: {improvement['id']}")
    print(f"  Type: {args.type}")
    print(f"  Description: {args.description}")
    return 0


# === M01 CORE: governed state, lifecycle commands (DESIGN.md 24.3, 24.7) ===
#
# State lives in milestones/<id>/state.yaml of the MAIN repository. Only this file's
# code writes it, and every write is a git commit authored "orchestrator" on branch main.
# Every state command holds one repository-wide lock (in the git common dir) for its whole
# run, so concurrent finishes serialise and never interleave a read-modify-write.


class Refused(Exception):
    """A precondition failed: exit 1, reason on stderr, state untouched."""


ORCH_NAME = "orchestrator"
ORCH_EMAIL = "orchestrator@ai2ii.invalid"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
GATE_OK_RE = re.compile(r"Decision:\**\s*APPROVED\b", re.MULTILINE)


def _strip_dot_slash(path: str) -> str:
    """Drop leading './' segments only (never '.git', '.worktrees' dots)."""
    while path.startswith("./"):
        path = path[2:]
    return path


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=cwd or _repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and res.returncode != 0:
        raise Refused(f"git {' '.join(args[:2])}: {(res.stderr or res.stdout).strip()}")
    return res.stdout


def _git_ok(*args: str, cwd: Path | None = None) -> bool:
    return (
        subprocess.run(
            ["git", *args], cwd=cwd or _repo_root(), capture_output=True, check=False
        ).returncode
        == 0
    )


def _require_main_branch() -> str | None:
    """State commands run in the main worktree, on branch main (DESIGN.md 24.3)."""
    root = _repo_root()
    first = ""
    for ln in _git("worktree", "list", "--porcelain").splitlines():
        if ln.startswith("worktree "):
            first = ln[len("worktree ") :]
            break
    if not first or Path(first).resolve() != root:
        return f"Refused: {root} is not the main worktree of its repository"
    branch = _git("symbolic-ref", "--quiet", "--short", "HEAD", check=False).strip()
    if branch != "main":
        return f"Refused: main worktree {root} is on '{branch or 'detached HEAD'}', not 'main'"
    return None


@contextlib.contextmanager
def _repo_lock() -> Any:
    common = (_repo_root() / _git("rev-parse", "--git-common-dir").strip()).resolve()
    with open(common / "ai2ii-orch.lock", "a", encoding="utf-8") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def governed(fn: Any) -> Any:
    """State commands: main worktree on main, serialised on the repository lock."""

    @functools.wraps(fn)
    def wrapper(args: Any) -> int:
        with _main_lock():
            return fn(args)

    return wrapper


def _rel(path: Path) -> str:
    return os.path.relpath(path, _repo_root())


def commit_paths(paths: list[Path], message: str) -> None:
    """Commit exactly these files in the main repository as the orchestrator."""
    rels = [_rel(p) for p in paths if p.exists()]
    if not rels:
        return
    _git("add", "-A", "--", *rels)
    if not _git("status", "--porcelain", "--", *rels).strip():
        return
    ident = f"{ORCH_NAME} <{ORCH_EMAIL}>"
    _git(
        *("-c", f"user.name={ORCH_NAME}", "-c", f"user.email={ORCH_EMAIL}"),
        *("-c", "commit.gpgsign=false"),
        *("commit", "-q", "--no-verify", f"--author={ident}", "-m", message),
        "--",
        *rels,
    )


def _state_file(milestone: str) -> Path:
    return MILESTONES_DIR / milestone / "state.yaml"


def load_state(milestone: str) -> dict[str, Any]:
    f = _state_file(milestone)
    state: dict[str, Any] = {}
    if f.exists():
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise Refused(f"corrupted state.yaml in {milestone}")
        state = data
    state.setdefault("status", "DRAFT")
    state.setdefault("criteria_version", None)
    state.setdefault("attempt", 0)
    for key in ("attempts", "escalations", "history"):
        if not isinstance(state.get(key), list):
            state[key] = []
    return state


def save_state(
    milestone: str,
    state: dict[str, Any],
    message: str | None = None,
    extra: list[Path] | None = None,
) -> None:
    """Atomically write state.yaml, then commit it (and `extra` files) as the orchestrator."""
    state["milestone"] = milestone
    f = _state_file(milestone)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(f.parent), prefix=".state.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as tf:
        tf.write(yaml.safe_dump(state, sort_keys=False))
        tf.flush()
        os.fsync(tf.fileno())
    os.replace(tmp, f)
    commit_paths(
        [f, *(extra or [])],
        message or f"orchestrator: {milestone} -> {state.get('status')}",
    )


def spec_hash(milestone: str) -> str:
    """criteria_version: sha256 of spec.yaml (DESIGN.md 24.6)."""
    return hashlib.sha256(
        (MILESTONES_DIR / milestone / "spec.yaml").read_bytes()
    ).hexdigest()


def _milestone_ids() -> list[str]:
    return sorted(p.parent.name for p in MILESTONES_DIR.glob("M*/spec.yaml"))


def _require_milestone(milestone: str) -> dict[str, Any]:
    if (
        not NAME_RE.match(milestone)
        or not (MILESTONES_DIR / milestone / "spec.yaml").is_file()
    ):
        raise Refused(f"unknown milestone {milestone}")
    return load_state(milestone)


def _set_status(state: dict[str, Any], to: str, note: str) -> None:
    state["history"].append(
        {"at": _utc_now(), "from": state["status"], "to": to, "note": note}
    )
    state["status"] = to


def _require_status(state: dict[str, Any], milestone: str, *allowed: str) -> None:
    if state["status"] not in allowed:
        raise Refused(
            f"{milestone} is {state['status']}; this command needs {' or '.join(allowed)}"
        )


def _require_current_spec(milestone: str, state: dict[str, Any]) -> None:
    cv = state.get("criteria_version")
    if not cv:
        raise Refused(f"{milestone} has no approved criteria_version")
    if spec_hash(milestone) != cv:
        raise Refused(f"spec.yaml of {milestone} changed since approval (run refresh)")


def _cur(state: dict[str, Any]) -> dict[str, Any]:
    if not state["attempts"]:
        raise Refused("no attempt recorded")
    return state["attempts"][-1]


def _nn(n: int) -> str:
    return f"{int(n):02d}"


def _max_attempts(state: dict[str, Any]) -> int:
    limit = int(load_workflow().get("limits", {}).get("max_attempts", 3))
    return limit + int(state.get("extra_attempts") or 0)


def _committed_text(rel: str, folder: str) -> str:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != folder:
        raise Refused(f"{rel} must be a path under {folder}/")
    res = subprocess.run(
        ["git", "show", f"HEAD:{p.as_posix()}"],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise Refused(f"{rel} is not committed on main")
    return res.stdout


def _names(text: str, token: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text))


def _check_approval(rel: str, tokens: list[str]) -> None:
    text = _committed_text(rel, "approvals")
    for token in tokens:
        if not _names(text, token):
            raise Refused(f"{rel} does not name {token}")
    if not GATE_OK_RE.search(text):
        raise Refused(f"{rel} does not record 'Decision: APPROVED'")


# --- worktrees, test runs ---


def _ensure_worktrees_excluded() -> None:
    exclude = _repo_root() / _git("rev-parse", "--git-path", "info/exclude").strip()
    exclude.parent.mkdir(parents=True, exist_ok=True)
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if ".worktrees/" not in current.splitlines():
        exclude.write_text(
            current
            + ("" if current.endswith("\n") or not current else "\n")
            + ".worktrees/\n",
            encoding="utf-8",
        )


def _add_worktree(branch: str, rel: str, start: str) -> None:
    if _git_ok("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"):
        raise Refused(f"branch {branch} already exists")
    if (_repo_root() / rel).exists():
        raise Refused(f"{rel} already exists")
    _ensure_worktrees_excluded()
    _git("worktree", "add", "-q", "-b", branch, str(_repo_root() / rel), start)


def _changed_paths(root: Path, base: str, head: str) -> list[str]:
    out = _git("diff", "--name-only", "--no-renames", "-z", base, head, cwd=root)
    return [p for p in out.split("\0") if p]


def _check_range_ownership(
    role: str, milestone: str, n: int, root: Path, base: str, head: str
) -> None:
    if not _git_ok("merge-base", "--is-ancestor", base, head, cwd=root):
        raise Refused(f"{head[:12]} does not descend from {base[:12]}")
    ok, violations = check_ownership(
        role, milestone, n, _changed_paths(root, base, head), root_dir=root
    )
    if not ok:
        raise Refused(f"{role} ownership violations: {', '.join(violations)}")


@contextlib.contextmanager
def _temp_tree(rev: str) -> Any:
    tmp = Path(tempfile.mkdtemp(prefix="ai2ii-wt-"))
    try:
        _git("worktree", "add", "-q", "--detach", str(tmp), rev)
        yield tmp
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(tmp)],
            cwd=_repo_root(),
            capture_output=True,
            check=False,
        )
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=_repo_root(),
            capture_output=True,
            check=False,
        )


def _run_logged(cmd: list[str], cwd: Path, log: Path, commit: str) -> int:
    """Run cmd, writing the log with '# command:', '# commit:' and '# exit:' lines."""
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("AI2II_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with open(log, "w", encoding="utf-8") as f:
        f.write(f"# command: {shlex.join(cmd)}\n# commit: {commit}\n")
        f.flush()
        try:
            rc, _, _ = run_process_with_group_timeout(cmd, cwd, 600, env, f)
        except subprocess.TimeoutExpired:
            f.write("\nTEST TIMEOUT\n")
            rc = 124
        f.write(f"\n# exit: {rc}\n")
    return rc


def _run_in_tree(
    rev: str,
    cmd: list[str],
    log: Path,
    overlay: tuple[str, str] | None = None,
    patch: str | None = None,
) -> int:
    """Run cmd in a throw-away checkout of rev (optionally with files from another
    commit overlaid, or a mutant patch applied); log it; commit the log. Returns the exit code."""
    label = rev
    with _temp_tree(rev) as tmp:
        rc: int | None = None
        try:
            if overlay:
                _git("checkout", "-q", overlay[0], "--", overlay[1], cwd=tmp)
            if patch:
                label = f"{rev} + mutant:{Path(patch).stem}"
                res = subprocess.run(
                    ["git", "apply", patch],
                    cwd=tmp,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode != 0:
                    log.parent.mkdir(parents=True, exist_ok=True)
                    log.write_text(
                        f"# command: git apply {patch}\n# commit: {label}\n{res.stderr}\n# exit: 126\n",
                        encoding="utf-8",
                    )
                    rc = 126
        except Refused as exc:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(
                f"# command: overlay\n# commit: {rev}\n{exc}\n# exit: 128\n",
                encoding="utf-8",
            )
            rc = 128
        if rc is None:
            rc = _run_logged(cmd, tmp, log, label)
    commit_paths([log], f"orchestrator: run log {_rel(log)}")
    return rc


def _run_dir(milestone: str, n: int, commit: str) -> Path:
    return RUNS_DIR / milestone / _nn(n) / commit[:12]


def _acceptance_cmd(paths: list[str]) -> list[str]:
    template = (
        load_workflow()
        .get("commands", {})
        .get("acceptance", "python3 -m pytest -q -p no:cacheprovider {paths}")
    )
    return _build_test_command(template, paths)


def _builder_cmd() -> list[str]:
    template = (
        load_workflow()
        .get("commands", {})
        .get("builder_tests", "python3 -m pytest -q -p no:cacheprovider tests")
    )
    return _build_test_command(template)


def _branch_head(branch: str) -> str:
    return _git("rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}").strip()


# --- read-only commands ---


def _summary(milestone: str) -> dict[str, Any]:
    state = load_state(milestone)
    spec = load_spec(milestone)
    return {
        "id": milestone,
        "title": spec.get("title", ""),
        "status": state["status"],
        "attempt": state["attempt"],
        "criteria_version": state["criteria_version"],
        "spec_hash": spec_hash(milestone),
        "depends_on": list(spec.get("depends_on") or []),
        "attempts": state["attempts"],
        "escalations": state["escalations"],
    }


def cmd_status(args: Any) -> int:
    rows = [_summary(m) for m in _milestone_ids()]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print("AI2II Orchestrator Status")
    print("=" * 50)
    for r in rows:
        cv = (r["criteria_version"] or "-")[:12]
        print(
            f"{r['id']}  {r['status']:<10} attempt {r['attempt']}  criteria {cv}  {r['title']}"
        )
    return 0


def cmd_show(args: Any) -> int:
    milestone = args.milestone
    state = _require_milestone(milestone)
    spec = load_spec(milestone)
    digest = spec_hash(milestone)
    if args.json:
        print(json.dumps({"spec": spec, "state": state, "spec_hash": digest}, indent=2))
        return 0
    print(f"Milestone: {milestone} — {spec.get('title', '')}")
    print(f"Status: {state['status']}")
    print(f"Attempt: {state['attempt']}")
    print(f"spec_hash: {digest[:12]} ({digest})")
    cv = state.get("criteria_version")
    print(f"criteria_version: {cv[:12] if cv else 'none'}")
    print(f"Depends On: {', '.join(spec.get('depends_on') or []) or 'None'}")
    print("\nSpecification:")
    print(yaml.safe_dump(spec, sort_keys=False).rstrip())
    return 0


# --- automatic transitions, invalidation ---


def _to_draft(milestone: str, state: dict[str, Any], note: str) -> None:
    _set_status(state, "DRAFT", note)
    state["criteria_version"] = None
    state.pop("reviewed_spec_hash", None)
    save_state(milestone, state)


def _cascade_stale(root: str) -> None:
    """Dependents of a STALE/DRAFT milestone that were verified or complete become STALE."""
    queue = [root]
    while queue:
        cur = queue.pop(0)
        for mid in _milestone_ids():
            if cur not in (load_spec(mid).get("depends_on") or []):
                continue
            st = load_state(mid)
            if st["status"] in ("COMPLETE", "VERIFIED"):
                _set_status(st, "STALE", f"dependency {cur} is no longer COMPLETE")
                save_state(mid, st)
                print(f"{mid}: -> STALE (dependency {cur})")
                queue.append(mid)


def cmd_refresh(args: Any) -> int:
    changed = 0
    for m in _milestone_ids():
        st = load_state(m)
        status = st["status"]
        digest = spec_hash(m)
        spec_changed = (
            status == "REVIEWED" and st.get("reviewed_spec_hash") not in (None, digest)
        ) or (
            status not in ("DRAFT", "REVIEWED") and st.get("criteria_version") != digest
        )
        if spec_changed:
            _to_draft(m, st, "spec.yaml changed after review/approval")
            print(f"{m}: {status} -> DRAFT (spec changed)")
            changed += 1
            _cascade_stale(m)
        elif status == "APPROVED" and all(
            load_state(d)["status"] == "COMPLETE"
            for d in (load_spec(m).get("depends_on") or [])
        ):
            _set_status(st, "READY", "every dependency is COMPLETE")
            save_state(m, st)
            print(f"{m}: APPROVED -> READY")
            changed += 1
    for m in _milestone_ids():
        if load_state(m)["status"] == "STALE":
            _cascade_stale(m)
    print(f"refresh: {changed} transition(s)")
    return 0


def cmd_invalidate(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    if not args.reason.strip():
        raise Refused("--reason must not be empty")
    if args.to == "STALE":
        _require_status(st, m, "COMPLETE", "VERIFIED")
        _set_status(st, "STALE", args.reason)
        save_state(m, st)
    else:
        if st["status"] == "DRAFT":
            raise Refused(f"{m} is already DRAFT")
        _to_draft(m, st, args.reason)
    print(f"{m}: -> {args.to}")
    _cascade_stale(m)
    return 0


def cmd_unblock(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    _require_status(st, m, "BLOCKED")
    if not args.note.strip():
        raise Refused("--note must not be empty")
    _require_current_spec(m, st)
    _set_status(st, "READY", f"unblocked: {args.note}")
    save_state(m, st)
    print(f"{m}: BLOCKED -> READY")
    return 0


# --- gates: review, approve ---


def cmd_review(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    _require_status(st, m, "DRAFT")
    digest = spec_hash(m)
    text = _committed_text(args.file, "reviews")
    if not _names(text, m):
        raise Refused(f"{args.file} does not name {m}")
    if digest[:12] not in text:
        raise Refused(f"{args.file} does not name spec hash {digest[:12]}")
    last = [ln.strip() for ln in text.splitlines() if ln.strip()][-1:]
    if last != ["Outcome: APPROVED"]:
        raise Refused(f"{args.file} does not end with 'Outcome: APPROVED'")
    if not load_spec(m).get("acceptance"):
        raise Refused(f"{m} has no acceptance criteria")
    st["reviewed_spec_hash"] = digest
    _set_status(st, "REVIEWED", f"reviewed by {args.file}")
    save_state(m, st)
    print(f"{m}: DRAFT -> REVIEWED")
    return 0


def cmd_approve(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    _require_status(st, m, "REVIEWED")
    digest = spec_hash(m)
    if st.get("reviewed_spec_hash") not in (None, digest):
        raise Refused("spec.yaml changed after review (run refresh)")
    _check_approval(args.file, ["G2", m, digest[:12]])
    st["criteria_version"] = digest
    _set_status(st, "APPROVED", f"G2 {args.file}; criteria_version {digest[:12]}")
    save_state(m, st)
    print(f"{m}: REVIEWED -> APPROVED (criteria_version {digest[:12]})")
    return 0


def cmd_approve_gate(args: Any) -> int:
    """Human gate sign-off file (G1-G4). It must still be committed before use."""
    gate, target = args.gate, args.target
    note = args.note or "Approved by human"
    if gate in ("G3", "G4"):
        if not re.fullmatch(r"[Ee]?\d+", target):
            raise Refused(
                f"{gate} target must be an escalation id like E012, got '{target}'"
            )
        target = f"E{int(target.lstrip('Ee')):03d}"
    elif gate == "G2":
        if not (MILESTONES_DIR / target / "spec.yaml").is_file():
            raise Refused(f"unknown milestone {target}")
    elif not NAME_RE.match(target):
        raise Refused(f"invalid target {target}")
    lines = [f"# {gate} Approval for {target}", "", f"**Target:** {target}"]
    if gate == "G2":
        lines.append(f"**Spec hash:** {spec_hash(target)[:12]}")
    lines += [
        f"**Note:** {note}",
        "",
        "**Human Decision:** APPROVED",
        f"**Date:** {_utc_now()}",
        "",
    ]
    APPROVALS_DIR.mkdir(parents=True, exist_ok=True)
    out = APPROVALS_DIR / f"{gate}-{target}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Recorded human {gate} approval in {_rel(out)} (commit it before use)")
    return 0


# --- build ---


def cmd_start_build(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    _require_status(st, m, "READY", "REWORK")
    _require_current_spec(m, st)
    for dep in load_spec(m).get("depends_on") or []:
        dep_status = load_state(dep)["status"]
        if dep_status != "COMPLETE":
            raise Refused(f"dependency {dep} is {dep_status}, not COMPLETE")
    n = int(st["attempt"]) + 1
    if n > _max_attempts(st):
        raise Refused(f"max_attempts reached for {m}; needs a G4 resolution")
    prev = st["attempts"][-1] if st["attempts"] else None
    if prev and prev.get("verify_branch"):
        base = _branch_head(
            prev["verify_branch"]
        )  # rework keeps code and acceptance tests
    else:
        base = _git("rev-parse", "HEAD").strip()
    branch, rel = f"m/{m}/a{_nn(n)}-build", f".worktrees/{m}-a{_nn(n)}-build"
    _add_worktree(branch, rel, base)
    st["attempt"] = n
    st["attempts"].append(
        {
            "n": n,
            "base": base,
            "branch": branch,
            "worktree": rel,
            "builder": {
                "agent": args.agent,
                "family": args.family,
                "model": args.model,
                "session": args.session,
            },
            "built": None,
            "verify_branch": None,
            "verify_worktree": None,
            "verifier": None,
            "verdict": None,
        }
    )
    _set_status(st, "BUILDING", f"attempt {_nn(n)} started by {args.agent}")
    save_state(m, st)
    print(f"{m}: -> BUILDING attempt {_nn(n)} in {rel} (base {base[:12]})")
    return 0


def cmd_finish_build(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    _require_status(st, m, "BUILDING")
    _require_current_spec(m, st)
    a = _cur(st)
    n, wt = a["n"], _repo_root() / a["worktree"]
    if not wt.is_dir():
        raise Refused(f"build worktree {a['worktree']} is missing")
    if _git("status", "--porcelain", cwd=wt).strip():
        raise Refused("build worktree is not clean")
    head = _git("rev-parse", "HEAD", cwd=wt).strip()
    build_md = f"milestones/{m}/attempts/{_nn(n)}/build.md"
    if not _git_ok("cat-file", "-e", f"HEAD:{build_md}", cwd=wt):
        raise Refused(f"{build_md} is not committed")
    _check_range_ownership("builder", m, n, wt, a["base"], head)
    log = _run_dir(m, n, head) / "build.log"
    rc = _run_in_tree(head, _builder_cmd(), log)
    if rc != 0:
        raise Refused(f"builder tests failed (exit {rc}, see {_rel(log)})")
    a["built"] = head
    _set_status(st, "BUILT", f"built at {head[:12]} (build.log)")
    save_state(m, st)
    print(f"{m}: BUILDING -> BUILT at {head[:12]}")
    return 0


# --- verify ---


def cmd_start_verify(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    _require_status(st, m, "BUILT")
    _require_current_spec(m, st)
    a = _cur(st)
    if args.session == a["builder"].get("session"):
        raise Refused("verifier session must differ from the builder session (I1)")
    n = a["n"]
    branch, rel = f"m/{m}/a{_nn(n)}-verify", f".worktrees/{m}-a{_nn(n)}-verify"
    _add_worktree(branch, rel, a["built"])
    a["verify_branch"], a["verify_worktree"] = branch, rel
    a["verifier"] = {
        "agent": args.agent,
        "family": args.family,
        "model": args.model,
        "session": args.session,
    }
    note = f"attempt {_nn(n)} verification started by {args.agent}"
    if args.family == a["builder"].get("family"):
        note += " (same family as builder: SHOULD differ, 24.15)"
    _set_status(st, "VERIFYING", note)
    save_state(m, st)
    print(f"{m}: BUILT -> VERIFYING in {rel}")
    return 0


def cmd_run_tests(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    _require_status(st, m, "VERIFYING")
    a = _cur(st)
    if not NAME_RE.match(args.name):
        raise Refused("--name must match [A-Za-z0-9_.-]+")
    paths = _test_paths(m, args.paths)
    vhead = _branch_head(a["verify_branch"])
    at = args.at
    overlay = patch = None
    rev = vhead
    if at == "base":
        rev, overlay = st["attempts"][0]["base"], (vhead, "acceptance")
    elif at.startswith("mutant:"):
        if not NAME_RE.match(at[7:]):
            raise Refused("invalid mutant name")
        patch = f"acceptance/{m}/mutants/{at[7:]}.patch"
    elif at != "built":
        raise Refused("--at must be built, base or mutant:<name>")
    log = _run_dir(m, a["n"], a["built"]) / f"{args.name}.log"
    rc = _run_in_tree(rev, _acceptance_cmd(paths), log, overlay, patch)
    print(f"Test run {args.name} at {at}: exit {rc}\nLog: {_rel(log)}")
    return 0 if rc == 0 else 1


def _test_paths(m: str, paths: list[str] | None) -> list[str]:
    paths = paths or [f"acceptance/{m}"]
    for p in paths:
        file_part = Path(p.split("::")[0])
        if (
            file_part.is_absolute()
            or ".." in file_part.parts
            or file_part.parts[:2] != ("acceptance", m)
        ):
            raise Refused(f"test path {p} must be under acceptance/{m}/")
    return paths


def _validate_verdict(
    m: str, st: dict[str, Any], a: dict[str, Any], v: Any
) -> list[str]:
    """Schema and provenance checks on verification.yaml (DESIGN.md 24.10)."""
    if not isinstance(v, dict):
        return ["verification.yaml is not a mapping"]
    errors: list[str] = []
    n = a["n"]
    if v.get("milestone") != m:
        errors.append(f"milestone is {v.get('milestone')}, expected {m}")
    if v.get("attempt") != n:
        errors.append(f"attempt is {v.get('attempt')}, expected {n}")
    commit = str(v.get("commit") or "")
    if len(commit) < 7 or not str(a["built"]).startswith(commit):
        errors.append(
            f"commit {commit or '(missing)'} does not match built commit {str(a['built'])[:12]}"
        )
    cv = str(v.get("criteria_version") or "")
    if len(cv) < 12 or not str(st.get("criteria_version") or "").startswith(cv):
        errors.append("criteria_version does not match the state")
    verdict = v.get("verdict")
    if verdict not in ("PASS", "FAIL", "BLOCKED", "INVALID"):
        errors.append(f"verdict {verdict!r} is not PASS|FAIL|BLOCKED|INVALID")
    if not isinstance(v.get("verifier"), dict):
        errors.append("verifier must be a mapping")
    acc = v.get("acceptance")
    val = v.get("validity")
    if not isinstance(acc, dict):
        errors.append("acceptance must be a mapping")
        acc = {}
    if val is None:
        val = {}
    if not isinstance(val, dict):
        errors.append("validity must be a mapping")
        val = {}
    for crit in load_spec(m).get("acceptance") or {}:
        entry = acc.get(crit)
        if not isinstance(entry, dict) or not entry.get("result"):
            errors.append(f"criterion {crit} is missing from acceptance")
        elif verdict == "PASS" and entry.get("result") != "PASS":
            errors.append(f"verdict is PASS but {crit} is {entry.get('result')}")
    for crit, entry in acc.items():
        if not isinstance(entry, dict):
            continue
        run = entry.get("run")
        if (entry.get("result") == "PASS" or run) and not _is_run_log(m, run):
            errors.append(
                f"acceptance {crit}: run log {run!r} does not exist under runs/{m}/"
            )
        if entry.get("result") == "PASS":
            ventry = val.get(crit)
            if not isinstance(ventry, dict):
                errors.append(f"PASS criterion {crit} has no validity entry")
                continue
            fails_on = str(ventry.get("fails_on") or "")
            if fails_on != "base" and not (
                fails_on.startswith("mutant:") and NAME_RE.match(fails_on[7:] or "!")
            ):
                errors.append(
                    f"validity {crit}: fails_on {fails_on!r} must be base or mutant:<name>"
                )
            if not _is_run_log(m, ventry.get("run")):
                errors.append(
                    f"validity {crit}: run log {ventry.get('run')!r} does not exist under runs/{m}/"
                )
            tests = entry.get("tests")
            if not isinstance(tests, list) or not tests:
                errors.append(f"acceptance {crit}: tests must be a non-empty list")
            else:
                try:
                    _test_paths(m, [str(t) for t in tests])
                except Refused as exc:
                    errors.append(f"acceptance {crit}: {exc}")
    return errors


def _is_run_log(m: str, rel: Any) -> bool:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        return False
    runs = (RUNS_DIR / m).resolve()
    target = (_repo_root() / rel).resolve()
    return target.is_file() and runs in target.parents


def _next_escalation_id() -> str:
    nums = [
        int(mo.group(1))
        for p in ESCALATIONS_DIR.glob("E*.md")
        if (mo := re.fullmatch(r"E(\d+)\.md", p.name))
    ]
    return f"E{max(nums, default=0) + 1:03d}"


def _open_escalation(
    m: str,
    st: dict[str, Any],
    a: dict[str, Any],
    reason: str,
    gate: str,
    verdict_text: str,
) -> Path:
    eid = _next_escalation_id()
    build_md = f"milestones/{m}/attempts/{_nn(a['n'])}/build.md"
    build = _git("show", f"{a['branch']}:{build_md}", check=False)
    body = f"""# Escalation {eid}

**Milestone:** {m}
**Attempt:** {a["n"]}
**Reason:** {reason}
**Gate:** {gate}
**Opened:** {_utc_now()}

## Spec
```yaml
{(MILESTONES_DIR / m / "spec.yaml").read_text(encoding="utf-8").rstrip()}
```

## Last build report
{build.strip() or "not available"}

## Last verification report
```yaml
{verdict_text.rstrip()}
```

## Resolution
Classification: pending
Outcome: pending
"""
    ESCALATIONS_DIR.mkdir(parents=True, exist_ok=True)
    out = ESCALATIONS_DIR / f"{eid}.md"
    out.write_text(body, encoding="utf-8")
    st["escalations"].append(
        {
            "id": eid,
            "reason": reason,
            "gate": gate,
            "classification": None,
            "outcome": None,
        }
    )
    return out


def cmd_finish_verify(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    _require_status(st, m, "VERIFYING")
    _require_current_spec(m, st)
    a = _cur(st)
    n, wt = a["n"], _repo_root() / a["verify_worktree"]
    if not wt.is_dir():
        raise Refused(f"verify worktree {a['verify_worktree']} is missing")
    if _git("status", "--porcelain", cwd=wt).strip():
        raise Refused("verify worktree is not clean")
    head = _git("rev-parse", "HEAD", cwd=wt).strip()
    _check_range_ownership("verifier", m, n, wt, a["built"], head)
    vpath = f"milestones/{m}/attempts/{_nn(n)}/verification.yaml"
    text = _git("show", f"HEAD:{vpath}", cwd=wt, check=False)
    if not text:
        raise Refused(f"{vpath} is not committed")
    v = yaml.safe_load(text)
    errors = _validate_verdict(m, st, a, v)
    if errors:
        raise Refused("verification.yaml rejected:\n  - " + "\n  - ".join(errors))
    verdict = v["verdict"]
    extra: list[Path] = []
    if verdict == "PASS":
        rundir = _run_dir(m, n, a["built"])
        failures = _confirm_pass(m, st, a, v, head, rundir)
        if failures:
            raise Refused("PASS not confirmed:\n  - " + "\n  - ".join(failures))
        a["verdict"] = "PASS"
        _set_status(st, "VERIFIED", f"PASS confirmed at {head[:12]}")
    elif verdict == "FAIL":
        a["verdict"] = "FAIL"
        if n < _max_attempts(st):
            _set_status(st, "REWORK", f"FAIL on attempt {_nn(n)}")
        else:
            extra.append(_open_escalation(m, st, a, "max_attempts", "G4", text))
            _set_status(
                st, "ESCALATED", f"FAIL at max_attempts; {st['escalations'][-1]['id']}"
            )
    elif verdict == "BLOCKED":
        a["verdict"] = "BLOCKED"
        _set_status(st, "BLOCKED", "verification could not run")
    else:
        a["verdict"] = "INVALID"
        extra.append(_open_escalation(m, st, a, "INVALID", "G3", text))
        _set_status(st, "ESCALATED", f"INVALID verdict; {st['escalations'][-1]['id']}")
    save_state(m, st, extra=extra)
    print(f"{m}: VERIFYING -> {st['status']}")
    return 0


def _confirm_pass(
    m: str,
    st: dict[str, Any],
    a: dict[str, Any],
    v: dict[str, Any],
    head: str,
    rundir: Path,
) -> list[str]:
    """The orchestrator's own runs behind a PASS (DESIGN.md 24.7, 24.9)."""
    failures: list[str] = []
    rc = _run_in_tree(
        head, _acceptance_cmd([f"acceptance/{m}"]), rundir / "final-acc.log"
    )
    if rc != 0:
        failures.append(
            f"acceptance/{m} fails at {head[:12]} (exit {rc}, see {_rel(rundir / 'final-acc.log')})"
        )
    base = st["attempts"][0]["base"]
    for crit, entry in v["acceptance"].items():
        if entry.get("result") != "PASS":
            continue
        fails_on = v["validity"][crit]["fails_on"]
        cmd = _acceptance_cmd([str(t) for t in entry["tests"]])
        log = rundir / f"final-validity-{crit}.log"
        missing = [
            str(x)
            for x in entry["tests"]
            if not _git_ok("cat-file", "-e", f"{head}:{str(x).split('::')[0]}")
        ]
        if missing:
            failures.append(f"{crit}: test file(s) not committed: {', '.join(missing)}")
            continue
        if fails_on == "base":
            vrc = _run_in_tree(base, cmd, log, overlay=(head, "acceptance"))
            # a failed test, or pytest unable to collect it because the feature is absent
            expected = (1, 2, 4)
        else:
            vrc = _run_in_tree(
                head, cmd, log, patch=f"acceptance/{m}/mutants/{fails_on[7:]}.patch"
            )
            expected = (1,)
        if vrc not in expected:
            failures.append(
                f"{crit}: validity case {fails_on} did not fail as a test failure (exit {vrc}, see {_rel(log)})"
            )
    return failures


# --- integration ---


def cmd_integrate(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    _require_status(st, m, "VERIFIED")
    _require_current_spec(m, st)
    if _git("status", "--porcelain", "--untracked-files=no").strip():
        raise Refused("main worktree has uncommitted changes")
    a = _cur(st)
    n = a["n"]
    pre = _git("rev-parse", "HEAD").strip()
    res = subprocess.run(
        [
            "git",
            "-c",
            f"user.name={ORCH_NAME}",
            "-c",
            f"user.email={ORCH_EMAIL}",
            "-c",
            "commit.gpgsign=false",
            "merge",
            "--no-ff",
            "--no-verify",
            "-q",
            "-m",
            f"orchestrator: integrate {m} attempt {_nn(n)}",
            a["verify_branch"],
        ],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    extra: list[Path] = []
    problem = ""
    if res.returncode != 0:
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=_repo_root(),
            capture_output=True,
            check=False,
        )
        problem = f"merge failed: {(res.stderr or res.stdout).strip()[:300]}"
    else:
        merge = _git("rev-parse", "HEAD").strip()
        suites = [m] + [
            x
            for x in _milestone_ids()
            if x != m and load_state(x)["status"] == "COMPLETE"
        ]
        for s in suites:
            sn = n if s == m else max(1, int(load_state(s).get("attempt") or 1))
            log = _run_dir(s, sn, merge) / f"integrate-{m}.log"
            rc = _run_in_tree_nocommit(merge, _acceptance_cmd([f"acceptance/{s}"]), log)
            extra.append(log)
            if rc != 0:
                problem = f"acceptance/{s} fails on merge commit {merge[:12]} (exit {rc}, see {_rel(log)})"
                break
    if problem:
        _git("reset", "--hard", "-q", pre)
        _set_status(st, "REWORK", f"integration failed: {problem}")
        save_state(m, st, extra=extra)
        raise Refused(f"integration failed, main restored to {pre[:12]}: {problem}")
    _set_status(st, "COMPLETE", f"merged {a['verify_branch']}; suites passed")
    save_state(m, st, extra=extra)
    print(f"{m}: VERIFIED -> COMPLETE")
    return 0


def _run_in_tree_nocommit(rev: str, cmd: list[str], log: Path) -> int:
    """Like _run_in_tree, but the log is committed with the state change that follows."""
    with _temp_tree(rev) as tmp:
        return _run_logged(cmd, tmp, log, rev)


# --- escalation resolution ---


def cmd_resolve(args: Any) -> int:
    m = args.milestone
    st = _require_milestone(m)
    _require_status(st, m, "ESCALATED")
    if not args.note.strip():
        raise Refused("--note must not be empty")
    esc = next((e for e in reversed(st["escalations"]) if not e.get("outcome")), None)
    if esc is None:
        raise Refused(f"{m} has no open escalation")
    gates = {esc["gate"]}
    if args.classification in ("MILESTONE_SPEC", "ARCHITECTURE"):
        gates.add("G3")
    limit = int(load_workflow().get("limits", {}).get("max_escalations", 2))
    if len(st["escalations"]) >= limit:
        gates.add("G4")
    if not args.approval:
        raise Refused(
            f"resolving {esc['id']} needs a committed approval for {', '.join(sorted(gates))} (--approval)"
        )
    _check_approval(args.approval, [esc["id"], *sorted(gates)])
    esc["classification"], esc["outcome"] = args.classification, args.outcome
    if args.outcome == "REWORK" and esc["reason"] == "max_attempts":
        st["extra_attempts"] = int(st.get("extra_attempts") or 0) + 1
    if args.outcome == "DRAFT":
        _to_draft_inplace(st)
    esc_file = ESCALATIONS_DIR / f"{esc['id']}.md"
    extra: list[Path] = []
    if esc_file.exists():
        with open(esc_file, "a", encoding="utf-8") as f:
            f.write(
                f"\n## Resolution (recorded {_utc_now()})\n\nClassification: {args.classification}\n"
                f"Outcome: {args.outcome}\nApproval: {args.approval}\nNote: {args.note}\n"
            )
        extra.append(esc_file)
    _set_status(
        st, args.outcome, f"{esc['id']} resolved: {args.classification}; {args.note}"
    )
    save_state(m, st, extra=extra)
    print(f"{m}: ESCALATED -> {args.outcome}")
    return 0


def _to_draft_inplace(st: dict[str, Any]) -> None:
    st["criteria_version"] = None
    st.pop("reviewed_spec_hash", None)


# --- init, ownership check, validate ---


def cmd_init_milestone(args: Any) -> int:
    milestone = args.milestone.upper()
    if not re.match(r"^M\d+$", milestone):
        raise Refused(f"invalid milestone id {milestone}")
    mdir = MILESTONES_DIR / milestone
    if (mdir / "spec.yaml").exists():
        raise Refused(f"{milestone} already exists")
    (mdir / "attempts").mkdir(parents=True, exist_ok=True)
    spec = {
        "id": milestone,
        "title": f"{milestone} - Initialized milestone",
        "objective": "Specify milestone objective",
        "depends_on": [],
        "inputs": [],
        "deliverables": [],
        "acceptance": {"AC1": "Specify falsifiable acceptance criterion"},
        "out_of_scope": [],
        "size_hint": "M",
    }
    (mdir / "spec.yaml").write_text(
        yaml.safe_dump(spec, sort_keys=False), encoding="utf-8"
    )
    save_state(milestone, load_state(milestone))
    print(f"Initialized {milestone}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return _run_command(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orch", description="AI2II Orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status / show
    p = subparsers.add_parser("status", help="Show project status")
    p.add_argument("--json", action="store_true", help="Output JSON status")
    p = subparsers.add_parser("show", help="Show milestone spec, state, and spec hash")
    p.add_argument("milestone", help="Milestone ID (e.g., M01)")
    p.add_argument("--json", action="store_true")

    p = subparsers.add_parser("init-milestone", help="Initialize a milestone")
    p.add_argument("milestone", help="Milestone ID (e.g., M01)")

    p = subparsers.add_parser("check-ownership", help="Check path ownership")
    p.add_argument("role", choices=["builder", "verifier"])
    p.add_argument("milestone")
    p.add_argument("attempt", type=int)
    p.add_argument("--base", default="HEAD~1", help="Base commit for diff")
    p.add_argument("--files", nargs="+", help="Files to check (instead of git diff)")

    # lifecycle (DESIGN.md 24.7)
    subparsers.add_parser("refresh", help="Apply automatic transitions")
    p = subparsers.add_parser("review", help="DRAFT -> REVIEWED")
    p.add_argument("milestone")
    p.add_argument("file", help="committed reviews/ file")
    p = subparsers.add_parser("approve", help="REVIEWED -> APPROVED (gate G2)")
    p.add_argument("milestone")
    p.add_argument("file", help="committed approvals/ file")
    for name, helptext in (
        ("start-build", "READY/REWORK -> BUILDING"),
        ("start-verify", "BUILT -> VERIFYING"),
    ):
        p = subparsers.add_parser(name, help=helptext)
        p.add_argument("milestone")
        p.add_argument("--agent", required=True)
        p.add_argument("--family", required=True)
        p.add_argument("--model", default="")
        p.add_argument("--session", required=True)
    p = subparsers.add_parser("finish-build", help="BUILDING -> BUILT")
    p.add_argument("milestone")
    p = subparsers.add_parser("finish-verify", help="Apply the verifier verdict")
    p.add_argument("milestone")
    p = subparsers.add_parser("integrate", help="VERIFIED -> COMPLETE (merge + suites)")
    p.add_argument("milestone")
    p = subparsers.add_parser("run-tests", help="Run acceptance tests with a log")
    p.add_argument("milestone")
    p.add_argument("--name", required=True, help="log name, e.g. acc, validity-AC1")
    p.add_argument("--at", default="built", help="built | base | mutant:<name>")
    p.add_argument("--paths", nargs="+", help="test paths under acceptance/<id>")
    p = subparsers.add_parser(
        "invalidate", help="COMPLETE/VERIFIED -> STALE, or -> DRAFT"
    )
    p.add_argument("milestone")
    p.add_argument("--to", required=True, choices=["STALE", "DRAFT"])
    p.add_argument("--reason", required=True)
    p = subparsers.add_parser("unblock", help="BLOCKED -> READY")
    p.add_argument("milestone")
    p.add_argument("--note", required=True)
    p = subparsers.add_parser(
        "resolve", help="Resolve an escalation (ESCALATED -> ...)"
    )
    p.add_argument("milestone")
    p.add_argument("--outcome", required=True, choices=ESCALATION_OUTCOMES)
    p.add_argument(
        "--classification", required=True, choices=ESCALATION_CLASSIFICATIONS
    )
    p.add_argument("--note", required=True)
    p.add_argument("--approval", help="committed approvals/ file (G3/G4)")

    # dispatch
    p = subparsers.add_parser("dispatch", help="Dispatch an agent for a role")
    p.add_argument("milestone")
    p.add_argument("role", choices=["builder", "verifier"])

    # approve-gate
    p = subparsers.add_parser(
        "approve-gate", help="Record explicit human gate approval (G1, G2, G3, G4)"
    )
    p.add_argument("gate", choices=["G1", "G2", "G3", "G4"])
    p.add_argument("target", help="Escalation ID (e.g., E001) or milestone ID")
    p.add_argument("--note", default="Approved by human", help="Approval note")

    # validate, seal, reseal, goldfish, context, doctor (ported from agentwork)
    subparsers.add_parser("validate", help="Validate milestone DAG and specs")
    subparsers.add_parser(
        "seal", help="Compute topological seal and write harness-manifest.json"
    )
    subparsers.add_parser(
        "reseal", help="Re-seal updated DAG into a new manifest generation"
    )

    p_gf = subparsers.add_parser(
        "goldfish", help="Run static specification & boundary audit"
    )
    p_gf.add_argument("--json", action="store_true")

    p_ctx = subparsers.add_parser(
        "context", help="Compile milestone context and 1-hop AST symbol signatures"
    )
    p_ctx.add_argument("milestone")
    p_ctx.add_argument("--json", action="store_true")

    subparsers.add_parser("doctor", help="Run system and sandbox diagnostics")

    # models
    p = subparsers.add_parser("models", help="Manage model configurations")
    p.add_argument(
        "action",
        choices=["list", "add", "remove", "test", "benchmark"],
        help="Action to perform",
    )
    p.add_argument("--name", help="Model name")
    p.add_argument("--provider", help="Provider (anthropic, openai, local, etc.)")
    p.add_argument("--model", help="Model ID (e.g., claude-opus, gpt-4o, qwen2.5)")
    p.add_argument(
        "--tier", choices=["high", "standard"], help="Tier for role assignment"
    )
    p.add_argument(
        "--role",
        choices=["architect", "reviewer", "builder", "verifier"],
        help="Role to assign",
    )
    p.add_argument("--command", help="Command template with {prompt_file}")

    # improve
    p = subparsers.add_parser(
        "improve", help="Capture orchestrator improvement / best practice"
    )
    p.add_argument(
        "type",
        choices=["pattern", "tool", "prompt", "workflow", "metric"],
        help="Improvement type",
    )
    p.add_argument("description", help="Description of the improvement")
    p.add_argument("--context", help="Context (milestone, role, situation)")
    p.add_argument("--author", help="Author/model that discovered this")
    p.add_argument("--tags", nargs="+", help="Tags for categorization")

    return parser


def _run_command(args: Any) -> int:

    handlers = {
        "status": cmd_status,
        "show": cmd_show,
        "init-milestone": governed(cmd_init_milestone),
        "check-ownership": cmd_check_ownership,
        "refresh": governed(cmd_refresh),
        "review": governed(cmd_review),
        "approve": governed(cmd_approve),
        "start-build": governed(cmd_start_build),
        "finish-build": governed(cmd_finish_build),
        "start-verify": governed(cmd_start_verify),
        "run-tests": governed(cmd_run_tests),
        "finish-verify": governed(cmd_finish_verify),
        "integrate": governed(cmd_integrate),
        "invalidate": governed(cmd_invalidate),
        "unblock": governed(cmd_unblock),
        "resolve": governed(cmd_resolve),
        "dispatch": cmd_dispatch,
        "approve-gate": cmd_approve_gate,
        "validate": cmd_validate,
        "seal": cmd_seal,
        "reseal": cmd_seal,
        "goldfish": cmd_goldfish,
        "context": cmd_context,
        "doctor": cmd_doctor,
        "models": cmd_models,
        "improve": cmd_improve,
    }

    try:
        return handlers[args.command](args)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except (OSError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
