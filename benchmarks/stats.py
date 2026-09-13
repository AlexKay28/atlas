"""Statistical significance tests and effect sizes for benchmark comparisons.

Provides:
  - Bootstrap confidence intervals (extracted from run_parallel_bench.py)
  - Paired permutation test (extracted from run_parallel_bench.py)
  - Wilcoxon signed-rank test for paired comparisons
  - Cohen's h effect size for proportion comparisons
  - generate_stats_report() — full stats report from trial data

Designed to work with trial dicts that have at minimum:
  task_id, benchmark, arm, passed, total_tokens, output_tokens, trial

No external dependencies beyond the standard library.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from typing import Any


# ---------------------------------------------------------------------------
# Bootstrap confidence interval
# ---------------------------------------------------------------------------

def bootstrap_ci(
    data: list[float],
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int | None = None,
) -> tuple[float, float, float]:
    """Bootstrap confidence interval for the mean of *data*.

    Returns (point_estimate, lower_bound, upper_bound).

    Uses percentile method: sort the bootstrap means and take the
    alpha/2 and 1-alpha/2 percentiles.
    """
    if not data:
        return 0.0, 0.0, 0.0
    if len(data) == 1:
        v = float(data[0])
        return v, v, v

    rng = random.Random(seed)
    n = len(data)
    means = []
    for _ in range(n_resamples):
        sample = [data[rng.randrange(n)] for _ in range(n)]
        means.append(statistics.fmean(sample))

    means.sort()
    alpha = 1.0 - confidence
    lo_idx = int(alpha / 2 * n_resamples)
    hi_idx = int((1 - alpha / 2) * n_resamples)
    hi_idx = min(hi_idx, n_resamples - 1)

    point = statistics.fmean(data)
    return point, means[lo_idx], means[hi_idx]


def bootstrap_ci_pass_rate(
    passed: list[bool],
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int | None = None,
) -> tuple[float, float, float]:
    """Bootstrap CI for the pass rate (proportion) of boolean *passed* list."""
    data = [1.0 if p else 0.0 for p in passed]
    point, lo, hi = bootstrap_ci(data, n_resamples, confidence, seed)
    return point, lo, hi


# ---------------------------------------------------------------------------
# Paired permutation test
# ---------------------------------------------------------------------------

def paired_permutation_test(
    a: list[float],
    b: list[float],
    n_permutations: int = 10_000,
    seed: int | None = None,
) -> float:
    """Two-sided paired permutation test.

    Tests whether the mean difference (a - b) is significantly
    different from zero by randomly swapping pairs.

    *a* and *b* must have the same length — they are paired observations.

    Returns a p-value in [0, 1].
    """
    if len(a) != len(b):
        raise ValueError(
            f"Paired test requires equal-length sequences: len(a)={len(a)}, len(b)={len(b)}"
        )
    n = len(a)
    if n == 0:
        return 1.0
    if n == 1:
        return 1.0

    diffs = [ai - bi for ai, bi in zip(a, b)]
    observed = abs(sum(diffs))

    rng = random.Random(seed)
    count = 0
    for _ in range(n_permutations):
        flipped = sum(d if rng.random() < 0.5 else -d for d in diffs)
        if abs(flipped) >= observed - 1e-12:
            count += 1

    return (count + 1) / (n_permutations + 1)


# ---------------------------------------------------------------------------
# Wilcoxon signed-rank test
# ---------------------------------------------------------------------------

def wilcoxon_signed_rank(
    a: list[float],
    b: list[float],
) -> dict[str, Any]:
    """Wilcoxon signed-rank test for paired data.

    Tests whether the median difference (a - b) is significantly
    different from zero.  Uses the normal approximation for the
    test statistic when n >= 10 (with continuity correction),
    and an exact small-n fallback otherwise.

    Returns a dict with keys:
        w_stat   — Wilcoxon W statistic (sum of positive ranks)
        z_stat   — normal approximation z-score (None for tiny n)
        p_value  — two-sided p-value
        n        — number of non-zero differences
    """
    if len(a) != len(b):
        raise ValueError(
            f"Paired test requires equal-length sequences: len(a)={len(a)}, len(b)={len(b)}"
        )

    diffs = [ai - bi for ai, bi in zip(a, b)]
    nonzero = [(abs(d), d) for d in diffs if d != 0]
    n = len(nonzero)

    if n == 0:
        return {"w_stat": 0.0, "z_stat": None, "p_value": 1.0, "n": 0}

    nonzero.sort(key=lambda x: x[0])

    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and nonzero[j + 1][0] == nonzero[i][0]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1

    w_plus = sum(ranks[k] for k in range(n) if nonzero[k][1] > 0)
    w_minus = sum(ranks[k] for k in range(n) if nonzero[k][1] < 0)
    w_stat = min(w_plus, w_minus)

    if n < 10:
        from itertools import combinations

        total = 2 ** n
        count = 0
        for mask in range(total):
            s = 0.0
            for bit in range(n):
                if mask & (1 << bit):
                    s += ranks[bit]
            if s <= w_stat + 1e-12 or s >= w_plus - 1e-12:
                if s <= w_stat + 1e-12:
                    count += 1
        p_value = min(1.0, 2.0 * count / total)
        return {"w_stat": w_stat, "z_stat": None, "p_value": p_value, "n": n}

    mu = n * (n + 1) / 4.0
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)

    if sigma == 0:
        return {"w_stat": w_stat, "z_stat": 0.0, "p_value": 1.0, "n": n}

    z = (w_stat - mu) / sigma
    p_value = 2.0 * (1.0 - _standard_normal_cdf(abs(z)))

    return {
        "w_stat": w_stat,
        "z_stat": z,
        "p_value": p_value,
        "n": n,
    }


def _standard_normal_cdf(x: float) -> float:
    """Approximate the standard normal CDF using the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# Cohen's h effect size
