# Plan Reformulation

## Purpose

Plans are based on assumptions about the optimal path. During execution, evidence
may invalidate those assumptions. REFORMULATE provides a structured way to exit a
failing plan, diagnose what went wrong, revise invalidated refs, and continue
with a new plan from the current execution point — without starting from scratch.

## When to Reformulate

Reformulate when:
- A hypothesis is falsified and the decision tree changes
- A search returns no results and the strategy can't work
- An unexpected constraint appears
- A step produces evidence contradicting the plan's premise
- The environment changed between planning and execution

Do NOT reformulate for:
- Transient failures (use retry instead)
- Expected iteration (use LOOP instead)
- Tasks that are simply hard (use challenge/decompose)

## REFORMULATE Protocol

Required artifacts:
```
E.failure + IF condition -> REFORMULATE -> R.diagnosis -> revised refs -> G.new_plan -> CONTINUE
```

Procedure:
1. Detect: a DONE predicate fails, or evidence contradicts a plan assumption.
2. Diagnose: run challenge or review to identify what went wrong.
3. Revise: retire invalidated refs (history preserved), create new ones.
4. Replan: decompose the goal with the new evidence into a new sub-plan.
5. Continue: resume execution under the new plan.

## Constraints

- Max 3 reformulations per run (configurable)
- The new plan must satisfy the same DONE predicates as the original (goal doesn't change)
- DIAGNOSE is mandatory — silent replanning is forbidden
- The reformulated plan is sealed (content-addressed)
- All committed evidence, findings, and decisions are preserved

## Example

```text
step.test: DO test_hypothesis(hypothesis = H.cause) -> E.test
DONE E.test.status == "confirmed"

IF E.test.status == "falsified"
  REFORMULATE
    DIAGNOSE: DO challenge(claim = H.cause, evidence = E.test) -> R.why
    REVISE: H.cause -> H.alt_cause
    REPLAN: DO decompose(goal = G.goal, evidence = [E.test, R.why]) -> G.plan2
    CONTINUE: G.plan2
```

## Relationship to Other Constructs

| Construct | When to use |
|---|---|
| LOOP | Expected iteration (refine until convergence) |
| RETRY | Transient failure (same plan, try again) |
| STOP | Terminal failure (cannot continue) |
| REFORMULATE | Plan itself was wrong (revise and continue) |

## Failure modes

- Reformulating without diagnosing (guessing what went wrong)
- Reformulating too often (hitting the 3-reformulation cap without progress)
- Losing committed evidence during reformulation (the new plan must inherit state)
- Reformulating when retry would suffice (transient vs structural failure)
