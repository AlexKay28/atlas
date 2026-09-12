# solution.md — issue #25: runtime-authored child plans and nested delegation

Epic: #27 (step 5). Sealed program: `demo/runs/issue-25-runtime-plans/program.think`
(seal `b64c4e8cc17369ebd7f29513d805f487d59a85acc1099b241a711815c1191105`,
linted valid and sealed 2026-09-12T18:01:09Z — before any source edit;
digest written to `seal.txt` and reproduced by the final code; the file's
md5 `33e001fa24240446cdefc6dff6f69128` is unchanged since seal time).

## What changed

A worker/model can now AUTHOR a complete child program at runtime. The
new registered command `delegate` dispatches like any DO command; its
worker reply is the authored child plan text, which the coordinator
validates, records, seals-like, and executes as a bounded isolated child
run. Zero grammar changes: delegate is a command, and the sealed demo
program (written before the source edits) does not use it.

### The command contract (registry/builtins.py)

`delegate(goal:text, constraints:text, max_steps:int>0) ->
plan_digest:artifact, result:artifact`. Effect class READ_ONLY (the
authoring dispatch itself writes nothing — the child's own steps carry
their own effect classes). Routing: minimum T2, preferred T3 (plan
authoring needs a strong model), validator T0 (deterministic validation
of the authored artifact). Failures: INVALID_INPUT (malformed reply or
bound), FORMALIZATION (unparseable/invalid/oversized plan), UNAVAILABLE.
Idempotency INPUT_DIGEST.

### Runtime flow (runtime/coordinator.py, `_execute_delegate_entry`)

Intercepted in `_drive_plan` after the standard INVOCATION_READY/
INVOCATION_DISPATCHED lifecycle (delegate is a plain plan entry; args
resolve, resume prior-lifecycle guards and the global-deadline check all
apply unchanged):

1. **Authoring**: the worker call returns the plan text. The handler
   contract is "reply IS the plan text (string)" — deterministic
   handlers return a fixed canonical sample plan; a ModelWorker reply is
   the issue-specified JSON `{"plan_text": "..."}` (both normalized by
   `_extract_plan_text`).
2. **Recording**: the artifact is appended as a CHILD_PLAN_AUTHORED event
   (payload `{step_id, plan_digest, plan_text}`) BEFORE any validation or
   execution — authored plans are part of history, never ephemeral, and
   stay recorded even when subsequently rejected. `plan_digest` is sha256
   over the canonical JSON of `{"name": delegated_<parent_step_id>,
   "plan_text": <raw text>}` — computable from the step id and raw text
   alone, so it exists even for plans that fail to parse.
3. **Validation**: `parse_program` + `validate_program` against the
   worker's registry, then the delegation bounds: step count <=
   `max_steps` (default 6, hard cap 12; the parameter is a plain
   JSON-literal argument, so zero new grammar), and no `delegate` command
   anywhere in the plan — plain steps, conditional DO lines, SCATTER
   bodies, GATHER judges, PAR branches, and transitively through every
   CALLed protocol file (no recursion; the walk relies on validation's
   existing acyclic-depth-8 protocol rule). Allowed node namespaces are
   enforced by the parser's typed-reference grammar. Any rejection fails
   the parent through the standard atomic path with a VALIDATION_FAILED
   payload `{step_id, plan_digest, failure_kind, detail}`.
4. **Sealed-like binding**: the executed program's name is bound to
   `delegated_<parent_step_id>` (dots normalized), making the lineage
   label part of the executed artifact and of its digest.
5. **Execution**: the accepted plan runs as an isolated child run
   `<parent_run_id>:<invocation_id>` through the exact CALL machinery
   (`_execute_program_child`): own ledger, own state namespace seeded
   from the authored plan's INPUT declarations with the resolved delegate
   arguments bound by leaf name (`goal` -> the plan's `*.goal` refs,
   `constraints` -> `*.constraints` — the same rule CALL uses), budget
   depth gate checked before dispatch, branch workspace/claim inherited
   inside PAR branches. The RUN_STARTED payload carries `child_of` and
   `call: "delegate:step.author"` lineage.