# ---------------------------------------------------------------------------

def cohens_h(p1: float, p2: float) -> float:
    """Cohen's h effect size for the difference between two proportions.

    h = |2 * arcsin(sqrt(p1)) - 2 * arcsin(sqrt(p2))|

    Interpretation (Cohen 1988):
        0.2  — small effect
        0.5  — medium effect
        0.8  — large effect
    """
    if not (0.0 <= p1 <= 1.0) or not (0.0 <= p2 <= 1.0):
        raise ValueError(f"Proportions must be in [0, 1]: p1={p1}, p2={p2}")
    phi1 = 2.0 * math.asin(math.sqrt(p1))
    phi2 = 2.0 * math.asin(math.sqrt(p2))
    return abs(phi1 - phi2)


# ---------------------------------------------------------------------------
# Two-proportion z-test
# ---------------------------------------------------------------------------

def two_proportion_z_test(
    successes1: int,
    n1: int,
    successes2: int,
    n2: int,
) -> dict[str, float]:
    """Two-proportion z-test (pooled).

    Tests H0: p1 == p2 vs H1: p1 != p2.

    Returns a dict with z_stat and p_value (two-sided).
    """
    if n1 <= 0 or n2 <= 0:
        raise ValueError("Sample sizes must be positive")
    p1 = successes1 / n1
    p2 = successes2 / n2
    pooled = (successes1 + successes2) / (n1 + n2)

    if pooled == 0 or pooled == 1:
        return {"z_stat": 0.0, "p_value": 1.0}

    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return {"z_stat": 0.0, "p_value": 1.0}

    z = (p1 - p2) / se
    p_value = 2.0 * (1.0 - _standard_normal_cdf(abs(z)))

    return {"z_stat": z, "p_value": p_value}


# ---------------------------------------------------------------------------
# Full stats report
# ---------------------------------------------------------------------------

