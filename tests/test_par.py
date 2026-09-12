"""Tests specifying the PAR block contract (issue #24).

Covers the grammar (``PAR MAX n`` + 2+ heterogeneous DO/CALL branch lines +
terminating ``BARRIER`` optionally declaring targets), validation (sibling
output reads before the join rejected, duplicate parent output targets
rejected, barrier target declaration pinned to the union of branch
targets, empty/single blocks rejected), the runtime (branches dispatch
concurrently as isolated child-scoped runs ``<run>:par<k>`` under the MAX
ceiling, the barrier waits for every branch, all-success adoption with
CHILD_ADOPTED per branch plus one PAR_JOINED, branch failure cancelling
siblings and failing the run atomically, nested PAR bounded by the budget
child-depth cap), determinism/replay (permutation-independent final
projection, identical replay after reopen, audit clean), and unchanged
behavior for programs without PAR.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import pytest

from tikhon.audit import audit_run
from tikhon.budgets import ExecutionBudget
from tikhon.registry.registry import builtin_registry
from tikhon.runtime import EventStore, EventType
from tikhon.runtime.coordinator import DeterministicWorker, SequentialCoordinator
from tikhon.runtime.tasks import TaskStatus
from tikhon.syntax import (
    ParseError,
    canonical_json,
    parse_program,
    seal_digest,
    validate_program,
)


def make_worker(**extra: Any) -> DeterministicWorker:
    handlers: dict[str, Any] = {
        name: (lambda **kwargs: {"result": kwargs})
        for name in builtin_registry().names()
    }
    handlers.update(
        {
            "define": lambda **kwargs: {"value": kwargs},
            "summarize": lambda source_refs: {"summary": list(source_refs)},
            "search": lambda query, scope: {"sites": [query, scope]},
            "report": lambda committed_refs, format: {"report": committed_refs},
        }
    )
    handlers.update(extra)
    return DeterministicWorker(handlers=handlers)


HETEROGENEOUS_PROGRAM = """\
PROGRAM het VERSION 1.0
INPUT
    G.goal = "inspect code and tests"
    C.scope = "src/"
PAR MAX 2
    step.inspect_code: DO search(query = G.goal, scope = C.scope) -> E.code
    CALL protocol.framing(request = G.goal, scope = C.scope) -> E.context, V.analysis
BARRIER -> E.code, E.context, V.analysis
step.combine: DO summarize(source_refs = [E.code, E.context]) -> D.plan
RETURN D.plan
"""


# ---------------------------------------------------------------------------
# Grammar and validation
# ---------------------------------------------------------------------------


def test_par_block_parses_heterogeneous_branches_and_barrier():
    program = parse_program(HETEROGENEOUS_PROGRAM)
    par = program.statements[0]
    assert type(par).__name__ == "Par"
    assert par.max_count == 2
    assert len(par.branches) == 2
    assert par.branches[0].invocation is not None
    assert par.branches[0].invocation.step_id == "step.inspect_code"
    assert par.branches[1].call is not None
    assert par.branches[1].call.protocol == "protocol.framing"
    assert par.barrier_targets == ("E.code", "E.context", "V.analysis")


def test_par_seals_deterministically_and_canonically():
    program = parse_program(HETEROGENEOUS_PROGRAM)
    canonical = json.loads(canonical_json(program))
    par = canonical["statements"][0]
    assert par["kind"] == "par"
    assert par["max"] == 2
    assert par["branches"][0]["kind"] == "invocation"
    assert par["branches"][1]["kind"] == "call"
    assert par["barrier"] == ["E.code", "E.context", "V.analysis"]
    # Comments and blank lines never change the seal.
    assert seal_digest(program) == seal_digest(
        parse_program("# a comment\n\n" + HETEROGENEOUS_PROGRAM)
    )


def test_par_requires_at_least_two_branches():
    with pytest.raises(ParseError, match="at least two branch lines"):
        parse_program(
            """\
PROGRAM one VERSION 1.0
PAR MAX 1
    step.a: DO define(x = 1) -> E.a
BARRIER
RETURN E.a
"""
        )


def test_par_requires_terminating_barrier():
    with pytest.raises(ParseError, match="BARRIER"):
        parse_program(
            """\
