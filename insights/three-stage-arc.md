# The Three-Stage Arc: Teaching Models a Specialized Reasoning Language

> The thesis of the next paper: "How to teach a model to reason in a
> specialized language for token consumption reduction."
> Dated 2026-09-14.

## The arc

```
Stage 1: TEACH BY PROMPT       (DONE — 63,348 trials, 2 models)
  93-token system prompt teaches the language (typed refs, protocols)
  Evidence: −49% tokens (GLM-5.3-Flash), −32% (gpt-oss-120b);
  quality +1.9% / −0.2%; HM wins on both models
  Deliverable: benchmarks/results/CROSS_MODEL_EVAL.md

Stage 2: PRACTICE BY EXECUTION (TAHOE-VM — in progress)
  Model compiles task → program.think, then EXECUTES it on itself:
  one atomic self-subcall per step, harness holds refs + validation,
  context grows O(refs) not O(history)
  Question: does OPERATING in the language beat IMITATING it?
  Deliverable: src/tahoe/vm_mode/ + 3-bench pilot with token gates

Stage 3: INTERNALIZE BY RL     (planned)
  GRPO over VM trajectories; reward = outcome grader + DONE-predicate
  process terms − λ·tokens
  The model learns the protocols AND when to use them (need-trigger as
  trained policy, not prompt text)
  Question: can the language become weights instead of text?
  Deliverable: prompted-VM vs RL-VM comparison
```

## Why each stage matters

- **Stage 1 is the transferability proof**: the same 93-token skill worked on two
  architecturally different models with zero per-model tuning. The language is
  a portable artifact, not a prompt hack.
- **Stage 2 is the execution proof**: refs are O(10) tokens vs O(100) CoT
  narration; subcall context is a state slice; pure-computation steps cost zero
  model tokens (deterministic executor). The harness adds fixed per-call
  overhead — see token-economics.md for why the language saves more than the
  harness spends.
- **Stage 3 is the internalization proof**: the deep-search finding is that
  reasoning length is directly RL-controllable (L1/LCPO). Need-trigger routing
  (when to enter VM mode) becomes a learned policy. The endpoint: the language
  stops being external text and becomes behavior.

## The unique asset across all three stages

**Machine-verified process rewards for free.** OpenAI's Let's Verify Step by
Step needed 800,000 human labels (PRM800K) for step-level supervision. TAHOE's
DONE predicates, parse validation, and typecheck produce equivalent signal
computationally — every step either passes its predicate or doesn't. This is
the single most defensible novelty of the program.

## Positioning line

OpenAI internalizes reasoning (o-series: protocol into weights, not
inspectable). Anthropic externalizes orchestration (code-exec, context
engineering: program around the model). TAHOE externalizes *reasoning itself*
as a typed language the model learns, executes on itself, and finally
internalizes — with verifiable rewards at every stage.
