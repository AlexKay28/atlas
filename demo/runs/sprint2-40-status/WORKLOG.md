# WORKLOG — sprint2-40-status

Seal: 77cad870ab6853acc53e5b94614d7a97fee27eb71201a0683d805aaaad9c2a66
Program: demo/runs/sprint2-40-status/program.think (linted valid and sealed 2026-09-12T19:30:00Z before any source edit; the program was copied from the sealed resolution plan in issue #40's comment, with only string literal path references changed from `src/atlas/` to `src/tahoe/` per the #53 TAHOE rebrand — logic stays identical. Recorded as a protocol note in evaluation.json.)

## step.frame
Status: succeeded
Inputs: G.goal from program.think INPUT block
Actions: Framed the issue: `_cmd_status` must answer "is my run stuck/dead/done" by reading RUN_FINISHED (or its absence) and rendering `status: running|succeeded|failed[:error]` above the progress bar; list ALL in-progress tasks in concurrent mode; hint `tahoe resume` when a run is non-terminal and stale.
Outputs: G.plan = the status lifecycle fix.

## step.search
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located the three integration points: (1) `cli.py:641-697` `_cmd_status` — renders only the ledger profile, never reads RUN_FINISHED; (2) `tasks.py:218-225` `profile()["current_task"]` — returns the first IN_PROGRESS task via `next()`, so concurrent runs show one arbitrary task; (3) `events.py:37` `EventType.RUN_FINISHED` — carries `{"status": "succeeded|failed", "error": "..."}` payload.
Outputs: E.sites = the three integration points.

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read the full `_cmd_status` implementation, `TaskLedger.profile()`, `EventStore.events()`, `EventType` enum, coordinator's RUN_FINISHED payloads (succeeded: `{"status": "succeeded"}`, failed: `{"status": "failed", "error": error}`), and existing status tests in test_cli.py and test_cli_ergo.py.
Outputs: ART.sources = the read sources.

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Pinned the defect: (a) `_cmd_status` gets `run_info` from `store.run()` which returns metadata but never the terminal status; (b) the event stream must be scanned for `RUN_FINISHED` to determine terminal state; (c) `profile()["current_task"]` uses `next()` which yields only the first match — need a list of all IN_PROGRESS task ids; (d) a crashed run has no RUN_FINISHED at all, so status should be "running" (non-terminal) with a `tahoe resume` hint to distinguish from a finished run.
Outputs: E.findings = the defect analysis.

## step.plan
Status: succeeded
Inputs: G.plan
Actions: Decomposed into three subtasks: (1) `tasks.py`: add `in_progress_tasks` list to `profile()` alongside existing `current_task` (backward compat — `current_task` stays as `in_progress_ids[0]`); (2) `cli.py`: rewrite `_cmd_status` to scan events for RUN_FINISHED, render `status: running|succeeded|failed[:error]` line, list all IN_PROGRESS tasks when >1, hint `tahoe resume` for non-terminal; add `--json` fields: `status`, `in_progress_tasks`, `error`, `hint`; (3) `tests/test_status.py`: 11 tests covering failed/concurrent/crashed/succeeded/json.
Outputs: G.subgoals = the three subtasks.

## step.patch
Status: succeeded
Inputs: G.subgoals, C.scope
Actions: Applied the patch: (1) `tasks.py`: replaced the `next()` generator with a list comprehension building `in_progress_ids`, set `current = in_progress_ids[0] if in_progress_ids else None`, added `"in_progress_tasks": in_progress_ids` to the profile dict; (2) `cli.py`: added `_run_terminal_status()` helper that scans events for RUN_FINISHED and returns `(status, error)`; rewrote `_cmd_status` to call it, print `status:` line before the progress bar, list all IN_PROGRESS tasks when >1 (human), add `in_progress_tasks`/`error`/`hint` to JSON; (3) `tests/test_status.py`: 11 new tests.
Outputs: ART.patch.

## step.test
Status: succeeded
Inputs: ART.patch
Actions: Ran full test suite: `PYTHONPATH=src python3 -m pytest -q` -> 875 passed in 21.62s (864 baseline + 11 new).
Outputs: V.tests = 875/875 green.

## step.check
Status: succeeded
Inputs: V.tests, C.done
Actions: Verified acceptance: (1) failed run shows `status: failed: kaput` — test_status_failed_run_shows_failed_marker_and_error; (2) concurrent run lists every IN_PROGRESS task — test_status_concurrent_run_lists_all_in_progress_tasks; (3) crashed (non-terminal) run shows `status: running` + `hint: tahoe resume`, distinct from `status: succeeded` — test_status_crashed_run_shows_running_not_succeeded, test_status_crashed_run_hints_resume; (4) --json carries `status`, `in_progress_tasks`, `error`, `hint` — test_status_failed_run_json_carries_error, test_status_concurrent_run_json_lists_all_in_progress, test_status_crashed_run_json_is_running_with_resume_hint; (5) existing suite green — 864 baseline unmodified.
Outputs: V.verdict = acceptance met.

## step.report
Status: succeeded
Inputs: V.verdict, V.tests
Actions: Rendered solution.md + evaluation.json; verified git status shows only owned files.
Outputs: ART.report.
