"""kickoff: the start-of-project command that asks the goal and writes the rails."""

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("wire_helpers", HERE / "test_wire.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)


def kickoff(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kickoff", *args],
        cwd=H.ROOT,
        env=H.ENV,
        capture_output=True,
        text=True,
        check=False,
        **kw,
    )


FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "PROJECT.md",
    "interop.yaml",
    "PROVENANCE.yaml",
    "RESULTS.md",
]


def answers(**over) -> dict:
    a = {
        "goal": "Show the Python client interoperates with the C server",
        "success": "Python client and C server pass observes-n1",
        "out_of_scope": "Group OSCORE",
        "spec": "draft-ietf-core-observe-multicast-notifications-15",
        "mode": "both",
        "checker_family": "google",
        "reviewer": "Mistral Vibe, runs commands",
        "not_live": "none",
        "peers": [
            {
                "name": "c-server",
                "path": "c",
                "role": "server",
                "family": "openai",
                "under_test": True,
            },
            {
                "name": "py-client",
                "path": "py",
                "role": "client",
                "family": "anthropic",
                "under_test": True,
            },
        ],
    }
    a.update(over)
    return a


def run_init(tmp: Path, a: dict, *extra: str):
    f = tmp / "answers.yaml"
    f.write_text(yaml.safe_dump(a))
    return kickoff(str(tmp / "proj"), "--answers", str(f), *extra)


def test_writes_every_rail_with_the_answers():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        r = run_init(tmp, answers())
        assert r.returncode == 0, r.stdout + r.stderr
        proj = tmp / "proj"
        assert sorted(p.name for p in proj.iterdir()) == sorted(FILES)
        agents = (proj / "AGENTS.md").read_text()
        assert "draft-ietf-core-observe-multicast-notifications-15" in agents
        assert "mocked" in agents and "Building with agents" in agents
        assert "AGENTS.md" in (proj / "CLAUDE.md").read_text()
        assert "Python client" in (proj / "PROJECT.md").read_text()
        m = yaml.safe_load((proj / "interop.yaml").read_text())
        assert m["checkers"][0]["family"] == "google"
        assert m["cells"][0]["server"] == "c-server"
        assert m["cells"][0]["clients"] == ["py-client"]
        prov = yaml.safe_load((proj / "PROVENANCE.yaml").read_text())
        assert {a["written_by"] for a in prov["artifacts"]} == {
            "openai",
            "anthropic",
            "google",
        }


def test_checker_from_an_implementation_family_is_refused():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        r = run_init(tmp, answers(checker_family="anthropic"))
        assert r.returncode == 2
        assert "checker family anthropic" in r.stderr
        assert not (tmp / "proj").exists()


def test_unanswered_question_is_refused():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        r = run_init(tmp, answers(goal=""))
        assert r.returncode == 2
        assert "unanswered: goal" in r.stderr


def test_single_family_is_warned_and_recorded():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        a = answers()
        a["peers"][0]["family"] = "anthropic"
        r = run_init(tmp, a)
        assert r.returncode == 0, r.stderr
        assert "every implementation under test comes from anthropic" in r.stdout
        assert "comes from anthropic" in (tmp / "proj" / "PROJECT.md").read_text()


def test_existing_rails_are_not_overwritten_without_force():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        assert run_init(tmp, answers()).returncode == 0
        r = run_init(tmp, answers())
        assert r.returncode == 2
        assert "already has AGENTS.md" in r.stderr
        assert run_init(tmp, answers(), "--force").returncode == 0


def test_no_terminal_and_no_answers_points_to_questions():
    with tempfile.TemporaryDirectory() as t:
        r = kickoff(str(Path(t) / "proj"), stdin=subprocess.DEVNULL)
        assert r.returncode == 2
        assert "--questions" in r.stderr


def test_questions_template_is_a_valid_answers_file_shape():
    r = kickoff("--questions")
    assert r.returncode == 0
    t = yaml.safe_load(r.stdout)
    assert "goal" in t and isinstance(t["peers"], list)
