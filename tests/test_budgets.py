"""Execution-tree budget tests (issue #22).

Specifies ``SequentialCoordinator.execute(..., budget=ExecutionBudget(...))``:
a root-owned scheduler budget shared across the whole execution tree —
one semaphore capping parent frontier workers AND simultaneous child-run
step executions, a global wall-clock deadline failing the run coherently
with in-flight invocations cancelled, per-invocation deadlines failing
overrunning invocations through the standard atomic path, and a child
depth cap.  ``budget=None`` keeps the historical behavior byte-identical.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from tikhon.audit import audit_run
from tikhon.budgets import BudgetDeadlineExceeded, BudgetGate, ExecutionBudget
from tikhon.runtime import EventStore, EventType
from tikhon.runtime.coordinator import DeterministicWorker, SequentialCoordinator
from tikhon.syntax import parse_program
from tikhon.worker_adapter import ModelWorker, WorkerError


class ConcurrencyTracker:
    """Handler wrapper recording peak concurrent executions."""

    def __init__(self, inner: Any, hold: float = 0.05):
        self._inner = inner
        self._hold = hold
        self._lock = threading.Lock()
        self._active = 0
        self.max_observed = 0

    def __call__(self, **kwargs: Any) -> Any:
        with self._lock:
            self._active += 1
            self.max_observed = max(self.max_observed, self._active)
        try:
            time.sleep(self._hold)
            return self._inner(**kwargs)
        finally:
            with self._lock:
                self._active -= 1


FOUR_INDEPENDENT = """\
PROGRAM fan VERSION 1.0
INPUT
    G.a = "a"
    G.b = "b"
    G.c = "c"
    G.d = "d"
step.a: DO define(goal = G.a) -> OUT.a
step.b: DO define(goal = G.b) -> OUT.b
step.c: DO define(goal = G.c) -> OUT.c
step.d: DO define(goal = G.d) -> OUT.d
RETURN OUT.a, OUT.b, OUT.c, OUT.d
"""

CALL_FAN = """\
PROGRAM callfan VERSION 1.0
INPUT
    G.a = "a"
    G.b = "b"
    G.c = "c"
    G.d = "d"
CALL protocol.leafa(request = G.a) -> E.ca
CALL protocol.leafb(request = G.b) -> E.cb
CALL protocol.leafc(request = G.c) -> E.cc
CALL protocol.leafd(request = G.d) -> E.cd
RETURN E.ca, E.cb, E.cc, E.cd
"""

LEAF_A = """\
PROGRAM leafa VERSION 1.0
INPUT
    G.request = ""
step.work: DO define(request = G.request) -> E.ca
RETURN E.ca
"""

LEAF_B = """\
PROGRAM leafb VERSION 1.0
INPUT
    G.request = ""
step.work: DO define(request = G.request) -> E.cb
RETURN E.cb
"""

LEAF_C = """\
PROGRAM leafc VERSION 1.0
INPUT
    G.request = ""
step.work: DO define(request = G.request) -> E.cc
RETURN E.cc
"""

LEAF_D = """\
PROGRAM leafd VERSION 1.0
INPUT
    G.request = ""
step.work: DO define(request = G.request) -> E.cd
RETURN E.cd
"""

LEAF_PROTOCOL = """\
PROGRAM leaf VERSION 1.0
INPUT
    G.request = ""
step.work: DO define(request = G.request) -> E.context
RETURN E.context
"""

NESTED_PROTOCOL = """\
PROGRAM mid VERSION 1.0
INPUT
    G.request = ""
