"""Tests for reasoning efficiency metrics (issue #86)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.metrics import (
    compute_all_metrics,
    compute_reasoning_concentration,
    compute_reasoning_efficiency,
    compute_redundancy_rate,
    count_typed_refs,
)


# -- RE: Reasoning Efficiency ------------------------------------------


def test_re_basic_ratio():
    assert compute_reasoning_efficiency(10, 1000) == pytest.approx(0.01)


def test_re_zero_verified_steps():
    assert compute_reasoning_efficiency(0, 1000) == 0.0


def test_re_zero_tokens_returns_zero():
    assert compute_reasoning_efficiency(10, 0) == 0.0


def test_re_negative_tokens_returns_zero():
    assert compute_reasoning_efficiency(10, -1) == 0.0


def test_re_large_values():
    assert compute_reasoning_efficiency(500, 1_000_000) == pytest.approx(0.0005)


# -- RC: Reasoning Concentration ---------------------------------------


def test_rc_basic_ratio():
    assert compute_reasoning_concentration(20, 500) == pytest.approx(0.04)


def test_rc_zero_refs():
    assert compute_reasoning_concentration(0, 500) == 0.0


def test_rc_zero_output_tokens_returns_zero():
    assert compute_reasoning_concentration(20, 0) == 0.0


def test_rc_negative_output_tokens_returns_zero():
    assert compute_reasoning_concentration(20, -1) == 0.0


# -- RR: Redundancy Rate -----------------------------------------------


def test_rr_basic_ratio():
    assert compute_redundancy_rate(3, 2, 10) == pytest.approx(0.5)


def test_rr_no_redundancy():
    assert compute_redundancy_rate(0, 0, 10) == 0.0


def test_rr_all_retired():
    assert compute_redundancy_rate(0, 10, 10) == 1.0


def test_rr_all_repeated():
    assert compute_redundancy_rate(10, 0, 10) == 1.0


def test_rr_all_redundant():
    assert compute_redundancy_rate(5, 5, 10) == 1.0


def test_rr_zero_total_refs_returns_zero():
    assert compute_redundancy_rate(3, 2, 0) == 0.0


def test_rr_negative_total_refs_returns_zero():
    assert compute_redundancy_rate(3, 2, -1) == 0.0


# -- compute_all_metrics ------------------------------------------------


def test_compute_all_metrics_complete_dict():
    summary = {
        "verified_logical_steps": 10,
        "total_tokens": 2000,
        "typed_refs_produced": 30,
        "output_tokens": 1000,
        "repeated_refs": 5,
        "retired_refs": 3,
        "total_refs_produced": 30,
    }
    result = compute_all_metrics(summary)
    assert result["re_reasoning_efficiency"] == pytest.approx(10 / 2000)
    assert result["rc_reasoning_concentration"] == pytest.approx(30 / 1000)
    assert result["rr_redundancy_rate"] == pytest.approx(8 / 30)


def test_compute_all_metrics_missing_keys_default_zero():
    result = compute_all_metrics({})
    assert result["re_reasoning_efficiency"] == 0.0
    assert result["rc_reasoning_concentration"] == 0.0
    assert result["rr_redundancy_rate"] == 0.0


def test_compute_all_metrics_partial_dict():
    summary = {"verified_logical_steps": 5, "total_tokens": 500}
    result = compute_all_metrics(summary)
    assert result["re_reasoning_efficiency"] == pytest.approx(0.01)
    assert result["rc_reasoning_concentration"] == 0.0
    assert result["rr_redundancy_rate"] == 0.0


def test_compute_all_metrics_keys_present():
    result = compute_all_metrics({})
    assert set(result) == {
        "re_reasoning_efficiency",
        "rc_reasoning_concentration",
        "rr_redundancy_rate",
    }


# -- edge: combined zero scenario --------------------------------------


def test_all_zero_inputs():
    summary = {
        "verified_logical_steps": 0,
        "total_tokens": 0,
        "typed_refs_produced": 0,
        "output_tokens": 0,
        "repeated_refs": 0,
        "retired_refs": 0,
        "total_refs_produced": 0,
    }
    result = compute_all_metrics(summary)
    assert result == {
        "re_reasoning_efficiency": 0.0,
        "rc_reasoning_concentration": 0.0,
        "rr_redundancy_rate": 0.0,
    }


# -- count_typed_refs ---------------------------------------------------


def test_ref_count_empty_string():
    result = count_typed_refs("")
    assert result["typed_refs_produced"] == 0
    assert result["total_refs_produced"] == 0
    assert result["verified_logical_steps"] == 0
    assert result["repeated_refs"] == 0
    assert result["retired_refs"] == 0


def test_ref_count_none():
    result = count_typed_refs(None)
    assert result["typed_refs_produced"] == 0
    assert result["total_refs_produced"] == 0


def test_ref_count_single_ref():
    text = "G.goal: solve the problem"
    result = count_typed_refs(text)
    assert result["typed_refs_produced"] == 1
    assert result["total_refs_produced"] == 1
    assert result["verified_logical_steps"] == 0
    assert result["repeated_refs"] == 0
    assert result["retired_refs"] == 0


def test_ref_count_multiple_distinct_refs():
    text = """G.goal: solve the problem
