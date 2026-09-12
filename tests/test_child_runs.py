"""Tests specifying isolated CALL child runs and parent output adoption (#20).

Contract under test: a ``CALL protocol.name(...)`` executes the protocol
as an ISOLATED child run in the same EventStore — deterministic id
``"<parent_run_id>:<invocation_id>"``, ``child_of``/``call`` lineage in
RUN_STARTED, its own task ledger, and a state namespace seeded only from
the explicitly passed CALL arguments (parent values are invisible).  A
succeeded child's RETURN refs are adopted onto the CALL targets by
exact-string mapping, recorded as CHILD_ADOPTED in the same atomic batch
as the CALL's SUCCEEDED delta; any non-succeeded child terminal fails the
parent through the standard atomic path with no adoption.  Parent and
child replay identically after reopen and audit clean.  A parent crash
during a CALL resumes by adopting an already-terminal child without
re-executing it, re-driving a non-terminal child, or starting a missing
one — and never duplicates an adoption.
"""

from __future__ import annotations

import sqlite3

import pytest

from tikhon.audit import audit_run
from tikhon.resume import resume_run
from tikhon.runtime import EventStore, EventType
from tikhon.runtime.coordinator import (
    CrashInterrupt,
    DeterministicWorker,
    SequentialCoordinator,
)
from tikhon.syntax import parse_program, validate_program


ISOLATION_PROTOCOL = """\
PROGRAM leaf VERSION 1.0

INPUT
    G.request = "declared-literal"
    C.scope = "declared-scope"

step.frame: DO define(request = G.request) -> G.plan
step.locate: DO search(query = G.plan, scope = C.scope) -> E.context

RETURN G.plan, E.context
"""

HANDLERS = {
    "define": lambda request: {"echo": request},
    "search": lambda query, scope: [f"hit:{query}:{scope}"],
    "fetch": lambda resource_refs: {"sources": resource_refs},
    "extract": lambda artifact, schema: {"analysis": artifact, "schema": schema},
    "summarize": lambda source_refs, budget: f"brief of {source_refs} ({budget})",
}


def make_worker(**overrides):
    handlers = dict(HANDLERS)
    handlers.update(overrides)
    return DeterministicWorker(handlers=handlers)


class CountingWorker(DeterministicWorker):
    """DeterministicWorker that records how often each command ran."""

    def __init__(self, handlers):
        super().__init__(handlers)
        self.calls: dict[str, int] = {}

    def execute(self, command, resolved_kwargs):
        self.calls[command] = self.calls.get(command, 0) + 1
        return super().execute(command, resolved_kwargs)


def write_protocol(root, name, text):
    protocols = root / "protocols"
    protocols.mkdir(exist_ok=True)
    (protocols / f"{name}.think").write_text(text, encoding="utf-8")
    return protocols


CALLER = """\
PROGRAM caller VERSION 1.0

INPUT
    G.request = "parent-secret"
    G.passed = "passed-value"

step.ask: DO define(request = G.request) -> G.probe
CALL protocol.leaf(request = G.passed, scope = "given-scope") -> G.plan
step.wrap: DO summarize(source_refs = G.plan, budget = 10) -> OUT.brief

RETURN G.plan, OUT.brief
"""


def run_caller(store, protocols, run_id, worker=None, crash_hook=None):
    coordinator = SequentialCoordinator(
        store=store,
        worker=worker or make_worker(),
        protocols_dir=protocols,
    )
    return coordinator.execute(
        parse_program(CALLER), run_id=run_id, crash_hook=crash_hook
    )


# -- isolation ---------------------------------------------------------


def test_child_sees_only_passed_arguments_not_parent_values(tmp_path):
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    with EventStore(tmp_path / "events.db") as store:
        result = run_caller(store, protocols, "run-iso")
        assert result["status"] == "succeeded"

        child = store.project_state("run-iso:inv-2")
        # The child bound the EXPLICITLY passed argument, not the
        # protocol file's declared literal and not the parent's nodes.
        assert child["nodes"]["G.plan"]["value"] == {"echo": "passed-value"}
        assert child["nodes"]["E.context"]["value"] == [
            "hit:" + str({"echo": "passed-value"}) + ":given-scope"
        ]
        # Parent values (G.probe carries "parent-secret") never leaked in.
        assert "G.probe" not in child["nodes"]
        assert "parent-secret" not in str(child["nodes"])
        # The child's own projected namespace is exactly its steps' targets.
        assert set(child["nodes"]) == {"G.plan", "E.context"}

        parent = store.project_state("run-iso")
        # ...and the parent only received the adopted target.
        assert set(parent["nodes"]) == {
            "G.probe", "G.plan", "OUT.brief",
        }
        assert "E.context" not in parent["nodes"]


