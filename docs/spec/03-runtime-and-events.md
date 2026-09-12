# Runtime and Event Semantics

- Status: Draft 0.1
- Rule: probabilistic workers, deterministic control

## Runtime Invariants

1. One fenced coordinator is the only writer to a run's event stream.
2. Sequence numbers are gapless logical time.
3. State and instruction pointer are deterministic projections of program plus events.
4. Worker output, timers, approvals, and external observations affect control only after
   they are recorded as events.
5. An invocation has at most one accepted terminal result.
6. A state delta commits with compare-and-swap against its read version.
7. Side-effect dispatch may be at-least-once; accepted commit is at-most-once.
8. Events and artifact payloads are immutable and digest-addressed.
9. Wall-clock arrival order cannot decide logical meaning unless source explicitly uses
   the `FIRST` event-choice construct.
10. No program reports success while required invocations remain nonterminal.
11. Exactly zero or one session-ledger task is `in_progress` per run.

## Invocation Lifecycle

| Current | Event | Next | Notes |
| --- | --- | --- | --- |
| `PENDING` | dependencies satisfied | `READY` | Pure projection |
| `READY` | approval required | `AWAITING_APPROVAL` | Intent digest fixed |
| `AWAITING_APPROVAL` | grant | `READY` | Grant binds exact digest |
| `AWAITING_APPROVAL` | deny/expire/revoke | terminal denial | Follow declared branch |
| `READY` | dispatch committed | `RUNNING` | Lease and attempt issued |
| `RUNNING` | worker result | `RESULT_RECEIVED` | Result immutable |
| `RESULT_RECEIVED` | validation passes and CAS commits | `SUCCEEDED` | Commit and terminal event atomic |
| `RESULT_RECEIVED` | validation fails | `REJECTED` | Retry, fail, or block decision |
| `RUNNING` | lease/deadline timer fires | `TIMED_OUT` | Retry policy evaluated |
| any nonterminal | cancellation requested | `CANCELLING` | Lease revoked |
| `CANCELLING` | acknowledgement or lease expiry | `CANCELLED` | Late results cannot commit |
| recoverable state | blocker recorded | `BLOCKED` | Explicit unblock event required |

`RETRYING` is an event/decision, not a durable state. A retry creates a new attempt under
the same invocation lineage.

## Event Envelope

```text
EVENT {
  seq: integer
  run_id: id
  program_version: digest
  event_type: enum
  instruction_id: ast-path
  invocation_id: id
  task_id: id?
  causation_seq: integer?
  correlation_id: id?
  attempt: integer
  state_version: integer
  payload_ref: digest?
  payload_schema: version?
  occurred_at: timestamp
}
```

`occurred_at` is diagnostic and never drives replay. Worker identity, policy details, and
tool configuration live in typed event payloads rather than every envelope.

`task_id` binds every atomic invocation to its session task ledger and is absent only on
coordinator bookkeeping events, including ledger events themselves.

Required event families are run, readiness, ledger, dispatch, heartbeat, result,
validation, commit, retry, timer, approval, cancellation, join, compensation, block, and
terminal.

## Leases, Heartbeats, and Fencing

A dispatch grants a worker lease containing invocation, attempt, worker, expiration, and
a monotonically increasing fencing token. Only that lease may submit a result.

Heartbeats prove liveness and may include progress and checkpoint references. They do not
prove semantic progress. Lease expiry permits redispatch with a larger fencing token.
Results from expired or older attempts are recorded as `LATE_RESULT` and cannot commit.

## Retry Rules

A retry policy declares maximum attempts, retryable failures, backoff, jitter, total
deadline, and required changed condition for semantic failures.

- transient transport and availability failures may retry with durable backoff timers;
- invalid input, permission denial, and failed deterministic predicates do not retry;
- insufficient evidence retries only with a new source, query, input, or budget;
- side-effect retries reuse the idempotency key;
- exhaustion follows a declared `FAILED`, `BLOCKED`, fallback, or compensation path.

