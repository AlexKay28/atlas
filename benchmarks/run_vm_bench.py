#!/usr/bin/env python3
"""Stage-2 pilot: 3-arm ablation — classic vs prompt-tahoe vs TAHOE-VM.

Token gates (insights/token-economics.md):
  GATE 1: VM output tokens <= prompt-tahoe output tokens on >= 2 of 3 benches
  GATE 2: VM context growth O(refs) — implicit: each subcall carries only the
          ref slice; measured here as llm_input_tokens vs classic's re-sent context

Usage (GLM-5.3-Flash via Eliza, as in all prior evals):
  export TAHOE_API_BASE=... TAHOE_API_KEY=... TAHOE_MODEL="."
  PYTHONPATH=src python3 benchmarks/run_vm_bench.py gsm8k 30
"""

import json
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_public_bench import grade_task, load_skill
from run_single_bench import load_single_benchmark
from runner_classic import run as run_classic
from tahoe.vm_mode import VMExecutor

ARMS = ("classic", "tahoe", "vm")
TRIALS_PER_TASK = 1  # VM is deterministic-ish per program; pilot budget-friendly
SEED = 42


def vm_call_model(system: str, user: str, max_tokens: int, effort: str = ""):
    """Adapter: VM subcalls ride the same endpoint as the other arms.

    Step subcalls are trivial queries — reasoning_effort=low cuts the
    thinking burn (verified: 30 -> 6 completion tokens on trivial queries).
    """
    extra = {"reasoning_effort": effort} if effort else None
    result = run_classic(
        task_id="vm-subcall",
        task_prompt=user,
        model=os.environ.get("TAHOE_MODEL", "."),
        api_base=os.environ.get("TAHOE_API_BASE", ""),
        api_key=os.environ.get("TAHOE_API_KEY", ""),
        max_turns=1,
        max_tokens=max_tokens,
        timeout_seconds=90,
        system_prompt=system,
        extra_body=extra,
    )
    return result.final_answer, result.input_tokens, result.output_tokens


def run_trial(task: dict, arm: str, skill_prompt: str) -> dict:
    t0 = time.time()
    try:
        if arm == "vm":
            executor = VMExecutor(vm_call_model)
            vm = executor.run(task["task_id"], task["description"])
            model_answer = vm.final_answer
            trial = {
                "task_id": task["task_id"],
                "benchmark": task["benchmark"],
                "arm": arm,
                "trial": 0,
                "input_tokens": vm.llm_input_tokens,
                "output_tokens": vm.llm_output_tokens,
                "total_tokens": vm.total_tokens,
                "wall_seconds": vm.wall_seconds,
                "passed": False,
                "failure_class": "none",
                "final_answer": model_answer,
                "quality_score": 0.0,
                "grader_detail": "",
                "vm_ok": vm.ok,
                "vm_error": vm.error,
                "compile_attempts": vm.compile_attempts,
                "deterministic_steps": vm.deterministic_steps,
                "llm_steps": vm.llm_steps,
                "steps": [s.to_dict() for s in vm.steps],
                "program": vm.program_text[:2000],
            }
            if not vm.ok:
                trial["failure_class"] = "vm_error"
        else:
            result = run_classic(
                task_id=task["task_id"],
                task_prompt=task["description"],
                model=os.environ.get("TAHOE_MODEL", "."),
                api_base=os.environ.get("TAHOE_API_BASE", ""),
                api_key=os.environ.get("TAHOE_API_KEY", ""),
                max_turns=1,
                max_tokens=2048,
                timeout_seconds=60,
                system_prompt=skill_prompt if arm == "tahoe" else "",
            )
            model_answer = result.final_answer
            trial = {
                "task_id": task["task_id"],
                "benchmark": task["benchmark"],
                "arm": arm,
                "trial": 0,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
                "wall_seconds": result.wall_seconds,
                "passed": False,
                "failure_class": "none",
                "final_answer": model_answer,
                "quality_score": 0.0,
                "grader_detail": "",
            }
        passed, detail = grade_task(task, model_answer)
        trial["passed"] = passed
        trial["grader_detail"] = detail
        trial["quality_score"] = 1.0 if passed else 0.0
        return trial
    except Exception as exc:
        return {
            "task_id": task["task_id"], "benchmark": task["benchmark"],
            "arm": arm, "trial": 0, "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "wall_seconds": time.time() - t0,
            "passed": False, "failure_class": "error",
            "final_answer": f"ERROR: {exc}", "quality_score": 0.0,
            "grader_detail": str(exc),
        }