step.pre: DO define(request = G.request) -> G.pre
CALL protocol.leaf(request = G.pre) -> E.context
RETURN E.context
"""


def _make_protocols(tmp_path, protocols: dict[str, str]):
    protocols_dir = tmp_path / "protocols"
    protocols_dir.mkdir(exist_ok=True)
    for name, text in protocols.items():
        (protocols_dir / f"{name}.think").write_text(text)
    return str(protocols_dir)


def test_budget_defaults_and_validation():
    budget = ExecutionBudget()
    assert budget.max_concurrent_workers == 4
    assert budget.global_deadline_seconds is None
    assert budget.per_invocation_deadline_seconds is None
    assert budget.max_child_depth == 8
    for kwargs in (
        {"max_concurrent_workers": 0},
        {"max_concurrent_workers": True},
        {"global_deadline_seconds": 0},
        {"global_deadline_seconds": -1.0},
        {"per_invocation_deadline_seconds": 0},
        {"max_child_depth": -1},
    ):
        with pytest.raises(ValueError):
            ExecutionBudget(**kwargs)
    gate = BudgetGate(ExecutionBudget(max_concurrent_workers=1))
    with pytest.raises(TypeError):
        BudgetGate("not-a-budget")  # type: ignore[arg-type]


def test_concurrency_cap_observed_via_tracking_handler(tmp_path):
    """budget.max_concurrent_workers caps parent workers tree-wide."""
    tracker = ConcurrencyTracker(lambda **kw: f"defined:{kw.get('goal')}")
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store, DeterministicWorker({"define": tracker})
    )
    result = coordinator.execute(
        parse_program(FOUR_INDEPENDENT),
        "capped",
        max_workers=4,
        budget=ExecutionBudget(max_concurrent_workers=2),
    )
    assert result["status"] == "succeeded"
    assert tracker.max_observed <= 2, (
        f"observed {tracker.max_observed} concurrent handler executions;"
        " budget cap is 2"
    )
    assert tracker.max_observed == 2, "the cap should actually be reached"
    report = audit_run(store, "capped")
    assert report.ok, report.findings


def test_one_semaphore_caps_parent_and_child_executions(tmp_path):
    """Nested fan-out cannot exceed the root concurrency cap."""
    tracker = ConcurrencyTracker(lambda **kw: f"defined:{kw.get('request')}")
    protocols_dir = _make_protocols(
        tmp_path,
        {"leafa": LEAF_A, "leafb": LEAF_B, "leafc": LEAF_C, "leafd": LEAF_D},
    )
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        DeterministicWorker({"define": tracker}),
        protocols_dir=protocols_dir,
    )
    result = coordinator.execute(
        parse_program(CALL_FAN),
        "callfan",
        max_workers=4,
        budget=ExecutionBudget(max_concurrent_workers=2),
    )
    assert result["status"] == "succeeded"
    # four child runs were spawned, but their step executions share the
    # same root semaphore as the parent frontier: never more than 2
    assert tracker.max_observed <= 2
    assert tracker.max_observed == 2
    for target in ("E.ca", "E.cb", "E.cc", "E.cd"):
        assert result["outputs"][target] == f"defined:{target[-1]}"
    report = audit_run(store, "callfan")
    assert report.ok, report.findings
    for invocation in ("inv-1", "inv-2", "inv-3", "inv-4"):
        child_id = f"callfan:{invocation}"
        assert store.run(child_id)["event_count"] > 0
        report = audit_run(store, child_id)
        assert report.ok, (child_id, report.findings)


def test_parent_waiting_for_child_completes_with_one_worker(tmp_path):
    """A one-worker budget cannot deadlock a parent awaiting a child."""
    tracker = ConcurrencyTracker(lambda **kw: f"defined:{kw.get('goal', kw.get('request'))}", hold=0.02)
    protocols_dir = _make_protocols(tmp_path, {"leaf": LEAF_PROTOCOL})
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        DeterministicWorker({"define": tracker}),
        protocols_dir=protocols_dir,
    )
    program = parse_program(
        """\
PROGRAM parent VERSION 1.0
INPUT
    G.a = "a"
