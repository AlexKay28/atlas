"""Tests for PAR resume after crash (issue #29).

Covers the three acceptance items from the issue:
  1. Crash after branch CHILD_ADOPTED + resume yields succeeded, with
     the PAR SUCCEEDED delta containing ALL barrier refs.
  2. project_state after resume contains every barrier ref.
  3. No duplicate INVOCATION_READY for an already-dispatched par<k> id.
"""

from __future__ import annotations

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
from tahoe.syntax import parse_program

PAR_RESUME_PROGRAM = """\
PROGRAM par_resume VERSION 1.0
INPUT
    G.goal = "test"
PAR MAX 2
    step.alpha: DO define(request = "alpha") -> E.alpha
    step.beta: DO define(request = "beta") -> E.beta
BARRIER -> E.alpha, E.beta
step.combine: DO summarize(source_refs = [E.alpha, E.beta]) -> D.plan
RETURN D.plan
"""


def make_worker() -> DeterministicWorker:
    handlers: dict[str, Any] = {
        "define": lambda request, **kwargs: {"value": request},
        "summarize": lambda source_refs: {"summary": list(source_refs)},
    }
    return DeterministicWorker(handlers=handlers)


def _barrier_refs() -> list[str]:
    return ["E.alpha", "E.beta"]


# ---------------------------------------------------------------------------
# Acceptance 1: crash after CHILD_ADOPTED + resume -> succeeded with all
# barrier refs in the PAR SUCCEEDED delta
# ---------------------------------------------------------------------------


def test_crash_after_branch_adoption_resume_succeeds_with_barrier_refs(tmp_path):
    """Crash at the PAR crash_hook (after all branches joined, before
    PAR SUCCEEDED); resume yields succeeded and the SUCCEEDED delta
    contains every barrier ref."""
    program = parse_program(PAR_RESUME_PROGRAM)
    store = EventStore(str(tmp_path / "events.db"))
    coordinator = SequentialCoordinator(
        store, make_worker(), protocols_dir="protocols"
    )

    barrier_refs = _barrier_refs()

    # The crash_hook fires at the PAR entry's crash window (after all
    # branches adopted, before the terminal SUCCEEDED batch).
    def crash_hook(idx):
        raise CrashInterrupt("crash after branch adoptions")

    with pytest.raises(CrashInterrupt):
        coordinator.execute(
            program, run_id="par-resume-1", crash_hook=crash_hook
        )

    # No FAILED or RUN_FINISHED before resume.
    events = store.events("par-resume-1")
    assert not any(e.event_type is EventType.FAILED for e in events)
    assert not any(e.event_type is EventType.RUN_FINISHED for e in events)

    # CHILD_ADOPTED events should be committed for every branch.
    adopted = [
        e for e in events if e.event_type is EventType.CHILD_ADOPTED
    ]
    assert len(adopted) == 2

    # Resume.
    result = resume_run(store, make_worker(), "par-resume-1", program)
    assert result["status"] == "succeeded", result.get("error", "")

    # The PAR SUCCEEDED delta contains all barrier refs.
    events_after = store.events("par-resume-1")
    succeeded = [
        e
        for e in events_after
        if e.event_type is EventType.SUCCEEDED and e.invocation_id == "inv-1"
    ]
    assert len(succeeded) == 1
    delta = succeeded[0].payload.get("delta")
    assert delta is not None
    add_nodes = delta["add_nodes"] if isinstance(delta, dict) else delta.add_nodes
    add_node_ids = {node["id"] for node in add_nodes}
    for ref in barrier_refs:
        assert ref in add_node_ids, f"barrier ref {ref} missing from PAR SUCCEEDED delta"

    # Audit clean.
    assert audit_run(store, "par-resume-1").ok
    store.close()


# ---------------------------------------------------------------------------
# Acceptance 2: project_state after resume contains every barrier ref
# ---------------------------------------------------------------------------


