# Issue #10 — tikhon resume: crash-window recovery algorithm

Design reference: `demo/runs/crash-recovery-glm52/solution.md` (read first;
crash-window table W0a-W12, resume pseudocode, exactly-once vs
at-least-once analysis). This run implements the pragmatic subset that is
correct-by-construction with the current event schema.

## What was built

1. **`src/tikhon/resume.py` (new)** — `resume_run(store, worker, run_id,
   program, memory=None, protocols_dir=None, workspace_root=None) -> dict`
   (same result shape as `SequentialCoordinator.execute`, plus
   `"already_terminal": true` when the run was already finished):

   - Terminal runs are never resumed (W4/W10/W11/W12): a RUN_FINISHED in
     the history returns the recorded status with **zero appends**.
   - Identity checks before anything is appended: `store.run(run_id)`
     raises `KeyError` for an unknown run, and the RUN_STARTED payload's
     recorded `program`/`version` must match the supplied program (a
     mismatched program is refused; per-step task-text matching adds a
     second guard).
   - Run state is rebuilt exactly as the coordinator held it at the crash
     point: INPUT declarations seed the `values` mapping, then committed
     SUCCEEDED deltas replay in seq order (add/revise write, retire pops).
     Deltas are replayed directly rather than read from
     `store.project_state` because the projection stores nodes in the
     `{"id": ..., "value": ...}` wrapper shape while the coordinator's
     `values` maps refs to bare values; the replay is the same
     deterministic projection with the wrapper removed.
   - The resume point is the first plan entry whose positional invocation
     id (`inv-<idx+1>`) lacks a SUCCEEDED terminal event. A non-prefix
     SUCCEEDED set is an impossible state and raises.
   - Tasks missing because the crash predated the task-creation batch
     (W0a) are created first with the same text/mapping rule as a fresh
     start (creation order == plan order).
   - Protocol CALL expansions: the INPUT bindings of already-committed
     entries are re-derived into `values` before the remaining steps run
     (bindings live outside every state delta).
   - Everything else is delegated to the coordinator's own machinery, so
     the resumed run satisfies the same ledger/event invariants as a
     fresh run: append-only, gapless seq continuation, CAS on
     `expected_state_version`, duplicate-SUCCEEDED guard.

2. **`src/tikhon/runtime/coordinator.py`** — minimal, behavior-preserving
   refactor plus the crash hook:

   - `CrashInterrupt(Exception)` — raised by a hook to abort `execute`
     mid-run; the hook site is outside every `try`/`except`, so it
     propagates out uncaught and the run keeps exactly its committed
     prefix (a true crash, not a failed run: no FAILED, no RUN_FINISHED).
   - `execute(program, run_id="run-1", *, crash_hook=None)` — the hook is
     called with the plan index right before VALIDATION_PASSED is
     appended, leaving the committed prefix at the RESULT_RECEIVED-
     persisted window (W5 boundary). `crash_hook=None` is a no-op; the
     extraction of `_create_plan_tasks` and `_drive_plan` changed no
     observable behavior (all 444 pre-existing tests pass unchanged).
   - `_drive_plan(..., start_idx=0)` — the resume path: the first
     executed entry may be mid-flight (task IN_PROGRESS from before the
     crash). `start_task` requires PENDING, so the start is skipped for
     an IN_PROGRESS task; committed `task_started`/INVOCATION_READY/
     INVOCATION_DISPATCHED events are never re-emitted; **the worker call
     is always re-executed** — dispatch never implies success
     (at-least-once for the worker call; the `run_id:invocation_id`
     idempotency key in DISPATCHED payloads, added in wave 4, remains the
     dedup contract for effectful workers). RESULT_RECEIVED,
     VALIDATION_PASSED and the atomic SUCCEEDED batch are appended fresh.
     Impossible states (task neither PENDING nor IN_PROGRESS for a
     non-terminal step) raise `TaskLedgerError`.

3. **`src/tikhon/cli.py`** — `tikhon resume --db PATH --run-id ID
   --program PATH --seal DIGEST [--workspace PATH]`: verifies the seal
   exactly like `run` (mismatch rejected before the store is opened),
   loads the program, opens the knowledge base like `run`, calls
   `resume_run`, and prints the same status/percent output with the same
   exit codes (`succeeded`/`100%`, exit 0 on success).

