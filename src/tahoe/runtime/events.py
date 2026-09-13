"""Durable event storage for TAHOE runs.

Implements the event envelope, gapless per-run sequencing inside
transactions, optimistic (CAS) state-version commits for SUCCEEDED
deltas, and deterministic state projection, per
docs/spec/03-runtime-and-events.md.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Sequence

from tahoe.state import StateDelta

__all__ = ["Event", "EventStore", "EventType", "StateVersionConflict", "canonical_json"]


class StateVersionConflict(ValueError):
    """CAS guard fired: another writer committed to the run first.

    Raised by :meth:`EventStore.append_batch` when a record's
    ``expected_state_version`` does not match the run's current version
    at transaction start.  In a concurrent-resume stampede this is the
    signal that another process already resumed the run; the loser
    should get a clean error, not an unhandled traceback.
    """

_TASK_LEDGER_AVAILABLE = False
try:
    from tahoe.runtime.tasks import TaskLedger, TaskLedgerError

    _TASK_LEDGER_AVAILABLE = True
except Exception:
    pass


class EventType(str, Enum):
    """Event families required by the runtime spec."""

    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    INVOCATION_READY = "invocation.ready"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    INVOCATION_DISPATCHED = "invocation.dispatched"
    HEARTBEAT = "invocation.heartbeat"
    INVOCATION_CLAIMED = "invocation.claimed"
    RESULT_RECEIVED = "invocation.result_received"
    VALIDATION_PASSED = "invocation.validation_passed"
    VALIDATION_FAILED = "invocation.validation_failed"
    SUCCEEDED = "invocation.succeeded"
    FAILED = "invocation.failed"
    TIMED_OUT = "invocation.timed_out"
    RETRYING = "invocation.retrying"
    LATE_RESULT = "invocation.late_result"
    CANCELLATION_REQUESTED = "cancellation.requested"
    CANCELLED = "invocation.cancelled"
    BLOCKED = "invocation.blocked"
    UNBLOCKED = "invocation.unblocked"
    JOIN_COMMITTED = "join.committed"
    COMPENSATION_COMPLETED = "compensation.completed"
    # Issue #20: a CALL's isolated child run finished succeeded and the
    # parent adopted its RETURN refs onto the CALL targets.  Carries no
    # state delta of its own — the adopted values commit inside the same
    # batch's SUCCEEDED delta, keeping the parent's state changes atomic.
    CHILD_ADOPTED = "child.adopted"
    # Issue #24: a PAR block's barrier joined — every branch reached a
    # terminal state.  Carries no state delta of its own (the branches'
    # adopted targets commit in the same batch's entry-terminal SUCCEEDED
    # delta); the payload records the per-branch terminal statuses and the
    # merged-artifact accounting.
    PAR_JOINED = "par.joined"
    # Issue #25: a delegate step's worker returned an AUTHORED child plan
    # and the coordinator recorded it before any validation or execution —
    # the authored artifact is part of history, never ephemeral.  Carries
    # no state delta of its own; the payload records the authoring step's
    # id, the plan digest (sha256 over the canonical JSON of the bound
    # plan identity + raw text) and the raw plan text.  Recorded even when
    # the plan is subsequently rejected, so a failed authoring attempt
    # stays diagnosable.
    CHILD_PLAN_AUTHORED = "child_plan.authored"
    # Issue #68: LOOP lifecycle events.  LOOP_STARTED fires when a loop
    # begins (ENTRY condition true); LOOP_ITERATION fires at the start of
    # each body execution; LOOP_EXITED fires when the EXIT condition
    # triggers (loop succeeds); LOOP_EXHAUSTED fires when MAX is reached
    # without EXIT (loop runs the EXHAUSTED terminal).
    LOOP_STARTED = "loop.started"
    LOOP_ITERATION = "loop.iteration"
    LOOP_EXITED = "loop.exited"
    LOOP_EXHAUSTED = "loop.exhausted"
    # Issue #69: TRY lifecycle events.  TRY_STARTED fires when speculative
    # dispatch begins; TRY_BRANCH_SUCCEEDED fires when a branch wins;
    # TRY_BRANCH_CANCELLED fires when a branch is cancelled (lost the race
    # or the TRY failed); TRY_COMPLETED fires when the TRY block resolves.
    TRY_STARTED = "try.started"
    TRY_BRANCH_SUCCEEDED = "try.branch_succeeded"
    TRY_BRANCH_CANCELLED = "try.branch_cancelled"
    TRY_COMPLETED = "try.completed"
    # Issue #80: a REFORMULATE block fired — the plan was reformulated
    # mid-execution.  Payload: {trigger_step, diagnosis_ref,
    # revised_refs, new_plan_digest, preserved_refs}.
    PLAN_REFORMULATED = "plan.reformulated"
    # Issue #77: AWAIT lifecycle events.  AWAIT_SUSPENDED records the
    # event selector and optional timeout when execution pauses;
    # AWAIT_RESUMED records the matching event or timeout expiry when
    # execution continues.
    AWAIT_SUSPENDED = "await.suspended"
    AWAIT_RESUMED = "await.resumed"
    # Issue #77: external events that AWAIT selectors match against.
    # An external system appends an EXTERNAL_EVENT with a payload
    # carrying the selector string; the AWAIT handler matches on it.
    EXTERNAL_EVENT = "external.event"
    # Issue #76: FIRST event-choice — the first matching event selector
    # fired.  Payload: {selector_index, selector, event_type, event_payload}.
    FIRST_EVENT_MATCHED = "first.event_matched"
    TASK_UPDATED = "task.updated"


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Event:
    """Immutable event envelope (spec: Event Envelope).

    ``occurred_at`` is diagnostic only and never drives replay.
    """

    seq: int
    run_id: str
    program_version: str
    event_type: EventType
    instruction_id: str = ""
    invocation_id: str = ""
    task_id: str = ""
    causation_seq: Optional[int] = None
    correlation_id: Optional[str] = None
    attempt: int = 0
    state_version: int = 0
    payload_ref: Optional[str] = None
    payload: Any = None
    occurred_at: datetime = field(default_factory=_utcnow)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    program_version TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    seq INTEGER NOT NULL,
    program_version TEXT NOT NULL,
    event_type TEXT NOT NULL,
    instruction_id TEXT NOT NULL DEFAULT '',
    invocation_id TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    causation_seq INTEGER,
    correlation_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    state_version INTEGER NOT NULL,
    payload_ref TEXT,
    payload TEXT,
    occurred_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS events_invocation_idx
    ON events (run_id, invocation_id, event_type);
CREATE INDEX IF NOT EXISTS events_run_type_idx
    ON events (run_id, event_type);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    description TEXT NOT NULL
);
"""

