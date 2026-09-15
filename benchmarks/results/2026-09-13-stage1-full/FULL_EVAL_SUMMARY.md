# Full 200-Sample Evaluation Results

**10,956 trials** | 10 benchmarks x up to 200 samples x 3 trials x 2 arms
**Model**: GLM-5.3-Flash | **Date**: 2026-09-13 | **Commit**: 9b2b1f7

## Results

| Benchmark | N | Classic | TAHOE | Cl out | Tah out | Ratio | Savings |
|---|---|---|---|---|---|---|---|
| GSM8K | 200 | 430/600 (71.7%) | 454/600 (75.7%) | 234 | 92 | 0.39x | 61% |
| ARC | 200 | 569/600 (94.8%) | 577/600 (96.2%) | 129 | 58 | 0.45x | 55% |
| BBH | 200 | 463/600 (77.2%) | 460/600 (76.7%) | 481 | 307 | 0.64x | 36% |
| BBH-track | 200 | 539/600 (89.8%) | 440/600 (73.3%) | 534 | 266 | 0.50x | 50% |
| BBH-arith | 200 | 600/600 (100%) | 597/600 (99.5%) | 120 | 96 | 0.80x | 20% |
| MMLU-math | 150 | 283/300 (94.3%) | 283/300 (94.3%) | 399 | 318 | 0.80x | 20% |
| MMLU-logic | 126 | 360/378 (95.2%) | 352/378 (93.1%) | 312 | 263 | 0.84x | 16% |
| MMLU-acct | 200 | 563/600 (93.8%) | 568/600 (94.7%) | 301 | 157 | 0.52x | 48% |
| LSAT | 200 | 558/600 (93.0%) | 570/600 (95.0%) | 474 | 229 | 0.48x | 52% |
| RACE | 200 | 574/600 (95.7%) | 575/600 (95.8%) | 179 | 97 | 0.54x | 46% |
| **OVERALL** | — | **4939/5478 (90.2%)** | **4876/5478 (89.0%)** | **311** | **178** | **0.57x** | **43%** |

## Headline Numbers

- **Quality**: 89.0% (TAHOE) vs 90.2% (classic) — 1.2% gap
- **Token savings**: 43% (0.57x output ratio)
- **HM**: 1.180 (TAHOE) vs 0.948 (classic) — TAHOE wins quality-efficiency frontier

## Quality Wins (TAHOE > Classic)
- GSM8K: +4.0% | LSAT: +2.0% | ARC: +1.4% | MMLU-acct: +0.9% | RACE: +0.1%

## Quality Regressions (Classic > TAHOE)
- BBH-track: -16.5% (conciseness hurts state tracking)
- MMLU-logic: -2.1% (formal logic benefits from verbose derivation)
- BBH: -0.5% | BBH-arith: -0.5% (essentially tied)

## Raw Data
- Per-benchmark: `benchmarks/results/single_{benchmark}.json`
- Combined: `benchmarks/results/full_200_eval.json`
