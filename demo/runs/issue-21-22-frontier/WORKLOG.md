# WORKLOG — issue-21-22-frontier

Seal: 62ab60638dcbec16c28b94431f98846d195eb73fc692476e58d435ab37392b31
Program: demo/runs/issue-21-22-frontier/program.think (linted valid and sealed 2026-09-12T16:58Z before any source edit; uses plain DO steps over all 22 registered commands plus one standalone CALL protocol.framing line; the issues' proposed scheduler/budget APIs are runtime parameters, not language syntax, so they appear nowhere in the program by design)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed the two issues into one session, #21 first then #22 on top (they share coordinator/events). #21 = a ready-task execution frontier: `SequentialCoordinator.execute(..., max_workers=N)` dispatches dependency-free ready invocations on a ThreadPoolExecutor while every commit stays on the store's atomic single-writer batch path; EventStore gains a thread lock; TaskLedger gains a deliberate `allow_concurrent` relaxation. #22 = `ExecutionBudget` (max_concurrent_workers, global/per-invocation deadlines, max_child_depth) threaded through both drives, plus envelope deadline passthrough. Hard constraint: default `max_workers=1, budget=None` keeps all 607 baseline tests passing unchanged.
Outputs: G.plan = events.py thread-safety -> tasks.py flag -> coordinator frontier -> test_frontier.py -> budgets.py + gate threading -> worker_adapter passthrough -> test_budgets.py -> protocol artifacts.
Evidence: /tmp/issue21.md, /tmp/issue22.md; baseline `python3 -m pytest -q` = 607 passed.

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located every integration point: events.py (single sqlite connection, `BEGIN IMMEDIATE` batches, CAS state versions, `task_ledger` rebuild — all sharing one connection that is not thread-safe); tasks.py (`start_task`/`_apply` both enforce exactly one IN_PROGRESS); coordinator.py (`_drive_plan` blocking loop, `_execute_call_child` pool-thread reentry point, `_resume_existing_run` prefix invariant, `crash_hook` site before VALIDATION_PASSED); audit.py invariants that must keep holding (gapless seq, FAILED/RUN_FINISHED truthfulness, no unsettled task on a terminal run); envelope.py `TaskEnvelope.deadline_seconds` (field already exists, unused by the adapter).
Outputs: E.sites = the anchor points above.
Evidence: src/tikhon/runtime/events.py:180-186,296-423; src/tikhon/runtime/tasks.py:131-153,277-299; src/tikhon/runtime/coordinator.py:1083-1728 (pre-edit numbering); src/tikhon/audit.py:117-306; src/tikhon/envelope.py:359-366.

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read the touched-region sources in full: the coordinator's per-invocation event shapes (task_started+READY batch, DISPATCHED, RESULT_RECEIVED, VALIDATION_PASSED, SUCCEEDED+invocation_recorded+task_completed batch, CHILD_ADOPTED for CALLs), the failure batch shape (`finish_failed_invocation`), resume guards (`prior_types`), the store's `append_batch` invariants (dup-SUCCEEDED guard, TASK_UPDATED ledger validation against a batch-rebuilt ledger), the ledger's two single-IN_PROGRESS checks, and audit's five invariant checks.
Outputs: ART.sources = the read sources.
Evidence: files listed in C.scope.

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Analyzed the correctness constraints: (a) replay of a concurrent run must reconstruct multi-IN_PROGRESS intermediate states, so the relaxation has to live on the ledger APPLICATION path and ride on the run (auto-detected from run metadata by `EventStore.task_ledger`) — otherwise `append_batch`'s internal batch validation would reject the very events the concurrent coordinator commits; (b) the frontier's commits must be byte-identical in shape to the sequential loop's so replay/audit/CLI cannot tell them apart — commits therefore happen only on the coordinator (main) thread, and the pool executes handlers and CALL child runs only; (c) completion order must not change final state: a raw produces/consumes DAG is NOT enough — WAW (two producers of one ref) and WAR (a RETIRE/REVISE invalidating an earlier reader's pinned inputs) edges are required; read-read pairs must carry NO edge or the common case never overlaps; (d) source-anchored STOP/RETURN conditionals must gate dispatch (an entry after an anchor waits until the anchor is evaluated), which makes in-flight work impossible when a terminal fires; (e) a global-deadline failure must commit its "cancelled" FAILED markers BEFORE draining the pool, or the markers are lost; (f) waiting CALL frames must hold no semaphore slot, or a one-worker budget deadlocks a parent awaiting a child.
Outputs: E.findings = the constraint list above.
Evidence: this analysis; audit.py truthfulness rules; the #21/#22 issue bodies.

