# Solution: issue-18-envelopes (GitHub issue #18, step 1 of epic #27)

## What was built

A harness-neutral task/result envelope protocol with three bindings, all
in the five allowed paths (`src/tikhon/envelope.py` new,
`src/tikhon/worker_adapter.py`, `src/tikhon/cli.py`,
`tests/test_envelope.py` new, `demo/runs/issue-18-envelopes/`):

### 1. Envelope protocol (`src/tikhon/envelope.py`)

- **TaskEnvelope** (coordinator -> worker dispatch), schema v1, canonical
  JSON (sorted keys, compact separators): `schema_version`, `run_id`,
  `invocation_id`, `task_id`, `attempt` (>=1), `idempotency_key`
  (`"<run_id>:<invocation_id>"`), `command`, `command_version`,
  `arguments` (pinned resolved snapshot), `input_digest` (sha256 over
  canonical `{command, arguments}`), `targets`, `done`
  (`{"op","ref","value"}` or null), `contract` (purpose, inputs,
  outputs, done_condition, effect_class, execution, capabilities,
  budget), `workspace_root`, `program {name,version}`, `seal_digest`,
  `deadline_seconds`.
- **ResultEnvelope** (worker -> coordinator result), schema v1: identity
  echo (run/invocation/task/attempt/idempotency_key/command), `status`
  (`succeeded|failed|blocked`), `payload` (JSON DO result), `evidence`
  (artifact refs/digests), `error` (required nonempty for failed/blocked,
  null for succeeded), `receipt` (worker/model identity and usage;
  `receipt["usage"]["tokens"] = None` means telemetry **unavailable**,
  distinguished from a measured zero per the issue).
- Frozen dataclasses with `to_json()/from_json()` (and `to_dict/
  from_dict`); strict validation with clear errors: unknown fields,
  missing fields, wrong schema version, empty identity, non-object
  arguments, non-string targets, bad DONE op, non-JSON-serializable
  values, invalid JSON, non-object wire text, unknown status, and
  error/status mismatches.
- `build_task_envelope(registry, ...)` resolves the command contract and
  summarizes it; `envelope_input_digest` pins the input snapshot.

### 2. Worker binding (`src/tikhon/worker_adapter.py`, refactor)

- `ModelWorker` now renders every dispatch as a TaskEnvelope and builds
  its prompt FROM it — the envelope's canonical JSON is embedded in the
  prompt and the contract preamble is restated from envelope fields.
- The reply is parsed strictly (unchanged fence-tolerant JSON rules) and
  wrapped into a **validated ResultEnvelope** (status succeeded, payload,
  receipt with routed model and `None` usage) before its payload is
  returned; `last_task_envelope` / `last_result_envelope` expose the
  binding for diagnostics/tests.
- The transport seam `transport(model, prompt) -> str`, tier routing,
  `WorkerError` tail behavior, and the coordinator's pinned
  `execute(command, resolved_kwargs)` dispatch signature are unchanged;
  that seam carries no run identity, so the adapter renders a documented
  `direct`-scoped envelope with a `direct:<input-digest>` idempotency
  key. All 24 pre-existing #8 adapter tests pass unmodified.

### 3. Sequential external-driver round trip (`envelope.py` + CLI)

- `tikhon next --db PATH --run-id ID --program PATH --seal DIGEST` prints
  the TaskEnvelope for the run's next ready invocation as one canonical
  JSON line. First call fresh-starts the run exactly like the coordinator
  (create_run with registry digest, RUN_STARTED, one batch-created ledger
  task per plan entry), then task_started + INVOCATION_READY +
  INVOCATION_DISPATCHED (the dispatch payload additionally carries an
  envelope binding: command/targets/done/revisions/retirements).
  Re-invocation while a result is pending re-renders the identical
  envelope (idempotent, no duplicate dispatch).
- `tikhon submit --db PATH --run-id ID --invocation-id ID --result-file
  PATH` parses and strictly validates the ResultEnvelope, cross-checks it
  against the dispatch (run, invocation, idempotency key, attempt,
  task, command — duplicate/stale/malformed rejected with exit 1 and
  nothing appended), then commits RESULT_RECEIVED and, when semantically
  valid (the coordinator's own `map_results_to_targets` + DONE predicate
  evaluation), the atomic SUCCEEDED batch (VALIDATION_PASSED, SUCCEEDED
  with the StateDelta, invocation_recorded with receipt usage,
  task_completed) — the same coordinator machinery, shapes and rules;
  `coordinator.py`/`events.py` are read-only imports. A failed result
  writes FAILED + RUN_FINISHED(failed); a blocked result writes BLOCKED +
  RUN_FINISHED(blocked); a succeeded-but-invalid result writes
  VALIDATION_FAILED (DONE) + FAILED + RUN_FINISHED(failed).
- The worker process never holds the store open: every CLI invocation
  opens and closes its own store.
- `ExternalDriver` is also importable directly (`next_envelope()` /
  `submit_result()`) for harness use.

## Demo run (external round trip)

`artifacts/external_driver_session.py` drove the sealed 6-step program
(define, search, extract, summarize, check, verify — with a ref-list
argument and a DONE predicate) entirely through the CLI: six
envelope/result/submit triples are captured in `artifacts/`, the run
terminated `succeeded`, `tikhon audit` reports OK, `tikhon status`
reports 100% completed 6/6 (`artifacts/session-evidence.txt`).

## Verification

- `python3 -m pytest -q`: **571 passed** (540 baseline + 31 new), no
  regressions; baseline deterministic behavior unchanged.
- `audit_run` clean after driver-driven success, failure, block, and
  DONE-failure runs (tests).
- The driver-driven event-type sequence is asserted identical to a
  coordinator-driven run of the same program (test).
- Seal recomputed after all edits matches `seal.txt`;
  `program.think` predates every source edit.

## Scope discipline

Only the five allowed paths were touched. `coordinator.py`,
`events.py`, `tasks.py`, `registry/`, `resume.py`, `audit.py`,
`syntax/`, `protocols/`, `docs/`, other demo runs: unmodified (read-only
imports only). Concurrent-work tree noise (`docs/README.md`,
`demo/runs/issue-17-reasoning-language/`, `docs/design/`) belongs to
other agents and was never edited by this run. No commits made.
