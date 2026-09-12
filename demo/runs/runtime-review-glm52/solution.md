# Adversarial Runtime Review: Thinklang MVP

## Findings

### Finding 1 — Non-mapping multi-target result raises `ParseError` outside the failure handler, leaving the run in an inconsistent state

**Severity: Critical**

**Location:** `src/thinklang/runtime/coordinator.py:201-205`

**Description:**

When a handler returns a non-`Mapping` result for a multi-target invocation, the coordinator raises `ParseError` at line 202. This raise occurs *after* `RESULT_RECEIVED` (line 177) and `VALIDATION_PASSED` (line 186) events have already been persisted, but *before* the `SUCCEEDED`/`FAILED`/`RUN_FINISHED` terminal events. The `ParseError` propagates uncaught past the coordinator's failure-handling code (the `try/except` at line 136-175 only wraps `worker.execute`, not the result-processing logic), leaving the event store in an inconsistent state:

- No `RUN_FINISHED` event is ever appended.
- The task ledger shows the invocation's task stuck in `IN_PROGRESS` (never cancelled or completed).
- The event log contains `VALIDATION_PASSED` followed by nothing — the invocation appears to have passed validation but then vanished.

The correct failure path (handler exception at line 138, or missing-keys at line 217) properly appends `FAILED`, `task_cancelled`, and `RUN_FINISHED`. The non-mapping path at line 202 does none of this.

**Reachable failure scenario:**

A user writes a program with multiple targets (`-> OUT.a, OUT.b`) and a custom handler that returns a non-dict value (e.g., a list, an int, or a string). The run crashes with an unhandled `ParseError`, the CLI prints the error and exits with code 1, but the event store is left without a `RUN_FINISHED` event. A subsequent `think status` call shows a task stuck in `IN_PROGRESS` and no terminal status. The run cannot be re-run (run ID is taken) and cannot be cleanly queried.

**Reproduction:**

```python
from thinklang.runtime import EventStore, DeterministicWorker, SequentialCoordinator
from thinklang.syntax import parse_program
import tempfile, os

prog = parse_program('''
PROGRAM bug VERSION 1.0
INPUT
    G.x = 1
step.one: DO define(value = G.x) -> E.a
step.two: DO bad(value = G.x) -> OUT.a, OUT.b
RETURN E.a, OUT.a, OUT.b
''')

with tempfile.TemporaryDirectory() as tmp:
    with EventStore(os.path.join(tmp, "db.sqlite")) as store:
        worker = DeterministicWorker({
            "define": lambda **kw: kw["value"],
            "bad": lambda **kw: 42,  # non-mapping
        })
        coord = SequentialCoordinator(store, worker)
        try:
            coord.execute(prog, run_id="r1")
        except Exception as e:
            print(f"Uncaught: {type(e).__name__}: {e}")

        history = store.events("r1")
        assert not any(e.event_type.value == "run.finished" for e in history)  # no RUN_FINISHED
        ledger = store.task_ledger("r1")
        assert ledger.profile()["counts"]["in_progress"] == 1  # task stuck
```

**Smallest credible fix:**

Move the `isinstance(result, Mapping)` check and `ParseError` raise into the `try/except` block at line 136, or convert it to the same `failed = True` / `error_msg` / append-batch / `break` pattern used by the missing-keys path (line 217-253), ensuring `FAILED`, `task_cancelled`, and `RUN_FINISHED` are always appended on any runtime failure.

---

### Finding 2 — `VALIDATION_PASSED` is emitted before the result is validated against expected targets

**Severity: High**

**Location:** `src/thinklang/runtime/coordinator.py:186-193` (emission of `VALIDATION_PASSED`) precedes `src/thinklang/runtime/coordinator.py:196-257` (target validation)

**Description:**

The coordinator unconditionally appends a `VALIDATION_PASSED` event immediately after `RESULT_RECEIVED`, before checking whether the result actually satisfies the invocation's target expectations. When the multi-target mapping check at line 206-218 finds missing keys, it appends a `FAILED` event — but `VALIDATION_PASSED` was already persisted. The event sequence for such an invocation is:

```
invocation.ready → invocation.dispatched → invocation.result_received → invocation.validation_passed → invocation.failed
```

This is self-contradictory: `validation_passed` asserts the result passed validation, yet `failed` immediately follows. Any consumer replaying the event log to reconstruct run state encounters a logical contradiction. The `VALIDATION_PASSED` event should only be emitted after confirming the result matches the expected schema/targets.

**Reachable failure scenario:**

