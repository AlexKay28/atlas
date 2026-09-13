# ADR-0001: Define a Graph-Based Language for Human-AI Thinking

- Status: Proposed
- Date: 2026-09-12
- Decision owners: Project maintainers
- Scope: Core language and protocol model

## Context

Natural-language conversations with AI are flexible but often inefficient. Intent,
constraints, assumptions, evidence, decisions, and unresolved questions become mixed
together. This increases token usage, makes reasoning difficult to inspect, and causes
the same context to be explained repeatedly.

We want a small synthetic language, expressed as structured pseudocode, that helps a
person organize thought and communicate with an AI more quickly. It must support both
linear instructions and interconnected reasoning patterns. It must also be suitable
for generic knowledge work such as analysis, planning, design, research, and review.

The language is not intended to encode hidden chain-of-thought or force an AI to reveal
private reasoning. It records inspectable working artifacts: claims, evidence,
questions, constraints, decisions, actions, and their relationships.

Personal workflows will be analyzed later. They must be representable as separate
protocol files built on top of the stable core defined here.

## Decision Drivers

- Reduce repeated prose and unnecessary tokens.
- Preserve meaning when a prompt is compressed.
- Make assumptions, uncertainty, and decisions explicit.
- Support reusable reasoning patterns without prescribing one universal workflow.
- Represent branching, dependencies, conflicts, and feedback loops.
- Remain readable and writable without specialized tooling.
- Permit validation and conversion to a graph in the future.
- Keep personal preferences separate from universal language rules.

## Brainstormed Rule Families

The language needs rules in the following families:

1. **Vocabulary rules** define a small set of node and relation types.
2. **Identity rules** give every reusable statement a stable identifier.
3. **Linking rules** define how statements support, constrain, contradict, refine, or
   depend on one another.
4. **Flow rules** describe valid transitions from a question to evidence, options,
   decisions, actions, and verification.
5. **Evidence rules** separate observations from interpretations and require source or
   confidence metadata when relevant.
6. **Decision rules** make alternatives, criteria, trade-offs, and consequences visible.
7. **Uncertainty rules** distinguish facts, assumptions, hypotheses, and unknowns.
8. **Compression rules** prefer references and structured fields over repeated prose.
9. **Boundary rules** define input, output, scope, exclusions, and stopping conditions.
10. **Validation rules** identify dangling references, unsupported claims, cycles,
    unresolved blockers, and incomplete decisions.
11. **Extension rules** allow domain and personal protocols without changing the core.
12. **Safety rules** prevent compression from hiding critical context, risk, or consent.

## Decision

We will define the language as a **typed property graph with a compact textual syntax**.
A document is a protocol instance: a set of typed nodes, typed links, metadata, and an
explicit requested output.

### Design Principles

1. **Meaning before brevity.** Compression is valid only when intent is preserved.
2. **Explicit over inferred.** Important constraints and assumptions must be written.
3. **Reference over repetition.** Define an idea once, then refer to its identifier.
4. **Facts are not interpretations.** Evidence, claims, and hypotheses use different
   node types.
5. **Uncertainty is data.** Confidence and unknowns are represented, not hidden.
6. **Decisions retain alternatives.** Rejected options and trade-offs remain traceable.
7. **Every action has a completion test.** Work is complete only when its acceptance
   condition is satisfied.
8. **Loops are explicit.** Iteration must name its stop condition or resource bound.
9. **Core and profile are separate.** Personal habits extend the language through
   profiles; they do not redefine core semantics.
10. **The text is the source of truth.** A graph visualization is a derived view.

### Core Node Types

| Type | Short form | Purpose |
| --- | --- | --- |
| Goal | `G` | Desired outcome or optimization target |
| Question | `Q` | Unknown to resolve |
| Context | `CTX` | Relevant background or state |
| Constraint | `C` | Hard boundary that must be respected |
| Preference | `P` | Soft boundary used to rank valid options |
| Fact | `F` | Accepted observation with adequate support |
| Evidence | `E` | Source, measurement, example, or observation |
| Assumption | `A` | Temporarily accepted statement requiring visibility |
| Hypothesis | `H` | Testable possible explanation |
| Option | `O` | Candidate approach |
| Criterion | `K` | Rule used to compare options |
| Decision | `D` | Selected option and rationale |
| Action | `X` | Executable next step |
| Check | `V` | Verification or acceptance test |
| Risk | `R` | Possible harmful or undesirable outcome |
| Unknown | `U` | Relevant gap not currently resolved |
| Output | `OUT` | Required response form or artifact |

The short forms are conveniences, not separate semantics. New core node types require a
new ADR. Domain-specific types should first be expressed as tags on existing types.

### Core Link Types

Links are directed and use a controlled vocabulary:

| Link | Meaning |
| --- | --- |
| `supports` | Source increases confidence in target |
| `contradicts` | Source conflicts with target |
| `depends_on` | Source cannot be resolved or executed without target |
| `constrains` | Source limits the valid form of target |
| `answers` | Source responds to a question |
| `derived_from` | Source was produced using target |
| `tests` | Source verifies or falsifies target |
| `mitigates` | Source reduces a risk |
| `selects` | Decision chooses an option |
| `rejects` | Decision explicitly declines an option |
| `precedes` | Source must occur before target |
| `refines` | Source makes target more specific without contradicting it |
| `produces` | Source creates target as an output |

