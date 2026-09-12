# Crash-Window Recovery Protocol for Thinklang

## 1. Crash-Window Table

The table below covers every persisted event boundary in `SequentialCoordinator.execute()` (`src/thinklang/runtime/coordinator.py:44-326`) from `INVOCATION_READY` through `RUN_FINISHED`. Each row identifies the crash window (what was last durably persisted), the observable state on resume, and the single unambiguous resume action.

"Last persisted event" means the event that was committed by a completed `BEGIN IMMEDIATE` transaction in `EventStore.append_batch()` (`src/thinklang/runtime/events.py:264-419`). A crash mid-transaction leaves no partial events because SQLite `BEGIN IMMEDIATE` provides atomicity.

### Existing event sequence per invocation (coordinator.py:95-293)

```
1. append_batch: [TASK_UPDATED(task_started), INVOCATION_READY]          # line 103-118
2. append:        INVOCATION_DISPATCHED                                    # line 127-134
3. --- worker.execute() call ---                                          # line 137
4. [failure path]
   4a. append_batch: [FAILED, TASK_UPDATED(invocation_recorded),
       TASK_UPDATED(task_cancelled), RUN_FINISHED]                        # line 143-173
[success path]
4. append:        RESULT_RECEIVED                                         # line 177-184
5. append:        VALIDATION_PASSED                                        # line 186-193
6. append_batch: [SUCCEEDED, TASK_UPDATED(invocation_recorded),
   TASK_UPDATED(task_completed)]                                          # line 264-293
[after all invocations]
7. append:        RUN_FINISHED                                             # line 321-325
```

### Crash-window table

| # | Last persisted event(s) | Worker called? | Observable state on resume | Resume action |
|---|---|---|---|---|
| W1 | `TASK_UPDATED(task_started)` + `INVOCATION_READY` (batch) | No | Task `in_progress`; invocation has no terminal event | Redispatch: emit `INVOCATION_DISPATCHED` with same `invocation_id`, then call worker |
| W2 | `INVOCATION_DISPATCHED` (single append) | No (crashed before call) | Task `in_progress`; dispatched but no result | Redispatch: dispatch was persisted but worker was never called. Call worker, emit `RESULT_RECEIVED` or `FAILED` |
| W3 | `INVOCATION_DISPATCHED` (single append) | Yes (crashed during call) | Same as W2 -- indistinguishable from W2 on resume | Treat as W2: cannot know if worker ran. For pure/read-only: redispatch freely. For effectful: use idempotency key to query external system (see Section 3) |
| W4 | `FAILED` + `TASK_UPDATED(invocation_recorded)` + `TASK_UPDATED(task_cancelled)` + `RUN_FINISHED` (failure batch) | Yes (worker raised) | Run `failed`; task `cancelled`; invocation terminal | No resume -- run is terminal |
| W5 | `RESULT_RECEIVED` (single append) | Yes (worker returned) | Invocation has result but no validation or terminal | Revalidate: rerun validation on stored result. If passes, emit `VALIDATION_PASSED` then SUCCEEDED batch |
| W6 | `RESULT_RECEIVED` + `VALIDATION_PASSED` (two single appends) | Yes | Result validated, no SUCCEEDED commit yet | Emit SUCCEEDED batch with CAS against current state version. Delta recomputed from stored result |
| W7 | `SUCCEEDED` (batch, but other records missing -- impossible) | Yes | N/A -- `append_batch` is atomic; all three records commit or none | N/A -- cannot happen with current `BEGIN IMMEDIATE` transaction |
| W8 | `SUCCEEDED` + `TASK_UPDATED(invocation_recorded)` + `TASK_UPDATED(task_completed)` (full success batch) | Yes | Invocation terminal; task `completed`; state version incremented | Advance to next invocation. This is the normal completed state |
| W9 | Last invocation's SUCCEEDED batch, no `RUN_FINISHED` yet | Yes | All invocations terminal; no `RUN_FINISHED` | Emit `RUN_FINISHED` with `status=succeeded` and return outputs |
| W10 | `RUN_FINISHED` with `status=succeeded` | Yes | Run is terminal | No resume -- run is complete |
| W11 | `RUN_FINISHED` with `status=failed` (from failure batch W4) | Yes | Run is terminal | No resume -- run failed |
| W12 | Multi-target missing keys: `FAILED` + ledger + `RUN_FINISHED` (batch, coordinator.py:221-251) | Yes | Run `failed`; task `cancelled` | No resume -- run is terminal. Same as W4 |

