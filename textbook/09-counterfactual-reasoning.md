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

## Counterfactual Protocol

Required artifacts:
```text
Q.counterfactual + H.causal_model + E.observed -> H.counterfactual -> V.simulation -> F.what_if -> OUT
```

Procedure:
1. State the question: what would have happened under a different condition?
2. Identify the causal model (H.*) that explains the observed outcome.
3. Modify the model: replace the actual cause with the counterfactual intervention.
4. Simulate: run the model forward under the modified condition.
5. Compare: what outcome does the modified model predict?
6. Return: the counterfactual finding and its confidence.

Example:
```text
G.counterfactual: Would latency be normal if the cache had not failed?
H.causal_model: Cache failure → stale responses → increased latency
E.observed: p95 = 4.2s during cache failure
H.counterfactual: Without cache failure, stale responses would not occur
V.simulation: Run load test with healthy cache at same traffic level
F.what_if: Simulated p95 with healthy cache = 0.8s
OUT.result: Yes, latency would be normal (0.8s vs 4.2s observed). Confidence: medium (simulation, not live).
OUT.basis: V.simulation
OUT.unknowns: Real traffic patterns may differ from simulation
```

## Relationship to Existing Commands

Counterfactual reasoning uses existing commands in a new protocol shape:
- `hypothesize`: Creates the counterfactual hypothesis (H.counterfactual)
- `test_hypothesis`: Runs the simulation (V.simulation)
- `challenge`: Tests whether the causal model is correct
- `compare`: Compares observed vs counterfactual outcomes

No new syntax is needed — the protocol is a composition of existing commands.

## Failure modes

- Reasoning about counterfactuals without a causal model (just guessing);
- Confusing "what would have happened" with "what should happen" (normative vs descriptive);
- Over-claiming confidence from a single simulation;
- Not testing the causal model itself (the model may be wrong).
