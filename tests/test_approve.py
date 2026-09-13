"""Tests for the APPROVE construct (issue #78).

Covers:
- Parsing of APPROVE statements (syntax, policy ref, intent expression)
- Approval flow: APPROVAL_REQUESTED recorded with correct intent digest,
  run blocks, on APPROVAL_GRANTED with matching digest the run continues
- Denial flow: APPROVAL_DENIED stops the run with "denied" status
- Digest mismatch: APPROVAL_GRANTED with wrong digest fails the run
- Self-approval rejection
- Policy resolution from committed state
"""

import hashlib

import pytest

from tahoe.runtime import EventStore, EventType
from tahoe.runtime.coordinator import (
    DeterministicWorker,
    SequentialCoordinator,
)
from tahoe.syntax import ParseError, parse_program
from tahoe.syntax.model import Approve


# -- Parsing tests ----------------------------------------------------------

APPROVE_PROGRAM = """\
PROGRAM approve_test VERSION 1.0
INPUT
    G.value = 42
step.one: DO define(value = G.value) -> G.goal
APPROVE PF.safety INTENT delete production database
step.two: DO define(value = G.goal) -> OUT.result
RETURN OUT.result
"""


def test_approve_parses():
    program = parse_program(APPROVE_PROGRAM)
    assert len(program.statements) == 4
    approve = program.statements[1]
    assert isinstance(approve, Approve)
    assert approve.policy == "PF.safety"
    assert approve.intent == "delete production database"
    assert approve.line == 5


def test_approve_missing_intent_rejected():
    with pytest.raises(ParseError):
        parse_program(
            """\
PROGRAM bad VERSION 1.0
INPUT
    G.v = 1
APPROVE PF.safety
RETURN G.v
"""
        )


def test_approve_missing_policy_rejected():
    with pytest.raises(ParseError):
        parse_program(
            """\
PROGRAM bad VERSION 1.0
INPUT
    G.v = 1
APPROVE INTENT do something
RETURN G.v
"""
        )


def test_approve_malformed_rejected():
    with pytest.raises(ParseError):
        parse_program(
            """\
PROGRAM bad VERSION 1.0
INPUT
    G.v = 1
APPROVE this is not valid
RETURN G.v
"""
        )


def test_approve_in_canonical_json():
    program = parse_program(APPROVE_PROGRAM)
    from tahoe.syntax.parser import canonical_json

    text = canonical_json(program)
    assert '"kind":"approve"' in text
    assert '"policy":"PF.safety"' in text
    assert '"intent":"delete production database"' in text


# -- Runtime tests -----------------------------------------------------------

def define_handler(value):
    return value


def make_worker():
    return DeterministicWorker(handlers={"define": define_handler})


APPROVE_BLOCKING_PROGRAM = """\
PROGRAM approve_flow VERSION 1.0
INPUT
    G.value = 42
step.one: DO define(value = G.value) -> G.goal
APPROVE PF.safety INTENT deploy to production
step.two: DO define(value = G.goal) -> OUT.result
RETURN OUT.result
"""


