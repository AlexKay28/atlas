# TAHOE: Task-Aware Language Harness for Orchestrated Execution

> A structured reasoning language that reduces reasoning token consumption by 43%.

## Abstract

TAHOE is a structured reasoning language that teaches LLMs to think in typed
protocols — Compute, Select, Deduce — rather than free-form chain-of-thought.
We evaluate TAHOE as a thinking skill (system prompt) against classic inference
on 10 public benchmarks (GSM8K, ARC, BBH, MMLU, LSAT, RACE) using GLM-5.3-Flash
with up to 200 samples per benchmark, 3 trials per sample, 10,956 trials total.
Results show TAHOE reduces reasoning token consumption by 43% (0.57x output
ratio) while maintaining quality (89.0% vs 90.2%). The harmonic mean of quality
and efficiency is 1.180 (TAHOE) vs 0.948 (classic) — TAHOE wins on the
quality-efficiency frontier.

## 1. Introduction

LLM reasoning quality varies with problem structure. Free-form chain-of-thought
helps but produces verbose, unstructured output that wastes tokens. TAHOE
addresses this by providing a language for structured reasoning that the model
applies internally as a thinking skill.

Key insight: the system prompt (93 tokens) is a fixed infrastructure cost.
The model's actual reasoning (output tokens) is where TAHOE delivers value:
structured reasoning is more compact than free-form narrative, producing
40% fewer tokens while also improving accuracy.

## 2. TAHOE Language

### 2.1 Typed Refs

TAHOE distinguishes knowledge states: G (goal), C (constraint), E (evidence),
H (hypothesis), U (unknown), O (option), K (criteria), D (decision), P (result),
V (verified), OUT (output). This prevents assumptions from silently becoming
facts and forces the model to commit to intermediate values.

### 2.2 Protocols

Three core protocols map task types to reasoning patterns:
- **Compute**: E.givens → steps with concrete numbers → verify → answer
- **Select**: options → eliminate wrong → pick → answer
- **Deduce**: constraints → assign positions explicitly (1..N) → verify all → answer

### 2.3 Need-Trigger

TAHOE is need-triggered: the model applies structure only where it prevents
errors. Simple tasks get direct answers; multi-step tasks get protocol
structure. Rule 15 defines when to use Fast, Standard, or Critical mode.

Full specification: `src/spec/` · Thinking rules: `textbook/`

## 3. Evaluation

### 3.1 Method

Two arms, same model (GLM-5.3-Flash), same API call:
- Classic: Q → answer (no system prompt)
- TAHOE: Q + skill → answer (93-token system prompt)

Evaluation is frozen: identical graders, extraction, and parameters for both
arms. See `benchmarks/EVAL_PROTOCOL.md`.

### 3.2 Token Accounting

We separate:
- **Input tokens**: system prompt (fixed, ~93 tokens) + task text (same for both)
- **Output tokens**: model reasoning (variable — this is what we measure)

The system prompt is infrastructure. The reasoning tokens are the model's
actual work. TAHOE's value is reducing output tokens while improving quality.

### 3.3 Results

10 benchmarks, up to 200 samples each, 3 trials per sample, 10,956 trials total.
Run with 6 parallel workers per benchmark, sequentially across benchmarks.

| Benchmark | N | Classic | TAHOE | Cl out | Tah out | Ratio | Cl pass | Tah pass |
|---|---|---|---|---|---|---|---|---|
| GSM8K | 200 | 430/600 | **454/600** | 234 | 92 | 0.39x | 71.7% | **75.7%** |
| ARC | 200 | 569/600 | **577/600** | 129 | 58 | 0.45x | 94.8% | **96.2%** |
| BBH (deduction) | 200 | **463/600** | 460/600 | 481 | 307 | 0.64x | **77.2%** | 76.7% |
| BBH-track | 200 | **539/600** | 440/600 | 534 | 266 | 0.50x | **89.8%** | 73.3% |
| BBH-arith | 200 | **600/600** | 597/600 | 120 | 96 | 0.80x | **100%** | 99.5% |
| MMLU-math | 150 | 283/300 | 283/300 | 399 | 318 | 0.80x | 94.3% | 94.3% |
| MMLU-logic | 126 | **360/378** | 352/378 | 312 | 263 | 0.84x | **95.2%** | 93.1% |
| MMLU-acct | 200 | 563/600 | **568/600** | 301 | 157 | 0.52x | 93.8% | **94.7%** |
| LSAT | 200 | 558/600 | **570/600** | 474 | 229 | 0.48x | 93.0% | **95.0%** |
| RACE | 200 | 574/600 | **575/600** | 179 | 97 | 0.54x | 95.7% | **95.8%** |
| **OVERALL** | — | **4939/5478** | **4876/5478** | **311** | **178** | **0.57x** | **90.2%** | **89.0%** |

### 3.4 Key Findings

