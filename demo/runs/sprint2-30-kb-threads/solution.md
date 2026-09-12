# Solution — sprint2-30-kb-threads

## Issue #30: KnowledgeBase is not thread-safe

The `KnowledgeBase` in `src/tahoe/memory.py` connected to SQLite without
`check_same_thread=False` and without a lock. The concurrent frontier
(coordinator.py:1332-1333) dispatches handlers on `ThreadPoolExecutor`
pool threads while the CLI creates the KB on the main thread — any
`max_workers>1` run using `remember` crashed with *"SQLite objects
created in a thread can only be used in that same thread."*

## Fix

Mirrored the `EventStore` threading pattern from `events.py:205-208`:

1. **`check_same_thread=False`** on `sqlite3.connect` — allows the
   connection to be shared across threads.
2. **One `threading.RLock`** (`self._lock`) guarding every public method
   (`set`/`get`/`keys`/`recall`/`delete` + `__contains__` + `close`) and
   the internal `_ensure_fts_shadow` — serializes all SQLite access so
   concurrent writes cannot corrupt the connection or the FTS5 shadow
   table.

The `RLock` (reentrant) was chosen to match `EventStore` and to allow
nested calls if any future code path calls a public method from within
another locked method.

JSON serialization (`json.dumps`) and key validation (`_validate_key`)
in `set()` remain outside the lock — they access no shared state.

The #45 FTS5 recall surface (`recall()` method, `knowledge_fts` shadow
table, bm25 ranking) and the exact-key grammar (`kb.[a-z][a-z0-9_]*`)
are unchanged — only locking was added.

## Files changed

- `src/tahoe/memory.py` — `import threading`, `self._lock = threading.RLock()`,
  `check_same_thread=False`, `with self._lock:` on every public method
- `tests/test_memory.py` — 3 new acceptance tests
- `demo/runs/sprint2-30-kb-threads/` — run artifacts

## Tests

- Baseline: 857 passed
- After fix: 860 passed (857 + 3 new)
- New tests:
  - `test_kb_callable_from_non_creator_thread` — KB created on main
    thread, methods called from a worker thread
  - `test_concurrent_remember_steps_succeed` — 2 `set` calls on
    `ThreadPoolExecutor(max_workers=2)`
  - `test_parallel_remember_and_recall_never_tears` — 40 `set` + 40
    `recall` on 4 threads, no exceptions, no torn values

## Seal

`9b788c700c05e4accc41a46c00999dc595a131cd910cf6ca496c2eafdb99ede5`
