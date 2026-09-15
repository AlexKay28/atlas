#!/usr/bin/env python3
"""Compare N skill prompts (single-call arms) on one benchmark.

Usage: PYTHONPATH=src python3 benchmarks/run_skill_compare.py <bench> <n> <skill1> <skill2> ...
Skills are file paths under benchmarks/. Arm "classic" = no prompt.
Env: N_WORKERS.
"""
import json, os, sys, time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_public_bench import grade_task
from run_single_bench import load_single_benchmark
from runner_classic import run as run_classic


def load_skills(names):
    from prompt_paths import resolve_prompt, PROMPT_FILES
    arms = [("classic", "")]
    for n in names:
        path = resolve_prompt(n)
        label = n.replace("tahoe_", "").replace(".txt", "").replace("_skill", "").replace("triz-implicit-", "triz-")
        arms.append((PROMPT_FILES.get(n, label), path.read_text()))
    return arms


def _worker(args):
    task, arm, prompt = args
    max_retries = 5
    for attempt in range(max_retries):
        t0 = time.time()
        try:
            r = run_classic(
                task_id=task["task_id"], task_prompt=task["description"],
                model=os.environ.get("TAHOE_MODEL", "."), api_base=os.environ.get("TAHOE_API_BASE", ""),
                api_key=os.environ.get("TAHOE_API_KEY", ""), max_turns=1, max_tokens=2048,
                timeout_seconds=60, system_prompt=prompt,
                extra_body={"reasoning_effort": os.environ.get("ARM_EFFORT", "")} if os.environ.get("ARM_EFFORT") else None,
            )
            # retry on rate-limit symptoms: empty answer with 0 tokens
            if r.output_tokens == 0 and not r.final_answer.strip() and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            passed, detail = grade_task(task, r.final_answer)
            return {"task_id": task["task_id"], "benchmark": task["benchmark"], "arm": arm,
                    "passed": passed, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                    "wall_seconds": time.time() - t0, "final_answer": r.final_answer,
                    "grader_detail": detail}
        except Exception as e:
            msg = str(e)
            if ("429" in msg or "inflight" in msg or "rate" in msg.lower()) and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"task_id": task["task_id"], "benchmark": task["benchmark"], "arm": arm,
                    "passed": False, "input_tokens": 0, "output_tokens": 0,
                    "wall_seconds": time.time() - t0, "final_answer": f"ERROR: {e}",
                    "grader_detail": msg}
    return {"task_id": task["task_id"], "benchmark": task["benchmark"], "arm": arm,
            "passed": False, "input_tokens": 0, "output_tokens": 0, "wall_seconds": 0.0,
            "final_answer": "ERROR: retries exhausted", "grader_detail": "rate limited"}


def main():
    bench = sys.argv[1] if len(sys.argv) > 1 else "gsm8k"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    skills = sys.argv[3:] if len(sys.argv) > 3 else ["tahoe-93.txt", "triz-implicit.txt"]
    workers = int(os.environ.get("N_WORKERS", "6"))

    tasks = load_single_benchmark(bench, n)
    arms = load_skills(skills)
    plan = [(t, a, p) for t in tasks for a, p in arms]
    print(f"{bench}: {len(tasks)} tasks x {len(arms)} arms = {len(plan)} trials", flush=True)

    trials, done, t0 = [], 0, time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_worker, a) for a in plan]
        for f in as_completed(futs):
            trials.append(f.result()); done += 1
            if done % 25 == 0 or done == len(plan):
                print(f"  [{done}/{len(plan)}] {done/(time.time()-t0):.1f}/s", flush=True)

    print(f"\n=== {bench}: SKILL COMPARISON ===\n")
    print(f"{'arm':12s} | {'pass':>10s} | {'in tok':>7s} | {'out tok':>7s} | {'tok/task':>8s}")
    print("-" * 58)
    stats = {}
    for arm, _ in arms:
        at = [t for t in trials if t["arm"] == arm]
        if not at: continue
        p = sum(1 for t in at if t["passed"])
        i = sum(t["input_tokens"] for t in at) / len(at)
        o = sum(t["output_tokens"] for t in at) / len(at)
        stats[arm] = {"pass": p/len(at), "out": o, "in": i, "n": len(at)}
        print(f"{arm:12s} | {p:>4d}/{len(at):<5d} | {i:>7.0f} | {o:>7.0f} | {(i+o):>8.0f}")

    base = stats.get("classic")
    for arm, s in stats.items():
        if arm == "classic" or not base: continue
        print(f"\n{arm} vs classic: quality {100*(s['pass']-base['pass']):+.1f}pp, "
              f"output tokens {s['out']/base['out']:.2f}x" if base['out'] else "")
        if "triz" in arm and "skill_prompt" not in str(arms):
            pass
    # tahoe vs triz direct
    if "triz" in stats and "skill_prompt" in stats:
        t, s = stats["skill_prompt"], stats["triz"]
        print(f"triz vs tahoe:   quality {100*(s['pass']-t['pass']):+.1f}pp, out tokens {s['out']/t['out']:.2f}x")

    from outdir import make_run_dir
    out_dir = make_run_dir(f"skill-cmp-{bench}")
    out_file = out_dir / "trials.json"
    with open(out_file, "w") as f:
        json.dump(trials, f, indent=2)
    print(f"\nSaved to {out_file}")


if __name__ == "__main__":
    main()
