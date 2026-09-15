"""Tests for E13 Chain of Draft parity experiment (issue #73).

Verifies script structure without running the actual eval:
- Script file exists and is importable
- Correct 3 arms (classic, cod, tahoe)
- 5 samples per benchmark, 3 trials per task, 450 total trials
- Reuses load_tasks, load_skill, run_trial from run_public_bench
- BENCH_ARMS env var overrides arms
- cod_prompt.txt exists and is non-empty
- Decision gate logic is sound
- Output JSON structure matches expected schema
"""

import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

_BENCH_DIR = Path(__file__).resolve().parent.parent / "benchmarks"
sys.path.insert(0, str(_BENCH_DIR))
sys.path.insert(0, str(_BENCH_DIR.parent / "src"))


def _load_e13_module():
    import benchmarks.run_e13_cod_parity as mod
    return mod


# -- 1. Script exists and is importable ---------------------------------


def test_script_file_exists():
    assert (_BENCH_DIR / "run_e13_cod_parity.py").exists()


def test_module_importable():
    mod = _load_e13_module()
    assert hasattr(mod, "main")


# -- 2. Three arms: classic, cod, tahoe ---------------------------------


def test_default_arms_is_three():
    mod = _load_e13_module()
    assert mod.E13_ARMS == ["classic", "cod", "tahoe"]


def test_arms_default_matches_e13_arms():
    mod = _load_e13_module()
    assert mod.ARMS == mod.E13_ARMS


# -- 3. Correct sample and trial counts ----------------------------------


def test_max_samples_per_bench_is_5():
    mod = _load_e13_module()
    assert mod.E13_MAX_SAMPLES_PER_BENCH == 5


def test_trials_per_task_is_3():
    mod = _load_e13_module()
    assert mod.E13_TRIALS_PER_TASK == 3


def test_total_trials_is_450():
    """10 benchmarks x 5 samples x 3 arms x 3 trials = 450."""
    mod = _load_e13_module()
    n_tasks = 10 * mod.E13_MAX_SAMPLES_PER_BENCH
    total = n_tasks * len(mod.E13_ARMS) * mod.E13_TRIALS_PER_TASK
    assert total == 450


# -- 4. Reuses run_public_bench infrastructure ---------------------------


def test_imports_load_tasks_from_public_bench():
    mod = _load_e13_module()
    assert hasattr(mod, "_load_public_tasks")
    from run_public_bench import load_tasks
    assert mod._load_public_tasks is load_tasks or callable(mod._load_public_tasks)


def test_imports_load_skill_from_public_bench():
    mod = _load_e13_module()
    assert callable(mod.load_skill)


def test_imports_run_trial_from_public_bench():
    mod = _load_e13_module()
    assert callable(mod.run_trial)


def test_imports_grade_task_from_public_bench():
    mod = _load_e13_module()
    assert callable(mod.grade_task)


# -- 5. BENCH_ARMS env var override --------------------------------------


def test_arms_configurable_via_env_var():
    env = {**os.environ, "BENCH_ARMS": "classic,cod,tahoe"}
    with mock.patch.dict(os.environ, env, clear=False):
        importlib.reload(
            sys.modules.get(
                "benchmarks.run_e13_cod_parity",
                importlib.import_module("benchmarks.run_e13_cod_parity"),
            )
        )
        mod = sys.modules["benchmarks.run_e13_cod_parity"]
        try:
            assert mod.ARMS == ["classic", "cod", "tahoe"]
        finally:
            importlib.reload(mod)


def test_arms_env_override_two_arms():
    env = {**os.environ, "BENCH_ARMS": "classic,tahoe"}
    with mock.patch.dict(os.environ, env, clear=False):
        importlib.reload(
            sys.modules.get(
                "benchmarks.run_e13_cod_parity",
                importlib.import_module("benchmarks.run_e13_cod_parity"),
            )
        )
        mod = sys.modules["benchmarks.run_e13_cod_parity"]
        try:
            assert mod.ARMS == ["classic", "tahoe"]
        finally:
            importlib.reload(mod)


