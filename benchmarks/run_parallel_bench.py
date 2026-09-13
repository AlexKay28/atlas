#!/usr/bin/env python3
"""Parallel benchmark runner — splits 600 trials across N worker processes."""

import json
import os
import random
import sys
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_public_bench import load_tasks, load_skill, run_trial, ARMS, TRIALS_PER_TASK, SEED, ARM_PROMPT_FILES, load_arm_prompt

N_WORKERS = int(os.environ.get("N_WORKERS", "6"))

# ARMS can be overridden via BENCH_ARMS env var (comma-separated arm names)
# This is already handled in run_public_bench.py, but we re-read here for
# clarity in the parallel runner.
_arms_env = os.environ.get("BENCH_ARMS", "")
if _arms_env:
    ARMS = [a.strip() for a in _arms_env.split(",") if a.strip()]


def worker_fn(args):
    """Run a single trial in a worker process."""
    task, arm, trial_idx, skill_prompt = args
    try:
        result = run_trial(task, arm, skill_prompt, trial_idx)
        return result
    except Exception as e:
        return {
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
        }


def main():
    print(f"Loading public benchmarks ({N_WORKERS} workers)...", flush=True)
    tasks = load_tasks()
    print(f"  {len(tasks)} tasks loaded", flush=True)

    skill_prompt = load_skill()

    trial_plan = []
    for task in tasks:
        for arm in ARMS:
            for t in range(TRIALS_PER_TASK):
                trial_plan.append((task, arm, t, skill_prompt))

    rng = random.Random(SEED)
    rng.shuffle(trial_plan)

    total = len(trial_plan)
    print(f"Running {total} trials across {N_WORKERS} workers...", flush=True)

    all_trials = []
    done = 0
    t0 = time.time()

    with ProcessPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(worker_fn, args): i for i, args in enumerate(trial_plan)}
        for fut in as_completed(futures):
            result = fut.result()
            all_trials.append(result)
            done += 1
            if done % 10 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  [{done}/{total}] {result['task_id']} / {result['arm']} / t{result['trial']} "
                      f"passed={result['passed']} out_tok={result['output_tokens']} "
                      f"({rate:.1f}/s, ETA {eta:.0f}s)", flush=True)

    print(f"\nDone in {time.time()-t0:.0f}s. {len(all_trials)} trials collected.", flush=True)

    # Print results table (same as run_public_bench.py)
    from collections import defaultdict
    groups = defaultdict(list)
    for t in all_trials:
        groups[(t["benchmark"], t["arm"])].append(t)

    print("\n=== PAPER RESULTS TABLE ===\n")

    # Dynamic table header: one column per arm
    arm_names = sorted(set(t['arm'] for t in all_trials))
    header_arm_cols = " | ".join(f"{a:>8s}" for a in arm_names)
    pass_arm_cols = " | ".join(f"{a+' pass':>8s}" for a in arm_names)
    print(f"{'benchmark':14s} | {header_arm_cols} | {pass_arm_cols}")
    print("-" * (16 + len(arm_names) * 19))

    for bench in sorted(set(t['benchmark'] for t in all_trials)):
        parts = [f"{bench:14s}"]
        for a in arm_names:
            arm_trials = [t for t in all_trials if t['benchmark']==bench and t['arm']==a]
            cp = sum(1 for x in arm_trials if x['passed'])
            parts.append(f"{cp:>3d}/{len(arm_trials):<4d}" if arm_trials else f"{'--':>8s}")
        for a in arm_names:
            arm_trials = [t for t in all_trials if t['benchmark']==bench and t['arm']==a]
            if arm_trials:
                cp = sum(1 for x in arm_trials if x['passed'])
                parts.append(f"{100*cp/len(arm_trials):>7.0f}%")
            else:
                parts.append(f"{'--':>8s}")
        print(" | ".join(parts))

    # Overall per arm
    print("-" * (16 + len(arm_names) * 19))
    parts = [f"{'OVERALL':14s}"]
    for a in arm_names:
        arm_trials = [t for t in all_trials if t['arm']==a]
        cp = sum(1 for x in arm_trials if x['passed'])
        parts.append(f"{cp:>3d}/{len(arm_trials):<4d}" if arm_trials else f"{'--':>8s}")
    for a in arm_names:
        arm_trials = [t for t in all_trials if t['arm']==a]
        if arm_trials:
            cp = sum(1 for x in arm_trials if x['passed'])
            parts.append(f"{100*cp/len(arm_trials):>7.0f}%")
        else:
            parts.append(f"{'--':>8s}")
    print(" | ".join(parts))

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "public_benchmarks.json", "w") as f:
        json.dump(all_trials, f, indent=2, sort_keys=True)
    print(f"\nResults saved to {results_dir}/public_benchmarks.json")


if __name__ == "__main__":
    main()
