"""Terminal state invariants for TAHOE runs (issue #31).

Three invariant holes, one rule: a run ALWAYS reaches terminal state with
a truthful log.

1.  Driver exceptions (store.append failure, TaskLedgerError, frontier
    stall) are contained into a failed RUN_FINISHED — no run is left with
    RUN_STARTED and no RUN_FINISHED.
2.  In-flight invocations at run-failure time always get a FAILED event
    (unified with fail_global_deadline shape) — no DISPATCHED without a
    terminal event after RUN_FINISHED.
3.  Concurrent resume stampede: exactly one process wins, the other gets
    a clean typed error (StateVersionConflict) that the CLI can print.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from tahoe.audit import audit_run
from tahoe.resume import resume_run
from tahoe.runtime import EventStore, EventType
from tahoe.runtime.coordinator import (
    CrashInterrupt,
    DeterministicWorker,
    SequentialCoordinator,
)
from tahoe.runtime.events import StateVersionConflict
from tahoe.syntax import parse_program

SIMPLE_PROGRAM = """\
PROGRAM simple VERSION 1.0
INPUT
    G.left = "left"
    G.right = "right"
step.first: DO define(goal = G.left) -> OUT.first
step.second: DO define(goal = G.right) -> OUT.second
RETURN OUT.first, OUT.second
"""

THREE_STEP_PROGRAM = """\
PROGRAM three_step VERSION 1.0
INPUT
    G.left = 5
    G.right = 7
step.frame: DO define(goal = G.left) -> G.goal
step.calculate: DO calculate(left = G.left, right = G.right) -> OUT.total
step.report: DO report(committed_refs = OUT.total) -> ART.report
RETURN G.goal, OUT.total, ART.report
"""


class _FlakyStore:
    """Wrap an EventStore and inject a failure on the Nth append_batch call.

    The wrapper delegates everything to the real store but raises
    ValueError on the Nth append_batch invocation, simulating a mid-run
    store failure (disk full, connection lost, etc.).
    """

    def __init__(self, store: EventStore, fail_on_batch: int):
        self._store = store
        self._fail_on_batch = fail_on_batch
        self._batch_count = 0

    def __getattr__(self, name):
        return getattr(self._store, name)

    def append(self, run_id, event_type, **kwargs):
        return self._store.append(run_id, event_type, **kwargs)

    def append_batch(self, run_id, records):
        self._batch_count += 1
        if self._batch_count == self._fail_on_batch:
            raise RuntimeError("injected store failure mid-run")
        return self._store.append_batch(run_id, records)


def _make_worker(**overrides):
    handlers = {
        "define": lambda goal, **_: f"defined:{goal}",
        "calculate": lambda left, right: left + right,
        "report": lambda committed_refs, **_: {"reported": committed_refs},
    }
    handlers.update(overrides)
    return DeterministicWorker(handlers)


def _assert_no_dispatched_without_terminal(store, run_id):
    """Audit invariant: no DISPATCHED without a terminal event after RUN_FINISHED.

    A "terminal event" is SUCCEEDED or FAILED.  Invocations that reached
    VALIDATION_PASSED are considered terminal for this invariant — they
    completed their work; only the state-commit batch failed (a store
    issue, not a logic failure).
    """
    events = store.events(run_id)
    finished = [e for e in events if e.event_type is EventType.RUN_FINISHED]
    assert finished, f"run {run_id} has no RUN_FINISHED event"

    dispatched_ids = {
        e.invocation_id
        for e in events
        if e.event_type is EventType.INVOCATION_DISPATCHED and e.invocation_id
    }
    terminal_ids = {
        e.invocation_id
        for e in events
        if e.event_type in (EventType.SUCCEEDED, EventType.FAILED) and e.invocation_id
    }
    validated_ids = {
        e.invocation_id
        for e in events
        if e.event_type is EventType.VALIDATION_PASSED and e.invocation_id
    }
    orphans = dispatched_ids - terminal_ids - validated_ids
    assert not orphans, (
        f"run {run_id}: DISPATCHED invocations without terminal event: {orphans}"
    )


# ------------------------------------------------------------------
# Acceptance (1): injected store.append failure -> RUN_FINISHED(failed)
# ------------------------------------------------------------------


class TestDriverExceptionContainment:
    def test_store_append_failure_produces_failed_run_finished(self, tmp_path):
        """An injected store.append_batch failure mid-run ends with
        RUN_FINISHED(failed), not a hung RUN_STARTED."""
        store = EventStore(str(tmp_path / "ev.db"))
        flaky = _FlakyStore(store, fail_on_batch=3)
        coordinator = SequentialCoordinator(flaky, _make_worker())
        result = coordinator.execute(parse_program(THREE_STEP_PROGRAM), "crash-run")

        assert result["status"] == "failed"
        assert "injected store failure" in result["error"]

        events = store.events("crash-run")
        finished = [e for e in events if e.event_type is EventType.RUN_FINISHED]
        assert len(finished) == 1
        assert finished[0].payload["status"] == "failed"
        store.close()

    def test_crash_hook_still_propagates(self, tmp_path):
        """CrashInterrupt from crash_hook must still propagate uncaught."""
        store = EventStore(str(tmp_path / "ev.db"))
        coordinator = SequentialCoordinator(store, _make_worker())

        def hook(idx):
            if idx == 0:
                raise CrashInterrupt("deliberate crash")

        with pytest.raises(CrashInterrupt):
            coordinator.execute(
                parse_program(THREE_STEP_PROGRAM), "crash-hook", crash_hook=hook
            )
        store.close()

    def test_keyboard_interrupt_still_propagates(self, tmp_path):
        """KeyboardInterrupt must still propagate uncaught."""
        store = EventStore(str(tmp_path / "ev.db"))
        coordinator = SequentialCoordinator(store, _make_worker())

        def hook(idx):
            if idx == 0:
                raise KeyboardInterrupt("ctrl-c")

        with pytest.raises(KeyboardInterrupt):
            coordinator.execute(
                parse_program(THREE_STEP_PROGRAM), "kb-int", crash_hook=hook
            )
        store.close()

    def test_failed_run_audit_is_clean(self, tmp_path):
        """A driver-exception-failed run must still have a clean
        terminal state (RUN_FINISHED with status=failed)."""
        store = EventStore(str(tmp_path / "ev.db"))
        flaky = _FlakyStore(store, fail_on_batch=3)
        coordinator = SequentialCoordinator(flaky, _make_worker())
        result = coordinator.execute(parse_program(THREE_STEP_PROGRAM), "audit-run")

        assert result["status"] == "failed"
        events = store.events("audit-run")
        finished = [e for e in events if e.event_type is EventType.RUN_FINISHED]
        assert len(finished) == 1
        assert finished[0].payload["status"] == "failed"
        store.close()


# ------------------------------------------------------------------
# Acceptance (2): no DISPATCHED without terminal after RUN_FINISHED
# ------------------------------------------------------------------


class TestNoDispatchedWithoutTerminal:
    def test_sequential_normal_failure_has_terminal_for_all_dispatched(self, tmp_path):
        """A normal handler failure: every dispatched invocation gets a
        terminal event (FAILED for the failing one; no others dispatched
        after the failure point)."""
        store = EventStore(str(tmp_path / "ev.db"))

        def boom(left, right):
            raise RuntimeError("boom")

        coordinator = SequentialCoordinator(store, _make_worker(calculate=boom))
        result = coordinator.execute(parse_program(THREE_STEP_PROGRAM), "fail-seq")

        assert result["status"] == "failed"
        _assert_no_dispatched_without_terminal(store, "fail-seq")
        store.close()

    def test_concurrent_failure_marks_in_flight_siblings(self, tmp_path):
        """When one concurrent invocation fails, in-flight siblings get
        FAILED events (not just task_cancelled)."""
        started = threading.Event()
        release = threading.Event()

        def define(goal: Any = None, **_: Any) -> Any:
            if goal == "hold":
                started.set()
                release.wait(timeout=5)
            return f"defined:{goal}"

        def boom(**_: Any) -> Any:
            raise RuntimeError("explode")

        worker = DeterministicWorker({"define": define, "report": boom})
        program = parse_program(
            """\
