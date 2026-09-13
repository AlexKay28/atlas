#!/usr/bin/env python3
"""Skill prompt ablation runner — 5 arms x 10 benchmarks x 5 samples x 3 trials = 750 trials.

Arms:
  classic — no system prompt (baseline)
  50      — minimal TAHOE skill (~50 tokens)
  93      — current production skill (~93 tokens, tahoe_skill_prompt.txt)
  150     — current + all 3 protocols with examples (~150 tokens)
  200     — full textbook distillation with need-trigger rules (~200 tokens)

EVALUATION INVARIANT: The grader and answer extraction logic must be IDENTICAL
for all arms. The ONLY difference between arms is the system prompt. Never
branch grading logic on arm identity.

Output: Pareto table — prompt_size x quality x output_tokens x HM (harmonic mean).
"""

import json
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_public_bench import (
    load_tasks,
    grade_task,
    extract_model_number,
)
from runner_classic import run as run_classic
from metrics import count_typed_refs, compute_all_metrics

# -- Configuration -------------------------------------------------------

ABLATION_ARMS = ["classic", "50", "93", "150", "200"]
TRIALS_PER_TASK = 3
MAX_SAMPLES_PER_BENCH = 10
SEED = 42

PROMPT_FILES = {
    "classic": None,
    "50": "tahoe_skill_50.txt",
    "93": "tahoe_skill_prompt.txt",
    "150": "tahoe_skill_150.txt",
    "200": "tahoe_skill_200.txt",
}

PROMPT_TOKEN_ESTIMATES = {
    "classic": 0,
    "50": 50,
    "93": 93,
    "150": 150,
    "200": 200,
}


# -- Prompt loading ------------------------------------------------------

def load_prompt(arm: str) -> str:
    """Load the system prompt for a given ablation arm.

    Returns "" for the classic arm (no prompt).
    """
    filename = PROMPT_FILES.get(arm)
    if filename is None:
        return ""
    path = os.path.join(os.path.dirname(__file__), filename)
    with open(path) as f:
        return f.read()


def load_all_prompts() -> dict:
    """Load all ablation prompts into a dict {arm: prompt_text}."""
    return {arm: load_prompt(arm) for arm in ABLATION_ARMS}


# -- Trial runner --------------------------------------------------------

def run_ablation_trial(task, arm, system_prompt, trial_idx):
    """Run a single ablation trial.

    Uses the same runner_classic.run and grade_task as the public bench
    so the evaluation invariant is preserved.
    """
    result = run_classic(
        task_id=f"{task['task_id']}-{arm}-t{trial_idx}",
        task_prompt=task["description"],
        model=os.environ.get("TAHOE_MODEL", "."),
        api_base=os.environ.get("TAHOE_API_BASE", ""),
        api_key=os.environ.get("TAHOE_API_KEY", ""),
        max_turns=1,
        max_tokens=2048,
        timeout_seconds=60,
        system_prompt=system_prompt,
    )
    passed, detail = grade_task(task, result.final_answer)

    ref_counts = count_typed_refs(result.final_answer)
    metrics = compute_all_metrics({
        "verified_logical_steps": ref_counts["verified_logical_steps"],
        "total_tokens": result.total_tokens,
        "typed_refs_produced": ref_counts["typed_refs_produced"],
        "output_tokens": result.output_tokens,
        "repeated_refs": ref_counts["repeated_refs"],
        "retired_refs": ref_counts["retired_refs"],
        "total_refs_produced": ref_counts["total_refs_produced"],
    })

    return {
        "task_id": task["task_id"],
        "benchmark": task["benchmark"],
        "arm": arm,
        "trial": trial_idx,
        "prompt_tokens_estimate": PROMPT_TOKEN_ESTIMATES[arm],
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "wall_seconds": result.wall_seconds,
        "passed": passed,
        "failure_class": "none" if passed else "wrong_answer",
        "final_answer": result.final_answer,
        "quality_score": 1.0 if passed else 0.0,
        "grader_detail": detail,
        "verified_logical_steps": ref_counts["verified_logical_steps"],
        "typed_refs_produced": ref_counts["typed_refs_produced"],
        "repeated_refs": ref_counts["repeated_refs"],
        "retired_refs": ref_counts["retired_refs"],
        "total_refs_produced": ref_counts["total_refs_produced"],
        "re_reasoning_efficiency": metrics["re_reasoning_efficiency"],
        "rc_reasoning_concentration": metrics["rc_reasoning_concentration"],
        "rr_redundancy_rate": metrics["rr_redundancy_rate"],
    }


