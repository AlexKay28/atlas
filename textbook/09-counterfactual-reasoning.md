# Counterfactual Reasoning

## Purpose

Counterfactual reasoning asks "what would have happened if X had not occurred?"
This is Pearl's do-calculus — reasoning about interventions and alternative worlds.
TAHOE handles counterfactuals through a protocol over existing commands rather
than new syntax.

## When to Use Counterfactual Reasoning

Use when:
- Root cause analysis requires reasoning about what DIDN'T happen
- Causal effect estimation is needed (not just correlation)
- "Would the system have failed anyway?" questions arise
- Decision evaluation requires comparing actual vs counterfactual outcomes

## Do-Calculus as Protocol Composition

Pearl's do-calculus distinguishes **observation** (seeing) from **intervention**
(doing). In TAHOE, the `do(X)` operator is not a new grammar token — it is the
act of feeding a **hypothetical premise** into `hypothesize` instead of the
factual one. The existing typed-ref flow enforces the distinction: factual
evidence (`E.observed`) and counterfactual hypothesis (`H.counterfactual`) are
different types, preventing silent substitution.

The counterfactual protocol reduces to three existing commands:

```text
Q.counterfactual + H.causal_model + E.observed
  -> step.cf_hyp: DO hypothesize(question = Q.counterfactual, evidence = [E.observed, H.causal_model]) -> H.counterfactual
  -> step.cf_test: DO challenge(claim = H.counterfactual, evidence = E.observed) -> R.cf_result
  -> step.cf_verify: DO verify(goal = Q.counterfactual, evidence = [R.cf_result]) -> V.cf_verdict
  -> OUT
```

### Why no new operator?

- `do(X)` is semantics, not syntax: the intervention is expressed by choosing
  what to feed into `hypothesize` — the *question* encodes the counterfactual
  premise ("What if X had not occurred?") and the *evidence* carries the
  factual observations plus the causal model.
- Typed refs enforce the distinction: `H.counterfactual` (hypothesis) cannot
  be confused with `E.observed` (fact) or `V.cf_verdict` (verified result).
- `challenge` stress-tests the counterfactual against factual evidence,
  playing the role of Pearl's "refutation test" — if the counterfactual
  contradicts observed data, the challenge surfaces the contradiction.
- `verify` closes the loop with an acceptance verdict on the original
  counterfactual question.

## Counterfactual Protocol

Required artifacts:
```text
Q.counterfactual + H.causal_model + E.observed -> H.counterfactual -> R.cf_result -> V.cf_verdict -> OUT
```

Procedure:
1. State the counterfactual question: what would have happened under a different
   condition? This is the `do(X)` intervention — the premise is hypothetical,
   not observed.
2. Identify the causal model (`H.causal_model`) that explains the observed
   outcome. This model is the structural equation Pearl's do-calculus operates
   on.
3. Form the counterfactual hypothesis (`H.counterfactual`) by feeding the
   counterfactual question and the causal model into `hypothesize`. The
   hypothesis must be falsifiable.
4. Challenge the counterfactual hypothesis against factual evidence
   (`E.observed`) using `challenge`. If the counterfactual contradicts what
   was actually observed, the challenge surfaces counterevidence.
5. Verify the counterfactual question against the challenge result using
   `verify`. This produces a typed verdict (`V.cf_verdict`) with a status.
6. Return the verdict, its basis, and unknowns.

### Worked Example

```text
G.counterfactual: Would latency be normal if the cache had not failed?
H.causal_model: Cache failure -> stale responses -> increased latency
E.observed: p95 = 4.2s during cache failure
H.counterfactual: Without cache failure, stale responses would not occur
V.simulation: Run load test with healthy cache at same traffic level
F.what_if: Simulated p95 with healthy cache = 0.8s
OUT.result: Yes, latency would be normal (0.8s vs 4.2s observed). Confidence: medium (simulation, not live).
OUT.basis: V.simulation
OUT.unknowns: Real traffic patterns may differ from simulation
```

### Executable TAHOE Program

The above reasoning expressed as a runnable TAHOE program:

```text
PROGRAM counterfactual VERSION 1.0

INPUT
    Q.counterfactual = "Would latency be normal if the cache had not failed?"
    H.causal_model = "Cache failure -> stale responses -> increased latency"
    E.observed = "p95 = 4.2s during cache failure"

step.cf_hyp: DO hypothesize(question = Q.counterfactual, evidence = [E.observed, H.causal_model]) -> H.counterfactual
step.cf_test: DO challenge(claim = H.counterfactual, evidence = E.observed) -> R.cf_result
step.cf_verify: DO verify(goal = Q.counterfactual, evidence = [R.cf_result]) -> V.cf_verdict
DONE V.cf_verdict == "verified"

RETURN V.cf_verdict
```

## Relationship to Existing Commands

Counterfactual reasoning uses existing commands in a new protocol shape:
- `hypothesize`: Creates the counterfactual hypothesis (`H.counterfactual`)
  from the counterfactual question and the causal model. The `do(X)`
  intervention is the choice of question — not a new syntax token.
- `challenge`: Stress-tests the counterfactual hypothesis against factual
  evidence (`E.observed`), surfacing any contradiction between the
  counterfactual world and the observed world.
- `verify`: Closes the loop with a typed verdict (`V.cf_verdict`) on the
  original counterfactual question.

No new syntax is needed — the protocol is a composition of existing commands.
The typed-ref system (`H.*` vs `E.*` vs `V.*`) prevents the counterfactual
hypothesis from being silently treated as a fact.

## DONE Predicates for Counterfactual Verification

A `DONE` predicate can assert properties of the counterfactual verdict,
providing a deterministic gate on the protocol's output:

```text
DONE V.cf_verdict == "verified"
```

This ensures the counterfactual reasoning produced a verified verdict, not
just a hypothesis. If the challenge surfaced a contradiction, the verdict
would differ and the DONE predicate would fail the run.

For asserting that the challenge found no contradiction:

```text
DONE R.cf_result.contradiction == false
```

This asserts that the challenge found no contradiction between the
counterfactual hypothesis and the observed evidence. (Note: when the
result is a dict, compare the full value or use a field-selecting DONE
predicate with a dict-equality check.)

## Failure modes

- Reasoning about counterfactuals without a causal model (just guessing);
- Confusing "what would have happened" with "what should happen" (normative vs descriptive);
- Over-claiming confidence from a single simulation;
- Not testing the causal model itself (the model may be wrong);
- Treating `H.counterfactual` as `E.*` or `F.*` — the typed-ref system prevents
  this, but a programmer may bypass it by skipping the `challenge` step.