PROGRAM nobarrier VERSION 1.0
PAR MAX 2
    step.a: DO define(x = 1) -> E.a
    step.b: DO define(x = 2) -> E.b
step.c: DO define(x = 3) -> E.c
RETURN E.c
"""
        )


def test_stray_barrier_rejected():
    with pytest.raises(ParseError, match="only valid as the terminator"):
        parse_program(
            """\
PROGRAM stray VERSION 1.0
BARRIER
RETURN E.a
"""
        )


def test_par_max_must_be_positive():
    with pytest.raises(ParseError, match="PAR MAX must be a positive integer"):
        parse_program(
            """\
PROGRAM zero VERSION 1.0
PAR MAX 0
    step.a: DO define(x = 1) -> E.a
    step.b: DO define(x = 2) -> E.b
BARRIER
RETURN E.a
"""
        )


def test_sibling_output_read_before_the_join_rejected():
    program = parse_program(
        """\
PROGRAM sib VERSION 1.0
PAR MAX 2
    step.a: DO define(x = 1) -> E.a
    step.b: DO define(x = E.a) -> E.b
BARRIER
RETURN E.b
"""
    )
    with pytest.raises(ParseError, match="used before definition"):
        validate_program(program, known_commands={"define"})


def test_duplicate_parent_output_targets_rejected():
    program = parse_program(
        """\
PROGRAM dup VERSION 1.0
PAR MAX 2
    step.a: DO define(x = 1) -> E.same
    step.b: DO define(x = 2) -> E.same
BARRIER
RETURN E.same
"""
    )
    with pytest.raises(ParseError, match="duplicate target"):
        validate_program(program, known_commands={"define"})


def test_barrier_targets_must_equal_the_branch_union():
    program = parse_program(
        """\
PROGRAM subset VERSION 1.0
PAR MAX 2
    step.a: DO define(x = 1) -> E.a
    step.b: DO define(x = 2) -> E.b
BARRIER -> E.a
RETURN E.a
"""
    )
    with pytest.raises(ParseError, match="exactly the union"):
        validate_program(program, known_commands={"define"})


def test_branch_target_colliding_with_parent_node_rejected():
    program = parse_program(
        """\
PROGRAM collide VERSION 1.0
INPUT
    E.z = 1
PAR MAX 2
    step.a: DO define(x = 1) -> E.a
    step.b: DO define(x = 2) -> E.z
BARRIER
RETURN E.a
"""
    )
    with pytest.raises(ParseError, match="duplicate target"):
        validate_program(program, known_commands={"define"})


def test_branch_revise_retire_rejected():
    program = parse_program(
        """\
PROGRAM rev VERSION 1.0
INPUT
    E.z = 1
PAR MAX 2
    step.a: DO define(x = 1) -> E.a REVISE E.z
    step.b: DO define(x = 2) -> E.b
BARRIER
RETURN E.a
"""
    )
    with pytest.raises(ParseError, match="REVISE/RETIRE"):
        validate_program(program, known_commands={"define"})


def test_pre_par_programs_seal_byte_identically():
    """Programs without PAR seal exactly as before the construct existed."""
    pre_par = (
        """\
PROGRAM pre VERSION 1.0
INPUT
    G.goal = "x"
