# Reliability-Constrained Model Routing — Solution

## 1. Optimal Tier Assignment (threshold 0.90)

| Job | Tier | Success Probability | Cost |
|-----|------|---------------------|------|
| A   | heavy  | 0.990 | 2.00 |
| B   | focused | 0.940 | 0.90 |
| C   | heavy  | 0.990 | 1.80 |
| D   | heavy  | 0.985 | 1.70 |

**Total cost: 6.40**

**Joint success probability:** 0.990 × 0.940 × 0.990 × 0.985 = **0.907475**

This satisfies the constraint P(all succeed) ≥ 0.90.

## 2. Reproducible Exhaustive Calculation

The calculation script is at `calculate.py` in this run directory. It enumerates all 3⁴ = 81 possible tier assignments (3 tiers for each of 4 jobs), computing for each:

- **Total cost** = sum of the four selected tier costs
- **Joint success probability** = product of the four selected success probabilities

The 81 assignments are sorted by total cost ascending. The first assignment with joint probability ≥ 0.90 is the minimum-cost feasible solution.

### Data (from task table)

```
Job A: small (p=0.82, c=0.20), focused (p=0.95, c=0.80), heavy (p=0.990, c=2.00)
Job B: small (p=0.70, c=0.20), focused (p=0.94, c=0.90), heavy (p=0.995, c=2.40)
Job C: small (p=0.88, c=0.25), focused (p=0.96, c=0.75), heavy (p=0.990, c=1.80)
Job D: small (p=0.75, c=0.15), focused (p=0.93, c=0.70), heavy (p=0.985, c=1.70)
```

### Verification

```
Joint prob = 0.990 × 0.940 × 0.990 × 0.985
           = 0.990 × 0.940 = 0.9306
           = 0.9306 × 0.990 = 0.921294
           = 0.921294 × 0.985 = 0.90747459

Total cost = 2.00 + 0.90 + 1.80 + 1.70 = 6.40
```

Full enumeration output is saved in `calculation_output.txt`.

## 3. Proof of Optimality (threshold 0.90)

All 76 assignments cheaper than cost 6.40 are listed below with their joint
probabilities. **None** has joint probability ≥ 0.90:

| Cost | Joint Prob | Feasible? | Assignment (A,B,C,D) |
|------|-----------|-----------|---------------------|
| 0.80 | 0.378840 | no | small, small, small, small |
| 1.30 | 0.413280 | no | small, small, focused, small |
| 1.35 | 0.469762 | no | small, small, small, focused |
| 1.40 | 0.438900 | no | focused, small, small, small |
| 1.50 | 0.508728 | no | small, focused, small, small |
| 1.85 | 0.512467 | no | small, small, focused, focused |
| 1.90 | 0.478800 | no | focused, small, focused, small |
| 1.95 | 0.544236 | no | focused, small, small, focused |
| 2.00 | 0.554976 | no | small, focused, focused, small |
| 2.05 | 0.630823 | no | small, focused, small, focused |
| 2.10 | 0.589380 | no | focused, focused, small, small |
| 2.35 | 0.497543 | no | small, small, small, heavy |
| 2.35 | 0.426195 | no | small, small, heavy, small |
| 2.45 | 0.593712 | no | focused, small, focused, focused |
| 2.55 | 0.688170 | no | small, focused, focused, focused |
| 2.60 | 0.642960 | no | focused, focused, focused, small |
| 2.60 | 0.457380 | no | heavy, small, small, small |
| 2.65 | 0.730831 | no | focused, focused, small, focused |
| 2.85 | 0.542774 | no | small, small, focused, heavy |
| 2.90 | 0.528482 | no | small, small, heavy, focused |
| 2.95 | 0.493762 | no | focused, small, heavy, small |
| 2.95 | 0.576422 | no | focused, small, small, heavy |
| 3.00 | 0.538494 | no | small, heavy, small, small |
| 3.05 | 0.668129 | no | small, focused, small, heavy |
| 3.05 | 0.572319 | no | small, focused, heavy, small |
| 3.10 | 0.498960 | no | heavy, small, focused, small |
| 3.15 | 0.797270 | no | focused, focused, focused, focused |
| 3.15 | 0.567151 | no | heavy, small, small, focused |
| 3.30 | 0.614196 | no | heavy, focused, small, small |
| 3.45 | 0.628824 | no | focused, small, focused, heavy |
| 3.50 | 0.587448 | no | small, heavy, focused, small |
| 3.50 | 0.612265 | no | focused, small, heavy, focused |
| 3.55 | 0.728868 | no | small, focused, focused, heavy |
| 3.55 | 0.667733 | no | small, heavy, small, focused |
| 3.60 | 0.623865 | no | focused, heavy, small, small |
| 3.60 | 0.709676 | no | small, focused, heavy, focused |
| 3.65 | 0.663052 | no | focused, focused, heavy, small |
| 3.65 | 0.774052 | no | focused, focused, small, heavy |
| 3.65 | 0.618710 | no | heavy, small, focused, focused |
| 3.80 | 0.670032 | no | heavy, focused, focused, small |
| 3.85 | 0.761603 | no | heavy, focused, small, focused |
| 3.90 | 0.559736 | no | small, small, heavy, heavy |
| 4.05 | 0.728436 | no | small, heavy, focused, focused |
| 4.10 | 0.680580 | no | focused, heavy, focused, small |
| 4.15 | 0.844421 | no | focused, focused, focused, heavy |
| 4.15 | 0.773593 | no | focused, heavy, small, focused |
| 4.15 | 0.600692 | no | heavy, small, small, heavy |
| 4.15 | 0.514552 | no | heavy, small, heavy, small |
| 4.20 | 0.822185 | no | focused, focused, heavy, focused |
| 4.35 | 0.830840 | no | heavy, focused, focused, focused |
| 4.50 | 0.648475 | no | focused, small, heavy, heavy |
| 4.55 | 0.707222 | no | small, heavy, small, heavy |
| 4.55 | 0.605806 | no | small, heavy, heavy, small |
| 4.60 | 0.751646 | no | small, focused, heavy, heavy |
| 4.65 | 0.843919 | no | focused, heavy, focused, focused |
| 4.65 | 0.655301 | no | heavy, small, focused, heavy |
| 4.70 | 0.638045 | no | heavy, small, heavy, focused |
| 4.80 | 0.650133 | no | heavy, heavy, small, small |
| 4.85 | 0.806644 | no | heavy, focused, small, heavy |
| 4.85 | 0.690970 | no | heavy, focused, heavy, small |
| 5.05 | 0.771515 | no | small, heavy, focused, heavy |
| 5.10 | 0.751199 | no | small, heavy, heavy, focused |
| 5.15 | 0.819343 | no | focused, heavy, small, heavy |
| 5.15 | 0.701848 | no | focused, heavy, heavy, small |
| 5.20 | 0.870809 | no | focused, focused, heavy, heavy |
| 5.30 | 0.709236 | no | heavy, heavy, focused, small |
| 5.35 | 0.879975 | no | heavy, focused, focused, heavy |
| 5.35 | 0.806165 | no | heavy, heavy, small, focused |
| 5.40 | 0.856803 | no | heavy, focused, heavy, focused |
| 5.65 | 0.893828 | no | focused, heavy, focused, heavy |
| 5.70 | 0.870292 | no | focused, heavy, heavy, focused |
| 5.70 | 0.675779 | no | heavy, small, heavy, heavy |
| 5.85 | 0.879453 | no | heavy, heavy, focused, focused |
| 6.10 | 0.795625 | no | small, heavy, heavy, heavy |
| 6.35 | 0.853841 | no | heavy, heavy, small, heavy |
| 6.35 | 0.731400 | no | heavy, heavy, heavy, small |

