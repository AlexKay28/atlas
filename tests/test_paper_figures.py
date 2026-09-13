"""Tests for paper/generate_figures.py (issue #92).

Validates that the script is importable, produces the expected
figure structure, and handles the benchmark data correctly.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAPER_DIR = ROOT / "paper"
SCRIPT = PAPER_DIR / "generate_figures.py"
DATA_PATH = ROOT / "benchmarks" / "results" / "public_benchmarks.json"
FIG_DIR = PAPER_DIR / "figures"


def _import_module():
    spec = importlib.util.spec_from_file_location("generate_figures", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_figures"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_script_exists_and_valid_python():
    assert SCRIPT.exists(), f"Script not found at {SCRIPT}"
    compile(SCRIPT.read_text(), str(SCRIPT), "exec")


def test_data_file_exists():
    assert DATA_PATH.exists(), f"Benchmark data not found at {DATA_PATH}"


def test_load_data():
    mod = _import_module()
    records = mod.load_data(DATA_PATH)
    assert len(records) == 600, f"Expected 600 trials, got {len(records)}"
    arms = {r["arm"] for r in records}
    assert arms == {"classic", "tahoe"}


def test_aggregate_by_benchmark():
    mod = _import_module()
    records = mod.load_data(DATA_PATH)
    stats = mod.aggregate_by_benchmark(records)
    expected_benchmarks = {
        "arc", "bbh", "bbh_arith", "bbh_track", "gsm8k",
        "lsat", "mmlu_acct", "mmlu_logic", "mmlu_math", "race",
    }
    assert set(stats.keys()) == expected_benchmarks
    for bench, arms in stats.items():
        for arm, s in arms.items():
            assert 0 <= s["pass_rate"] <= 1
            assert s["count"] > 0
            assert s["mean_output"] > 0


def test_bench_labels_cover_all():
    mod = _import_module()
    records = mod.load_data(DATA_PATH)
    benchmarks = {r["benchmark"] for r in records}
    for b in benchmarks:
        assert b in mod.BENCH_LABELS, f"Missing label for benchmark: {b}"


def test_generate_all_produces_files():
    mod = _import_module()
    if not mod.HAS_MPL:
        pytest.skip("matplotlib not available")
    paths = mod.generate_all(DATA_PATH, FIG_DIR)
    assert len(paths) == 5  # 1 combined + 4 individual
    for p in paths:
        assert Path(p).exists(), f"Output file missing: {p}"
        assert Path(p).stat().st_size > 0, f"Empty PDF: {p}"


def test_generate_all_without_mpl():
    mod = _import_module()
    if mod.HAS_MPL:
        pytest.skip("matplotlib is available — skipping no-mpl path")
    paths = mod.generate_all(DATA_PATH, FIG_DIR)
    assert paths == [], "Should return empty list when matplotlib unavailable"


def test_individual_figure_functions_exist():
    mod = _import_module()
    for name in ["figure1_quality_vs_tokens", "figure2_pass_rate_bars",
                 "figure3_token_savings", "figure4_reasoning_comparison"]:
        assert hasattr(mod, name), f"Missing function: {name}"


def test_figure4_picks_task_with_both_arms():
    mod = _import_module()
    records = mod.load_data(DATA_PATH)
    by_task = {}
    for r in records:
        by_task.setdefault(r["task_id"], {})[r["arm"]] = r
    has_both = any("classic" in v and "tahoe" in v for v in by_task.values())
    assert has_both, "No task has both classic and tahoe trials"