def test_child_events_and_ledger_are_outside_the_parent_namespace(tmp_path):
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    with EventStore(tmp_path / "events.db") as store:
        run_caller(store, protocols, "run-iso")

        parent_events = store.events("run-iso")
        child_events = store.events("run-iso:inv-2")
        # Parent history never contains the child's step invocations.
        parent_instructions = {
            event.instruction_id for event in parent_events
            if event.instruction_id
        }
        assert parent_instructions == {
            "step.ask", "protocol.leaf", "step.wrap",
        }
        child_instructions = {
            event.instruction_id for event in child_events
            if event.instruction_id
        }
        assert child_instructions == {"step.frame", "step.locate"}
        # Parent ledger: ask, the CALL, wrap.  Child ledger: its own steps.
        parent_texts = [
            task.text for task in store.task_ledger("run-iso").tasks.values()
        ]
        assert parent_texts == [
            "step.ask: DO define",
            "CALL protocol.leaf",
            "step.wrap: DO summarize",
        ]
        child_texts = [
            task.text
            for task in store.task_ledger("run-iso:inv-2").tasks.values()
        ]
        assert child_texts == ["step.frame: DO define", "step.locate: DO search"]


def test_child_run_started_marks_child_of_and_call(tmp_path):
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    with EventStore(tmp_path / "events.db") as store:
        run_caller(store, protocols, "run-iso")
        started = store.events("run-iso:inv-2")[0]
        assert started.event_type is EventType.RUN_STARTED
        assert started.payload["child_of"] == "run-iso"
        assert started.payload["call"] == "protocol.leaf"
        assert started.payload["program"] == "leaf"
        run_row = store.run("run-iso:inv-2")
        assert run_row["metadata"]["child_of"] == "run-iso"
        assert run_row["metadata"]["call"] == "protocol.leaf"


# -- adoption ----------------------------------------------------------


def test_child_adopted_event_precedes_the_call_succeeded_delta(tmp_path):
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    with EventStore(tmp_path / "events.db") as store:
        run_caller(store, protocols, "run-iso")

        history = store.events("run-iso")
        adoptions = [
            event for event in history
            if event.event_type is EventType.CHILD_ADOPTED
        ]
        assert len(adoptions) == 1
        adoption = adoptions[0]
        assert adoption.invocation_id == "inv-2"
        assert adoption.task_id
        assert adoption.payload["child_run_id"] == "run-iso:inv-2"
        assert adoption.payload["adopted"] == {"G.plan": "G.plan"}
        assert adoption.payload["child_status"] == "succeeded"

        succeeded = next(
            event for event in history
            if event.event_type is EventType.SUCCEEDED
            and event.invocation_id == "inv-2"
        )
        assert adoption.seq < succeeded.seq
        # The adopted value commits exactly in the CALL's SUCCEEDED delta.
        assert succeeded.payload["delta"]["add_nodes"] == [
            {"id": "G.plan", "value": {"echo": "passed-value"}}
        ]