A handler returns `{"summary": "ok"}` for a two-target invocation `-> OUT.summary, OUT.detail`. The event log shows `validation_passed` then `failed` for the same invocation. A monitoring or audit tool that filters on `VALIDATION_PASSED` events would count this invocation as valid, masking the failure.

**Reproduction:**

```python
from thinklang.runtime import EventStore, DeterministicWorker, SequentialCoordinator
from thinklang.syntax import parse_program
import tempfile, os

prog = parse_program('''
PROGRAM bug2 VERSION 1.0
INPUT
    G.x = 1
step.one: DO define(value = G.x) -> G.goal
step.two: DO partial(value = G.x) -> OUT.summary, OUT.detail
RETURN G.goal, OUT.summary, OUT.detail
''')

with tempfile.TemporaryDirectory() as tmp:
    with EventStore(os.path.join(tmp, "db.sqlite")) as store:
        worker = DeterministicWorker({
            "define": lambda **kw: kw["value"],
            "partial": lambda **kw: {"summary": "ok"},  # missing 'detail'
        })
        SequentialCoordinator(store, worker).execute(prog, run_id="r1")
        inv2 = [e for e in store.events("r1") if e.invocation_id == "inv-2"]
        types = [e.event_type.value for e in inv2]
        assert "invocation.validation_passed" in types
        assert "invocation.failed" in types
        assert types.index("invocation.validation_passed") < types.index("invocation.failed")
```

**Smallest credible fix:**

Move the `VALIDATION_PASSED` append (line 186-193) to *after* the multi-target key check (after line 257), so it is only emitted when the result has been fully validated against all targets.

---

### Finding 3 — Multi-target leaf-name collision silently assigns the same value to distinct targets

**Severity: Medium**

**Location:** `src/thinklang/runtime/coordinator.py:209-213`

**Description:**

When resolving multi-target results, the coordinator extracts the leaf component of each target (`leaf = target.split('.')[-1]`) and looks up `leaf` in the result mapping. If two targets share the same leaf name (e.g., `OUT.a.x` and `OUT.b.x`), and the handler returns `{"x": value}`, both targets receive the same value. The user cannot get different values into `OUT.a.x` and `OUT.b.x` from a single handler return, because the leaf-based lookup silently maps both to the same key.

The parser accepts the program (the targets are distinct references), the coordinator executes without error, and state projection commits both nodes with identical values. No warning or error is emitted. The user sees two output nodes with the same value and may not realize the handler's other keys (if any) were ignored.

**Reachable failure scenario:**

A user writes `DO split() -> OUT.a.x, OUT.b.x` and a handler returns `{"x": 1, "a_x": 10, "b_x": 20}`. Both `OUT.a.x` and `OUT.b.x` are set to `1`; the `a_x` and `b_x` keys are silently discarded. The user expects `OUT.a.x = 10` and `OUT.b.x = 20` based on the handler's return, but gets `1` for both.

**Reproduction:**

```python
from thinklang.runtime import EventStore, DeterministicWorker, SequentialCoordinator
from thinklang.syntax import parse_program
import tempfile, os

prog = parse_program('''
PROGRAM bug3 VERSION 1.0
INPUT
    G.x = 1
step.one: DO split(value = G.x) -> OUT.a.x, OUT.b.x
RETURN OUT.a.x, OUT.b.x
''')

with tempfile.TemporaryDirectory() as tmp:
    with EventStore(os.path.join(tmp, "db.sqlite")) as store:
        worker = DeterministicWorker({"split": lambda **kw: {"x": 1, "a_x": 10, "b_x": 20}})
        result = SequentialCoordinator(store, worker).execute(prog, run_id="r1")
        assert result["outputs"] == {"OUT.a.x": 1, "OUT.b.x": 1}  # both 1, not 10 and 20
```

**Smallest credible fix:**

When multiple targets share a leaf name, fall back to the full target name lookup only, or require the handler to return keys matching the full target names. Alternatively, emit a warning or error when two targets in the same invocation share a leaf name and the handler returns a mapping with that leaf as a key.

---

### Finding 4 — Failed run leaves subsequent tasks in `PENDING` without cancellation

**Severity: Medium**

**Location:** `src/thinklang/runtime/coordinator.py:66-90` (batch task creation) and `src/thinklang/runtime/coordinator.py:136-175` (failure handling)

**Description:**

The coordinator creates tasks for *all* invocations upfront in a single batch (line 66-90) before any invocation is executed. When a handler fails mid-run (line 136-175), the failed task is cancelled and `RUN_FINISHED` with `status: failed` is appended, but the remaining un-started tasks are left in `PENDING` state — they are never cancelled. The task ledger profile shows `pending > 0` for a failed run, which is misleading: the run is terminal (no further execution will occur), but the ledger implies work remains.

