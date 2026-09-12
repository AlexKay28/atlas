# Solution: issue #5 — Semantic memory: cross-run KB namespace with remember/recall

## What was implemented

CoALA's semantic memory (durable knowledge across runs) now exists alongside
Tikhon's working memory (run-local `G/C/E` nodes) and episodic memory (the
event store).

### 1. `src/tikhon/memory.py` (new) — `KnowledgeBase`
- Backed by its own SQLite file (typically `<db dir>/kb.sqlite`); schema:
  `key TEXT PRIMARY KEY, value TEXT NOT NULL, source_run TEXT, updated_at TEXT NOT NULL`.
- API: `set(key, value, source_run=None)` (returns the stored record),
  `get(key)` (decoded value, `None` when absent), `delete(key)` (returns
  whether a row was removed), `keys(prefix=None)` (sorted tuple), plus
  `__contains__`, `close()`, and context-manager support.
- Keys are validated against `kb.[a-z][a-z0-9_]*` — the `kb.` prefix is
  mandatory at the API boundary; keys are stored **with** the prefix
  internally, so program-facing `KB.<name>` maps one-to-one onto `kb.<name>`.
- Values are stored as canonical JSON (`json.dumps(..., sort_keys=True,
  separators=(",", ":"))`); non-serializable values raise `ValueError`.
- `updated_at` is UTC ISO-8601 (`datetime.now(timezone.utc).isoformat()`).

### 2. Grammar (`src/tikhon/syntax/parser.py`)
- `KB` added to the `_PREFIX` set, so `KB.<name>` parses wherever typed
  references do (arguments, reference lists, DONE left-hand sides).
- `validate_program` rules:
  (a) `KB.*` refs are accepted in argument positions without run-local
  definitions (they resolve from the KnowledgeBase at dispatch time);
  (b) `KB.*` refs are rejected as invocation targets with "cannot be an
  invocation target: semantic memory is written with the remember command";
  (c) `KB.*` declarations in INPUT are rejected with "cannot be declared in
  INPUT: semantic memory is durable across runs".

### 3. Commands (`src/tikhon/registry/builtins.py`)
- `remember@1.0.0`: inputs `key:kb_key`, `value:json`; effect `kb_write`;
  `EffectClass.REVERSIBLE_WRITE` (the closest existing class — a KB row can
  be overwritten/deleted, so no new enum value was needed);
  `IdempotencyMode.BUSINESS_KEY`; compensation "delete the written key or
  restore the previous value"; evidence `stored_key`, `source_run`,
  `updated_at`.
- `recall@1.0.0`: input `query:kb_key_or_prefix` (exact key or prefix);
  `EffectClass.READ_ONLY`; outputs `values:map`, `matched_keys:refs`;
  returns `{key: value}` for the exact key or every key under the prefix.

### 4. Coordinator (`src/tikhon/runtime/coordinator.py`)
- `SequentialCoordinator(store, worker, memory=None)`.
- `KB.<name>` argument refs (single or inside reference lists) resolve at
  dispatch time via `memory.get("kb.<name>")`; unknown keys fail the
  invocation through the standard failure path (`FAILED` + `RUN_FINISHED`).
- When `memory is None` and the program uses `KB.` refs, a clear
  `ValueError` ("no knowledge base was provided: construct
  SequentialCoordinator with memory=KnowledgeBase(path)") is raised **before
  run creation**, so the event store stays clean.

### 5. CLI (`src/tikhon/cli.py`)
- `_cmd_run` always opens a `KnowledgeBase` rooted next to `--db`
  (`<db dir>/kb.sqlite`), passes it to the coordinator, and hands it to the
  handlers.
- `_deterministic_handlers(memory=None, run_id="")` (zero-arg compatible)
  gained deterministic `remember`/`recall` handlers: remember writes with
  `source_run` = the CLI run id (evidence = source run id); recall returns
  the exact key's value or all values under the query prefix.

## Storage format and key rules
- File: `<db dir>/kb.sqlite`, table `knowledge`.
- Stored keys carry the `kb.` prefix and match `kb.[a-z][a-z0-9_]*`
  (lowercase first letter; digits/underscores after; no dashes).
- Values: canonical JSON text (sorted keys, no whitespace, non-ASCII kept).
- Provenance: `source_run` (writing run id) and `updated_at` (UTC ISO-8601)
  recorded on every write; `set` upserts.

## Verification
- Baseline before edits: 265 passed. Final suite: 314 passed
  (49 new or extended tests across test_memory.py, test_syntax.py,
  test_coordinator.py, test_registry.py).
- `demo/runs/issue-05-kb-memory/program.think` uses only pre-existing
  commands, was linted `valid` and sealed to
  `05ce785668d65695c213329ffb6bf989f695b604ed7416d2bf5f2c0b4f6d8a1c`
  **before** any source edit, and was never modified afterwards.
- `scratch-remember-recall.think` (inside the run dir) lints `valid` with
  the new `remember`/`recall` commands.
- Live two-run CLI demo through one `kb.sqlite`: run-1/run-2 remember and
  recall `kb.plan_digest`; a third recall-only run retrieved the value an
  earlier run wrote (`{'kb.plan_digest': 'issue-05 semantic memory smoke
  test'}`), and `tikhon audit` reports `OK` for the run.

## Deviations / limitations
- No new `EffectClass` value was required: `REVERSIBLE_WRITE` already
  existed and is the honest class for a durable-but-overwritable store, so
  there is no enum deviation to record.
- A DONE predicate over a `KB.*` ref is rejected at parse time (the
  pre-existing "must be one of the step's targets" rule); KB facts are
  observed by recalling them into a state node first.
- `RETURN`/`STOP` of a bare `KB.*` ref still fails with the pre-existing
  "unresolved reference" error: terminal outputs are state nodes, so KB
  facts must be recalled into a node before being returned.
- `recall` with no matches returns an empty mapping (deterministic) rather
  than failing; a missing exact key at coordinator resolution, however,
  fails the invocation with a clear error.
- The concurrent issue-#15 agent edits parser.py/coordinator.py and shared
  test files; all edits here were small, additive, and separated (the
  `_PREFIX` line, validation branches, resolution loop, and new methods/
  tests), and the full suite is green with both changes in place.
