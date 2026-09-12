# Completeness and Conformance

- Status: Draft 0.1
- Claim: complete by composition for bounded knowledge-work programs

## Meaning of Completeness

The language does not need one primitive for every profession or technology. It is
complete for the project when bounded work can be represented as a composition of:

```text
frame -> acquire -> transform -> model -> reason/calculate
      -> choose/design -> change -> check -> communicate -> revise
```

A representation is incomplete if it requires a worker to infer hidden control flow,
perform multiple effect classes in one command, invent a completion condition, or mutate
unreferenced global state.

## Developer Work Matrix

| Work pattern | Typical composition | Required proof |
| --- | --- | --- |
| Clarify a request | `define -> AWAIT -> revise` | Goal, constraints, output, unknowns |
| Open research | `decompose -> search -> fetch -> read -> extract -> synthesize -> report` | Source coverage and unresolved gaps |
| Targeted lookup | `locate/search -> fetch/read -> verify -> report` | Exact source and scoped answer |
| Repository exploration | `list/search -> read -> trace -> summarize` | Paths, symbols, and call/data path |
| Log investigation | `locate -> read -> extract -> correlate -> hypothesize` | Exact errors, times, and environment |
| Causal reasoning | `observe -> hypothesize -> test_hypothesis -> challenge -> choose` | Distinguishing prediction and evidence |
| Compare alternatives | `define -> compare -> rank -> challenge -> choose` | Constraints, criteria, trade-offs |
| Arithmetic | `define -> calculate -> check` | Expression, units, precision |
| Statistical analysis | `sample/read -> normalize -> aggregate -> estimate -> verify` | Population, assumptions, uncertainty |
| Symbolic math | `define -> derive/solve -> prove/check` | Valid derivation or counterexample |
| Simulation | `define -> simulate -> aggregate -> compare -> report` | Model, parameters, seed, sensitivity |
| Metric definition | `define -> verify -> accept` | Formula, units, population, window |
| Metric investigation | `observe -> aggregate -> diff -> correlate -> hypothesize -> test` | Baseline and causal limits |
| Benchmark | `define -> benchmark -> aggregate -> compare -> report` | Controlled environment and variance |
| Software design | `define -> search/read -> design -> challenge -> review -> choose` | Interfaces, invariants, risks, checks |
| Implementation | `plan_steps -> read -> edit/create -> test -> review -> verify` | Patch and acceptance tests |
| Refactoring | `trace -> test -> edit -> test -> diff -> verify` | Behavior preserved and scope bounded |
| Debugging | `reproduce -> observe/read -> hypothesize -> test_hypothesis -> edit -> test -> verify` | Root cause and regression check |
| Code review | `diff/read -> trace -> review -> report` | Reachable failure scenarios and locations |
| Build/package | `configure -> run -> check -> report` | Exit, produced artifacts, reproducibility |
| Deployment | `plan_steps -> APPROVE -> configure/run -> monitor -> verify` | Intent-bound approval and health window |
| Migration | `sample -> migrate -> aggregate/check -> verify` | Counts, invariants, rollback or forward fix |
| System health | `observe -> aggregate -> compare -> correlate -> report/monitor` | Time window, units, gaps, thresholds |
| Incident response | `observe -> define -> choose -> APPROVE -> run -> monitor -> revise` | Containment, evidence, timeline, recovery |
| Documentation | `read -> synthesize -> edit/create -> review -> report` | Accuracy, audience, links, freshness |
| Planning | `decompose -> compare -> choose -> plan_steps -> challenge` | Dependencies, owners, checks, risks |
| Prioritization | `define -> aggregate -> rank -> challenge -> choose` | Criteria, weights, uncertainty |
| Learning | `define -> read -> explain -> test -> revise -> accept` | Recall and transfer, not recognition |

## Atomicity Conformance

Every invocation must pass:

1. one principal transformation;
2. one effect class;
3. bounded inputs and outputs;
4. declared preconditions and effects;
5. one observable completion predicate;
6. typed failures;
7. evidence appropriate to impact;
8. idempotency or explicit non-repeatability;
9. no hidden child-agent or tool dispatch outside declared capability;
10. no global state mutation outside returned delta;
11. one session-ledger task binding, absent only for coordinator bookkeeping.

## Program Conformance

A program must pass:

- grammar and reference validation;
- every command resolves to a pinned complete contract;
- every protocol call resolves and has bounded recursion;
- all branches terminate or join;
- every loop has progress, bound, success exit, and exhaustion exit;
- fan-out is bounded and join semantics are explicit;
- every returned reference exists on its terminal path;
- every consequential effect has approval and compensation policy;
- the final validator tests the original goal;
- budgets and permissions are sufficient but least-privileged.

## Reference Program A: Research

```text
PROGRAM research_choice VERSION 0.1
INPUT
  Q.choice = "Which option satisfies the target constraints?"
  C.sources = "Use primary or authoritative sources"

step.parts: DO decompose(goal = Q.choice, limit = 5) -> Q.parts
SCATTER Q.part IN Q.parts MAX 5
  step.search: DO search(query = Q.part, scope = "web", limit = 8) -> E.urls[Q.part]
  step.fetch: DO fetch(resources = E.urls[Q.part]) -> ART.sources[Q.part]
  step.extract: DO extract(artifacts = ART.sources[Q.part], schema = "claim.v1") -> E.claims[Q.part]
GATHER step.extract AS E.all USING all
step.model: DO synthesize(findings = E.all) -> F.model
step.review: DO challenge(claim = F.model) -> R.gaps
step.output: DO report(inputs = [F.model, R.gaps]) -> OUT.report
step.verify: DO verify(goal = Q.choice, evidence = E.all) -> V.answer
RETURN OUT.report, V.answer
```

## Reference Program B: Software Change

```text
PROGRAM repair_defect VERSION 0.1
INPUT
  G.fix = "Observed behavior matches the contract"
  C.scope = "Smallest root-cause fix"

step.repro: DO reproduce(discrepancy = G.fix, attempts = 3) -> E.repro
step.trace: DO trace(origin = E.repro, boundary = "component") -> ART.path
step.hyp: DO hypothesize(evidence = [E.repro, ART.path], limit = 3) -> H.causes
SCATTER H.cause IN H.causes MAX 3
  step.probe: DO test_hypothesis(hypothesis = H.cause) -> E.probe[H.cause]
GATHER step.probe AS E.probes USING all
step.pick: DO choose(options = H.causes, evidence = E.probes) -> D.cause
step.patch: DO edit(intent = D.cause, scope = C.scope) -> ART.patch
step.test: DO test(target = ART.patch, cases = ["reproduction", "regression"]) -> V.tests
step.review: DO review(artifact = ART.patch, criteria = [G.fix, C.scope]) -> R.review
IF V.tests.status != "passed"
  STOP failed(V.tests)
ELSE IF count(R.review.blocking) > 0
  STOP failed(R.review)
ELSE
  step.final: DO verify(goal = G.fix, evidence = [V.tests, R.review]) -> V.result
  RETURN ART.patch, V.result
```

## Reference Program C: Metric Investigation

```text
PROGRAM explain_metric VERSION 0.1
INPUT
  Q.change = "Why did p95 increase?"
  K.metric = "p95 latency in milliseconds over one-hour windows"
  CTX.deploys = "Versioned deployment-event artifact"
  CTX.traffic = "Versioned traffic-mix artifact"

step.observe: DO observe(target = K.metric, window = duration("7d")) -> ART.series
step.stats: DO aggregate(dataset = ART.series, metric = K.metric) -> F.stats
step.delta: DO diff(left = F.stats.baseline, right = F.stats.current) -> E.delta
step.events: DO correlate(datasets = [E.delta, CTX.deploys, CTX.traffic]) -> E.associations
step.hyp: DO hypothesize(evidence = [E.delta, E.associations], limit = 4) -> H.causes
SCATTER H.cause IN H.causes MAX 4
  step.test: DO test_hypothesis(hypothesis = H.cause) -> E.test[H.cause]
GATHER step.test AS E.tests USING all
step.answer: DO choose(options = H.causes, evidence = E.tests) -> D.cause
step.report: DO report(inputs = [D.cause, E.delta, E.tests]) -> OUT.report
step.verify: DO verify(goal = Q.change, evidence = E.tests) -> V.explanation
RETURN OUT.report, V.explanation
```

## Coverage Gate

A release may claim standard-library completeness only when:

- every catalog command appears in a valid fixture or is explicitly experimental;
- all matrix rows have a parsing and planning fixture;
- the three reference programs execute with deterministic workers;
- forced failure at every instruction yields a defined terminal or recovery path;
- replay reconstructs identical committed state;
- no task requires a compound placeholder such as `research_everything`;
- human reviewers can map source to AST to events to final evidence.
