#!/usr/bin/env python3
"""Run a single benchmark at scale — 200 samples x 3 trials x 2 arms in parallel.

Usage:
  export TAHOE_API_BASE=...
  export TAHOE_API_KEY=...
  PYTHONPATH=src python3 benchmarks/run_single_bench.py <benchmark_name> <n_samples> > /tmp/bench_<name>.log 2>&1

Results saved to benchmarks/results/single_<benchmark_name>.json
"""

import json
import os
import random
import sys
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_public_bench import (
    load_skill, run_trial, grade_task, ARMS, TRIALS_PER_TASK, SEED,
    extract_gsm8k_gold, extract_model_number, grade_gsm8k, grade_arc,
    grade_bbh, grade_bbh_arith, grade_lsat, grade_mmlu, grade_race,
)
from metrics import count_typed_refs

N_WORKERS = int(os.environ.get("N_WORKERS", "6"))


def load_single_benchmark(bench_name, n_samples):
    """Load tasks for a single benchmark."""
    from datasets import load_dataset
    rng = random.Random(SEED)
    tasks = []

    if bench_name == "gsm8k":
        ds = load_dataset('gsm8k', 'main', split='test')
        indices = rng.sample(range(len(ds)), min(n_samples, len(ds)))
        for i in indices:
            ex = ds[i]
            tasks.append({
                "task_id": f"gsm8k-{i:04d}",
                "benchmark": "gsm8k",
                "description": ex["question"],
                "expected": ex["answer"],
                "grader": "gsm8k",
                "difficulty": "medium",
            })
    elif bench_name == "arc":
        ds = load_dataset('allenai/ai2_arc', 'ARC-Challenge', split='test')
        indices = rng.sample(range(len(ds)), min(n_samples, len(ds)))
        for i in indices:
            ex = ds[i]
            choices = " ".join(f"({k}) {v}" for k, v in zip(ex["choices"]["label"], ex["choices"]["text"]))
            tasks.append({
                "task_id": f"arc-{i:04d}",
                "benchmark": "arc",
                "description": f"{ex['question']}\n\nChoices: {choices}\n\nAnswer with just the letter (A, B, C, or D).",
                "expected": ex["answerKey"],
                "grader": "arc",
                "difficulty": "hard",
            })
    elif bench_name == "bbh":
        ds = load_dataset('lukaemon/bbh', 'logical_deduction_seven_objects', split='test')
        indices = rng.sample(range(len(ds)), min(n_samples, len(ds)))
        for i in indices:
            ex = ds[i]
            tasks.append({
                "task_id": f"bbh-{i:04d}",
                "benchmark": "bbh",
                "description": f"{ex['input']}\n\nAnswer with the letter of the correct option.",
                "expected": ex["target"],
                "grader": "bbh",
                "difficulty": "hard",
            })
    elif bench_name == "bbh_track":
        ds = load_dataset('lukaemon/bbh', 'tracking_shuffled_objects_seven_objects', split='test')
        indices = rng.sample(range(len(ds)), min(n_samples, len(ds)))
        for i in indices:
            ex = ds[i]
            tasks.append({
                "task_id": f"bbh-track-{i:04d}",
                "benchmark": "bbh_track",
                "description": f"{ex['input']}\n\nAnswer with the letter of the correct option.",
                "expected": ex["target"],
                "grader": "bbh",
                "difficulty": "hard",
            })
    elif bench_name == "bbh_arith":
        ds = load_dataset('lukaemon/bbh', 'multistep_arithmetic_two', split='test')
        indices = rng.sample(range(len(ds)), min(n_samples, len(ds)))
        for i in indices:
            ex = ds[i]
            tasks.append({
                "task_id": f"bbh-arith-{i:04d}",
                "benchmark": "bbh_arith",
                "description": f"{ex['input']}\n\nAnswer with just the number.",
                "expected": ex["target"],
                "grader": "bbh_arith",
                "difficulty": "hard",
            })
    elif bench_name == "mmlu_math":
        ds = load_dataset('hails/mmlu_no_train', 'college_mathematics', split='test')
        indices = rng.sample(range(len(ds)), min(n_samples, len(ds)))
        for i in indices:
            ex = ds[i]
            choices = "\n".join(f"({chr(ord('A')+j)}) {c}" for j, c in enumerate(ex["choices"]))
            tasks.append({
                "task_id": f"mmlu-math-{i:04d}",
                "benchmark": "mmlu_math",
                "description": f"{ex['question']}\n\n{choices}\n\nAnswer with just the letter (A, B, C, or D).",
                "expected": str(ex["answer"]),
                "choices": ex["choices"],
                "grader": "mmlu",
                "difficulty": "hard",
            })
    elif bench_name == "mmlu_logic":
        ds = load_dataset('hails/mmlu_no_train', 'formal_logic', split='test')
        indices = rng.sample(range(len(ds)), min(n_samples, len(ds)))
        for i in indices:
            ex = ds[i]
            choices = "\n".join(f"({chr(ord('A')+j)}) {c}" for j, c in enumerate(ex["choices"]))
            tasks.append({
                "task_id": f"mmlu-logic-{i:04d}",
                "benchmark": "mmlu_logic",
                "description": f"{ex['question']}\n\n{choices}\n\nAnswer with just the letter (A, B, C, or D).",
                "expected": str(ex["answer"]),
                "choices": ex["choices"],
                "grader": "mmlu",
                "difficulty": "hard",
            })
    elif bench_name == "mmlu_acct":
        ds = load_dataset('hails/mmlu_no_train', 'professional_accounting', split='test')
        indices = rng.sample(range(len(ds)), min(n_samples, len(ds)))
        for i in indices:
            ex = ds[i]
            choices = "\n".join(f"({chr(ord('A')+j)}) {c}" for j, c in enumerate(ex["choices"]))
            tasks.append({
                "task_id": f"mmlu-acct-{i:04d}",
                "benchmark": "mmlu_acct",
                "description": f"{ex['question']}\n\n{choices}\n\nAnswer with just the letter (A, B, C, or D).",
                "expected": str(ex["answer"]),
                "choices": ex["choices"],
                "grader": "mmlu",
                "difficulty": "hard",
            })
    elif bench_name == "lsat":
        ds = load_dataset('hails/agieval-lsat-lr', split="test")
        indices = rng.sample(range(len(ds)), min(n_samples, len(ds)))
        for i in indices:
            ex = ds[i]
            choices = "\n".join(ex["choices"])
            gold_idx = ex["gold"][0] if isinstance(ex["gold"], list) else ex["gold"]
            gold_letter = chr(ord("A") + gold_idx)
            tasks.append({
                "task_id": f"lsat-{i:04d}",
                "benchmark": "lsat",
                "description": f"{ex['query']}\n\n{choices}\n\nAnswer with just the letter (A, B, C, D, or E).",
                "expected": gold_letter,
                "grader": "lsat",
                "difficulty": "hard",
            })
    elif bench_name == "race":
        import ast as _ast
        ds = load_dataset("EleutherAI/race", "high", split="test")
        indices = rng.sample(range(len(ds)), min(n_samples, len(ds)))
        for i in indices:
            ex = ds[i]
            probs = _ast.literal_eval(ex['problems'])
            prob = probs[0]
            choices = "\n".join(f"({chr(ord('A')+j)}) {opt}" for j, opt in enumerate(prob['options']))
            tasks.append({
                "task_id": f"race-{i:04d}",
                "benchmark": "race",
                "description": f"Read the following passage and answer the question.\n\n{ex['article']}\n\nQuestion: {prob['question']}\n\n{choices}\n\nAnswer with just the letter (A, B, C, or D).",
                "expected": prob['answer'],
                "grader": "race",
                "difficulty": "hard",
            })
    else:
        raise ValueError(f"Unknown benchmark: {bench_name}")

    return tasks


