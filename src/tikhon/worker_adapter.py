"""Model worker adapter with tier-based routing (issue #8).

``ModelWorker`` duck-types ``DeterministicWorker`` (``.commands`` property,
``.execute(command, resolved_kwargs)``) but produces DO results by
dispatching a contract prompt to a language model instead of calling a
Python handler.  All network/subprocess detail lives behind the
``transport`` callable — ``transport(model: str, prompt: str) -> str`` —
so tests use stubs and the CLI wires real HTTP/exec transports from
environment configuration (see ``tikhon.cli._build_model_worker``).

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

import json
from typing import Any, Callable, Mapping, Sequence

from tikhon.registry.enums import RoutingTier
from tikhon.registry.registry import Registry
from tikhon.runtime.coordinator import map_results_to_targets

__all__ = ["DEFAULT_TIMEOUT_SECONDS", "ModelWorker", "WorkerError"]

#: Default deadline advertised to transports (``ModelWorker.timeout_seconds``).
DEFAULT_TIMEOUT_SECONDS = 120.0

Transport = Callable[[str, str], str]


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
    ):
        self._registry = registry
        self._transport = transport
        self._tier_models: dict[Any, str] = dict(tier_models or {})
        self._default_model = default_model
        # Retained for callers that build transports around this worker;
        # the transport itself owns all I/O details including its deadline.
        self.timeout_seconds = timeout_seconds

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
        prompt = self._build_prompt(spec, resolved_kwargs, target_refs)
        raw = self._transport(model, prompt)
        parsed = self._parse_response(raw, command)
        if target_refs:
            _, mapping_error = map_results_to_targets(target_refs, parsed)
            if mapping_error is not None:
                raise WorkerError(
                    f"model response for command {command!r} failed"
                    f" target mapping: {mapping_error}",
                    raw if isinstance(raw, str) else None,
                )
        return parsed

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

    def _build_prompt(
        self,
        spec: Any,
        resolved_kwargs: Mapping[str, Any],
        targets: tuple[str, ...],
    ) -> str:
        """Contract preamble + resolved kwargs + strict JSON-only reply rule."""
        lines = [
            "You are the model worker executing one step of a tikhon program.",
            "",
            f"Command: {spec.name} (version {spec.version})",
            f"Purpose: {spec.purpose}",
            f"Inputs: {', '.join(spec.inputs)}",
            f"Outputs: {', '.join(spec.outputs)}",
            f"Done condition: {spec.done}",
            "",
            "Resolved arguments (JSON):",
            json.dumps(dict(resolved_kwargs), ensure_ascii=False, sort_keys=True, default=str),
            "",
        ]
        if len(targets) > 1:
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
