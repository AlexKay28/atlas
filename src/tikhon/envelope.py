"""Harness-neutral task/result envelope protocol (issue #18).

Defines the canonical JSON envelopes for (a) coordinator -> worker task
dispatch (:class:`TaskEnvelope`) and (b) worker -> coordinator result
submission (:class:`ResultEnvelope`), with strict validation and clear
errors.  The envelopes are the shared contract any backend driver can
implement — the #8 ``ModelWorker`` adapter renders its prompt FROM a
TaskEnvelope and parses replies INTO a ResultEnvelope, and the sequential
external driver (``tikhon next`` / ``tikhon submit``) moves them through
the event store so the worker process never needs to hold the store open.

Envelope schema (v1) — TaskEnvelope::

    schema_version  "1"
    run_id          coordinator run identity (nonempty)
    invocation_id   positional invocation id "inv-N" (nonempty)
    task_id         ledger task id (nonempty)
    attempt         >= 1 dispatch attempt this envelope answers
    idempotency_key "<run_id>:<invocation_id>" dedup contract
    command         registered command name
    command_version resolved contract version
    arguments       resolved, JSON-serializable kwargs (pinned input snapshot)
    input_digest    sha256 over canonical {"command", "arguments"}
    targets         step target refs (empty only for adapter-scoped
                    direct dispatch, where the coordinator's 2-argument
                    seam carries no target refs)
    done            {"op","ref","value"} DONE predicate or null
    contract        summary of the resolved command contract
    workspace_root  workspace binding for effectful commands (or null)
    program         {"name","version"} of the owning program
    seal_digest     sealed program digest (or null)
    deadline_seconds contract budget deadline (or null)

ResultEnvelope::

    schema_version  "1"
    run_id / invocation_id / task_id / attempt / idempotency_key / command
                    echo the answered TaskEnvelope identity
    status          "succeeded" | "failed" | "blocked"
    payload         JSON-serializable DO result (succeeded)
    evidence        tuple of artifact refs / digests supporting the result
    error           required nonempty for failed/blocked, null otherwise
    receipt         execution receipt; receipt["usage"]["tokens"] is a
                    measured int, or null when the telemetry is UNAVAILABLE
                    (distinguish unavailable telemetry from measured zero)

Also hosts the sequential external driver: :class:`ExternalDriver` renders
TaskEnvelopes for a run's next ready invocation from the event store and
commits submitted ResultEnvelopes through the same coordinator machinery
(plan building, task ledger, event shapes and validation rules are reused
from ``runtime.coordinator`` / ``runtime.events`` — neither is modified).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from tikhon.registry.enums import EffectClass
from tikhon.runtime.coordinator import (
    SequentialCoordinator,
    evaluate_done_predicate,
    map_results_to_targets,
)
from tikhon.runtime.events import EventStore, EventType, _Record
from tikhon.state import StateDelta

__all__ = [
    "DIRECT_DISPATCH_INVOCATION_ID",
    "DIRECT_DISPATCH_RUN_ID",
    "DIRECT_DISPATCH_TASK_ID",
    "ENVELOPE_SCHEMA_VERSION",
    "RESULT_STATUSES",
    "DriverError",
    "EnvelopeValidationError",
    "ExternalDriver",
    "ResultEnvelope",
    "TaskEnvelope",
    "build_task_envelope",
    "done_predicate_to_dict",
    "envelope_input_digest",
]

#: Wire-format version.  ``from_json`` rejects any other value.
ENVELOPE_SCHEMA_VERSION = "1"

#: Result statuses accepted by the protocol (issue #18).
RESULT_STATUSES = ("succeeded", "failed", "blocked")

#: Identity placeholders for adapter-scoped dispatch: ``ModelWorker``
#: answers the coordinator's pinned 2-argument ``execute`` seam, which
#: carries no run identity, so it renders a self-consistent direct-dispatch
#: envelope whose idempotency key digests the command and its arguments.
DIRECT_DISPATCH_RUN_ID = "direct"
DIRECT_DISPATCH_INVOCATION_ID = "dispatch"
DIRECT_DISPATCH_TASK_ID = "direct"

_DONE_OPS = ("equals", "in", "matched")

_TASK_ENVELOPE_FIELDS = (
    "schema_version",
    "run_id",
    "invocation_id",
    "task_id",
    "attempt",
    "idempotency_key",
    "command",
    "command_version",
    "arguments",
    "input_digest",
    "targets",
    "done",
    "contract",
    "workspace_root",
    "program",
    "seal_digest",
    "deadline_seconds",
)

_RESULT_ENVELOPE_FIELDS = (
    "schema_version",
    "run_id",
    "invocation_id",
    "task_id",
    "attempt",
    "idempotency_key",
    "command",
    "status",
    "payload",
    "evidence",
    "error",
    "receipt",
)


class EnvelopeValidationError(ValueError):
    """An envelope is malformed: clear message naming the defect."""


class DriverError(Exception):
    """The external driver refused an operation (stale, duplicate,
    terminal, or unbound invocation)."""


def _canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise EnvelopeValidationError(message)


def _nonempty_str(value: Any, field: str) -> None:
    _check(
        isinstance(value, str) and value != "",
        f"envelope field {field!r} must be a nonempty string, got {value!r}",
    )


def _json_serializable(value: Any, field: str) -> None:
    try:
        _canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise EnvelopeValidationError(
            f"envelope field {field!r} is not JSON-serializable: {exc}"
        ) from exc


def _string_list(value: Any, field: str) -> None:
    _check(
        isinstance(value, (list, tuple))
        and all(isinstance(item, str) and item for item in value),
        f"envelope field {field!r} must be a list of nonempty strings,"
        f" got {value!r}",
    )


def envelope_input_digest(command: str, arguments: Mapping[str, Any]) -> str:
    """Sha256 over the canonical ``{"command", "arguments"}`` snapshot."""
    payload = _canonical_json({"arguments": dict(arguments), "command": command})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def done_predicate_to_dict(done: Any) -> Optional[dict[str, Any]]:
    """Normalize a DONE predicate (dict or ``DonePredicate``-shaped) to a dict."""
    if done is None:
        return None
    if isinstance(done, Mapping):
        return {"op": done["op"], "ref": done["ref"], "value": done["value"]}
    return {"op": done.op, "ref": done.ref, "value": done.value}


def build_task_envelope(
    registry: Any,
    *,
    run_id: str,
    invocation_id: str,
    task_id: str,
    attempt: int,
    idempotency_key: str,
    command: str,
    arguments: Mapping[str, Any],
    targets: Iterable[str],
    done: Any = None,
    workspace_root: Optional[str] = None,
    program: Optional[Mapping[str, Any]] = None,
    seal_digest: Optional[str] = None,
) -> "TaskEnvelope":
    """Render a TaskEnvelope for one dispatch against a command registry.

    Resolves the command contract from ``registry`` and summarizes it into
    the envelope's ``contract`` block; computes ``input_digest`` over the
    pinned resolved arguments; carries the output contract (targets and
    DONE predicate) and the workspace binding.
    """
    spec = registry.resolve(command)
    budget = spec.budget
    contract = {
        "purpose": spec.purpose,
        "inputs": list(spec.inputs),
        "outputs": list(spec.outputs),
        "done_condition": spec.done,
        "effect_class": spec.effect_class.value,
        "execution": spec.execution.value,
        "capabilities": list(spec.capabilities),
        "budget": {
            "max_seconds": budget.max_seconds,
            "max_tokens": budget.max_tokens,
            "max_cost": budget.max_cost,
            "max_attempts": budget.max_attempts,
            "max_output_bytes": budget.max_output_bytes,
        },
    }
    return TaskEnvelope(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        run_id=run_id,
        invocation_id=invocation_id,
        task_id=task_id,
        attempt=attempt,
        idempotency_key=idempotency_key,
        command=command,
        command_version=spec.version,
        arguments=dict(arguments),
        input_digest=envelope_input_digest(command, arguments),
        targets=tuple(targets),
        done=done_predicate_to_dict(done),
        contract=contract,
        workspace_root=workspace_root,
        program=dict(program) if program is not None else None,
        seal_digest=seal_digest,
        deadline_seconds=budget.max_seconds,
    )


@dataclass(frozen=True)
class TaskEnvelope:
    """Coordinator -> worker task dispatch envelope (schema v1)."""

    schema_version: str
    run_id: str
    invocation_id: str
    task_id: str
    attempt: int
    idempotency_key: str
    command: str
    command_version: str
    arguments: dict[str, Any]
    input_digest: str
    targets: tuple[str, ...]
    done: Optional[dict[str, Any]]
    contract: dict[str, Any]
    workspace_root: Optional[str]
    program: Optional[dict[str, Any]]
    seal_digest: Optional[str]
    deadline_seconds: Optional[float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "targets", tuple(self.targets))

    # -- validation ----------------------------------------------------

    def validate(self) -> None:
        """Strictly validate; raise :class:`EnvelopeValidationError`."""
        _check(
            self.schema_version == ENVELOPE_SCHEMA_VERSION,
            f"unsupported envelope schema_version {self.schema_version!r};"
            f" expected {ENVELOPE_SCHEMA_VERSION!r}",
        )
        for field in ("run_id", "invocation_id", "task_id", "idempotency_key",
                      "command", "command_version", "input_digest"):
            _nonempty_str(getattr(self, field), field)
        _check(
            isinstance(self.attempt, int)
            and not isinstance(self.attempt, bool)
            and self.attempt >= 1,
            f"envelope field 'attempt' must be an integer >= 1,"
            f" got {self.attempt!r}",
        )
        _check(
            isinstance(self.arguments, Mapping),
            f"envelope field 'arguments' must be a JSON object,"
            f" got {type(self.arguments).__name__}",
        )
        _check(
            all(isinstance(key, str) for key in self.arguments),
            "envelope field 'arguments' must have string keys",
        )
        _json_serializable(dict(self.arguments), "arguments")
        # Targets may be empty only for adapter-scoped direct dispatch,
        # where the coordinator's pinned 2-argument seam carries no target
        # refs; every grammatical invocation targets at least one ref and
        # driver-rendered envelopes always carry them.
        _string_list(self.targets, "targets")
        if self.done is not None:
            _check(
                isinstance(self.done, Mapping)
                and set(self.done) == {"op", "ref", "value"},
                "envelope field 'done' must be an object with exactly"
                f" op/ref/value keys, got {self.done!r}",
            )
            _nonempty_str(self.done.get("op"), "done.op")
            _nonempty_str(self.done.get("ref"), "done.ref")
            _check(
                self.done.get("op") in _DONE_OPS,
                f"envelope field 'done.op' must be one of {_DONE_OPS},"
                f" got {self.done.get('op')!r}",
            )
            _json_serializable(self.done.get("value"), "done.value")
        _check(
            isinstance(self.contract, Mapping),
            f"envelope field 'contract' must be a JSON object,"
            f" got {type(self.contract).__name__}",
        )
        for field in ("purpose", "done_condition", "effect_class", "execution"):
            _nonempty_str(self.contract.get(field), f"contract.{field}")
        for field in ("inputs", "outputs", "capabilities"):
            _string_list(self.contract.get(field), f"contract.{field}")
        _check(
            isinstance(self.contract.get("budget"), Mapping),
            "envelope field 'contract.budget' must be a JSON object",
        )
        if self.workspace_root is not None:
            _nonempty_str(self.workspace_root, "workspace_root")
        if self.program is not None:
            _check(
                isinstance(self.program, Mapping)
                and isinstance(self.program.get("name"), str)
                and isinstance(self.program.get("version"), str),
                "envelope field 'program' must be an object with string"
                f" name/version, got {self.program!r}",
            )
        if self.seal_digest is not None:
            _nonempty_str(self.seal_digest, "seal_digest")
        if self.deadline_seconds is not None:
            _check(
                isinstance(self.deadline_seconds, (int, float))
                and not isinstance(self.deadline_seconds, bool)
                and self.deadline_seconds > 0,
                f"envelope field 'deadline_seconds' must be a positive"
                f" number, got {self.deadline_seconds!r}",
            )

    # -- serialization -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict form."""
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "invocation_id": self.invocation_id,
            "task_id": self.task_id,
            "attempt": self.attempt,
            "idempotency_key": self.idempotency_key,
            "command": self.command,
            "command_version": self.command_version,
            "arguments": self.arguments,
            "input_digest": self.input_digest,
            "targets": list(self.targets),
            "done": self.done,
            "contract": self.contract,
            "workspace_root": self.workspace_root,
            "program": self.program,
            "seal_digest": self.seal_digest,
            "deadline_seconds": self.deadline_seconds,
        }

    def to_json(self) -> str:
        """Canonical JSON after strict validation."""
        self.validate()
        return _canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "TaskEnvelope":
        """Parse and strictly validate a wire envelope."""
        return cls.from_dict(_load_envelope_object(
            text, "task", _TASK_ENVELOPE_FIELDS
        ))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TaskEnvelope":
        """Build from a mapping with strict field checks."""
        _check_envelope_fields(data, "task", _TASK_ENVELOPE_FIELDS)
        envelope = cls(
            schema_version=data["schema_version"],
            run_id=data["run_id"],
            invocation_id=data["invocation_id"],
            task_id=data["task_id"],
            attempt=data["attempt"],
            idempotency_key=data["idempotency_key"],
            command=data["command"],
            command_version=data["command_version"],
            arguments=dict(data["arguments"]),
            input_digest=data["input_digest"],
            targets=tuple(data["targets"]),
            done=dict(data["done"]) if data["done"] is not None else None,
            contract=dict(data["contract"]),
            workspace_root=data["workspace_root"],
            program=dict(data["program"]) if data["program"] is not None else None,
            seal_digest=data["seal_digest"],
            deadline_seconds=data["deadline_seconds"],
        )
        envelope.validate()
        return envelope


