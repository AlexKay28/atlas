from __future__ import annotations

import concurrent.futures
import os
from typing import TYPE_CHECKING, Any, Callable, Mapping

from tahoe.runtime.events import EventType, _Record
from tahoe.runtime.tasks import TaskStatus
from tahoe.syntax import load_protocol
from tahoe.syntax.model import Invocation, Par, ParBranch, Program
from tahoe.state import StateDelta

if TYPE_CHECKING:
    from tahoe.budgets import BudgetGate
    from tahoe.claims import ResourceLedger
    from tahoe.runtime.coordinator import _PlanEntry


def par_branch_invocation_id(branch: int) -> str:
    """The parent-side invocation id of one PAR branch (issue #24)."""
    return f"par{branch}"


def par_branch_run_id(parent_run_id: str, branch: int) -> str:
    """The isolated child run id of one PAR branch (issue #24)."""
    return f"{parent_run_id}:{par_branch_invocation_id(branch)}"


def par_branch_summary(branch: ParBranch) -> str:
    """The canonical summary text of one PAR branch (task texts, events)."""
    if branch.invocation is not None:
        return f"{branch.invocation.step_id}: DO {branch.invocation.command}"
    return f"CALL {branch.call.protocol}"


def par_branch_task_text(branch: ParBranch, position: int) -> str:
    """The ledger task text for one PAR branch (issue #24: one per branch)."""
    return f"PAR branch {position}: {par_branch_summary(branch)}"


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


