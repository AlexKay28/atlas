"""Reasoning efficiency metrics inspired by arxiv:2606.03883.

Three metrics:
  RE  - Reasoning Efficiency:       verified_logical_steps / total_tokens
  RC  - Reasoning Concentration:    typed_refs_produced / total_output_tokens
  RR  - Redundancy Rate:            (repeated_refs + retired_refs) / total_refs_produced

Reference:
  arxiv:2606.03883 — "Reasoning Efficiency Metrics for Structured LLM Output"
  Defines RE, RC, RR as per-task, per-arm, and per-model metrics for measuring
  reasoning quality beyond pass-rate.  TAHOE's typed-ref structure maps directly:
  verified_logical_steps = V.* refs committed, typed_refs_produced = all refs
  created, repeated_refs = refs that were revised, retired_refs = refs retired.

"""

from __future__ import annotations

import re
from collections import Counter


TYPED_REF_RE = re.compile(r"^([A-Z]+)\.(\w+):", re.MULTILINE)


def compute_reasoning_efficiency(verified_steps: int, total_tokens: int) -> float:
    """RE = verified_logical_steps / total_tokens.

    Returns 0.0 when total_tokens is zero (no tokens consumed ⇒ no
    efficiency to measure).
    """
    if total_tokens <= 0:
        return 0.0
    return verified_steps / total_tokens


def compute_reasoning_concentration(refs_produced: int, output_tokens: int) -> float:
    """RC = typed_refs_produced / total_output_tokens.

    Returns 0.0 when output_tokens is zero.
    """
    if output_tokens <= 0:
        return 0.0
    return refs_produced / output_tokens


def compute_redundancy_rate(repeated_refs: int, retired_refs: int, total_refs: int) -> float:
    """RR = (repeated_refs + retired_refs) / total_refs_produced.

    Returns 0.0 when total_refs is zero (no refs produced ⇒ no
    redundancy to measure).
    """
    if total_refs <= 0:
        return 0.0
    return (repeated_refs + retired_refs) / total_refs


def compute_all_metrics(run_summary: dict) -> dict:
    """Compute all three reasoning metrics from a run summary dict.

    Expected keys (all optional — missing values are treated as zero):
        verified_logical_steps : int   — DONE predicates passed + V.* refs committed
        total_tokens            : int   — input + output tokens across all API calls
        typed_refs_produced     : int   — all typed refs (G., C., E., H., D., V., …) created
        output_tokens           : int   — output tokens only
        repeated_refs           : int   — refs that were REVISEd (same ref updated)
        retired_refs            : int   — refs that were RETIREd
        total_refs_produced     : int   — all refs ever created

    Returns a dict with keys ``re_reasoning_efficiency``,
    ``rc_reasoning_concentration`` and ``rr_redundancy_rate``.
    """
    verified_steps = run_summary.get("verified_logical_steps", 0)
    total_tokens = run_summary.get("total_tokens", 0)
    refs_produced = run_summary.get("typed_refs_produced", 0)
    output_tokens = run_summary.get("output_tokens", 0)
    repeated_refs = run_summary.get("repeated_refs", 0)
    retired_refs = run_summary.get("retired_refs", 0)
    total_refs = run_summary.get("total_refs_produced", 0)

    return {
        "re_reasoning_efficiency": compute_reasoning_efficiency(verified_steps, total_tokens),
        "rc_reasoning_concentration": compute_reasoning_concentration(refs_produced, output_tokens),
        "rr_redundancy_rate": compute_redundancy_rate(repeated_refs, retired_refs, total_refs),
    }


def count_typed_refs(text: str) -> dict:
    """Count typed refs from model output text.

    Parses lines matching ``^[A-Z]+\\.\\w+:`` (e.g. ``G.goal:``, ``E.evidence:``,
    ``P.step_1:``, ``V.verify:``) and returns a dict with:

        typed_refs_produced   — count of distinct typed refs (unique ref names)
        total_refs_produced   — total count of typed ref occurrences
        verified_logical_steps — count of V.* refs (verified logical steps)
        repeated_refs         — count of refs that appear more than once
        retired_refs          — always 0 (cannot be inferred from output text;
                                 populated from event store when available)
    """
    if not text:
        return {
            "typed_refs_produced": 0,
            "total_refs_produced": 0,
            "verified_logical_steps": 0,
            "repeated_refs": 0,
            "retired_refs": 0,
        }

    matches = TYPED_REF_RE.findall(text)
    ref_names = [f"{prefix}.{name}" for prefix, name in matches]
    ref_counts = Counter(ref_names)

    typed_refs_produced = len(ref_counts)
    total_refs_produced = len(ref_names)
    verified_logical_steps = sum(
        count for ref, count in ref_counts.items() if ref.startswith("V.")
    )
    repeated_refs = sum(count - 1 for count in ref_counts.values() if count > 1)
    retired_refs = 0

    return {
        "typed_refs_produced": typed_refs_produced,
        "total_refs_produced": total_refs_produced,
        "verified_logical_steps": verified_logical_steps,
        "repeated_refs": repeated_refs,
        "retired_refs": retired_refs,
    }
