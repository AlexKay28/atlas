"""Unified failure-record assembly for the TAHOE coordinator (issue #38).

All six+ failure-assembly sites in the pre-refactor coordinator.py built the
same record shape: optional VALIDATION_FAILED, then FAILED, invocation_recorded,
task_cancelled, cancel-pending-tasks, RUN_FINISHED — one atomic batch.  This
module provides parametrized builders so every site consumes the same
functions, eliminating the duplication that forced every bugfix to be applied
twice (the PAR resume bug #29 lived only in the sequential path).

The functions are pure record builders: they return ``list[_Record]`` and
never touch the store — the caller appends the batch.  This keeps the
single-writer commit semantics untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from tahoe.runtime.events import EventType, _Record
from tahoe.runtime.tasks import TaskStatus

if TYPE_CHECKING:
    from tahoe.runtime.coordinator import _PlanEntry


def _invocation_recorded(store: Any, task_id: str) -> _Record:
    """The standard invocation_recorded task update (zero usage placeholder)."""
    return _Record(
        event_type=EventType.TASK_UPDATED,
        task_id=task_id,
        payload={
            "kind": "invocation_recorded", "id": task_id,
            "tokens": 0, "cost": 0.0, "retries": 0,
            "elapsed_seconds": 0.0,
        },
        store=store,
    )


def _task_cancelled(store: Any, task_id: str) -> _Record:
    """The standard task_cancelled record."""
    return _Record(
        event_type=EventType.TASK_UPDATED,
        task_id=task_id,
        payload={"kind": "task_cancelled", "id": task_id},
        store=store,
    )


def _run_finished_failed(store: Any, error: str) -> _Record:
    """RUN_FINISHED(failed, error)."""
    return _Record(
        event_type=EventType.RUN_FINISHED,
        payload={"status": "failed", "error": error},
        store=store,
    )


def cancel_pending(
    store: Any,
    statement_to_task: dict[int, str],
    from_idx: int,
    plan_len: int,
) -> list[_Record]:
    """Cancel every created-but-unreached plan task from ``from_idx`` onward.

    Conditional tasks are created lazily, so absent mappings are skipped.
    """
    return [
        _task_cancelled(store, statement_to_task[pending_idx])
        for pending_idx in range(from_idx, plan_len)
        if pending_idx in statement_to_task
    ]


def fail_invocation(
    store: Any,
    run_id: str,
    plan: list["_PlanEntry"],
    statement_to_task: dict[int, str],
    idx: int,
    instruction_id: str,
    invocation_id: str,
    task_id: str,
    error: str,
    validation: dict[str, Any] | None = None,
) -> list[_Record]:
    """Build the atomic failure batch for one invocation.

    The record sequence:
    1. VALIDATION_FAILED (optional, when ``validation`` is not None)
    2. FAILED (instruction_id, invocation_id, task_id, error)
    3. invocation_recorded (task_id)
    4. task_cancelled (task_id)
    5. cancel_pending (idx+1 .. len(plan))
    6. RUN_FINISHED(failed, error)

    The caller appends the batch to ``store``.
    """
    records: list[_Record] = []
    if validation is not None:
        records.append(_Record(
            event_type=EventType.VALIDATION_FAILED,
            instruction_id=instruction_id,
            invocation_id=invocation_id,
            task_id=task_id,
            payload=validation,
            store=store,
        ))
    records.append(_Record(
        event_type=EventType.FAILED,
        instruction_id=instruction_id,
        invocation_id=invocation_id,
        task_id=task_id,
        payload={"error": error},
        store=store,
    ))
    records.append(_invocation_recorded(store, task_id))
    records.append(_task_cancelled(store, task_id))
    records.extend(cancel_pending(store, statement_to_task, idx + 1, len(plan)))
    records.append(_run_finished_failed(store, error))
    return records


def fail_invocation_concurrent(
    store: Any,
    run_id: str,
    plan: list["_PlanEntry"],
    statement_to_task: dict[int, str],
    idx: int,
    instruction_id: str,
    invocation_id: str,
    task_id: str,
    error: str,
    validation: dict[str, Any] | None = None,
    in_flight: dict[int, Any] | None = None,
    terminal: set[int] | None = None,
) -> list[_Record]:
    """Build the concurrent-variant failure batch.

    Same as :func:`fail_invocation` plus: mark in-flight sibling invocations
    FAILED (issue #31: audit invariant "no DISPATCHED without terminal event
    after RUN_FINISHED").  Pending tasks that are in-flight or already
    terminal are excluded from the cancel-pending pass (they are handled
    individually).  The caller is responsible for draining the pool
    after appending this batch.
    """
    in_flight = in_flight or {}
    terminal = terminal or set()

    records: list[_Record] = []
    if validation is not None:
        records.append(_Record(
            event_type=EventType.VALIDATION_FAILED,
            instruction_id=instruction_id,
            invocation_id=invocation_id,
            task_id=task_id,
            payload=validation,
            store=store,
        ))
    records.append(_Record(
        event_type=EventType.FAILED,
        instruction_id=instruction_id,
        invocation_id=invocation_id,
        task_id=task_id,
        payload={"error": error},
        store=store,
    ))
    records.append(_invocation_recorded(store, task_id))
    records.append(_task_cancelled(store, task_id))

    # Cancel pending tasks that are NOT in-flight and NOT terminal
    # (in-flight siblings get their own FAILED + cancel below).
    for pending_idx in range(idx + 1, len(plan)):
        if pending_idx in statement_to_task and (
            pending_idx not in in_flight and pending_idx not in terminal
        ):
            records.append(_task_cancelled(store, statement_to_task[pending_idx]))

    # Mark in-flight siblings FAILED so the audit invariant holds.
    for inflight_idx in sorted(in_flight):
        if inflight_idx == idx:
            continue
        inflight_entry = plan[inflight_idx]
        inflight_instruction = (
            inflight_entry.call.protocol
            if inflight_entry.call is not None
            else inflight_entry.invocation.step_id
        )
        inflight_task = statement_to_task.get(inflight_idx)
        if inflight_task is None:
            continue
        inflight_invocation = f"inv-{inflight_idx + 1}"
        records.append(_Record(
            event_type=EventType.FAILED,
            instruction_id=inflight_instruction,
            invocation_id=inflight_invocation,
            task_id=inflight_task,
            payload={"error": f"cancelled: {error}"},
            store=store,
        ))
        records.append(_invocation_recorded(store, inflight_task))
        records.append(_task_cancelled(store, inflight_task))

    records.append(_run_finished_failed(store, error))
    return records


def fail_run(
    store: Any,
    run_id: str,
    plan: list["_PlanEntry"],
    statement_to_task: dict[int, str],
    from_idx: int,
    error: str,
) -> list[_Record]:
    """Build the failure batch for a run without an owning invocation (issue #3).

    A condition referencing a retired node cannot be tied to an invocation
    task, so the batch is reduced: cancel pending tasks + RUN_FINISHED.
    """
    records = cancel_pending(store, statement_to_task, from_idx, len(plan))
    records.append(_run_finished_failed(store, error))
    return records


def fail_global_deadline_sequential(
    store: Any,
    run_id: str,
    plan: list["_PlanEntry"],
    statement_to_task: dict[int, str],
    from_idx: int,
) -> list[_Record]:
    """Build the failure batch for a global-budget-deadline expiration (seq).

    The invocation that was about to dispatch carries FAILED + invocation_recorded
    + task_cancelled, every unreached task is cancelled, RUN_FINISHED records
    "global deadline exceeded".
    """
    entry = plan[from_idx]
    instruction_id = (
        entry.call.protocol
        if entry.call is not None
        else (entry.invocation.step_id if entry.invocation else "")
    )
    task_id = statement_to_task.get(from_idx)
    records: list[_Record] = []
    if task_id is not None:
        records.append(_Record(
            event_type=EventType.FAILED,
            instruction_id=instruction_id,
            invocation_id=f"inv-{from_idx + 1}",
            task_id=task_id,
            payload={"error": "global deadline exceeded"},
            store=store,
        ))
        records.append(_invocation_recorded(store, task_id))
        records.append(_task_cancelled(store, task_id))
    records.extend(cancel_pending(store, statement_to_task, from_idx + 1, len(plan)))
    records.append(_run_finished_failed(store, "global deadline exceeded"))
    return records


def fail_global_deadline_concurrent(
    store: Any,
    run_id: str,
    plan: list["_PlanEntry"],
    statement_to_task: dict[int, str],
    in_flight: dict[int, Any],
    terminal: set[int],
    trigger_idx: int | None = None,
    reason: str = "global deadline exceeded",
) -> list[_Record]:
    """Build the concurrent-variant global-deadline failure batch.

    In-flight invocations are marked FAILED with "cancelled: <reason>",
    the trigger invocation (if not in-flight/terminal) carries the plain
    reason, remaining tasks are cancelled, RUN_FINISHED records the failure.
    """
    records: list[_Record] = []

    def fail_one(idx: int, error: str) -> None:
        entry = plan[idx]
        instruction_id = (
            entry.call.protocol
            if entry.call is not None
            else entry.invocation.step_id
        )
        task_id = statement_to_task[idx]
        records.append(_Record(
            event_type=EventType.FAILED,
            instruction_id=instruction_id,
            invocation_id=f"inv-{idx + 1}",
            task_id=task_id,
            payload={"error": error},
            store=store,
        ))
        records.append(_invocation_recorded(store, task_id))
        records.append(_task_cancelled(store, task_id))

    if (
        trigger_idx is not None
        and trigger_idx not in terminal
        and trigger_idx not in in_flight
        and trigger_idx in statement_to_task
    ):
        fail_one(trigger_idx, reason)
    for idx in list(in_flight):
        fail_one(idx, f"cancelled: {reason}")
    for pending_idx in range(len(plan)):
        if (
            pending_idx not in terminal
            and pending_idx not in in_flight
            and pending_idx != trigger_idx
            and pending_idx in statement_to_task
        ):
            records.append(_task_cancelled(store, statement_to_task[pending_idx]))
    records.append(_run_finished_failed(store, reason))
    return records


def fail_run_from_exception(
    store: Any,
    run_id: str,
    plan: list["_PlanEntry"],
    statement_to_task: dict[int, str],
    error: str,
) -> list[_Record]:
    """Build the failure batch for an unhandled driver exception (issue #31).

    Every dispatched-but-not-yet-terminal invocation is marked FAILED,
    all unsettled tasks are cancelled, and RUN_FINISHED(failed) is appended.
    """
    events = store.events(run_id)
    dispatched_invocations: set[str] = set()
    terminal_invocations: set[str] = set()
    validated_invocations: set[str] = set()
    for event in events:
        if event.event_type is EventType.INVOCATION_DISPATCHED and event.invocation_id:
            dispatched_invocations.add(event.invocation_id)
        if event.event_type is EventType.SUCCEEDED and event.invocation_id:
            terminal_invocations.add(event.invocation_id)
        if event.event_type is EventType.FAILED and event.invocation_id:
            terminal_invocations.add(event.invocation_id)
        if event.event_type is EventType.VALIDATION_PASSED and event.invocation_id:
            validated_invocations.add(event.invocation_id)
    import re
    inflight = dispatched_invocations - terminal_invocations
    inflight = inflight - validated_invocations

    records: list[_Record] = []
    for invocation_id in sorted(inflight):
        idx_match = re.fullmatch(r"inv-(\d+)", invocation_id)
        if idx_match is None:
            continue
        idx = int(idx_match.group(1)) - 1
        task_id = statement_to_task.get(idx)
        if task_id is None:
            continue
        instruction_id = ""
        if 0 <= idx < len(plan):
            entry = plan[idx]
            instruction_id = (
                entry.call.protocol
                if entry.call is not None
                else (entry.invocation.step_id if entry.invocation else "")
            )
        records.append(_Record(
            event_type=EventType.FAILED,
            instruction_id=instruction_id,
            invocation_id=invocation_id,
            task_id=task_id,
            payload={"error": f"cancelled: {error}"},
            store=store,
        ))
        records.append(_invocation_recorded(store, task_id))
        records.append(_task_cancelled(store, task_id))

    for pending_idx in range(len(plan)):
        if pending_idx in statement_to_task:
            inv_id = f"inv-{pending_idx + 1}"
            if inv_id in terminal_invocations or inv_id in inflight:
                continue
            records.append(_task_cancelled(store, statement_to_task[pending_idx]))

    records.append(_run_finished_failed(store, error))
    return records


def cancel_task_if_unsettled(
    store: Any,
    run_id: str,
    task_id: str,
    records: list[_Record],
    reason: str | None = None,
) -> None:
    """Queue a task_cancelled record when the task is not yet terminal."""
    ledger = store.task_ledger(run_id)
    task = ledger.tasks.get(task_id)
    if task is None or task.status in (
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
    ):
        return
    payload: dict[str, Any] = {"kind": "task_cancelled", "id": task_id}
    if reason:
        payload["reason"] = reason
    records.append(_Record(
        event_type=EventType.TASK_UPDATED,
        task_id=task_id,
        payload=payload,
        store=store,
    ))
