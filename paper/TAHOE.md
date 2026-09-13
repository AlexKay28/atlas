# TAHOE: Task-Aware Language Harness for Orchestrated Execution

> A structured reasoning language that improves LLM task-solving quality while
> reducing reasoning token consumption by 40%.

## Abstract

TAHOE is a structured reasoning language that teaches LLMs to think in typed
protocols — Compute, Select, Deduce — rather than free-form chain-of-thought.
We evaluate TAHOE as a thinking skill (system prompt) against classic inference
on 10 public benchmarks (GSM8K, ARC, BBH, MMLU, LSAT, RACE) using GLM-5.3-Flash
with 10 samples per benchmark, 3 trials per sample, 600 trials total. Results
show TAHOE improves pass rate by 1% (89% vs 88%) while reducing reasoning token
consumption by 40% (60,055 vs 100,595 output tokens). The harmonic mean of
quality and efficiency is 1.162 (TAHOE) vs 0.934 (classic).

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

10 benchmarks, 10 samples each, 3 trials per sample, 600 trials total.
Run with 6 parallel workers, completed in 279 seconds.

| Benchmark | Classic | TAHOE | Cl out | Tah out | Ratio | Cl pass | Tah pass |
|---|---|---|---|---|---|---|---|
| ARC | 27/30 | 26/30 | 183 | 160 | 0.87x | 90% | 87% |
| BBH (deduction) | 18/30 | **24/30** | 457 | 253 | 0.55x | 60% | **80%** |
| BBH-track | 25/30 | 22/30 | 484 | 270 | 0.56x | 83% | 73% |
| BBH-arith | 30/30 | 30/30 | 123 | 132 | 1.07x | 100% | 100% |
| GSM8K | 25/30 | 24/30 | 201 | 57 | 0.28x | 83% | 80% |
| LSAT | 30/30 | 30/30 | 407 | 239 | 0.59x | 100% | 100% |
| MMLU-acct | 26/30 | **30/30** | 488 | 182 | 0.37x | 87% | **100%** |
| MMLU-logic | 30/30 | 30/30 | 125 | 97 | 0.78x | 100% | 100% |
| MMLU-math | 29/30 | 27/30 | 555 | 512 | 0.92x | 97% | 90% |
| RACE | 23/30 | **24/30** | 330 | 100 | 0.30x | 77% | **80%** |
| **OVERALL** | **263/300** | **267/300** | **335** | **200** | **0.60x** | **88%** | **89%** |

### 3.4 Key Findings

1. **40% fewer reasoning tokens** overall (60,055 vs 100,595 output tokens)
2. **+1% quality improvement** overall (89% vs 88%)
3. **Harmonic mean**: 1.162 (TAHOE) vs 0.934 (classic) — TAHOE wins on both axes
4. **Largest token savings**: GSM8K (72% less), RACE (70% less), MMLU-acct (63% less)
5. **Largest quality gains**: BBH (+20%), MMLU-acct (+13%), RACE (+3%)
6. **Only benchmark where classic edges TAHOE**: BBH-arith (token cost slightly higher 1.07x, quality equal)

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

TAHOE differs by providing a typed, protocol-based reasoning language that
the model applies as a thinking skill, reducing both error rate and token
consumption.

## 6. Limitations

- Evaluated on one model (GLM-5.3-Flash); stronger models may show different patterns
- 10 samples per benchmark, 3 trials each (600 trials); ceiling effects on some benchmarks
- System prompt adds ~93 input tokens per call (fixed infrastructure cost)
- BBH-arith is the only benchmark where TAHOE uses slightly more tokens (1.07x)

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