### Pre-invocation crash windows

| # | Last persisted event | Resume action |
|---|---|---|
| W0a | `RUN_STARTED` only | Recreate all tasks (batch), then proceed to first invocation's W1 |
| W0b | All `TASK_UPDATED(task_created)` batch (coordinator.py:89-90) | Proceed to first invocation's W1 -- tasks already created |

## 2. Deterministic Resume Algorithm

```pseudocode
function resume(run_id, program, store):
    # 1. Project current state from committed events
    events = store.events(run_id)          # gapless, ordered by seq
    state = store.project_state(run_id)     # deterministic projection

    # 2. Determine which invocations are complete
    completed_invocations = set()
    terminal_invocations = {}  # invocation_id -> "succeeded" | "failed"
    for event in events:
        if event.event_type == EventType.SUCCEEDED and event.invocation_id:
            completed_invocations.add(event.invocation_id)
            terminal_invocations[event.invocation_id] = "succeeded"
        if event.event_type == EventType.FAILED and event.invocation_id:
            terminal_invocations[event.invocation_id] = "failed"

    # 3. Check if run is already terminal
    run_finished = any(e.event_type == EventType.RUN_FINISHED for e in events)
    if run_finished:
        finished_event = next(e for e in events
                             if e.event_type == EventType.RUN_FINISHED)
        status = finished_event.payload.get("status")
        return {"run_id": run_id, "status": status, "events": events}

    # 4. Find the next invocation to execute
    invocations = [s for s in program.statements if isinstance(s, Invocation)]
    next_idx = len(completed_invocations)

    if next_idx >= len(invocations):
        # W9: All invocations succeeded but RUN_FINISHED was not persisted
        store.append(run_id, EventType.RUN_FINISHED,
                      payload={"status": "succeeded"})
        return {"run_id": run_id, "status": "succeeded"}

    # 5. Check for a partially-complete invocation (W2, W3, W5, W6)
    #    An invocation is "in flight" if it has INVOCATION_READY
    #    but no terminal event (SUCCEEDED/FAILED).
    in_flight = None
    for event in events:
        if (event.event_type == EventType.INVOCATION_READY
                and event.invocation_id not in terminal_invocations):
            in_flight = event.invocation_id
            in_flight_task_id = event.task_id

    if in_flight is not None:
        statement = invocations[next_idx]
        invocation_id = in_flight
        task_id = in_flight_task_id

        has_dispatched = any(
            e.event_type == EventType.INVOCATION_DISPATCHED
            and e.invocation_id == invocation_id for e in events)
        has_result = any(
            e.event_type == EventType.RESULT_RECEIVED
            and e.invocation_id == invocation_id for e in events)
        has_validation = any(
            e.event_type == EventType.VALIDATION_PASSED
            and e.invocation_id == invocation_id for e in events)

        if has_validation:
            # W6: validated but SUCCEEDED batch not committed
            result_event = next(e for e in events
                if e.event_type == EventType.RESULT_RECEIVED
                and e.invocation_id == invocation_id)
            result = result_event.payload["result"]
            delta = compute_delta(statement, result)
            expected_sv = store._current_state_version(run_id)
            store.append_batch(run_id, [
                _Record(EventType.SUCCEEDED, invocation_id=invocation_id,
                        task_id=task_id, expected_state_version=expected_sv,
                        payload={"delta": delta}),
                _Record(EventType.TASK_UPDATED, task_id=task_id,
                        payload={"kind": "invocation_recorded", "id": task_id,
                                 "tokens": 0, "cost": 0.0, "retries": 0,
                                 "elapsed_seconds": 0.0}),
                _Record(EventType.TASK_UPDATED, task_id=task_id,
                        payload={"kind": "task_completed", "id": task_id,
                                 "evidence": "..."}),
            ])
            return resume(run_id, program, store)  # advance

        if has_result:
            # W5: result received but not validated
            result_event = next(e for e in events
                if e.event_type == EventType.RESULT_RECEIVED
                and e.invocation_id == invocation_id)
            result = result_event.payload["result"]
            if validate_result(statement, result):
                store.append(run_id, EventType.VALIDATION_PASSED,
                    invocation_id=invocation_id, task_id=task_id)
                return resume(run_id, program, store)  # recurse to W6
            else:
                emit_failure_batch(store, run_id, invocation_id, task_id,
                    statement, "validation failed on resume")
                return {"run_id": run_id, "status": "failed"}

        if has_dispatched:
            # W2/W3: dispatched but no result
            # For effectful workers: consult idempotency key (Section 3)
            result = worker.execute(statement.command, resolved_kwargs)
            return resume_after_worker(store, run_id, statement,
                invocation_id, task_id, result)

        # W1: INVOCATION_READY persisted but not dispatched
        resolved_kwargs = resolve_args(statement, state)
        store.append(run_id, EventType.INVOCATION_DISPATCHED,
            invocation_id=invocation_id, task_id=task_id,
            payload={"args": resolved_kwargs})
        result = worker.execute(statement.command, resolved_kwargs)
        return resume_after_worker(store, run_id, statement,
            invocation_id, task_id, result)

    # 6. No in-flight invocation -- start the next one (W0b -> W1)
    statement = invocations[next_idx]
    task_id = statement_to_task[next_idx]
    invocation_id = f"inv-{next_idx + 1}"

    ledger = store.task_ledger(run_id)
    ledger.start_task(task_id)
    store.append_batch(run_id, [
        _Record(EventType.TASK_UPDATED, task_id=task_id,
                payload={"kind": "task_started", "id": task_id}),
        _Record(EventType.INVOCATION_READY,
                instruction_id=statement.step_id,
                invocation_id=invocation_id, task_id=task_id,
                payload={"command": statement.command}),
    ])
    resolved_kwargs = resolve_args(statement, state)
    store.append(run_id, EventType.INVOCATION_DISPATCHED,
        invocation_id=invocation_id, task_id=task_id,
        payload={"args": resolved_kwargs})
    result = worker.execute(statement.command, resolved_kwargs)
    return resume_after_worker(store, run_id, statement,
        invocation_id, task_id, result)


function resume_after_worker(store, run_id, statement, invocation_id,
                              task_id, result):
    # Emit RESULT_RECEIVED, VALIDATION_PASSED, then SUCCEEDED batch
    # (same as coordinator.py:177-293 for the success path)
    store.append(run_id, EventType.RESULT_RECEIVED,
        invocation_id=invocation_id, task_id=task_id,
        payload={"result": result})
    store.append(run_id, EventType.VALIDATION_PASSED,
        invocation_id=invocation_id, task_id=task_id)
    delta = compute_delta(statement, result)
    expected_sv = store._current_state_version(run_id)
    store.append_batch(run_id, [
        _Record(EventType.SUCCEEDED, invocation_id=invocation_id,
                task_id=task_id, expected_state_version=expected_sv,
                payload={"delta": delta}),
        _Record(EventType.TASK_UPDATED, task_id=task_id,
                payload={"kind": "invocation_recorded", "id": task_id,
                         "tokens": 0, "cost": 0.0, "retries": 0,
                         "elapsed_seconds": 0.0}),
        _Record(EventType.TASK_UPDATED, task_id=task_id,
                payload={"kind": "task_completed", "id": task_id,
                         "evidence": "..."}),
    ])
    return resume(run_id, program, store)
```