Sleeping inside a coordinator or worker does not implement a durable retry.

## Side Effects and Reconciliation

Each side-effecting invocation uses an idempotency key derived from stable run and
instruction identity plus a business key where available. The runtime assumes dispatch
can be duplicated.

If a worker crashes after an external effect but before returning, the next attempt must
query the external system by idempotency key or expected state. It adopts an already
completed effect, retries an absent effect, or blocks on an ambiguous effect.

Every reversible write registers its compensation before commit. Compensation runs in
reverse commit order and is itself an audited command. Irreversible effects cannot be
described as rollback-capable; post-effect failure becomes `BLOCKED` with escalation.

## Approval Semantics

Approval binds approver, policy, expiry, and digest of the exact effect intent. The digest
is checked again before dispatch and commit. Editing the effect invalidates approval.

Grant, denial, expiry, and revocation are distinct events. Denial is not validation
rejection and cannot enter automatic retry. The agent proposing an effect cannot approve
it under the same responsibility boundary.

## Deterministic Scatter/Gather

`SCATTER` reads a committed bounded collection. Branch identities are allocated in stable
collection order before dispatch. Branches write disjoint addresses or buffer deltas for
an atomic gather commit.

Join rules are pure functions of the set of terminal branch outcomes:

- `all`: every branch must succeed;
- `any`: first logically accepted success wins;
- `k(n)`: at least `n` branches must succeed;
- `quorum(ratio)`: declared fraction must succeed;
- `ranked(criteria)`: validator ranks completed results; ties use stable branch identity.

For `any`, an explicit `FIRST` event choice may use recorded arrival order. Otherwise
arrival time is not semantic. After a join commits, unnecessary workers are cancelled and
late returns cannot alter the join.

Partial failure is always part of the join payload. A join cannot silently discard it.

## Protocol Calls

`CALL protocol.name(...)` creates a child event namespace and pins protocol version. The
caller supplies inputs, budget, and allowed capabilities. Outputs become visible only
after the child terminal event validates its return contract.

Recursive calls require a static depth bound and decreasing progress measure. A protocol
cannot dynamically grant itself broader permission or budget.

## Recovery and Replay

- `inspect` reads history without execution.
- `revalidate` reruns deterministic validators over stored results.
- `resume` projects state and continues after the last event.
- `reexecute` creates new attempts from a chosen state version.
- `fork` creates a new run lineage from a historical state.

Program, protocol, command, predicate, schema, and policy versions are pinned in the run
start event. Upgrades use explicit migration or fork; old history is never reinterpreted
silently under new semantics.

## Cancellation

Cancellation is a request followed by acknowledgement or lease expiry. It propagates from
program to child protocol to invocation unless a protected cleanup scope is declared.
Workers must stop tool use and report known partial effects. Detected effects are adopted,
compensated, or escalated according to policy.

## Session Task Ledger

Ledger changes are ordinary events of the `ledger` family: task created, revised,
reordered, split, and cancelled. They are coordinator bookkeeping; they never rewrite
history, alter the sealed program, or grant authority.

On each committed event the coordinator reprojects the ledger deterministically:

- counts of `pending`, `in_progress`, `completed`, and `cancelled` tasks by priority;
- completion percentage from declared task weights, equal weights when undeclared;
- per-task timing, attempt and retry counts, token and tool cost, and terminal outcome;
- a run profile for status and progress-bar display: totals per status, percent
  complete, current task, elapsed time, and aggregate cost.

A task may be marked `completed` only by recorded evidence or a terminal invocation
bound to its `task_id`. The projection is telemetry and display state; it is not a
control input and never extends program semantics.

## Observability

Minimum runtime metrics are queue delay, execution duration, validation duration, token
and tool cost, retries, timeouts, cancellations, stale results, commit conflicts,
approval wait, compensation outcomes, and end-to-end acceptance. Metrics are telemetry;
domain measurements remain typed graph artifacts.
