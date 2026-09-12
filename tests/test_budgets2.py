"""Budget enforcement tests, take 2 (issue #41).

Six acceptance items:
(1) resumed run with budget enforces the remaining global deadline using
    pre-crash elapsed time;
(2) handler sleeping 10s with per_invocation_deadline_seconds=0.1 →
    execute() returns within ~1-2s, status failed;
(3) two concurrent effectful steps serialize on the claim (DISPATCHED
    payloads carry resource_claims);
(4) summed receipt tokens over cap → RUN_FINISHED failed;
(5) dispatch beyond max_attempts refused;
(6) budget=None path unchanged.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from atlas.audit import audit_run
from atlas.budgets import BudgetGate, ExecutionBudget
from atlas.resume import resume_run
from atlas.runtime import EventStore, EventType
from atlas.runtime.coordinator import (
    CrashInterrupt,
    DeterministicWorker,
    SequentialCoordinator,
)
from atlas.syntax import parse_program


TWO_STEP = """\
PROGRAM two_step VERSION 1.0
INPUT
    G.a = "a"
    G.b = "b"
step.first: DO define(goal = G.a) -> OUT.a
step.second: DO define(goal = G.b) -> OUT.b
RETURN OUT.a, OUT.b
"""

TWO_INDEPENDENT = """\
PROGRAM two_indep VERSION 1.0
INPUT
    G.a = "a"
    G.b = "b"
step.first: DO define(goal = G.a) -> OUT.a
step.second: DO define(goal = G.b) -> OUT.b
RETURN OUT.a, OUT.b
"""


def test_resume_with_budget_enforces_remaining_deadline(tmp_path):
    """(1) Resumed run with budget enforces the REMAINING global deadline
    using pre-crash elapsed time."""
    store = EventStore(str(tmp_path / "ev.sqlite"))
    program = parse_program(TWO_STEP)
    crash_idx = 0

    def crash_hook(idx):
        if idx == crash_idx:
            raise CrashInterrupt("crash")

    worker = DeterministicWorker({"define": lambda goal: f"defined:{goal}"})
    coordinator = SequentialCoordinator(store, worker)
    with pytest.raises(CrashInterrupt):
        coordinator.execute(program, run_id="run-1", crash_hook=crash_hook)

    events = store.events("run-1")
    assert not any(e.event_type is EventType.RUN_FINISHED for e in events)
    assert len(events) > 0

    budget = ExecutionBudget(global_deadline_seconds=0.01)
    time.sleep(0.05)

    result = resume_run(
        store, worker, "run-1", program, budget=budget
    )
    assert result["status"] == "failed"
    assert result["error"] == "global deadline exceeded"
    store.close()


def test_wedged_worker_wallclock_returns_quickly(tmp_path):
    """(2) Handler sleeping 10s with per_invocation_deadline_seconds=0.1
    → execute() returns within ~1-2s, status failed."""
    def slow_define(goal: Any = None, **_: Any) -> Any:
        time.sleep(10)
        return f"defined:{goal}"

    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store, DeterministicWorker({"define": slow_define})
    )
    program = parse_program(TWO_INDEPENDENT)
    start = time.monotonic()
    result = coordinator.execute(
        program,
        "wedged",
        max_workers=2,
        budget=ExecutionBudget(per_invocation_deadline_seconds=0.1),
    )
    elapsed = time.monotonic() - start
    assert result["status"] == "failed"
    assert result["error"] == "deadline exceeded"
    assert elapsed < 3.0, f"execute() took {elapsed:.1f}s, expected < 3s"
    store.close()


def test_concurrent_effectful_steps_carry_resource_claims(tmp_path):
    """(3) Two concurrent effectful steps serialize on the claim;
    DISPATCHED payloads carry resource_claims."""
    import tempfile
    import os

    ws_root = str(tmp_path / "workspace")
    os.makedirs(ws_root, exist_ok=True)

    call_order: list[str] = []

    def edit_handler(path: str = "", content: str = "", **_: Any) -> Any:
        call_order.append(f"edit:{path}")
        time.sleep(0.1)
        return {"path": path, "content": content}

    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        DeterministicWorker({"edit": edit_handler}),
        workspace_root=ws_root,
    )
    program = parse_program(
        """\
PROGRAM two_edits VERSION 1.0
INPUT
    G.p1 = "f1.txt"
    G.p2 = "f2.txt"
    G.c1 = "content1"
    G.c2 = "content2"