def _worker(args):
    task, arm, skill_prompt = args
    return run_trial(task, arm, skill_prompt)


def main():
    bench_name = sys.argv[1] if len(sys.argv) > 1 else "gsm8k"
    n_samples = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    n_workers = int(os.environ.get("N_WORKERS", "5"))

    print(f"Loading {bench_name} ({n_samples} samples, 3 arms)...", flush=True)
    tasks = load_single_benchmark(bench_name, n_samples)
    skill_prompt = load_skill()

    plan = [(task, arm, skill_prompt) for task in tasks for arm in ARMS]
    print(f"Running {len(plan)} trials across {n_workers} workers...", flush=True)

    trials = []
    done = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = [pool.submit(_worker, args) for args in plan]
        for fut in as_completed(futures):
            trials.append(fut.result())
            done += 1
            if done % 10 == 0 or done == len(plan):
                rate = done / (time.time() - t0)
                print(f"  [{done}/{len(plan)}] ({rate:.1f}/s)", flush=True)

    # ---- results table ----
    print(f"\n=== {bench_name} — 3-ARM PILOT ===\n")
    print(f"{'arm':10s} | {'pass':>10s} | {'in tok':>7s} | {'out tok':>7s} | {'wall s':>7s}")
    print("-" * 55)
    stats = {}
    for arm in ARMS:
        arm_trials = [t for t in trials if t["arm"] == arm]
        if not arm_trials:
            continue
        passed = sum(1 for t in arm_trials if t["passed"])
        in_tok = sum(t["input_tokens"] for t in arm_trials) / len(arm_trials)
        out_tok = sum(t["output_tokens"] for t in arm_trials) / len(arm_trials)
        wall = sum(t["wall_seconds"] for t in arm_trials) / len(arm_trials)
        stats[arm] = {"pass_rate": passed / len(arm_trials), "in": in_tok, "out": out_tok}
        print(f"{arm:10s} | {passed:>4d}/{len(arm_trials):<5d} | {in_tok:>7.0f} | {out_tok:>7.0f} | {wall:>7.1f}")

    # ---- gates ----
    print("\n=== TOKEN GATES (insights/token-economics.md) ===")
    if "vm" in stats and "tahoe" in stats:
        ratio = stats["vm"]["out"] / stats["tahoe"]["out"] if stats["tahoe"]["out"] else float("inf")
        print(f"  VM/tahoe output-token ratio: {ratio:.2f}x  (gate: <= 1.00x)")
        print(f"  VM/tahoe quality: {stats['vm']['pass_rate']:.3f} vs {stats['tahoe']['pass_rate']:.3f}")
    if "vm" in stats and "classic" in stats:
        in_ratio = stats["vm"]["in"] / stats["classic"]["in"] if stats["classic"]["in"] else float("inf")
        print(f"  VM/classic input-token ratio: {in_ratio:.2f}x (context growth proxy)")

    vm_trials = [t for t in trials if t["arm"] == "vm"]
    vm_ok = sum(1 for t in vm_trials if t.get("vm_ok"))
    if vm_trials:
        print(f"  VM episodes ok: {vm_ok}/{len(vm_trials)}; "
              f"deterministic steps: {sum(t.get('deterministic_steps', 0) for t in vm_trials)}; "
              f"llm steps: {sum(t.get('llm_steps', 0) for t in vm_trials)}")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_file = results_dir / f"vm_pilot_{bench_name}.json"
    with open(out_file, "w") as f:
        json.dump(trials, f, indent=2, sort_keys=True)
    print(f"\nSaved to {out_file}")


if __name__ == "__main__":
    main()
