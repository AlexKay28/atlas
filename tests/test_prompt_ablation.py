"""Tests for skill prompt ablation runner (#89).

Verifies:
- All 4 ablation prompt files exist and are non-empty
- PROMPT_FILES maps each arm to the correct prompt file
- load_prompt returns non-empty text for each ablation arm
- load_prompt returns "" for classic (no prompt)
- ABLATION_ARMS has exactly 5 arms in the right order
- PROMPT_TOKEN_ESTIMATES matches the arm list
- build_trial_plan produces 750 trials (5 arms x 10 bench x 5 samples x 3)
- compute_harmonic_mean handles edge cases
- compute_pareto_table produces correct structure
- format_pareto_table returns a non-empty string
- run_ablation_trial produces a valid result dict
"""

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

_BENCH_DIR = Path(__file__).resolve().parent.parent / "benchmarks"
sys.path.insert(0, str(_BENCH_DIR))
sys.path.insert(0, str(_BENCH_DIR.parent / "src"))


def _load_ablation_module():
    import benchmarks.run_prompt_ablation as mod
    return mod


# -- 1. Prompt files exist and are non-empty ------------------------------

@pytest.mark.parametrize("filename", [
    "tahoe_skill_50.txt",
    "tahoe_skill_prompt.txt",
    "tahoe_skill_150.txt",
    "tahoe_skill_200.txt",
])
def test_prompt_file_exists_and_nonempty(filename):
    path = _BENCH_DIR / filename
    assert path.exists(), f"Missing prompt file: {filename}"
    content = path.read_text().strip()
    assert len(content) > 10, f"Prompt file {filename} is too short"


# -- 2. Prompt token ordering: 50 < 93 < 150 < 200 -----------------------

def test_prompt_sizes_are_monotonically_increasing():
    files = [
        "tahoe_skill_50.txt",
        "tahoe_skill_prompt.txt",
        "tahoe_skill_150.txt",
        "tahoe_skill_200.txt",
    ]
    sizes = [len((_BENCH_DIR / f).read_text()) for f in files]
    for i in range(len(sizes) - 1):
        assert sizes[i] < sizes[i + 1], (
            f"Prompt {files[i]} ({sizes[i]} chars) should be shorter than "
            f"{files[i+1]} ({sizes[i+1]} chars)"
        )


# -- 3. ABLATION_ARMS and PROMPT_FILES ------------------------------------

def test_ablation_arms_has_five_arms():
    mod = _load_ablation_module()
    assert mod.ABLATION_ARMS == ["classic", "50", "93", "150", "200"]


def test_prompt_files_keys_match_arms():
    mod = _load_ablation_module()
    assert set(mod.PROMPT_FILES.keys()) == set(mod.ABLATION_ARMS)


def test_prompt_files_classic_is_none():
    mod = _load_ablation_module()
    assert mod.PROMPT_FILES["classic"] is None


def test_prompt_files_93_points_to_production_skill():
    mod = _load_ablation_module()
    assert mod.PROMPT_FILES["93"] == "tahoe_skill_prompt.txt"


def test_prompt_token_estimates_match_arms():
    mod = _load_ablation_module()
    assert set(mod.PROMPT_TOKEN_ESTIMATES.keys()) == set(mod.ABLATION_ARMS)
    assert mod.PROMPT_TOKEN_ESTIMATES["classic"] == 0
    assert mod.PROMPT_TOKEN_ESTIMATES["50"] == 50
    assert mod.PROMPT_TOKEN_ESTIMATES["93"] == 93
    assert mod.PROMPT_TOKEN_ESTIMATES["150"] == 150
    assert mod.PROMPT_TOKEN_ESTIMATES["200"] == 200


# -- 4. load_prompt -------------------------------------------------------

def test_load_prompt_returns_nonempty_for_ablation_arms():
    mod = _load_ablation_module()
    for arm in ("50", "93", "150", "200"):
        text = mod.load_prompt(arm)
        assert isinstance(text, str)
        assert len(text) > 10, f"Prompt for arm '{arm}' is empty"


