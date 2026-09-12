"""Tests for the cross-run semantic memory KnowledgeBase (issue #5).

The KnowledgeBase is durable JSON key/value storage backed by its own
SQLite file (typically ``kb.sqlite`` next to the event store).  Keys must
match ``kb.[a-z][a-z0-9_]*``; values are any JSON-serializable object,
stored as canonical JSON.  These tests specify the module API used by the
``remember``/``recall`` commands and the coordinator's ``KB.<name>``
reference resolution.
"""

import pytest

from atlas.memory import KnowledgeBase


def test_set_get_roundtrip(tmp_path):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        record = kb.set("kb.user_name", "atlas", source_run="run-1")
        assert record["key"] == "kb.user_name"
        assert record["value"] == "atlas"
        assert record["source_run"] == "run-1"
        assert record["updated_at"]
        assert kb.get("kb.user_name") == "atlas"


def test_values_may_be_any_json_shape(tmp_path):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        kb.set("kb.plan", {"steps": ["frame", "seal"], "budget": 4000})
        kb.set("kb.scores", [1, 2, 3])
        kb.set("kb.flag", True)
        kb.set("kb.empty", None)
        kb.set("kb.ratio", 1.5)
        assert kb.get("kb.plan") == {"steps": ["frame", "seal"], "budget": 4000}
        assert kb.get("kb.scores") == [1, 2, 3]
        assert kb.get("kb.flag") is True
        assert kb.get("kb.empty") is None
        assert kb.get("kb.ratio") == 1.5


def test_get_missing_key_returns_none(tmp_path):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        assert kb.get("kb.absent") is None


def test_delete_removes_and_reports_presence(tmp_path):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        kb.set("kb.temp", "gone soon")
        assert kb.delete("kb.temp") is True
        assert kb.get("kb.temp") is None
        assert kb.delete("kb.temp") is False


def test_set_overwrites_existing_key(tmp_path):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        kb.set("kb.status", "draft", source_run="run-1")
        kb.set("kb.status", "sealed", source_run="run-2")
        assert kb.get("kb.status") == "sealed"
        assert tuple(kb.keys()) == ("kb.status",)


def test_values_persist_across_reopen(tmp_path):
    path = tmp_path / "kb.sqlite"
    with KnowledgeBase(path) as kb:
        kb.set("kb.lesson", {"text": "seal before editing"}, source_run="run-1")

    with KnowledgeBase(path) as reopened:
        assert reopened.get("kb.lesson") == {"text": "seal before editing"}
        assert "kb.lesson" in reopened
        assert reopened.keys() == ("kb.lesson",)


def test_keys_prefix_filter(tmp_path):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        kb.set("kb.user_name", "atlas")
        kb.set("kb.user_home", "/home/atlas")
        kb.set("kb.plan_digest", "abc123")
        assert kb.keys() == ("kb.plan_digest", "kb.user_home", "kb.user_name")
        assert kb.keys(prefix="kb.user") == ("kb.user_home", "kb.user_name")
        assert kb.keys(prefix="kb.user_name") == ("kb.user_name",)
        assert kb.keys(prefix="kb.nobody") == ()


@pytest.mark.parametrize(
    "bad_key", ["user_name", "kb.", "kb.User", "kb.1st", "kb.has-dash", "kb.has space", "", "KB.user"]
)
def test_invalid_key_format_rejected(tmp_path, bad_key):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        with pytest.raises(ValueError, match="kb\\."):
            kb.set(bad_key, "x")
        with pytest.raises(ValueError):
            kb.get(bad_key)
        with pytest.raises(ValueError):
            kb.delete(bad_key)


def test_non_serializable_value_rejected(tmp_path):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        with pytest.raises(ValueError, match="JSON-serializable"):
            kb.set("kb.bad", object())
        assert "kb.bad" not in kb


# --- Issue #45: recall() FTS5 ranking over values ---

def test_recall_ranks_matching_key_first(tmp_path):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        kb.set("kb.config", {"text": "database connection settings"})
        kb.set("kb.deploy_steps", {"text": "how to deploy the service"})
        kb.set("kb.notes", {"text": "random meeting notes about lunch"})
        results = kb.recall("deploy")
        assert len(results) > 0
        assert results[0][0] == "kb.deploy_steps"


def test_delete_removes_key_from_recall(tmp_path):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        kb.set("kb.alpha", {"text": "deploy instructions here"})
        kb.set("kb.beta", {"text": "deploy guide for production"})
        results_before = kb.recall("deploy")
        keys_before = [k for k, _ in results_before]
        assert "kb.alpha" in keys_before
        kb.delete("kb.alpha")
        results_after = kb.recall("deploy")
        keys_after = [k for k, _ in results_after]
        assert "kb.alpha" not in keys_after


def test_recall_empty_kb_returns_empty(tmp_path):
    with KnowledgeBase(tmp_path / "kb.sqlite") as kb:
        assert kb.recall("anything") == []


def test_recall_lazy_creation_on_old_db(tmp_path):
    """An old DB file created without FTS5 gets the shadow table on reopen."""
    path = tmp_path / "kb.sqlite"
    # Simulate an old DB: create the knowledge table and insert a row
    # WITHOUT creating the FTS5 shadow table (as a pre-#45 version would).
    import sqlite3
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE knowledge ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL,"
        " source_run TEXT, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO knowledge (key, value, source_run, updated_at)"
        " VALUES (?, ?, ?, ?)",
        ("kb.legacy", '{"text":"created before fts5 support"}', None, "2026-01-01"),
    )
    conn.commit()
    conn.close()
    # Now open with the new KnowledgeBase — it should create + backfill FTS5.
    with KnowledgeBase(path) as kb:
        results = kb.recall("created")
        assert len(results) > 0
        assert results[0][0] == "kb.legacy"
