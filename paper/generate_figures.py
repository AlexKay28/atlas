#!/usr/bin/env python3
"""Generate PDF figures for the TAHOE arxiv paper (issue #92).

Reads benchmarks/results/2026-09-13-stage1-full/full_test_eval.json (corrected full-test-set data)
and produces four PDF figures in paper/figures/:

  Figure 1 — Quality vs Output-Token-Ratio scatter (classic vs tahoe)
  Figure 2 — Per-benchmark bar chart (pass rate, grouped bars)
  Figure 3 — Token savings by benchmark (horizontal bar chart, %)
  Figure 4 — Example side-by-side reasoning (text comparison PDF)

Run:  PYTHONPATH=src python3 paper/generate_figures.py

Requires matplotlib (pip install matplotlib).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "benchmarks" / "results" / "2026-09-13-stage1-full" / "full_test_eval.json"
FIG_DIR = ROOT / "paper" / "figures"

BENCH_LABELS = {
    "arc": "ARC",
    "bbh": "BBH",
    "bbh_arith": "BBH-Arith",
    "bbh_track": "BBH-Track",
    "gsm8k": "GSM8K",
    "lsat": "LSAT",
    "mmlu_acct": "MMLU-Acct",
    "mmlu_logic": "MMLU-Logic",
    "mmlu_math": "MMLU-Math",
    "race": "RACE",
}

CLASSIC_COLOR = "#4477AA"
TAHOE_COLOR = "#EE6677"


def load_data(path: Path = DATA_PATH) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def aggregate_by_benchmark(records: list[dict]) -> dict[str, dict[str, dict]]:
    """Return {benchmark: {arm: {pass_rate, mean_output, mean_total, mean_quality, count, ...}}}."""
    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        grouped[r["benchmark"]][r["arm"]].append(r)

    result: dict[str, dict[str, dict]] = {}
    for bench, arms in grouped.items():
        result[bench] = {}
        for arm, trials in arms.items():
            n = len(trials)
            passed = sum(1 for t in trials if t["passed"])
            result[bench][arm] = {
                "pass_rate": passed / n if n else 0.0,
                "mean_output": sum(t["output_tokens"] for t in trials) / n if n else 0.0,
                "mean_total": sum(t["total_tokens"] for t in trials) / n if n else 0.0,
                "mean_quality": sum(t["quality_score"] for t in trials) / n if n else 0.0,
                "count": n,
                "passed": passed,
            }
    return result


def figure1_quality_vs_tokens(stats: dict[str, dict[str, dict]], pdf: PdfPages) -> None:
    """Scatter: quality (pass rate) vs mean output tokens, one point per benchmark per arm."""
    fig, ax = plt.subplots(figsize=(6, 4.5))

    for arm, color, marker in [("classic", CLASSIC_COLOR, "o"), ("tahoe", TAHOE_COLOR, "^")]:
        xs, ys = [], []
        for bench in sorted(stats):
            if arm in stats[bench]:
                xs.append(stats[bench][arm]["mean_output"])
                ys.append(stats[bench][arm]["pass_rate"])
        ax.scatter(xs, ys, c=color, marker=marker, s=80, label=arm.capitalize(), zorder=3, alpha=0.85)

    ax.set_xlabel("Mean Output Tokens per Trial")
    ax.set_ylabel("Pass Rate")
    ax.set_title("Figure 1: Quality vs Output Tokens")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)


def figure2_pass_rate_bars(stats: dict[str, dict[str, dict]], pdf: PdfPages) -> None:
    """Grouped bar chart: pass rate per benchmark, classic vs tahoe."""
    benchmarks = sorted(stats)
    labels = [BENCH_LABELS.get(b, b) for b in benchmarks]
    x = range(len(benchmarks))
    width = 0.35

    classic_rates = [stats[b].get("classic", {}).get("pass_rate", 0) for b in benchmarks]
    tahoe_rates = [stats[b].get("tahoe", {}).get("pass_rate", 0) for b in benchmarks]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar([i - width / 2 for i in x], classic_rates, width, color=CLASSIC_COLOR, label="Classic")
    ax.bar([i + width / 2 for i in x], tahoe_rates, width, color=TAHOE_COLOR, label="TAHOE")

    ax.set_ylabel("Pass Rate")
    ax.set_title("Figure 2: Pass Rate by Benchmark")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylim(0, 1.1)
    ax.legend(loc="upper right")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)


def figure3_token_savings(stats: dict[str, dict[str, dict]], pdf: PdfPages) -> None:
    """Horizontal bar chart: % token savings (classic - tahoe) / classic per benchmark."""
    benchmarks = sorted(stats)
    savings = []
    for b in benchmarks:
        classic = stats[b].get("classic", {})
        tahoe = stats[b].get("tahoe", {})
        if classic.get("mean_total", 0) > 0 and tahoe.get("mean_total", 0) > 0:
            pct = (classic["mean_total"] - tahoe["mean_total"]) / classic["mean_total"] * 100
        else:
            pct = 0.0
        savings.append(pct)

    labels = [BENCH_LABELS.get(b, b) for b in benchmarks]
    colors = [TAHOE_COLOR if s > 0 else CLASSIC_COLOR for s in savings]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(labels, savings, color=colors, height=0.6)
    ax.set_xlabel("Token Savings (%)")
    ax.set_title("Figure 3: Token Savings by Benchmark (TAHOE vs Classic)")
    ax.axvline(0, color="black", linewidth=0.5)
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)


def figure4_reasoning_comparison(records: list[dict], pdf: PdfPages) -> None:
    """Text comparison: pick a task with both classic and tahoe answers, show side-by-side."""
    by_task: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in records:
        by_task[r["task_id"]][r["arm"]] = r

    best_task = None
    best_diff = 0
    for task_id, arms in by_task.items():
        if "classic" in arms and "tahoe" in arms:
            c = arms["classic"]
            t = arms["tahoe"]
            if c["passed"] and t["passed"] and c["output_tokens"] > t["output_tokens"]:
                diff = c["output_tokens"] - t["output_tokens"]
                if diff > best_diff:
                    best_diff = diff
                    best_task = task_id

    if best_task is None:
        best_task = next(iter(by_task))

    classic = by_task[best_task].get("classic", {})
    tahoe = by_task[best_task].get("tahoe", {})

    classic_text = classic.get("final_answer", "N/A")
    tahoe_text = tahoe.get("final_answer", "N/A")
    classic_tokens = classic.get("output_tokens", 0)
    tahoe_tokens = tahoe.get("output_tokens", 0)

    def truncate(text: str, max_chars: int = 600) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n..."

    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(12, 6))
    fig.suptitle(f"Figure 4: Reasoning Comparison (task: {best_task})", fontsize=12, fontweight="bold")

    ax_left.set_title(f"Classic ({classic_tokens} output tokens)", fontsize=10)
    ax_left.axis("off")
    ax_left.text(
        0.02, 0.98, truncate(classic_text),
        transform=ax_left.transAxes, fontsize=7, verticalalignment="top",
        fontfamily="monospace", wrap=True,
        bbox=dict(boxstyle="round", facecolor="#E8EEF6", alpha=0.8),
    )

    ax_right.set_title(f"TAHOE ({tahoe_tokens} output tokens)", fontsize=10)
    ax_right.axis("off")
    ax_right.text(
        0.02, 0.98, truncate(tahoe_text),
        transform=ax_right.transAxes, fontsize=7, verticalalignment="top",
        fontfamily="monospace", wrap=True,
        bbox=dict(boxstyle="round", facecolor="#F9E8E8", alpha=0.8),
    )

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    pdf.savefig(fig)
    plt.close(fig)


def generate_all(data_path: Path = DATA_PATH, fig_dir: Path = FIG_DIR) -> list[str]:
    """Generate all four figures. Returns list of output file paths."""
    if not HAS_MPL:
        print("WARNING: matplotlib not available. Install with: pip install matplotlib", file=sys.stderr)
        print("Scripts are valid but no PDFs were generated.", file=sys.stderr)
        return []

    fig_dir.mkdir(parents=True, exist_ok=True)
    records = load_data(data_path)
    stats = aggregate_by_benchmark(records)

    pdf_path = fig_dir / "tahoe_figures.pdf"
    individual_paths = [
        fig_dir / "figure1_quality_vs_tokens.pdf",
        fig_dir / "figure2_pass_rate_bars.pdf",
        fig_dir / "figure3_token_savings.pdf",
        fig_dir / "figure4_reasoning_comparison.pdf",
    ]

    # Combined PDF
    with PdfPages(pdf_path) as pdf:
        figure1_quality_vs_tokens(stats, pdf)
        figure2_pass_rate_bars(stats, pdf)
        figure3_token_savings(stats, pdf)
        figure4_reasoning_comparison(records, pdf)

    # Individual PDFs
    for idx, (func, args) in enumerate([
        (figure1_quality_vs_tokens, (stats,)),
        (figure2_pass_rate_bars, (stats,)),
        (figure3_token_savings, (stats,)),
        (figure4_reasoning_comparison, (records,)),
    ]):
        with PdfPages(individual_paths[idx]) as pdf:
            func(*args, pdf=pdf)

    all_paths = [str(pdf_path)] + [str(p) for p in individual_paths]
    print(f"Generated {len(all_paths)} PDF files in {fig_dir}/")
    for p in all_paths:
        print(f"  {p}")
    return all_paths


if __name__ == "__main__":
    generate_all()
