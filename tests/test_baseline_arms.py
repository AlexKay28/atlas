"""Tests for baseline arm prompt files and runner integration (#75).

Verifies:
- All 4 baseline prompt files exist and are non-empty
- ARM_PROMPT_FILES maps each arm to the correct prompt file
- load_arm_prompt returns non-empty text for each baseline arm
- load_arm_prompt returns "" for classic (no prompt)
- ARMS is configurable via BENCH_ARMS env var
- run_trial selects the correct system prompt per arm
- Existing classic/tahoe arms are unchanged
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


def _load_bench_module():
    import benchmarks.run_public_bench as mod
    return mod


# -- 1. Prompt files exist and are non-empty ------------------------------

@pytest.mark.parametrize("filename", [
    "cot.txt",
    "cod.txt",
    "tot.txt",
    "react.txt",
])
def test_prompt_file_exists_and_nonempty(filename):
    path = _BENCH_DIR.parent / "language" / "baselines" / filename
    assert path.exists(), f"Missing prompt file: {filename}"
    content = path.read_text().strip()
    assert len(content) > 10, f"Prompt file {filename} is too short"


@pytest.mark.parametrize("filename,expected_phrase", [
    ("cot.txt", "step by step"),
    ("cod.txt", "bullet point"),
    ("tot.txt", "multiple"),
    ("react.txt", "Reason then act"),
])
def test_prompt_file_contains_expected_phrase(filename, expected_phrase):
    content = (_BENCH_DIR.parent / "language" / "baselines" / filename).read_text().lower()
    assert expected_phrase.lower() in content


# -- 2. ARM_PROMPT_FILES mapping -----------------------------------------

def test_arm_prompt_files_has_all_six_arms():
    mod = _load_bench_module()
    expected_arms = {"classic", "tahoe", "cot", "cod", "tot", "react"}
    assert set(mod.ARM_PROMPT_FILES.keys()) == expected_arms


def test_arm_prompt_files_classic_is_none():
    mod = _load_bench_module()
    assert mod.ARM_PROMPT_FILES["classic"] is None


def test_arm_prompt_files_tahoe_points_to_skill_prompt():
    mod = _load_bench_module()
    assert mod.ARM_PROMPT_FILES["tahoe"] == "tahoe-93.txt"


# -- 3. load_arm_prompt --------------------------------------------------

def test_load_arm_prompt_returns_nonempty_for_baseline_arms():
    mod = _load_bench_module()
    for arm in ("cot", "cod", "tot", "react"):
        text = mod.load_arm_prompt(arm)
        assert isinstance(text, str)
        assert len(text) > 10, f"Prompt for arm '{arm}' is empty"


def test_load_arm_prompt_returns_empty_for_classic():
    mod = _load_bench_module()
    assert mod.load_arm_prompt("classic") == ""


def test_load_arm_prompt_uses_cache():
    mod = _load_bench_module()
    cache = {}
    text1 = mod.load_arm_prompt("cot", cache)
    text2 = mod.load_arm_prompt("cot", cache)
    assert text1 == text2
    assert "cot" in cache


def test_load_arm_prompt_unknown_arm_returns_empty():
    mod = _load_bench_module()
    assert mod.load_arm_prompt("nonexistent_arm") == ""


# -- 4. ARMS configurable via BENCH_ARMS env var --------------------------

def test_default_arms_is_classic_and_tahoe():
    mod = _load_bench_module()
    assert mod.DEFAULT_ARMS == ["classic", "tahoe"]


def test_all_arms_includes_baselines():
    mod = _load_bench_module()
    for arm in ("cot", "cod", "tot", "react"):
        assert arm in mod.ALL_ARMS


def test_arms_configurable_via_env_var():
    env = {**os.environ, "BENCH_ARMS": "classic,cot,react"}
    with mock.patch.dict(os.environ, env, clear=False):
        importlib.reload(sys.modules.get("benchmarks.run_public_bench",
                                          importlib.import_module("benchmarks.run_public_bench")))
        mod = sys.modules["benchmarks.run_public_bench"]
        try:
            assert mod.ARMS == ["classic", "cot", "react"]
        finally:
            # Restore
            importlib.reload(mod)


# -- 5. run_trial selects correct system prompt per arm ------------------

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


def test_run_trial_uses_correct_prompt_for_cot():
    mod = _load_bench_module()
    captured = {}

    def fake_run_classic(**kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _fake_classic_result()

    with mock.patch.object(mod, "run_classic", side_effect=fake_run_classic):
        task = {
            "task_id": "test-001",
            "benchmark": "gsm8k",
            "description": "What is 2+2?",
            "expected": "4",
            "grader": "gsm8k",
        }
        mod.run_trial(task, "cot", "tahoe skill text", 0)
    assert captured["system_prompt"] != ""
    assert "step by step" in captured["system_prompt"].lower()


def test_run_trial_uses_correct_prompt_for_cod():
    mod = _load_bench_module()
    captured = {}

    def fake_run_classic(**kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _fake_classic_result()

    with mock.patch.object(mod, "run_classic", side_effect=fake_run_classic):
        task = {
            "task_id": "test-002",
            "benchmark": "gsm8k",
            "description": "What is 3+3?",
            "expected": "6",
            "grader": "gsm8k",
        }
        mod.run_trial(task, "cod", "tahoe skill text", 0)
    assert captured["system_prompt"] != ""
    assert "bullet" in captured["system_prompt"].lower()


def test_run_trial_uses_correct_prompt_for_tot():
    mod = _load_bench_module()
    captured = {}

    def fake_run_classic(**kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _fake_classic_result()

    with mock.patch.object(mod, "run_classic", side_effect=fake_run_classic):
        task = {
            "task_id": "test-003",
            "benchmark": "gsm8k",
            "description": "What is 4+4?",
            "expected": "8",
            "grader": "gsm8k",
        }
        mod.run_trial(task, "tot", "tahoe skill text", 0)
    assert captured["system_prompt"] != ""
    assert "multiple" in captured["system_prompt"].lower()


def test_run_trial_uses_correct_prompt_for_react():
    mod = _load_bench_module()
    captured = {}

    def fake_run_classic(**kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _fake_classic_result()

    with mock.patch.object(mod, "run_classic", side_effect=fake_run_classic):
        task = {
            "task_id": "test-004",
            "benchmark": "gsm8k",
            "description": "What is 5+5?",
            "expected": "10",
            "grader": "gsm8k",
        }
        mod.run_trial(task, "react", "tahoe skill text", 0)
    assert captured["system_prompt"] != ""
    assert "reason" in captured["system_prompt"].lower()


def test_run_trial_classic_uses_empty_prompt():
    mod = _load_bench_module()
    captured = {}

    def fake_run_classic(**kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _fake_classic_result()

    with mock.patch.object(mod, "run_classic", side_effect=fake_run_classic):
        task = {
            "task_id": "test-005",
            "benchmark": "gsm8k",
            "description": "What is 6+6?",
            "expected": "12",
            "grader": "gsm8k",
        }
        mod.run_trial(task, "classic", "tahoe skill text", 0)
    assert captured["system_prompt"] == ""


def test_run_trial_tahoe_uses_skill_prompt():
    mod = _load_bench_module()
    captured = {}
    skill_text = "TAHOE skill prompt"

    def fake_run_classic(**kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _fake_classic_result()

    with mock.patch.object(mod, "run_classic", side_effect=fake_run_classic):
        task = {
            "task_id": "test-006",
            "benchmark": "gsm8k",
            "description": "What is 7+7?",
            "expected": "14",
            "grader": "gsm8k",
        }
        mod.run_trial(task, "tahoe", skill_text, 0)
    assert captured["system_prompt"] == skill_text


# -- 6. run_trial produces valid result dict for each arm -----------------

@pytest.mark.parametrize("arm", ["classic", "tahoe", "cot", "cod", "tot", "react"])
def test_run_trial_produces_valid_result_for_arm(arm):
    mod = _load_bench_module()

    def fake_run_classic(**kwargs):
        return _fake_classic_result(final_answer="42")

    with mock.patch.object(mod, "run_classic", side_effect=fake_run_classic):
        task = {
            "task_id": f"test-{arm}",
            "benchmark": "gsm8k",
            "description": "What is 1+1?",
            "expected": "2",
            "grader": "gsm8k",
        }
        result = mod.run_trial(task, arm, "tahoe skill", 0)
    assert isinstance(result, dict)
    assert result["arm"] == arm
    assert result["task_id"] == f"test-{arm}"
    assert "passed" in result
    assert "final_answer" in result
    assert "total_tokens" in result


# -- 7. load_skill backward compat --------------------------------------

def test_load_skill_returns_tahoe_prompt():
    mod = _load_bench_module()
    text = mod.load_skill()
    assert isinstance(text, str)
    assert len(text) > 0
    assert "TAHOE" in text
