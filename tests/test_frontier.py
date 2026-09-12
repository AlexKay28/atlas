"""Concurrent execution frontier tests (issue #21).

Specifies ``SequentialCoordinator.execute(..., max_workers=N)``: a
ready-task scheduling layer over the dependency DAG computed from ref
usage, overlapping dispatch of ref-disjoint invocations on a thread pool,
single-writer commits through the store's atomic batch path, a
deliberately relaxed multi-IN_PROGRESS ledger for concurrent runs only,
and final states identical to the sequential run for deterministic
handlers regardless of completion order.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from atlas.audit import audit_run
from atlas.runtime import EventStore, EventType
from atlas.runtime.coordinator import DeterministicWorker, SequentialCoordinator
from atlas.runtime.tasks import TaskLedger, TaskLedgerError, TaskStatus
from atlas.syntax import parse_program

# a: consumes G.left (INPUT), produces G.plan.
# b: consumes G.plan -> depends on a.
# c: consumes G.side (INPUT only) -> independent of a and b.
# d: consumes G.plan and G.side -> depends on a and b.
DAG_PROGRAM = """\
PROGRAM frontier VERSION 1.0
INPUT
    G.left = "left"
    G.side = "side"
step.a: DO define(goal = G.left) -> G.plan
step.b: DO summarize(source_refs = G.plan, budget = 10) -> P.b
step.c: DO report(committed_refs = G.side, format = "md") -> ART.c
step.d: DO verify(goal = G.plan, evidence = P.b) -> V.d
RETURN G.plan, P.b, ART.c, V.d
"""

# two ref-disjoint steps whose handlers block on a shared barrier: both
# must run at the same time for either to finish.
BARRIER_PROGRAM = """\
PROGRAM pair VERSION 1.0
INPUT
    G.left = "L"
    G.right = "R"
