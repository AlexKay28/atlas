# Grader Lessons: Eval Integrity From the BBH Bug

> Discovered 2026-09-14 during the gpt-oss-120b run. Commit 0645918.

## What happened

The BBH grader only accepted answers in `"(X)"` format:

```python
# OLD (buggy): exact format match
model_match = re.search(r'\(([A-Z])\)', model_clean)
expected_match = re.search(r'\(([A-Z])\)', expected_clean)
if model_match and expected_match:
    return model_match.group(1) == expected_match.group(1)
if model_match:                                  # bare letter vs (E) expected
    ...
return model_clean == expected_clean             # "E" == "(E)" → False!
```

Models answering correctly with a bare letter (`E`) were failed. gpt-oss-120b's
classic arm prefers bare-letter output → classic scored **1.1% on BBH** —
an absurd artifact, not a real capability signal.

## The damage it caused (before detection)

- GLM full-test-set run reported BBH classic at 78.1% and BBH-track classic at
  89.7%, and a dramatic "TAHOE regression" on BBH-track (−13.8%).
- After fixing the grader and re-grading stored answers offline:
  BBH classic **99.5%**, BBH-track classic **99.9%** — the "regression"
  VANISHED entirely. It was a grader artifact, not a model behavior.
- Earlier eval rounds inherited the same bias (600-trial and 200-sample runs).

## How it was found

Cross-model replication: gpt-oss-120b scored near-zero on BBH classic while
GLM scored 78% — an inconsistency impossible for a real capability difference.
Format-level inspection of `final_answer` fields showed bare letters failing
exact-match against `"(E)"` targets.

## The rules this buys

1. **Graders must accept every reasonable answer format** for the task:
   parenthesized, bare letter, letter-in-text, numeric variants. Write graders
   against the UNION of output formats your model population produces.
2. **Test graders against actual model output distributions** before trusting
   cross-arm comparisons — run the grader over a handful of raw model answers
   from EACH arm first.
3. **Cross-model inconsistency is a grader alarm.** If model A scores 78% and
   model B scores 1% where both are competent, suspect the grader before the
   model.
4. **Store `final_answer` + `grader_detail` per trial.** It enabled offline
   re-grading of 31,524 stored trials without re-running a single API call.
   Raw-answer persistence is what made the fix cheap.
5. **Never branch grading logic on arm identity** (frozen invariant held —
   the bug was in the shared grader, not arm-dependent logic).

## Current grader (fixed)

```python
# NEW: accepts "(X)", bare "X", or letter-as-word in text
model_match = re.search(r'\(([A-Z])\)', model_clean)
if model_match: ...
m = re.search(r'\b([A-Z])\b', model_clean.upper())
if m: return m.group(1) == expected_letter
```

Applied in run_public_bench.py `grade_bbh`; stored GLM results re-graded in
benchmarks/results/2026-09-13-stage1-full/full_test_eval.json.
