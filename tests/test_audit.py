"""Tests for replay-based run verification (issue #14, tikhon.audit).

Contract under test:

- ``audit_run(store, run_id) -> AuditReport`` re-derives every run
  invariant from the event store alone and reports each violation with
  the offending event sequence numbers: gapless sequencing, event
  truthfulness (VALIDATION_PASSED/SUCCEEDED vs FAILED ordering, at most
  one RUN_FINISHED, RUN_FINISHED status consistency), ledger invariants
  on terminal runs (no PENDING/IN_PROGRESS tasks, nonempty evidence on
  COMPLETED tasks, nonempty task_id/instruction_id on invocation-bound
  events), and state projection determinism.
- ``tikhon audit --db PATH --run-id ID`` prints OK or each violation
  with seq refs; exits 0 clean, 1 on violations, 1 for unknown run.

Runs are produced by SequentialCoordinator + DeterministicWorker;
violations are injected by appending crafted events directly via
``EventStore.append`` (or by tampering with the store, where the append
API is deliberately unable to produce the corruption).
"""

from __future__ import annotations

import pytest

from tikhon.audit import audit_run
from tikhon.cli import _deterministic_handlers, main
from tikhon.runtime import (
    DeterministicWorker,
    EventStore,
    EventType,
    SequentialCoordinator,
)
from tikhon.runtime.events import canonical_json
from tikhon.syntax import parse_program

RUN_ID = "run-1"

SUCCEED_PROGRAM = """\
PROGRAM audit_ok VERSION 1.0

INPUT
    G.goal = "produce two clean results"

step.frame: DO define(request = G.goal) -> G.plan
step.act: DO search(query = G.plan) -> E.hits

RETURN G.plan, E.hits
"""

BLOCKED_PROGRAM = """\
PROGRAM audit_blocked VERSION 1.0

step.frame: DO define(request = "wait for input") -> G.plan

STOP blocked(G.plan)
"""

RAISE_PROGRAM = """\
PROGRAM audit_boom VERSION 1.0

step.boom: DO boom(x = 1) -> E.r

RETURN E.r
"""

MISSING_KEY_PROGRAM = """\
PROGRAM audit_missing_key VERSION 1.0

step.split: DO define(value = {"other": 1}) -> A.one, A.two

RETURN A.one, A.two
"""


def _boom_handlers():
    handlers = _deterministic_handlers()

    def _boom(**kwargs):
        raise RuntimeError("kaput")

    handlers["boom"] = _boom
    return handlers


def _execute(store, program_text, run_id=RUN_ID, handlers=None):
    program = parse_program(program_text)
    worker = DeterministicWorker(
        handlers if handlers is not None else _deterministic_handlers()
    )
    coordinator = SequentialCoordinator(store, worker)
    return coordinator.execute(program, run_id=run_id)


def _assert_clean(store, run_id=RUN_ID):
    report = audit_run(store, run_id)
    assert report.ok, f"unexpected findings: {report.to_dict()}"
    assert report.findings == ()
    assert report.run_id == run_id
    assert report.event_count > 0
    return report


def _events_of_type(store, run_id, event_type):
    return [ev for ev in store.events(run_id) if ev.event_type is event_type]


def _finding(report, code):
    matches = [f for f in report.findings if f.code == code]
    assert matches, (
        f"no finding {code!r} in report: {report.to_dict()}"
    )
    return matches[0]


# -- clean runs produced by the coordinator ---------------------------


