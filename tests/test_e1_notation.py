"""Tests for E1 notation efficiency experiment (issue #72)."""

import json
import os
import subprocess
import sys

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "run_e1_notation.py")
RESULTS = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "results", "e1_notation.json")
NOTATIONS = ("verbose_english", "tahoe_typed_refs", "minimal_symbols")


def test_script_runs_and_produces_valid_output(tmp_path):
    """Run the script as a subprocess and validate the JSON output."""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    proc = subprocess.run(
        [sys.executable, os.path.abspath(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert proc.returncode == 0, f"Script failed:\n{proc.stderr}"
    assert os.path.exists(RESULTS), "Results JSON was not created"
    with open(RESULTS) as f:
        data = json.load(f)
    assert data["experiment"] == "E1_notation_efficiency"
    assert len(data["snippets"]) == 10
    for snip in data["snippets"]:
        for nat in NOTATIONS:
            assert nat in snip["tokens"]
            assert isinstance(snip["tokens"][nat], int)
            assert snip["tokens"][nat] > 0
    for nat in NOTATIONS:
        assert nat in data["totals"]
        assert nat in data["averages"]
        assert nat in data["ratios"]


def test_tokenizer_consistency():
    """The tokenizer is deterministic for the same input."""
    from benchmarks.run_e1_notation import tokenize, token_count

    text = "IF (3+5)%2=0 THEN V.result: true DONE"
    tokens1 = tokenize(text)
    tokens2 = tokenize(text)
    assert tokens1 == tokens2
    assert token_count(text) == len(tokens1)


def test_categories_covered():
    """All five categories must appear in the snippets."""
    from benchmarks.run_e1_notation import SNIPPETS

    categories = {s.category for s in SNIPPETS}
    expected = {"arithmetic", "logical_deduction", "planning", "selection", "multi_step_reasoning"}
    assert categories == expected


def test_ten_snippets():
    from benchmarks.run_e1_notation import SNIPPETS

    assert len(SNIPPETS) == 10
