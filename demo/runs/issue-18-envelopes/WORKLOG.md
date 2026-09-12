# Worklog: issue-18-envelopes

Seal: `fa9e60b6f371b4c3313b1cbf94c5bdae587c2a7320d852126e785fcc27da304f`
(program.think was linted `valid` and sealed to seal.txt before any source
edit; the digest still recomputes byte-identically after all edits.)

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to the #18 step-1 scope: a harness-neutral task/result envelope protocol (`TaskEnvelope` / `ResultEnvelope`, schema v1, canonical JSON, strict validation), a binding of the existing #8 `ModelWorker` onto that protocol (prompt built FROM the TaskEnvelope, reply parsed INTO a ResultEnvelope, transport seam and coordinator dispatch signature unchanged), and a sequential external-driver round trip (`tikhon next` / `tikhon submit`) that moves envelopes through the event store so the worker process never holds it open. Coordinator.py and events.py are read-only imports only (Wave 9 owns them).
Outputs: `G.plan` = seal, read coordinator/events/registry/CLI, design the envelope schema and driver event shapes, implement, test, drive the demo run externally.
Evidence: Baseline `python3 -m pytest -q` showed `540 passed in 7.32s` before any edit.

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Read `runtime/coordinator.py` (dispatch seam `worker.execute(command, resolved_kwargs)`, `map_results_to_targets`, `evaluate_done_predicate`, the atomic SUCCEEDED batch `succeeded + invocation_recorded + task_completed`, plan flattening and the resume prefix rules), `runtime/events.py` (`EventStore.append/append_batch`, `_Record`, CAS via `expected_state_version`, `EventType` set), `runtime/tasks.py` (`TaskLedger` transitions), `resume.py` (values replay and SUCCEEDED-prefix rules to reuse), `worker_adapter.py` (#8 adapter), `cli.py` (seal guard style), and `registry/` (22 builtin contracts with `Budget`/`RoutingPolicy`). Confirmed the installed console script is a stale site-packages copy, so all CLI work runs via `PYTHONPATH=src python3 -m tikhon` (same workaround as prior issues).
Outputs: `E.patterns` = the integration points and the exact event shapes the driver must reproduce.
Evidence: The coordinator writes DISPATCHED payload `{"args", "idempotency_key"}` and the atomic batch in that order; resume reuses `coordinator._build_plan/_task_text`, establishing the precedent of driving through coordinator machinery without editing it.

## step.design
Status: succeeded
Inputs: `E.patterns`
Actions: Designed envelope schema v1. TaskEnvelope: `schema_version, run_id, invocation_id, task_id, attempt, idempotency_key, command, command_version, arguments (pinned resolved snapshot), input_digest (sha256 over canonical {command, arguments}), targets, done (op/ref/value or null), contract (purpose/inputs/outputs/done_condition/effect_class/execution/capabilities/budget), workspace_root, program, seal_digest, deadline_seconds`. ResultEnvelope: same identity echo plus `status (succeeded|failed|blocked), payload, evidence, error (required nonempty for failed/blocked), receipt (worker/model identity and usage; usage `None` = telemetry unavailable, distinguished from measured zero)`. Strict validation with clear errors at the wire boundary (`from_json`/`from_dict`: unknown fields, missing fields, wrong schema version, type and serializability checks). The driver reuses the coordinator's own machinery: `SequentialCoordinator._build_plan/_create_plan_tasks/_task_text/_reject_unresolved_refs/_resolve_kb_ref`, `map_results_to_targets`, `evaluate_done_predicate`, ledger transitions and the coordinator's event shapes; the dispatch record additionally carries an envelope binding (`command/targets/done/revisions/retirements`) so `submit` works from the store alone. Failure semantics: failed -> FAILED + RUN_FINISHED(failed), blocked -> BLOCKED + RUN_FINISHED(blocked), succeeded-but-invalid -> VALIDATION_FAILED (DONE only) + FAILED + RUN_FINISHED(failed); duplicate/stale/attempt-mismatched submissions are rejected without appending anything.
Outputs: `E.design` = schema, validation rules, driver event shapes, and the ModelWorker envelope binding.
Evidence: Design keeps every existing duck-type and signature: coordinator dispatch stays `execute(command, resolved_kwargs)`; the adapter renders a documented `direct`-scoped envelope for that path (`direct:<input-digest>` idempotency key) because the pinned seam carries no run identity.

## step.patch
Status: succeeded
Inputs: `E.design`, `C.scope`
Actions: Added `src/tikhon/envelope.py` (dataclasses + `build_task_envelope` + `ExternalDriver` with `next_envelope`/`submit_result`); refactored `src/tikhon/worker_adapter.py` (prompt built from the rendered TaskEnvelope with its canonical JSON embedded; reply parsed and validated into a ResultEnvelope with model receipt; `last_task_envelope`/`last_result_envelope` diagnostics; transport seam, tier routing, strict-JSON parsing and WorkerError tail behavior unchanged); added `next`/`submit` subcommands to `src/tikhon/cli.py` (seal-verified `next` with program validation; store-only `submit` with optional `--program/--seal` identity check; malformed/duplicate/stale exits 1). Added `tests/test_envelope.py` (31 tests). The sealed program.think predates all of these edits.
Outputs: `P.patch` = changes confined to src/tikhon/envelope.py (new), src/tikhon/worker_adapter.py, src/tikhon/cli.py, tests/test_envelope.py (new), demo/runs/issue-18-envelopes/.
Evidence: `git status --porcelain` shows exactly those paths plus unrelated concurrent work (docs/README.md, demo/runs/issue-17-reasoning-language/, docs/design/) that this run never touched; coordinator.py, events.py, tasks.py, registry/, resume.py, audit.py, syntax/ untouched.

## step.check
Status: succeeded
Inputs: `P.patch`, `C.done`
Actions: Wrote tests/test_envelope.py: envelope JSON round trips (dataclass -> json -> dataclass equality for task and result, failed/blocked included), strict validation rejections (unknown/missing fields, wrong schema version, empty identity, non-object arguments, non-string targets, bad done op, non-JSON-serializable values, invalid JSON / non-object wire text, unknown status, error/status combinations), ModelWorker envelope binding (prompt embeds the envelope's canonical JSON and restates the contract; reply becomes a validated ResultEnvelope; receipt usage `tokens: None` = unavailable, never a fabricated zero; direct-dispatch envelope itself round trips), and the CLI round trip on a 2-step program (next -> submit -> next -> submit reaches a succeeded run; audit clean; ledger completed; projected state correct; idempotent re-next; event-type sequence identical to a coordinator-driven run of the same program; duplicate/malformed/stale-key/stale-attempt submissions rejected with nothing appended; failed and blocked results finish the run truthfully with a clean audit; DONE-predicate failure emits VALIDATION_FAILED; receipt usage lands in the ledger). Then ran the full suite.
Outputs: `V.tests` = full suite green.
Evidence: `python3 -m pytest -q`: 571 passed (540 baseline + 31 new), 7.85s. The demo run was then driven end-to-end externally via `artifacts/external_driver_session.py` (CLI only): 6/6 steps, terminal `succeeded`, `tikhon audit` OK, `tikhon status` 100% completed 6/6 (artifacts/session-evidence.txt).

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Recomputed the seal after all edits (matches seal.txt byte-for-byte); verified no forbidden paths were touched; confirmed the deterministic CI baseline is unchanged (default CLI behavior identical; coordinator dispatch signature untouched); confirmed the ModelWorker still passes all 24 pre-existing #8 tests unmodified.
Outputs: `V.result` = issue #18 step 1 (protocol + binding + sequential external round trip) complete; no commits made.
Evidence: `PYTHONPATH=src python3 -m tikhon seal demo/runs/issue-18-envelopes/program.think` -> fa9e60b6f371b4c3313b1cbf94c5bdae587c2a7320d852126e785fcc27da304f; artifacts/ holds the six envelope/result/submit triples and session-evidence.txt.
