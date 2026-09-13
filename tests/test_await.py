"""Tests for the AWAIT construct (issue #77).

Covers parsing (with and without TIMEOUT), suspension (AWAIT_SUSPENDED
recorded, run returns "blocked"), resume on event match (AWAIT_RESUMED
recorded, next plan entry executes), resume on timeout (AWAIT_RESUMED
with reason "timeout", continuation without event), and resume
re-blocking when neither event nor timeout has fired.
"""

import time

import pytest

from tahoe.memory import KnowledgeBase
from tahoe.runtime import EventStore, EventType
from tahoe.runtime.coordinator import (
    DeterministicWorker,
    SequentialCoordinator,
)
from tahoe.syntax import Await, parse_program
from tahoe.resume import resume_run


# -- Parsing ---------------------------------------------------------------

def test_await_parses_without_timeout():
    program = parse_program(
        'PROGRAM waiter VERSION 1.0\n'
        'INPUT\n'
        '    G.ready = false\n'
        'AWAIT event.ready\n'
        'STOP completed()\n'
    )
    assert len(program.statements) == 2
    stmt = program.statements[0]
    assert isinstance(stmt, Await)
    assert stmt.selector == "event.ready"
    assert stmt.timeout is None


def test_await_parses_with_timeout():
    program = parse_program(
        'PROGRAM waiter VERSION 1.0\n'
        'INPUT\n'
        '    G.ready = false\n'
        'AWAIT event.ready TIMEOUT 30s\n'
        'STOP completed()\n'
    )
    assert len(program.statements) == 2
    stmt = program.statements[0]
    assert isinstance(stmt, Await)
    assert stmt.selector == "event.ready"
    assert stmt.timeout == "30s"


def test_await_rejects_empty_selector():
    with pytest.raises(Exception):
        parse_program(
            'PROGRAM waiter VERSION 1.0\n'
            'INPUT\n'
            '    G.ready = false\n'
            'AWAIT\n'
            'STOP completed()\n'
        )


# -- Suspension -----------------------------------------------------------

AWAIT_PROGRAM = """\
PROGRAM waiter VERSION 1.0
INPUT
    G.goal = "done"
step.setup: DO define(goal = G.goal) -> G.prepared
AWAIT event.ready
step.finish: DO define(goal = G.prepared) -> OUT.result
RETURN OUT.result
"""

AWAIT_TIMEOUT_PROGRAM = """\
PROGRAM waiter VERSION 1.0
INPUT
    G.goal = "done"
step.setup: DO define(goal = G.goal) -> G.prepared
AWAIT event.ready TIMEOUT 0s
step.finish: DO define(goal = G.prepared) -> OUT.result
RETURN OUT.result
"""


def test_await_suspends_and_blocks(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(handlers={"define": lambda goal: goal})
        result = SequentialCoordinator(store, worker).execute(
            parse_program(AWAIT_PROGRAM), run_id="run-await-suspend"
        )
        assert result["status"] == "blocked"
        assert result["reason"] == "await"
        assert result["selector"] == "event.ready"

        history = store.events("run-await-suspend")
        suspended = [
            e for e in history if e.event_type is EventType.AWAIT_SUSPENDED
        ]
        assert len(suspended) == 1
        assert suspended[0].payload["selector"] == "event.ready"
        assert suspended[0].payload["timeout"] is None

        # No RUN_FINISHED — the run is non-terminal.
        run_finished = [
            e for e in history if e.event_type is EventType.RUN_FINISHED
        ]
        assert len(run_finished) == 0


# -- Resume on event match -------------------------------------------------

def test_await_resumes_on_event(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(handlers={"define": lambda goal: goal})

        # First run: suspends.
        result = SequentialCoordinator(store, worker).execute(
            parse_program(AWAIT_PROGRAM), run_id="run-await-resume"
        )
        assert result["status"] == "blocked"

        # Simulate external event: append an EXTERNAL_EVENT matching the selector.
        store.append(
            "run-await-resume",
            EventType.EXTERNAL_EVENT,
            payload={"selector": "event.ready", "source": "test"},
        )

        # Resume: should find the event and continue.
        result = resume_run(
            store, worker, "run-await-resume", parse_program(AWAIT_PROGRAM)
        )
        assert result["status"] == "succeeded"
        assert result["outputs"] == {"OUT.result": "done"}

        history = store.events("run-await-resume")
        resumed = [
            e for e in history if e.event_type is EventType.AWAIT_RESUMED
        ]
        assert len(resumed) == 1
        assert resumed[0].payload["reason"] == "event"
        assert resumed[0].payload["selector"] == "event.ready"

        run_finished = [
            e for e in history if e.event_type is EventType.RUN_FINISHED
        ]
        assert len(run_finished) == 1
        assert run_finished[0].payload["status"] == "succeeded"


# -- Resume on timeout ----------------------------------------------------

def test_await_resumes_on_timeout(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(handlers={"define": lambda goal: goal})

        # First run: suspends with 0s timeout (already expired on resume).
        result = SequentialCoordinator(store, worker).execute(
            parse_program(AWAIT_TIMEOUT_PROGRAM), run_id="run-await-timeout"
        )
        assert result["status"] == "blocked"

        # No external event appended — timeout should fire on resume.
        result = resume_run(
            store, worker, "run-await-timeout",
            parse_program(AWAIT_TIMEOUT_PROGRAM)
        )
        assert result["status"] == "succeeded"
        assert result["outputs"] == {"OUT.result": "done"}

        history = store.events("run-await-timeout")
        resumed = [
            e for e in history if e.event_type is EventType.AWAIT_RESUMED
        ]
        assert len(resumed) == 1
        assert resumed[0].payload["reason"] == "timeout"
        assert resumed[0].payload["selector"] == "event.ready"


# -- Re-block when neither event nor timeout ------------------------------

def test_await_reblocks_without_event_or_timeout(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = DeterministicWorker(handlers={"define": lambda goal: goal})

        # First run: suspends (no timeout).
        result = SequentialCoordinator(store, worker).execute(
            parse_program(AWAIT_PROGRAM), run_id="run-await-reblock"
        )
        assert result["status"] == "blocked"

        # Resume without event: should re-block.
        result = resume_run(
            store, worker, "run-await-reblock", parse_program(AWAIT_PROGRAM)
        )
        assert result["status"] == "blocked"
        assert result["reason"] == "await"

        # Only one AWAIT_SUSPENDED (not duplicated on re-block).
        history = store.events("run-await-reblock")
        suspended = [
            e for e in history if e.event_type is EventType.AWAIT_SUSPENDED
        ]
        assert len(suspended) == 1
        resumed = [
            e for e in history if e.event_type is EventType.AWAIT_RESUMED
        ]
        assert len(resumed) == 0
