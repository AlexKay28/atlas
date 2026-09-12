# Reusable Reasoning Protocols

## Purpose

A protocol is a reusable graph shape for a class of work. It tells the human and AI
which artifacts must be visible without dictating hidden thought or forcing every task
through the same sequence.

Select one primary protocol per goal. Compose protocols only when the output of one is
the input of another.

## Protocol Selection

| Situation | Protocol |
| --- | --- |
| Need to understand an unfamiliar topic | Explore |
| Need to choose among approaches | Decide |
| Need executable steps | Plan |
| Observed behavior differs from expected behavior | Debug |
| Need to evaluate an artifact | Review |
| Need to test and retain new knowledge | Learn |

## Explore Protocol

Use when the problem space is unclear and immediate commitment would be premature.

Required artifacts:

```text
Q -> CTX -> F/E/A/U -> H or themes -> OUT
```

Procedure:

1. Define the question and why its answer matters.
2. Bound the scope, time horizon, and required confidence.
3. Collect decision-shaping evidence rather than all available information.
4. Separate facts, assumptions, and unknowns.
5. Group observations into competing models or themes.
6. Identify contradictions and high-value unknowns.
7. Return findings, confidence, and the next useful investigation.

Stop when the question can be answered at the required confidence or when the next
evidence costs more than its expected value.

Failure modes:

- collecting information without a decision or question;
- returning a list of facts with no synthesis;
- presenting one interpretation as certain;
- continuing research after the answer is sufficient.

## Decide Protocol

Use for consequential choices with more than one valid approach.

Required artifacts:

```text
G + C + P -> O -> K -> D -> R -> V -> OUT
```

Procedure:

1. State the outcome and decision deadline.
2. Reject options that violate hard constraints.
3. Include the status quo when doing nothing is possible.
4. Create materially different options.
5. Define criteria before scoring options.
6. Compare evidence, trade-offs, reversibility, and uncertainty.
7. Select one option or explicitly defer with a condition for reopening.
8. Record rejected options and decisive reasons.
9. Define risks, mitigations, and a result check.

Compact example:

```text
G.store: Select storage for the event stream.
C.volume: Support 20k writes/second.
P.ops: Prefer existing operational expertise.
O.pg: Partitioned PostgreSQL.
O.kafka: Kafka.
K.scale: Sustained write capacity. weight=critical
K.ops: Team familiarity. weight=high
D.store: Select Kafka. confidence=0.8
D.store -selects-> O.kafka
R.skill: Limited incident-response experience.
X.drill: Run a recovery exercise.
X.drill -mitigates-> R.skill
V.load: Sustain target throughput and complete recovery drill.
```

Failure modes:

- designing criteria after choosing an option;
- listing only the preferred option;
- treating preferences as constraints;
- omitting the cost of reversal.

## Plan Protocol

Use after the outcome is sufficiently clear.

Required artifacts:

```text
G + C + D -> X with depends_on/precedes links -> V -> OUT
```

Procedure:

1. Describe the completed state.
2. Identify deliverables, not categories of activity.
3. Split work at independently verifiable boundaries.
4. Link real dependencies; do not imply order merely by list position.
5. Put the highest-risk validation before expensive implementation.
6. Assign owner, status, and completion check where useful.
7. Identify the critical path and parallel work.
8. End with the next executable action, not a vague phase.

Good action:

```text
X.fixture: Add fixtures for valid, invalid, and cyclic graphs.
V.fixture: Each expected parser outcome is asserted.
```

Weak action:

```text
X.quality: Improve quality.
```

Failure modes:

- actions too large to verify;
- sequence inferred from formatting rather than links;
- dependencies added for convenience rather than necessity;
- testing deferred until all implementation is complete.

## Debug Protocol

Use when observed and expected behavior differ. Do not edit before establishing evidence
for a cause when the issue is non-trivial.

Required artifacts:

```text
Q.failure + F.expected + E.observed -> H -> V -> D/X -> V.regression -> OUT
```

Procedure:

1. State expected and observed behavior precisely.
2. Reproduce the failure or explain why reproduction is impossible.
3. Preserve exact errors, environment, version, and input.
4. Identify the smallest failing boundary.
5. Generate hypotheses that make different predictions.
6. Test the cheapest discriminating prediction first.
7. Record the supported root cause.
8. Apply the smallest fix addressing that cause.
9. Verify the original reproduction and relevant regressions.

Failure modes:

- changing code before reproducing or inspecting evidence;
- confusing correlation with cause;
- testing several hypotheses with one uncontrolled change;
- accepting disappearance of the symptom without a regression check.

## Review Protocol

Use to find defects and decision risks in an artifact.

Required artifacts:

```text
CTX + C + intended behavior -> E + R -> D/X -> OUT
```

Procedure:

1. Identify the artifact's intended behavior and boundaries.
2. Inspect changed or decision-relevant material first.
3. Trace behavior across interfaces and failure paths.
4. Compare implementation with constraints and existing contracts.
5. Report findings ordered by severity and likelihood.
6. Attach evidence and exact location to each finding.
7. Separate blocking defects from optional improvements.
8. State testing gaps and residual risks when no defect is found.

A review finding should contain:

```text
R.<id>: <observable failure and affected scenario>
E.<id>: <location or evidence>
X.<id>: <smallest corrective direction>
```

Failure modes:

- summarizing before looking for defects;
- reporting style preferences as correctness issues;
- identifying a theoretical risk with no reachable scenario;
- saying "no issues" without noting untested boundaries.

## Learn Protocol

Use when the goal is transferable understanding rather than a one-time answer.

Required artifacts:

```text
Q -> H/current model -> E/example -> V.recall + V.transfer -> F/U -> OUT
```

Procedure:

1. State what capability should exist after learning.
2. Record the current model or prediction before reading the answer.
3. Study the minimum explanation that resolves the gap.
4. Produce an example without copying.
5. Test recall after a delay.
6. Test transfer on a different problem.
7. Keep failed predictions and corrections as useful evidence.

Failure modes:

- mistaking recognition for understanding;
- collecting notes without retrieval practice;
- memorizing one example rather than testing transfer;
- requesting exhaustive explanations before locating the gap.

## Protocol Composition

Composition must name the handoff:

```text
explore.OUT.findings -> decide.CTX
decide.D.choice -> plan.D
plan.X.implementation -> review.CTX
debug.D.root_cause -> plan.G.fix
```

Do not run all protocols by default. Each protocol must reduce a specific uncertainty or
produce an artifact needed by the next one.

## Protocol Exit Contract

Every protocol returns:

```text
OUT.result: requested artifact
OUT.basis: decisive evidence or criteria
OUT.unknowns: unresolved items that could change the result
OUT.next: smallest useful next action, or stop
OUT.check: acceptance result or verification method
```

Fields with no meaningful content may be omitted, except `result` and `check`.
