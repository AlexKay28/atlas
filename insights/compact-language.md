# The Compact Language: TAHOE Grammar + TRIZ Operators, Implicit

> The compound result (2026-09-14): TAHOE typed-ref grammar + TRIZ operators
> (IFR-first, obstacle-naming, minimal derivation) as SILENT thinking
> discipline — output contract = the answer only. 900-trial pilot across
> 10 benchmarks, GLM-5.3-Flash, 30 samples x 3 arms.

## Headline

| Arm | Quality | Avg out tokens | vs classic |
|---|---|---|---|
| classic | 93.7% | 337 | — |
| tahoe-93 (Stage 1) | 97.0% | 189 | −44% tokens, +3.3pp |
| **tahoe-triz-implicit** | **96.3%** | **141** | **−58% tokens, +2.6pp** |

Quality statistically tied across skills (n=300); token reduction consistent
in direction on 9/10 benchmarks per arm. gsm8k quality gain is far outside
noise: classic 70% → tahoe 86.7% → **triz-implicit 90%**.

## The journey that produced it (three failed/successive hypotheses)

1. **Explicit TRIZ notation (visible I/O lines)** — FAILED hard: gsm8k 343 out
   tokens (worse than classic), LSAT 7/30 (−73pp). Forcing the language into
   output amputates reasoning: 9 format lines cost more than the narrative
   they replace, and ≤20-word refs destroy logic chains.
2. **Discovery that reframed everything**: Stage-1's tahoe-93 median output is
   48 tokens — mostly JUST THE ANSWER. The skill never produced visible
   structure; it internalized the protocol into hidden reasoning. The compact
   language of logic already worked — *invisibly*. (TRIZ IFR satisfied:
   structure performs itself without appearing in output.)
3. **Implicit TRIZ** — TRIZ operators as silent discipline, answer-only output:
   beats plain tahoe on both axes (gsm8k 90% @ 49t vs 86.7% @ 68t; lsat tied
   @ 131t vs 235t).

## The law this establishes

**The language of reasoning must shape thought, never constrain output.**
Visible notation taxes every token; internalized notation taxes nothing.
TAHOE-VM's failure and the explicit-TRIZ failure are the same failure —
externalizing what should stay in the weights. The compact "language of
consciousness" is a thinking discipline, not an output format.

## The language itself (benchmarks/tahoe_triz_implicit.txt)

Five silent moves, fixed order:
1. **Fix the ideal** (IFR) — bounds the search before it starts
2. **Name the obstacle** — the one unknown between here and the ideal
3. **Inventory only what the obstacle needs** — resource bounding
4. **Derive minimally** — one op per fact: calculate, infer, eliminate, separate
5. **Verify closure** — on contradiction: separate in space/time/structure/condition

Then STOP. Output only the answer.

TRIZ contributes the *semantics* (search-bounding operators); TAHOE
contributes the *discipline* (typed commitment, verify-before-answer,
deterministic-first). Compounded: the model wanders less (IFR-first) and
emits nothing but the answer (output contract).

## Scaled confirmation (200 samples, 6,000 trials, GLM-5.3-Flash)

| Bench | classic | tahoe-93 | triz-implicit |
|---|---|---|---|
| gsm8k | 71.0% / 238t | 80.0% / 82t | **94.5% / 53t** |
| arc | 96.0% / 123t | 96.5% / 53t | 95.5% / 45t |
| bbh | 98.5% / 485t | 99.0% / 296t | 98.5% / 209t |
| bbh_arith | 100% / 120t | 99.5% / 93t | 99.5% / 80t |
| bbh_track | 100% / 517t | 100% / 253t | 99.0% / 209t |
| lsat | 94.0% / 485t | 95.5% / 245t | 95.5% / 149t |
| mmlu_acct | 93.0% / 303t | 94.5% / 182t | 94.0% / 124t |
| mmlu_logic | 95.2% / 294t | 92.9% / 248t | 93.7% / 210t |
| mmlu_math | 95.0% / 374t | 97.0% / 317t | 95.0% / 260t |
| race | 96.0% / 169t | 95.5% / 104t | 95.0% / 73t |
| **OVERALL** | **93.8% / 308t** | **95.0% / 178t** | **96.2% / 132t** |

**HM: classic 0.968 → tahoe 1.227 → triz-implicit 1.362.**

The gsm8k ladder is the headline: 71.0% → 80.0% → **94.5%** (+23.5pp over
classic at 78% fewer reasoning tokens; +14.5pp over tahoe at 0.65x tokens —
both far outside binomial noise at n=200). triz-implicit ≤ tahoe tokens on
10/10 benches; quality ≥ tahoe overall (96.2% vs 95.0%).

## Raw data

- `benchmarks/results/skill_cmp_{bench}.json` — 10 benches x 3 arms x 30
- Prompt ablation (5 skill sizes, 1500 trials): all sizes cut tokens 22-39%
  vs classic with flat quality; results/prompt_ablation.json
- Explicit-TRIZ failure evidence: skill_cmp gsm8k/lsat runs (overwritten by
  the implicit run on gsm8k; lsat explicit run in git history 833e987^)

## ⚠️ CORRECTION (2026-09-14, post-scale): the quality ladders were extraction artifacts

After the 200-sample run I audited the gsm8k grader and found the v1 number
extractor split thousands/LaTeX-formatted numbers ('1{,}430' → '430',
'2\,000' → '000'), failing ~13-27% of classic-arm answers that were actually
CORRECT (21 of 22 "rescued" tasks had the right number buried in LaTeX prose).
Same disease as the BBH '(X)' bug — the third grader-format lesson this
project has produced.

v3 extractor (priority: #### → boxed → LAST bold span → 'answer is' → last
separator-aware number) installed arm-agnostically; full gsm8k re-runs:

| Arm | GLM gsm8k | GLM out | oss gsm8k | oss out |
|---|---|---|---|---|
| classic | **91.0%** | 235 | **87.0%** | 304 |
| tahoe-93 | 95.5% | 83 | 93.0% | 121 |
| triz-implicit | 95.5% | **63** | 92.5% | 118 |

### Corrected honest claims (what survives)

1. **Token savings are the robust result**: −62/−73% (GLM gsm8k), −60/−61%
   (oss), −42-57% overall across benches. Direction holds on every bench,
   both models.
2. **Quality gains are real but modest**: +4.5-6pp on gsm8k, +0.4-0.8pp
   overall (GLM, within-noise on most benches). NOT +23.5pp.
3. **The compound language ≈ plain tahoe on quality** (95.5 vs 95.5 GLM
   gsm8k; overall 96.3 vs 96.7 pre-correction) at −18-26% fewer tokens than
   tahoe. IFR-first bounding is a token lever, not a quality lever.
4. The earlier "+23.5pp ladder" and "HM 1.362" headlines are RETRACTED —
   they compared clean-format skill outputs against broken-extraction classic
   outputs.
5. The law (shape thought, never constrain output) still stands — the
   explicit-TRIZ LSAT collapse (7/30) was quality-real, not extraction.
6. Every numeric-bench comparison in this project must carry the v3 grader
   going forward. Stage-1 full-eval gsm8k row also corrected offline
   (classic 68.5%, tahoe 80.3%).

The meta-lesson, three occurrences deep: **when one arm answers in a
different FORMAT than another, the grader is part of the experiment.** Audit
extraction on raw outputs from EVERY arm before believing any cross-arm delta.
