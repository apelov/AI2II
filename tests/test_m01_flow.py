"""M01 lifecycle tests. Each runs the orchestrator as a subprocess in a temporary repository."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

_spec = importlib.util.spec_from_file_location(
    "flow_repo", Path(__file__).resolve().parent / "flow_repo.py"
)
_flow = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("flow_repo", _flow)
_spec.loader.exec_module(_flow)
ACC_TEST, REAL_ROOT, Repo, with_repo = (
    _flow.ACC_TEST,
    _flow.REAL_ROOT,
    _flow.Repo,
    _flow.with_repo,
)


def authors(r: Repo, m: str) -> set[str]:
    return set(
        r.git("log", "--format=%an", "--", f"milestones/{m}/state.yaml").splitlines()
    )


def finish_verify_with(r: Repo, vwt, mutate) -> tuple[int, str]:
    doc = r.verification_doc()
    mutate(doc)
    r.write_verification(vwt, doc)
    rc, _, err = r.orch("finish-verify", "M01")
    return rc, err


# --- interface, status, show ---


@with_repo
def test_interface_commands_exist(repo: Repo) -> None:
    out = repo.ok("--help")
    for cmd in [
        "refresh",
        "review",
        "approve",
        "start-build",
        "finish-build",
        "start-verify",
        "run-tests",
        "finish-verify",
        "integrate",
        "invalidate",
        "unblock",
        "resolve",
        "status",
        "show",
    ]:
        assert cmd in out


@with_repo
def test_show_reports_sha256_of_spec_file(repo: Repo) -> None:
    data = json.loads(repo.ok("show", "M01", "--json"))
    expect = hashlib.sha256(
        (repo.root / "milestones/M01/spec.yaml").read_bytes()
    ).hexdigest()
    assert data["spec_hash"] == expect
    assert expect[:12] in repo.ok("show", "M01")
    rc, _, _ = repo.orch("show", "NOPE")
    assert rc == 1


@with_repo
def test_usage_error_is_exit_2(repo: Repo) -> None:
    assert repo.orch("start-build")[0] == 2


# --- AC4 preconditions / gates ---


@with_repo
def test_approve_needs_review_and_hash_bound_approval(repo: Repo) -> None:
    h = repo.spec_hash()[:12]
    (repo.root / "reviews").mkdir()
    (repo.root / "reviews/r.md").write_text(f"M01 {h}\nOutcome: CHANGES_REQUESTED\n")
    (repo.root / "approvals").mkdir()
    (repo.root / "approvals/stale.md").write_text(
        "G2 M01 000000000000\n**Human Decision:** APPROVED\n"
    )
    (repo.root / "approvals/ok.md").write_text(f"G2 M01 {h}\nDecision: APPROVED\n")
    repo.commit("files")
    # DRAFT -> REVIEWED needs an approving review naming the hash
    assert repo.orch("review", "M01", "reviews/r.md")[0] == 1
    assert repo.orch("review", "M01", "reviews/missing.md")[0] == 1
    assert repo.orch("review", "M01", "../etc/passwd")[0] == 1
    assert not (repo.root / "milestones/M01/state.yaml").exists()
    (repo.root / "reviews/r.md").write_text(f"M01 {h}\n\nOutcome: APPROVED\n")
    repo.commit("review ok")
    repo.ok("review", "M01", "reviews/r.md")
    assert repo.status() == "REVIEWED"
    before = repo.state_bytes()
    assert repo.orch("approve", "M01", "approvals/stale.md")[0] == 1  # wrong hash
    assert repo.orch("approve", "M01", "approvals/nope.md")[0] == 1
    assert repo.state_bytes() == before
    repo.ok("approve", "M01", "approvals/ok.md")
    assert repo.state()["criteria_version"] == repo.spec_hash()


@with_repo
def test_uncommitted_approval_is_refused(repo: Repo) -> None:
    h = repo.spec_hash()[:12]
    (repo.root / "reviews").mkdir()
    (repo.root / "reviews/r.md").write_text(f"M01 {h}\n\nOutcome: APPROVED\n")
    # not committed
    assert repo.orch("review", "M01", "reviews/r.md")[0] == 1


@with_repo
def test_preconditions_leave_state_unchanged(repo: Repo) -> None:
    repo.approve("M01")
    repo.approve("M02")
    before = {m: repo.state_bytes(m) for m in ("M01", "M02")}
    assert repo.status("M02") == "APPROVED"  # M01 not COMPLETE
    assert repo.orch("finish-verify", "M01")[0] == 1  # READY
    assert repo.orch("finish-build", "M01")[0] == 1  # READY
    assert (
        repo.orch(
            "start-verify", "M01", "--agent", "a", "--family", "f", "--session", "s"
        )[0]
        == 1
    )
    assert (
        repo.orch(
            "start-build", "M02", "--agent", "a", "--family", "f", "--session", "s"
        )[0]
        == 1
    )
    assert repo.orch("integrate", "M01")[0] == 1
    assert repo.orch("unblock", "M01", "--note", "n")[0] == 1
    assert {m: repo.state_bytes(m) for m in ("M01", "M02")} == before


@with_repo
def test_start_verify_refuses_builder_session(repo: Repo) -> None:
    repo.approve()
    repo.built()
    before = repo.state_bytes()
    rc, _, err = repo.orch(
        "start-verify", "M01", "--agent", "v", "--family", "f", "--session", "b1"
    )
    assert rc == 1 and "session" in err
    assert repo.state_bytes() == before


@with_repo
def test_approve_gate_fails_cleanly_on_bad_target(repo: Repo) -> None:
    rc, out, err = repo.orch("approve-gate", "G3", "not-a-number")
    assert rc == 1 and "Traceback" not in err + out
    assert repo.orch("approve-gate", "G4", "E7")[0] == 0
    assert (repo.root / "approvals/G4-E007.md").exists()


# --- AC1 / AC2 / AC3 build ---


@with_repo
def test_finish_build_rejects_protected_paths(repo: Repo) -> None:
    repo.approve()
    for bad in (
        "acceptance/M01/test_x.py",
        "milestones/M01/spec.yaml",
        "milestones/M01/state.yaml",
        "workflow.yaml",
        "orch",
    ):
        r = Repo()
        try:
            r.approve()
            wt = r.start_build()
            r.good_build(wt)
            (wt / bad).parent.mkdir(parents=True, exist_ok=True)
            (wt / bad).write_text("x\n")
            r.commit("sneaky", cwd=wt)
            rc, _, err = r.orch("finish-build", "M01")
            assert rc == 1 and bad in err, bad
            assert r.status() == "BUILDING"
        finally:
            r.cleanup()


@with_repo
def test_finish_build_rejects_dot_prefixed_protected_path(repo: Repo) -> None:
    repo.approve()
    wt = repo.start_build()
    repo.good_build(wt)
    (wt / ".git_hooks").mkdir()
    (wt / ".worktrees").mkdir()
    (wt / ".worktrees/x").write_text("x")
    repo.git("add", "-f", ".worktrees/x", cwd=wt)
    repo.git("commit", "-q", "-m", "dot", cwd=wt)
    rc, _, err = repo.orch("finish-build", "M01")
    assert rc == 1 and ".worktrees/x" in err


@with_repo
def test_finish_build_requires_clean_tree_and_build_md(repo: Repo) -> None:
    repo.approve()
    wt = repo.start_build()
    (wt / "src").mkdir(exist_ok=True)
    (wt / "src/m01.py").write_text("def double(x):\n    return x * 2\n")
    (wt / "tests").mkdir(exist_ok=True)
    repo.commit("no build.md", cwd=wt)
    rc, _, err = repo.orch("finish-build", "M01")
    assert rc == 1 and "build.md" in err
    repo.good_build(wt)
    (wt / "stray.txt").write_text("dirty")
    rc, _, err = repo.orch("finish-build", "M01")
    assert rc == 1 and "clean" in err
    assert repo.status() == "BUILDING"


@with_repo
def test_failing_builder_test_keeps_building_and_logs(repo: Repo) -> None:
    repo.approve()
    wt = repo.start_build()
    repo.good_build(wt)
    (wt / "src/m01.py").write_text("def double(x):\n    return x + 3\n")
    repo.commit("broken", cwd=wt)
    rc, _, _ = repo.orch("finish-build", "M01")
    assert rc == 1 and repo.status() == "BUILDING"
    logs = list((repo.root / "runs/M01/01").glob("*/build.log"))
    assert len(logs) == 1
    text = logs[0].read_text()
    assert text.startswith("# command: ") and "# commit: " in text
    assert "# exit: 1" in text
    assert repo.git("status", "--porcelain") == ""


@with_repo
def test_finish_build_succeeds_and_logs_success(repo: Repo) -> None:
    repo.approve()
    repo.built()
    st = repo.state()
    a = st["attempts"][0]
    assert st["status"] == "BUILT" and a["built"] == repo.git("rev-parse", a["branch"])
    log = repo.root / "runs/M01/01" / a["built"][:12] / "build.log"
    assert "# exit: 0" in log.read_text()
    assert repo.git("status", "--porcelain") == ""


# --- AC5 / AC6 verification ---


@with_repo
def test_full_lifecycle_to_complete(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    repo.write_verification(vwt, repo.verification_doc())
    repo.ok("finish-verify", "M01")
    assert repo.status() == "VERIFIED"
    pre = repo.git("rev-parse", "HEAD")
    repo.ok("integrate", "M01")
    assert repo.status() == "COMPLETE"
    assert (repo.root / "src/m01.py").exists()
    assert (repo.root / "acceptance/M01/test_m01.py").exists()
    assert repo.git("merge-base", "--is-ancestor", pre, "HEAD") == ""
    assert authors(repo, "M01") == {"orchestrator"}
    assert repo.git("status", "--porcelain") == ""
    # a fresh process reproduces the state
    rows = json.loads(repo.ok("status", "--json"))
    assert {r["id"]: r["status"] for r in rows}["M01"] == "COMPLETE"
    # dependent can now become READY and start building
    repo.approve("M02")
    assert repo.status("M02") == "READY"


BAD_VERDICTS = [
    (lambda d: d["acceptance"].pop("AC2"), "AC2"),
    (lambda d: d.update(commit="deadbeefdeadbeef"), "commit"),
    (lambda d: d.update(criteria_version="0" * 64), "criteria_version"),
    (
        lambda d: d["acceptance"]["AC1"].update(run="runs/M01/01/nope/acc.log"),
        "AC1",
    ),
    (lambda d: d["validity"].pop("AC1"), "validity"),
    (lambda d: d["validity"]["AC2"].update(run="runs/M01/01/nope/v.log"), "AC2"),
    (lambda d: d.update(verdict="MAYBE"), "verdict"),
    # last: it writes a file under attempts/02, which the verifier does not own
    (lambda d: d.update(attempt=2), "attempt"),
]


@with_repo
def test_finish_verify_rejects_bad_verdict_files(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    before = repo.state_bytes()
    for mutate, needle in BAD_VERDICTS:
        rc, err = finish_verify_with(repo, vwt, mutate)
        assert rc == 1 and needle in err, (needle, rc, err)
        assert repo.state_bytes() == before and repo.status() == "VERIFYING"


@with_repo
def test_pass_needs_validity_case_that_really_fails(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    # a validity case pointing at a mutant that does not break the cited test
    patch = vwt / "acceptance/M01/mutants/noop.patch"
    patch.write_text("")
    repo.commit("noop mutant", cwd=vwt)
    doc = repo.verification_doc()
    doc["validity"]["AC2"]["fails_on"] = "mutant:noop"
    repo.write_verification(vwt, doc)
    rc, _, err = repo.orch("finish-verify", "M01")
    assert rc == 1 and "AC2" in err
    assert repo.status() == "VERIFYING"


@with_repo
def test_pass_needs_acceptance_suite_to_pass(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    (vwt / "acceptance/M01/test_m01.py").write_text(
        ACC_TEST + "\n\ndef test_wrong():\n    assert False\n"
    )
    repo.commit("failing extra test", cwd=vwt)
    repo.write_verification(vwt, repo.verification_doc())
    rc, _, err = repo.orch("finish-verify", "M01")
    assert rc == 1 and "final-acc.log" in err
    assert repo.status() == "VERIFYING"


@with_repo
def test_verifier_cannot_touch_implementation(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    (vwt / "src/m01.py").write_text("def double(x):\n    return 4\n")
    repo.commit("fix the code", cwd=vwt)
    repo.write_verification(vwt, repo.verification_doc())
    rc, _, err = repo.orch("finish-verify", "M01")
    assert rc == 1 and "src/m01.py" in err


@with_repo
def test_run_tests_logs_and_validity_modes(repo: Repo) -> None:
    repo.approve()
    repo.verifying()
    a = repo.state()["attempts"][0]
    d = repo.root / "runs/M01/01" / a["built"][:12]
    assert "# exit: 0" in (d / "acc.log").read_text()
    assert "# exit: 1" in (d / "validity-AC2.log").read_text()
    assert "mutant:triple" in (d / "validity-AC2.log").read_text()
    assert (d / "validity-AC1.log").read_text().count("# exit:") == 1
    assert (
        repo.orch("run-tests", "M01", "--name", "x", "--paths", "tests/test_m01.py")[0]
        == 1
    )
    assert repo.orch("run-tests", "M01", "--name", "x", "--at", "nowhere")[0] == 1


# --- AC7 rework / escalation ---


def fail_doc(repo: Repo) -> dict:
    doc = repo.verification_doc(verdict="FAIL")
    doc["acceptance"] = {"AC1": {"result": "FAIL"}, "AC2": {"result": "FAIL"}}
    doc["validity"] = {}
    return doc


@with_repo
def test_fail_gives_rework_then_escalation_then_needs_g4(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    repo.write_verification(vwt, fail_doc(repo))
    repo.ok("finish-verify", "M01")
    assert repo.status() == "REWORK"
    # second and third attempt, chained from the previous verification branch
    for n in (2, 3):
        wt = repo.start_build()
        assert repo.state()["attempt"] == n
        att = wt / f"milestones/M01/attempts/{n:02d}"
        att.mkdir(parents=True)
        (att / "build.md").write_text("Status: COMPLETE\n")
        repo.commit(f"build {n}", cwd=wt)
        repo.ok("finish-build", "M01")
        v = repo.start_verify(session=f"v{n}")
        doc = fail_doc(repo)
        repo.write_verification(v, doc)
        repo.ok("finish-verify", "M01")
    assert repo.status() == "ESCALATED"
    esc = repo.state()["escalations"][0]
    assert esc["id"] == "E001" and esc["gate"] == "G4"
    assert (repo.root / "escalations/E001.md").exists()
    assert repo.git("status", "--porcelain") == ""
    # refused without a committed G4 approval
    before = repo.state_bytes()
    args = [
        "resolve",
        "M01",
        "--outcome",
        "REWORK",
        "--classification",
        "IMPLEMENTATION",
        "--note",
        "go",
    ]
    assert repo.orch(*args)[0] == 1
    (repo.root / "approvals").mkdir(exist_ok=True)
    (repo.root / "approvals/G4-E001.md").write_text("G4 E001\nDecision: APPROVED\n")
    assert (
        repo.orch(*args, "--approval", "approvals/G4-E001.md")[0] == 1
    )  # not committed
    assert repo.state_bytes() == before
    repo.commit("G4")
    repo.ok(*args, "--approval", "approvals/G4-E001.md")
    assert repo.status() == "REWORK"
    repo.start_build()  # one extra attempt was granted
    assert repo.state()["attempt"] == 4


@with_repo
def test_invalid_verdict_escalates_to_g3(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    repo.write_verification(
        vwt,
        repo.verification_doc(verdict="INVALID")
        | {"acceptance": {"AC1": {"result": "FAIL"}, "AC2": {"result": "FAIL"}}},
    )
    repo.ok("finish-verify", "M01")
    assert repo.status() == "ESCALATED"
    assert repo.state()["escalations"][0]["gate"] == "G3"


@with_repo
def test_blocked_verdict_and_unblock(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    doc = repo.verification_doc(verdict="BLOCKED")
    doc["acceptance"] = {"AC1": {"result": "BLOCKED"}, "AC2": {"result": "BLOCKED"}}
    repo.write_verification(vwt, doc)
    repo.ok("finish-verify", "M01")
    assert repo.status() == "BLOCKED"
    assert repo.orch("unblock", "M01", "--note", " ")[0] == 1
    repo.ok("unblock", "M01", "--note", "env fixed")
    assert repo.status() == "READY"


# --- AC8 change control ---


@with_repo
def test_spec_change_returns_to_draft_and_invalidate_cascades(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    repo.write_verification(vwt, repo.verification_doc())
    repo.ok("finish-verify", "M01")
    repo.ok("integrate", "M01")
    repo.approve("M02")
    # invalidate COMPLETE M01 -> STALE; M02 is only READY so it is untouched
    repo.ok("invalidate", "M01", "--to", "STALE", "--reason", "code changed")
    assert repo.status("M01") == "STALE"
    assert repo.orch("invalidate", "M01", "--to", "STALE", "--reason", "again")[0] == 1
    assert repo.orch("invalidate", "M01", "--to", "DRAFT", "--reason", " ")[0] == 1
    # spec edit on an approved milestone
    spec = repo.root / "milestones/M03/spec.yaml"
    repo.approve("M03")
    spec.write_text(spec.read_text() + "# edited\n")
    repo.commit("edit spec")
    repo.ok("refresh")
    assert repo.status("M03") == "DRAFT"
    assert repo.state("M03")["criteria_version"] is None
    # still-approved spec is untouched
    assert repo.status("M02") in ("READY", "APPROVED")


def test_invalidating_complete_dependency_stales_complete_dependents() -> None:
    r = Repo({"M01": [], "M02": ["M01"]})
    try:
        r.approve("M01")
        vwt = r.verifying("M01")
        r.write_verification(vwt, r.verification_doc("M01"), "M01")
        r.ok("finish-verify", "M01")
        r.ok("integrate", "M01")
        r.approve("M02")
        assert r.status("M02") == "READY"
        st = r.state("M02")
        st["status"] = "COMPLETE"  # stand-in for a fully integrated dependent
        (r.root / "milestones/M02/state.yaml").write_text(yaml.safe_dump(st))
        r.commit("dependent complete")
        r.ok("invalidate", "M01", "--to", "STALE", "--reason", "x")
        assert r.status("M01") == "STALE" and r.status("M02") == "STALE"
    finally:
        r.cleanup()


# --- AC9 integration ---


@with_repo
def test_integration_conflict_restores_main_and_reworks(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    repo.write_verification(vwt, repo.verification_doc())
    repo.ok("finish-verify", "M01")
    (repo.root / "src").mkdir(exist_ok=True)
    (repo.root / "src/m01.py").write_text("# conflicting content on main\n")
    pre = repo.commit("main moves on")
    rc, _, err = repo.orch("integrate", "M01")
    assert rc == 1 and "restored" in err
    assert repo.git("status", "--porcelain") == ""
    head = repo.git("rev-parse", "HEAD")
    assert repo.git("log", "-1", "--format=%an") == "orchestrator"
    assert repo.git("rev-parse", f"{head}~1") == pre
    assert repo.status() == "REWORK"
    assert (repo.root / "src/m01.py").read_text() == "# conflicting content on main\n"


@with_repo
def test_integration_suite_failure_restores_main(repo: Repo) -> None:
    repo.approve()
    vwt = repo.verifying()
    repo.write_verification(vwt, repo.verification_doc())
    repo.ok("finish-verify", "M01")
    # a COMPLETE milestone whose own suite breaks on the merge commit
    other = repo.root / "acceptance/M09"
    other.mkdir(parents=True)
    (other / "test_nine.py").write_text("def test_nine():\n    assert False\n")
    repo.commit("M09 suite")
    state9 = repo.root / "milestones/M09/state.yaml"
    state9.parent.mkdir(parents=True)
    (state9.parent / "spec.yaml").write_text(
        "id: M09\ntitle: nine\nobjective: o\ndepends_on: []\nacceptance:\n  AC1: x\n"
    )
    state9.write_text(yaml.safe_dump({"status": "COMPLETE", "attempt": 1}))
    pre = repo.commit("M09 complete")
    rc, _, err = repo.orch("integrate", "M01")
    assert rc == 1 and "acceptance/M09" in err
    assert repo.status() == "REWORK"
    assert not (repo.root / "src/m01.py").exists()
    assert repo.git("status", "--porcelain") == ""
    assert repo.git("merge-base", "--is-ancestor", pre, "HEAD") == ""


# --- AC10 / AC11 persistence and concurrency ---


@with_repo
def test_concurrent_finishes_do_not_corrupt_state(repo: Repo) -> None:
    repo.approve("M01")
    repo.approve("M03")
    wts = {m: repo.start_build(m, session=f"b-{m}") for m in ("M01", "M03")}
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
        for m in ("M01", "M03")
    ]
    results = [p.communicate() for p in procs]
    assert [p.returncode for p in procs] == [0, 0], results
    for m in ("M01", "M03"):
        assert repo.status(m) == "BUILT"
        assert authors(repo, m) == {"orchestrator"}
    assert repo.git("status", "--porcelain") == ""
    rows = {r["id"]: r["status"] for r in json.loads(repo.ok("status", "--json"))}
    assert rows["M01"] == rows["M03"] == "BUILT"


@with_repo
def test_state_commands_require_main_branch(repo: Repo) -> None:
    repo.git("checkout", "-q", "-b", "feature")
    rc, _, err = repo.orch("refresh")
    assert rc == 1 and "feature" in err
    assert repo.orch("status")[0] == 0


@with_repo
def test_state_commands_refuse_outside_main_worktree(repo: Repo) -> None:
    repo.approve()
    wt = repo.start_build()
    (wt / "orchestrator.py").write_text((repo.root / "orchestrator.py").read_text())
    before = repo.state_bytes()
    res = subprocess.run(
        [sys.executable, str(wt / "orchestrator.py"), "refresh"],
        cwd=wt,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1 and "main worktree" in res.stderr
    assert repo.state_bytes() == before


# --- real repository sanity (read-only) ---


def test_real_milestone_specs_form_a_valid_dag() -> None:
    res = subprocess.run(
        [sys.executable, str(REAL_ROOT / "orchestrator.py"), "validate"],
        cwd=REAL_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stdout
