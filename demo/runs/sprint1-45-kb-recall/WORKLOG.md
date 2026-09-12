# WORKLOG — sprint1-45-kb-recall

Seal: bcc2623f5cffa3e5a67b58129a12068f237ec05d0630e5bac60bd37866cbaa9c
Program: demo/runs/sprint1-45-kb-recall/program.think (linted valid and sealed before any source edit; program is never modified after sealing)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done, C.forbidden from program.think INPUT block
Actions: Framed issue #45 into deliverables: (1) FTS5 shadow table over canonical value text maintained inside set()/delete() in memory.py; (2) recall(query, k=5) -> list[(key, score)] ranked by bm25; (3) defensive schema version + lazy recreation on old DB files; (4) tests for all four acceptance criteria; (5) demo run artifacts (WORKLOG, solution.md, evaluation.json). Constraints: exact get()/keys()/KB.<name> grammar unchanged; no thread-safety fixes; no new syntax; only owned files touched.
Outputs: G.plan = the deliverables above.
Evidence: gh issue view 45; issue text in prompt; program.think INPUT block.

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located the code sites: src/tikhon/memory.py (129 lines, full file — the only source to edit); tests/test_memory.py (100 lines — existing tests to keep green, new tests to add); coordinator.py:697-708 (_resolve_kb_ref — read-only, uses exact get()/`in` — must not change); demo/runs/sprint1-45-kb-recall/ (run directory). No other files in scope.
Outputs: E.sites = {memory.py, test_memory.py, coordinator.py:697-708, demo/runs/sprint1-45-kb-recall/}
Evidence: src/tikhon/memory.py (full read); tests/test_memory.py (full read); src/tikhon/runtime/coordinator.py lines 697-708 (read-only).

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read memory.py fully: KnowledgeBase class with _SCHEMA table (knowledge: key TEXT PK, value TEXT, source_run TEXT, updated_at TEXT), __init__ creates schema, set() uses INSERT ON CONFLICT UPDATE with canonical JSON, get() uses SELECT WHERE key=?, delete() uses DELETE WHERE key=?, keys() uses LIKE prefix filter, __contains__ uses SELECT 1. Coordinator _resolve_kb_ref uses `key in self.memory` (__contains__) then `self.memory.get(key)` — both exact-key operations that must remain unchanged. FTS5 is available in this env's sqlite3.
Outputs: ART.sources = the read source code and FTS5 verification.
Evidence: src/tikhon/memory.py lines 1-129; src/tikhon/runtime/coordinator.py lines 697-708; python3 FTS5 availability check (CREATE VIRTUAL TABLE t USING fts5(x) succeeded).

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Extracted the FTS5 shadow-table design constraints: (1) Shadow table `knowledge_fts USING fts5(key UNINDEXED, value)` mirrors the canonical value text for bm25 ranking; key is UNINDEXED so it's stored but not tokenized. (2) Maintained inside set() (INSERT INTO knowledge_fts ON CONFLICT DO UPDATE or DELETE+INSERT) and delete() (DELETE FROM knowledge_fts WHERE key=?). (3) Schema version stored in a meta table or pragma; if FTS5 table is missing on old DB, recreate lazily on first set()/recall(). (4) recall(query, k=5) runs `SELECT key, bm25(knowledge_fts) AS score FROM knowledge_fts WHERE knowledge_fts MATCH ? ORDER BY score LIMIT ?` — bm25 returns negative values (lower = better match), so ORDER BY score ASC (most negative = best). (5) On empty KB (no rows), recall returns []. (6) get()/keys()/__contains__ unchanged — they query the original `knowledge` table, not the FTS5 table.
Outputs: E.findings = the design constraints above.
Evidence: SQLite FTS5 documentation (bm25 ranking function returns negative scores, lower = better); existing memory.py code patterns.

## step.decompose
Status: succeeded
Inputs: G.plan
Actions: Split into subtasks: (1) Add FTS5 shadow table schema + schema_version meta table to __init__; (2) Update set() to maintain FTS5 shadow; (3) Update delete() to maintain FTS5 shadow; (4) Add recall() method; (5) Add lazy recreation for old DB files; (6) Write 4 acceptance tests; (7) Run full test suite; (8) Write demo run artifacts.
Outputs: G.subgoals = the 8 subtasks above.
Evidence: this decomposition.

## step.hypothesize
Status: succeeded
Inputs: G.goal, E.findings
Actions: Generated candidate designs for FTS5 maintenance: (H1) External-content FTS5 table (content='knowledge', content_rowid='rowid') — rejected: the knowledge table has no rowid column (TEXT PRIMARY KEY), and external content with text PK is fragile; (H2) Separate FTS5 table with key UNINDEXED + value, maintained manually in set()/delete() — chosen: simplest, direct control, no external-content sync complexity; (H3) FTS5 table with contenttable pointing at a view — rejected: over-engineering for this scope. For the bm25 ordering: (H1) ORDER BY score ASC (bm25 returns negatives, most negative = best) — chosen; (H2) ORDER BY score DESC — rejected: would rank worst matches first. For lazy recreation: check if knowledge_fts exists in sqlite_master; if not, CREATE + backfill from existing knowledge rows.
Outputs: H.theses = H2 with ASC ordering and lazy recreation.
Evidence: SQLite FTS5 docs; existing code patterns in memory.py.

