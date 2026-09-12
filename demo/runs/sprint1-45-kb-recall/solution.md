# Solution — Issue #45: KB recall — FTS5 ranking over values

## Summary

Added an FTS5 shadow table (`knowledge_fts`) over the canonical value text in `src/tikhon/memory.py`, maintained in lockstep with the `knowledge` table inside `set()` and `delete()`. Exposed `recall(query, k=5) -> list[tuple[str, float]]` ranked by bm25. The existing `get()`, `keys()`, `__contains__`, and the `KB.<name>` exact-ref grammar are unchanged — `recall()` is additive API.

## Implementation

### FTS5 shadow table

- **Schema**: `CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(key UNINDEXED, value)` — `key` is UNINDEXED (stored but not tokenized), `value` is the canonical JSON text indexed for full-text search.
- **Meta table**: `_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)` stores `fts_schema_version = "1"` for future migrations.

### Lazy creation on old DB files

- `_ensure_fts_shadow()` checks `sqlite_master` for the `knowledge_fts` table. If missing (old DB created before FTS5 support), it creates the table and backfills all existing rows from `knowledge` so `recall()` works immediately on reopen.

### Maintenance in set() and delete()

- `set()`: after the UPSERT into `knowledge`, executes `DELETE FROM knowledge_fts WHERE key=?` then `INSERT INTO knowledge_fts (key, value) VALUES (?, ?)` — keeping the shadow table in sync. FTS5 tables don't support `ON CONFLICT`, so DELETE+INSERT is the correct pattern.
- `delete()`: after the DELETE from `knowledge`, executes `DELETE FROM knowledge_fts WHERE key=?`.

### recall(query, k=5)

- `SELECT key, bm25(knowledge_fts) AS score FROM knowledge_fts WHERE knowledge_fts MATCH ? ORDER BY score LIMIT ?`
- bm25 returns negative values (more negative = better match), so `ORDER BY score` (ASC) ranks the best match first.
- Empty query string returns `[]`. Empty KB returns `[]` (no rows to match).

## Files changed

- `src/tikhon/memory.py` — FTS5 shadow table, lazy creation, set()/delete() maintenance, recall() method
- `tests/test_memory.py` — 4 new acceptance tests

## Tests

- 760 existing tests pass unchanged
- 4 new tests: `test_recall_ranks_matching_key_first`, `test_delete_removes_key_from_recall`, `test_recall_empty_kb_returns_empty`, `test_recall_lazy_creation_on_old_db`
- Total: 764 passed in 21.15s

## Deviations

- None. No forbidden files touched. No new program syntax. No thread-safety changes. Existing API surface unchanged.
