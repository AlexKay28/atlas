"""Tests specifying the branch-workspace, resource-claim and artifact-merge
contract (issue #23).

Covers the ``ResourceLedger`` primitive (exclusive in-process claims,
thread-safe, run-scoped by construction), the coordinator wiring without
new syntax (effectful dispatches inside branches claim
``workspace:<branch identity>`` and are annotated on their DISPATCHED
payloads; the artifact merge claims ``merge:<run_id>``), branch workspace
isolation for PAR branches and scatter candidates (effectful writes land
in ``<workspace_root>/branches/<branch_id>/`` while the parent workspace
stays untouched; read-only dispatches still see the main root), the
explicit deterministic artifact merge after a join (disjoint artifacts
integrate with every adopted path accounted; a cross-branch path
collision fails the run atomically with a clear error and no silent
overwrite), and unchanged no-branch behavior.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

import pytest

from atlas.audit import audit_run
from atlas.claims import ResourceLedger
from atlas.runtime import EventStore, EventType
from atlas.runtime.coordinator import DeterministicWorker, SequentialCoordinator
from atlas.syntax import parse_program


def edit_handler(workspace_root: str):
    """The workspace-sandboxed edit handler shape (mirrors the CLI builtin)."""

    def edit(path: str, content: str, _workspace_root: str | None = None, **_: Any) -> str:
        base = _workspace_root or workspace_root
        target = os.path.join(base, path)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        return os.path.relpath(target, os.path.realpath(base))

    return edit


def make_worker(**extra: Any) -> DeterministicWorker:
    handlers: dict[str, Any] = {
        "define": lambda **kwargs: {"value": kwargs},
        "summarize": lambda source_refs: {"summary": list(source_refs)},
    }
    handlers.update(extra)
    return DeterministicWorker(handlers=handlers)


TWO_BRANCH_EDIT_PROGRAM = """\
PROGRAM branches VERSION 1.0
INPUT
    G.goal = "write two disjoint files"
PAR MAX 2
    step.left: DO edit(path = "left.txt", content = "L") -> ART.left
    step.right: DO edit(path = "right.txt", content = "R") -> ART.right
BARRIER -> ART.left, ART.right
step.combine: DO summarize(source_refs = [ART.left, ART.right]) -> P.plan
RETURN P.plan
"""


# ---------------------------------------------------------------------------
# ResourceLedger primitive
# ---------------------------------------------------------------------------


def test_claim_is_exclusive_and_release_frees_the_hold():
    ledger = ResourceLedger()
    assert ledger.claim("workspace:par1", "owner-a") is True
    # Exclusive: a second holder (or the same holder again) is rejected
    # while the hold lives.
    assert ledger.claim("workspace:par1", "owner-b") is False
    assert ledger.claim("workspace:par1", "owner-a") is False
    assert ledger.holder("workspace:par1") == "owner-a"
    # Only the holder can release.
    assert ledger.release("workspace:par1", "owner-b") is False
    assert ledger.holder("workspace:par1") == "owner-a"
    assert ledger.release("workspace:par1", "owner-a") is True
    # Released: the resource is claimable again.
    assert ledger.holder("workspace:par1") is None
    assert ledger.claim("workspace:par1", "owner-b") is True


def test_independent_resources_are_claimed_concurrently():
    ledger = ResourceLedger()
    assert ledger.claim("workspace:par1", "owner-a") is True
    assert ledger.claim("workspace:par2", "owner-b") is True
    assert ledger.claim("merge:run-1", "owner-c") is True


def test_claims_serialize_conflicting_work_across_threads():
    ledger = ResourceLedger()
    order: list[str] = []
    first_held = threading.Event()
    second_rejected = threading.Event()
    first_released = threading.Event()

    def holder() -> None:
        assert ledger.claim("merge:run-1", "first") is True
        order.append("first-claimed")
        first_held.set()
        second_rejected.wait(2.0)
        assert ledger.release("merge:run-1", "first") is True
        order.append("first-released")
        first_released.set()

    def waiter() -> None:
        first_held.wait(2.0)
        # The conflicting claim is rejected while the first holds it.
        assert ledger.claim("merge:run-1", "second") is False
        second_rejected.set()
        # After the release the serialized claim succeeds.
        first_released.wait(2.0)
        assert ledger.claim("merge:run-1", "second") is True
        order.append("second-claimed")

    threads = [threading.Thread(target=holder), threading.Thread(target=waiter)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5.0)
    assert order == ["first-claimed", "first-released", "second-claimed"]


def test_ledger_validates_arguments():
    ledger = ResourceLedger()
    with pytest.raises(ValueError):
        ledger.claim("", "owner")
    with pytest.raises(ValueError):
        ledger.claim("res", "")
    with pytest.raises(ValueError):
        ledger.release("res", "")


# ---------------------------------------------------------------------------
# Branch workspace isolation (PAR branches and scatter candidates)
# ---------------------------------------------------------------------------


def test_par_branches_editing_the_same_relative_path_stay_isolated(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    program = parse_program(
        """\
