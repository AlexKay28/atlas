from __future__ import annotations

import math
import os
import re
from typing import TYPE_CHECKING, Any, Callable, Mapping

from tahoe.runtime.events import EventType, _Record
from tahoe.runtime.planning import map_results_to_targets
from tahoe.runtime.tasks import TaskLedgerError, TaskStatus
from tahoe.state import StateDelta
from tahoe.syntax.model import Gather, Invocation, Program, Scatter

if TYPE_CHECKING:
    from tahoe.budgets import BudgetGate
    from tahoe.claims import ResourceLedger
    from tahoe.runtime.coordinator import _PlanEntry


_CANDIDATE_INVOCATION_RE = re.compile(r"^inv-(\d+)\.cand(\d+)$")


def _k_of_n(mode: str, total: int) -> int:
    """Resolve the required-success count for a k-of-n or quorum mode.

    ``k:3`` -> 3.  ``quorum:0.67`` -> ceil(total * 0.67).  Other modes
    raise ValueError (callers should gate on the mode prefix first).
    """
    if mode.startswith("k:"):
        return int(mode.split(":", 1)[1])
    if mode.startswith("quorum:"):
        ratio = float(mode.split(":", 1)[1])
        return max(1, math.ceil(total * ratio))
    raise ValueError(f"not a k-of-n or quorum mode: {mode}")


def candidate_invocation_id(scatter_invocation_id: str, candidate: int) -> str:
    """The invocation id of one candidate of a scatter entry (issue #4)."""
    return f"{scatter_invocation_id}.cand{candidate}"


def candidate_node_id(alias_ref: str, candidate: int, target_leaf: str) -> str:
    """The candidate-scoped node id for one body target (issue #4).

    Candidate results commit to ``<alias>.c<k>.<leaf>`` — never to the
    body step's raw target names — so losers stay recorded in state while
    only the gather's alias carries the join's committed value.
    """
    return f"{alias_ref}.c{candidate}.{target_leaf}"


def candidate_task_text(body: Invocation, candidate: int) -> str:
    """The ledger task text for one candidate of a scatter entry (issue #4: ``[candidate k]``)."""
    return f"{body.step_id}: DO {body.command} [candidate {candidate}]"


def branch_workspace_dir(base: str | None, branch_id: str) -> str | None:
    """The isolated workspace subdirectory for one branch (issue #23).

    ``<base>/branches/<branch_id>/`` — nested branches (a PAR inside a
    branch run) nest under the enclosing branch's own directory, keeping
    each branch tree disjoint.  ``None`` base (no workspace declared)
    means no branch isolation.
    """
    if base is None:
        return None
    return os.path.join(base, "branches", branch_id)


def judge_score(result: Any) -> float:
    """Deterministically extract a ranked-gather score from a judge result.

    A number (or bool) scores directly; the string ``"passed"`` scores 1.0
    and any other string 0.0; a mapping prefers a numeric ``score`` field
    and falls back to ``status == "passed"`` -> 1.0 / 0.0.  Anything else
    raises ValueError (the gather fails through the standard path rather
    than guessing a score).
    """
    if isinstance(result, bool):
        return 1.0 if result else 0.0
    if isinstance(result, (int, float)):
        return float(result)
    if isinstance(result, str):
        return 1.0 if result == "passed" else 0.0
    if isinstance(result, Mapping):
        score = result.get("score")
        if isinstance(score, bool):
            return 1.0 if score else 0.0
        if isinstance(score, (int, float)):
            return float(score)
        status = result.get("status")
        if isinstance(status, str):
            return 1.0 if status == "passed" else 0.0
        raise ValueError(
            "judge result has no scorable field: expected a number, the"
            ' string "passed", or a mapping with a numeric "score" field'
            ' or a "status" field'
        )
    raise ValueError(
        f"judge result is not scorable: {type(result).__name__}"
    )


