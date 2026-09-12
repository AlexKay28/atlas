"""Frozen command-contract records (docs/spec/02-command-catalog.md).

Every catalog field is mandatory, including explicit ``none``. Construction
validates shape, closed vocabularies, and bounded collections; rejected
contracts raise ``ContractError``/``ReservedNameError`` at build time.
:meth:`CommandSpec.to_dict` and :meth:`CommandSpec.from_dict` give a
deterministic plain-data form that round-trips through JSON.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from .enums import EffectClass, ExecutionMode, FailureKind, IdempotencyMode, RoutingTier
from .errors import ContractError, ReservedNameError, SchemaError

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

#: Coordinator control words (docs/spec/05-live-authoring-and-routing.md plus
#: AWAIT/APPROVE from the command catalog). No worker command may take one of
#: these names, in any letter case.
RESERVED_CONTROL_NAMES = frozenset(
    {"await", "approve", "seal", "run", "pause", "resume", "cancel", "fork"}
)


_TIER_ORDER = {RoutingTier.T0: 0, RoutingTier.T1: 1, RoutingTier.T2: 2, RoutingTier.T3: 3}


def _tier_rank(tier: RoutingTier) -> int:
    return _TIER_ORDER[tier]


#: Closed type grammar for ``inputs`` and ``parameters`` entries.
#: Each entry is ``name:type`` where ``type`` must be one of:
#: - a primitive atom from ``_TYPE_ATOMS``
#: - a node-type prefix from ``_NODE_TYPE_PREFIXES`` (single uppercase letter
#:   or ``OUT``)
#: - a slash compound where every segment is a valid type atom
#: - ``int`` with a bound (``int<=N``, ``int>N``, ``int>=N``, ``int<N``)
_TYPE_ATOMS = frozenset({
    "text", "json", "bool", "map", "tuple", "numeric", "enum", "descriptor",
    "artifact", "artifacts", "immutable", "refs", "ranked_refs",
    "kb_key", "kb_key_or_prefix",
    "workspace_relative", "deterministic", "predicates",
    "media_types", "token_cap", "bounded_types", "pinned_ref",
    "pddl", "smt", "lean4", "isabelle",
})

_NODE_TYPE_PREFIXES = frozenset({
    "G", "Q", "C", "K", "OUT", "V", "D", "H", "U", "E", "R", "F", "P", "ART",
})

_ENTRY_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_INT_BOUND_PATTERN = re.compile(r"^int(<=|>=|>|<)(\d+)$")


def _validate_type_entry(entry: str, field_name: str) -> None:
    """Validate one ``name:type`` entry against the closed type grammar."""
    if ":" not in entry:
        raise SchemaError(
            f"{field_name} entry {entry!r} must be 'name:type'"
        )
    name, type_part = entry.split(":", 1)
    if not _ENTRY_NAME_PATTERN.fullmatch(name):
        raise SchemaError(
            f"{field_name} entry {entry!r} has an invalid name {name!r}"
        )
    if not type_part:
        raise SchemaError(
            f"{field_name} entry {entry!r} has an empty type"
        )
    if type_part.startswith("int"):
        if _INT_BOUND_PATTERN.fullmatch(type_part):
            return
        raise SchemaError(
            f"{field_name} entry {entry!r}: int parameter requires a bound"
            " (e.g. int<=100, int>0, int>=1, int<1000)"
        )
    if "/" in type_part:
        segments = type_part.split("/")
        for seg in segments:
            if seg not in _TYPE_ATOMS and seg not in _NODE_TYPE_PREFIXES:
                raise SchemaError(
                    f"{field_name} entry {entry!r}: unknown type segment {seg!r}"
                    f" in compound type {type_part!r}"
                )
        return
    if type_part in _TYPE_ATOMS or type_part in _NODE_TYPE_PREFIXES:
        return
    raise SchemaError(
        f"{field_name} entry {entry!r}: unknown type {type_part!r}"
    )


def _nonempty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must be a nonempty string, got {value!r}")
    return value


def _freeze_tuple(values: Any, field_name: str, *, allow_empty: bool = False) -> tuple:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise ContractError(f"{field_name} must be a sequence, got {values!r}")
    items = tuple(values)
    if not allow_empty and not items:
        raise ContractError(f"{field_name} must declare at least one entry")
    return items


def _str_tuple(values: Any, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    items = _freeze_tuple(values, field_name, allow_empty=allow_empty)
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ContractError(f"{field_name} entries must be nonempty strings, got {item!r}")
    return items


def _coerce_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError:
            pass
    allowed = ", ".join(member.value for member in enum_cls)
    raise ContractError(f"{field_name} must be one of [{allowed}], got {value!r}")


def _nonneg_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field_name} must be a number, got {value!r}")
    if not math.isfinite(value) or value < 0:
        raise ContractError(f"{field_name} must be a finite non-negative number, got {value!r}")
    return value


def _nonneg_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{field_name} must be an integer, got {value!r}")
    if value < 0:
        raise ContractError(f"{field_name} must be non-negative, got {value!r}")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{field_name} must be an integer, got {value!r}")
    if value < 1:
        raise ContractError(f"{field_name} must be at least 1, got {value!r}")
    return value


@dataclass(frozen=True)
class Budget:
    """Resource caps of a command contract: time, tokens, cost, attempts, output size."""

    max_seconds: float
    max_tokens: int
    max_cost: float
    max_attempts: int
    max_output_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_seconds", _nonneg_number(self.max_seconds, "budget.max_seconds"))
        object.__setattr__(self, "max_tokens", _nonneg_int(self.max_tokens, "budget.max_tokens"))
        object.__setattr__(self, "max_cost", _nonneg_number(self.max_cost, "budget.max_cost"))
        object.__setattr__(self, "max_attempts", _positive_int(self.max_attempts, "budget.max_attempts"))
        object.__setattr__(
            self, "max_output_bytes", _nonneg_int(self.max_output_bytes, "budget.max_output_bytes")
        )

    def to_dict(self) -> dict:
        return {
            "max_seconds": self.max_seconds,
            "max_tokens": self.max_tokens,
            "max_cost": self.max_cost,
            "max_attempts": self.max_attempts,
            "max_output_bytes": self.max_output_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Budget":
        return cls(
            max_seconds=data["max_seconds"],
            max_tokens=data["max_tokens"],
            max_cost=data["max_cost"],
            max_attempts=data["max_attempts"],
            max_output_bytes=data["max_output_bytes"],
        )


@dataclass(frozen=True)
class FailureSpec:
    """One entry of the closed typed failure set, with retryability and recovery path."""

    kind: FailureKind
    retryable: bool
    recovery: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_enum(self.kind, FailureKind, "failures.kind"))
        if not isinstance(self.retryable, bool):
            raise ContractError(f"failures.retryable must be a bool, got {self.retryable!r}")
        _nonempty_str(self.recovery, "failures.recovery")

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "retryable": self.retryable, "recovery": self.recovery}

    @classmethod
    def from_dict(cls, data: dict) -> "FailureSpec":
        return cls(kind=data["kind"], retryable=data["retryable"], recovery=data["recovery"])


@dataclass(frozen=True)
class RoutingPolicy:
    """Worker routing profile (docs/spec/05-live-authoring-and-routing.md)."""

    minimum_tier: RoutingTier
    permitted_tiers: tuple[RoutingTier, ...]
    preferred_tier: RoutingTier
    validator_tier: RoutingTier
    confidence_policy: str
    escalation_on: tuple[FailureKind, ...]
    fallback_chain: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "minimum_tier", _coerce_enum(self.minimum_tier, RoutingTier, "routing.minimum_tier")
        )
        object.__setattr__(
            self, "preferred_tier", _coerce_enum(self.preferred_tier, RoutingTier, "routing.preferred_tier")
        )
        object.__setattr__(
            self, "validator_tier", _coerce_enum(self.validator_tier, RoutingTier, "routing.validator_tier")
        )
        permitted = tuple(
            _coerce_enum(tier, RoutingTier, "routing.permitted_tiers entry")
            for tier in _freeze_tuple(self.permitted_tiers, "routing.permitted_tiers")
        )
        object.__setattr__(self, "permitted_tiers", permitted)
        _nonempty_str(self.confidence_policy, "routing.confidence_policy")
        escalation_on = tuple(
            _coerce_enum(kind, FailureKind, "routing.escalation_on entry")
            for kind in _freeze_tuple(self.escalation_on, "routing.escalation_on", allow_empty=True)
        )
        object.__setattr__(self, "escalation_on", escalation_on)
        object.__setattr__(
            self,
            "fallback_chain",
            _str_tuple(self.fallback_chain, "routing.fallback_chain", allow_empty=True),
        )
        if self.minimum_tier not in permitted:
            raise ContractError("routing.permitted_tiers must include routing.minimum_tier")
        if self.preferred_tier not in permitted:
            raise ContractError("routing.permitted_tiers must include routing.preferred_tier")
        if self.validator_tier not in permitted:
            raise ContractError("routing.permitted_tiers must include routing.validator_tier")
        for tier in permitted:
            if _tier_rank(tier) < _tier_rank(self.minimum_tier):
                raise ContractError(
                    f"routing.permitted_tiers contains {tier.value}"
                    f" which is below routing.minimum_tier {self.minimum_tier.value}"
                )

    def to_dict(self) -> dict:
        return {
            "minimum_tier": self.minimum_tier.value,
            "permitted_tiers": [tier.value for tier in self.permitted_tiers],
            "preferred_tier": self.preferred_tier.value,
            "validator_tier": self.validator_tier.value,
            "confidence_policy": self.confidence_policy,
            "escalation_on": [kind.value for kind in self.escalation_on],
            "fallback_chain": list(self.fallback_chain),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RoutingPolicy":
        return cls(
            minimum_tier=data["minimum_tier"],
            permitted_tiers=tuple(data["permitted_tiers"]),
            preferred_tier=data["preferred_tier"],
            validator_tier=data["validator_tier"],
            confidence_policy=data["confidence_policy"],
            escalation_on=tuple(data["escalation_on"]),
            fallback_chain=tuple(data["fallback_chain"]),
        )


@dataclass(frozen=True)
class CommandSpec:
    """Complete, immutable contract of one command.

    Field order mirrors docs/spec/02-command-catalog.md. Every field is
    mandatory, including explicit ``none``.
    """

    name: str
    version: str
    purpose: str
    inputs: tuple[str, ...]
    parameters: tuple[str, ...]
    preconditions: tuple[str, ...]
    outputs: tuple[str, ...]
    effects: tuple[str, ...]
    done: str
    failures: tuple[FailureSpec, ...]
    effect_class: EffectClass
    execution: ExecutionMode
    capabilities: tuple[str, ...]
    evidence: tuple[str, ...]
    budget: Budget
    idempotency: IdempotencyMode
    compensation: str
    routing: RoutingPolicy

    def __post_init__(self) -> None:
        name = self.name
        if not isinstance(name, str):
            raise ContractError(f"command name must be a string, got {name!r}")
        if name.casefold() in RESERVED_CONTROL_NAMES:
            raise ReservedNameError(
                f"command name {name!r} collides with a reserved control word"
            )
        if not NAME_PATTERN.fullmatch(name):
            raise ContractError(f"command name must be lowercase snake_case, got {name!r}")
        version = self.version
        if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
            raise ContractError(
                f"version must be semver-ish MAJOR.MINOR.PATCH, got {version!r}"
            )
        _nonempty_str(self.purpose, "purpose")
        object.__setattr__(self, "inputs", _str_tuple(self.inputs, "inputs"))
        object.__setattr__(self, "parameters", _str_tuple(self.parameters, "parameters"))
        for entry in self.inputs:
            _validate_type_entry(entry, "inputs")
        for entry in self.parameters:
            _validate_type_entry(entry, "parameters")
        object.__setattr__(self, "preconditions", _str_tuple(self.preconditions, "preconditions"))
        object.__setattr__(self, "outputs", _str_tuple(self.outputs, "outputs"))
        object.__setattr__(self, "effects", _str_tuple(self.effects, "effects"))
        _nonempty_str(self.done, "done")
        object.__setattr__(
            self, "failures", _freeze_tuple(self.failures, "failures")
        )
        for failure in self.failures:
            if not isinstance(failure, FailureSpec):
                raise ContractError(f"failures entries must be FailureSpec, got {failure!r}")
        object.__setattr__(
            self, "effect_class", _coerce_enum(self.effect_class, EffectClass, "effect_class")
        )
        object.__setattr__(
            self, "execution", _coerce_enum(self.execution, ExecutionMode, "execution")
        )
        object.__setattr__(self, "capabilities", _str_tuple(self.capabilities, "capabilities"))
        object.__setattr__(self, "evidence", _str_tuple(self.evidence, "evidence"))
        if not isinstance(self.budget, Budget):
            raise ContractError(f"budget must be a Budget, got {self.budget!r}")
        object.__setattr__(
            self, "idempotency", _coerce_enum(self.idempotency, IdempotencyMode, "idempotency")
        )
        _nonempty_str(self.compensation, "compensation")
        if not isinstance(self.routing, RoutingPolicy):
            raise ContractError(f"routing must be a RoutingPolicy, got {self.routing!r}")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "purpose": self.purpose,
            "inputs": list(self.inputs),
            "parameters": list(self.parameters),
            "preconditions": list(self.preconditions),
            "outputs": list(self.outputs),
            "effects": list(self.effects),
            "done": self.done,
            "failures": [failure.to_dict() for failure in self.failures],
            "effect_class": self.effect_class.value,
            "execution": self.execution.value,
            "capabilities": list(self.capabilities),
            "evidence": list(self.evidence),
            "budget": self.budget.to_dict(),
            "idempotency": self.idempotency.value,
            "compensation": self.compensation,
            "routing": self.routing.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CommandSpec":
        return cls(
            name=data["name"],
            version=data["version"],
            purpose=data["purpose"],
            inputs=tuple(data["inputs"]),
            parameters=tuple(data["parameters"]),
            preconditions=tuple(data["preconditions"]),
            outputs=tuple(data["outputs"]),
            effects=tuple(data["effects"]),
            done=data["done"],
            failures=tuple(FailureSpec.from_dict(f) for f in data["failures"]),
            effect_class=data["effect_class"],
            execution=data["execution"],
            capabilities=tuple(data["capabilities"]),
            evidence=tuple(data["evidence"]),
            budget=Budget.from_dict(data["budget"]),
            idempotency=data["idempotency"],
            compensation=data["compensation"],
            routing=RoutingPolicy.from_dict(data["routing"]),
        )