PROGRAM samepath VERSION 1.0
INPUT
    G.goal = "both branches write same.txt"
PAR MAX 2
    step.left: DO edit(path = "same.txt", content = "L") -> ART.left
    step.right: DO edit(path = "same.txt", content = "R") -> ART.right
BARRIER -> ART.left, ART.right
RETURN ART.left
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(edit=edit_handler(str(workspace))),
        workspace_root=str(workspace),
    )
    result = coordinator.execute(program, run_id="iso-1")
    # The merge sees both artifacts and refuses to integrate the collision.
    assert result["status"] == "failed"
    assert "artifact merge collision" in result["error"]
    # Isolation: each branch wrote its own file in its own subdirectory.
    assert (workspace / "branches" / "par1" / "same.txt").read_text() == "L"
    assert (workspace / "branches" / "par2" / "same.txt").read_text() == "R"
    # The parent workspace root was never touched directly by a branch.
    assert not (workspace / "same.txt").exists()
    assert audit_run(store, "iso-1").ok
    store.close()


def test_disjoint_branch_artifacts_integrate_into_the_parent_workspace(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    program = parse_program(TWO_BRANCH_EDIT_PROGRAM)
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(edit=edit_handler(str(workspace))),
        workspace_root=str(workspace),
    )
    result = coordinator.execute(program, run_id="merge-1")
    assert result["status"] == "succeeded"
    # Disjoint patches integrate: both files land in the parent workspace.
    assert (workspace / "left.txt").read_text() == "L"
    assert (workspace / "right.txt").read_text() == "R"
    # The branch subdirectories keep their own copies (evidence preserved).
    assert (workspace / "branches" / "par1" / "left.txt").exists()
    assert (workspace / "branches" / "par2" / "right.txt").exists()
    # The merge's explicit accounting lists every adopted artifact path.
    joined = next(
        event
        for event in store.events("merge-1")
        if event.event_type is EventType.PAR_JOINED
    )
    assert joined.payload["merged_artifacts"] == [
        {"branch": "par1", "node": "ART.left", "path": "left.txt", "copied": True},
        {"branch": "par2", "node": "ART.right", "path": "right.txt", "copied": True},
    ]
    assert audit_run(store, "merge-1").ok
    store.close()


