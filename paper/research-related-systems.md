# Related Systems and Adopted Ideas

This note records external ideas used to improve the project. Futuris web search was used
to discover and compare sources on 2026-09-12. The source material is inspiration, not a
claim that this project implements or is compatible with the referenced systems.

## Planning Languages

### STRIPS and PDDL

PDDL action schemas make applicability and state transition explicit through parameters,
preconditions, and effects. We adopt:

- commands declare preconditions and postcondition/effect schemas;
- applicability is checked against committed state before dispatch;
- successful results produce explicit state deltas;
- planning and execution remain separate responsibilities.

We do not adopt automatic plan synthesis in the first runtime. The authoring agent writes
the program, and the event manager executes it.

Sources:

- [PDDL 2.1, Fox and Long](https://www.jair.org/index.php/jair/article/view/10329)
- [STRIPS, Fikes and Nilsson](https://www.semanticscholar.org/paper/STRIPS%3A-A-New-Approach-to-the-Application-of-to-Fikes-Nilsson/c547e1f79e6039d05c5ae433a36612d7f8e4d3f5)

### Hierarchical Task Networks

HTN planning separates compound tasks from primitive executable actions and permits
alternative decomposition methods with applicability conditions. We adopt:

- named protocols are compound operations;
- protocols decompose into commands and control instructions;
- method selection is explicit and recorded;
- recursion is allowed only through bounded protocol calls.

Sources:

- [Semantics for Hierarchical Task-Network Planning](https://www.cs.umd.edu/~nau/papers/erol1994semantics.pdf)
- [SHOP2](https://www.jair.org/index.php/jair/article/view/10366)

## Reactive Execution

### Behavior Trees

Behavior trees compose actions through small control nodes and a common status model. We
adopt explicit `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, and `BLOCKED` outcomes, plus
selector-like fallback and retry behavior. We do not use tree shape as the universal
program representation because data dependencies and event history are graph-shaped.

Source:

- [Behavior Trees in Robotics and AI](https://arxiv.org/abs/1709.00084)

### BPMN and Workflow Patterns

BPMN and the Workflow Patterns work distinguish sequence, exclusive choice,
event-driven choice, parallel split, synchronization, cancellation, and compensation.
We adopt:

- state-based `IF` and event-based `FIRST` are different constructs;
- joins declare `all`, `any`, `k-of-n`, `quorum`, or ranked semantics;
- partial failures are explicit join inputs;
- compensating work is named and runs in reverse commit order.

Sources:

- [OMG BPMN 2.0 specification](https://www.omg.org/spec/BPMN/2.0/)
- [Workflow Patterns](https://workflowpatterns.com/patterns/control/)

## Dataflow and Composition

### Common Workflow Language

CWL separates workflow requirements from hints and defines data-driven scatter/gather.
We adopt:

- requirements are enforced; hints may be ignored;
- executable expressions are allowed only in declared language fields;
- fan-out is derived from committed collections rather than generated implicitly;
- inputs and outputs cross command boundaries through typed artifacts.

Sources:

- [CWL 1.2 specification](https://www.commonwl.org/v1.2/Specification.html)
- [CWL user guide](https://www.commonwl.org/user_guide/)

### Unix Pipes

Unix pipelines demonstrate the leverage of small tools, uniform interfaces, and explicit
composition. We adopt small commands and explicit adapters. We add stronger typing,
evidence, state versioning, and side-effect policies because language-model output is less
predictable than byte streams.

Sources:

- [The Evolution of the Unix Time-sharing System](https://archive.org/details/evolution-of-unix-tss)
- [The Art of Unix Programming: Basics of the Unix Philosophy](http://www.catb.org/~esr/writings/taoup/html/ch01s06.html)

## Durable Execution and Event Sourcing

Durable workflow systems reconstruct orchestration state from recorded history while
isolating nondeterministic and side-effecting activities. We adopt:

- the event log is the durable source of truth;
- coordinator decisions are deterministic projections of program plus history;
- agent calls and external observations enter history as events;
- activity dispatch is at-least-once, while commits are at-most-once per invocation;
- idempotency keys or read-back reconciliation provide effectively-once effects;
- timers, retries, approvals, and cancellation are durable events;
- program and command versions are pinned for replay.

Sources:

- [Temporal workflows](https://docs.temporal.io/workflows)
- [Temporal message passing](https://docs.temporal.io/encyclopedia/workflow-message-passing)
- [Microsoft event sourcing pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)

## Cognitive Architectures

BDI, SOAR, OODA, and CoALA reinforce separation between current beliefs, goals,
intentions, operators, observations, and memory classes. We adopt the distinction between
working state, immutable episode history, reusable semantic knowledge, and procedural
protocols. We do not attempt to simulate human cognition or preserve private
chain-of-thought.

Sources:

- [The Soar Cognitive Architecture](https://soar.eecs.umich.edu/)
- [CoALA: Cognitive Architectures for Language Agents](https://arxiv.org/abs/2309.02427)

## Ideas Explicitly Rejected

- One unbounded autonomous agent owning planning, execution, and approval
- Free-form agent-to-agent conversation as a runtime protocol
- Wall-clock completion order determining branch meaning
- Worker self-reports being treated as proof of completion
- Retrieved text becoming executable control flow
- "Exactly once" claims without idempotency or reconciliation
- Infinite primitive vocabularies organized by domain nouns
- Token reduction used as the only success metric

## Resulting Project Position

The project combines a typed knowledge graph, a compact executable workflow language, a
durable event-driven coordinator, and isolated probabilistic workers. Its distinctive
boundary is that semantic work is delegated to agents, while control flow, permissions,
state commits, and completion are explicit and deterministic wherever possible.