step.a: DO define(request = G.goal) -> E.a
RETURN E.a
"""
    )
    assert seal_digest(parse_program(pre_par)) == seal_digest(
        parse_program(pre_par)
    )
    # A PAR block elsewhere does not perturb this program's canonical form.
    assert '"kind":"par"' not in canonical_json(parse_program(pre_par))


# ---------------------------------------------------------------------------
# Runtime: heterogeneous branches, barrier, adoption
# ---------------------------------------------------------------------------


def test_heterogeneous_do_and_call_branches_execute_and_combine(tmp_path):
    program = parse_program(HETEROGENEOUS_PROGRAM)
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store, make_worker(), protocols_dir="protocols"
    )
    result = coordinator.execute(program, run_id="het-1")
    assert result["status"] == "succeeded", result.get("error")
    state = store.project_state("het-1")["nodes"]
    # Both branch outputs adopted under their own names, then combined.
    assert "E.code" in state
    assert "E.context" in state and "V.analysis" in state
    assert state["D.plan"]["value"] == {
        "summary": [state["E.code"]["value"], state["E.context"]["value"]]
    }
    # One CHILD_ADOPTED per branch, then PAR_JOINED, then the entry commit.
    events = store.events("het-1")
    adopted = [
        event for event in events if event.event_type is EventType.CHILD_ADOPTED
    ]
    assert {event.invocation_id for event in adopted} == {"par1", "par2"}
    joined = [
        event for event in events if event.event_type is EventType.PAR_JOINED
    ]
    assert len(joined) == 1
    assert joined[0].payload["branches"] == {"par1": "succeeded", "par2": "succeeded"}
    assert joined[0].payload["targets"] == ["E.code", "E.context", "V.analysis"]
    # Branch child runs are isolated and audit-clean.
    for branch in ("het-1:par1", "het-1:par2"):
        assert audit_run(store, branch).ok
    assert audit_run(store, "het-1").ok
    store.close()


def test_ledger_has_one_task_per_branch_and_no_block_task(tmp_path):
    program = parse_program(HETEROGENEOUS_PROGRAM)
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store, make_worker(), protocols_dir="protocols"
    )
    assert coordinator.execute(program, run_id="led-1")["status"] == "succeeded"
    ledger = store.task_ledger("led-1")
    texts = {task.text: task.status for task in ledger.tasks.values()}
    assert any(text.startswith("PAR branch 1: ") for text in texts)
    assert any(text.startswith("PAR branch 2: ") for text in texts)
    assert all(
        task.status is TaskStatus.COMPLETED for task in ledger.tasks.values()
    )
    assert not any(text.startswith("PAR MAX") for text in texts)
    store.close()


def test_barrier_waits_for_the_slow_branch_before_adopting(tmp_path):
    release = threading.Event()
    fast_arrived = threading.Event()

    def define(request, **kwargs: Any) -> Any:
        if request == "slow":
            # The slow branch blocks until the fast branch has completed
            # and the barrier has been observed to hold everything back.
            fast_arrived.wait(2.0)
            release.wait(5.0)
            return {"value": "slow"}
        fast_arrived.set()
        release.wait(5.0)
        return {"value": "fast"}

    program = parse_program(
        """\
PROGRAM slowfast VERSION 1.0
INPUT
    G.goal = "x"
PAR MAX 2
    step.slow: DO define(request = "slow") -> E.slow
    step.fast: DO define(request = "fast") -> E.fast
BARRIER -> E.slow, E.fast
step.combine: DO summarize(source_refs = [E.slow, E.fast]) -> D.plan
RETURN D.plan
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        DeterministicWorker(handlers={
            "define": define,
            "summarize": lambda source_refs: {"summary": list(source_refs)},
        }),
        protocols_dir="protocols",
    )
    outcome: dict[str, Any] = {}

    def run() -> None:
        outcome["result"] = coordinator.execute(program, run_id="bar-1")

    thread = threading.Thread(target=run)
    thread.start()
    # Give the branches time to dispatch; neither may be adopted before the
    # barrier, and the run must still be incomplete while the slow branch
    # holds the barrier open.
    time.sleep(0.15)
    assert "E.fast" not in store.project_state("bar-1")["nodes"]
    assert "E.slow" not in store.project_state("bar-1")["nodes"]
    release.set()
    thread.join(10.0)
    result = outcome["result"]
    assert result["status"] == "succeeded", result.get("error")
    state = store.project_state("bar-1")["nodes"]
    assert state["E.slow"]["value"] == {"value": "slow"}
    assert state["E.fast"]["value"] == {"value": "fast"}
    assert audit_run(store, "bar-1").ok
    store.close()


def test_completion_order_permutations_preserve_the_final_state(tmp_path):
    """Both completion orders produce the same projected final state."""
    program_text = """\
PROGRAM perm VERSION 1.0
INPUT
    G.goal = "x"
PAR MAX 2
    step.first: DO define(request = "first") -> E.first
    step.second: DO define(request = "second") -> E.second
BARRIER -> E.first, E.second
RETURN E.first
"""

    def run_with(first_delay: float, second_delay: float, run_id: str) -> dict:
        def define(request, **kwargs: Any) -> Any:
            time.sleep(first_delay if request == "first" else second_delay)
            return {"value": request}

        store = EventStore(str(tmp_path / f"{run_id}.sqlite"))
        coordinator = SequentialCoordinator(
            store, make_worker(define=define)
        )
        result = coordinator.execute(parse_program(program_text), run_id=run_id)
        assert result["status"] == "succeeded"
        state = store.project_state(run_id)
        store.close()
        return state

    first_wins = run_with(0.2, 0.0, "perm-1")
    second_wins = run_with(0.0, 0.2, "perm-2")
    assert first_wins["nodes"] == second_wins["nodes"]
    assert first_wins["state_version"] == second_wins["state_version"]


