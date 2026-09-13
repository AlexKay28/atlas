# Smart Thinking Rules

## Purpose

These rules define how to turn an unclear request into a reliable result. They optimize
for correctness, speed, and cognitive clarity together. They do not prescribe hidden
internal reasoning. They prescribe visible artifacts that a person and an AI can check.

## The Core Equation

Better thinking is not more thinking. It is spending attention where a mistake would
change the outcome:

```text
thinking_value = decision_impact * uncertainty_reduced / effort
```

Use more analysis when impact and uncertainty are high. Use a direct action when the
task is reversible, low-risk, and easy to verify.

## Rule 1: Name the Outcome Before the Method

Start with the state that should be true after the work, not the activity to perform.

Weak:

```text
Analyze our API design.
```

Strong:

```text
G.api: Decide whether the API is safe to release.
OUT.review: Blocking defects, evidence, and smallest fixes.
V.release: No unresolved critical compatibility or security risk.
```

Why: an activity can continue indefinitely; an outcome supplies a stopping condition.

## Rule 2: Separate Hard Constraints from Preferences

A constraint invalidates an option. A preference ranks otherwise valid options.

```text
C.deadline: Must ship by Friday.
C.privacy: Customer data must not leave the private network.
PF.style: Prefer fewer dependencies.
PF.cost: Prefer lower operating cost.
```

Never sacrifice a constraint to improve a preference unless a decision explicitly
changes the constraint.

## Rule 3: Find the Decision-Shaping Facts

Include a fact only if changing it could change an option, decision, action, or check.
This is the relevance test:

```text
if remove(fact) cannot change(result): omit(fact)
```

Background that is interesting but cannot affect the result belongs outside the active
context.

## Rule 4: Distinguish Knowledge States

Do not write every statement as if it were equally true.

```text
F.observed: The process exited with code 137.
E.log: Kernel log reports an out-of-memory kill.
A.limit: The container memory limit is 2 GiB.
H.cause: Input expansion exceeded the memory limit.
U.volume: Peak input size is not yet measured.
```

This prevents assumptions from silently becoming facts.

## Rule 5: Resolve the Highest-Value Unknown First

Rank unknowns by their ability to change the decision:

```text
information_value = probability_of_change * impact_of_change / cost_to_learn
```

Test the unknown with the highest information value, not the unknown that is easiest or
most interesting.

## Rule 6: Generate Alternatives Before Commitment

For consequential decisions, produce at least two genuinely different options. A
cosmetic variation is not an alternative.

```text
O.patch: Repair the current design.
O.replace: Replace the component.
O.defer: Keep the current behavior and defer the decision.
```

Include the status quo when it is a real choice. Premature commitment causes later
evidence to be interpreted defensively.

## Rule 7: Compare Options Using Explicit Criteria

Criteria should be chosen before ranking options. Otherwise the criteria may be changed
to justify a preferred answer.

```text
K.correctness: Meets all acceptance conditions. weight=critical
K.reversibility: Easy to undo if evidence changes. weight=high
K.time: Can be completed this week. weight=medium
```

Reject any option that violates a constraint before comparing preferences.

## Rule 8: Prefer Reversible Steps Under Uncertainty

When two options are similarly useful, choose the one that preserves future choices.
Use a small experiment when it can cheaply replace speculation with evidence.

```text
X.probe: Test the migration on 1% of traffic.
V.probe: Error rate and latency remain within release limits.
```

Irreversible actions require stronger evidence and a rollback or mitigation plan.

## Rule 9: Make Causal Claims Testable

Replace vague explanations with predictions.

Weak:

```text
H.cause: The cache is probably broken.
```

Strong:

```text
H.cause: Stale cache entries cause the incorrect response.
V.cause: Bypassing the cache removes the failure on the same request.
```

A hypothesis without a possible disconfirming observation is not yet useful for action.

## Rule 10: Use the Smallest Action That Produces Evidence

Do not create a complete implementation when a smaller probe can answer the critical
question. Prefer this progression:

```text
inspect -> reproduce -> isolate -> prototype -> implement -> deploy
```

Skip steps when justified by low risk, not merely by impatience.

## Rule 11: Define Completion Before Starting

Every action needs an observable completion test. "Looks good" is not a test.

```text
X.parser: Implement the parser.
V.syntax: All valid examples parse and all invalid fixtures report their exact error.
```

If success cannot be observed, refine the goal or admit that the result is exploratory.

## Rule 12: Stop When Marginal Value Becomes Low

Continue analysis only while another step is likely to change the decision or materially
reduce risk. Stop when:

- the acceptance condition is met;
- all high-impact unknowns are resolved or explicitly accepted;
- the next evidence costs more than the expected decision improvement;
- the time or token budget is reached;
- only low-impact preferences remain undecided.

## Rule 13: Preserve Dissent and Contradictions

Do not erase conflicting evidence to make the graph neat. Record it and decide whether
to resolve it, accept it as risk, or leave the decision open.

```text
E.load_test -supports-> H.capacity_ok
E.incident -contradicts-> H.capacity_ok
U.difference: Why do the environments produce different results?
```

## Rule 14: Update Locally, Not Globally

When evidence changes, revise only the nodes that depend on it. Stable identifiers and
links make this possible. Avoid rewriting the entire explanation, which wastes tokens
and can introduce accidental changes.

## Rule 15: Match Rigor to Consequence

Use three operating levels:

| Level | Suitable for | Required structure |
| --- | --- | --- |
| Fast | Reversible, low-impact task | `G`, `OUT`, optional `V` |
| Standard | Normal professional work | `G`, `C`, relevant facts, action, `V` |
| Critical | Expensive, unsafe, or irreversible | evidence, alternatives, risks, decision, independent checks |

Do not apply critical-process overhead to trivial work. Do not use fast mode for a
decision whose failure is difficult to reverse.

## Compact Checklist

Before asking the AI:

- Is the desired outcome observable?
- Are constraints separated from preferences?
- Which facts can actually change the result?
- Which statements are assumptions or unknowns?
- What output is needed, and what is explicitly not needed?

Before accepting the result:

- Were alternatives considered when the decision mattered?
- Does the evidence support the claims?
- Is the next action small and executable?
- Is there an observable verification step?
- Would another analysis turn probably change the result?