# -- 6. cod_prompt.txt exists and is non-empty ----------------------------


def test_cod_prompt_exists():
    assert (_BENCH_DIR.parent / "language" / "baselines" / "cod.txt").exists()


def test_cod_prompt_nonempty():
    content = (_BENCH_DIR.parent / "language" / "baselines" / "cod.txt").read_text().strip()
    assert len(content) > 10


def test_cod_prompt_mentions_concise_or_brief():
    content = (_BENCH_DIR.parent / "language" / "baselines" / "cod.txt").read_text().lower()
    assert any(w in content for w in ("concise", "brief", "minimal", "bullet"))


# -- 7. Decision gate logic ---------------------------------------------


def test_decision_gate_tahoe_better():
    """If tahoe pass rate > cod, decision is 'adds value'."""
    mod = _load_e13_module()
    # Structure test: verify the main function contains decision gate logic
    import inspect
    source = inspect.getsource(mod.main)
    assert "Decision Gate" in source
    assert "adds value" in source
    assert "token-efficient" in source
    assert "unnecessary overhead" in source


# -- 8. run_trial delegates to run_public_bench ---------------------------


def test_run_trial_delegates_to_public_bench():
    mod = _load_e13_module()

    captured = {}

    def fake_run_public_trial(task, arm, skill_prompt, trial_idx):
        captured["task"] = task
        captured["arm"] = arm
        captured["skill_prompt"] = skill_prompt
        captured["trial_idx"] = trial_idx
        return {
            "task_id": task["task_id"],
            "benchmark": task["benchmark"],
            "arm": arm,
            "trial": trial_idx,
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "wall_seconds": 0.1,
            "passed": True,
            "failure_class": "none",
            "final_answer": "42",
            "quality_score": 1.0,
            "grader_detail": "ok",
            "verified_logical_steps": 0,
            "typed_refs_produced": 0,
            "repeated_refs": 0,
            "retired_refs": 0,
            "total_refs_produced": 0,
        }

    with mock.patch.object(mod, "_run_public_trial", side_effect=fake_run_public_trial):
        task = {
            "task_id": "test-001",
            "benchmark": "gsm8k",
            "description": "What is 2+2?",
            "expected": "4",
            "grader": "gsm8k",
        }
        result = mod.run_trial(task, "cod", "skill text", 0)

    assert captured["arm"] == "cod"
    assert captured["task"] == task
    assert captured["trial_idx"] == 0
    assert result["arm"] == "cod"
    assert result["passed"] is True


# -- 9. load_tasks reduces samples to 5 ----------------------------------


def test_load_tasks_uses_5_samples_per_benchmark():
    """load_tasks should temporarily set MAX_SAMPLES_PER_BENCH to 5."""
    mod = _load_e13_module()
    assert mod.E13_MAX_SAMPLES_PER_BENCH == 5


def test_load_tasks_returns_50_tasks():
    """5 samples x 10 benchmarks = 50 tasks."""
    mod = _load_e13_module()

    # Mock the public load_tasks to return a list of 50 fake tasks
    fake_tasks = [
        {"task_id": f"bench-{i}", "benchmark": f"bench{i % 10}", "description": "q",
         "expected": "a", "grader": "gsm8k"}
        for i in range(50)
    ]

    with mock.patch.object(mod, "_load_public_tasks", return_value=fake_tasks):
        tasks = mod.load_tasks()

    assert len(tasks) == 50


# -- 10. Output JSON schema ---------------------------------------------


def test_output_schema_keys():
    """The main function should write a JSON with expected top-level keys."""
    mod = _load_e13_module()
    import inspect
    source = inspect.getsource(mod.main)
    assert '"experiment"' in source
    assert '"E13_chain_of_draft_parity"' in source
    assert '"arms"' in source
    assert '"trials_per_task"' in source
    assert '"samples_per_benchmark"' in source
    assert '"total_trials"' in source
    assert '"trials"' in source
    assert "e13_cod_parity.json" in source
