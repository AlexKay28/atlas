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

from run_public_bench import load_tasks, load_skill, run_trial, ARMS, TRIALS_PER_TASK, SEED

N_WORKERS = int(os.environ.get("N_WORKERS", "6"))


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
    print(f"{'benchmark':14s} | {'classic':>8s} | {'tahoe':>8s} | {'cl out':>7s} | {'tah out':>7s} | {'ratio':>5s} | {'cl pass':>7s} | {'tah pass':>8s}")
    print("-" * 85)

    for bench in sorted(set(t['benchmark'] for t in all_trials)):
        c = [t for t in all_trials if t['benchmark']==bench and t['arm']=='classic']
        ta = [t for t in all_trials if t['benchmark']==bench and t['arm']=='tahoe']
        cp = sum(1 for x in c if x['passed'])
        tp = sum(1 for x in ta if x['passed'])
        co = sum(x['output_tokens'] for x in c) / len(c) if c else 0
        to = sum(x['output_tokens'] for x in ta) / len(ta) if ta else 0
        ratio = f"{to/co:.2f}x" if co > 0 else "N/A"
        print(f"{bench:14s} | {cp:>3d}/{len(c):<4d} | {tp:>3d}/{len(ta):<4d} | {co:>7.0f} | {to:>7.0f} | {ratio:>5s} | {100*cp/len(c):>6.0f}% | {100*tp/len(ta):>7.0f}%")

    ac = [t for t in all_trials if t['arm']=='classic']
    at = [t for t in all_trials if t['arm']=='tahoe']
    cp = sum(1 for t in ac if t['passed'])
    tp = sum(1 for t in at if t['passed'])
    co = sum(t['output_tokens'] for t in ac)
    to = sum(t['output_tokens'] for t in at)
    qc = cp / len(ac)
    qt = tp / len(at)
    eff = co / to if to > 0 else 0
    hm_c = 2 * qc / (qc + 1)
    hm_t = 2 * qt * eff / (qt + eff) if (qt + eff) > 0 else 0

    print("-" * 85)
    print(f"{'OVERALL':14s} | {cp:>3d}/{len(ac):<4d} | {tp:>3d}/{len(at):<4d} | {co//len(ac):>7.0f} | {to//len(at):>7.0f} | {to/co:>4.2f}x | {100*qc:>6.0f}% | {100*qt:>7.0f}%")
    print(f"\nClassic: quality={qc:.3f} output_tokens={co} HM={hm_c:.3f}")
    print(f"Tahoe:   quality={qt:.3f} output_tokens={to} HM={hm_t:.3f} ratio={1/eff:.2f}x")
    print(f"TAHOE saves {100*(1-to/co):.0f}% reasoning tokens")
    print(f"HM winner: {'TAHOE' if hm_t > hm_c else 'classic'}")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "public_benchmarks.json", "w") as f:
        json.dump(all_trials, f, indent=2, sort_keys=True)
    print(f"\nResults saved to {results_dir}/public_benchmarks.json")


if __name__ == "__main__":
    main()