step.first: DO define(goal = G.a) -> OUT.first
CALL protocol.leaf(request = OUT.first) -> E.context
step.last: DO define(goal = E.context) -> OUT.last
RETURN OUT.first, E.context, OUT.last
"""
    )
    result = coordinator.execute(
        program,
        "parent",
        max_workers=2,
        budget=ExecutionBudget(max_concurrent_workers=1),
    )
    assert result["status"] == "succeeded"
    assert result["outputs"]["E.context"] == "defined:defined:a"
    report = audit_run(store, "parent")
    assert report.ok, report.findings
    report = audit_run(store, "parent:inv-2")
    assert report.ok, report.findings


def test_per_invocation_deadline_fails_invocation_atomically(tmp_path):
    """An overrunning invocation fails through the standard atomic path."""
    def define(goal: Any = None, **_: Any) -> Any:
        time.sleep(0.4)
        return f"defined:{goal}"

    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store, DeterministicWorker({"define": define})
    )
    result = coordinator.execute(
        parse_program(FOUR_INDEPENDENT),
        "invdeadline",
        max_workers=2,
        budget=ExecutionBudget(per_invocation_deadline_seconds=0.05),
    )
    assert result["status"] == "failed"
    assert result["error"] == "deadline exceeded"
    events = store.events("invdeadline")
    failed = [e for e in events if e.event_type is EventType.FAILED]
    assert len(failed) == 1
    assert failed[0].payload["error"] == "deadline exceeded"
    finished = [e for e in events if e.event_type is EventType.RUN_FINISHED]
    assert finished[0].payload["status"] == "failed"
    counts = store.task_ledger("invdeadline").profile()["counts"]
    assert counts["completed"] == 0
    assert counts["completed"] + counts["cancelled"] == 4
    report = audit_run(store, "invdeadline")
    assert report.ok, report.findings


def test_sequential_per_invocation_deadline_discards_late_result(tmp_path):
    """Sequential drive: the deadline is checked after the handler returns."""
    def define(goal: Any = None, **_: Any) -> Any:
        time.sleep(0.2)
        return f"defined:{goal}"

    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store, DeterministicWorker({"define": define})
    )
    program = parse_program(
        """\
PROGRAM seqd VERSION 1.0
INPUT
    G.a = "a"
step.only: DO define(goal = G.a) -> OUT.a
RETURN OUT.a
"""
    )
    result = coordinator.execute(
        program,
        "seqd",
        budget=ExecutionBudget(per_invocation_deadline_seconds=0.05),
    )
    assert result["status"] == "failed"
    assert result["error"] == "deadline exceeded"
    events = store.events("seqd")
    # the late result committed nothing
    assert not [e for e in events if e.event_type is EventType.SUCCEEDED]
    assert not [e for e in events if e.event_type is EventType.RESULT_RECEIVED]
    report = audit_run(store, "seqd")
    assert report.ok, report.findings


def test_global_deadline_fails_run_and_cancels_in_flight(tmp_path):
    """Global deadline: run fails coherently; in-flight work is cancelled."""
    started = threading.Event()

    def define(goal: Any = None, **_: Any) -> Any:
        if goal == "hold":
            started.set()
            time.sleep(0.5)
            return "defined:hold"
        return f"defined:{goal}"

    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store, DeterministicWorker({"define": define})
    )
    program = parse_program(
        """\
PROGRAM gdeadline VERSION 1.0
INPUT
    G.hold = "hold"
    G.q = "q"
    G.r = "r"
