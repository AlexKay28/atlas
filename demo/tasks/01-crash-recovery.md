# Crash-Window Recovery Protocol

## Goal

Design a minimal recovery protocol for Tikhon when the coordinator process
can crash after any persisted event and the same run is resumed later.

## Context

Inspect the actual implementation under `src/tikhon/runtime/`. Invocation
lifecycle events, task updates, state deltas, and `RUN_FINISHED` may be written
in transactional batches. A worker invocation can be pure, read-only, or
externally effectful. The existing coordinator is sequential.

## Deliverable

Write `solution.md` containing:

1. A crash-window table covering every boundary from `INVOCATION_READY` through
   task completion and `RUN_FINISHED`.
2. A deterministic resume algorithm expressed as precise pseudocode.
3. The persisted identity/idempotency data required for pure, read-only, and
   externally effectful workers.
4. At least five concrete regression tests, including a crash after a worker
   effect but before local success persistence.
5. A short argument for which guarantees are exactly-once and which can only be
   at-least-once without cooperation from an external system.

## Constraints

- Cite exact source paths and relevant symbols from the current repository.
- Preserve append-only event history and gapless per-run sequence numbers.
- Never infer success merely because a task was dispatched.
- Do not edit `src/`, `tests/`, or this task file.
- Clearly separate behavior that exists now from behavior you propose.

## Acceptance

- Every persisted crash boundary has one unambiguous resume action.
- The algorithm cannot commit a partial multi-target delta.
- External side-effect duplication is addressed with a concrete protocol, not
  with an unsupported exactly-once claim.
- Proposed tests are mechanically implementable against the current APIs.