@dataclass(frozen=True)
class ResultEnvelope:
    """Worker -> coordinator result submission envelope (schema v1)."""

    schema_version: str
    run_id: str
    invocation_id: str
    task_id: str
    attempt: int
    idempotency_key: str
    command: str
    status: str
    payload: Any
    evidence: tuple[str, ...]
    error: Optional[str]
    receipt: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if self.error == "":
            object.__setattr__(self, "error", None)

    # -- validation ----------------------------------------------------

    def validate(self) -> None:
        """Strictly validate; raise :class:`EnvelopeValidationError`."""
        _check(
            self.schema_version == ENVELOPE_SCHEMA_VERSION,
            f"unsupported envelope schema_version {self.schema_version!r};"
            f" expected {ENVELOPE_SCHEMA_VERSION!r}",
        )
        for field in ("run_id", "invocation_id", "task_id", "idempotency_key",
                      "command"):
            _nonempty_str(getattr(self, field), field)
        _check(
            isinstance(self.attempt, int)
            and not isinstance(self.attempt, bool)
            and self.attempt >= 1,
            f"envelope field 'attempt' must be an integer >= 1,"
            f" got {self.attempt!r}",
        )
        _check(
            self.status in RESULT_STATUSES,
            f"envelope field 'status' must be one of {RESULT_STATUSES},"
            f" got {self.status!r}",
        )
        _json_serializable(self.payload, "payload")
        _string_list(self.evidence, "evidence")
        if self.status == "succeeded":
            _check(
                self.error is None,
                "envelope field 'error' must be null when status is"
                f" 'succeeded', got {self.error!r}",
            )
        else:
            _nonempty_str(self.error, "error")
        _check(
            isinstance(self.receipt, Mapping),
            f"envelope field 'receipt' must be a JSON object,"
            f" got {type(self.receipt).__name__}",
        )
        _json_serializable(dict(self.receipt), "receipt")

    # -- serialization -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict form."""
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "invocation_id": self.invocation_id,
            "task_id": self.task_id,
            "attempt": self.attempt,
            "idempotency_key": self.idempotency_key,
            "command": self.command,
            "status": self.status,
            "payload": self.payload,
            "evidence": list(self.evidence),
            "error": self.error,
            "receipt": self.receipt,
        }

    def to_json(self) -> str:
        """Canonical JSON after strict validation."""
        self.validate()
        return _canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "ResultEnvelope":
        """Parse and strictly validate a wire envelope."""
        return cls.from_dict(_load_envelope_object(
            text, "result", _RESULT_ENVELOPE_FIELDS
        ))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResultEnvelope":
        """Build from a mapping with strict field checks."""
        _check_envelope_fields(data, "result", _RESULT_ENVELOPE_FIELDS)
        envelope = cls(
            schema_version=data["schema_version"],
            run_id=data["run_id"],
            invocation_id=data["invocation_id"],
            task_id=data["task_id"],
            attempt=data["attempt"],
            idempotency_key=data["idempotency_key"],
            command=data["command"],
            status=data["status"],
            payload=data["payload"],
            evidence=tuple(data["evidence"]),
            error=data["error"],
            receipt=dict(data["receipt"]),
        )
        envelope.validate()
        return envelope


