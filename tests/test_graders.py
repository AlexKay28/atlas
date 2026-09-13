"""Tests for eval/graders.py: pass/fail cases per grader type, the factory,
and composite behavior with mixed pass/fail."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.graders import (
    CompositeGrader,
    ContainsGrader,
    ExactMatchGrader,
    JSONFieldGrader,
    TestPassGrader,
    make_grader,
)


class TestExactMatchGrader:
    def test_pass(self):
        grader = ExactMatchGrader()
        passed, detail = grader("Route 3, total cost: 16", {"answer": "Route 3, total cost: 16"})
        assert passed is True
        assert "exact match" in detail

    def test_fail(self):
        grader = ExactMatchGrader()
        passed, detail = grader("Route 3, cost 16", {"answer": "Route 3, total cost: 16"})
        assert passed is False
        assert "Route 3, total cost: 16" in detail

    def test_missing_answer_key_fails(self):
        grader = ExactMatchGrader()
        passed, _ = grader("anything", {})
        assert passed is False

    def test_type_mismatch_fails(self):
        grader = ExactMatchGrader()
        passed, _ = grader(3, {"answer": "3"})
        assert passed is False


class TestContainsGrader:
    def test_pass(self):
        grader = ContainsGrader()
        passed, detail = grader("def add(a, b): return a + b", {"substring": "return a + b"})
        assert passed is True

    def test_fail(self):
        grader = ContainsGrader()
        passed, detail = grader("def add(a, b): return a - b", {"substring": "return a + b"})
        assert passed is False
        assert "return a + b" in detail

    def test_missing_substring_key_fails(self):
        grader = ContainsGrader()
        passed, _ = grader("some text", {})
        assert passed is False

    def test_non_string_result_is_coerced(self):
        grader = ContainsGrader()
        passed, _ = grader(12345, {"substring": "234"})
        assert passed is True


class TestJSONFieldGrader:
    def test_pass(self):
        grader = JSONFieldGrader()
        passed, _ = grader('{"subtask_count": 5}', {"field": "subtask_count", "value": 5})
        assert passed is True

    def test_wrong_value_fails(self):
        grader = JSONFieldGrader()
        passed, detail = grader('{"subtask_count": 4}', {"field": "subtask_count", "value": 5})
        assert passed is False
        assert "subtask_count" in detail

    def test_missing_field_fails(self):
        grader = JSONFieldGrader()
        passed, _ = grader('{"other": 5}', {"field": "subtask_count", "value": 5})
        assert passed is False

    def test_invalid_json_fails(self):
        grader = JSONFieldGrader()
        passed, detail = grader("not json at all", {"field": "subtask_count", "value": 5})
        assert passed is False
        assert "JSON" in detail

    def test_non_object_json_fails(self):
        grader = JSONFieldGrader()
        passed, _ = grader("[1, 2, 3]", {"field": "subtask_count", "value": 5})
        assert passed is False

    def test_pre_parsed_dict_result_passes(self):
        grader = JSONFieldGrader()
        passed, _ = grader({"subtask_count": 5}, {"field": "subtask_count", "value": 5})
        assert passed is True


class TestTestPassGrader:
    def test_pass(self):
        grader = TestPassGrader()
        passed, detail = grader("ignored result", {"test_cmd": "true"})
        assert passed is True
        assert "0" in detail

    def test_fail(self):
        grader = TestPassGrader()
        passed, detail = grader("ignored result", {"test_cmd": "exit 3"})
        assert passed is False
        assert "3" in detail

    def test_missing_test_cmd_fails(self):
        grader = TestPassGrader()
        passed, _ = grader("ignored result", {})
        assert passed is False

    def test_output_tail_included_on_failure(self):
        grader = TestPassGrader()
        passed, detail = grader("ignored result", {"test_cmd": "echo boom >&2; exit 1"})
        assert passed is False
        assert "boom" in detail


class TestCompositeGrader:
    def test_all_pass(self):
        grader = CompositeGrader([ContainsGrader(), ExactMatchGrader()])
        passed, detail = grader(
            "Route 3, total cost: 16",
            {"substring": "Route 3", "answer": "Route 3, total cost: 16"},
        )
        assert passed is True
        assert "FAIL" not in detail

    def test_mixed_pass_fail(self):
        grader = CompositeGrader([ContainsGrader(), ExactMatchGrader()])
        passed, detail = grader("the answer is 3", {"substring": "3", "answer": "3"})
        assert passed is False
        assert "ContainsGrader: PASS" in detail
        assert "ExactMatchGrader: FAIL" in detail

    def test_all_fail(self):
        grader = CompositeGrader([ExactMatchGrader(), ContainsGrader()])
        passed, _ = grader("nope", {"answer": "yes", "substring": "yes"})
        assert passed is False

    def test_sub_graders_from_expected_state_strings(self):
        grader = CompositeGrader()
        passed, detail = grader(
            "y = x * c",
            {"graders": ["contains"], "substring": "y = x * c"},
        )
        assert passed is True
        assert "ContainsGrader: PASS" in detail

    def test_sub_grader_dict_spec_merges_params(self):
        grader = CompositeGrader()
        passed, _ = grader(
            '{"subtask_count": 5}',
            {
                "graders": [
                    {"type": "json_field", "params": {"field": "subtask_count", "value": 5}}
                ],
                "field": "ignored_outer",
                "value": None,
            },
        )
        assert passed is True

    def test_single_callable_in_constructor(self):
        grader = CompositeGrader(ContainsGrader())
        passed, _ = grader("has Resume inside", {"substring": "Resume"})
        assert passed is True

    def test_no_sub_graders_fails(self):
        grader = CompositeGrader()
        passed, detail = grader("x", {})
        assert passed is False
        assert "no sub-graders" in detail

    def test_invalid_spec_fails(self):
        grader = CompositeGrader([42])
        passed, _ = grader("x", {})
        assert passed is False

    def test_unknown_sub_grader_type_fails(self):
        grader = CompositeGrader(["bogus_type"])
        passed, detail = grader("x", {})
        assert passed is False
        assert "bogus_type" in detail


class TestMakeGrader:
    @pytest.mark.parametrize(
        "name, cls",
        [
            ("exact_match", ExactMatchGrader),
            ("contains", ContainsGrader),
            ("json_field", JSONFieldGrader),
            ("test_pass", TestPassGrader),
            ("composite", CompositeGrader),
        ],
    )
    def test_factory_builds_each_type(self, name, cls):
        grader = make_grader(name)
        assert isinstance(grader, cls)
        assert callable(grader)

    def test_factory_unknown_type_raises(self):
        with pytest.raises(ValueError, match="bogus"):
            make_grader("bogus")