# -- Pareto table --------------------------------------------------------

def compute_harmonic_mean(quality: float, efficiency: float) -> float:
    """Harmonic mean of quality (pass rate) and efficiency (1/output_tokens normalized).

    HM = 2 * quality * efficiency / (quality + efficiency)
    Returns 0.0 when either input is 0.
    """
    if quality <= 0 or efficiency <= 0:
        return 0.0
    return 2 * quality * efficiency / (quality + efficiency)


def compute_pareto_table(trials: list) -> list:
    """Compute the Pareto table: one row per arm.

    Columns: arm, prompt_tokens, quality (pass rate), avg_output_tokens,
             avg_total_tokens, HM, RE, RC, RR.
    """
    by_arm = defaultdict(list)
    for t in trials:
        by_arm[t["arm"]].append(t)

    rows = []
    for arm in ABLATION_ARMS:
        arm_trials = by_arm.get(arm, [])
        n = len(arm_trials)
        if n == 0:
            rows.append({
                "arm": arm,
                "prompt_tokens": PROMPT_TOKEN_ESTIMATES[arm],
                "quality": 0.0,
                "avg_output_tokens": 0.0,
                "avg_total_tokens": 0.0,
                "hm": 0.0,
                "re": 0.0,
                "rc": 0.0,
                "rr": 0.0,
                "n_trials": 0,
            })
            continue

        passed_count = sum(1 for t in arm_trials if t["passed"])
        quality = passed_count / n
        avg_out = sum(t["output_tokens"] for t in arm_trials) / n
        avg_total = sum(t["total_tokens"] for t in arm_trials) / n
        avg_re = sum(t["re_reasoning_efficiency"] for t in arm_trials) / n
        avg_rc = sum(t["rc_reasoning_concentration"] for t in arm_trials) / n
        avg_rr = sum(t["rr_redundancy_rate"] for t in arm_trials) / n

        # Efficiency: inverse of normalized output tokens (fewer tokens = more efficient)
        # Normalize by a reference (e.g. 2048 max tokens)
        max_out = 2048.0
        efficiency = 1.0 - (avg_out / max_out) if avg_out < max_out else 0.0
        hm = compute_harmonic_mean(quality, efficiency)

        rows.append({
            "arm": arm,
            "prompt_tokens": PROMPT_TOKEN_ESTIMATES[arm],
            "quality": quality,
            "avg_output_tokens": avg_out,
            "avg_total_tokens": avg_total,
            "hm": hm,
            "re": avg_re,
            "rc": avg_rc,
            "rr": avg_rr,
            "n_trials": n,
        })

    return rows


def format_pareto_table(rows: list) -> str:
    """Format the Pareto table as a printable string."""
    header = (
        f"{'arm':>8s} | {'prompt':>6s} | {'quality':>7s} | "
        f"{'out_tok':>7s} | {'tot_tok':>7s} | {'HM':>6s} | "
        f"{'RE':>6s} | {'RC':>6s} | {'RR':>6s} | {'n':>4s}"
    )
    sep = "-" * len(header)
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"{r['arm']:>8s} | {r['prompt_tokens']:>6d} | {r['quality']:>7.1%} | "
            f"{r['avg_output_tokens']:>7.0f} | {r['avg_total_tokens']:>7.0f} | "
            f"{r['hm']:>6.3f} | "
            f"{r['re']:>6.4f} | {r['rc']:>6.4f} | {r['rr']:>6.4f} | "
            f"{r['n_trials']:>4d}"
        )
    return "\n".join(lines)


