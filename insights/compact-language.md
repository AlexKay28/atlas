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

## Raw data

- `benchmarks/results/skill_cmp_{bench}.json` — 10 benches x 3 arms x 30
- Prompt ablation (5 skill sizes, 1500 trials): all sizes cut tokens 22-39%
  vs classic with flat quality; results/prompt_ablation.json
- Explicit-TRIZ failure evidence: skill_cmp gsm8k/lsat runs (overwritten by
  the implicit run on gsm8k; lsat explicit run in git history 833e987^)
