#!/usr/bin/env python3
"""Run public benchmark eval: GSM8K, ARC-Challenge, BBH.

Same ablation design: classic (Q -> answer) vs tahoe (Q + skill -> answer).
Single API call per trial. Numeric/exact graders.

EVALUATION INVARIANT: The grader and answer extraction logic must be IDENTICAL
for both arms. The ONLY difference between arms is the system prompt (TAHOE
thinking skill vs nothing). Never branch grading logic on arm identity.

Usage:
  export TAHOE_API_BASE="https://your-api-endpoint/v1"
  export TAHOE_API_KEY="your-api-key"
  export TAHOE_MODEL="."
  # export SSL_CERT_FILE if your endpoint uses a custom CA
  PYTHONPATH=src python3 benchmarks/run_public_bench.py
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
from metrics import compute_all_metrics, count_typed_refs

from prompt_paths import resolve_prompt

SKILL_PATH = str(resolve_prompt("tahoe"))

# Baseline prompt file paths — each arm maps to a prompt file in benchmarks/
ARM_PROMPT_FILES = {
    "classic": None,  # no system prompt
    "tahoe": "tahoe-93.txt",
    "cot": "cot.txt",
    "cod": "cod.txt",
    "tot": "tot.txt",
    "react": "react.txt",
}

DEFAULT_ARMS = ["classic", "tahoe"]
ALL_ARMS = list(ARM_PROMPT_FILES.keys())

# ARMS is configurable via env var BENCH_ARMS (comma-separated) or defaults to DEFAULT_ARMS
_arms_env = os.environ.get("BENCH_ARMS", "")
if _arms_env:
    ARMS = [a.strip() for a in _arms_env.split(",") if a.strip()]
else:
    ARMS = list(DEFAULT_ARMS)

TRIALS_PER_TASK = 3
SEED = 42
MAX_SAMPLES_PER_BENCH = 10  # 10 samples per benchmark for paper


def load_arm_prompt(arm, prompt_cache=None):
    """Load the system prompt for a given arm.

    Returns the prompt text, or "" if the arm has no prompt file.
    Uses prompt_cache dict if provided to avoid re-reading files.
    """
    if prompt_cache and arm in prompt_cache:
        return prompt_cache[arm]
    prompt_file = ARM_PROMPT_FILES.get(arm)
    if prompt_file is None:
        text = ""
    else:
        from prompt_paths import resolve_prompt
        path = resolve_prompt(prompt_file)
        with open(path) as f:
            text = f.read()
    if prompt_cache is not None:
        prompt_cache[arm] = text
    return text

# MATH grader: extract \boxed{} answer
def grade_math(model_answer, expected_answer):
    """MATH: extract \\boxed{} from both, compare numerically when possible."""
    def extract_boxed(text):
        match = re.search(r'\\boxed\{([^}]+)\}', text)
        return match.group(1).strip() if match else ""
    model_boxed = extract_boxed(model_answer)
    expected_boxed = extract_boxed(expected_answer)
    if not model_boxed:
        # Fallback: last number
        nums = re.findall(r'-?\d+\.?\d*', model_answer)
        model_boxed = nums[-1] if nums else model_answer.strip()[:50]
    if not expected_boxed:
        nums = re.findall(r'-?\d+\.?\d*', expected_answer)
        expected_boxed = nums[-1] if nums else expected_answer.strip()
    # Try numeric comparison
    try:
        return float(model_boxed) == float(expected_boxed), f"expected={expected_boxed}, got={model_boxed}"
    except (ValueError, TypeError):
        return model_boxed == expected_boxed, f"expected={expected_boxed}, got={model_boxed}"

# RACE grader: answer is A/B/C/D
def grade_race(model_answer, expected_answer):
    """RACE: match answer letter (A/B/C/D)."""
    model_letter = re.sub(r'\*+', '', model_answer.strip()).upper()
    expected = expected_answer.strip().upper()
    if len(model_letter) > 1:
        match = re.search(r'\b([A-D])\b', model_letter)
        if match:
            model_letter = match.group(1)
    return model_letter == expected, f"expected={expected}, got={model_letter}"

# MMLU grader: answer is index (0-3), choices are A-D
def grade_mmlu(model_answer, expected_answer, choices=None):
    """MMLU: answer is an index 0-3, model outputs a letter."""
    model_letter = re.sub(r'\*+', '', model_answer.strip()).upper()
    if len(model_letter) > 1:
        match = re.search(r'\b([A-D])\b', model_letter)
        if match:
            model_letter = match.group(1)
    expected_idx = int(expected_answer)
    expected_letter = chr(ord("A") + expected_idx)
    return model_letter == expected_letter, f"expected={expected_letter}, got={model_letter}"


def load_skill():
    """Load the TAHOE skill prompt — backward compat for existing callers."""
    return load_arm_prompt("tahoe")


def extract_gsm8k_gold(answer_text):
    """GSM8K official: extract the number after #### in the gold answer."""
    match = re.search(r'####\s*([\d,]+)', answer_text)
    return match.group(1).replace(',', '') if match else ""


_SEP_NUM_RE = r"-?\d{1,3}(?:[,\u202f ]\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?"