## step.compare / step.rank / step.challenge / step.choose
Status: succeeded
Inputs: H.theses, C.done / V.compared / H.theses, E.findings / R.ranked, V.challenge
Actions: Compared H2 against H1/H3: H2 is simplest, gives full control over shadow maintenance, no external-content fragility. Challenged: what if FTS5 table gets out of sync? — set() uses DELETE+INSERT on FTS5 (not ON CONFLICT, since FTS5 doesn't support ON CONFLICT); delete() removes from both tables; lazy init backfills existing rows. What if the DB was created by an old version without FTS5? — __init__ checks sqlite_master and creates + backfills. Chose H2 with DELETE+INSERT pattern for FTS5 maintenance and lazy backfill.
Outputs: V.compared, R.ranked, V.challenge, D.choice = H2 with DELETE+INSERT and lazy backfill.
Evidence: this analysis; SQLite FTS5 limitations (no ON CONFLICT support).

## step.remember / step.recall
Status: succeeded
Inputs: D.choice / K.record
Actions: Recorded: FTS5 shadow table over canonical value text with key UNINDEXED; maintained via DELETE+INSERT in set() and DELETE in delete(); lazy recreation on old DBs via sqlite_master check + backfill; recall() uses bm25() ASC ordering; schema_version stored in a meta table.
Outputs: K.record, K.recalled.
Evidence: this step.

## step.design
Status: succeeded
Inputs: E.findings
Actions: Designed the minimal diff: (1) Add _FTS_SCHEMA constant and _SCHEMA_VERSION constant; (2) In __init__: create _SCHEMA (existing), create meta table with schema_version, create FTS5 shadow table, backfill if needed; (3) In set(): after existing INSERT/UPDATE on knowledge, DELETE from knowledge_fts WHERE key=? then INSERT INTO knowledge_fts; (4) In delete(): after existing DELETE on knowledge, DELETE from knowledge_fts WHERE key=?; (5) Add recall(self, query, k=5) method: SELECT key, bm25(knowledge_fts) AS score FROM knowledge_fts WHERE knowledge_fts MATCH ? ORDER BY score ASC LIMIT ?; return list of (key, score) tuples; on empty result return []. (6) Update __all__ to include nothing new (recall is a method, not a module-level export). (7) Tests: test_recall_ranks_matching_key_first, test_delete_removes_from_recall, test_recall_empty_kb, existing tests unchanged.
Outputs: P.design = the implementation design above.
Evidence: this design step.

## step.solve / step.prove
Status: succeeded
Inputs: G.goal / C.done
Actions: Formalized the solution: FTS5 shadow table `knowledge_fts(key UNINDEXED, value)` maintained in lockstep with the `knowledge` table; recall() uses bm25() for ranking; schema version stored in `_meta` table; lazy creation on old DB files via sqlite_master check + backfill from existing knowledge rows. Proved the contract: get()/keys()/__contains__ query only the `knowledge` table (unchanged); recall() queries only `knowledge_fts` (additive); set()/delete() maintain both tables atomically; no new syntax or coordinator changes.
Outputs: U.solution, A.proof.
Evidence: src/tikhon/memory.py (edited); tests/test_memory.py (edited).

## step.patch
Status: succeeded
Inputs: P.design
Actions: Edited src/tikhon/memory.py: added FTS5 shadow table schema, meta table with schema version, lazy creation + backfill in __init__, FTS5 maintenance in set() and delete(), recall() method with bm25 ranking. Edited tests/test_memory.py: added 4 acceptance tests.
Outputs: ART.patch = src/tikhon/memory.py (modified), tests/test_memory.py (modified)
Evidence: See git diff; code changes described in detail in step.solve.

## step.test
Status: succeeded
Inputs: ART.patch
Actions: Ran PYTHONPATH=src python3 -m pytest -q — all tests pass including 4 new acceptance tests.
Outputs: V.tests = 764 passed (760 existing + 4 new)
Evidence: pytest output: 764 passed in 21.36s

## step.check
Status: succeeded
Inputs: V.tests
Actions: Verified full suite green; verified git status --porcelain shows only owned files.
Outputs: V.verdict = suite_green, files_clean
Evidence: pytest exit code 0; git status --porcelain shows only src/tikhon/memory.py, tests/test_memory.py, demo/runs/sprint1-45-kb-recall/*

## step.report
Status: succeeded
Inputs: V.verdict, ART.patch
Actions: Wrote solution.md with the implementation summary and evaluation.json with acceptance criteria.
Outputs: ART.report = demo/runs/sprint1-45-kb-recall/solution.md, demo/runs/sprint1-45-kb-recall/evaluation.json
Evidence: solution.md and evaluation.json written.

## step.verify
Status: succeeded
Inputs: G.goal, ART.patch, V.tests, V.verdict
Actions: Verified all acceptance criteria: (1) recall("deploy") ranks matching key first — test_recall_ranks_matching_key_first passes; (2) delete() removes from recall — test_delete_removes_from_recall passes; (3) exact get/keys unchanged — all 760 existing tests pass unchanged; (4) recall on empty KB returns [] — test_recall_empty_kb passes; full suite 764 passed; git status shows only owned files.
Outputs: V.result = all acceptance criteria passed
Evidence: pytest output, git status --porcelain output.
