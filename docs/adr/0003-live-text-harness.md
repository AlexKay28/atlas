# ADR-0003: Use Live Transactional Authoring with Tiered Agent Execution

- Status: Proposed
- Date: 2026-09-12
- Decision owners: Project maintainers
- Depends on: ADR-0001 and ADR-0002
- Scope: Text-level harness boundary, live authoring, execution gates, and model tiers

## Context

The project is not primarily a workflow service, agent SDK, or software library. It is a
text-level harness for disciplined AI work. A capable model should be able to express an
intensive task more clearly and compactly than in repeated natural-language turns. The
text should be readable as reasoning, strict enough to interpret, and executable through
atomic worker calls.

Authoring and execution should overlap. While the smart model continues writing later
parts of a program, earlier complete parts may already run through faster and cheaper
agents. This creates a live thinking pipeline:

```text
smart author writes -> complete region is sealed -> coordinator dispatches workers
                   -> author continues          -> results return into typed state
                   -> author reads results and writes the next region
```

However, partial text must never execute accidentally. The same document also contains
ordinary explanation, rules, comments, unfinished ideas, and glue text. The runtime needs
an explicit transaction boundary between writing text and authorizing execution.

## Decision Drivers

- Keep the primary artifact plain text that humans and models can read and write.
- Reduce frontier-model tokens by delegating bounded operations to cheaper models.
- Start useful work before the complete program has been authored.
- Prevent unfinished source, quoted examples, and ordinary prose from executing.
- Preserve deterministic meaning when source changes during execution.
- Recompute only work affected by changed inputs.
- Maintain quality through invariant contracts and independent verification.
- Keep runtime implementations replaceable; semantics belong to the language.

## Decision

The language will use **inert-by-default text with explicitly fenced program regions and
transactional `SEAL` and `RUN` gates**.

A smart authoring model writes prose and draft program regions. Drafts are continuously
parsed and validated but cannot execute. `SEAL` freezes a valid region into an immutable,
content-addressed revision. `RUN` opens that exact sealed revision to the event manager.
The event manager may execute eligible instructions while the author continues writing
other drafts.

The runtime is deterministic control software, not the smart reasoning model. Semantic
commands are routed to the smallest worker tier proven capable of satisfying the same
contract and quality checks.

## Product Boundary

The product is:

- a concise textual language for goals, knowledge, commands, and control;
- an interaction discipline for an authoring model;
- a contract between text, event manager, and atomic workers;
- a portable event and state model;
- a conformance suite proving semantic behavior.

The project may provide a reference interpreter, but the language is not defined by one
runtime, model provider, or agent framework. A conforming implementation may use local
processes, remote agents, queues, notebooks, or another orchestrator if observable
semantics remain the same.

## Source Regions

One document may contain these region types:

| Region | Purpose | Executable |
| --- | --- | --- |
| Prose | Human explanation and discussion | Never |
| `NOTE` | Explicit non-normative comment | Never |
| `RULE` | Declarative constraints and reusable policy | Only read as state/policy |
| `DATA` | Literal typed input | Only read as state |
| `PROGRAM` in `DRAFT` state | Incomplete or editable instructions | Never |
| `PROGRAM` in `SEALED` state | Immutable validated revision | Eligible but not started |
| Control record | `SEAL`, `RUN`, `PAUSE`, `CANCEL`, `RESUME`, `FORK` | Coordinator operation |

Text is data unless it appears in a complete recognized region. Examples quoted inside
prose remain inert.

## Transactional Authoring Lifecycle

```text
DRAFT -> VALIDATING -> SEALED -> ELIGIBLE -> RUNNING -> TERMINAL
   |         |           |
   |         v           v
   +------ INVALID     STALE
```

### Draft

- May be incomplete and may contain parser error nodes.
- Is continuously linted for fast feedback.
- Cannot create events, request tools, reserve budget, or mutate state.
- May reference other drafts for authoring convenience, but cannot seal until required
  references resolve to input or sealed revisions.

### Seal

