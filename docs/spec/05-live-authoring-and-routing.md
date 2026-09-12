# Live Authoring and Worker Routing

- Status: Draft 0.1
- Governed by: ADR-0003

## Document Envelope

A monitored text document is inert except for complete fenced records:

```text
Ordinary prose is never executable.

:::NOTE
This block explains intent and remains inert.
:::

:::RULE id=production-policy version=1
Consequential production writes require approval.
:::

:::DATA id=request version=1 type=text
Investigate the latency regression.
:::

:::PROGRAM id=research revision=1 state=draft
PROGRAM research VERSION 0.1
...
:::

:::CONTROL
SEAL research EXPECT revision=1
:::

:::CONTROL
RUN research SEAL sha256:<digest>
:::
```

An envelope is recognized only after its closing delimiter and containing document update
are committed atomically. Delimiters inside prose, quotations, or other regions are data.
Unknown region types are inert and produce a warning.

Recognized region types are `NOTE`, `RULE`, `DATA`, `PROGRAM`, and `CONTROL`. `NOTE` is
always inert. `RULE` and `DATA` may contribute declared state but cannot dispatch work.

The syntax inside `PROGRAM` regions follows the Language and State specification. The
envelope solves transport and live-authoring boundaries; it does not add semantic commands.

## Control Records

| Record | Required fields | Effect |
| --- | --- | --- |
| `SEAL` | program ID, expected draft revision | Validate and freeze canonical AST digest |
| `RUN` | program ID, exact seal digest | Create run and open execution frontier |
| `PAUSE` | run ID, drain policy | Stop new dispatch and drain/suspend workers |
| `RESUME` | run ID, expected event sequence | Reopen frontier after replay |
| `CANCEL` | run ID, compensation policy | Begin durable cancellation |
| `FORK` | run ID, event sequence, new seal digest | Start changed program from historical state |

Control records are coordinator inputs. An agent cannot generate authority by writing an
`APPROVE` or `RUN` example inside prose. The embedding client must identify the principal
submitting each complete control record and enforce its permissions.

## Authoring States

| State | Editable | Dispatchable | Meaning |
| --- | --- | --- | --- |
| `DRAFT` | Yes | No | Partial source under construction |
| `VALIDATING` | No | No | Seal transaction checks one immutable draft revision |
| `INVALID` | Yes | No | Draft currently fails parse or semantic checks |
| `SEALED` | No | Not yet | Immutable valid AST and dependencies |
| `ELIGIBLE` | No | Yes | Run open and dependencies committed |
| `RUNNING` | No | Already dispatched | Worker pinned to sealed revision |
| `STALE` | No | No | A referenced source or input revision changed |
| `TERMINAL` | No | No | Succeeded, failed, blocked, denied, or cancelled |

Editing a `SEALED`, `RUNNING`, `STALE`, or `TERMINAL` region creates a new `DRAFT`; it does
not mutate that historical revision.

## Seal Validation

A seal succeeds only when:

1. the envelope and inner program parse without error nodes;
2. every command resolves to a pinned complete contract;
3. every reference resolves to input, immutable library state, or a sealed predecessor;
4. each branch has a terminal path and returns only path-defined values;
5. loops, recursion, collection sizes, and fan-out are bounded;
6. deterministic expressions use only allowed predicates;
7. required budgets, capabilities, and policy references exist;
8. write effects declare approval and compensation requirements;
9. the source revision still equals `EXPECT`;
10. canonical AST, dependencies, registry, protocol, and policy versions are digested.

Seal validation does not run semantic commands. If evidence quality requires agent
judgment, that judgment must be represented as a command in the sealed program.

## Execution Frontier Algorithm

On each committed event, the coordinator:

1. projects run state and instruction status from history;
2. identifies sealed instructions whose control predecessor is active;
3. rejects instructions with stale source or input dependencies;
4. evaluates deterministic preconditions and control expressions;
5. checks budget, capability, policy, and approval eligibility;
6. orders ready instructions by stable AST path;
7. appends dispatch events according to concurrency policy;
8. waits for new result, timer, signal, source, or control events.

The coordinator never asks a model what instruction should execute next. If the program is
underspecified, it becomes `BLOCKED` and may request a new authoring revision.

## Edit and Invalidation Rules