step.hold: DO define(goal = G.hold) -> OUT.hold
step.quick: DO define(goal = G.q) -> OUT.q
step.last: DO define(goal = OUT.q) -> OUT.last
RETURN OUT.hold, OUT.q, OUT.last
"""
    )
    result = coordinator.execute(
        program,
        "gdeadline",
        max_workers=2,
        budget=ExecutionBudget(global_deadline_seconds=0.15),
    )
    assert result["status"] == "failed"
    assert result["error"] == "global deadline exceeded"
    events = store.events("gdeadline")
    cancelled_failures = [
        e
        for e in events
        if e.event_type is EventType.FAILED
        and e.payload["error"] == "cancelled: global deadline exceeded"
    ]
    assert cancelled_failures, "in-flight invocations must be marked cancelled"
    # no adoption or completion from the cancelled in-flight invocation
    hold_succeeded = [
        e
        for e in events
        if e.instruction_id == "step.hold"
        and e.event_type is EventType.SUCCEEDED
    ]
    assert hold_succeeded == []
    counts = store.task_ledger("gdeadline").profile()["counts"]
    assert counts["in_progress"] == 0
    assert counts["completed"] + counts["cancelled"] == 3
    report = audit_run(store, "gdeadline")
    assert report.ok, report.findings


def test_sequential_global_deadline_checked_before_dispatch(tmp_path):
    """Sequential drive: the deadline is checked before each dispatch."""
    def define(goal: Any = None, **_: Any) -> Any:
        time.sleep(0.15)
        return f"defined:{goal}"

    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store, DeterministicWorker({"define": define})
    )
    program = parse_program(
        """\
PROGRAM seqg VERSION 1.0
INPUT
    G.a = "a"
    G.b = "b"
step.first: DO define(goal = G.a) -> OUT.a
step.second: DO define(goal = G.b) -> OUT.b
RETURN OUT.a, OUT.b
"""
    )
    result = coordinator.execute(
        program,
        "seqg",
        budget=ExecutionBudget(global_deadline_seconds=0.05),
    )
    assert result["status"] == "failed"
    assert result["error"] == "global deadline exceeded"
    events = store.events("seqg")
    # the first step committed before the deadline; the second never ran
    assert [
        e for e in events
        if e.instruction_id == "step.first"
        and e.event_type is EventType.SUCCEEDED
    ]
    assert not [
        e for e in events
        if e.instruction_id == "step.second"
        and e.event_type is EventType.INVOCATION_DISPATCHED
    ]
    report = audit_run(store, "seqg")
    assert report.ok, report.findings


def test_child_depth_cap_enforced_in_frontier(tmp_path):
    """A CALL nesting deeper than max_child_depth fails atomically."""
    protocols_dir = _make_protocols(
        tmp_path, {"leaf": LEAF_PROTOCOL, "mid": NESTED_PROTOCOL}
    )
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        DeterministicWorker({"define": lambda **kw: f"defined:{kw}"}),
        protocols_dir=protocols_dir,
    )
    program = parse_program(
        """\
PROGRAM deep VERSION 1.0
INPUT
    G.a = "a"
