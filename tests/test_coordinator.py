"""Tests specifying the deterministic sequential coordinator contract.

Covers docs/spec/03-runtime-and-events.md: the invocation lifecycle event
order, nonempty ``task_id`` binding on every invocation event, full ledger
completion accounting, failure recording without false completion, unknown
command rejection before run creation, STOP-terminal runs (``blocked`` with
a recorded reason, ``completed``), multi-target commits keyed by handler
mapping leaf names, and missing-key multi-target results failing coherently
without committing ``None`` or stranding a task. Also covers non-mapping
results, duplicate target leaves, truthful validation ordering, and cancellation
of future tasks after terminal failure. Deterministic replay of state and task
ledger after SQLite reopen.
``tikhon.runtime.coordinator`` is
specified by these tests before implementation.
"""

from typing import Any

import pytest

from tikhon.memory import KnowledgeBase
from tikhon.runtime import EventStore, EventType
from tikhon.runtime.coordinator import (
    DeterministicWorker,
    SequentialCoordinator,
    evaluate_condition,
    map_results_to_targets,
)
from tikhon.runtime.tasks import TaskStatus
from tikhon.syntax import ParseError, parse_program

CANONICAL_PROGRAM = """\
PROGRAM adder VERSION 1.0
INPUT
    G.left = 5
    G.right = 7
step.define: DO define(goal = G.left) -> G.goal
step.calculate: DO calculate(left = G.left, right = G.right) -> OUT.total
RETURN G.goal, OUT.total
"""

UNKNOWN_COMMAND_PROGRAM = """\
PROGRAM mystery VERSION 1.0
INPUT
    G.left = 1
step.magic: DO teleport(input = G.left) -> OUT.x
RETURN OUT.x
"""

BLOCKED_PROGRAM = """\
PROGRAM gatekeeper VERSION 1.0
INPUT
    U.reason = "waiting on approval"
step.prepare: DO define(goal = U.reason) -> G.goal
STOP blocked(U.reason)
"""

COMPLETED_PROGRAM = """\
PROGRAM finisher VERSION 1.0
INPUT
    G.note = "all done"
step.mark: DO define(goal = G.note) -> G.goal
STOP completed()
"""

SPLIT_PROGRAM = """\
PROGRAM splitter VERSION 1.0
INPUT
    G.left = 3
    G.right = 4
step.split: DO split_pair(left = G.left, right = G.right) -> OUT.summary, OUT.detail
RETURN OUT.summary, OUT.detail
"""

PARTIAL_SPLIT_PROGRAM = """\
PROGRAM partialsplit VERSION 1.0
INPUT
    G.left = 3
    G.right = 4
step.setup: DO define(goal = G.left) -> G.goal
step.split: DO split_pair(left = G.left, right = G.right) -> OUT.summary, OUT.detail
RETURN OUT.summary, OUT.detail
"""

EXPECTED_OUTPUTS = {
    "G.goal": {"goal": "add two inputs", "observed": 5},
    "OUT.total": 12,
}

LIFECYCLE = (
    EventType.INVOCATION_READY,
    EventType.INVOCATION_DISPATCHED,
    EventType.RESULT_RECEIVED,
    EventType.VALIDATION_PASSED,
    EventType.SUCCEEDED,
)

INVOCATION_EVENT_TYPES = set(LIFECYCLE) | {EventType.FAILED}


def define_handler(goal):
    return {"goal": "add two inputs", "observed": goal}


def calculate_handler(left, right):
    return left + right


def broken_calculate_handler(left, right):
    raise RuntimeError("boom")


def split_pair_handler(left, right):
    return {"summary": f"{left}+{right}", "detail": left * right}


def partial_split_pair_handler(left, right):
    return {"summary": f"{left}+{right}"}


def make_worker(calculate=calculate_handler):
    return DeterministicWorker(
        handlers={"define": define_handler, "calculate": calculate}
    )


def run_canonical(store, run_id="run-1", worker=None):
    program = parse_program(CANONICAL_PROGRAM)
    coordinator = SequentialCoordinator(store=store, worker=worker or make_worker())
    return coordinator.execute(program, run_id=run_id)


def events_by_invocation(history):
    grouped = {}
    for event in history:
        if event.invocation_id:
            grouped.setdefault(event.invocation_id, []).append(event)
    return grouped