def test_branch_failure_cancels_sibling_and_fails_run_atomically(tmp_path):
    def boom(**kwargs: Any) -> Any:
        raise ValueError("worker exploded")

    program = parse_program(
        """\
PROGRAM bfail VERSION 1.0
INPUT
    G.goal = "x"
PAR MAX 2
    step.bad: DO boom(request = G.goal) -> E.bad
    step.good: DO define(request = G.goal) -> E.good
BARRIER -> E.bad, E.good
step.after: DO summarize(source_refs = [E.good]) -> P.after
RETURN P.after
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store, make_worker(boom=boom), protocols_dir="protocols"
    )
    result = coordinator.execute(program, run_id="fail-1")
    assert result["status"] == "failed"
    assert "worker exploded" in result["error"]
    # Atomic: nothing after the barrier ran; the sibling output was never
    # adopted into the parent state.
    state = store.project_state("fail-1")["nodes"]
    assert "E.good" not in state
    assert "P.after" not in state
    # The sibling branch task is cancelled, the failed branch task settled.
    ledger = store.task_ledger("fail-1")
    statuses = {task.text: task.status for task in ledger.tasks.values()}
    assert any(
        "PAR branch 1" in text and status is TaskStatus.CANCELLED
        for text, status in statuses.items()
    )
    assert any(
        "PAR branch 2" in text and status is TaskStatus.CANCELLED
        for text, status in statuses.items()
    )
    assert audit_run(store, "fail-1").ok
    store.close()


def test_max_cap_bounds_concurrent_branch_dispatch(tmp_path):
    active = 0
    peak = 0
    lock = threading.Lock()

    def tracked_define(**kwargs: Any) -> Any:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"value": "x"}

    program = parse_program(
        """\
PROGRAM cap VERSION 1.0
INPUT
    G.goal = "x"
PAR MAX 1
    step.a: DO define(request = G.goal) -> E.a
    step.b: DO define(request = G.goal) -> E.b
BARRIER
RETURN E.a
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store, make_worker(define=tracked_define)
    )
    result = coordinator.execute(program, run_id="cap-1")
    assert result["status"] == "succeeded"
    assert peak == 1
    assert audit_run(store, "cap-1").ok
    store.close()