def _load_envelope_object(
    text: str, kind: str, fields: tuple[str, ...]
) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise EnvelopeValidationError(
            f"{kind} envelope is not valid JSON: {exc}"
        ) from exc
    _check(
        isinstance(data, dict),
        f"{kind} envelope must be a JSON object, got {type(data).__name__}",
    )
    return data


def _check_envelope_fields(
    data: Mapping[str, Any], kind: str, fields: tuple[str, ...]
) -> None:
    known = set(fields)
    unknown = sorted(set(data) - known)
    if unknown:
        raise EnvelopeValidationError(
            f"{kind} envelope has unknown fields: {', '.join(unknown)};"
            f" known fields: {', '.join(fields)}"
        )
    missing = sorted(known - set(data))
    if missing:
        raise EnvelopeValidationError(
            f"{kind} envelope is missing fields: {', '.join(missing)}"
        )


# --------------------------------------------------------------------------
# Sequential external driver (issue #18 round trip)
# --------------------------------------------------------------------------


_INVOCATION_PATTERN = re.compile(r"^inv-(\d+)$")


class _PlanHelperWorker:
    """Worker stand-in so the coordinator's plan helpers can be reused
    without ever dispatching a worker call."""

    def __init__(self, commands: Iterable[str]):
        self._commands = set(commands)

    @property
    def commands(self) -> set[str]:
        return self._commands

    def execute(self, command: str, resolved_kwargs: dict[str, Any]) -> Any:
        raise AssertionError("external driver never dispatches a worker call")


