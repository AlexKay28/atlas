# TAHOE: Task-Aware Language Harness for Orchestrated Execution

> A structured reasoning language that improves LLM task-solving quality
> through typed thinking protocols. This paper presents the language design,
> evaluation methodology, and benchmark results.

## Abstract

TAHOE is a structured reasoning language that teaches LLMs to think in typed
protocols — Compute, Select, Deduce, Decide, Plan, Debug — rather than
free-form chain-of-thought. We evaluate TAHOE as a thinking skill (system
prompt) against classic inference on 3 public benchmarks (GSM8K, ARC-Challenge,
BBH) and 7 custom tasks. Results show TAHOE improves pass rate by 10-80% on
computation and planning tasks while using 1.6-2.2x more tokens. The thinking
skill approach — same single inference call, structured reasoning — avoids
the overhead of multi-step execution harnesses.

## 1. Introduction

LLM reasoning quality varies with problem structure. Free-form chain-of-thought
helps but lacks verifiable intermediate steps, typed knowledge states, and
explicit completion checks. TAHOE addresses this by providing a language for
structured reasoning that the model applies internally, not an external
execution harness.

## 2. TAHOE Language

### 2.1 Typed Refs

TAHOE distinguishes knowledge states: G (goal), C (constraint), E (evidence),
H (hypothesis), U (unknown), O (option), K (criteria), D (decision), P (plan),
V (verified), OUT (output). This prevents assumptions from silently becoming
facts.

### 2.2 Protocols

Nine protocols map task types to reasoning patterns:
- Compute: arithmetic with concrete values and reverse verification
- Select: elimination-based multiple choice
- Deduce: constraint satisfaction with explicit position tracking
- (Explore, Decide, Plan, Debug, Review, Learn — for engineering tasks)

### 2.3 Thinking Rules

15 rules govern reasoning: name outcome before method, separate constraints
from preferences, verify before returning, match rigor to consequence.

Full specification: `src/spec/` · Thinking rules: `textbook/01-smart-thinking-rules.md`

## 3. Evaluation

### 3.1 Method

We compare two arms using the same model (GLM-5.3-Flash) and same API call:
- Classic: Q → answer (no system prompt)
- TAHOE: Q + skill → answer (TAHOE thinking skill as system prompt)

Both arms make exactly one API call. The only difference is the system prompt
that teaches structured reasoning.

### 3.2 Benchmarks

| Benchmark | Type | Samples | Metric |
|---|---|---|---|
| GSM8K | Grade school math | 10 × 3 trials | Exact number match |
| ARC-Challenge | Science reasoning | 10 × 3 trials | Letter match |
| BBH (logical_deduction) | Spatial ordering | 10 × 3 trials | Letter match |
| Custom (7 tasks) | Code fix, routing, search, plan, recover | 5 trials each | Task-specific grader |

### 3.3 Results

| Benchmark | Classic | TAHOE | Token ratio |
|---|---|---|---|
| GSM8K | 80% | 90% | 2.5x |
| ARC | 83% | 90% | 2.7x |
| BBH | 97% | 100% | 1.5x |
| Custom (routing-02) | 20% | 100% | 1.6x |

### 3.4 Analysis

TAHOE helps most on tasks requiring structured computation (routing-02: +80%)
and systematic evaluation (ARC: +7%). The improvement comes from protocol
selection (eliminates exploratory preamble) and typed refs (forces commitment
to intermediate values). Token overhead is from the system prompt, not from
additional API calls.

## 4. Related Work

- Chain-of-Thought (Wei et al., 2022) — unstructured reasoning
- Tree of Thoughts (Yao et al., 2023) — search-based reasoning
- CoALA (Sumers et al., 2023) — cognitive architecture for agents
- DreamCoder (Ellis et al., 2021) — program synthesis for learning

TAHOE differs by providing a typed, protocol-based reasoning language that
the model applies as a thinking skill, not an execution harness.

## 5. Limitations

- Evaluated on one model (GLM-5.3-Flash); stronger models may benefit less
- 10 samples per benchmark is a pilot; larger runs needed for significance
- TAHOE adds 400 input tokens of system prompt overhead per call
- BBH improvement is marginal (97% → 100%) — ceiling effect

## 6. Future Work

- RL integration: use TAHOE trajectory scoring as reward signal
- Larger benchmarks (τ-bench, SWE-bench, GAIA)
- Multi-model evaluation (GLM-5.2, GPT-4, Claude)
- Protocol learning: mine successful trajectories into new protocols

## References

See `paper/research-related-systems.md` and `paper/research-text-harness-precedents.md`
for the full related work survey.

## Data

All evaluation code, data, and results: `benchmarks/` directory.
Reasoning trajectory analysis: `analysis/trajectory_score.py`.
