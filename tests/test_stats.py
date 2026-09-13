"""Tests for benchmarks/stats.py — bootstrap CIs, permutation tests,
Wilcoxon signed-rank, Cohen's h, and generate_stats_report.

Fast by construction: tests use small sample sizes and few resamples
to stay well under the suite's time budget.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.stats import (
    _standard_normal_cdf,
    bootstrap_ci,
    bootstrap_ci_pass_rate,
    cohens_h,
    generate_stats_report,
    paired_permutation_test,
    two_proportion_z_test,
    wilcoxon_signed_rank,
)


# -- Bootstrap CI --------------------------------------------------------


def test_bootstrap_ci_returns_point_estimate():
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    point, lo, hi = bootstrap_ci(data, n_resamples=1000, seed=42)
    assert point == pytest.approx(3.0)
    assert lo <= point <= hi


def test_bootstrap_ci_empty_returns_zeros():
    point, lo, hi = bootstrap_ci([])
    assert (point, lo, hi) == (0.0, 0.0, 0.0)


def test_bootstrap_ci_single_element():
    point, lo, hi = bootstrap_ci([42.0])
    assert point == 42.0
    assert lo == 42.0
    assert hi == 42.0


def test_bootstrap_ci_brackets_mean():
    data = [10.0] * 50 + [20.0] * 50
    point, lo, hi = bootstrap_ci(data, n_resamples=5000, seed=42)
    assert point == pytest.approx(15.0)
    assert lo < 15.0
    assert hi > 15.0
    assert lo > 10.0
    assert hi < 20.0


def test_bootstrap_ci_is_deterministic_with_seed():
    data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    r1 = bootstrap_ci(data, n_resamples=1000, seed=123)
    r2 = bootstrap_ci(data, n_resamples=1000, seed=123)
    assert r1 == r2


def test_bootstrap_ci_confidence_level_widens_interval():
    data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    _, lo90, hi90 = bootstrap_ci(data, n_resamples=5000, seed=42, confidence=0.90)
    _, lo99, hi99 = bootstrap_ci(data, n_resamples=5000, seed=42, confidence=0.99)
    assert lo99 <= lo90
    assert hi99 >= hi90


# -- Bootstrap CI pass rate ---------------------------------------------


def test_bootstrap_ci_pass_rate_all_pass():
    point, lo, hi = bootstrap_ci_pass_rate([True] * 20, n_resamples=1000, seed=42)
    assert point == 1.0
    assert lo == 1.0
    assert hi == 1.0


def test_bootstrap_ci_pass_rate_all_fail():
    point, lo, hi = bootstrap_ci_pass_rate([False] * 20, n_resamples=1000, seed=42)
    assert point == 0.0
    assert lo == 0.0
    assert hi == 0.0


def test_bootstrap_ci_pass_rate_half():
    passed = [True] * 50 + [False] * 50
    point, lo, hi = bootstrap_ci_pass_rate(passed, n_resamples=5000, seed=42)
    assert point == pytest.approx(0.5)
    assert 0.3 < lo < 0.5
    assert 0.5 < hi < 0.7


# -- Paired permutation test --------------------------------------------


def test_permutation_test_identical_returns_high_p():
    a = [5.0, 6.0, 7.0, 8.0, 9.0]
    p = paired_permutation_test(a, a, n_permutations=2000, seed=42)
    assert p > 0.5


def test_permutation_test_large_effect_low_p():
    a = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    b = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    p = paired_permutation_test(a, b, n_permutations=5000, seed=42)
    assert p < 0.05


def test_permutation_test_unequal_length_raises():
    with pytest.raises(ValueError, match="equal-length"):
        paired_permutation_test([1, 2, 3], [1, 2])


def test_permutation_test_empty_returns_one():
    assert paired_permutation_test([], []) == 1.0


def test_permutation_test_single_pair_returns_one():
    assert paired_permutation_test([5.0], [3.0]) == 1.0


def test_permutation_test_deterministic_with_seed():
    a = [5.0, 6.0, 7.0, 8.0]
    b = [1.0, 2.0, 3.0, 4.0]
    p1 = paired_permutation_test(a, b, n_permutations=1000, seed=99)
    p2 = paired_permutation_test(a, b, n_permutations=1000, seed=99)
    assert p1 == p2


# -- Wilcoxon signed-rank test ------------------------------------------


def test_wilcoxon_identical_returns_p_one():
    result = wilcoxon_signed_rank([5.0, 6.0, 7.0], [5.0, 6.0, 7.0])
    assert result["p_value"] == 1.0
    assert result["n"] == 0


def test_wilcoxon_large_effect_low_p():
    a = [20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0]
    b = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    result = wilcoxon_signed_rank(a, b)
    assert result["p_value"] < 0.05
    assert result["z_stat"] is not None
    assert result["n"] == 10


def test_wilcoxon_all_zero_diffs():
    result = wilcoxon_signed_rank([3.0, 3.0], [3.0, 3.0])
    assert result["p_value"] == 1.0
    assert result["n"] == 0


def test_wilcoxon_unequal_length_raises():
    with pytest.raises(ValueError, match="equal-length"):
        wilcoxon_signed_rank([1, 2, 3], [1, 2])


def test_wilcoxon_small_n_exact():
    result = wilcoxon_signed_rank([10.0, 20.0, 30.0], [1.0, 2.0, 3.0])
    assert result["n"] == 3
    assert 0.0 < result["p_value"] <= 1.0
    assert result["z_stat"] is None


def test_wilcoxon_returns_dict_with_expected_keys():
    result = wilcoxon_signed_rank([1.0, 2.0, 3.0, 4.0], [0.5, 1.0, 1.5, 2.0])
    assert set(result) == {"w_stat", "z_stat", "p_value", "n"}


def test_wilcoxon_ties_handled():
    a = [2.0, 2.0, 4.0, 6.0]
    b = [1.0, 1.0, 1.0, 1.0]
    result = wilcoxon_signed_rank(a, b)
    assert result["n"] == 4
    assert 0.0 < result["p_value"] <= 1.0


# -- Cohen's h -----------------------------------------------------------


def test_cohens_h_zero_when_equal():
    assert cohens_h(0.5, 0.5) == pytest.approx(0.0, abs=1e-10)


def test_cohens_h_known_value():
    h = cohens_h(0.8, 0.6)
    expected = abs(2 * __import__("math").asin(__import__("math").sqrt(0.8))
                   - 2 * __import__("math").asin(__import__("math").sqrt(0.6)))
    assert h == pytest.approx(expected)


def test_cohens_h_extreme_proportions():
    h = cohens_h(0.0, 1.0)
    assert h == pytest.approx(__import__("math").pi, abs=1e-6)


def test_cohens_h_out_of_range_raises():
    with pytest.raises(ValueError):
        cohens_h(-0.1, 0.5)
    with pytest.raises(ValueError):
        cohens_h(0.5, 1.1)


def test_cohens_h_symmetric():
    assert cohens_h(0.9, 0.3) == pytest.approx(cohens_h(0.3, 0.9))


# -- Two-proportion z-test -----------------------------------------------


def test_z_test_identical_proportions():
    result = two_proportion_z_test(10, 20, 10, 20)
    assert result["z_stat"] == pytest.approx(0.0)
    assert result["p_value"] == pytest.approx(1.0)


def test_z_test_large_effect_significant():
    result = two_proportion_z_test(90, 100, 10, 100)
    assert result["p_value"] < 0.05
    assert result["z_stat"] > 0


def test_z_test_all_pass():
    result = two_proportion_z_test(20, 20, 20, 20)
    assert result["p_value"] == 1.0


def test_z_test_all_fail():
    result = two_proportion_z_test(0, 20, 0, 20)
    assert result["p_value"] == 1.0


def test_z_test_zero_n_raises():
    with pytest.raises(ValueError):
        two_proportion_z_test(1, 0, 1, 10)


# -- _standard_normal_cdf ------------------------------------------------


def test_standard_normal_cdf_zero():
    assert _standard_normal_cdf(0.0) == pytest.approx(0.5)


def test_standard_normal_cdf_symmetry():
    for x in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        cdf_x = _standard_normal_cdf(x)
        cdf_neg = _standard_normal_cdf(-x)
        assert cdf_x + cdf_neg == pytest.approx(1.0)


def test_standard_normal_cdf_extremes():
    assert _standard_normal_cdf(-5.0) < 1e-6
    assert _standard_normal_cdf(5.0) > 1.0 - 1e-6


# -- generate_stats_report -----------------------------------------------


def _make_trials():
    """Build a small synthetic trial set with two arms."""
    trials = []
    for task_id in ["t1", "t2", "t3"]:
        for arm in ["classic", "tahoe"]:
            for k in range(10):
                if arm == "tahoe":
                    passed = k < 8
                    tokens = 100 + k * 10
                else:
                    passed = k < 5
                    tokens = 200 + k * 10
                trials.append({
                    "task_id": task_id,
                    "benchmark": "bench_a",
                    "arm": arm,
                    "trial": k,
                    "passed": passed,
                    "total_tokens": tokens,
                    "output_tokens": tokens // 2,
                    "input_tokens": tokens // 2,
                })
    return trials


def test_generate_stats_report_empty():
    report = generate_stats_report([])
    assert report == {"groups": {}, "comparisons": {}, "per_task": {}}


def test_generate_stats_report_has_groups():
    trials = _make_trials()
    report = generate_stats_report(trials, n_resamples=500, n_permutations=500, seed=42)
    assert "bench_a/classic" in report["groups"]
    assert "bench_a/tahoe" in report["groups"]


def test_generate_stats_report_group_stats():
    trials = _make_trials()
    report = generate_stats_report(trials, n_resamples=500, n_permutations=500, seed=42)
    g = report["groups"]["bench_a/tahoe"]
    assert g["n"] == 30
    assert g["pass_rate"] == pytest.approx(0.8)
    assert g["n_passed"] == 24
    assert g["pass_rate_ci"][0] <= g["pass_rate"] <= g["pass_rate_ci"][1]
    assert g["mean_tokens"] > 0
    assert g["mean_tokens_ci"][0] <= g["mean_tokens"] <= g["mean_tokens_ci"][1]


def test_generate_stats_report_has_comparisons():
    trials = _make_trials()
    report = generate_stats_report(trials, n_resamples=500, n_permutations=500, seed=42)
    assert "bench_a/classic_vs_tahoe" in report["comparisons"]


def test_generate_stats_report_comparison_fields():
    trials = _make_trials()
    report = generate_stats_report(trials, n_resamples=500, n_permutations=500, seed=42)
    comp = report["comparisons"]["bench_a/classic_vs_tahoe"]
    assert comp["arm_a"] == "classic"
    assert comp["arm_b"] == "tahoe"
    assert comp["pass_rate_a"] == pytest.approx(0.5)
    assert comp["pass_rate_b"] == pytest.approx(0.8)
    assert comp["cohens_h"] > 0
    assert "z_stat" in comp["z_test"]
    assert "p_value" in comp["z_test"]
    assert 0.0 < comp["permutation_p"] <= 1.0
    assert "p_value" in comp["wilcoxon"]


def test_generate_stats_report_per_task():
    trials = _make_trials()
    report = generate_stats_report(trials, n_resamples=500, n_permutations=500, seed=42)
    assert "t1/classic_vs_tahoe" in report["per_task"]
    assert "t2/classic_vs_tahoe" in report["per_task"]
    assert "t3/classic_vs_tahoe" in report["per_task"]


def test_generate_stats_report_large_effect_significant():
    trials = _make_trials()
    report = generate_stats_report(trials, n_resamples=1000, n_permutations=2000, seed=42)
    comp = report["comparisons"]["bench_a/classic_vs_tahoe"]
    assert comp["cohens_h"] > 0.2
    assert comp["z_test"]["p_value"] < 0.05


def test_generate_stats_report_deterministic():
    trials = _make_trials()
    r1 = generate_stats_report(trials, n_resamples=500, n_permutations=500, seed=77)
    r2 = generate_stats_report(trials, n_resamples=500, n_permutations=500, seed=77)
    assert r1 == r2


def test_generate_stats_report_three_arms():
    trials = []
    for task_id in ["t1"]:
        for arm in ["classic", "tahoe", "baseline"]:
            for k in range(10):
                passed = (k + hash(arm)) % 3 != 0
                tokens = 100 + k * 20
                trials.append({
                    "task_id": task_id,
                    "benchmark": "bench_x",
                    "arm": arm,
                    "trial": k,
                    "passed": passed,
                    "total_tokens": tokens,
                    "output_tokens": tokens // 2,
                    "input_tokens": tokens // 2,
                })
    report = generate_stats_report(trials, n_resamples=300, n_permutations=300, seed=42)
    assert len(report["comparisons"]) == 3
    assert "bench_x/baseline_vs_classic" in report["comparisons"]
    assert "bench_x/baseline_vs_tahoe" in report["comparisons"]
    assert "bench_x/classic_vs_tahoe" in report["comparisons"]