class ExternalDriver:
    """Sequential external driver over an EventStore (issue #18).

    Renders a :class:`TaskEnvelope` for a run's next ready invocation
    (:meth:`next_envelope`, used by ``tikhon next``) and commits a submitted
    :class:`ResultEnvelope` (:meth:`submit_result`, used by ``tikhon
    submit``) through the same coordinator machinery: plan flattening, task
    ledger transitions, event shapes and the coordinator's own validation
    functions are reused from ``SequentialCoordinator`` — the coordinator
    itself is not modified.

    Each process opens its own store; the external worker never holds the
    store open.  Runs driven this way are indistinguishable in the event
    log from coordinator-driven runs (module tests assert the identical
    event-type sequence).
    """

    def __init__(
        self,
        store: EventStore,
        program: Any,
        run_id: str,
        *,
        registry: Any = None,
        memory: Any = None,
        workspace_root: Optional[str] = None,
        protocols_dir: Any = None,
        seal_digest: Optional[str] = None,
    ):
        if registry is None:
            from tikhon.registry import builtin_registry

            registry = builtin_registry()
        self.store = store
        self.program = program
        self.run_id = run_id
        self.registry = registry
        self.memory = memory
        self.workspace_root = workspace_root
        self.seal_digest = seal_digest
        self._helper = SequentialCoordinator(
            store,
            _PlanHelperWorker(registry.names()),
            memory=memory,
            workspace_root=workspace_root,
            protocols_dir=protocols_dir,
        )
        self._plan: Optional[list] = None

    # -- shared helpers --------------------------------------------------

    def _plan_entries(self) -> list:
        if self._plan is None:
            if self.program is None:
                raise DriverError(
                    "ExternalDriver requires the program for this operation"
                )
            # The sequential driver replays exactly the coordinator's
            # unconditional plan; source-anchored conditionals and protocol
            # calls are out of scope and rejected up front, never silently
            # skipped.
            from tikhon.syntax.model import Call, Conditional

            for statement in self.program.statements:
                if isinstance(statement, (Conditional, Call)):
                    raise DriverError(
                        "external driver supports plain sequential DO steps"
                        " only: the program contains an IF conditional or"
                        " CALL statement"
                    )
            plan = self._helper._build_plan(self.program)
            for entry in plan:
                unsupported = (
                    entry.condition is not None
                    or entry.binds
                    or entry.finalizes
                )
                if unsupported:
                    raise DriverError(
                        "external driver supports plain sequential DO steps"
                        f" only: step {entry.invocation.step_id} carries an"
                        " IF condition, CALL expansion, or protocol"
                        " finalize clause"
                    )
            self._plan = plan
        return self._plan

    def _require_run(self) -> tuple:
        """Load the run and its events; raise DriverError when unknown."""
        try:
            self.store.run(self.run_id)
            return self.store.events(self.run_id)
        except KeyError as exc:
            raise DriverError(f"unknown run: {self.run_id!r}") from exc

    def _reject_terminal(self, events: tuple) -> None:
        for event in events:
            if event.event_type is EventType.RUN_FINISHED:
                payload = event.payload if isinstance(event.payload, dict) else {}
                raise DriverError(
                    f"run {self.run_id!r} is already terminal"
                    f" (status {payload.get('status', 'unknown')!r});"
                    " no further invocations or results are accepted"
                )

    def _check_program_identity(self, events: tuple) -> None:
        """The run must belong to this program (resume's identity rule)."""
        if self.program is None:
            return
        run_started = next(
            (
                event
                for event in events
                if event.event_type is EventType.RUN_STARTED
            ),
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
            if recorded != (self.program.name, self.program.version):
                raise DriverError(
                    f"program {self.program.name}@{self.program.version}"
                    f" does not match the run's recorded program"
                    f" {recorded[0]}@{recorded[1]}"
                )

    def _values(self, events: tuple) -> dict[str, Any]:
        """Rebuild the run-state values mapping (resume's replay rule)."""
        values: dict[str, Any] = {}
        for decl in self.program.declarations:
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
        return values

    def _succeeded_prefix(self, events: tuple) -> int:
        """First plan index without a SUCCEEDED terminal (resume's rule)."""
        succeeded = {
            event.invocation_id
            for event in events
            if event.event_type is EventType.SUCCEEDED and event.invocation_id
        }
        plan = self._plan_entries()
        start_idx = len(plan)
        for idx in range(len(plan)):
            if f"inv-{idx + 1}" not in succeeded:
                start_idx = idx
                break
        expected = {f"inv-{i + 1}" for i in range(start_idx)}
        if succeeded != expected:
            raise DriverError(
                f"run {self.run_id!r} has a non-prefix set of SUCCEEDED"
                f" invocations {sorted(succeeded)}; impossible for the"
                " sequential coordinator"
            )
        return start_idx

    def _statement_to_task(self) -> dict[int, str]:
        """Positional plan-index -> task-id mapping (creation order rule)."""
        ledger = self.store.task_ledger(self.run_id)
        task_ids = list(ledger.tasks)
        plan = self._plan_entries()
        if len(task_ids) != len(plan):
            raise DriverError(
                f"run {self.run_id!r} has {len(task_ids)} ledger tasks but"
                f" the program plans {len(plan)} steps; refusing to drive a"
                " mismatched program"
            )
        return {idx: task_ids[idx] for idx in range(len(plan))}

    def _effectful_commands(self) -> frozenset[str]:
        durable = {
            EffectClass.REVERSIBLE_WRITE,
            EffectClass.IRREVERSIBLE_WRITE,
        }
        return frozenset(
            name
            for name in self.registry.names()
            if self.registry.resolve(name).effect_class in durable
        )

    # -- next ------------------------------------------------------------

    def next_envelope(self) -> TaskEnvelope:
        """Dispatch (or re-render) the next ready invocation's envelope.

        The first call on a fresh run starts it exactly like the
        coordinator does (create_run, RUN_STARTED with the registry
        digest, one batch-created ledger task per plan entry); later calls
        are pure driver steps over the committed event prefix.
        """
        plan = self._plan_entries()
        try:
            self.store.run(self.run_id)
        except KeyError:
            self._start_run(plan)
        self._reject_terminal(self.store.events(self.run_id))
        events = self.store.events(self.run_id)
        self._check_program_identity(events)

        start_idx = self._succeeded_prefix(events)
        if start_idx >= len(plan):
            raise DriverError(
                f"run {self.run_id!r} has no ready invocation: every plan"
                " step already succeeded"
            )
        entry = plan[start_idx]
        statement = entry.invocation
        invocation_id = f"inv-{start_idx + 1}"
        statement_to_task = self._statement_to_task()
        task_id = statement_to_task[start_idx]

        ledger = self.store.task_ledger(self.run_id)
        task = ledger.tasks[task_id]
        invocation_events = [
            event
            for event in events
            if event.invocation_id == invocation_id
        ]
        prior_types = {event.event_type for event in invocation_events}

        if task.status.value == "pending" and not prior_types:
            ledger.start_task(task_id)
            self.store.append_batch(self.run_id, [
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
        elif task.status.value == "in_progress":
            # In-flight re-render (crash window or repeated `next`):
            # committed lifecycle events are never re-emitted.
            if EventType.INVOCATION_READY not in prior_types:
                self.store.append(
                    self.run_id,
                    EventType.INVOCATION_READY,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={"command": statement.command},
                )
        else:
            raise DriverError(
                f"task {task_id} for step {statement.step_id} is"
                f" {task.status.value}; cannot dispatch"
            )

        values = self._values(events)
        resolved_kwargs = self._resolve_arguments(statement, values)

        if EventType.INVOCATION_DISPATCHED not in prior_types:
            self.store.append(
                self.run_id,
                EventType.INVOCATION_DISPATCHED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={
                    "args": resolved_kwargs,
                    "idempotency_key": f"{self.run_id}:{invocation_id}",
                    "command": statement.command,
                    "targets": list(statement.targets),
                    "done": done_predicate_to_dict(statement.done),
                    "revisions": list(statement.revisions),
                    "retirements": list(statement.retirements),
                },
            )

        events = self.store.events(self.run_id)
        attempt = sum(
            1
            for event in events
            if event.invocation_id == invocation_id
            and event.event_type is EventType.INVOCATION_DISPATCHED
        )
        return build_task_envelope(
            self.registry,
            run_id=self.run_id,
            invocation_id=invocation_id,
            task_id=task_id,
            attempt=attempt,
            idempotency_key=f"{self.run_id}:{invocation_id}",
            command=statement.command,
            arguments=resolved_kwargs,
            targets=statement.targets,
            done=statement.done,
            workspace_root=self.workspace_root,
            program={"name": self.program.name, "version": self.program.version},
            seal_digest=self.seal_digest,
        )

    def _start_run(self, plan: list) -> None:
        """Fresh-start the run with the coordinator's exact event prefix."""
        from tikhon.registry.registry import registry_digest

        digest = registry_digest(self.registry)
        self.store.create_run(
            self.run_id,
            f"{self.program.name}@{self.program.version}",
            metadata={"program": self.program.name, "registry_digest": digest},
        )
        self.store.append(
            self.run_id,
            EventType.RUN_STARTED,
            payload={
                "program": self.program.name,
                "version": self.program.version,
                "registry_digest": digest,
            },
        )
        self._helper._create_plan_tasks(self.run_id, plan)

    def _resolve_arguments(
        self, statement: Any, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Resolve invocation arguments exactly like the coordinator."""
        resolved: dict[str, Any] = {}
        for arg in statement.args:
            SequentialCoordinator._reject_unresolved_refs(arg.value, values)
            if isinstance(arg.value, str) and arg.value in values:
                resolved[arg.name] = values[arg.value]
            elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                resolved[arg.name] = self._helper._resolve_kb_ref(arg.value)
            elif isinstance(arg.value, list):
                resolved[arg.name] = [
                    values[item]
                    if isinstance(item, str) and item in values
                    else self._helper._resolve_kb_ref(item)
                    if isinstance(item, str) and item.startswith("KB.")
                    else item
                    for item in arg.value
                ]
            else:
                resolved[arg.name] = arg.value
        if (
            self.workspace_root is not None
            and statement.command in self._effectful_commands()
        ):
            resolved["_workspace_root"] = self.workspace_root
        return resolved

    # -- submit ----------------------------------------------------------

    def submit_result(self, result: ResultEnvelope) -> dict[str, Any]:
        """Validate and commit one submitted result envelope.

        Writes RESULT_RECEIVED and — when the result is semantically valid
        (mapping + DONE predicate) — VALIDATION_PASSED and the atomic
        SUCCEEDED batch, exactly like the coordinator; a failed or blocked
        result, or a semantically invalid succeeded one, fails the run
        through the same atomic cancellation path.  Duplicate, stale, or
        malformed submissions are rejected without appending anything.
        """
        result.validate()
        events = self._require_run()
        self._reject_terminal(events)

        ledger = self.store.task_ledger(self.run_id)
        task_ids = list(ledger.tasks)
        match = _INVOCATION_PATTERN.fullmatch(result.invocation_id)
        _check_submission(
            match is not None
            and 1 <= int(match.group(1)) <= len(task_ids),
            f"unknown invocation {result.invocation_id!r} for run"
            f" {self.run_id!r} ({len(task_ids)} planned tasks)",
        )
        idx = int(match.group(1)) - 1
        task_id = task_ids[idx]

        invocation_events = [
            event
            for event in events
            if event.invocation_id == result.invocation_id
        ]
        dispatched = [
            event
            for event in invocation_events
            if event.event_type is EventType.INVOCATION_DISPATCHED
        ]
        _check_submission(
            bool(dispatched),
            f"invocation {result.invocation_id!r} has not been dispatched;"
            " run `tikhon next` first",
        )
        _check_submission(
            not any(
                event.event_type is EventType.RESULT_RECEIVED
                for event in invocation_events
            ),
            f"duplicate submission: invocation {result.invocation_id!r}"
            " already has a RESULT_RECEIVED event",
        )
        dispatch = dispatched[-1]
        binding = dispatch.payload if isinstance(dispatch.payload, dict) else {}
        _check_submission(
            "targets" in binding and "command" in binding,
            f"dispatch record for {result.invocation_id!r} carries no"
            " envelope binding (targets/command); this run was not"
            " dispatched by the external driver",
        )
        _check_submission(
            result.run_id == self.run_id,
            f"stale result: run_id {result.run_id!r} does not match the"
            f" dispatched run {self.run_id!r}",
        )
        _check_submission(
            result.idempotency_key == binding.get("idempotency_key"),
            f"stale result: idempotency_key {result.idempotency_key!r}"
            f" does not match the dispatched key"
            f" {binding.get('idempotency_key')!r}",
        )
        _check_submission(
            result.attempt == len(dispatched),
            f"stale attempt: result answers attempt {result.attempt} but"
            f" invocation {result.invocation_id!r} was dispatched"
            f" {len(dispatched)} time(s)",
        )
        _check_submission(
            result.task_id == dispatch.task_id,
            f"stale result: task_id {result.task_id!r} does not match the"
            f" dispatched task {dispatch.task_id!r}",
        )
        _check_submission(
            result.command == binding.get("command"),
            f"stale result: command {result.command!r} does not match the"
            f" dispatched command {binding.get('command')!r}",
        )

        instruction_id = dispatch.instruction_id
        targets = tuple(binding["targets"])
        done = binding.get("done")
        revisions = tuple(binding.get("revisions", ()))
        retirements = tuple(binding.get("retirements", ()))

        usage = result.receipt.get("usage")
        usage = usage if isinstance(usage, Mapping) else {}
        recorded = _recorded_usage(usage)

        records: list[_Record] = [
            _Record(
                event_type=EventType.RESULT_RECEIVED,
                instruction_id=instruction_id,
                invocation_id=result.invocation_id,
                task_id=task_id,
                payload={
                    "result": result.payload,
                    "receipt": dict(result.receipt),
                    "evidence": list(result.evidence),
                },
                store=self.store,
            ),
        ]

        if result.status != "succeeded":
            # Semantic failure: process exit codes never imply success; a
            # failed or blocked result fails (or blocks) the run through
            # the coordinator's atomic cancellation path.
            if result.status == "failed":
                records.append(_Record(
                    event_type=EventType.FAILED,
                    instruction_id=instruction_id,
                    invocation_id=result.invocation_id,
                    task_id=task_id,
                    payload={"error": result.error},
                    store=self.store,
                ))
                finished_payload: dict[str, Any] = {
                    "status": "failed", "error": result.error,
                }
            else:
                records.append(_Record(
                    event_type=EventType.BLOCKED,
                    instruction_id=instruction_id,
                    invocation_id=result.invocation_id,
                    task_id=task_id,
                    payload={"reason": result.error},
                    store=self.store,
                ))
                finished_payload = {"status": "blocked", "reason": result.error}
            records.append(_invocation_recorded_record(
                self.store, task_id, recorded
            ))
            records.append(_task_cancelled_record(self.store, task_id))
            records.extend(self._pending_cancellation_records(task_ids, idx))
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload=finished_payload,
                store=self.store,
            ))
            self.store.append_batch(self.run_id, records)
            return {
                "run_id": self.run_id,
                "invocation_id": result.invocation_id,
                "recorded": True,
                "run_status": finished_payload["status"],
            }

        target_values, mapping_error = map_results_to_targets(targets, result.payload)
        if mapping_error is None and done is not None:
            passed, detail = evaluate_done_predicate(
                _SimpleDone(done), target_values
            )
            if not passed:
                mapping_error = (
                    f"DONE predicate failed for {instruction_id}: {detail}"
                )
                predicate_payload = {
                    "step_id": instruction_id,
                    "predicate": dict(done),
                    "detail": detail,
                }
            else:
                predicate_payload = None
        else:
            predicate_payload = None

        if mapping_error is not None:
            records.append(_Record(
                event_type=EventType.FAILED,
                instruction_id=instruction_id,
                invocation_id=result.invocation_id,
                task_id=task_id,
                payload={"error": mapping_error},
                store=self.store,
            ))
            if predicate_payload is not None:
                records.insert(1, _Record(
                    event_type=EventType.VALIDATION_FAILED,
                    instruction_id=instruction_id,
                    invocation_id=result.invocation_id,
                    task_id=task_id,
                    payload=predicate_payload,
                    store=self.store,
                ))
            records.append(_invocation_recorded_record(
                self.store, task_id, recorded
            ))
            records.append(_task_cancelled_record(self.store, task_id))
            records.extend(self._pending_cancellation_records(task_ids, idx))
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": mapping_error},
                store=self.store,
            ))
            self.store.append_batch(self.run_id, records)
            return {
                "run_id": self.run_id,
                "invocation_id": result.invocation_id,
                "recorded": True,
                "run_status": "failed",
            }

        records.append(_Record(
            event_type=EventType.VALIDATION_PASSED,
            instruction_id=instruction_id,
            invocation_id=result.invocation_id,
            task_id=task_id,
            payload={},
            store=self.store,
        ))

        add_nodes = [
            {"id": target, "value": value}
            for target, value in target_values.items()
        ]
        if revisions:
            # REVISE pins the step to a single target (validation rule).
            revised_value = target_values[targets[0]]
            add_nodes.extend(
                {"id": ref, "value": revised_value} for ref in revisions
            )
        delta = StateDelta(
            add_nodes=tuple(add_nodes),
            retire_nodes=tuple(retirements),
        )
        expected_sv = self.store.run(self.run_id)["state_version"]
        records.append(_Record(
            event_type=EventType.SUCCEEDED,
            instruction_id=instruction_id,
            invocation_id=result.invocation_id,
            task_id=task_id,
            expected_state_version=expected_sv,
            payload={"delta": delta},
            store=self.store,
        ))
        records.append(_invocation_recorded_record(
            self.store, task_id, recorded
        ))
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=task_id,
            payload={
                "kind": "task_completed", "id": task_id,
                "evidence": f"{result.command} -> {list(targets)}",
            },
            store=self.store,
        ))

        run_status = "in_progress"
        if idx == len(task_ids) - 1:
            # Last plan step: finish the run through the terminal rules.
            terminal = self._terminal_status()
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload=terminal,
                store=self.store,
            ))
            run_status = terminal["status"]

        self.store.append_batch(self.run_id, records)
        return {
            "run_id": self.run_id,
            "invocation_id": result.invocation_id,
            "recorded": True,
            "run_status": run_status,
        }

    def _pending_cancellation_records(
        self, task_ids: list[str], from_idx: int
    ) -> list[_Record]:
        return [
            _task_cancelled_record(self.store, task_ids[pending_idx])
            for pending_idx in range(from_idx + 1, len(task_ids))
        ]

    def _terminal_status(self) -> dict[str, Any]:
        """Terminal RUN_FINISHED payload for a bare RETURN/STOP ending."""
        if self.program is not None:
            for statement in self.program.statements:
                from tikhon.syntax.model import Return, Stop

                if isinstance(statement, Return):
                    return {"status": "succeeded"}
                if isinstance(statement, Stop):
                    if statement.kind == "completed":
                        return {"status": "succeeded"}
                    payload: dict[str, Any] = {"status": statement.kind}
                    values = self._values(self.store.events(self.run_id))
                    reason = values.get(statement.ref) if statement.ref else None
                    if reason is not None:
                        payload["reason"] = reason
                    return payload
        return {"status": "succeeded"}


class _SimpleDone:
    """Dict-shaped DONE predicate adapter for evaluate_done_predicate."""

    def __init__(self, data: Mapping[str, Any]):
        self.op = data["op"]
        self.ref = data["ref"]
        self.value = data["value"]


def _check_submission(condition: bool, message: str) -> None:
    if not condition:
        raise DriverError(message)


def _recorded_usage(usage: Mapping[str, Any]) -> dict[str, Any]:
    """Ledger metrics from a result receipt.

    Unavailable telemetry (``None``) is recorded as the ledger zero — the
    distinction between unavailable and measured zero is preserved in the
    RESULT_RECEIVED event's receipt payload, which the ledger cannot carry.
    """
    def _int(name: str) -> int:
        value = usage.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    def _float(name: str) -> float:
        value = usage.get(name)
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    return {
        "tokens": _int("tokens"),
        "cost": _float("cost"),
        "retries": _int("retries"),
        "elapsed_seconds": _float("elapsed_seconds"),
    }


def _invocation_recorded_record(
    store: EventStore, task_id: str, recorded: Mapping[str, Any]
) -> _Record:
    return _Record(
        event_type=EventType.TASK_UPDATED,
        task_id=task_id,
        payload={
            "kind": "invocation_recorded", "id": task_id,
            "tokens": recorded["tokens"],
            "cost": recorded["cost"],
            "retries": recorded["retries"],
            "elapsed_seconds": recorded["elapsed_seconds"],
        },
        store=store,
    )


def _task_cancelled_record(store: EventStore, task_id: str) -> _Record:
    return _Record(
        event_type=EventType.TASK_UPDATED,
        task_id=task_id,
        payload={"kind": "task_cancelled", "id": task_id},
        store=store,
    )
