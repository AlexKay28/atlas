# Reliability-Constrained Model Routing

## Goal

Choose a static model tier for each of four independent atomic jobs. Minimize
total cost while keeping the probability that all jobs succeed at or above
`0.90`.

## Data

Each job receives one attempt. Outcomes are independent. Cost is charged once
regardless of success. A static policy chooses all tiers before execution.

| Job | Small success/cost | Focused success/cost | Heavy success/cost |
| --- | --- | --- | --- |
| A | 0.82 / 0.20 | 0.95 / 0.80 | 0.990 / 2.00 |
| B | 0.70 / 0.20 | 0.94 / 0.90 | 0.995 / 2.40 |
| C | 0.88 / 0.25 | 0.96 / 0.75 | 0.990 / 1.80 |
| D | 0.75 / 0.15 | 0.93 / 0.70 | 0.985 / 1.70 |

## Deliverable

Write `solution.md` containing:

1. The optimal tier assignment, total cost, and joint success probability.
2. A reproducible exhaustive or branch-and-bound calculation.
3. A proof that no cheaper assignment satisfies the reliability constraint.
4. The cheapest assignment if the threshold is changed to `0.85`.
5. A sensitivity analysis identifying the single probability estimate whose
   small decrease is most likely to change the `0.90` optimum.

## Constraints

- Keep full precision during search; round only displayed results.
- Do not assume retries, correlations, dynamic escalation, or volume discounts.
- Put any calculation script inside the run directory, not elsewhere.
- Do not edit this task file.

## Acceptance

- Every reported assignment is independently reproducible.
- Feasibility uses the product of all four selected success probabilities.
- Optimality is established against all cheaper assignments, not asserted.
- Sensitivity reasoning includes a numerical break point or margin.