_SCHEMA_VERSION = 2  # v1: initial + task_id column; v2: events_run_type_idx


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _Record:
    """Internal representation of one event to append in a batch.

    Fields mirror :meth:`EventStore.append` parameters.  ``event_type``
    is normalised to an :class:`EventType` and ``payload`` is normalised
    before the transaction opens, so validation inside the transaction
    sees exactly what will be persisted.
    """

    __slots__ = (
        "event_type", "instruction_id", "invocation_id", "task_id",
        "attempt", "expected_state_version", "payload", "causation_seq",
        "correlation_id",
    )

    def __init__(
        self,
        event_type: "EventType | str",
        instruction_id: str = "",
        invocation_id: str = "",
        task_id: str = "",
        attempt: int = 0,
        expected_state_version: Optional[int] = None,
        payload: Any = None,
        causation_seq: Optional[int] = None,
        correlation_id: Optional[str] = None,
        store: Optional["EventStore"] = None,
    ):
        if not isinstance(event_type, EventType):
            event_type = EventType(event_type)
        self.event_type = event_type
        self.instruction_id = instruction_id
        self.invocation_id = invocation_id
        self.task_id = task_id
        self.attempt = attempt
        self.expected_state_version = expected_state_version
        if store is not None:
            payload = store._normalize_payload(event_type, payload)
        self.payload = payload
        self.causation_seq = causation_seq
        self.correlation_id = correlation_id


