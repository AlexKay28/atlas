# Command Registry and Standard Catalog

- Status: Draft 0.1
- Principle: one command, one semantic responsibility, one observable completion boundary

## Registry Contract

Every command definition contains:

```text
COMMAND <name>@<version>
purpose       = <one principal verb>
inputs        = <typed references and artifacts>
parameters    = <bounded typed schema>
preconditions = <deterministic state predicates>
outputs       = <typed references and artifacts>
effects       = <allowed delta and external-effect schema>
done          = <machine-evaluable predicate or validator command>
failures      = <closed typed set with retryability>
effect_class  = pure | read_only | reversible_write | irreversible_write
execution     = immediate | long_running
capabilities  = <required worker/tool capabilities>
evidence      = <required proof of execution>
budget        = <time, tokens, cost, attempts, output size>
idempotency   = none | input_digest | business_key | external_key
compensation  = <command reference or none>
routing       = <permitted tiers, validator, confidence, escalation, fallback>
```

All fields are mandatory, including explicit `none`. Registry loading rejects unknown
types, missing validators, command/control name collisions, and unbounded collections.

## Standard Catalog

The table specifies semantic signatures and minimum completion. Concrete registry files
will expand each row into the complete contract above.

### Frame and Acquire

| Command | Input -> output | Minimum done condition |
| --- | --- | --- |
| `define` | request -> typed `G/C/P/K/OUT` | Ambiguities are `Q/U`, not hidden assumptions |
| `decompose` | goal/protocol -> bounded subgoals | Children cover parent and have stop checks |
| `list` | container -> item refs | Listing scope and pagination are complete |
| `locate` | descriptor -> resource refs | Each result is addressable and matches scope |
| `search` | query + scope -> ranked candidates | Query, scope, source, and ranking evidence recorded |
| `fetch` | resource refs -> immutable artifacts | Digest and retrieval metadata recorded |
| `read` | artifact range -> observations | Requested range consumed without claiming omitted data |
| `observe` | system + window -> evidence artifact | Time, environment, units, and gaps recorded |
| `sample` | population + method -> sample | Method, seed if applicable, and coverage recorded |

### Transform and Model

| Command | Input -> output | Minimum done condition |
| --- | --- | --- |
| `parse` | artifact + grammar -> typed tree | Full input accepted or exact parse defects returned |
| `extract` | artifact + schema -> typed records | Every record links to source location |
| `filter` | collection + predicate -> collection | Predicate and rejected count recorded |
| `normalize` | values + target schema -> values | Units, encoding, and loss policy explicit |
| `sort` | collection + keys -> collection | Stable order and key definitions recorded |
| `group` | collection + key -> grouped collection | Every input belongs to declared group/error bucket |
| `merge` | compatible collections -> collection | Conflict and deduplication policy applied |
| `summarize` | source refs + budget -> summary | Claims retain source refs; no new claims introduced |
| `classify` | items + taxonomy -> labels | Every item labeled or placed in unknown class |
| `relate` | nodes + relation schema -> links | Every link uses controlled type and evidence |
| `trace` | origin + boundary -> path graph | Reachable path or typed not-found result returned |
| `diff` | two versions -> patch/differences | Direction, scope, and unchanged assumptions explicit |
| `correlate` | aligned datasets -> associations | Method, lag, sample size, and non-causality warning recorded |

### Reason and Mathematics

| Command | Input -> output | Minimum done condition |
| --- | --- | --- |
| `infer` | facts + rule/model -> claims | Rule/model and supporting inputs linked |
| `hypothesize` | question + evidence -> hypotheses | Alternatives are distinct and falsifiable |
| `challenge` | claim/decision -> counterevidence/risks | Strongest plausible failure cases checked |
| `compare` | options + criteria -> comparison | Constraints applied before preferences; unknown cells explicit |
| `estimate` | evidence + method -> estimate/range | Units, assumptions, range, and sensitivity recorded |
| `synthesize` | findings -> coherent model | Contradictions retained or resolved explicitly |
| `calculate` | numeric expression + values -> value | Exact expression, units, precision, and errors returned |
| `derive` | premises + formal rules -> derivation | Every step follows a declared rule |
| `solve` | formal problem + constraints -> solution | Solution satisfies constraints or impossibility evidence returned |
| `simulate` | model + parameters + seed/runs -> distribution | Model version, parameters, seed, and run count recorded |
| `aggregate` | dataset + metric definition -> metrics | Population, missing-data policy, units, and formula recorded |