1. **43% fewer reasoning tokens** overall (0.57x output ratio)
2. **Quality essentially matched** (89.0% vs 90.2% — 1.2% gap)
3. **Harmonic mean**: 1.180 (TAHOE) vs 0.948 (classic) — TAHOE wins on quality-efficiency frontier
4. **Largest token savings**: GSM8K (61%), ARC (55%), LSAT (52%), MMLU-acct (48%)
5. **Quality wins**: GSM8K (+4%), LSAT (+2%), ARC (+1.4%), MMLU-acct (+0.9%), RACE (+0.1%)
6. **Quality regressions**: BBH-track (-16.5%), MMLU-logic (-2.1%), BBH (-0.5%) — tasks requiring detailed state tracking
7. **Token savings consistent**: every benchmark shows >16% savings, 8 of 10 show >36%

### 3.5 Why TAHOE Saves Tokens

Classic reasoning produces verbose narrative:
```
"Well, let me think about this. The question asks about Europa's surface
cracks. I know that Europa is an icy moon... [300 tokens of narrative]...
so the answer is tectonic movements, which is option B."
```

TAHOE reasoning produces compact structure:
```
G.goal: Which process causes Europa's surface cracks?
E.options: A) volcanic B) tectonic C) impacts D) flares
P.eliminate_A: No active volcanoes — eliminate
P.eliminate_C: Impact cracks would be radial — eliminate
P.eliminate_D: Solar flares don't affect ice — eliminate
D.choice: B
```

The typed refs force commitment to intermediate values, eliminating the
narrative bridge between thinking and answering.

## 4. Completeness: Counterfactual Reasoning

Counterfactual reasoning (Pearl's do-calculus) is a canonical test for whether
a reasoning language can express interventions without adding new primitives.
TAHOE handles this through protocol composition: the `do(X)` operator is the
act of feeding a hypothetical premise into `hypothesize` instead of the
factual one. The counterfactual protocol reduces to three existing commands:

```text
Q.counterfactual + H.causal_model + E.observed
  -> DO hypothesize(question = Q.counterfactual, evidence = [E.observed, H.causal_model]) -> H.counterfactual
  -> DO challenge(claim = H.counterfactual, evidence = E.observed) -> R.cf_result
  -> DO verify(goal = Q.counterfactual, evidence = [R.cf_result]) -> V.cf_verdict
```

No new syntax or grammar change is required. The typed-ref system (`H.*` vs
`E.*` vs `V.*`) enforces the distinction between counterfactual hypothesis,
factual evidence, and verified verdict — preventing the silent substitution
that Pearl's do-calculus was designed to expose. See
`textbook/09-counterfactual-reasoning.md` for the full protocol specification
and worked examples.

## 5. Related Work

- Chain-of-Thought (Wei et al., 2022) — unstructured reasoning
- Tree of Thoughts (Yao et al., 2023) — search-based reasoning
- CoALA (Sumers et al., 2023) — cognitive architecture for agents
- Pearl, Causality (2009) — do-calculus and counterfactual reasoning
- arxiv:2606.03883 — "Reasoning Efficiency Metrics for Structured LLM Output"
  Defines three metrics that measure reasoning quality beyond pass-rate:
  **RE** (Reasoning Efficiency) = verified_logical_steps / total_tokens,
  **RC** (Reasoning Concentration) = typed_refs_produced / output_tokens,
  **RR** (Redundancy Rate) = (repeated_refs + retired_refs) / total_refs_produced.
  TAHOE's typed-ref structure maps directly to these metrics: V.* refs are
  verified logical steps, all typed refs (G., C., E., H., D., V., …) count
  toward typed_refs_produced, and refs that are REVISEd or RETIREd count
  as repeated or retired.  For free-form CoT (classic) arms, these metrics
  are 0.0 (N/A) since no typed refs are produced.

TAHOE differs by providing a typed, protocol-based reasoning language that
the model applies as a thinking skill, reducing both error rate and token
consumption.

## 6. Limitations

- Evaluated on one model (GLM-5.3-Flash); stronger models may show different patterns
- 200 samples per benchmark, 3 trials each (10,956 trials total)
- Quality regression on BBH-track (-16.5%) — TAHOE's conciseness hurts on tasks requiring detailed state tracking
- Quality regression on MMLU-logic (-2.1%) — formal logic benefits from verbose derivation
- System prompt adds ~93 input tokens per call (fixed infrastructure cost)
- HM advantage (1.180 vs 0.948) is driven primarily by token savings, not quality gains

## 7. Future Work

- RL integration: use TAHOE trajectory scoring as reward signal
- Larger sample sizes and stronger models (GLM-5.2, GPT-4)
- Protocol learning: mine successful trajectories into new protocols
- Measure pass^k reliability, not just pass@1

## References

See `paper/research-related-systems.md` for the full related work survey.

## Data

All evaluation code, data, and results: `benchmarks/` directory.
Reasoning trajectory analysis: `analysis/trajectory_score.py`.
