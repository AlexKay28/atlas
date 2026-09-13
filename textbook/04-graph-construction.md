# Graph Construction Rules

## Purpose

The graph is a compact external model of a problem. It makes dependencies, evidence,
choices, and checks visible. It should contain enough structure to support action and
revision, but no structure added only for visual completeness.

## Construction Procedure

Build graphs in five passes:

1. **Anchor:** add the primary `G` or `Q` and required `OUT`.
2. **Bound:** add hard `C`, relevant `P`, and essential `CTX`.
3. **Model:** add `F`, `E`, `A`, `H`, `U`, and their links.
4. **Commit:** add `O`, `K`, `D`, `R`, and executable `X` nodes.
5. **Close:** add `V`, remove irrelevant nodes, and validate references.

Do not begin by converting every sentence into a node. Begin with the outcome and add
only concepts needed to support it.

## Node Rules

### One Claim per Node

A node should be independently testable, revisable, or referenceable.

Bad:

```text
F.system: The system is slow and unreliable because the database is overloaded.
```

Better:

```text
F.latency: p95 latency is 4.2 seconds.
F.errors: Error rate is 3.1%.
H.database: Database saturation causes the latency and errors.
```

### Type by Epistemic Role

Choose type based on how the statement is known, not grammar:

- use `E` for raw observations or sources;
- use `F` for observations currently accepted as true;
- use `A` for an unverified premise temporarily relied upon;
- use `H` for an explanation that can be tested;
- use `U` for a gap that remains unresolved.

### Stable Identity

Keep an identifier while wording changes but meaning remains. Create a new identifier
when the concept changes. Retire obsolete nodes rather than silently reusing their IDs.

Good identifiers are short and semantic:

```text
G.release
C.compatibility
H.memory_leak
V.rollback
```

Avoid positional identifiers such as `item7`, which become meaningless after edits.

### Operational Content

Write content that can guide a decision or check. Prefer quantities, boundaries, and
observable behavior over adjectives.

Weak: `C.fast: Must be fast.`

Strong: `C.latency: p95 must remain below 300 ms at 1,000 requests/second.`

## Link Rules

### Direction Must Read as a Sentence

```text
E.profile -supports-> H.database
X.index -mitigates-> R.latency
D.storage -selects-> O.kafka
V.load -tests-> H.capacity
```

Read each as "source link target." Reverse a link if that sentence is false.

### Use the Narrowest Valid Link

Prefer `tests`, `contradicts`, or `constrains` over a vague association. The core does
not include `relates_to` because it communicates no useful operation.

### Do Not Encode Sequence Accidentally

Visual or textual order does not imply execution order. Use `precedes` only when order
matters and `depends_on` only when the target is genuinely required.

```text
X.deploy -depends_on-> X.test
X.test -precedes-> X.deploy
```

Usually one of these links is enough. Use both only if consumers require both dependency
and explicit schedule semantics.

### Evidence Can Support More Than One Claim

Reuse the evidence node instead of duplicating its content:

```text
E.trace -supports-> H.timeout
E.trace -contradicts-> H.auth
```

### Record Decision Traceability

A decision should link to the selected option and decisive criteria or evidence:

```text
D.cache -selects-> O.redis
D.cache -rejects-> O.local
D.cache -derived_from-> K.consistency
D.cache -derived_from-> E.load_test
```

## Subgraphs and Boundaries

Split a graph when:

- a region has a separate goal and output;
- it can be reused as a generic protocol;
- it changes at a different rate from the parent graph;
- it contains domain detail most consumers do not need;
- its ownership or access boundary differs.

Connect subgraphs through explicit input and output nodes. Do not rely on hidden shared
context.

## Cycles and Iteration

Cycles in evidence refinement can be useful. Cycles in dependencies can deadlock.

Every intentional loop must declare:

```text
LOOP refine
  ENTRY V.result == "initial"
  WHILE count(U.high_impact) > 0
  PROGRESS count(U.high_impact) decreases
  MAX 3
  EXIT V.acceptance.status == "passed"
  EXHAUSTED STOP unresolved(U.high_impact)
  step.improve: DO challenge(claim = V.result) -> R.gap
  step.fix: DO edit(intent = R.gap) -> ART.fix
  step.retest: DO test(target = ART.fix) -> V.result
```

The normative executable form is defined in
[Language and State](../spec/01-language-and-state.md). Never leave an unbounded
`depends_on` cycle.

## Graph Normalization

Before sharing a graph:

1. Merge duplicate nodes with identical meaning.
2. Split nodes containing multiple independently changeable claims.
3. Replace vague links with controlled link types.
4. Remove orphan nodes that cannot affect the goal or output.
5. Resolve dangling references.
6. Mark contradictions as resolved, accepted risk, or open unknown.
7. Ensure actions have checks.
8. Ensure decisions retain selected and rejected options where relevant.

## Minimal Graph Patterns

### Direct Task

```text
G.result -> X.action -> V.check -> OUT.result
```

### Evidence-Based Claim

```text
E.source -supports-> H.claim
V.test -tests-> H.claim
H.claim -answers-> Q.question
```

### Constrained Decision

```text
C.limit -constrains-> O.a
C.limit -constrains-> O.b
K.value -> D.choice -selects-> O.b
```

### Risk-Controlled Action

```text
X.rollback -mitigates-> R.failure
V.canary -tests-> X.deploy
```

## Validation Levels

| Level | Checks |
| --- | --- |
| Syntax | Node shape, link shape, known vocabulary |
| Reference | Unique IDs and no dangling links |
| Structural | Required nodes, no invalid dependency cycles |
| Protocol | Required shape for explore, decide, plan, debug, review, or learn |
| Semantic | Constraints, claims, and checks are meaningful to a human reviewer |

Software can reliably automate the first three levels. Protocol and semantic validation
will still require contextual judgment.

## When Not to Use a Graph

Use ordinary language when the task is:

- a single factual question with little ambiguity;
- a reversible action with an obvious check;
- social or creative conversation where structure is not the goal;
- shorter to perform than to model;
- unlikely to be revisited or composed with other work.

The graph is an efficiency mechanism, not a ceremony.
