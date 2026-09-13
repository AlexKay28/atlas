# Probabilistic Reasoning

## Purpose

Probability types extend TAHOE's epistemic states with numeric belief levels.
PR.* refs hold values in [0, 1] and represent prior, likelihood, or posterior
probabilities.

## When to Use Probabilistic Reasoning

Use PR.* when:
- A conclusion depends on uncertain evidence weighted by probability
- Bayesian updating is needed (prior + evidence -> posterior)
- Expected value computation requires probability estimates
- A decision threshold is probabilistic ("act if posterior > 0.9")

## PR. Type

| Ref | Meaning | Example |
|---|---|---|
| `PR.prior` | Initial belief before evidence | `PR.prior = 0.3` |
| `PR.likelihood` | P(evidence | hypothesis) | `PR.likelihood = 0.8` |
| `PR.posterior` | Updated belief after evidence | `PR.posterior = 0.55` |
| `PR.contradiction` | P(claim is false | new evidence) | `PR.contradiction = 0.15` |

## Bayesian Update Protocol

Required artifacts:
```
H.hypothesis + PR.prior + E.evidence -> PR.likelihood -> PR.posterior -> V.threshold -> OUT
```

Procedure:
1. State the hypothesis and prior probability.
2. Collect evidence relevant to the hypothesis.
3. Estimate likelihood P(evidence | hypothesis).
4. Compute posterior using Bayes: posterior is proportional to prior times likelihood.
5. Check if posterior exceeds the decision threshold.
6. If not, either collect more evidence or accept the uncertainty.

Example:
```text
G.decide: Decide whether to deploy based on test results.
H.stable: The system is stable under load.
PR.prior = 0.6
E.load_test: Stress test passed at 80% capacity.
PR.likelihood = 0.85
PR.posterior = 0.85
V.threshold: PR.posterior > 0.8
OUT.decision: Deploy — posterior exceeds threshold.
```

Failure modes:
- Using PR.* for subjective confidence without calibration data;
- Confusing PR.prior with A.* (assumption — a prior is numeric, an assumption is not);
- Not updating the prior after new evidence arrives.

## Expected Value Computation

```text
G.invest: Should we invest in optimization X?
PR.success = 0.7
E.gain_if_success = 100000
E.loss_if_fail = 40000
P.expected_value: 0.7 * 100000 - 0.3 * 40000 = 58000
V.threshold: P.expected_value > 50000
OUT.decision: Invest — expected value is positive and above threshold.
```

## Relationship to Confidence

PR.* is NOT the same as confidence metadata:
- `confidence=0.7` is metadata on any ref — a subjective estimate of certainty.
- `PR.posterior = 0.7` is a typed state — it represents a computed probability with a documented basis.

Use PR.* when the probability itself is the output of reasoning. Use confidence
metadata when expressing subjective certainty about a non-probabilistic claim.