def generate_stats_report(
    trials: list[dict],
    n_resamples: int = 10_000,
    n_permutations: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate a full statistical report from trial data.

    Expects trial dicts with keys:
        task_id, benchmark, arm, passed, trial, total_tokens, output_tokens

    The report contains:
        - Per-group (benchmark, arm) statistics with bootstrap CIs on pass rate
        - Pairwise arm comparisons with permutation tests, Wilcoxon, Cohen's h
        - Per-task pairwise comparisons

    Returns a nested dict suitable for JSON serialization.
    """
    if not trials:
        return {"groups": {}, "comparisons": {}, "per_task": {}}

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in trials:
        bench = t.get("benchmark", t.get("task_id", "unknown"))
        arm = t.get("arm", "unknown")
        groups[(bench, arm)].append(t)

    arms = sorted({arm for _, arm in groups})
    benchmarks = sorted({bench for bench, _ in groups})

    # --- Per-group stats with bootstrap CI on pass rate ---
    group_stats: dict[str, dict] = {}
    for (bench, arm) in sorted(groups):
        gtrials = groups[(bench, arm)]
        passed = [t.get("passed", False) for t in gtrials]
        tokens = [t.get("total_tokens", 0) for t in gtrials]
        out_tokens = [t.get("output_tokens", 0) for t in gtrials]

        pr_point, pr_lo, pr_hi = bootstrap_ci_pass_rate(
            passed, n_resamples=n_resamples, seed=seed,
        )
        tok_point, tok_lo, tok_hi = bootstrap_ci(
            tokens, n_resamples=n_resamples, seed=seed,
        )

        group_stats[f"{bench}/{arm}"] = {
            "n": len(gtrials),
            "pass_rate": pr_point,
            "pass_rate_ci": [pr_lo, pr_hi],
            "mean_tokens": tok_point,
            "mean_tokens_ci": [tok_lo, tok_hi],
            "mean_output_tokens": statistics.fmean(out_tokens) if out_tokens else 0.0,
            "n_passed": sum(1 for p in passed if p),
        }

    # --- Pairwise arm comparisons per benchmark ---
    comparisons: dict[str, dict] = {}
    for bench in benchmarks:
        for i, arm_a in enumerate(arms):
            for arm_b in arms[i + 1:]:
                ga = groups.get((bench, arm_a), [])
                gb = groups.get((bench, arm_b), [])
                if not ga or not gb:
                    continue

                key = f"{bench}/{arm_a}_vs_{arm_b}"
                comparisons[key] = _compare_groups(ga, gb, arm_a, arm_b,
                                                   n_resamples, n_permutations, seed)

    # --- Per-task pairwise comparisons (by task_id within each benchmark) ---
    per_task: dict[str, dict] = {}
    task_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for t in trials:
        bench = t.get("benchmark", "unknown")
        task_id = t.get("task_id", "unknown")
        arm = t.get("arm", "unknown")
        task_groups[(bench, task_id, arm)].append(t)

    for (bench, task_id, arm) in sorted(task_groups):
        pass  # just validate keys exist

    all_task_ids = sorted({t.get("task_id", "") for t in trials})
    for task_id in all_task_ids:
        for i, arm_a in enumerate(arms):
            for arm_b in arms[i + 1:]:
                ga = [t for t in trials
                      if t.get("task_id") == task_id and t.get("arm") == arm_a]
                gb = [t for t in trials
                      if t.get("task_id") == task_id and t.get("arm") == arm_b]
                if not ga or not gb:
                    continue
                key = f"{task_id}/{arm_a}_vs_{arm_b}"
                per_task[key] = _compare_groups(ga, gb, arm_a, arm_b,
                                                n_resamples, n_permutations, seed)

    return {
        "groups": group_stats,
        "comparisons": comparisons,
        "per_task": per_task,
    }


def _compare_groups(
    ga: list[dict],
    gb: list[dict],
    arm_a: str,
    arm_b: str,
    n_resamples: int,
    n_permutations: int,
    seed: int,
) -> dict[str, Any]:
    """Compare two trial groups — shared by comparisons and per_task."""
    passed_a = [t.get("passed", False) for t in ga]
    passed_b = [t.get("passed", False) for t in gb]
    tokens_a = [t.get("total_tokens", 0) for t in ga]
    tokens_b = [t.get("total_tokens", 0) for t in gb]

    p_a = sum(1 for p in passed_a if p) / len(passed_a) if passed_a else 0.0
    p_b = sum(1 for p in passed_b if p) / len(passed_b) if passed_b else 0.0

    h = cohens_h(p_a, p_b)

    z_result = two_proportion_z_test(
        sum(1 for p in passed_a if p), len(passed_a),
        sum(1 for p in passed_b if p), len(passed_b),
    )

    min_n = min(len(tokens_a), len(tokens_b))
    paired_a = tokens_a[:min_n]
    paired_b = tokens_b[:min_n]

    perm_p = paired_permutation_test(
        paired_a, paired_b, n_permutations=n_permutations, seed=seed,
    )

    wilcoxon = wilcoxon_signed_rank(paired_a, paired_b)

    return {
        "arm_a": arm_a,
        "arm_b": arm_b,
        "n_a": len(ga),
        "n_b": len(gb),
        "pass_rate_a": p_a,
        "pass_rate_b": p_b,
        "cohens_h": h,
        "z_test": z_result,
        "permutation_p": perm_p,
        "wilcoxon": wilcoxon,
    }