The closest infeasible competitor costs 5.65 with joint probability 0.893828
(assignment: A=focused, B=heavy, C=focused, D=heavy) — still below 0.90.
The next feasible assignment costs 6.70 (A=focused, B=heavy, C=heavy,
D=heavy, joint prob = 0.921761), which is 0.30 more expensive.

**Therefore no cheaper assignment satisfies the reliability constraint, and
the optimum at cost 6.40 is proven.**

## 4. Cheapest Assignment at Threshold 0.85

| Job | Tier | Success Probability | Cost |
|-----|------|---------------------|------|
| A   | focused | 0.95 | 0.80 |
| B   | focused | 0.94 | 0.90 |
| C   | heavy  | 0.990 | 1.80 |
| D   | heavy  | 0.985 | 1.70 |

**Total cost: 5.20**

**Joint success probability:** 0.95 × 0.94 × 0.990 × 0.985 = **0.870809**

This satisfies P(all succeed) ≥ 0.85. All 64 assignments cheaper than 5.20
have joint probability < 0.85 (the closest is cost 5.15, prob 0.819343, which is still below 0.85; the next feasible at 0.85 is cost 5.20).

## 5. Sensitivity Analysis

### Margin above threshold

The optimum's joint probability is 0.907475, giving a margin of only
**0.007475** above the 0.90 threshold.

### Break points for each selected probability estimate

For each probability in the optimum, the maximum decrease before the joint
probability drops below 0.90 is computed as:

    delta_max = p_i × (1 − 0.90 / P_joint)

where `p_i` is the individual success probability and `P_joint = 0.907475`.

| Job | Tier | p (current) | Max decrease (absolute) | Break point p | Break ratio |
|-----|------|-------------|------------------------|---------------|-------------|
| B   | focused | 0.940 | 0.007742 | 0.932258 | 0.82% |
| D   | heavy  | 0.985 | 0.008113 | 0.976887 | 0.82% |
| A   | heavy  | 0.990 | 0.008154 | 0.981846 | 0.82% |
| C   | heavy  | 0.990 | 0.008154 | 0.981846 | 0.82% |

### Most sensitive estimate

**Job B's focused-tier success probability (0.940)** is the most sensitive
single estimate. It has the smallest absolute break margin: a decrease of
just **0.007742** (from 0.940 to 0.932258) would push the joint probability
below 0.90, invalidating the current optimum.

This is because Job B is the only job assigned to the focused tier (the
others are on heavy), and its probability of 0.940 is the lowest in the
optimal assignment. Although the break ratio is the same (0.82%) for all
four estimates due to the multiplicative structure, the absolute margin is
smallest for Job B.

When the optimum breaks, the next feasible assignment is
(A=focused, B=heavy, C=heavy, D=heavy) at cost 6.70 with joint probability
0.921761 — a cost increase of 0.30.
