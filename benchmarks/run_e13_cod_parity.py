#!/usr/bin/env python3
"""E13: Chain of Draft parity experiment — prove TAHOE's structure adds
value beyond a "be brief and structured" prompt, or acknowledge it doesn't.

3 arms: classic (no prompt), cod (Chain of Draft), tahoe (TAHOE skill).
Same 10 benchmarks from run_public_bench.py, 5 samples per benchmark,
3 trials per task — 150 trials per arm, 450 total.

EVALUATION INVARIANT: The grader and answer extraction logic must be
IDENTICAL for all arms. The ONLY difference between arms is the system
prompt. Never branch grading logic on arm identity.

Usage:
  export TAHOE_API_BASE="https://your-api-endpoint/v1"
  export TAHOE_API_KEY="your-api-key"
  export TAHOE_MODEL="."
  PYTHONPATH=src python3 benchmarks/run_e13_cod_parity.py

  # Override arms via env:
  BENCH_ARMS=classic,cod,tahoe PYTHONPATH=src python3 benchmarks/run_e13_cod_parity.py
"""

import json
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_public_bench import (
    load_tasks as _load_public_tasks,
    load_arm_prompt,
    load_skill,
    run_trial as _run_public_trial,
    grade_task,
    ARM_PROMPT_FILES,
    SEED,
)
from runner_classic import run as run_classic
from metrics import count_typed_refs

E13_ARMS = ["classic", "cod", "tahoe"]
E13_TRIALS_PER_TASK = 3
E13_MAX_SAMPLES_PER_BENCH = 5

_arms_env = os.environ.get("BENCH_ARMS", "")
if _arms_env:
    ARMS = [a.strip() for a in _arms_env.split(",") if a.strip()]
else:
    ARMS = list(E13_ARMS)


def load_tasks():
    """Load 5 tasks from each of the 10 benchmarks (50 total).

    Reuses the same benchmark datasets and sampling logic as
    run_public_bench.load_tasks, but with MAX_SAMPLES_PER_BENCH=5
    to keep the experiment budget at 450 trials.
    """
    import run_public_bench as rpb

    original_max = rpb.MAX_SAMPLES_PER_BENCH
    rpb.MAX_SAMPLES_PER_BENCH = E13_MAX_SAMPLES_PER_BENCH
    try:
        tasks = _load_public_tasks()
    finally:
        rpb.MAX_SAMPLES_PER_BENCH = original_max
    return tasks


def run_trial(task, arm, skill_prompt, trial_idx):
    """Run a single trial for a given arm.

    Reuses the same grading and token-counting infrastructure as
    run_public_bench.run_trial — the ONLY difference between arms
    is the system prompt.
    """
    return _run_public_trial(task, arm, skill_prompt, trial_idx)