def extract_model_number(text):
    """Extract a number from model output — same for both arms.

    v3 (grader-format fix, arm-agnostic). Priority order:
    1. #### N          (official GSM8K marker)
    2. \\boxed{...}    (nested-brace tolerant)
    3. LAST bold span  (**Answer: $12** / **It takes 5 hours**)
    4. 'answer is N' / 'total = N' (last occurrence)
    5. last separator-aware number
    Handles '1{,}430', '2\\,000', '$2,180', thin spaces. v1 split formatted
    numbers ('1,430' -> '430'); v2 broke on brace-stripping order — both
    under-credited verbose LaTeX answers (the BBH lesson, again).
    """
    text = str(text).strip()
    match = re.search(r"####\s*([\d,]+)", text)
    if match:
        return match.group(1).replace(",", "")
    sep = _SEP_NUM_RE
    boxed = re.search(r"\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}", text)
    if boxed:
        nums = re.findall(sep, boxed.group(1))
        if nums:
            return nums[-1].replace(",", "").replace("\u202f", "")
    norm = (
        text.replace("\\,", "")
        .replace("\\ ", "")
        .replace("\u202f", " ")
        .replace("$", "")
    )
    bolds = re.findall(r"\*\*([^*]+)\*\*", norm)
    if bolds:
        nums = re.findall(sep, bolds[-1])
        if nums:
            return nums[-1].replace(",", "")
    matches = re.findall(
        r"(?:answer|result|total)\s*(?:is|=|:)\s*(" + sep + r")", norm, re.I)
    if matches:
        return matches[-1].replace(",", "")
    nums = re.findall(sep, norm)
    if nums:
        return nums[-1].replace(",", "")
    return norm[:50]


def grade_gsm8k(model_answer, expected_answer):
    """GSM8K: extract number from model output, compare to gold number."""
    model_num = extract_model_number(model_answer)
    expected_num = extract_gsm8k_gold(expected_answer)
    return model_num == expected_num, f"expected={expected_num}, got={model_num}"


def grade_arc(model_answer, expected_answer):
    """ARC: match answerKey (A/B/C/D). Official eval = exact letter match."""
    model_letter = re.sub(r'\*+', '', model_answer.strip()).upper()
    expected = expected_answer.strip().upper()
    if len(model_letter) > 1:
        match = re.search(r'\b([A-D])\b', model_letter)
        if match:
            model_letter = match.group(1)
    return model_letter == expected, f"expected={expected}, got={model_letter}"


def grade_bbh(model_answer, expected_answer):
    """BBH: match the correct option letter. Official eval = letter equality.

    Accepts '(X)', 'X', or any text containing the letter as a word/paren.
    """
    model_clean = re.sub(r'\*+', '', model_answer.strip())
    expected_clean = expected_answer.strip()
    expected_match = re.search(r'\(([A-Z])\)', expected_clean)
    expected_letter = expected_match.group(1) if expected_match else expected_clean

    # 1. (X) pattern
    model_match = re.search(r'\(([A-Z])\)', model_clean)
    if model_match:
        return model_match.group(1) == expected_letter, (
            f"expected={expected_letter}, got={model_match.group(1)}"
        )
    # 2. bare letter
    m = re.search(r'\b([A-Z])\b', model_clean.upper())
    if m:
        return m.group(1) == expected_letter, (
            f"expected={expected_letter}, got={m.group(1)}"
        )
    return model_clean == expected_clean, f"expected={expected_letter}, got={model_clean[:50]}"


def grade_bbh_arith(model_answer, expected_answer):
    """BBH multistep arithmetic: compare final number."""
    model_num = extract_model_number(model_answer)
    expected_num = extract_model_number(expected_answer)
    return model_num == expected_num, f"expected={expected_num}, got={model_num}"


