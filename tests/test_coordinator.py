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

import pytest

from tikhon.runtime import EventStore, EventType
from tikhon.runtime.coordinator import (
    DeterministicWorker,
    SequentialCoordinator,
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
