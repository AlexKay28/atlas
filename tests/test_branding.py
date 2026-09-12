"""Grep gate test (issue #52): zero 'tikhon' references in live code/docs.

Asserts that ``git grep -c tikhon`` over src/ tests/ README.md docs/
pyproject.toml .opencode/ returns ZERO matches. Historical demo/runs/**
are exempt (immutable evidence).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_tikhon_references_in_live_code():
    """No 'tikhon' (case-insensitive) in src/ tests/ README.md docs/ pyproject.toml .opencode/."""
    scopes = [
        "src/",
        "tests/",
        "README.md",
        "docs/",
        "pyproject.toml",
        ".opencode/",
    ]
    result = subprocess.run(
        [
            "git", "grep", "-i", "-c", "tikhon",
            "--",
            *scopes,
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    # git grep returns 0 if matches found, 1 if no matches
    assert result.returncode == 1, (
        f"Found 'tikhon' references in live code/docs:\n{result.stdout}"
    )
    assert result.stdout == "", (
        f"Unexpected 'tikhon' matches:\n{result.stdout}"
    )
