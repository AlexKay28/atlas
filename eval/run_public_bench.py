#!/usr/bin/env python3
"""Run public benchmark eval: GSM8K, ARC-Challenge, BBH.

Same ablation design: classic (Q -> answer) vs tahoe (Q + skill -> answer).
Single API call per trial. Numeric/exact graders.

Usage:
  export TAHOE_API_BASE="https://api.eliza.yandex.net/raw/internal/v2/models/GLM-5.3-Flash_alexkay28/v1"
  export TAHOE_API_KEY="$(cat ~/.soy/token)"
  export TAHOE_MODEL="."
  export SSL_CERT_FILE=/etc/ssl/certs/yandex-ca.pem
  PYTHONPATH=src python3 eval/run_public_bench.py
"""

import json
import os
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from runner_classic import run as run_classic
from report import generate_markdown_table, generate_json_report, generate_per_task_comparison

SKILL_PATH = os.path.join(os.path.dirname(__file__), "tahoe_skill_prompt.txt")
ARMS = ["classic", "tahoe"]
TRIALS_PER_TASK = 3
SEED = 42
MAX_SAMPLES_PER_BENCH = 10  # 10 samples per benchmark for pilot


def load_skill():
    with open(SKILL_PATH) as f:
        return f.read()


def extract_gsm8k_answer(text):
    """Extract the final number from a GSM8K answer."""
    # GSM8K answers end with #### <number>
    match = re.search(r'####\s*([\d,]+)', text)
    if match:
        return match.group(1).replace(',', '')
    # Fallback: last number in text
    nums = re.findall(r'-?\d+', text)
    return nums[-1] if nums else ""


def extract_model_number(text):
    """Extract a number from model output."""
    text = text.strip()
    # Try to find #### pattern first
    match = re.search(r'####\s*([\d,]+)', text)
    if match:
        return match.group(1).replace(',', '')
    # Try "answer is X"
    match = re.search(r'(?:answer|result)\s*(?:is|=)\s*([\d,]+)', text, re.I)
    if match:
        return match.group(1).replace(',', '')
    # Last number
    nums = re.findall(r'-?\d+', text)
    return nums[-1] if nums else text


def grade_gsm8k(model_answer, expected_answer):
    model_num = extract_model_number(model_answer)
    expected_num = extract_gsm8k_answer(expected_answer)
    return model_num == expected_num, f"expected={expected_num}, got={model_num}"


def grade_arc(model_answer, expected_answer):
    """ARC: answer is a letter (A/B/C/D)."""
    model_answer = model_answer.strip().upper()
    expected = expected_answer.strip().upper()
    # Extract first letter if model gives a longer answer
    if len(model_answer) > 1:
        match = re.search(r'\b([A-D])\b', model_answer)
        if match:
            model_answer = match.group(1)
    return model_answer == expected, f"expected={expected}, got={model_answer}"


def grade_bbh(model_answer, expected_answer):
    """BBH: answer is like (D) or a word."""
    model_answer = model_answer.strip()
    expected = expected_answer.strip()
    # Extract letter from (X) format
    match = re.search(r'\(([A-Z])\)', model_answer)
    if match:
        model_answer = match.group(1)
    match = re.search(r'\(([A-Z])\)', expected)
    if match:
        expected = match.group(1)
    return model_answer.upper() == expected.upper(), f"expected={expected}, got={model_answer}"


def load_tasks():
    """Load tasks from 3 public benchmarks."""
    from datasets import load_dataset
    tasks = []

    # GSM8K — grade school math word problems
    gsm8k = load_dataset('gsm8k', 'main', split='test')
    rng = random.Random(SEED)
    indices = rng.sample(range(len(gsm8k)), MAX_SAMPLES_PER_BENCH)
    for i in indices:
        ex = gsm8k[i]
        tasks.append({
            "task_id": f"gsm8k-{i:04d}",
            "benchmark": "gsm8k",
            "description": ex["question"],
            "expected": ex["answer"],
            "grader": "gsm8k",
            "difficulty": "medium",
        })

    # ARC-Challenge — science multiple choice
    arc = load_dataset('allenai/ai2_arc', 'ARC-Challenge', split='test')
    indices = rng.sample(range(len(arc)), MAX_SAMPLES_PER_BENCH)
    for i in indices:
        ex = arc[i]
        choices = " ".join(f"({k}) {v}" for k, v in zip(ex["choices"]["label"], ex["choices"]["text"]))
        tasks.append({
            "task_id": f"arc-{i:04d}",
            "benchmark": "arc",
            "description": f"{ex['question']}\n\nChoices: {choices}\n\nAnswer with just the letter (A, B, C, or D).",
            "expected": ex["answerKey"],
            "grader": "arc",
            "difficulty": "hard",
        })

    # BBH — logical deduction
    bbh = load_dataset('lukaemon/bbh', 'logical_deduction_seven_objects', split='test')
    indices = rng.sample(range(len(bbh)), MAX_SAMPLES_PER_BENCH)
    for i in indices:
        ex = bbh[i]
        tasks.append({
            "task_id": f"bbh-{i:04d}",
            "benchmark": "bbh",
            "description": f"{ex['input']}\n\nAnswer with the letter of the correct option.",
            "expected": ex["target"],
            "grader": "bbh",
            "difficulty": "hard",
        })

    return tasks


