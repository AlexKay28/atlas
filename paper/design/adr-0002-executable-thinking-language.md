# ADR-0002: Build an Executable Thinking Language for AI Agents

- Status: Proposed
- Date: 2026-09-12
- Decision owners: Project maintainers
- Depends on: [ADR-0001](0001-ai-thinking-language.md)
- Scope: Language execution model, orchestration, and atomic agent operations

## Context

ADR-0001 defines a graph vocabulary for representing goals, facts, assumptions,
hypotheses, decisions, actions, checks, and their relationships. That representation is
useful, but a passive graph does not by itself perform research, reasoning, coding,
calculation, system inspection, or verification.

The project needs an executable language that an AI can both write and read. A program
in this language describes a disciplined sequence of thinking and working operations.
A runtime follows that sequence and delegates each atomic operation to a separate worker
agent. The program is therefore closer to source code than to a prompt template:

- the language expresses intent and control flow;
- the event manager behaves like an interpreter and scheduler;
- atomic commands behave like function calls;
- worker agents behave like processors for those calls;
- the shared graph behaves like typed memory;
- the event log behaves like the canonical execution timeline.

The central metaphor is a **thinking motor**. One visible execution line moves through
time. It dispatches bounded work, receives results, updates state, evaluates conditions,
and advances to the next instruction until the requested outcome is verified or the
program reaches an explicit terminal state.

## Problem Statement

Natural-language agents commonly mix five concerns in one opaque interaction:

1. deciding what should happen;
2. retaining problem state;
3. performing a unit of work;
4. deciding what happens next;
5. explaining the result.

This makes execution difficult to inspect, replay, parallelize, validate, or optimize.
It also wastes tokens because context and intermediate conclusions are repeatedly
restated.

We need to separate these concerns while preserving a syntax that a person can read and
an AI can generate reliably.

## Decision Drivers

- Express complex intellectual and software-engineering work as composable operations.
- Make execution order and decision points explicit.
- Give every atomic operation a clear completion boundary.
- Isolate worker-agent context to reduce distraction and token consumption.
- Preserve one inspectable source of truth across many agent calls.
- Support sequential work, safe parallelism, branching, bounded iteration, and recovery.
- Cover research, search, reasoning, mathematics, coding, system work, metrics, testing,
  and communication without creating a separate language for every domain.
- Allow deterministic replay of control flow even when agent outputs are probabilistic.
- Verify outcomes instead of treating a plausible agent response as completion.

## Decision

We will build a **typed, event-driven, executable thinking language** interpreted by one
coordinator. Programs consist of state declarations, atomic command invocations,
control-flow instructions, and explicit completion checks.

The coordinator owns the canonical timeline. It advances an instruction pointer,
dispatches each executable command to a worker agent, validates the returned result,
commits accepted changes to shared state, appends an event, and then advances control.

Worker agents never own global control flow. They perform one bounded operation and
return a typed result. They cannot silently change the program, shared state, or success
criteria.

## System Model

```text
human or authoring agent
          |
          v
   thinking program
          |
          v
 +-------------------+
 | event manager     |  instruction pointer + scheduler + policy
 +-------------------+
    |       |      |
    v       v      v
 worker   worker  worker   isolated atomic executions
    |       |      |
    +-------+------+
            |
            v
   validator / join
            |
            v
 typed graph state + append-only event timeline
            |
            v
 verified output or explicit terminal failure
```

### Components

| Component | Responsibility |
| --- | --- |
| Authoring agent | Converts a human goal into a valid thinking program |
| Program | Declares state, commands, control flow, budgets, and checks |
| Event manager | Interprets the program and owns execution order |
| Instruction pointer | Identifies the next eligible instruction on the main timeline |
| Dispatcher | Selects a worker capability and creates its isolated call context |
| Worker agent | Executes exactly one atomic command contract |
| Validator | Checks result shape, evidence, constraints, and completion condition |
| Graph state | Stores current typed knowledge and artifacts |
| Event timeline | Records dispatch, result, decision, mutation, failure, and retry events |
| Policy layer | Controls permissions, budgets, concurrency, and human approval |

## Language Layers

The language has four layers with strict responsibilities:

1. **State layer:** typed nodes and links from ADR-0001.
2. **Command layer:** atomic transformations over state or the external world.
3. **Control layer:** sequence, branch, parallel dispatch, join, bounded loop, retry,
   approval, and termination.
