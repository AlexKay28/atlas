import dataclasses

import pytest

from tahoe.runtime.tasks import Task, TaskStatus, TaskLedger, TaskLedgerError


def make_task(**overrides):
    kwargs = dict(
        id="t1",
        text="do the thing",
        status=TaskStatus.PENDING,
        priority=0,
        parent=None,
        dependencies=(),
        creator="user",
        revision=1,
        evidence=(),
    )
    kwargs.update(overrides)
    return Task(**kwargs)


def test_task_status_members():
    assert {"PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED"} <= set(TaskStatus.__members__)


def test_task_is_frozen_with_expected_fields():
    task = make_task()
    names = {field.name for field in dataclasses.fields(task)}
    assert {"id", "text", "status", "priority", "parent", "dependencies", "creator", "revision", "evidence"} <= names
    with pytest.raises(dataclasses.FrozenInstanceError):
        task.text = "mutated"


def test_ledger_starts_empty():
    profile = TaskLedger().profile()
    assert profile["counts"]["total"] == 0
    assert profile["percent_complete"] == 0.0
    assert profile["current_task"] is None
    assert profile["tasks"] == {}


def test_create_task():
    ledger = TaskLedger()
    task = ledger.create_task(text="write spec", creator="agent")
    assert task.text == "write spec"
    assert task.creator == "agent"
    assert task.status is TaskStatus.PENDING
    assert task.revision == 1
    assert task.parent is None
    assert task.dependencies == ()
    assert task.evidence == ()
    assert ledger.tasks[task.id] == task


def test_revise_text_and_priority():
    ledger = TaskLedger()
    task = ledger.create_task(text="draft")
    revised = ledger.revise_task(task.id, text="final text", priority=7)
    assert revised.text == "final text"
    assert revised.priority == 7
    assert revised.revision == 2
    assert ledger.tasks[task.id] == revised


def test_reorder():
    ledger = TaskLedger()
    a = ledger.create_task(text="a")
    b = ledger.create_task(text="b")
    c = ledger.create_task(text="c")
    ordered = ledger.reorder([c.id, a.id, b.id])
    assert [t.id for t in ordered] == [c.id, a.id, b.id]
    assert ordered[0].priority <= ordered[1].priority <= ordered[2].priority


def test_split_into_children():
    ledger = TaskLedger()
    parent = ledger.create_task(text="big task")
    children = ledger.split_task(parent.id, ["part one", "part two"])
    assert [child.text for child in children] == ["part one", "part two"]
    assert all(child.parent == parent.id for child in children)
    assert all(child.status is TaskStatus.PENDING for child in children)
    assert set(ledger.tasks) == {parent.id, children[0].id, children[1].id}


def test_cancel_task():
    ledger = TaskLedger()
    task = ledger.create_task(text="obsolete")
    assert ledger.cancel_task(task.id).status is TaskStatus.CANCELLED


def test_pending_to_in_progress_to_completed_with_evidence():
    ledger = TaskLedger()
    task = ledger.create_task(text="work")
    started = ledger.start_task(task.id)
    assert started.status is TaskStatus.IN_PROGRESS
    finished = ledger.complete_task(task.id, evidence="diff sha 1234")
    assert finished.status is TaskStatus.COMPLETED
    assert "diff sha 1234" in finished.evidence
    profile = ledger.profile()
    assert profile["percent_complete"] == 100.0
    assert profile["current_task"] is None


def test_complete_without_evidence_rejected():
    ledger = TaskLedger()
    task = ledger.create_task(text="work")
    ledger.start_task(task.id)
    with pytest.raises(TaskLedgerError):
        ledger.complete_task(task.id, evidence="")


def test_second_in_progress_rejected():
    ledger = TaskLedger()
    a = ledger.create_task(text="a")
    b = ledger.create_task(text="b")
    ledger.start_task(a.id)
    with pytest.raises(TaskLedgerError):
        ledger.start_task(b.id)


def test_start_before_dependency_completes_rejected():
    ledger = TaskLedger()
    first = ledger.create_task(text="first")
    second = ledger.create_task(text="second", dependencies=(first.id,))
    with pytest.raises(TaskLedgerError):
        ledger.start_task(second.id)


def test_profile_counts_current_task_and_task_metrics():
    ledger = TaskLedger()
    a = ledger.create_task(text="a")
    b = ledger.create_task(text="b")
    ledger.start_task(a.id)
    profile = ledger.profile()
    assert profile["counts"]["total"] == 2
    assert profile["counts"]["pending"] == 1
    assert profile["counts"]["in_progress"] == 1
    assert profile["counts"]["completed"] == 0
    assert profile["counts"]["cancelled"] == 0
    assert profile["percent_complete"] == 0.0
    assert profile["current_task"] == a.id
    assert set(profile["tasks"]) == {a.id, b.id}
    for metrics in profile["tasks"].values():
        assert metrics["attempts"] == 0
        assert metrics["retries"] == 0
        assert metrics["tokens"] == 0
        assert metrics["cost"] == 0
        assert metrics["elapsed_seconds"] == 0


def test_record_invocation_updates_metrics():
    ledger = TaskLedger()
    task = ledger.create_task(text="a")
    ledger.record_invocation(task.id, tokens=100, cost=0.5, retries=1, elapsed_seconds=2.0)
    ledger.record_invocation(task.id, tokens=50, cost=0.25, retries=0, elapsed_seconds=1.5)
    metrics = ledger.profile()["tasks"][task.id]
    assert metrics["attempts"] == 2
    assert metrics["retries"] == 1
    assert metrics["tokens"] == 150
    assert metrics["cost"] == pytest.approx(0.75)
    assert metrics["elapsed_seconds"] == pytest.approx(3.5)


def test_record_invocation_unknown_task_rejected():
    ledger = TaskLedger()
    with pytest.raises(TaskLedgerError):
        ledger.record_invocation("missing", tokens=1)


def test_events_roundtrip_preserves_state():
    ledger = TaskLedger()
    a = ledger.create_task(text="a", priority=2)
    b = ledger.create_task(text="b", dependencies=(a.id,))
    ledger.revise_task(a.id, text="a revised", priority=5)
    ledger.start_task(a.id)
    ledger.record_invocation(a.id, tokens=10, cost=0.1, retries=0, elapsed_seconds=1.0)
    ledger.complete_task(a.id, evidence="done")
    ledger.start_task(b.id)
    replayed = TaskLedger.from_events(ledger.events)
    assert replayed.tasks == ledger.tasks
    assert replayed.profile() == ledger.profile()