class ParEngine:
    """Mixin: PAR-block execution for the sequential coordinator (issue #24).

    Extracted from ``coordinator.py`` to keep the PAR machinery in its own
    module.  The host class (``SequentialCoordinator``) mixes this in and
    supplies ``self.store``, ``self.workspace_root``, ``self.protocols_dir``
    and the helper methods referenced below (``_resolve_call_arguments``,
    ``_adopt_branch_nodes``, ``_merge_branch_artifacts``, ``_build_branch_program``,
    ``_execute_program_child``, ``_bind_child_inputs``, ``_resolve_kb_ref``,
    ``_reject_unresolved_refs``, ``_cancel_task_if_unsettled``).
    """

    def _par_branch_task_ids(self, run_id: str, par: Par) -> list[str]:
        """Branch-order ledger task ids for a PAR block's branches.

        One task per branch, no block task (issue #24).  Existing tasks
        (a resume after a crash inside the block) are found by their
        canonical text; missing ones are created in one batch with the
        same record shape as the plan's task-creation batch.
        """
        ledger = self.store.task_ledger(run_id)
        by_text = {
            task.text: task_id for task_id, task in ledger.tasks.items()
        }
        mapping: list[str] = []
        create_records: list[_Record] = []
        create_ledger = self.store.task_ledger(run_id)
        for position, branch in enumerate(par.branches, 1):
            text = par_branch_task_text(branch, position)
            existing = by_text.get(text)
            if existing is not None:
                mapping.append(existing)
                continue
            task = create_ledger.create_task(text=text, creator="coordinator")
            mapping.append(task.id)
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

    def _execute_par_entry(
        self,
        program: Program,
        run_id: str,
        entry: _PlanEntry,
        idx: int,
        invocation_id: str,
        values: dict[str, Any],
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
    ) -> dict[str, Any] | None:
        """Execute one PAR plan entry (issue #24): branches + barrier.

        Branches dispatch concurrently onto a pool capped at
        ``min(MAX, branch count)`` (further capped tree-wide by the
        budget's shared semaphore); each branch executes as an isolated
        child-scoped run ``<run_id>:par<k>`` (state isolation for free
        from the child-run machinery) whose effectful dispatches write
        into the branch's isolated workspace subdirectory and hold the
        branch's ``workspace:<branch run id>`` claim (issue #23).  Every
        commit happens on the coordinator's single-writer thread.

        The barrier blocks until every branch is terminal.  All
        succeeded: the branch outputs are adopted by explicit target
        mapping — one CHILD_ADOPTED per branch at its completion, then a
        single entry-terminal SUCCEEDED committing every adopted target
        in branch order (atomically published declared outputs) — the
        explicit artifact merge integrates branch-produced ART.* paths,
        and a PAR_JOINED event records the branch statuses and the merge
        accounting.  Any branch failure: the standard atomic failure path
        (one FAILED, sibling tasks cancelled, in-flight pool work drained
        and discarded, RUN_FINISHED failed); sibling results are never
        adopted.
        """
        par = entry.par
        instruction_id = f"par.inv-{idx + 1}"
        base = branch_root if branch_root is not None else self.workspace_root
        branch_tasks = self._par_branch_task_ids(run_id, par)
        branch_targets = [
            (
                branch.invocation.targets
                if branch.invocation is not None
                else branch.call.targets
            )
            for branch in par.branches
        ]
        published = list(par.barrier_targets) or [
            target for targets in branch_targets for target in targets
        ]

        def fail_par(error: str, failed_position: int | None = None) -> dict[str, Any]:
            """Fail the run at the PAR entry (standard atomic path).

            A branch-attributable failure carries the branch's FAILED
            event (invocation id ``par<k>``); a join-level failure (the
            artifact merge) carries the PAR entry's positional invocation
            id with the ``"par"`` payload marker — the PAR block owns no
            ledger task of its own, so neither carries a task_id (the
            audit exempts exactly these marked events).
            """
            records: list[_Record] = []
            if failed_position is not None:
                task_id = branch_tasks[failed_position - 1]
                records.extend([
                    _Record(
                        event_type=EventType.FAILED,
                        instruction_id=par_branch_summary(
                            par.branches[failed_position - 1]
                        ),
                        invocation_id=par_branch_invocation_id(failed_position),
                        task_id=task_id,
                        payload={"error": error},
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={"kind": "task_started", "id": task_id},
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
                ])
            else:
                records.append(_Record(
                    event_type=EventType.FAILED,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    payload={"error": error, "par": True},
                    store=self.store,
                ))
            for position, task_id in enumerate(branch_tasks, 1):
                self._cancel_task_if_unsettled(
                    run_id, task_id, records,
                    reason=(
                        f"[branch {position}] {error}"
                        if failed_position is not None
                        and position != failed_position
                        else None
                    ),
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

        # Branch tasks already terminal from a crashed earlier drive keep
        # their accounting; their outputs are re-read from the committed
        # child state instead of re-dispatching (at-least-once, and the
        # store's dup-SUCCEEDED guard stays untouched).  Issue #29: the
        # adoption is re-derived exactly as the live path does
        # (_adopt_branch_nodes on the terminal child run — a pure read of
        # committed state), not stored as an empty list.
        ledger = self.store.task_ledger(run_id)
        already_joined: dict[int, list[dict[str, Any]]] = {}
        pending_positions: list[int] = []
        for position, task_id in enumerate(branch_tasks, 1):
            task = ledger.tasks.get(task_id)
            if task is not None and task.status is TaskStatus.COMPLETED:
                child_run_id = par_branch_run_id(run_id, position)
                targets = branch_targets[position - 1]
                child_values: dict[str, Any] = {}
                adopted_nodes, _ = self._adopt_branch_nodes(
                    child_run_id, child_values, targets
                )
                already_joined[position] = adopted_nodes
            else:
                pending_positions.append(position)

        adopted_by_branch: dict[int, list[dict[str, Any]]] = dict(already_joined)
        branch_dirs: dict[str, str | None] = {
            f"par{position}": branch_workspace_dir(base, f"par{position}")
            for position in range(1, len(par.branches) + 1)
        }
        failure: dict[str, Any] | None = None
        max_at_once = max(1, min(par.max_count, len(par.branches)))

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_at_once
        ) as pool:
            in_flight: dict[int, concurrent.futures.Future] = {}
            queue = list(pending_positions)

            def dispatch_branch(position: int) -> dict[str, Any] | None:
                """Dispatch one branch; returns a failure result or None."""
                branch = par.branches[position - 1]
                branch_invocation_id = par_branch_invocation_id(position)
                child_run_id = par_branch_run_id(run_id, position)
                task_id = branch_tasks[position - 1]
                summary = par_branch_summary(branch)
                if gate is not None and gate.depth_exceeded(child_run_id):
                    return fail_par(
                        f"branch run {child_run_id} depth"
                        f" {gate.depth_of(child_run_id)} exceeds budget"
                        f" max_child_depth {gate.budget.max_child_depth}",
                        failed_position=position,
                    )
                try:
                    if branch.call is not None:
                        resolved = self._resolve_call_arguments(branch.call, values)
                    else:
                        resolved = self._resolve_branch_arguments(
                            branch.invocation, values
                        )
                except Exception as exc:
                    return fail_par(
                        f"PAR branch {position} ({summary}) failed to"
                        f" resolve arguments: {exc}",
                        failed_position=position,
                    )
                branch_workspace = branch_dirs[f"par{position}"]
                branch_claim = (
                    f"workspace:{child_run_id}"
                    if branch_workspace is not None
                    else None
                )
                # Issue #29: a resumed branch dispatched before the crash
                # carries pre-crash lifecycle events — never re-emit them
                # (same prior_types guard the plain-invocation path uses).
                branch_prior_types: set[EventType] = set()
                branch_task = ledger.tasks.get(task_id)
                if (
                    branch_task is not None
                    and branch_task.status is TaskStatus.IN_PROGRESS
                ):
                    branch_prior_types = {
                        event.event_type
                        for event in self.store.events(run_id)
                        if event.invocation_id == branch_invocation_id
                    }
                ready_records: list[_Record] = []
                if EventType.INVOCATION_READY not in branch_prior_types:
                    ready_records.append(_Record(
                        event_type=EventType.INVOCATION_READY,
                        instruction_id=summary,
                        invocation_id=branch_invocation_id,
                        task_id=task_id,
                        payload={"command": summary},
                        store=self.store,
                    ))
                if EventType.INVOCATION_DISPATCHED not in branch_prior_types:
                    ready_records.append(_Record(
                        event_type=EventType.INVOCATION_DISPATCHED,
                        instruction_id=summary,
                        invocation_id=branch_invocation_id,
                        task_id=task_id,
                        payload={
                            "child_run_id": child_run_id,
                            "branch_id": f"par{position}",
                        },
                        store=self.store,
                    ))
                if ready_records:
                    self.store.append_batch(run_id, ready_records)
                in_flight[position] = pool.submit(
                    self._execute_par_branch,
                    branch,
                    resolved,
                    run_id,
                    position,
                    gate,
                    claims,
                    branch_workspace,
                    branch_claim,
                )
                return None

            while queue or in_flight:
                if failure is not None:
                    break
                while queue and len(in_flight) < max_at_once:
                    position = queue.pop(0)
                    failure = dispatch_branch(position)
                    if failure is not None:
                        break
                if failure is not None or not in_flight:
                    break
                owner = {future: pos for pos, future in in_flight.items()}
                done, _ = concurrent.futures.wait(
                    list(in_flight.values()),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    position = owner[future]
                    del in_flight[position]
                    if failure is not None:
                        continue
                    branch = par.branches[position - 1]
                    task_id = branch_tasks[position - 1]
                    child_run_id = par_branch_run_id(run_id, position)
                    summary = par_branch_summary(branch)
                    try:
                        child = future.result()
                    except Exception as exc:
                        failure = fail_par(
                            f"PAR branch {position} ({summary}) failed:"
                            f" {exc}",
                            failed_position=position,
                        )
                        continue
                    child_status = child.get("status", "unknown")
                    if child_status != "succeeded":
                        child_error = child.get("error")
                        error = (
                            f"branch run {child_run_id} for"
                            f" {summary} finished with status"
                            f" {child_status!r}; the PAR branch cannot"
                            " adopt its outputs"
                        )
                        if child_error:
                            error = f"{error}: {child_error}"
                        failure = fail_par(error, failed_position=position)
                        continue
                    targets = branch_targets[position - 1]
                    try:
                        adopted_nodes, adopted_map = self._adopt_branch_nodes(
                            child_run_id, child["child_values"], targets
                        )
                    except Exception as exc:
                        failure = fail_par(str(exc), failed_position=position)
                        continue
                    branch_artifacts = [
                        {"branch": f"par{position}", "node": node["id"],
                         "path": node["value"]}
                        for node in adopted_nodes
                        if node["id"].startswith("ART.")
                        and isinstance(node["value"], str)
                    ]
                    self.store.append_batch(run_id, [
                        _Record(
                            event_type=EventType.RESULT_RECEIVED,
                            instruction_id=summary,
                            invocation_id=par_branch_invocation_id(position),
                            task_id=task_id,
                            payload={
                                "child_run_id": child_run_id,
                                "status": child_status,
                            },
                            store=self.store,
                        ),
                        _Record(
                            event_type=EventType.CHILD_ADOPTED,
                            instruction_id=summary,
                            invocation_id=par_branch_invocation_id(position),
                            task_id=task_id,
                            payload={
                                "child_run_id": child_run_id,
                                "adopted": adopted_map,
                                "child_status": child_status,
                                "artifacts": branch_artifacts,
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
                                    f"PAR branch {position} ({child_run_id})"
                                    f" -> {list(targets)}"
                                ),
                            },
                            store=self.store,
                        ),
                    ])
                    adopted_by_branch[position] = adopted_nodes

        if failure is not None:
            # In-flight branches are cancelled: not-yet-started branches
            # were never dispatched; started child runs run to completion
            # in their own histories while the pool drains, and their
            # results are discarded uncommitted (never adopted).
            return failure

        # -- barrier: all branches terminal and succeeded ------------------
        artifacts: list[dict[str, Any]] = []
        for position in range(1, len(par.branches) + 1):
            artifacts.extend(
                {
                    "branch": f"par{position}",
                    "node": node["id"],
                    "path": node["value"],
                }
                for node in adopted_by_branch.get(position, [])
                if node["id"].startswith("ART.")
                and isinstance(node["value"], str)
            )
        merged, merge_error = self._merge_branch_artifacts(
            run_id,
            f"{run_id}:{invocation_id}",
            claims,
            artifacts,
            branch_dirs,
        )
        if merge_error is not None:
            return fail_par(merge_error)

        if crash_hook is not None:
            # Crash window after every branch joined and the merge is
            # decided, before the entry's terminal batch: resume re-derives
            # the adoptions and the merge from committed state.
            crash_hook(idx)

        ordered_nodes: list[dict[str, Any]] = []
        branch_statuses: dict[str, str] = {}
        for position in range(1, len(par.branches) + 1):
            branch_statuses[f"par{position}"] = "succeeded"
            ordered_nodes.extend(adopted_by_branch.get(position, []))
        for node in ordered_nodes:
            values[node["id"]] = node["value"]

        par_record = {
            "max": par.max_count,
            "branches": branch_statuses,
            "targets": published,
            "merged_artifacts": merged,
        }
        expected_sv = self.store._current_state_version(run_id)
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.PAR_JOINED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                payload={
                    "branches": branch_statuses,
                    "targets": published,
                    "merged_artifacts": merged,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                expected_state_version=expected_sv,
                payload={
                    "delta": StateDelta(add_nodes=tuple(ordered_nodes)),
                    "par": par_record,
                },
                store=self.store,
            ),
        ])
        return None

    def _execute_par_branch(
        self,
        branch: ParBranch,
        resolved: Mapping[str, Any],
        parent_run_id: str,
        position: int,
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_workspace: str | None,
        branch_claim: str | None,
    ) -> dict[str, Any]:
        """Execute one PAR branch as an isolated child run (issue #24).

        A CALL branch loads its protocol and binds the resolved arguments
        (exactly like a CALL child run); a DO branch executes a synthetic
        single-invocation program whose INPUT declarations carry the
        dispatch-resolved argument values.  Both run under the
        deterministic child id ``<parent_run_id>:par<position>`` and
        inherit the branch's isolated workspace root and claim resource.
        """
        child_run_id = par_branch_run_id(parent_run_id, position)
        if branch.call is not None:
            protocol = load_protocol(branch.call.protocol, self.protocols_dir)
            child_values = self._bind_child_inputs(protocol, resolved)
            result = self._execute_program_child(
                protocol,
                child_run_id,
                parent_run_id,
                branch.call.protocol,
                child_values,
                gate,
                claims=claims,
                branch_workspace=branch_workspace,
                branch_claim=branch_claim,
            )
            result["protocol"] = protocol
            return result
        child_program = self._build_branch_program(
            branch.invocation, resolved
        )
        child_values = {
            declaration.ref: declaration.value
            for declaration in child_program.declarations
        }
        return self._execute_program_child(
            child_program,
            child_run_id,
            parent_run_id,
            f"par:{branch.invocation.command}",
            child_values,
            gate,
            claims=claims,
            branch_workspace=branch_workspace,
            branch_claim=branch_claim,
        )

    def _resolve_branch_arguments(
        self,
        invocation: Invocation,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Resolve a DO branch's arguments against the parent state.

        Same resolution rules as a plain invocation dispatch (guard first,
        bare refs and reference lists from ``values``, ``KB.*`` from the
        knowledge base, literals through) — pinned at dispatch time so the
        branch child observes exactly the committed state the PAR
        dispatch saw.
        """
        resolved: dict[str, Any] = {}
        for arg in invocation.args:
            self._reject_unresolved_refs(arg.value, values)
            if isinstance(arg.value, str) and arg.value in values:
                resolved[arg.name] = values[arg.value]
            elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                resolved[arg.name] = self._resolve_kb_ref(arg.value)
            elif isinstance(arg.value, list):
                resolved[arg.name] = [
                    values[item] if isinstance(item, str) and item in values
                    else self._resolve_kb_ref(item)
                    if isinstance(item, str) and item.startswith("KB.")
                    else item
                    for item in arg.value
                ]
            else:
                resolved[arg.name] = arg.value
        return resolved