C.constraint: must be fast
E.evidence: the answer is 42
P.step_1: do something
H.thesis: the result is correct
V.verify: check the answer
D.decision: pick option C"""
    result = count_typed_refs(text)
    assert result["typed_refs_produced"] == 7
    assert result["total_refs_produced"] == 7
    assert result["verified_logical_steps"] == 1
    assert result["repeated_refs"] == 0
    assert result["retired_refs"] == 0


def test_ref_count_repeated_refs():
    text = """G.goal: solve the problem
G.goal: try again differently
E.evidence: found the answer
E.evidence: confirmed
P.step_1: first step"""
    result = count_typed_refs(text)
    assert result["typed_refs_produced"] == 3
    assert result["total_refs_produced"] == 5
    assert result["verified_logical_steps"] == 0
    assert result["repeated_refs"] == 2
    assert result["retired_refs"] == 0


def test_ref_count_verified_steps():
    text = """G.goal: solve it
V.verify: checked step 1
V.verify: checked step 2
V.confirmed: all good"""
    result = count_typed_refs(text)
    assert result["verified_logical_steps"] == 3
    assert result["typed_refs_produced"] == 3
    assert result["total_refs_produced"] == 4
    assert result["repeated_refs"] == 1


def test_ref_count_mixed_verified_and_repeated():
    text = """G.goal: solve it
P.step_1: do something
P.step_1: redo it
V.verify: checked
V.verify: double checked"""
    result = count_typed_refs(text)
    assert result["typed_refs_produced"] == 3
    assert result["total_refs_produced"] == 5
    assert result["verified_logical_steps"] == 2
    assert result["repeated_refs"] == 2


def test_ref_count_no_typed_refs_in_plain_text():
    text = """The answer is 42.
This is a plain chain-of-thought without any typed refs.
Just regular reasoning text."""
    result = count_typed_refs(text)
    assert result["typed_refs_produced"] == 0
    assert result["total_refs_produced"] == 0
    assert result["verified_logical_steps"] == 0


def test_ref_count_tahoe_skill_output():
    text = """G.goal: Which process causes Europa's surface cracks?
E.options: A) volcanic B) tectonic C) impacts D) flares
P.eliminate_A: No active volcanoes — eliminate
P.eliminate_C: Impact cracks would be radial — eliminate
P.eliminate_D: Solar flares don't affect ice — eliminate
D.choice: B"""
    result = count_typed_refs(text)
    assert result["typed_refs_produced"] == 6
    assert result["total_refs_produced"] == 6
    assert result["verified_logical_steps"] == 0
    assert result["repeated_refs"] == 0


def test_ref_count_underscore_in_name():
    text = "P.step_1: first\nP.step_2: second\nP.step_10: tenth"
    result = count_typed_refs(text)
    assert result["typed_refs_produced"] == 3
    assert result["total_refs_produced"] == 3


def test_ref_count_case_sensitive():
    text = "G.goal: upper case\ng.goal: lower case should not match"
    result = count_typed_refs(text)
    assert result["typed_refs_produced"] == 1
    assert result["total_refs_produced"] == 1


def test_ref_count_metrics_integration():
    """count_typed_refs output feeds directly into compute_all_metrics."""
    text = """G.goal: solve it
P.step_1: do something
V.verify: checked
E.evidence: done"""
    ref_counts = count_typed_refs(text)
    summary = {**ref_counts, "total_tokens": 1000, "output_tokens": 500}
    metrics = compute_all_metrics(summary)
    assert metrics["re_reasoning_efficiency"] == pytest.approx(1 / 1000)
    assert metrics["rc_reasoning_concentration"] == pytest.approx(4 / 500)
    assert metrics["rr_redundancy_rate"] == 0.0