**Key properties of the algorithm:**

- **Append-only**: Never modifies or deletes existing events. Only appends new events with the next gapless seq number (guaranteed by `append_batch` at `events.py:300-303`).
- **No partial multi-target delta**: The SUCCEEDED event and its delta are committed atomically inside one `append_batch` transaction (`events.py:264-419`). If the batch fails (e.g., CAS conflict), no state is modified. On resume, the algorithm re-projects state and retries with the correct `expected_state_version`.
- **Never infers success from dispatch**: The algorithm checks for `SUCCEEDED` terminal events, not `INVOCATION_DISPATCHED`, to determine completion (step 2). A dispatched-but-no-result invocation (W2/W3) is re-executed, not assumed complete.
- **Idempotent resume**: Calling `resume()` multiple times produces the same result because it projects state from the full event history each time and only appends missing events.

## 3. Persisted Identity / Idempotency Data

The idempotency requirements differ by worker classification. All three use the same stable identity: `run_id + instruction_id (step_id) + invocation_id`, which is already persisted in the event envelope (`events.py:69-89`).

### Pure workers (no side effects, deterministic)

**Required data**: `run_id`, `instruction_id`, `invocation_id` (all already in event envelope).

**Resume behavior**: Pure workers can be redispatched freely. The result of re-execution is identical to the original. On resume after W2/W3, simply redispatch. If a `RESULT_RECEIVED` was already persisted (W5/W6), use the stored result -- no need to re-execute.