def worker_fn(args):
    task, arm, trial_idx, skill_prompt = args
    try:
        result = run_trial(task, arm, skill_prompt, trial_idx)
        return result
    except Exception as e:
        return {
            "task_id": task["task_id"], "benchmark": task["benchmark"],
            "arm": arm, "trial": trial_idx,
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "wall_seconds": 0.0, "passed": False, "failure_class": "error",
            "final_answer": f"ERROR: {e}", "quality_score": 0.0,
            "grader_detail": str(e),
            "verified_logical_steps": 0, "typed_refs_produced": 0,
            "repeated_refs": 0, "retired_refs": 0, "total_refs_produced": 0,
        }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_single_bench.py <benchmark_name> [n_samples]")
        sys.exit(1)

    bench_name = sys.argv[1]
    n_samples = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    if str(sys.argv[2]) == "all":
        n_samples = 999999  # will be capped by dataset size

    print(f"Loading {bench_name} ({n_samples} samples)...", flush=True)
    tasks = load_single_benchmark(bench_name, n_samples)
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
            if done % 50 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  [{done}/{total}] {result['task_id']} / {result['arm']} / t{result['trial']} "
                      f"passed={result['passed']} out_tok={result['output_tokens']} "
                      f"({rate:.1f}/s, ETA {eta:.0f}s)", flush=True)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s. {len(all_trials)} trials collected.", flush=True)

    # Results table
    c = [t for t in all_trials if t['arm'] == 'classic']
    ta = [t for t in all_trials if t['arm'] == 'tahoe']
    cp = sum(1 for x in c if x['passed'])
    tp = sum(1 for x in ta if x['passed'])
    co = sum(x['output_tokens'] for x in c) / len(c) if c else 0
    to = sum(x['output_tokens'] for x in ta) / len(ta) if ta else 0
    ratio = f"{to/co:.2f}x" if co > 0 else "N/A"

    print(f"\n{'benchmark':14s} | {'classic':>8s} | {'tahoe':>8s} | {'cl out':>7s} | {'tah out':>7s} | {'ratio':>5s}")
    print("-" * 65)
    print(f"{bench_name:14s} | {cp:>4d}/{len(c):<4d} | {tp:>4d}/{len(ta):<4d} | {co:>7.0f} | {to:>7.0f} | {ratio:>5s}")
    print(f"  Classic: {100*cp/len(c):.1f}% pass, {co:.0f} avg out tokens")
    print(f"  Tahoe:   {100*tp/len(ta):.1f}% pass, {to:.0f} avg out tokens")
    print(f"  Token savings: {100*(1-to/co):.0f}%" if co > 0 else "")

    # Save
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_file = results_dir / f"single_{bench_name}.json"
    with open(out_file, "w") as f:
        json.dump(all_trials, f, indent=2, sort_keys=True)
    print(f"\nResults saved to {out_file}", flush=True)


if __name__ == "__main__":
    main()