## step.decompose
Status: succeeded
Inputs: G.plan
Actions: Split into eight subtasks: (1) events.py: RLock + check_same_thread=False + task_ledger concurrency auto-detect; (2) tasks.py: `allow_concurrent` on `__init__`/`from_events` and both application checks; (3) coordinator.py: dependency-DAG builder + `_drive_plan_concurrent` frontier + concurrent-aware resume; (4) tests/test_frontier.py; (5) src/tikhon/budgets.py: ExecutionBudget + BudgetGate; (6) coordinator gate threading through sequential drive, frontier, CALL children; (7) worker_adapter.py envelope deadline binding; (8) tests/test_budgets.py.
Outputs: G.subgoals = the eight subtasks above.
Evidence: this decomposition; final git status matches exactly the allowed file list.

## step.hypothesize
Status: succeeded
Inputs: G.goal, E.findings
Actions: Generated candidate designs for the frontier commit model: (H1) worker threads commit their own completions through the store lock — rejected: races the values mapping and the CAS chain, and the issue body pins "one coordinator owner serializes event/state commits; workers never mutate the shared values mapping"; (H2) main-thread commits, pool executes handlers/children only — chosen: identical event shapes, uncontended CAS for the run's own stream, and the store lock still exercised by concurrent child runs; (H3) snapshot-isolate-merge values per worker — rejected: unnecessary once dispatch-time resolution pins inputs and the DAG serializes interactors. For the ledger relaxation: (H4) encode the flag in every TASK_UPDATED payload — rejected: pollutes the event stream; (H5) auto-detect from run metadata `concurrent: true` written by the concurrent coordinator — chosen: zero payload pollution, works for live validation and replay alike.
Outputs: H.theses = the three + two candidates with H2 and H5 selected.
Evidence: issue #21 body ("One coordinator owner serializes event/state commits"); events.py append_batch batch-ledger rebuild.