This does not cause data corruption (the run status is correctly `failed`), but it produces an inaccurate task ledger that could confuse status reporting, audit, and monitoring tools. The `think status` command shows `pending` tasks and a progress bar below 100%, even though the run is finished and will never resume.

**Reachable failure scenario:**

A 3-step program fails at step 2. Step 1's task is completed, step 2's task is cancelled, step 3's task remains `pending`. `think status` shows 33% complete with 1 pending task, even though the run is permanently failed.

**Reproduction:**

```python
from thinklang.runtime import EventStore, DeterministicWorker, SequentialCoordinator
from thinklang.syntax import parse_program
import tempfile, os

prog = parse_program('''
PROGRAM bug4 VERSION 1.0
INPUT
    G.x = 1
step.first: DO define(value = G.x) -> E.a
step.second: DO crash(value = G.x) -> E.b
step.third: DO define(value = G.x) -> E.c
RETURN E.a, E.b, E.c
''')

with tempfile.TemporaryDirectory() as tmp:
    with EventStore(os.path.join(tmp, "db.sqlite")) as store:
        def crash(**kw): raise RuntimeError("boom")
        worker = DeterministicWorker({"define": lambda **kw: kw["value"], "crash": crash})
        result = SequentialCoordinator(store, worker).execute(prog, run_id="r1")
        assert result["status"] == "failed"
        ledger = store.task_ledger("r1")
        profile = ledger.profile()
        assert profile["counts"]["pending"] == 1   # task-3 left dangling
        assert profile["counts"]["cancelled"] == 1
        assert profile["counts"]["completed"] == 1
```

**Smallest credible fix:**

After the failure `break` at line 175, cancel all remaining `PENDING` tasks (those with indices greater than the failed invocation's index) by appending `task_cancelled` events for each, or cancel them in the same batch as the `RUN_FINISHED` event.

---

## Investigated Areas With No Defect Found

1. **Seal digest determinism** (`src/thinklang/syntax/parser.py:274-275`): The `seal_digest` function uses `canonical_json` with `sort_keys=True` and compact separators. Comments and blank lines are stripped by the parser before serialization. Verified that programs differing only in whitespace/comments produce identical seals.

2. **Gapless sequence numbering** (`src/thinklang/runtime/events.py:300-303`): `append_batch` computes `MAX(seq) + 1` inside a `BEGIN IMMEDIATE` transaction. Rejected batches roll back, so seq is always gapless. Verified by `test_event_store.py` and `test_event_task_binding.py:134-165`.

3. **Optimistic state-version CAS** (`src/thinklang/runtime/events.py:334-339`): The `expected_state_version` check inside `append_batch` correctly rejects stale versions. Verified by `test_event_store.py:80-113`.

4. **Duplicate SUCCEEDED terminal rejection** (`src/thinklang/runtime/events.py:342-348`): The `succeeded_invocations` set correctly prevents a second `SUCCEEDED` for the same `invocation_id`, including within the same batch. Verified by `test_event_store.py:116-152`.

5. **Event store persistence across reopen** (`src/thinklang/runtime/events.py:174-183`): State projection and task ledger replay are byte-identical after SQLite reopen. Verified by `test_coordinator.py:399-416` and `test_event_store.py:155-184`.

6. **Parser reference validation** (`src/thinklang/syntax/parser.py:194-239`): `validate_program` correctly rejects undefined references, duplicate targets, duplicate step IDs, unknown commands, and missing terminals. Verified by `test_syntax.py`.

7. **Task ledger state machine** (`src/thinklang/runtime/tasks.py:240-330`): The `_apply` method enforces correct transitions: `PENDING → IN_PROGRESS → COMPLETED/CANCELLED`, single in-progress constraint, dependency completion check. Verified by `test_task_ledger.py`.

8. **Command registry validation** (`src/thinklang/registry/spec.py:253-296`): `CommandSpec.__post_init__` validates name, version, mandatory fields, enum values, and routing tier consistency. Verified by `test_registry.py`.

9. **CLI seal enforcement** (`src/thinklang/cli.py:112-132`): The `run` command correctly requires and verifies the seal digest before executing. Missing or wrong seals exit nonzero without creating a run. Verified by `test_cli.py:98-124`.

10. **Concurrent access** (`src/thinklang/runtime/events.py:290`): The current API is single-threaded (single connection, no async handlers), so no interleaving is possible. No speculative concurrency issue is reported per the task constraints.