CALL protocol.mid(request = G.a) -> E.context
RETURN E.context
"""
    )
    result = coordinator.execute(
        program,
        "deep",
        max_workers=2,
        budget=ExecutionBudget(max_child_depth=1),
    )
    assert result["status"] == "failed"
    assert "max_child_depth 1" in result["error"]
    # the grandchild run was never started
    child_id = "deep:inv-1"
    child_events = store.events(child_id)
    assert any(
        e.event_type is EventType.FAILED
        and "max_child_depth" in e.payload["error"]
        for e in child_events
    )
    # the depth cap fires at the child's own CALL dispatch: the
    # grandchild run was never created and never dispatched
    grandchild_ids = [
        event.payload["child_run_id"]
        for event in child_events
        if event.event_type is EventType.INVOCATION_DISPATCHED
        and isinstance(event.payload, dict)
        and "child_run_id" in event.payload
    ]
    assert grandchild_ids == [], (
        "a depth-capped child CALL must not dispatch the grandchild"
    )
    inner_failed = [
        event
        for event in child_events
        if event.event_type is EventType.FAILED
        and event.instruction_id == "protocol.leaf"
    ]
    assert inner_failed, "the child's inner CALL must carry the FAILED event"
    report = audit_run(store, "deep")
    assert report.ok, report.findings
    report = audit_run(store, child_id)
    assert report.ok, report.findings


def test_default_child_depth_admits_eight_levels(tmp_path):
    """budget default max_child_depth=8 matches the static grammar cap."""
    protocols = {"leaf": LEAF_PROTOCOL}
    # chain: level1 -> ... -> level7 -> leaf (8 protocol frames total,
    # exactly the grammar's static depth cap and the budget default)
    for level in range(1, 7):
        protocols[f"level{level}"] = (
            f"PROGRAM level{level} VERSION 1.0\n"
            "INPUT\n    G.request = \"\"\n"
            f"step.pre: DO define(request = G.request) -> G.pre\n"
            f"CALL protocol.level{level + 1}(request = G.pre)"
            f" -> E.context\n"
            f"RETURN E.context\n"
        )
    protocols["level7"] = (
        "PROGRAM level7 VERSION 1.0\n"
        "INPUT\n    G.request = \"\"\n"
        "step.pre: DO define(request = G.request) -> G.pre\n"
        "CALL protocol.leaf(request = G.pre) -> E.context\n"
        "RETURN E.context\n"
    )
    protocols_dir = _make_protocols(tmp_path, protocols)
    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        DeterministicWorker({"define": lambda **kw: "ok"}),
        protocols_dir=protocols_dir,
    )
    program = parse_program(
        """\
PROGRAM chain VERSION 1.0
INPUT
    G.a = "a"
CALL protocol.level1(request = G.a) -> E.context
RETURN E.context
"""
    )
    result = coordinator.execute(
        program, "chain", budget=ExecutionBudget()
    )
    assert result["status"] == "succeeded"
    report = audit_run(store, "chain")
    assert report.ok, report.findings


def test_budget_none_keeps_behavior_identical(tmp_path):
    """budget=None and no argument produce byte-identical event streams."""
    worker = DeterministicWorker({"define": lambda goal, **_: f"defined:{goal}"})
    program = parse_program(FOUR_INDEPENDENT)
    store_plain = EventStore(str(tmp_path / "plain.sqlite"))
    store_explicit = EventStore(str(tmp_path / "explicit.sqlite"))
    plain = SequentialCoordinator(store_plain, worker).execute(program, "same")
    explicit = SequentialCoordinator(
        store_explicit, worker
    ).execute(program, "same", budget=None)

    def shape(store: EventStore) -> list[tuple]:
        return [
            (
                event.seq,
                event.event_type.value,
                event.instruction_id,
                event.invocation_id,
                event.task_id,
                repr(event.payload),
            )
            for event in store.events("same")
        ]

    assert shape(store_plain) == shape(store_explicit)
    assert plain["status"] == explicit["status"] == "succeeded"


def test_model_worker_envelope_carries_budget_deadline():
    """The execution budget's deadline binds into rendered TaskEnvelopes."""
    from tikhon.registry.registry import builtin_registry

    def transport(model: str, prompt: str) -> str:
        return '{"goal": "x"}'

    worker = ModelWorker(
        builtin_registry(),
        transport,
        tier_models={"T0": "m0"},
        default_model="m0",
    )
    result = worker.execute("define", {"goal": "x"})
    assert result == {"goal": "x"}
    assert worker.last_task_envelope.deadline_seconds is not None  # contract

    bounded = ModelWorker(
        builtin_registry(),
        transport,
        tier_models={"T0": "m0"},
        default_model="m0",
        deadline_seconds=5.0,
    )
    bounded.execute("define", {"goal": "x"})
    assert bounded.last_task_envelope.deadline_seconds == 5.0
    # canonical JSON still validates with the bound deadline
    bounded.last_task_envelope.to_json()


def test_budget_deadline_exceeded_exception_message():
    """The typed deadline error records the standard failure reason."""
    exc = BudgetDeadlineExceeded("deadline exceeded")
    assert str(exc) == "deadline exceeded"
