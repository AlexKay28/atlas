# Quality Control and Safety

## Purpose

Compression and structure can make weak reasoning look precise. This guide defines the
checks required to preserve effectiveness and quality while reducing conversation size.

## Two Independent Validation Questions

Always distinguish:

1. **Is the graph well formed?** IDs, links, required nodes, and cycles are valid.
2. **Is the conclusion well supported?** Evidence, interpretation, and real-world
   behavior justify the result.

A valid graph can still contain false premises. Passing syntax validation never proves
the conclusion.

## Evidence Quality Ladder

Rank evidence by directness and relevance, not by volume:

| Level | Evidence | Typical use |
| --- | --- | --- |
| E0 | Unsupported assertion | Hypothesis generation only |
| E1 | Anecdote or single example | Identify possible behavior |
| E2 | Reproducible observation | Support a scoped claim |
| E3 | Controlled comparison or authoritative source | Support a decision |
| E4 | Independent replication across relevant conditions | High-confidence decision |

Required evidence rises with impact, irreversibility, and uncertainty. Not every routine
task needs E4 evidence.

## Source Rules

- Cite the source closest to the original observation.
- Preserve exact versions, dates, inputs, units, and environment when they matter.
- Distinguish source content from interpretation.
- Prefer direct inspection over a summary when wording or implementation is decisive.
- Record material disagreement among credible sources.
- Do not invent citations or imply inspection that did not occur.

## Assumption Budget

Every unresolved assumption adds failure risk. For each material assumption:

```text
assumption_risk = probability_wrong * impact_if_wrong
```

Test high-risk assumptions. Explicitly accept low-risk assumptions. Do not spend time
validating assumptions that cannot change the result.

## Confidence Rules

Confidence is not decoration. Attach it only when its basis is visible.

Confidence should consider:

- quality and coverage of evidence;
- number and importance of unresolved unknowns;
- sensitivity of the decision to assumptions;
- agreement across independent checks;
- whether the relevant environment was tested.

Do not infer numeric precision from a subjective estimate. `confidence=0.7` means an
ordered level of belief, not a measured probability unless calibrated data exists.

## Adversarial Check

Before accepting an important decision, ask:

1. What evidence would make this conclusion false?
2. Which assumption has the largest failure impact?
3. Is there a plausible alternative explanation?
4. Did the evaluation omit an affected user, environment, or boundary?
5. Is the recommendation favored because it is familiar rather than superior?
6. Can the result pass its metric while failing the real goal?

Record only challenges that are plausible and decision-relevant. Endless hypothetical
objections are not rigor.

## Verification Pyramid

Use the cheapest check that gives enough confidence, then escalate:

```text
static inspection -> focused test -> integration test -> real-world trial -> monitoring
```

The check should cover the original success condition, not merely whether the action
completed.

Weak:

```text
V.deploy: Deployment command exited successfully.
```

Strong:

```text
V.release: Deployment completed, target behavior passes, and error rate remains below
the threshold during the observation window.
```

## Decision Quality Gate

Before accepting a non-trivial `D` node, verify:

- the goal is still the correct goal;
- all options satisfy hard constraints;
- materially different alternatives were considered;
- criteria were not retrofitted to the preferred option;
- decisive evidence is linked;
- rejected options have concise reasons;
- uncertainty and downside risk are visible;
- the decision includes a check and reopening condition.

## Action Quality Gate

Every important `X` node should be:

- specific enough that two people interpret it the same way;
- small enough to complete and verify;
- linked to the goal or decision it advances;
- assigned an owner when responsibility is shared;
- bounded by constraints and safety requirements;
- paired with success and failure observations;
- reversible or accompanied by mitigation when possible.

## AI Error Controls

An AI must not:

- convert a likely statement into a fact without evidence;
- claim to have read, tested, or executed something it did not inspect;
- hide unresolved contradictions inside a fluent summary;
- produce invented values to fill a structured field;
- continue confidently when a missing constraint can change the result;
- optimize the requested metric while ignoring the stated goal;
- treat user agreement as verification.

When blocked, it should return:

```text
U.blocker: <missing or conflicting information>
impact: <what could be wrong without it>
Q.resolve: <smallest question or inspection that resolves it>
```

## Human Error Controls

The human should watch for:

- automation bias caused by polished output;
- confirmation bias in option and criterion selection;
- sunk-cost bias when new evidence challenges an existing graph;
- false precision from numeric confidence or weighted tables;
- omission of stakeholders who bear the downside;
- accepting a result because it is concise rather than correct.

## Safety Escalation

Increase rigor when a task affects security, privacy, finances, legal obligations,
health, physical safety, production availability, or irreversible user data.

Critical mode requires:

- explicit affected scope;
- authoritative evidence where available;
- named risks and mitigations;
- independent or redundant verification;
- rollback, containment, or recovery strategy;
- human approval at the appropriate responsibility boundary.

Compression must never remove these controls to meet a token budget.

## Quality-Preserving Stop Rule

Stop when:

- the requested output exists;
- the acceptance check passes;
- no unresolved item exceeds the accepted risk threshold;
- additional analysis is unlikely to change the decision;
- residual uncertainty and monitoring are documented.

Do not stop merely because a plausible answer has been produced.

## Pilot Scorecard

Score each protocol trial from 0 to 2:

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Correctness | Failed | Partly correct | Acceptance passed |
| Traceability | Unsupported | Partial basis | Claims linked to evidence |
| Efficiency | More rework | Similar cost | Less total cost |
| Clarity | Ambiguous | Understandable | Independently actionable |
| Adaptability | Rewrite required | Some reuse | Local graph update only |

Reject a language optimization if it lowers correctness or safety, even when it improves
the token score. Adopt it when repeated trials preserve quality and lower total cost.
