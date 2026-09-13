# TAHOE Reasoning Analysis

> Scoring functions for evaluating reasoning trajectories against TAHOE language
> patterns. Used for RL reward signals and iterative quality improvement.

## Purpose

When a model reasons in TAHOE, its output can be scored against the language's
protocols, rules, and quality criteria. This produces:

1. **Protocol adherence** — did the model use the right protocol for the task?
2. **Typed ref discipline** — did it distinguish facts from hypotheses?
3. **Verification quality** — did it check its answer before returning?
4. **Token efficiency** — did it avoid narrative and use concrete values?
5. **Completeness** — did it produce all required artifacts for the protocol?

## Scoring

Each trajectory receives a score from 0.0 to 1.0:

| Component | Weight | What it measures |
|---|---|---|
| Protocol match | 0.20 | Right protocol selected for task type |
| Ref usage | 0.15 | Typed refs used correctly (G/C/E/H/V/OUT) |
| Verification | 0.20 | DONE predicate present and checked |
| Token efficiency | 0.15 | Output tokens / answer tokens ratio |
| Completeness | 0.15 | All protocol artifacts present |
| Answer correctness | 0.15 | Final answer matches expected |

## Model judge

In addition to programmatic scoring, a second model can judge the trajectory
quality by reading the reasoning and scoring it on:

- Clarity of reasoning chain
- Absence of unsupported claims
- Proper constraint handling
- Whether the verification step would catch errors

This dual scoring (programmatic + model judge) enables iterative improvement:
the model judge identifies weaknesses that programmatic rules can't catch.
