"""Tests for tahoe status lifecycle (issue #40).

Acceptance:
  (1) failed run shows failed marker + error;
  (2) concurrent run lists every IN_PROGRESS task;
  (3) crashed (non-terminal) run renders distinctly from finished;
  (4) --json carries the new fields;
  (5) existing suite green.
"""

import json
import re

import pytest

from tahoe.cli import main
from tahoe.runtime import (
    DeterministicWorker,
    EventStore,
    EventType,
    SequentialCoordinator,
)
from tahoe.runtime.tasks import TaskLedger, TaskStatus
from tahoe.syntax import parse_program

RUN_ID = "run-40"

CANONICAL = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {"request": "ship"}

step.one: DO define(value = G.goal) -> E.result

RETURN E.result
"""

FAIL_PROGRAM = """\
PROGRAM fail_demo VERSION 1.0

step.boom: DO define(value = "boom") -> E.r

RETURN E.r
"""

CONCURRENT_PROGRAM = """\
PROGRAM concurrent_demo VERSION 1.0

INPUT
    G.a = "a"
    G.b = "b"

step.first: DO define(goal = G.a) -> OUT.first
step.second: DO define(goal = G.b) -> OUT.second

RETURN OUT.first, OUT.second
"""

DIGEST_RE = re.compile(r"\b[0-9a-f]{64}\b")


def _write(tmp_path, text, name="demo.think"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _seal_of(tmp_path, capsys, text=CANONICAL, name="seal-input.think"):
    p = _write(tmp_path, text, name)
    rc = main(["seal", str(p)])
    assert rc == 0
    out = capsys.readouterr().out
    m = DIGEST_RE.search(out)
    assert m is not None
    return m.group(0)


def _run(tmp_path, capsys, text=CANONICAL, run_id=RUN_ID):
    program = _write(tmp_path, text)
    db = tmp_path / "events.db"
    digest = _seal_of(tmp_path, capsys, text=text)
    rc = main([
        "run", str(program), "--db", str(db),
        "--run-id", run_id, "--seal", digest,
    ])
    captured = capsys.readouterr()
    return db, rc, captured.out, captured.err


def _status(capsys, db, run_id=RUN_ID, json_=False):
    argv = ["status", "--db", str(db), "--run-id", run_id]
    if json_:
        argv.append("--json")
    rc = main(argv)
    out, err = capsys.readouterr()
    return rc, out, err


def _boom_handlers():
    from tahoe.cli import _deterministic_handlers
    handlers = _deterministic_handlers()
    def _boom(**kwargs):
        raise RuntimeError("kaput")
    handlers["define"] = _boom
    return handlers


def _run_failed(tmp_path, run_id="run-fail"):
    """Execute a program that fails, leaving a RUN_FINISHED failed event."""
    store = EventStore(str(tmp_path / "fail.db"))
    program = parse_program(FAIL_PROGRAM)
    worker = DeterministicWorker(_boom_handlers())
    coordinator = SequentialCoordinator(store, worker)
    coordinator.execute(program, run_id=run_id)
    store.close()
    return tmp_path / "fail.db"


def _run_concurrent(tmp_path, run_id="run-concurrent"):
    """Create a store with two IN_PROGRESS tasks (concurrent mode, no
    RUN_FINISHED — simulates a crashed concurrent run).
    """
    db = tmp_path / "concurrent.db"
    store = EventStore(str(db))
    store.create_run(run_id, "v1", metadata={"concurrent": True})
    ledger = TaskLedger(allow_concurrent=True)
    t1 = ledger.create_task("step.first: DO define(goal = G.a) -> OUT.first")
    t2 = ledger.create_task("step.second: DO define(goal = G.b) -> OUT.second")
    ledger.start_task(t1.id)
    ledger.start_task(t2.id)
    for ev in ledger.events:
        store.append_task_event(run_id, dict(ev))
    store.close()
    return db


def _run_crashed(tmp_path, run_id="run-crashed"):
    """Create a store that started running but has no RUN_FINISHED
    (simulates a crash before completion).
    """
    db = tmp_path / "crashed.db"
    store = EventStore(str(db))
    store.create_run(run_id, "v1", metadata={})
    ledger = TaskLedger(allow_concurrent=False)
    t1 = ledger.create_task("step.one: DO define(value = G.goal) -> E.result")
    ledger.start_task(t1.id)
    for ev in ledger.events:
        store.append_task_event(run_id, dict(ev))
    store.close()
    return db


# -- (1) failed run shows failed marker + error -------------------------------

def test_status_failed_run_shows_failed_marker_and_error(tmp_path, capsys):
    db = _run_failed(tmp_path)
    rc, out, err = _status(capsys, db, run_id="run-fail")
    assert rc == 0
    assert "failed" in out.lower()
    assert "kaput" in out.lower()


def test_status_failed_run_json_carries_error(tmp_path, capsys):
    db = _run_failed(tmp_path)
    rc, out, err = _status(capsys, db, run_id="run-fail", json_=True)
    assert rc == 0
    data = json.loads(out)
    assert data["status"] == "failed"
    assert data["error"] is not None
    assert "kaput" in data["error"].lower()


# -- (2) concurrent run lists every IN_PROGRESS task --------------------------

def test_status_concurrent_run_lists_all_in_progress_tasks(tmp_path, capsys):
    db = _run_concurrent(tmp_path)
    rc, out, err = _status(capsys, db, run_id="run-concurrent")
    assert rc == 0
    assert "step.first" in out
    assert "step.second" in out
    assert "in progress" in out.lower()


def test_status_concurrent_run_json_lists_all_in_progress(tmp_path, capsys):
    db = _run_concurrent(tmp_path)
    rc, out, err = _status(capsys, db, run_id="run-concurrent", json_=True)
    assert rc == 0
    data = json.loads(out)
    assert data["status"] == "running"
    assert len(data["in_progress_tasks"]) == 2
    ids = {t["id"] for t in data["in_progress_tasks"]}
    assert "task-1" in ids
    assert "task-2" in ids


# -- (3) crashed (non-terminal) run renders distinctly from finished ----------

def test_status_crashed_run_shows_running_not_succeeded(tmp_path, capsys):
    db = _run_crashed(tmp_path)
    rc, out, err = _status(capsys, db, run_id="run-crashed")
    assert rc == 0
    assert "running" in out.lower()
    assert "succeeded" not in out.lower()


def test_status_crashed_run_hints_resume(tmp_path, capsys):
    db = _run_crashed(tmp_path)
    rc, out, err = _status(capsys, db, run_id="run-crashed")
    assert rc == 0
    assert "resume" in out.lower()


def test_status_crashed_run_json_is_running_with_resume_hint(tmp_path, capsys):
    db = _run_crashed(tmp_path)
    rc, out, err = _status(capsys, db, run_id="run-crashed", json_=True)
    assert rc == 0
    data = json.loads(out)
    assert data["status"] == "running"
    assert data["hint"] == "tahoe resume"
    assert data["error"] is None


# -- (4) succeeded run still works (regression) -------------------------------

def test_status_succeeded_run_shows_succeeded(tmp_path, capsys):
    db, rc, _, _ = _run(tmp_path, capsys)
    assert rc == 0
    rc, out, err = _status(capsys, db)
    assert rc == 0
    assert "succeeded" in out.lower()


def test_status_succeeded_run_json_has_status_succeeded(tmp_path, capsys):
    db, rc, _, _ = _run(tmp_path, capsys)
    assert rc == 0
    rc, out, err = _status(capsys, db, json_=True)
    assert rc == 0
    data = json.loads(out)
    assert data["status"] == "succeeded"
    assert data["error"] is None
    assert data["hint"] is None


# -- (5) profile() returns in_progress_tasks list -----------------------------

def test_profile_returns_in_progress_tasks_list():
    ledger = TaskLedger(allow_concurrent=True)
    t1 = ledger.create_task("task one")
    t2 = ledger.create_task("task two")
    ledger.start_task(t1.id)
    ledger.start_task(t2.id)
    profile = ledger.profile()
    assert profile["in_progress_tasks"] == ["task-1", "task-2"]
    assert profile["current_task"] == "task-1"


def test_profile_in_progress_tasks_empty_when_all_done():
    ledger = TaskLedger()
    t1 = ledger.create_task("task one")
    ledger.start_task(t1.id)
    ledger.complete_task(t1.id, "done")
    profile = ledger.profile()
    assert profile["in_progress_tasks"] == []
    assert profile["current_task"] is None