6. **Adoption**: the authored plan's RETURN refs map POSITIONALLY onto
   the delegate step's targets (authored RETURN ref k -> target k; the
   author cannot know the parent's target names, so CALL's exact-string
   rule cannot apply). Values are read from the child's committed state
   (seeded bindings + replayed deltas), so fresh and resumed adoptions
   are identical. One atomic batch commits CHILD_ADOPTED (payload
   `{child_run_id, adopted, child_status, plan_digest}`) + SUCCEEDED
   (delta = the adopted nodes) + invocation_recorded + task_completed.
   A DONE predicate on the delegate step is evaluated over the adopted
   targets. A non-succeeded child terminal fails the parent atomically.

### Replay identity (the accepted artifact is the recorded one)

On resume of an in-flight delegate step, the coordinator reuses the
recorded CHILD_PLAN_AUTHORED payload instead of re-asking the worker — a
crash can never trigger unrecorded replanning. A crash BEFORE the event
committed means the plan was never accepted; that authoring re-runs
(at-least-once, the standard dispatch contract). The child run itself
resumes through the shared CALL machinery (terminal child adopted without
re-execution, non-terminal child re-driven).

### Deterministic worker compatibility (cli.py)

`_deterministic_handlers` gains a `delegate` handler returning a FIXED
canonical 3-step sample plan (define/calculate/check echoing the goal via
the leaf-name binding), so tests and CI never need a model. Under
`--worker model`, delegate is NOT in `DETERMINISTIC_UNDER_MODEL`: it
routes to the model per its T2/T3 contract.

### Model worker prompt (worker_adapter.py)

The delegate envelope's prompt instructs: reply with ONLY
`{"plan_text": "..."}` carrying one complete canonical-grammar program —
registered commands only, step count within the requested max_steps
bound, no delegate inside (no recursion), terminal RETURN whose refs map
one-to-one onto the step's targets in order, INPUT declarations binding
the resolved arguments by leaf name.

### Compatibility

- `events.py`: one new EventType (`child_plan.authored`); carries no
  delta, so projection is untouched.
- `audit.py`: zero changes — CHILD_PLAN_AUTHORED is not in
  `_INVOCATION_BOUND_TYPES` (like CHILD_ADOPTED), and all delegate
  lifecycle events carry task_id + instruction_id. Audits stay clean on
  succeeded, failed, and crashed-then-resumed trees (tested).
- `syntax/`: zero changes — delegate is a command; the plan-entry bounds
  (step count, recursion) are runtime checks, not grammar.
- `budgets.py`/`envelope.py`/`resume.py`/`memory.py`/`bridge.py`: zero
  changes; resume reuses the coordinator's shared machinery.
- Delegate programs force the sequential plan loop (like scatter/PAR
  programs), so the concurrent frontier never sees a delegate entry.
- Registry digest changes (a new command); `tests/test_registry.py`
  updated additively (BUILTIN_NAMES + a DELEGATE_COMMANDS group).

## Files changed

- `src/tikhon/registry/builtins.py` — the delegate CommandSpec + registration (23 builtins).
- `src/tikhon/runtime/events.py` — EventType.CHILD_PLAN_AUTHORED only.
- `src/tikhon/runtime/coordinator.py` — delegate constants/helpers (`delegate_plan_name`, `delegate_plan_digest`, `count_plan_steps`, `_extract_plan_text`, `_uses_delegate`), `_recorded_delegate_plan`, `_plan_contains_delegate`, `_execute_delegate_entry`, the `_drive_plan` interception, sequential-force for delegate programs.
- `src/tikhon/cli.py` — deterministic fixed-sample-plan delegate handler.
- `src/tikhon/worker_adapter.py` — delegate authoring prompt section.
- `tests/test_registry.py` — additive: BUILTIN_NAMES + DELEGATE_COMMANDS + delegate contract tests.
- `tests/test_delegate.py` — new, 10 tests.
- `demo/runs/issue-25-runtime-plans/` — program.think (sealed pre-edit), seal.txt, WORKLOG.md, solution.md, evaluation.json.