# -- Main ----------------------------------------------------------------

def build_trial_plan(tasks, arms, trials_per_task, seed):
    """Build the shuffled trial plan: task x arm x trial."""
    plan = []
    for task in tasks:
        for arm in arms:
            for t in range(trials_per_task):
                plan.append((task, arm, t))
    rng = random.Random(seed)
    rng.shuffle(plan)
    return plan


def main():
    print("Loading public benchmarks...", flush=True)
    tasks = load_tasks()
    print(f"  {len(tasks)} tasks loaded", flush=True)

    prompts = load_all_prompts()
    for arm in ABLATION_ARMS:
        plen = len(prompts[arm])
        print(f"  arm={arm:>8s}  prompt_len={plen:>4d} chars  est_tokens={PROMPT_TOKEN_ESTIMATES[arm]}", flush=True)

    plan = build_trial_plan(tasks, ABLATION_ARMS, TRIALS_PER_TASK, SEED)
    total = len(plan)
    print(f"\nRunning {total} trials (shuffled, seed={SEED})...", flush=True)

    all_trials = []
    done = 0
    t0 = time.time()

    for task, arm, trial_idx in plan:
        system_prompt = prompts[arm]
        try:
            result = run_ablation_trial(task, arm, system_prompt, trial_idx)
            all_trials.append(result)
        except Exception as e:
            all_trials.append({
                "task_id": task["task_id"],
                "benchmark": task["benchmark"],
                "arm": arm,
                "trial": trial_idx,
                "prompt_tokens_estimate": PROMPT_TOKEN_ESTIMATES[arm],
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "wall_seconds": 0.0,
                "passed": False,
                "failure_class": "error",
                "final_answer": f"ERROR: {e}",
                "quality_score": 0.0,
                "grader_detail": str(e),
                "verified_logical_steps": 0,
                "typed_refs_produced": 0,
                "repeated_refs": 0,
                "retired_refs": 0,
                "total_refs_produced": 0,
                "re_reasoning_efficiency": 0.0,
                "rc_reasoning_concentration": 0.0,
                "rr_redundancy_rate": 0.0,
            })
        done += 1
        if done % 25 == 0 or done == total:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            print(f"  [{done}/{total}] {task['task_id']} / {arm} / t{trial_idx} "
                  f"({rate:.1f}/s)", flush=True)

    print(f"\nDone in {time.time()-t0:.0f}s. {len(all_trials)} trials collected.\n")

    # Pareto table
    rows = compute_pareto_table(all_trials)
    print("=== PARETO TABLE (prompt_size x quality x output_tokens x HM) ===\n")
    print(format_pareto_table(rows))

    # Per-benchmark breakdown
    print("\n=== PER-BENCHMARK PASS RATE ===\n")
    benchmarks = sorted(set(t["benchmark"] for t in all_trials))
    arm_names = ABLATION_ARMS
    print(f"{'benchmark':16s} | " + " | ".join(f"{a:>8s}" for a in arm_names))
    print("-" * (18 + len(arm_names) * 11))
    for bench in benchmarks:
        parts = [f"{bench:16s}"]
        for arm in arm_names:
            bt = [t for t in all_trials if t["benchmark"] == bench and t["arm"] == arm]
            if bt:
                cp = sum(1 for x in bt if x["passed"])
                parts.append(f"{cp:>3d}/{len(bt):<4d}")
            else:
                parts.append(f"{'--':>8s}")
        print(" | ".join(parts))

    # Save results
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "prompt_ablation.json", "w") as f:
        json.dump({"trials": all_trials, "pareto": rows}, f, indent=2, sort_keys=True)
    print(f"\nResults saved to {results_dir}/prompt_ablation.json")


if __name__ == "__main__":
    main()
