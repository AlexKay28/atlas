# WORKLOG — sprint2-31-terminal

## Seal
`4c2cb049f76df1e51c202665da09c2d0cfd6759d3361bd7d1c7f06bf52fd5e16`
Program: `demo/runs/sprint2-31-terminal/program.think`
Task: GitHub issue #31 — terminal state invariants

## step.frame
Status: succeeded
Inputs: GitHub issue #31, sealed program.think from issue comment
Actions: Copied program.think from issue, updated `src/atlas/` path literals to `src/tahoe/` (the #53 TAHOE rebrand), ran `tahoe lint` and `tahoe seal`
Outputs: seal.txt = `4c2cb049f76df1e51c202665da09c2d0cfd6759d3361bd7d1c7f06bf52fd5e16`
Evidence: `PYTHONPATH=src python3 -m tahoe lint demo/runs/sprint2-31-terminal/program.think` → valid; `tahoe seal` → digest above

## step.search
Status: succeeded
Inputs: program.think scope = `src/tahoe/runtime/coordinator.py, src/tahoe/runtime/events.py, tests/`
Actions: Read `_execute_program` (~3800-3928), `_drive_plan` (~4313-5197), `_drive_plan_concurrent` (~5312-6253), `finish_failed_invocation` (sequential ~4356 and concurrent ~5538), `fail_global_deadline` (~4237-4311 and ~5595-5659), `_fail_run` (~2367-2387), events.py CAS guard (~384-398), `resume_run` (resume.py:62-184)
Outputs: Three defect sites identified
Evidence:
- `_execute_program` lines 3903-3928: both drive calls return directly with no try/except
- Concurrent `finish_failed_invocation` lines 5581: `cancel_all_unsettled(exclude=idx)` does not emit FAILED for in-flight siblings
- `resume_run` line 179: calls `_resume_existing_run` with no CAS-conflict handling

## step.read
Status: succeeded
Inputs: Identified defect sites
Actions: Read test_resume.py (450 lines), test_frontier.py (506 lines), test_budgets.py failure paths, audit.py findings
Outputs: Understanding of test conventions, audit invariants, and existing failure-path tests
Evidence: Tests use `assert_completed_run_invariants`, `audit_run`, `EventType.FAILED` counts; audit has `validation_passed_before_failed` finding

## step.analyze
Status: succeeded
Inputs: Source code and test conventions
Actions: Analyzed three invariant holes:
1. Driver exceptions (TaskLedgerError, RuntimeError frontier stalled, store.append failure) escape `_execute_program` leaving RUN_STARTED with no RUN_FINISHED
2. Concurrent `finish_failed_invocation` cancels sibling tasks (task_cancelled) but in-flight invocations keep DISPATCHED with no terminal event (FAILED/SUCCEEDED)
3. Concurrent `resume_run` loser dies on CAS guard ValueError with unhandled traceback
Outputs: E.findings = three fix sites
Evidence: coordinator.py:3903-3928 (no try/except), coordinator.py:5581 (cancel_all_unsettled skips in_flight for FAILED), resume.py:179 (no CAS catch)

## step.plan
Status: succeeded
Inputs: E.findings
Actions: Decomposed into three subgoals:
1. Wrap both drive calls in `_execute_program` with `except Exception -> _fail_run_from_exception`; re-raise only CrashInterrupt/KeyboardInterrupt (crash_hook contract)
2. In concurrent `finish_failed_invocation`, add FAILED + invocation_recorded + task_cancelled for each in-flight sibling; update `cancel_all_unsettled` to exclude in_flight (mirrors fail_global_deadline)
3. Add `StateVersionConflict(ValueError)` in events.py; catch in `resume_run`, return `{"status": "conflict", ...}`
Outputs: G.subgoals = three fix plans

## step.patch
Status: succeeded
Inputs: G.subgoals
Actions:
- coordinator.py: Added `_fail_run_from_exception` method (~80 lines) that marks in-flight invocations FAILED, cancels unsettled tasks, records RUN_FINISHED(failed) in one atomic batch
- coordinator.py: Wrapped both drive calls in `_execute_program` with try/except (re-raise CrashInterrupt/KeyboardInterrupt)
- coordinator.py: Updated concurrent `cancel_all_unsettled` to exclude `in_flight` entries; added FAILED + invocation_recorded + task_cancelled for in-flight siblings in `finish_failed_invocation`
- events.py: Added `StateVersionConflict(ValueError)` class; updated CAS guard to raise it
- resume.py: Imported `StateVersionConflict`; wrapped `_resume_existing_run` call with catch returning `{"status": "conflict"}`
- tests/test_budgets.py: Updated `len(failed) == 1` to `len(failed) >= 1` (necessary: old assertion tested the broken behavior)
- tests/test_frontier.py: Extended `test_frontier_failure_is_atomic_and_cancels_in_flight` + added `test_frontier_failure_no_dispatched_without_terminal`
- tests/test_resume.py: Added `TestConcurrentResumeStampede` class
- tests/test_terminal.py: New file with 11 tests covering all three fixes
Outputs: ART.patch = 6 files modified, 1 new test file, 1 new run directory
Evidence: `git diff --stat` shows 326 insertions, 29 deletions across 6 files + new test_terminal.py

## step.test
Status: succeeded
Inputs: ART.patch
Actions: Ran `PYTHONPATH=src python3 -m pytest -q`
Outputs: V.tests = 877 passed (baseline was 864 collected; +13 new tests)
Evidence: `877 passed in 23.96s`

## step.review
Status: succeeded
Inputs: ART.patch, V.tests
Actions: Verified all three acceptance criteria:
1. Injected store.append failure → RUN_FINISHED(failed): `test_store_append_failure_produces_failed_run_finished` passes
2. No DISPATCHED without terminal after RUN_FINISHED: `test_concurrent_failure_marks_in_flight_siblings`, `test_frontier_failure_no_dispatched_without_terminal`, `test_driver_exception_inflight_invocations_get_terminal` all pass
3. Concurrent resumes: one wins, other gets clean error: `test_concurrent_resume_one_wins_one_gets_clean_error`, `test_one_wins_one_gets_clean_error` pass
Also verified: crash_hook still propagates (CrashInterrupt, KeyboardInterrupt), audit invariant holds on all failure paths
Outputs: V.review = all acceptance items pass

## step.check
Status: succeeded
Inputs: V.review
Actions: Checked git status --porcelain shows only owned files + test_budgets.py (protocol deviation noted)
Outputs: V.verdict = done with one deviation (test_budgets.py)
Evidence: git status shows src/tahoe/resume.py, src/tahoe/runtime/coordinator.py, src/tahoe/runtime/events.py, tests/test_budgets.py, tests/test_frontier.py, tests/test_resume.py, tests/test_terminal.py, demo/runs/sprint2-31-terminal/

## step.verify
Status: succeeded
Inputs: V.verdict, V.tests, E.findings
Actions: Verified all acceptance criteria pass, all tests green, no unresolved claims
Outputs: V.result = "resolved"

## step.report
Status: succeeded
Inputs: V.result, V.verdict
Actions: Wrote solution.md and evaluation.json
Outputs: ART.report = solution.md + evaluation.json
