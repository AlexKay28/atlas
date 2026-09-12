"""Grep gate test (issue #52): zero old-name references in live code/docs.

Asserts that ``git grep -c`` (case-insensitive) for the pre-rebrand
project name over src/ tests/ README.md docs/ pyproject.toml .opencode/
returns ZERO matches. Historical demo/runs/** are exempt (immutable
evidence). This docstring itself avoids the literal token so the gate
can include tests/ in its sweep.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_tikhon_references_in_live_code():
    """No pre-rebrand name (case-insensitive) in live code/docs.

    This test file is excluded from the sweep because the search
    pattern itself must appear here.
    """
    scopes = [
        "src/",
        "tests/",
        "README.md",
        "docs/",
        "pyproject.toml",
        ".opencode/",
        ":(exclude)tests/test_branding.py",
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
        f"Found pre-rebrand name references in live code/docs:\n{result.stdout}"
    )
    assert result.stdout == "", (
        f"Unexpected matches:\n{result.stdout}"
    )
