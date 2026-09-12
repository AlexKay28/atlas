# Solution: issue-14-tikhon-audit — tikhon audit: replay-based run verification

One-command trust check over a persisted run: `tikhon audit --db PATH --run-id ID`
re-derives every invariant a trusted run must satisfy from the event store
alone and prints `OK` (exit 0) or one line per violation with the offending
event seq numbers (exit 1; exit 1 for unknown runs).

## Seal

`program.think` was written, linted (`valid`), and sealed **before any source
edit**; it was never modified afterwards.

- seal digest: `7bb111695c89d0fd7af57ddc247f12784d6ec409931f5276418c57cb68957308`
- program.think sha256: `a309f8f647b2bbc0d2021cb845fe9b1047fb46e34ef3679d9254d43c622f3557`
- mtime 18:35:47, predating the first edit to `cli.py` (18:4x) and all other source files.

## Files changed

- `src/tikhon/audit.py` (new) — `audit_run(store, run_id) -> AuditReport` plus `AuditFinding`/`AuditReport` dataclasses and five check helpers.
- `src/tikhon/cli.py` — `_cmd_audit`, `audit` subparser (`--db`, `--run-id`), import of `audit_run`, module docstring updated, `if __name__ == "__main__"` guard added.
- `src/tikhon/__main__.py` — `main()` return value now propagated via `raise SystemExit(main())` (explicitly permitted by the issue; without it `python3 -m tikhon audit` always exited 0).
- `tests/test_audit.py` (new) — 18 tests.
- `demo/runs/issue-14-tikhon-audit/` — `program.think`, `seal.txt`, `WORKLOG.md`, `solution.md`, `evaluation.json`.

## Audit invariants enforced (all findings carry seq numbers)

1. **Gapless sequencing** (`gapless_sequence`) — the run's events are exactly `seq` 0..n-1.
2. **Event truthfulness**
   - `validation_passed_before_failed` / `validation_passed_after_failed` — an invocation that ever receives FAILED must not carry VALIDATION_PASSED in either order (the issue's injection example is the after-case; the invariant sentence covers the before-case; both are lies).
   - `succeeded_after_failed` — no SUCCEEDED for an invocation after its FAILED.
   - `multiple_run_finished` — at most one RUN_FINISHED.
   - `run_finished_status_mismatch` — RUN_FINISHED status `succeeded` requires no preceding FAILED; status `failed` requires a preceding FAILED (status `blocked` without FAILED is legitimate and stays clean).
3. **Ledger invariants** (on a terminal run, i.e. RUN_FINISHED exists)
   - `unsettled_task_on_terminal_run` — no task left PENDING or IN_PROGRESS (reported with the task's last ledger-event seq and the RUN_FINISHED seq).
   - `completed_task_missing_evidence` — every COMPLETED task has nonempty evidence.
   - `invocation_event_missing_ids` — every invocation-bound event (all 14 `invocation.*` types, checked on every run, terminal or not) carries nonempty `task_id` and `instruction_id`.
4. **Projection determinism** (`state_projection_nondeterministic`) — `store.project_state` run twice must produce identical state (compared via `canonical_json`).

## Verification

- Full suite: `python3 -m pytest -q` → **265 passed** (216 baseline + 18 new audit tests + tests landing from parallel in-repo work; zero failures).
- Dogfooded end to end: ran this run's own sealed `program.think` through `tikhon run`, audited the resulting db (`OK`, exit 0), injected a stray `invocation.result_received` with empty ids into a copy (audited: `violations: 1 - invocation_event_missing_ids (seq: 65) ...`, exit 1), audited a nonexistent run (`error: unknown run: nope`, exit 1).

## Design notes / limitations

- `EventStore.append` by construction cannot produce some corrupt states (evidence-less `task_completed` is rejected by ledger validation; seq numbers are transaction-enforced gapless). The audit still checks them — they model external tampering — and the evidence test simulates the tamper with a direct SQL `UPDATE`, which is the only way to reach that state.
- The ledger projection in `audit.py` is a minimal hand-rolled projection of `TASK_UPDATED` kinds (created/started/completed/cancelled) because findings need per-event seq attribution, which `TaskLedger` does not expose.
- A run with zero events (created but never started) audits clean: no seq violations, not terminal, so ledger invariants do not apply.
