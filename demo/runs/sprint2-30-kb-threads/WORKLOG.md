# WORKLOG — sprint2-30-kb-threads

Seal: 9b788c700c05e4accc41a46c00999dc595a131cd910cf6ca496c2eafdb99ede5
Program: demo/runs/sprint2-30-kb-threads/program.think (linted valid and sealed before any source edit; program is never modified after sealing)

Protocol note: the sealed ATLAS plan in issue #30 references `src/atlas/memory.py` and `tests/test_memory.py` in C.scope. The #53 TAHOE rebrand moved all `src/atlas/` paths to `src/tahoe/`. Only string literals mentioning `src/atlas/` were updated to `src/tahoe/`; logic is identical. Recorded as a protocol deviation in evaluation.json.

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done, C.advanced from program.think INPUT block
Actions: Framed issue #30 into deliverables: (1) Add `check_same_thread=False` to `sqlite3.connect` in KnowledgeBase.__init__; (2) Add one `threading.RLock` guarding every public method (set/get/keys/recall/delete + `__contains__` + `close` + FTS5 maintenance in `_ensure_fts_shadow`); (3) Mirror the EventStore threading pattern (events.py:205-208); (4) Keep the #45 FTS5 recall surface and exact-key grammar unchanged; (5) Tests for all acceptance criteria; (6) Demo run artifacts.
Outputs: G.plan = the deliverables above.
Evidence: gh issue view 30 (with comments); issue text in prompt; program.think INPUT block.

## step.search
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located the code sites: src/tahoe/memory.py (194 lines pre-edit — the only source to edit); tests/test_memory.py (156 lines — existing tests to keep green, new tests to add); src/tahoe/runtime/events.py (625 lines — read-only, the EventStore threading pattern to mirror: `self._lock = threading.RLock()` + `sqlite3.connect(path, isolation_level=None, check_same_thread=False)` + `with self._lock:` on every method); src/tahoe/runtime/coordinator.py:1332-1333 (read-only — ThreadPoolExecutor dispatches handlers on pool threads, confirming the concurrent frontier that exposes the bug).
Outputs: E.sites = {memory.py, test_memory.py, events.py (pattern), coordinator.py:1332-1333 (context)}
Evidence: src/tahoe/memory.py (full read); src/tahoe/runtime/events.py (full read); src/tahoe/runtime/coordinator.py lines 1332-1333 (read-only); tests/test_memory.py (full read).

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read memory.py fully: KnowledgeBase.__init__ (line 55) calls `sqlite3.connect(path)` without `check_same_thread=False` — the root cause. No lock anywhere. set/get/delete/keys/recall/__contains__/close all access `self._conn` directly. EventStore (events.py:205-208) uses `self._lock = threading.RLock()` and `sqlite3.connect(path, isolation_level=None, check_same_thread=False)`, then wraps every method body in `with self._lock:`. The coordinator dispatches handler functions onto a ThreadPoolExecutor (coordinator.py:1332-1333), so handlers run on pool threads while the CLI creates the KB on the main thread — any max_workers>1 run using remember crashes with "SQLite objects created in a thread can only be used in that same thread."
Outputs: ART.sources = the read source code and defect analysis.
Evidence: src/tahoe/memory.py lines 51-194; src/tahoe/runtime/events.py lines 203-216, 232-233, 244-249, 332-333, 473-480, 514-519; src/tahoe/runtime/coordinator.py lines 1332-1392.

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Extracted the defect context: (1) Root cause: `sqlite3.connect(path)` on line 55 creates a connection bound to the main thread; pool threads cannot use it. (2) Fix: add `check_same_thread=False` (lets the connection be shared across threads) and one `threading.RLock` to serialize access (prevents concurrent SQLite writes from corrupting state). (3) The RLock must wrap every public method body — set/get/delete/keys/recall/__contains__/close — plus the internal `_ensure_fts_shadow`. (4) The `__init__` itself is called on the creator thread, but schema setup should still hold the lock for consistency. (5) The FTS5 maintenance in set() (DELETE+INSERT on knowledge_fts) and delete() (DELETE on knowledge_fts) are already inside the same method body as the knowledge table operations, so wrapping the entire method body suffices. (6) `json.dumps` and `_validate_key` in set() are outside the lock (no shared state) — only the `self._conn` operations need guarding.
Outputs: E.findings = the defect context and fix strategy.
Evidence: this analysis; EventStore pattern in events.py; SQLite threading documentation.

