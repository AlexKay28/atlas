# Protocol Discovery Report

**Trials analyzed:** 300  
**Passed:** 267 | **Failed:** 33  
**Pass rate:** 89.0%

## Refs Found

- **Vocabulary refs (in skill prompt):** (none)
- **Emergent refs (not in vocabulary):** (none)
- **All refs:** (none)

## Benchmark Pass Rates

| Benchmark | Pass Rate |
|-----------|-----------|
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

## Reasoning Pattern Pass Rates

| Pattern | Pass Rate |
|---------|-----------|
| assumption | 100.0% |
| ordering | 100.0% |
| tracking | 100.0% |
| verification | 100.0% |
| no_patterns | 89.5% |
| sequence | 88.9% |
| table | 80.0% |
| compute | 75.0% |
| deduction | 71.4% |
| formula | 50.0% |

## Score Correlation (passed_mean - failed_mean)

| Component | Delta |
|-----------|-------|
| trajectory_overall | +0.1259 |
| trajectory_protocol_match | -0.0138 |
| trajectory_ref_usage | +0.0000 |
| trajectory_verification | -0.0159 |
| trajectory_token_efficiency | +0.0000 |
| trajectory_completeness | +0.0000 |
| trajectory_answer_correct | +0.8788 |

## Protocol Sequences

No canonical protocol sequences found in final_answer fields.

## Emergent Sequences

No emergent protocol sequences found.

## Clusters (size >= 2)

| Cluster | Size | Pass Rate | Mean Score | Common Patterns |
|---------|------|-----------|------------|-----------------|
| no_refs|no_patterns | 275 | 89.5% | 0.285 |  |
| bench:race|no_patterns | 30 | 80.0% | 0.270 |  |
| bench:arc|no_patterns | 30 | 86.7% | 0.280 |  |
| bench:bbh_arith|no_patterns | 30 | 100.0% | 0.300 |  |
| bench:lsat|no_patterns | 30 | 100.0% | 0.300 |  |
| bench:mmlu_acct|no_patterns | 28 | 100.0% | 0.300 |  |
| bench:mmlu_logic|no_patterns | 27 | 100.0% | 0.300 |  |
| bench:gsm8k|no_patterns | 27 | 85.2% | 0.286 |  |
| bench:bbh_track|no_patterns | 26 | 69.2% | 0.254 |  |
| bench:bbh|no_patterns | 25 | 80.0% | 0.271 |  |
| bench:mmlu_math|no_patterns | 22 | 90.9% | 0.286 |  |
| no_refs|sequence | 3 | 100.0% | 0.340 | sequence |
| no_refs|assumption | 3 | 100.0% | 0.309 | assumption |
| no_refs|compute | 3 | 33.3% | 0.339 | compute |
| no_refs|ordering+sequence | 2 | 100.0% | 0.350 | sequence, ordering |
| bench:mmlu_acct|assumption | 2 | 100.0% | 0.314 | assumption |
| bench:gsm8k|compute | 2 | 0.0% | 0.359 | compute |
| bench:bbh|ordering+sequence | 2 | 100.0% | 0.350 | sequence, ordering |

## Answer Format Distribution

| Format | Count |
|--------|-------|
| letter_paren | 156 |
| letter_plain | 75 |
| number | 40 |
| short_text | 15 |
| letter_bold | 6 |
| dollar | 4 |
| extended_reasoning | 4 |

## Key Findings

1. **Pass rate:** 89.0% across 300 trials
2. **No emergent refs** — all refs found are within the skill vocabulary
3. **Most predictive score component:** trajectory_answer_correct (delta=+0.8788)
4. **Best benchmark:** mmlu_acct (100.0%)
5. **Worst benchmark:** bbh_track (73.3%)