Links should state one relationship only. Ambiguous relationships such as `relates_to`
are excluded from the core because they do not help execution or validation.

### Minimal Syntax

The initial syntax is line-oriented Markdown-like text:

```text
@protocol compare-approaches

G.speed: Reduce time and tokens needed to reach a sound decision.
C.quality: Do not trade correctness for brevity.
Q.choice: Which approach best satisfies the goal?

O.a: Use free-form conversation.
O.b: Use typed nodes and links.
K.tokens: Minimize repeated context. weight=high
K.audit: Preserve a reviewable decision trail. weight=high

D.core: Select typed nodes and links. confidence=0.8
D.core -selects-> O.b
D.core -rejects-> O.a
D.core -derived_from-> K.tokens
D.core -derived_from-> K.audit

X.prototype: Write one protocol using the core syntax.
X.prototype -depends_on-> D.core
V.usable: A second person can interpret the protocol without explanation.
V.usable -tests-> X.prototype

OUT.result: decision, unresolved unknowns, next action
```

Each node has the form `<TYPE>.<id>: <content> [metadata]`. Each link has the form
`<source> -<link_type>-> <target>`. Identifiers are unique within a document and remain
stable while the meaning of the node remains stable.

### Metadata

Metadata is optional unless required by a protocol. The initial common keys are:

- `confidence`: number from `0` to `1`; required for uncertain decisions or claims.
- `status`: `open`, `active`, `blocked`, `accepted`, `rejected`, or `done`.
- `priority`: `low`, `medium`, `high`, or `critical`.
- `weight`: relative importance of a criterion.
- `source`: human-readable reference or URI for evidence.
- `owner`: person or agent responsible for an action.
- `due`: ISO 8601 date or timestamp.
- `tags`: comma-separated extension labels.

Metadata must not carry semantics that should be represented as a node or link. For
example, a dependency is a `depends_on` link, not a free-text metadata value.

### Canonical Thinking Cycle

The default protocol is a graph, not a mandatory linear chain, but it follows this
canonical cycle:

```text
frame -> inspect -> model -> generate -> decide -> act -> verify -> update
```

- **Frame:** declare goal, scope, constraints, output, and stopping condition.
- **Inspect:** collect context, facts, evidence, unknowns, and assumptions.
- **Model:** connect causes, dependencies, contradictions, and risks.
- **Generate:** create distinct options or hypotheses.
- **Decide:** compare options against explicit criteria and record trade-offs.
- **Act:** assign the smallest useful next action.
- **Verify:** test the result against observable acceptance conditions.
- **Update:** revise affected nodes while retaining decision history.

A protocol may skip a phase only when the omission is explicit or the phase is not
relevant. High-impact or irreversible decisions should not skip inspect, decide, or
verify.

### Language Invariants

A conforming protocol must satisfy these rules:

1. It contains at least one `G` or `Q` node.
2. It declares at least one `OUT` node.
3. Every link references existing node identifiers.
4. A `D` node selects exactly one option unless it is explicitly marked `open`.
5. Every executable `X` node is tested by at least one `V` node or states why no check
   is possible.
6. Evidence does not become a fact merely by being linked; acceptance is explicit.
7. Assumptions that materially affect a decision link to that decision.
8. Contradictions are resolved, accepted as an explicit risk, or left as an `U` node.
9. Cycles containing `depends_on` or `precedes` are invalid unless declared as an
   intentional bounded loop.
10. Unknown identifiers, node types, link types, and metadata keys produce validation
    warnings rather than silently changing meaning.

### Compression Rules

To reduce token consumption without reducing decision quality:

- Use identifiers to refer to prior concepts instead of restating them.
- Include only context that can change an option, decision, action, or check.
- Prefer one claim per node so it can be accepted, rejected, or revised independently.
- Replace conversational filler with explicit node types and links.
- Use summaries as derived nodes and preserve links to their sources.
- Expand abbreviations at first use unless they are part of the core vocabulary.
- Do not compress away exceptions, negative constraints, uncertainty, or safety risks.
- Allow the AI to request expansion with `Q` nodes when compressed input is ambiguous.

### Human-AI Interaction Contract

When receiving a protocol, an AI should:

1. Preserve identifiers when responding or editing the graph.
2. Distinguish supplied facts from its own hypotheses.
3. Add explicit `A`, `U`, or `Q` nodes instead of silently guessing.
4. Return the requested `OUT` fields first.
5. Avoid repeating unchanged context unless the output must be standalone.
6. Challenge contradictions and constraints before optimizing preferences.
7. Propose the smallest next action that can reduce important uncertainty.
8. Report confidence only when it can explain the basis in inspectable terms.
9. Never claim that graph structure proves truth; it only improves traceability.

### Extension Model

Extensions are separate protocol or profile files. They may:

- define templates made from core nodes and links;
- require additional metadata for a domain;
- define aliases for common patterns;
- define ordering, response style, and token-budget preferences;
- add validation rules scoped to the extension;
- import other extensions explicitly.

Extensions may not change the meaning of a core type or link. A personal profile should
describe preferences such as preferred detail level, decision style, challenge level,
default output, and escalation rules. It should not contain project-specific facts.

The planned separation is:

```text
language/core          stable node, link, and syntax definitions
protocols/generic      reusable workflows such as decide, debug, plan, and review
profiles/personal      individual communication and thinking preferences
instances              concrete problem graphs
```

### Initial Generic Protocols

The first reusable protocols should be deliberately small:

| Protocol | Required shape |
| --- | --- |
| `explore` | `Q -> E/F/A/U -> OUT` |
| `decide` | `G/C/P -> O -> K -> D -> R -> OUT` |
| `plan` | `G/C -> X -> V -> OUT` |
| `debug` | `Q -> E -> H -> V -> D/X -> V -> OUT` |
| `review` | `CTX/C -> E/R -> D/X -> OUT` |
| `learn` | `Q -> H -> E/V -> F/U -> OUT` |

These shapes are templates, not rigid pipelines. Links provide their exact semantics.

## Alternatives Considered

### Free-Form Prompt Templates

Prompt templates are immediately accessible, but relationships remain implicit and
templates become difficult to compose. They improve consistency but do not provide a
stable reasoning model.

### YAML or JSON as the Primary Syntax

YAML and JSON are easy to parse but verbose for live conversation and awkward for
humans to edit quickly. A structured serialization may be added later as an interchange
format generated from the textual source.

### A Linear Pipeline Language

A fixed sequence is simple but cannot naturally represent competing hypotheses,
multiple dependencies, contradiction, or feedback. The canonical cycle remains useful
as a default view, while the underlying model is a graph.

### Unrestricted Natural-Language Relationship Labels

Open-ended labels are expressive but prevent reliable validation and cause synonymous
links to fragment the model. A small controlled vocabulary is preferable, with changes
made through ADRs.

### Personal Rules in the Core Grammar

This would optimize the language for one person quickly, but it would make semantics
unstable and reduce reuse. Personal behavior belongs in profiles layered over the core.

## Consequences

### Positive

- Conversations can refer to stable identifiers instead of repeating full context.
- Reasoning artifacts can be inspected, diffed, validated, and visualized.
- Personal protocols can evolve independently from the language core.
- Explicit unknowns and verification steps reduce premature conclusions.
- The same graph can support concise AI prompts and richer human review.

### Negative

- Users must learn a compact vocabulary and identifier convention.
- Very small or casual requests may take longer when forced into the syntax.
- Over-structuring can create false precision or bureaucratic overhead.
- A graph can preserve a flawed assumption just as efficiently as a sound one.
- Tooling will eventually be needed for validation, formatting, and visualization.

### Mitigations

- Use the language only when structure saves more effort than it costs.
- Keep the core vocabulary small and require evidence for additions.
- Permit mixed documents containing syntax plus ordinary explanatory prose.
- Validate structural correctness separately from factual correctness.
- Test protocols against real tasks and measure both token use and outcome quality.

## Success Criteria

This decision is successful when pilot tasks demonstrate that:

- another person or AI can interpret a protocol without oral explanation;
- repeated context is reduced compared with an equivalent natural-language session;
- key assumptions, alternatives, and checks remain visible after compression;
- the same core represents at least analysis, planning, debugging, and review;
- a personal profile changes interaction style without changing core semantics;
- the text can be parsed into nodes and links without ambiguous grammar.

We will not optimize only for token count. A shorter interaction that produces more
errors, rework, or unverified decisions is not an improvement.

## Open Questions

- Should node content permit multiline blocks, and how should they terminate?
- Should identifiers be local to a file or globally namespaced?
- Which metadata keys must be standardized before the first parser?
- How should protocol imports, versions, and compatibility be expressed?
- Should confidence use numeric values, qualitative labels, or both?
- What is the minimum syntax for declaring an intentional bounded loop?
- Which graph serialization format should be generated first?
- Which measurements best balance tokens, elapsed time, correctness, and user effort?
- Which personal sections are stable preferences versus situation-specific context?

## Next Steps

1. Collect the user's personal thinking and communication sections without translating
   them prematurely.
2. Classify each section as core semantic, generic protocol, personal profile, or
   problem-instance context.
3. Model two real tasks with the proposed syntax and record ambiguities.
4. Revise the vocabulary only when both examples require the same missing concept.
5. Define a separate personal profile file and a machine-readable graph schema.
6. Build a minimal parser or validator only after the text format survives the pilots.

## Review Trigger

Review this ADR after two end-to-end pilot tasks, or earlier if a task cannot be modeled
without redefining a core node or link.

## Supporting Guides

Operational rules and examples are maintained separately so this ADR remains focused on
the architectural decision. See the [documentation index](../README.md) for guides on
smart thinking, token economy, reusable protocols, graph construction, quality control,
and personal-profile extraction.