**Existing support**: The current coordinator always uses the same `invocation_id` format `f"inv-{idx + 1}"` (`coordinator.py:96`), providing stable invocation identity. The duplicate-SUCCEEDED guard in `append_batch` (`events.py:342-348`) prevents a second terminal for the same invocation.

### Read-only workers (external reads, no writes)

**Required data**: `run_id`, `instruction_id`, `invocation_id`, plus the dispatched `args` (already stored in `INVOCATION_DISPATCHED` payload at `coordinator.py:133`).

**Resume behavior**: Read-only workers may return different results on retry (the external source may have changed). The resume algorithm must decide:
- If `RESULT_RECEIVED` is already persisted (W5/W6): use the stored result. The read was already performed and recorded; re-reading could produce a different answer, but the first result is the committed one.
- If only `INVOCATION_DISPATCHED` exists (W2/W3): redispatch. The read is idempotent in the sense that no external state was modified. The new result is accepted as the authoritative one.

**Proposed addition**: Store a `read_at` timestamp in the `RESULT_RECEIVED` payload for diagnostic purposes. This does not affect replay but helps audit whether a stale read was used.

### Externally effectful workers (external writes)

**Required data** (all proposed -- not yet in the current codebase):

1. **Idempotency key**: `f"{run_id}:{instruction_id}:{invocation_id}:{attempt}"` -- derived from stable run and instruction identity per the spec (`docs/spec/03-runtime-and-events.md:97-98`). This key must be sent to the external system as part of the effect request.

2. **Effect manifest**: A description of the intended effect, stored in the `INVOCATION_DISPATCHED` payload alongside `args`:
   ```json
   {
     "effect_type": "http_post",
     "target": "https://api.example.com/endpoint",
     "body_hash": "sha256:..."
   }
   ```
   This allows the resume algorithm to query the external system for the effect's status.

3. **Effect result** (proposed): On successful effect completion, the worker returns an `effect_receipt` containing the external system's confirmation. This is stored in `RESULT_RECEIVED` payload:
   ```json
   {
     "result": "...",
     "effect_receipt": {"external_id": "res-123", "status": "committed"}
   }
   ```

**Resume behavior for W3 (crash after worker effect, before result persistence)**:

This is the critical case mentioned in the acceptance criteria. The coordinator crashed after the worker performed the external effect but before `RESULT_RECEIVED` was persisted. On resume:

```
1. The resume algorithm sees INVOCATION_DISPATCHED with no RESULT_RECEIVED.
2. It cannot know whether the effect was performed.
3. It extracts the idempotency key from the dispatch payload.
4. It queries the external system using the idempotency key:
   a. If the external system confirms the effect was committed:
      -> Adopt the effect result. Emit RESULT_RECEIVED with the adopted result.
      -> Do NOT redispatch. Proceed to validation.
   b. If the external system has no record of the effect:
      -> The effect was not performed. Redispatch.
   c. If the external system returns an ambiguous status:
      -> Emit BLOCKED event with reason "ambiguous external effect".
      -> Escalate per spec: "post-effect failure becomes BLOCKED with escalation"
         (docs/spec/03-runtime-and-events.md:107-108).
```