def test_multiple_calls_map_returns_to_their_own_targets(tmp_path):
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    program = parse_program("""\
PROGRAM twice VERSION 1.0

INPUT
    G.request = "x"

step.ask: DO define(request = G.request) -> G.probe
CALL protocol.leaf(request = "first", scope = "one") -> G.plan
CALL protocol.leaf(request = "second", scope = "two") -> E.context

RETURN G.plan, E.context
""")
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store=store, worker=make_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-twice")
        assert result["status"] == "succeeded"
        assert result["outputs"]["G.plan"] == {"echo": "first"}
        assert result["outputs"]["E.context"] == [
            "hit:" + str({"echo": "second"}) + ":two"
        ]
        # Two separate child runs; the second child never saw the first's
        # values despite identical local names.
        first = store.project_state("run-twice:inv-2")
        second = store.project_state("run-twice:inv-3")
        assert first["nodes"]["E.context"]["value"] == [
            "hit:" + str({"echo": "first"}) + ":one"
        ]
        assert second["nodes"]["G.plan"]["value"] == {"echo": "second"}
        adoptions = [
            event for event in store.events("run-twice")
            if event.event_type is EventType.CHILD_ADOPTED
        ]
        assert [event.payload["child_run_id"] for event in adoptions] == [
            "run-twice:inv-2", "run-twice:inv-3",
        ]
        assert [event.payload["adopted"] for event in adoptions] == [
            {"G.plan": "G.plan"}, {"E.context": "E.context"},
        ]


def test_returning_an_input_binding_without_a_step_target_adopts_it(tmp_path):
    # A protocol may RETURN an INPUT ref directly; the adoption reads the
    # child's seeded binding even though no step targeted it.
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL.replace(
        "RETURN G.plan, E.context", "RETURN G.request, E.context",
    ))
    program = parse_program("""\
PROGRAM passthrough VERSION 1.0

INPUT
    G.origin = "x"

step.ask: DO define(request = G.origin) -> G.probe
CALL protocol.leaf(request = G.probe, scope = "s") -> G.request

RETURN G.request
""")
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store=store, worker=make_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-pass")
        assert result["status"] == "succeeded"
        assert result["outputs"]["G.request"] == {"echo": "x"}


# -- failure propagation -------------------------------------------------


def test_failing_child_fails_parent_atomically_with_no_adoption(tmp_path):
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)

    def broken_search(query, scope):
        raise RuntimeError("child boom")

    with EventStore(tmp_path / "events.db") as store:
        result = run_caller(
            store, protocols, "run-fail", worker=make_worker(search=broken_search)
        )
        assert result["status"] == "failed"
        assert "child boom" in result["error"]
        assert result["outputs"] == {}

        # Child terminal-failed in its own history.
        child_history = store.events("run-fail:inv-2")
        assert child_history[-1].event_type is EventType.RUN_FINISHED
        assert child_history[-1].payload["status"] == "failed"

        parent_history = store.events("run-fail")
        assert parent_history[-1].payload["status"] == "failed"
        failed = [
            event for event in parent_history
            if event.event_type is EventType.FAILED
        ]
        assert len(failed) == 1
        assert failed[0].invocation_id == "inv-2"
        assert failed[0].instruction_id == "protocol.leaf"
        assert not any(
            event.event_type is EventType.CHILD_ADOPTED
            for event in parent_history
        )
        assert not any(
            event.event_type is EventType.SUCCEEDED
            and event.invocation_id == "inv-2"
            for event in parent_history
        )
        ledger = store.task_ledger("run-fail")
        profile = ledger.profile()
        assert profile["counts"]["completed"] == 1
        assert profile["counts"]["cancelled"] == 2
        assert store.project_state("run-fail")["nodes"].keys() == {"G.probe"}


def test_blocked_child_fails_parent_and_stays_terminal_blocked(tmp_path):
    protocols = write_protocol(
        tmp_path,
        "leaf",
        ISOLATION_PROTOCOL.replace(
            "step.locate: DO search(query = G.plan, scope = C.scope) -> E.context",
            "step.locate: DO search(query = G.plan, scope = C.scope) -> E.context\n"
            'IF C.scope == "given-scope" STOP blocked(E.context)',
        ),
    )
    with EventStore(tmp_path / "events.db") as store:
        result = run_caller(store, protocols, "run-blocked")
        assert result["status"] == "failed"
        assert "blocked" in result["error"]
        child_history = store.events("run-blocked:inv-2")
        assert child_history[-1].payload["status"] == "blocked"
        assert not any(
            event.event_type is EventType.CHILD_ADOPTED
            for event in store.events("run-blocked")
        )


# -- replay / audit ------------------------------------------------------