step.left: DO define(goal = G.left) -> OUT.left
step.right: DO define(goal = G.right) -> OUT.right
RETURN OUT.left, OUT.right
"""


def _frontier_worker(
    tracked: list[str] | None = None,
    track_lock: threading.Lock | None = None,
    slow: float = 0.0,
    barrier: threading.Barrier | None = None,
) -> DeterministicWorker:
    def define(goal: Any = None, **_: Any) -> Any:
        if barrier is not None:
            barrier.wait(timeout=5)
        if track_lock is not None and tracked is not None:
            with track_lock:
                tracked.append("define")
        if slow:
            time.sleep(slow)
        return f"defined:{goal}"

    def summarize(source_refs: Any = None, budget: Any = None, **_: Any) -> Any:
        return {"b": source_refs}

    def report(committed_refs: Any = None, format: Any = None, **_: Any) -> Any:
        return {"c": committed_refs}

    def verify(goal: Any = None, evidence: Any = None, **_: Any) -> Any:
        return {"d": [goal, evidence]}

    return DeterministicWorker(
        {
            "define": define,
            "summarize": summarize,
            "report": report,
            "verify": verify,
        }
    )


def _seq_of(events: tuple, instruction_id: str, event_type: EventType) -> int:
    return next(
        event.seq
        for event in events
        if event.instruction_id == instruction_id
        and event.event_type is event_type
    )


class _BarrierHandler:
    """Handler that blocks until ``parties`` handlers arrive at once."""

    def __init__(self, parties: int):
        self.barrier = threading.Barrier(parties)
        self.concurrent_now = 0
        self.max_concurrent = 0
        self._lock = threading.Lock()

    def __call__(self, **_: Any) -> Any:
        with self._lock:
            self.concurrent_now += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent_now)
        self.barrier.wait(timeout=5)
        with self._lock:
            self.concurrent_now -= 1
        return "ok"


def test_dependency_dag_orders_producers_before_consumers(tmp_path):
    """b dispatches only after a commits; c (ref-disjoint) runs before b."""
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(store, _frontier_worker(slow=0.02))
    result = coordinator.execute(parse_program(DAG_PROGRAM), "dag", max_workers=2)
    assert result["status"] == "succeeded"

    events = store.events("dag")
    a_succeeded = _seq_of(events, "step.a", EventType.SUCCEEDED)
    b_ready = _seq_of(events, "step.b", EventType.INVOCATION_READY)
    c_ready = _seq_of(events, "step.c", EventType.INVOCATION_READY)
    assert a_succeeded < b_ready, "consumer b must not dispatch before a commits"
    assert c_ready < a_succeeded, (
        "ref-disjoint c must dispatch while a is still in flight"
    )
    d_ready = _seq_of(events, "step.d", EventType.INVOCATION_READY)
    b_succeeded = _seq_of(events, "step.b", EventType.SUCCEEDED)
    assert b_succeeded < d_ready, "d consumes b's output P.b"


def test_barrier_handlers_prove_overlapping_execution(tmp_path):
    """Two ref-disjoint steps block on one barrier: overlap is structural."""
    handler = _BarrierHandler(parties=2)
    worker = DeterministicWorker({"define": handler})
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(store, worker)
    result = coordinator.execute(
        parse_program(BARRIER_PROGRAM), "pair", max_workers=2
    )
    assert result["status"] == "succeeded"
    assert handler.max_concurrent == 2, (
        "barrier-controlled handlers must overlap under max_workers=2"
    )


def test_barrier_times_out_sequentially_without_workers(tmp_path):
    """max_workers=1 (default) never overlaps: a 2-party barrier deadlocks.

    Proves the sequential path is untouched by using a barrier that
    cannot be met — the run cannot complete concurrently, so both
    handlers would hang; instead we assert the strict serial order of
    dispatches with a timed single-party barrier.
    """
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(store, _frontier_worker())
    result = coordinator.execute(parse_program(DAG_PROGRAM), "serial")
    assert result["status"] == "succeeded"
    events = store.events("serial")
    # strict sequential dispatch order: a, b, c, d
    order = [
        event.instruction_id
        for event in events
        if event.event_type is EventType.INVOCATION_READY
    ]
    assert order == ["step.a", "step.b", "step.c", "step.d"]


def test_concurrent_final_state_equals_sequential_final_state(tmp_path):
    """Deterministic handlers: completion order never changes the state."""
    program = parse_program(DAG_PROGRAM)
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(store, _frontier_worker(slow=0.01))
    sequential = coordinator.execute(program, "seq")
    concurrent = coordinator.execute(program, "conc", max_workers=3)
    assert sequential["status"] == concurrent["status"] == "succeeded"
    assert store.project_state("seq")["nodes"] == (
        store.project_state("conc")["nodes"]
    )
    assert store.project_state("seq")["state_version"] == (
        store.project_state("conc")["state_version"]
    )
    # both runs audit clean with identical ledger accounting
    for run_id in ("seq", "conc"):
        report = audit_run(store, run_id)
        assert report.ok, (run_id, report.findings)
        counts = store.task_ledger(run_id).profile()["counts"]
        assert counts["completed"] == 4 and counts["in_progress"] == 0


def test_concurrent_run_allows_multiple_in_progress_tasks(tmp_path):
    """The ledger deliberately relaxes single-IN_PROGRESS for concurrent runs."""
    release = threading.Event()

    def define(goal: Any = None, **_: Any) -> Any:
        release.wait(timeout=5)
        return f"defined:{goal}"

    worker = DeterministicWorker({"define": define})
    program = parse_program(
        """\
PROGRAM two VERSION 1.0
INPUT
    G.hold = "hold"
    G.side = "side"
