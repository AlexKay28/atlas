# Solution — issue #41: Budgets, take 2

## Files changed
- `src/tikhon/budgets.py` — `ExecutionBudget.max_total_tokens`, `BudgetGate.elapsed_offset`, `BudgetGate.add_tokens`/`spent_tokens`/`token_cap_exceeded`
- `src/tikhon/resume.py` — `resume_run(budget=, max_workers=)`, gate construction with elapsed offset from first event timestamp
- `src/tikhon/runtime/coordinator.py` — `_command_max_attempts`, attempt tracking in both paths, token feeding from `_receipt` in result dicts, claims threading through `_drive_plan_concurrent`, bounded `drain_in_flight(timeout=1.0)`, `pool.shutdown(wait=False)`
- `tests/test_budgets2.py` — 9 new tests covering all 6 acceptance items

## Implementation summary

### Part A: Resume gate
- `resume_run` gains `budget: ExecutionBudget | None = None` and `max_workers: int | None = None`
- When `budget` is set and `global_deadline_seconds` is not None, the elapsed offset is derived from `(now - events[0].occurred_at).total_seconds()` so the gate enforces the *remaining* deadline
- `BudgetGate.__init__` accepts `elapsed_offset` and shifts `_started` backwards
- `_resume_existing_run` gains `max_workers` parameter, threads through to concurrent path

### Part B: Wedged-worker wall-clock
- `drain_in_flight` gains a `timeout=1.0` parameter so `concurrent.futures.wait` is bounded
- Per-invocation deadline path: `finish_failed_invocation` (which commits the failure batch) runs BEFORE `drain_in_flight` so a hung handler cannot block the commit
- `ThreadPoolExecutor` context manager replaced with manual `try/finally` + `pool.shutdown(wait=False)` so pool exit is non-blocking

### Part C: Claims on concurrent path
- `_drive_plan_concurrent` gains `claims: ResourceLedger | None = None`
- `dispatch_entry` claims `workspace:<run_id>:<invocation_id>` for effectful commands, annotates DISPATCHED payload with `resource_claims`
- `process_completion` releases the claim after the handler returns (success or failure)
- `held_claims` dict tracks per-invocation claim resources

### Part D: Token/attempt caps
- `ExecutionBudget` gains `max_total_tokens: int | None = None`
- `BudgetGate` gains `add_tokens(count)`, `spent_tokens` property, `token_cap_exceeded()` method
- Both sequential and concurrent paths feed the gate from `result["_receipt"]["usage"]["tokens"]` after RESULT_RECEIVED
- Token cap exceeded → `finish_failed_invocation` with "token budget exceeded"
- `_command_max_attempts(command)` resolves the registry's `contract.budget.max_attempts`; both paths track `attempt_counts` and refuse dispatch when the cap is met
- `budget=None` and caps unset → all code paths untouched (byte-identical)

## Test results
```
PYTHONPATH=src python3 -m pytest -q → 779 passed in 18.87s
```
(770 pre-existing + 9 new)