def test_parent_and_child_replay_identically_after_reopen(tmp_path):
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    db = tmp_path / "events.db"
    with EventStore(db) as store:
        result = run_caller(store, protocols, "run-iso")
        assert result["status"] == "succeeded"
        before = {
            run_id: (
                store.project_state(run_id),
                store.task_ledger(run_id).tasks,
                store.events(run_id),
            )
            for run_id in ("run-iso", "run-iso:inv-2")
        }

    reopened = EventStore(db)
    try:
        for run_id, (state, tasks, events) in before.items():
            assert reopened.project_state(run_id) == state
            assert reopened.task_ledger(run_id).tasks == tasks
            assert reopened.events(run_id) == events
    finally:
        reopened.close()


def test_parent_and_child_runs_audit_clean(tmp_path):
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    with EventStore(tmp_path / "events.db") as store:
        run_caller(store, protocols, "run-iso")
        for run_id in ("run-iso", "run-iso:inv-2"):
            report = audit_run(store, run_id)
            assert report.ok, (
                run_id,
                [finding.to_dict() for finding in report.findings],
            )


def test_failed_tree_audits_clean_parent_and_child(tmp_path):
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)

    def broken_search(query, scope):
        raise RuntimeError("child boom")

    with EventStore(tmp_path / "events.db") as store:
        run_caller(
            store, protocols, "run-fail", worker=make_worker(search=broken_search)
        )
        for run_id in ("run-fail", "run-fail:inv-2"):
            report = audit_run(store, run_id)
            assert report.ok, (
                run_id,
                [finding.to_dict() for finding in report.findings],
            )


# -- resume across a CALL ------------------------------------------------


def crash_at(target_idx):
    def hook(idx):
        if idx == target_idx:
            raise CrashInterrupt(f"simulated crash at plan index {idx}")

    return hook


def test_crash_after_child_completion_resumes_by_adoption_only(tmp_path):
    # Crash window: the child is fully terminal but the parent has not
    # adopted yet (hook fires right before the CALL's VALIDATION_PASSED).
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    db = tmp_path / "events.db"
    with EventStore(db) as store:
        with pytest.raises(CrashInterrupt):
            run_caller(store, protocols, "run-resume", crash_hook=crash_at(1))
        # The child is terminal-succeeded; the parent is mid-CALL.
        child_history = store.events("run-resume:inv-2")
        assert child_history[-1].payload["status"] == "succeeded"
        assert not any(
            event.event_type is EventType.CHILD_ADOPTED
            for event in store.events("run-resume")
        )

    with EventStore(db) as store:
        worker = CountingWorker(dict(HANDLERS))
        result = resume_run(
            store, worker, "run-resume", parse_program(CALLER),
            protocols_dir=protocols,
        )
        assert result["status"] == "succeeded"
        # The terminal child was adopted WITHOUT re-executing any of its
        # steps; only the parent's trailing step ran.
        assert worker.calls == {"summarize": 1}
        assert result["outputs"]["G.plan"] == {"echo": "passed-value"}
        adoptions = [
            event for event in store.events("run-resume")
            if event.event_type is EventType.CHILD_ADOPTED
        ]
        assert len(adoptions) == 1
        report = audit_run(store, "run-resume")
        assert report.ok, [f.to_dict() for f in report.findings]
        report = audit_run(store, "run-resume:inv-2")
        assert report.ok, [f.to_dict() for f in report.findings]


