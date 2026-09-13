"""Tests for the FIRST event-choice construct (issue #76).

Covers parsing, execution, and event matching:

- Parse a FIRST block with two selectors and a body
- Parse a FIRST block with three selectors
- Reject a FIRST with fewer than two selectors
- Reject a FIRST with an empty body
- Execute a FIRST block when an event matches the first selector
- Execute a FIRST block when an event matches the second selector
- Block (return None) when no event matches any selector
- Record FIRST_EVENT_MATCHED with the correct selector index
- Body statements execute after the match (DO invocations commit)
- STOP in the body terminates the run
"""

import tempfile
from pathlib import Path

import pytest

from tahoe.runtime import EventStore, EventType
from tahoe.runtime.coordinator import (
    DeterministicWorker,
    SequentialCoordinator,
)
from tahoe.syntax import parse_program, validate_program
from tahoe.syntax.model import First


FIRST_TWO_SELECTORS = """\
PROGRAM first_choice VERSION 1.0
INPUT
    G.input = "hello"
FIRST approval.granted OR approval.denied
    step.respond: DO define(text = G.input) -> OUT.result
    RETURN OUT.result
"""

FIRST_THREE_SELECTORS = """\
PROGRAM first_three VERSION 1.0
INPUT
    G.input = "hello"
FIRST approval.granted OR approval.denied OR timeout.expired
    step.respond: DO define(text = G.input) -> OUT.result
    RETURN OUT.result
"""

FIRST_WITH_STOP = """\
PROGRAM first_stop VERSION 1.0
INPUT
    G.input = "hello"
FIRST approval.granted OR approval.denied
    STOP completed()
"""

FIRST_ONE_SELECTOR_BAD = """\
PROGRAM first_bad VERSION 1.0
INPUT
    G.input = "hello"
FIRST approval.granted
    step.respond: DO define(text = G.input) -> OUT.result
    RETURN OUT.result
"""

FIRST_EMPTY_BODY_BAD = """\
PROGRAM first_empty VERSION 1.0
INPUT
    G.input = "hello"
FIRST approval.granted OR approval.denied
RETURN OUT.x
"""

FIRST_WITH_STEP_BEFORE = """\
PROGRAM first_prefixed VERSION 1.0
INPUT
    G.input = "hello"
step.prep: DO define(value = G.input) -> G.prepared
FIRST approval.granted OR approval.denied
    step.respond: DO define(text = G.prepared) -> OUT.result
    RETURN OUT.result
"""


def _run_with_event(source: str, event_type: EventType | None, handlers: dict, run_id="run-first-1"):
    """Parse and run a program, optionally injecting an event after run creation.

    We subclass SequentialCoordinator to inject the event right after
    create_run, before the plan drives.  The FIRST entry scans the
    event history and finds the injected event.
    """
    program = parse_program(source)
    store = EventStore(":memory:")
    worker = DeterministicWorker(handlers)

    class InjectingCoordinator(SequentialCoordinator):
        def _drive_plan(self, *args, **kwargs):
            if event_type is not None:
                store.append(run_id, event_type, payload={"injected": True})
            return super()._drive_plan(*args, **kwargs)

    coordinator = InjectingCoordinator(store, worker)
    return coordinator.execute(program, run_id=run_id)


def _make_store():
    return EventStore(":memory:")


class TestFirstParsing:
    def test_parse_two_selectors(self):
        program = parse_program(FIRST_TWO_SELECTORS)
        first_stmts = [s for s in program.statements if isinstance(s, First)]
        assert len(first_stmts) == 1
        first = first_stmts[0]
        assert first.selectors == ("approval.granted", "approval.denied")
        assert len(first.body) == 2

    def test_parse_three_selectors(self):
        program = parse_program(FIRST_THREE_SELECTORS)
        first_stmts = [s for s in program.statements if isinstance(s, First)]
        assert len(first_stmts) == 1
        first = first_stmts[0]
        assert first.selectors == (
            "approval.granted",
            "approval.denied",
            "timeout.expired",
        )

    def test_reject_single_selector(self):
        with pytest.raises(Exception):
            parse_program(FIRST_ONE_SELECTOR_BAD)

    def test_reject_empty_body(self):
        with pytest.raises(Exception):
            parse_program(FIRST_EMPTY_BODY_BAD)

    def test_first_not_in_unsupported(self):
        import tahoe.syntax.parser as p
        assert "FIRST" not in p._UNSUPPORTED