def grade_task(task, model_answer):
    grader = task["grader"]
    if grader == "gsm8k":
        return grade_gsm8k(model_answer, task["expected"])
    elif grader == "arc":
        return grade_arc(model_answer, task["expected"])
    elif grader == "bbh":
        return grade_bbh(model_answer, task["expected"])
    return False, "unknown grader"


def run_trial(task, arm, skill_prompt, trial_idx):
    system_prompt = skill_prompt if arm == "tahoe" else ""
    result = run_classic(
        task_id=f"{task['task_id']}-{arm}-t{trial_idx}",
        task_prompt=task["description"],
        model=os.environ.get("TAHOE_MODEL", "."),
        api_base=os.environ.get("TAHOE_API_BASE", ""),
        api_key=os.environ.get("TAHOE_API_KEY", ""),
        max_turns=1,
        max_tokens=1024,
        timeout_seconds=60,
        system_prompt=system_prompt,
    )
    passed, detail = grade_task(task, result.final_answer)
    return {
        "task_id": task["task_id"],
        "benchmark": task["benchmark"],
        "arm": arm,
        "trial": trial_idx,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "wall_seconds": result.wall_seconds,
        "passed": passed,
        "failure_class": "none" if passed else "wrong_answer",
        "authoring_tokens": 0,
        "final_answer": result.final_answer,
        "quality_score": 1.0 if passed else 0.0,
        "grader_detail": detail,
    }


def main():
    print("Loading public benchmarks...")
    tasks = load_tasks()
    print(f"  {len(tasks)} tasks loaded ({MAX_SAMPLES_PER_BENCH} per benchmark x 3 benchmarks)")

    skill_prompt = load_skill()

    trial_plan = []
    for task in tasks:
        for arm in ARMS:
            for t in range(TRIALS_PER_TASK):
                trial_plan.append((task, arm, t))

    rng = random.Random(SEED)
    rng.shuffle(trial_plan)

    print(f"Running {len(trial_plan)} trials (shuffled, seed={SEED})...")
    all_trials = []
    for i, (task, arm, trial_idx) in enumerate(trial_plan):
        print(f"  [{i+1}/{len(trial_plan)}] {task['task_id']} / {arm} / t{trial_idx} ...", end=" ", flush=True)
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
            })

    print("\n=== RESULTS (per benchmark) ===\n")

    # Group by benchmark + arm
    from collections import defaultdict
    groups = defaultdict(list)
    for t in all_trials:
        groups[(t["benchmark"], t["arm"])].append(t)

    print("| benchmark | arm | trials | pass_rate | mean_tokens | mean_wall |")
    print("|---|---|---|---|---|---|")
    for (bench, arm) in sorted(groups):
        trials = groups[(bench, arm)]
        passed = sum(1 for t in trials if t["passed"])
        mean_tokens = sum(t["total_tokens"] for t in trials) / len(trials)
        mean_wall = sum(t["wall_seconds"] for t in trials) / len(trials)
        print(f"| {bench} | {arm} | {len(trials)} | {passed}/{len(trials)} ({100*passed/len(trials):.0f}%) | {mean_tokens:.0f} | {mean_wall:.1f}s |")

    # Save
    results_dir = Path("eval/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "public_benchmarks.json", "w") as f:
        json.dump(all_trials, f, indent=2, sort_keys=True)

    print(f"\nResults saved to {results_dir}/public_benchmarks.json")


if __name__ == "__main__":
    main()