def test_scatter_candidates_get_isolated_branch_workspaces(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    program = parse_program(
        """\
PROGRAM scatterws VERSION 1.0
INPUT
    Q.parts = ["alpha", "beta"]
SCATTER X.part IN Q.parts MAX 2
  step.write: DO edit(path = "part.txt", content = X.part) -> ART.f
GATHER write AS E.all USING all
RETURN E.all
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(edit=edit_handler(str(workspace))),
        workspace_root=str(workspace),
    )
    result = coordinator.execute(program, run_id="scat-1")
    assert result["status"] == "failed"  # same relative path -> explicit conflict
    assert "artifact merge collision" in result["error"]
    assert (
        workspace / "branches" / "cand1" / "part.txt"
    ).read_text() == "alpha"
    assert (
        workspace / "branches" / "cand2" / "part.txt"
    ).read_text() == "beta"
    assert not (workspace / "part.txt").exists()
    store.close()


def test_scatter_disjoint_candidate_artifacts_integrate(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    program = parse_program(
        """\
PROGRAM scatterok VERSION 1.0
INPUT
    Q.parts = ["one", "two"]
SCATTER X.part IN Q.parts MAX 2
  step.write: DO edit(path = X.part, content = X.part) -> ART.f
GATHER write AS E.all USING all
RETURN E.all
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(edit=edit_handler(str(workspace))),
        workspace_root=str(workspace),
    )
    result = coordinator.execute(program, run_id="scat-2")
    assert result["status"] == "succeeded"
    assert (workspace / "one").read_text() == "one"
    assert (workspace / "two").read_text() == "two"
    succeeded = next(
        event
        for event in store.events("scat-2")
        if event.event_type is EventType.SUCCEEDED
        and isinstance(event.payload, dict)
        and "merge" in event.payload
    )
    assert succeeded.payload["merge"]["artifacts"] == [
        {"branch": "cand1", "node": "E.all.c1.f", "path": "one", "copied": True},
        {"branch": "cand2", "node": "E.all.c2.f", "path": "two", "copied": True},
    ]
    assert audit_run(store, "scat-2").ok
    store.close()


# ---------------------------------------------------------------------------
# Claim wiring (no new syntax)
# ---------------------------------------------------------------------------


def test_effectful_branch_dispatches_claim_and_annotate(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    program = parse_program(TWO_BRANCH_EDIT_PROGRAM)
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(edit=edit_handler(str(workspace))),
        workspace_root=str(workspace),
    )
    assert coordinator.execute(program, run_id="claim-1")["status"] == "succeeded"
    parent_dispatched = [
        event
        for event in store.events("claim-1")
        if event.event_type is EventType.INVOCATION_DISPATCHED
        and event.invocation_id.startswith("par")
    ]
    # The parent-side branch dispatches carry the branch identity.
    assert {event.invocation_id for event in parent_dispatched} == {"par1", "par2"}
    # The effectful dispatches inside the branch child runs hold the
    # branch's exclusive claim and write into the branch root.
    for branch in ("par1", "par2"):
        child_dispatched = [
            event
            for event in store.events(f"claim-1:{branch}")
            if event.event_type is EventType.INVOCATION_DISPATCHED
        ]
        assert len(child_dispatched) == 1
        payload = child_dispatched[0].payload
        assert payload["resource_claims"] == [f"workspace:claim-1:{branch}"]
        assert payload["args"]["_workspace_root"] == str(
            workspace / "branches" / branch
        )
    # The merge machinery held the run's merge claim (covered by
    # test_merge_failure_releases_the_merge_claim); by the time the run is
    # terminal every hold is released.
    assert audit_run(store, "claim-1").ok
    store.close()


def test_top_level_effectful_dispatch_stays_unclaimed_and_unannotated(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    program = parse_program(
        """\
PROGRAM plain VERSION 1.0
INPUT
    G.goal = "x"
step.write: DO edit(path = "top.txt", content = "T") -> ART.top
RETURN ART.top
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(edit=edit_handler(str(workspace))),
        workspace_root=str(workspace),
    )
    assert coordinator.execute(program, run_id="plain-1")["status"] == "succeeded"
    dispatched = next(
        event
        for event in store.events("plain-1")
        if event.event_type is EventType.INVOCATION_DISPATCHED
    )
    assert "resource_claims" not in dispatched.payload
    assert dispatched.payload["args"]["_workspace_root"] == str(workspace)
    assert (workspace / "top.txt").read_text() == "T"
    store.close()


def test_merge_failure_releases_the_merge_claim(tmp_path):
    """A merge that fails on a collision must not leak its claim."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    seen_claims: list[str] = []
    original_claim = ResourceLedger.claim
    original_release = ResourceLedger.release

    def spy_claim(self, resource, owner):
        seen_claims.append(("claim", resource))
        return original_claim(self, resource, owner)

    def spy_release(self, resource, owner):
        seen_claims.append(("release", resource))
        return original_release(self, resource, owner)

    program = parse_program(
        """\
PROGRAM col VERSION 1.0
INPUT
    G.goal = "x"
PAR MAX 2
    step.left: DO edit(path = "same.txt", content = "L") -> ART.left
    step.right: DO edit(path = "same.txt", content = "R") -> ART.right
BARRIER
RETURN ART.left
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(edit=edit_handler(str(workspace))),
        workspace_root=str(workspace),
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(ResourceLedger, "claim", spy_claim)
        monkeypatch.setattr(ResourceLedger, "release", spy_release)
        result = coordinator.execute(program, run_id="claim-2")
    assert result["status"] == "failed"
    assert ("claim", "merge:claim-2") in seen_claims
    assert ("release", "merge:claim-2") in seen_claims
    store.close()


# ---------------------------------------------------------------------------
# Collision -> atomic failure; no-branch behavior unchanged
# ---------------------------------------------------------------------------


def test_collision_fails_the_run_atomically_without_partial_publication(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    program = parse_program(
        """\
PROGRAM col2 VERSION 1.0
INPUT
    G.goal = "x"
PAR MAX 2
    step.left: DO edit(path = "same.txt", content = "L") -> ART.left
    step.right: DO edit(path = "same.txt", content = "R") -> ART.right
BARRIER -> ART.left, ART.right
step.after: DO define(request = G.goal) -> E.after
RETURN E.after
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(edit=edit_handler(str(workspace))),
        workspace_root=str(workspace),
    )
    result = coordinator.execute(program, run_id="col-1")
    assert result["status"] == "failed"
    error = result["error"]
    assert "artifact merge collision" in error
    assert "same.txt" in error and "par1" in error and "par2" in error
    # Atomic: a step after the barrier never ran; the run is terminal.
    assert "E.after" not in store.project_state("col-1")["nodes"]
    assert audit_run(store, "col-1").ok
    # The colliding files stay in their branch workspaces as evidence; the
    # parent workspace root received no silent overwrite.
    assert not (workspace / "same.txt").exists()
    store.close()


def test_no_branch_program_behavior_unchanged(tmp_path):
    """A program with no branches behaves byte-identically to the pre-#23
    workspace semantics (top-level root injected, no claims annotation,
    no branch directories created)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    program = parse_program(
        """\
PROGRAM nobranch VERSION 1.0
INPUT
    G.goal = "x"
step.a: DO define(request = G.goal) -> E.a
step.write: DO edit(path = "out.txt", content = "O") -> ART.out
step.read: DO summarize(source_refs = [ART.out]) -> P.s
RETURN P.s
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(edit=edit_handler(str(workspace))),
        workspace_root=str(workspace),
    )
    result = coordinator.execute(program, run_id="plain-2")
    assert result["status"] == "succeeded"
    assert (workspace / "out.txt").read_text() == "O"
    assert not (workspace / "branches").exists()
    for event in store.events("plain-2"):
        if event.event_type is EventType.INVOCATION_DISPATCHED:
            assert "resource_claims" not in event.payload
    assert audit_run(store, "plain-2").ok
    store.close()


# ---------------------------------------------------------------------------
# Unknown effect metadata and shared KB access (issue #23 acceptance)
# ---------------------------------------------------------------------------


def test_custom_command_without_registry_effect_metadata_is_undeclared(tmp_path):
    """A custom command unknown to the builtin registry carries no effect
    metadata, so it is treated as undeclared — never automatically pure,
    but also not claimed: no workspace root is injected, no claim is
    annotated, and its writes are the handler's own responsibility."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    writes: list[str] = []

    def custom_write(path: str, content: str, **kwargs: Any) -> str:
        # No _workspace_root injection: the handler sees none.
        assert "_workspace_root" not in kwargs
        writes.append(f"{path}={content}")
        return path

    program = parse_program(
        """\
PROGRAM custom VERSION 1.0
INPUT
    G.goal = "x"
PAR MAX 2
    step.a: DO custom_write(path = "a.txt", content = "A") -> E.a
    step.b: DO custom_write(path = "b.txt", content = "B") -> E.b
BARRIER
RETURN E.a
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(custom_write=custom_write),
        workspace_root=str(workspace),
    )
    result = coordinator.execute(program, run_id="custom-1")
    assert result["status"] == "succeeded"
    assert sorted(writes) == ["a.txt=A", "b.txt=B"]
    # Undeclared effects: no claim annotated on the parent-side branch
    # dispatches, and no workspace root injected into the child dispatches.
    for event in store.events("custom-1"):
        if (
            event.event_type is EventType.INVOCATION_DISPATCHED
            and event.invocation_id.startswith("par")
        ):
            assert "resource_claims" not in event.payload
    for branch in ("par1", "par2"):
        for event in store.events(f"custom-1:{branch}"):
            if event.event_type is EventType.INVOCATION_DISPATCHED:
                assert "_workspace_root" not in event.payload["args"]
                assert "resource_claims" not in event.payload
    assert audit_run(store, "custom-1").ok
    store.close()


def test_shared_kb_writes_from_branches_are_recorded_and_isolated(tmp_path):
    """Two PAR branches writing the shared knowledge base (remember is a
    durable write per the registry): both dispatches are claimed as
    branch work (durable-write effect class) and both writes land in the
    shared KB — coordination is recorded, not magically serialized away."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    kb_writes: list[tuple[str, Any]] = []
    program = parse_program(
        """\
PROGRAM kbshare VERSION 1.0
INPUT
    G.goal = "both branches record findings"
PAR MAX 2
    step.left: DO remember(key = "findings.left", value = "L") -> K.left
    step.right: DO remember(key = "findings.right", value = "R") -> K.right
BARRIER -> K.left, K.right
RETURN K.left
"""
    )
    store = EventStore(str(tmp_path / "run.sqlite"))
    coordinator = SequentialCoordinator(
        store,
        make_worker(
            remember=lambda key, value, **kwargs: kb_writes.append((key, value))
            or {"key": key}
        ),
        workspace_root=str(workspace),
    )
    result = coordinator.execute(program, run_id="kb-1")
    assert result["status"] == "succeeded"
    assert sorted(kb_writes) == [
        ("findings.left", "L"),
        ("findings.right", "R"),
    ]
    # remember is a durable write: its in-branch dispatches carry the
    # branch claims exactly like edit.
    claims = set()
    for branch in ("par1", "par2"):
        for event in store.events(f"kb-1:{branch}"):
            if event.event_type is EventType.INVOCATION_DISPATCHED:
                claims.update(event.payload.get("resource_claims", []))
    assert claims == {"workspace:kb-1:par1", "workspace:kb-1:par2"}
    assert audit_run(store, "kb-1").ok
    store.close()