4. **`tests/test_resume.py` (new)** — 19 tests: hook-driven crashes at
   step 1 and mid-program (step 2 of 3) with worker call-count assertions
   proving at-least-once re-execution; W0a (hand-built RUN_STARTED-only
   prefix); W1 and W2/W3 (committed tail rewound to the window per the
   design doc's own regression-test recipe); W9 (RUN_FINISHED deleted
   after a full run — exactly one event appended on resume);
   already-terminal no-op for succeeded and failed runs; unknown run;
   mismatched-program refusals (appends nothing); projection equality
   against a normal full run; ledger fully complete after resume; and
   CLI end-to-end (resume completes a crashed run, already-terminal
   resume appends nothing, seal mismatch and missing seal rejected).

## Crash windows covered vs deferred

| Window | Status | Where |
|---|---|---|
| W0a (RUN_STARTED only) | covered | `resume_run` creates missing tasks; test_w0a |
| W0b (tasks created, nothing started) | covered | same path, start_idx=0, PENDING tasks; exercised by W0a test |
| W1 (task_started + READY, no dispatch) | covered | in-flight branch appends DISPATCHED; test_w1 |
| W2/W3 (dispatched, worker may/may not have run) | covered | DISPATCHED never re-emitted, worker re-executed; test_w2w3 |
| W4/W12 (failure batch committed) | covered | RUN_FINISHED present → no-op; test_resume_already_terminal_failed |
| W5 (RESULT_RECEIVED, no validation) | covered (re-execute variant) | the hook leaves exactly this window; resume re-runs the worker instead of adopting the stored result — at-least-once, documented below |
| W6 (validated, no SUCCEEDED batch) | covered transitively | cannot be distinguished from W5 by the resume point logic; the same re-execution path appends a fresh VALIDATION_PASSED + SUCCEEDED batch (the stale VALIDATION_PASSED is harmless: audit truthfulness only forbids VALIDATION_PASSED combined with FAILED) |
| W7 | n/a | impossible — append_batch is atomic |
| W8 (step completed) | covered | normal advance-to-next-step path |
| W9 (all steps done, no RUN_FINISHED) | covered | finish section emits RUN_FINISHED; test_w9 |
| W10/W11 (terminal) | covered | no-op resume |
| W3 external-effect query by idempotency key | deferred | needs external-system cooperation that does not exist; the DISPATCHED payload already carries the key (`run_id:invocation_id`), so effectful workers can dedup on their side |
| W5 result adoption without worker re-call | deferred | optimization only; re-execution is semantically safe for the deterministic builtin workers and permitted by the at-least-once dispatch guarantee |

## Exactly-once vs at-least-once after this change

- Exactly-once (unchanged, by construction): state delta commits (atomic
  batch + CAS + duplicate-SUCCEEDED guard), gapless seq continuation,
  ledger transitions, multi-target delta atomicity, RUN_FINISHED emission.
- At-least-once (deliberate): the worker call of the interrupted step is
  re-executed on resume. For the builtin deterministic workers this is
  invisible; for effectful workers the persisted
  `run_id:invocation_id` idempotency key is the dedup contract.

## Protocol

`demo/runs/issue-10-resume/program.think` was linted and sealed
(`15787b57f059a3ef9bb3828e0d47b01ae14d65eb6d1082ade46a943605a925f0`)
before the first source edit and never modified afterwards (md5
7a436d5ccf836f9d71462bed4264b0a7 unchanged, digest recomputed after all
edits matches `seal.txt`). `WORKLOG.md` tracks every step. CLI evidence:
the sealed program's run was crashed mid-demo (36 events, 3 of 7 steps
committed) and `tikhon resume` completed it (`succeeded`/`100%`, 66
gapless events, 7 SUCCEEDED for 7 steps, 7 DISPATCHED — no duplicates,
`tikhon audit` OK); a second resume appended nothing (66 → 66); a wrong
digest was refused with exit 1 before touching the store.
