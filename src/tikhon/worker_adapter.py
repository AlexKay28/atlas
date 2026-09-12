"""Model worker adapter with tier-based routing (issues #8 and #18).

``ModelWorker`` duck-types ``DeterministicWorker`` (``.commands`` property,
``.execute(command, resolved_kwargs)``) but produces DO results by
dispatching a contract prompt to a language model instead of calling a
Python handler.  All network/subprocess detail lives behind the
``transport`` callable — ``transport(model: str, prompt: str) -> str |
TransportResult`` — so tests use stubs and the CLI wires real HTTP/exec
transports from environment configuration (see
``tikhon.cli._build_model_worker``).

Issue #43 transport seam contract: a transport callable may return
either a bare ``str`` (legacy — text only, no usage) or a
``TransportResult(text, usage)`` dataclass where ``usage`` is a ``dict``
or ``None``.  ``ModelWorker.execute`` unwraps ``TransportResult`` to
obtain the text for parsing and maps a non-None ``usage`` dict's
``"tokens"`` value into the receipt it already builds; legacy
``str``-returning transports continue to yield ``None`` tokens and cost.
The downstream ``envelope._recorded_usage`` consumer already reads
``receipt["usage"]["tokens"]`` and ``receipt["usage"]["cost"]``, so no
envelope changes are needed.  The CLI HTTP transport wiring (in
``cli.py``) constructs a ``TransportResult`` from the HTTP response
body's ``usage`` dict — see the solution report for exact wiring.

Issue #18 binding: every dispatch is rendered as a
``tikhon.envelope.TaskEnvelope`` — the resolved contract summary, pinned
resolved arguments, targets, DONE predicate and an input-digest
idempotency key — and the prompt is built from that envelope (the
envelope's canonical JSON is embedded in the prompt, so the worker sees
the same binding a harness-neutral driver would submit).  The model's
reply is parsed strictly and wrapped into a ``tikhon.envelope.
ResultEnvelope`` (status ``succeeded``, payload, receipt with model
identity and usage — ``None`` usage meaning telemetry unavailable, not
zero) before its payload is returned.  Because the coordinator's pinned
``execute(command, resolved_kwargs)`` seam carries no run identity, the
adapter renders a direct-dispatch envelope whose identity placeholders
are the ``direct`` constants from ``tikhon.envelope``; runs dispatched
through ``tikhon next`` carry real ``run/invocation/task`` identity in
their envelopes instead.

Routing picks the model per the command contract's ``RoutingPolicy``:
``tier_models[preferred_tier]`` first (keys may be the strings "T0".."T3"
or ``RoutingTier`` members, which share those values), falling back to
``default_model``.  Responses must be strict JSON (a single optional
```json fence is tolerated); multi-target results are validated with the
coordinator's own ``map_results_to_targets`` rules.  Any unparseable or
invalid response raises ``WorkerError`` carrying the raw response tail
(last 500 chars), which the coordinator's existing exception path turns
into a coherent failed run.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Callable, Mapping, Sequence

from tikhon.envelope import (
    DIRECT_DISPATCH_INVOCATION_ID,
    DIRECT_DISPATCH_RUN_ID,
    DIRECT_DISPATCH_TASK_ID,
    ENVELOPE_SCHEMA_VERSION,
    EnvelopeValidationError,
    ResultEnvelope,
    TaskEnvelope,
    build_task_envelope,
    envelope_input_digest,
)
from tikhon.registry.enums import RoutingTier
from tikhon.registry.registry import Registry
from tikhon.runtime.coordinator import map_results_to_targets

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "ModelWorker",
    "TransportResult",
    "WorkerError",
]

#: Default deadline advertised to transports (``ModelWorker.timeout_seconds``).
DEFAULT_TIMEOUT_SECONDS = 120.0


@dataclasses.dataclass
class TransportResult:
    """Issue #43: transport return value carrying usage telemetry.

    A transport callable may return either a bare ``str`` (legacy) or a
    ``TransportResult`` with ``text`` (the raw model reply) and optional
    ``usage`` (a dict, e.g. ``{"tokens": 123}``).  When ``usage`` is
    ``None`` the receipt records ``None`` tokens/cost, exactly as the
    legacy str path does.
    """

    text: str
    usage: dict[str, Any] | None = None


Transport = Callable[[str, str], "str | TransportResult"]


class WorkerError(Exception):
    """A model worker response could not be produced or validated.

    Carries ``tail`` — the last 500 characters of the raw response — in
    the exception message, so the coordinator's existing exception path
    records a coherent, diagnosable failure without false completion.
    """

    def __init__(self, message: str, raw_response: str | None = None):
        tail = ""
        if isinstance(raw_response, str):
            tail = raw_response[-500:]
        self.tail = tail
        if tail:
            super().__init__(f"{message} | raw response tail: {tail}")
        else:
            super().__init__(message)


def _strip_json_fence(text: str) -> str:
    """Strip one optional ```json (or bare ```) fence around the payload."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    first_line_break = stripped.find("\n")
    if first_line_break == -1:
        return stripped
    header = stripped[3:first_line_break].strip().lower()
    if header not in ("", "json"):
        return stripped
    body = stripped[first_line_break + 1 :]
    closing = body.rfind("```")
    if closing != -1 and body[closing:].strip() == "```":
        body = body[:closing]
    return body.strip()