class ScatterEngine:
    """Mixin: scatter/gather execution methods extracted from the coordinator.

    Mixed into ``SequentialCoordinator`` so the scatter/gather machinery
    shares the coordinator's ``store``, ``worker``, ``workspace_root``,
    and helper methods (``_execute_worker_call``, ``_reject_unresolved_refs``,
    ``_resolve_kb_ref``, ``_cancel_task_if_unsettled``, ``_merge_branch_artifacts``).
    """

    @staticmethod
    def _gather_for(program: Program, scatter: Scatter) -> Gather:
        """The GATHER statement directly following ``scatter`` (validated)."""
        statements = program.statements
        for position, statement in enumerate(statements):
            if statement is scatter:
                if position + 1 < len(statements):
                    following = statements[position + 1]
                    if isinstance(following, Gather) and (
                        following.body_step_id == scatter.body.step_id
                    ):
                        return following
                break
        raise ValueError(
            f"SCATTER block for {scatter.body.step_id} has no directly"
            " following GATHER"
        )

    @staticmethod
    @staticmethod
    def _scatter_for(program: Program, gather: Gather) -> Scatter:
        """The SCATTER statement directly preceding ``gather`` (validated)."""
        statements = program.statements
        for position, statement in enumerate(statements):
            if statement is gather:
                if position > 0:
                    preceding = statements[position - 1]
                    if isinstance(preceding, Scatter) and (
                        preceding.body.step_id == gather.body_step_id
                    ):
                        return preceding
                break
        raise ValueError(
            f"GATHER of {gather.body_step_id} has no directly preceding"
            " SCATTER block"
        )
    def _candidate_task_ids(
        self,
        run_id: str,
        body: Invocation,
        count: int,
    ) -> dict[int, str]:
        """Map candidate number -> ledger task id, creating missing tasks.

        Existing candidate tasks (a resume after a crash inside the
        scatter) are found by their canonical text; missing ones are
        created in one batch with the same record shape as the plan's
        task-creation batch (crash window W0a for candidates).
        """
        ledger = self.store.task_ledger(run_id)
        by_text = {
            task.text: task_id for task_id, task in ledger.tasks.items()
        }
        mapping: dict[int, str] = {}
        create_records: list[_Record] = []
        create_ledger = self.store.task_ledger(run_id)
        for k in range(1, count + 1):
            text = candidate_task_text(body, k)
            existing = by_text.get(text)
            if existing is not None:
                mapping[k] = existing
                continue
            task = create_ledger.create_task(text=text, creator="coordinator")
            mapping[k] = task.id
            create_records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task.id,
                payload={
                    "kind": "task_created", "id": task.id, "text": task.text,
                    "priority": task.priority, "parent": task.parent,
                    "dependencies": task.dependencies, "creator": task.creator,
                },
                store=self.store,
            ))
        if create_records:
            self.store.append_batch(run_id, create_records)
        return mapping

    def _candidate_cancel_reasons(
        self, run_id: str, task_ids: dict[int, str]
    ) -> dict[int, str]:
        """Candidate number -> recorded loser reason (resume reconstruction)."""
        reasons: dict[int, str] = {}
        task_to_k = {task_id: k for k, task_id in task_ids.items()}
        for event in self.store.events(run_id):
            if event.event_type is not EventType.TASK_UPDATED:
                continue
            payload = event.payload
            if not isinstance(payload, dict):
                continue
            if payload.get("kind") != "task_cancelled":
                continue
            k = task_to_k.get(payload.get("id"))
            if k is not None and isinstance(payload.get("reason"), str):
                reasons[k] = payload["reason"]
        return reasons
    def _execute_scatter_entry(
        self,
        program: Program,
        run_id: str,
        entry: _PlanEntry,
        idx: int,
        invocation_id: str,
        task_id: str,
        values: dict[str, Any],
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None" = None,
        branch_root: str | None = None,
    ) -> dict[str, Any] | None:
        """Execute one SCATTER plan entry (issue #4).

        Expands the committed collection into candidates (bounded by MAX;
        a longer list fails the run), runs the body step once per candidate
        in collection order through the normal invocation machinery, and
        commits each candidate's delta to candidate-scoped nodes
        ``<alias>.c<k>.<leaf>``.  Returns a terminal/failed result dict, or
        ``None`` when execution continues with the next plan entry.
        Issue #23: each candidate is a branch — its effectful dispatches
        write into ``<base>/branches/cand<k>/`` and hold the candidate's
        exclusive workspace claim.
        """
        scatter = entry.scatter
        gather = self._gather_for(program, scatter)
        body = scatter.body
        alias = gather.alias_ref
        instruction_id = f"scatter.{body.step_id}"

        def cancel_pending_plan(from_idx: int, records: list[_Record]) -> None:
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
                for pending_idx in range(from_idx, len(plan))
                if pending_idx in statement_to_task
            )

        def fail_scatter(error: str) -> dict[str, Any]:
            """Fail the run at the scatter entry (collection-level failure)."""
            records = [
                _Record(
                    event_type=EventType.FAILED,
                    instruction_id=instruction_id,
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
            cancel_pending_plan(idx + 1, records)
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": error},
                store=self.store,
            ))
            self.store.append_batch(run_id, records)
            return {
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "outputs": {},
            }

        # The scatter entry's own ledger task stays PENDING while the
        # candidates run: the strict single-in-progress ledger invariant
        # (no concurrent IN_PROGRESS tasks in a sequential run) forbids
        # overlapping it with the per-candidate tasks that carry the live
        # lifecycle.  The task starts and completes when the expansion
        # finalizes, in the entry's terminal batch below.
        ledger = self.store.task_ledger(run_id)
        task = ledger.tasks.get(task_id)
        if task is not None and task.status not in (
            TaskStatus.PENDING,
            TaskStatus.IN_PROGRESS,
        ):
            raise TaskLedgerError(
                f"task {task_id} for non-terminal step"
                f" {instruction_id} is {task.status.value};"
                " cannot resume"
            )

        collection_value = values.get(scatter.collection_ref)
        if not isinstance(collection_value, list):
            return fail_scatter(
                f"SCATTER collection {scatter.collection_ref} is"
                f" {type(collection_value).__name__} at runtime;"
                " it must be a list"
            )
        if len(collection_value) > scatter.max_count:
            return fail_scatter(
                f"SCATTER collection {scatter.collection_ref} has"
                f" {len(collection_value)} items, exceeding MAX"
                f" {scatter.max_count}"
            )
        count = len(collection_value)

        candidate_tasks = self._candidate_task_ids(run_id, body, count)

        # Candidates already committed before a crash: their invocation ids
        # are "inv-<K>.cand<k>" and their scoped nodes replayed into values.
        scatter_invocation = f"inv-{idx + 1}"
        prior_success: dict[int, dict[str, Any]] = {}
        for event in self.store.events(run_id):
            if event.event_type is not EventType.SUCCEEDED:
                continue
            match = _CANDIDATE_INVOCATION_RE.fullmatch(event.invocation_id)
            if match is None or int(match.group(1)) != idx + 1:
                continue
            k = int(match.group(2))
            leaf_values: dict[str, Any] = {}
            for target in body.targets:
                node = candidate_node_id(
                    alias, k, target.split(".")[-1]
                )
                if node not in values:
                    return fail_scatter(
                        f"candidate {k} committed a SUCCEEDED event but"
                        f" node {node} is missing from the replayed state"
                    )
                leaf_values[target] = values[node]
            prior_success[k] = leaf_values

        candidate_values: dict[int, dict[str, Any]] = {}
        loser_errors: dict[int, str] = {}
        winner: int | None = None
        is_kofn = gather.mode.startswith("k:") or gather.mode.startswith("quorum:")
        for k in range(1, count + 1):
            if k in prior_success:
                candidate_values[k] = prior_success[k]
                if gather.mode == "any" and winner is None:
                    # Deterministic first-success rule (issue #27): the
                    # lowest candidate index with a committed success.
                    winner = k
                continue
            if gather.mode == "any" and winner is not None:
                records: list[_Record] = []
                self._cancel_task_if_unsettled(
                    run_id, candidate_tasks[k], records
                )
                if records:
                    self.store.append_batch(run_id, records)
                continue
            cand_task_id = candidate_tasks[k]
            outcome = self._execute_scatter_candidate(
                run_id=run_id,
                scatter=scatter,
                alias=alias,
                candidate=k,
                invocation_id=candidate_invocation_id(scatter_invocation, k),
                task_id=cand_task_id,
                item_value=collection_value[k - 1],
                values=values,
                scatter_idx=idx,
                crash_hook=crash_hook,
                gate=gate,
                claims=claims,
                branch_root=branch_root,
            )
            status, payload_outcome, validation = outcome
            if status == "succeeded":
                candidate_values[k] = payload_outcome
                if gather.mode == "any":
                    winner = k
                    records = []
                    for rest in range(k + 1, count + 1):
                        self._cancel_task_if_unsettled(
                            run_id, candidate_tasks[rest], records
                        )
                    if records:
                        self.store.append_batch(run_id, records)
                    break
                continue
            # Candidate failure.
            if gather.mode in ("all", "ranked"):
                return self._fail_scatter_candidate(
                    run_id=run_id,
                    plan=plan,
                    statement_to_task=statement_to_task,
                    idx=idx,
                    scatter_task_id=task_id,
                    body=body,
                    candidate_tasks=candidate_tasks,
                    candidate=k,
                    invocation_id=candidate_invocation_id(
                        scatter_invocation, k
                    ),
                    error=payload_outcome,
                    validation=validation,
                )
            # USING any or k-of-n/quorum: the candidate is a loser —
            # cancelled and recorded, never a FAILED event (audit
            # truthfulness: a run that may yet succeed cannot carry
            # FAILED events).
            loser_errors[k] = payload_outcome
            records = []
            self._cancel_task_if_unsettled(
                run_id,
                cand_task_id,
                records,
                reason=f"[candidate {k}] {payload_outcome}",
            )
            if records:
                self.store.append_batch(run_id, records)

        if gather.mode == "any" and winner is None:
            return self._fail_scatter_all_losers(
                run_id=run_id,
                plan=plan,
                statement_to_task=statement_to_task,
                idx=idx,
                scatter_invocation=scatter_invocation,
                scatter_task_id=task_id,
                body=body,
                candidate_tasks=candidate_tasks,
                loser_errors=loser_errors,
            )

        if is_kofn:
            required = _k_of_n(gather.mode, count)
            succeeded = len(candidate_values)
            if succeeded < required:
                return self._fail_scatter_kofn(
                    run_id=run_id,
                    plan=plan,
                    statement_to_task=statement_to_task,
                    idx=idx,
                    scatter_invocation=scatter_invocation,
                    scatter_task_id=task_id,
                    body=body,
                    candidate_tasks=candidate_tasks,
                    candidate_values=candidate_values,
                    loser_errors=loser_errors,
                    required=required,
                    mode=gather.mode,
                )

        if crash_hook is not None:
            # Crash window after the fan-out completed, before the scatter
            # entry's own terminal batch: resume re-derives the expansion
            # from the committed candidate events without re-running any
            # committed candidate (at-least-once per candidate).
            crash_hook(idx)

        evidence = (
            f"SCATTER {scatter.item_ref} IN {scatter.collection_ref}:"
            f" expanded {count} candidate(s)"
        )
        if gather.mode == "any" and winner is not None:
            evidence += f"; first success at candidate {winner}"
        if is_kofn:
            required = _k_of_n(gather.mode, count)
            evidence += (
                f"; {len(candidate_values)}/{count} succeeded"
                f" (required {required})"
            )
        if loser_errors:
            evidence += (
                f"; losers recorded: {len(loser_errors)}"
            )
        expected_sv = self.store._current_state_version(run_id)
        # Terminal batch: the entry's compressed task lifecycle (start
        # after the candidates settled — see the note at the top) plus the
        # empty-delta SUCCEEDED that marks the entry terminal for resume.
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
                payload={
                    "command": (
                        f"SCATTER {scatter.item_ref} IN"
                        f" {scatter.collection_ref} MAX"
                        f" {scatter.max_count}"
                    )
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.VALIDATION_PASSED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={},
                store=self.store,
            ),
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                expected_state_version=expected_sv,
                payload={
                    "delta": StateDelta(),
                    "scatter": {
                        "item_ref": scatter.item_ref,
                        "collection_ref": scatter.collection_ref,
                        "max": scatter.max_count,
                        "alias": alias,
                        "mode": gather.mode,
                        "candidates": count,
                        "winner": winner,
                        "losers": {
                            str(k): loser_errors[k] for k in sorted(loser_errors)
                        },
                    },
                },
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
                    "evidence": evidence,
                },
                store=self.store,
            ),
        ])
        return None
    def _execute_scatter_candidate(
        self,
        *,
        run_id: str,
        scatter: Scatter,
        alias: str,
        candidate: int,
        invocation_id: str,
        task_id: str,
        item_value: Any,
        values: dict[str, Any],
        scatter_idx: int,
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None" = None,
        branch_root: str | None = None,
    ) -> tuple[str, Any, Any]:
        """Run one per-candidate body step through the invocation machinery.

        Emits the full candidate lifecycle (READY, DISPATCHED,
        RESULT_RECEIVED, VALIDATION_PASSED, the atomic SUCCEEDED batch with
        the candidate-scoped delta).  Failures return
        ``("failed", error, validation_payload)`` without emitting failure
        events — the caller decides the mode-specific failure recording.
        Issue #23: the candidate is a branch — its effectful dispatch
        writes into its isolated workspace subdirectory and holds the
        candidate's exclusive claim for the handler's duration.
        """
        body = scatter.body
        instruction_id = body.step_id
        ledger = self.store.task_ledger(run_id)
        task = ledger.tasks.get(task_id)
        prior_types: set[EventType] = set()
        if task is not None and task.status is TaskStatus.IN_PROGRESS:
            prior_types = {
                event.event_type
                for event in self.store.events(run_id)
                if event.invocation_id == invocation_id
            }
        elif task is not None and task.status is not TaskStatus.PENDING:
            raise TaskLedgerError(
                f"candidate task {task_id} for {instruction_id}"
                f" [candidate {candidate}] is {task.status.value};"
                " cannot resume"
            )
        if EventType.INVOCATION_READY not in prior_types:
            if task is not None and task.status is TaskStatus.IN_PROGRESS:
                self.store.append(
                    run_id,
                    EventType.INVOCATION_READY,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={"command": body.command},
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
                        payload={"command": body.command},
                        store=self.store,
                    ),
                ])

        candidate_state = dict(values)
        candidate_state[scatter.item_ref] = item_value
        try:
            resolved_kwargs: dict[str, Any] = {}
            for arg in body.args:
                self._reject_unresolved_refs(arg.value, candidate_state)
                if isinstance(arg.value, str) and arg.value in candidate_state:
                    resolved_kwargs[arg.name] = candidate_state[arg.value]
                elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                    resolved_kwargs[arg.name] = self._resolve_kb_ref(arg.value)
                elif isinstance(arg.value, list):
                    resolved_kwargs[arg.name] = [
                        candidate_state[item]
                        if isinstance(item, str) and item in candidate_state
                        else self._resolve_kb_ref(item)
                        if isinstance(item, str) and item.startswith("KB.")
                        else item
                        for item in arg.value
                    ]
                else:
                    resolved_kwargs[arg.name] = arg.value
        except Exception as exc:
            return ("failed", str(exc), None)

        # Issue #23: the candidate is a branch — its effectful dispatch
        # writes into its isolated workspace subdirectory and holds the
        # candidate's exclusive workspace claim for the handler's
        # duration (annotated on the DISPATCHED payload).
        from tahoe.runtime.coordinator import _effectful_commands
        dispatch_root = branch_root or self.workspace_root
        branch_claim_held: str | None = None
        if (
            dispatch_root is not None
            and body.command in _effectful_commands()
        ):
            resolved_kwargs["_workspace_root"] = branch_workspace_dir(
                dispatch_root, f"cand{candidate}"
            )
            if claims is not None:
                candidate_claim = f"workspace:{run_id}:{invocation_id}"
                if claims.claim(candidate_claim, f"{run_id}:{invocation_id}"):
                    branch_claim_held = candidate_claim
                else:
                    return (
                        "failed",
                        f"resource claim failed: {candidate_claim} is held"
                        f" by {claims.holder(candidate_claim)!r}",
                        None,
                    )

        if EventType.INVOCATION_DISPATCHED not in prior_types:
            dispatched_payload: dict[str, Any] = {
                "args": resolved_kwargs,
                "idempotency_key": f"{run_id}:{invocation_id}",
                "candidate": candidate,
            }
            if branch_claim_held is not None:
                dispatched_payload["resource_claims"] = [branch_claim_held]
            self.store.append(
                run_id,
                EventType.INVOCATION_DISPATCHED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload=dispatched_payload,
            )

        try:
            result = self._execute_worker_call(body.command, resolved_kwargs, gate)
        except Exception as exc:
            return ("failed", str(exc), None)
        finally:
            if branch_claim_held is not None:
                claims.release(
                    branch_claim_held, f"{run_id}:{invocation_id}"
                )

        self.store.append(
            run_id,
            EventType.RESULT_RECEIVED,
            instruction_id=instruction_id,
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
                return ("failed", "token budget exceeded", None)

        target_values, validation_error = map_results_to_targets(
            body.targets, result
        )
        if validation_error is not None:
            return ("failed", validation_error, None)

        validation_payload: dict[str, Any] | None = None
        if body.done is not None:
            from tahoe.runtime.coordinator import evaluate_done_predicate
            passed, detail = evaluate_done_predicate(body.done, target_values)
            if not passed:
                validation_payload = {
                    "step_id": body.step_id,
                    "candidate": candidate,
                    "predicate": {
                        "op": body.done.op,
                        "ref": body.done.ref,
                        "value": body.done.value,
                    },
                    "detail": detail,
                }
                return (
                    "failed",
                    f"DONE predicate failed for {body.step_id}"
                    f" [candidate {candidate}]: {detail}",
                    validation_payload,
                )

        add_nodes = [
            {
                "id": candidate_node_id(
                    alias, candidate, target.split(".")[-1]
                ),
                "value": target_values[target],
            }
            for target in body.targets
        ]
        for node in add_nodes:
            values[node["id"]] = node["value"]

        if crash_hook is not None:
            # Crash window before the candidate's terminal batch: resume
            # re-executes exactly this candidate (at-least-once; the
            # DISPATCHED idempotency key is the dedup contract).
            crash_hook(scatter_idx)

        self.store.append(
            run_id,
            EventType.VALIDATION_PASSED,
            instruction_id=instruction_id,
            invocation_id=invocation_id,
            task_id=task_id,
            payload={},
        )

        delta = StateDelta(add_nodes=tuple(add_nodes))
        expected_sv = self.store._current_state_version(run_id)
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                expected_state_version=expected_sv,
                payload={
                    "delta": delta,
                    "candidate": candidate,
                },
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
                        f"{body.command} ->"
                        f" {[node['id'] for node in add_nodes]}"
                        f" [candidate {candidate}]"
                    ),
                },
                store=self.store,
            ),
        ])
        return ("succeeded", dict(target_values), None)
    def _fail_scatter_candidate(
        self,
        *,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        idx: int,
        scatter_task_id: str,
        body: Invocation,
        candidate_tasks: dict[int, str],
        candidate: int,
        invocation_id: str,
        error: str,
        validation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Fail the run atomically on a candidate failure (all/ranked)."""
        records: list[_Record] = []
        if validation is not None:
            records.append(_Record(
                event_type=EventType.VALIDATION_FAILED,
                instruction_id=body.step_id,
                invocation_id=invocation_id,
                task_id=candidate_tasks[candidate],
                payload=validation,
                store=self.store,
            ))
        records.append(_Record(
            event_type=EventType.FAILED,
            instruction_id=body.step_id,
            invocation_id=invocation_id,
            task_id=candidate_tasks[candidate],
            payload={"error": error},
            store=self.store,
        ))
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=candidate_tasks[candidate],
            payload={
                "kind": "invocation_recorded",
                "id": candidate_tasks[candidate],
                "tokens": 0, "cost": 0.0, "retries": 0,
                "elapsed_seconds": 0.0,
            },
            store=self.store,
        ))
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=candidate_tasks[candidate],
            payload={"kind": "task_cancelled", "id": candidate_tasks[candidate]},
            store=self.store,
        ))
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=scatter_task_id,
            payload={"kind": "task_cancelled", "id": scatter_task_id},
            store=self.store,
        ))
        for k in range(candidate + 1, len(candidate_tasks) + 1):
            self._cancel_task_if_unsettled(
                run_id, candidate_tasks[k], records
            )
        for pending_idx in range(idx + 1, len(plan)):
            if pending_idx in statement_to_task:
                records.append(_Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                ))
        records.append(_Record(
            event_type=EventType.RUN_FINISHED,
            payload={
                "status": "failed",
                "error": f"candidate {candidate} failed: {error}",
            },
            store=self.store,
        ))
        self.store.append_batch(run_id, records)
        return {
            "run_id": run_id,
            "status": "failed",
            "error": f"candidate {candidate} failed: {error}",
            "outputs": {},
        }
    def _fail_scatter_all_losers(
        self,
        *,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        idx: int,
        scatter_invocation: str,
        scatter_task_id: str,
        body: Invocation,
        candidate_tasks: dict[int, str],
        loser_errors: dict[int, str],
    ) -> dict[str, Any]:
        """Fail the run when every candidate lost under USING any.

        Losers carried no FAILED events while the run could still succeed
        (audit truthfulness: a succeeding run may not contain FAILED
        events); now that the join cannot succeed, each loser records its
        FAILED event and the run finishes failed through the standard
        shape.
        """
        records: list[_Record] = []
        for k in sorted(loser_errors):
            cand_task_id = candidate_tasks[k]
            records.append(_Record(
                event_type=EventType.FAILED,
                instruction_id=body.step_id,
                invocation_id=candidate_invocation_id(scatter_invocation, k),
                task_id=cand_task_id,
                payload={"error": loser_errors[k]},
                store=self.store,
            ))
            records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=cand_task_id,
                payload={
                    "kind": "invocation_recorded", "id": cand_task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ))
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=scatter_task_id,
            payload={"kind": "task_cancelled", "id": scatter_task_id},
            store=self.store,
        ))
        for pending_idx in range(idx + 1, len(plan)):
            if pending_idx in statement_to_task:
                records.append(_Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                ))
        if loser_errors:
            error = (
                f"USING any gather failed: all {len(loser_errors)}"
                f" candidate(s) failed; last error:"
                f" {loser_errors[max(loser_errors)]}"
            )
        else:
            error = (
                "USING any gather failed: the collection produced no"
                " candidates to select from"
            )
        records.append(_Record(
            event_type=EventType.RUN_FINISHED,
            payload={"status": "failed", "error": error},
            store=self.store,
        ))
        self.store.append_batch(run_id, records)
        return {
            "run_id": run_id,
            "status": "failed",
            "error": error,
            "outputs": {},
        }
    def _fail_scatter_kofn(
        self,
        *,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        idx: int,
        scatter_invocation: str,
        scatter_task_id: str,
        body: Invocation,
        candidate_tasks: dict[int, str],
        candidate_values: dict[int, dict[str, Any]],
        loser_errors: dict[int, str],
        required: int,
        mode: str,
    ) -> dict[str, Any]:
        """Fail the run when k-of-n or quorum threshold was not met (issue #84).

        Like ``_fail_scatter_all_losers`` but for the k-of-n/quorum join:
        the losers' FAILED events are recorded now that the join cannot
        succeed, and the run finishes failed through the standard shape.
        """
        records: list[_Record] = []
        for k in sorted(loser_errors):
            cand_task_id = candidate_tasks[k]
            records.append(_Record(
                event_type=EventType.FAILED,
                instruction_id=body.step_id,
                invocation_id=candidate_invocation_id(scatter_invocation, k),
                task_id=cand_task_id,
                payload={"error": loser_errors[k]},
                store=self.store,
            ))
            records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=cand_task_id,
                payload={
                    "kind": "invocation_recorded", "id": cand_task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ))
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=scatter_task_id,
            payload={"kind": "task_cancelled", "id": scatter_task_id},
            store=self.store,
        ))
        for pending_idx in range(idx + 1, len(plan)):
            if pending_idx in statement_to_task:
                records.append(_Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                ))
        succeeded = len(candidate_values)
        total = len(candidate_tasks)
        if mode.startswith("k:"):
            error = (
                f"USING k({required}) gather failed: only {succeeded}"
                f" of {total} candidate(s) succeeded (need {required})"
            )
        else:
            ratio = mode.split(":", 1)[1]
            error = (
                f"USING quorum({ratio}) gather failed: only {succeeded}"
                f" of {total} candidate(s) succeeded (need {required})"
            )
        records.append(_Record(
            event_type=EventType.RUN_FINISHED,
            payload={"status": "failed", "error": error},
            store=self.store,
        ))
        self.store.append_batch(run_id, records)
        return {
            "run_id": run_id,
            "status": "failed",
            "error": error,
            "outputs": {},
        }
    def _candidate_state_values(
        self,
        values: Mapping[str, Any],
        alias: str,
        body: Invocation,
        candidate: int,
    ) -> dict[str, Any] | None:
        """One candidate's committed target values, or None if incomplete."""
        leaf_values: dict[str, Any] = {}
        for target in body.targets:
            node = candidate_node_id(alias, candidate, target.split(".")[-1])
            if node not in values:
                return None
            leaf_values[target] = values[node]
        return leaf_values
    def _execute_gather_entry(
        self,
        program: Program,
        run_id: str,
        entry: _PlanEntry,
        idx: int,
        invocation_id: str,
        task_id: str,
        values: dict[str, Any],
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None" = None,
        branch_root: str | None = None,
    ) -> dict[str, Any] | None:
        """Execute one GATHER plan entry (issue #4): the explicit join.

        Reads the preceding scatter's expansion record and the
        candidate-scoped nodes from committed state, evaluates the join
        rule, and commits the alias node with the selection evidence in
        the task's completion.  ``all`` joins every candidate's value in
        candidate order; ``any`` takes the first candidate-order success;
        ``ranked`` executes the judge step once per candidate (item and
        body-target bindings) and commits the max score, ties breaking to
        the lowest candidate index.  Issue #23: when the body produced
        ART.* artifacts inside branch workspaces, the explicit artifact
        merge integrates the disjoint paths into the parent workspace and
        records the accounting in the join's SUCCEEDED payload; a
        cross-branch path collision fails the run atomically.
        """
        gather = entry.gather
        scatter = self._scatter_for(program, gather)
        body = scatter.body
        alias = gather.alias_ref
        instruction_id = f"gather.{gather.body_step_id}"
        scatter_invocation = f"inv-{idx}"

        def fail_gather(error: str) -> dict[str, Any]:
            records = [
                _Record(
                    event_type=EventType.FAILED,
                    instruction_id=instruction_id,
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
            for pending_idx in range(idx + 1, len(plan)):
                if pending_idx in statement_to_task:
                    records.append(_Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=statement_to_task[pending_idx],
                        payload={
                            "kind": "task_cancelled",
                            "id": statement_to_task[pending_idx],
                        },
                        store=self.store,
                    ))
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": error},
                store=self.store,
            ))
            self.store.append_batch(run_id, records)
            return {
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "outputs": {},
            }

        ledger = self.store.task_ledger(run_id)
        task = ledger.tasks.get(task_id)
        prior_types: set[EventType] = set()
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
        if EventType.INVOCATION_READY not in prior_types:
            if task is not None and task.status is TaskStatus.IN_PROGRESS:
                self.store.append(
                    run_id,
                    EventType.INVOCATION_READY,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={
                        "command": (
                            f"GATHER {gather.body_step_id} AS {alias}"
                            f" USING {gather.mode}"
                        )
                    },
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
                        payload={
                            "command": (
                                f"GATHER {gather.body_step_id} AS {alias}"
                                f" USING {gather.mode}"
                            )
                        },
                        store=self.store,
                    ),
                ])

        # The scatter's expansion record is the single source of truth for
        # the candidate count, the any-winner and the loser errors — read
        # from the committed event, so a fresh run and a resume derive the
        # join identically.
        scatter_record: dict[str, Any] | None = None
        for event in self.store.events(run_id):
            if (
                event.event_type is EventType.SUCCEEDED
                and event.invocation_id == scatter_invocation
                and isinstance(event.payload, dict)
                and isinstance(event.payload.get("scatter"), dict)
            ):
                scatter_record = event.payload["scatter"]
        if scatter_record is None:
            return fail_gather(
                f"GATHER of {gather.body_step_id} found no expansion record"
                f" for {scatter_invocation}: the scatter entry has not"
                " committed"
            )
        count = int(scatter_record.get("candidates", 0))
        collection_value = values.get(scatter.collection_ref)
        if not isinstance(collection_value, list) or len(collection_value) != count:
            return fail_gather(
                f"GATHER of {gather.body_step_id}: collection"
                f" {scatter.collection_ref} disagrees with the scatter's"
                f" expansion record ({count} candidates)"
            )

        selection: dict[str, Any] = {"mode": gather.mode, "candidates": count}
        evidence: str
        winner: int | None = None
        alias_value: Any

        if gather.mode == "all":
            joined: list[Any] = []
            for k in range(1, count + 1):
                leaf_values = self._candidate_state_values(
                    values, alias, body, k
                )
                if leaf_values is None:
                    return fail_gather(
                        f"GATHER USING all: candidate {k} has no committed"
                        f" result nodes under {alias}.c{k}"
                    )
                if len(body.targets) == 1:
                    joined.append(leaf_values[body.targets[0]])
                else:
                    joined.append(
                        {
                            target.split(".")[-1]: value
                            for target, value in leaf_values.items()
                        }
                    )
            alias_value = joined
            evidence = (
                f"join all: committed {alias} from {count} candidate(s)"
                " in collection order"
            )

        elif gather.mode == "any":
            winner = scatter_record.get("winner")
            if not isinstance(winner, int) or not (
                1 <= winner <= count
            ):
                return fail_gather(
                    f"GATHER USING any: the scatter recorded no winning"
                    " candidate"
                )
            leaf_values = self._candidate_state_values(
                values, alias, body, winner
            )
            if leaf_values is None:
                return fail_gather(
                    f"GATHER USING any: winner candidate {winner} has no"
                    f" committed result nodes under {alias}.c{winner}"
                )
            if len(body.targets) == 1:
                alias_value = leaf_values[body.targets[0]]
            else:
                alias_value = {
                    target.split(".")[-1]: value
                    for target, value in leaf_values.items()
                }
            losers = scatter_record.get("losers", {})
            selection["winner"] = winner
            selection["losers"] = losers
            if losers:
                evidence = (
                    f"join any: winner candidate {winner}; losers recorded"
                    f" (cancelled, not committed): {losers}"
                )
            else:
                evidence = (
                    f"join any: winner candidate {winner}; no losers"
                )

        elif gather.mode.startswith("k:") or gather.mode.startswith("quorum:"):
            required = _k_of_n(gather.mode, count)
            losers = scatter_record.get("losers", {})
            joined: list[Any] = []
            succeeded_count = 0
            for k in range(1, count + 1):
                leaf_values = self._candidate_state_values(
                    values, alias, body, k
                )
                if leaf_values is not None:
                    succeeded_count += 1
                    if len(body.targets) == 1:
                        joined.append(leaf_values[body.targets[0]])
                    else:
                        joined.append(
                            {
                                target.split(".")[-1]: value
                                for target, value in leaf_values.items()
                            }
                        )
            if succeeded_count < required:
                return fail_gather(
                    f"GATHER USING {gather.mode}: only {succeeded_count}"
                    f" of {count} candidate(s) succeeded (need {required})"
                )
            alias_value = joined
            selection["required"] = required
            selection["succeeded"] = succeeded_count
            selection["losers"] = losers
            if losers:
                evidence = (
                    f"join {gather.mode}: committed {alias} from"
                    f" {succeeded_count}/{count} candidate(s)"
                    f" (required {required}); losers: {losers}"
                )
            else:
                evidence = (
                    f"join {gather.mode}: committed {alias} from"
                    f" {succeeded_count}/{count} candidate(s)"
                    f" (required {required})"
                )

        else:  # ranked
            judge = gather.judge
            if judge is None:
                return fail_gather(
                    "GATHER USING ranked requires a JUDGE step"
                )
            if judge.done is not None:
                return fail_gather(
                    "GATHER judge steps do not support DONE predicates"
                )
            scores: dict[int, float] = {}
            for k in range(1, count + 1):
                leaf_values = self._candidate_state_values(
                    values, alias, body, k
                )
                if leaf_values is None:
                    return fail_gather(
                        f"GATHER USING ranked: candidate {k} has no"
                        f" committed result nodes under {alias}.c{k}"
                    )
                judge_state = dict(values)
                judge_state[scatter.item_ref] = collection_value[k - 1]
                judge_state.update(leaf_values)
                try:
                    resolved_kwargs: dict[str, Any] = {}
                    for arg in judge.args:
                        self._reject_unresolved_refs(arg.value, judge_state)
                        if isinstance(arg.value, str) and (
                            arg.value in judge_state
                        ):
                            resolved_kwargs[arg.name] = judge_state[arg.value]
                        elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                            resolved_kwargs[arg.name] = self._resolve_kb_ref(
                                arg.value
                            )
                        elif isinstance(arg.value, list):
                            resolved_kwargs[arg.name] = [
                                judge_state[item]
                                if isinstance(item, str) and item in judge_state
                                else self._resolve_kb_ref(item)
                                if isinstance(item, str) and item.startswith("KB.")
                                else item
                                for item in arg.value
                            ]
                        else:
                            resolved_kwargs[arg.name] = arg.value
                    result = self._execute_worker_call(
                        judge.command, resolved_kwargs, gate
                    )
                    scores[k] = judge_score(result)
                except Exception as exc:
                    return fail_gather(
                        f"GATHER judge for candidate {k} failed: {exc}"
                    )
            best = max(scores.values())
            winner = min(
                k for k, score in scores.items() if score == best
            )
            leaf_values = self._candidate_state_values(
                values, alias, body, winner
            )
            if len(body.targets) == 1:
                alias_value = leaf_values[body.targets[0]]
            else:
                alias_value = {
                    target.split(".")[-1]: value
                    for target, value in leaf_values.items()
                }
            selection["winner"] = winner
            selection["scores"] = {str(k): scores[k] for k in sorted(scores)}
            evidence = (
                f"join ranked: winner candidate {winner}"
                f" (score {scores[winner]}); scores:"
                f" {selection['scores']}; judge {judge.command}"
            )

        if crash_hook is not None:
            # Crash window after the join is decided, before the alias
            # commits: resume re-derives the join deterministically.
            crash_hook(idx)

        # Issue #23: explicit artifact merge for branch-produced ART.*
        # nodes (workspace-gated, so pre-#23 programs without a declared
        # workspace behave exactly as before).
        merge_payload: dict[str, Any] | None = None
        merge_base = branch_root or self.workspace_root
        if merge_base is not None and any(
            target.startswith("ART.") for target in body.targets
        ):
            merge_artifacts: list[dict[str, Any]] = []
            merge_dirs: dict[str, str | None] = {}
            for k in range(1, count + 1):
                merge_dirs[f"cand{k}"] = branch_workspace_dir(
                    merge_base, f"cand{k}"
                )
                for target in body.targets:
                    if not target.startswith("ART."):
                        continue
                    node = candidate_node_id(alias, k, target.split(".")[-1])
                    node_value = values.get(node)
                    if isinstance(node_value, str):
                        merge_artifacts.append({
                            "branch": f"cand{k}",
                            "node": node,
                            "path": node_value,
                        })
            merged, merge_error = self._merge_branch_artifacts(
                run_id,
                f"{run_id}:{invocation_id}",
                claims,
                merge_artifacts,
                merge_dirs,
            )
            if merge_error is not None:
                return fail_gather(merge_error)
            merge_payload = {"artifacts": merged}

        self.store.append(
            run_id,
            EventType.VALIDATION_PASSED,
            instruction_id=instruction_id,
            invocation_id=invocation_id,
            task_id=task_id,
            payload={},
        )

        expected_sv = self.store._current_state_version(run_id)
        delta = StateDelta(add_nodes=({"id": alias, "value": alias_value},))
        values[alias] = alias_value
        gather_succeeded_payload: dict[str, Any] = {
            "delta": delta,
            "gather": selection,
        }
        if merge_payload is not None:
            gather_succeeded_payload["merge"] = merge_payload
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                expected_state_version=expected_sv,
                payload=gather_succeeded_payload,
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
                    "evidence": evidence,
                },
                store=self.store,
            ),
        ])
        return None

