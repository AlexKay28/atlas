"""Event-sourced task ledger for the tikhon runtime."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskLedgerError(Exception):
    pass


@dataclass(frozen=True)
class Task:
    id: str
    text: str
    status: TaskStatus
    priority: int
    parent: Optional[str]
    dependencies: tuple[str, ...]
    creator: str
    revision: int
    evidence: tuple[str, ...]


_METRIC_ZERO: dict[str, Any] = {
    "attempts": 0,
    "retries": 0,
    "tokens": 0,
    "cost": 0.0,
    "elapsed_seconds": 0.0,
}


class TaskLedger:
    """Event-sourced task ledger.

    Issue #21: ``allow_concurrent`` deliberately relaxes the strict
    single-IN_PROGRESS invariant for runs executing a concurrent
    frontier — multiple tasks of one run may be IN_PROGRESS at once.
    The default stays strict so sequential runs and replay of
    sequential runs are unchanged; concurrent runs reconstruct their
    multi-IN_PROGRESS intermediate states by replaying with the flag
    set (the flag rides on the run, see ``EventStore.task_ledger``).
    """

    def __init__(self, *, allow_concurrent: bool = False) -> None:
        self._allow_concurrent = bool(allow_concurrent)
        self._events: list[dict[str, Any]] = []
        self._tasks: dict[str, Task] = {}
        self._metrics: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_events(
        cls,
        events: Iterable[Mapping[str, Any]],
        *,
        allow_concurrent: bool = False,
    ) -> "TaskLedger":
        ledger = cls(allow_concurrent=allow_concurrent)
        for event in events:
            ledger._commit(dict(event))
        return ledger

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(e) for e in self._events)

    @property
    def tasks(self) -> dict[str, Task]:
        return dict(self._tasks)

    def create_task(
        self,
        text: str,
        creator: str = "user",
        priority: int = 0,
        parent: Optional[str] = None,
        dependencies: Sequence[str] = (),
    ) -> Task:
        if not isinstance(text, str) or not text.strip():
            raise TaskLedgerError("task text must be a nonempty string")
        deps = tuple(dependencies)
        for dep in deps:
            if dep not in self._tasks:
                raise TaskLedgerError(f"unknown dependency: {dep}")
        if parent is not None and parent not in self._tasks:
            raise TaskLedgerError(f"unknown parent task: {parent}")
        return self._commit(
            {
                "kind": "task_created",
                "id": f"task-{len(self._tasks) + 1}",
                "text": text,
                "priority": int(priority),
                "parent": parent,
                "dependencies": deps,
                "creator": creator,
            }
        )

    def revise_task(
        self,
        task_id: str,
        text: Optional[str] = None,
        priority: Optional[int] = None,
    ) -> Task:
        self._require(task_id)
        if text is None and priority is None:
            raise TaskLedgerError("revise_task requires text or priority")
        if text is not None and (not isinstance(text, str) or not text.strip()):
            raise TaskLedgerError("task text must be a nonempty string")
        event: dict[str, Any] = {"kind": "task_revised", "id": task_id}
        if text is not None:
            event["text"] = text
        if priority is not None:
            event["priority"] = int(priority)
        return self._commit(event)

    def reorder(self, ordered_ids: Sequence[str]) -> list[Task]:
        order = tuple(ordered_ids)
        seen: set[str] = set()
        for task_id in order:
            if task_id not in self._tasks:
                raise TaskLedgerError(f"unknown task: {task_id}")
            if task_id in seen:
                raise TaskLedgerError(f"duplicate task in reorder: {task_id}")
            seen.add(task_id)
        return self._commit({"kind": "task_reordered", "order": order})

    def split_task(self, parent_id: str, texts: Sequence[str]) -> list[Task]:
        self._require(parent_id)
        items = list(texts)
        if not items:
            raise TaskLedgerError("split_task requires at least one child text")
        for text in items:
            if not isinstance(text, str) or not text.strip():
                raise TaskLedgerError("child task text must be a nonempty string")
        return [self.create_task(text=text, parent=parent_id) for text in items]

    def start_task(self, task_id: str) -> Task:
        task = self._require(task_id)
        if task.status is not TaskStatus.PENDING:
            raise TaskLedgerError(
                f"cannot start task {task_id} in status {task.status.value}"
            )
        in_progress = [
            other.id
            for other in self._tasks.values()
            if other.status is TaskStatus.IN_PROGRESS
        ]
        if in_progress and not self._allow_concurrent:
            raise TaskLedgerError(f"task {in_progress[0]} is already in progress")
        incomplete = [
            dep
            for dep in task.dependencies
            if self._tasks[dep].status is not TaskStatus.COMPLETED
        ]
        if incomplete:
            raise TaskLedgerError(
                f"dependencies not completed for {task_id}: {', '.join(incomplete)}"
            )
        return self._commit({"kind": "task_started", "id": task_id})

    def complete_task(self, task_id: str, evidence: str) -> Task:
        task = self._require(task_id)
        if task.status is not TaskStatus.IN_PROGRESS:
            raise TaskLedgerError(
                f"cannot complete task {task_id} in status {task.status.value}"
            )
        if not isinstance(evidence, str) or not evidence.strip():
            raise TaskLedgerError("completion requires nonempty evidence")
        return self._commit(
            {"kind": "task_completed", "id": task_id, "evidence": evidence}
        )

    def cancel_task(self, task_id: str) -> Task:
        task = self._require(task_id)
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            raise TaskLedgerError(
                f"cannot cancel task {task_id} in status {task.status.value}"
            )
        return self._commit({"kind": "task_cancelled", "id": task_id})

    def record_invocation(
        self,
        task_id: str,
        tokens: int = 0,
        cost: float = 0.0,
        retries: int = 0,
        elapsed_seconds: float = 0.0,
    ) -> dict[str, Any]:
        self._require(task_id)
        return self._commit(
            {
                "kind": "invocation_recorded",
                "id": task_id,
                "tokens": int(tokens),
                "cost": float(cost),
                "retries": int(retries),
                "elapsed_seconds": float(elapsed_seconds),
            }
        )

    def profile(self) -> dict[str, Any]:
        counts = {status.value: 0 for status in TaskStatus}
        for task in self._tasks.values():
            counts[task.status.value] += 1
        total = len(self._tasks)
        completed = counts[TaskStatus.COMPLETED.value]
        current = next(
            (
                task.id
                for task in self._tasks.values()
                if task.status is TaskStatus.IN_PROGRESS
            ),
            None,
        )
        return {
            "counts": {
                "total": total,
                "pending": counts[TaskStatus.PENDING.value],
                "in_progress": counts[TaskStatus.IN_PROGRESS.value],
                "completed": completed,
                "cancelled": counts[TaskStatus.CANCELLED.value],
            },
            "percent_complete": (completed / total * 100.0) if total else 0.0,
            "current_task": current,
            "tasks": {
                task_id: dict(metrics)
                for task_id, metrics in self._metrics.items()
            },
        }

    def _require(self, task_id: str) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError:
            raise TaskLedgerError(f"unknown task: {task_id}") from None

    def _replace_task(self, task_id: str, **changes: Any) -> Task:
        try:
            old = self._tasks[task_id]
        except KeyError:
            raise TaskLedgerError(f"unknown task: {task_id}") from None
        new = replace(old, revision=old.revision + 1, **changes)
        self._tasks[task_id] = new
        return new

    def _commit(self, event: dict[str, Any]) -> Any:
        self._events.append(dict(event))
        return self._apply(dict(event))

    def _apply(self, event: Mapping[str, Any]) -> Any:
        kind = event["kind"]
        if kind == "task_created":
            task_id = event["id"]
            if task_id in self._tasks:
                raise TaskLedgerError(f"duplicate task id: {task_id}")
            task = Task(
                id=task_id,
                text=event["text"],
                status=TaskStatus.PENDING,
                priority=event["priority"],
                parent=event.get("parent"),
                dependencies=tuple(event.get("dependencies", ())),
                creator=event.get("creator", "user"),
                revision=1,
                evidence=(),
            )
            self._tasks[task_id] = task
            self._metrics[task_id] = dict(_METRIC_ZERO)
            return task
        if kind == "task_revised":
            changes: dict[str, Any] = {}
            if "text" in event:
                changes["text"] = event["text"]
            if "priority" in event:
                changes["priority"] = event["priority"]
            return self._replace_task(event["id"], **changes)
        if kind == "task_reordered":
            order = tuple(event["order"])
            for index, task_id in enumerate(order):
                if self._tasks[task_id].priority != index:
                    self._replace_task(task_id, priority=index)
            return [self._tasks[task_id] for task_id in order]
        if kind == "task_started":
            task = self._require(event["id"])
            if task.status is not TaskStatus.PENDING:
                raise TaskLedgerError(
                    f"cannot start task {event['id']} in status {task.status.value}"
                )
            in_progress = [
                other.id
                for other in self._tasks.values()
                if other.status is TaskStatus.IN_PROGRESS
            ]
            if in_progress and not self._allow_concurrent:
                raise TaskLedgerError(f"task {in_progress[0]} is already in progress")
            incomplete = [
                dep
                for dep in task.dependencies
                if self._tasks[dep].status is not TaskStatus.COMPLETED
            ]
            if incomplete:
                raise TaskLedgerError(
                    f"dependencies not completed for {event['id']}: {', '.join(incomplete)}"
                )
            return self._replace_task(event["id"], status=TaskStatus.IN_PROGRESS)
        if kind == "task_completed":
            task = self._require(event["id"])
            if task.status is not TaskStatus.IN_PROGRESS:
                raise TaskLedgerError(
                    f"cannot complete task {event['id']} in status {task.status.value}"
                )
            if not isinstance(event.get("evidence", ""), str) or not event["evidence"].strip():
                raise TaskLedgerError("completion requires nonempty evidence")
            old = self._tasks[event["id"]]
            return self._replace_task(
                event["id"],
                status=TaskStatus.COMPLETED,
                evidence=old.evidence + (event["evidence"],),
            )
        if kind == "task_cancelled":
            task = self._require(event["id"])
            if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                raise TaskLedgerError(
                    f"cannot cancel task {event['id']} in status {task.status.value}"
                )
            return self._replace_task(event["id"], status=TaskStatus.CANCELLED)
        if kind == "invocation_recorded":
            self._require(event["id"])
            metrics = self._metrics[event["id"]]
            metrics["attempts"] += 1
            metrics["retries"] += event["retries"]
            metrics["tokens"] += event["tokens"]
            metrics["cost"] += event["cost"]
            metrics["elapsed_seconds"] += event["elapsed_seconds"]
            return dict(metrics)
        raise TaskLedgerError(f"unknown event kind: {kind}")
