"""Deterministic sequential coordinator for tikhon programs.

Implements the runtime contract from docs/spec/03-runtime-and-events.md:
sequential invocation lifecycle, durable task ledger per invocation,
deterministic state commits, and failure handling without false
completion.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from tikhon.runtime.events import EventStore, EventType, _Record
from tikhon.runtime.tasks import TaskLedger, TaskLedgerError
from tikhon.state import StateDelta
from tikhon.syntax import validate_program
from tikhon.syntax.model import Invocation, Program, Return, Stop

__all__ = ["DeterministicWorker", "SequentialCoordinator", "map_results_to_targets"]


def map_results_to_targets(
    targets: tuple[str, ...],
    result: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Map a worker result to step target references.

    Returns ``(target_values, None)`` on success or ``(None, error_msg)``
    on failure.  Single-target invocations accept any result type.
    Multi-target invocations require a mapping whose keys match either
    the full target reference or the leaf name (the last ``.``-segment),
    with duplicate leaf names resolved only by full-key match.
    """
    if len(targets) == 1:
        return {targets[0]: result}, None

    if not isinstance(result, Mapping):
        return None, (
            f"handler returned non-mapping for multiple targets"
        )

    leaves = [target.split(".")[-1] for target in targets]
    duplicate_leaves = {leaf for leaf in leaves if leaves.count(leaf) > 1}

    target_values: dict[str, Any] = {}
    missing_keys: list[str] = []
    ambiguous_keys: list[str] = []

    for target, leaf in zip(targets, leaves):
        if target in result:
            target_values[target] = result[target]
        elif leaf in result and leaf not in duplicate_leaves:
            target_values[target] = result[leaf]
        elif leaf in result:
            ambiguous_keys.append(leaf)
        else:
            missing_keys.append(target)

    errors: list[str] = []
    if ambiguous_keys:
        errors.append(
            "ambiguous result keys: " + ", ".join(sorted(set(ambiguous_keys)))
        )
    if missing_keys:
        errors.append("missing result keys: " + ", ".join(missing_keys))
    if errors:
        return None, "; ".join(errors)

    return target_values, None


class DeterministicWorker:
    """Wraps a mapping of command-name -> handler callable."""

    def __init__(self, handlers: Mapping[str, Callable[..., Any]]):
        self._handlers: dict[str, Callable[..., Any]] = dict(handlers)

    @property
    def commands(self) -> set[str]:
        return set(self._handlers)

    def execute(self, command: str, resolved_kwargs: dict[str, Any]) -> Any:
        handler = self._handlers[command]
        return handler(**resolved_kwargs)


