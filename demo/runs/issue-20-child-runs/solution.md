# solution.md — issue #20: true isolated CALL children and parent output adoption

Epic: #27 (step 2). Sealed program: `demo/runs/issue-20-child-runs/program.think`
(seal `1b71e0f8b79375f8fd47d99e499724b6b35e72a72b87111531da902fe945c3da`,
digest written to `seal.txt` before any source edit and reproduced by the
final code).

## What changed

`CALL protocol.name(args) -> targets` no longer expands the protocol
inline into the caller's plan (the wave-4 behavior). Executing a CALL
plan entry now spawns an **isolated child run** in the same EventStore
and adopts the child's outputs explicitly.

### Child identity
- `run_id = "<parent_run_id>:<invocation_id>"` where `invocation_id` is
  the CALL entry's positional plan id (`inv-N`). Deterministic from the
  plan alone (no event reads needed to name a run), collision-free in
  the run tree (repeated calls differ in N; nested calls chain:
  `run:inv-2:inv-4`), and identical across resume attempts.
- The child's RUN_STARTED payload and run metadata carry
  `"child_of": <parent_run_id>` and `"call": protocol.name`.

### Isolation
- The child runs through the SAME coordinator machinery
  (`SequentialCoordinator._execute_program` on the same store, worker,
  memory, protocols_dir, workspace_root): its own task ledger, its own
  `inv-1..inv-N` sequence, its own state namespace.
- The child's initial state is seeded **only** from the protocol's INPUT
  declarations with values resolved from the explicitly passed CALL
  arguments against the parent's state at the call site. Parent values
  are otherwise invisible; `KB.*` refs still resolve from the shared
  knowledge base.

### Adoption
- A succeeded child's RETURN refs map onto the CALL targets by
  exact-string match (validation pins targets to a subset of RETURN
  refs). The source is the child's committed state — seeded INPUT
  bindings plus replayed SUCCEEDED deltas — so a fresh adoption and a
  resume-after-crash adoption are identical, and a ref the child
  retired is correctly non-adoptable (adopting it fails the parent).
- The parent appends one atomic batch:
  `CHILD_ADOPTED` (payload `{child_run_id, adopted: {target: ref},
  child_status}`) → `SUCCEEDED` (delta = the adopted nodes) →
  `invocation_recorded` → `task_completed`. The adoption event carries
  no delta itself, so the parent's state version bumps exactly once per
  CALL, and the store's duplicate-SUCCEEDED guard makes a re-adoption
  of the same invocation impossible.

### Failure
- Any non-succeeded child terminal (failed, blocked, cancelled, …)
  fails the parent through the standard atomic path: FAILED at the
  CALL's invocation, unreached parent tasks cancelled, RUN_FINISHED
  failed, no adoption, no partial parent outputs. The child stays
  terminal in its own history; the parent's error carries the child's
  error text.

### Resume (crash windows across a CALL)
`resume_run` delegates its core to the coordinator's
`_resume_existing_run` (shared with child re-drive). When the parent
resumes into a CALL entry, `_execute_call_child` branches on the child
run's state:
- **missing** (crash between DISPATCHED and child creation): starts the
  child fresh;
- **non-terminal** (crash during the child): re-drives it from its
  first non-terminal step (at-least-once; the child's own
  `run:inv` idempotency keys cover effectful steps);
- **terminal-succeeded** (crash after child completion, before
  adoption): adopts WITHOUT re-executing any child step;
- **terminal-failed**: fails the parent atomically, never adopts.
Crashes after adoption (the batch committed) skip the CALL entry
entirely — no duplicate output commits.

### Compatibility
- `events.py`: only `EventType.CHILD_ADOPTED = "child.adopted"` added;
  projection needs nothing (the event carries no delta).
- `parser.py`: zero changes — the current standalone CALL grammar
  suffices; the issue's proposed `CALL ... AS child(...)` syntax was
  not implemented.
- `audit.py`: zero changes — CHILD_ADOPTED is not in
  `_INVOCATION_BOUND_TYPES`, CALL lifecycle events carry
  task_id/instruction_id (instruction_id = the protocol reference), and
  parent and child ledgers both settle (tests assert clean audits on
  succeeded AND failed trees).
- `envelope.py` (not touched) reads `_PlanEntry.binds/finalizes`; those
  fields are kept as always-empty vestiges and the external driver
  still rejects CALL programs up front.
- Behavior change vs wave 4: protocol steps no longer appear in the
  parent ledger and protocol-internal refs no longer land in parent
  state (including RETIRE, which is now child-local); the parent's
  invocation-id sequence no longer continues across the CALL boundary.
  Existing seals are unaffected (the grammar and canonical JSON are
  unchanged).
- Nested calls stay bounded by the static depth-8 validation; CALL
  remains synchronous (concurrency comes from parallel scopes, per the
  issue).
