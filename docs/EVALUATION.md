# TAHOE Evaluation Results

> Canonical record of all evaluation runs. Updated: 2026-09-14.

## Current State: Cross-Model Evaluation (63,348 trials)

Two models, 10 public benchmarks, **full test sets**, 3 trials per sample, 2 arms
(classic vs tahoe). Same frozen eval protocol — identical graders, extraction,
max_turns=1, max_tokens=2048, timeout=60s for both arms.

### Headline Numbers

| Model | Trials | Classic | TAHOE | Token ratio | HM classic | HM tahoe |
|---|---|---|---|---|---|---|
| GLM-5.3-Flash | 31,524 | 89.6% | **91.5%** (+1.9%) | 0.51x (-49%) | 0.945 | **1.247** |
| gpt-oss-120b | 31,824 | 89.1% | 88.9% (-0.2%) | 0.68x (-32%) | 0.942 | **1.107** |

**TAHOE wins the quality-efficiency frontier on both models.** The 93-token skill
prompt transfers across models without per-model tuning.

### GLM-5.3-Flash (full test sets, grader-corrected)

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

### gpt-oss-120b (full test sets)

| Benchmark | N | Classic | TAHOE | Ratio |
|---|---|---|---|---|
| GSM8K | 1319 | 77.9% | **79.4%** | 0.40x |
| ARC | 1172 | **94.4%** | 94.1% | 0.71x |
| BBH | 250 | 99.1% | **99.7%** | 0.83x |
| BBH-track | 250 | **100%** | 99.6% | 0.83x |
| BBH-arith | 250 | **99.9%** | 99.6% | 0.88x |
| MMLU-math | 100 | 96.7% | 96.7% | 0.83x |
| MMLU-logic | 126 | **95.5%** | 95.0% | 0.84x |
| MMLU-acct | 282 | 89.6% | 89.6% | 0.82x |
| LSAT | 510 | **85.4%** | 83.1% | 0.72x |
| RACE | 1045 | **89.8%** | 88.7% | 0.85x |
| **OVERALL** | — | **89.1%** | **88.9%** | **0.68x** |

## Evaluation History

| Date | Run | Trials | Key result |
|---|---|---|---|
| 2026-09-13 | Pilot (10 samples) | 600 | 40% token savings, +1% quality, HM 1.162 vs 0.934 |
| 2026-09-13 | 200-sample run | 10,956 | 43% savings, quality tied, HM 1.180 vs 0.948 |
| 2026-09-14 | GLM full test sets | 31,524 | 49% savings, +1.3% quality (pre-grader-fix) |
| 2026-09-14 | gpt-oss-120b full test sets | 31,824 | 32% savings, quality matched |
| 2026-09-14 | Grader fix + re-grade | — | BBH-track "regression" was grader artifact; GLM overall corrected to +1.9% |

## Grader Format Lesson (important)

The original BBH grader only accepted answers in "(X)" format. Models answering
with bare letters ("E") were failed despite being correct. This produced a fake
"BBH-track quality regression" in earlier GLM results (-13.8% that vanished after
the fix — actual: classic 99.9%, tahoe 99.5%).

**Rule**: graders must accept every reasonable answer format (parenthesized,
bare letter, letter-in-text). Test graders against actual model output
distributions before trusting cross-arm comparisons. Grader fix applied in
commit 0645918; stored results re-graded offline.

## Key Findings

1. **TAHOE transfers across models** — never tuned per-model
2. **Math benefits most**: GSM8K +7.7% (GLM) / +1.5% (gpt-oss) quality with ~60% token savings
3. **Reasoning-heavy models compress less** (gpt-oss-120b 32% vs GLM 49%) — their CoT is already lean
4. **Token savings are universal**: 12-62% across all 20 model-benchmark pairs
5. **HM (quality-efficiency harmonic mean) favors TAHOE everywhere**

## Infrastructure

- Runners: `benchmarks/run_skill_compare.py` (canonical arm comparison), `run_single_bench.py` (per-benchmark), `run_parallel_bench.py` (all + CIs) — see `benchmarks/README.md`
- **Runs never overwrite**: active runners write to `results/runs/<timestamp>_<name>/` via `outdir.py`
- Stats: `benchmarks/stats.py` — bootstrap CIs, permutation tests, Wilcoxon, Cohen's h
- Protocol: `benchmarks/EVAL_PROTOCOL.md` — frozen invariants
- Rate-limit retry: worker_fn backs off on 429/inflight errors, retries empty 0-token answers

## Raw Data

Results are frozen into dated study directories (see
`benchmarks/results/README.md` for the index):

- GLM Stage-1: `benchmarks/results/2026-09-13-stage1-full/full_test_eval.json` (grader-corrected)
- gpt-oss-120b Stage-1: `benchmarks/results/2026-09-13-stage1-full/oss_full_eval.json`
- Per-benchmark: `benchmarks/results/2026-09-13-stage1-full/single_{benchmark}.json`
- Skill comparisons: `benchmarks/results/2026-09-14-skill-study/skill_cmp_*.json`
- Legacy summaries: same directory (`FULL_TEST_SET_EVAL.md`, `FULL_EVAL_SUMMARY.md`)

**Note**: gsm8k rows were re-graded with the v3 extractor (grader-format fix);
legacy summaries predate that correction.

## Model Endpoints

- GLM-5.3-Flash: `https://api.eliza.yandex.net/raw/internal/v2/models/GLM-5.3-Flash_alexkay28/v1`
- gpt-oss-120b: `https://api.eliza.yandex.net/raw/internal/gpt-oss-120b/v1` (note: NO /v2)
- Auth: `Authorization: Bearer $TOKEN`, pool header `Ya-Pool` (quota: 5 inflight per family)