This protocol follows the spec directly: "The next attempt must query the external system by idempotency key or expected state. It adopts an already completed effect, retries an absent effect, or blocks on an ambiguous effect" (`docs/spec/03-runtime-and-events.md:102-104`).

**What exists now**: The `INVOCATION_DISPATCHED` payload stores `args` (`coordinator.py:133`), but no idempotency key or effect manifest. The `DeterministicWorker` interface (`coordinator.py:22-34`) has no mechanism for the worker to report an effect receipt. These are proposed additions.

## 4. Regression Tests

All tests are implementable against the existing APIs: `EventStore` (`events.py:164-542`), `SequentialCoordinator` (`coordinator.py:37-326`), `DeterministicWorker` (`coordinator.py:22-34`), `TaskLedger` (`tasks.py:43-330`), and `StateDelta` (`delta.py:13-76`).

### Test 1: Crash after INVOCATION_READY, before INVOCATION_DISPATCHED (W1)

```python
def test_crash_after_ready_before_dispatch(tmp_path):
    """Crash after task_started + INVOCATION_READY batch but before dispatch.
    Resume should redispatch the same invocation."""
    store = EventStore(str(tmp_path / "test.db"))
    program = parse_and_validate(program_with_2_steps)
    worker = DeterministicWorker({"define": lambda **kw: "plan",
                                    "search": lambda **kw: "results"})
    coordinator = SequentialCoordinator(store, worker)

    # Manually create run and persist up to INVOCATION_READY for inv-1
    store.create_run("run-1", "test@1.0")
    store.append("run-1", EventType.RUN_STARTED, payload={"program": "test"})
    # Create task batch
    ledger = store.task_ledger("run-1")
    task = ledger.create_task(text="step.frame: DO define", creator="coordinator")
    store.append_batch("run-1", [
        _Record(EventType.TASK_UPDATED, task_id=task.id,
                payload={"kind": "task_created", "id": task.id, ...}),
    ])
    # task_started + INVOCATION_READY batch
    store.append_batch("run-1", [
        _Record(EventType.TASK_UPDATED, task_id=task.id,
                payload={"kind": "task_started", "id": task.id}),
        _Record(EventType.INVOCATION_READY, instruction_id="step.frame",
                invocation_id="inv-1", task_id=task.id,
                payload={"command": "define"}),
    ])

    # Crash happens here. Now resume:
    events = store.events("run-1")
    assert any(e.event_type == EventType.INVOCATION_READY for e in events)
    assert not any(e.event_type == EventType.INVOCATION_DISPATCHED for e in events)

    # Resume should dispatch and complete inv-1, then run inv-2
    result = resume("run-1", program, store, worker)
    assert result["status"] == "succeeded"
    # Verify inv-1 has SUCCEEDED terminal
    all_events = store.events("run-1")
    succeeded = [e for e in all_events if e.event_type == EventType.SUCCEEDED]
    assert len(succeeded) == 2  # both invocations completed
```

### Test 2: Crash after INVOCATION_DISPATCHED, before worker result (W2/W3)

```python
def test_crash_after_dispatch_before_result(tmp_path):
    """Crash after INVOCATION_DISPATCHED but before RESULT_RECEIVED.
    For a pure worker, resume should redispatch and complete."""
    store = EventStore(str(tmp_path / "test.db"))
    program = parse_and_validate(program_with_1_step)
    call_count = 0
    def counting_handler(**kw):
        nonlocal call_count
        call_count += 1
        return "result"
    worker = DeterministicWorker({"define": counting_handler})
    coordinator = SequentialCoordinator(store, worker)

    # Persist up to INVOCATION_DISPATCHED
    store.create_run("run-1", "test@1.0")
    store.append("run-1", EventType.RUN_STARTED, payload={"program": "test"})
    # ... create task, task_started, INVOCATION_READY, INVOCATION_DISPATCHED ...

    # Crash here. Resume:
    result = resume("run-1", program, store, worker)
    assert result["status"] == "succeeded"
    assert call_count == 1  # worker was called exactly once on resume

    # Verify gapless sequence
    events = store.events("run-1")
    seqs = [e.seq for e in events]
    assert seqs == list(range(len(seqs)))  # 0, 1, 2, ... gapless
```

