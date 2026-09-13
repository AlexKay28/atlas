"""Reasoning efficiency metrics inspired by arxiv:2606.03883.

Three metrics:
  RE  - Reasoning Efficiency:       verified_logical_steps / total_tokens
  RC  - Reasoning Concentration:    typed_refs_produced / total_output_tokens
  RR  - Redundancy Rate:            (repeated_refs + retired_refs) / total_refs_produced
"""

from __future__ import annotations


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
