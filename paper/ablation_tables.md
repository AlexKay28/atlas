# Appendix A: Ablation Tables

## Table A1: Prompt Size Ablation

System prompt varied across four token budgets (50, 93, 150, 200) to measure
the effect of skill-prompt length on pass rate and token efficiency. The 93-token
variant is the default TAHOE skill prompt used in all main results.

| Prompt Size | Pass Rate | Avg Output Tokens | Token Ratio vs Classic | Notes |
|---|---|---|---|---|
| 50 tokens (minimal) | — | — | — | Placeholder — pending #89 ablation results |
| 93 tokens (default) | 89.0% | 200 | 0.60x | Main eval configuration |
| 150 tokens (extended) | — | — | — | Placeholder — pending #89 ablation results |
| 200 tokens (full spec) | — | — | — | Placeholder — pending #89 ablation results |

> **Note:** Full ablation data from issue #89 will populate the placeholder rows.
> The 93-token row reflects the main evaluation (Table 1 in Section 3.3).

---

## Table A2: E1 Notation Efficiency

Token cost of expressing equivalent reasoning snippets across three notation
styles. Ten snippets span five categories: arithmetic, logical deduction,
planning, selection, and multi-step reasoning.

| Snippet ID | Category | Description | Verbose English | TAHOE Typed Refs | Minimal Symbols |
|---|---|---|---|---|---|
| arith_1 | arithmetic | Add two numbers and check parity | 18 | 15 | 9 |
| arith_2 | arithmetic | Multiply and compare to threshold | 21 | 22 | 13 |
| logic_1 | logical_deduction | Modus ponens | 15 | 27 | 21 |
| logic_2 | logical_deduction | Contrapositive reasoning | 21 | 26 | 15 |
| plan_1 | planning | Two-step plan with dependency | 25 | 26 | 12 |
| plan_2 | planning | Conditional branching plan | 25 | 34 | 15 |
| select_1 | selection | Choose the maximum of three values | 23 | 30 | 19 |
| select_2 | selection | Filter a list by predicate | 18 | 26 | 12 |
| multi_1 | multi_step_reasoning | Transitive dependency chain | 31 | 37 | 22 |
| multi_2 | multi_step_reasoning | Iterative refinement until convergence | 27 | 45 | 23 |
| **Total** | | | **224** | **288** | **161** |
| **Average** | | | **22.4** | **28.8** | **16.1** |

### Notation Ratios (relative to verbose English)

| Notation Style | Total Tokens | Ratio vs Verbose | Interpretation |
|---|---|---|---|
| Verbose English | 224 | 1.00x | Baseline |
| TAHOE Typed Refs | 288 | 1.29x | Overhead from ref-typing |
| Minimal Symbols | 161 | 0.72x | Compression from symbolic notation |

**Finding:** TAHOE typed refs carry a 29% notation overhead vs verbose English
because typed-ref prefixes (G., E., D., etc.) add tokens per line. However,
minimal-symbol notation (without ref types) achieves 28% compression. The
typed-ref overhead buys correctness enforcement: refs prevent silent
substitution of assumptions for facts (see Section 2.1). The token savings
observed in the main evaluation (40% fewer output tokens) come from structural
compression of the reasoning itself, not from the notation alone.

---

## Table A3: Protocol Discovery Summary

Analysis of 300 TAHOE evaluation trajectories mining for emergent protocol
patterns, vocabulary adoption, and reasoning-pattern correlations.

### Overall

| Metric | Value |
|---|---|
| Trials analyzed | 300 |
| Passed | 267 |
| Failed | 33 |
| Pass rate | 89.0% |
| Vocabulary refs found | 0 |
| Emergent refs (outside vocabulary) | 0 |
| Canonical protocol sequences | 0 |
| Emergent protocol sequences | 0 |

### Benchmark Pass Rates (sorted descending)

| Benchmark | Pass Rate |
|---|---|
| mmlu_acct | 100.0% |
| mmlu_logic | 100.0% |
| bbh_arith | 100.0% |
| lsat | 100.0% |
| mmlu_math | 90.0% |
| arc | 86.7% |
| race | 80.0% |
| bbh | 80.0% |
| gsm8k | 80.0% |
| bbh_track | 73.3% |

### Reasoning Pattern Pass Rates