def test_branches_overlap_up_to_the_max(tmp_path):
    barrier = threading.Barrier(2, timeout=5.0)

    def barrier_define(**kwargs: Any) -> Any:
        # Two-party barrier: only met when both branches truly overlap.
        barrier.wait()
        return {"value": "x"}

    program = parse_program(
        """\
PROGRAM overlap VERSION 1.0
INPUT
    G.goal = "x"
PAR MAX 2
    step.a: DO define(request = G.goal) -> E.a
    step.b: DO define(request = G.goal) -> E.b
BARRIER
RETURN E.a
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store, make_worker(define=barrier_define)
    )
    result = coordinator.execute(program, run_id="ovl-1")
    assert result["status"] == "succeeded"
    assert audit_run(store, "ovl-1").ok
    store.close()


def test_replay_identity_after_reopen(tmp_path):
    program = parse_program(HETEROGENEOUS_PROGRAM)
    db = str(tmp_path / "run.sqlite")
    store = EventStore(db)
    coordinator = SequentialCoordinator(
        store, make_worker(), protocols_dir="protocols"
    )
    assert coordinator.execute(program, run_id="rep-1")["status"] == "succeeded"
    first_projection = store.project_state("rep-1")
    first_events = [
        (event.seq, event.event_type.value, event.invocation_id,
         event.instruction_id, event.state_version)
        for event in store.events("rep-1")
    ]
    store.close()
    # Reopen the same database: replay is identical.
    reopened = EventStore(db)
    assert reopened.project_state("rep-1") == first_projection
    second_events = [
        (event.seq, event.event_type.value, event.invocation_id,
         event.instruction_id, event.state_version)
        for event in reopened.events("rep-1")
    ]
    assert second_events == first_events
    assert audit_run(reopened, "rep-1").ok
    reopened.close()


def test_workspace_isolation_active_inside_par_branches(tmp_path):
    """Issue #23's isolation applies to PAR branches (edit writes land in
    the branch's workspace subdirectory; the parent workspace stays clean;
    the merge integrates disjoint paths)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    def edit(path: str, content: str, _workspace_root: str | None = None, **_: Any) -> str:
        base = _workspace_root or str(workspace)
        target = os.path.join(base, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    program = parse_program(
        """\
PROGRAM parws VERSION 1.0
INPUT
    G.goal = "x"
PAR MAX 2
    step.left: DO edit(path = "left.txt", content = "L") -> ART.left
    step.right: DO edit(path = "right.txt", content = "R") -> ART.right
BARRIER -> ART.left, ART.right
step.combine: DO summarize(source_refs = [ART.left, ART.right]) -> P.plan
RETURN P.plan
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store, make_worker(edit=edit), workspace_root=str(workspace)
    )
    result = coordinator.execute(program, run_id="pws-1")
    assert result["status"] == "succeeded", result.get("error")
    assert (workspace / "branches" / "par1" / "left.txt").read_text() == "L"
    assert (workspace / "branches" / "par2" / "right.txt").read_text() == "R"
    assert (workspace / "left.txt").read_text() == "L"
    assert (workspace / "right.txt").read_text() == "R"
    assert audit_run(store, "pws-1").ok
    store.close()


def test_nested_par_bounded_by_budget_child_depth(tmp_path, monkeypatch):
    """A CALL branch whose protocol contains its own PAR block nests one
    level deeper; the budget's child-depth cap bounds it."""
    protocols = tmp_path / "protocols"
    protocols.mkdir()
    (protocols / "inner.think").write_text(
        """\
PROGRAM inner VERSION 1.0
INPUT
    G.seed = "x"
PAR MAX 2
    step.i1: DO define(request = G.seed) -> E.i1
    step.i2: DO define(request = G.seed) -> E.i2
BARRIER
RETURN E.i1, E.i2
""",
        encoding="utf-8",
    )
    program = parse_program(
        """\
PROGRAM outer VERSION 1.0
INPUT
    G.goal = "x"
PAR MAX 2
    CALL protocol.inner(seed = G.goal) -> E.i1, E.i2
    step.flat: DO define(request = G.goal) -> E.f
BARRIER -> E.i1, E.i2, E.f
RETURN E.i1
"""
    )
    # Default depth (8): the nested PAR succeeds.
    store = EventStore(str(tmp_path / "ok.sqlite"))
    coordinator = SequentialCoordinator(
        store, make_worker(), protocols_dir=str(protocols)
    )
    result = coordinator.execute(program, run_id="nest-1")
    assert result["status"] == "succeeded", result.get("error")
    assert set(store.project_state("nest-1")["nodes"]) >= {"E.i1", "E.i2", "E.f"}
    assert audit_run(store, "nest-1").ok
    store.close()
    # Depth 1: the nested PAR's branches (depth 2) exceed the cap, the
    # protocol run fails, and the outer PAR fails atomically.
    store2 = EventStore(str(tmp_path / "capped.sqlite"))
    coordinator2 = SequentialCoordinator(
        store2, make_worker(), protocols_dir=str(protocols)
    )
    result2 = coordinator2.execute(
        program, run_id="nest-2", budget=ExecutionBudget(max_child_depth=1)
    )
    assert result2["status"] == "failed"
    assert "max_child_depth" in result2["error"]
    assert audit_run(store2, "nest-2").ok
    store2.close()


def test_non_par_programs_behave_identically(tmp_path):
    """A sequential program (no PAR) is untouched by the new machinery."""
    program = parse_program(
        """\
PROGRAM plain VERSION 1.0
INPUT
    G.goal = "x"
step.a: DO define(request = G.goal) -> E.a
step.b: DO summarize(source_refs = [E.a]) -> P.b
RETURN P.b
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(store, make_worker())
    result = coordinator.execute(program, run_id="plain-1")
    assert result["status"] == "succeeded"
    assert "PAR" not in canonical_json(program)
    assert audit_run(store, "plain-1").ok
    store.close()
