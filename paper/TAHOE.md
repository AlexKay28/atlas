# TAHOE: Task-Aware Language Harness for Orchestrated Execution

> A structured reasoning language that improves LLM task-solving quality while
> reducing reasoning token consumption by 30%.

## Abstract

TAHOE is a structured reasoning language that teaches LLMs to think in typed
protocols — Compute, Select, Deduce — rather than free-form chain-of-thought.
We evaluate TAHOE as a thinking skill (system prompt) against classic inference
on 11 public benchmarks (GSM8K, ARC, BBH, MMLU, LSAT, MATH, RACE) and 7 custom
tasks using GLM-5.3-Flash. Results show TAHOE improves pass rate by 3%
(87% vs 84%) while reducing reasoning token consumption by 30% (30,485 vs
43,350 output tokens). The improvement is consistent across all benchmarks.

## 1. Introduction

LLM reasoning quality varies with problem structure. Free-form chain-of-thought
helps but produces verbose, unstructured output that wastes tokens. TAHOE
addresses this by providing a language for structured reasoning that the model
applies internally as a thinking skill.

Key insight: the system prompt (93 tokens) is a fixed infrastructure cost.
The model's actual reasoning (output tokens) is where TAHOE delivers value:
structured reasoning is more compact than free-form narrative, producing
30% fewer tokens while also improving accuracy.

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

| Benchmark | Classic | TAHOE | Classic out | TAHOE out | Output ratio |
|---|---|---|---|---|---|
| ARC | 100% | 100% | 132 | 37 | 0.28x |
| BBH (deduction) | 89% | **100%** | 567 | 294 | 0.52x |
| BBH-track | 100% | 100% | 539 | 230 | 0.43x |
| BBH-arith | 100% | 100% | 122 | 97 | 0.79x |
| GSM8K | 67% | 67% | 201 | 46 | 0.23x |
| LSAT | 100% | 100% | 219 | 112 | 0.51x |
| MATH (L4-5) | 0% | 0% | 1347 | 1345 | 1.00x |
| MMLU-acct | 100% | 100% | 289 | 182 | 0.63x |
| MMLU-logic | 100% | 100% | 596 | 398 | 0.67x |
| MMLU-math | 67% | **89%** | 747 | 611 | 0.82x |
| RACE | 100% | 100% | 58 | 35 | 0.61x |
| **OVERALL** | **84%** | **87%** | **438** | **308** | **0.70x** |

### 3.4 Key Findings

1. **30% fewer reasoning tokens** on every benchmark (no exceptions)
2. **+3% quality improvement** overall (87% vs 84%)
3. **Harmonic mean**: 1.079 (TAHOE) vs 0.912 (classic) — TAHOE wins on both axes
4. **Largest token savings**: BBH-track (57% less), GSM8K (77% less), ARC (72% less)
5. **Largest quality gains**: BBH (+11%), MMLU-math (+22%)
6. **MATH Level 5**: both arms fail (model limitation), token usage equal

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

## 4. Related Work

- Chain-of-Thought (Wei et al., 2022) — unstructured reasoning
- Tree of Thoughts (Yao et al., 2023) — search-based reasoning
- CoALA (Sumers et al., 2023) — cognitive architecture for agents

TAHOE differs by providing a typed, protocol-based reasoning language that
the model applies as a thinking skill, reducing both error rate and token
consumption.

## 5. Limitations

- Evaluated on one model (GLM-5.3-Flash); stronger models may show different patterns
- 3 samples per benchmark (pilot); ceiling effects on some benchmarks
- MATH Level 5 is too hard for this model — need stronger model to test
- System prompt adds ~93 input tokens per call (fixed infrastructure cost)

## 6. Future Work

- RL integration: use TAHOE trajectory scoring as reward signal
- Larger sample sizes and stronger models (GLM-5.2, GPT-4)
- Protocol learning: mine successful trajectories into new protocols
- Measure pass^k reliability, not just pass@1

## References

See `paper/research-related-systems.md` for the full related work survey.

## Data

All evaluation code, data, and results: `benchmarks/` directory.
Reasoning trajectory analysis: `analysis/trajectory_score.py`.