def test_canonical_program_executes_to_state_nodes_and_outputs(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        result = run_canonical(store, run_id="run-1")

        assert result["run_id"] == "run-1"
        assert result["status"] == "succeeded"
        assert result["outputs"] == EXPECTED_OUTPUTS

        state = store.project_state("run-1")
        assert state["state_version"] == 2
        assert set(state["nodes"]) == {"G.goal", "OUT.total"}
        assert state["nodes"]["OUT.total"]["value"] == 12
        assert state["nodes"]["G.goal"]["value"] == EXPECTED_OUTPUTS["G.goal"]


def test_every_invocation_event_has_nonempty_task_id(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        run_canonical(store, run_id="run-1")
        history = store.events("run-1")
        ledger = store.task_ledger("run-1")

        bindings = {}
        for event in history:
            if event.event_type in INVOCATION_EVENT_TYPES:
                assert event.task_id
                assert event.invocation_id
                assert event.instruction_id.startswith("step.")
                bindings.setdefault(event.invocation_id, set()).add(event.task_id)

        assert len(bindings) == 2
        instructions = {
            event.instruction_id
            for event in history
            if event.event_type in INVOCATION_EVENT_TYPES
        }
        assert instructions == {"step.define", "step.calculate"}
        for task_ids in bindings.values():
            assert len(task_ids) == 1
        assert {next(iter(ids)) for ids in bindings.values()} <= set(ledger.tasks)


def test_task_ledger_ends_fully_complete(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        run_canonical(store, run_id="run-1")
        ledger = store.task_ledger("run-1")
        profile = ledger.profile()

        assert profile["percent_complete"] == 100.0
        assert profile["current_task"] is None
        assert profile["counts"]["total"] == 2
        assert profile["counts"]["completed"] == 2
        assert profile["counts"]["pending"] == 0
        assert profile["counts"]["in_progress"] == 0
        assert profile["counts"]["cancelled"] == 0
        for task in ledger.tasks.values():
            assert task.status is TaskStatus.COMPLETED
            assert task.evidence


def test_ledger_during_first_handler_already_has_all_step_tasks(tmp_path):
    captured = {}

    with EventStore(tmp_path / "events.db") as store:

        def probing_define_handler(goal):
            ledger = store.task_ledger("run-1")
            captured["profile"] = ledger.profile()
            captured["tasks"] = ledger.tasks
            return define_handler(goal)

        worker = DeterministicWorker(
            handlers={
                "define": probing_define_handler,
                "calculate": calculate_handler,
            }
        )
        result = run_canonical(store, run_id="run-1", worker=worker)

        assert result["status"] == "succeeded"

        tasks = captured["tasks"]
        profile = captured["profile"]

        assert len(tasks) == 2
        counts = profile["counts"]
        assert counts["total"] == 2
        assert counts["in_progress"] == 1
        assert counts["pending"] == 1
        current = profile["current_task"]
        assert current is not None
        assert "step.define" in tasks[current].text
        assert any("step.calculate" in task.text for task in tasks.values())
        assert profile["percent_complete"] == 0.0


def test_invocation_lifecycle_event_order(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        run_canonical(store, run_id="run-1")
        history = store.events("run-1")

        assert history[0].event_type is EventType.RUN_STARTED
        assert history[-1].event_type is EventType.RUN_FINISHED
        assert history[-1].payload["status"] == "succeeded"

        grouped = events_by_invocation(history)
        assert len(grouped) == 2
        for events in grouped.values():
            assert tuple(event.event_type for event in events) == LIFECYCLE


def test_command_failure_records_failed_and_run_finished(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = make_worker(calculate=broken_calculate_handler)
        result = run_canonical(store, run_id="run-fail", worker=worker)

        assert result["status"] == "failed"
        assert "boom" in result["error"]
        assert result["outputs"] == {}

        history = store.events("run-fail")
        assert history[-1].event_type is EventType.RUN_FINISHED
        assert history[-1].payload["status"] == "failed"

        failed = [event for event in history if event.event_type is EventType.FAILED]
        assert len(failed) == 1
        assert failed[0].instruction_id == "step.calculate"
        assert "boom" in str(failed[0].payload)

        grouped = events_by_invocation(history)
        calc = [
            events
            for events in grouped.values()
            if events[0].instruction_id == "step.calculate"
        ]
        assert len(calc) == 1
        assert tuple(event.event_type for event in calc[0]) == (
            EventType.INVOCATION_READY,
            EventType.INVOCATION_DISPATCHED,
            EventType.FAILED,
        )

        state = store.project_state("run-fail")
        assert state["state_version"] == 1
        assert set(state["nodes"]) == {"G.goal"}

        ledger = store.task_ledger("run-fail")
        profile = ledger.profile()
        assert profile["percent_complete"] == 50.0
        assert profile["current_task"] is None
        assert profile["counts"]["in_progress"] == 0
        failed_task = ledger.tasks[failed[0].task_id]
        assert failed_task.status is TaskStatus.CANCELLED
        assert not failed_task.evidence
        completed = [
            task for task in ledger.tasks.values() if task.status is TaskStatus.COMPLETED
        ]
        assert len(completed) == 1
        assert completed[0].evidence


def test_stop_blocked_records_blocked_run_finished_with_reason(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(BLOCKED_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())
        result = coordinator.execute(program, run_id="run-blocked")

        assert result["status"] == "blocked"
        assert result["outputs"] == {}

        history = store.events("run-blocked")
        assert history[-1].event_type is EventType.RUN_FINISHED
        assert history[-1].payload["status"] == "blocked"
        assert history[-1].payload["reason"] == "waiting on approval"


def test_stop_completed_returns_succeeded(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(COMPLETED_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())
        result = coordinator.execute(program, run_id="run-done")

        assert result["status"] == "succeeded"
        assert result["outputs"] == {}

        history = store.events("run-done")
        assert history[-1].event_type is EventType.RUN_FINISHED
        assert history[-1].payload["status"] == "succeeded"


def test_multi_target_commit_from_mapping_by_leaf_name(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(
            handlers={"define": define_handler, "split_pair": split_pair_handler}
        )
        program = parse_program(SPLIT_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=worker)
        result = coordinator.execute(program, run_id="run-split")

        assert result["status"] == "succeeded"
        assert result["outputs"] == {
            "OUT.summary": "3+4",
            "OUT.detail": 12,
        }

        state = store.project_state("run-split")
        assert state["state_version"] == 1
        assert set(state["nodes"]) == {"OUT.summary", "OUT.detail"}
        assert state["nodes"]["OUT.summary"]["value"] == "3+4"
        assert state["nodes"]["OUT.detail"]["value"] == 12


def test_missing_mapping_key_fails_run_without_none_or_stuck_task(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(
            handlers={
                "define": define_handler,
                "split_pair": partial_split_pair_handler,
            }
        )
        program = parse_program(PARTIAL_SPLIT_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=worker)
        result = coordinator.execute(program, run_id="run-partial")

        assert result["status"] == "failed"
        assert "detail" in result["error"]
        assert result["outputs"] == {}

        history = store.events("run-partial")
        assert history[-1].event_type is EventType.RUN_FINISHED
        assert history[-1].payload["status"] == "failed"

        state = store.project_state("run-partial")
        assert state["state_version"] == 1
        assert set(state["nodes"]) == {"G.goal"}
        assert all(node["value"] is not None for node in state["nodes"].values())

        failed = [event for event in history if event.event_type is EventType.FAILED]
        assert len(failed) == 1
        assert failed[0].instruction_id == "step.split"
        assert "detail" in str(failed[0].payload)
        split_events = [event.event_type for event in history if event.invocation_id == "inv-2"]
        assert EventType.VALIDATION_PASSED not in split_events

        ledger = store.task_ledger("run-partial")
        profile = ledger.profile()
        assert profile["current_task"] is None
        assert profile["counts"]["in_progress"] == 0
        failed_task = ledger.tasks[failed[0].task_id]
        assert failed_task.status is TaskStatus.CANCELLED
        assert not failed_task.evidence
        completed = [
            task for task in ledger.tasks.values() if task.status is TaskStatus.COMPLETED
        ]
        assert len(completed) == 1
        assert completed[0].evidence


def test_non_mapping_multi_target_fails_and_closes_all_tasks(tmp_path):
    source = """\
PROGRAM invalid_result VERSION 1.0
INPUT
    G.value = 1
step.setup: DO define(goal = G.value) -> G.goal
step.split: DO split_pair(value = G.value) -> OUT.left, OUT.right
step.unreached: DO define(goal = G.value) -> E.unreached
RETURN OUT.left, OUT.right
"""
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(
            handlers={"define": define_handler, "split_pair": lambda value: 42}
        )
        result = SequentialCoordinator(store, worker).execute(
            parse_program(source), run_id="run-invalid-result"
        )

        assert result["status"] == "failed"
        assert "non-mapping" in result["error"]
        history = store.events("run-invalid-result")
        assert history[-1].event_type is EventType.RUN_FINISHED
        split_events = [event.event_type for event in history if event.invocation_id == "inv-2"]
        assert split_events == [
            EventType.INVOCATION_READY,
            EventType.INVOCATION_DISPATCHED,
            EventType.RESULT_RECEIVED,
            EventType.FAILED,
        ]
        counts = store.task_ledger("run-invalid-result").profile()["counts"]
        assert counts == {
            "total": 3,
            "pending": 0,
            "in_progress": 0,
            "completed": 1,
            "cancelled": 2,
        }


def test_multi_target_full_keys_disambiguate_duplicate_leaves(tmp_path):
    source = """\
PROGRAM nested_targets VERSION 1.0
INPUT
    G.value = 1
step.split: DO split_pair(value = G.value) -> OUT.left.value, OUT.right.value
RETURN OUT.left.value, OUT.right.value
"""
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(
            handlers={
                "split_pair": lambda value: {
                    "value": 0,
                    "OUT.left.value": 10,
                    "OUT.right.value": 20,
                }
            }
        )
        result = SequentialCoordinator(store, worker).execute(
            parse_program(source), run_id="run-nested-targets"
        )

        assert result["status"] == "succeeded"
        assert result["outputs"] == {
            "OUT.left.value": 10,
            "OUT.right.value": 20,
        }


def test_duplicate_leaf_alias_without_full_keys_fails_as_ambiguous(tmp_path):
    source = """\
PROGRAM ambiguous_targets VERSION 1.0
INPUT
    G.value = 1
step.split: DO split_pair(value = G.value) -> OUT.left.value, OUT.right.value
RETURN OUT.left.value, OUT.right.value
"""
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(
            handlers={"split_pair": lambda value: {"value": value}}
        )
        result = SequentialCoordinator(store, worker).execute(
            parse_program(source), run_id="run-ambiguous-targets"
        )

        assert result["status"] == "failed"
        assert "ambiguous result key" in result["error"]
        assert store.project_state("run-ambiguous-targets")["nodes"] == {}


def test_worker_failure_cancels_unreached_tasks(tmp_path):
    source = """\
PROGRAM future_tasks VERSION 1.0
INPUT
    G.value = 1
step.setup: DO define(goal = G.value) -> G.goal
step.fail: DO calculate(left = G.value, right = G.value) -> OUT.total
step.unreached: DO define(goal = G.value) -> E.unreached
RETURN OUT.total
"""
    with EventStore(tmp_path / "events.db") as store:
        worker = make_worker(calculate=broken_calculate_handler)
        result = SequentialCoordinator(store, worker).execute(
            parse_program(source), run_id="run-future-tasks"
        )

        assert result["status"] == "failed"
        counts = store.task_ledger("run-future-tasks").profile()["counts"]
        assert counts == {
            "total": 3,
            "pending": 0,
            "in_progress": 0,
            "completed": 1,
            "cancelled": 2,
        }


def test_unknown_command_rejected_before_run_creation(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(UNKNOWN_COMMAND_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())

        with pytest.raises(ParseError, match="unknown command"):
            coordinator.execute(program, run_id="run-x")

        with pytest.raises(KeyError):
            store.run("run-x")
        assert store.events("run-x") == ()


def test_state_and_ledger_replay_identical_after_reopen(tmp_path):
    db = tmp_path / "events.db"
    with EventStore(db) as store:
        result = run_canonical(store, run_id="run-1")
        assert result["status"] == "succeeded"
        state_before = store.project_state("run-1")
        ledger_before = store.task_ledger("run-1")
        tasks_before = ledger_before.tasks
        profile_before = ledger_before.profile()

    reopened = EventStore(db)
    try:
        assert reopened.project_state("run-1") == state_before
        ledger_after = reopened.task_ledger("run-1")
        assert ledger_after.tasks == tasks_before
        assert ledger_after.profile() == profile_before
    finally:
        reopened.close()


def test_single_target_accepts_any_type():
    targets = ("OUT.result",)
    for result in [42, "hello", [1, 2], {"a": 1}, None]:
        vals, err = map_results_to_targets(targets, result)
        assert err is None
        assert vals == {"OUT.result": result}


def test_multi_target_by_full_key():
    targets = ("OUT.left", "OUT.right")
    result = {"OUT.left": 10, "OUT.right": 20}
    vals, err = map_results_to_targets(targets, result)
    assert err is None
    assert vals == {"OUT.left": 10, "OUT.right": 20}


def test_multi_target_by_leaf_name():
    targets = ("OUT.summary", "OUT.detail")
    result = {"summary": "ok", "detail": 42}
    vals, err = map_results_to_targets(targets, result)
    assert err is None
    assert vals == {"OUT.summary": "ok", "OUT.detail": 42}


def test_non_mapping_result_for_multi_target_fails():
    targets = ("OUT.left", "OUT.right")
    vals, err = map_results_to_targets(targets, 42)
    assert vals is None
    assert "non-mapping" in err


def test_ambiguous_duplicate_leaf_fails():
    targets = ("OUT.left.value", "OUT.right.value")
    result = {"value": 1}
    vals, err = map_results_to_targets(targets, result)
    assert vals is None
    assert "ambiguous result key" in err


def test_missing_key_fails():
    targets = ("OUT.summary", "OUT.detail")
    result = {"summary": "ok"}
    vals, err = map_results_to_targets(targets, result)
    assert vals is None
    assert "missing result keys" in err
    assert "OUT.detail" in err


REF_LIST_PROGRAM = """\
PROGRAM lister VERSION 1.0
INPUT
    G.left = 5
    G.right = 7
step.first: DO define(goal = G.left) -> G.goal
step.total: DO calculate(items = [G.left, G.right]) -> OUT.total
step.wrap: DO calculate(items = [OUT.total, G.left]) -> OUT.wrapped
RETURN OUT.total, OUT.wrapped
"""


def sum_items_handler(items):
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    return sum(items)


def make_list_worker():
    return DeterministicWorker(
        handlers={"define": define_handler, "calculate": sum_items_handler}
    )


def test_reference_list_argument_resolves_to_values(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(REF_LIST_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_list_worker())
        result = coordinator.execute(program, run_id="run-lists")

        assert result["status"] == "succeeded"
        assert result["outputs"] == {"OUT.total": 12, "OUT.wrapped": 17}

        state = store.project_state("run-lists")
        assert state["nodes"]["OUT.total"]["value"] == 12
        assert state["nodes"]["OUT.wrapped"]["value"] == 17


def test_reference_list_dispatch_payload_carries_resolved_list(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(REF_LIST_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_list_worker())
        coordinator.execute(program, run_id="run-lists")

        dispatched = {
            event.instruction_id: event.payload["args"]
            for event in store.events("run-lists")
            if event.event_type is EventType.INVOCATION_DISPATCHED
        }
        assert dispatched["step.total"]["items"] == [5, 7]
        assert dispatched["step.wrap"]["items"] == [12, 5]


def test_json_list_literal_argument_passes_through_unchanged(tmp_path):
    captured: dict[str, Any] = {}

    def echo_handler(**kwargs):
        captured.update(kwargs)
        return "ok"

    program = parse_program(
        """\
PROGRAM literal VERSION 1.0
INPUT
    G.left = 5
step.echo: DO echo(tags = ["alpha", "beta"], nums = [1, 2], ref = G.left) -> OUT.echo
RETURN OUT.echo
"""
    )
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(
            handlers={"define": define_handler, "echo": echo_handler}
        )
        result = SequentialCoordinator(store=store, worker=worker).execute(
            program, run_id="run-literal"
        )

        assert result["status"] == "succeeded"
        assert result["outputs"] == {"OUT.echo": "ok"}
        assert captured == {"tags": ["alpha", "beta"], "nums": [1, 2], "ref": 5}


DONE_PASS_PROGRAM = """\
PROGRAM gate VERSION 1.0
INPUT
    G.left = 5
step.setup: DO define(goal = G.left) -> G.goal
DONE G.goal == {"goal": "add two inputs", "observed": 5}
step.total: DO calculate(left = G.left, right = G.left) -> OUT.total
DONE OUT.total == 10
RETURN G.goal, OUT.total
"""

DONE_FAIL_PROGRAM = """\
PROGRAM gate VERSION 1.0
INPUT
    G.left = 5
step.setup: DO define(goal = G.left) -> G.goal
step.total: DO calculate(left = G.left, right = G.left) -> OUT.total
DONE OUT.total == 11
step.unreached: DO define(goal = G.left) -> E.unreached
RETURN G.goal, OUT.total
"""

DONE_MATCHED_FAIL_PROGRAM = """\
PROGRAM gate VERSION 1.0
INPUT
    G.left = 5
step.setup: DO define(goal = G.left) -> E.status
DONE matched(E.status, "ok-[0-9]+")
RETURN E.status
"""


MATCHED_PASS_PROGRAM = """\
PROGRAM gate VERSION 1.0
INPUT
    G.left = 5
step.setup: DO define(goal = G.left) -> E.status
DONE matched(E.status, "ok-[0-9]+")
RETURN E.status
"""


def test_matched_passing_predicate_succeeds(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(handlers={"define": lambda goal: "ok-42"})
        result = SequentialCoordinator(store, worker).execute(
            parse_program(MATCHED_PASS_PROGRAM), run_id="run-matched-pass"
        )

        assert result["status"] == "succeeded"
        assert result["outputs"] == {"E.status": "ok-42"}
        lifecycle = tuple(
            event.event_type
            for event in store.events("run-matched-pass")
            if event.invocation_id == "inv-1"
        )
        assert lifecycle == LIFECYCLE


def test_done_passing_predicate_keeps_existing_lifecycle(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(store, make_worker()).execute(
            parse_program(DONE_PASS_PROGRAM), run_id="run-done-pass"
        )

        assert result["status"] == "succeeded"
        assert result["outputs"] == {
            "G.goal": {"goal": "add two inputs", "observed": 5},
            "OUT.total": 10,
        }

        history = store.events("run-done-pass")
        grouped = events_by_invocation(history)
        assert len(grouped) == 2
        for events in grouped.values():
            assert tuple(event.event_type for event in events) == LIFECYCLE

        state = store.project_state("run-done-pass")
        assert state["nodes"]["OUT.total"]["value"] == 10


def test_failing_equals_predicate_fails_run_without_commit(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(store, make_worker()).execute(
            parse_program(DONE_FAIL_PROGRAM), run_id="run-done-fail"
        )

        assert result["status"] == "failed"
        assert "DONE predicate failed" in result["error"]
        assert result["outputs"] == {}

        history = store.events("run-done-fail")
        assert history[-1].event_type is EventType.RUN_FINISHED
        assert history[-1].payload["status"] == "failed"

        total_events = [
            event.event_type for event in history if event.invocation_id == "inv-2"
        ]
        assert total_events == [
            EventType.INVOCATION_READY,
            EventType.INVOCATION_DISPATCHED,
            EventType.RESULT_RECEIVED,
            EventType.VALIDATION_FAILED,
            EventType.FAILED,
        ]

        validation = [
            event for event in history
            if event.event_type is EventType.VALIDATION_FAILED
        ]
        assert len(validation) == 1
        assert validation[0].instruction_id == "step.total"
        assert validation[0].task_id
        assert validation[0].payload["step_id"] == "step.total"
        assert validation[0].payload["predicate"] == {
            "op": "equals", "ref": "OUT.total", "value": 11,
        }
        assert "expected 11" in validation[0].payload["detail"]
        assert "got 10" in validation[0].payload["detail"]

        state = store.project_state("run-done-fail")
        assert state["state_version"] == 1
        assert set(state["nodes"]) == {"G.goal"}
        assert "OUT.total" not in state["nodes"]

        counts = store.task_ledger("run-done-fail").profile()["counts"]
        assert counts == {
            "total": 3,
            "pending": 0,
            "in_progress": 0,
            "completed": 1,
            "cancelled": 2,
        }


def test_failing_matched_predicate_fails_run_without_commit(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(handlers={"define": lambda goal: "failed-1"})
        result = SequentialCoordinator(store, worker).execute(
            parse_program(DONE_MATCHED_FAIL_PROGRAM), run_id="run-matched-fail"
        )

        assert result["status"] == "failed"
        assert "DONE predicate failed" in result["error"]

        history = store.events("run-matched-fail")
        assert history[-1].event_type is EventType.RUN_FINISHED
        assert history[-1].payload["status"] == "failed"

        lifecycle = [
            event.event_type for event in history if event.invocation_id == "inv-1"
        ]
        assert lifecycle == [
            EventType.INVOCATION_READY,
            EventType.INVOCATION_DISPATCHED,
            EventType.RESULT_RECEIVED,
            EventType.VALIDATION_FAILED,
            EventType.FAILED,
        ]

        validation = next(
            event for event in history
            if event.event_type is EventType.VALIDATION_FAILED
        )
        assert validation.payload["predicate"] == {
            "op": "matched", "ref": "E.status", "value": "ok-[0-9]+",
        }
        assert "does not match pattern" in validation.payload["detail"]

        state = store.project_state("run-matched-fail")
        assert state["nodes"] == {}

        counts = store.task_ledger("run-matched-fail").profile()["counts"]
        assert counts == {
            "total": 1,
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "cancelled": 1,
        }


def test_matched_predicate_rejects_non_string_value(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(store, make_worker()).execute(
            parse_program(DONE_MATCHED_FAIL_PROGRAM), run_id="run-matched-type"
        )

        assert result["status"] == "failed"
        validation = next(
            event for event in store.events("run-matched-type")
            if event.event_type is EventType.VALIDATION_FAILED
        )
        assert "requires a string value, got dict" in validation.payload["detail"]


def test_done_equality_is_json_strict_about_bools(tmp_path):
    source = """\
PROGRAM strict VERSION 1.0
INPUT
    G.left = 1
step.setup: DO define(goal = G.left) -> E.count
DONE E.count == true
RETURN E.count
"""
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(handlers={"define": lambda goal: 1})
        result = SequentialCoordinator(store, worker).execute(
            parse_program(source), run_id="run-strict"
        )

        assert result["status"] == "failed"
        validation = next(
            event for event in store.events("run-strict")
            if event.event_type is EventType.VALIDATION_FAILED
        )
        assert "got 1" in validation.payload["detail"]


def test_invocations_without_done_unchanged(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        result = run_canonical(store, run_id="run-plain")

        assert result["status"] == "succeeded"
        history = store.events("run-plain")
        assert not [
            event for event in history
            if event.event_type is EventType.VALIDATION_FAILED
        ]
        grouped = events_by_invocation(history)
        for events in grouped.values():
            assert tuple(event.event_type for event in events) == LIFECYCLE


# -- registry digest in RUN_STARTED (issue #15) -------------------------


def test_run_started_carries_stable_registry_digest(tmp_path):
    from tikhon.registry import builtin_registry
    from tikhon.registry.registry import registry_digest

    with EventStore(tmp_path / "events.db") as store:
        run_canonical(store, run_id="run-digest")
        started = store.events("run-digest")[0]
        assert started.event_type is EventType.RUN_STARTED

        expected = registry_digest(builtin_registry())
        assert started.payload["registry_digest"] == expected
        assert started.payload["program"] == "adder"
        assert started.payload["version"] == "1.0"
        metadata = store.run("run-digest")["metadata"]
        assert metadata["registry_digest"] == expected
        assert metadata["program"] == "adder"


def test_two_coordinators_same_registry_same_digest(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        run_canonical(store, run_id="run-a")
        run_canonical(store, run_id="run-b")
        first = store.events("run-a")[0].payload["registry_digest"]
        second = store.events("run-b")[0].payload["registry_digest"]
        assert first == second
        assert len(first) == 64


def test_extra_spec_changes_registry_digest():
    import dataclasses

    from tikhon.registry import Registry, builtin_registry
    from tikhon.registry.registry import registry_digest

    base = builtin_registry()
    baseline = registry_digest(base)

    extended = Registry()
    for name in base.names():
        for version in base.versions(name):
            extended.register(base.resolve(name, version))
    extra = dataclasses.replace(
        base.resolve("define"), name="zz_extra_probe", version="1.0.0"
    )
    extended.register(extra)

    assert registry_digest(extended) != baseline


# -- cross-run semantic memory (issue #5) --------------------------------

KB_REMEMBER_PROGRAM = """\
PROGRAM rememberer VERSION 1.0
INPUT
    G.fact = "seal before editing"
step.frame: DO define(goal = G.fact) -> G.plan
step.store: DO remember(key = "kb.lesson", value = G.fact) -> ART.record
RETURN ART.record
"""

KB_RECALL_PROGRAM = """\
PROGRAM recallr VERSION 1.0
INPUT
    G.query = "kb.lesson"
step.fetch: DO recall(query = "kb.lesson") -> OUT.found
step.wrap: DO define(goal = OUT.found) -> G.recalled
RETURN OUT.found, G.recalled
"""


def test_remember_persists_value_across_runs_and_files(tmp_path):
    kb_path = tmp_path / "kb.sqlite"
    remembered: dict[str, Any] = {}

    with EventStore(tmp_path / "events.db") as store:
        memory = KnowledgeBase(kb_path)

        def remember_handler(key, value):
            record = memory.set(key, value, source_run="run-remember")
            remembered.update(record)
            return record

        worker = DeterministicWorker(
            handlers={
                "define": define_handler,
                "remember": remember_handler,
            }
        )
        result = SequentialCoordinator(store, worker, memory=memory).execute(
            parse_program(KB_REMEMBER_PROGRAM), run_id="run-remember"
        )

        assert result["status"] == "succeeded"
        assert remembered["key"] == "kb.lesson"
        assert remembered["value"] == "seal before editing"
        assert remembered["source_run"] == "run-remember"
        assert remembered["updated_at"]
        memory.close()

    with KnowledgeBase(kb_path) as reopened:
        assert reopened.get("kb.lesson") == "seal before editing"


def test_recall_across_runs_resolves_kb_ref_into_state_node(tmp_path):
    kb_path = tmp_path / "kb.sqlite"
    with KnowledgeBase(kb_path) as memory:
        memory.set("kb.lesson", "seal before editing", source_run="run-1")

    with EventStore(tmp_path / "events.db") as store:
        memory = KnowledgeBase(kb_path)
        worker = DeterministicWorker(
            handlers={
                "define": define_handler,
                "recall": lambda query: {query: memory.get(query)},
            }
        )
        result = SequentialCoordinator(store, worker, memory=memory).execute(
            parse_program(KB_RECALL_PROGRAM), run_id="run-recall"
        )
        memory.close()

        assert result["status"] == "succeeded"
        assert result["outputs"] == {
            "OUT.found": {"kb.lesson": "seal before editing"},
            "G.recalled": {"goal": "add two inputs", "observed": {"kb.lesson": "seal before editing"}},
        }

        state = store.project_state("run-recall")
        assert state["nodes"]["OUT.found"]["value"] == {
            "kb.lesson": "seal before editing"
        }

        dispatched = {
            event.instruction_id: event.payload["args"]
            for event in store.events("run-recall")
            if event.event_type is EventType.INVOCATION_DISPATCHED
        }
        assert dispatched["step.fetch"] == {"query": "kb.lesson"}


def test_end_to_end_run1_remembers_run2_recalls_same_kb_file(tmp_path):
    kb_path = tmp_path / "kb.sqlite"

    with EventStore(tmp_path / "events.db") as store:
        memory = KnowledgeBase(kb_path)
        worker = DeterministicWorker(
            handlers={
                "define": define_handler,
                "remember": lambda key, value: memory.set(key, value, source_run="run-1"),
            }
        )
        first = SequentialCoordinator(store, worker, memory=memory).execute(
            parse_program(KB_REMEMBER_PROGRAM), run_id="run-1"
        )
        assert first["status"] == "succeeded"
        memory.close()

    with EventStore(tmp_path / "events.db") as store:
        memory = KnowledgeBase(kb_path)
        worker = DeterministicWorker(
            handlers={
                "define": define_handler,
                "recall": lambda query: {query: memory.get(query)},
            }
        )
        second = SequentialCoordinator(store, worker, memory=memory).execute(
            parse_program(KB_RECALL_PROGRAM), run_id="run-2"
        )
        memory.close()

        assert second["status"] == "succeeded"
        assert second["outputs"]["OUT.found"] == {"kb.lesson": "seal before editing"}


def test_kb_ref_without_memory_raises_clear_error_before_run(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        coordinator = SequentialCoordinator(store, make_worker())

        with pytest.raises(ValueError, match="no knowledge base"):
            coordinator.execute(
                parse_program(
                    """\
PROGRAM needs_kb VERSION 1.0
INPUT
    G.left = 1
step.use: DO define(goal = KB.lesson) -> G.goal
RETURN G.goal
"""
                ),
                run_id="run-nokb",
            )

        # raised before run creation: the event store stays clean
        with pytest.raises(KeyError):
            store.run("run-nokb")
        assert store.events("run-nokb") == ()


def test_unknown_kb_key_fails_resolution_clearly(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        memory = KnowledgeBase(tmp_path / "kb.sqlite")
        result = SequentialCoordinator(store, make_worker(), memory=memory).execute(
            parse_program(
                """\
PROGRAM missing_kb VERSION 1.0
INPUT
    G.left = 1
step.use: DO define(goal = KB.absent) -> G.goal
RETURN G.goal
"""
            ),
            run_id="run-missing-kb",
        )
        memory.close()

        assert result["status"] == "failed"
        assert "kb.absent" in result["error"]


def test_kb_ref_inside_reference_list_resolves_from_memory(tmp_path):
    source = """\
PROGRAM list_kb VERSION 1.0
INPUT
    G.left = 5
step.total: DO calculate(items = [G.left, KB.right]) -> OUT.total
RETURN OUT.total
"""
    with EventStore(tmp_path / "events.db") as store:
        memory = KnowledgeBase(tmp_path / "kb.sqlite")
        memory.set("kb.right", 7)
        result = SequentialCoordinator(store, make_list_worker(), memory=memory).execute(
            parse_program(source), run_id="run-kb-list"
        )
        memory.close()

        assert result["status"] == "succeeded"
        assert result["outputs"] == {"OUT.total": 12}


# --- idempotency keys and workspace policy (issue #9) -------------------------


def dispatched_payloads(store, run_id):
    return [
        event.payload
        for event in store.events(run_id)
        if event.event_type is EventType.INVOCATION_DISPATCHED
    ]


def test_every_dispatched_payload_carries_the_idempotency_key(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        run_canonical(store, run_id="run-1")

        payloads = dispatched_payloads(store, "run-1")
        assert len(payloads) == 2
        for index, payload in enumerate(payloads, start=1):
            assert payload["idempotency_key"] == f"run-1:inv-{index}"


def test_idempotency_key_uses_the_explicit_run_id(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        run_canonical(store, run_id="issue-09-run-7")

        payloads = dispatched_payloads(store, "issue-09-run-7")
        for index, payload in enumerate(payloads, start=1):
            assert payload["idempotency_key"] == f"issue-09-run-7:inv-{index}"


def test_failed_invocation_still_dispatched_with_idempotency_key(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        run_canonical(
            store, run_id="run-boom", worker=make_worker(calculate=broken_calculate_handler)
        )

        payloads = dispatched_payloads(store, "run-boom")
        assert len(payloads) == 2
        assert payloads[1]["idempotency_key"] == "run-boom:inv-2"


def test_workspace_root_injected_only_for_effectful_commands(tmp_path):
    captured: dict[str, Any] = {}

    def edit_handler(**kwargs):
        captured.update(kwargs)
        return "scratch/edited.txt"

    program = parse_program(
        """\
PROGRAM workspace VERSION 1.0
INPUT
    G.note = "hello"
step.write: DO edit(path = "scratch/edited.txt", content = G.note) -> E.written
step.echo: DO define(goal = G.note) -> G.goal
RETURN E.written, G.goal
"""
    )
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(handlers={"edit": edit_handler, "define": define_handler})
        coordinator = SequentialCoordinator(
            store=store, worker=worker, workspace_root=str(tmp_path / "ws")
        )
        result = coordinator.execute(program, run_id="run-ws")

        assert result["status"] == "succeeded"
        assert captured["_workspace_root"] == str(tmp_path / "ws")
        payloads = dispatched_payloads(store, "run-ws")
        assert payloads[0]["args"]["_workspace_root"] == str(tmp_path / "ws")
        assert "_workspace_root" not in payloads[1]["args"]


def test_no_workspace_root_means_no_injection(tmp_path):
    captured: dict[str, Any] = {}

    def edit_handler(**kwargs):
        captured.update(kwargs)
        return "scratch/edited.txt"

    program = parse_program(
        """\
PROGRAM workspace VERSION 1.0
INPUT
    G.note = "hello"
step.write: DO edit(path = "scratch/edited.txt", content = G.note) -> E.written
RETURN E.written
"""
    )
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(handlers={"edit": edit_handler})
        result = SequentialCoordinator(store=store, worker=worker).execute(
            program, run_id="run-nows"
        )

        assert result["status"] == "succeeded"
        assert "_workspace_root" not in captured


# -- protocol calls (issue #12): inline expansion of sealed protocols -----


def write_test_protocol(root, name, text):
    protocols = root / "protocols"
    protocols.mkdir(exist_ok=True)
    path = protocols / f"{name}.think"
    path.write_text(text, encoding="utf-8")
    return protocols


FRAMING_TEST_PROTOCOL = """\
PROGRAM framing VERSION 1.0

INPUT
    G.request = "frame the problem"
    C.scope = "repository working tree"

step.frame: DO define(request = G.request) -> G.plan
step.locate: DO search(query = G.plan, scope = C.scope) -> E.context
step.read: DO fetch(resource_refs = E.context) -> ART.sources
step.analyze: DO extract(artifact = ART.sources, schema = "frame_analysis") -> V.analysis

RETURN G.plan, E.context, ART.sources, V.analysis
"""

CALLER_TEST_PROGRAM = """\
PROGRAM caller VERSION 1.0

INPUT
    G.request = "frame the kb issue"

step.ask: DO define(request = G.request) -> G.probe
CALL protocol.framing(request = G.probe, scope = "src/tikhon") -> G.plan, V.analysis
step.wrap: DO summarize(source_refs = V.analysis, budget = 100) -> OUT.brief

RETURN G.plan, V.analysis, OUT.brief
"""

PROTOCOL_TEST_HANDLERS = {
    "define": lambda request: {"echo": request},
    "search": lambda query, scope: [f"hit:{query}:{scope}"],
    "fetch": lambda resource_refs: {"sources": resource_refs},
    "extract": lambda artifact, schema: {"analysis": artifact, "schema": schema},
    "summarize": lambda source_refs, budget: f"brief of {source_refs} ({budget})",
}


def make_protocol_worker(**overrides):
    handlers = dict(PROTOCOL_TEST_HANDLERS)
    handlers.update(overrides)
    return DeterministicWorker(handlers=handlers)


def test_call_creates_isolated_child_run_and_adopts_targets(tmp_path):
    # Issue #20: a CALL no longer expands the protocol inline.  It spawns
    # an isolated child run in the same EventStore; the parent's ledger
    # holds one "CALL ..." task and the child's ledger the protocol's own
    # tasks; parent state receives only the adopted CALL targets.
    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL)
    program = parse_program(CALLER_TEST_PROGRAM)
    with EventStore(tmp_path / "events.db") as store:
        coordinator = SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        )
        result = coordinator.execute(program, run_id="run-call")

        assert result["status"] == "succeeded"
        assert result["outputs"]["G.plan"] == {"echo": {"echo": "frame the kb issue"}}
        assert result["outputs"]["OUT.brief"].startswith("brief of")

        parent_state = store.project_state("run-call")
        # Adopted CALL targets carry the protocol-produced values.
        assert parent_state["nodes"]["G.plan"]["value"] == {"echo": {"echo": "frame the kb issue"}}
        assert parent_state["nodes"]["V.analysis"]["value"]["schema"] == "frame_analysis"
        # Child-internal state nodes never leak into the parent projection.
        assert "E.context" not in parent_state["nodes"]
        assert "ART.sources" not in parent_state["nodes"]

        child_run_id = "run-call:inv-2"
        child_state = store.project_state(child_run_id)
        # The child's namespace holds its own steps' outputs plus the
        # INPUT binding resolved from the explicit CALL argument.
        assert child_state["nodes"]["G.plan"]["value"] == {"echo": {"echo": "frame the kb issue"}}
        assert child_state["nodes"]["E.context"]["value"] == [
            "hit:" + str({"echo": {"echo": "frame the kb issue"}}) + ":src/tikhon"
        ]
        assert child_state["metadata"]["child_of"] == "run-call"
        assert child_state["metadata"]["call"] == "protocol.framing"

        parent_ledger = store.task_ledger("run-call")
        assert [task.text for task in parent_ledger.tasks.values()] == [
            "step.ask: DO define",
            "CALL protocol.framing",
            "step.wrap: DO summarize",
        ]
        assert parent_ledger.profile()["counts"]["completed"] == 3
        child_ledger = store.task_ledger(child_run_id)
        assert [task.text for task in child_ledger.tasks.values()] == [
            "step.frame: DO define",
            "step.locate: DO search",
            "step.read: DO fetch",
            "step.analyze: DO extract",
        ]
        assert child_ledger.profile()["percent_complete"] == 100.0


def test_child_run_started_marks_lineage_and_own_invocation_sequence(tmp_path):
    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL)
    program = parse_program(CALLER_TEST_PROGRAM)
    with EventStore(tmp_path / "events.db") as store:
        SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-call")

        child_run_id = "run-call:inv-2"
        started = next(
            event
            for event in store.events(child_run_id)
            if event.event_type is EventType.RUN_STARTED
        )
        assert started.payload["child_of"] == "run-call"
        assert started.payload["call"] == "protocol.framing"

        # The child's invocation ids restart in its own namespace; the
        # parent's ids cover its own plan (ask, CALL, wrap).
        child_grouped = events_by_invocation(store.events(child_run_id))
        assert sorted(child_grouped) == ["inv-1", "inv-2", "inv-3", "inv-4"]
        parent_grouped = events_by_invocation(store.events("run-call"))
        assert sorted(parent_grouped) == ["inv-1", "inv-2", "inv-3"]
        call_ready = [
            event
            for event in store.events("run-call")
            if event.event_type is EventType.INVOCATION_READY
            and event.invocation_id == "inv-2"
        ]
        assert call_ready[0].instruction_id == "protocol.framing"
        assert call_ready[0].payload["command"] == "CALL protocol.framing"


def test_adopted_call_records_child_adopted_before_succeeded(tmp_path):
    from tikhon.audit import audit_run

    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL)
    program = parse_program(CALLER_TEST_PROGRAM)
    with EventStore(tmp_path / "events.db") as store:
        SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-call")

        history = store.events("run-call")
        adopted = [
            event for event in history
            if event.event_type is EventType.CHILD_ADOPTED
        ]
        assert len(adopted) == 1
        event = adopted[0]
        assert event.payload["child_run_id"] == "run-call:inv-2"
        assert event.payload["adopted"] == {"G.plan": "G.plan", "V.analysis": "V.analysis"}
        assert event.payload["child_status"] == "succeeded"
        assert event.invocation_id == "inv-2"
        # The adoption precedes the CALL's SUCCEEDED delta in the parent log.
        succeeded = next(
            candidate
            for candidate in history
            if candidate.event_type is EventType.SUCCEEDED
            and candidate.invocation_id == "inv-2"
        )
        assert event.seq < succeeded.seq

        report = audit_run(store, "run-call")
        assert report.ok, [finding.to_dict() for finding in report.findings]


def test_repeated_calls_stay_isolated_and_map_returns_per_target(tmp_path):
    # Two CALLs to the same protocol, each targeting different parent
    # refs with identical child-local names: separate child runs, no
    # leakage, per-target mapping.
    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL)
    program = parse_program("""\
PROGRAM twice VERSION 1.0

INPUT
    G.request = "first"

step.ask: DO define(request = G.request) -> G.probe
CALL protocol.framing(request = G.probe, scope = "a") -> V.analysis
CALL protocol.framing(request = G.request, scope = "b") -> E.context

RETURN V.analysis, E.context
""")
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-twice")

        assert result["status"] == "succeeded"
        # Per-target mapping: each child returned a distinct ref.
        assert result["outputs"]["V.analysis"]["schema"] == "frame_analysis"
        assert result["outputs"]["E.context"] == ["hit:" + str({"echo": "first"}) + ":b"]

        first_state = store.project_state("run-twice:inv-2")
        second_state = store.project_state("run-twice:inv-3")
        # Isolated namespaces: identical child-local names never collide.
        assert first_state["nodes"]["E.context"]["value"] == [
            "hit:" + str({"echo": {"echo": "first"}}) + ":a"
        ]
        assert second_state["nodes"]["E.context"]["value"] == [
            "hit:" + str({"echo": "first"}) + ":b"
        ]
        parent_state = store.project_state("run-twice")
        assert parent_state["nodes"]["V.analysis"]["value"]["schema"] == "frame_analysis"
        assert parent_state["nodes"]["E.context"]["value"] == [
            "hit:" + str({"echo": "first"}) + ":b"
        ]


def test_protocol_call_events_replay_identically_after_reopen(tmp_path):
    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL)
    db = tmp_path / "events.db"
    program = parse_program(CALLER_TEST_PROGRAM)
    with EventStore(db) as store:
        result = SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-call")
        assert result["status"] == "succeeded"
        parent_before = store.project_state("run-call")
        child_before = store.project_state("run-call:inv-2")
        parent_ledger_before = store.task_ledger("run-call")
        child_ledger_before = store.task_ledger("run-call:inv-2")
        parent_events_before = store.events("run-call")
        child_events_before = store.events("run-call:inv-2")

    reopened = EventStore(db)
    try:
        assert reopened.project_state("run-call") == parent_before
        assert reopened.project_state("run-call:inv-2") == child_before
        assert reopened.task_ledger("run-call").tasks == parent_ledger_before.tasks
        assert reopened.task_ledger("run-call:inv-2").tasks == child_ledger_before.tasks
        assert reopened.events("run-call") == parent_events_before
        assert reopened.events("run-call:inv-2") == child_events_before
    finally:
        reopened.close()


def test_protocol_call_runs_audit_clean_parent_and_child(tmp_path):
    from tikhon.audit import audit_run

    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL)
    program = parse_program(CALLER_TEST_PROGRAM)
    with EventStore(tmp_path / "events.db") as store:
        SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-call")

        for run_id in ("run-call", "run-call:inv-2"):
            report = audit_run(store, run_id)
            assert report.ok, (run_id, [f.to_dict() for f in report.findings])


def test_failing_child_fails_caller_atomically(tmp_path):
    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL)

    def broken_extract(artifact, schema):
        raise RuntimeError("protocol boom")

    program = parse_program(CALLER_TEST_PROGRAM)
    with EventStore(tmp_path / "events.db") as store:
        worker = make_protocol_worker(extract=broken_extract)
        result = SequentialCoordinator(
            store=store, worker=worker, protocols_dir=protocols
        ).execute(program, run_id="run-fail")

        assert result["status"] == "failed"
        assert "protocol boom" in result["error"]
        assert result["outputs"] == {}

        # The child run itself is terminal-failed in its own history.
        child_history = store.events("run-fail:inv-2")
        assert child_history[-1].event_type is EventType.RUN_FINISHED
        assert child_history[-1].payload["status"] == "failed"

        parent_history = store.events("run-fail")
        assert parent_history[-1].event_type is EventType.RUN_FINISHED
        assert parent_history[-1].payload["status"] == "failed"
        failed = [e for e in parent_history if e.event_type is EventType.FAILED]
        assert len(failed) == 1
        assert failed[0].instruction_id == "protocol.framing"
        assert failed[0].invocation_id == "inv-2"
        # No adoption happened: no CHILD_ADOPTED, no CALL SUCCEEDED.
        assert not any(
            e.event_type is EventType.CHILD_ADOPTED for e in parent_history
        )
        assert not any(
            e.event_type is EventType.SUCCEEDED and e.invocation_id == "inv-2"
            for e in parent_history
        )

        ledger = store.task_ledger("run-fail")
        profile = ledger.profile()
        assert profile["counts"]["completed"] == 1
        assert profile["counts"]["cancelled"] == 2
        assert profile["counts"]["pending"] == 0
        assert profile["counts"]["in_progress"] == 0
        cancelled_texts = {
            task.text for task in ledger.tasks.values()
            if task.status is TaskStatus.CANCELLED
        }
        assert "CALL protocol.framing" in cancelled_texts
        assert "step.wrap: DO summarize" in cancelled_texts

        state = store.project_state("run-fail")
        assert "OUT.brief" not in state["nodes"]
        assert "G.plan" not in state["nodes"]
        assert "V.analysis" not in state["nodes"]


def test_child_stop_blocked_fails_caller_without_adoption(tmp_path):
    # Any non-succeeded child terminal (here a conditional STOP blocked)
    # fails the parent through the standard atomic path.
    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL.replace(
        "step.analyze: DO extract(artifact = ART.sources, schema = \"frame_analysis\") -> V.analysis",
        "step.analyze: DO extract(artifact = ART.sources, schema = \"frame_analysis\") -> V.analysis\n"
        "IF C.scope == \"nowhere\" STOP blocked(E.context)",
    ))
    program = parse_program(CALLER_TEST_PROGRAM)
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-not-blocked")

        assert result["status"] == "succeeded"  # condition false: child succeeds

    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL.replace(
        "step.analyze: DO extract(artifact = ART.sources, schema = \"frame_analysis\") -> V.analysis",
        "step.analyze: DO extract(artifact = ART.sources, schema = \"frame_analysis\") -> V.analysis\n"
        "IF C.scope == \"src/tikhon\" STOP blocked(E.context)",
    ))
    program = parse_program(CALLER_TEST_PROGRAM)
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-blocked")

        assert result["status"] == "failed"
        assert "blocked" in result["error"]
        child_history = store.events("run-blocked:inv-2")
        assert child_history[-1].payload["status"] == "blocked"
        assert not any(
            e.event_type is EventType.CHILD_ADOPTED
            for e in store.events("run-blocked")
        )


def test_missing_protocol_rejected_before_run_creation(tmp_path):
    program = parse_program(CALLER_TEST_PROGRAM)
    with EventStore(tmp_path / "events.db") as store:
        coordinator = SequentialCoordinator(
            store=store, worker=make_protocol_worker(),
            protocols_dir=tmp_path / "protocols",
        )
        with pytest.raises(ParseError, match="protocol protocol.framing not found"):
            coordinator.execute(program, run_id="run-x")
        with pytest.raises(KeyError):
            store.run("run-x")
        assert store.events("run-x") == ()


def test_nested_protocol_call_executes(tmp_path):
    # A child executes another child: parent -> child -> grandchild, all
    # with deterministic run ids and surviving reopen/replay.
    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL.replace(
        "step.read: DO fetch(resource_refs = E.context) -> ART.sources",
        "step.read: DO fetch(resource_refs = E.context) -> ART.sources\n"
        "CALL protocol.inner(request = G.request, scope = C.scope) -> E.deep1, E.deep2",
    ))
    write_test_protocol(tmp_path, "inner", """\
PROGRAM inner VERSION 1.0

INPUT
    G.request = "x"
    C.scope = "y"

step.deep: DO define(request = G.request) -> E.deep1
step.deeper: DO extract(artifact = E.deep1, schema = "deep") -> E.deep2

RETURN E.deep1, E.deep2
""")
    program = parse_program(CALLER_TEST_PROGRAM)
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-nested")

        assert result["status"] == "succeeded"
        # Three runs in the tree: parent, child (framing), grandchild
        # (inner) — deterministic ids chained through invocation ids.
        grandchild_id = "run-nested:inv-2:inv-4"
        grandchild_ledger = store.task_ledger(grandchild_id)
        grandchild_texts = [
            task.text for task in grandchild_ledger.tasks.values()
        ]
        assert grandchild_texts == [
            "step.deep: DO define",
            "step.deeper: DO extract",
        ]
        grandchild_state = store.project_state(grandchild_id)
        assert grandchild_state["nodes"]["E.deep2"]["value"]["schema"] == "deep"
        assert grandchild_state["metadata"]["child_of"] == "run-nested:inv-2"
        # The grandchild's internal nodes stay out of the parent and the
        # child's projections; the child adopts only its own CALL targets.
        child_state = store.project_state("run-nested:inv-2")
        assert "E.deep1" in child_state["nodes"]  # adopted by the child's CALL
        parent_state = store.project_state("run-nested")
        assert "E.deep1" not in parent_state["nodes"]
        assert "E.deep2" not in parent_state["nodes"]
        assert parent_state["nodes"]["G.plan"]["value"] == {"echo": {"echo": "frame the kb issue"}}


# -- revise/retire node deltas (issue #7) ---------------------------------
#
# A step's trailing `REVISE r1, r2 | RETIRE r3` clause commits inside the
# SAME StateDelta as the step's adds: REVISEd refs (existing earlier
# nodes, never the step's own targets; REVISE requires a single-target
# step) are set to the step's single target value, RETIREd refs are
# removed from the projection while history retains them, the version
# bumps once for the step, and replay after reopen is identical.

REVISE_RETIRE_PROGRAM = """\
PROGRAM corrector VERSION 1.0
INPUT
    G.left = 5
step.first: DO define(goal = G.left) -> G.summary
step.stale: DO define(goal = G.left) -> E.stale
step.fix: DO calculate(left = G.left, right = G.left) -> E.correction REVISE G.summary | RETIRE E.stale
RETURN E.correction
"""

CORRECTIONS_WORKER = DeterministicWorker(
    handlers={
        "define": define_handler,
        "calculate": calculate_handler,
    }
)


def run_corrections(store, run_id, program_text=REVISE_RETIRE_PROGRAM, worker=None):
    coordinator = SequentialCoordinator(
        store=store, worker=worker or CORRECTIONS_WORKER
    )
    return coordinator.execute(parse_program(program_text), run_id=run_id)


def test_revise_replaces_value_and_retire_removes_in_same_delta(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        result = run_corrections(store, "run-corrections")

        assert result["status"] == "succeeded"
        assert result["outputs"] == {"E.correction": 10}

        state = store.project_state("run-corrections")
        assert state["state_version"] == 3
        assert set(state["nodes"]) == {"G.summary", "E.correction"}
        # REVISE: the earlier node now carries the step's target value.
        assert state["nodes"]["G.summary"]["value"] == 10
        # RETIRE: removed from the projection.
        assert "E.stale" not in state["nodes"]


def test_succeeded_payload_carries_revise_and_retire_with_adds(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        run_corrections(store, "run-corrections")

        succeeded = [
            event for event in store.events("run-corrections")
            if event.event_type is EventType.SUCCEEDED
        ]
        fix = next(
            event for event in succeeded
            if event.instruction_id == "step.fix"
        )
        delta = fix.payload["delta"]
        assert delta["add_nodes"] == [{"id": "E.correction", "value": 10}]
        assert delta["revise_nodes"] == [{"id": "G.summary", "value": 10}]
        assert delta["retire_nodes"] == ["E.stale"]
        # One version bump for the whole step, adds and corrections alike.
        assert fix.state_version == 3


def test_revised_value_visible_to_later_steps(tmp_path):
    program = """\
PROGRAM reviser VERSION 1.0
INPUT
    G.left = 5
step.first: DO define(goal = G.left) -> G.summary
step.fix: DO calculate(left = G.left, right = G.left) -> E.correction REVISE G.summary
step.after: DO calculate(left = G.summary, right = G.left) -> OUT.after
DONE OUT.after == 15
RETURN E.correction, OUT.after
"""
    with EventStore(tmp_path / "events.db") as store:
        result = run_corrections(store, "run-revised", program_text=program)

        assert result["status"] == "succeeded"
        # G.summary was revised to 10 by step.fix; the later step and its
        # DONE predicate observe the revised value.
        assert result["outputs"] == {"E.correction": 10, "OUT.after": 15}


def test_retired_node_unavailable_to_later_steps_fails_coherently(tmp_path):
    program = REVISE_RETIRE_PROGRAM.replace(
        "step.fix: DO calculate(left = G.left, right = G.left) -> E.correction REVISE G.summary | RETIRE E.stale",
        "step.fix: DO calculate(left = G.left, right = G.left) -> E.correction REVISE G.summary | RETIRE E.stale\n"
        "step.after: DO calculate(left = E.stale, right = G.left) -> OUT.after",
    )
    with EventStore(tmp_path / "events.db") as store:
        result = run_corrections(store, "run-retired-use", program_text=program)

        assert result["status"] == "failed"
        assert "E.stale" in result["error"]
        assert "retired" in result["error"]
        history = store.events("run-retired-use")
        assert history[-1].payload["status"] == "failed"
        state = store.project_state("run-retired-use")
        assert "OUT.after" not in state["nodes"]
        counts = store.task_ledger("run-retired-use").profile()["counts"]
        assert counts["cancelled"] == 1
        assert counts["completed"] == 3


def test_retire_only_keeps_history_and_replays_identically(tmp_path):
    program = """\
PROGRAM retirer VERSION 1.0
INPUT
    G.left = 5
step.first: DO define(goal = G.left) -> G.summary
step.stale: DO define(goal = G.left) -> E.stale
step.fix: DO calculate(left = G.left, right = G.left) -> E.correction RETIRE E.stale
RETURN E.correction
"""
    db = tmp_path / "events.db"
    with EventStore(db) as store:
        result = run_corrections(store, "run-retire-only", program_text=program)
        assert result["status"] == "succeeded"

        state = store.project_state("run-retire-only")
        assert set(state["nodes"]) == {"G.summary", "E.correction"}
        assert state["state_version"] == 3

        # History retains the retired node: the earlier SUCCEEDED delta
        # still carries its add, unmodified.
        stale_add = next(
            event
            for event in store.events("run-retire-only")
            if event.event_type is EventType.SUCCEEDED
            and event.instruction_id == "step.stale"
        )
        assert stale_add.payload["delta"]["add_nodes"] == [
            {"id": "E.stale", "value": {"goal": "add two inputs", "observed": 5}}
        ]

        before = store.project_state("run-retire-only")

    reopened = EventStore(db)
    try:
        assert reopened.project_state("run-retire-only") == before
    finally:
        reopened.close()


def test_revise_retire_run_replays_identically_and_audits_clean(tmp_path):
    from tikhon.audit import audit_run

    db = tmp_path / "events.db"
    with EventStore(db) as store:
        result = run_corrections(store, "run-corrections")
        assert result["status"] == "succeeded"
        state_before = store.project_state("run-corrections")
        ledger_before = store.task_ledger("run-corrections")

        report = audit_run(store, "run-corrections")
        assert report.ok, [finding.to_dict() for finding in report.findings]

    reopened = EventStore(db)
    try:
        assert reopened.project_state("run-corrections") == state_before
        assert reopened.task_ledger("run-corrections").tasks == ledger_before.tasks
    finally:
        reopened.close()


def test_retire_inside_child_is_child_local_and_blocks_adoption(tmp_path):
    # Issue #20 isolation: a RETIRE inside a protocol's child run removes
    # the node from the CHILD's namespace only.  A RETURNed ref the child
    # retired is no longer committed, so adopting it fails the parent
    # through the standard atomic path instead of publishing a phantom.
    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL.replace(
        "step.analyze: DO extract(artifact = ART.sources, schema = \"frame_analysis\") -> V.analysis",
        "step.analyze: DO extract(artifact = ART.sources, schema = \"frame_analysis\") -> V.analysis\n"
        "step.trim: DO summarize(source_refs = V.analysis, budget = 10) -> E.trim RETIRE E.context",
    ))
    caller = parse_program("""\
PROGRAM caller VERSION 1.0

INPUT
    G.request = "frame the kb issue"

step.ask: DO define(request = G.request) -> G.probe
CALL protocol.framing(request = G.probe, scope = "src/tikhon") -> E.context

RETURN E.context
""")
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        ).execute(caller, run_id="run-protocol-retire")

        # The caller adopts E.context, which the child retired.
        assert result["status"] == "failed"
        assert "did not commit RETURN reference E.context" in result["error"]
        child_state = store.project_state("run-protocol-retire:inv-2")
        # The retirement is visible in the child's own projection...
        assert "E.context" not in child_state["nodes"]
        assert child_state["nodes"]["E.trim"]["value"].startswith("brief of")
        parent_state = store.project_state("run-protocol-retire")
        # ...but nothing was published to the caller.
        assert "E.context" not in parent_state["nodes"]
        assert "E.trim" not in parent_state["nodes"]

    # A protocol that retires a ref it does NOT return keeps succeeding;
    # the caller simply never sees the retired child-internal node.
    protocols = write_test_protocol(tmp_path, "framing", FRAMING_TEST_PROTOCOL.replace(
        "step.analyze: DO extract(artifact = ART.sources, schema = \"frame_analysis\") -> V.analysis",
        "step.analyze: DO extract(artifact = ART.sources, schema = \"frame_analysis\") -> V.analysis\n"
        "step.trim: DO summarize(source_refs = V.analysis, budget = 10) -> E.trim RETIRE E.context",
    ).replace(
        "RETURN G.plan, E.context, ART.sources, V.analysis",
        "RETURN G.plan, ART.sources, V.analysis",
    ))
    caller = parse_program("""\
PROGRAM caller VERSION 1.0

INPUT
    G.request = "frame the kb issue"

step.ask: DO define(request = G.request) -> G.probe
CALL protocol.framing(request = G.probe, scope = "src/tikhon") -> G.plan, V.analysis

RETURN G.plan, V.analysis
""")
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store=store, worker=make_protocol_worker(), protocols_dir=protocols
        ).execute(caller, run_id="run-retire-ok")

        assert result["status"] == "succeeded"
        child_state = store.project_state("run-retire-ok:inv-2")
        assert "E.context" not in child_state["nodes"]
        parent_state = store.project_state("run-retire-ok")
        assert parent_state["nodes"]["V.analysis"]["value"]["schema"] == "frame_analysis"


# --------------------------------------------------------------------------
# Issue #3: IF branches with deterministic expressions.
# --------------------------------------------------------------------------

REPAIR_PROGRAM = """\
PROGRAM repair_defect VERSION 0.1
INPUT
    G.fix = "Observed behavior matches the contract"
    C.scope = "Smallest root-cause fix"
step.repro: DO define(goal = G.fix) -> E.repro
step.pick: DO choose(options = E.repro, scope = C.scope) -> D.cause
step.patch: DO define(goal = D.cause) -> ART.patch
step.test: DO test_patch(target = ART.patch) -> V.tests
step.review: DO review_patch(artifact = ART.patch) -> R.review
IF V.tests.status != "passed" STOP failed(V.tests)
IF count(R.review.blocking) > 0 STOP failed(R.review)
step.final: DO verify(goal = G.fix, evidence = [V.tests, R.review]) -> V.result
RETURN ART.patch, V.result
"""

BRANCH_PROGRAM = """\
PROGRAM branch VERSION 1.0
INPUT
    G.flag = "go"
    G.left = 20
    G.right = 22
step.mark: DO define(goal = G.flag) -> V.flag
IF G.flag == "go" step.extra: DO calculate(left = G.left, right = G.right) -> OUT.total
RETURN V.flag
"""

EARLY_RETURN_PROGRAM = """\
PROGRAM early VERSION 1.0
INPUT
    G.flag = "early"
step.mark: DO define(goal = G.flag) -> V.flag
IF G.flag == "early" RETURN V.flag
step.late: DO calculate(left = 1, right = 2) -> OUT.total
RETURN V.flag, OUT.total
"""

GATE_PROGRAM = """\
PROGRAM gate VERSION 1.0
INPUT
    V.mode = "deny"
IF V.mode == "deny" STOP denied(V.mode)
step.work: DO define(goal = V.mode) -> V.out
RETURN V.out
"""


def choose_handler(options, scope):
    return {"cause": f"root cause from {options}", "scope": scope}


def verify_handler(goal, evidence):
    return {"result": "verified", "goal": goal}


def make_repair_worker(test_result, review_result):
    return DeterministicWorker(
        handlers={
            "define": define_handler,
            "choose": choose_handler,
            "test_patch": lambda target: test_result,
            "review_patch": lambda artifact: review_result,
            "verify": verify_handler,
        }
    )


def run_repair(store, run_id, test_result, review_result):
    program = parse_program(REPAIR_PROGRAM)
    coordinator = SequentialCoordinator(
        store=store, worker=make_repair_worker(test_result, review_result)
    )
    return coordinator.execute(program, run_id=run_id)


def test_reference_program_b_failing_check_stops_with_reason_payload(tmp_path):
    # Reference Program B (docs/spec/04-completeness.md), flattened onto
    # single lines: a failed check fires `IF V.tests.status != "passed"
    # STOP failed(V.tests)` exactly like a bare STOP, with the mapping node
    # as the resolved reason.
    with EventStore(tmp_path / "events.db") as store:
        result = run_repair(
            store,
            "run-repair-failed",
            test_result={"status": "failed", "detail": "regression in parser"},
            review_result={"blocking": [], "notes": "clean"},
        )

        assert result["status"] == "failed"
        assert result["outputs"] == {}

        history = store.events("run-repair-failed")
        assert history[-1].event_type is EventType.RUN_FINISHED
        assert history[-1].payload["status"] == "failed"
        assert history[-1].payload["reason"] == {
            "status": "failed",
            "detail": "regression in parser",
        }

        # step.final never executed: no lifecycle events, task cancelled.
        assert not [
            event
            for event in history
            if event.invocation_id == "inv-6"
        ]
        ledger = store.task_ledger("run-repair-failed")
        profile = ledger.profile()
        assert profile["counts"]["total"] == 6
        assert profile["counts"]["completed"] == 5
        assert profile["counts"]["cancelled"] == 1
        assert profile["counts"]["pending"] == 0
        assert profile["counts"]["in_progress"] == 0
        cancelled = [
            task
            for task in ledger.tasks.values()
            if task.status is TaskStatus.CANCELLED
        ]
        assert [task.text for task in cancelled] == ["step.final: DO verify"]

        # State commits stop at the review: V.tests exists, V.result not.
        state = store.project_state("run-repair-failed")
        assert state["nodes"]["V.tests"]["value"] == {
            "status": "failed",
            "detail": "regression in parser",
        }
        assert "V.result" not in state["nodes"]


def test_reference_program_b_false_conditions_continue_to_return(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        result = run_repair(
            store,
            "run-repair-ok",
            test_result={"status": "passed", "cases": 42},
            review_result={"blocking": [], "notes": "clean"},
        )

        assert result["status"] == "succeeded"
        assert result["outputs"]["ART.patch"] is not None
        assert result["outputs"]["V.result"] == {
            "result": "verified",
            "goal": "Observed behavior matches the contract",
        }

        history = store.events("run-repair-ok")
        grouped = events_by_invocation(history)
        assert [event.event_type for event in grouped["inv-6"]] == list(LIFECYCLE)
        ledger = store.task_ledger("run-repair-ok")
        profile = ledger.profile()
        assert profile["counts"]["total"] == 6
        assert profile["counts"]["completed"] == 6
        assert profile["counts"]["cancelled"] == 0


def test_count_condition_over_review_blockers_stops_with_review_reason(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        result = run_repair(
            store,
            "run-repair-blocking",
            test_result={"status": "passed"},
            review_result={"blocking": ["scope creep", "missing test"]},
        )

        assert result["status"] == "failed"
        history = store.events("run-repair-blocking")
        assert history[-1].payload["status"] == "failed"
        assert history[-1].payload["reason"] == {
            "blocking": ["scope creep", "missing test"]
        }
        ledger = store.task_ledger("run-repair-blocking")
        assert ledger.profile()["counts"]["cancelled"] == 1


def test_conditional_count_over_ref_list_value(tmp_path):
    # count() reads a list-valued node committed by an earlier step.
    program = parse_program(
        """\
PROGRAM counter VERSION 1.0
INPUT
    G.seed = 3
step.collect: DO collect_items(seed = G.seed) -> E.items
IF count(E.items) == 3 STOP blocked(E.items)
RETURN E.items
"""
    )
    worker = DeterministicWorker(
        handlers={"collect_items": lambda seed: ["a", "b", "c"]}
    )
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(store=store, worker=worker).execute(
            program, run_id="run-count"
        )
        assert result["status"] == "blocked"
        assert store.events("run-count")[-1].payload["reason"] == ["a", "b", "c"]

    program_false = parse_program(
        """\
PROGRAM counter VERSION 1.0
INPUT
    G.seed = 3
step.collect: DO collect_items(seed = G.seed) -> E.items
IF count(E.items) > 3 STOP blocked(E.items)
RETURN E.items
"""
    )
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(store=store, worker=worker).execute(
            program_false, run_id="run-count-false"
        )
        assert result["status"] == "succeeded"
        assert result["outputs"] == {"E.items": ["a", "b", "c"]}


def test_evaluate_condition_truth_tables():
    values = {
        "V.flag": "go",
        "V.count": 2,
        "V.none": None,
        "E.items": ["a", "b"],
        "V.on": True,
    }
    assert evaluate_condition('V.flag == "go"', values) is True
    assert evaluate_condition('V.flag != "go"', values) is False
    assert evaluate_condition('V.flag != "stop"', values) is True
    assert evaluate_condition("count(E.items) == 2", values) is True
    assert evaluate_condition("count(E.items) != 2", values) is False
    assert evaluate_condition("count(E.items) < 3", values) is True
    assert evaluate_condition("count(E.items) <= 2", values) is True
    assert evaluate_condition("count(E.items) > 1", values) is True
    assert evaluate_condition("count(E.items) >= 3", values) is False
    assert evaluate_condition('V.flag == "go" AND V.count == 2', values) is True
    assert evaluate_condition('V.flag == "go" AND V.count == 3', values) is False
    assert evaluate_condition('V.flag == "stop" OR V.count == 2', values) is True
    assert evaluate_condition('V.flag == "stop" OR V.count == 3', values) is False
    assert evaluate_condition("NOT V.flag == \"go\"", values) is False
    assert evaluate_condition("NOT V.flag == \"stop\"", values) is True
    # Left-associative: (a AND b) OR c.
    assert evaluate_condition(
        'V.flag == "go" AND V.count == 3 OR V.flag == "go"', values
    ) is True
    # JSON-strict equality: a bool never equals 0/1 (same rule as DONE).
    assert evaluate_condition("V.on == 1", values) is False
    assert evaluate_condition("V.on == true", values) is True
    assert evaluate_condition("V.none == null", values) is True


def test_evaluate_condition_missing_or_non_list_refs_raise():
    values = {"V.flag": "go"}
    with pytest.raises(ValueError, match="V.missing.*not in run state"):
        evaluate_condition('V.missing == "go"', values)
    with pytest.raises(ValueError, match="count condition requires a list"):
        evaluate_condition("count(V.flag) > 0", values)


def test_invocation_inside_true_conditional_runs_full_lifecycle(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(BRANCH_PROGRAM)
        result = SequentialCoordinator(
            store=store, worker=make_worker()
        ).execute(program, run_id="run-branch-true")

        assert result["status"] == "succeeded"
        assert result["outputs"] == {"V.flag": define_handler(goal="go")}

        history = store.events("run-branch-true")
        grouped = events_by_invocation(history)
        # The conditional step went through the exact same lifecycle.
        assert [event.event_type for event in grouped["inv-2"]] == list(LIFECYCLE)
        dispatched = next(
            event
            for event in grouped["inv-2"]
            if event.event_type is EventType.INVOCATION_DISPATCHED
        )
        assert dispatched.payload["args"] == {"left": 20, "right": 22}

        ledger = store.task_ledger("run-branch-true")
        assert ledger.profile()["counts"]["total"] == 2
        assert ledger.profile()["counts"]["completed"] == 2
        task = next(
            task
            for task in ledger.tasks.values()
            if task.text == "step.extra: DO calculate"
        )
        assert task.status is TaskStatus.COMPLETED

        state = store.project_state("run-branch-true")
        assert state["nodes"]["OUT.total"]["value"] == 42
        assert state["state_version"] == 2


def test_invocation_inside_false_conditional_is_skipped_entirely(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(
            BRANCH_PROGRAM.replace('G.flag = "go"', 'G.flag = "stop"')
        )
        result = SequentialCoordinator(
            store=store, worker=make_worker()
        ).execute(program, run_id="run-branch-false")

        assert result["status"] == "succeeded"
        assert result["outputs"]["V.flag"] == define_handler(goal="stop")

        history = store.events("run-branch-false")
        assert not [
            event for event in history if event.invocation_id == "inv-2"
        ]
        # No task was ever created for the skipped branch: a false
        # conditional performs no work.
        ledger = store.task_ledger("run-branch-false")
        profile = ledger.profile()
        assert profile["counts"]["total"] == 1
        assert profile["counts"]["completed"] == 1

        state = store.project_state("run-branch-false")
        assert "OUT.total" not in state["nodes"]
        assert state["state_version"] == 1


def test_failing_conditional_invocation_fails_run_atomically(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(BRANCH_PROGRAM)
        worker = DeterministicWorker(
            handlers={
                "define": define_handler,
                "calculate": broken_calculate_handler,
            }
        )
        result = SequentialCoordinator(store=store, worker=worker).execute(
            program, run_id="run-branch-broken"
        )

        assert result["status"] == "failed"
        assert "boom" in result["error"]
        history = store.events("run-branch-broken")
        grouped = events_by_invocation(history)
        assert [event.event_type for event in grouped["inv-2"]][-1] is (
            EventType.FAILED
        )
        assert store.project_state("run-branch-broken")["nodes"].keys() == {
            "V.flag"
        }
        ledger = store.task_ledger("run-branch-broken")
        # The failed conditional step's own task is cancelled by the
        # standard failure batch, exactly like a failing bare invocation.
        assert ledger.profile()["counts"]["cancelled"] == 1
        assert ledger.profile()["counts"]["completed"] == 1


def test_conditional_return_finishes_run_and_cancels_later_tasks(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(EARLY_RETURN_PROGRAM)
        result = SequentialCoordinator(
            store=store, worker=make_worker()
        ).execute(program, run_id="run-early")

        assert result["status"] == "succeeded"
        assert result["outputs"] == {"V.flag": define_handler(goal="early")}

        history = store.events("run-early")
        assert history[-1].event_type is EventType.RUN_FINISHED
        assert history[-1].payload == {"status": "succeeded"}
        assert not [
            event for event in history if event.invocation_id == "inv-2"
        ]
        ledger = store.task_ledger("run-early")
        profile = ledger.profile()
        assert profile["counts"]["total"] == 2
        assert profile["counts"]["completed"] == 1
        assert profile["counts"]["cancelled"] == 1


def test_conditional_return_with_false_condition_falls_through(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(
            EARLY_RETURN_PROGRAM.replace('G.flag = "early"', 'G.flag = "late"')
        )
        result = SequentialCoordinator(
            store=store, worker=make_worker()
        ).execute(program, run_id="run-not-early")

        assert result["status"] == "succeeded"
        assert result["outputs"]["OUT.total"] == 3
        ledger = store.task_ledger("run-not-early")
        assert ledger.profile()["counts"]["completed"] == 2


def test_conditional_stop_before_any_invocation_gates_the_run(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(GATE_PROGRAM)
        result = SequentialCoordinator(
            store=store, worker=make_worker()
        ).execute(program, run_id="run-gate")

        assert result["status"] == "denied"
        history = store.events("run-gate")
        assert history[-1].payload == {"status": "denied", "reason": "deny"}
        assert not [
            event for event in history if event.invocation_id == "inv-1"
        ]
        ledger = store.task_ledger("run-gate")
        profile = ledger.profile()
        assert profile["counts"]["total"] == 1
        assert profile["counts"]["cancelled"] == 1


def test_conditional_gate_open_runs_everything(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(GATE_PROGRAM.replace('V.mode = "deny"', 'V.mode = "allow"'))
        result = SequentialCoordinator(
            store=store, worker=make_worker()
        ).execute(program, run_id="run-gate-open")

        assert result["status"] == "succeeded"
        grouped = events_by_invocation(store.events("run-gate-open"))
        assert [event.event_type for event in grouped["inv-1"]] == list(LIFECYCLE)
