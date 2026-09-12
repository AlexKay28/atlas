"""Cross-run semantic memory (CoALA "semantic memory") for tikhon.

A :class:`KnowledgeBase` is durable key/value knowledge that outlives a
single run, backed by its own SQLite file (typically ``kb.sqlite`` next to
the event store).  Program-facing references are ``KB.<name>``; the stored
keys carry the enforced ``kb.`` prefix (``kb.<name>``) while values are
canonical JSON.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

__all__ = ["KnowledgeBase"]

_KEY_RE = re.compile(r"^kb\.[a-z][a-z0-9_]*$")
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS knowledge ("
    "key TEXT PRIMARY KEY,"
    "value TEXT NOT NULL,"
    "source_run TEXT,"
    "updated_at TEXT NOT NULL)"
)
_META_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS _meta ("
    "key TEXT PRIMARY KEY,"
    "value TEXT NOT NULL)"
)
_FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
    "key UNINDEXED,"
    "value)"
)
_FTS_SCHEMA_VERSION = "1"


class KnowledgeBase:
    """Durable JSON key/value store shared across runs.

    Keys must match ``kb.[a-z][a-z0-9_]*`` — the ``kb.`` prefix is
    mandatory and enforced here, so program-facing ``KB.<name>`` references
    map one-to-one onto stored keys.  Values must be JSON-serializable and
    are stored as canonical JSON text (sorted keys, no whitespace).
    """

    def __init__(self, path: str):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute(_SCHEMA)
        self._conn.execute(_META_SCHEMA)
        self._ensure_fts_shadow()

    def _ensure_fts_shadow(self) -> None:
        """Create the FTS5 shadow table if missing and backfill existing rows.

        On an old DB file created before FTS5 support, the shadow table
        does not exist; this method creates it and copies all canonical
        values from the ``knowledge`` table so ``recall()`` works
        immediately.  A schema version is stored in ``_meta`` for future
        migrations.
        """
        exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_fts'"
        ).fetchone()
        self._conn.execute(_FTS_SCHEMA)
        if exists is None:
            self._conn.execute(
                "INSERT INTO knowledge_fts (key, value)"
                " SELECT key, value FROM knowledge"
            )
        self._conn.execute(
            "INSERT INTO _meta (key, value) VALUES ('fts_schema_version', ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_FTS_SCHEMA_VERSION,),
        )
        self._conn.commit()

    def set(self, key: str, value: Any, source_run: str | None = None) -> dict[str, Any]:
        """Store ``value`` under ``key`` and return the stored record."""
        _validate_key(key)
        try:
            canonical = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"KB value for {key!r} must be JSON-serializable: {exc}") from exc
        updated_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO knowledge (key, value, source_run, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET"
            " value=excluded.value, source_run=excluded.source_run,"
            " updated_at=excluded.updated_at",
            (key, canonical, source_run, updated_at),
        )
        self._conn.execute(
            "DELETE FROM knowledge_fts WHERE key = ?", (key,)
        )
        self._conn.execute(
            "INSERT INTO knowledge_fts (key, value) VALUES (?, ?)",
            (key, canonical),
        )
        self._conn.commit()
        return {
            "key": key,
            "value": value,
            "source_run": source_run,
            "updated_at": updated_at,
        }

    def get(self, key: str) -> Any:
        """Return the decoded value for ``key``, or ``None`` when absent."""
        _validate_key(key)
        row = self._conn.execute(
            "SELECT value FROM knowledge WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def delete(self, key: str) -> bool:
        """Remove ``key``; return whether a row was deleted."""
        _validate_key(key)
        cursor = self._conn.execute("DELETE FROM knowledge WHERE key = ?", (key,))
        self._conn.execute("DELETE FROM knowledge_fts WHERE key = ?", (key,))
        self._conn.commit()
        return cursor.rowcount > 0

    def keys(self, prefix: str | None = None) -> tuple[str, ...]:
        """Stored keys, optionally filtered by ``prefix``, in sorted order."""
        if prefix is None:
            rows = self._conn.execute("SELECT key FROM knowledge").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT key FROM knowledge WHERE key LIKE ? ESCAPE '\\'"
                " ORDER BY key",
                (_like_escape(prefix) + "%",),
            ).fetchall()
        return tuple(row[0] for row in rows)

    def recall(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Return up to ``k`` ``(key, score)`` pairs ranked by FTS5 bm25.

        The shadow table ``knowledge_fts`` indexes the canonical value
        text of every stored key.  ``recall()`` is additive API for
        drivers/delegates — it does not change ``get()``, ``keys()``,
        or the ``KB.<name>`` exact-ref grammar.
        """
        if not query.strip():
            return []
        rows = self._conn.execute(
            "SELECT key, bm25(knowledge_fts) AS score"
            " FROM knowledge_fts"
            " WHERE knowledge_fts MATCH ?"
            " ORDER BY score"
            " LIMIT ?",
            (query, k),
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        row = self._conn.execute(
            "SELECT 1 FROM knowledge WHERE key = ?", (key,)
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "KnowledgeBase":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _validate_key(key: str) -> None:
    if not isinstance(key, str) or _KEY_RE.fullmatch(key) is None:
        raise ValueError(
            f"invalid KB key {key!r}: must match kb.[a-z][a-z0-9_]*"
        )


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