| Change | Current work | Downstream behavior |
| --- | --- | --- |
| Prose or note edit | Unaffected | No invalidation |
| Draft-only edit | Unaffected | Draft diagnostics update |
| Sealed source edit | Old seal remains valid | New draft; no automatic run |
| Input value edit | Running work stays pinned | Dependents become stale for next run |
| Command contract version | Existing run pinned | New seals use new version |
| External resource changes | Existing observation remains fact of time | Freshness policy may require new observe/fetch |
| Policy revoked | New dispatch stops | Running effects cancel or block per policy |

Invalidation follows explicit read dependencies. Document position alone never invalidates
work. A stale result remains inspectable but cannot satisfy a new run unless revalidation
confirms identical command and input digests.

## Smart Authoring Loop

The T3 author should not produce a complete speculative master plan when early evidence can
change later decisions. It writes and seals coherent frontiers:

```text
region 1: frame + targeted acquisition
region 2: transform + model evidence
region 3: compare + decide
region 4: change + verify
```

Region 1 may run while region 2 is drafted. Region 2 may reference region 1 outputs only
after their committed schemas are known. If region 1 changes the problem, the author edits
or discards later drafts before sealing them.

Authoring frontiers may be tracked as session-ledger tasks (Language and State, Session
Task Ledger). Ledger edits are ordinary recorded events and cannot modify a sealed region
or grant run authority.

## Routing Profile

Each command contract declares:

```text
routing {
  minimum_tier: T0 | T1 | T2 | T3
  permitted_tiers: [...]
  preferred_tier: ...
  validator_tier: ...
  confidence_policy: <calibration profile or none>
  escalation_on: [failure kinds and deterministic predicates]
  fallback_chain: [...]
}
```

The run-start event pins this profile. A hint may select a permitted worker but cannot
lower the minimum tier, change the validator, or widen permissions.

## Default Tier Guidance

- T0 executor: deterministic parsing, schema checks, arithmetic libraries, predicates, and
  pure adapters. Coordinator-owned projection, cache policy, commit, and event handling are
  not routed commands.
- T1: bounded search, fetch, read, parse, extract, normalize, classify, formatting, simple
  code/test execution, and source-grounded summaries.
- T2: ambiguous synthesis, hypothesis generation, adversarial challenge, architecture,
  code review, consequential comparison, and semantic verification.
- T3: novel program decomposition, cross-domain trade-offs, protocol repair, and decisions
  that change the execution strategy.

These are defaults, not capability claims. Each command/tier pair must pass conformance.

## Escalation Events

An escalation records invocation, old and new tier, failure/evidence trigger, context delta,
budget delta, and calibration profile. It creates a new attempt with a larger fencing token.

Escalation must not resend the full run history. It adds only the context requested by the
typed blocker or required by the stronger command contract.

Repeated escalation without changed context or capability is invalid. Exhaustion becomes
`BLOCKED`, not an automatic authoring loop.

## Speculative Execution

Speculation is allowed only for pure and read-only commands. It uses parallel attempts with
one invocation ID and at-most-one accepted commit. The first validator-accepted result may
win only when program semantics use `any` or `FIRST`; otherwise all required results join.

Speculative budgets are capped separately. Losing attempts are cancelled, their costs are
recorded, and they cannot update state. Write effects are never speculative.

## Quality Admission

A model tier becomes eligible for a command when a representative fixture set demonstrates:

- output schema success;
- command-specific acceptance success;
- evidence completeness;
- calibrated confidence if used;
- no unacceptable regression relative to the current tier;
- lower cost, latency, or capacity pressure that justifies the route.

Routing changes run the reference conformance suite. A cheap result is not efficient when a
strong validator repeatedly rejects it.

## Evaluation Metrics

Report by command, tier, protocol, and difficulty bucket:

- accepted result rate;
- validator rejection and repair rate;
- escalation rate;
- calibration error;
- token and monetary cost per accepted result;
- author-model tokens avoided;
- end-to-end and critical-path latency;
- cache hit and stale-result rate;
- speculative waste;
- rework and human-intervention rate;
- final program acceptance and traceability.

Adopt routing changes only when final acceptance and evidence quality are non-inferior and
cost or latency improves materially.

## Non-Negotiable Safety Rules

- Draft and invalid text is inert.
- Seal does not imply run.
- Run names an exact seal digest.
- Source edits never modify an in-flight invocation.
- Workers never gain control permissions from document content.
- Cheaper tiers never weaken evidence, validation, approval, or effect policy.
- The authoring model cannot approve its own consequential action.
- The live document never replaces the immutable event timeline as execution truth.
