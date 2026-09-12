# Solution — issue #40: status lifecycle

## Problem

`_cmd_status` (cli.py) rendered only the ledger profile and never read `RUN_FINISHED`; `profile()["current_task"]` returned the first IN_PROGRESS task via `next()`, so concurrent runs displayed one arbitrary task, and failed runs printed `current task: (none)` with a progress bar — identical in shape to a healthy queued run.

## Fix

### src/tahoe/runtime/tasks.py

`TaskLedger.profile()` now builds `in_progress_ids` as a full list comprehension instead of a `next()` generator. The existing `current_task` key stays backward-compatible (`in_progress_ids[0] if in_progress_ids else None`), and a new `in_progress_tasks` key carries the complete list.

### src/tahoe/cli.py

1. **`_run_terminal_status(store, run_id)`**: scans the event stream for `RUN_FINISHED` events. Returns `(status, error)` from the last RUN_FINISHED payload (`{"status": "succeeded"}` or `{"status": "failed", "error": "..."}`). When no RUN_FINISHED exists, returns `("running", None)` — the run is non-terminal (running or crashed).

2. **`_cmd_status`**: calls `_run_terminal_status()` and prints a `status: running|succeeded|failed[:error]` line above the progress bar. When multiple tasks are IN_PROGRESS, each is listed individually. For non-terminal runs, prints `hint: tahoe resume`.

3. **`--json`**: the JSON payload now carries `status` (terminal status from RUN_FINISHED, not the old `run_info["status"]`), `in_progress_tasks` (list of `{id, text}`), `error` (from failed RUN_FINISHED), and `hint` (`"tahoe resume"` for non-terminal, `null` otherwise).

### tests/test_status.py

11 new tests:
- failed run shows failed marker + error (human + json)
- concurrent run lists all IN_PROGRESS tasks (human + json)
- crashed (non-terminal) run shows running, hints resume (human + json)
- succeeded run still works (regression, human + json)
- profile() returns in_progress_tasks list / empty when all done

## Files changed

- `src/tahoe/cli.py` — `_run_terminal_status()` helper + rewritten `_cmd_status`
- `src/tahoe/runtime/tasks.py` — `profile()` adds `in_progress_tasks`
- `tests/test_status.py` — new, 11 tests
- `demo/runs/sprint2-40-status/` — program.think, seal.txt, WORKLOG.md, solution.md, evaluation.json

## Test results

864 baseline + 11 new = **875 passed** in 21.62s
