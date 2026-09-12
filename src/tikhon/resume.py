"""Crash-window recovery: resume an interrupted tikhon run (issue #10).

Implements the pragmatic subset of the deterministic resume algorithm
from ``demo/runs/crash-recovery-glm52/solution.md`` (crash-window table
W0a-W12) that is correct-by-construction with the current event schema:

- A run with a RUN_FINISHED event is terminal: the recorded status is
  returned without appending anything (``"already_terminal": true``).
  This covers W4, W10, W11 and W12 — no resume is possible or needed.
- Otherwise the first plan entry without a terminal SUCCEEDED event is
  re-executed through the coordinator's own machinery
  (``SequentialCoordinator._drive_plan``).  Committed lifecycle events
  (task_started / INVOCATION_READY / INVOCATION_DISPATCHED) are never
  re-emitted, but the worker call IS re-executed: dispatch never implies
  success (at-least-once for the worker call; the ``run_id:invocation_id``
  idempotency key carried by INVOCATION_DISPATCHED payloads since wave 4
  is the dedup contract for effectful workers).  RESULT_RECEIVED,
  VALIDATION_PASSED and the atomic SUCCEEDED batch are appended fresh.
- Tasks missing because the crash predated the task-creation batch (W0a)
  are created first with the same text/mapping rule as a normal start.
- Tasks for already-completed steps are COMPLETED; the resumed step's
  task is IN_PROGRESS (started before the crash) — ``start_task``
  requires PENDING, so the coordinator skips the start when the task is
  already IN_PROGRESS and raises only on impossible states.
- Append-only: resume appends new events with the continuing gapless
  seq the EventStore guarantees, and a second SUCCEEDED terminal for the
  same invocation is impossible by the store's duplicate guard.

Deferred windows (see solution.md): W5 result adoption without a worker
re-call (the resume path re-executes instead — at-least-once), and the
idempotency-key external-effect query for W3 (needs external system
cooperation that does not exist yet).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tikhon.runtime.coordinator import SequentialCoordinator, _uses_kb_refs
from tikhon.runtime.events import EventStore, EventType, _Record
from tikhon.state import StateDelta
from tikhon.syntax import validate_program

if TYPE_CHECKING:
    from tikhon.memory import KnowledgeBase
    from tikhon.syntax.model import Program

__all__ = ["resume_run"]


def resume_run(
    store: EventStore,
    worker: Any,
    run_id: str,
    program: "Program",
    memory: "KnowledgeBase | None" = None,
    protocols_dir: str | None = None,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    """Resume an interrupted run; same result shape as ``execute``.

    Loads the run's events; returns the recorded terminal status when a
    RUN_FINISHED exists, otherwise rebuilds run state, ensures the plan's
    tasks exist, and drives the remaining steps through a
    :class:`SequentialCoordinator` with the same ledger/event invariants
    as a fresh start.

    ``workspace_root`` mirrors the coordinator's WorkspacePolicy hook so
    a resumed run dispatches effectful commands exactly like ``run``.
    """
    validate_program(
        program,
        known_commands=worker.commands,
        protocols_dir=protocols_dir,
    )
    if memory is None and _uses_kb_refs(program):
        raise ValueError(
            "program uses KB.* references but no knowledge base was"
            " provided: pass memory=KnowledgeBase(path) to resume_run"
        )

    events = store.events(run_id)

    # -- identity: the run must exist and belong to this program ------
    # (store.run raises KeyError for an unknown run; the RUN_STARTED
    # payload records the program name/version a fresh start sealed in.)
    store.run(run_id)
    run_started = next(
        (event for event in events if event.event_type is EventType.RUN_STARTED),
        None,
    )
    if (
        run_started is not None
        and isinstance(run_started.payload, dict)
        and run_started.payload.get("program") is not None
    ):
        recorded = (
            run_started.payload.get("program"),
            run_started.payload.get("version"),
        )
        if recorded != (program.name, program.version):
            raise ValueError(
                f"program {program.name}@{program.version} does not match"
                f" the run's recorded program {recorded[0]}@{recorded[1]};"
                " refusing to resume with a mismatched program"
            )

    # -- terminal runs are never resumed (W4/W10/W11/W12) -------------
    run_finished = [
        event for event in events if event.event_type is EventType.RUN_FINISHED
    ]
    if run_finished:
        payload = (
            run_finished[-1].payload
            if isinstance(run_finished[-1].payload, dict)
            else {}
        )
        result: dict[str, Any] = {
            "run_id": run_id,
            "status": payload.get("status", "unknown"),
            "outputs": {},
            "already_terminal": True,
        }
        if "error" in payload:
            result["error"] = payload["error"]
        return result

    # -- rebuild the run-state values mapping --------------------------
    # INPUT declarations seed the mapping exactly like a fresh start;
    # committed SUCCEEDED deltas then replay in seq order (add/revise
    # write, retire pops) so the reconstruction matches the values the
    # coordinator held at the crash point — including declarations no
    # step ever targeted and refs retired by a REVISE/RETIRE correction.
    values: dict[str, Any] = {}
    for decl in program.declarations:
        values[decl.ref] = decl.value
    for event in events:
        if event.event_type is not EventType.SUCCEEDED:
            continue
        payload = event.payload
        if not isinstance(payload, dict) or "delta" not in payload:
            continue
        delta = StateDelta.from_dict(payload["delta"])
        for node in delta.add_nodes:
            values[node["id"]] = node["value"]
        for node in delta.revise_nodes:
            values[node["id"]] = node["value"]
        for ref in delta.retire_nodes:
            values.pop(ref, None)

    coordinator = SequentialCoordinator(
        store,
        worker,
        memory=memory,
        workspace_root=workspace_root,
        protocols_dir=protocols_dir,
    )
    plan = coordinator._build_plan(program)

    # -- find the first non-terminal step ------------------------------
    # Invocation ids are positional (inv-1..inv-N in plan order), so a
    # step is terminal exactly when its invocation id carries a
    # SUCCEEDED event.  Dispatch alone never implies success.
    succeeded = {
        event.invocation_id
        for event in events
        if event.event_type is EventType.SUCCEEDED and event.invocation_id
    }
    start_idx = len(plan)
    for idx in range(len(plan)):
        if f"inv-{idx + 1}" not in succeeded:
            start_idx = idx
            break
    expected_terminal = {f"inv-{i + 1}" for i in range(start_idx)}
    if succeeded != expected_terminal:
        raise ValueError(
            f"run {run_id!r} has a non-prefix set of SUCCEEDED"
            f" invocations {sorted(succeeded)}; impossible for the"
            " sequential coordinator"
        )

    # -- ensure tasks exist (W0a: crash before the creation batch) -----
    ledger = store.task_ledger(run_id)
    task_ids = list(ledger.tasks)
    if len(task_ids) > len(plan):
        raise ValueError(
            f"run {run_id!r} has {len(task_ids)} tasks but the program"
            f" plans {len(plan)}; refusing to resume a mismatched program"
        )
    for idx, task_id in enumerate(task_ids):
        expected_text = coordinator._task_text(plan[idx])
        if ledger.tasks[task_id].text != expected_text:
            raise ValueError(
                f"task {task_id!r} ({ledger.tasks[task_id].text!r}) does"
                f" not match plan step {idx} ({expected_text!r});"
                " refusing to resume with a mismatched program"
            )
    if len(task_ids) < len(plan):
        create_records: list[_Record] = []
        create_ledger = store.task_ledger(run_id)
        for idx in range(len(task_ids), len(plan)):
            entry = plan[idx]
            task = create_ledger.create_task(
                text=coordinator._task_text(entry),
                creator="coordinator",
            )
            create_records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task.id,
                payload={
                    "kind": "task_created", "id": task.id, "text": task.text,
                    "priority": task.priority, "parent": task.parent,
                    "dependencies": task.dependencies,
                    "creator": task.creator,
                },
                store=store,
            ))
        store.append_batch(run_id, create_records)
        task_ids = list(store.task_ledger(run_id).tasks)
    statement_to_task = {idx: task_ids[idx] for idx in range(len(plan))}

    # -- replay protocol INPUT bindings of already-committed entries ---
    # Protocol CALL expansions bind their INPUT declarations into the
    # shared values mapping when the expansion's first entry executes;
    # those bindings are not part of any state delta, so entries after a
    # mid-expansion crash point need them re-derived to resolve args.
    for idx in range(start_idx):
        for protocol_name, call_args, declarations in plan[idx].binds:
            coordinator._bind_protocol_inputs(
                protocol_name, call_args, declarations, values
            )

    return coordinator._drive_plan(
        program,
        run_id,
        plan,
        values,
        statement_to_task,
        start_idx=start_idx,
    )
