"""Tests for the SQLite EventStore (docs/spec/03-runtime-and-events.md)."""

import hashlib
import json
import sqlite3
from dataclasses import FrozenInstanceError

import pytest

from tikhon.runtime import EventStore, EventType
from tikhon.state import StateDelta


def make_delta() -> StateDelta:
    return StateDelta(
        add_nodes=({"id": "n1", "kind": "task"}, {"id": "n2", "kind": "task"}),
        revise_nodes=({"id": "n1", "status": "done"},),
        retire_nodes=("n2",),
        add_artifacts=({"id": "a1", "digest": "deadbeef"},),
    )


def test_append_and_replay(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-1", "prog@1", metadata={"owner": "alex"})
        store.append("run-1", EventType.RUN_STARTED)
        event = store.append(
            "run-1",
            EventType.SUCCEEDED,
            instruction_id="prog.step[0]",
            invocation_id="inv-1",
            attempt=1,
            expected_state_version=0,
            payload={"delta": make_delta(), "tokens": 42},
        )

        assert event.seq == 1
        assert event.state_version == 1
        assert event.payload_ref == hashlib.sha256(
            json.dumps(
                {"delta": make_delta().to_dict(), "tokens": 42},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        history = store.events("run-1")
        assert isinstance(history, tuple)
        assert [e.seq for e in history] == [0, 1]
        assert history[1].event_type is EventType.SUCCEEDED
        assert history[1].payload == {"delta": make_delta().to_dict(), "tokens": 42}
        assert history[1].instruction_id == "prog.step[0]"
        assert history[1].invocation_id == "inv-1"

        state = store.project_state("run-1")
        assert state["state_version"] == 1
        assert state["nodes"] == {"n1": {"id": "n1", "kind": "task", "status": "done"}}
        assert state["artifacts"] == {"a1": {"id": "a1", "digest": "deadbeef"}}

        info = store.run("run-1")
        assert info["program_version"] == "prog@1"
        assert info["metadata"] == {"owner": "alex"}
        assert info["state_version"] == 1
        assert info["event_count"] == 2


def test_payload_stored_as_canonical_json(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-1", "prog@1")
        store.append("run-1", EventType.RESULT_RECEIVED, payload={"b": 1, "a": {"z": 1, "y": 2}})

        raw = sqlite3.connect(tmp_path / "events.db").execute(
            "SELECT payload, payload_ref FROM events"
        ).fetchone()
        expected = json.dumps({"a": {"y": 2, "z": 1}, "b": 1}, sort_keys=True, separators=(",", ":"))
        assert raw[0] == expected
        assert raw[1] == hashlib.sha256(expected.encode("utf-8")).hexdigest()


def test_optimistic_version_conflict_rejected(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-1", "prog@1")
        store.append(
            "run-1",
            EventType.SUCCEEDED,
            invocation_id="inv-1",
            payload={"delta": make_delta()},
        )
        assert store.project_state("run-1")["state_version"] == 1

        with pytest.raises(ValueError, match="state version conflict"):
            store.append(
                "run-1",
                EventType.SUCCEEDED,
                invocation_id="inv-2",
                expected_state_version=0,
                payload={"delta": StateDelta(add_nodes=({"id": "n9"},))},
            )

        # rejected append was not persisted
        assert len(store.events("run-1")) == 1
        assert "n9" not in store.project_state("run-1")["nodes"]

        # matching the current version commits
        event = store.append(
            "run-1",
            EventType.SUCCEEDED,
            invocation_id="inv-2",
            expected_state_version=1,
            payload={"delta": StateDelta(add_nodes=({"id": "n9"},))},
        )
        assert event.state_version == 2
        assert store.project_state("run-1")["nodes"]["n9"] == {"id": "n9"}


def test_duplicate_succeeded_terminal_rejected(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-1", "prog@1")
        store.append(
            "run-1",
            EventType.SUCCEEDED,
            invocation_id="inv-1",
            payload={"delta": StateDelta(add_nodes=({"id": "n1"},))},
        )

        with pytest.raises(ValueError, match="SUCCEEDED terminal"):
            store.append(
                "run-1",
                EventType.SUCCEEDED,
                invocation_id="inv-1",
                attempt=2,
                payload={"delta": StateDelta(add_nodes=({"id": "n1b"},))},
            )

        # rejected duplicate was not persisted; seq stays gapless
        assert len(store.events("run-1")) == 1
        assert store.project_state("run-1")["state_version"] == 1
        assert "n1b" not in store.project_state("run-1")["nodes"]

        # a different invocation may still succeed
        event = store.append(
            "run-1",
            EventType.SUCCEEDED,
            invocation_id="inv-2",
            payload={"delta": StateDelta(add_nodes=({"id": "n2"},))},
        )
        assert event.seq == 1

        # SUCCEEDED with empty invocation_id is not deduplicated
        store.append("run-1", EventType.SUCCEEDED)
        store.append("run-1", EventType.SUCCEEDED)
        assert [e.seq for e in store.events("run-1")] == [0, 1, 2, 3]


def test_persists_across_reopen(tmp_path):
    db = tmp_path / "events.db"
    store = EventStore(db)
    store.create_run("run-1", "prog@1", metadata={"k": "v"})
    store.append("run-1", EventType.RUN_STARTED)
    store.append(
        "run-1",
        EventType.SUCCEEDED,
        invocation_id="inv-1",
        payload={"delta": make_delta()},
    )
    before = store.project_state("run-1")
    store.close()

    reopened = EventStore(db)
    try:
        history = reopened.events("run-1")
        assert [e.seq for e in history] == [0, 1]
        assert history[1].invocation_id == "inv-1"
        assert history[1].event_type is EventType.SUCCEEDED
        assert history[1].payload == {"delta": make_delta().to_dict()}
        assert reopened.run("run-1")["metadata"] == {"k": "v"}
        assert reopened.project_state("run-1") == before

        # sequencing continues gaplessly after reopen
        event = reopened.append("run-1", EventType.RUN_FINISHED)
        assert event.seq == 2
        assert event.state_version == 1
    finally:
        reopened.close()


def test_runs_are_independent(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-a", "prog@1")
        store.create_run("run-b", "prog@2")
        store.append(
            "run-a",
            EventType.SUCCEEDED,
            invocation_id="inv-a",
            payload={"delta": StateDelta(add_nodes=({"id": "a1"},))},
        )
        store.append("run-b", EventType.RUN_STARTED)

        # run-b starts from its own seq 0 and state version 0
        event = store.append(
            "run-b",
            EventType.SUCCEEDED,
            invocation_id="inv-b",
            expected_state_version=0,
            payload={"delta": StateDelta(add_nodes=({"id": "b1"},))},
        )
        assert event.seq == 1
        assert event.state_version == 1

        state_a = store.project_state("run-a")
        state_b = store.project_state("run-b")
        assert state_a["state_version"] == 1
        assert state_b["state_version"] == 1
        assert set(state_a["nodes"]) == {"a1"}
        assert set(state_b["nodes"]) == {"b1"}
        assert state_b["program_version"] == "prog@2"

        assert [e.seq for e in store.events("run-a")] == [0]
        assert [e.seq for e in store.events("run-b")] == [0, 1]


def test_state_delta_roundtrip_and_immutability():
    delta = make_delta()
    assert StateDelta.from_dict(delta.to_dict()) == delta
    assert not delta.is_empty()
    assert StateDelta().is_empty()

    with pytest.raises(FrozenInstanceError):
        delta.add_nodes = ()


def test_unknown_and_duplicate_runs(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        with pytest.raises(ValueError, match="unknown run"):
            store.append("nope", EventType.RUN_STARTED)
        with pytest.raises(KeyError):
            store.run("nope")

        store.create_run("run-1", "prog@1")
        with pytest.raises(ValueError, match="already exists"):
            store.create_run("run-1", "prog@2")


def test_validation_failed_event_roundtrip(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        store.create_run("run-1", "prog@1")
        event = store.append(
            "run-1",
            EventType.VALIDATION_FAILED,
            instruction_id="step.one",
            invocation_id="inv-1",
            task_id="task-1",
            payload={
                "step_id": "step.one",
                "predicate": {"op": "equals", "ref": "E.result", "value": 11},
                "detail": "expected 11, got 10",
            },
        )
        assert event.state_version == 0

        history = store.events("run-1")
        assert [e.event_type for e in history] == [EventType.VALIDATION_FAILED]
        assert history[0].payload["predicate"]["ref"] == "E.result"
        assert history[0].instruction_id == "step.one"
        assert history[0].task_id == "task-1"