def main():
    print("E13: Chain of Draft parity experiment")
    print(f"  Arms: {ARMS}")
    print(f"  Trials per task: {E13_TRIALS_PER_TASK}")
    print(f"  Samples per benchmark: {E13_MAX_SAMPLES_PER_BENCH}")
    print()

    print("Loading tasks...")
    tasks = load_tasks()
    print(f"  {len(tasks)} tasks loaded ({E13_MAX_SAMPLES_PER_BENCH} per benchmark x 10 benchmarks)")

    skill_prompt = load_skill()

    trial_plan = []
    for task in tasks:
        for arm in ARMS:
            for t in range(E13_TRIALS_PER_TASK):
                trial_plan.append((task, arm, t))

    rng = random.Random(SEED)
    rng.shuffle(trial_plan)

    expected_total = len(tasks) * len(ARMS) * E13_TRIALS_PER_TASK
    print(f"Running {len(trial_plan)} trials (expected {expected_total}, seed={SEED})...")
    all_trials = []
    for i, (task, arm, trial_idx) in enumerate(trial_plan):
        print(
            f"  [{i+1}/{len(trial_plan)}] {task['task_id']} / {arm} / t{trial_idx} ...",
            end=" ",
            flush=True,
        )
        try:
            result = run_trial(task, arm, skill_prompt, trial_idx)
            all_trials.append(result)
            print(f"passed={result['passed']} tokens={result['total_tokens']}")
        except Exception as e:
            print(f"ERROR: {e}")
            all_trials.append({
                "task_id": task["task_id"],
                "benchmark": task["benchmark"],
                "arm": arm,
                "trial": trial_idx,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "wall_seconds": 0.0,
                "passed": False,
                "failure_class": "error",
                "final_answer": f"ERROR: {e}",
                "quality_score": 0.0,
                "verified_logical_steps": 0,
                "typed_refs_produced": 0,
                "repeated_refs": 0,
                "retired_refs": 0,
                "total_refs_produced": 0,
            })

    print("\n=== E13 RESULTS: 3-Arm Comparison ===\n")

    arm_names = sorted(set(t["arm"] for t in all_trials))

    # Pass rate table
    header = f"{'benchmark':16s} | " + " | ".join(f"{a:>12s}" for a in arm_names)
    print(header)
    print("-" * (18 + len(arm_names) * 15))

    for bench in sorted(set(t["benchmark"] for t in all_trials)):
        parts = [f"{bench:16s}"]
        for a in arm_names:
            arm_trials = [t for t in all_trials if t["benchmark"] == bench and t["arm"] == a]
            if arm_trials:
                cp = sum(1 for x in arm_trials if x["passed"])
                parts.append(f"{cp:>3d}/{len(arm_trials):<3d} ({100*cp/len(arm_trials):>3.0f}%)")
            else:
                parts.append(f"{'--':>12s}")
        print(" | ".join(parts))

    print("-" * (18 + len(arm_names) * 15))
    parts = [f"{'OVERALL':16s}"]
    for a in arm_names:
        arm_trials = [t for t in all_trials if t["arm"] == a]
        cp = sum(1 for x in arm_trials if x["passed"])
        parts.append(f"{cp:>3d}/{len(arm_trials):<3d} ({100*cp/len(arm_trials):>3.0f}%)")
    print(" | ".join(parts))

    # Token table
    print("\n=== Token Usage (mean total tokens) ===\n")
    print(f"{'benchmark':16s} | " + " | ".join(f"{a:>12s}" for a in arm_names))
    print("-" * (18 + len(arm_names) * 15))

    for bench in sorted(set(t["benchmark"] for t in all_trials)):
        parts = [f"{bench:16s}"]
        for a in arm_names:
            arm_trials = [t for t in all_trials if t["benchmark"] == bench and t["arm"] == a]
            if arm_trials:
                mean_tok = sum(x["total_tokens"] for x in arm_trials) / len(arm_trials)
                parts.append(f"{mean_tok:>12.0f}")
            else:
                parts.append(f"{'--':>12s}")
        print(" | ".join(parts))

    print("-" * (18 + len(arm_names) * 15))
    parts = [f"{'OVERALL':16s}"]
    for a in arm_names:
        arm_trials = [t for t in all_trials if t["arm"] == a]
        mean_tok = sum(x["total_tokens"] for x in arm_trials) / len(arm_trials)
        parts.append(f"{mean_tok:>12.0f}")
    print(" | ".join(parts))

    # Decision gate
    print("\n=== Decision Gate ===\n")
    if "cod" in arm_names and "tahoe" in arm_names:
        cod_trials = [t for t in all_trials if t["arm"] == "cod"]
        tahoe_trials = [t for t in all_trials if t["arm"] == "tahoe"]
        cod_pass = sum(1 for x in cod_trials if x["passed"])
        tahoe_pass = sum(1 for x in tahoe_trials if x["passed"])
        cod_rate = cod_pass / len(cod_trials) if cod_trials else 0
        tahoe_rate = tahoe_pass / len(tahoe_trials) if tahoe_trials else 0
        cod_tokens = sum(x["total_tokens"] for x in cod_trials) / len(cod_trials) if cod_trials else 0
        tahoe_tokens = sum(x["total_tokens"] for x in tahoe_trials) / len(tahoe_trials) if tahoe_trials else 0

        print(f"  CoD   pass rate: {cod_pass}/{len(cod_trials)} = {cod_rate:.1%}")
        print(f"  TAHOE pass rate: {tahoe_pass}/{len(tahoe_trials)} = {tahoe_rate:.1%}")
        print(f"  CoD   mean tokens: {cod_tokens:.0f}")
        print(f"  TAHOE mean tokens: {tahoe_tokens:.0f}")

        if tahoe_rate > cod_rate:
            print("  -> TAHOE adds value (correctness > CoD)")
        elif tahoe_rate == cod_rate and tahoe_tokens <= cod_tokens:
            print("  -> TAHOE is token-efficient (equal correctness, <= CoD tokens)")
        elif tahoe_rate == cod_rate and tahoe_tokens > cod_tokens:
            print("  -> TAHOE is unnecessary overhead (equal correctness, > CoD tokens)")
        else:
            print("  -> TAHOE underperforms CoD (lower correctness)")

    # Save
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    output = {
        "experiment": "E13_chain_of_draft_parity",
        "arms": ARMS,
        "trials_per_task": E13_TRIALS_PER_TASK,
        "samples_per_benchmark": E13_MAX_SAMPLES_PER_BENCH,
        "total_trials": len(all_trials),
        "trials": all_trials,
    }
    with open(results_dir / "e13_cod_parity.json", "w") as f:
        json.dump(output, f, indent=2, sort_keys=True)

    print(f"\nResults saved to {results_dir}/e13_cod_parity.json")


if __name__ == "__main__":
    main()
