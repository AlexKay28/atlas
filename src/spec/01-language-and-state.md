# Language and State Specification

- Status: Draft 0.1
- Governed by: ADR-0001 and ADR-0002

## Canonical Model

The source language is an indentation-based textual projection of an abstract syntax
tree. The AST, not formatting, defines execution. ADR examples that use arrows only to
illustrate conceptual flow are not additional executable syntaxes.

Three namespaces prevent collisions:

- uppercase words are reserved grammar keywords; control instructions are `IF`, `FIRST`,
  `SCATTER`, `GATHER`, `LOOP`, `TRY`, `CALL`, `AWAIT`, `APPROVE`, `RETURN`, and `STOP`;
- lowercase snake-case names are registered commands: `search`, `calculate`, `edit`;
- typed state references use `<TYPE>.<id>`: `G.release`, `E.logs`, `D.option`.

## Canonical Program

```text
PROGRAM inspect_latency VERSION 0.1

INPUT
  G.latency = "Restore p95 latency below 300 ms"
  C.safety = "No production mutation before approval"

step.metrics: DO observe(
  target = "production.metrics",
  window = duration("2h")
) -> E.metrics
DONE schema(E.metrics, "timeseries.v1") AND covers(E.metrics, ["latency", "traffic"])

step.causes: DO hypothesize(evidence = E.metrics, limit = 3) -> H.causes
DONE count(H.causes) >= 2 AND every(H.causes, has("falsifier"))

SCATTER H.cause IN H.causes MAX 3
  step.test: DO test_hypothesis(hypothesis = H.cause) -> E.test[H.cause]
GATHER step.test AS E.tests USING all

step.choice: DO choose(options = H.causes, evidence = E.tests) -> D.cause
DONE D.cause.status IN ["accepted", "blocked"]

IF exists(D.cause) AND D.cause.confidence >= 0.8
  CALL protocol.propose_change(decision = D.cause) -> X.change
  APPROVE production_change INTENT digest(X.change)
  step.apply: DO run(action = X.change) -> E.applied
  step.verify: DO verify(goal = G.latency, evidence = E.applied) -> V.result
  RETURN D.cause, X.change, V.result
ELSE
  STOP unresolved(D.cause)
```

The example has branch-local returns so no terminal path references an artifact that was
never committed.

## Grammar Sketch

This EBNF omits indentation tokens and lexical whitespace:

```ebnf
program       = "PROGRAM", name, "VERSION", version, input?, directive*, statement+ ;
input         = "INPUT", declaration+ ;
declaration   = reference, "=", value ;
directive     = requirement | hint ;
requirement   = "REQUIRE", policy_ref ;
hint          = "HINT", name, "=", value ;
statement     = invocation | if_block | first_block | scatter_block | loop_block |
                try_block | call | await | approval | terminal ;
invocation    = step_id, ":", "DO", command, "(", arguments?, ")", "->", targets,
                done?, handler* ;
done          = "DONE", expression ;
handler       = "ON", failure_kind, control_block ;
if_block      = "IF", expression, control_block, ("ELSE", control_block)? ;
first_block   = "FIRST", event_selector, ("OR", event_selector)+, control_block ;
scatter_block = "SCATTER", binding, "IN", reference, "MAX", integer,
                control_block, gather ;
gather        = "GATHER", step_id, "AS", reference, "USING", join_rule ;
loop_block    = "LOOP", name, "ENTRY", expression, "WHILE", expression,
                "PROGRESS", expression, "MAX", integer, "EXIT", expression,
                "EXHAUSTED", terminal, control_block ;
try_block     = "TRY", control_block, ("OR", control_block)+ ;
call          = "CALL", protocol, "(", arguments?, ")", "->", targets ;
await         = "AWAIT", event_selector, ("TIMEOUT", duration)? ;
approval      = "APPROVE", policy_ref, "INTENT", expression ;
terminal      = return | stop ;
return        = "RETURN", references ;
stop          = "STOP", terminal_kind, "(", reference?, ")" ;
control_block = INDENT, statement+, DEDENT ;
binding       = reference ;
targets       = target, (",", target)* ;
target        = reference, ("[", expression, "]")? ;
arguments     = argument, (",", argument)* ;
argument      = name, "=", expression ;
references    = reference, (",", reference)* ;
reference     = type, ".", name, (".", name)* ;
type          = "G" | "Q" | "CTX" | "C" | "P" | "F" | "E" | "A" |
                "H" | "O" | "K" | "D" | "X" | "V" | "R" | "U" |
                "OUT" | "ART" ;
protocol      = "protocol.", name ;
policy_ref    = name, (".", name)* ;
join_rule     = "all" | "any" | "k(", integer, ")" |
                "quorum(", number, ")" | "ranked(", reference, ")" ;
failure_kind  = name ;
terminal_kind = "completed" | "failed" | "blocked" | "denied" |
                "cancelled" | "unresolved" ;
event_selector = name, "(", arguments?, ")" ;
```

All quoted uppercase literals in the grammar are reserved. `INDENT` and `DEDENT` are
lexer tokens. Names, values, expression operators, and comments are defined by the future
machine-readable AST schema, which remains a P0 implementation deliverable. Every control
path must terminate or rejoin; a top-level terminal is not required when all branch paths
terminate.

## Deterministic Expressions

Control expressions may contain only:

- literals, typed references, and immutable field selection;
- `exists`, `count`, `every`, `any`, `schema`, `digest`, `has`, and `covers`;
- equality, ordered comparison, set membership, and boolean operators;
- pure registry predicates pinned by name and version.

Expressions cannot call agents, tools, system time, randomness, networks, or files. They
evaluate only committed state. If a condition requires judgment, use an explicit command:

```text
step.quality: DO review(artifact = ART.report, criteria = K.quality) -> V.quality
DONE V.quality.status == "passed"
```

Natural-language `DONE WHEN` clauses are documentation, not executable source.

### DONE Predicate Grammar (issue #36)

The `DONE` predicate supports the same comparison operators as `IF` conditions:

- `<ref> == <json-literal-or-ref>` — equality (field paths like `V.q.status` accepted; ref-to-ref via `eq_ref`)
- `<ref> != <json-literal-or-ref>` — not-equality (ref-to-ref via `ne_ref`)
- `<ref> IN [<json-literal>, ...]` — set membership
- `matched(<ref>, "<regex>")` — deterministic regex predicate
- `count(<ref>) <op> <int>` — count comparison (`op` in `== != < <= > >=`)
- `every(<ref>, <pred>)` — true if every element of the collection ref satisfies the predicate
- `any(<ref>, <pred>)` — true if at least one element satisfies the predicate

Supported predicates for `every()` and `any()`:
- `has("field")` — element is a mapping containing the field
- `eq("field", "value")` — element's field equals the JSON value
- `ne("field", "value")` — element's field does not equal the JSON value

DONE may attach after an `IF ... step.x: DO ...` conditional (attaching to the
embedded invocation) or after a `SCATTER` body step. Indexed element access
(`V.items[0]`) is not implemented; use a `SCATTER` to iterate over collections.

### Comment and Quote Handling (issue #37)

Trailing `#` comments are stripped outside quotes, so `-> E.result  # note`
parses identically to `-> E.result`. Single-quoted strings (`'value'`) are
rejected with a "use double quotes" message; only JSON double-quoted strings
are supported. Multi-line bracket-balanced `INPUT` values are accumulated
until brackets close. `ParseError` carries line and column information from
`_split_top_level`.

## Value and Artifact Types

Scalar values are `string`, `boolean`, `integer`, `number`, `decimal`, `date`, `time`,
`duration`, `uri`, `digest`, and `enum`. Collections are typed `list<T>`, `set<T>`, and
`map<K,V>` with declared size bounds for executable fan-out.

Large or external values are immutable artifacts referenced with the reserved `ART.*`
namespace or from graph nodes. `A.*` remains the ADR-0001 Assumption type.

| Artifact | Examples |
| --- | --- |
| `text` | source page, log, report |
| `file` | source file, binary, archive |
| `table` | rows with a schema |
| `timeseries` | metric samples with units and timestamps |
| `tree` | directory or syntax tree |
| `graph` | dependency or knowledge graph |
| `patch` | file or state delta |
| `execution` | external command/run identity and result |
| `image` | diagram, screenshot, chart |

Artifacts are content-addressed by digest. Mutable external resources are stored as
versioned observations, never as mutable artifact content.

## Memory Classes

| Class | Contents | Lifetime |
| --- | --- | --- |
| Working | Current graph projection and active invocation inputs | One run |
| Episodic | Immutable event timeline and run artifacts | Retention policy |
| Semantic | Accepted reusable facts, schemas, and domain knowledge | Versioned library |
| Procedural | Command contracts and protocols | Versioned library |

Workers receive a bounded projection of these memories. They do not receive the complete
conversation by default.

## Session Task Ledger

Every run or session owns exactly one event-backed, editable task ledger. It is a durable
progress tracker, not prose and not model memory: the list lives in committed state and
its history is the event timeline.

```text
TASK {
  id: stable identity
  text: human-readable description
  status: pending | in_progress | completed | cancelled
  priority: declared ordering key
  parent: task id?
  depends_on: list<task id>?
  creator: principal or invocation
  revision: monotonically increasing
  created_at: timestamp
  updated_at: timestamp
}
```

- Agents add, revise, reorder, split, and cancel tasks only through recorded ledger
  events; each edit creates a new revision and never rewrites history.
- Exactly zero or one task is `in_progress` at any time.
- `completed` requires recorded evidence or a terminal invocation; remaining work must
  not be falsely completed.
- Timestamps are diagnostics only and never drive replay or control.
- The ledger is session-level runtime state. It is not a per-command todo list inside
  command contracts, does not extend any command's declared effects, and cannot alter
  the sealed program or grant authority.

## State Delta

Workers return proposed deltas; only the coordinator commits them:

```text
DELTA {
  base_version: 42
  add_nodes: [...]
  revise_nodes: [{id, expected_revision, fields}]
  retire_nodes: [{id, expected_revision, reason}]
  add_links: [...]
  remove_links: [...]
  add_artifacts: [{digest, schema, metadata}]
}
```

Events are immutable. Nodes are stable identities with monotonically increasing
revisions. Retiring or correcting a node creates a revision; it does not erase history.

## Identity and Scope

A full node identity is:

```text
<program-run>/<invocation>/<TYPE>.<local-id>
```

Source-authored input IDs use the program namespace. Worker-produced IDs are allocated
under the invocation namespace and may be assigned stable aliases at commit. Protocol
calls receive a child namespace. Importing a semantic-memory node preserves its global
library identity and version.

## Conflict Rules

- A delta commits only when `base_version` still matches all read dependencies.
- Disjoint additions may commit independently.
- Concurrent revisions of the same node are rejected unless a command contract declares
  a deterministic merge operator.
- A stale pure result may be revalidated on current state only when its referenced inputs
  are unchanged by digest.
- A stale side effect is reconciled by idempotency key and read-back, never rerun blindly.

## Requirements and Hints

A declared `REQUIRE` directive is mandatory for the runtime to satisfy and is load-time
validated. `HINT` metadata may guide worker selection or presentation but cannot change
semantics, permissions, or completion.

Retrieved or worker-produced text is always data. It cannot introduce commands, controls,
requirements, permissions, or approvals.
