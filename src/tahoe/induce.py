"""Inline induction engine — derive general rules from specific observations.

Issue #79: the ``induce`` command spec exists in ``builtins.py`` but had
no implementation.  This module provides the handler that the coordinator's
``DeterministicWorker`` calls when a program executes
``step.<id>: DO induce(observations = [...], ...) -> H.rule``.

The induction algorithm is deterministic and structural:

1. Each observation is a dict with at least a ``pattern`` key (a string)
   and optional ``outcome`` (success/failure) and ``context`` (dict).
2. Observations are grouped by their ``pattern`` value.
3. A pattern becomes a candidate rule when it has >= ``min_examples``
   supporting observations.
4. Each candidate rule gets a falsifier: a condition that, if observed
   in a future example, would refute the rule.  The simplest falsifier
   is "an observation with this pattern but a different outcome".
5. Rules are sorted by support count (descending) and capped at
   ``max_rules``.
6. When ``falsifier_required`` is true, rules without a falsifier are
   dropped.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "InduceError",
    "InsufficientExamples",
    "NoCommonPattern",
    "induce_handler",
    "induce",
]


class InduceError(Exception):
    """Base error for induction failures."""


class InsufficientExamples(InduceError):
    """Fewer than ``min_examples`` observations provided."""


class NoCommonPattern(InduceError):
    """No pattern shared by enough observations."""


def _extract_pattern(observation: Any) -> str | None:
    """Extract the pattern string from one observation.

    An observation may be:
    - a string (treated as the pattern itself)
    - a dict with a ``pattern`` key
    - a dict with a ``event`` key (fallback)
    """
    if isinstance(observation, str):
        return observation
    if isinstance(observation, dict):
        return observation.get("pattern") or observation.get("event")
    return None


def _extract_outcome(observation: Any) -> str:
    """Extract the outcome label from one observation.

    Defaults to ``"unknown"`` when no outcome is declared.
    """
    if isinstance(observation, dict):
        outcome = observation.get("outcome")
        if outcome is not None:
            return str(outcome)
    return "unknown"


def _extract_context(observation: Any) -> dict[str, Any]:
    """Extract the context dict from one observation."""
    if isinstance(observation, dict):
        ctx = observation.get("context", {})
        if isinstance(ctx, dict):
            return ctx
    return {}


def _find_falsifier(
    pattern: str,
    outcomes: dict[str, list[dict]],
) -> str | None:
    """Derive a falsifier condition for a pattern.

    A falsifier is a human-readable condition that would refute the rule.
    When the pattern has mixed outcomes, the falsifier is:
    "observation with pattern '<pattern>' and outcome != '<dominant>'".
    When all outcomes are the same, the falsifier is:
    "observation with pattern '<pattern>' and outcome != '<outcome>'".
    """
    unique_outcomes = list(outcomes.keys())
    if len(unique_outcomes) == 1:
        only = unique_outcomes[0]
        return f"pattern('{pattern}') AND outcome != '{only}'"
    dominant = max(unique_outcomes, key=lambda o: len(outcomes[o]))
    return f"pattern('{pattern}') AND outcome != '{dominant}'"


def induce_handler(
    observations: list[Any] | None = None,
    target_pattern: str | None = None,
    min_examples: int = 2,
    max_rules: int = 5,
    falsifier_required: bool = True,
    **_extra: Any,
) -> dict[str, Any]:
    """Induce candidate rules from a list of observations.

    Returns a dict with keys:
    - ``rules``: list of candidate rule dicts, each with:
      - ``pattern``: the generalized pattern string
      - ``support``: number of supporting observations
      - ``falsifier``: a condition that would refute the rule
      - ``outcomes``: mapping of outcome -> count
      - ``rule_name``: a generated name for the rule
    - ``total_observations``: count of observations received
    - ``patterns_found``: number of distinct patterns
    """
    if observations is None:
        observations = []

    if not isinstance(observations, list):
        raise InduceError(
            f"observations must be a list, got {type(observations).__name__}"
        )

    total = len(observations)

    if total < min_examples:
        raise InsufficientExamples(
            f"need at least {min_examples} observations, got {total}"
        )

    # Group observations by pattern.
    pattern_outcomes: dict[str, dict[str, list[dict]]] = {}
    for obs in observations:
        pattern = _extract_pattern(obs)
        if pattern is None:
            continue
        outcome = _extract_outcome(obs)
        context = _extract_context(obs)
        if pattern not in pattern_outcomes:
            pattern_outcomes[pattern] = {}
        if outcome not in pattern_outcomes[pattern]:
            pattern_outcomes[pattern][outcome] = []
        pattern_outcomes[pattern][outcome].append(
            {"observation": obs, "context": context}
        )

    if not pattern_outcomes:
        raise NoCommonPattern(
            "no extractable patterns found in observations"
        )

    # Build candidate rules.
    candidates: list[dict[str, Any]] = []
    for pattern, outcomes in pattern_outcomes.items():
        support = sum(len(v) for v in outcomes.values())
        if support < min_examples:
            continue
        if target_pattern is not None and pattern != target_pattern:
            continue
        falsifier = _find_falsifier(pattern, outcomes)
        if falsifier is None and falsifier_required:
            continue
        rule_name = _generate_rule_name(pattern)
        candidates.append({
            "pattern": pattern,
            "support": support,
            "falsifier": falsifier,
            "outcomes": {o: len(v) for o, v in outcomes.items()},
            "rule_name": rule_name,
        })

    if not candidates:
        raise NoCommonPattern(
            "no pattern met the minimum support threshold"
        )

    # Sort by support (descending) and cap.
    candidates.sort(key=lambda r: r["support"], reverse=True)
    candidates = candidates[:max_rules]

    return {
        "rules": candidates,
        "total_observations": total,
        "patterns_found": len(pattern_outcomes),
    }


def _generate_rule_name(pattern: str) -> str:
    """Generate a deterministic rule name from a pattern string."""
    import re
    sanitized = re.sub(r"[^a-z0-9]", "_", pattern.lower())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        sanitized = "rule"
    return f"induced_{sanitized}"


# Alias matching the naming convention of other handlers.
induce = induce_handler
