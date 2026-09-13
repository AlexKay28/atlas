"""Drive loops for the TAHOE coordinator (issue #38).

Extracted from coordinator.py: the sequential and concurrent plan-drive
loops, worker-call dispatch, budget-deadline enforcement, and the
dependency-DAG helpers for the concurrent frontier.

The two drive loops (_drive_plan and _drive_plan_concurrent) share the
same per-entry lifecycle (READY, DISPATCHED, RESULT_RECEIVED,
VALIDATION_PASSED, SUCCEEDED batch) and the same failure handling
(unified in finalize.py).  A future evolution can collapse them into one
loop with a scheduling-strategy object; this module isolates them so
that collapse is a local change.

Mixed into ``SequentialCoordinator`` via the ``DriveEngine`` mixin.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import re
import time
from typing import TYPE_CHECKING, Any, Callable, Mapping

from tahoe.budgets import BudgetDeadlineExceeded, BudgetGate
from tahoe.runtime import finalize as _finalize
from tahoe.runtime import planning as _planning
from tahoe.runtime.events import EventType, _Record
from tahoe.runtime.tasks import TaskStatus
from tahoe.state import StateDelta
from tahoe.syntax import is_typed_reference
from tahoe.syntax.model import Call, Program, Return, Stop, Loop, Invocation, Try, Conditional
from tahoe.syntax import is_typed_reference, parse_program as parse_program_text
from tahoe.syntax.model import Call, Program, Return, Stop, Loop, Invocation, Reformulate, First
from tahoe.syntax.model import Call, Program, Return, Stop, Loop, Invocation, Reformulate, Await
from tahoe.syntax.model import Call, Program, Return, Stop, Loop, Invocation, Reformulate, Approve

# Re-import constants and helpers from engine modules (issue #38 extraction).
from tahoe.runtime.delegate import (
    DELEGATE_COMMAND,
    DELEGATE_DEFAULT_MAX_STEPS,
    DELEGATE_HARD_MAX_STEPS,
)
from tahoe.runtime.par import (
    par_branch_invocation_id,
    par_branch_run_id,
    par_branch_summary,
    branch_workspace_dir,
)
from tahoe.runtime.scatter import (
    candidate_invocation_id,
    candidate_node_id,
)
from tahoe.runtime.deterministic import DeterministicStepExecutor
from tahoe.runtime.helpers import (
    _CANDIDATE_INVOCATION_RE,
    _PAR_INVOCATION_RE,
    _effectful_commands,
    _command_max_attempts,
    _command_max_tokens,
    _command_max_output_bytes,
    _command_max_cost,
    map_results_to_targets,
    evaluate_done_predicate,
    evaluate_condition,
)

if TYPE_CHECKING:
    from tahoe.claims import ResourceLedger
    from tahoe.runtime.coordinator import _PlanEntry


def _monotonic() -> float:
    """Monotonic clock for budget deadlines (issue #22)."""
    return time.monotonic()


class DriveEngine:
    """Mixin: drive loops, worker dispatch, budget enforcement.

    Consumed by ``SequentialCoordinator`` — all methods assume the host
    class provides ``self.store``, ``self.worker``, ``self.workspace_root``,
    ``self.protocols_dir``, ``self.memory`` and the engine mixins.
    """

    def _dispatch_worker_call(
        self,
        command: str,
        resolved_kwargs: dict[str, Any],
        gate: "BudgetGate | None" = None,
    ) -> Any:
        """Pool-side handler execution under the budget gate (issue #22).

        Runs on a frontier worker thread: with a gate it holds one of
        the tree's shared concurrency slots for the handler's duration
        (waiting CALL frames hold no slot — their children's step
        executions acquire their own, so a one-worker budget cannot
        deadlock a parent awaiting a child).  Per-invocation deadlines
        are enforced by the frontier's future timeouts, not here.
        """
        if gate is None:
            return self.worker.execute(command, resolved_kwargs)
        gate.acquire_slot()
        try:
            return self.worker.execute(command, resolved_kwargs)
        finally:
            gate.release_slot()

    @staticmethod
    def _frontier_wait_timeout(
        gate: "BudgetGate | None",
        in_flight: "dict[int, concurrent.futures.Future]",
        dispatched_at: Mapping[int, float],
    ) -> float | None:
        """Wait horizon: the nearest budget deadline among in-flight work."""
        if gate is None or not in_flight:
            return None
        candidates: list[float] = []
        global_remaining = gate.global_remaining()
        if global_remaining is not None:
            candidates.append(global_remaining)
        per_invocation = gate.budget.per_invocation_deadline_seconds
        if per_invocation is not None:
            now = _monotonic()
            remainders = [
                dispatched_at[idx] + per_invocation - now
                for idx in in_flight
                if idx in dispatched_at
            ]
            if remainders:
                candidates.append(max(0.0, min(remainders)))
        return min(candidates) if candidates else None

    def _execute_worker_call(
        self,
        command: str,
        resolved_kwargs: dict[str, Any],
        gate: "BudgetGate | None" = None,
    ) -> Any:
        """One sequential handler dispatch under the budget gate (issue #22).

        ``gate=None`` dispatches exactly as before.  With a gate, the
        call holds one of the tree's shared concurrency slots and a
        per-invocation deadline is checked after the handler returns —
        a running handler cannot be interrupted, so an overrunning
        result is discarded by failing the invocation (the DISPATCHED
        idempotency key keeps the at-least-once contract honest).

        Issue #61: when deterministic execution is enabled (env var
        ``TAHOE_DETERMINISTIC=1``), pure-computation commands
        (``calculate``, ``check``, ``choose``, ``rank``) are evaluated
        locally by :class:`DeterministicStepExecutor` before the worker
        is called.  If the executor returns ``None`` (inputs require
        model reasoning), the call falls through to the worker as
        before.
        """
        det_result = DeterministicStepExecutor.try_execute(
            command, resolved_kwargs
        )
        if det_result is not None:
            return det_result
        if gate is None:
            return self.worker.execute(command, resolved_kwargs)
        per_invocation = gate.budget.per_invocation_deadline_seconds
        started_at = _monotonic()
        gate.acquire_slot()
        try:
            result = self.worker.execute(command, resolved_kwargs)
        finally:
            gate.release_slot()
        if per_invocation is not None and (
            _monotonic() - started_at
        ) > per_invocation:
            raise BudgetDeadlineExceeded("deadline exceeded")
        return result

    def _fail_global_deadline(
        self,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        from_idx: int,
    ) -> dict[str, Any]:
        """Fail a run whose global budget deadline expired (issue #22)."""
        records = _finalize.fail_global_deadline_sequential(
            self.store, run_id, plan, statement_to_task, from_idx,
        )
        self.store.append_batch(run_id, records)
        return {
            "run_id": run_id,
            "status": "failed",
            "error": "global deadline exceeded",
            "outputs": {},
        }

    @staticmethod
    def _parse_timeout(timeout: str) -> float | None:
        """Parse a duration string like ``30s``, ``5m``, ``2h`` into seconds.

        Returns ``None`` if the string does not match a known suffix.
        """
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smhd])", timeout.strip())
        if match is None:
            return None
        value = float(match.group(1))
        unit = match.group(2)
        multipliers = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
        return value * multipliers[unit]

    def _drive_plan(
        self,
        program: Program,
        run_id: str,
        plan: list[_PlanEntry],
        values: dict[str, Any],
        statement_to_task: dict[int, str],
        *,
        start_idx: int = 0,
        crash_hook: "Callable[[int], None] | None" = None,
        gate: "BudgetGate | None" = None,
        claims: "ResourceLedger | None" = None,
        branch_root: str | None = None,
        branch_claim: str | None = None,
    ) -> dict[str, Any]:
        """Drive the plan's per-invocation loop from ``start_idx`` on.

        ``start_idx > 0`` is the resume path (issue #10): every plan entry
        before it already committed a SUCCEEDED terminal event, so its
        task is COMPLETED and its deltas are already folded into
        ``values``.  The entry at ``start_idx`` may be mid-flight from
        before a crash (task IN_PROGRESS): its committed lifecycle events
        are never re-emitted, but its worker call is re-executed
        (at-least-once; the DISPATCHED idempotency key is the dedup
        contract for effectful workers).

        ``gate`` (issue #22) enforces an :class:`ExecutionBudget` at the
        dispatch boundaries: the global deadline before each dispatch
        (which is also "before a child starts" for CALL entries), the
        child-depth cap before a CALL dispatches, and a concurrency slot
        plus per-invocation deadline around each worker call.
        ``gate=None`` (the default) leaves every code path untouched.

        ``claims``/``branch_root``/``branch_claim`` (issue #23/#24) carry
        the run tree's resource ledger and the enclosing branch context:
        inside a branch, effectful dispatches write into the branch
        workspace subdirectory, hold the branch's claim for the handler's
        duration, and annotate their DISPATCHED payload with the held
        claims; a PAR entry nests its branches under the current branch
        root.
        """
        # -- batch all task-creation records --------------------------

        def finish_failed_invocation(
            idx: int,
            instruction_id: str,
            invocation_id: str,
            task_id: str,
            error: str,
            validation: dict[str, Any] | None = None,
        ) -> None:
            records = _finalize.fail_invocation(
                self.store, run_id, plan, statement_to_task,
                idx, instruction_id, invocation_id, task_id, error, validation,
            )
            self.store.append_batch(run_id, records)

        failed = False
        error_msg: str | None = None

        # Issue #41: per-invocation attempt count for max_attempts enforcement.
        attempt_counts: dict[str, int] = {}

        # Issue #3: conditionals anchored before the first invocation (their
        # refs can only be declared INPUT nodes) are evaluated up front.  On
        # resume every anchor before start_idx was already handled before
        # the crash and is deliberately not re-evaluated.
        anchors = self._collect_anchors(program)
        if start_idx == 0:
            anchor_result = self._run_conditionals(
                run_id,
                anchors.get(0, ()),
                values,
                plan,
                statement_to_task,
                cancel_from_idx=0,
            )
            if anchor_result is not None:
                return anchor_result

        idx = start_idx
        while idx < len(plan):
            entry = plan[idx]
            statement = entry.invocation
            call = entry.call
            # Issue #4: scatter and gather entries execute through their own
            # machinery (candidate expansion / explicit join) and never fall
            # through to the plain invocation path below.  Issue #24: a PAR
            # entry executes its branches concurrently through the child-run
            # machinery and joins at its barrier.
            if (
                entry.scatter is not None
                or entry.gather is not None
                or entry.par is not None
                or entry.loop is not None
                or entry.try_ is not None
                or entry.reformulate is not None
                or entry.first is not None
                or entry.await_ is not None
                or entry.approve is not None
            ):
                # Issue #22: the global deadline is checked before each
                # dispatch, mirroring the other entry kinds.
                if gate is not None and gate.global_expired():
                    return self._fail_global_deadline(
                        run_id, plan, statement_to_task, idx
                    )
                invocation_id = f"inv-{idx + 1}"
                task_id = statement_to_task.get(idx)
                if entry.scatter is not None:
                    result = self._execute_scatter_entry(
                        program,
                        run_id,
                        entry,
                        idx,
                        invocation_id,
                        task_id,
                        values,
                        plan,
                        statement_to_task,
                        crash_hook,
                        gate,
                        claims,
                        branch_root,
                    )
                elif entry.gather is not None:
                    result = self._execute_gather_entry(
                        program,
                        run_id,
                        entry,
                        idx,
                        invocation_id,
                        task_id,
                        values,
                        plan,
                        statement_to_task,
                        crash_hook,
                        gate,
                        claims,
                        branch_root,
                    )
                elif entry.loop is not None:
                    result = self._execute_loop_entry(
                        program,
                        run_id,
                        entry,
                        idx,
                        invocation_id,
                        values,
                        plan,
                        statement_to_task,
                        crash_hook,
                        gate,
                        claims,
                        branch_root,
                    )
                elif entry.try_ is not None:
                    result = self._execute_try_entry(
                        program, run_id, entry, idx,
                        f"inv-{idx + 1}", values, plan,
                        statement_to_task, crash_hook, gate, claims,
                        branch_root,
                    )
                elif entry.reformulate is not None:
                    # Issue #80: a conditional REFORMULATE (inside an IF
                    # block) evaluates its condition before executing.
                    if entry.condition is not None:
                        try:
                            fired = evaluate_condition(entry.condition, values)
                        except ValueError as exc:
                            return self._fail_run(
                                run_id, plan, statement_to_task, idx, str(exc)
                            )
                        if not fired:
                            idx += 1
                            continue
                    result = self._execute_reformulate_entry(
                        program,
                        run_id,
                        entry,
                        idx,
                        invocation_id,
                        values,
                        plan,
                        statement_to_task,
                        crash_hook,
                        gate,
                        claims,
                        branch_root,
                    )
                elif entry.first is not None:
                    result = self._execute_first_entry(
                        program, run_id, entry, idx,
                        invocation_id, values, plan,
                        statement_to_task, crash_hook, gate, claims,
                        branch_root,
                    )
                elif entry.await_ is not None:
                    result = self._execute_await_entry(
                        program, run_id, entry, idx,
                        invocation_id, values, plan,
                        statement_to_task, crash_hook, gate, claims,
                        branch_root,
                    )
                elif entry.approve is not None:
                    result = self._execute_approve_entry(
                        program,
                        run_id,
                        entry,
                        idx,
                        invocation_id,
                        values,
                        plan,
                        statement_to_task,
                        crash_hook,
                        gate,
                        claims,
                        branch_root,
                    )
                else:
                    result = self._execute_par_entry(
                        program,
                        run_id,
                        entry,
                        idx,
                        invocation_id,
                        values,
                        plan,
                        statement_to_task,
                        crash_hook,
                        gate,
                        claims,
                        branch_root,
                    )
                if result is not None:
                    return result
                anchor_result = self._run_conditionals(
                    run_id,
                    anchors.get(idx + 1, ()),
                    values,
                    plan,
                    statement_to_task,
                    cancel_from_idx=idx + 1,
                )
                if anchor_result is not None:
                    return anchor_result
                idx += 1
                continue
            # Issue #20: a CALL entry's instruction id is the protocol
            # reference (the CALL statement's AST anchor); a DO step's is
            # its step id.  Both are nonempty, keeping the audit invariant.
            instruction_id = (
                call.protocol if call is not None else statement.step_id
            )
            invocation_id = f"inv-{idx + 1}"
            if entry.condition is not None:
                # Issue #3: a conditional DO invocation executes only when
                # its condition holds over the committed state; a false
                # condition skips the statement entirely — no task, no
                # events, no state change.  A fired branch creates its
                # ledger task here and then runs the exact same lifecycle
                # as an unconditional entry below.
                try:
                    fired = evaluate_condition(entry.condition, values)
                except ValueError as exc:
                    return self._fail_run(
                        run_id, plan, statement_to_task, idx, str(exc)
                    )
                if not fired:
                    idx += 1
                    continue
                task_id = statement_to_task.get(idx)
                if task_id is None:
                    task_id = self._create_single_plan_task(run_id, entry)
                    statement_to_task[idx] = task_id
            elif entry.else_condition is not None:
                # Issue #83: an else-branch entry executes only when the
                # IF condition is FALSE.  A true condition skips the else
                # branch entirely.
                try:
                    fired = evaluate_condition(entry.else_condition, values)
                except ValueError as exc:
                    return self._fail_run(
                        run_id, plan, statement_to_task, idx, str(exc)
                    )
                if fired:
                    idx += 1
                    continue
                if statement is not None:
                    task_id = statement_to_task.get(idx)
                    if task_id is None:
                        task_id = self._create_single_plan_task(run_id, entry)
                        statement_to_task[idx] = task_id
                else:
                    # else-branch terminal (STOP/RETURN): execute directly
                    for s in program.statements:
                        if isinstance(s, Conditional) and s.else_branch is not None:
                            for es in s.else_branch:
                                if es is entry.invocation or (
                                    not isinstance(es, Invocation) and es is not None
                                ):
                                    pass
                    # Find the matching else-branch terminal statement
                    for cond_stmt in program.statements:
                        if (
                            isinstance(cond_stmt, Conditional)
                            and cond_stmt.else_branch is not None
                        ):
                            for es in cond_stmt.else_branch:
                                if not isinstance(es, Invocation):
                                    if isinstance(es, Stop):
                                        self._cancel_pending_after(
                                            run_id, plan,
                                            statement_to_task, idx,
                                        )
                                        return self._terminal_stop(
                                            run_id, es, values
                                        )
                                    if isinstance(es, Return):
                                        self._cancel_pending_after(
                                            run_id, plan,
                                            statement_to_task, idx,
                                        )
                                        return self._terminal_return(
                                            run_id, es.refs, values
                                        )
                    idx += 1
                    continue
            else:
                task_id = statement_to_task[idx]

            # Issue #22: the global deadline is checked before each
            # dispatch — which for a CALL entry is also "before the
            # child starts".  Exceeding it fails the run coherently
            # through the recorded global-deadline path.
            if gate is not None and gate.global_expired():
                return self._fail_global_deadline(
                    run_id, plan, statement_to_task, idx
                )

            # Issue #10: a resumed in-flight step carries pre-crash
            # lifecycle events.  Its task is already IN_PROGRESS
            # (`start_task` requires PENDING), and task_started,
            # INVOCATION_READY and INVOCATION_DISPATCHED may already be
            # committed — they are never re-emitted.  Dispatching does
            # NOT imply success: the worker call below always re-runs.
            prior_types: set[EventType] = set()
            ledger = self.store.task_ledger(run_id)
            task = ledger.tasks.get(task_id)
            if task is not None and task.status is TaskStatus.IN_PROGRESS:
                prior_types = {
                    event.event_type
                    for event in self.store.events(run_id)
                    if event.invocation_id == invocation_id
                }
            elif task is not None and task.status is not TaskStatus.PENDING:
                # Impossible state: a non-terminal step whose task is
                # neither PENDING (fresh) nor IN_PROGRESS (in flight).
                raise TaskLedgerError(
                    f"task {task_id} for non-terminal step"
                    f" {instruction_id} is {task.status.value};"
                    " cannot resume"
                )
            ready_command = (
                f"CALL {call.protocol}" if call is not None else statement.command
            )
            if EventType.INVOCATION_READY not in prior_types:
                if task is not None and task.status is TaskStatus.IN_PROGRESS:
                    # Impossible per the atomic task_started+READY batch;
                    # recorded defensively so the log stays truthful.
                    self.store.append(
                        run_id,
                        EventType.INVOCATION_READY,
                        instruction_id=instruction_id,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={"command": ready_command},
                    )
                else:
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
                            instruction_id=instruction_id,
                            invocation_id=invocation_id,
                            task_id=task_id,
                            payload={"command": ready_command},
                            store=self.store,
                        ),
                    ])

            if call is not None:
                # Issue #20: a CALL executes an isolated child run instead
                # of expanding the protocol inline (the pre-#20 behavior).
                # The child lives in the same EventStore under the
                # deterministic id "<parent_run_id>:<invocation_id>", owns
                # its own ledger and state namespace (seeded only from the
                # explicitly passed CALL arguments), and its RETURN refs
                # are adopted onto the CALL targets on success — recorded
                # as CHILD_ADOPTED in the same atomic batch as the CALL's
                # SUCCEEDED delta.  Any non-succeeded child terminal fails
                # the parent through the standard atomic path.
                child_run_id = f"{run_id}:{invocation_id}"
                # Issue #22: the execution-tree child-depth cap is checked
                # before the child is dispatched at all.
                if gate is not None and gate.depth_exceeded(child_run_id):
                    failed = True
                    error_msg = (
                        f"child run {child_run_id} depth"
                        f" {gate.depth_of(child_run_id)} exceeds budget"
                        f" max_child_depth {gate.budget.max_child_depth}"
                    )
                    finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, error_msg
                    )
                    break
                try:
                    resolved_call_args = self._resolve_call_arguments(
                        call, values
                    )
                except Exception as exc:
                    failed = True
                    error_msg = str(exc)
                    finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, error_msg
                    )
                    break

                if EventType.INVOCATION_DISPATCHED not in prior_types:
                    self.store.append(
                        run_id,
                        EventType.INVOCATION_DISPATCHED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "args": resolved_call_args,
                            "idempotency_key": f"{run_id}:{invocation_id}",
                            "child_run_id": child_run_id,
                        },
                    )

                child_result = self._execute_call_child(
                    call,
                    resolved_call_args,
                    run_id,
                    invocation_id,
                    gate=gate,
                    claims=claims,
                    branch_workspace=branch_root,
                    branch_claim=branch_claim,
                )
                child_status = child_result.get("status", "unknown")
                if child_status != "succeeded":
                    # Failed/blocked/cancelled children never publish
                    # partial caller outputs: the parent fails at the
                    # CALL's invocation and the child stays terminal in
                    # its own history.
                    child_error = child_result.get("error")
                    failed = True
                    error_msg = (
                        f"child run {child_run_id} for {call.protocol}"
                        f" finished with status {child_status!r}; the CALL"
                        " cannot adopt its outputs"
                    )
                    if child_error:
                        error_msg = f"{error_msg}: {child_error}"
                    finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, error_msg
                    )
                    break

                if EventType.RESULT_RECEIVED not in prior_types:
                    self.store.append(
                        run_id,
                        EventType.RESULT_RECEIVED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "child_run_id": child_run_id,
                            "status": child_status,
                        },
                    )

                try:
                    adopted_nodes, adopted_map = self._adopt_child_result(
                        call, child_result
                    )
                except Exception as exc:
                    failed = True
                    error_msg = str(exc)
                    finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, error_msg
                    )
                    break

                if crash_hook is not None:
                    # Issue #10/#20: crash window after the child is
                    # terminal but before the parent adopts — resume
                    # detects the terminal child and adopts without
                    # re-executing it.
                    crash_hook(idx)

                self.store.append(
                    run_id,
                    EventType.VALIDATION_PASSED,
                    instruction_id=call.protocol,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={},
                )

                for node in adopted_nodes:
                    values[node["id"]] = node["value"]

                delta = StateDelta(add_nodes=tuple(adopted_nodes))
                expected_sv = self.store._current_state_version(run_id)

                # batch: CHILD_ADOPTED + SUCCEEDED + invocation_recorded
                # + task_completed — one atomic append so an adoption is
                # never split from its state commit (the store's
                # duplicate-SUCCEEDED guard then makes a re-adoption of
                # the same invocation impossible).
                self.store.append_batch(run_id, [
                    _Record(
                        event_type=EventType.CHILD_ADOPTED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "child_run_id": child_run_id,
                            "adopted": adopted_map,
                            "child_status": child_status,
                        },
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.SUCCEEDED,
                        instruction_id=call.protocol,
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
                            "evidence": (
                                f"CALL {call.protocol} ({child_run_id})"
                                f" -> {list(call.targets)}"
                            ),
                        },
                        store=self.store,
                    ),
                ])

                # Issue #3: conditionals anchored directly after this entry
                # in source order are evaluated over the state it just
                # committed (including the adopted values).
                anchor_result = self._run_conditionals(
                    run_id,
                    anchors.get(idx + 1, ()),
                    values,
                    plan,
                    statement_to_task,
                    cancel_from_idx=idx + 1,
                )
                if anchor_result is not None:
                    return anchor_result
                idx += 1
                continue

            try:
                resolved_kwargs: dict[str, Any] = {}
                for arg in statement.args:
                    # Issue #7: guard first so a ref retired by an earlier
                    # step fails the invocation clearly instead of passing
                    # the raw ref string through as a literal.
                    self._reject_unresolved_refs(arg.value, values)
                    if isinstance(arg.value, str) and arg.value in values:
                        resolved_kwargs[arg.name] = values[arg.value]
                    elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                        # KB.<name> resolves from the cross-run knowledge base
                        # at dispatch time, never from run-local state.
                        resolved_kwargs[arg.name] = self._resolve_kb_ref(arg.value)
                    elif isinstance(arg.value, list):
                        # Reference-list argument ([E.a, E.b]): each listed ref
                        # resolves through the same values mapping as single
                        # refs; literal items (validation guarantees ref-shaped
                        # strings always resolve) pass through untouched.
                        resolved_kwargs[arg.name] = [
                            values[item] if isinstance(item, str) and item in values
                            else self._resolve_kb_ref(item)
                            if isinstance(item, str) and item.startswith("KB.")
                            else item
                            for item in arg.value
                        ]
                    else:
                        resolved_kwargs[arg.name] = arg.value
            except Exception as exc:
                # KB resolution errors (no memory, unknown key) fail the
                # invocation through the standard failure path.
                failed = True
                error_msg = str(exc)
                finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id, error_msg
                )
                break

            # WorkspacePolicy (issue #9) + branch isolation (issue #23):
            # effectful dispatches learn the declared workspace root so
            # handlers can sandbox their writes; inside a branch the root
            # is the branch's isolated subdirectory and the dispatch holds
            # the branch's exclusive claim for the handler's duration,
            # annotated on the DISPATCHED payload (no new event types).
            dispatch_root = branch_root or self.workspace_root
            branch_claim_held: str | None = None
            if (
                dispatch_root is not None
                and statement.command in _effectful_commands()
            ):
                resolved_kwargs["_workspace_root"] = dispatch_root
                if branch_root is not None and claims is not None:
                    branch_claim_held = branch_claim
                    owner = f"{run_id}:{invocation_id}"
                    if not claims.claim(branch_claim_held, owner):
                        failed = True
                        error_msg = (
                            f"resource claim failed: {branch_claim_held} is"
                            f" held by {claims.holder(branch_claim_held)!r}"
                        )
                        finish_failed_invocation(
                            idx, statement.step_id, invocation_id, task_id,
                            error_msg,
                        )
                        break

            if EventType.INVOCATION_DISPATCHED not in prior_types:
                dispatched_payload: dict[str, Any] = {
                    "args": resolved_kwargs,
                    "idempotency_key": f"{run_id}:{invocation_id}",
                }
                if branch_claim_held is not None:
                    dispatched_payload["resource_claims"] = [branch_claim_held]
                if DeterministicStepExecutor.is_enabled():
                    dispatched_payload["_deterministic"] = (
                        DeterministicStepExecutor.try_execute(
                            statement.command, resolved_kwargs
                        ) is not None
                    )
                self.store.append(
                    run_id,
                    EventType.INVOCATION_DISPATCHED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload=dispatched_payload,
                )

            if statement.command == DELEGATE_COMMAND:
                # Issue #25: a delegate step AUTHORS a child plan at
                # runtime.  The worker reply is the authored plan text;
                # the coordinator records it (CHILD_PLAN_AUTHORED),
                # validates and bounds it, then executes it as an isolated
                # child run and adopts its RETURN refs onto the step's
                # targets — all inside _execute_delegate_entry, which
                # fails the run atomically through the standard path on
                # any rejection or non-succeeded child.
                delegate_result = self._execute_delegate_entry(
                    run_id,
                    idx,
                    invocation_id,
                    task_id,
                    statement,
                    resolved_kwargs,
                    values,
                    plan,
                    statement_to_task,
                    prior_types,
                    crash_hook,
                    gate,
                    claims,
                    branch_root,
                    branch_claim,
                    finish_failed_invocation,
                )
                if delegate_result is not None:
                    return delegate_result
                anchor_result = self._run_conditionals(
                    run_id,
                    anchors.get(idx + 1, ()),
                    values,
                    plan,
                    statement_to_task,
                    cancel_from_idx=idx + 1,
                )
                if anchor_result is not None:
                    return anchor_result
                idx += 1
                continue

            # Issue #41: enforce contract.budget.max_attempts at the
            # coordinator dispatch layer — refuse to dispatch when the
            # invocation's attempt count already meets the cap.
            cap = _command_max_attempts(statement.command)
            if cap is not None:
                prior_attempts = attempt_counts.get(invocation_id, 0)
                if prior_attempts >= cap:
                    failed = True
                    error_msg = (
                        f"max_attempts ({cap}) exceeded for"
                        f" {statement.command} on {invocation_id}"
                    )
                    finish_failed_invocation(
                        idx, statement.step_id, invocation_id, task_id, error_msg
                    )
                    break
                attempt_counts[invocation_id] = prior_attempts + 1

            # Issue #85: pre-dispatch token budget check.
            cmd_max_tokens = _command_max_tokens(statement.command)
            if (
                gate is not None
                and cmd_max_tokens is not None
                and cmd_max_tokens > 0
            ):
                total_cap = gate.budget.max_total_tokens
                if total_cap is not None:
                    remaining = gate.remaining_tokens(total_cap)
                    if not gate.check_token_budget(cmd_max_tokens, remaining):
                        failed = True
                        error_msg = "insufficient_token_budget"
                        finish_failed_invocation(
                            idx, statement.step_id, invocation_id,
                            task_id, error_msg,
                        )
                        break

            try:
                result = self._execute_worker_call(
                    statement.command, resolved_kwargs, gate
                )
            except Exception as exc:
                failed = True
                error_msg = str(exc)
                finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id, error_msg
                )
                break
            finally:
                # The branch claim covers exactly the handler's duration;
                # releasing twice is a no-op (only the holder can release).
                if branch_claim_held is not None:
                    claims.release(
                        branch_claim_held, f"{run_id}:{invocation_id}"
                    )
                    branch_claim_held = None

            self.store.append(
                run_id,
                EventType.RESULT_RECEIVED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={"result": result},
            )

            # Issue #41: feed the budget gate's token accumulator from
            # the result receipt if the worker carries usage info.
            # Issue #85: also accumulate cost from receipt.usage.cost.
            if gate is not None and isinstance(result, dict):
                receipt = result.get("_receipt")
                if isinstance(receipt, dict):
                    usage = receipt.get("usage")
                    if isinstance(usage, dict):
                        tokens = usage.get("tokens", 0)
                        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0:
                            gate.add_tokens(tokens)
                        cost = usage.get("cost")
                        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > 0:
                            gate.add_cost(cost)
                if gate.token_cap_exceeded():
                    failed = True
                    error_msg = "token budget exceeded"
                    finish_failed_invocation(
                        idx, statement.step_id, invocation_id, task_id, error_msg
                    )
                    break
                if gate.cost_cap_exceeded():
                    failed = True
                    error_msg = "cost budget exceeded"
                    finish_failed_invocation(
                        idx, statement.step_id, invocation_id, task_id, error_msg
                    )
                    break

            # Issue #85: post-result token ceiling check — if output
            # tokens exceeded the command's max_tokens, mark BUDGET_EXCEEDED.
            cmd_max_tokens = _command_max_tokens(statement.command)
            if (
                cmd_max_tokens is not None
                and cmd_max_tokens > 0
                and isinstance(result, dict)
            ):
                receipt = result.get("_receipt")
                if isinstance(receipt, dict):
                    usage = receipt.get("usage")
                    if isinstance(usage, dict):
                        out_tokens = usage.get("output_tokens")
                        if (
                            isinstance(out_tokens, int)
                            and not isinstance(out_tokens, bool)
                            and out_tokens > cmd_max_tokens
                        ):
                            failed = True
                            error_msg = "budget_exceeded"
                            finish_failed_invocation(
                                idx, statement.step_id, invocation_id,
                                task_id, error_msg,
                            )
                            break

            # Issue #85: post-result output-size check — reject oversized
            # results before commit.
            cmd_max_bytes = _command_max_output_bytes(statement.command)
            if cmd_max_bytes is not None and cmd_max_bytes > 0:
                try:
                    import json as _json
                    payload_size = len(
                        _json.dumps(result, ensure_ascii=False, default=str)
                        .encode("utf-8")
                    )
                except Exception:
                    payload_size = 0
                if payload_size > cmd_max_bytes:
                    failed = True
                    error_msg = "output_too_large"
                    finish_failed_invocation(
                        idx, statement.step_id, invocation_id,
                        task_id, error_msg,
                    )
                    break

            # Issue #85: post-result per-invocation cost ceiling check —
            # if the receipt's cost exceeded the command's max_cost, fail.
            cmd_max_cost = _command_max_cost(statement.command)
            if (
                cmd_max_cost is not None
                and cmd_max_cost > 0
                and isinstance(result, dict)
            ):
                receipt = result.get("_receipt")
                if isinstance(receipt, dict):
                    usage = receipt.get("usage")
                    if isinstance(usage, dict):
                        cost = usage.get("cost")
                        if (
                            isinstance(cost, (int, float))
                            and not isinstance(cost, bool)
                            and cost > cmd_max_cost
                        ):
                            failed = True
                            error_msg = "cost_exceeded"
                            finish_failed_invocation(
                                idx, statement.step_id, invocation_id,
                                task_id, error_msg,
                            )
                            break

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
                    idx, statement.step_id, invocation_id, task_id, validation_error
                )
                break

            if statement.done is not None:
                passed, detail = evaluate_done_predicate(statement.done, target_values)
                if not passed:
                    validation_payload = {
                        "step_id": statement.step_id,
                        "predicate": {
                            "op": statement.done.op,
                            "ref": statement.done.ref,
                            "value": statement.done.value,
                        },
                        "detail": detail,
                    }
                    failed = True
                    error_msg = (
                        f"DONE predicate failed for {statement.step_id}: {detail}"
                    )
                    finish_failed_invocation(
                        idx, statement.step_id, invocation_id, task_id, error_msg,
                        validation=validation_payload,
                    )
                    break

            # Issue #7: resolve the step's REVISE/RETIRE corrections here,
            # before VALIDATION_PASSED, so a malformed (unvalidated)
            # invocation fails through the standard atomic path.  REVISE
            # refs are set to the step's single target value (validation
            # pins REVISE to single-target steps); RETIRE refs are removed
            # from the projection.  Both commit inside the same SUCCEEDED
            # delta as the step's adds, so later steps observe the
            # corrected state and the version bumps once per step.
            revision_nodes: list[dict[str, Any]] = []
            retired_nodes: list[str] = []
            try:
                if statement.revisions:
                    if len(statement.targets) != 1 or (
                        statement.targets[0] not in target_values
                    ):
                        raise ValueError(
                            f"REVISE on {statement.step_id} requires the"
                            " step's single target value"
                        )
                    revised_value = target_values[statement.targets[0]]
                    revision_nodes = [
                        {"id": ref, "value": revised_value}
                        for ref in statement.revisions
                    ]
                retired_nodes = list(statement.retirements)
            except Exception as exc:
                failed = True
                error_msg = str(exc)
                finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id, error_msg
                )
                break

            if crash_hook is not None:
                # Issue #10: crash-window hook.  Called with the plan
                # index right before VALIDATION_PASSED is appended; an
                # exception raised here propagates out of the coordinator
                # uncaught (this site is outside every try/except),
                # leaving the committed prefix exactly at the
                # RESULT_RECEIVED-persisted window.
                crash_hook(idx)

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
            # Issue #7: keep the run-state values mapping in lockstep with
            # the corrections so later steps resolve revised values and
            # fail coherently on retired refs.
            for node in revision_nodes:
                values[node["id"]] = node["value"]
            for ref in retired_nodes:
                values.pop(ref, None)

            delta = StateDelta(
                add_nodes=tuple(add_nodes),
                revise_nodes=tuple(revision_nodes),
                retire_nodes=tuple(retired_nodes),
            )

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

            # Issue #3: conditionals anchored directly after this entry in
            # source order are evaluated over the state it just committed;
            # a fired STOP/RETURN ends the run here, so later entries never
            # execute and their tasks stay cancelled.
            anchor_result = self._run_conditionals(
                run_id,
                anchors.get(idx + 1, ()),
                values,
                plan,
                statement_to_task,
                cancel_from_idx=idx + 1,
            )
            if anchor_result is not None:
                return anchor_result

            idx += 1

        outputs: dict[str, Any] = {}
        if not failed:
            # Issue #3: conditionals anchored after the last invocation run
            # before the bare terminal scan (source order).
            if len(plan) > 0:
                anchor_result = self._run_conditionals(
                    run_id,
                    anchors.get(len(plan), ()),
                    values,
                    plan,
                    statement_to_task,
                    cancel_from_idx=len(plan),
                )
                if anchor_result is not None:
                    return anchor_result
            for statement in program.statements:
                if isinstance(statement, Return):
                    return self._terminal_return(run_id, statement.refs, values)
                if isinstance(statement, Stop):
                    return self._terminal_stop(run_id, statement, values)

        if failed:
            return {"run_id": run_id, "status": "failed", "error": error_msg or "", "outputs": {}}

        self.store.append(
            run_id,
            EventType.RUN_FINISHED,
            payload={"status": "succeeded"},
        )
        return {"run_id": run_id, "status": "succeeded", "outputs": outputs}

    # ------------------------------------------------------------------
    # LOOP execution (issue #68)
    # ------------------------------------------------------------------

    def _execute_loop_entry(
        self,
        program: Program,
        run_id: str,
        entry: "_PlanEntry",
        idx: int,
        invocation_id: str,
        values: dict[str, Any],
        plan: list["_PlanEntry"],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
    ) -> dict[str, Any] | None:
        """Execute one LOOP block (issue #68).

        Algorithm:
        1. Check ENTRY condition. If false, skip the loop.
        2. For iteration = 1 to MAX:
           a. Check WHILE condition. If false, break (normal completion).
           b. Execute body statements sequentially.
           c. Check PROGRESS: compare progress metric to previous iteration.
              If no progress, STOP blocked.
           d. Check EXIT condition. If true, break (loop succeeds).
        3. If MAX reached without EXIT: execute EXHAUSTED terminal.
        """
        loop = entry.loop
        assert loop is not None

        # Check ENTRY condition
        try:
            entry_holds = evaluate_condition(loop.entry_condition, values)
        except ValueError as exc:
            return self._fail_run(
                run_id, plan, statement_to_task, idx, str(exc)
            )
        if not entry_holds:
            self.store.append(
                run_id,
                EventType.LOOP_STARTED,
                invocation_id=invocation_id,
                payload={"name": loop.name, "entry": False},
            )
            return None

        self.store.append(
            run_id,
            EventType.LOOP_STARTED,
            invocation_id=invocation_id,
            payload={"name": loop.name, "entry": True, "max": loop.max_iterations},
        )

        prev_progress: float | None = None
        for iteration in range(1, loop.max_iterations + 1):
            self.store.append(
                run_id,
                EventType.LOOP_ITERATION,
                invocation_id=invocation_id,
                payload={
                    "name": loop.name,
                    "iteration": iteration,
                    "max": loop.max_iterations,
                },
            )

            # Check WHILE condition
            try:
                while_holds = evaluate_condition(loop.while_condition, values)
            except ValueError as exc:
                return self._fail_run(
                    run_id, plan, statement_to_task, idx, str(exc)
                )
            if not while_holds:
                self.store.append(
                    run_id,
                    EventType.LOOP_EXITED,
                    invocation_id=invocation_id,
                    payload={
                        "name": loop.name,
                        "reason": "while_false",
                        "iteration": iteration,
                    },
                )
                return None

            # Execute body statements
            for body_stmt in loop.body:
                result = self._execute_loop_body_statement(
                    body_stmt,
                    program,
                    run_id,
                    invocation_id,
                    iteration,
                    values,
                    plan,
                    statement_to_task,
                    crash_hook,
                    gate,
                    claims,
                    branch_root,
                )
                if result is not None:
                    return result

            # Check PROGRESS
            current_progress = self._evaluate_progress(
                loop.progress_expression, values, loop.line
            )
            if current_progress is not None:
                if prev_progress is not None:
                    direction = self._progress_direction(loop.progress_expression)
                    if direction == "decreases":
                        if current_progress >= prev_progress:
                            # No progress — block the run
                            stop = Stop("blocked", None)
                            self.store.append(
                                run_id,
                                EventType.LOOP_EXHAUSTED,
                                invocation_id=invocation_id,
                                payload={
                                    "name": loop.name,
                                    "reason": "no_progress",
                                    "iteration": iteration,
                                },
                            )
                            return self._terminal_stop(run_id, stop, values)
                    elif direction == "increases":
                        if current_progress <= prev_progress:
                            stop = Stop("blocked", None)
                            self.store.append(
                                run_id,
                                EventType.LOOP_EXHAUSTED,
                                invocation_id=invocation_id,
                                payload={
                                    "name": loop.name,
                                    "reason": "no_progress",
                                    "iteration": iteration,
                                },
                            )
                            return self._terminal_stop(run_id, stop, values)
                prev_progress = current_progress

            # Check EXIT condition
            try:
                exit_holds = evaluate_condition(loop.exit_condition, values)
            except ValueError as exc:
                return self._fail_run(
                    run_id, plan, statement_to_task, idx, str(exc)
                )
            if exit_holds:
                self.store.append(
                    run_id,
                    EventType.LOOP_EXITED,
                    invocation_id=invocation_id,
                    payload={
                        "name": loop.name,
                        "reason": "exit_condition",
                        "iteration": iteration,
                    },
                )
                return None

        # MAX reached without EXIT — run EXHAUSTED terminal
        self.store.append(
            run_id,
            EventType.LOOP_EXHAUSTED,
            invocation_id=invocation_id,
            payload={
                "name": loop.name,
                "reason": "max_reached",
                "iteration": loop.max_iterations,
            },
        )
        if isinstance(loop.exhausted, Stop):
            return self._terminal_stop(run_id, loop.exhausted, values)
        return None

    def _progress_direction(self, expr: str) -> str:
        """Extract 'decreases' or 'increases' from a PROGRESS expression."""
        lower = expr.lower()
        if "decreases" in lower:
            return "decreases"
        if "increases" in lower:
            return "increases"
        return "decreases"

    def _evaluate_progress(
        self, expr: str, values: dict[str, Any], line_no: int
    ) -> float | None:
        """Evaluate a PROGRESS expression to a numeric metric.

        The expression looks like ``U.high_impact.count decreases`` or
        ``count(U.high_impact) decreases``.  We strip the trailing
        direction keyword and evaluate the remaining ref or count()
        expression against committed state.
        """
        lower = expr.lower()
        for direction in ("decreases", "increases"):
            idx = lower.rfind(direction)
            if idx != -1:
                metric_expr = expr[:idx].strip()
                break
        else:
            metric_expr = expr.strip()

        if metric_expr.startswith("count(") and metric_expr.endswith(")"):
            ref = metric_expr[6:-1].strip()
            val = values.get(ref)
            if isinstance(val, list):
                return float(len(val))
            if isinstance(val, (int, float)):
                return float(val)
            return None

        val = values.get(metric_expr)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        if isinstance(val, list):
            return float(len(val))
        return None

    def _execute_loop_body_statement(
        self,
        body_stmt: object,
        program: Program,
        run_id: str,
        loop_invocation_id: str,
        iteration: int,
        values: dict[str, Any],
        plan: list["_PlanEntry"],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
    ) -> dict[str, Any] | None:
        """Execute one statement inside a LOOP body (issue #68).

        Handles DO invocations, STOP, RETURN, and IF conditionals.  Each
        DO invocation runs through the standard worker-dispatch path and
        commits its results to ``values`` (the same shared dict as the
        parent run).  STOP and RETURN terminate the run.
        """
        from tahoe.runtime.helpers import map_results_to_targets

        if isinstance(body_stmt, Stop):
            self._cancel_pending_after(
                run_id, plan, statement_to_task, 0
            )
            return self._terminal_stop(run_id, body_stmt, values)

        if isinstance(body_stmt, Return):
            self._cancel_pending_after(
                run_id, plan, statement_to_task, 0
            )
            return self._terminal_return(run_id, body_stmt.refs, values)

        if isinstance(body_stmt, Invocation):
            invocation_id = f"{loop_invocation_id}.iter{iteration}.{body_stmt.step_id}"
            instruction_id = body_stmt.step_id

            ledger = self.store.task_ledger(run_id)
            task = ledger.create_task(
                text=f"{body_stmt.step_id}: DO {body_stmt.command}"
                f" [LOOP iteration {iteration}]",
                creator="coordinator",
            )
            task_id = task.id

            self.store.append_batch(run_id, [
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "task_created", "id": task_id,
                        "text": task.text,
                        "priority": task.priority, "parent": task.parent,
                        "dependencies": task.dependencies,
                        "creator": task.creator,
                    },
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={"kind": "task_started", "id": task_id},
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.INVOCATION_READY,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={"command": body_stmt.command},
                    store=self.store,
                ),
            ])

            # Resolve arguments
            try:
                resolved_kwargs: dict[str, Any] = {}
                for arg in body_stmt.args:
                    self._reject_unresolved_refs(arg.value, values)
                    if isinstance(arg.value, str) and arg.value in values:
                        resolved_kwargs[arg.name] = values[arg.value]
                    elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                        resolved_kwargs[arg.name] = self._resolve_kb_ref(arg.value)
                    elif isinstance(arg.value, list):
                        resolved_kwargs[arg.name] = [
                            values[item] if isinstance(item, str) and item in values
                            else self._resolve_kb_ref(item)
                            if isinstance(item, str) and item.startswith("KB.")
                            else item
                            for item in arg.value
                        ]
                    else:
                        resolved_kwargs[arg.name] = arg.value
            except Exception as exc:
                failed = True
                error_msg = str(exc)
                finish_failed_invocation = lambda idx, iid, vid, tid, err: None
                records = _finalize.fail_invocation(
                    self.store, run_id, plan, statement_to_task,
                    0, instruction_id, invocation_id, task_id, error_msg,
                )
                self.store.append_batch(run_id, records)
                return {"run_id": run_id, "status": "failed", "error": error_msg, "outputs": {}}

            dispatch_root = branch_root or self.workspace_root
            if (
                dispatch_root is not None
                and body_stmt.command in _effectful_commands()
            ):
                resolved_kwargs["_workspace_root"] = dispatch_root

            self.store.append(
                run_id,
                EventType.INVOCATION_DISPATCHED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={
                    "args": resolved_kwargs,
                    "idempotency_key": f"{run_id}:{invocation_id}",
                },
            )

            try:
                result = self._execute_worker_call(
                    body_stmt.command, resolved_kwargs, gate
                )
            except Exception as exc:
                records = _finalize.fail_invocation(
                    self.store, run_id, plan, statement_to_task,
                    0, instruction_id, invocation_id, task_id, str(exc),
                )
                self.store.append_batch(run_id, records)
                return {"run_id": run_id, "status": "failed", "error": str(exc), "outputs": {}}

            self.store.append(
                run_id,
                EventType.RESULT_RECEIVED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={"result": result},
            )

            target_values, validation_error = map_results_to_targets(
                body_stmt.targets, result
            )
            if validation_error is not None:
                records = _finalize.fail_invocation(
                    self.store, run_id, plan, statement_to_task,
                    0, instruction_id, invocation_id, task_id, validation_error,
                )
                self.store.append_batch(run_id, records)
                return {"run_id": run_id, "status": "failed", "error": validation_error, "outputs": {}}

            self.store.append(
                run_id,
                EventType.VALIDATION_PASSED,
                instruction_id=instruction_id,
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

            self.store.append_batch(run_id, [
                _Record(
                    event_type=EventType.SUCCEEDED,
                    instruction_id=instruction_id,
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
                        "evidence": f"{body_stmt.command} -> {body_stmt.targets}",
                    },
                    store=self.store,
                ),
            ])
            return None

        if isinstance(body_stmt, Conditional):
            try:
                fired = evaluate_condition(body_stmt.condition, values)
            except ValueError as exc:
                return self._fail_run(
                    run_id, plan, statement_to_task, 0, str(exc)
                )
            if fired:
                embedded = body_stmt.statement
                if isinstance(embedded, Stop):
                    return self._terminal_stop(run_id, embedded, values)
                if isinstance(embedded, Return):
                    return self._terminal_return(run_id, embedded.refs, values)
                if isinstance(embedded, Invocation):
                    return self._execute_loop_body_statement(
                        embedded, program, run_id, loop_invocation_id,
                        iteration, values, plan, statement_to_task,
                        crash_hook, gate, claims, branch_root,
                    )
            return None

        return None

    # ------------------------------------------------------------------
    # TRY execution (issue #69)
    # ------------------------------------------------------------------

    def _execute_try_entry(
        self,
        program: Program,
        run_id: str,
        entry: "_PlanEntry",
        idx: int,
        invocation_id: str,
        values: dict[str, Any],
        plan: list["_PlanEntry"],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
    ) -> dict[str, Any] | None:
        """Execute one TRY plan entry (issue #69): speculative dispatch.

        All branches dispatch concurrently (bounded by ``max_count``);
        the first branch to reach SUCCEEDED wins.  Other branches are
        cancelled.  If all branches fail, the TRY fails with a composite
        failure.  The winning branch's committed nodes are adopted into
        the parent run's state.

        Each branch executes as an isolated child run (like PAR branches)
        via ``_execute_program_child``.  The branch's DO invocations run
        in a synthetic child program whose INPUT declarations carry the
        parent state refs the branch reads.
        """
        try_block = entry.try_
        assert try_block is not None
        instruction_id = f"try.inv-{idx + 1}"
        branch_count = len(try_block.branches)
        max_at_once = try_block.max_count or branch_count
        max_at_once = max(1, min(max_at_once, branch_count))

        self.store.append(
            run_id,
            EventType.TRY_STARTED,
            invocation_id=invocation_id,
            payload={
                "branches": branch_count,
                "max": try_block.max_count,
            },
        )

        # Collect all targets across all branches (for adoption)
        all_branch_targets: list[tuple[str, ...]] = []
        for branch_body in try_block.branches:
            branch_targets: list[str] = []
            for stmt in branch_body:
                if isinstance(stmt, Invocation):
                    branch_targets.extend(stmt.targets)
                elif hasattr(stmt, 'targets') and isinstance(stmt.targets, tuple):
                    branch_targets.extend(stmt.targets)
            all_branch_targets.append(tuple(branch_targets))

        # Build synthetic child programs and seed values for each branch
        branch_programs: list[Program] = []
        branch_child_values: list[dict[str, Any]] = []
        for i, branch_body in enumerate(try_block.branches):
            child_prog, child_vals = self._build_try_branch_program(
                branch_body, values, f"try_branch_{i}"
            )
            branch_programs.append(child_prog)
            branch_child_values.append(child_vals)

        # Dispatch branches concurrently
        base = branch_root if branch_root is not None else self.workspace_root
        import concurrent.futures

        in_flight: dict[int, concurrent.futures.Future] = {}
        branch_results: dict[int, dict[str, Any]] = {}
        branch_statuses: dict[int, str] = {}

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_at_once
        ) as pool:
            for i, child_prog in enumerate(branch_programs):
                child_run_id = f"{run_id}:{invocation_id}.try{i + 1}"
                if gate is not None and gate.depth_exceeded(child_run_id):
                    return self._fail_run(
                        run_id, plan, statement_to_task, idx,
                        f"TRY branch {i + 1} depth exceeds budget",
                    )
                future = pool.submit(
                    self._execute_program_child,
                    child_prog,
                    child_run_id,
                    run_id,
                    f"try:{invocation_id}.try{i + 1}",
                    branch_child_values[i],
                    gate,
                    claims,
                    base,
                    None,
                )
                in_flight[i] = future

            # Wait for first SUCCEEDED or all FAILED
            winner: int | None = None
            while in_flight:
                owner = {f: i for i, f in in_flight.items()}
                done, _ = concurrent.futures.wait(
                    list(in_flight.values()),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    i = owner[future]
                    del in_flight[i]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {
                            "status": "failed",
                            "error": str(exc),
                            "outputs": {},
                        }
                    child_status = result.get("status", "unknown")
                    branch_results[i] = result
                    branch_statuses[i] = child_status
                    if child_status == "succeeded" and winner is None:
                        winner = i
                        self.store.append(
                            run_id,
                            EventType.TRY_BRANCH_SUCCEEDED,
                            invocation_id=invocation_id,
                            payload={"branch": i + 1},
                        )
                if winner is not None:
                    break

        # Cancel remaining branches
        for i in range(branch_count):
            if i == winner:
                continue
            if i in in_flight:
                in_flight[i].cancel()
            self.store.append(
                run_id,
                EventType.TRY_BRANCH_CANCELLED,
                invocation_id=invocation_id,
                payload={"branch": i + 1, "status": branch_statuses.get(i, "cancelled")},
            )

        if winner is None:
            # All branches failed
            errors = [
                f"branch {i + 1}: {branch_results.get(i, {}).get('error', 'unknown')}"
                for i in range(branch_count)
            ]
            composite_error = "; ".join(errors)
            self.store.append(
                run_id,
                EventType.TRY_COMPLETED,
                invocation_id=invocation_id,
                payload={"status": "failed", "branches": branch_statuses},
            )
            return self._fail_run(
                run_id, plan, statement_to_task, idx,
                f"TRY failed: all {branch_count} branches failed:"
                f" {composite_error}",
            )

        # Adopt the winner's outputs from committed child state
        winner_run_id = f"{run_id}:{invocation_id}.try{winner + 1}"
        winner_targets = all_branch_targets[winner]
        child_values_dict: dict[str, Any] = {}
        adopted_nodes, _ = self._adopt_branch_nodes(
            winner_run_id, child_values_dict, winner_targets,
        )
        for node in adopted_nodes:
            values[node["id"]] = node["value"]

        self.store.append(
            run_id,
            EventType.TRY_COMPLETED,
            invocation_id=invocation_id,
            payload={
                "status": "succeeded",
                "winner": winner + 1,
                "branches": branch_statuses,
            },
        )

        expected_sv = self.store._current_state_version(run_id)
        delta = StateDelta(add_nodes=tuple(adopted_nodes))
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                expected_state_version=expected_sv,
                payload={"delta": delta},
                store=self.store,
            ),
        ])
        return None

    def _build_try_branch_program(
        self,
        branch_body: tuple,
        values: dict[str, Any],
        name: str,
    ) -> tuple[Program, dict[str, Any]]:
        """Build a synthetic child program for one TRY branch (issue #69).

        Each branch body is a tuple of statements (invocations, conditionals,
        calls, stops, returns).  We build a minimal Program wrapping them
        with INPUT declarations seeded from the parent state refs the branch
        reads, and RETURN of all targets produced by the branch's invocations.

        Returns ``(program, child_values)`` where ``child_values`` is the
        initial state mapping for the child run.
        """
        from tahoe.syntax.model import Declaration

        # Collect all targets from invocations in the branch
        targets: list[str] = []
        for stmt in branch_body:
            if isinstance(stmt, Invocation):
                targets.extend(stmt.targets)

        # Collect all refs the branch reads (from invocation args)
        from tahoe.runtime.planning import scan_arg_refs
        read_refs: set[str] = set()
        for stmt in branch_body:
            if isinstance(stmt, Invocation):
                for arg in stmt.args:
                    read_refs |= scan_arg_refs(arg.value)
            elif isinstance(stmt, Conditional):
                from tahoe.runtime.planning import condition_refs
                read_refs |= condition_refs(stmt.condition)

        # Build INPUT declarations for refs that exist in parent state
        declarations: list[Declaration] = []
        child_values: dict[str, Any] = {}
        for ref in sorted(read_refs):
            if ref in values:
                declarations.append(Declaration(ref, values[ref]))
                child_values[ref] = values[ref]

        # Check for explicit RETURN/STOP in the branch
        has_terminal = any(
            isinstance(stmt, (Return, Stop)) for stmt in branch_body
        )

        statements: list = list(branch_body)
        if not has_terminal and targets:
            statements.append(Return(tuple(targets)))

        return Program(
            name=name,
            version="1.0",
            declarations=tuple(declarations),
            statements=tuple(statements),
        ), child_values

    # ------------------------------------------------------------------
    # Concurrent execution frontier (issue #21)
    # REFORMULATE execution (issue #80)
    # ------------------------------------------------------------------

    _MAX_REFORMULATIONS = 3

    def _execute_reformulate_entry(
        self,
        program: Program,
        run_id: str,
        entry: "_PlanEntry",
        idx: int,
        invocation_id: str,
        values: dict[str, Any],
        plan: list["_PlanEntry"],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
    ) -> dict[str, Any] | None:
        """Execute one REFORMULATE block (issue #80).

        1. Execute the DIAGNOSE step (standard DO dispatch).
        2. For each REVISE pair: retire old_ref, create new_ref with the
           old ref's value as a starting point.
        3. Execute the REPLAN step — this produces a child plan (like
           delegate, but inherits parent state).
        4. Record PLAN_REFORMULATED event.
        5. Replace the remaining plan entries with the new plan's entries.
        6. Continue execution from the first entry of the new plan.

        The key difference from ``delegate``: the child plan inherits
        committed state (not isolated).  The child plan's INPUT is
        auto-populated from current committed refs.  The child plan
        REPLACES the remaining steps of the parent.

        Bounded: max 3 reformulations per run.
        """
        reformulate = entry.reformulate
        assert reformulate is not None

        # Enforce the reformulation cap
        reformulation_count = sum(
            1
            for event in self.store.events(run_id)
            if event.event_type is EventType.PLAN_REFORMULATED
        )
        if reformulation_count >= self._MAX_REFORMULATIONS:
            error_msg = (
                f"max reformulations ({self._MAX_REFORMULATIONS}) exceeded"
                f" for run {run_id}"
            )
            return self._fail_run(
                run_id, plan, statement_to_task, idx, error_msg
            )

        # -- Step 1: DIAGNOSE (standard DO dispatch) -------------------
        diagnose = reformulate.diagnose
        diag_invocation_id = f"{invocation_id}.diagnose"
        diag_task_id = self._create_single_plan_task(
            run_id,
            _planning.PlanEntry(invocation=diagnose),
        )

        try:
            diag_resolved_kwargs: dict[str, Any] = {}
            for arg in diagnose.args:
                self._reject_unresolved_refs(arg.value, values)
                if isinstance(arg.value, str) and arg.value in values:
                    diag_resolved_kwargs[arg.name] = values[arg.value]
                elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                    diag_resolved_kwargs[arg.name] = self._resolve_kb_ref(arg.value)
                elif isinstance(arg.value, list):
                    diag_resolved_kwargs[arg.name] = [
                        values[item] if isinstance(item, str) and item in values
                        else self._resolve_kb_ref(item)
                        if isinstance(item, str) and item.startswith("KB.")
                        else item
                        for item in arg.value
                    ]
                else:
                    diag_resolved_kwargs[arg.name] = arg.value
        except Exception as exc:
            error_msg = str(exc)
            records = _finalize.fail_invocation(
                self.store, run_id, plan, statement_to_task,
                idx, diagnose.step_id, diag_invocation_id, diag_task_id, error_msg,
            )
            self.store.append_batch(run_id, records)
            return {"run_id": run_id, "status": "failed", "error": error_msg, "outputs": {}}

        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=diag_task_id,
                payload={"kind": "task_started", "id": diag_task_id},
                store=self.store,
            ),
            _Record(
                event_type=EventType.INVOCATION_READY,
                instruction_id=diagnose.step_id,
                invocation_id=diag_invocation_id,
                task_id=diag_task_id,
                payload={"command": diagnose.command},
                store=self.store,
            ),
            _Record(
                event_type=EventType.INVOCATION_DISPATCHED,
                instruction_id=diagnose.step_id,
                invocation_id=diag_invocation_id,
                task_id=diag_task_id,
                payload={
                    "args": diag_resolved_kwargs,
                    "idempotency_key": f"{run_id}:{diag_invocation_id}",
                },
                store=self.store,
            ),
        ])

        try:
            diag_result = self._execute_worker_call(
                diagnose.command, diag_resolved_kwargs, gate
            )
        except Exception as exc:
            error_msg = str(exc)
            records = _finalize.fail_invocation(
                self.store, run_id, plan, statement_to_task,
                idx, diagnose.step_id, diag_invocation_id, diag_task_id, error_msg,
            )
            self.store.append_batch(run_id, records)
            return {"run_id": run_id, "status": "failed", "error": error_msg, "outputs": {}}

        diag_targets, diag_error = map_results_to_targets(
            diagnose.targets, diag_result
        )
        if diag_error is not None:
            records = _finalize.fail_invocation(
                self.store, run_id, plan, statement_to_task,
                idx, diagnose.step_id, diag_invocation_id, diag_task_id, diag_error,
            )
            self.store.append_batch(run_id, records)
            return {"run_id": run_id, "status": "failed", "error": diag_error, "outputs": {}}

        self.store.append(run_id, EventType.RESULT_RECEIVED,
            instruction_id=diagnose.step_id,
            invocation_id=diag_invocation_id,
            task_id=diag_task_id,
            payload={"result": diag_result},
        )
        self.store.append(run_id, EventType.VALIDATION_PASSED,
            instruction_id=diagnose.step_id,
            invocation_id=diag_invocation_id,
            task_id=diag_task_id,
            payload={},
        )

        diag_add_nodes: list[dict[str, Any]] = []
        for target, val in diag_targets.items():
            values[target] = val
            diag_add_nodes.append({"id": target, "value": val})
        diag_delta = StateDelta(add_nodes=tuple(diag_add_nodes))
        expected_sv = self.store._current_state_version(run_id)
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=diagnose.step_id,
                invocation_id=diag_invocation_id,
                task_id=diag_task_id,
                expected_state_version=expected_sv,
                payload={"delta": diag_delta},
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=diag_task_id,
                payload={
                    "kind": "invocation_recorded", "id": diag_task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=diag_task_id,
                payload={
                    "kind": "task_completed", "id": diag_task_id,
                    "evidence": f"DIAGNOSE {diagnose.command} -> {diagnose.targets}",
                },
                store=self.store,
            ),
        ])

        # -- Step 2: REVISE (retire old refs, create new refs) ----------
        revise_nodes: list[dict[str, Any]] = []
        retire_nodes: list[str] = []
        for old_ref, new_ref in reformulate.revise:
            old_value = values.get(old_ref)
            retire_nodes.append(old_ref)
            values.pop(old_ref, None)
            values[new_ref] = old_value
            revise_nodes.append({"id": new_ref, "value": old_value})

        if revise_nodes or retire_nodes:
            revise_delta = StateDelta(
                add_nodes=tuple(revise_nodes),
                retire_nodes=tuple(retire_nodes),
            )
            expected_sv = self.store._current_state_version(run_id)
            self.store.append(run_id, EventType.SUCCEEDED,
                instruction_id="REFORMULATE:REVISE",
                invocation_id=invocation_id,
                expected_state_version=expected_sv,
                payload={"delta": revise_delta},
            )

        # -- Step 3: REPLAN (produce a new sub-plan) --------------------
        replan = reformulate.replan
        replan_invocation_id = f"{invocation_id}.replan"
        replan_task_id = self._create_single_plan_task(
            run_id,
            _planning.PlanEntry(invocation=replan),
        )

        try:
            replan_resolved_kwargs: dict[str, Any] = {}
            for arg in replan.args:
                self._reject_unresolved_refs(arg.value, values)
                if isinstance(arg.value, str) and arg.value in values:
                    replan_resolved_kwargs[arg.name] = values[arg.value]
                elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                    replan_resolved_kwargs[arg.name] = self._resolve_kb_ref(arg.value)
                elif isinstance(arg.value, list):
                    replan_resolved_kwargs[arg.name] = [
                        values[item] if isinstance(item, str) and item in values
                        else self._resolve_kb_ref(item)
                        if isinstance(item, str) and item.startswith("KB.")
                        else item
                        for item in arg.value
                    ]
                else:
                    replan_resolved_kwargs[arg.name] = arg.value
        except Exception as exc:
            error_msg = str(exc)
            records = _finalize.fail_invocation(
                self.store, run_id, plan, statement_to_task,
                idx, replan.step_id, replan_invocation_id, replan_task_id, error_msg,
            )
            self.store.append_batch(run_id, records)
            return {"run_id": run_id, "status": "failed", "error": error_msg, "outputs": {}}

        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=replan_task_id,
                payload={"kind": "task_started", "id": replan_task_id},
                store=self.store,
            ),
            _Record(
                event_type=EventType.INVOCATION_READY,
                instruction_id=replan.step_id,
                invocation_id=replan_invocation_id,
                task_id=replan_task_id,
                payload={"command": replan.command},
                store=self.store,
            ),
            _Record(
                event_type=EventType.INVOCATION_DISPATCHED,
                instruction_id=replan.step_id,
                invocation_id=replan_invocation_id,
                task_id=replan_task_id,
                payload={
                    "args": replan_resolved_kwargs,
                    "idempotency_key": f"{run_id}:{replan_invocation_id}",
                },
                store=self.store,
            ),
        ])

        try:
            replan_result = self._execute_worker_call(
                replan.command, replan_resolved_kwargs, gate
            )
        except Exception as exc:
            error_msg = str(exc)
            records = _finalize.fail_invocation(
                self.store, run_id, plan, statement_to_task,
                idx, replan.step_id, replan_invocation_id, replan_task_id, error_msg,
            )
            self.store.append_batch(run_id, records)
            return {"run_id": run_id, "status": "failed", "error": error_msg, "outputs": {}}

        replan_targets, replan_error = map_results_to_targets(
            replan.targets, replan_result
        )
        if replan_error is not None:
            records = _finalize.fail_invocation(
                self.store, run_id, plan, statement_to_task,
                idx, replan.step_id, replan_invocation_id, replan_task_id, replan_error,
            )
            self.store.append_batch(run_id, records)
            return {"run_id": run_id, "status": "failed", "error": replan_error, "outputs": {}}

        self.store.append(run_id, EventType.RESULT_RECEIVED,
            instruction_id=replan.step_id,
            invocation_id=replan_invocation_id,
            task_id=replan_task_id,
            payload={"result": replan_result},
        )
        self.store.append(run_id, EventType.VALIDATION_PASSED,
            instruction_id=replan.step_id,
            invocation_id=replan_invocation_id,
            task_id=replan_task_id,
            payload={},
        )

        replan_add_nodes: list[dict[str, Any]] = []
        for target, val in replan_targets.items():
            values[target] = val
            replan_add_nodes.append({"id": target, "value": val})
        replan_delta = StateDelta(add_nodes=tuple(replan_add_nodes))
        expected_sv = self.store._current_state_version(run_id)
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=replan.step_id,
                invocation_id=replan_invocation_id,
                task_id=replan_task_id,
                expected_state_version=expected_sv,
                payload={"delta": replan_delta},
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=replan_task_id,
                payload={
                    "kind": "invocation_recorded", "id": replan_task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=replan_task_id,
                payload={
                    "kind": "task_completed", "id": replan_task_id,
                    "evidence": f"REPLAN {replan.command} -> {replan.targets}",
                },
                store=self.store,
            ),
        ])

        # -- Step 4: Record PLAN_REFORMULATED --------------------------
        continue_ref = reformulate.continue_ref
        if continue_ref not in replan_targets:
            error_msg = (
                f"REFORMULATE CONTINUE ref {continue_ref} was not produced"
                f" by the REPLAN step (targets: {list(replan.targets)})"
            )
            records = _finalize.fail_invocation(
                self.store, run_id, plan, statement_to_task,
                idx, "REFORMULATE", invocation_id,
                statement_to_task.get(idx, ""), error_msg,
            )
            self.store.append_batch(run_id, records)
            return {"run_id": run_id, "status": "failed", "error": error_msg, "outputs": {}}

        new_plan_value = replan_targets[continue_ref]
        revised_refs_list = [
            {"old": old, "new": new}
            for old, new in reformulate.revise
        ]
        preserved_refs = sorted(
            ref for ref in values
            if ref.startswith("G.")
        )

        from tahoe.syntax.parser import canonical_json as _canon_json
        import json as _json
        if isinstance(new_plan_value, str):
            new_plan_digest = hashlib.sha256(
                new_plan_value.encode("utf-8")
            ).hexdigest()
        elif isinstance(new_plan_value, (list, dict)):
            new_plan_digest = hashlib.sha256(
                _json.dumps(new_plan_value, sort_keys=True,
                            default=str).encode("utf-8")
            ).hexdigest()
        else:
            new_plan_digest = hashlib.sha256(
                _canon_json(program).encode("utf-8")
            ).hexdigest()

        self.store.append(
            run_id,
            EventType.PLAN_REFORMULATED,
            invocation_id=invocation_id,
            payload={
                "trigger_step": invocation_id,
                "diagnosis_ref": diag_targets,
                "revised_refs": revised_refs_list,
                "new_plan_ref": continue_ref,
                "new_plan_digest": new_plan_digest,
                "preserved_refs": preserved_refs,
                "reformulation_count": reformulation_count + 1,
            },
        )

        # -- Step 5: Replace remaining plan with new plan -------------
        # The new plan is the value produced by the REPLAN step.
        # We create new plan entries from the new plan value.
        # For the deterministic test harness, the new plan value is
        # a list of step definitions that get converted to PlanEntry.
        new_entries: list[_PlanEntry] = []
        if isinstance(new_plan_value, list):
            for step_def in new_plan_value:
                if isinstance(step_def, dict):
                    step_id = step_def.get("step_id", "step.reformulated")
                    command = step_def.get("command", "define")
                    args_list = step_def.get("args", [])
                    targets_list = step_def.get("targets", [])
                    from tahoe.syntax.model import Argument
                    args_tuple = tuple(
                        Argument(a["name"], a["value"])
                        for a in args_list
                    )
                    new_invocation = Invocation(
                        step_id=step_id,
                        command=command,
                        args=args_tuple,
                        targets=tuple(targets_list),
                    )
                    new_entries.append(
                        _planning.PlanEntry(invocation=new_invocation)
                    )
        elif isinstance(new_plan_value, str):
            try:
                new_program = parse_program_text(new_plan_value)
                new_entries = _planning.build_plan(new_program)
            except Exception:
                pass

        # If no new entries were created, create a simple pass-through
        if not new_entries:
            new_entries = [
                _planning.PlanEntry(
                    invocation=Invocation(
                        step_id="step.reformulated_continue",
                        command="define",
                        args=(),
                        targets=("G.reformulated_result",),
                    )
                )
            ]

        # Cancel remaining tasks after this entry
        self._cancel_pending_after(
            run_id, plan, statement_to_task, idx + 1
        )

        # Replace remaining plan entries with new entries
        plan[idx + 1:] = new_entries

        # Create tasks for new entries
        for new_idx, new_entry in enumerate(new_entries):
            plan_idx = idx + 1 + new_idx
            if plan_idx in statement_to_task:
                continue
            if new_entry.invocation is not None:
                new_task_id = self._create_single_plan_task(run_id, new_entry)
                statement_to_task[plan_idx] = new_task_id

        return None

    _TYPED_REF_CANDIDATE_RE = _planning._TYPED_REF_CANDIDATE_RE

    # ------------------------------------------------------------------
    # FIRST execution (issue #76)
    # ------------------------------------------------------------------

    def _execute_first_entry(
        self,
        program: Program,
        run_id: str,
        entry: "_PlanEntry",
        idx: int,
        invocation_id: str,
        values: dict[str, Any],
        plan: list["_PlanEntry"],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
    ) -> dict[str, Any] | None:
        """Execute one FIRST event-choice block (issue #76).

        The FIRST construct subscribes to a set of event selectors and
        waits for the first one to fire.  When an event matches a
        selector, the remaining selectors are cancelled and the body
        statements execute sequentially (reusing the LOOP body execution
        path).  A FIRST_EVENT_MATCHED event records which selector fired.

        Event selectors are simple string patterns of the form
        ``event_name`` or ``event_name(args)`` — a name with optional
        parenthesised arguments.  Matching is by event type name: an
        incoming event whose type matches the selector's name fires
        that selector.

        For the deterministic test harness, events are injected via
        the EventStore before execution — the coordinator scans the
        run's event history for matching events.  If no event matches,
        the FIRST block blocks (returns None, leaving the run
        non-terminal); if exactly one matches, the body executes.
        """
        first = entry.first
        assert first is not None

        # Scan the run's event history for a matching event
        events = self.store.events(run_id)
        matched_selector: int | None = None
        matched_event = None
        for selector_idx, selector in enumerate(first.selectors):
            selector_name = selector.split("(")[0].strip()
            for event in events:
                event_type_name = event.event_type.value
                if event_type_name == selector_name or event_type_name.startswith(selector_name + "."):
                    matched_selector = selector_idx
                    matched_event = event
                    break
            if matched_selector is not None:
                break

        if matched_selector is None:
            # No matching event found — block the run
            self.store.append(
                run_id,
                EventType.BLOCKED,
                invocation_id=invocation_id,
                payload={
                    "selectors": list(first.selectors),
                    "reason": "no matching event",
                },
            )
            return self._fail_run(
                run_id, plan, statement_to_task, idx,
                "FIRST: no matching event for any selector",
            )

        # Record FIRST_EVENT_MATCHED
        self.store.append(
            run_id,
            EventType.FIRST_EVENT_MATCHED,
            invocation_id=invocation_id,
            payload={
                "selector_index": matched_selector,
                "selector": first.selectors[matched_selector],
                "event_type": matched_event.event_type.value
                if matched_event
                else None,
            },
        )

        # Execute body statements sequentially (reuse LOOP body path for
        # DO invocations; handle STOP/RETURN directly to avoid cancelling
        # already-completed tasks from earlier plan entries).
        for body_stmt in first.body:
            if isinstance(body_stmt, Stop):
                return self._terminal_stop(run_id, body_stmt, values)
            if isinstance(body_stmt, Return):
                return self._terminal_return(run_id, body_stmt.refs, values)
            result = self._execute_loop_body_statement(
                body_stmt,
                program,
                run_id,
                invocation_id,
                1,  # iteration = 1
                values,
                plan,
                statement_to_task,
                crash_hook,
                gate,
                claims,
                branch_root,
            )
            if result is not None:
                return result

        # Record SUCCEEDED for the FIRST entry
        expected_sv = self.store._current_state_version(run_id)
        self.store.append(
            run_id,
            EventType.SUCCEEDED,
            invocation_id=invocation_id,
            expected_state_version=expected_sv,
            payload={"delta": StateDelta()},
        )
        return None

    # ------------------------------------------------------------------
    # AWAIT execution (issue #77)
    # ------------------------------------------------------------------

    def _execute_await_entry(
        self,
        program: Program,
        run_id: str,
        entry: "_PlanEntry",
        idx: int,
        invocation_id: str,
        values: dict[str, Any],
        plan: list["_PlanEntry"],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
    ) -> dict[str, Any] | None:
        """Execute an AWAIT statement (issue #77).

        Records AWAIT_SUSPENDED with the event selector and optional
        timeout, then blocks the run (returns a "blocked" result without
        appending RUN_FINISHED — the run is non-terminal).  On resume,
        checks for a matching event in the event store; if found,
        records AWAIT_RESUMED and continues.  If a timeout was set and
        no event arrived, records AWAIT_RESUMED with reason "timeout"
        and continues without the event.  If neither, re-blocks.
        """
        await_stmt = entry.await_
        assert await_stmt is not None
        selector = await_stmt.selector
        timeout = await_stmt.timeout

        # On resume, check if AWAIT_SUSPENDED was already recorded.
        events = self.store.events(run_id)
        existing_suspended = [
            e for e in events
            if e.event_type is EventType.AWAIT_SUSPENDED
            and e.invocation_id == invocation_id
        ]

        if not existing_suspended:
            # First pass: record suspension and block the run.
            self.store.append(
                run_id,
                EventType.AWAIT_SUSPENDED,
                invocation_id=invocation_id,
                payload={
                    "selector": selector,
                    "timeout": timeout,
                },
            )
            return {
                "run_id": run_id,
                "status": "blocked",
                "reason": "await",
                "selector": selector,
                "outputs": {},
            }

        # Resume: check for a matching event or timeout.
        suspended_event = existing_suspended[-1]
        suspended_payload = suspended_event.payload or {}
        suspended_selector = suspended_payload.get("selector", selector)
        suspended_timeout = suspended_payload.get("timeout", timeout)

        # Check for matching events recorded after AWAIT_SUSPENDED.
        # External events are stored as EXTERNAL_EVENT with a payload
        # carrying the selector string; the match is on that payload field.
        suspended_seq = suspended_event.seq
        matching_events = [
            e for e in events
            if e.seq > suspended_seq
            and e.event_type is EventType.EXTERNAL_EVENT
            and isinstance(e.payload, dict)
            and e.payload.get("selector") == suspended_selector
        ]

        timed_out = False
        if suspended_timeout:
            deadline = self._parse_timeout(suspended_timeout)
            if deadline is not None:
                from datetime import datetime, timezone
                suspended_ts = suspended_event.occurred_at
                elapsed = (datetime.now(timezone.utc) - suspended_ts).total_seconds()
                if elapsed >= deadline:
                    timed_out = True

        if matching_events:
            match_event = matching_events[0]
            self.store.append(
                run_id,
                EventType.AWAIT_RESUMED,
                invocation_id=invocation_id,
                payload={
                    "reason": "event",
                    "selector": suspended_selector,
                    "matched_seq": match_event.seq,
                },
            )
            return None  # continue to next plan entry
        elif timed_out:
            self.store.append(
                run_id,
                EventType.AWAIT_RESUMED,
                invocation_id=invocation_id,
                payload={
                    "reason": "timeout",
                    "selector": suspended_selector,
                },
            )
            return None  # continue to next plan entry
        else:
            # No event and no timeout: re-block.
            return {
                "run_id": run_id,
                "status": "blocked",
                "reason": "await",
                "selector": suspended_selector,
                "outputs": {},
            }

    # ------------------------------------------------------------------
    # APPROVE execution (issue #78)
    # ------------------------------------------------------------------

    def _execute_approve_entry(
        self,
        program: Program,
        run_id: str,
        entry: "_PlanEntry",
        idx: int,
        invocation_id: str,
        values: dict[str, Any],
        plan: list["_PlanEntry"],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
    ) -> dict[str, Any] | None:
        """Execute an APPROVE statement (issue #78).

        Computes an SHA-256 digest of the intent expression, records
        APPROVAL_REQUESTED with {policy_ref, intent_digest, step_index},
        and blocks the run (RUN_FINISHED with status "blocked" and
        reason "approve").  On resume, checks for APPROVAL_GRANTED or
        APPROVAL_DENIED events recorded after the suspension:

        - APPROVAL_GRANTED: verifies the grant's ``intent_digest`` matches
          the request's; on mismatch the run fails.  On match, continues
          to the next plan entry.
        - APPROVAL_DENIED: records RUN_FINISHED with status "denied" and
          stops the run.
        - Neither found: re-blocks the run.
        """
        approve_stmt = entry.approve
        assert approve_stmt is not None
        policy_ref = approve_stmt.policy
        intent_expr = approve_stmt.intent

        intent_digest = hashlib.sha256(intent_expr.encode("utf-8")).hexdigest()

        # On resume, check if APPROVAL_REQUESTED was already recorded.
        events = self.store.events(run_id)
        existing_requested = [
            e for e in events
            if e.event_type is EventType.APPROVAL_REQUESTED
            and e.invocation_id == invocation_id
        ]

        if not existing_requested:
            # First pass: record the approval request and block the run.
            self.store.append(
                run_id,
                EventType.APPROVAL_REQUESTED,
                invocation_id=invocation_id,
                payload={
                    "policy_ref": policy_ref,
                    "intent": intent_expr,
                    "intent_digest": intent_digest,
                    "step_index": idx,
                },
            )
            self.store.append(
                run_id,
                EventType.RUN_FINISHED,
                payload={
                    "status": "blocked",
                    "reason": "approve",
                    "policy_ref": policy_ref,
                    "intent_digest": intent_digest,
                },
            )
            return {
                "run_id": run_id,
                "status": "blocked",
                "reason": "approve",
                "policy_ref": policy_ref,
                "intent_digest": intent_digest,
                "outputs": {},
            }
        else:
            # Resume: check for APPROVAL_GRANTED or APPROVAL_DENIED.
            request_event = existing_requested[-1]
            request_payload = request_event.payload or {}
            request_digest = request_payload.get("intent_digest", intent_digest)
            request_seq = request_event.seq

            granted_events = [
                e for e in events
                if e.seq > request_seq
                and e.event_type is EventType.APPROVAL_GRANTED
                and e.invocation_id == invocation_id
            ]
            denied_events = [
                e for e in events
                if e.seq > request_seq
                and e.event_type is EventType.APPROVAL_DENIED
                and e.invocation_id == invocation_id
            ]

            if granted_events:
                grant_event = granted_events[-1]
                grant_payload = grant_event.payload or {}
                grant_digest = grant_payload.get("intent_digest")
                if grant_digest != request_digest:
                    return self._fail_run(
                        run_id, plan, statement_to_task, idx,
                        "APPROVAL_GRANTED digest mismatch: approval was"
                        " for a different intent",
                    )
                # Digest matches: continue to next plan entry.
                return None

            if denied_events:
                # Approval denied: stop the run with "denied" status.
                self.store.append(
                    run_id,
                    EventType.RUN_FINISHED,
                    payload={
                        "status": "denied",
                        "reason": "approval denied",
                        "policy_ref": policy_ref,
                    },
                )
                return {
                    "run_id": run_id,
                    "status": "denied",
                    "reason": "approval denied",
                    "outputs": {},
                }

            # No grant or denial yet: re-block.
            self.store.append(
                run_id,
                EventType.RUN_FINISHED,
                payload={
                    "status": "blocked",
                    "reason": "approve",
                    "policy_ref": policy_ref,
                    "intent_digest": request_digest,
                },
            )
            return {
                "run_id": run_id,
                "status": "blocked",
                "reason": "approve",
                "policy_ref": policy_ref,
                "intent_digest": request_digest,
                "outputs": {},
            }

    @staticmethod
    def _scan_arg_refs(value: Any) -> frozenset[str]:
        """Typed refs an argument value reads (issue #21 DAG input)."""
        return _planning.scan_arg_refs(value)

    def _condition_refs(self, condition: str) -> frozenset[str]:
        """Refs an IF condition reads (issue #21 DAG input)."""
        return _planning.condition_refs(condition)

    def _entry_refs(
        self, entry: _PlanEntry
    ) -> tuple[frozenset[str], frozenset[str]]:
        """The refs one plan entry reads and writes (issue #21)."""
        return _planning.entry_refs(entry)

    @staticmethod
    def _refs_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
        """Whether two ref sets touch (field-selection aware, issue #21)."""
        return _planning.refs_overlap(a, b)

    def _build_dependency_dag(
        self, plan: list[_PlanEntry]
    ) -> list[frozenset[int]]:
        """Plan index -> indices that must be terminal before it dispatches."""
        return _planning.build_dependency_dag(plan)

    def _drive_plan_concurrent(
        self,
        program: Program,
        run_id: str,
        plan: list[_PlanEntry],
        values: dict[str, Any],
        statement_to_task: dict[int, str],
        *,
        initial_terminal: frozenset[int] = frozenset(),
        crash_hook: "Callable[[int], None] | None" = None,
        max_workers: int = 2,
        gate: "BudgetGate | None" = None,
        claims: "ResourceLedger | None" = None,
    ) -> dict[str, Any]:
        """Drive the plan through a ready-task frontier (issue #21).

        Ready = every plan entry sharing a ref with this one is already
        terminal (dependency DAG from ref usage) and every source-anchored
        conditional at or before its position is evaluated.  Ready
        entries dispatch in stable plan order onto a thread pool; the
        pool executes worker handlers and CALL child runs only — every
        commit (READY, DISPATCHED, RESULT_RECEIVED, the atomic SUCCEEDED
        batch, failures) happens on the coordinator's single-writer
        path in this thread, so the event shapes per invocation are
        identical to the sequential loop and the run's CAS state
        versions stay uncontended.

        Conditional DO entries and CALL entries execute only when all
        refs they consume are terminal: the frontier naturally
        serializes them behind their producers.  A conditional whose
        condition does not fire is terminal without work; later
        consumers of its targets then fail exactly like the sequential
        coordinator (unresolved reference at dispatch).

        Completion order — not plan order — fixes commit order; the
        projection is order-independent because interacting entries are
        serialized by the DAG and ref-disjoint deltas commute.
        ``crash_hook`` fires at the same site as the sequential loop
        (before VALIDATION_PASSED) and propagates uncaught, leaving the
        committed prefix intact while in-flight pool work is discarded.

        Resume (``initial_terminal``): entries already SUCCEEDED before
        a crash are terminal from the start; in-flight entries
        re-dispatch through the same prior-lifecycle-event guards as the
        sequential resume (committed READY/DISPATCHED are never
        re-emitted; the worker call is re-executed, at-least-once).

        ``gate`` (issue #22) enforces an :class:`ExecutionBudget`: a
        loop-top global-deadline check (failing the run and cancelling
        in-flight invocations), a per-invocation deadline via future
        timeouts, the child-depth cap at CALL dispatch, and a shared
        concurrency slot around every handler execution (waiting CALL
        frames hold no slot, so a one-worker budget cannot deadlock a
        parent awaiting a child).
        """
        deps = self._build_dependency_dag(plan)
        anchors = self._collect_anchors(program)

        terminal: set[int] = set(initial_terminal)
        in_flight: dict[int, concurrent.futures.Future] = {}
        anchor_evaluated: set[int] = set()
        dispatched_at: dict[int, float] = {}
        # Issue #41: per-invocation claim tracking for the concurrent path.
        held_claims: dict[int, str] = {}
        # Issue #41: per-invocation attempt count for max_attempts enforcement.
        attempt_counts: dict[str, int] = {}
        executor: concurrent.futures.ThreadPoolExecutor | None = None

        def drain_in_flight(timeout: float | None = 1.0) -> None:
            """Discard outstanding pool work (issue #21 cancellation rule).

            Not-yet-started futures are cancelled; started handlers
            cannot be interrupted, so they run to completion and their
            results are dropped uncommitted — a late result can never
            overwrite an accepted output or resurrect a failed run.

            Issue #41: the wait is bounded by ``timeout`` seconds so a
            hung handler cannot block ``execute()`` indefinitely after
            the run was already finalized.
            """
            for future in in_flight.values():
                future.cancel()
            if in_flight:
                concurrent.futures.wait(
                    list(in_flight.values()), timeout=timeout
                )
            in_flight.clear()

        def cancel_all_unsettled(exclude: int | None = None) -> list[_Record]:
            return [
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                )
                for pending_idx in range(len(plan))
                if pending_idx != exclude
                and pending_idx not in terminal
                and pending_idx not in in_flight
                and pending_idx in statement_to_task
            ]

        def finish_failed_invocation(
            idx: int,
            instruction_id: str,
            invocation_id: str,
            task_id: str,
            error: str,
            validation: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Fail one invocation and the run (mirrors the sequential batch)."""
            records = _finalize.fail_invocation_concurrent(
                self.store, run_id, plan, statement_to_task,
                idx, instruction_id, invocation_id, task_id, error, validation,
                in_flight=in_flight, terminal=terminal,
            )
            self.store.append_batch(run_id, records)
            return {
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "outputs": {},
            }

        def fail_global_deadline(
            trigger_idx: int | None = None,
            reason: str = "global deadline exceeded",
        ) -> dict[str, Any]:
            """Run-level failure when the global budget deadline expired."""
            records = _finalize.fail_global_deadline_concurrent(
                self.store, run_id, plan, statement_to_task,
                in_flight, terminal, trigger_idx, reason,
            )
            self.store.append_batch(run_id, records)
            return {
                "run_id": run_id,
                "status": "failed",
                "error": reason,
                "outputs": {},
            }

        def evaluate_reached_anchors() -> dict[str, Any] | None:
            """Evaluate source-anchored STOP/RETURN conditionals in order.

            An anchor at position ``pos`` is reached once every earlier
            entry is terminal; dispatch gating keeps later entries
            undispatched until it has been evaluated, so a fired
            terminal never races past in-flight work (in-flight is
            necessarily empty when an anchor evaluates).
            """
            for pos in sorted(anchors):
                if pos in anchor_evaluated:
                    continue
                if any(i not in terminal for i in range(pos)):
                    continue
                anchor_evaluated.add(pos)
                result = self._run_conditionals(
                    run_id,
                    anchors[pos],
                    values,
                    plan,
                    statement_to_task,
                    cancel_from_idx=pos,
                )
                if result is not None:
                    return result
            return None

        def next_ready() -> int | None:
            for idx in range(len(plan)):
                if idx in terminal or idx in in_flight:
                    continue
                if any(dep not in terminal for dep in deps[idx]):
                    continue
                if any(
                    pos not in anchor_evaluated
                    for pos in anchors
                    if pos <= idx
                ):
                    continue
                return idx
            return None

        def dispatch_entry(idx: int) -> tuple[str, Any]:
            """Run a ready entry's dispatch phase; submit its execution.

            Returns ``("dispatched", future)``, ``("skipped", None)`` for
            a conditional whose condition is false, or
            ``("run_failed", result)`` when the dispatch itself failed
            the run through the standard atomic path.
            """
            entry = plan[idx]
            statement = entry.invocation
            call = entry.call
            instruction_id = (
                call.protocol if call is not None else statement.step_id
            )
            invocation_id = f"inv-{idx + 1}"
            if entry.condition is not None:
                try:
                    fired = evaluate_condition(entry.condition, values)
                except ValueError as exc:
                    records = cancel_all_unsettled()
                    records.append(_Record(
                        event_type=EventType.RUN_FINISHED,
                        payload={"status": "failed", "error": str(exc)},
                        store=self.store,
                    ))
                    self.store.append_batch(run_id, records)
                    return (
                        "run_failed",
                        {
                            "run_id": run_id,
                            "status": "failed",
                            "error": str(exc),
                            "outputs": {},
                        },
                    )
                if not fired:
                    return ("skipped", None)
                task_id = statement_to_task.get(idx)
                if task_id is None:
                    task_id = self._create_single_plan_task(run_id, entry)
                    statement_to_task[idx] = task_id
            else:
                task_id = statement_to_task[idx]

            # Resume guard: an in-flight (crashed mid-dispatch) step keeps
            # its committed lifecycle events; the worker call re-runs.
            prior_types: set[EventType] = set()
            ledger = self.store.task_ledger(run_id)
            task = ledger.tasks.get(task_id)
            if task is not None and task.status is TaskStatus.IN_PROGRESS:
                prior_types = {
                    event.event_type
                    for event in self.store.events(run_id)
                    if event.invocation_id == invocation_id
                }
            elif task is not None and task.status is not TaskStatus.PENDING:
                raise TaskLedgerError(
                    f"task {task_id} for non-terminal step"
                    f" {instruction_id} is {task.status.value};"
                    " cannot resume"
                )
            ready_command = (
                f"CALL {call.protocol}" if call is not None else statement.command
            )
            if EventType.INVOCATION_READY not in prior_types:
                if task is not None and task.status is TaskStatus.IN_PROGRESS:
                    self.store.append(
                        run_id,
                        EventType.INVOCATION_READY,
                        instruction_id=instruction_id,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={"command": ready_command},
                    )
                else:
                    ledger.start_task(task_id)
                    self.store.append_batch(run_id, [
                        _Record(
                            event_type=EventType.TASK_UPDATED,
                            task_id=task_id,
                            payload={"kind": "task_started", "id": task_id},
                            store=self.store,
                        ),
                        _Record(
                            event_type=EventType.INVOCATION_READY,
                            instruction_id=instruction_id,
                            invocation_id=invocation_id,
                            task_id=task_id,
                            payload={"command": ready_command},
                            store=self.store,
                        ),
                    ])

            if call is not None:
                child_run_id = f"{run_id}:{invocation_id}"
                # Issue #22: child-depth cap, checked before dispatch.
                if gate is not None and gate.depth_exceeded(child_run_id):
                    return (
                        "run_failed",
                        finish_failed_invocation(
                            idx,
                            call.protocol,
                            invocation_id,
                            task_id,
                            f"child run {child_run_id} depth"
                            f" {gate.depth_of(child_run_id)} exceeds budget"
                            f" max_child_depth"
                            f" {gate.budget.max_child_depth}",
                        ),
                    )
                try:
                    resolved_call_args = self._resolve_call_arguments(
                        call, values
                    )
                except Exception as exc:
                    return (
                        "run_failed",
                        finish_failed_invocation(
                            idx, call.protocol, invocation_id, task_id, str(exc)
                        ),
                    )
                if EventType.INVOCATION_DISPATCHED not in prior_types:
                    self.store.append(
                        run_id,
                        EventType.INVOCATION_DISPATCHED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "args": resolved_call_args,
                            "idempotency_key": f"{run_id}:{invocation_id}",
                            "child_run_id": child_run_id,
                        },
                    )
                assert executor is not None
                future: concurrent.futures.Future = executor.submit(
                    self._execute_call_child,
                    call,
                    resolved_call_args,
                    run_id,
                    invocation_id,
                    gate,
                )
                return ("dispatched", future)

            try:
                resolved_kwargs: dict[str, Any] = {}
                for arg in statement.args:
                    self._reject_unresolved_refs(arg.value, values)
                    if isinstance(arg.value, str) and arg.value in values:
                        resolved_kwargs[arg.name] = values[arg.value]
                    elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                        resolved_kwargs[arg.name] = self._resolve_kb_ref(arg.value)
                    elif isinstance(arg.value, list):
                        resolved_kwargs[arg.name] = [
                            values[item] if isinstance(item, str) and item in values
                            else self._resolve_kb_ref(item)
                            if isinstance(item, str) and item.startswith("KB.")
                            else item
                            for item in arg.value
                        ]
                    else:
                        resolved_kwargs[arg.name] = arg.value
            except Exception as exc:
                return (
                    "run_failed",
                    finish_failed_invocation(
                        idx, statement.step_id, invocation_id, task_id, str(exc)
                    ),
                )

            # Issue #41: enforce contract.budget.max_attempts at the
            # coordinator dispatch layer.
            cap = _command_max_attempts(statement.command)
            if cap is not None:
                prior_attempts = attempt_counts.get(invocation_id, 0)
                if prior_attempts >= cap:
                    return (
                        "run_failed",
                        finish_failed_invocation(
                            idx, statement.step_id, invocation_id, task_id,
                            f"max_attempts ({cap}) exceeded for"
                            f" {statement.command} on {invocation_id}",
                        ),
                    )
                attempt_counts[invocation_id] = prior_attempts + 1

            # Issue #85: pre-dispatch token budget check (concurrent path).
            cmd_max_tokens = _command_max_tokens(statement.command)
            if (
                gate is not None
                and cmd_max_tokens is not None
                and cmd_max_tokens > 0
            ):
                total_cap = gate.budget.max_total_tokens
                if total_cap is not None:
                    remaining = gate.remaining_tokens(total_cap)
                    if not gate.check_token_budget(cmd_max_tokens, remaining):
                        return (
                            "run_failed",
                            finish_failed_invocation(
                                idx, statement.step_id, invocation_id,
                                task_id, "insufficient_token_budget",
                            ),
                        )

            # Issue #41: thread claims through the concurrent path.
            # Effectful dispatches claim workspace:<run_id>:<invocation_id>
            # for the handler's duration, mirroring the sequential loop.
            dispatch_root = self.workspace_root
            claim_resource: str | None = None
            if (
                dispatch_root is not None
                and statement.command in _effectful_commands()
            ):
                resolved_kwargs["_workspace_root"] = dispatch_root
                if claims is not None:
                    claim_resource = f"workspace:{run_id}:{invocation_id}"
                    owner = f"{run_id}:{invocation_id}"
                    if not claims.claim(claim_resource, owner):
                        return (
                            "run_failed",
                            finish_failed_invocation(
                                idx, statement.step_id, invocation_id,
                                task_id,
                                f"resource claim failed: {claim_resource}"
                                f" is held by"
                                f" {claims.holder(claim_resource)!r}",
                            ),
                        )

            if EventType.INVOCATION_DISPATCHED not in prior_types:
                dispatched_payload: dict[str, Any] = {
                    "args": resolved_kwargs,
                    "idempotency_key": f"{run_id}:{invocation_id}",
                }
                if claim_resource is not None:
                    dispatched_payload["resource_claims"] = [claim_resource]
                self.store.append(
                    run_id,
                    EventType.INVOCATION_DISPATCHED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload=dispatched_payload,
                )

            assert executor is not None
            if claim_resource is not None:
                held_claims[idx] = claim_resource
            future = executor.submit(
                self._dispatch_worker_call,
                statement.command,
                resolved_kwargs,
                gate,
            )
            return ("dispatched", future)

        def process_completion(
            idx: int, future: concurrent.futures.Future
        ) -> dict[str, Any] | None:
            """Commit one completed invocation (single-writer path)."""
            entry = plan[idx]
            statement = entry.invocation
            call = entry.call
            instruction_id = (
                call.protocol if call is not None else statement.step_id
            )
            invocation_id = f"inv-{idx + 1}"
            task_id = statement_to_task[idx]

            try:
                outcome = future.result()
            except Exception as exc:
                # Issue #41: release the held claim on failure.
                if idx in held_claims and claims is not None:
                    claims.release(held_claims.pop(idx), f"{run_id}:{invocation_id}")
                return finish_failed_invocation(
                    idx, instruction_id, invocation_id, task_id, str(exc)
                )

            # Issue #41: release the held claim after the handler returns.
            if idx in held_claims and claims is not None:
                claims.release(held_claims.pop(idx), f"{run_id}:{invocation_id}")

            if call is not None:
                child_run_id = f"{run_id}:{invocation_id}"
                child_status = outcome.get("status", "unknown")
                if child_status != "succeeded":
                    child_error = outcome.get("error")
                    error_msg = (
                        f"child run {child_run_id} for {call.protocol}"
                        f" finished with status {child_status!r}; the CALL"
                        " cannot adopt its outputs"
                    )
                    if child_error:
                        error_msg = f"{error_msg}: {child_error}"
                    return finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, error_msg
                    )
                self.store.append(
                    run_id,
                    EventType.RESULT_RECEIVED,
                    instruction_id=call.protocol,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={
                        "child_run_id": child_run_id,
                        "status": child_status,
                    },
                )
                try:
                    adopted_nodes, adopted_map = self._adopt_child_result(
                        call, outcome
                    )
                except Exception as exc:
                    return finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, str(exc)
                    )
                if crash_hook is not None:
                    # Same crash window as the sequential loop: after the
                    # child is terminal, before the parent adopts.
                    crash_hook(idx)
                self.store.append(
                    run_id,
                    EventType.VALIDATION_PASSED,
                    instruction_id=call.protocol,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={},
                )
                for node in adopted_nodes:
                    values[node["id"]] = node["value"]
                delta = StateDelta(add_nodes=tuple(adopted_nodes))
                expected_sv = self.store._current_state_version(run_id)
                self.store.append_batch(run_id, [
                    _Record(
                        event_type=EventType.CHILD_ADOPTED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "child_run_id": child_run_id,
                            "adopted": adopted_map,
                            "child_status": child_status,
                        },
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.SUCCEEDED,
                        instruction_id=call.protocol,
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
                            "evidence": (
                                f"CALL {call.protocol} ({child_run_id})"
                                f" -> {list(call.targets)}"
                            ),
                        },
                        store=self.store,
                    ),
                ])
                terminal.add(idx)
                return None

            result = outcome
            self.store.append(
                run_id,
                EventType.RESULT_RECEIVED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={"result": result},
            )

            # Issue #41: feed the budget gate's token accumulator from
            # the result receipt if the worker carries usage info.
            if gate is not None and isinstance(result, dict):
                receipt = result.get("_receipt")
                if isinstance(receipt, dict):
                    usage = receipt.get("usage")
                    if isinstance(usage, dict):
                        tokens = usage.get("tokens", 0)
                        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0:
                            gate.add_tokens(tokens)
                if gate.token_cap_exceeded():
                    return finish_failed_invocation(
                        idx, statement.step_id, invocation_id, task_id,
                        "token budget exceeded",
                    )

            # Issue #85: post-result token ceiling check (concurrent path).
            cmd_max_tokens = _command_max_tokens(statement.command)
            if (
                cmd_max_tokens is not None
                and cmd_max_tokens > 0
                and isinstance(result, dict)
            ):
                receipt = result.get("_receipt")
                if isinstance(receipt, dict):
                    usage = receipt.get("usage")
                    if isinstance(usage, dict):
                        out_tokens = usage.get("output_tokens")
                        if (
                            isinstance(out_tokens, int)
                            and not isinstance(out_tokens, bool)
                            and out_tokens > cmd_max_tokens
                        ):
                            return finish_failed_invocation(
                                idx, statement.step_id, invocation_id,
                                task_id, "budget_exceeded",
                            )

            # Issue #85: post-result output-size check (concurrent path).
            cmd_max_bytes = _command_max_output_bytes(statement.command)
            if cmd_max_bytes is not None and cmd_max_bytes > 0:
                try:
                    import json as _json
                    payload_size = len(
                        _json.dumps(result, ensure_ascii=False, default=str)
                        .encode("utf-8")
                    )
                except Exception:
                    payload_size = 0
                if payload_size > cmd_max_bytes:
                    return finish_failed_invocation(
                        idx, statement.step_id, invocation_id,
                        task_id, "output_too_large",
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
                return finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id,
                    validation_error,
                )

            if statement.done is not None:
                passed, detail = evaluate_done_predicate(
                    statement.done, target_values
                )
                if not passed:
                    validation_payload = {
                        "step_id": statement.step_id,
                        "predicate": {
                            "op": statement.done.op,
                            "ref": statement.done.ref,
                            "value": statement.done.value,
                        },
                        "detail": detail,
                    }
                    return finish_failed_invocation(
                        idx, statement.step_id, invocation_id, task_id,
                        f"DONE predicate failed for {statement.step_id}:"
                        f" {detail}",
                        validation=validation_payload,
                    )

            revision_nodes: list[dict[str, Any]] = []
            retired_nodes: list[str] = []
            try:
                if statement.revisions:
                    if len(statement.targets) != 1 or (
                        statement.targets[0] not in target_values
                    ):
                        raise ValueError(
                            f"REVISE on {statement.step_id} requires the"
                            " step's single target value"
                        )
                    revised_value = target_values[statement.targets[0]]
                    revision_nodes = [
                        {"id": ref, "value": revised_value}
                        for ref in statement.revisions
                    ]
                retired_nodes = list(statement.retirements)
            except Exception as exc:
                return finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id, str(exc)
                )

            if crash_hook is not None:
                # Same crash window as the sequential loop (issue #10):
                # outside every try/except, so the exception propagates
                # uncaught and the committed prefix stays untouched.
                crash_hook(idx)

            self.store.append(
                run_id,
                EventType.VALIDATION_PASSED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={},
            )

            for target, val in target_values.items():
                values[target] = val
            for node in revision_nodes:
                values[node["id"]] = node["value"]
            for ref in retired_nodes:
                values.pop(ref, None)

            delta = StateDelta(
                add_nodes=tuple(
                    {"id": target, "value": value}
                    for target, value in target_values.items()
                ),
                revise_nodes=tuple(revision_nodes),
                retire_nodes=tuple(retired_nodes),
            )
            expected_sv = self.store._current_state_version(run_id)
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
                        "evidence": (
                            f"{statement.command} -> {statement.targets}"
                        ),
                    },
                    store=self.store,
                ),
            ])
            terminal.add(idx)
            return None

        pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers
        )
        executor = pool
        try:
            while True:
                # Issue #22: the global deadline is checked before each
                # dispatch cycle; work remaining + expired deadline fails
                # the run coherently.  An all-terminal run finishes
                # normally — the deadline limits work, not completion.
                if gate is not None and gate.global_expired() and not all(
                    idx in terminal for idx in range(len(plan))
                ):
                    # Issue #41: record the failure (marking in-flight
                    # invocations cancelled) BEFORE draining the pool
                    # work; the drain is bounded so a hung handler
                    # cannot block execute() indefinitely.
                    result = fail_global_deadline(next_ready())
                    drain_in_flight()
                    return result

                anchor_result = evaluate_reached_anchors()
                if anchor_result is not None:
                    drain_in_flight()
                    return anchor_result

                while len(in_flight) < max_workers:
                    idx = next_ready()
                    if idx is None:
                        break
                    kind, payload = dispatch_entry(idx)
                    if kind == "run_failed":
                        drain_in_flight()
                        return payload
                    if kind == "skipped":
                        terminal.add(idx)
                        anchor_result = evaluate_reached_anchors()
                        if anchor_result is not None:
                            drain_in_flight()
                            return anchor_result
                        continue
                    in_flight[idx] = payload
                    dispatched_at[idx] = _monotonic()

                if not in_flight:
                    if all(idx in terminal for idx in range(len(plan))):
                        break
                    raise RuntimeError(
                        f"frontier stalled on run {run_id!r}: ready and"
                        " in-flight sets are empty with entries remaining"
                    )

                owner = {future: idx for idx, future in in_flight.items()}
                done, _ = concurrent.futures.wait(
                    in_flight.values(),
                    timeout=self._frontier_wait_timeout(gate, in_flight, dispatched_at),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    idx = owner[future]
                    del in_flight[idx]
                    del dispatched_at[idx]
                    # Issue #22: a completion arriving after the global
                    # deadline is discarded uncommitted (a cancellation
                    # request is never mistaken for confirmed
                    # termination — the pool work is drained, not joined
                    # into the run's outcome).
                    if gate is not None and gate.global_expired():
                        result = fail_global_deadline()
                        drain_in_flight()
                        return result
                    failure = process_completion(idx, future)
                    if failure is not None:
                        drain_in_flight()
                        return failure

                # Issue #22: per-invocation deadlines of still-running
                # futures — an overrunning invocation fails through the
                # standard atomic path; its late result is discarded.
                # Issue #41: the failure batch is committed BEFORE
                # draining, and the drain is bounded.
                if (
                    gate is not None
                    and in_flight
                    and gate.budget.per_invocation_deadline_seconds
                    is not None
                ):
                    now = _monotonic()
                    per_invocation = (
                        gate.budget.per_invocation_deadline_seconds
                    )
                    expired = [
                        idx
                        for idx in in_flight
                        if now - dispatched_at[idx] >= per_invocation
                    ]
                    if expired:
                        idx = expired[0]
                        entry = plan[idx]
                        instruction_id = (
                            entry.call.protocol
                            if entry.call is not None
                            else entry.invocation.step_id
                        )
                        in_flight.pop(idx)
                        del dispatched_at[idx]
                        # Issue #41: finalize the failure batch BEFORE
                        # draining the pool so a hung handler cannot
                        # block the commit; the drain is bounded.
                        result = finish_failed_invocation(
                            idx,
                            instruction_id,
                            f"inv-{idx + 1}",
                            statement_to_task[idx],
                            "deadline exceeded",
                        )
                        drain_in_flight()
                        return result
        finally:
            # Issue #41: shutdown with wait=False so a hung handler
            # cannot block execute() at pool exit — the failure batch
            # was already committed above; outstanding pool work is
            # discarded.
            pool.shutdown(wait=False)

        for statement in program.statements:
            if isinstance(statement, Return):
                return self._terminal_return(run_id, statement.refs, values)
            if isinstance(statement, Stop):
                return self._terminal_stop(run_id, statement, values)

        self.store.append(
            run_id,
            EventType.RUN_FINISHED,
            payload={"status": "succeeded"},
        )
        return {"run_id": run_id, "status": "succeeded", "outputs": {}}