`SEAL` is a transaction. It parses the complete region, resolves references, checks command
contracts, control-flow termination, budgets, and permissions, then creates a digest of
the canonical AST and dependency versions.

Sealing produces no semantic side effect. A failed seal returns diagnostics and leaves the
draft inert.

### Run

`RUN` names an exact seal digest. It creates a run-start event and opens eligible
instructions to dispatch. It never means "run the latest text."

An author may seal without running, inspect a plan, and run later. Consequential effects
still require the approvals defined by ADR-0002.

### Pause and Cancel

`PAUSE` prevents new dispatches while allowing an explicit policy to drain or suspend
running work. `CANCEL` follows durable cancellation and compensation semantics. Neither
rewrites source or erases committed history.

## Incremental Execution

Program regions may be sealed and run independently when their inputs and outputs form a
valid boundary. A later region can depend on committed output from an earlier run.

The authoring model does not need to finish an entire long plan before useful work begins.
It should seal the smallest coherent frontier whose execution can produce evidence needed
for the next authoring decision.

This creates a repeated live cycle:

```text
frame -> write bounded region -> seal -> run -> observe committed result
      -> refine next region    -> seal -> run -> verify
```

Speculative execution is not the default. Work may start only when its sealed contract and
inputs are sufficient even if later program regions remain unwritten.

## Source Revision Rules

- A sealed region is immutable.
- Editing sealed text creates a new draft revision.
- A running invocation remains pinned to its old seal digest.
- New source cannot change the meaning of an in-flight invocation.
- Changing a dependency marks downstream sealed regions `STALE`.
- Stale regions do not dispatch until revalidated and resealed.
- Pure results may be reused only when command version and all input digests match.
- Side effects are never automatically repeated because source changed.
- Re-execution creates a new run or fork with an auditable relationship to the prior run.

Invalidation propagates through explicit references, not document position. Unaffected
regions remain valid.

## Execution Frontier

At any moment, the document has one execution frontier: the set of sealed instructions
whose dependencies are committed and whose enclosing run is open.

The event manager advances only this frontier. Draft text beyond it is invisible to
execution. Completed work behind it remains committed. Parallel eligible instructions may
run according to declared scatter/gather rules, but the canonical event timeline remains
the single red line through logical time.

## Model Tiers

| Tier | Role | Typical work |
| --- | --- | --- |
| T0 deterministic | Interpreter plus sandboxed deterministic executors | No language model |
| T1 fast worker | Mechanical or tool-bound atomic tasks | search, fetch, parse, extract, test, format |
| T2 strong worker | Bounded judgment | hypothesize, compare, review, verify, design |
| T3 author/supervisor | Novel decomposition and program repair | author regions, resolve blockers, revise protocol |
| Human authority | Intent, approval, unacceptable ambiguity | consequential approval and policy decisions |

Tier controls cost and latency, never semantics. Input schema, output schema, constraints,
done condition, and evidence policy remain identical when a command changes tier.

## Routing Rules

1. Command contracts declare permitted and minimum tiers.
2. Routing uses conformance evidence, not model reputation alone.
3. T0 work never consumes model tokens; coordinator-only commit and event authority are
   not routed worker responsibilities.
4. T1 is preferred only after passing the command's acceptance fixtures.
5. Consequential judgment receives independent T2 or deterministic validation.
6. A worker cannot validate its own consequential output.
7. Escalation creates a new attempt under the same invocation lineage.
8. Tier unavailability is explicit; the runtime never silently substitutes a model.
9. Confidence used by control flow must be calibrated for command and tier.
10. T3 repairs a program by new draft, seal, and fork; it cannot mutate live control flow.

## Escalation

Escalate from T1 to T2 when structured output is invalid after allowed repair, evidence is
insufficient, confidence is below a calibrated contract threshold, or an independent
check finds a material contradiction.

Escalate to T3 when decomposition is invalid, a loop makes no progress, repeated state
conflicts expose a program defect, join recovery is undefined, or a command repeatedly
fails despite valid changed conditions.