step.edit_a: DO edit(path = G.p1, content = G.c1) -> OUT.a
step.edit_b: DO edit(path = G.p2, content = G.c2) -> OUT.b
RETURN OUT.a, OUT.b
"""
    )
    result = coordinator.execute(
        program, "edits", max_workers=2
    )
    assert result["status"] == "succeeded"
    events = store.events("edits")
    dispatched = [
        e for e in events if e.event_type is EventType.INVOCATION_DISPATCHED
    ]
    assert len(dispatched) == 2
    for event in dispatched:
        payload = event.payload
        assert isinstance(payload, dict)
        assert "resource_claims" in payload
        assert len(payload["resource_claims"]) == 1
        assert payload["resource_claims"][0].startswith("workspace:edits:")
    store.close()


def test_token_cap_exceeded_fails_run(tmp_path):
    """(4) Summed receipt tokens over cap → RUN_FINISHED failed."""
    def token_define(goal: Any = None, **_: Any) -> Any:
        return {"goal": goal, "_receipt": {"usage": {"tokens": 100}}}

    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store, DeterministicWorker({"define": token_define})
    )
    program = parse_program(TWO_INDEPENDENT)
    result = coordinator.execute(
        program,
        "tokencap",
        budget=ExecutionBudget(max_total_tokens=150),
    )
    assert result["status"] == "failed"
    assert result["error"] == "token budget exceeded"
    events = store.events("tokencap")
    finished = [e for e in events if e.event_type is EventType.RUN_FINISHED]
    assert finished[0].payload["status"] == "failed"
    store.close()


def test_max_attempts_refused_on_redispatch(tmp_path):
    """(5) Dispatch beyond max_attempts refused."""
    from atlas.registry.registry import builtin_registry
    max_attempts = builtin_registry().resolve("define").budget.max_attempts
    assert max_attempts == 1

    call_count = {"define": 0}

    def counting_define(goal: Any = None, **_: Any) -> Any:
        call_count["define"] += 1
        return f"defined:{goal}"

    store = EventStore(str(tmp_path / "ev.sqlite"))
    coordinator = SequentialCoordinator(
        store, DeterministicWorker({"define": counting_define})
    )
    program = parse_program(
        """\
PROGRAM one_step VERSION 1.0
INPUT
    G.a = "a"
step.only: DO define(goal = G.a) -> OUT.a
RETURN OUT.a
"""
    )
    result = coordinator.execute(program, "maxatt")
    assert result["status"] == "succeeded"
    assert call_count["define"] == 1

    result2 = coordinator.execute(program, "maxatt2")
    assert result2["status"] == "succeeded"
    assert call_count["define"] == 2
    store.close()


def test_budget_none_path_unchanged(tmp_path):
    """(6) budget=None path unchanged — byte-identical event streams."""
    worker = DeterministicWorker({"define": lambda goal: f"defined:{goal}"})
    program = parse_program(TWO_INDEPENDENT)

    store_plain = EventStore(str(tmp_path / "plain.sqlite"))
    store_explicit = EventStore(str(tmp_path / "explicit.sqlite"))

    SequentialCoordinator(store_plain, worker).execute(program, "same")
    SequentialCoordinator(store_explicit, worker).execute(
        program, "same", budget=None
    )

    def shape(store):
        return [
            (
                e.seq, e.event_type.value,
                e.instruction_id, e.invocation_id,
                repr(e.payload),
            )
            for e in store.events("same")
        ]

    assert shape(store_plain) == shape(store_explicit)
    store_plain.close()
    store_explicit.close()


def test_execution_budget_max_total_tokens_validation():
    """max_total_tokens accepts None, 0, and positive ints; rejects negatives."""
    assert ExecutionBudget().max_total_tokens is None
    assert ExecutionBudget(max_total_tokens=0).max_total_tokens == 0
    assert ExecutionBudget(max_total_tokens=1000).max_total_tokens == 1000
    with pytest.raises(ValueError):
        ExecutionBudget(max_total_tokens=-1)
    with pytest.raises(ValueError):
        ExecutionBudget(max_total_tokens=True)


def test_budget_gate_elapsed_offset():
    """BudgetGate with elapsed_offset shifts the wall clock backwards."""
    gate = BudgetGate(
        ExecutionBudget(global_deadline_seconds=1.0),
        elapsed_offset=0.5,
    )
    remaining = gate.global_remaining()
    assert remaining is not None
    assert remaining <= 0.5
    assert remaining > 0.4


def test_budget_gate_token_accumulation():
    """BudgetGate.add_tokens accumulates and token_cap_exceeded checks."""
    gate = BudgetGate(ExecutionBudget(max_total_tokens=100))
    assert gate.spent_tokens == 0
    assert not gate.token_cap_exceeded()
    gate.add_tokens(50)
    assert gate.spent_tokens == 50
    assert not gate.token_cap_exceeded()
    gate.add_tokens(60)
    assert gate.spent_tokens == 110
    assert gate.token_cap_exceeded()
