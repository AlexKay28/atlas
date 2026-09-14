"""Issue #94: protocol.triz — contradiction-driven ideation protocol.

Contract under test:
- protocols/triz.think loads and executes end-to-end as a CALL child
  run (acceptance #1).
- The behavior contract is checkable from the event log: the child run
  emits no hypothesize instruction before the challenge that states the
  physical contradiction (acceptance #3).
- The spectrum step consumes BOTH search branches — the discipline's
  own hits and the remote-field raid.
- KB persistence: the classified spectrum is remembered under the
  caller's kb_key and recalled by prefix.
- Parent and child audit clean.
"""

import sqlite3
from pathlib import Path

from tahoe.audit import audit_run
from tahoe.runtime import EventStore
from tahoe.runtime.coordinator import (
    DeterministicWorker,
    SequentialCoordinator,
)
from tahoe.syntax import parse_program

REPO = Path(__file__).resolve().parents[1]
PROTOCOLS = REPO / "protocols"

CALLER = """\
PROGRAM triz_demo VERSION 1.0

INPUT
    G.task = "an agent retries a failing tool call with identical arguments forever"
    C.discipline = "AI agent harness engineering"
    C.remote = "chemical process control"
    C.kb_key = "triz/test-harness"

CALL protocol.triz(task = G.task, done = "every candidate classified as pattern, compromise or antipattern; zero unclassified", discipline = C.discipline, remote = C.remote, ifr_question = "state the IFR: the function performs itself with what is on site; name the obstacle", moves_question = "propose concrete moves that remove the stated contradiction; use both evidence branches; name the principle", criteria = "pattern removes the contradiction; compromise softens it; antipattern widens it; prefer higher ideality", kb_key = C.kb_key) -> V.contradiction, E.spectrum, V.matrix, E.ordering, K.spectrum, ART.report
step.recall: DO recall(query = "triz/") -> OUT.prior

RETURN V.contradiction, E.spectrum, V.matrix, ART.report, OUT.prior
"""

REMEMBERED: dict = {}


def _remember(key, value):
    REMEMBERED[key] = value
    return {"stored": key}


HANDLERS = {
    "define": lambda request: {"plan": f"framed: {request}"},
    "summarize": lambda source_refs, budget: f"claim ({budget} tokens): {source_refs}",
    "challenge": lambda claim, evidence: {
        "counterevidence": [f"counter to {claim}"],
        "contradiction": "the retry must happen (to recover) and must not happen (identical arguments cannot succeed)",
    },
    "hypothesize": lambda question, evidence: [
        f"move[{i}] under {question}: from {len(evidence)} evidence streams"
        for i in range(3)
    ],
    "search": lambda query, scope: [f"hit[{scope}]: {query}"],
    "compare": lambda options, criteria: {
        "matrix": options,
        "criteria": criteria,
        "classes": ["pattern", "compromise", "antipattern"],
    },
    "rank": lambda options, criteria: [f"ranked: {option}" for option in options],
    "verify": lambda goal, evidence: "resolved",
    "remember": _remember,
    "recall": lambda query: [f"kb-hit: {query}"],
    "check": lambda artifact, predicate: "pass",
    "report": lambda committed_refs, format: f"report[{format}]: {committed_refs}",
}


def make_worker(**overrides):
    handlers = dict(HANDLERS)
    handlers.update(overrides)
    return DeterministicWorker(handlers=handlers)


def run_caller(tmp_path, run_id="run-triz"):
    REMEMBERED.clear()
    with EventStore(tmp_path / "events.db") as store:
        coordinator = SequentialCoordinator(
            store=store,
            worker=make_worker(),
            protocols_dir=PROTOCOLS,
        )
        result = coordinator.execute(parse_program(CALLER), run_id=run_id)
    return result, tmp_path / "events.db"


def child_run_ids(db_path, parent="run-triz"):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT run_id FROM events WHERE run_id LIKE ?", (f"{parent}:%",)
        ).fetchall()
    finally:
        conn.close()
    return sorted(row[0] for row in rows)


def first_index(events, instruction_id):
    return next(
        i for i, e in enumerate(events) if e.instruction_id == instruction_id
    )


def test_protocol_triz_executes_end_to_end(tmp_path):
    result, _ = run_caller(tmp_path)
    assert result["status"] == "succeeded"


def test_no_hypothesize_before_the_contradiction(tmp_path):
    # Acceptance #3: formulate before generating, enforced from the
    # ordered event log of the child run.
    _, db_path = run_caller(tmp_path)
    child_id = child_run_ids(db_path)[0]
    with EventStore(db_path) as store:
        events = list(store.events(child_id))
    assert first_index(events, "step.contra") < first_index(events, "step.ideal")
    assert first_index(events, "step.contra") < first_index(events, "step.moves")


def test_spectrum_consumes_discipline_and_remote_branches(tmp_path):
    _, db_path = run_caller(tmp_path)
    child_id = child_run_ids(db_path)[0]
    with EventStore(db_path) as store:
        child = store.project_state(child_id)
    known = str(child["nodes"]["E.known"]["value"])
    raids = str(child["nodes"]["E.raids"]["value"])
    assert "AI agent harness engineering" in known
    assert "chemical process control" in raids
    # The moves step saw both branches plus the contradiction.
    spectrum = str(child["nodes"]["E.spectrum"]["value"])
    assert "3 evidence streams" in spectrum


def test_kb_triz_round_trip_under_caller_key(tmp_path):
    _, db_path = run_caller(tmp_path)
    assert "triz/test-harness" in REMEMBERED
    with EventStore(db_path) as store:
        parent = store.project_state("run-triz")
    prior = parent["nodes"]["OUT.prior"]["value"]
    assert prior, "recall(triz/) must surface the stored spectrum"


def test_parent_and_child_audit_clean(tmp_path):
    _, db_path = run_caller(tmp_path)
    with EventStore(db_path) as store:
        for run_id in ("run-triz", *child_run_ids(db_path)):
            report = audit_run(store, run_id)
            assert report.ok, (
                run_id,
                [finding.to_dict() for finding in report.findings],
            )


def test_parent_adopts_all_protocol_returns(tmp_path):
    _, db_path = run_caller(tmp_path)
    with EventStore(db_path) as store:
        parent = store.project_state("run-triz")
    for ref in (
        "V.contradiction",
        "E.spectrum",
        "V.matrix",
        "E.ordering",
        "K.spectrum",
        "ART.report",
        "OUT.prior",
    ):
        assert ref in parent["nodes"], ref