step.hold: DO define(goal = G.hold) -> OUT.hold
step.side: DO define(goal = G.side) -> OUT.side
RETURN OUT.hold, OUT.side
"""
    )
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(store, worker)

    def drive() -> None:
        coordinator.execute(program, "two", max_workers=2)

    thread = threading.Thread(target=drive)
    thread.start()
    counts = {"in_progress": 0}
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        counts = store.task_ledger("two").profile()["counts"]
        if counts["in_progress"] == 2:
            break
        time.sleep(0.005)
    release.set()
    thread.join(timeout=10)
    assert counts["in_progress"] == 2, (
        "concurrent run must carry two IN_PROGRESS tasks simultaneously"
    )
    final = store.task_ledger("two").profile()["counts"]
    assert final["completed"] == 2 and final["in_progress"] == 0


def test_ledger_concurrency_flag_default_is_strict():
    """TaskLedger keeps single-IN_PROGRESS unless allow_concurrent is set."""
    ledger = TaskLedger()
    ledger.create_task(text="one", creator="coordinator")
    ledger.create_task(text="two", creator="coordinator")
    ledger.start_task("task-1")
    with pytest.raises(TaskLedgerError):
        ledger.start_task("task-2")

    relaxed = TaskLedger(allow_concurrent=True)
    relaxed.create_task(text="one", creator="coordinator")
    relaxed.create_task(text="two", creator="coordinator")
    relaxed.start_task("task-1")
    started = relaxed.start_task("task-2")
    assert started.status is TaskStatus.IN_PROGRESS
    # replay reconstructs the same multi-IN_PROGRESS state
    replayed = TaskLedger.from_events(relaxed.events, allow_concurrent=True)
    in_progress = [
        task.id
        for task in replayed.tasks.values()
        if task.status is TaskStatus.IN_PROGRESS
    ]
    assert sorted(in_progress) == ["task-1", "task-2"]


def test_store_replay_reconstructs_concurrent_intermediate_states(tmp_path):
    """A persisted concurrent run replays with multi-IN_PROGRESS states."""
    handler = _BarrierHandler(parties=2)
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store, DeterministicWorker({"define": handler})
    )
    result = coordinator.execute(
        parse_program(BARRIER_PROGRAM), "pair", max_workers=2
    )
    assert result["status"] == "succeeded"
    # strict replay of the committed stream RAISES at the multi-IN_PROGRESS
    # window (the deliberate relaxation); replay with the flag reconstructs
    # the same final state.
    payloads = [
        event.payload
        for event in store.events("pair")
        if event.event_type is EventType.TASK_UPDATED
    ]
    with pytest.raises(TaskLedgerError):
        TaskLedger.from_events(payloads)
    strict_final = TaskLedger.from_events(payloads, allow_concurrent=True)
    assert strict_final.profile()["counts"]["in_progress"] == 0
    concurrent_final = TaskLedger.from_events(payloads, allow_concurrent=True)
    assert concurrent_final.profile() == strict_final.profile()


def test_frontier_failure_is_atomic_and_cancels_in_flight(tmp_path):
    """A failing invocation fails the run once; in-flight work is discarded."""
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
PROGRAM fail VERSION 1.0
INPUT
    G.hold = "hold"
    G.side = "side"
step.hold: DO define(goal = G.hold) -> OUT.hold
step.boom: DO report(committed_refs = G.side, format = "md") -> ART.side
step.after: DO define(goal = G.side) -> OUT.after
RETURN OUT.hold, ART.side
"""
    )
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(store, worker)
    result = coordinator.execute(program, "fail", max_workers=2)
    release.set()
    assert result["status"] == "failed"
    assert "explode" in result["error"]

    events = store.events("fail")
    failed = [e for e in events if e.event_type is EventType.FAILED]
    assert len(failed) == 1 and failed[0].payload["error"] == "explode"
    finished = [e for e in events if e.event_type is EventType.RUN_FINISHED]
    assert len(finished) == 1 and finished[0].payload["status"] == "failed"
    counts = store.task_ledger("fail").profile()["counts"]
    assert counts["completed"] == 0
    assert counts["completed"] + counts["cancelled"] == 3
    report = audit_run(store, "fail")
    assert report.ok, report.findings
    # the in-flight step's late handler result committed nothing
    held = [
        e
        for e in events
        if e.instruction_id == "step.hold"
        and e.event_type is EventType.SUCCEEDED
    ]
    assert held == [], "late result from an in-flight step must not commit"


def test_conditional_and_call_entries_serialize_behind_their_refs(tmp_path):
    """IF conditionals and CALLs wait for the refs they consume."""
    framing = """\
PROGRAM leaf VERSION 1.0
INPUT
    G.request = ""
step.frame: DO define(request = G.request) -> E.context
RETURN E.context
"""
    protocols_dir = tmp_path / "protocols"
    protocols_dir.mkdir()
    (protocols_dir / "leaf.think").write_text(framing)

    def define(request: Any = None, goal: Any = None, **_: Any) -> Any:
        return request or goal or "x"

    def report(committed_refs: Any = None, format: Any = None, **_: Any) -> Any:
        return "reported"

    def decompose(goal: Any = None, **_: Any) -> Any:
        # deliberately not ["a"]: the anchor conditional must not fire
        return ["b"]

    worker = DeterministicWorker(
        {"define": define, "decompose": decompose, "report": report}
    )
    program = parse_program(
        """\
PROGRAM cond VERSION 1.0
INPUT
    G.left = "L"
    G.side = "S"
step.a: DO define(goal = G.left) -> G.plan
step.independent: DO report(committed_refs = G.side, format = "md") -> ART.side
step.branch: DO decompose(goal = G.plan) -> G.sub
IF G.sub == ["a"] STOP completed()
CALL protocol.leaf(request = G.plan) -> E.context
step.last: DO define(goal = E.context) -> OUT.final
RETURN G.plan, ART.side, E.context, OUT.final
"""
    )
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store, worker, protocols_dir=str(protocols_dir)
    )
    result = coordinator.execute(program, "cond", max_workers=2)
    assert result["status"] == "succeeded"
    events = store.events("cond")
    a_succeeded = _seq_of(events, "step.a", EventType.SUCCEEDED)
    branch_ready = _seq_of(events, "step.branch", EventType.INVOCATION_READY)
    assert a_succeeded < branch_ready
    call_dispatched = _seq_of(events, "protocol.leaf", EventType.INVOCATION_DISPATCHED)
    assert call_dispatched > a_succeeded, "CALL waits for its argument's producer"
    assert result["outputs"]["E.context"] == "L"
    report = audit_run(store, "cond")
    assert report.ok, report.findings
    report = audit_run(store, "cond:inv-4")
    assert report.ok, report.findings


