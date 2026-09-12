# Worklog: issue-14-tikhon-audit

Seal: `7bb111695c89d0fd7af57ddc247f12784d6ec409931f5276418c57cb68957308`

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to a replay-based audit of persisted runs: new module src/tikhon/audit.py with `audit_run(store, run_id)`, a `tikhon audit --db --run-id` CLI subcommand, and tests/test_audit.py; no syntax/, runtime/, or registry/ edits.
Outputs: `G.plan` = seal program first, write audit.py, extend cli.py, write tests, run full suite, verify seal.
Evidence: Baseline `python3 -m pytest -q` before any edit: `216 passed in 0.59s`.

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Read runtime/events.py (Event envelope, EventType vocabulary, gapless sequencing, project_state), runtime/coordinator.py (event families a real run emits: TASK_UPDATED ledger records, INVOCATION_READY/DISPATCHED, RESULT_RECEIVED, VALIDATION_PASSED, SUCCEEDED with delta, FAILED, RUN_FINISHED), runtime/tasks.py (TaskStatus vocabulary), cli.py subcommand style.
Outputs: `E.patterns` = audit can rely on: per-invocation ids on invocation-bound events, ledger kinds task_created/started/completed/cancelled, RUN_FINISHED payload {"status": ...}, store.project_state determinism.
Evidence: EventStore.append already enforces gapless seq, single SUCCEEDED per invocation, and ledger-valid TASK_UPDATED — so audit violations model external tampering, exactly what a trust check must catch.

## step.invariants
Status: succeeded
Inputs: `E.patterns`
Actions: Designed the four invariant groups with seq-number attribution: (1) gapless seq == 0..n-1; (2) truthfulness — no VALIDATION_PASSED and FAILED for the same invocation in either order, no SUCCEEDED after FAILED, at most one RUN_FINISHED, RUN_FINISHED status consistent with preceding FAILED events (succeeded requires none, 'failed' requires one; 'blocked' without FAILED is legitimate); (3) ledger — on a terminal run no task PENDING/IN_PROGRESS, every COMPLETED task has nonempty evidence, every invocation-bound event (14 invocation.* types) carries nonempty task_id and instruction_id; (4) project_state run twice must match byte-identically via canonical_json.
Outputs: `E.invariants` = check list, each producing an AuditFinding{code, message, seqs}.
Evidence: Blocked runs produced by SequentialCoordinator finish with status "blocked" and no FAILED event, so the status check must accept that; validated against coordinator.py lines 333-354.

## step.implement
Status: succeeded
Inputs: `E.invariants`
Actions: Wrote src/tikhon/audit.py: AuditFinding and AuditReport dataclasses (with to_dict), audit_run(store, run_id) raising KeyError for unknown runs, and helpers _check_gapless, _check_truthfulness, _check_invocation_ids, _check_ledger (hand-rolled TASK_UPDATED projection keeping per-task last status seq and evidence), _check_projection_determinism.
Outputs: `P.audit` = audit.py with 5 check functions and 2 report types.
Evidence: Module imports only tikhon.runtime.events (read-only); a self-review caught and fixed a generator-variable shadowing bug that would have silently disabled the failed-vs-passed ordering comparisons.

## step.commit
Status: succeeded
Inputs: `P.audit`
Actions: Added `_cmd_audit` + `audit` subparser to src/tikhon/cli.py (prints OK or `violations: N` with one `- code (seq: ...): message` line per finding; exit 0 clean, 1 violations, 1 unknown run); added the missing `if __name__ == "__main__"` guard to cli.py and fixed src/tikhon/__main__.py (explicitly permitted) to `raise SystemExit(main())` so `python3 -m tikhon` propagates exit codes.
Outputs: `ART.audit` = cli.py audit subcommand wired; __main__.py exit-code fix.
Evidence: Dogfood run: `tikhon run` of this run's own sealed program.succeeded; `tikhon audit` on its db printed `OK` exit 0; after injecting a stray `invocation.result_received` with empty ids at seq 65 into a copy of the db, `tikhon audit` printed `violations: 1 - invocation_event_missing_ids (seq: 65) ...` exit 1; unknown run printed `error: unknown run: nope` exit 1.

## step.check
Status: succeeded
Inputs: `ART.audit`, `C.done`
Actions: Wrote tests/test_audit.py: 18 tests — clean audits of succeeded, failed (handler raises), blocked, and missing-key-failure runs built via SequentialCoordinator + DeterministicWorker; unknown run raises KeyError; injected violations via EventStore.append (VALIDATION_PASSED after FAILED and before FAILED, SUCCEEDED after FAILED, second RUN_FINISHED, RUN_FINISHED claiming succeeded after FAILED, stray invocation event with empty ids, pending and in_progress tasks on a terminal run) and one simulated store tamper (evidence stripped from a committed task_completed payload — the append API rejects that by design); nondeterministic projection via a flaky project_state override; three CLI exit-code tests through cli.main(argv).
Outputs: `V.tests` = full suite green.
Evidence: `python3 -m pytest -q` → `265 passed` (216 baseline + 18 new audit tests + parallel agent work landing in the same window).

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Recomputed the program seal after all edits, re-hashed program.think, and checked every acceptance criterion.
Outputs: `V.result` = goal satisfied.
Evidence: Post-edit seal `7bb111695c89d0fd7af57ddc247f12784d6ec409931f5276418c57cb68957308` equals seal.txt; program.think sha256 `a309f8f647b2bbc0d2021cb845fe9b1047fb46e34ef3679d9254d43c622f3557` and mtime 18:35:47 predate every source edit and are unchanged; suite 265 passed.