4. **Protocol layer:** reusable programs composed from commands and control instructions.

Domain libraries may provide commands or protocols, but they must obey the same command
contract and runtime semantics.

## Program Shape

The initial human-readable form is:

```text
PROGRAM investigate_latency

INPUT:
  G.fix: Restore p95 latency below 300 ms.
  C.safety: Do not modify production before approval.

DO observe(
  target="production metrics",
  window="last 2 hours"
) -> E.metrics
DONE WHEN E.metrics includes latency, traffic, errors, and resource saturation

DO hypothesize(
  evidence=E.metrics,
  max=3
) -> H.causes
DONE WHEN hypotheses are distinct and each has a falsifying check

SCATTER H.cause IN H.causes MAX 3
  DO test_hypothesis(hypothesis=H.cause) -> E.test[H.cause]
GATHER test_hypothesis AS E.tests USING all

DO choose(
  options=H.causes,
  evidence=E.tests,
  constraints=[C.safety]
) -> D.cause
DONE WHEN D.cause is accepted or blocked with a typed reason

IF D.cause.status == "accepted":
  CALL protocol.propose_change(decision=D.cause) -> X.fix
  APPROVE production_change INTENT digest(X.fix)
  DO run(action=X.fix) -> E.change
  DO verify(goal=G.fix, evidence=E.change) -> V.result
  RETURN D.cause, X.fix, V.result
ELSE:
  STOP unresolved(D.cause)
```

This syntax is illustrative. A parser grammar will be standardized separately. The
semantic elements in the example are architectural requirements.

## Atomic Command Contract

Every executable command is a typed function with this logical signature:

```text
command(
  input_refs,
  parameters,
  constraints,
  budget,
  permissions
) -> {
  outputs,
  evidence,
  status,
  confidence,
  unknowns,
  metrics
}
```

Every command definition must declare:

- **name:** one stable verb with one meaning;
- **purpose:** the single transformation it performs;
- **accepted inputs:** node and artifact types it can consume;
- **produced outputs:** node and artifact types it may create;
- **preconditions:** facts that must be true before dispatch;
- **effects:** allowed state delta and external postconditions;
- **done condition:** observable requirements for successful completion;
- **failure modes:** expected typed failures and whether they are retryable;
- **side-effect class:** pure, read-only, reversible write, irreversible write;
- **required capability:** worker or tool capability needed;
- **evidence policy:** what proves the operation was performed;
- **budget:** token, time, cost, and attempt limits;
- **idempotency:** whether replay can safely repeat the operation.
- **routing:** permitted worker tiers, validator, and escalation policy.

A command is incomplete if any of these fields is unknown. The runtime must reject an
incomplete command definition rather than allowing the worker to infer its contract.

## Atomicity

A command is atomic when it has one principal verb, one bounded responsibility, and one
independently testable result.

Atomicity is semantic, not necessarily computational. A search may query several
sources, but its only responsibility is to return relevant source candidates. It must
not silently choose an architecture. A coding command may edit several lines, but its
only responsibility is one declared change with one acceptance boundary.

A command must be split when:

- it contains two independently useful outcomes;
- part of it can fail or retry without repeating the rest;
- it mixes read-only analysis with external mutation;
- it both produces and approves a consequential decision;
- different parts require different permissions or worker capabilities;
- its completion cannot be expressed as one observable condition.

Examples:

```text
search_and_choose    -> search, compare, choose
implement_and_apply  -> edit, test, APPROVE, run, verify
research_everything  -> decompose, SCATTER(search), SCATTER(extract), synthesize
```

## Primitive Operation Families

The standard library will provide atomic commands in these closed families:

| Family | Responsibility | Representative commands |
| --- | --- | --- |
| Frame | Define work and boundaries | `define`, `decompose` |
| Acquire | Obtain external or stored information | `list`, `locate`, `search`, `fetch`, `read`, `observe`, `sample` |
| Transform | Change representation without adding conclusions | `parse`, `extract`, `filter`, `normalize`, `sort`, `group`, `merge`, `summarize` |
| Model | Create explicit structure | `classify`, `relate`, `trace`, `diff`, `correlate` |
| Reason | Produce defeasible conclusions | `infer`, `hypothesize`, `challenge`, `compare`, `estimate`, `synthesize` |
| Mathematics | Apply formal numeric or symbolic operations | `calculate`, `derive`, `solve`, `simulate`, `aggregate` |
| Decide | Commit among valid alternatives | `rank`, `choose` |
| Design | Specify a future artifact or system | `design`, `plan_steps` |
| Change | Mutate code, data, configuration, or systems | `create`, `edit`, `remove`, `configure`, `migrate`, `run`, `rollback` |
| Check | Evaluate behavior or truth conditions | `reproduce`, `check`, `test`, `test_hypothesis`, `verify`, `prove`, `review`, `benchmark`, `monitor` |
| Communicate | Produce a consumable representation | `explain`, `report`, `visualize` |
| Curate | Change accepted graph knowledge | `accept`, `revise`, `retire` |