### Test 3: Crash after RESULT_RECEIVED, before VALIDATION_PASSED (W5)

```python
def test_crash_after_result_before_validation(tmp_path):
    """Crash after RESULT_RECEIVED but before VALIDATION_PASSED.
    Resume should revalidate the stored result and proceed."""
    store = EventStore(str(tmp_path / "test.db"))
    program = parse_and_validate(program_with_1_step)
    worker = DeterministicWorker({"define": lambda **kw: "result"})
    coordinator = SequentialCoordinator(store, worker)

    # Persist up to RESULT_RECEIVED
    # ... setup run, task, INVOCATION_READY, INVOCATION_DISPATCHED,
    #     RESULT_RECEIVED ...
    # Crash before VALIDATION_PASSED

    result = resume("run-1", program, store, worker)
    assert result["status"] == "succeeded"

    events = store.events("run-1")
    assert any(e.event_type == EventType.VALIDATION_PASSED for e in events)
    assert any(e.event_type == EventType.SUCCEEDED for e in events)
    assert any(e.event_type == EventType.RUN_FINISHED for e in events)

    # Verify the worker was NOT called again (result adopted from storage)
    # (Track via call_count as in test 2)
```

### Test 4: Crash after VALIDATION_PASSED, before SUCCEEDED batch (W6)

```python
def test_crash_after_validation_before_succeeded(tmp_path):
    """Crash after VALIDATION_PASSED but before SUCCEEDED batch.
    Resume should emit SUCCEEDED batch using stored result and advance."""
    store = EventStore(str(tmp_path / "test.db"))
    program = parse_and_validate(program_with_2_steps)
    worker = DeterministicWorker({"define": lambda **kw: "plan",
                                    "search": lambda **kw: "results"})

    # Persist up to VALIDATION_PASSED for inv-1
    # ... setup run, task, READY, DISPATCHED, RESULT_RECEIVED,
    #     VALIDATION_PASSED ...
    # Crash before SUCCEEDED batch

    result = resume("run-1", program, store, worker)
    assert result["status"] == "succeeded"

    events = store.events("run-1")
    succeeded_events = [e for e in events
                       if e.event_type == EventType.SUCCEEDED]
    assert len(succeeded_events) == 2

    # Verify state projection includes the delta from inv-1
    state = store.project_state("run-1")
    assert "G.plan" in state["nodes"]  # from inv-1's delta
```

### Test 5: Crash after worker effect but before local success persistence (critical acceptance case)