class ModelWorker:
    """Routes command dispatch to tier-configured models via a transport.

    Implements the same duck-type as ``DeterministicWorker``: a
    ``.commands`` property (the registry's command names) and
    ``.execute(command, resolved_kwargs)``.  ``registry`` is used for
    contract lookup only — the worker never mutates it.
    """

    def __init__(
        self,
        registry: Registry,
        transport: Transport,
        tier_models: Mapping[str | RoutingTier, str] | None = None,
        default_model: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        deadline_seconds: float | None = None,
    ):
        self._registry = registry
        self._transport = transport
        self._tier_models: dict[Any, str] = dict(tier_models or {})
        self._default_model = default_model
        # Retained for callers that build transports around this worker;
        # the transport itself owns all I/O details including its deadline.
        self.timeout_seconds = timeout_seconds
        # Issue #22: the execution budget's per-invocation deadline,
        # carried on every rendered TaskEnvelope.  When both the command
        # contract's budget and this deadline are set, the tighter (min)
        # wins; ``None`` leaves the envelope's contract deadline untouched.
        self._deadline_seconds = deadline_seconds
        # Issue #18 diagnostics: the envelope the last dispatch rendered
        # and the result envelope its reply was parsed into.
        self.last_task_envelope: TaskEnvelope | None = None
        self.last_result_envelope: ResultEnvelope | None = None

    @property
    def commands(self) -> set[str]:
        return set(self._registry.names())

    def execute(
        self,
        command: str,
        resolved_kwargs: dict[str, Any],
        targets: Sequence[str] | None = None,
    ) -> Any:
        """Produce one step's DO result through the model.

        ``targets`` is optional because the coordinator dispatches with
        exactly ``(command, resolved_kwargs)`` and validates the returned
        value itself; direct callers that know the step's target refs may
        pass them to get the same ``map_results_to_targets`` check (and
        the refs named in the prompt) before the value is returned.
        """
        spec = self._registry.resolve(command)
        model = self._resolve_model(spec)
        target_refs = tuple(targets) if targets is not None else ()
        task_envelope = build_task_envelope(
            self._registry,
            run_id=DIRECT_DISPATCH_RUN_ID,
            invocation_id=DIRECT_DISPATCH_INVOCATION_ID,
            task_id=DIRECT_DISPATCH_TASK_ID,
            attempt=1,
            idempotency_key=(
                f"direct:{envelope_input_digest(command, resolved_kwargs)}"
            ),
            command=command,
            arguments=dict(resolved_kwargs),
            targets=target_refs,
        )
        if self._deadline_seconds is not None:
            # Issue #22: bind the execution budget's deadline into the
            # envelope — min with the command contract's own budget so
            # the worker sees the effective dispatch deadline.
            contract_deadline = task_envelope.deadline_seconds
            effective = (
                float(self._deadline_seconds)
                if contract_deadline is None
                else min(float(contract_deadline), float(self._deadline_seconds))
            )
            task_envelope = dataclasses.replace(
                task_envelope, deadline_seconds=effective
            )
        self.last_task_envelope = task_envelope
        prompt = self._build_prompt(task_envelope)
        raw = self._transport(model, prompt)
        raw_text, usage = self._unwrap_transport(raw)
        parsed = self._parse_response(raw_text, command)
        result_envelope = self._build_result_envelope(
            task_envelope, model, parsed, raw_text, usage
        )
        if target_refs:
            _, mapping_error = map_results_to_targets(target_refs, parsed)
            if mapping_error is not None:
                raise WorkerError(
                    f"model response for command {command!r} failed"
                    f" target mapping: {mapping_error}",
                    raw_text,
                )
        return result_envelope.payload

    def _resolve_model(self, spec: Any) -> str:
        """Preferred tier first, then ``default_model``; else ``WorkerError``."""
        tier: RoutingTier = spec.routing.preferred_tier
        model = self._tier_models.get(tier.value)
        if model is None:
            model = self._tier_models.get(tier)
        if model is None:
            model = self._default_model
        if not model:
            raise WorkerError(
                f"no model configured for routing tier {tier.value!r}"
                f" (preferred tier of command {spec.name!r}) and no"
                " default_model was provided"
            )
        return model

    def _build_prompt(self, envelope: TaskEnvelope) -> str:
        """Contract preamble rendered FROM the TaskEnvelope.

        The envelope's canonical JSON is embedded so the worker sees the
        exact dispatch binding (identity, idempotency key, pinned
        arguments, output contract); the remaining lines restate the
        resolved contract fields carried by the envelope.
        """
        contract = envelope.contract
        lines = [
            "You are the model worker executing one step of a tikhon program.",
            "",
            "Task envelope (schema v1, canonical JSON):",
            envelope.to_json(),
            "",
            f"Command: {envelope.command} (version {envelope.command_version})",
            f"Purpose: {contract['purpose']}",
            f"Inputs: {', '.join(contract['inputs'])}",
            f"Outputs: {', '.join(contract['outputs'])}",
            f"Done condition: {contract['done_condition']}",
            "",
            "Resolved arguments (JSON):",
            json.dumps(dict(envelope.arguments), ensure_ascii=False, sort_keys=True, default=str),
            "",
        ]
        targets = envelope.targets
        if envelope.command == "delegate":
            # Issue #25: a delegate dispatch AUTHORS a child plan.  The
            # reply contract is the issue-specified JSON shape; the
            # coordinator validates the plan text against the registry
            # (registered commands only, bounded step count, no nested
            # delegate) and adopts the plan's RETURN refs onto the
            # dispatching step's targets positionally.
            lines.append(
                "This step AUTHORS a bounded child plan at runtime."
                " Before authoring, run the Step 0 skill/MCP inventory:"
                " scan locally available skills (.opencode/skills/,"
                " .claude/skills/, built-ins) by task match; if no local"
                " match, search ahood (`ahood skill search \"<keywords>\"`),"
                " read the candidate SKILL.md, install a pinned snapshot"
                ' (`ahood skill add owner/skill@version`), verify the pin in'
                " .claude/skills.lock.json, then load. Record relied-on"
                " skills in the plan's INPUT declarations."
                ' Reply with ONLY a JSON object {"plan_text": "..."}'
                " whose plan_text value is one complete tikhon program in"
                " the canonical grammar: a PROGRAM header, INPUT"
                " declarations binding the resolved arguments by their"
                " leaf names (the goal argument binds the leaf name"
                ' "goal", the constraints argument the leaf name'
                ' "constraints"), step.<id>: DO lines using only'
                " registered commands, and a terminal RETURN.  Keep the"
                " step count within the requested max_steps bound (hard"
                " cap 12), never use the delegate command inside the"
                " authored plan (no recursion), and end with RETURN refs"
                " mapping one-to-one onto this step's targets in order."
            )
        elif len(targets) > 1:
            lines.append(
                "This step commits results to multiple targets:"
                f" {', '.join(targets)}."
                " Reply with ONLY a JSON object whose keys are the full"
                " target refs or their unique leaf names."
            )
        elif len(targets) == 1:
            lines.append(
                f"This step commits its result to the single target"
                f" {targets[0]}."
                " Reply with ONLY a JSON object; for a single target any"
                " JSON value is acceptable."
            )
        else:
            lines.append(
                "Reply with ONLY a JSON object and nothing else — no prose,"
                " no explanation. For multi-target steps the JSON keys must"
                " be the full target refs or their unique leaf names; for a"
                " single target any JSON value is acceptable."
            )
        return "\n".join(lines)

    def _unwrap_transport(self, raw: Any) -> tuple[str, dict[str, Any] | None]:
        """Unwrap a transport return value into (text, usage).

        Legacy ``str`` returns ``(text, None)``; ``TransportResult``
        returns ``(result.text, result.usage)``.
        """
        if isinstance(raw, TransportResult):
            return raw.text, raw.usage
        return raw, None

    def _build_result_envelope(
        self,
        task_envelope: TaskEnvelope,
        model: str,
        parsed: Any,
        raw: Any,
        usage: dict[str, Any] | None = None,
    ) -> ResultEnvelope:
        """Wrap the parsed reply INTO a validated ResultEnvelope.

        The reply payload becomes a ``succeeded`` result; the receipt
        records the routed model identity and usage.  When ``usage`` is
        a dict with an integer ``"tokens"`` value, that value is carried
        into the receipt; otherwise tokens are ``None`` (telemetry
        unavailable — distinguished from a measured zero).  ``cost`` is
        ``None`` unless a price table is configured upstream.
        """
        tokens: int | None = None
        if isinstance(usage, dict):
            value = usage.get("tokens")
            if isinstance(value, int) and not isinstance(value, bool):
                tokens = value
        result_envelope = ResultEnvelope(
            schema_version=ENVELOPE_SCHEMA_VERSION,
            run_id=task_envelope.run_id,
            invocation_id=task_envelope.invocation_id,
            task_id=task_envelope.task_id,
            attempt=task_envelope.attempt,
            idempotency_key=task_envelope.idempotency_key,
            command=task_envelope.command,
            status="succeeded",
            payload=parsed,
            evidence=(),
            error=None,
            receipt={
                "model": model,
                "usage": {"tokens": tokens, "cost": None},
            },
        )
        try:
            result_envelope.validate()
        except EnvelopeValidationError as exc:
            raise WorkerError(
                f"model response for command {task_envelope.command!r}"
                f" produced an invalid result envelope: {exc}",
                raw if isinstance(raw, str) else None,
            ) from exc
        self.last_result_envelope = result_envelope
        return result_envelope

    def _parse_response(self, raw: Any, command: str) -> Any:
        """Strict JSON parse after stripping one optional ```json fence."""
        if not isinstance(raw, str):
            raise WorkerError(
                f"model response for command {command!r} is not text"
                f" (got {type(raw).__name__})"
            )
        try:
            return json.loads(_strip_json_fence(raw))
        except ValueError as exc:
            raise WorkerError(
                f"model response for command {command!r} is not valid JSON:"
                f" {exc}",
                raw,
            ) from exc