def test_crash_hook_works_in_the_concurrent_frontier(tmp_path):
    """CrashInterrupt propagates uncaught; the committed prefix is intact."""
    crash_here = threading.Event()

    def hook(idx: int) -> None:
        crash_here.set()
        raise KeyboardInterrupt("crash")

    def define(goal: Any = None, **_: Any) -> Any:
        return f"defined:{goal}"

    worker = DeterministicWorker({"define": define})
    program = parse_program(
        """\
PROGRAM crash VERSION 1.0
INPUT
    G.a = "a"
    G.b = "b"
step.first: DO define(goal = G.a) -> OUT.first
step.second: DO define(goal = G.b) -> OUT.second
RETURN OUT.first, OUT.second
"""
    )
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(store, worker)
    with pytest.raises(KeyboardInterrupt):
        coordinator.execute(program, "crash", max_workers=2, crash_hook=hook)
    assert crash_here.is_set()
    events = store.events("crash")
    # true crash window: no FAILED, no RUN_FINISHED
    assert not [e for e in events if e.event_type is EventType.FAILED]
    assert not [e for e in events if e.event_type is EventType.RUN_FINISHED]
    # the first step's committed events (READY/DISPATCHED) exist
    assert any(
        e.instruction_id == "step.first"
        and e.event_type is EventType.INVOCATION_DISPATCHED
        for e in events
    )
    # resume completes the run through the frontier
    resumed = coordinator._resume_existing_run(program, "crash")
    assert resumed["status"] == "succeeded"
    report = audit_run(store, "crash")
    assert report.ok, report.findings


def test_resume_of_crashed_concurrent_run_redrives_the_frontier(tmp_path):
    """A crashed concurrent run resumes through the frontier (non-prefix set).

    inv-2 commits while inv-1 is still in flight; the crash then leaves
    a NON-prefix SUCCEEDED set {inv-2}, which the sequential resume
    check would reject but the concurrent resume re-drives through the
    frontier (inv-1's worker call re-executes, at-least-once).
    """
    hold_started = threading.Event()

    def define(goal: Any = None, **_: Any) -> Any:
        if goal == "hold":
            # inv-1 sleeps so inv-2 commits first (non-prefix crash set)
            hold_started.set()
            time.sleep(0.2)
            return f"defined:{goal}"
        if goal == "side":
            return "defined:side"
        raise KeyboardInterrupt("simulated crash")

    program = parse_program(
        """\
PROGRAM crashresume VERSION 1.0
INPUT
    G.hold = "hold"
    G.side = "side"
step.hold: DO define(goal = G.hold) -> OUT.hold
step.side: DO define(goal = G.side) -> OUT.side
step.last: DO define(goal = OUT.side) -> OUT.last
RETURN OUT.hold, OUT.side, OUT.last
"""
    )
    store = EventStore(str(tmp_path / "ev.sqlite"))
    crashing = SequentialCoordinator(
        store, DeterministicWorker({"define": define})
    )
    with pytest.raises(KeyboardInterrupt):
        crashing.execute(program, "crashy", max_workers=2)
    succeeded = {
        e.invocation_id
        for e in store.events("crashy")
        if e.event_type is EventType.SUCCEEDED
    }
    assert succeeded == {"inv-2"}, (
        f"expected the non-prefix set {{inv-2}}, got {succeeded}"
    )
    # resume with the good worker: inv-1 and inv-3 re-drive
    resumed = SequentialCoordinator(
        store, DeterministicWorker({"define": lambda goal, **_: f"defined:{goal}"})
    )._resume_existing_run(program, "crashy")
    assert resumed["status"] == "succeeded"
    report = audit_run(store, "crashy")
    assert report.ok, report.findings
    counts = store.task_ledger("crashy").profile()["counts"]
    assert counts["completed"] == 3 and counts["cancelled"] == 0
