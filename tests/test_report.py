import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.report import (
    compute_stats,
    generate_json_report,
    generate_markdown_table,
    generate_per_task_comparison,
    group_trials,
)

TASKS = ["t1", "t2", "t3"]
ARMS = ["classic", "opencode", "tahoe"]


def build_trials():
    trials = []
    for ti, task in enumerate(TASKS):
        for ai, arm in enumerate(ARMS):
            for k in range(5):
                total = 100 * (k + 1) + 10 * ti + 5 * ai
                passed = (k + ti + ai) % 3 != 0
                quality = 0.5 + 0.1 * (k + ti + ai) if passed else 0.0
                trials.append({
                    "task_id": task,
                    "arm": arm,
                    "trial": k,
                    "input_tokens": total // 2,
                    "output_tokens": total - total // 2,
                    "total_tokens": total,
                    "wall_seconds": 10.0 + k,
                    "passed": passed,
                    "failure_class": "none" if passed else "assert_failed",
                    "authoring_tokens": total if arm == "tahoe" else 0,
                    "quality_score": quality,
                })
    return trials


def test_group_trials_groups_by_task_and_arm():
    trials = build_trials()
    groups = group_trials(trials)

    assert len(groups) == 9
    assert sum(len(group) for group in groups.values()) == len(trials)

    for (task_id, arm), group in groups.items():
        assert task_id in TASKS
        assert arm in ARMS
        assert len(group) == 5
        assert all(trial["task_id"] == task_id for trial in group)
        assert all(trial["arm"] == arm for trial in group)
        assert [trial["trial"] for trial in group] == [0, 1, 2, 3, 4]

    assert set(groups) == {(task, arm) for task in TASKS for arm in ARMS}


def test_compute_stats_mean_and_percentiles():
    trials = build_trials()
    stats = compute_stats(group_trials(trials)[("t1", "classic")])

    assert stats["mean_tokens"] == pytest.approx(300.0)
    assert stats["p25_tokens"] == pytest.approx(200.0)
    assert stats["p50_tokens"] == pytest.approx(300.0)
    assert stats["p75_tokens"] == pytest.approx(400.0)
    assert stats["mean_wall"] == pytest.approx(12.0)
    assert stats["mean_input_tokens"] == pytest.approx(150.0)
    assert stats["mean_output_tokens"] == pytest.approx(150.0)
    assert stats["mean_authoring_tokens"] == pytest.approx(0.0)
    assert stats["pass_rate"] == pytest.approx(0.6)
    assert stats["mean_quality"] > 0.0
    assert stats["tokens_per_success"] > 0.0


def test_compute_stats_authoring_tokens_only_for_tahoe():
    groups = group_trials(build_trials())

    tahoe_stats = compute_stats(groups[("t1", "tahoe")])
    assert tahoe_stats["mean_authoring_tokens"] == pytest.approx(310.0)

    classic_stats = compute_stats(groups[("t2", "classic")])
    assert classic_stats["mean_authoring_tokens"] == pytest.approx(0.0)
    assert classic_stats["mean_tokens"] == pytest.approx(310.0)


def test_compute_stats_single_trial_percentiles():
    single = dict(build_trials()[1])
    stats = compute_stats([single])

    assert stats["mean_tokens"] == pytest.approx(single["total_tokens"])
    assert stats["p25_tokens"] == pytest.approx(single["total_tokens"])
    assert stats["p50_tokens"] == pytest.approx(single["total_tokens"])
    assert stats["p75_tokens"] == pytest.approx(single["total_tokens"])
    assert stats["pass_rate"] == pytest.approx(1.0)


def test_generate_markdown_table_format():
    table = generate_markdown_table(build_trials())
    lines = table.split("\n")

    assert lines[0] == "| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success | RE | RC | RR |"
    assert lines[1] == "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    assert len(lines) == 11

    assert "| t1 | classic | 5 | 0.60 | 0.44 | 300.00 | 200.00 | 300.00 | 400.00 | 12.00 | 333.33 | 0.0000 | 0.0000 | 0.0000 |" in lines
    assert "| t1 | tahoe | 5 | 0.60 | 0.52 | 310.00 | 210.00 | 310.00 | 410.00 | 12.00 | 276.67 | 0.0000 | 0.0000 | 0.0000 |" in lines

    data_rows = lines[2:]
    assert all(row.startswith("| t") and row.endswith("|") for row in data_rows)
    assert [tuple(part.strip() for part in row.split("|")[1:3]) for row in data_rows] == [
        ("t1", "classic"), ("t1", "opencode"), ("t1", "tahoe"),
        ("t2", "classic"), ("t2", "opencode"), ("t2", "tahoe"),
        ("t3", "classic"), ("t3", "opencode"), ("t3", "tahoe"),
    ]


def test_generate_json_report_structure():
    report = json.loads(generate_json_report(build_trials()))

    assert set(report) == {"groups"}
    assert len(report["groups"]) == 9

    entry = next(
        g for g in report["groups"]
        if g["task_id"] == "t1" and g["arm"] == "classic"
    )
    assert entry["trials"] == 5
    assert entry["pass_rate"] == pytest.approx(0.6)
    assert entry["mean_tokens"] == pytest.approx(300.0)
    assert entry["p25_tokens"] == pytest.approx(200.0)
    assert entry["p50_tokens"] == pytest.approx(300.0)
    assert entry["p75_tokens"] == pytest.approx(400.0)
    assert entry["mean_wall"] == pytest.approx(12.0)
    assert entry["mean_input_tokens"] == pytest.approx(150.0)
    assert entry["mean_output_tokens"] == pytest.approx(150.0)
    assert entry["mean_authoring_tokens"] == pytest.approx(0.0)

    for group in report["groups"]:
        assert {"task_id", "arm", "trials", "pass_rate", "mean_tokens",
                "p25_tokens", "p50_tokens", "p75_tokens", "mean_wall",
                "mean_input_tokens", "mean_output_tokens",
                "mean_authoring_tokens", "mean_quality",
                "p25_quality", "p75_quality",
                "tokens_per_success",
                "re_reasoning_efficiency",
                "rc_reasoning_concentration",
                "rr_redundancy_rate"} <= set(group)


def test_generate_per_task_comparison_format():
    report = generate_per_task_comparison(build_trials())
    tables = report.split("\n\n")

    assert len(tables) == 3
    for table, task in zip(tables, TASKS):
        assert table.startswith("| task_id | metric | classic | opencode | tahoe |")
        assert f"| {task} | pass_rate |" in table

    first = tables[0].split("\n")
    assert first[0] == "| task_id | metric | classic | opencode | tahoe |"
    assert first[1] == "|---|---|---|---|---|"

    metrics = [line.split("|")[2].strip() for line in first[2:]]
    assert metrics == ["pass_rate", "mean_tokens", "p25_tokens", "p75_tokens", "mean_wall", "mean_quality", "tokens_per_success", "re_reasoning_efficiency", "rc_reasoning_concentration", "rr_redundancy_rate"]

    assert "| t1 | pass_rate | 0.60 | 0.80 | 0.60 |" in first
    assert "| t1 | mean_tokens | 300.00 | 305.00 | 310.00 |" in first

    second = tables[1].split("\n")
    assert "| t2 | pass_rate | 0.80 | 0.60 | 0.60 |" in second
    assert any("| t2 | mean_quality |" in line for line in second)
    assert any("| t2 | tokens_per_success |" in line for line in second)
