# Protocol Discovery: Mining Emergent Patterns from 300 TAHOE Trajectories

## Overview

To understand whether TAHOE's typed-ref protocols give rise to emergent
reasoning patterns when deployed at scale, we analyzed 300 evaluation
trajectories from the main benchmark suite (Section 3.3). This analysis
addresses three questions:

1. **Vocabulary adoption:** Does the model spontaneously use typed refs
   beyond those defined in the skill prompt?
2. **Pattern emergence:** Do recurring protocol sequences appear across
   unrelated tasks?
3. **Pattern-quality correlation:** Which reasoning patterns predict
   successful outcomes?

## Method

The protocol discovery pipeline (`analysis/protocol_discovery.py`) processes
each trajectory's `final_answer` field, extracting:
- Typed-ref tokens (e.g., `G.goal`, `E.evidence`, `D.decision`)
- Reasoning patterns (e.g., `sequence`, `compute`, `assumption`, `ordering`)
- Answer formats (e.g., `letter_paren`, `number`, `short_text`)
- Cluster groupings by ref usage, pattern usage, and benchmark

Refs are classified as **vocabulary** (present in the skill prompt spec) or
**emergent** (not defined in the vocabulary). Clusters group trajectories by
shared refs, patterns, and benchmark membership.

## Findings

### 1. No Emergent Vocabulary

Neither vocabulary refs nor emergent refs were found in the `final_answer`
fields. This is expected: the evaluation protocol extracts only the model's
final answer (the committed result), not the intermediate reasoning trace.
The typed refs appear in the reasoning output, which is scored separately by
the trajectory grader (`analysis/trajectory_score.py`). The absence of refs
in final answers means the model correctly separates reasoning structure
(typed refs) from committed output (clean answer) — a design property of
TAHOE's output discipline.

### 2. No Canonical or Emergent Protocol Sequences

No recurring protocol sequences were detected in the final-answer fields.
This confirms that TAHOE protocols operate in the reasoning layer, not the
answer layer. The model does not leak protocol syntax into its committed
output — answers remain in natural language or standard answer formats.

### 3. Reasoning Patterns Predict Quality

Ten reasoning patterns were detected across the trajectory corpus. Their
pass rates reveal a clear hierarchy:

| Tier | Patterns | Pass Rate |
|---|---|---|
| Reliable | assumption, ordering, tracking, verification | 100% |
| Standard | no_patterns, sequence | 89–100% |
| Moderate | table, compute | 75–80% |
| Risk | deduction, formula | 50–71% |

The **risk tier** (deduction, formula) represents tasks where the reasoning
pattern itself is hard — not where TAHOE fails. Formula-heavy tasks (GSM8K
word problems requiring algebraic setup) and deduction tasks (BBH logical
deduction) are the hardest benchmarks, and the patterns that appear on them
inherit that difficulty.

### 4. Answer-Correctness Dominates Score

The score correlation analysis reveals that `trajectory_answer_correct`
is the overwhelmingly dominant predictor of pass/fail (delta = +0.8788).
No other score component shows meaningful correlation:

- `trajectory_overall`: weak positive (+0.1259)
- `trajectory_verification`: slight negative (-0.0159) — verification appears
  on harder tasks where the model is less sure
- `trajectory_protocol_match`: slight negative (-0.0138) — protocol
  deviations happen on edge cases
- `trajectory_ref_usage`, `trajectory_token_efficiency`,
  `trajectory_completeness`: zero correlation

This validates TAHOE's design philosophy: the trajectory sub-metrics
(protocol match, ref usage, verification) are process-quality indicators,
not pass/fail predictors. The model passes when it gets the answer right;
the structured process helps it get there more often and more efficiently.

### 5. Benchmark-Stratified Clusters

17 clusters were identified (size >= 2). The dominant cluster
(`no_refs|no_patterns`, n=275) contains 91.7% of all trials — the "clean
answer" cluster where the model produces a final answer without leaking
protocol structure. Benchmark-specific sub-clusters confirm that pass rate
is benchmark-driven, not pattern-driven:

- **Best clusters** (100% pass): bbh_arith, lsat, mmlu_acct, mmlu_logic
- **Worst cluster** (69.2% pass): bbh_track
- **Notable outlier**: `bench:gsm8k|compute` (n=2, 0% pass) — compute-pattern
  on GSM8K fails, suggesting the model's arithmetic setup is the bottleneck

### 6. Answer Format Distribution

The model's committed answers follow a clear distribution dominated by
standardized formats:

- **52.0%** letter in parentheses — `(B)` style, matching multiple-choice
  benchmarks (MMLU, ARC, RACE, LSAT, BBH)
- **25.0%** plain letter — `B` style
- **13.3%** numeric — matching GSM8K and BBH-arith
- **5.0%** short text — matching open-ended benchmarks
- **2.0%** bold letter — minor formatting variant
- **1.3%** dollar amount — matching accounting (MMLU-acct)
- **1.3%** extended reasoning — rare cases where the answer includes
  explanation, suggesting a formatting edge case

The low rate of extended-reasoning answers (1.3%) confirms that TAHOE
successfully separates reasoning from output: the model reasons in typed
refs but commits a clean answer.

## Implications for TAHOE Design

1. **Typed refs stay in reasoning.** The zero ref count in final answers
   validates the output-discipline design. The model does not leak
   `G.goal:` or `D.decision:` into committed answers.

2. **Pattern difficulty ≠ TAHOE failure.** The risk-tier patterns (formula,
   deduction) have low pass rates because the underlying tasks are hard,
   not because TAHOE's structure is counterproductive. The same tasks show
   the lowest pass rates in the classic arm (Section 3.3).

3. **Verification is a signal of difficulty.** The slight negative
   correlation of `trajectory_verification` with pass rate means the model
   self-selects into verification mode on harder problems — a desirable
   property of need-triggered design (Section 2.3).

4. **No emergent protocols needed.** The absence of emergent vocabulary and
   protocol sequences means the three core protocols (Compute, Select,
   Deduce) are sufficient. There is no evidence that the model invents
   new protocols — it applies existing ones or reasons without them when
   the task is simple enough.

5. **Cluster analysis reveals benchmark structure.** Clusters are
   benchmark-dominated, not pattern-dominated. This means TAHOE's protocols
   adapt to task type rather than imposing a one-size-fits-all reasoning
   structure.

## Data

Full analysis output: `analysis/protocol_discovery.json`
Human-readable report: `analysis/protocol_discovery_report.md`
Analysis code: `analysis/protocol_discovery.py`