def test_crash_during_child_execution_rerives_nonterminal_child(tmp_path):
    # Crash window: the child run exists but is non-terminal (its tail is
    # rewound to just after step.frame committed).  Resume re-drives the
    # child from its first non-terminal step (at-least-once).
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    db = tmp_path / "events.db"
    child_id = "run-resume2:inv-2"
    with EventStore(db) as store:
        with pytest.raises(CrashInterrupt):
            run_caller(store, protocols, "run-resume2", crash_hook=crash_at(1))
        # Rewind the child to just after step.locate's VALIDATION_PASSED:
        # step.locate's SUCCEEDED batch and RUN_FINISHED are removed,
        # leaving a non-terminal child whose in-flight step.locate task is
        # IN_PROGRESS while step.frame is already terminal.
        child_events = store.events(child_id)
        locate_validation_seq = max(
            event.seq for event in child_events
            if event.event_type is EventType.VALIDATION_PASSED
        )
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "DELETE FROM events WHERE run_id = ? AND seq > ?",
                (child_id, locate_validation_seq),
            )
            conn.commit()
        finally:
            conn.close()
        rewound = store.events(child_id)
        assert rewound[-1].event_type is EventType.VALIDATION_PASSED
        assert not any(
            event.event_type is EventType.RUN_FINISHED
            for event in rewound
        )

    with EventStore(db) as store:
        worker = CountingWorker(dict(HANDLERS))
        result = resume_run(
            store, worker, "run-resume2", parse_program(CALLER),
            protocols_dir=protocols,
        )
        assert result["status"] == "succeeded"
        # The non-terminal child was re-driven from its first
        # non-terminal step (step.locate at-least-once); the terminal
        # step.frame was NOT re-executed; the parent's trailing step ran.
        assert worker.calls == {"search": 1, "summarize": 1}
        assert result["outputs"]["G.plan"] == {"echo": "passed-value"}
        for run_id in ("run-resume2", child_id):
            report = audit_run(store, run_id)
            assert report.ok, (
                run_id,
                [finding.to_dict() for finding in report.findings],
            )


def test_crash_before_child_creation_starts_the_child_fresh(tmp_path):
    # Crash window: the parent dispatched the CALL but died before the
    # child run was created.  Resume starts the child from scratch.
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    db = tmp_path / "events.db"
    child_id = "run-resume3:inv-2"
    with EventStore(db) as store:
        with pytest.raises(CrashInterrupt):
            run_caller(store, protocols, "run-resume3", crash_hook=crash_at(1))
        conn = sqlite3.connect(db)
        try:
            conn.execute("DELETE FROM events WHERE run_id = ?", (child_id,))
            conn.execute("DELETE FROM runs WHERE run_id = ?", (child_id,))
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(KeyError):
            store.run(child_id)

    with EventStore(db) as store:
        worker = CountingWorker(dict(HANDLERS))
        result = resume_run(
            store, worker, "run-resume3", parse_program(CALLER),
            protocols_dir=protocols,
        )
        assert result["status"] == "succeeded"
        # The child ran from scratch exactly once.
        assert worker.calls == {
            "define": 1, "search": 1, "summarize": 1,
        }
        assert result["outputs"]["G.plan"] == {"echo": "passed-value"}
        started = store.events(child_id)[0]
        assert started.payload["child_of"] == "run-resume3"
        report = audit_run(store, "run-resume3")
        assert report.ok, [f.to_dict() for f in report.findings]


def test_crash_after_adoption_does_not_duplicate_outputs(tmp_path):
    # Crash window: the parent already adopted (CHILD_ADOPTED + the
    # CALL's SUCCEEDED committed) but died before finishing the run.
    # Resume skips the CALL entry entirely — no second adoption.
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)
    with EventStore(tmp_path / "events.db") as store:
        with pytest.raises(CrashInterrupt):
            run_caller(store, protocols, "run-resume4", crash_hook=crash_at(2))
        history = store.events("run-resume4")
        assert any(
            event.event_type is EventType.CHILD_ADOPTED
            for event in history
        )
        assert not any(
            event.event_type is EventType.RUN_FINISHED
            for event in history
        )

        worker = CountingWorker(dict(HANDLERS))
        result = resume_run(
            store, worker, "run-resume4", parse_program(CALLER),
            protocols_dir=protocols,
        )
        assert result["status"] == "succeeded"
        adoptions = [
            event for event in store.events("run-resume4")
            if event.event_type is EventType.CHILD_ADOPTED
        ]
        assert len(adoptions) == 1
        call_succeeded = [
            event for event in store.events("run-resume4")
            if event.event_type is EventType.SUCCEEDED
            and event.invocation_id == "inv-2"
        ]
        assert len(call_succeeded) == 1
        assert result["outputs"]["G.plan"] == {"echo": "passed-value"}
        report = audit_run(store, "run-resume4")
        assert report.ok, [f.to_dict() for f in report.findings]


