# Enhancement Plan

This plan turns the architectural idea into an implementable and testable language.
Priority reflects dependency order, not only importance.

## P0: Make the Language Implementable

### P0.1 Canonical Syntax and AST

- [x] Select one canonical executable syntax.
- [x] Define grammar for declarations, calls, sequence, branch, scatter/gather, bounded
  loops, approval, protocol calls, return, and stop.
- [ ] Define machine syntax for retry-policy attachment.
- [x] Define deterministic expressions for `IF` and `DONE`.
- [x] Separate machine predicates from judgment that requires a worker command.
- [x] Define identifiers, collections, artifacts, and state references.
- [ ] Publish a machine-readable JSON Schema for the AST.
- [ ] Implement parser fixtures for every grammar production.

Exit: every reference program parses into one unambiguous AST, and malformed programs
produce a location and expected construct.

### P0.2 Command Registry

- [x] Define the complete command-contract schema.
- [x] Add declared postconditions/effects to preconditions and done conditions.
- [x] Define a minimum standard-library catalog across all operation families.
- [x] Bind each command to typed inputs, outputs, effects, evidence, and completion.
- [x] Separate command names from control-keyword and protocol names.
- [ ] Serialize the registry into machine-readable definitions.
- [ ] Implement load-time validation and duplicate-name rejection.

Exit: every command in every reference program resolves to one complete registry entry.

### P0.3 State and Artifact Model

- [x] Define append-only state deltas and immutable event facts.
- [x] Define node identity and revision semantics.
- [x] Define collection and large-artifact boundaries.
- [x] Define optimistic version checks and stale-result handling.
- [ ] Define the session task-ledger record and its event-backed add, revise, reorder,
  split, and cancel operations.
- [ ] Select a content-addressed artifact format and storage implementation.
- [ ] Implement state projection and conflict tests.

Exit: two concurrent worker results reading the same state have a deterministic commit or
rejection outcome.

### P0.4 Runtime and Timeline

- [x] Define lifecycle transitions, including approval denial and cancellation.
- [x] Define event envelope and canonical logical ordering.
- [x] Define leases, heartbeats, fencing, retries, and durable timers.
- [x] Define idempotency and external side-effect reconciliation.
- [x] Define compensation and irreversible-write behavior.
- [x] Define deterministic scatter/gather and loser cancellation.
- [ ] Enforce the zero-or-one `in_progress` ledger invariant and `task_id` binding on
  every atomic invocation except coordinator bookkeeping.
- [ ] Implement ledger projection with progress counts, percentage, per-task
  timing/token/cost/retry metrics, and the run progress profile.
- [ ] Implement a sequential event manager with deterministic fake workers.
- [ ] Prove replay reconstructs the same state and instruction pointer.

Exit: a process crash at every lifecycle transition can resume without losing committed
work or committing an invocation twice.

### P0.5 Completeness and Conformance

- [x] Define completeness as compositional coverage, not an infinite verb list.
- [x] Map developer work patterns to standard commands and control constructs.
- [x] Define conformance dimensions and admission rules for new primitives.
- [ ] Add ledger conformance fixtures: task binding on invocations, single
  `in_progress` enforcement, and rejection of falsely completed tasks.
- [ ] Create executable reference programs for research, software change, and metrics.
- [ ] Execute every command family in at least one conformance fixture.

Exit: all required work domains can be represented without compound commands, hidden
control flow, or undefined completion conditions.

### P0.6 Live Authoring and Tier Routing

- [x] Define inert prose, draft program, sealed revision, and explicit run records.
- [x] Define editing and dependency-scoped invalidation during execution.
- [x] Define the execution frontier for partially authored documents.
- [x] Separate deterministic runtime, fast worker, strong worker, author, and human tiers.
- [x] Define escalation, speculation, and quality-admission rules.
- [ ] Implement incremental envelope parsing and draft diagnostics.
- [ ] Test editing a source dependency while an old revision is running.
- [ ] Calibrate at least one T1 and T2 worker on the same command fixtures.

Exit: a smart author continues drafting while an earlier seal executes through a cheaper
worker, and a concurrent source edit cannot alter or incorrectly validate that run.

## P1: Build the First Runtime

- [ ] Implement AST types and parser.
- [ ] Implement command-registry loader and validator.
- [ ] Implement immutable event store and graph-state projection.
- [ ] Implement worker request/result envelopes.
- [ ] Implement a deterministic coordinator with sequence and branch.
- [ ] Add bounded loop, retry, protocol call, and approval controls.
- [ ] Add scatter/gather after sequential replay is proven.
- [ ] Implement pure, read-only, reversible-write, and irreversible-write policies.
- [ ] Add content-addressed artifact storage.
- [ ] Add a CLI to validate, run, inspect, resume, fork, and revalidate programs.

Exit: the three reference programs execute against deterministic test workers and survive
forced coordinator restarts.

## P2: Connect Real Agents and Tools

- [ ] Add a capability registry for model, search, repository, shell, math, and system
  adapters.
- [ ] Route each command to the smallest sufficient model and context slice.
- [ ] Add worker leases, cancellation, and heartbeat support.
- [ ] Validate structured worker output before state commit.
- [ ] Add idempotency adapters and read-back checks for external systems.
- [ ] Require intent-bound human approval for consequential effects.
- [ ] Add policy-controlled secrets and least-privilege tool access.

Exit: replacing one worker model or tool adapter does not change program semantics or
reference-program acceptance results.

## P3: Optimize and Evaluate

- [ ] Compare against a single large autonomous agent on equivalent tasks.
- [ ] Measure input tokens, output tokens, turns, elapsed time, retries, rework, and
  acceptance success.
- [ ] Cache pure results by command version and input/artifact digest.
- [ ] Add safe command fusion for adjacent pure operations.
- [ ] Add state summaries that retain source links and version hashes.
- [ ] Tune routing by command difficulty rather than using one model for every command.
- [ ] Validate the personal-profile layer on repeated real sessions.

Exit: successful programs reduce total cost while preserving or improving correctness,
traceability, and verification quality.

## Decision Gates

Do not start parallel execution until sequential replay is deterministic.

Do not connect irreversible tools until approvals bind to an exact intent digest.

Do not add a primitive because a domain uses a new noun. Add one only when existing
operations cannot express its semantics, effects, failure modes, or completion.

Do not optimize token count before the conformance suite measures acceptance and rework.
