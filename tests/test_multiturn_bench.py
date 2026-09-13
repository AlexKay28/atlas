"""Tests for benchmarks/run_multiturn_bench.py (issue #91).

Tests cover:
  - Task definitions (3 suites, 5 tasks each)
  - Graders for each suite
  - Tool implementations (calculator, code executor, search)
  - Result dataclass structure
  - Metrics aggregation
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "benchmarks") not in sys.path:
    sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.run_multiturn_bench import (
    ARMS,
    TRIALS_PER_TASK,
    SUITES,
    MultiTurnResult,
    MultiTurnTask,
    aggregate_metrics,
    get_all_tasks,
    run_multiturn_trial,
    suite_code_generation,
    suite_multi_step_planning,
    suite_tool_use,
    total_trial_count,
    tool_calculator,
    tool_code_executor,
    tool_search,
    CALCULATOR_SCHEMA,
    CODE_EXECUTOR_SCHEMA,
    SEARCH_SCHEMA,
    TOOL_IMPLEMENTATIONS,
)


# ---------------------------------------------------------------------------
# Suite / task definition tests
# ---------------------------------------------------------------------------

class TestSuiteDefinitions:
    def test_three_suites_defined(self):
        assert len(SUITES) == 3
        assert "code_generation" in SUITES
        assert "tool_use" in SUITES
        assert "multi_step_planning" in SUITES

    def test_code_generation_suite_has_5_tasks(self):
        tasks = suite_code_generation()
        assert len(tasks) == 5
        for t in tasks:
            assert t.suite == "code_generation"
            assert t.max_turns == 3
            assert t.grader is not None
            assert len(t.tools) == 1  # code_executor

    def test_tool_use_suite_has_5_tasks(self):
        tasks = suite_tool_use()
        assert len(tasks) == 5
        for t in tasks:
            assert t.suite == "tool_use"
            assert t.max_turns == 3
            assert t.grader is not None

    def test_multi_step_planning_suite_has_5_tasks(self):
        tasks = suite_multi_step_planning()
        assert len(tasks) == 5
        for t in tasks:
            assert t.suite == "multi_step_planning"
            assert t.max_turns == 5
            assert t.grader is not None

    def test_get_all_tasks_returns_15(self):
        tasks = get_all_tasks()
        assert len(tasks) == 15
        ids = [t.task_id for t in tasks]
        assert len(ids) == len(set(ids)), "duplicate task_ids"

    def test_task_ids_are_unique_across_suites(self):
        tasks = get_all_tasks()
        ids = [t.task_id for t in tasks]
        assert len(ids) == len(set(ids))

    def test_each_task_has_nonempty_description(self):
        for t in get_all_tasks():
            assert len(t.description) > 20, f"{t.task_id} has short description"

    def test_code_generation_tasks_have_code_executor_tool(self):
        for t in suite_code_generation():
            tool_names = [tool["function"]["name"] for tool in t.tools]
            assert "code_executor" in tool_names

    def test_tool_use_tasks_have_calculator_or_search(self):
        for t in suite_tool_use():
            tool_names = [tool["function"]["name"] for tool in t.tools]
            assert "calculator" in tool_names or "search" in tool_names

    def test_planning_tasks_have_tools(self):
        for t in suite_multi_step_planning():
            assert len(t.tools) > 0, f"{t.task_id} has no tools"


# ---------------------------------------------------------------------------
# Grader tests
# ---------------------------------------------------------------------------

class TestCodeGenGrader:
    def test_correct_function_passes(self):
        tasks = suite_code_generation()
        grader = tasks[0].grader
        passed, detail = grader("def add(a, b): return a + b", tasks[0].expected_state)
        assert passed is True

    def test_wrong_function_fails(self):
        tasks = suite_code_generation()
        grader = tasks[0].grader
        passed, detail = grader("def add(a, b): return a - b", tasks[0].expected_state)
        assert passed is False

    def test_factorial_task_graded_on_output(self):
        tasks = suite_code_generation()
        factorial_task = next(t for t in tasks if t.task_id == "mt-cg-03")
        passed, _ = factorial_task.grader("def factorial(n):\n    result = 1\n    for i in range(1, n+1):\n        result *= i\n    return result\n# test: 120", factorial_task.expected_state)
        assert passed is True


class TestToolUseGrader:
    def test_correct_answer_passes(self):
        tasks = suite_tool_use()
        paris_task = next(t for t in tasks if t.task_id == "mt-tu-01")
        passed, _ = paris_task.grader("The capital of France is Paris.", paris_task.expected_state)
        assert passed is True

    def test_wrong_answer_fails(self):
        tasks = suite_tool_use()
        paris_task = next(t for t in tasks if t.task_id == "mt-tu-01")
        passed, _ = paris_task.grader("The capital of France is London.", paris_task.expected_state)
        assert passed is False

    def test_calc_task_graded_on_result(self):
        tasks = suite_tool_use()
        calc_task = next(t for t in tasks if t.task_id == "mt-tu-02")
        passed, _ = calc_task.grader("15 * 23 = 345", calc_task.expected_state)
        assert passed is True


class TestPlanningGrader:
    def test_multi_substring_passes(self):
        tasks = suite_multi_step_planning()
        capitals_task = next(t for t in tasks if t.task_id == "mt-mp-01")
        passed, detail = capitals_task.grader(
            "Paris is the capital of France. Tokyo is the capital of Japan.",
            capitals_task.expected_state,
        )
        assert passed is True

    def test_missing_substring_fails(self):
        tasks = suite_multi_step_planning()
        capitals_task = next(t for t in tasks if t.task_id == "mt-mp-01")
        passed, detail = capitals_task.grader(
            "Paris is the capital of France.",
            capitals_task.expected_state,
        )
        assert passed is False
        assert "Tokyo" in detail

    def test_calc_planning_graded_on_result(self):
        tasks = suite_multi_step_planning()
        calc_task = next(t for t in tasks if t.task_id == "mt-mp-02")
        passed, _ = calc_task.grader("100 + 400 = 500", calc_task.expected_state)
        assert passed is True


# ---------------------------------------------------------------------------
# Tool implementation tests
# ---------------------------------------------------------------------------

class TestCalculator:
    def test_simple_addition(self):
        assert tool_calculator("2 + 3") == "5"

    def test_multiplication(self):
        assert tool_calculator("15 * 23") == "345"

    def test_order_of_operations(self):
        assert tool_calculator("2 + 3 * 4") == "14"

    def test_parentheses(self):
        assert tool_calculator("(2 + 3) * 4") == "20"

    def test_division(self):
        assert tool_calculator("10 / 2") == "5"

    def test_float_division(self):
        assert tool_calculator("7 / 2") == "3.5"

    def test_power(self):
        assert tool_calculator("2 ** 10") == "1024"

    def test_negative_number(self):
        assert tool_calculator("-5 + 10") == "5"

    def test_unsafe_input_rejected(self):
        with pytest.raises(Exception):
            tool_calculator("__import__('os').system('echo hacked')")

    def test_empty_input_rejected(self):
        with pytest.raises(Exception):
            tool_calculator("")


class TestCodeExecutor:
    def test_simple_print(self):
        result = tool_code_executor("print('hello')")
        assert result == "hello"

    def test_arithmetic(self):
        result = tool_code_executor("print(2 + 3)")
        assert result == "5"

    def test_function_def_and_call(self):
        result = tool_code_executor("def f(x): return x * 2\nprint(f(5))")
        assert result == "10"

    def test_error_output(self):
        result = tool_code_executor("print(undefined_var)")
        assert "error" in result.lower()

    def test_syntax_error(self):
        result = tool_code_executor("def broken(")
        assert "error" in result.lower()

    def test_no_output(self):
        result = tool_code_executor("x = 5")
        assert "no output" in result.lower()

    def test_timeout_protection(self):
        result = tool_code_executor("while True: pass")
        assert "timed out" in result.lower()


class TestSearch:
    def test_known_query(self):
        result = tool_search("capital of france")
        assert result == "Paris"

    def test_case_insensitive(self):
        result = tool_search("CAPITAL OF JAPAN")
        assert result == "Tokyo"

    def test_unknown_query(self):
        result = tool_search("what is the meaning of life")
        assert result == "no results found"

    def test_partial_match(self):
        result = tool_search("height of mount everest")
        assert "8848" in result

    def test_search_db_has_expected_entries(self):
        from benchmarks.run_multiturn_bench import _SEARCH_DB
        assert "capital of france" in _SEARCH_DB
        assert len(_SEARCH_DB) >= 10


# ---------------------------------------------------------------------------
# Tool schema tests
# ---------------------------------------------------------------------------

class TestToolSchemas:
    def test_calculator_schema_structure(self):
        assert CALCULATOR_SCHEMA["type"] == "function"
        fn = CALCULATOR_SCHEMA["function"]
        assert fn["name"] == "calculator"
        assert "expression" in fn["parameters"]["properties"]

    def test_code_executor_schema_structure(self):
        assert CODE_EXECUTOR_SCHEMA["type"] == "function"
        fn = CODE_EXECUTOR_SCHEMA["function"]
        assert fn["name"] == "code_executor"
        assert "code" in fn["parameters"]["properties"]

    def test_search_schema_structure(self):
        assert SEARCH_SCHEMA["type"] == "function"
        fn = SEARCH_SCHEMA["function"]
        assert fn["name"] == "search"
        assert "query" in fn["parameters"]["properties"]

    def test_tool_implementations_cover_all_schemas(self):
        assert "calculator" in TOOL_IMPLEMENTATIONS
        assert "code_executor" in TOOL_IMPLEMENTATIONS
        assert "search" in TOOL_IMPLEMENTATIONS
        for name, impl in TOOL_IMPLEMENTATIONS.items():
            assert callable(impl)


# ---------------------------------------------------------------------------
# Result dataclass tests
# ---------------------------------------------------------------------------

class TestMultiTurnResult:
    def test_default_values(self):
        r = MultiTurnResult(
            task_id="test-1", suite="test", arm="classic", trial=0, passed=False
        )
        assert r.task_id == "test-1"
        assert r.arm == "classic"
        assert r.trial == 0
        assert r.passed is False
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.total_tokens == 0
        assert r.turns == 0
        assert r.turns_to_completion == 0
        assert r.failure_class == "none"
        assert r.final_answer == ""
        assert r.per_turn_quality == []
        assert r.error_recovery is False

    def test_can_set_all_fields(self):
        r = MultiTurnResult(
            task_id="t1", suite="s1", arm="tahoe", trial=2, passed=True,
            grader_detail="ok", input_tokens=100, output_tokens=50,
            total_tokens=150, wall_seconds=1.5, turns=3,
            turns_to_completion=2, failure_class="none",
            final_answer="42", per_turn_quality=[False, True, True],
            error_recovery=True,
        )
        assert r.total_tokens == 150
        assert r.turns == 3
        assert r.error_recovery is True


# ---------------------------------------------------------------------------
# Trial count tests
# ---------------------------------------------------------------------------

class TestTrialCounts:
    def test_two_arms(self):
        assert ARMS == ["classic", "tahoe"]

    def test_three_trials(self):
        assert TRIALS_PER_TASK == 3

    def test_total_trial_count(self):
        total = total_trial_count()
        assert total == 15 * 2 * 3  # 90


# ---------------------------------------------------------------------------
# Metrics aggregation tests
# ---------------------------------------------------------------------------

class TestAggregateMetrics:
    def _make_results(self, n=6):
        results = []
        for i in range(n):
            results.append(MultiTurnResult(
                task_id=f"t{i}", suite="code_generation",
                arm="classic" if i % 2 == 0 else "tahoe",
                trial=i // 2, passed=i % 3 == 0,
                total_tokens=100 + i, turns=2 + (i % 2),
                turns_to_completion=2 if i % 3 == 0 else 0,
                error_recovery=i % 4 == 0,
            ))
        return results

    def test_aggregate_returns_suites_and_overall(self):
        results = self._make_results()
        agg = aggregate_metrics(results)
        assert "suites" in agg
        assert "overall" in agg

    def test_aggregate_has_all_suites(self):
        results = self._make_results()
        agg = aggregate_metrics(results)
        # Only code_generation has data in mock
        assert "code_generation" in agg["suites"]

    def test_overall_has_both_arms(self):
        results = self._make_results()
        agg = aggregate_metrics(results)
        assert "classic" in agg["overall"]
        assert "tahoe" in agg["overall"]

    def test_pass_rate_calculated(self):
        results = self._make_results(6)
        agg = aggregate_metrics(results)
        classic_stats = agg["overall"]["classic"]
        assert 0.0 <= classic_stats["pass_rate"] <= 1.0

    def test_empty_results_handled(self):
        agg = aggregate_metrics([])
        for suite_name in SUITES:
            assert suite_name in agg["suites"]
        for arm in ARMS:
            assert arm in agg["overall"]


# ---------------------------------------------------------------------------
# Mock runner test (no API calls)
# ---------------------------------------------------------------------------

class TestRunMultiturnTrial:
    def _fake_response(self, content=None, tool_calls=None, pt=10, ct=5):
        message = SimpleNamespace(content=content, tool_calls=tool_calls)
        usage = SimpleNamespace(prompt_tokens=pt, completion_tokens=ct)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    def _fake_tool_call(self, name="search", arguments='{"query": "capital of france"}'):
        return SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name=name, arguments=arguments),
        )

    def _fake_openai(self, responses):
        import types as _types
        fake = _types.ModuleType("openai")
        fake.APIError = type("APIError", (Exception,), {})
        fake.APITimeoutError = type("APITimeoutError", (Exception,), {})

        call_count = [0]

        class _Completions:
            def create(self, **kwargs):
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(responses):
                    r = responses[idx]
                    if isinstance(r, BaseException):
                        raise r
                    return r
                return self._default()

            def _default(self):
                return self._fake_response(content="default")

        class _Chat:
            def __init__(self):
                self.completions = _Completions()

        class _Client:
            def __init__(self):
                self.chat = _Chat()

        fake.OpenAI = lambda **kw: _Client()
        return fake

    def test_tool_use_trial_runs_with_mock(self):
        responses = [
            self._fake_response(
                tool_calls=[self._fake_tool_call(
                    name="search",
                    arguments='{"query": "capital of france"}'
                )],
            ),
            self._fake_response(content="The capital of France is Paris."),
        ]
        fake_openai = self._fake_openai(responses)

        tasks = suite_tool_use()
        task = next(t for t in tasks if t.task_id == "mt-tu-01")

        with mock.patch.dict(os.environ, {"TAHOE_API_KEY": "test-key"}, clear=False):
            with mock.patch.dict(sys.modules, {"openai": fake_openai}):
                result = run_multiturn_trial(task, "classic", 0)

        assert result.task_id == "mt-tu-01"
        assert result.arm == "classic"
        assert result.trial == 0
        assert result.turns == 2
        assert result.passed is True

    def test_tahoe_arm_loads_skill_prompt(self):
        responses = [self._fake_response(content="Paris")]
        fake_openai = self._fake_openai(responses)

        tasks = suite_tool_use()
        task = next(t for t in tasks if t.task_id == "mt-tu-01")

        with mock.patch.dict(os.environ, {"TAHOE_API_KEY": "test-key"}, clear=False):
            with mock.patch.dict(sys.modules, {"openai": fake_openai}):
                result = run_multiturn_trial(task, "tahoe", 0)

        assert result.arm == "tahoe"
        assert result.passed is True

    def test_code_gen_trial_with_mock(self):
        responses = [
            self._fake_response(
                tool_calls=[self._fake_tool_call(
                    name="code_executor",
                    arguments='{"code": "def add(a, b): return a + b\\nprint(add(1, 2))"}'
                )],
            ),
            self._fake_response(content="def add(a, b): return a + b"),
        ]
        fake_openai = self._fake_openai(responses)

        tasks = suite_code_generation()
        task = tasks[0]  # mt-cg-01

        with mock.patch.dict(os.environ, {"TAHOE_API_KEY": "test-key"}, clear=False):
            with mock.patch.dict(sys.modules, {"openai": fake_openai}):
                result = run_multiturn_trial(task, "classic", 0)

        assert result.task_id == "mt-cg-01"
        assert result.passed is True
        assert result.turns == 2

    def test_grader_fails_on_wrong_answer(self):
        responses = [self._fake_response(content="The capital is London.")]
        fake_openai = self._fake_openai(responses)

        tasks = suite_tool_use()
        task = next(t for t in tasks if t.task_id == "mt-tu-01")

        with mock.patch.dict(os.environ, {"TAHOE_API_KEY": "test-key"}, clear=False):
            with mock.patch.dict(sys.modules, {"openai": fake_openai}):
                result = run_multiturn_trial(task, "classic", 0)

        assert result.passed is False
        assert "Paris" not in result.final_answer
