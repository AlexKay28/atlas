"""Tests for TAHOE reasoning trajectory scoring."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.trajectory_score import score_trajectory, TrajectoryScore


def test_good_compute_trajectory():
    text = """
G.goal: How much will 3 books cost at $12 each with 10% tax?
E.price = 12
E.quantity = 3
P.subtotal: 3 * 12 = 36
P.tax: 36 * 0.10 = 3.60
P.total: 36 + 3.60 = 39.60
DONE P.total == 39.60
OUT.answer: 39.60
"""
    score = score_trajectory(text, "compute", "39.60")
    assert score.overall > 0.7, f"expected > 0.7, got {score.overall}"
    assert score.verification > 0.5
    assert score.answer_correct == 1.0
    assert score.protocol_match > 0.4


def test_narrative_trajectory_scores_low_on_efficiency():
    text = """
Let me think about this. Well, first I need to consider the price.
The price is $12 each, and we need 3 books. Let me think...
3 times 12 is 36. Now I should calculate the tax.
10% of 36 is 3.60. So the total is 39.60.
"""
    score = score_trajectory(text, "compute", "39.60")
    assert score.token_efficiency < 0.5, f"expected < 0.5, got {score.token_efficiency}"


def test_missing_verification_scores_low():
    text = """
G.goal: compute total
E.price = 12
P.total: 3 * 12 = 36
OUT.answer: 36
"""
    score = score_trajectory(text, "compute", "36")
    assert score.verification <= 0.3, f"expected <= 0.3, got {score.verification}"


def test_good_select_trajectory():
    text = """
G.goal: Which process causes Europa's surface cracks?
E.options: A) volcanic B) tectonic C) impacts D) flares
P.eliminate_A: No active volcanoes — eliminate
P.eliminate_C: Impact cracks would be radial — eliminate
P.eliminate_D: Solar flares don't affect ice — eliminate
D.choice: B
DONE D.choice in E.options
OUT.answer: (B)
"""
    score = score_trajectory(text, "select", "(B)")
    assert score.overall > 0.6
    assert score.protocol_match > 0.5
    assert score.answer_correct == 1.0


def test_good_deduce_trajectory():
    text = """
G.goal: Which book is third from the right?
C.leftmost: White is position 1
C.rightmost: Black is position 7
P.positions: 1=White 2=Blue 3=Red 4=Gray 5=Brown 6=Orange 7=Black
DONE all constraints satisfied
OUT.answer: (C)
"""
    score = score_trajectory(text, "deduce", "(C)")
    assert score.overall > 0.6
    assert score.completeness > 0.5


def test_no_refs_scores_zero_ref_usage():
    text = "The answer is 42 because I calculated it."
    score = score_trajectory(text, "compute", "42")
    assert score.ref_usage == 0.0


def test_concrete_values_boost_efficiency():
    text_without = "G.goal: compute total\nP.result: price times quantity\nOUT.answer: 36"
    text_with = "G.goal: compute total\nP.result: 3 * 12 = 36\nOUT.answer: 36"
    s1 = score_trajectory(text_without, "compute", "36")
    s2 = score_trajectory(text_with, "compute", "36")
    assert s2.token_efficiency >= s1.token_efficiency


def test_answer_not_found_scores_zero():
    text = "G.goal: compute\nP.result: 3 * 12 = 36\nOUT.answer: 36"
    score = score_trajectory(text, "compute", "42")
    assert score.answer_correct == 0.0


def test_overall_score_in_range():
    text = "G.goal: test\nOUT.answer: yes"
    score = score_trajectory(text, "compute", "yes")
    assert 0.0 <= score.overall <= 1.0
