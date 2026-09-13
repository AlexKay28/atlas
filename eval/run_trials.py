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

ARMS = ["classic", "opencode", "tahoe"]
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
    from tahoe.syntax import parse_program
    from tahoe.runtime import EventStore, SequentialCoordinator
    from tahoe.runtime.coordinator import DeterministicWorker
    from tahoe.worker_adapter import make_worker

    program_source = task.get("program_source", "")
    if not program_source.strip():
        return {
            "task_id": task["task_id"],
            "arm": "tahoe",
            "trial": trial_idx,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "wall_seconds": 0.0,
            "passed": False,
            "failure_class": "no_program",
            "authoring_tokens": 0,
            "final_answer": "",
        }

    started = time.monotonic()
    try:
        program = parse_program(program_source)
        store = EventStore()
        api_base = os.environ.get("TAHOE_API_BASE", "")
        api_key = os.environ.get("TAHOE_API_KEY", "")
        if api_base and api_key:
            worker = make_worker(1, api_base=api_base, api_key=api_key,
                                 model=os.environ.get("TAHOE_MODEL", "."))
        else:
            worker = DeterministicWorker()
        coordinator = SequentialCoordinator(store=store, worker=worker)
        run_id = f"ablation-{task['task_id']}-t{trial_idx}"
        coordinator.execute(program, run_id=run_id)
        events = store.events
        final_answer = ""
        for ev in reversed(events):
            if ev.get("kind") == "step_result":
                final_answer = str(ev.get("payload", {}).get("result", ""))
                break

        input_tokens = 0
        output_tokens = 0
        for ev in events:
            usage = ev.get("payload", {}).get("receipt", {}).get("usage", {})
            if usage:
                input_tokens += usage.get("input_tokens", 0) or 0
                output_tokens += usage.get("output_tokens", 0) or 0

        return {
            "task_id": task["task_id"],
            "arm": "tahoe",
            "trial": trial_idx,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "wall_seconds": time.monotonic() - started,
            "passed": True,
            "failure_class": "none",
            "authoring_tokens": 0,
            "final_answer": final_answer,
        }
    except Exception as exc:
        return {
            "task_id": task["task_id"],
            "arm": "tahoe",
            "trial": trial_idx,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "wall_seconds": time.monotonic() - started,
            "passed": False,
            "failure_class": "error",
            "authoring_tokens": 0,
            "final_answer": f"ERROR: {exc}",
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
