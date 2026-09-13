"""Token distribution and solution quality report for the ablation study."""

import json
import statistics
from collections import defaultdict

try:
    from metrics import compute_all_metrics
except ImportError:
    from benchmarks.metrics import compute_all_metrics

STAT_FIELDS = (
    "pass_rate",
    "mean_tokens",
    "p25_tokens",
    "p50_tokens",
    "p75_tokens",
    "mean_wall",
    "mean_input_tokens",
    "mean_output_tokens",
    "mean_authoring_tokens",
    "mean_quality",
    "p25_quality",
    "p75_quality",
    "tokens_per_success",
)

REASONING_METRIC_FIELDS = (
    "re_reasoning_efficiency",
    "rc_reasoning_concentration",
    "rr_redundancy_rate",
)

COMPARISON_METRICS = (
    "pass_rate",
    "mean_tokens",
    "p25_tokens",
    "p75_tokens",
    "mean_wall",
    "mean_quality",
    "tokens_per_success",
    "re_reasoning_efficiency",
    "rc_reasoning_concentration",
    "rr_redundancy_rate",
)


def _percentiles(values):
    if not values:
        return 0.0, 0.0, 0.0
    if len(values) == 1:
        only = float(values[0])
        return only, only, only
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    return quartiles[0], quartiles[1], quartiles[2]


def _fmt(value):
    if value is None:
        return "-"
    return f"{float(value):.2f}"


def group_trials(trials):
    groups = defaultdict(list)
    for trial in trials:
        groups[(trial["task_id"], trial["arm"])].append(trial)
    return dict(groups)


def compute_reasoning_metrics(run_data) -> dict:
    """Compute RE, RC, RR reasoning metrics from run results.

    Accepts either a list of trial dicts (as used by compute_stats) or a
    single run-summary dict.  When trial-level ref/token counts are
    absent (e.g. classic-arm public-bench trials), the metrics are 0.0.
    """
    if isinstance(run_data, dict):
        return compute_all_metrics(run_data)

    if not run_data:
        return {field: 0.0 for field in REASONING_METRIC_FIELDS}

    totals = {
        "verified_logical_steps": sum(t.get("verified_logical_steps", 0) for t in run_data),
        "total_tokens": sum(t.get("total_tokens", 0) for t in run_data),
        "typed_refs_produced": sum(t.get("typed_refs_produced", 0) for t in run_data),
        "output_tokens": sum(t.get("output_tokens", 0) for t in run_data),
        "repeated_refs": sum(t.get("repeated_refs", 0) for t in run_data),
        "retired_refs": sum(t.get("retired_refs", 0) for t in run_data),
        "total_refs_produced": sum(t.get("total_refs_produced", 0) for t in run_data),
    }
    return compute_all_metrics(totals)


def compute_stats(trials):
    if not trials:
        return {field: 0.0 for field in STAT_FIELDS + REASONING_METRIC_FIELDS}
    totals = [trial["total_tokens"] for trial in trials]
    inputs = [trial["input_tokens"] for trial in trials]
    outputs = [trial["output_tokens"] for trial in trials]
    walls = [trial["wall_seconds"] for trial in trials]
    authoring = [trial.get("authoring_tokens") or 0 for trial in trials]
    p25, p50, p75 = _percentiles(totals)
    passed = sum(1 for trial in trials if trial["passed"])

    qualities = [
        trial.get("quality_score") for trial in trials
        if trial.get("quality_score") is not None
    ]
    if qualities:
        q_p25, q_p50, q_p75 = _percentiles(qualities)
        mean_quality = statistics.fmean(qualities)
    else:
        q_p25 = q_p50 = q_p75 = 0.0
        mean_quality = 0.0

    success_tokens = [
        trial["total_tokens"] for trial in trials if trial["passed"]
    ]
    tokens_per_success = (
        statistics.fmean(success_tokens) if success_tokens else 0.0
    )

    result = {
        "pass_rate": passed / len(trials),
        "mean_tokens": statistics.fmean(totals),
        "p25_tokens": p25,
        "p50_tokens": p50,
        "p75_tokens": p75,
        "mean_wall": statistics.fmean(walls),
        "mean_input_tokens": statistics.fmean(inputs),
        "mean_output_tokens": statistics.fmean(outputs),
        "mean_authoring_tokens": statistics.fmean(authoring),
        "mean_quality": mean_quality,
        "p25_quality": q_p25,
        "p75_quality": q_p75,
        "tokens_per_success": tokens_per_success,
    }
    result.update(compute_reasoning_metrics(trials))
    return result


def generate_markdown_table(trials):
    groups = group_trials(trials)
    lines = [
        "| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success | RE | RC | RR |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for task_id, arm in sorted(groups):
        group = groups[(task_id, arm)]
        stats = compute_stats(group)
        lines.append(
            "| {task} | {arm} | {n} | {pr} | {mq} | {mt} | {p25} | {p50} | {p75} | {mw} | {tps} | {re_:.4f} | {rc:.4f} | {rr:.4f} |".format(
                task=task_id,
                arm=arm,
                n=len(group),
                pr=_fmt(stats["pass_rate"]),
                mq=_fmt(stats["mean_quality"]),
                mt=_fmt(stats["mean_tokens"]),
                p25=_fmt(stats["p25_tokens"]),
                p50=_fmt(stats["p50_tokens"]),
                p75=_fmt(stats["p75_tokens"]),
                mw=_fmt(stats["mean_wall"]),
                tps=_fmt(stats["tokens_per_success"]),
                re_=stats["re_reasoning_efficiency"],
                rc=stats["rc_reasoning_concentration"],
                rr=stats["rr_redundancy_rate"],
            )
        )
    return "\n".join(lines)


def generate_json_report(trials):
    groups = group_trials(trials)
    entries = []
    for task_id, arm in sorted(groups):
        group = groups[(task_id, arm)]
        entry = {"task_id": task_id, "arm": arm, "trials": len(group)}
        entry.update(compute_stats(group))
        entries.append(entry)
    return json.dumps({"groups": entries}, indent=2, sort_keys=True)


def generate_per_task_comparison(trials):
    groups = group_trials(trials)
    arms = sorted({arm for _, arm in groups})
    tasks = sorted({task for task, _ in groups})
    tables = []
    for task in tasks:
        stats_by_arm = {
            arm: compute_stats(groups[(task, arm)])
            for arm in arms
            if (task, arm) in groups
        }
        lines = [
            "| task_id | metric | " + " | ".join(arms) + " |",
            "|" + "---|" * (2 + len(arms)),
        ]
        for metric in COMPARISON_METRICS:
            cells = [
                _fmt(stats_by_arm[arm][metric]) if arm in stats_by_arm else "-"
                for arm in arms
            ]
            lines.append("| {} | {} | {} |".format(task, metric, " | ".join(cells)))
        tables.append("\n".join(lines))
    return "\n\n".join(tables)
