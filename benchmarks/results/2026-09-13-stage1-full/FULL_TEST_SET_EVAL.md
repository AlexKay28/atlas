# Full Test Set Evaluation Results

**31,524 trials** | 10 benchmarks x full test sets x 3 trials x 2 arms
**Model**: GLM-5.3-Flash | **Date**: 2026-09-14 | **Commit**: pending

## Results

| Benchmark | N | Classic | TAHOE | Cl out | Tah out | Ratio | Savings |
|---|---|---|---|---|---|---|---|
| GSM8K | 1319 | 2822/3957 (71.3%) | 3126/3957 (79.0%) | 241 | 91 | 0.38x | 62% |
| ARC | 1172 | 3374/3516 (96.0%) | 3366/3516 (95.7%) | 121 | 58 | 0.48x | 52% |
| BBH | 250 | 586/750 (78.1%) | 584/750 (77.9%) | 472 | 288 | 0.61x | 39% |
| BBH-track | 250 | 673/750 (89.7%) | 569/750 (75.9%) | 521 | 270 | 0.52x | 48% |
| BBH-arith | 200 | 600/600 (100%) | 599/600 (99.8%) | 117 | 97 | 0.83x | 17% |
| MMLU-math | 100 | 283/300 (94.3%) | 283/300 (94.3%) | 399 | 318 | 0.80x | 20% |
| MMLU-logic | 126 | 360/378 (95.2%) | 352/378 (93.1%) | 312 | 263 | 0.84x | 16% |
| MMLU-acct | 282 | 813/846 (96.1%) | 815/846 (96.3%) | 238 | 138 | 0.58x | 42% |
| LSAT | 510 | 1429/1530 (93.4%) | 1452/1530 (94.9%) | 432 | 210 | 0.49x | 51% |
| RACE | 1045 | 2950/3135 (94.1%) | 2942/3135 (93.8%) | 189 | 100 | 0.53x | 47% |
| **OVERALL** | — | **13890/15762 (88.1%)** | **14088/15762 (89.4%)** | **246** | **125** | **0.51x** | **49%** |

## Headline Numbers

- **Quality**: 89.4% (TAHOE) vs 88.1% (classic) — **+1.3%**
- **Token savings**: 49% (0.51x output ratio)
- **HM**: 1.227 (TAHOE) vs 0.937 (classic) — TAHOE wins decisively
- **Total trials**: 31,524

## Quality Wins (TAHOE > Classic)
- GSM8K: +7.7% (79.0 vs 71.3) — strongest quality gain
- LSAT: +1.5% (94.9 vs 93.4)
- MMLU-acct: +0.2% (96.3 vs 96.1)

## Quality Regressions (Classic > TAHOE)
- BBH-track: -13.8% (75.9 vs 89.7) — conciseness hurts state tracking
- MMLU-logic: -2.1% (93.1 vs 95.2) — formal logic benefits from verbose derivation
- ARC: -0.3% (95.7 vs 96.0) — essentially tied
- RACE: -0.3% (93.8 vs 94.1) — essentially tied

## Raw Data
- Per-benchmark: `benchmarks/results/single_{benchmark}.json`
- Combined: `benchmarks/results/full_test_eval.json`
