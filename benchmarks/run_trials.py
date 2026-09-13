#!/usr/bin/env python3
"""Run the ablation trials: 7 tasks x 3 arms x 5 trials = 105 runs.

Usage:
  export TAHOE_API_BASE="https://api.eliza.yandex.net/raw/internal/v2/models/GLM-5.3-Flash_alexkay28/v1"
  export TAHOE_API_KEY="$(cat ~/.soy/token)"
  export TAHOE_MODEL="."
  export SSL_CERT_FILE=/etc/ssl/certs/yandex-ca.pem
  PYTHONPATH=src python3 eval/run_trials.py
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
from runner_opencode import run as run_opencode
from graders import make_grader
from report import generate_markdown_table, generate_json_report, generate_per_task_comparison

TASK_FILES = [
    "eval/tasks/routing-01.yaml",
    "eval/tasks/routing-02.yaml",
    "eval/tasks/code-fix-01.yaml",
    "eval/tasks/code-fix-02.yaml",
    "eval/tasks/search-01.yaml",
    "eval/tasks/plan-01.yaml",
    "eval/tasks/recover-01.yaml",
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
    grader_type = task["grader"]["type"]
    grader = make_grader(grader_type)
    answer = arm_result.get("final_answer", "")
    passed, detail = grader(answer, task.get("expected_state", {}))
    quality = 1.0 if passed else 0.0
    return passed, quality, detail


def _normalize_tahoe_answer(answer):
    """Extract the actual answer value from TAHOE's JSON wrapper."""
    if not answer:
        return ""
    answer = answer.strip()
    # Try parsing as JSON
    try:
        data = json.loads(answer)
    except (json.JSONDecodeError, ValueError):
        # Not JSON — try extracting a number from prose like "Committed refs: 16"
        import re
        nums = re.findall(r'\b(\d+)\b', answer)
        if nums:
            return nums[-1]  # last number is usually the answer
        return answer
    # Common wrapper patterns
    if isinstance(data, dict):
        for key in ("answer", "result", "value", "output", "report"):
            if key in data:
                val = data[key]
                if isinstance(val, (str, int, float)):
                    return str(val)
                if isinstance(val, dict):
                    for k2 in ("answer", "result", "value"):
                        if k2 in val:
                            return str(val[k2])
                    return json.dumps(val)
        # If it has only one key, return that value
        if len(data) == 1:
            val = list(data.values())[0]
            return str(val) if not isinstance(val, (dict, list)) else json.dumps(val)
        # Look for any numeric value in the dict
        for k, v in data.items():
            if isinstance(v, (int, float)):
                return str(v)
    if isinstance(data, (int, float)):
        return str(data)
    # Fallback: extract last number from string
    import re
    nums = re.findall(r'\b(\d+)\b', answer)
    if nums:
        return nums[-1]
    return answer


def run_classic_arm(task, trial_idx):
    result = run_classic(
        task_id=task["task_id"],
        task_prompt=task["description"],
        model=os.environ.get("TAHOE_MODEL", "."),
        api_base=os.environ.get("TAHOE_API_BASE", ""),
        api_key=os.environ.get("TAHOE_API_KEY", ""),
        max_turns=5,
        max_tokens=512,
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


def run_opencode_arm(task, trial_idx):
    result = run_opencode(
        task_id=task["task_id"],
        task_prompt=task["description"],
        model=os.environ.get("TAHOE_MODEL", "GLM-5.3-Flash_alexkay28/."),
        agent="build",
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        timeout_seconds=120,
    )
    return {
        "task_id": task["task_id"],
        "arm": "opencode",
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
    Same single API call as classic. The only difference is the system prompt
    that teaches the model to structure its reasoning in TAHOE.
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
    "opencode": run_opencode_arm,
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

    results_dir = Path("eval/results")
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