Escalate to a human for consequential approval, ambiguous external side effects, policy
conflict, exhausted budget with material uncertainty, or a decision outside delegated
authority.

## Quality Preservation

The smart/cheap split is accepted only per command, not globally. A worker tier is eligible
for a command when conformance trials show equivalent acceptance under the same validator.

Required controls are:

- invariant done conditions across tiers;
- producer/validator independence for consequential results;
- sampled T2 review of accepted T1 work;
- calibrated confidence by command and tier;
- evidence requirements based on impact, not model price;
- automatic escalation on typed failures;
- reference-program regression after routing changes;
- no reduction of safety or approval policy to save tokens.

## Efficiency Model

The authoring model should spend tokens on decisions that shape the program: framing,
decomposition, choosing contracts, resolving contradictions, and repairing the plan. It
should not repeatedly perform mechanical search, retrieval, transformation, execution, or
formatting that a validated worker can complete.

```text
total_cost = author_tokens + worker_tokens + tool_cost
           + validation + retries + rework + failure_cost
```

The design succeeds only if cost per accepted result and end-to-end latency improve while
acceptance quality, evidence, and traceability do not decline.

## Related Precedents

- Literate programming and Org Babel mix prose with explicit executable blocks.
- Jupyter demonstrates the danger of hidden state and arbitrary execution order.
- Pluto and marimo demonstrate dependency-based reactive invalidation.
- Hazel and typed holes demonstrate useful structure during incomplete authoring.
- Terraform separates inspectable planning from approved effects.
- ReWOO and LLMCompiler demonstrate token and latency gains from plan/worker separation.
- IBM PDL demonstrates an interpreted prompt document with schema and replay trace.
- LMQL, Guidance, DSPy, and BAML demonstrate constrained generation and typed interfaces.

These systems provide components, but none defines this complete text-level harness.

## Alternatives Considered

### Execute Every Complete-Looking Line Immediately

Rejected because temporary syntax validity does not mean semantic completeness or user
intent. It makes editing dangerous and replay unstable.

### Wait for the Entire Document

Rejected because long planning blocks delay independent search, measurement, and tests.
The execution-frontier model preserves safety while allowing overlap.

### Let the Smart Model Directly Call Every Tool

Rejected because it consumes frontier-model context on mechanical work and recreates the
opaque single-agent loop.

### Treat Every Code Fence as Executable

Rejected because examples and quoted programs would become effects. Execution requires a
validated seal plus an explicit run gate.

### Automatically Re-run Everything After an Edit

Rejected because it wastes tokens and can duplicate external effects. Invalidation is
dependency-scoped, and side effects require explicit reconciliation or a new run.

## Consequences

### Positive

- Thinking and execution overlap without executing unfinished text.
- The smart model concentrates on high-value structure and supervision.
- Fast workers reduce latency and cost for validated atomic work.
- Immutable seals make live editing compatible with replay.
- The document remains the readable source artifact.
- Fine-grained invalidation avoids repeating unaffected work.

### Negative

- Authors must understand draft, seal, run, stale, and revision states.
- The editor or transport must commit control records atomically.
- Poor decomposition may create too many small agent calls.
- Tier calibration and sampled validation add operational work.
- Live execution makes source-version visualization essential.

## Success Criteria

- Ordinary prose and partial drafts never dispatch work.
- A complete sealed region begins before later regions are authored.
- Editing an in-flight region creates a new revision without changing the current run.
- Downstream invalidation is correct and limited to actual dependencies.
- T1 workers reduce cost or latency on admitted commands with no acceptance regression.
- A T3 author can inspect events and repair a blocked program through a new sealed revision.
- The same text and seal digests produce the same control decisions on replay.
- Users can read the document and identify what is commentary, planned, eligible, running,
  stale, completed, and blocked.

## Review Trigger

Review after a prototype demonstrates concurrent authoring and execution across three
sealed regions, including one source edit during a running worker and one T1-to-T2
escalation.
