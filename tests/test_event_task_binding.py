"""Tests binding the TaskLedger to the durable EventStore.

Per docs/spec/03-runtime-and-events.md: ledger events are stored as
TASK_UPDATED events, every invocation envelope may carry a ``task_id``,
and the coordinator reprojects the ledger deterministically from the
run's stored task events.
"""

import pytest

from tikhon.runtime import EventStore, EventType
from tikhon.runtime.events import _Record
from tikhon.runtime.tasks import TaskLedger, TaskLedgerError, TaskStatus
from tikhon.state import StateDelta


def test_two_ledger_events_append(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-1", "prog@1")

        ledger = TaskLedger()
        task = ledger.create_task(text="draft the plan")
        ledger.start_task(task.id)

        store.append_task_event("run-1", dict(ledger.events[0]))
        store.append_task_event("run-1", dict(ledger.events[1]))

        history = store.events("run-1")
        assert [e.seq for e in history] == [0, 1]
        assert all(e.event_type is EventType.TASK_UPDATED for e in history)

        replayed = store.task_ledger("run-1")
        assert replayed.tasks[task.id].status is TaskStatus.IN_PROGRESS
        assert replayed.tasks[task.id].text == "draft the plan"


def test_profile_matches_before_and_after_reopen(tmp_path):
    db = tmp_path / "events.db"

    ledger = TaskLedger()
    a = ledger.create_task(text="write tests")
    b = ledger.create_task(text="run tests", dependencies=(a.id,))
    ledger.start_task(a.id)
    ledger.record_invocation(a.id, tokens=10, cost=0.5, elapsed_seconds=1.0)
    ledger.complete_task(a.id, evidence="all green")
    ledger.start_task(b.id)
    ledger.cancel_task(b.id)

    store = EventStore(db)
    try:
        store.create_run("run-1", "prog@1")
        for event in ledger.events:
            store.append_task_event("run-1", dict(event))
        expected = ledger.profile()
        assert store.task_ledger("run-1").profile() == expected
    finally:
        store.close()

    reopened = EventStore(db)
    try:
        assert reopened.task_ledger("run-1").profile() == expected
    finally:
        reopened.close()


def test_event_task_id_roundtrip_for_invocation(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-1", "prog@1")
        store.append(
            "run-1",
            EventType.RESULT_RECEIVED,
            invocation_id="inv-1",
            task_id="task-1",
            payload={"tokens": 5},
        )

        event = store.events("run-1")[-1]
        assert event.event_type is EventType.RESULT_RECEIVED
        assert event.invocation_id == "inv-1"
        assert event.task_id == "task-1"


def test_append_task_event_rejects_invalid_transition(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-1", "prog@1")

        ledger = TaskLedger()
        task = ledger.create_task(text="work")
        store.append_task_event("run-1", dict(ledger.events[0]))

        with pytest.raises(TaskLedgerError):
            store.append_task_event("run-1", {"kind": "task_started", "id": "missing"})

        # completing a pending task (never started) is an invalid transition
        with pytest.raises(TaskLedgerError):
            store.append_task_event(
                "run-1", {"kind": "task_completed", "id": task.id, "evidence": "x"}
            )

        # rejected appends were not persisted; seq stays gapless
        history = store.events("run-1")
        assert len(history) == 1
        assert [e.seq for e in history] == [0]
        assert store.task_ledger("run-1").tasks[task.id].status is TaskStatus.PENDING


def test_runs_have_independent_ledgers(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-a", "prog@1")
        store.create_run("run-b", "prog@1")

        ledger_a = TaskLedger()
        task_a = ledger_a.create_task(text="alpha")
        for event in ledger_a.events:
            store.append_task_event("run-a", dict(event))

        ledger_b = TaskLedger()
        task_b = ledger_b.create_task(text="beta")
        ledger_b.start_task(task_b.id)
        for event in ledger_b.events:
            store.append_task_event("run-b", dict(event))

        view_a = store.task_ledger("run-a")
        view_b = store.task_ledger("run-b")
        assert set(view_a.tasks) == {task_a.id}
        assert view_a.tasks[task_a.id].text == "alpha"
        assert view_a.tasks[task_a.id].status is TaskStatus.PENDING

        assert set(view_b.tasks) == {task_b.id}
        assert view_b.tasks[task_b.id].text == "beta"
        assert view_b.tasks[task_b.id].status is TaskStatus.IN_PROGRESS


def test_invalid_second_batch_record_leaves_event_count_unchanged(tmp_path):
    """If any record in a batch is invalid, the *entire* batch rolls back
    and the event count is unchanged."""
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-1", "prog@1")

        # first record: a valid task_created
        # second record: invalid task_started for a nonexistent task id
        records = [
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id="task-1",
                payload={"kind": "task_created", "id": "task-1",
                         "text": "do work", "priority": 0,
                         "parent": None, "dependencies": [], "creator": "user"},
                store=store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id="missing",
                payload={"kind": "task_started", "id": "missing"},
                store=store,
            ),
        ]

        with pytest.raises(TaskLedgerError):
            store.append_batch("run-1", records)

        # nothing was persisted
        assert len(store.events("run-1")) == 0
        assert store.run("run-1")["event_count"] == 0
        assert store.task_ledger("run-1").tasks == {}


def test_successful_state_plus_task_terminal_batch_replays_coherently(tmp_path):
    """A batch containing SUCCEEDED (state delta), invocation_recorded,
    and task_completed replays coherently: state projection and task
    ledger agree with the events on disk."""
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-1", "prog@1")

        # precondition: one task created and started
        store.append_task_event("run-1", {
            "kind": "task_created", "id": "task-1", "text": "work",
            "priority": 0, "parent": None, "dependencies": [],
            "creator": "coordinator",
        })
        store.append_task_event("run-1", {"kind": "task_started", "id": "task-1"})
        store.append(
            "run-1",
            EventType.INVOCATION_READY,
            instruction_id="step.1",
            invocation_id="inv-1",
            task_id="task-1",
            payload={"command": "calculate"},
        )
        store.append(
            "run-1",
            EventType.INVOCATION_DISPATCHED,
            instruction_id="step.1",
            invocation_id="inv-1",
            task_id="task-1",
            payload={"args": {}},
        )
        store.append(
            "run-1",
            EventType.RESULT_RECEIVED,
            instruction_id="step.1",
            invocation_id="inv-1",
            task_id="task-1",
            payload={"result": 42},
        )
        store.append(
            "run-1",
            EventType.VALIDATION_PASSED,
            instruction_id="step.1",
            invocation_id="inv-1",
            task_id="task-1",
            payload={},
        )

        expected_sv = store._current_state_version("run-1")
        delta = StateDelta(add_nodes=({"id": "OUT.total", "value": 42},))

        # the terminal batch: SUCCEEDED + invocation_recorded + task_completed
        records = [
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id="step.1",
                invocation_id="inv-1",
                task_id="task-1",
                expected_state_version=expected_sv,
                payload={"delta": delta},
                store=store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id="task-1",
                payload={"kind": "invocation_recorded", "id": "task-1",
                         "tokens": 0, "cost": 0.0, "retries": 0,
                         "elapsed_seconds": 0.0},
                store=store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id="task-1",
                payload={"kind": "task_completed", "id": "task-1",
                         "evidence": "calculate -> ['OUT.total']"},
                store=store,
            ),
        ]

        events = store.append_batch("run-1", records)
        assert len(events) == 3
        assert events[0].event_type is EventType.SUCCEEDED
        assert events[0].state_version == expected_sv + 1
        assert events[1].event_type is EventType.TASK_UPDATED
        assert events[2].event_type is EventType.TASK_UPDATED

        # state projection is coherent
        state = store.project_state("run-1")
        assert state["state_version"] == expected_sv + 1
        assert "OUT.total" in state["nodes"]
        assert state["nodes"]["OUT.total"]["value"] == 42

        # task ledger is coherent
        ledger = store.task_ledger("run-1")
        assert ledger.tasks["task-1"].status is TaskStatus.COMPLETED
        assert ledger.tasks["task-1"].evidence == ("calculate -> ['OUT.total']",)
        profile = ledger.profile()
        assert profile["counts"]["completed"] == 1
        assert profile["counts"]["in_progress"] == 0
        assert profile["percent_complete"] == 100.0

        # replay across reopen is coherent
        store.close()
        reopened = EventStore(tmp_path / "events.db")
        try:
            assert reopened.project_state("run-1") == state
            ledger_after = reopened.task_ledger("run-1")
            assert ledger_after.tasks["task-1"].status is TaskStatus.COMPLETED
            assert ledger_after.profile() == profile
        finally:
            reopened.close()
