"""Deterministic sequential coordinator for tikhon programs.

Implements the runtime contract from docs/spec/03-runtime-and-events.md:
sequential invocation lifecycle, durable task ledger per invocation,
deterministic state commits, and failure handling without false
completion.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from tikhon.runtime.events import EventStore, EventType, _Record
from tikhon.runtime.tasks import TaskLedger, TaskLedgerError
from tikhon.state import StateDelta
from tikhon.syntax import load_protocol, validate_program
from tikhon.syntax.model import Argument, Call, Declaration, Invocation, Program, Return, Stop

if TYPE_CHECKING:
    from tikhon.memory import KnowledgeBase
    from tikhon.syntax.model import DonePredicate

__all__ = [
    "DeterministicWorker",
    "SequentialCoordinator",
    "evaluate_done_predicate",
    "map_results_to_targets",
]


@dataclasses.dataclass(frozen=True)
class _PlanEntry:
    """One flattened execution-plan entry (issue #12 protocol calls).

    ``task_prefix`` prefixes the ledger task text (``"protocol.name: "`` for
    steps expanded from a protocol, ``""`` for the caller's own steps).
    ``binds`` carry ``(protocol_name, call_args, declarations)`` triples
    applied in order before the entry's own arguments resolve — the first
    entry of a protocol expansion binds the protocol's INPUT declarations
    from the resolved CALL arguments.  ``finalizes`` carry
    ``(protocol_name, caller_targets)`` pairs applied in order after the
    entry's own targets commit — the last entry of a protocol expansion
    commits the protocol's RETURN refs to the caller's CALL targets.
    """

    invocation: Invocation
    task_prefix: str = ""
    binds: tuple[tuple[str, tuple[Argument, ...], tuple[Declaration, ...]], ...] = ()
    finalizes: tuple[tuple[str, tuple[str, ...]], ...] = ()

_BUILTIN_REGISTRY_DIGEST: str | None = None
_EFFECTFUL_COMMANDS: frozenset[str] | None = None


def _builtin_registry_digest() -> str:
    """Digest of the builtin command registry, computed once per process."""
    global _BUILTIN_REGISTRY_DIGEST
    if _BUILTIN_REGISTRY_DIGEST is None:
        from tikhon.registry.registry import builtin_registry, registry_digest

        _BUILTIN_REGISTRY_DIGEST = registry_digest(builtin_registry())
    return _BUILTIN_REGISTRY_DIGEST


def _effectful_commands() -> frozenset[str]:
    """Names of builtin commands whose effect class is a durable write.

    Resolved from the builtin registry (the contract source of truth), once
    per process.  Commands unknown to the builtin registry (custom worker
    handlers) are never treated as effectful.
    """
    global _EFFECTFUL_COMMANDS
    if _EFFECTFUL_COMMANDS is None:
        from tikhon.registry.enums import EffectClass
        from tikhon.registry.registry import builtin_registry

        durable = {EffectClass.REVERSIBLE_WRITE, EffectClass.IRREVERSIBLE_WRITE}
        registry = builtin_registry()
        _EFFECTFUL_COMMANDS = frozenset(
            name
            for name in registry.names()
            if registry.resolve(name).effect_class in durable
        )
    return _EFFECTFUL_COMMANDS


def _uses_kb_refs(program: Program) -> bool:
    """Whether any invocation argument mentions a ``KB.`` reference."""
    for statement in program.statements:
        if not isinstance(statement, Invocation):
            continue
        for arg in statement.args:
            if isinstance(arg.value, str) and arg.value.startswith("KB."):
                return True
            if isinstance(arg.value, list) and any(
                isinstance(item, str) and item.startswith("KB.")
                for item in arg.value
            ):
                return True
    return False


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


def _json_equal(left: Any, right: Any) -> bool:
    """JSON-strict equality: a bool never equals 0/1 (Python int/bool blur)."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, dict):
        return (
            isinstance(right, dict)
            and set(left) == set(right)
            and all(_json_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, list):
        return (
            isinstance(right, list)
            and len(left) == len(right)
            and all(_json_equal(item, other) for item, other in zip(left, right))
        )
    if isinstance(right, (dict, list)):
        return False
    return left == right


def evaluate_done_predicate(
    done: "DonePredicate",
    target_values: Mapping[str, Any],
) -> tuple[bool, str]:
    """Purely and deterministically evaluate a DONE predicate.

    Evaluates only over the committed ``target_values`` mapping: no worker
    calls, no clocks, no randomness, no I/O.  Returns ``(passed, detail)``
    where ``detail`` explains the failure and is empty on success.
    """
    actual = target_values.get(done.ref)
    if done.op == "equals":
        if _json_equal(actual, done.value):
            return True, ""
        return False, f"expected {done.value!r}, got {actual!r}"
    if done.op == "in":
        options = done.value if isinstance(done.value, list) else []
        if any(_json_equal(actual, option) for option in options):
            return True, ""
        return False, f"value {actual!r} not in {options!r}"
    if done.op == "matched":
        if not isinstance(actual, str):
            return False, (
                f"matched predicate requires a string value,"
                f" got {type(actual).__name__}"
            )
        if re.fullmatch(done.value, actual) is not None:
            return True, ""
        return False, f"value {actual!r} does not match pattern {done.value!r}"
    raise ValueError(f"unknown DONE predicate {done.op!r}")


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
    """Drives a tikhon program sequentially through an EventStore.

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

    def _bind_protocol_inputs(
        self,
        protocol_name: str,
        call_args: tuple[Argument, ...],
        declarations: tuple[Declaration, ...],
        values: dict[str, Any],
    ) -> None:
        """Bind a protocol's INPUT declarations from resolved CALL args.

        Binding mirrors program declarations: each INPUT ref is written
        into the shared run-state ``values`` mapping, keyed by its full
        typed reference, using the CALL argument whose name matches the
        declaration's leaf segment (validation guarantees an exact cover).
        """
        resolved: dict[str, Any] = {}
        for arg in call_args:
            resolved[arg.name] = self._resolve_arg_value(arg.value, values)
        for declaration in declarations:
            leaf = declaration.ref.split(".")[-1]
            values[declaration.ref] = resolved[leaf]

    @staticmethod
    def _apply_call_finalizes(
        finalizes: tuple[tuple[str, tuple[str, ...]], ...],
        target_values: Mapping[str, Any],
        values: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Commit protocol RETURN refs to the caller's CALL targets.

        Returns the extra state nodes to merge into the owning step's
        SUCCEEDED delta.  Validation pins CALL targets to a subset of the
        protocol's RETURN refs, so each target is committed from the value
        the protocol produced under the same reference (this step's own
        ``target_values`` first, then earlier run state); a missing ref
        raises and fails the run through the standard atomic path.
        """
        nodes: list[dict[str, Any]] = []
        seen = set(target_values)
        for protocol_name, caller_targets in finalizes:
            for target in caller_targets:
                if target in target_values:
                    value = target_values[target]
                elif target in values:
                    value = values[target]
                else:
                    raise ValueError(
                        f"protocol {protocol_name} did not commit RETURN"
                        f" reference {target}"
                    )
                if target not in seen:
                    nodes.append({"id": target, "value": value})
                    seen.add(target)
        return nodes

    def _build_plan(self, program: Program) -> list[_PlanEntry]:
        """Flatten the program into an execution plan (issue #12).

        Caller invocations keep their positions; each CALL expands the
        protocol's invocations inline at the call site with the protocol
        name prefixed onto their task texts and invocation ids continuing
        the parent sequence.  The expansion's first entry binds the
        protocol's INPUT declarations; the last entry commits the
        protocol's RETURN refs to the CALL targets.
        """
        entries: list[_PlanEntry] = []

        def walk(statements: tuple[object, ...], prefix: str) -> None:
            for statement in statements:
                if isinstance(statement, Invocation):
                    entries.append(_PlanEntry(statement, prefix))
                elif isinstance(statement, Call):
                    protocol = load_protocol(statement.protocol, self.protocols_dir)
                    before = len(entries)
                    walk(protocol.statements, f"{statement.protocol}: ")
                    if len(entries) == before:
                        # validate_program rejects empty protocols before
                        # execution; this is a defensive guard only.
                        raise ValueError(
                            f"protocol {statement.protocol} contains no"
                            " invocations to execute"
                        )
                    first = entries[before]
                    entries[before] = dataclasses.replace(
                        first,
                        binds=first.binds
                        + ((statement.protocol, statement.args, protocol.declarations),),
                    )
                    last = entries[-1]
                    entries[-1] = dataclasses.replace(
                        last,
                        finalizes=last.finalizes
                        + ((statement.protocol, statement.targets),),
                    )

        walk(program.statements, "")
        return entries

    def execute(self, program: Program, run_id: str = "run-1") -> dict[str, Any]:
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
        self.store.create_run(
            run_id,
            program_version,
            metadata={"program": program.name, "registry_digest": registry_digest},
        )

        self.store.append(
            run_id,
            EventType.RUN_STARTED,
            payload={
                "program": program.name,
                "version": program.version,
                "registry_digest": registry_digest,
            },
        )

        values: dict[str, Any] = {}
        for decl in program.declarations:
            values[decl.ref] = decl.value

        # Issue #12: flatten caller invocations and protocol-call
        # expansions into one sequential plan.  Protocol steps execute
        # inline through the same per-invocation loop below: their tasks
        # are created in the same up-front batch with the protocol name
        # prefixed onto the task text, and their invocation ids continue
        # the parent sequence.
        plan: list[_PlanEntry] = self._build_plan(program)

        # -- batch all task-creation records --------------------------
        statement_to_task: dict[int, str] = {}
        create_records: list[_Record] = []
        create_ledger = self.store.task_ledger(run_id)
        for idx, entry in enumerate(plan):
            statement = entry.invocation
            task = create_ledger.create_task(
                text=(
                    f"{entry.task_prefix}{statement.step_id}:"
                    f" DO {statement.command}"
                ),
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
            validation: dict[str, Any] | None = None,
        ) -> None:
            records = []
            if validation is not None:
                records.append(
                    _Record(
                        event_type=EventType.VALIDATION_FAILED,
                        instruction_id=statement.step_id,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload=validation,
                        store=self.store,
                    )
                )
            records.append(
                _Record(
                    event_type=EventType.FAILED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={"error": error},
                    store=self.store,
                )
            )
            records.append(
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "invocation_recorded", "id": task_id,
                        "tokens": 0, "cost": 0.0, "retries": 0,
                        "elapsed_seconds": 0.0,
                    },
                    store=self.store,
                )
            )
            records.append(
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={"kind": "task_cancelled", "id": task_id},
                    store=self.store,
                )
            )
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
                for pending_idx in range(idx + 1, len(plan))
            )
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": error},
                store=self.store,
            ))
            self.store.append_batch(run_id, records)

        failed = False
        error_msg: str | None = None

        for idx, entry in enumerate(plan):
            statement = entry.invocation
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

            # Issue #12: entering a protocol expansion binds the protocol's
            # INPUT declarations from the resolved CALL args (like program
            # declarations) before the first protocol step resolves its own
            # arguments.  Binding failures take the standard atomic path.
            for protocol_name, call_args, declarations in entry.binds:
                try:
                    self._bind_protocol_inputs(
                        protocol_name, call_args, declarations, values
                    )
                except Exception as exc:
                    failed = True
                    error_msg = f"protocol {protocol_name}: {exc}"
                    finish_failed_invocation(
                        idx, statement, invocation_id, task_id, error_msg
                    )
                    break
            if failed:
                break

            try:
                resolved_kwargs: dict[str, Any] = {}
                for arg in statement.args:
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
                    idx, statement, invocation_id, task_id, error_msg
                )
                break

            if (
                self.workspace_root is not None
                and statement.command in _effectful_commands()
            ):
                # WorkspacePolicy: effectful dispatches learn the declared
                # workspace root so handlers can sandbox their writes.
                resolved_kwargs["_workspace_root"] = self.workspace_root

            self.store.append(
                run_id,
                EventType.INVOCATION_DISPATCHED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={
                    "args": resolved_kwargs,
                    "idempotency_key": f"{run_id}:{invocation_id}",
                },
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
                        idx, statement, invocation_id, task_id, error_msg,
                        validation=validation_payload,
                    )
                    break

            # Issue #12: leaving a protocol expansion commits the protocol's
            # RETURN refs to the caller's CALL targets.  Applied before
            # VALIDATION_PASSED so a commit failure keeps the truthful
            # event order (no VALIDATION_PASSED before FAILED).
            try:
                finalize_nodes = self._apply_call_finalizes(
                    entry.finalizes, target_values, values
                )
            except Exception as exc:
                failed = True
                error_msg = str(exc)
                finish_failed_invocation(
                    idx, statement, invocation_id, task_id, error_msg
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
            add_nodes.extend(finalize_nodes)

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
