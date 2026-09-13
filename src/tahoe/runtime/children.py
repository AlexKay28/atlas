"""Child-run engine for the TAHOE coordinator (issue #38).

Extracted from coordinator.py: the CALL child-run machinery (start,
resume, read-back), child result adoption, PAR branch program synthesis,
and explicit artifact merge.  These methods are mixed into
``SequentialCoordinator`` via the ``ChildEngine`` mixin.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from tahoe.runtime.events import EventType, _Record
from tahoe.runtime.tasks import TaskStatus
from tahoe.syntax import load_protocol
from tahoe.syntax.model import (
    Argument,
    Call,
    Declaration,
    Invocation,
    Program,
    Return,
)

if TYPE_CHECKING:
    from tahoe.budgets import BudgetGate
    from tahoe.claims import ResourceLedger


class ChildEngine:
    """Mixin: CALL child runs, adoption, branch programs, artifact merge.

    Consumed by ``SequentialCoordinator`` — all methods assume the host
    class provides ``self.store``, ``self.worker``, ``self.memory``,
    ``self.workspace_root`` and ``self.protocols_dir``.
    """

    def _bind_child_inputs(
        self,
        protocol: Program,
        resolved: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Seed the child run's initial state from resolved CALL args (issue #20)."""
        child_values: dict[str, Any] = {
            declaration.ref: declaration.value
            for declaration in protocol.declarations
        }
        for declaration in protocol.declarations:
            leaf = declaration.ref.split(".")[-1]
            if leaf in resolved:
                child_values[declaration.ref] = resolved[leaf]
        return child_values

    @staticmethod
    def _apply_committed_deltas(values: dict[str, Any], events: Any) -> None:
        """Replay committed SUCCEEDED deltas onto a values mapping in seq order.

        Shared by resume (issue #10) and child adoption (issue #20):
        add/revise write, retire pops — reproducing the values mapping the
        coordinator held at any committed point of the run.
        """
        from tahoe.state import StateDelta

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

    def _execute_call_child(
        self,
        call: Call,
        resolved: Mapping[str, Any],
        parent_run_id: str,
        invocation_id: str,
        gate: "BudgetGate | None" = None,
        claims: "ResourceLedger | None" = None,
        branch_workspace: str | None = None,
        branch_claim: str | None = None,
    ) -> dict[str, Any]:
        """Start, resume, or read back the CALL's isolated child run (issue #20)."""
        protocol = load_protocol(call.protocol, self.protocols_dir)
        child_run_id = f"{parent_run_id}:{invocation_id}"
        child_values = self._bind_child_inputs(protocol, resolved)
        result = self._execute_program_child(
            protocol,
            child_run_id,
            parent_run_id,
            call.protocol,
            child_values,
            gate,
            claims=claims,
            branch_workspace=branch_workspace,
            branch_claim=branch_claim,
        )
        result["protocol"] = protocol
        return result

    def _execute_program_child(
        self,
        program: Program,
        child_run_id: str,
        parent_run_id: str,
        call_name: str | None,
        child_values: Mapping[str, Any],
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None" = None,
        branch_workspace: str | None = None,
        branch_claim: str | None = None,
        inherit_state: bool = False,
    ) -> dict[str, Any]:
        """Start, resume, or read back one isolated child run (issue #24).

        When ``inherit_state`` is True (issue #80 REFORMULATE), the child
        run's initial state includes all committed refs from the parent —
        the child plan inherits the parent's state namespace rather than
        running in isolation.  The child plan is still sealed
        (content-addressed).
        """
        try:
            self.store.run(child_run_id)
        except KeyError:
            result = self._execute_program(
                program,
                child_run_id,
                child_of=parent_run_id,
                call_name=call_name,
                initial_values=dict(child_values),
                gate=gate,
                claims=claims,
                branch_workspace=branch_workspace,
                branch_claim=branch_claim,
            )
            result["child_values"] = dict(child_values)
            return result
        events = self.store.events(child_run_id)
        finished = [
            event for event in events
            if event.event_type is EventType.RUN_FINISHED
        ]
        if finished:
            payload = (
                finished[-1].payload
                if isinstance(finished[-1].payload, dict)
                else {}
            )
            result: dict[str, Any] = {
                "run_id": child_run_id,
                "status": payload.get("status", "unknown"),
                "outputs": {},
                "child_values": dict(child_values),
            }
            if "error" in payload:
                result["error"] = payload["error"]
            return result
        result = self._resume_existing_run(
            program,
            child_run_id,
            initial_values=dict(child_values),
            gate=gate,
            claims=claims,
            branch_workspace=branch_workspace,
            branch_claim=branch_claim,
        )
        result["child_values"] = dict(child_values)
        return result

    def _adopt_child_result(
        self,
        call: Call,
        child: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Map the child's RETURN refs onto the CALL targets (issue #20)."""
        child_run_id = child["run_id"]
        values: dict[str, Any] = dict(child["child_values"])
        self._apply_committed_deltas(values, self.store.events(child_run_id))
        adopted_nodes: list[dict[str, Any]] = []
        adopted_map: dict[str, str] = {}
        for target in call.targets:
            if target not in values:
                raise ValueError(
                    f"child run {child_run_id} for {call.protocol} did not"
                    f" commit RETURN reference {target}"
                )
            adopted_nodes.append({"id": target, "value": values[target]})
            adopted_map[target] = target
        return adopted_nodes, adopted_map

    def _adopt_branch_nodes(
        self,
        child_run_id: str,
        child_values: Mapping[str, Any],
        targets: tuple[str, ...],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Map a PAR branch child's committed refs onto the parent (issue #24)."""
        values: dict[str, Any] = dict(child_values)
        self._apply_committed_deltas(values, self.store.events(child_run_id))
        adopted_nodes: list[dict[str, Any]] = []
        adopted_map: dict[str, str] = {}
        for target in targets:
            if target not in values:
                raise ValueError(
                    f"branch run {child_run_id} did not commit reference"
                    f" {target}"
                )
            adopted_nodes.append({"id": target, "value": values[target]})
            adopted_map[target] = target
        return adopted_nodes, adopted_map

    def _build_branch_program(
        self,
        branch_invocation: Invocation,
        resolved_kwargs: Mapping[str, Any],
    ) -> Program:
        """The synthetic single-invocation child program for a DO branch."""
        declarations = tuple(
            Declaration(f"Q.{name}", value)
            for name, value in resolved_kwargs.items()
        )
        args = tuple(
            Argument(name, f"Q.{name}", argument.line)
            for name, argument in (
                (argument.name, argument) for argument in branch_invocation.args
            )
        )
        invocation = dataclasses.replace(branch_invocation, args=args)
        return Program(
            "par_branch",
            "1.0",
            declarations,
            (invocation, Return(invocation.targets)),
        )

    def _merge_branch_artifacts(
        self,
        run_id: str,
        owner: str,
        claims: "ResourceLedger | None",
        artifacts: list[dict[str, Any]],
        branch_dirs: Mapping[str, str | None],
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Integrate branch-produced artifacts into the parent workspace (issue #23)."""
        if not artifacts:
            return [], None
        resource = f"merge:{run_id}"
        if claims is not None:
            if not claims.claim(resource, owner):
                return [], (
                    f"resource claim failed: {resource} is held by"
                    f" {claims.holder(resource)!r}"
                )
        try:
            seen: dict[str, str] = {}
            for artifact in artifacts:
                path = artifact["path"]
                prior = seen.get(path)
                if prior is not None and prior != artifact["branch"]:
                    return [], (
                        f"artifact merge collision: relative path"
                        f" {path!r} was produced by branches"
                        f" {prior!r} and {artifact['branch']!r}; refusing"
                        " to overwrite — integrate the branches explicitly"
                    )
                seen[path] = artifact["branch"]
            merged: list[dict[str, Any]] = []
            for artifact in artifacts:
                entry: dict[str, Any] = {
                    "branch": artifact["branch"],
                    "node": artifact["node"],
                    "path": artifact["path"],
                }
                branch_dir = branch_dirs.get(artifact["branch"])
                if self.workspace_root is not None and branch_dir is not None:
                    source = Path(branch_dir) / artifact["path"]
                    if source.is_file():
                        destination = Path(self.workspace_root) / artifact["path"]
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, destination)
                        entry["copied"] = True
                    else:
                        entry["copied"] = False
                merged.append(entry)
            return merged, None
        finally:
            if claims is not None:
                claims.release(resource, owner)
