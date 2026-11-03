"""Acceptance tests for M00: Dummy milestone for infrastructure testing."""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def test_ac1_file_exists():
    """AC1: A file named M00_DONE exists in the source tree."""
    done_file = REPO_ROOT / "M00_DONE"
    assert done_file.exists(), "M00_DONE file does not exist"


def test_ac2_file_content():
    """AC2: The file contains the text 'M00 complete'."""
    done_file = REPO_ROOT / "M00_DONE"
    if done_file.exists():
        content = done_file.read_text()
        assert "M00 complete" in content, (
            f"File does not contain 'M00 complete', got: {content}"
        )
