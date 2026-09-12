# Worklog: issue-10-resume

Seal: `15787b57f059a3ef9bb3828e0d47b01ae14d65eb6d1082ade46a943605a925f0`

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to the crash-window recovery layer: a new `resume_run` in `src/tikhon/resume.py`, a `crash_hook` parameter on `SequentialCoordinator.execute` (raising `CrashInterrupt` uncaught from outside every try/except so the committed prefix is real), a minimal coordinator refactor so resume can drive the remaining steps through the same ledger/event machinery, and a `tikhon resume` CLI subcommand verifying the seal exactly like `run`. No changes to syntax/, registry/, events.py, tasks.py, audit.py, memory.py, or other run dirs.
Outputs: `G.plan` = baseline suite, design-doc read, resume module, coordinator hook + drive refactor, CLI subcommand, tests, full suite.
Evidence: Baseline `python3 -m pytest -q` showed `444 passed in 6.23s` before any edit.

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Read demo/runs/crash-recovery-glm52/solution.md first (crash-window table W0a-W12, resume pseudocode, exactly-once vs at-least-once analysis). Located the invocation lifecycle in runtime/coordinator.py (task-creation batch, per-invocation loop, failure batch, finish section), the gapless seq + CAS + duplicate-SUCCEEDED guards in runtime/events.py, the PENDING-only `start_task` transition in runtime/tasks.py, and the audit invariants in audit.py (duplicate RESULT_RECEIVED/READY/DISPATCHED are not violations; terminal runs must leave no task unsettled).
Outputs: `E.windows` = covered windows W0a, W1, W2/W3, W5, W8/W9, W10/W11; deferred W4/W12 (terminal by construction), W6/W7 (atomic batches), idempotency-key external queries.
Evidence: tasks.py:131-153 `start_task` requires PENDING and no other IN_PROGRESS task; events.py:342-348 duplicate-SUCCEEDED guard; audit.py:31-46 invocation-bound types with no duplicate-lifecycle-event check.

## step.design
Status: succeeded
Inputs: `E.windows`
Actions: Designed the pragmatic subset that is correct-by-construction with the current event schema: resume projects `values` from INPUT declarations plus an in-order replay of committed SUCCEEDED deltas (add/revise set, retire pops), takes the first invocation without a terminal SUCCEEDED event as the resume point, never re-emits committed lifecycle events (task_started/READY/DISPATCHED) but always re-executes the worker call (at-least-once; the `run_id:invocation_id` DISPATCHED idempotency key stays the dedup contract for effectful workers), creates tasks missing because of a W0a crash, raises only on impossible states (non-prefix SUCCEEDED set, non-PENDING non-IN_PROGRESS resumed task, plan/task text mismatch), and finishes through the coordinator's own RUN_FINISHED logic.
Outputs: `E.design` = resume algorithm, coordinator `crash_hook` + `_create_plan_tasks`/`_drive_plan` extraction, CLI subcommand shape.
Evidence: The hook call site sits after the finalizes/revisions try-block and before the VALIDATION_PASSED append, so a raising hook leaves exactly window W5 (RESULT_RECEIVED persisted, no validation, no terminal) and propagates out of `execute` uncaught.

## step.patch
Status: succeeded
Inputs: `E.design`
Actions: Wrote `src/tikhon/resume.py` (`resume_run`); refactored `src/tikhon/runtime/coordinator.py` (new `CrashInterrupt`, extracted `_create_plan_tasks` and `_drive_plan`, `crash_hook` parameter on `execute`, resumed in-flight branch skipping `start_task`/committed lifecycle events); added the `tikhon resume` subcommand to `src/tikhon/cli.py` (seal verified exactly like `run` before touching the store, memory opened like `run`, same status/percent output and exit codes).
Outputs: `P.patch` = two source files edited, one module and one test file added.
Evidence: program.think and seal.txt (15787b57f059a3ef9bb3828e0d47b01ae14d65eb6d1082ade46a943605a925f0) were written and hashed before the first source edit; the digest recomputed after all edits matches and program.think was never modified afterwards.

## step.apply
Status: succeeded
Inputs: `P.patch`
Actions: Added tests/test_resume.py: crash-before-first-step and mid-program (step 2 of 3) via the hook, crash-after-last-step-before-RUN_FINISHED (W9, RUN_FINISHED deleted per the design doc's own regression-test recipe), W0a (hand-built RUN_STARTED-only prefix), W1 and W2/W3 (committed tail rewound to the window), already-terminal no-op (succeeded and failed), unknown run, projection equality against a normal full run, and CLI end-to-end (resume completes a hooked crash, already-terminal resume is a no-op, seal mismatch rejected).
Outputs: `ART.patch` = tests/test_resume.py plus the source changes of step.patch.
Evidence: Diffs confined to src/tikhon/resume.py (new), src/tikhon/runtime/coordinator.py, src/tikhon/cli.py, tests/test_resume.py (new), and demo/runs/issue-10-resume/.

## step.check
Status: succeeded
Inputs: `ART.patch`, `C.done`
Actions: Linted the sealed program through the real CLI, ran the resume CLI end-to-end (hook-crashed run resumed to succeeded/100%, already-terminal resume appending nothing, seal mismatch refused), audited resumed runs with `tikhon audit`, and ran the full pytest suite.
Outputs: `V.tests` = all checks passed.
Evidence: `program.think` lints `valid`; a run of the sealed program crashed mid-demo through the coordinator hook (36 events, 3 of 7 steps committed, last event invocation.result_received) and `tikhon resume` completed it printing `succeeded`/`100%` — 66 gapless events, 7 SUCCEEDED for 7 steps, 7 DISPATCHED (no duplicates), `tikhon audit` prints OK; a second resume appended nothing (66 → 66 events); a wrong digest is refused with exit 1 before the store is opened; full suite green (484 passed, recorded in evaluation.json).

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Recomputed the program seal and checked every acceptance condition against the goal.
Outputs: `V.result` = goal satisfied.
Evidence: Seal digest recomputed after all edits equals seal.txt (15787b57f059a3ef9bb3828e0d47b01ae14d65eb6d1082ade46a943605a925f0); program.think unchanged since sealing; all acceptance criteria in evaluation.json hold.