class EventStore:
    """SQLite-backed, append-only event store.

    Sequence numbers are gapless per run: each batch runs inside a
    ``BEGIN IMMEDIATE`` transaction that computes ``MAX(seq) + 1`` and
    inserts atomically. ``state_version`` is the run's projected state
    version *after* the event applies; it increments only for SUCCEEDED
    events carrying a delta.

    Thread-safety (issue #21): a single connection guarded by one
    reentrant lock serializes every access, so concurrent frontier
    workers and child runs executing on pool threads share the store
    without corrupting the connection or the gapless sequence. The
    coordinator owner remains the single writer for a run's own event
    stream; the lock only makes the shared connection safe.
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False
        )
        self._succeeded_cache: dict[str, set[str]] = {}
        self._ledger_cache: dict[str, tuple["TaskLedger", int]] = {}
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(_SCHEMA)
            self._run_migrations()

    def _run_migrations(self) -> None:
        """Versioned schema migrations via PRAGMA user_version.

        v1 (implicit for old DBs): the task_id column added by the
        legacy ``_migrate_task_id`` ALTER.  v2: the events_run_type_idx
        index (already in _SCHEMA for fresh DBs, added here for old ones).
        """
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]

        if current < 1:
            cols = {
                row[1]
                for row in self._conn.execute("PRAGMA table_info(events)").fetchall()
            }
            if "task_id" not in cols:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN task_id TEXT NOT NULL DEFAULT ''"
                )
            self._conn.execute("PRAGMA user_version = 1")
            current = 1

        if current < 2:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS events_run_type_idx"
                " ON events (run_id, event_type)"
            )
            self._conn.execute("PRAGMA user_version = 2")
            current = 2

        for version, desc in [(1, "task_id column"), (2, "events_run_type_idx")]:
            row = self._conn.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at, description)"
                    " VALUES (?, ?, ?)",
                    (version, _utcnow().isoformat(), desc),
                )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- runs ---------------------------------------------------------

    def create_run(
        self,
        run_id: str,
        program_version: str,
        metadata: Optional[dict] = None,
    ) -> None:
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO runs (run_id, program_version, metadata, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (run_id, program_version, canonical_json(metadata or {}),
                     _utcnow().isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"run already exists: {run_id!r}") from exc

    def run(self, run_id: str) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id, program_version, metadata, created_at FROM runs"
                " WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown run: {run_id!r}")
            state_version = self._current_state_version(run_id)
            event_count = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
        return {
            "run_id": row[0],
            "program_version": row[1],
            "metadata": json.loads(row[2]),
            "created_at": datetime.fromisoformat(row[3]),
            "state_version": state_version,
            "event_count": event_count,
        }

    # -- events -------------------------------------------------------

    def append(
        self,
        run_id: str,
        event_type: "EventType | str",
        instruction_id: str = "",
        invocation_id: str = "",
        task_id: str = "",
        attempt: int = 0,
        expected_state_version: Optional[int] = None,
        payload: Any = None,
        *,
        causation_seq: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Event:
        """Append one event to a run inside a transaction.

        Delegates to :meth:`append_batch` with a single record.
        """
        records = [
            _Record(
                event_type=event_type,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                attempt=attempt,
                expected_state_version=expected_state_version,
                payload=payload,
                causation_seq=causation_seq,
                correlation_id=correlation_id,
                store=self,
            )
        ]
        events = self.append_batch(run_id, records)
        return events[0]

    def append_batch(
        self,
        run_id: str,
        records: Sequence["_Record"],
    ) -> tuple[Event, ...]:
        """Append multiple events in one ``BEGIN IMMEDIATE`` transaction.

        - rejects unknown runs;
        - rejects a version mismatch when ``expected_state_version`` is
          given on a record (compare-and-swap against the run's current
          version *at transaction start*);
        - rejects a second SUCCEEDED terminal event for the same
          nonempty ``invocation_id`` (checked against committed events
          plus preceding records in this batch);
        - validates TASK_UPDATED records against the task ledger
          projected at transaction start plus preceding records;
        - increments the run's state version only when an event is
          SUCCEEDED and its payload carries a ``delta``;
        - any invalid record rolls back the entire batch.

        Each ``record`` is a :class:`_Record` instance whose field names
        mirror :meth:`append` parameters.
        """
        if not records:
            return ()

        # Single-writer guard (issue #21): the whole transaction — seq
        # allocation, CAS check, ledger validation, inserts, commit —
        # holds the store lock, so concurrent completions and child runs
        # serialize their batches and the gapless sequence is preserved.
        with self._lock:
            return self._append_batch_locked(run_id, records)

    def _append_batch_locked(
        self,
        run_id: str,
        records: Sequence["_Record"],
    ) -> tuple[Event, ...]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            run_row = self._conn.execute(
                "SELECT program_version FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run_row is None:
                raise ValueError(f"unknown run: {run_id!r}")
            program_version = run_row[0]

            current_state_version = self._current_state_version(run_id)
            seq = self._conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 FROM events WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]

            # Pre-build a TaskLedger at transaction-start state for
            # validating TASK_UPDATED records.  If TaskLedger is not
            # available, task validation is skipped (same guard as the
            # old append_task_event).
            batch_ledger: Optional["TaskLedger"] = None
            if _TASK_LEDGER_AVAILABLE:
                batch_ledger = self._task_ledger_cached(run_id)

            results: list[Event] = []
            succeeded_invocations: set[str] = self._succeeded_invocations(run_id)

            for record in records:
                event_type = record.event_type
                payload = record.payload

                delta: Optional[StateDelta] = None
                if event_type is EventType.SUCCEEDED and isinstance(payload, dict) and "delta" in payload:
                    raw = payload["delta"]
                    delta = raw if isinstance(raw, StateDelta) else StateDelta.from_dict(raw)

                # expected_state_version CAS check
                if record.expected_state_version is not None and record.expected_state_version != current_state_version:
                    raise StateVersionConflict(
                        f"state version conflict for run {run_id!r}:"
                        f" expected {record.expected_state_version}, current {current_state_version}"
                    )

                # duplicate SUCCEEDED terminal check
                if event_type is EventType.SUCCEEDED and record.invocation_id:
                    if record.invocation_id in succeeded_invocations:
                        raise StateVersionConflict(
                            f"invocation {record.invocation_id!r} in run {run_id!r}"
                            " already has a SUCCEEDED terminal event"
                            " (concurrent resume detected)"
                        )
                    succeeded_invocations.add(record.invocation_id)

                # TASK_UPDATED validation against ledger at tx-start
                # plus preceding records in this batch
                if event_type is EventType.TASK_UPDATED and batch_ledger is not None:
                    if payload is not None and isinstance(payload, dict):
                        batch_ledger._commit(dict(payload))

                state_version = current_state_version + 1 if delta is not None else current_state_version

                payload_json = canonical_json(payload) if payload is not None else None
                payload_ref = (
                    hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
                    if payload_json is not None
                    else None
                )
                occurred_at = _utcnow()

                self._conn.execute(
                    "INSERT INTO events (run_id, seq, program_version, event_type,"
                    " instruction_id, invocation_id, task_id, causation_seq,"
                    " correlation_id, attempt, state_version, payload_ref,"
                    " payload, occurred_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        seq,
                        program_version,
                        event_type.value,
                        record.instruction_id,
                        record.invocation_id,
                        record.task_id,
                        record.causation_seq,
                        record.correlation_id,
                        record.attempt,
                        state_version,
                        payload_ref,
                        payload_json,
                        occurred_at.isoformat(),
                    ),
                )

                results.append(Event(
                    seq=seq,
                    run_id=run_id,
                    program_version=program_version,
                    event_type=event_type,
                    instruction_id=record.instruction_id,
                    invocation_id=record.invocation_id,
                    task_id=record.task_id,
                    causation_seq=record.causation_seq,
                    correlation_id=record.correlation_id,
                    attempt=record.attempt,
                    state_version=state_version,
                    payload_ref=payload_ref,
                    payload=payload,
                    occurred_at=occurred_at,
                ))

                seq += 1
                if delta is not None:
                    current_state_version = state_version

            self._conn.execute("COMMIT")
        except BaseException:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            self._succeeded_cache.pop(run_id, None)
            self._ledger_cache.pop(run_id, None)
            raise

        self._succeeded_cache.pop(run_id, None)
        self._ledger_cache.pop(run_id, None)

        return tuple(results)

    def events(self, run_id: str) -> tuple[Event, ...]:
        """Return the run's full history in gapless seq order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, program_version, event_type, instruction_id, invocation_id,"
                " task_id, causation_seq, correlation_id, attempt, state_version,"
                " payload_ref, payload, occurred_at"
                " FROM events WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ).fetchall()
        return tuple(
            Event(
                seq=row[0],
                run_id=run_id,
                program_version=row[1],
                event_type=EventType(row[2]),
                instruction_id=row[3],
                invocation_id=row[4],
                task_id=row[5],
                causation_seq=row[6],
                correlation_id=row[7],
                attempt=row[8],
                state_version=row[9],
                payload_ref=row[10],
                payload=json.loads(row[11]) if row[11] is not None else None,
                occurred_at=datetime.fromisoformat(row[12]),
            )
            for row in rows
        )

    # -- projection ---------------------------------------------------

    def ref_history(self, run_id: str, ref: str) -> list[dict[str, Any]]:
        """Return the revision history of a single ref (issue #81).

        Replays all SUCCEEDED deltas in seq order and collects every event
        that added, revised, or retired *ref*, producing a list of revision
        records in chronological order::

            {"action": "add"|"revise"|"retire", "value": <value>,
             "event_type": "invocation.succeeded", "seq": <int>,
             "invocation_id": "..."}

        A ref that was never touched returns an empty list (not an error).
        Retire records carry ``value: None``.
        """
        from tahoe.state import StateDelta

        records: list[dict[str, Any]] = []
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, event_type, invocation_id, payload"
                " FROM events WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ).fetchall()
        for seq, event_type, invocation_id, payload_json in rows:
            if EventType(event_type) is not EventType.SUCCEEDED:
                continue
            if payload_json is None:
                continue
            payload = json.loads(payload_json)
            if not isinstance(payload, dict) or "delta" not in payload:
                continue
            delta = StateDelta.from_dict(payload["delta"])
            for node in delta.add_nodes:
                if node.get("id") == ref:
                    records.append({
                        "action": "add",
                        "value": node.get("value"),
                        "event_type": event_type,
                        "seq": seq,
                        "invocation_id": invocation_id,
                    })
            for node in delta.revise_nodes:
                if node.get("id") == ref:
                    records.append({
                        "action": "revise",
                        "value": node.get("value"),
                        "event_type": event_type,
                        "seq": seq,
                        "invocation_id": invocation_id,
                    })
            if ref in delta.retire_nodes:
                records.append({
                    "action": "retire",
                    "value": None,
                    "event_type": event_type,
                    "seq": seq,
                    "invocation_id": invocation_id,
                })
        return records

    def project_state(self, run_id: str) -> dict:
        """Deterministically project run state from its event history."""
        info = self.run(run_id)
        state: dict = {
            "run_id": info["run_id"],
            "program_version": info["program_version"],
            "metadata": info["metadata"],
            "state_version": 0,
            "nodes": {},
            "artifacts": {},
        }
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_type, payload, state_version FROM events"
                " WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ).fetchall()
        for event_type, payload_json, state_version in rows:
            if EventType(event_type) is EventType.SUCCEEDED and payload_json is not None:
                payload = json.loads(payload_json)
                if isinstance(payload, dict) and "delta" in payload:
                    StateDelta.from_dict(payload["delta"]).apply_to(state)
            state["state_version"] = state_version
        return state

    # -- internals ----------------------------------------------------

    def _succeeded_invocations(self, run_id: str) -> set[str]:
        """Return the set of invocation_ids that already have a SUCCEEDED
        event, using an in-memory cache invalidated on each successful
        batch commit."""
        if run_id in self._succeeded_cache:
            return set(self._succeeded_cache[run_id])
        rows = self._conn.execute(
            "SELECT DISTINCT invocation_id FROM events"
            " WHERE run_id = ? AND event_type = ? AND invocation_id != ''",
            (run_id, EventType.SUCCEEDED.value),
        ).fetchall()
        result = {row[0] for row in rows}
        self._succeeded_cache[run_id] = result
        return set(result)

    def _task_ledger_cached(self, run_id: str) -> "TaskLedger":
        """Rebuild the TaskLedger incrementally, caching by max
        TASK_UPDATED seq.  On a cache hit, only events after the cached
        seq are replayed.  Returns a *copy* so callers may mutate it
        (e.g. append_batch validation) without corrupting the cache.
        """
        if not _TASK_LEDGER_AVAILABLE:
            raise RuntimeError("TaskLedger is not available")
        allow_concurrent = self._run_allows_concurrent(run_id)
        cached = self._ledger_cache.get(run_id)
        if cached is not None:
            ledger, cached_max_seq = cached
            rows = self._conn.execute(
                "SELECT payload, seq FROM events"
                " WHERE run_id = ? AND event_type = ? AND seq > ?"
                " ORDER BY seq ASC",
                (run_id, EventType.TASK_UPDATED.value, cached_max_seq),
            ).fetchall()
            for row in rows:
                if row[0] is not None:
                    ledger._commit(json.loads(row[0]))
            new_max = rows[-1][1] if rows else cached_max_seq
            self._ledger_cache[run_id] = (ledger, new_max)
            return TaskLedger.from_events(
                list(ledger.events), allow_concurrent=allow_concurrent
            )
        rows = self._conn.execute(
            "SELECT payload, seq FROM events"
            " WHERE run_id = ? AND event_type = ? ORDER BY seq ASC",
            (run_id, EventType.TASK_UPDATED.value),
        ).fetchall()
        payloads = [json.loads(row[0]) for row in rows if row[0] is not None]
        max_seq = rows[-1][1] if rows else -1
        ledger = TaskLedger.from_events(payloads, allow_concurrent=allow_concurrent)
        self._ledger_cache[run_id] = (ledger, max_seq)
        return TaskLedger.from_events(
            list(ledger.events), allow_concurrent=allow_concurrent
        )

    def _current_state_version(self, run_id: str) -> int:
        row = self._conn.execute(
            "SELECT state_version FROM events WHERE run_id = ?"
            " ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return row[0] if row is not None else 0

    @staticmethod
    def _normalize_payload(event_type: EventType, payload: Any) -> Any:
        if isinstance(payload, StateDelta):
            return {"delta": payload.to_dict()}
        if (
            event_type is EventType.SUCCEEDED
            and isinstance(payload, dict)
            and isinstance(payload.get("delta"), StateDelta)
        ):
            payload = dict(payload)
            payload["delta"] = payload["delta"].to_dict()
        return payload

    # -- task ledger integration --------------------------------------

    def append_task_event(self, run_id: str, event: dict) -> Event:
        """Validate a proposed ledger event by replay, then persist it.

        Delegates to :meth:`append_batch` with a single TASK_UPDATED
        record.  Validation (dry-run commit against the ledger at
        transaction start) happens inside the transaction; any
        :class:`TaskLedgerError` rolls back.
        """
        if not _TASK_LEDGER_AVAILABLE:
            raise RuntimeError("TaskLedger is not available")

        record = _Record(
            event_type=EventType.TASK_UPDATED,
            task_id=event.get("id", ""),
            payload=dict(event),
            store=self,
        )
        events = self.append_batch(run_id, [record])
        return events[0]

    def task_ledger(
        self,
        run_id: str,
        *,
        allow_concurrent: "bool | None" = None,
    ) -> "TaskLedger":
        """Rebuild a :class:`TaskLedger` from stored TASK_UPDATED payloads.

        Issue #21: when ``allow_concurrent`` is left unset it is
        auto-detected from the run metadata — a run the coordinator
        started in concurrent mode (``concurrent: true``) replays with a
        ledger that permits multiple IN_PROGRESS tasks, so both live
        validation inside ``append_batch`` and later replay reconstruct
        the same multi-IN_PROGRESS intermediate states.  An explicit
        ``False`` keeps the default strict single-in-progress rule.

        Issue #39: uses an incremental cache keyed by max TASK_UPDATED
        seq to avoid full rebuild per batch.
        """
        if not _TASK_LEDGER_AVAILABLE:
            raise RuntimeError("TaskLedger is not available")
        if allow_concurrent is None:
            return self._task_ledger_cached(run_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM events"
                " WHERE run_id = ? AND event_type = ? ORDER BY seq ASC",
                (run_id, EventType.TASK_UPDATED.value),
            ).fetchall()
        payloads = [json.loads(row[0]) for row in rows if row[0] is not None]
        return TaskLedger.from_events(payloads, allow_concurrent=allow_concurrent)

    def _run_allows_concurrent(self, run_id: str) -> bool:
        """Whether the run was started in concurrent mode (issue #21)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT metadata FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return False
        try:
            metadata = json.loads(row[0])
        except ValueError:
            return False
        return isinstance(metadata, dict) and metadata.get("concurrent") is True