def grade_lsat(model_answer, expected_answer):
    """LSAT: answer is a letter (A-E)."""
    model_letter = re.sub(r'\*+', '', model_answer.strip()).upper()
    expected = expected_answer.strip().upper()
    if len(model_letter) > 1:
        match = re.search(r'\b([A-E])\b', model_letter)
        if match:
            model_letter = match.group(1)
    return model_letter == expected, f"expected={expected}, got={model_letter}"


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

    # BBH — logical deduction 7 objects (hard)
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

    # BBH — tracking shuffled objects 7 (hard — state tracking across shuffles)
    bbh_track = load_dataset('lukaemon/bbh', 'tracking_shuffled_objects_seven_objects', split='test')
    indices = rng.sample(range(len(bbh_track)), MAX_SAMPLES_PER_BENCH)
    for i in indices:
        ex = bbh_track[i]
        tasks.append({
            "task_id": f"bbh-track-{i:04d}",
            "benchmark": "bbh_track",
            "description": f"{ex['input']}\n\nAnswer with the letter of the correct option.",
            "expected": ex["target"],
            "grader": "bbh",
            "difficulty": "hard",
        })

    # BBH — multistep arithmetic (hard — 3+ step computation)
    bbh_arith = load_dataset('lukaemon/bbh', 'multistep_arithmetic_two', split='test')
    indices = rng.sample(range(len(bbh_arith)), MAX_SAMPLES_PER_BENCH)
    for i in indices:
        ex = bbh_arith[i]
        tasks.append({
            "task_id": f"bbh-arith-{i:04d}",
            "benchmark": "bbh_arith",
            "description": f"{ex['input']}\n\nAnswer with just the number.",
            "expected": ex["target"],
            "grader": "bbh_arith",
            "difficulty": "hard",
        })

    # MMLU — college mathematics (hard — university-level math)
    mmlu_math = load_dataset('hails/mmlu_no_train', 'college_mathematics', split='test')
    indices = rng.sample(range(len(mmlu_math)), MAX_SAMPLES_PER_BENCH)
    for i in indices:
        ex = mmlu_math[i]
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

    # MMLU — formal logic (hard — logical reasoning)
    mmlu_logic = load_dataset('hails/mmlu_no_train', 'formal_logic', split='test')
    indices = rng.sample(range(len(mmlu_logic)), MAX_SAMPLES_PER_BENCH)
    for i in indices:
        ex = mmlu_logic[i]
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

    # MMLU — professional accounting (hard — finance reasoning)
    mmlu_acct = load_dataset('hails/mmlu_no_train', 'professional_accounting', split='test')
    indices = rng.sample(range(len(mmlu_acct)), MAX_SAMPLES_PER_BENCH)
    for i in indices:
        ex = mmlu_acct[i]
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

    # LSAT-LR — logical reasoning (hard — law school)
    lsat = load_dataset('hails/agieval-lsat-lr', split="test")
    indices = rng.sample(range(len(lsat)), MAX_SAMPLES_PER_BENCH)
    for i in indices:
        ex = lsat[i]
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

    # RACE — long reading comprehension (hard — 1500+ char passages)
    import ast as _ast
    race = load_dataset("EleutherAI/race", "high", split="test")
    indices = rng.sample(range(len(race)), MAX_SAMPLES_PER_BENCH)
    for i in indices:
        ex = race[i]
        probs = _ast.literal_eval(ex['problems'])
        prob = probs[0]  # Take first question from each article
        choices = "\n".join(f"({chr(ord('A')+j)}) {opt}" for j, opt in enumerate(prob['options']))
        tasks.append({
            "task_id": f"race-{i:04d}",
            "benchmark": "race",
            "description": f"Read the following passage and answer the question.\n\n{ex['article']}\n\nQuestion: {prob['question']}\n\n{choices}\n\nAnswer with just the letter (A, B, C, or D).",
            "expected": prob['answer'],
            "grader": "race",
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
    elif grader == "bbh_arith":
        return grade_bbh_arith(model_answer, task["expected"])
    elif grader == "lsat":
        return grade_lsat(model_answer, task["expected"])
    elif grader == "mmlu":
        return grade_mmlu(model_answer, task["expected"], task.get("choices"))
    elif grader == "math":
        return grade_math(model_answer, task["expected"])
    elif grader == "race":
        return grade_race(model_answer, task["expected"])
    return False, "unknown grader"


def run_trial(task, arm, skill_prompt, trial_idx):
    # Determine system prompt: tahoe arm uses the passed skill_prompt;
    # baseline arms load their own prompt from ARM_PROMPT_FILES.
    if arm == "tahoe":
        system_prompt = skill_prompt
    else:
        system_prompt = load_arm_prompt(arm)
    result = run_classic(
        task_id=f"{task['task_id']}-{arm}-t{trial_idx}",
        task_prompt=task["description"],
        model=os.environ.get("TAHOE_MODEL", "."),
        api_base=os.environ.get("TAHOE_API_BASE", ""),
        api_key=os.environ.get("TAHOE_API_KEY", ""),
        max_turns=1,
        max_tokens=2048,  # increased for hard reasoning tasks
        timeout_seconds=60,
        system_prompt=system_prompt,
    )
    passed, detail = grade_task(task, result.final_answer)

    ref_counts = count_typed_refs(result.final_answer)
    verified_steps = ref_counts["verified_logical_steps"]
    typed_refs = ref_counts["typed_refs_produced"]
    repeated_refs = ref_counts["repeated_refs"]
    retired_refs = ref_counts["retired_refs"]
    total_refs = ref_counts["total_refs_produced"]

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
        "verified_logical_steps": verified_steps,
        "typed_refs_produced": typed_refs,
        "repeated_refs": repeated_refs,
        "retired_refs": retired_refs,
        "total_refs_produced": total_refs,
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
                "verified_logical_steps": 0,
                "typed_refs_produced": 0,
                "repeated_refs": 0,
                "retired_refs": 0,
                "total_refs_produced": 0,
            })

    print("\n=== RESULTS (per benchmark) ===\n")

    # Group by benchmark + arm
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

    # Save
    from outdir import make_run_dir
    results_dir = make_run_dir("public-bench")
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "public_benchmarks.json", "w") as f:
        json.dump(all_trials, f, indent=2, sort_keys=True)

    print(f"\nResults saved to {results_dir}/public_benchmarks.json")


if __name__ == "__main__":
    main()