def test_load_prompt_returns_empty_for_classic():
    mod = _load_ablation_module()
    assert mod.load_prompt("classic") == ""


def test_load_all_prompts_returns_dict():
    mod = _load_ablation_module()
    prompts = mod.load_all_prompts()
    assert isinstance(prompts, dict)
    assert set(prompts.keys()) == set(mod.ABLATION_ARMS)
    assert prompts["classic"] == ""
    for arm in ("50", "93", "150", "200"):
        assert len(prompts[arm]) > 10


# -- 5. build_trial_plan --------------------------------------------------

def test_build_trial_plan_total_count():
    mod = _load_ablation_module()
    n_arms = len(mod.ABLATION_ARMS)
    n_tasks = 50  # 10 benchmarks x 5 samples
    n_trials = mod.TRIALS_PER_TASK
    expected = n_arms * n_tasks * n_trials
    tasks = [{"task_id": f"t{i}", "benchmark": f"b{i // 5}"} for i in range(n_tasks)]
    plan = mod.build_trial_plan(tasks, mod.ABLATION_ARMS, n_trials, mod.SEED)
    assert len(plan) == expected
    assert len(plan) == 750


def test_build_trial_plan_is_deterministic():
    mod = _load_ablation_module()
    tasks = [{"task_id": f"t{i}", "benchmark": "b"} for i in range(10)]
    plan1 = mod.build_trial_plan(tasks, mod.ABLATION_ARMS, 3, 42)
    plan2 = mod.build_trial_plan(tasks, mod.ABLATION_ARMS, 3, 42)
    assert plan1 == plan2


def test_build_trial_plan_covers_all_arms():
    mod = _load_ablation_module()
    tasks = [{"task_id": f"t{i}", "benchmark": "b"} for i in range(10)]
    plan = mod.build_trial_plan(tasks, mod.ABLATION_ARMS, 3, 42)
    arms_in_plan = set(arm for _, arm, _ in plan)
    assert arms_in_plan == set(mod.ABLATION_ARMS)


# -- 6. compute_harmonic_mean ---------------------------------------------

def test_hm_both_zero():
    mod = _load_ablation_module()
    assert mod.compute_harmonic_mean(0.0, 0.5) == 0.0
    assert mod.compute_harmonic_mean(0.5, 0.0) == 0.0


def test_hm_both_one():
    mod = _load_ablation_module()
    assert mod.compute_harmonic_mean(1.0, 1.0) == pytest.approx(1.0)


def test_hm_symmetric():
    mod = _load_ablation_module()
    assert mod.compute_harmonic_mean(0.8, 0.4) == pytest.approx(
        mod.compute_harmonic_mean(0.4, 0.8)
    )


def test_hm_known_value():
    mod = _load_ablation_module()
    # HM(0.5, 0.5) = 2 * 0.5 * 0.5 / (0.5 + 0.5) = 0.5
    assert mod.compute_harmonic_mean(0.5, 0.5) == pytest.approx(0.5)


# -- 7. compute_pareto_table ---------------------------------------------

def test_pareto_table_has_row_per_arm():
    mod = _load_ablation_module()
    trials = [
        {"arm": arm, "passed": True, "output_tokens": 100, "total_tokens": 200,
         "re_reasoning_efficiency": 0.01, "rc_reasoning_concentration": 0.02,
         "rr_redundancy_rate": 0.0}
        for arm in mod.ABLATION_ARMS
    ]
    rows = mod.compute_pareto_table(trials)
    assert len(rows) == len(mod.ABLATION_ARMS)
    arms_in_rows = [r["arm"] for r in rows]
    assert arms_in_rows == mod.ABLATION_ARMS


def test_pareto_table_row_fields():
    mod = _load_ablation_module()
    trials = [{"arm": "50", "passed": True, "output_tokens": 50,
               "total_tokens": 100, "re_reasoning_efficiency": 0.01,
               "rc_reasoning_concentration": 0.02, "rr_redundancy_rate": 0.0}]
    rows = mod.compute_pareto_table(trials)
    row = rows[1]  # "50" is index 1
    assert row["arm"] == "50"
    assert row["prompt_tokens"] == 50
    assert row["quality"] == 1.0
    assert row["avg_output_tokens"] == 50.0
    assert row["n_trials"] == 1
    assert "hm" in row
    assert "re" in row
    assert "rc" in row
    assert "rr" in row