Control instructions such as `IF`, `FIRST`, `SCATTER`, `GATHER`, `LOOP`, `TRY`, `CALL`,
`AWAIT`, `APPROVE`, `RETURN`, and `STOP` are executed by the event manager. Retry is a
pinned invocation policy, not source-level improvisation. Controls are not reasoning
commands and do not require worker agents.

The operation families are intended to be complete by composition. New domain work
should first be expressed as a protocol over existing primitives. A new primitive is
justified only when the work has distinct semantics, inputs, outputs, failure behavior,
or side-effect policy that existing commands cannot represent without ambiguity.

## Execution Lifecycle

Each command invocation follows this summary lifecycle. The normative transition table is
in the Runtime and Event specification.

```text
PENDING
  -> READY
  -> RUNNING
  -> RESULT_RECEIVED
  -> SUCCEEDED
```

Alternative terminal paths are:

```text
READY -> AWAITING_APPROVAL -> READY | DENIED
RESULT_RECEIVED -> REJECTED -> READY | FAILED | BLOCKED
RUNNING -> TIMED_OUT -> READY | FAILED | BLOCKED
any nonterminal state -> CANCELLING -> CANCELLED
any nonterminal state -> BLOCKED
```

Validation, state-delta commit, terminal event append, and transition to `SUCCEEDED` are
one atomic coordinator transaction. Retry decisions create a new attempt; `RETRYING` is
an event, not a durable state.

Only committed output may update shared graph state. Worker scratch work is private to
the invocation and is discarded unless explicitly returned as an artifact.

## The Canonical Timeline

The event manager maintains one ordered event stream. Parallel workers may run in the
background, but their results become visible to the program only through a deterministic
join and commit order.

Each event uses this minimum envelope:

```text
seq
run_id
program_version
event_type
instruction_id
invocation_id
causation_seq
correlation_id
attempt
state_version
payload_ref
payload_schema
occurred_at
```

`seq` is logical time. `occurred_at` is diagnostic only. Worker identity and policy
decisions are carried by typed event payloads when relevant.

The event stream is the red line through execution. It answers what was attempted, why
it was eligible, which state it read, what it returned, whether the return was accepted,
and what instruction became eligible next.

Wall-clock completion order must not silently determine logical meaning.

## State and Context Isolation

The coordinator provides each worker only:

- the command contract;
- referenced input nodes and artifacts;
- applicable constraints and policies;
- the required output schema;
- the completion condition;
- the allowed budget and tools.

It does not send the entire conversation or graph by default. This minimizes tokens and
reduces unrelated context influencing the result.

Workers return deltas, not a rewritten global state. The coordinator validates and
commits those deltas using optimistic state versions. A stale result is rejected or
re-evaluated if relevant inputs changed while the worker was running.

## Sequential and Parallel Execution

Sequential execution is the default because it is easiest to understand and replay.

Commands may run in parallel only when:

- their required inputs are committed;
- neither depends on the other's output;
- their side effects do not conflict;
- the join rule is explicit;
- the policy permits the combined resource use.

A `GATHER` must define whether it requires all results, any successful result, a count or
ratio quorum, or a ranked winner. Partial failure must never be silently ignored.

## Branching and Iteration

Branches evaluate explicit values in committed state. A worker may recommend a branch,
but the coordinator applies it.

Loops must declare:

- entry condition;
- continuation condition;
- progress metric;
- maximum iterations or budget;
- successful exit condition;
- exhausted exit behavior.

Unbounded autonomous loops are invalid. A loop that makes no progress must stop as
`BLOCKED` rather than continue consuming tokens.

## Side Effects and Approval

Commands are classified as:

| Class | Meaning | Default policy |
| --- | --- | --- |
| Pure | Reads provided state and returns derived state | Run automatically |
| Read-only | Inspects an external system without changing it | Run within access policy |
| Reversible write | Changes external state with a reliable rollback | Run only when authorized |
| Irreversible write | Has destructive, public, financial, or unsafe consequences | Require explicit approval |

The worker proposing a consequential action cannot approve its own action. Approval is
a control event owned by policy or a responsible human.

## Failure Semantics

Failure is typed data, not an invitation for unbounded improvisation:

```text
FAILURE {
  kind: invalid_input | unavailable | timeout | permission | conflict |
        insufficient_evidence | validation | execution | unknown
  retryable: true | false
  partial_outputs: [...]
  evidence: [...]
  suggested_resolution: ...
}
```

Retries require an explicit policy and changed conditions, such as a different source,
larger budget, repaired input, or transient backoff. Repeating the identical call after
a semantic failure is invalid.

## Completeness Model

The language is considered operationally complete when any supported workday task can
be decomposed into this universal cycle:

```text
frame
-> acquire
-> transform
-> model
-> reason or calculate
-> decide or design
-> change
-> check
-> communicate
```

Not every task uses every phase. Completeness means each necessary phase has atomic
primitives and that outputs from one phase are valid inputs to another.

Coverage must be demonstrated through reference programs for at least:

- open-ended and targeted research;
- web, repository, document, and structured-data search;
- qualitative and causal reasoning;
- arithmetic, statistics, symbolic math, estimation, and simulation;
- software exploration, design, implementation, refactoring, review, and debugging;
- shell, build, deployment, configuration, and system-health operations;
- metric definition, collection, aggregation, comparison, benchmarking, and monitoring;
- testing, formal checks where possible, evidence review, and acceptance verification;
- planning, prioritization, decision records, explanation, and reporting.

No finite vocabulary can guarantee every future domain concept. The completeness claim
is therefore **compositional and extensible**, not absolute. A task is covered when it
can be represented without an ambiguous compound command or hidden control flow.

## Definition of Done for an Atomic Invocation

An invocation is `SUCCEEDED` only when:

1. all declared preconditions were met;
2. the assigned worker used only permitted capabilities;
3. output matches the declared type and schema;
4. the command-specific done condition passes;
5. required evidence is attached;
6. confidence and unknowns are represented when relevant;
7. side effects are observed, not merely claimed;
8. output was validated against constraints;
9. the state delta committed successfully;
10. the terminal event was appended to the canonical timeline.

An agent message saying that work is complete satisfies none of these conditions by
itself.

## Definition of Done for a Program

A program is complete only when:

- every required instruction reached a terminal state;
- no unresolved failure blocks the requested output;
- returned artifacts exist in committed state;
- final checks test the original goal, not only intermediate actions;
- hard constraints remain satisfied;
- residual risks and unknowns are within the declared acceptance policy;
- the event timeline can explain the path from input to output;
- final output matches the requested format and token budget.

## Token-Efficiency Rules

- Workers receive referenced context slices, not full session history.
- Commands return structured deltas and evidence references, not repeated narratives.
- Shared facts and decisions are stored once and referenced by stable IDs.
- Summaries are cached artifacts linked to their source state version.
- Independent commands may run concurrently when safe.
- Failed validation returns precise defects rather than rerunning the whole protocol.
- The coordinator escalates context or budget only when a typed blocker requires it.
- Final reporting uses committed outputs and does not restate the complete event log.

## Determinism and Reproducibility

Agent reasoning may be probabilistic. Runtime behavior must still be reproducible at the
control level. A run records program version, command version, input state version,
worker configuration, tool permissions, budgets, output, validation result, and event
order.

Replay modes are:

- **inspect:** read a past timeline without execution;
- **revalidate:** run validators against stored outputs;
- **resume:** continue from the last committed state;
- **reexecute:** invoke workers again from a selected state version;
- **fork:** create a new run from a past state with changed instructions.

## Security and Trust Boundaries

- Program text and external content are untrusted inputs.
- Retrieved content cannot create control instructions unless explicitly parsed and
  approved as code.
- Worker permissions follow least privilege per invocation.
- Secrets are referenced through protected handles and are not stored in graph text.
- External mutations require auditable capability and policy decisions.
- Worker output is untrusted until validation and commit.
- An authoring agent cannot grant permissions through generated language text.

## Alternatives Considered

### One Large Autonomous Agent

This is easy to start but mixes planning, state, execution, and verification. It is
difficult to replay, expensive in context, and vulnerable to silent drift.

