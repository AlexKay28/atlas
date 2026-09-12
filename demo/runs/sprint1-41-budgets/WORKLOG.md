# WORKLOG — sprint1-41-budgets

Seal: 7e79777961edb16ae117da0a73ade3f277151d9332887daa118ec511b80e4b9c
Program: demo/runs/sprint1-41-budgets/program.think (linted valid and sealed 2026-09-12T19:30:00Z before any source edit)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed issue #41 into four implementation parts: (A) resume gate with elapsed offset; (B) wedged-worker wall-clock bounding; (C) claims threading through concurrent path; (D) token/attempt caps enforcement.
Outputs: G.plan = the four-part implementation plan.
Evidence: gh issue view 41.

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located every touch point: budgets.py (ExecutionBudget, BudgetGate); resume.py (resume_run, _resume_existing_run call); coordinator.py (_drive_plan ~4249, _drive_plan_concurrent ~5209, _execute_worker_call ~4143, _dispatch_worker_call ~4095, _frontier_wait_timeout ~4119); envelope.py lines 220-260 (contract.budget shape) and 1290-1330 (_recorded_usage); claims.py (ResourceLedger).
Outputs: E.sites = the integration points above.
Evidence: Read-only source inspection of all named regions.

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read the full source of budgets.py (153 lines), resume.py (145 lines), targeted regions of coordinator.py (6k lines), claims.py (88 lines), envelope.py regions (220-260, 1290-1330), test_budgets.py (585 lines), test_resume.py (449 lines), test_frontier.py (header), demo/runs/issue-26-benchmarks/ (sealed-run format).
Outputs: ART.sources = the read sources.
Evidence: All files listed in C.scope plus read-only context files.

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Analyzed the four enforcement holes: (A) resume_run has no budget parameter, BudgetGate._started uses time.monotonic() with no offset; (B) drain_in_flight blocks forever on hung handlers, ThreadPoolExecutor.__exit__ also blocks; per_invocation_deadline_seconds is enforced via _frontier_wait_timeout but the drain after failure is unbounded; (C) _drive_plan_concurrent has no claims parameter, concurrent effectful dispatches have no workspace claim; (D) ExecutionBudget has no max_total_tokens, BudgetGate has no token accumulator, contract.budget.max_attempts is never checked at dispatch.
Outputs: E.findings = the four holes with specific line references.
Evidence: Source analysis of coordinator.py, budgets.py, envelope.py.

## step.decompose
Status: succeeded
Inputs: G.plan
Actions: Split into four subtasks matching the issue's Fix section: (A) add budget/max_workers to resume_run, derive elapsed_offset from first event timestamp, thread through _resume_existing_run; (B) bound drain_in_flight with timeout, finalize failure before drain, use pool.shutdown(wait=False); (C) add claims parameter to _drive_plan_concurrent, claim workspace:<run_id>:<invocation_id>, release after handler; (D) add max_total_tokens to ExecutionBudget, add token accumulator to BudgetGate, feed gate from result receipts, enforce max_attempts via _command_max_attempts.
Outputs: G.subgoals = the four subtasks.
Evidence: This decomposition.

## step.hypothesize / step.compare / step.rank / step.challenge / step.choose
Status: succeeded
Inputs: E.findings, C.done
Actions: Chose elapsed_offset from first event timestamp (vs explicit parameter) because events[0].occurred_at is always available and requires no API change. Chose pool.shutdown(wait=False) over daemon thread policy because it's simpler and ThreadPoolExecutor already uses daemon threads internally. Chose _receipt key convention for token feeding because envelope.py is forbidden. Chose _command_max_attempts lookup table (cached) for attempt cap enforcement.
Outputs: D.choice = the implementation design.
Evidence: Source analysis.

## step.solve / step.prove
Status: succeeded
Inputs: G.goal / C.done
Actions: Implemented all four parts: budgets.py (+61 lines: max_total_tokens, elapsed_offset, token accumulator); resume.py (+41 lines: budget/max_workers params, gate construction with elapsed offset); coordinator.py (+200 lines: _command_max_attempts, attempt tracking, token feeding, claims threading, bounded drain, pool.shutdown(wait=False)). All 770 pre-existing tests pass; 9 new tests cover all 6 acceptance items.
Outputs: U.solution, A.proof.
Evidence: PYTHONPATH=src python3 -m pytest -q -> 779 passed in 18.87s.

## step.patch / step.test / step.check
Status: succeeded
Inputs: P.design
Actions: Applied patches to src/tikhon/budgets.py, src/tikhon/resume.py, src/tikhon/runtime/coordinator.py. Wrote tests/test_budgets2.py with 9 tests covering all 6 acceptance items plus 3 helper tests. Full suite: 779 passed (770 existing + 9 new) in 18.87s.
Outputs: ART.patch, V.tests = 9/9 green; full suite 779 passed.
Evidence: PYTHONPATH=src python3 -m pytest -q -> 779 passed in 18.87s.

## step.report / step.verify
Status: succeeded
Inputs: V.verdict / G.goal, V.tests, R.samples
Actions: Verified all 6 acceptance items: (1) resume with budget enforces remaining deadline; (2) 10s handler + 0.1s deadline returns < 3s; (3) concurrent edit DISPATCHED payloads carry resource_claims; (4) summed receipt tokens over cap → RUN_FINISHED failed; (5) max_attempts enforced at dispatch; (6) budget=None byte-identical. Git status shows changes only in owned files (budgets.py, resume.py, coordinator.py, test_budgets2.py, demo/runs/sprint1-41-budgets/).
Outputs: ART.report, V.result, and this WORKLOG/solution.md/evaluation.json.
Evidence: 9/9 new tests green; 779 total green; git status clean for owned files only.