def test_audit_clean_on_succeeded_run(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        result = _execute(store, SUCCEED_PROGRAM)
        assert result["status"] == "succeeded"
        _assert_clean(store)


def test_audit_clean_on_failed_run(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        result = _execute(store, RAISE_PROGRAM, handlers=_boom_handlers())
        assert result["status"] == "failed"
        assert _events_of_type(store, RUN_ID, EventType.FAILED)
        _assert_clean(store)


def test_audit_clean_on_blocked_run(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        result = _execute(store, BLOCKED_PROGRAM)
        assert result["status"] == "blocked"
        _assert_clean(store)


def test_audit_clean_on_missing_key_failure_run(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        result = _execute(store, MISSING_KEY_PROGRAM)
        assert result["status"] == "failed"
        failed = _events_of_type(store, RUN_ID, EventType.FAILED)
        assert failed and "missing result keys" in failed[0].payload["error"]
        _assert_clean(store)


def test_audit_unknown_run_raises_keyerror(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        with pytest.raises(KeyError):
            audit_run(store, "no-such-run")


# -- injected violations ----------------------------------------------


def test_audit_detects_validation_passed_after_failed(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, RAISE_PROGRAM, handlers=_boom_handlers())
        failed = _events_of_type(store, RUN_ID, EventType.FAILED)[0]
        injected = store.append(
            RUN_ID,
            EventType.VALIDATION_PASSED,
            instruction_id=failed.instruction_id,
            invocation_id=failed.invocation_id,
            task_id=failed.task_id,
            payload={},
        )
        report = audit_run(store, RUN_ID)
        assert not report.ok
        finding = _finding(report, "validation_passed_after_failed")
        assert injected.seq in finding.seqs
        assert failed.seq in finding.seqs


def test_audit_detects_validation_passed_before_failed(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, BLOCKED_PROGRAM)
        ready = _events_of_type(store, RUN_ID, EventType.INVOCATION_READY)[0]
        injected_pass = store.append(
            RUN_ID,
            EventType.VALIDATION_PASSED,
            instruction_id=ready.instruction_id,
            invocation_id=ready.invocation_id,
            task_id=ready.task_id,
            payload={},
        )
        injected = store.append(
            RUN_ID,
            EventType.FAILED,
            instruction_id=ready.instruction_id,
            invocation_id=ready.invocation_id,
            task_id=ready.task_id,
            payload={"error": "late failure"},
        )
        report = audit_run(store, RUN_ID)
        assert not report.ok
        pair = next(
            finding for finding in report.findings
            if finding.code == "validation_passed_before_failed"
            and injected_pass.seq in finding.seqs
            and injected.seq in finding.seqs
        )
        assert pair.seqs


def test_audit_detects_succeeded_after_failed(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, RAISE_PROGRAM, handlers=_boom_handlers())
        failed = _events_of_type(store, RUN_ID, EventType.FAILED)[0]
        injected = store.append(
            RUN_ID,
            EventType.SUCCEEDED,
            instruction_id=failed.instruction_id,
            invocation_id=failed.invocation_id,
            task_id=failed.task_id,
            payload={},
        )
        report = audit_run(store, RUN_ID)
        assert not report.ok
        finding = _finding(report, "succeeded_after_failed")
        assert failed.seq in finding.seqs
        assert injected.seq in finding.seqs


def test_audit_detects_second_run_finished(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, SUCCEED_PROGRAM)
        first = _events_of_type(store, RUN_ID, EventType.RUN_FINISHED)[0]
        injected = store.append(RUN_ID, EventType.RUN_FINISHED,
                                payload={"status": "succeeded"})
        report = audit_run(store, RUN_ID)
        assert not report.ok
        finding = _finding(report, "multiple_run_finished")
        assert first.seq in finding.seqs
        assert injected.seq in finding.seqs


def test_audit_detects_run_finished_claiming_success_after_failure(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, RAISE_PROGRAM, handlers=_boom_handlers())
        failed = _events_of_type(store, RUN_ID, EventType.FAILED)[0]
        injected = store.append(RUN_ID, EventType.RUN_FINISHED,
                                payload={"status": "succeeded"})
        report = audit_run(store, RUN_ID)
        assert not report.ok
        finding = _finding(report, "run_finished_status_mismatch")
        assert failed.seq in finding.seqs
        assert injected.seq in finding.seqs


def test_audit_detects_stray_invocation_event_with_empty_ids(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, SUCCEED_PROGRAM)
        injected = store.append(
            RUN_ID, EventType.RESULT_RECEIVED,
            instruction_id="", invocation_id="inv-stray", task_id="",
            payload={},
        )
        report = audit_run(store, RUN_ID)
        assert not report.ok
        finding = _finding(report, "invocation_event_missing_ids")
        assert finding.seqs == (injected.seq,)
        assert "task_id" in finding.message
        assert "instruction_id" in finding.message


def _stray_task_payload(kind, task_id, **extra):
    payload = {"kind": kind, "id": task_id}
    payload.update(extra)
    return payload


def test_audit_detects_pending_task_on_terminal_run(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, SUCCEED_PROGRAM)
        injected = store.append(
            RUN_ID, EventType.TASK_UPDATED, task_id="task-3",
            payload=_stray_task_payload(
                "task_created", "task-3", text="stray task",
                priority=0, parent=None, dependencies=[], creator="audit",
            ),
        )
        report = audit_run(store, RUN_ID)
        assert not report.ok
        finding = _finding(report, "unsettled_task_on_terminal_run")
        assert injected.seq in finding.seqs
        assert "pending" in finding.message


def test_audit_detects_in_progress_task_on_terminal_run(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, SUCCEED_PROGRAM)
        store.append(
            RUN_ID, EventType.TASK_UPDATED, task_id="task-3",
            payload=_stray_task_payload(
                "task_created", "task-3", text="stray task",
                priority=0, parent=None, dependencies=[], creator="audit",
            ),
        )
        started = store.append(
            RUN_ID, EventType.TASK_UPDATED, task_id="task-3",
            payload=_stray_task_payload("task_started", "task-3"),
        )
        report = audit_run(store, RUN_ID)
        assert not report.ok
        finding = _finding(report, "unsettled_task_on_terminal_run")
        assert started.seq in finding.seqs
        assert "in_progress" in finding.message


def test_audit_detects_completed_task_without_evidence(tmp_path):
    """The append API rejects evidence-less completions by design, so the
    corruption is simulated by tampering with the committed payload —
    exactly the kind of store damage an audit must catch."""
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, SUCCEED_PROGRAM)
        completed = next(
            ev for ev in store.events(RUN_ID)
            if ev.event_type is EventType.TASK_UPDATED
            and isinstance(ev.payload, dict)
            and ev.payload.get("kind") == "task_completed"
            and ev.payload.get("id") == "task-1"
        )
        tampered = dict(completed.payload)
        tampered["evidence"] = ""
        store._conn.execute(
            "UPDATE events SET payload = ? WHERE run_id = ? AND seq = ?",
            (canonical_json(tampered), RUN_ID, completed.seq),
        )
        report = audit_run(store, RUN_ID)
        assert not report.ok
        finding = _finding(report, "completed_task_missing_evidence")
        assert completed.seq in finding.seqs
        assert "task-1" in finding.message


def test_audit_detects_nondeterministic_projection(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, SUCCEED_PROGRAM)
        original = store.project_state
        calls = []

        def flaky(run_id):
            state = original(run_id)
            calls.append(1)
            if len(calls) == 2:
                state = dict(state)
                state["state_version"] = state["state_version"] + 1
            return state

        store.project_state = flaky
        report = audit_run(store, RUN_ID)
        assert not report.ok
        _finding(report, "state_projection_nondeterministic")


# -- CLI surface -------------------------------------------------------


def test_cli_audit_clean_run_exits_zero(tmp_path, capsys):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, SUCCEED_PROGRAM)
    rc = main(["audit", "--db", str(tmp_path / "events.db"),
               "--run-id", RUN_ID])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK" in captured.out


def test_cli_audit_violated_run_exits_one_with_seq_refs(tmp_path, capsys):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, RAISE_PROGRAM, handlers=_boom_handlers())
        failed = _events_of_type(store, RUN_ID, EventType.FAILED)[0]
        injected = store.append(
            RUN_ID, EventType.VALIDATION_PASSED,
            instruction_id=failed.instruction_id,
            invocation_id=failed.invocation_id,
            task_id=failed.task_id,
            payload={},
        )
    rc = main(["audit", "--db", str(tmp_path / "events.db"),
               "--run-id", RUN_ID])
    captured = capsys.readouterr()
    assert rc == 1
    assert "validation_passed_after_failed" in captured.out
    assert str(injected.seq) in captured.out
    assert str(failed.seq) in captured.out


def test_cli_audit_unknown_run_exits_one(tmp_path, capsys):
    with EventStore(str(tmp_path / "events.db")) as store:
        _execute(store, SUCCEED_PROGRAM)
    rc = main(["audit", "--db", str(tmp_path / "events.db"),
               "--run-id", "no-such-run"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "unknown run" in captured.err


# -- legacy runs without a registry digest (issue #15) ------------------


def test_audit_clean_on_legacy_run_without_registry_digest(tmp_path):
    """Pre-digest event stores (no registry_digest in RUN_STARTED) audit clean."""
    with EventStore(str(tmp_path / "events.db")) as store:
        store.create_run(RUN_ID, "legacy@1.0", metadata={"program": "legacy"})
        store.append(
            RUN_ID,
            EventType.RUN_STARTED,
            payload={"program": "legacy", "version": "1.0"},
        )
        store.append(RUN_ID, EventType.RUN_FINISHED, payload={"status": "succeeded"})

        report = audit_run(store, RUN_ID)
        assert report.ok, f"unexpected findings: {report.to_dict()}"
        assert report.findings == ()
        assert not [
            finding for finding in report.findings
            if "registry_digest" in finding.code or "registry_digest" in finding.message
        ]