### Static Prompt Templates

Templates improve consistency but do not define runtime state, branching, concurrency,
failure, or completion semantics.

### A Passive Knowledge Graph

A graph provides traceability but not execution order. ADR-0001 remains the state model;
this ADR adds executable semantics.

### One Specialized Language per Domain

This could provide precise commands but would fragment orchestration. We instead use a
small universal command algebra plus typed domain libraries.

### Free-Form Agent-to-Agent Conversation

Agents negotiating tasks in prose recreate the ambiguity and token repetition this
project is intended to remove. Worker calls use contracts and typed deltas.

## Consequences

### Positive

- Complex work becomes inspectable as code and events.
- Atomic workers use smaller, more relevant contexts.
- Failures can retry or resume without repeating successful work.
- Sequential logic remains understandable while safe work can run in parallel.
- Quality gates are part of execution rather than optional prose instructions.
- New domain capability can be added through libraries without changing the runtime.

### Negative

- The runtime, validator, event store, and command registry add implementation cost.
- Decomposition introduces overhead for trivial tasks.
- Poor command boundaries can create excessive agent calls.
- Probabilistic worker output requires stronger validation than normal function returns.
- Shared-state versioning and parallel joins require careful semantics.

### Mitigations

- Permit direct natural-language execution for low-risk trivial tasks.
- Fuse commands only through named, tested protocols rather than ambiguous compound verbs.
- Cache pure and read-only results by command and input-state version.
- Start with sequential execution and add parallelism after deterministic commits work.
- Require reference programs and conformance tests before claiming command completeness.

## Initial Scope

Version 0.1 will define:

- textual program examples and a machine-readable abstract syntax tree;
- the ADR-0001 state types;
- command registry and complete command contract;
- sequence, branch, bounded loop, parallel, join, approval, return, and stop controls;
- isolated worker dispatch;
- append-only event timeline;
- state-delta validation and commit;
- side-effect policy and typed failures;
- reference programs covering the required completeness domains.

Version 0.1 will not define:

- a self-modifying runtime;
- workers that alter control flow directly;
- unrestricted recursive agent spawning;
- unbounded loops;
- implicit permissions;
- automatic trust in worker assertions;
- optimization based only on token count.

## Success Criteria

This decision succeeds when:

- a human and an AI independently interpret the same program order and completion rules;
- each semantic command maps to one isolated executor invocation; model-based commands use
  worker agents while deterministic T0 commands may use sandboxed in-process adapters;
- workers can be replaced without changing program semantics;
- a failed command resumes without repeating committed predecessors;
- parallel completion order does not change the logical result;
- every committed result has a validator outcome and evidence trail;
- reference programs cover all listed workday domains by composition;
- compared with one large-agent execution, successful runs use less repeated context
  without reducing correctness or verification quality.

## Open Questions

- Should the source syntax be indentation-based, expression-based, or serialized first?
- Which commands belong in the universal standard library versus domain libraries?
- What state-delta format best supports both human review and machine validation?
- How should confidence be calibrated across different worker types?
- Which join strategies are necessary in version 0.1?
- When should adjacent pure commands be fused into one worker call for efficiency?
- How should cached results expire when external evidence changes?
- Which event-store and state-version model should the prototype use?

## Next Steps

1. Define the abstract syntax tree independently of surface syntax.
2. Specify the command registry schema and worker result schema.
3. Write the atomic command catalog with one definition of done per command.
4. Build a completeness matrix from developer work patterns to command compositions.
5. Write three reference programs: research, software change, and metric investigation.
6. Implement a sequential event-manager prototype with fake deterministic workers.
7. Add validation, retries, approvals, and then safe parallel execution.
8. Compare the prototype with a single-agent baseline using correctness, turns, tokens,
   execution time, and rework.

## Review Trigger

Review this ADR after the three reference programs execute end to end, or earlier if a
required task cannot be decomposed without hidden control flow or an ambiguous command.

## Normative Specifications

The illustrative syntax in this ADR is refined by the following draft specifications:

- [Language and State](../spec/01-language-and-state.md)
- [Command Catalog](../spec/02-command-catalog.md)
- [Runtime and Events](../spec/03-runtime-and-events.md)
- [Completeness and Conformance](../spec/04-completeness.md)

Where an illustrative example in this ADR differs from a draft specification, the draft
specification is the candidate behavior to validate before this ADR moves to Accepted.