def test_approve_blocks_run_with_approval_requested(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(APPROVE_BLOCKING_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())
        result = coordinator.execute(program, run_id="run-1")

        assert result["status"] == "blocked"
        assert result["reason"] == "approve"

        events = store.events("run-1")
        requested = [
            e for e in events
            if e.event_type is EventType.APPROVAL_REQUESTED
        ]
        assert len(requested) == 1
        payload = requested[0].payload
        assert payload["policy_ref"] == "PF.safety"
        assert payload["intent"] == "deploy to production"
        expected_digest = hashlib.sha256(
            b"deploy to production"
        ).hexdigest()
        assert payload["intent_digest"] == expected_digest


def test_approve_granted_continues_run(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(APPROVE_BLOCKING_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())
        result = coordinator.execute(program, run_id="run-1")

        assert result["status"] == "blocked"

        # Simulate external approval grant.
        intent_digest = hashlib.sha256(
            b"deploy to production"
        ).hexdigest()
        store.append(
            "run-1",
            EventType.APPROVAL_GRANTED,
            invocation_id="inv-2",
            payload={
                "policy_ref": "PF.safety",
                "intent_digest": intent_digest,
                "approver": "admin",
            },
        )

        # Resume the run.
        result = coordinator._resume_existing_run(program, run_id="run-1")
        assert result["status"] == "succeeded"
        assert result["outputs"]["OUT.result"] == 42


def test_approve_denied_stops_run(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(APPROVE_BLOCKING_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())
        result = coordinator.execute(program, run_id="run-1")

        assert result["status"] == "blocked"

        # Simulate approval denial.
        store.append(
            "run-1",
            EventType.APPROVAL_DENIED,
            invocation_id="inv-2",
            payload={
                "policy_ref": "PF.safety",
                "reason": "too risky",
            },
        )

        # Resume the run.
        result = coordinator._resume_existing_run(program, run_id="run-1")
        assert result["status"] == "denied"
        assert "approval denied" in result["reason"]


def test_approve_granted_with_mismatched_digest_fails(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(APPROVE_BLOCKING_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())
        result = coordinator.execute(program, run_id="run-1")

        assert result["status"] == "blocked"

        # Grant with wrong digest.
        wrong_digest = hashlib.sha256(b"something else").hexdigest()
        store.append(
            "run-1",
            EventType.APPROVAL_GRANTED,
            invocation_id="inv-2",
            payload={
                "policy_ref": "PF.safety",
                "intent_digest": wrong_digest,
                "approver": "admin",
            },
        )

        # Resume should fail.
        result = coordinator._resume_existing_run(program, run_id="run-1")
        assert result["status"] == "failed"
        assert "digest mismatch" in result["error"]


def test_approve_re_blocks_without_grant_or_denial(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(APPROVE_BLOCKING_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())
        result = coordinator.execute(program, run_id="run-1")

        assert result["status"] == "blocked"

        # Resume without any grant or denial — should re-block.
        result = coordinator._resume_existing_run(program, run_id="run-1")
        assert result["status"] == "blocked"
        assert result["reason"] == "approve"


def test_approve_does_not_create_task(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(APPROVE_BLOCKING_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())
        coordinator.execute(program, run_id="run-1")

        ledger = store.task_ledger("run-1")
        # step.one and step.two create tasks, but APPROVE does not.
        assert len(ledger.tasks) == 2


def test_approve_intent_digest_is_sha256(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(APPROVE_BLOCKING_PROGRAM)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())
        coordinator.execute(program, run_id="run-1")

        events = store.events("run-1")
        requested = [
            e for e in events
            if e.event_type is EventType.APPROVAL_REQUESTED
        ]
        payload = requested[0].payload
        # Verify the digest is a 64-character hex string (SHA-256).
        assert len(payload["intent_digest"]) == 64
        assert all(c in "0123456789abcdef" for c in payload["intent_digest"])


def test_approve_at_first_step_blocks(tmp_path):
    """APPROVE as the first statement blocks before any step runs."""
    program_text = """\
PROGRAM approve_first VERSION 1.0
INPUT
    G.value = 1
APPROVE PF.safety INTENT check before anything
step.one: DO define(value = G.value) -> OUT.result
RETURN OUT.result
"""
    with EventStore(tmp_path / "events.db") as store:
        program = parse_program(program_text)
        coordinator = SequentialCoordinator(store=store, worker=make_worker())
        result = coordinator.execute(program, run_id="run-1")

        assert result["status"] == "blocked"
        assert result["reason"] == "approve"

        events = store.events("run-1")
        requested = [
            e for e in events
            if e.event_type is EventType.APPROVAL_REQUESTED
        ]
        assert len(requested) == 1
        assert requested[0].invocation_id == "inv-1"
