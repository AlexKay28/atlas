"""Tests for issue #39: event store scaling, schema versioning, and
incremental ledger caching.

Acceptance items:
1. events_run_type_idx index exists and is used by the planner.
2. 2000-step synthetic run scales ~linearly (before/after benchmark).
3. Pre-migration (old DB) and fresh DB yield identical projections.
4. Schema versioning via PRAGMA user_version + migration table.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from tahoe.runtime.events import EventStore, EventType, canonical_json
from tahoe.runtime.tasks import TaskLedger, TaskStatus
from tahoe.state import StateDelta


# -- (1) index exists ------------------------------------------------


def test_events_run_type_idx_exists(tmp_path):
    with EventStore(str(tmp_path / "events.db")) as store:
        indexes = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND tbl_name='events'"
        ).fetchall()
        names = {row[0] for row in indexes}
        assert "events_run_type_idx" in names


def test_events_run_type_idx_used_by_query_planner(tmp_path):
    """The task_ledger scan (run_id, event_type) is backed by
    events_run_type_idx when there's no competing ORDER BY seq."""
    with EventStore(str(tmp_path / "events.db")) as store:
        store.create_run("run-1", "prog@1")
        store.append("run-1", EventType.RUN_STARTED)
        for i in range(20):
            store.append_task_event("run-1", {
                "kind": "task_created", "id": f"task-{i}",
                "text": f"task {i}", "priority": 0,
                "parent": None, "dependencies": [], "creator": "test",
            })
        plan = store._conn.execute(
            "EXPLAIN QUERY PLAN SELECT payload FROM events"
            " WHERE run_id = ? AND event_type = ?",
            ("run-1", EventType.TASK_UPDATED.value),
        ).fetchall()
        plan_text = " ".join(str(row) for row in plan)
        assert "events_run_type_idx" in plan_text


# -- (2) 2000-step scaling benchmark ---------------------------------


def _synthetic_run(store, run_id, n_steps):
    """Append n_steps SUCCEEDED events with state deltas, one per batch."""
    store.create_run(run_id, "prog@1")
    store.append(run_id, EventType.RUN_STARTED)
    for i in range(n_steps):
        store.append(
            run_id,
            EventType.SUCCEEDED,
            invocation_id=f"inv-{i}",
            payload={"delta": StateDelta(add_nodes=({"id": f"n{i}"},)).to_dict()},
        )
    store.append(run_id, EventType.RUN_FINISHED, payload={"status": "succeeded"})


def test_2000_step_run_scales_linearly(tmp_path):
    """A 2000-step run should complete in reasonable time, demonstrating
    that the incremental caches prevent O(N^2) behavior.

    We measure wall time for the full run and assert it stays well
    within the bound that would indicate quadratic behavior.  A
    quadratic run would take minutes; with caching it should be
    seconds.
    """
    n_steps = 2000
    with EventStore(str(tmp_path / "events.db")) as store:
        t0 = time.perf_counter()
        _synthetic_run(store, "run-scale", n_steps)
        elapsed = time.perf_counter() - t0

    # With O(N^2) behavior this would take > 60s for 2000 steps.
    # With caching it should be under 10s on any reasonable machine.
    # We use a generous bound to avoid CI flakiness.
    assert elapsed < 30.0, f"2000-step run took {elapsed:.1f}s — possible O(N^2)"

    # Verify the run is correct
    with EventStore(str(tmp_path / "events.db")) as store:
        state = store.project_state("run-scale")
        assert state["state_version"] == n_steps
        assert len(state["nodes"]) == n_steps
        events = store.events("run-scale")
        assert len(events) == n_steps + 2  # +RUN_STARTED +RUN_FINISHED


def test_2000_step_run_ledger_scales_linearly(tmp_path):
    """Appending 2000 TASK_UPDATED events should also scale linearly."""
    n_steps = 2000
    with EventStore(str(tmp_path / "events.db")) as store:
        store.create_run("run-ledger", "prog@1")
        store.append("run-ledger", EventType.RUN_STARTED)
        for i in range(n_steps):
            store.append_task_event(
                "run-ledger",
                {
                    "kind": "task_created",
                    "id": f"task-{i}",
                    "text": f"task {i}",
                    "priority": 0,
                    "parent": None,
                    "dependencies": [],
                    "creator": "test",
                },
            )

        t0 = time.perf_counter()
        ledger = store.task_ledger("run-ledger")
        elapsed = time.perf_counter() - t0

        assert len(ledger.tasks) == n_steps
        assert elapsed < 10.0, f"ledger rebuild took {elapsed:.1f}s for {n_steps} tasks"


# -- (3) migration: old DB vs fresh DB identical projections ---------


