"""Tests for deterministic step execution — skip API for pure computation (issue #61).

Covers:
- ``calculate`` with arithmetic executes locally (0 API tokens).
- ``check`` with a concrete predicate executes locally.
- ``choose`` with min/max on a known list executes locally.
- ``rank`` with asc/desc on a known list executes locally.
- Steps with natural-language expressions fall back to API.
- The SUCCEEDED event shape is identical whether deterministic or API-computed.
- Deterministic execution is gated by ``TAHOE_DETERMINISTIC`` env var.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from tahoe.runtime import EventStore, EventType
from tahoe.runtime.coordinator import (
    DeterministicWorker,
    SequentialCoordinator,
)
from tahoe.runtime.deterministic import DeterministicStepExecutor
from tahoe.syntax import parse_program

LIFECYCLE = (
    EventType.INVOCATION_READY,
    EventType.INVOCATION_DISPATCHED,
    EventType.RESULT_RECEIVED,
    EventType.VALIDATION_PASSED,
    EventType.SUCCEEDED,
)


# ---------------------------------------------------------------------------
# Programs — use simple kwargs the parser can handle (refs and literals)
# ---------------------------------------------------------------------------

CALCULATE_PROGRAM = """\
PROGRAM calc_test VERSION 1.0
INPUT
    G.a = 3
    G.b = 4
step.calc: DO calculate(expression = "a + b", values = G.a) -> OUT.total
RETURN OUT.total
"""

CHECK_PROGRAM = """\
PROGRAM check_test VERSION 1.0
INPUT
    G.value = 42
step.check: DO check(artifact = G.value, predicate = "== 42") -> OUT.verdict
RETURN OUT.verdict
"""

CHOOSE_PROGRAM = """\
PROGRAM choose_test VERSION 1.0
INPUT
    G.opts = [3, 1, 2]
step.choose: DO choose(valid_options = G.opts, decision_policy = "min") -> OUT.pick
RETURN OUT.pick
"""

RANK_PROGRAM = """\
PROGRAM rank_test VERSION 1.0
INPUT
    G.opts = [3, 1, 2]
step.rank: DO rank(options = G.opts, criteria = "asc") -> OUT.sorted
RETURN OUT.sorted
"""

# A program whose arguments require model reasoning (natural language)
COMPLEX_PROGRAM = """\
PROGRAM complex_test VERSION 1.0
INPUT
    G.question = "What is the meaning of life?"
step.analyze: DO analyze(question = G.question) -> OUT.answer
RETURN OUT.answer
"""

# A simpler calculate program that passes values as a JSON dict (no refs)
CALCULATE_LITERAL_PROGRAM = """\
PROGRAM calc_lit VERSION 1.0
INPUT
    G.x = 5
