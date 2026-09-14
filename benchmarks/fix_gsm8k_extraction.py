#!/usr/bin/env python3
"""Fix GSM8K answer extraction: LaTeX artifacts + thousands separators.

The old extractor (last plain `[-?\\d+]+`) split comma/LaTeX-formatted numbers
('1{,}430', '2\\,000', '$2,180' -> '430'/'000'/'180'), under-crediting verbose
LaTeX answers. This v2 extractor is arm-agnostic (same function for all arms)
and mirrors common eval-harness handling: #### -> boxed -> bold/'Answer:' ->
last separator-aware number.

Re-grades stored final_answers in place for: skill_cmp_gsm8k.json,
full_test_eval.json (gsm8k subset), single_gsm8k.json.
"""

import json
import re
from pathlib import Path

_SEP_NUM = r"-?\d{1,3}(?:[,\u202f ]\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?"


def extract_model_number_v2(text: str) -> str:
    text = str(text).strip()
    # 1. official #### marker
    m = re.search(r"####\s*([\d,]+)", text)
    if m:
        return m.group(1).replace(",", "")
    # normalize LaTeX/formatting artifacts (keep digits + separators)
    norm = (
        text.replace("\\,", "")
        .replace("\\ ", "")
        .replace("\u202f", " ")
        .replace("{", "")
        .replace("}", "")
        .replace("$", "")
        .replace("\\$", "")
        .replace("\\text", "")
        .replace("\\$", "")
    )
    norm = re.sub(r"\*\*", "", norm)
    # 2. boxed answer
    m = re.search(r"\\boxed\{([^}]*)\}", norm)
    if m:
        nums = re.findall(_SEP_NUM, m.group(1))
        if nums:
            return nums[-1].replace(",", "").replace("\u202f", "")
    # 3. bold / 'Answer:' patterns
    m = re.search(r"(?:answer|total|raised|costs?|paid|takes?)\s*[:=]?\s*(" + _SEP_NUM + r")", norm, re.I)
    if m:
        return m.group(1).replace(",", "").replace("\u202f", "")
    m = re.search(r"\*{2}[^*]*?(" + _SEP_NUM + r")[^*]*?\*{2}", norm)
    if m:
        return m.group(1).replace(",", "").replace("\u202f", "")
    # 4. last separator-aware number
    nums = re.findall(_SEP_NUM, norm)
    if nums:
        return nums[-1].replace(",", "").replace("\u202f", "")
    return norm[:50]


def grade_with_v2(final_answer: str, grader_detail: str) -> bool | None:
    """Re-grade using expected from the stored grader_detail."""
    m = re.search(r"expected=([-\d,\.]+)", grader_detail)
    if not m:
        return None
    expected = m.group(1).replace(",", "")
    got = extract_model_number_v2(final_answer)
    try:
        return abs(float(got) - float(expected)) < 1e-6
    except ValueError:
        return got == expected


def main():
    targets = [
        Path("benchmarks/results/skill_cmp_gsm8k.json"),
        Path("benchmarks/results/full_test_eval.json"),
        Path("benchmarks/results/single_gsm8k.json"),
    ]
    for path in targets:
        if not path.exists():
            continue
        trials = json.load(open(path))
        changed = 0
        scanned = 0
        for t in trials:
            if t.get("benchmark") != "gsm8k":
                continue
            scanned += 1
            new_passed = grade_with_v2(t.get("final_answer", ""), t.get("grader_detail", ""))
            if new_passed is None:
                continue
            if bool(new_passed) != bool(t["passed"]):
                changed += 1
                t["passed"] = bool(new_passed)
                t["quality_score"] = 1.0 if new_passed else 0.0
                t["failure_class"] = "none" if new_passed else "wrong_answer"
        with open(path, "w") as f:
            json.dump(trials, f, indent=2, sort_keys=True)
        print(f"{path.name}: scanned {scanned} gsm8k trials, re-graded {changed}")

    # corrected summary per source
    print("\n=== CORRECTED gsm8k numbers ===")
    trials = json.load(open("benchmarks/results/skill_cmp_gsm8k.json"))
    for arm in ("classic", "skill_prompt", "triz_implicit"):
        at = [t for t in trials if t["arm"] == arm]
        p = sum(1 for t in at if t["passed"])
        o = sum(t["output_tokens"] for t in at) / len(at)
        print(f"  {arm:14s}: {p}/{len(at)} ({100*p/len(at):.1f}%), avg out {o:.0f}")

    trials = json.load(open("benchmarks/results/full_test_eval.json"))
    for arm in ("classic", "tahoe"):
        at = [t for t in trials if t.get("benchmark") == "gsm8k" and t["arm"] == arm]
        if at:
            p = sum(1 for t in at if t["passed"])
            print(f"  Stage-1 {arm:10s}: {p}/{len(at)} ({100*p/len(at):.1f}%)")


if __name__ == "__main__":
    main()