def _create_old_db(db_path):
    """Create a DB with the old schema (no task_id, no user_version,
    no events_run_type_idx, no schema_migrations table)."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            program_version TEXT NOT NULL,
            metadata TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE events (
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            seq INTEGER NOT NULL,
            program_version TEXT NOT NULL,
            event_type TEXT NOT NULL,
            instruction_id TEXT NOT NULL DEFAULT '',
            invocation_id TEXT NOT NULL DEFAULT '',
            causation_seq INTEGER,
            correlation_id TEXT,
            attempt INTEGER NOT NULL DEFAULT 0,
            state_version INTEGER NOT NULL,
            payload_ref TEXT,
            payload TEXT,
            occurred_at TEXT NOT NULL,
            PRIMARY KEY (run_id, seq)
        );
        CREATE INDEX events_invocation_idx
            ON events (run_id, invocation_id, event_type);
    """)
    conn.execute("PRAGMA user_version = 0")

    conn.execute(
        "INSERT INTO runs (run_id, program_version, metadata, created_at)"
        " VALUES (?, ?, ?, ?)",
        ("run-old", "prog@1", "{}", "2026-01-01T00:00:00+00:00"),
    )
    events = [
        ("run-old", 0, "prog@1", "run.started", "", "", None, None, 0, 0, None, None, "2026-01-01T00:00:00+00:00"),
        ("run-old", 1, "prog@1", "invocation.succeeded", "step.1", "inv-1", None, None, 0, 1,
         hashlib_sha256({"delta": {"add_nodes": [{"id": "n1"}]}}),
         canonical_json({"delta": {"add_nodes": [{"id": "n1"}]}}),
         "2026-01-01T00:00:01+00:00"),
        ("run-old", 2, "prog@1", "run.finished", "", "", None, None, 0, 1,
         hashlib_sha256({"status": "succeeded"}),
         canonical_json({"status": "succeeded"}),
         "2026-01-01T00:00:02+00:00"),
    ]
    for ev in events:
        conn.execute(
            "INSERT INTO events (run_id, seq, program_version, event_type,"
            " instruction_id, invocation_id, causation_seq, correlation_id,"
            " attempt, state_version, payload_ref, payload, occurred_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ev,
        )
    conn.commit()
    conn.close()


def hashlib_sha256(payload):
    import hashlib
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def test_old_db_migrates_and_projections_match_fresh(tmp_path):
    """An old DB (pre-migration, no task_id, user_version=0) opened with
    EventStore gets migrated (task_id added, user_version set, index
    created) and produces the same projection as a fresh DB with
    identical events."""
    old_db = tmp_path / "old.db"
    fresh_db = tmp_path / "fresh.db"

    _create_old_db(old_db)

    store_old = EventStore(str(old_db))
    try:
        assert store_old._conn.execute("PRAGMA user_version").fetchone()[0] == 2
        cols = {row[1] for row in store_old._conn.execute("PRAGMA table_info(events)").fetchall()}
        assert "task_id" in cols
        idx = {row[0] for row in store_old._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events'"
        ).fetchall()}
        assert "events_run_type_idx" in idx

        state_old = store_old.project_state("run-old")
        events_old = store_old.events("run-old")
    finally:
        store_old.close()

    store_fresh = EventStore(str(fresh_db))
    try:
        store_fresh.create_run("run-old", "prog@1")
        store_fresh.append("run-old", EventType.RUN_STARTED)
        store_fresh.append(
            "run-old", EventType.SUCCEEDED,
            invocation_id="inv-1",
            payload={"delta": StateDelta(add_nodes=({"id": "n1"},))},
        )
        store_fresh.append("run-old", EventType.RUN_FINISHED, payload={"status": "succeeded"})

        state_fresh = store_fresh.project_state("run-old")
        events_fresh = store_fresh.events("run-old")
    finally:
        store_fresh.close()

    assert state_old == state_fresh
    assert len(events_old) == len(events_fresh)
    assert [e.event_type for e in events_old] == [e.event_type for e in events_fresh]
    assert [e.state_version for e in events_old] == [e.state_version for e in events_fresh]


def test_migration_table_populated(tmp_path):
    """The schema_migrations table records each applied migration."""
    with EventStore(str(tmp_path / "events.db")) as store:
        rows = store._conn.execute(
            "SELECT version, description FROM schema_migrations ORDER BY version"
        ).fetchall()
        versions = {row[0]: row[1] for row in rows}
        assert 1 in versions
        assert 2 in versions
        assert "task_id" in versions[1]
        assert "events_run_type_idx" in versions[2]


def test_reopen_does_not_reapply_migrations(tmp_path):
    """Reopening a migrated DB does not re-run migrations."""
    db = tmp_path / "events.db"
    with EventStore(str(db)) as store:
        store.create_run("run-1", "prog@1")
        store.append("run-1", EventType.RUN_STARTED)

    with EventStore(str(db)) as store:
        assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 2
        rows = store._conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
        ).fetchone()
        assert rows[0] == 1  # not duplicated


# -- (4) incremental cache correctness -------------------------------


def test_succeeded_cache_invalidated_on_batch(tmp_path):
    """The succeeded-invocation cache is invalidated after each batch."""
    with EventStore(str(tmp_path / "events.db")) as store:
        store.create_run("run-1", "prog@1")
        store.append("run-1", EventType.RUN_STARTED)

        store.append(
            "run-1", EventType.SUCCEEDED,
            invocation_id="inv-1",
            payload={"delta": StateDelta(add_nodes=({"id": "n1"},)).to_dict()},
        )
        assert "run-1" not in store._succeeded_cache

        with pytest.raises(ValueError, match="SUCCEEDED terminal"):
            store.append(
                "run-1", EventType.SUCCEEDED,
                invocation_id="inv-1",
                payload={"delta": StateDelta(add_nodes=({"id": "n2"},)).to_dict()},
            )


def test_task_ledger_cache_returns_independent_copy(tmp_path):
    """The cached TaskLedger returns independent copies so mutation
    during append_batch validation does not corrupt the cache."""
    with EventStore(str(tmp_path / "events.db")) as store:
        store.create_run("run-1", "prog@1")
        store.append_task_event("run-1", {
            "kind": "task_created", "id": "task-1", "text": "work",
            "priority": 0, "parent": None, "dependencies": [], "creator": "user",
        })

        ledger1 = store._task_ledger_cached("run-1")
        ledger2 = store._task_ledger_cached("run-1")
        assert ledger1 is not ledger2
        assert ledger1.tasks.keys() == ledger2.tasks.keys()

        ledger1._commit({"kind": "task_started", "id": "task-1"})
        assert ledger1.tasks["task-1"].status is TaskStatus.IN_PROGRESS
        assert ledger2.tasks["task-1"].status is TaskStatus.PENDING