def test_pareto_table_empty_trials():
    mod = _load_ablation_module()
    rows = mod.compute_pareto_table([])
    assert len(rows) == len(mod.ABLATION_ARMS)
    for r in rows:
        assert r["quality"] == 0.0
        assert r["n_trials"] == 0


# -- 8. format_pareto_table -----------------------------------------------

def test_format_pareto_table_returns_string():
    mod = _load_ablation_module()
    rows = mod.compute_pareto_table([])
    text = mod.format_pareto_table(rows)
    assert isinstance(text, str)
    assert "arm" in text
    assert "HM" in text
    for arm in mod.ABLATION_ARMS:
        assert arm in text


# -- 9. run_ablation_trial ------------------------------------------------

def _fake_classic_result(final_answer="42", input_tokens=10, output_tokens=5):
    return SimpleNamespace(
        task_id="test-001",
        arm="classic",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        wall_seconds=0.1,
        passed=True,
        failure_class="none",
        turns=1,
        final_answer=final_answer,
    )


def test_run_ablation_trial_produces_valid_result():
    mod = _load_ablation_module()

    def fake_run_classic(**kwargs):
        return _fake_classic_result()

    with mock.patch.object(mod, "run_classic", side_effect=fake_run_classic):
        task = {
            "task_id": "gsm8k-0001",
            "benchmark": "gsm8k",
            "description": "What is 2+2?",
            "expected": "#### 4",
            "grader": "gsm8k",
        }
        result = mod.run_ablation_trial(task, "50", "minimal prompt", 0)

    assert isinstance(result, dict)
    assert result["arm"] == "50"
    assert result["task_id"] == "gsm8k-0001"
    assert result["trial"] == 0
    assert result["prompt_tokens_estimate"] == 50
    assert "passed" in result
    assert "final_answer" in result
    assert "total_tokens" in result
    assert "re_reasoning_efficiency" in result
    assert "rc_reasoning_concentration" in result
    assert "rr_redundancy_rate" in result


def test_run_ablation_trial_classic_uses_empty_prompt():
    mod = _load_ablation_module()
    captured = {}

    def fake_run_classic(**kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _fake_classic_result()

    with mock.patch.object(mod, "run_classic", side_effect=fake_run_classic):
        task = {
            "task_id": "gsm8k-0002",
            "benchmark": "gsm8k",
            "description": "What is 3+3?",
            "expected": "#### 6",
            "grader": "gsm8k",
        }
        mod.run_ablation_trial(task, "classic", "", 0)

    assert captured["system_prompt"] == ""


def test_run_ablation_trial_200_uses_prompt():
    mod = _load_ablation_module()
    captured = {}
    prompt_200 = mod.load_prompt("200")

    def fake_run_classic(**kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _fake_classic_result()

    with mock.patch.object(mod, "run_classic", side_effect=fake_run_classic):
        task = {
            "task_id": "gsm8k-0003",
            "benchmark": "gsm8k",
            "description": "What is 4+4?",
            "expected": "#### 8",
            "grader": "gsm8k",
        }
        mod.run_ablation_trial(task, "200", prompt_200, 0)

    assert captured["system_prompt"] == prompt_200
    assert "trigger" in captured["system_prompt"].lower()


# -- 10. Eval invariant: same grader for all arms --------------------------

def test_grader_is_arm_independent():
    """The grade_task function must not branch on arm identity."""
    mod = _load_ablation_module()
    import benchmarks.run_public_bench as bench_mod
    import inspect
    source = inspect.getsource(bench_mod.grade_task)
    # grade_task should not reference "arm"
    assert "arm" not in source.lower(), (
        "grade_task must not reference 'arm' — evaluation invariant"
    )