| Pattern | Trials | Pass Rate | Interpretation |
|---|---|---|---|
| assumption | 3 | 100.0% | Explicit assumption tracking |
| ordering | 2+ | 100.0% | Spatial/temporal ordering |
| tracking | 2+ | 100.0% | State tracking |
| verification | 2+ | 100.0% | Self-verification step |
| no_patterns | 275 | 89.5% | No detectable pattern |
| sequence | 3 | 88.9% | Sequential reasoning |
| table | 2+ | 80.0% | Tabular layout |
| compute | 3 | 75.0% | Arithmetic computation |
| deduction | 2+ | 71.4% | Logical deduction |
| formula | 2+ | 50.0% | Formula application |

### Score Correlation (passed_mean - failed_mean)

| Score Component | Delta | Interpretation |
|---|---|---|
| trajectory_answer_correct | +0.8788 | Dominant predictor of pass |
| trajectory_overall | +0.1259 | Weak positive correlation |
| trajectory_verification | -0.0159 | Slight negative (verification on harder tasks) |
| trajectory_protocol_match | -0.0138 | Slight negative (protocol deviations on harder tasks) |
| trajectory_ref_usage | 0.0000 | No correlation |
| trajectory_token_efficiency | 0.0000 | No correlation |
| trajectory_completeness | 0.0000 | No correlation |

### Cluster Summary (size >= 2)

| Cluster | Size | Pass Rate | Mean Score | Common Patterns |
|---|---|---|---|---|
| no_refs\|no_patterns | 275 | 89.5% | 0.285 | — |
| bench:race\|no_patterns | 30 | 80.0% | 0.270 | — |
| bench:arc\|no_patterns | 30 | 86.7% | 0.280 | — |
| bench:bbh_arith\|no_patterns | 30 | 100.0% | 0.300 | — |
| bench:lsat\|no_patterns | 30 | 100.0% | 0.300 | — |
| bench:mmlu_acct\|no_patterns | 28 | 100.0% | 0.300 | — |
| bench:mmlu_logic\|no_patterns | 27 | 100.0% | 0.300 | — |
| bench:gsm8k\|no_patterns | 27 | 85.2% | 0.286 | — |
| bench:bbh_track\|no_patterns | 26 | 69.2% | 0.254 | — |
| bench:bbh\|no_patterns | 25 | 80.0% | 0.271 | — |
| bench:mmlu_math\|no_patterns | 22 | 90.9% | 0.286 | — |
| no_refs\|sequence | 3 | 100.0% | 0.340 | sequence |
| no_refs\|assumption | 3 | 100.0% | 0.310 | assumption |
| no_refs\|compute | 3 | 33.3% | 0.339 | compute |
| no_refs\|ordering+sequence | 2 | 100.0% | 0.350 | sequence, ordering |
| bench:mmlu_acct\|assumption | 2 | 100.0% | 0.314 | assumption |
| bench:gsm8k\|compute | 2 | 0.0% | 0.359 | compute |
| bench:bbh\|ordering+sequence | 2 | 100.0% | 0.350 | sequence, ordering |

### Answer Format Distribution

| Format | Count | Share |
|---|---|---|
| letter_paren | 156 | 52.0% |
| letter_plain | 75 | 25.0% |
| number | 40 | 13.3% |
| short_text | 15 | 5.0% |
| letter_bold | 6 | 2.0% |
| dollar | 4 | 1.3% |
| extended_reasoning | 4 | 1.3% |

---

## Table A4: Baseline Comparison

Comparison of TAHOE against established reasoning frameworks across the same
benchmark suite. All baselines use the same model (GLM-5.3-Flash) and identical
evaluation protocol (Section 3.1).

| Method | Overall Pass Rate | Avg Output Tokens | Token Ratio vs Classic | Key Difference |
|---|---|---|---|---|
| Classic (no prompt) | 88.0% | 335 | 1.00x | Baseline free-form CoT |
| **TAHOE** | **89.0%** | **200** | **0.60x** | Typed-ref protocols as thinking skill |
| Chain-of-Thought (CoT) | — | — | — | Placeholder — pending #75 results |
| Chain-of-Draft (CoD) | — | — | — | Placeholder — pending #75 results |
| Tree of Thoughts (ToT) | — | — | — | Placeholder — pending #75 results |
| ReAct | — | — | — | Placeholder — pending #75 results |

> **Note:** Full baseline comparison data from issue #75 will populate the
> placeholder rows. The Classic and TAHOE rows reflect the main evaluation
> (Section 3.3).