def test_failed_child_then_resume_stays_failed_and_never_adopts(tmp_path):
    # A crashed-then-resumed parent whose child fails on the re-drive
    # fails atomically; the terminal-failed child is not re-executed.
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL)

    def broken_search(query, scope):
        raise RuntimeError("child boom")

    with EventStore(tmp_path / "events.db") as store:
        result = run_caller(
            store, protocols, "run-fail2", worker=make_worker(search=broken_search)
        )
        assert result["status"] == "failed"

        worker = CountingWorker(dict(HANDLERS))
        result = resume_run(
            store, worker, "run-fail2", parse_program(CALLER),
            protocols_dir=protocols,
        )
        assert result["status"] == "failed"
        assert "blocked" not in result["error"]
        assert "child boom" in result["error"]
        # The already-terminal child was not re-executed.
        assert "summarize" not in worker.calls
        assert "define" not in worker.calls
        assert not any(
            event.event_type is EventType.CHILD_ADOPTED
            for event in store.events("run-fail2")
        )


# -- nesting and depth bound --------------------------------------------


def test_two_level_nested_calls_chain_child_run_ids(tmp_path):
    protocols = write_protocol(tmp_path, "leaf", ISOLATION_PROTOCOL.replace(
        "step.locate: DO search(query = G.plan, scope = C.scope) -> E.context",
        "step.locate: DO search(query = G.plan, scope = C.scope) -> E.context\n"
        'CALL protocol.inner(request = G.request, scope = "deep") -> F.result',
    ))
    protocols = write_protocol(tmp_path, "inner", """\
PROGRAM inner VERSION 1.0

INPUT
    G.request = "x"
    C.scope = "y"

step.deep: DO define(request = G.request) -> F.result

RETURN F.result
""")
    program = parse_program("""\
PROGRAM top VERSION 1.0

INPUT
    G.request = "top"

step.ask: DO define(request = G.request) -> G.probe
CALL protocol.leaf(request = G.probe, scope = "s") -> G.plan

RETURN G.plan
""")
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store=store, worker=make_worker(), protocols_dir=protocols
        ).execute(program, run_id="run-nest")
        assert result["status"] == "succeeded"
        grandchild_id = "run-nest:inv-2:inv-3"
        grandchild = store.project_state(grandchild_id)
        # The grandchild's INPUT came from the leaf child's G.request,
        # which the leaf bound from its CALL argument (G.probe's value).
        assert grandchild["nodes"]["F.result"]["value"] == {"echo": {"echo": "top"}}
        assert grandchild["metadata"]["child_of"] == "run-nest:inv-2"
        # The parent adopts only its own CALL target; deeper nodes stay
        # inside their own runs.
        parent = store.project_state("run-nest")
        assert "I.result" not in parent["nodes"]
        for run_id in ("run-nest", "run-nest:inv-2", grandchild_id):
            report = audit_run(store, run_id)
            assert report.ok, (
                run_id,
                [finding.to_dict() for finding in report.findings],
            )


def test_nested_call_chain_beyond_depth_eight_still_rejected(tmp_path):
    # A two-level CALL executes; the static depth bound (8) still holds
    # for deeper chains, independent of the runtime mechanism.
    for depth in range(9):
        is_last = depth == 8
        steps = (
            "step.leaf: DO define(request = G.request) -> Q.leaf"
            if is_last
            else (
                f"CALL protocol.d{depth + 1}(request = G.request,"
                ' scope = C.scope) -> Q.deep'
            )
        )
        returns = "Q.leaf" if is_last else "Q.deep"
        write_protocol(
            tmp_path,
            f"d{depth}",
            (
                f"PROGRAM d{depth} VERSION 1.0\n\n"
                "INPUT\n"
                '    G.request = "x"\n'
                '    C.scope = "y"\n\n'
                f"{steps}\n\n"
                f"RETURN {returns}\n"
            ),
        )
    program = parse_program("""\
PROGRAM deep VERSION 1.0

INPUT
    G.request = "top"
    C.scope = "s"

step.ask: DO define(request = G.request) -> G.probe
CALL protocol.d0(request = G.probe, scope = "s") -> Q.deep

RETURN Q.deep
""")
    with pytest.raises(Exception, match="depth exceeds limit 8"):
        validate_program(
            program, known_commands=set(HANDLERS), protocols_dir=tmp_path / "protocols"
        )