class SequentialCoordinator:
    """Drives a tikhon program sequentially through an EventStore."""

    def __init__(self, store: EventStore, worker: DeterministicWorker):
        self.store = store
        self.worker = worker

    def execute(self, program: Program, run_id: str = "run-1") -> dict[str, Any]:
        validate_program(program, known_commands=self.worker.commands)

        program_version = f"{program.name}@{program.version}"
        self.store.create_run(run_id, program_version, metadata={"program": program.name})

        self.store.append(
            run_id,
            EventType.RUN_STARTED,
            payload={"program": program.name, "version": program.version},
        )

        values: dict[str, Any] = {}
        for decl in program.declarations:
            values[decl.ref] = decl.value

        invocations: list[Invocation] = []
        for statement in program.statements:
            if not isinstance(statement, Invocation):
                break
            invocations.append(statement)

        # -- batch all task-creation records --------------------------
        statement_to_task: dict[int, str] = {}
        create_records: list[_Record] = []
        create_ledger = self.store.task_ledger(run_id)
        for idx, statement in enumerate(invocations):
            task = create_ledger.create_task(
                text=f"{statement.step_id}: DO {statement.command}",
                creator="coordinator",
            )
            task_id = task.id
            statement_to_task[idx] = task_id

            create_records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "task_created", "id": task_id, "text": task.text,
                    "priority": task.priority, "parent": task.parent,
                    "dependencies": task.dependencies, "creator": task.creator,
                },
                store=self.store,
            ))

        if create_records:
            self.store.append_batch(run_id, create_records)

        def finish_failed_invocation(
            idx: int,
            statement: Invocation,
            invocation_id: str,
            task_id: str,
            error: str,
        ) -> None:
            records = [
                _Record(
                    event_type=EventType.FAILED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={"error": error},
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "invocation_recorded", "id": task_id,
                        "tokens": 0, "cost": 0.0, "retries": 0,
                        "elapsed_seconds": 0.0,
                    },
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={"kind": "task_cancelled", "id": task_id},
                    store=self.store,
                ),
            ]
            records.extend(
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                )
                for pending_idx in range(idx + 1, len(invocations))
            )
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": error},
                store=self.store,
            ))
            self.store.append_batch(run_id, records)

        failed = False
        error_msg: str | None = None

        for idx, statement in enumerate(invocations):
            invocation_id = f"inv-{idx + 1}"
            task_id = statement_to_task[idx]

            ledger = self.store.task_ledger(run_id)
            ledger.start_task(task_id)

            # batch: task_started + INVOCATION_READY
            self.store.append_batch(run_id, [
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={"kind": "task_started", "id": task_id},
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.INVOCATION_READY,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={"command": statement.command},
                    store=self.store,
                ),
            ])

            resolved_kwargs: dict[str, Any] = {}
            for arg in statement.args:
                if isinstance(arg.value, str) and arg.value in values:
                    resolved_kwargs[arg.name] = values[arg.value]
                else:
                    resolved_kwargs[arg.name] = arg.value

            self.store.append(
                run_id,
                EventType.INVOCATION_DISPATCHED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={"args": resolved_kwargs},
            )

            try:
                result = self.worker.execute(statement.command, resolved_kwargs)
            except Exception as exc:
                failed = True
                error_msg = str(exc)
                finish_failed_invocation(
                    idx, statement, invocation_id, task_id, error_msg
                )
                break

            self.store.append(
                run_id,
                EventType.RESULT_RECEIVED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={"result": result},
            )

            target_values, validation_error = map_results_to_targets(
                statement.targets, result
            )

            if validation_error is not None:
                if validation_error == "handler returned non-mapping for multiple targets":
                    validation_error = (
                        f"handler {statement.command} returned non-mapping"
                        " for multiple targets"
                    )
                failed = True
                error_msg = validation_error
                finish_failed_invocation(
                    idx, statement, invocation_id, task_id, validation_error
                )
                break

            self.store.append(
                run_id,
                EventType.VALIDATION_PASSED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={},
            )

            add_nodes: list[dict[str, Any]] = []
            for target, val in target_values.items():
                values[target] = val
                add_nodes.append({"id": target, "value": val})

            delta = StateDelta(add_nodes=tuple(add_nodes))

            expected_sv = self.store._current_state_version(run_id)

            # batch: SUCCEEDED + invocation_recorded + task_completed
            self.store.append_batch(run_id, [
                _Record(
                    event_type=EventType.SUCCEEDED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    expected_state_version=expected_sv,
                    payload={"delta": delta},
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "invocation_recorded", "id": task_id,
                        "tokens": 0, "cost": 0.0, "retries": 0,
                        "elapsed_seconds": 0.0,
                    },
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "task_completed", "id": task_id,
                        "evidence": f"{statement.command} -> {statement.targets}",
                    },
                    store=self.store,
                ),
            ])

        outputs: dict[str, Any] = {}
        if not failed:
            for statement in program.statements:
                if isinstance(statement, Return):
                    for ref in statement.refs:
                        outputs[ref] = values.get(ref)
                    break
                if isinstance(statement, Stop):
                    if statement.kind == "completed":
                        run_status = "succeeded"
                    else:
                        run_status = statement.kind
                    reason = values.get(statement.ref) if statement.ref else None
                    finished_payload: dict[str, Any] = {"status": run_status}
                    if reason is not None:
                        finished_payload["reason"] = reason
                    self.store.append(
                        run_id,
                        EventType.RUN_FINISHED,
                        payload=finished_payload,
                    )
                    return {"run_id": run_id, "status": run_status, "outputs": outputs}

        if failed:
            return {"run_id": run_id, "status": "failed", "error": error_msg or "", "outputs": {}}

        self.store.append(
            run_id,
            EventType.RUN_FINISHED,
            payload={"status": "succeeded"},
        )
        return {"run_id": run_id, "status": "succeeded", "outputs": outputs}