### Decide, Design, and Change

| Command | Input -> output | Minimum done condition |
| --- | --- | --- |
| `rank` | options + criteria -> ordering | Tie and missing-evidence policy applied |
| `choose` | valid options + evidence -> `D` | Status is accepted with one option, or blocked with typed reason |
| `design` | goal + constraints -> specification | Interfaces, invariants, risks, and acceptance checks defined |
| `plan_steps` | goal + decision -> action graph | Dependencies, owners if needed, and checks defined |
| `create` | specification -> new artifact/resource | Result exists and identity/read-back evidence attached |
| `edit` | artifact + change intent -> patch | Patch is scoped and intent is satisfied |
| `remove` | resource + intent -> tombstone/effect | Absence verified; recovery or irreversibility declared |
| `configure` | system + desired state -> config delta | Effective configuration read back |
| `migrate` | source + target + mapping -> migrated resource | Counts, invariants, and rollback/forward policy pass |
| `run` | executable action -> execution artifact | Exit and externally observable result recorded |
| `rollback` | committed effect + compensation -> effect | Compensating outcome read back and linked to original |

### Check and Communicate

| Command | Input -> output | Minimum done condition |
| --- | --- | --- |
| `reproduce` | expected/observed discrepancy -> evidence | Same symptom reproduced or bounded counterevidence recorded |
| `check` | artifact + deterministic predicate -> `V` | Predicate result and inspected version recorded |
| `test` | target + cases/oracle -> `V` | Cases, environment, expected and actual results recorded |
| `test_hypothesis` | `H` + falsifier -> evidence | Prediction observed, contradicted, or blocked explicitly |
| `verify` | goal + evidence -> `V` | Original acceptance condition evaluated |
| `prove` | proposition + formal system -> proof/counterexample | Machine checker accepts proof or returns defect |
| `review` | artifact + criteria -> findings | Relevant scope inspected; findings have evidence and severity |
| `benchmark` | candidates + workload -> measurements | Controlled workload, environment, repetitions, and variance recorded |
| `monitor` | signal + window + condition -> time-series `V` | Window terminates, gaps explicit, condition evaluated |
| `explain` | result + audience -> explanation | Basis, assumptions, and requested depth covered |
| `report` | committed refs + format -> report artifact | Required sections present and claims trace to state |
| `visualize` | graph/data + view spec -> image/spec | View is reproducible and encodings are labeled |

### State Curation

| Command | Input -> output | Minimum done condition |
| --- | --- | --- |
| `accept` | supported claim -> accepted fact revision | Required evidence policy passes |
| `revise` | node + new evidence -> node revision | Reason and affected dependents recorded |
| `retire` | obsolete node -> retired revision | History retained and active references resolved |

State curation is semantic work performed by a worker and validated by policy. The actual
delta commit remains coordinator-only.

## Human Interaction

Human interaction is control, not an agent command:

- `AWAIT question(...)` waits for missing information;
- `APPROVE policy INTENT digest(...)` requests consequential authorization;
- replies and approval decisions enter the timeline as immutable events.

A worker may produce a `Q` node, but cannot impersonate the human response or approval.

## Primitive Admission Test

A proposed new command is rejected if it is:

- an alias for an existing semantic operation;
- a domain noun rather than a transformation;
- a fixed composition that belongs in a named protocol;
- a control construct disguised as worker work;
- missing an independently observable completion condition;
- mixing pure/read-only work with mutation;
- useful only because an existing command contract is underspecified.

It is admitted only with contract, validator, failure fixtures, effect policy, and at
least two reference-program uses.
