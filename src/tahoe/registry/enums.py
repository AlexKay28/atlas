"""Closed enumerations of the command contract.

Vocabulary is fixed by docs/adr/0002-executable-thinking-language.md
(side-effect classes, idempotency modes, typed failure kinds) and
docs/adr/0003-live-text-harness.md (model tiers T0..T3).
"""

from __future__ import annotations

from enum import Enum


class EffectClass(Enum):
    """Side-effect class of a command (ADR-0002, "Side Effects and Approval")."""

    PURE = "pure"
    READ_ONLY = "read_only"
    REVERSIBLE_WRITE = "reversible_write"
    IRREVERSIBLE_WRITE = "irreversible_write"


class ExecutionMode(Enum):
    """Whether a command completes within one bounded dispatch or runs long."""

    IMMEDIATE = "immediate"
    LONG_RUNNING = "long_running"


class IdempotencyMode(Enum):
    """Whether replay can safely repeat the operation (ADR-0002)."""

    NONE = "none"
    INPUT_DIGEST = "input_digest"
    BUSINESS_KEY = "business_key"
    EXTERNAL_KEY = "external_key"


class FailureKind(Enum):
    """Closed set of typed failure kinds (ADR-0002, "Failure Semantics")."""

    INVALID_INPUT = "invalid_input"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    PERMISSION = "permission"
    CONFLICT = "conflict"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    VALIDATION = "validation"
    FORMALIZATION = "formalization"
    EXECUTION = "execution"
    INSUFFICIENT_EXAMPLES = "insufficient_examples"
    NO_COMMON_PATTERN = "no_common_pattern"
    ALL_RULES_FALSIFIED = "all_rules_falsified"
    UNKNOWN = "unknown"


class RoutingTier(Enum):
    """Worker execution tiers (ADR-0003, "Model Tiers").

    T0 deterministic executors use no language model; T1 fast workers handle
    mechanical tool-bound tasks; T2 strong workers handle bounded judgment;
    T3 authors/supervisors handle novel decomposition and program repair.
    """

    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