```python
def test_crash_after_external_effect_before_success(tmp_path):
    """Crash after an externally effectful worker performs the side effect
    but before RESULT_RECEIVED is persisted. Resume must use the idempotency
    key to query the external system and adopt or retry accordingly."""
    store = EventStore(str(tmp_path / "test.db"))
    program = parse_and_validate(program_with_1_effectful_step)

    # Mock external system that records idempotency keys
    external_system = {}
    effect_results = {}

    def effectful_worker(**kw):
        idempotency_key = kw.get("idempotency_key")
        if idempotency_key in external_system:
            # Effect already performed -- this is a redispatch
            return effect_results[idempotency_key]
        # Perform the effect
        external_system[idempotency_key] = "committed"
        result = {"effect_id": "ext-001", "status": "committed"}
        effect_results[idempotency_key] = result
        return result

    worker = DeterministicWorker({"effect": effectful_worker})

    # Persist up to INVOCATION_DISPATCHED with idempotency key in payload
    store.create_run("run-1", "test@1.0")
    store.append("run-1", EventType.RUN_STARTED, payload={"program": "test"})
    # ... create task, INVOCATION_READY ...
    idempotency_key = "run-1:step.effect:inv-1:0"
    store.append("run-1", EventType.INVOCATION_DISPATCHED,
        invocation_id="inv-1", task_id=task_id,
        payload={"args": {}, "idempotency_key": idempotency_key})

    # Simulate: worker was called, effect was performed, but crash
    # before RESULT_RECEIVED
    external_system[idempotency_key] = "committed"
    effect_results[idempotency_key] = {"effect_id": "ext-001",
                                         "status": "committed"}

    # Resume: the algorithm should query the external system via
    # idempotency_key, find the effect was already committed, and adopt
    # the result WITHOUT redispatching.
    result = resume("run-1", program, store, worker,
                    external_system=external_system)
    assert result["status"] == "succeeded"

    events = store.events("run-1")
    result_event = next(e for e in events
                       if e.event_type == EventType.RESULT_RECEIVED)
    assert result_event.payload["result"]["effect_id"] == "ext-001"

    # Verify the effect was NOT performed twice
    assert len(external_system) == 1  # only one idempotency key
```

### Test 6: Crash after all invocations succeed, before RUN_FINISHED (W9)

```python
def test_crash_after_all_succeeded_before_run_finished(tmp_path):
    """All invocations have SUCCEEDED but RUN_FINISHED was not persisted.
    Resume should emit RUN_FINISHED and return succeeded."""
    store = EventStore(str(tmp_path / "test.db"))
    program = parse_and_validate(program_with_2_steps)
    worker = DeterministicWorker({"define": lambda **kw: "plan",
                                    "search": lambda **kw: "results"})

    # Run to completion normally
    coordinator = SequentialCoordinator(store, worker)
    coordinator.execute(program, run_id="run-1")

    # Delete the RUN_FINISHED event to simulate crash before persistence
    store._conn.execute(
        "DELETE FROM events WHERE run_id = ? AND event_type = ?",
        ("run-1", EventType.RUN_FINISHED.value)
    )

    # Verify RUN_FINISHED is gone
    events = store.events("run-1")
    assert not any(e.event_type == EventType.RUN_FINISHED for e in events)
    # Verify all invocations succeeded
    succeeded = [e for e in events if e.event_type == EventType.SUCCEEDED]
    assert len(succeeded) == 2

    # Resume should emit RUN_FINISHED
    result = resume("run-1", program, store, worker)
    assert result["status"] == "succeeded"

    events = store.events("run-1")
    finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
    assert len(finished) == 1
    assert finished[0].payload["status"] == "succeeded"
```

## 5. Exactly-Once vs At-Least-Once Guarantees

### Exactly-once (guaranteed by the current runtime)

1. **State delta commits**: The `SUCCEEDED` event with its `StateDelta` is committed atomically inside a `BEGIN IMMEDIATE` transaction (`events.py:290, 411`). The CAS check on `expected_state_version` (`events.py:335-339`) ensures only one delta commits against a given read version. The duplicate-SUCCEEDED guard (`events.py:342-348`) prevents a second terminal for the same invocation. On resume, if `SUCCEEDED` is already persisted, the invocation is skipped. If it was not persisted, the delta is recomputed from the stored result and committed with the current state version. This is exactly-once.

2. **Event sequence numbers**: Gapless per run, guaranteed by `MAX(seq)+1` inside the transaction (`events.py:300-303`). On resume, new events continue from the last committed seq. No gaps, no duplicates.

3. **Task ledger transitions**: The `TaskLedger._apply()` method (`tasks.py:244-330`) validates state transitions (e.g., cannot start a task that is not `PENDING`, cannot complete a task that is not `IN_PROGRESS`). The `append_batch` method validates `TASK_UPDATED` records against the ledger projected at transaction start (`events.py:352-354`). Invalid transitions roll back the entire batch.

