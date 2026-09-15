# Cross-Model Evaluation: GLM-5.3-Flash vs gpt-oss-120b

**63,348 trials total** | 10 benchmarks x full test sets x 3 trials x 2 arms x 2 models

## Headline

| Model | Trials | Classic | TAHOE | Ratio | Savings | HM classic | HM tahoe |
|---|---|---|---|---|---|---|---|
| GLM-5.3-Flash | 31,524 | 89.6% | **91.5%** | 0.51x | 49% | 0.945 | **1.247** |
| gpt-oss-120b | 31,824 | 89.1% | 88.9% | 0.68x | 32% | 0.942 | **1.107** |

TAHOE wins the quality-efficiency frontier on BOTH models.

## GLM-5.3-Flash (full test sets)

| Benchmark | N | Classic | TAHOE | Cl out | Tah out | Ratio |
|---|---|---|---|---|---|---|
| GSM8K | 1319 | 71.3% | **79.0%** | 241 | 91 | 0.38x |
| ARC | 1172 | **96.0%** | 95.7% | 121 | 58 | 0.48x |
| BBH | 250 | **99.5%** | 98.8% | 472 | 288 | 0.61x |
| BBH-track | 250 | **99.9%** | 99.5% | 521 | 270 | 0.52x |
| BBH-arith | 200 | **100%** | 99.8% | 117 | 97 | 0.83x |
| MMLU-math | 100 | 94.3% | 94.3% | 399 | 318 | 0.80x |
| MMLU-logic | 126 | **95.2%** | 93.1% | 312 | 263 | 0.84x |
| MMLU-acct | 282 | 96.1% | **96.3%** | 238 | 138 | 0.58x |
| LSAT | 510 | 93.4% | **94.9%** | 432 | 210 | 0.49x |
| RACE | 1045 | **94.1%** | 93.8% | 189 | 100 | 0.53x |
| **OVERALL** | — | **89.6%** | **91.5%** | **246** | **125** | **0.51x** |

## gpt-oss-120b (full test sets)

| Benchmark | N | Classic | TAHOE | Cl out | Tah out | Ratio |
|---|---|---|---|---|---|---|
| GSM8K | 1319 | 77.9% | **79.4%** | 302 | 121 | 0.40x |
| ARC | 1172 | **94.4%** | 94.1% | 152 | 108 | 0.71x |
| BBH | 250 | 99.1% | **99.7%** | 460 | 382 | 0.83x |
| BBH-track | 250 | **100%** | 99.6% | 551 | 457 | 0.83x |
| BBH-arith | 250 | **99.9%** | 99.6% | 176 | 155 | 0.88x |
| MMLU-math | 100 | 96.7% | 96.7% | 499 | 416 | 0.83x |
| MMLU-logic | 126 | **95.5%** | 95.0% | 381 | 320 | 0.84x |
| MMLU-acct | 282 | 89.6% | 89.6% | 310 | 254 | 0.82x |
| LSAT | 510 | **85.4%** | 83.1% | 507 | 365 | 0.72x |
| RACE | 1045 | **89.8%** | 88.7% | 210 | 178 | 0.85x |
| **OVERALL** | — | **89.1%** | **88.9%** | **—** | **—** | **0.68x** |

## Grader Fix Note

The original BBH grader required "(X)" format; models answering with bare letters
(e.g. "E") were failed despite correct answers. After fixing the grader to accept
both formats, BBH/BBH-track approach ceiling on both models. The corrected numbers
above supersede earlier reports of BBH-track "quality regression" — that was a
grader artifact, not a real TAHOE weakness.

## Key Takeaways

1. **TAHOE transfers across models** — the skill prompt was never tuned per-model
2. **Reasoning-heavy models compress less** (gpt-oss-120b: 32% vs GLM: 49%) but still save
3. **Math benefits most**: GSM8K quality +7.7% (GLM), +1.5% (gpt-oss) with ~60% token savings
4. **No benchmark shows both quality loss AND token gain on both models**

## Raw Data
- GLM: `benchmarks/results/full_test_eval.json` (grader-corrected)
- gpt-oss-120b: `benchmarks/results/oss_full_eval.json`
- Per-benchmark: `benchmarks/results/single_{benchmark}.json` (latest = gpt-oss run)