def test_project_state_after_resume_contains_every_barrier_ref(tmp_path):
    """After crash + resume, project_state contains every barrier ref."""
    program = parse_program(PAR_RESUME_PROGRAM)
    store = EventStore(str(tmp_path / "events.db"))
    coordinator = SequentialCoordinator(
        store, make_worker(), protocols_dir="protocols"
    )

    barrier_refs = _barrier_refs()

    def crash_hook(idx):
        raise CrashInterrupt("crash after branch adoptions")

    with pytest.raises(CrashInterrupt):
        coordinator.execute(
            program, run_id="par-resume-2", crash_hook=crash_hook
        )

    result = resume_run(store, make_worker(), "par-resume-2", program)
    assert result["status"] == "succeeded"

    state = store.project_state("par-resume-2")
    nodes = state["nodes"]
    for ref in barrier_refs:
        assert ref in nodes, f"barrier ref {ref} missing from project_state"

    # The post-PAR step also succeeded — its output is present too.
    assert "D.plan" in nodes
    store.close()


# ---------------------------------------------------------------------------
# Acceptance 3: no duplicate INVOCATION_READY for an already-dispatched
# par<k> id
# ---------------------------------------------------------------------------


def test_no_duplicate_invocation_ready_for_dispatched_par_branch(tmp_path):
    """A branch dispatched before the crash does not get a duplicate
    INVOCATION_READY on resume.

    We simulate a crash at the PAR crash_hook (all branches joined, all
    READY/DISPATCHED committed).  After resume, the already-joined
    branches are re-derived without re-dispatching — no duplicate
    INVOCATION_READY for any par<k> id.
    """
    program = parse_program(PAR_RESUME_PROGRAM)
    store = EventStore(str(tmp_path / "events.db"))
    coordinator = SequentialCoordinator(
        store, make_worker(), protocols_dir="protocols"
    )

    def crash_hook(idx):
        raise CrashInterrupt("crash after branch adoptions")

    with pytest.raises(CrashInterrupt):
        coordinator.execute(
            program, run_id="par-resume-3", crash_hook=crash_hook
        )

    # Before resume: each par<k> has exactly one INVOCATION_READY.
    events_before = store.events("par-resume-3")
    ready_before = [
        e for e in events_before if e.event_type is EventType.INVOCATION_READY
    ]
    par_ready_before = [e for e in ready_before if e.invocation_id.startswith("par")]
    assert len(par_ready_before) == 2

    # Resume.
    result = resume_run(store, make_worker(), "par-resume-3", program)
    assert result["status"] == "succeeded"

    # After resume: still exactly one INVOCATION_READY per par<k> id.
    events_after = store.events("par-resume-3")
    par_ready_after = [
        e
        for e in events_after
        if e.event_type is EventType.INVOCATION_READY
        and e.invocation_id.startswith("par")
    ]
    assert len(par_ready_after) == 2, (
        f"expected 2 INVOCATION_READY for par<k> ids, got {len(par_ready_after)}"
    )

    # Also check INVOCATION_DISPATCHED is not duplicated.
    par_dispatched = [
        e
        for e in events_after
        if e.event_type is EventType.INVOCATION_DISPATCHED
        and e.invocation_id.startswith("par")
    ]
    assert len(par_dispatched) == 2, (
        f"expected 2 INVOCATION_DISPATCHED for par<k> ids,"
        f" got {len(par_dispatched)}"
    )

    store.close()


# ---------------------------------------------------------------------------
# Extra: resume projection equals a normal full run
# ---------------------------------------------------------------------------


def test_resume_projection_equals_normal_full_run(tmp_path):
    """The state projection after crash + resume matches a crash-free run."""
    program = parse_program(PAR_RESUME_PROGRAM)

    # Normal run.
    normal_store = EventStore(str(tmp_path / "normal.db"))
    coordinator = SequentialCoordinator(
        normal_store, make_worker(), protocols_dir="protocols"
    )
    coordinator.execute(program, run_id="run-x")
    normal_state = normal_store.project_state("run-x")
    normal_store.close()

    # Crash + resume run.
    crash_store = EventStore(str(tmp_path / "crash.db"))
    crash_coord = SequentialCoordinator(
        crash_store, make_worker(), protocols_dir="protocols"
    )

    def crash_hook(idx):
        raise CrashInterrupt("crash after branch adoptions")

    with pytest.raises(CrashInterrupt):
        crash_coord.execute(program, run_id="run-x", crash_hook=crash_hook)

    resume_run(crash_store, make_worker(), "run-x", program)
    resume_state = crash_store.project_state("run-x")

    import json
    assert json.dumps(normal_state, sort_keys=True) == json.dumps(
        resume_state, sort_keys=True
    )
    crash_store.close()
