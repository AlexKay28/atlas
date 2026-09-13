"""Tests for the history() temporal query operator (issue #81).

Covers parsing of ``history(<ref>)`` in IF conditions and DONE predicates,
evaluation against the event store, empty history, and multiple revisions.
"""

import os
import tempfile

import pytest

from tahoe.runtime.events import EventStore, EventType
from tahoe.runtime.helpers import evaluate_condition, evaluate_done_predicate
from tahoe.state import StateDelta
from tahoe.syntax import DonePredicate, parse_condition


# -- Parser tests --------------------------------------------------------

def test_history_parses_as_condition_node():
    ast = parse_condition("history(E.result)")
    assert ast == ("history", "E.result")


def test_history_with_count_parses():
    ast = parse_condition("count(history(E.tests)) >= 3")
    assert ast == ("count", ("history", "E.tests"), ">=", 3)


def test_history_combined_with_and_parses():
    ast = parse_condition('history(V.flag) AND V.status == "go"')
    assert ast == (
        "and",
        ("history", "V.flag"),
        ("eq", "V.status", "go"),
    )


def test_history_combined_with_or_parses():
    ast = parse_condition('V.flag == "go" OR history(E.result)')
    assert ast == (
        "or",
        ("eq", "V.flag", "go"),
        ("history", "E.result"),
    )


def test_history_with_not_parses():
    ast = parse_condition("NOT history(V.flag)")
    assert ast == ("not", ("history", "V.flag"))


def test_history_in_done_predicate():
    from tahoe.syntax.parser import _parse_done_expression
    pred = _parse_done_expression("history(E.result)", 1)
    assert pred.op == "history"
    assert pred.ref == "E.result"
    assert pred.value is None


def test_history_requires_typed_ref():
    with pytest.raises(Exception):
        parse_condition("history(not_a_ref)")


def test_history_requires_closing_paren():
    with pytest.raises(Exception):
        parse_condition("history(E.result")


def test_history_empty_ref_rejected():
    with pytest.raises(Exception):
        parse_condition("history()")


# -- Event store ref_history tests ---------------------------------------

@pytest.fixture
def store():
    d = tempfile.mkdtemp()
    s = EventStore(os.path.join(d, "test.db"))
    s.create_run("run-1", "v1")
    yield s
    s.close()


def test_ref_history_empty_for_unknown_ref(store):
    assert store.ref_history("run-1", "V.missing") == []


def test_ref_history_single_add(store):
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-1",
        payload={"delta": StateDelta(add_nodes=[{"id": "V.flag", "value": "go"}]).to_dict()},
    )
    hist = store.ref_history("run-1", "V.flag")
    assert len(hist) == 1
    assert hist[0]["action"] == "add"
    assert hist[0]["value"] == "go"
    assert hist[0]["invocation_id"] == "inv-1"


def test_ref_history_multiple_updates(store):
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-1",
        payload={"delta": StateDelta(add_nodes=[{"id": "V.flag", "value": "go"}]).to_dict()},
    )
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-2",
        payload={"delta": StateDelta(revise_nodes=[{"id": "V.flag", "value": "slow"}]).to_dict()},
    )
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-3",
        payload={"delta": StateDelta(revise_nodes=[{"id": "V.flag", "value": "stop"}]).to_dict()},
    )
    hist = store.ref_history("run-1", "V.flag")
    assert len(hist) == 3
    assert hist[0]["action"] == "add"
    assert hist[0]["value"] == "go"
    assert hist[1]["action"] == "revise"
    assert hist[1]["value"] == "slow"
    assert hist[2]["action"] == "revise"
    assert hist[2]["value"] == "stop"
    assert [r["invocation_id"] for r in hist] == ["inv-1", "inv-2", "inv-3"]


def test_ref_history_with_retire(store):
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-1",
        payload={"delta": StateDelta(add_nodes=[{"id": "V.flag", "value": "go"}]).to_dict()},
    )
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-2",
        payload={"delta": StateDelta(retire_nodes=["V.flag"]).to_dict()},
    )
    hist = store.ref_history("run-1", "V.flag")
    assert len(hist) == 2
    assert hist[0]["action"] == "add"
    assert hist[1]["action"] == "retire"
    assert hist[1]["value"] is None


