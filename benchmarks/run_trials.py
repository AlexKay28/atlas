#!/usr/bin/env python3
"""Run the ablation trials: 7 tasks x 2 arms x 5 trials = 70 runs.

EVALUATION INVARIANT: The grader and answer extraction logic must be IDENTICAL
for both arms. The ONLY difference between arms is the system prompt (TAHOE
thinking skill vs nothing). Never branch grading logic on arm identity.

Usage:
  export TAHOE_API_BASE="https://your-api-endpoint/v1"
  export TAHOE_API_KEY="your-api-key"
  export TAHOE_MODEL="."
  # export SSL_CERT_FILE if your endpoint uses a custom CA
  PYTHONPATH=src python3 benchmarks/run_trials.py
"""

import json
import os
import random
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from runner_classic import run as run_classic
from graders import make_grader
from report import generate_markdown_table, generate_json_report, generate_per_task_comparison

TASK_FILES = [
    "benchmarks/tasks/routing-01.yaml",
    "benchmarks/tasks/routing-02.yaml",
    "benchmarks/tasks/code-fix-01.yaml",
    "benchmarks/tasks/code-fix-02.yaml",
    "benchmarks/tasks/search-01.yaml",
    "benchmarks/tasks/plan-01.yaml",
    "benchmarks/tasks/recover-01.yaml",
]

ARMS = ["classic", "tahoe"]
TRIALS_PER_ARM = 5
SEED = 42


def load_tasks():
    import yaml
    tasks = {}
    for path in TASK_FILES:
        with open(path) as f:
            t = yaml.safe_load(f)
        tasks[t["task_id"]] = t
    return tasks


def grade_trial(task, arm_result):
    """Grade a trial. Same logic for both arms — no arm-dependent behavior."""
    grader_type = task["grader"]["type"]
    grader = make_grader(grader_type)
    answer = arm_result.get("final_answer", "")
    passed, detail = grader(answer, task.get("expected_state", {}))
    quality = 1.0 if passed else 0.0
    return passed, quality, detail


def run_classic_arm(task, trial_idx):
    result = run_classic(
        task_id=task["task_id"],
        task_prompt=task["description"],
        model=os.environ.get("TAHOE_MODEL", "."),
        api_base=os.environ.get("TAHOE_API_BASE", ""),
        api_key=os.environ.get("TAHOE_API_KEY", ""),
        max_turns=1,
        max_tokens=1024,
        timeout_seconds=60,
    )
    return {
        "task_id": task["task_id"],
        "arm": "classic",
        "trial": trial_idx,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "wall_seconds": result.wall_seconds,
        "passed": result.passed,
        "failure_class": result.failure_class,
        "authoring_tokens": 0,
        "final_answer": result.final_answer,
    }


def run_tahoe_arm(task, trial_idx):
    """TAHOE arm: classic + TAHOE thinking skill as system prompt.

    Q + tahoe_skill -> {thinking*tahoe} answer
    Same single API call, same parameters as classic. The ONLY difference
    is the system prompt that teaches the model to structure its reasoning.
    """
    skill_prompt_path = os.path.join(os.path.dirname(__file__), "tahoe_skill_prompt.txt")
    with open(skill_prompt_path) as f:
        system_prompt = f.read()

    result = run_classic(
        task_id=task["task_id"],
        task_prompt=task["description"],
        model=os.environ.get("TAHOE_MODEL", "."),
        api_base=os.environ.get("TAHOE_API_BASE", ""),
        api_key=os.environ.get("TAHOE_API_KEY", ""),
        max_turns=1,
        max_tokens=1024,
        timeout_seconds=60,
        system_prompt=system_prompt,
    )
    return {
        "task_id": task["task_id"],
        "arm": "tahoe",
        "trial": trial_idx,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "wall_seconds": result.wall_seconds,
        "passed": result.passed,
        "failure_class": result.failure_class,
        "authoring_tokens": 0,
        "final_answer": result.final_answer,
    }


ARM_RUNNERS = {
    "classic": run_classic_arm,
    "tahoe": run_tahoe_arm,
}


def main():
    print("Loading tasks...")
    tasks = load_tasks()
    print(f"  {len(tasks)} tasks loaded")

    all_trials = []
    trial_plan = []
    for task_id in tasks:
        for arm in ARMS:
            for t in range(TRIALS_PER_ARM):
                trial_plan.append((task_id, arm, t))

    rng = random.Random(SEED)
    rng.shuffle(trial_plan)

    print(f"Running {len(trial_plan)} trials (shuffled, seed={SEED})...")
    for i, (task_id, arm, trial_idx) in enumerate(trial_plan):
        task = tasks[task_id]
        print(f"  [{i+1}/{len(trial_plan)}] {task_id} / {arm} / trial {trial_idx} ...", end=" ", flush=True)
        try:
            result = ARM_RUNNERS[arm](task, trial_idx)
            passed, quality, detail = grade_trial(task, result)
            result["passed"] = passed
            result["quality_score"] = quality
            result["grader_detail"] = detail
            all_trials.append(result)
            print(f"passed={passed} tokens={result['total_tokens']} wall={result['wall_seconds']:.1f}s")
        except Exception as exc:
            print(f"ERROR: {exc}")
            traceback.print_exc()
            all_trials.append({
                "task_id": task_id,
                "arm": arm,
                "trial": trial_idx,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "wall_seconds": 0.0,
                "passed": False,
                "failure_class": "runner_error",
                "authoring_tokens": 0,
                "final_answer": f"ERROR: {exc}",
                "quality_score": 0.0,
                "grader_detail": str(exc),
            })

    print("\n=== RESULTS ===\n")
    print(generate_markdown_table(all_trials))
    print()
    print(generate_per_task_comparison(all_trials))

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "trials.json", "w") as f:
        json.dump(all_trials, f, indent=2, sort_keys=True)
    with open(results_dir / "report.json", "w") as f:
        f.write(generate_json_report(all_trials))
    with open(results_dir / "report.md", "w") as f:
        f.write("# Ablation results — GLM-5.3-Flash\n\n")
        f.write(generate_markdown_table(all_trials))
        f.write("\n\n")
        f.write(generate_per_task_comparison(all_trials))

    print(f"\nResults saved to {results_dir}/")


if __name__ == "__main__":
    main()