class TestFirstExecution:
    def test_first_matches_first_selector(self):
        result = _run_with_event(
            FIRST_TWO_SELECTORS,
            EventType.APPROVAL_GRANTED,
            {"define": lambda **kw: kw.get("text", "")},
        )
        assert result["status"] == "succeeded"
        assert result["outputs"]["OUT.result"] == "hello"

    def test_first_matches_second_selector(self):
        result = _run_with_event(
            FIRST_TWO_SELECTORS,
            EventType.APPROVAL_DENIED,
            {"define": lambda **kw: kw.get("text", "")},
        )
        assert result["status"] == "succeeded"
        assert result["outputs"]["OUT.result"] == "hello"

    def test_first_no_matching_event_blocks(self):
        result = _run_with_event(
            FIRST_TWO_SELECTORS,
            None,
            {"define": lambda **kw: kw.get("text", "")},
        )
        assert result["status"] != "succeeded"

    def test_first_records_event_matched(self):
        store = EventStore(":memory:")
        program = parse_program(FIRST_TWO_SELECTORS)
        worker = DeterministicWorker({"define": lambda **kw: kw.get("text", "")})

        class InjectingCoordinator(SequentialCoordinator):
            def _drive_plan(self, *args, **kwargs):
                store.append("run-first-1", EventType.APPROVAL_DENIED, payload={"reason": "no"})
                return super()._drive_plan(*args, **kwargs)

        coordinator = InjectingCoordinator(store, worker)
        coordinator.execute(program, run_id="run-first-1")
        events = store.events("run-first-1")
        matched = [
            e for e in events if e.event_type is EventType.FIRST_EVENT_MATCHED
        ]
        assert len(matched) == 1
        assert matched[0].payload["selector_index"] == 1
        assert matched[0].payload["selector"] == "approval.denied"

    def test_first_with_stop_body(self):
        result = _run_with_event(
            FIRST_WITH_STOP,
            EventType.APPROVAL_GRANTED,
            {"define": lambda **kw: kw.get("text", "")},
        )
        assert result["status"] == "succeeded"

    def test_first_body_invocation_commits(self):
        store = EventStore(":memory:")
        program = parse_program(FIRST_TWO_SELECTORS)
        worker = DeterministicWorker({"define": lambda **kw: kw.get("text", "")})

        class InjectingCoordinator(SequentialCoordinator):
            def _drive_plan(self, *args, **kwargs):
                store.append("run-first-1", EventType.APPROVAL_GRANTED, payload={"ok": True})
                return super()._drive_plan(*args, **kwargs)

        coordinator = InjectingCoordinator(store, worker)
        result = coordinator.execute(program, run_id="run-first-1")
        events = store.events("run-first-1")
        # The body invocation committed OUT.result (SUCCEEDED with delta)
        body_succeeded = [
            e
            for e in events
            if e.event_type is EventType.SUCCEEDED
            and e.invocation_id
            and "step.respond" in e.invocation_id
        ]
        assert len(body_succeeded) >= 1
        # FIRST_EVENT_MATCHED was recorded
        matched = [
            e for e in events if e.event_type is EventType.FIRST_EVENT_MATCHED
        ]
        assert len(matched) == 1
        # The run succeeded with the body's output
        assert result["status"] == "succeeded"
        assert result["outputs"]["OUT.result"] == "hello"

    def test_first_with_step_before(self):
        result = _run_with_event(
            FIRST_WITH_STEP_BEFORE,
            EventType.APPROVAL_GRANTED,
            {"define": lambda **kw: kw.get("text", kw.get("value", ""))},
        )
        assert result["status"] == "succeeded"
        assert result["outputs"]["OUT.result"] == "hello"

    def test_first_event_type_in_enum(self):
        assert hasattr(EventType, "FIRST_EVENT_MATCHED")
        assert EventType.FIRST_EVENT_MATCHED.value == "first.event_matched"