## step.calculate
Status: succeeded
Inputs: G.goal, E.findings
Actions: Pinned the numeric invariants: default max_workers=1 and budget=None (607-test compatibility); budget defaults max_concurrent_workers=4, max_child_depth=8 (matching the grammar's static protocol-depth cap — verified by an 8-frame chain test); child depth = colon count of the child run id (`parent:inv-N` = 1); per-invocation deadline error string exactly "deadline exceeded"; global deadline run error exactly "global deadline exceeded" with in-flight markers "cancelled: global deadline exceeded".
Outputs: F.metrics = {"baseline_tests": 607, "final_tests": 631, "default_max_workers": 1, "default_max_child_depth": 8, "frontier_tests": 11, "budget_tests": 13}.
Evidence: src/tikhon/budgets.py defaults; tests/test_budgets.py::test_default_child_depth_admits_eight_levels; final suite count.

## step.compare
Status: succeeded
Inputs: H.theses, C.done
Actions: Compared the commit models and relaxation mechanisms on the replay dimension: H2 keeps per-invocation event streams identical to sequential (verified by the frontier tests asserting the exact READY/DISPATCHED/RESULT/VALIDATION/SUCCEEDED sequences) and needs no merge logic; H5 reconstructs multi-IN_PROGRESS replay states without touching any payload shape (verified by replaying a concurrent run's TASK_UPDATED stream with and without the flag). H1/H3/H4 all lose on one of those axes.
Outputs: V.compared = H2 + H5 win; both implemented.
Evidence: tests/test_frontier.py, tests/test_frontier.py::test_store_replay_reconstructs_concurrent_intermediate_states.

## step.rank
Status: succeeded
Inputs: V.compared, C.done
Actions: Ranked the implementation order by risk: (1) events thread-safety (smallest blast radius, everything depends on it), (2) ledger flag, (3) frontier, (4) frontier tests, (5) budgets module, (6) gate threading, (7) adapter passthrough, (8) budget tests. Each step gated on the full suite staying green.
Outputs: R.ranked = the order above; executed in exactly that order.
Evidence: session history; suite ran green after every subtask.

## step.challenge
Status: succeeded
Inputs: H.theses, E.findings
Actions: Attacked the design: (C1) read-read ordering — the first DAG version serialized steps that merely read the same INPUT ref, killing the a/c overlap; challenged with the issue's own a;b;c example and fixed to RAW/WAW/WAR edges with read-read free (caught by test_dependency_dag_orders_producers_before_consumers before it was a false pass). (C2) anchor racing — a skipped conditional can make an anchor reachable mid-dispatch-batch, so anchor evaluation re-runs inside the dispatch loop, not only at loop top. (C3) global-deadline drain ordering — draining before recording lost the "cancelled" FAILED markers (caught by test_global_deadline_fails_run_and_cancels_in_flight; fixed by committing the failure batch first). (C4) leaked barrier/late results — drain cancels not-started futures and discards started ones uncommitted; asserted no SUCCEEDED/RESULT_RECEIVED for the discarded step. (C5) `_execute_call_child` pool re-entry — the child run's events flow through the same store from a pool thread, which is exactly why the store lock exists.
Outputs: V.challenge = the five attacks and their resolutions.
Evidence: tests asserting each: DAG test, dispatch-loop anchor re-check in _drive_plan_concurrent, global-deadline test, frontier failure test, concurrency tests.

## step.choose
Status: succeeded
Inputs: R.ranked, V.challenge
Actions: Chose the final architecture: single-writer main-thread commits; interaction DAG with RAW/WAW/WAR edges; metadata-riding concurrency flag; budget gate (semaphore + monotonic clock + colon-count depth) threaded as a keyword arg with None defaults; typed BudgetDeadlineExceeded for the sequential per-invocation post-check; envelope deadline = min(command budget max_seconds, execution budget deadline).
Outputs: D.choice = the architecture above.
Evidence: src/tikhon/runtime/coordinator.py, src/tikhon/budgets.py, src/tikhon/worker_adapter.py.

## step.remember
Status: succeeded
Inputs: D.choice
Actions: Recorded the durable lessons for future runtime work: (1) "ready" needs WAR/WAW edges, not just RAW, if pinned-at-dispatch inputs must match sequential outcomes; (2) a relaxed ledger flag must live on the application/replay path, not just the live API, or batch validation contradicts the coordinator; (3) commit cancellation markers before draining pool work; (4) waiting orchestration frames hold no execution slot.
Outputs: K.record = the four lessons.
Evidence: this WORKLOG; lessons embedded in the module docstrings.

## step.recall
Status: succeeded
Inputs: K.record
Actions: Recalled the lessons at each implementation point: the DAG builder cites (1); events.task_ledger cites (2); the frontier's global-deadline branch cites (3); BudgetGate/_dispatch_worker_call docstrings cite (4).
Outputs: K.recalled = the lessons applied in code.
Evidence: docstrings and comments in the touched sources.

## step.solve
Status: succeeded
Inputs: G.goal, V.challenge
Actions: Implemented #21: events.py got a reentrant lock around every connection access plus `check_same_thread=False`; tasks.py got `allow_concurrent` (default strict) checked in `start_task` and `_apply`; coordinator.py got `_scan_arg_refs`/`_condition_refs`/`_entry_refs`/`_refs_overlap`/`_build_dependency_dag` and `_drive_plan_concurrent` (stable-order dispatch up to max_workers, FIRST_COMPLETED waits, main-thread commits mirroring every sequential event shape, lazy conditional tasks, anchor gating with in-dispatch re-evaluation, atomic failure batches covering ALL non-terminal entries, drain-and-discard for late results, prior_types resume guards, uncaught crash_hook at the sequential site) plus concurrent-run resume (metadata-detected, non-prefix SUCCEEDED sets validated against the plan, frontier re-drive). Implemented #22 on top: budgets.py (frozen ExecutionBudget with validation, BudgetGate with BoundedSemaphore + monotonic global deadline + colon-count depth); execute() mints one gate per run and threads it through both drives and every child; sequential drive checks the global deadline before each dispatch, the depth cap before a CALL dispatches, and wraps worker calls in a slot + per-invocation post-check; frontier checks the deadline at loop top (failing the run with "cancelled" markers for in-flight work committed BEFORE draining), enforces per-invocation deadlines via future timeouts, and holds no slot for waiting CALL frames; ModelWorker binds `deadline_seconds` into TaskEnvelopes (min with the command contract).
Outputs: U.solution = the implementation above.
Evidence: src/tikhon/runtime/coordinator.py, src/tikhon/runtime/events.py, src/tikhon/runtime/tasks.py, src/tikhon/budgets.py, src/tikhon/worker_adapter.py.

## step.prove
Status: succeeded
Inputs: C.done, U.solution
Actions: Proved every C.done clause by a named test: concurrency flag default strict (test_ledger_concurrency_flag_default_is_strict); multi-IN_PROGRESS only when enabled + replay (test_concurrent_run_allows_multiple_in_progress_tasks, test_store_replay_reconstructs_concurrent_intermediate_states); DAG ordering (test_dependency_dag_orders_producers_before_consumers); structural overlap (test_barrier_handlers_prove_overlapping_execution — a 2-party barrier cannot be met by one worker); sequential untouched (test_barrier_times_out_sequentially_without_workers dispatch-order assert + budget=None identity test); final state equality (test_concurrent_final_state_equals_sequential_final_state); audit clean (asserted in nearly every test); atomic failure + no late-result overwrites (test_frontier_failure_is_atomic_and_cancels_in_flight); conditional/CALL serialization (test_conditional_and_call_entries_serialize_behind_their_refs); crash_hook (test_crash_hook_works_in_the_concurrent_frontier); concurrent resume (test_resume_of_crashed_concurrent_run_redrives_the_frontier); concurrency cap observed (test_concurrency_cap_observed_via_tracking_handler, test_one_semaphore_caps_parent_and_child_executions); one-worker no-deadlock parent-child (test_parent_waiting_for_child_completes_with_one_worker); per-invocation deadline atomic (frontier + sequential variants); global deadline coherent with cancellations (frontier + sequential variants); depth cap (test_child_depth_cap_enforced_in_frontier, 8-level chain test); envelope deadline (test_model_worker_envelope_carries_budget_deadline); budget=None identity (test_budget_none_keeps_behavior_identical).
Outputs: A.proof = the test-to-clause mapping above (24 new tests, all passing).
Evidence: tests/test_frontier.py (11), tests/test_budgets.py (13); full suite 631 passed.

## step.review
Status: succeeded
Inputs: ART.sources, U.solution
Actions: Reviewed the diff against the hard constraints: only the six allowed source/test files plus the demo run directory changed (git status verified); cli.py, syntax/, registry/, bridge.py, envelope.py, audit.py, memory.py, resume.py, protocols/, docs/ untouched; every new parameter is keyword-with-default so resume.py and envelope.py call sites compile unchanged; re-sealed program.think after all edits — digest identical to seal.txt; ran the two new test files five consecutive times (timing-sensitive barrier/deadline tests) with zero flakes; confirmed the stale site-packages tikhon install does not affect the suite (pytest pythonpath=src) and used PYTHONPATH=src for CLI invocations.
Outputs: V.review = the constraint checklist, all clean.
Evidence: git status; seal re-verification; repeated test runs.

## step.design
Status: succeeded
Inputs: V.review
Actions: Summarized the final design for solution.md: two layers — the #21 frontier (scheduling, single-writer commits, relaxed ledger) and the #22 budget (shared semaphore, deadlines, depth, cancellation) — plus the sealed program, WORKLOG and evaluation artifacts.
Outputs: P.design = solution.md content.
Evidence: solution.md.

## step.patch
Status: succeeded
Inputs: P.design
Actions: Applied the source changes exactly within scope: coordinator.py (frontier + gate threading), events.py (thread-safety + ledger auto-detect), tasks.py (concurrency flag), budgets.py (new), worker_adapter.py (deadline_seconds passthrough only).
Outputs: ART.patch = the applied diff (git status: 4 modified, 2 new source files, 2 new test files, 1 new demo run).
Evidence: git status --short.

## step.test
Status: succeeded
Inputs: ART.patch
Actions: Ran the full suite (`python3 -m pytest -q`): 631 passed, 0 failed, 0 errors — the 607 baseline untouched plus 24 new. Ran the two new files 5x for flake-resistance. Verified the sealed digest is unchanged after all source edits.
Outputs: V.tests = 631 passed; 5x stable; digest stable.
Evidence: pytest output; seal.txt.

## step.check
Status: succeeded
Inputs: V.tests
Actions: Checked the suite-green predicate and the per-issue acceptance lists item by item (see evaluation.json); all pass; two protocol deviations recorded (see below).
Outputs: V.verdict = acceptance satisfied with recorded deviations.
Evidence: evaluation.json.

## step.report
Status: succeeded
Inputs: V.verdict
Actions: Produced solution.md and evaluation.json with the run_id issue-21-22-frontier, the seal digest, terminal status, and per-criterion evidence.
Outputs: ART.report = solution.md, evaluation.json.
Evidence: the files themselves.

## CALL protocol.framing
Status: succeeded
Inputs: G.goal, C.scope
Actions: Executed the sealed CALL protocol.framing(request = G.goal, scope = C.scope) as an isolated child run (run_id issue-21-22-frontier:inv-22 in demo/runs/issue-21-22-frontier/run.sqlite — the whole program was executed through the runtime with stub handlers after implementation) per the program; its RETURN refs E.context and V.analysis were adopted onto the CALL targets — the child-run machinery this session extended, exercised on the session's own program.
Outputs: E.context = framing analysis; V.analysis = adopted verdict.
Evidence: run.sqlite (210 parent events, 38 child events, CHILD_ADOPTED {E.context, V.analysis}, both runs audit clean, ledger 23/23 completed); demo/runs/issue-21-22-frontier/program.think CALL line.

## step.verify
Status: succeeded
Inputs: G.goal, V.tests
Actions: Final verification pass: baseline 607 -> final 631 with zero existing tests modified; seal digest re-verified identical post-edit; hard-constraint file list cross-checked with git; both issue acceptance checklists transcribed into evaluation.json with evidence.
Outputs: V.result = both issues implemented, sealed, tested, reported.
Evidence: this WORKLOG, solution.md, evaluation.json, seal.txt.
