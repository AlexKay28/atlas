"""Deterministic sequential coordinator for TAHOE programs.

Implements the runtime contract from docs/spec/03-runtime-and-events.md:
sequential invocation lifecycle, durable task ledger per invocation,
deterministic state commits, and failure handling without false
completion.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import hashlib
import os
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from tahoe.budgets import BudgetDeadlineExceeded, BudgetGate, ExecutionBudget
from tahoe.claims import ResourceLedger
from tahoe.runtime.events import (
    EventStore,
    EventType,
    _Record,
    canonical_json as _canonical_event_json,
)
from tahoe.runtime import finalize as _finalize
from tahoe.runtime import planning as _planning
from tahoe.runtime.children import ChildEngine
from tahoe.runtime.par import ParEngine
from tahoe.runtime.scatter import ScatterEngine
from tahoe.runtime.delegate import DelegateEngine
from tahoe.runtime.driver import DriveEngine
from tahoe.runtime.tasks import TaskLedger, TaskLedgerError, TaskStatus
from tahoe.state import StateDelta
from tahoe.syntax import (
    ParseError,
    is_typed_reference,
    load_protocol,
    parse_condition,
    parse_program,
    validate_program,
)
from tahoe.syntax.model import (
    Argument,
    Call,
    Conditional,
    Declaration,
    Gather,
    Invocation,
    Loop,
    Par,
    ParBranch,
    Program,
    Return,
    Scatter,
    Stop,
    Try,
)

if TYPE_CHECKING:
    from tahoe.memory import KnowledgeBase
    from tahoe.syntax.model import DonePredicate

__all__ = [
    "CrashInterrupt",
    "DeterministicWorker",
    "SequentialCoordinator",
    "evaluate_condition",
    "evaluate_done_predicate",
    "judge_score",
    "map_results_to_targets",
]


class CrashInterrupt(Exception):
    """Raised by a ``crash_hook`` to abort ``execute`` mid-run (issue #10).

    The hook site lives outside every ``try``/``except`` in the
    coordinator, so this exception propagates out of ``execute`` uncaught
    and the run keeps exactly its committed event prefix — a true crash
    window, not a failed run (no FAILED, no RUN_FINISHED).
    """


def _monotonic() -> float:
    """Monotonic clock for budget deadlines (issue #22)."""
    return time.monotonic()


# Issue #4: per-candidate invocation ids hang off their scatter entry's
# positional id ("inv-<K>" -> "inv-<K>.cand<k>", 1-based k), keeping every
# candidate invocation distinct from the plan's positional ids while staying
# derivable from the plan alone (resume reconstructs scatter progress from
# these ids).
from tahoe.runtime.helpers import (  # noqa: E402,F401
    _CANDIDATE_INVOCATION_RE,
    _PAR_INVOCATION_RE,
)

_PlanEntry = _planning.PlanEntry

# Re-export helpers moved to engine modules (backward compatibility).
from tahoe.runtime.par import (  # noqa: E402,F401
    branch_workspace_dir,
    par_branch_invocation_id,
    par_branch_run_id,
    par_branch_summary,
    par_branch_task_text,
)
from tahoe.runtime.scatter import (  # noqa: E402,F401
    candidate_invocation_id,
    candidate_node_id,
    candidate_task_text,
    judge_score,
)
from tahoe.runtime.delegate import (  # noqa: E402,F401
    DELEGATE_COMMAND,
    DELEGATE_DEFAULT_MAX_STEPS,
    DELEGATE_HARD_MAX_STEPS,
    DELEGATE_PROTOCOL_DEPTH_LIMIT,
    count_plan_steps,
    delegate_plan_digest,
    delegate_plan_name,
)


from tahoe.runtime.helpers import (  # noqa: E402,F401
    _BUILTIN_REGISTRY_DIGEST,
    _builtin_registry_digest,
    _EFFECTFUL_COMMANDS,
    _effectful_commands,
    _COMMAND_MAX_ATTEMPTS,
    _command_max_attempts,
    _uses_kb_refs,
    _uses_scatter,
    _uses_par,
    _uses_delegate,
    _uses_loop,
    _uses_try,
    _uses_reformulate,
    _invocation_uses_kb_refs,
    _json_equal,
    evaluate_done_predicate,
    evaluate_condition,
    _eval_condition_node,
    _condition_operand,
    _compare,
)

map_results_to_targets = _planning.map_results_to_targets

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


class SequentialCoordinator(ChildEngine, ParEngine, ScatterEngine, DelegateEngine, DriveEngine):
    """Drives an TAHOE program sequentially through an EventStore.

    ``workspace_root`` is the WorkspacePolicy hook (issue #9): when set,
    every dispatch of an effectful command (durable-write class per the
    builtin registry, e.g. ``edit``) injects a resolved ``_workspace_root``
    kwarg so handlers can sandbox their writes; when ``None``, effectful
    commands still dispatch but no root is provided and handlers decide
    whether that is acceptable.
    """

    def __init__(
        self,
        store: EventStore,
        worker: DeterministicWorker,
        memory: "KnowledgeBase | None" = None,
        workspace_root: str | None = None,
        protocols_dir: str | Path | None = None,
    ):
        self.store = store
        self.worker = worker
        self.memory = memory
        self.workspace_root = workspace_root
        # Issue #12: directory holding sealed protocol files.  ``None``
        # means the default ``protocols/`` under the current working
        # directory (resolved lazily, only when a program CALLs a protocol).
        self.protocols_dir = protocols_dir

    def _resolve_kb_ref(self, ref: str) -> Any:
        """Resolve a ``KB.<name>`` reference from the knowledge base."""
        if self.memory is None:
            raise ValueError(
                f"KB reference {ref} requires a knowledge base:"
                " construct SequentialCoordinator with"
                " memory=KnowledgeBase(path)"
            )
        key = "kb." + ref.split(".", 1)[1]
        if key not in self.memory:
            raise ValueError(f"KB key {key!r} not found (reference {ref})")
        return self.memory.get(key)

    @staticmethod
    def _reject_unresolved_refs(value: Any, values: Mapping[str, Any]) -> None:
        """Fail ref-shaped arguments that no longer resolve (issue #7).

        Validation guarantees every ref inside an argument resolves at
        dispatch time — except refs retired by an earlier step's RETIRE
        clause.  Passing such a ref through as a literal would silently
        feed the raw ref string to the worker, so the invocation must
        fail clearly instead.  Purely additive: before retirement existed
        this guard was unreachable for validated programs, so it cannot
        change the behavior of any pre-#7 program.
        """
        if isinstance(value, str):
            if (
                value not in values
                and not value.startswith("KB.")
                and is_typed_reference(value)
            ):
                raise ValueError(
                    f"reference {value} is not in run state (retired or"
                    " undefined); retired nodes cannot be read by later"
                    " steps"
                )
        elif isinstance(value, list):
            for item in value:
                SequentialCoordinator._reject_unresolved_refs(item, values)

    def _resolve_arg_value(self, value: Any, values: Mapping[str, Any]) -> Any:
        """Resolve one raw argument value against run state (issue #12).

        Same resolution rules as invocation arguments: a bare typed ref
        resolves from ``values``, a ``KB.*`` ref from the knowledge base,
        reference lists resolve item-wise, literals pass through.
        """
        if isinstance(value, str) and value in values:
            return values[value]
        if isinstance(value, str) and value.startswith("KB."):
            return self._resolve_kb_ref(value)
        if isinstance(value, list):
            return [
                values[item] if isinstance(item, str) and item in values
                else self._resolve_kb_ref(item)
                if isinstance(item, str) and item.startswith("KB.")
                else item
                for item in value
            ]
        return value

    def _resolve_call_arguments(
        self,
        call: Call,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Resolve a CALL's arguments against the caller's run state (issue #20).

        Returns a ``protocol INPUT leaf name -> resolved value`` mapping:
        each argument is guarded by :meth:`_reject_unresolved_refs` and
        resolved like an invocation argument (bare ref from ``values``,
        ``KB.*`` from the knowledge base, reference lists item-wise,
        literals pass through).  Validation guarantees the argument names
        exactly cover the protocol's INPUT leaf names.
        """
        resolved: dict[str, Any] = {}
        for arg in call.args:
            self._reject_unresolved_refs(arg.value, values)
            resolved[arg.name] = self._resolve_arg_value(arg.value, values)
        return resolved


    def _build_plan(self, program: Program) -> list[_PlanEntry]:
        """Flatten the program into an execution plan."""
        return _planning.build_plan(program)

    def _create_plan_tasks(
        self, run_id: str, plan: list[_PlanEntry]
    ) -> dict[int, str]:
        """Batch-create one ledger task per plan entry (crash window W0b).

        Returns the ``plan index -> task_id`` mapping.  Kept separate from
        :meth:`_drive_plan` so resume (issue #10) can recreate tasks
        missing after a crash before the creation batch (W0a) and reuse
        the identical mapping rule (creation order == plan order).
        """
        statement_to_task: dict[int, str] = {}
        create_records: list[_Record] = []
        create_ledger = self.store.task_ledger(run_id)
        for idx, entry in enumerate(plan):
            if entry.condition is not None:
                # Issue #3: conditional entries are not part of the up-front
                # creation batch — a false branch performs no work, so its
                # ledger task exists only when the condition fires (created
                # lazily in _drive_plan).
                continue
            if entry.par is not None:
                # Issue #24: a PAR block creates no task of its own — the
                # ledger carries one task per branch, created when the
                # entry executes (_par_branch_task_ids).
                continue
            if entry.loop is not None:
                # Issue #68: a LOOP block creates no task of its own —
                # body iteration tasks are created lazily during
                # execution.
                continue
            if entry.try_ is not None:
                # Issue #69: a TRY block creates no task of its own —
                # branch tasks are created lazily during execution.
                continue
            if entry.reformulate is not None:
                # Issue #80: a REFORMULATE block creates no task of its
                # own — diagnose/replan sub-tasks are created lazily
                # during execution.
                continue
            if entry.first is not None:
                # Issue #76: a FIRST block creates no task of its own —
                # event-choice execution is not yet implemented.
                continue
            if entry.await_ is not None:
                # Issue #77: an AWAIT statement creates no task —
                # suspension/resume is handled through the event system.
                continue
            if entry.approve is not None:
                # Issue #78: an APPROVE statement creates no task —
                # the approval gate is handled through the event system.
                continue
            task = create_ledger.create_task(
                text=self._task_text(entry),
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
        return statement_to_task

    def _task_text(self, entry: _PlanEntry) -> str:
        """The canonical ledger task text for one plan entry."""
        return _planning.task_text(entry)

    def _collect_anchors(self, program: Program) -> dict[int, list]:
        """Map plan index -> STOP/RETURN conditionals at that source anchor."""
        return _planning.collect_anchors(program)

    def _create_single_plan_task(self, run_id: str, entry: _PlanEntry) -> str:
        """Create one ledger task for a lazily reached conditional entry.

        The task text and creation record mirror ``_create_plan_tasks``
        exactly, so a fired conditional step is indistinguishable in the
        ledger from an unconditional one (issue #3).
        """
        statement = entry.invocation
        ledger = self.store.task_ledger(run_id)
        task = ledger.create_task(
            text=self._task_text(entry),
            creator="coordinator",
        )
        self.store.append(
            run_id,
            EventType.TASK_UPDATED,
            task_id=task.id,
            payload={
                "kind": "task_created", "id": task.id, "text": task.text,
                "priority": task.priority, "parent": task.parent,
                "dependencies": task.dependencies, "creator": task.creator,
            },
        )
        return task.id

    def _cancel_pending_after(
        self,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        from_idx: int,
    ) -> None:
        """Cancel every created-but-unreached plan task from ``from_idx``.

        Fired conditional STOP/RETURN terminals leave later invocations
        unreached; their batch-created tasks are cancelled exactly like the
        failure path.  Conditional tasks are created lazily, so absent
        mappings are skipped — no task exists for work that never started.
        """
        records = [
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=statement_to_task[pending_idx],
                payload={
                    "kind": "task_cancelled",
                    "id": statement_to_task[pending_idx],
                },
                store=self.store,
            )
            for pending_idx in range(from_idx, len(plan))
            if pending_idx in statement_to_task
        ]
        if records:
            self.store.append_batch(run_id, records)

    def _terminal_return(
        self, run_id: str, refs: tuple[str, ...], values: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Finish a run through a RETURN terminal (bare or conditional)."""
        outputs: dict[str, Any] = {ref: values.get(ref) for ref in refs}
        self.store.append(
            run_id,
            EventType.RUN_FINISHED,
            payload={"status": "succeeded"},
        )
        return {"run_id": run_id, "status": "succeeded", "outputs": outputs}

    def _terminal_stop(
        self, run_id: str, stop: Stop, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Finish a run through a STOP terminal (bare or conditional).

        ``completed`` maps to a succeeded run; every other kind is recorded
        verbatim, with the referenced node's value as the reason payload
        when the ref resolves.
        """
        if stop.kind == "completed":
            run_status = "succeeded"
        else:
            run_status = stop.kind
        reason = values.get(stop.ref) if stop.ref else None
        finished_payload: dict[str, Any] = {"status": run_status}
        if reason is not None:
            finished_payload["reason"] = reason
        self.store.append(
            run_id,
            EventType.RUN_FINISHED,
            payload=finished_payload,
        )
        return {"run_id": run_id, "status": run_status, "outputs": {}}

    def _fail_run(
        self,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        from_idx: int,
        error: str,
    ) -> dict[str, Any]:
        """Fail a run without an owning invocation (issue #3)."""
        records = _finalize.fail_run(
            self.store, run_id, plan, statement_to_task, from_idx, error,
        )
        self.store.append_batch(run_id, records)
        return {"run_id": run_id, "status": "failed", "error": error, "outputs": {}}

    def _fail_run_from_exception(
        self,
        run_id: str,
        plan: list["_PlanEntry"],
        statement_to_task: dict[int, str],
        error: str,
    ) -> None:
        """Centralized failure batch for an unhandled driver exception (issue #31)."""
        records = _finalize.fail_run_from_exception(
            self.store, run_id, plan, statement_to_task, error,
        )
        try:
            self.store.append_batch(run_id, records)
        except Exception:
            pass

    def _run_conditionals(
        self,
        run_id: str,
        conditionals: list,
        values: dict[str, Any],
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        cancel_from_idx: int,
    ) -> dict[str, Any] | None:
        """Evaluate source-anchored STOP/RETURN conditionals in order.

        A false condition skips the embedded statement and execution
        continues; a fired STOP/RETURN cancels the unreached plan tasks and
        finishes the run through the existing terminal handling.  Returns
        the terminal result dict, or ``None`` when no conditional fired.
        Conditional DO invocations never appear here — they are plan
        entries evaluated inside the loop itself.

        Issue #83: ``_ElseAnchor`` entries are evaluated with inverted
        logic — the else-branch terminal fires when the condition is FALSE.
        """
        from tahoe.runtime.planning import _ElseAnchor, _IfExtraAnchor
        for conditional in conditionals:
            if isinstance(conditional, _IfExtraAnchor):
                try:
                    fired = evaluate_condition(
                        conditional.conditional.condition, values
                    )
                except ValueError as exc:
                    return self._fail_run(
                        run_id, plan, statement_to_task, cancel_from_idx, str(exc)
                    )
                if not fired:
                    continue
                embedded = conditional.statement
                self._cancel_pending_after(
                    run_id, plan, statement_to_task, cancel_from_idx
                )
                if isinstance(embedded, Stop):
                    return self._terminal_stop(run_id, embedded, values)
                if isinstance(embedded, Return):
                    return self._terminal_return(run_id, embedded.refs, values)
                continue
            if isinstance(conditional, _ElseAnchor):
                try:
                    fired = not evaluate_condition(
                        conditional.conditional.condition, values
                    )
                except ValueError as exc:
                    return self._fail_run(
                        run_id, plan, statement_to_task, cancel_from_idx, str(exc)
                    )
                if not fired:
                    continue
                embedded = conditional.statement
                self._cancel_pending_after(
                    run_id, plan, statement_to_task, cancel_from_idx
                )
                if isinstance(embedded, Stop):
                    return self._terminal_stop(run_id, embedded, values)
                if isinstance(embedded, Return):
                    return self._terminal_return(run_id, embedded.refs, values)
                continue
            try:
                fired = evaluate_condition(conditional.condition, values)
            except ValueError as exc:
                return self._fail_run(
                    run_id, plan, statement_to_task, cancel_from_idx, str(exc)
                )
            if not fired:
                continue
            embedded = conditional.statement
            self._cancel_pending_after(
                run_id, plan, statement_to_task, cancel_from_idx
            )
            if isinstance(embedded, Stop):
                return self._terminal_stop(run_id, embedded, values)
            if isinstance(embedded, Return):
                return self._terminal_return(run_id, embedded.refs, values)
        return None

    def _cancel_task_if_unsettled(
        self, run_id: str, task_id: str, records: list[_Record], reason: str | None = None
    ) -> None:
        """Queue a task_cancelled record when the task is not yet terminal."""
        _finalize.cancel_task_if_unsettled(
            self.store, run_id, task_id, records, reason,
        )

    def execute(
        self,
        program: Program,
        run_id: str = "run-1",
        *,
        crash_hook: "Callable[[int], None] | None" = None,
        max_workers: int = 1,
        budget: "ExecutionBudget | None" = None,
    ) -> dict[str, Any]:
        """Execute one program run.

        ``max_workers`` (issue #21) selects the execution strategy: the
        default ``1`` keeps the historical blocking sequential loop
        untouched; any value ``> 1`` dispatches dependency-free ready
        invocations concurrently on a thread pool of that size while
        every commit stays on the single-writer atomic batch path (see
        :meth:`_drive_plan_concurrent`).  CALL child runs always execute
        their own plans sequentially.

        ``budget`` (issue #22) installs an :class:`ExecutionBudget`
        shared across the run's whole execution tree: it caps active
        workers and child step executions (one semaphore), enforces a
        global and per-invocation deadline, and caps child-run nesting
        depth.  A budget only caps — it never enables concurrency on
        its own — and ``None`` (the default) keeps the historical
        behavior unchanged.
        """
        if not isinstance(max_workers, int) or isinstance(max_workers, bool):
            raise ValueError(
                f"max_workers must be an integer, got {max_workers!r}"
            )
        if max_workers < 1:
            raise ValueError(
                f"max_workers must be >= 1, got {max_workers}"
            )
        if budget is not None and not isinstance(budget, ExecutionBudget):
            raise TypeError(
                f"budget must be an ExecutionBudget or None,"
                f" got {type(budget).__name__}"
            )
        gate = BudgetGate(budget) if budget is not None else None
        # Issue #23: one run-scoped resource ledger shared across the
        # run's whole execution tree (branch workspace claims, merge
        # claims).
        claims = ResourceLedger()
        return self._execute_program(
            program,
            run_id,
            crash_hook=crash_hook,
            max_workers=max_workers,
            gate=gate,
            claims=claims,
        )

    def _execute_program(
        self,
        program: Program,
        run_id: str,
        *,
        crash_hook: "Callable[[int], None] | None" = None,
        child_of: str | None = None,
        call_name: str | None = None,
        initial_values: Mapping[str, Any] | None = None,
        max_workers: int = 1,
        gate: "BudgetGate | None" = None,
        claims: "ResourceLedger | None" = None,
        branch_workspace: str | None = None,
        branch_claim: str | None = None,
    ) -> dict[str, Any]:
        """Start and drive one run (issue #20 parameterized start).

        ``execute`` is the top-level entry point.  A CALL's child run
        reuses this same machinery with ``child_of``/``call_name`` set
        (recorded in the run's metadata and RUN_STARTED payload for
        lineage) and ``initial_values`` seeding the child's isolated
        state namespace from the resolved CALL arguments.

        Issue #21: ``max_workers > 1`` marks the run's metadata
        ``concurrent`` (the flag the task-ledger replay reads to permit
        multiple IN_PROGRESS tasks) and drives the plan through the
        concurrent frontier instead of the sequential loop.

        Issue #23: ``claims`` is the run tree's shared resource ledger
        and ``branch_workspace``/``branch_claim`` carry the enclosing
        branch's isolated workspace root and claim resource into child
        runs (a PAR branch CALLing a protocol keeps the branch sandbox).
        """
        validate_program(
            program,
            known_commands=self.worker.commands,
            protocols_dir=self.protocols_dir,
        )
        if self.memory is None and _uses_kb_refs(program):
            raise ValueError(
                "program uses KB.* references but no knowledge base was"
                " provided: construct SequentialCoordinator with"
                " memory=KnowledgeBase(path)"
            )

        program_version = f"{program.name}@{program.version}"
        registry_digest = _builtin_registry_digest()
        metadata: dict[str, Any] = {
            "program": program.name,
            "registry_digest": registry_digest,
        }
        started_payload: dict[str, Any] = {
            "program": program.name,
            "version": program.version,
            "registry_digest": registry_digest,
        }
        concurrent_run = (
            max_workers > 1
            and not _uses_scatter(program)
            and not _uses_par(program)
            and not _uses_delegate(program)
            and not _uses_loop(program)
            and not _uses_try(program)
            and not _uses_reformulate(program)
        )
        if concurrent_run:
            metadata["concurrent"] = True
            metadata["max_workers"] = max_workers
        elif max_workers > 1:
            # Issue #4: scatter programs always drive the sequential plan
            # loop (candidate fan-out semantics, loser cancellation and the
            # resume invariants are defined over candidate order); the
            # requested width is recorded but does not switch the plan
            # frontier on.  Issue #24: PAR programs likewise drive the
            # sequential plan loop — a PAR entry brings its own bounded
            # branch pool.  Issue #25: delegate programs drive the
            # sequential loop for the same reason — a delegate entry brings
            # its own authoring + child-run machinery.
            metadata["max_workers"] = max_workers
        if child_of is not None:
            metadata["child_of"] = child_of
            metadata["call"] = call_name
            started_payload["child_of"] = child_of
            started_payload["call"] = call_name
        self.store.create_run(run_id, program_version, metadata=metadata)

        self.store.append(
            run_id,
            EventType.RUN_STARTED,
            payload=started_payload,
        )

        values: dict[str, Any] = {}
        for decl in program.declarations:
            values[decl.ref] = decl.value
        if initial_values:
            values.update(initial_values)

        # Issue #20: flatten caller invocations and CALL statements into
        # one sequential plan.  Protocol steps execute in their own
        # isolated child run; a CALL entry drives the child and adopts
        # its RETURN refs (see _execute_call).
        plan: list[_PlanEntry] = self._build_plan(program)

        statement_to_task = self._create_plan_tasks(run_id, plan)

        try:
            if concurrent_run:
                return self._drive_plan_concurrent(
                    program,
                    run_id,
                    plan,
                    values,
                    statement_to_task,
                    crash_hook=crash_hook,
                    max_workers=max_workers,
                    gate=gate,
                    claims=claims,
                )

            return self._drive_plan(
                program,
                run_id,
                plan,
                values,
                statement_to_task,
                start_idx=0,
                crash_hook=crash_hook,
                gate=gate,
                claims=claims,
                branch_root=branch_workspace,
                branch_claim=branch_claim,
            )
        except (CrashInterrupt, KeyboardInterrupt):
            raise
        except Exception:
            import traceback

            tb_summary = traceback.format_exc().strip()
            error_msg = f"RUN_FINISHED failed with traceback summary:\n{tb_summary}"
            self._fail_run_from_exception(
                run_id, plan, statement_to_task, error_msg
            )
            return {
                "run_id": run_id,
                "status": "failed",
                "error": error_msg,
                "outputs": {},
            }

    def _resume_existing_run(
        self,
        program: Program,
        run_id: str,
        *,
        initial_values: Mapping[str, Any] | None = None,
        gate: "BudgetGate | None" = None,
        claims: "ResourceLedger | None" = None,
        branch_workspace: str | None = None,
        branch_claim: str | None = None,
        max_workers: int = 1,
    ) -> dict[str, Any]:
        """Continue a non-terminal run (issue #10 core, shared with #20).

        Rebuilds run state (declarations — overridden by
        ``initial_values`` for child runs' resolved CALL inputs — then
        committed SUCCEEDED deltas in seq order), verifies the
        SUCCEEDED-invocation prefix invariant, ensures the plan's tasks
        exist with the canonical texts, and drives the remaining plan
        through :meth:`_drive_plan`.  Used by ``tahoe.resume.resume_run``
        for a crashed parent and by ``_execute_call`` to re-drive a
        non-terminal child (at-least-once; the DISPATCHED idempotency key
        is the dedup contract for effectful workers).
        """
        events = self.store.events(run_id)

        values: dict[str, Any] = {}
        for decl in program.declarations:
            values[decl.ref] = decl.value
        if initial_values:
            values.update(initial_values)
        # INPUT declarations seed the mapping exactly like a fresh start;
        # committed SUCCEEDED deltas then replay in seq order (add/revise
        # write, retire pops) so the reconstruction matches the values the
        # coordinator held at the crash point — including declarations no
        # step ever targeted and refs retired by a REVISE/RETIRE correction.
        self._apply_committed_deltas(values, events)

        plan = self._build_plan(program)

        # -- find the first non-terminal step ------------------------------
        # Invocation ids are positional (inv-1..inv-N in plan order), so a
        # step is terminal exactly when its invocation id carries a
        # SUCCEEDED event.  Dispatch alone never implies success.
        # Issue #21: a concurrent run commits SUCCEEDED events in
        # completion order, so its terminal set is generally NOT a
        # prefix; such runs validate the set against the plan instead
        # and re-drive every remaining entry through the frontier.
        concurrent_run = self.store._run_allows_concurrent(run_id)
        succeeded_all = {
            event.invocation_id
            for event in events
            if event.event_type is EventType.SUCCEEDED and event.invocation_id
        }
        # Issue #4: per-candidate SUCCEEDED events carry composite ids
        # ("inv-<K>.cand<k>") hanging off their scatter entry's positional
        # id; they are validated against the plan's scatter entries and
        # excluded from the positional prefix invariant.  Issue #24: PAR
        # branch parent-side events carry "par<k>" invocation ids but no
        # SUCCEEDED events (branch adoptions commit under the PAR entry's
        # positional id), so par<k> ids are defensively excluded from the
        # positional set as well.
        candidate_success_ids: set[str] = set()
        positional_success_ids: set[str] = set()
        for invocation in succeeded_all:
            if _CANDIDATE_INVOCATION_RE.fullmatch(invocation):
                candidate_success_ids.add(invocation)
            elif _PAR_INVOCATION_RE.fullmatch(invocation):
                continue
            else:
                positional_success_ids.add(invocation)
        scatter_positions = {
            idx + 1
            for idx, entry in enumerate(plan)
            if entry.scatter is not None
        }
        for invocation in candidate_success_ids:
            match = _CANDIDATE_INVOCATION_RE.fullmatch(invocation)
            if int(match.group(1)) not in scatter_positions:
                raise ValueError(
                    f"run {run_id!r} has SUCCEEDED candidate invocation"
                    f" {invocation!r} but plan entry {match.group(1)} is"
                    " not a SCATTER block; impossible for the sequential"
                    " coordinator"
                )
        succeeded = positional_success_ids
        if concurrent_run:
            terminal_indices: set[int] = set()
            for inv in succeeded:
                match = re.fullmatch(r"inv-(\d+)", inv)
                if match is None or not (1 <= int(match.group(1)) <= len(plan)):
                    raise ValueError(
                        f"run {run_id!r} has SUCCEEDED invocation {inv!r}"
                        f" outside the {len(plan)}-entry plan; impossible"
                        " for the concurrent coordinator"
                    )
                terminal_indices.add(int(match.group(1)) - 1)
        else:
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
        # Issue #24: PAR entries create no plan task of their own (the
        # ledger carries one task per branch, created during execution),
        # so resume aligns task ids with the plan positions that DO carry
        # static tasks — every entry except PAR blocks.  Conditional
        # entries keep their historical positional treatment (they trail
        # the plan and their tasks are created here when missing).
        ledger = self.store.task_ledger(run_id)
        task_ids = list(ledger.tasks)
        static_positions = [
            idx for idx, entry in enumerate(plan)
            if entry.par is None and entry.loop is None and entry.try_ is None
            if entry.par is None and entry.loop is None
            and entry.reformulate is None
            and entry.first is None
            and entry.await_ is None
            and entry.approve is None
        ]
        if len(task_ids) > len(static_positions):
            # Issue #4: tasks beyond the plan's own entries are per-candidate
            # fan-out tasks ("step.<id>: DO <command> [candidate k]") created
            # while a scatter entry executed; issue #24 adds the PAR
            # branches' per-branch tasks ("PAR branch <k>: <summary>");
            # anything else means the program does not match the run.
            scatter_body_ids = sorted(
                {
                    entry.scatter.body.step_id
                    for entry in plan
                    if entry.scatter is not None
                }
            )
            candidate_text_res = [
                re.compile(
                    rf"^{re.escape(body_id)}: DO [a-z][a-z0-9_]*"
                    rf" \[candidate \d+\]$"
                )
                for body_id in scatter_body_ids
            ]
            par_branch_text_res = [
                re.compile(
                    rf"^PAR branch \d+: (?:step\.[a-z][a-z0-9_]*: DO"
                    rf" [a-z][a-z0-9_]*|CALL protocol\.[a-z][a-z0-9_.]*)$"
                )
                for _entry in plan
                if _entry.par is not None
            ]
            for extra_id in task_ids[len(static_positions):]:
                text = ledger.tasks[extra_id].text
                if not any(
                    pattern.fullmatch(text)
                    for pattern in candidate_text_res + par_branch_text_res
                ):
                    raise ValueError(
                        f"run {run_id!r} has {len(task_ids)} tasks but the"
                        f" program plans {len(plan)} and task {extra_id!r}"
                        f" ({text!r}) is not a scatter candidate or PAR"
                        " branch task; refusing to resume a mismatched"
                        " program"
                    )
        for position, task_id in enumerate(task_ids[: len(static_positions)]):
            plan_idx = static_positions[position]
            expected_text = self._task_text(plan[plan_idx])
            if ledger.tasks[task_id].text != expected_text:
                raise ValueError(
                    f"task {task_id!r} ({ledger.tasks[task_id].text!r}) does"
                    f" not match plan step {plan_idx} ({expected_text!r});"
                    " refusing to resume with a mismatched program"
                )
        if len(task_ids) < len(static_positions):
            create_records: list[_Record] = []
            create_ledger = self.store.task_ledger(run_id)
            for plan_idx in static_positions[len(task_ids):]:
                entry = plan[plan_idx]
                task = create_ledger.create_task(
                    text=self._task_text(entry),
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
                    store=self.store,
                ))
            self.store.append_batch(run_id, create_records)
            task_ids = list(self.store.task_ledger(run_id).tasks)
        statement_to_task = {
            static_positions[position]: task_id
            for position, task_id in enumerate(task_ids[: len(static_positions)])
        }

        if concurrent_run:
            resume_workers = max_workers if max_workers > 1 else int(
                self.store.run(run_id)["metadata"].get("max_workers") or 2
            )
            return self._drive_plan_concurrent(
                program,
                run_id,
                plan,
                values,
                statement_to_task,
                initial_terminal=frozenset(terminal_indices),
                max_workers=resume_workers,
                gate=gate,
                claims=claims,
            )

        return self._drive_plan(
            program,
            run_id,
            plan,
            values,
            statement_to_task,
            start_idx=start_idx,
            gate=gate,
            claims=claims,
            branch_root=branch_workspace,
            branch_claim=branch_claim,
        )