4. **Multi-target deltas**: When a worker returns results for multiple targets, the coordinator computes all `add_nodes` and wraps them in a single `StateDelta` (`coordinator.py:195-258`). This delta is committed in a single `SUCCEEDED` event inside one atomic batch. A partial multi-target delta cannot commit -- either all targets are applied or none.

5. **Run terminal events**: `RUN_FINISHED` is a single append (`coordinator.py:321-325`). On resume, if it exists, the run is terminal and no further events are appended. If it does not exist, the resume algorithm determines what is missing and emits exactly one `RUN_FINISHED`.

### At-least-once (without external system cooperation)

1. **Worker dispatch**: The `INVOCATION_DISPATCHED` event is persisted before the worker is called (`coordinator.py:127-134`). If the coordinator crashes after dispatch but before `RESULT_RECEIVED` (W2/W3), the worker may or may not have executed. On resume, the worker is redispatched. For pure workers, this is safe (idempotent). For read-only workers, a new read may return different data, but the first persisted `RESULT_RECEIVED` is authoritative. For effectful workers, the effect may be performed twice unless the external system supports idempotency key-based deduplication.

2. **External side effects**: This is the fundamental at-least-once boundary. The spec acknowledges this: "Side-effect dispatch may be at-least-once; accepted commit is at-most-once" (`docs/spec/03-runtime-and-events.md`, invariant 7). The coordinator cannot prevent duplicate external effects without cooperation from the external system. The proposed idempotency key protocol (Section 3) reduces this to exactly-once *when the external system supports idempotency keys*, but the runtime itself can only guarantee at-least-once dispatch.

3. **The W3 crash window** (crash after effect, before result persistence): This is the hardest case. The coordinator cannot distinguish "worker crashed before effect" from "worker crashed after effect" -- both look like `INVOCATION_DISPATCHED` with no `RESULT_RECEIVED`. The proposed protocol requires the external system to support idempotency key queries. If it does, the resume algorithm queries, adopts, or retries. If it does not, the effect may be duplicated, and the only mitigation is to make the effect itself idempotent (e.g., upsert with a unique key).

### Summary table

| Guarantee | Scope | Mechanism |
|---|---|---|
| Exactly-once | State delta application | Atomic batch + CAS + duplicate-SUCCEEDED guard |
| Exactly-once | Event sequence gaplessness | `MAX(seq)+1` in transaction |
| Exactly-once | Task ledger transitions | State machine validation in `_apply()` |
| Exactly-once | Multi-target delta atomicity | Single SUCCEEDED event in one batch |
| Exactly-once | Run terminal detection | RUN_FINISHED presence check |
| At-least-once | Worker dispatch | Redispatch on resume after W2/W3 |
| At-least-once | External side effects | Idempotency key protocol (requires external cooperation) |
| At-most-once | Accepted commit | SUCCEEDED is terminal; duplicate rejected |

### Existing vs proposed behavior

| Aspect | Existing (current code) | Proposed |
|---|---|---|
| Event persistence | Atomic batches via `append_batch` (`events.py:264-419`) | No change -- already exactly-once |
| State delta commit | CAS on `expected_state_version` (`events.py:335-339`) | No change -- already exactly-once |
| Duplicate SUCCEEDED prevention | `succeeded_invocations` set check (`events.py:342-348`) | No change |
| Resume / recovery | Not implemented -- coordinator is sequential, no resume logic (`coordinator.py:44-326`) | Proposed: `resume()` algorithm in Section 2 |
| Idempotency keys | Not stored in event payloads | Proposed: add to `INVOCATION_DISPATCHED` payload |
| Effect manifest | Not stored | Proposed: add to `INVOCATION_DISPATCHED` payload |
| Effect receipt | Not returned by `DeterministicWorker` | Proposed: extend worker interface |
| External system query on resume | Not implemented | Proposed: query-by-idempotency-key protocol in Section 3 |
| W5/W6 recovery (revalidate stored result) | Not implemented | Proposed: revalidation logic in resume algorithm |
| W9 recovery (emit missing RUN_FINISHED) | Not implemented | Proposed: terminal check in resume algorithm |