## step.plan
Status: succeeded
Inputs: G.plan
Actions: Decomposed into subtasks: (1) Add `import threading` to memory.py; (2) Add `self._lock = threading.RLock()` before `sqlite3.connect` in __init__; (3) Change `sqlite3.connect(path)` to `sqlite3.connect(path, check_same_thread=False)`; (4) Wrap __init__ schema setup in `with self._lock:`; (5) Wrap `_ensure_fts_shadow` body in `with self._lock:`; (6) Wrap `set` body (the self._conn operations) in `with self._lock:`; (7) Wrap `get` body in `with self._lock:`; (8) Wrap `delete` body in `with self._lock:`; (9) Wrap `keys` body in `with self._lock:`; (10) Wrap `recall` body in `with self._lock:`; (11) Wrap `__contains__` body in `with self._lock:`; (12) Wrap `close` body in `with self._lock:`; (13) Write 3 acceptance tests; (14) Run full suite; (15) Write demo artifacts.
Outputs: G.subgoals = the 15 subtasks above.
Evidence: this decomposition.

## step.patch
Status: succeeded
Inputs: G.subgoals
Actions: Edited src/tahoe/memory.py: added `import threading`, added `self._lock = threading.RLock()`, changed `sqlite3.connect(path)` to `sqlite3.connect(path, check_same_thread=False)`, wrapped every public method body and `_ensure_fts_shadow` in `with self._lock:`. The JSON serialization and key validation in `set()` remain outside the lock (no shared state). Edited tests/test_memory.py: added 3 acceptance tests (test_kb_callable_from_non_creator_thread, test_concurrent_remember_steps_succeed, test_parallel_remember_and_recall_never_tears).
Outputs: ART.patch = src/tahoe/memory.py (modified), tests/test_memory.py (modified)
Evidence: git diff; code changes described above.

## step.test
Status: succeeded
Inputs: ART.patch
Actions: Ran `PYTHONPATH=src python3 -m pytest -q` — all 860 tests pass (857 baseline + 3 new). The 3 new tests cover: (1) KB methods callable from a non-creator thread; (2) concurrent remember steps with max_workers=2 succeed; (3) parallel remember+recall of one key never tears (40 set + 40 recall on 4 threads).
Outputs: V.tests = 860 passed in 20.36s
Evidence: pytest output: 860 passed in 20.36s

## DONE matched(V.tests, "passed")
Status: succeeded
Inputs: V.tests
Actions: Confirmed V.tests matches "passed" — all 860 tests passed.
Outputs: gate passed
Evidence: pytest exit code 0.

## step.review
Status: succeeded
Inputs: ART.patch, V.tests
Actions: Reviewed the patch against C.done: (1) max_workers=2 run with two remember steps succeeds — test_concurrent_remember_steps_succeed passes; (2) KB methods callable from a non-creator thread — test_kb_callable_from_non_creator_thread passes; (3) parallel remember+recall never tears — test_parallel_remember_and_recall_never_tears passes; (4) all #45 recall tests pass unchanged — test_recall_ranks_matching_key_first, test_delete_removes_key_from_recall, test_recall_empty_kb_returns_empty, test_recall_lazy_creation_on_old_db all pass. The FTS5 recall surface and exact-key grammar are untouched (only locking added).
Outputs: V.review = all acceptance criteria met
Evidence: test output; git diff showing only locking changes (no FTS5 or key grammar changes).

## step.check
Status: succeeded
Inputs: V.review
Actions: Checked V.review against C.done predicate: "a max_workers=2 run with two remember steps succeeds and parallel remember and recall never tear" — both confirmed by tests.
Outputs: V.verdict = acceptance_criteria_met
Evidence: V.review.

## step.verify
Status: succeeded
Inputs: G.goal, V.verdict, V.tests, E.findings
Actions: Verified the goal "Make KnowledgeBase thread-safe: check_same_thread=False plus one reentrant lock around all operations so concurrent runs using remember do not crash" is fully achieved. All 857 existing tests pass unchanged (857+3=860 total). The fix mirrors the EventStore pattern exactly: `check_same_thread=False` + one `RLock` around every public method.
Outputs: V.result = "resolved"
Evidence: 860 passed; git status --porcelain shows only owned files (src/tahoe/memory.py, tests/test_memory.py, demo/runs/sprint2-30-kb-threads/).

## DONE V.result == "resolved"
Status: succeeded
Inputs: V.result
Actions: Confirmed V.result equals "resolved".
Outputs: gate passed
Evidence: V.result.

## step.report
Status: succeeded
Inputs: V.result, V.verdict
Actions: Wrote solution.md and evaluation.json.
Outputs: ART.report = demo/runs/sprint2-30-kb-threads/solution.md, demo/runs/sprint2-30-kb-threads/evaluation.json
Evidence: solution.md and evaluation.json written.
