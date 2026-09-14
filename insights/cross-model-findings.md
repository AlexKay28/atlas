# Cross-Model Findings: GLM-5.3-Flash vs gpt-oss-120b

> 63,348 trials, full test sets, 10 benchmarks, 3 trials/sample, 2 arms.
> Frozen eval protocol. Dated 2026-09-14. Commit 0645918.

## Headline

| Model | Trials | Classic | TAHOE | Token ratio | Savings | HM classic | HM tahoe |
|---|---|---|---|---|---|---|---|
| GLM-5.3-Flash | 31,524 | 89.6% | **91.5%** (+1.9%) | 0.51x | 49% | 0.945 | **1.247** |
| gpt-oss-120b | 31,824 | 89.1% | 88.9% (−0.2%) | 0.68x | 32% | 0.942 | **1.107** |

TAHOE wins the quality-efficiency frontier on BOTH models. The 93-token skill
transfers with zero per-model tuning.

## Per-benchmark (GLM)

| Benchmark | N | Classic | TAHOE | Ratio |
|---|---|---|---|---|
| GSM8K | 1319 | 71.3% | **79.0%** | 0.38x |
| ARC | 1172 | **96.0%** | 95.7% | 0.48x |
| BBH | 250 | **99.5%** | 98.8% | 0.61x |
| BBH-track | 250 | **99.9%** | 99.5% | 0.52x |
| BBH-arith | 200 | **100%** | 99.8% | 0.83x |
| MMLU-math | 100 | 94.3% | 94.3% | 0.80x |
| MMLU-logic | 126 | **95.2%** | 93.1% | 0.84x |
| MMLU-acct | 282 | 96.1% | **96.3%** | 0.58x |
| LSAT | 510 | 93.4% | **94.9%** | 0.49x |
| RACE | 1045 | **94.1%** | 93.8% | 0.53x |

(gpt-oss full table: benchmarks/results/CROSS_MODEL_EVAL.md)

## Key findings

1. **Math benefits most from structure.** GSM8K: +7.7% quality (GLM) / +1.5%
   (gpt-oss) with ~60% token savings. Typed Compute protocol maps directly.
2. **Reasoning-native models compress less.** gpt-oss-120b is a reasoning model —
   its free-form CoT is already lean, so TAHOE saves 32% vs GLM's 49%.
   **Interpretation: internalized reasoning (RL-trained CoT) and external
   reasoning protocols partially substitute.** As models internalize more,
   single-shot protocol advantage shrinks — but long-horizon state management
   (Stage 2/3 territory) remains.
3. **Token savings are universal**: 12-62% across all 20 model-benchmark pairs.
   Never negative.
4. **No benchmark shows both quality loss AND token gain on both models.**
   The only real regression class: state-tracking (BBH-track pre-grader-fix was
   an artifact; MMLU-logic −2.1% is real but small).

## Practical infrastructure notes (gpt-oss-120b on Eliza)

- Endpoint: `https://api.eliza.yandex.net/raw/internal/gpt-oss-120b/v1` (NO /v2!)
- Reasoning model: thinking arrives in `reasoning`/`reasoning_content`, answer
  in `content`; rate-limited calls return EMPTY content with 0 tokens.
- Pool quota: **5 inflight per model family** — 60 parallel workers cause 429
  thrashing. Solution: sequential benchmark chain, 5 workers, retry with
  exponential backoff + empty-answer retry in worker_fn (run_single_bench.py).
- GLM endpoint: `.../raw/internal/v2/models/GLM-5.3-Flash_alexkay28/v1` (HAS /v2).