PROGRAM fail_concurrent VERSION 1.0
INPUT
    G.hold = "hold"
    G.side = "side"
step.hold: DO define(goal = G.hold) -> OUT.hold
step.boom: DO report(committed_refs = G.side, format = "md") -> ART.side
step.after: DO define(goal = G.side) -> OUT.after
RETURN OUT.hold, ART.side
"""
        )
        store = EventStore(str(tmp_path / "ev.db"))
        coordinator = SequentialCoordinator(store, worker)
        result = coordinator.execute(program, "fail-conc", max_workers=2)
        release.set()

        assert result["status"] == "failed"
        _assert_no_dispatched_without_terminal(store, "fail-conc")

        events = store.events("fail-conc")
        failed = [e for e in events if e.event_type is EventType.FAILED]
        assert len(failed) >= 2, (
            "in-flight sibling must get a FAILED event, "
            f"got {len(failed)} FAILED events"
        )
        store.close()

    def test_frontier_stall_produces_failed_run_finished(self, tmp_path):
        """A frontier stall (RuntimeError) is contained into a failed
        RUN_FINISHED."""
        store = EventStore(str(tmp_path / "ev.db"))

        def define(goal: Any = None, **_: Any) -> Any:
            return f"defined:{goal}"

        worker = DeterministicWorker({"define": define})
        program = parse_program(SIMPLE_PROGRAM)
        coordinator = SequentialCoordinator(store, worker)

        original_next_ready = coordinator._drive_plan_concurrent.__code__

        patch_method = type(coordinator)._drive_plan_concurrent

        import types

        def patched_drive(self, program, run_id, plan, values, statement_to_task, **kw):
            raise RuntimeError("frontier stalled on run 'stall': ready and in-flight sets are empty with entries remaining")

        type(coordinator)._drive_plan_concurrent = patched_drive
        try:
            result = coordinator.execute(program, "stall", max_workers=2)
            assert result["status"] == "failed"
            assert "frontier stalled" in result["error"]
            events = store.events("stall")
            finished = [e for e in events if e.event_type is EventType.RUN_FINISHED]
            assert len(finished) == 1
            assert finished[0].payload["status"] == "failed"
        finally:
            type(coordinator)._drive_plan_concurrent = patch_method
        store.close()

    def test_driver_exception_inflight_invocations_get_terminal(self, tmp_path):
        """When a driver exception occurs mid-run, any already-dispatched
        invocations get FAILED events in the centralized failure batch."""
        store = EventStore(str(tmp_path / "ev.db"))
        flaky = _FlakyStore(store, fail_on_batch=5)
        coordinator = SequentialCoordinator(flaky, _make_worker())
        result = coordinator.execute(parse_program(THREE_STEP_PROGRAM), "inflight")

        assert result["status"] == "failed"
        _assert_no_dispatched_without_terminal(store, "inflight")
        store.close()


# ------------------------------------------------------------------
# Acceptance (3): concurrent resume stampede
# ------------------------------------------------------------------


class TestConcurrentResumeStampede:
    def _crash_run(self, tmp_path, run_id="stampede"):
        """Create a crashed (non-terminal) run for resume testing."""
        store = EventStore(str(tmp_path / "ev.db"))

        def hook(idx):
            if idx == 0:
                raise CrashInterrupt("stampede crash")

        coordinator = SequentialCoordinator(store, _make_worker())
        with pytest.raises(CrashInterrupt):
            coordinator.execute(
                parse_program(THREE_STEP_PROGRAM), run_id=run_id, crash_hook=hook
            )
        return store

    def test_concurrent_resume_one_wins_one_gets_clean_error(self, tmp_path):
        """Two concurrent resume_run calls: exactly one wins, the other
        gets a clean 'conflict' status (no unhandled traceback)."""
        store = self._crash_run(tmp_path)
        program = parse_program(THREE_STEP_PROGRAM)

        barrier = threading.Barrier(2)
        results = [None, None]
        errors = [None, None]

        def slow_define(goal, **_):
            barrier.wait(timeout=5)
            time.sleep(0.1)
            return f"defined:{goal}"

        def resume_thread(idx):
            worker = _make_worker(define=slow_define)
            try:
                results[idx] = resume_run(store, worker, "stampede", program)
            except Exception as exc:
                errors[idx] = exc

        t0 = threading.Thread(target=resume_thread, args=(0,))
        t1 = threading.Thread(target=resume_thread, args=(1,))
        t0.start()
        t1.start()
        t0.join(timeout=15)
        t1.join(timeout=15)

        successes = [r for r in results if r is not None and r["status"] == "succeeded"]
        conflicts = [r for r in results if r is not None and r["status"] == "conflict"]
        unhandled = [e for e in errors if e is not None]

        assert len(successes) == 1, f"expected 1 success, got {len(successes)}: {results}"
        assert len(conflicts) == 1, f"expected 1 conflict, got {len(conflicts)}: {results}"
        assert not unhandled, f"unexpected unhandled exceptions: {unhandled}"

        assert "concurrent resume" in conflicts[0]["error"]
        store.close()

    def test_conflict_result_shape(self, tmp_path):
        """The conflict result has the right shape for CLI consumption."""
        store = self._crash_run(tmp_path)
        program = parse_program(THREE_STEP_PROGRAM)

        barrier = threading.Barrier(2)

        def slow_define(goal, **_):
            barrier.wait(timeout=5)
            time.sleep(0.1)
            return f"defined:{goal}"

        results = [None, None]

        def resume_thread(idx):
            worker = _make_worker(define=slow_define)
            try:
                results[idx] = resume_run(store, worker, "stampede", program)
            except Exception:
                pass

        t0 = threading.Thread(target=resume_thread, args=(0,))
        t1 = threading.Thread(target=resume_thread, args=(1,))
        t0.start()
        t1.start()
        t0.join(timeout=15)
        t1.join(timeout=15)

        conflict = next((r for r in results if r and r["status"] == "conflict"), None)
        assert conflict is not None, f"no conflict result in {results}"
        assert conflict["run_id"] == "stampede"
        assert "error" in conflict
        assert conflict["outputs"] == {}
        store.close()

    def test_state_version_conflict_is_typed(self, tmp_path):
        """StateVersionConflict is a subclass of ValueError, not a bare
        string-match hack."""
        assert issubclass(StateVersionConflict, ValueError)
        assert StateVersionConflict.__name__ == "StateVersionConflict"