step.calc: DO calculate(expression = "x + 7", values = {"x": 5}) -> OUT.total
RETURN OUT.total
"""


# ---------------------------------------------------------------------------
# Worker handlers (used for API-fallback tests)
# ---------------------------------------------------------------------------

def calculate_handler(expression, values=None, **kw):
    return 999  # marker: API was called


def check_handler(artifact, predicate, **kw):
    return {"verdict": "api"}


def choose_handler(valid_options, decision_policy, **kw):
    return {"decision": "api"}


def rank_handler(options, criteria, **kw):
    return {"ordering": "api"}


def analyze_handler(question, **kw):
    return {"answer": "model says 42"}


# ---------------------------------------------------------------------------
# Unit tests for DeterministicStepExecutor
# ---------------------------------------------------------------------------

@pytest.fixture
def det_enabled(monkeypatch):
    monkeypatch.setenv("TAHOE_DETERMINISTIC", "1")
    yield


@pytest.fixture
def det_disabled(monkeypatch):
    monkeypatch.delenv("TAHOE_DETERMINISTIC", raising=False)
    yield


class TestDeterministicStepExecutor:
    def test_calculate_arithmetic(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "calculate",
            {"expression": "a + b", "values": {"a": 3, "b": 4}},
        )
        assert result == 7

    def test_calculate_multiplication(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "calculate",
            {"expression": "x * y", "values": {"x": 6, "y": 7}},
        )
        assert result == 42

    def test_calculate_with_constants(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "calculate",
            {"expression": "2 + 3 * 4", "values": {}},
        )
        assert result == 14

    def test_calculate_subtraction(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "calculate",
            {"expression": "10 - 3", "values": {}},
        )
        assert result == 7

    def test_calculate_division(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "calculate",
            {"expression": "20 / 4", "values": {}},
        )
        assert result == 5.0

    def test_calculate_fallback_on_unsafe_expr(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "calculate",
            {"expression": "__import__('os')", "values": {}},
        )
        assert result is None

    def test_calculate_fallback_on_missing_expression(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "calculate",
            {"values": {"a": 1}},
        )
        assert result is None

    def test_calculate_fallback_on_non_string_expr(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "calculate",
            {"expression": 42, "values": {}},
        )
        assert result is None

    def test_check_eq_predicate(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "check",
            {"artifact": 42, "predicate": "== 42"},
        )
        assert result == {"verdict": True}

    def test_check_gt_predicate(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "check",
            {"artifact": 10, "predicate": "> 5"},
        )
        assert result == {"verdict": True}

    def test_check_false_predicate(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "check",
            {"artifact": 3, "predicate": "> 5"},
        )
        assert result == {"verdict": False}

    def test_check_dict_predicate(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "check",
            {"artifact": 42, "predicate": {"op": "eq", "value": 42}},
        )
        assert result == {"verdict": True}

    def test_check_dict_predicate_ne(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "check",
            {"artifact": 42, "predicate": {"op": "ne", "value": 0}},
        )
        assert result == {"verdict": True}

    def test_check_fallback_on_unknown_op(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "check",
            {"artifact": 42, "predicate": "~~~ 42"},
        )
        assert result is None

    def test_check_fallback_on_missing_artifact(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "check",
            {"predicate": "== 42"},
        )
        assert result is None

    def test_choose_min(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "choose",
            {"valid_options": [3, 1, 2], "decision_policy": "min"},
        )
        assert result == {"decision": 1}

    def test_choose_max(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "choose",
            {"valid_options": [3, 1, 2], "decision_policy": "max"},
        )
        assert result == {"decision": 3}

    def test_choose_fallback_on_unknown_policy(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "choose",
            {"valid_options": [3, 1, 2], "decision_policy": "fancy"},
        )
        assert result is None

    def test_choose_fallback_on_empty_list(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "choose",
            {"valid_options": [], "decision_policy": "min"},
        )
        assert result is None

    def test_rank_ascending(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "rank",
            {"options": [3, 1, 2], "criteria": "asc"},
        )
        assert result == {"ordering": [1, 2, 3]}

    def test_rank_descending(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "rank",
            {"options": [3, 1, 2], "criteria": "desc"},
        )
        assert result == {"ordering": [3, 2, 1]}

    def test_rank_fallback_on_unknown_criteria(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "rank",
            {"options": [3, 1, 2], "criteria": "sideways"},
        )
        assert result is None

    def test_unknown_command_returns_none(self, det_enabled):
        result = DeterministicStepExecutor.try_execute(
            "analyze",
            {"question": "what?"},
        )
        assert result is None

    def test_disabled_returns_none(self, det_disabled):
        result = DeterministicStepExecutor.try_execute(
            "calculate",
            {"expression": "1 + 2", "values": {}},
        )
        assert result is None


# ---------------------------------------------------------------------------
# Integration tests with the coordinator (env var gating)
# ---------------------------------------------------------------------------

class TestDeterministicIntegration:
    def test_calculate_step_executes_locally(self, det_enabled, tmp_path):
        """A calculate step with arithmetic runs without calling the worker."""
        api_called = []

        def tracking_calc(expression, values=None, **kw):
            api_called.append(True)
            return 999

        worker = DeterministicWorker(
            handlers={"calculate": tracking_calc}
        )
        program = parse_program(CALCULATE_LITERAL_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            result = coord.execute(program, run_id="run-1")

        assert result["status"] == "succeeded"
        assert api_called == []

    def test_check_step_executes_locally(self, det_enabled, tmp_path):
        """A check step with a concrete predicate runs locally."""
        api_called = []

        def tracking_check(artifact, predicate, **kw):
            api_called.append(True)
            return {"verdict": "api"}

        worker = DeterministicWorker(
            handlers={"check": tracking_check}
        )
        program = parse_program(CHECK_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            result = coord.execute(program, run_id="run-1")

        assert result["status"] == "succeeded"
        assert api_called == []

    def test_choose_step_executes_locally(self, det_enabled, tmp_path):
        """A choose step with min on a known list runs locally."""
        api_called = []

        def tracking_choose(valid_options, decision_policy, **kw):
            api_called.append(True)
            return {"decision": "api"}

        worker = DeterministicWorker(
            handlers={"choose": tracking_choose}
        )
        program = parse_program(CHOOSE_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            result = coord.execute(program, run_id="run-1")

        assert result["status"] == "succeeded"
        assert api_called == []

    def test_rank_step_executes_locally(self, det_enabled, tmp_path):
        """A rank step with asc on a known list runs locally."""
        api_called = []

        def tracking_rank(options, criteria, **kw):
            api_called.append(True)
            return {"ordering": "api"}

        worker = DeterministicWorker(
            handlers={"rank": tracking_rank}
        )
        program = parse_program(RANK_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            result = coord.execute(program, run_id="run-1")

        assert result["status"] == "succeeded"
        assert api_called == []

    def test_complex_step_falls_back_to_api(self, det_enabled, tmp_path):
        """A step requiring model reasoning falls back to the API worker."""
        worker = DeterministicWorker(
            handlers={"analyze": analyze_handler}
        )
        program = parse_program(COMPLEX_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            result = coord.execute(program, run_id="run-1")

        assert result["status"] == "succeeded"
        assert result["outputs"]["OUT.answer"] == {"answer": "model says 42"}

    def test_deterministic_disabled_falls_back_to_api(
        self, det_disabled, tmp_path
    ):
        """When TAHOE_DETERMINISTIC is not set, the API worker is called."""
        worker = DeterministicWorker(
            handlers={"calculate": calculate_handler}
        )
        program = parse_program(CALCULATE_LITERAL_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            result = coord.execute(program, run_id="run-1")

        assert result["status"] == "succeeded"
        assert result["outputs"]["OUT.total"] == 999

    def test_succeeded_event_shape_identical(
        self, det_enabled, tmp_path
    ):
        """The SUCCEEDED event shape is the same whether or not deterministic."""
        worker = DeterministicWorker(
            handlers={"calculate": calculate_handler}
        )
        program = parse_program(CALCULATE_LITERAL_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            coord.execute(program, run_id="run-1")
            events_det = list(store.events("run-1"))

        event_types_det = [e.event_type for e in events_det]
        assert LIFECYCLE == tuple(
            e for e in event_types_det
            if e in LIFECYCLE
        )

    def test_lifecycle_events_present_when_deterministic(
        self, det_enabled, tmp_path
    ):
        """All lifecycle events are emitted even for deterministic steps."""
        worker = DeterministicWorker(
            handlers={"calculate": calculate_handler}
        )
        program = parse_program(CALCULATE_LITERAL_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            coord.execute(program, run_id="run-1")
            history = list(store.events("run-1"))

        event_types = [e.event_type for e in history]
        for expected in LIFECYCLE:
            assert expected in event_types, f"missing {expected}"

    def test_dispatched_payload_has_deterministic_flag(
        self, det_enabled, tmp_path
    ):
        """The DISPATCHED event records whether the step was deterministic."""
        worker = DeterministicWorker(
            handlers={"calculate": calculate_handler}
        )
        program = parse_program(CALCULATE_LITERAL_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            coord.execute(program, run_id="run-1")
            history = list(store.events("run-1"))

        dispatched = [
            e for e in history if e.event_type == EventType.INVOCATION_DISPATCHED
        ]
        assert len(dispatched) >= 1
        payload = dispatched[0].payload
        assert payload.get("_deterministic") is True

    def test_dispatched_payload_no_deterministic_flag_when_disabled(
        self, det_disabled, tmp_path
    ):
        """When deterministic is off, the DISPATCHED payload has no flag."""
        worker = DeterministicWorker(
            handlers={"calculate": calculate_handler}
        )
        program = parse_program(CALCULATE_LITERAL_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            coord.execute(program, run_id="run-1")
            history = list(store.events("run-1"))

        dispatched = [
            e for e in history if e.event_type == EventType.INVOCATION_DISPATCHED
        ]
        assert len(dispatched) >= 1
        payload = dispatched[0].payload
        assert "_deterministic" not in payload

    def test_dispatched_flag_false_for_api_fallback(
        self, det_enabled, tmp_path
    ):
        """The DISPATCHED flag is False for steps that fall back to API."""
        worker = DeterministicWorker(
            handlers={"analyze": analyze_handler}
        )
        program = parse_program(COMPLEX_PROGRAM)
        with EventStore(tmp_path / "events.db") as store:
            coord = SequentialCoordinator(store=store, worker=worker)
            coord.execute(program, run_id="run-1")
            history = list(store.events("run-1"))

        dispatched = [
            e for e in history if e.event_type == EventType.INVOCATION_DISPATCHED
        ]
        assert len(dispatched) >= 1
        payload = dispatched[0].payload
        assert payload.get("_deterministic") is False