def test_ref_history_only_includes_named_ref(store):
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-1",
        payload={"delta": StateDelta(add_nodes=[
            {"id": "V.flag", "value": "go"},
            {"id": "V.other", "value": 42},
        ]).to_dict()},
    )
    hist = store.ref_history("run-1", "V.flag")
    assert len(hist) == 1
    assert hist[0]["value"] == "go"


def test_ref_history_skips_non_succeeded_events(store):
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-1",
        payload={"delta": StateDelta(add_nodes=[{"id": "V.flag", "value": "go"}]).to_dict()},
    )
    store.append(
        "run-1", EventType.FAILED, invocation_id="inv-1",
        payload={"error": "something"},
    )
    hist = store.ref_history("run-1", "V.flag")
    assert len(hist) == 1


def test_ref_history_seq_ordering(store):
    for i in range(5):
        store.append(
            "run-1", EventType.SUCCEEDED, invocation_id=f"inv-{i+1}",
            payload={"delta": StateDelta(revise_nodes=[{"id": "V.counter", "value": i}]).to_dict()},
        )
    hist = store.ref_history("run-1", "V.counter")
    assert [r["seq"] for r in hist] == [0, 1, 2, 3, 4]
    assert [r["value"] for r in hist] == [0, 1, 2, 3, 4]


# -- Evaluator tests -----------------------------------------------------

def _make_history_fn(store, run_id):
    def history_fn(ref):
        return store.ref_history(run_id, ref)
    return history_fn


def test_evaluate_history_alone_true(store):
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-1",
        payload={"delta": StateDelta(add_nodes=[{"id": "V.flag", "value": "go"}]).to_dict()},
    )
    history_fn = _make_history_fn(store, "run-1")
    assert evaluate_condition("history(V.flag)", {}, history_fn=history_fn) is True


def test_evaluate_count_history_gte(store):
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-1",
        payload={"delta": StateDelta(add_nodes=[{"id": "V.flag", "value": "go"}]).to_dict()},
    )
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-2",
        payload={"delta": StateDelta(revise_nodes=[{"id": "V.flag", "value": "stop"}]).to_dict()},
    )
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-3",
        payload={"delta": StateDelta(revise_nodes=[{"id": "V.flag", "value": "go2"}]).to_dict()},
    )
    history_fn = _make_history_fn(store, "run-1")
    assert evaluate_condition("count(history(V.flag)) >= 3", {}, history_fn=history_fn) is True
    assert evaluate_condition("count(history(V.flag)) >= 4", {}, history_fn=history_fn) is False


def test_evaluate_count_history_empty(store):
    history_fn = _make_history_fn(store, "run-1")
    assert evaluate_condition("count(history(V.missing)) >= 1", {}, history_fn=history_fn) is False
    assert evaluate_condition("count(history(V.missing)) == 0", {}, history_fn=history_fn) is True


def test_evaluate_history_combined_with_condition(store):
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-1",
        payload={"delta": StateDelta(add_nodes=[{"id": "V.flag", "value": "go"}]).to_dict()},
    )
    store.append(
        "run-1", EventType.SUCCEEDED, invocation_id="inv-2",
        payload={"delta": StateDelta(add_nodes=[{"id": "V.status", "value": "ok"}]).to_dict()},
    )
    history_fn = _make_history_fn(store, "run-1")
    result = evaluate_condition(
        'history(V.flag) AND V.status == "ok"',
        {"V.status": "ok"},
        history_fn=history_fn,
    )
    assert result is True


def test_evaluate_history_without_callback_raises():
    with pytest.raises(ValueError, match="history.*event-store"):
        evaluate_condition("history(V.flag)", {})


def test_evaluate_count_history_without_callback_raises():
    with pytest.raises(ValueError, match="history.*event-store"):
        evaluate_condition("count(history(V.flag)) >= 1", {})


def test_evaluate_history_in_done_predicate_raises_without_context():
    pred = DonePredicate("history", "E.result", None, 1)
    with pytest.raises(ValueError, match="history.*event-store"):
        evaluate_done_predicate(pred, {})
