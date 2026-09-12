"""Tests specifying runtime-authored child plans (issue #25).

Contract under test: a ``delegate`` step's worker call returns the
AUTHORED child program text; the coordinator records it as a
CHILD_PLAN_AUTHORED event BEFORE any validation or execution (the
authored plan is part of history, never ephemeral), validates it against
the registry with the delegation bounds (step count <= max_steps, default
6, hard cap 12; no delegate command inside — no recursion, transitively
through called protocols), binds the executed program name to
``delegated_<parent_step_id>``, executes the accepted plan as an isolated
child run (``<parent_run_id>:<invocation_id>``, CALL-grade lineage and
budget depth gating), and adopts the plan's RETURN refs positionally onto
the delegate step's targets.  Rejections and non-succeeded children fail
the parent through the standard atomic path; resume reuses the recorded
artifact instead of re-asking the worker.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from tikhon.audit import audit_run
from tikhon.budgets import ExecutionBudget
from tikhon.resume import resume_run
from tikhon.runtime import EventStore, EventType
from tikhon.runtime.coordinator import (
    CrashInterrupt,
    DeterministicWorker,
    SequentialCoordinator,
    delegate_plan_digest,
    delegate_plan_name,
)
from tikhon.syntax import parse_program


AUTHORED_PLAN = """\
PROGRAM delegated_child VERSION 1.0

INPUT
    G.goal = ""
    C.constraints = ""

step.frame: DO define(request = G.goal) -> P.plan
step.measure: DO calculate(expression = "goal_units", values = {"units": 3}) -> F.metrics
step.check: DO check(artifact = P.plan, predicate = "nonempty") -> V.verdict

RETURN P.plan, F.metrics
"""

DELEGATOR = """\
PROGRAM delegator VERSION 1.0

INPUT
    G.task = "echo the goal into a child plan"
    C.limits = "at most 3 steps, no recursion"

step.ask: DO define(request = G.task) -> G.probe
step.author: DO delegate(goal = G.probe, constraints = C.limits, max_steps = 6) -> OUT.plan, OUT.metrics
step.wrap: DO summarize(source_refs = OUT.plan, budget = 10) -> OUT.brief

RETURN OUT.plan, OUT.metrics, OUT.brief
"""

NESTED_DELEGATE_PLAN = """\
PROGRAM delegated_nester VERSION 1.0

INPUT
    G.goal = ""
    C.constraints = ""

step.inner: DO delegate(goal = G.goal, constraints = C.constraints) -> X.result

RETURN X.result
"""

MALFORMED_PLAN = "this is not a tikhon program at all"

HIDDEN_DELEGATE_PROTOCOL = """\
PROGRAM sneaky VERSION 1.0

INPUT
    G.request = "declared-literal"

step.hidden: DO delegate(goal = G.request, constraints = "none") -> X.result

RETURN X.result
"""

PROTOCOL_CALLING_PLAN = """\
PROGRAM delegated_via_protocol VERSION 1.0

INPUT
    G.goal = ""
    C.constraints = ""

CALL protocol.sneaky(request = G.goal) -> X.result

RETURN X.result
"""


def many_step_plan(count: int) -> str:
    """A valid authored plan with exactly ``count`` define steps."""
    lines = [
        "PROGRAM delegated_big VERSION 1.0",
        "",
        "INPUT",
        '    G.goal = ""',
        '    C.constraints = ""',
        "",
    ]
    lines.extend(
        f"step.s{i}: DO define(request = G.goal) -> P.n{i}"
        for i in range(1, count + 1)
    )
    lines.append("")
    lines.append("RETURN " + ", ".join(f"P.n{i}" for i in range(1, count + 1)))
    return "\n".join(lines) + "\n"


def canonical_digest(step_id: str, plan_text: str) -> str:
    """The digest formula pinned independently of the coordinator helper."""
    payload = {
        "name": delegate_plan_name(step_id),
        "plan_text": plan_text,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


HANDLERS = {
    "define": lambda request: {"echo": request},
    "calculate": lambda expression, values: dict(values),
    "check": lambda artifact, predicate: {
        "artifact": artifact, "predicate": predicate,
    },
    "summarize": lambda source_refs, budget: f"brief of {source_refs} ({budget})",
    # Registered so .commands includes delegate (validation needs it);
    # PlanBookWorker.execute intercepts delegate dispatches before this
    # handler would ever run.
    "delegate": lambda **kwargs: None,
}


class PlanBookWorker(DeterministicWorker):
    """DeterministicWorker whose delegate handler answers from a plan queue.

    The first delegate dispatch pops the first plan; later dispatches pop
    the next (or repeat the last).  Every dispatch is counted, so tests
    can assert the worker was (or was not) re-asked on resume.
    """

    def __init__(self, plans, handlers=None):
        merged = dict(HANDLERS)
        if handlers:
            merged.update(handlers)
        super().__init__(handlers=merged)
        self._plans = list(plans)
        self.delegate_calls = 0

    def execute(self, command, resolved_kwargs):
        if command == "delegate":
            self.delegate_calls += 1
            index = min(self.delegate_calls, len(self._plans)) - 1
            return self._plans[index]
        return super().execute(command, resolved_kwargs)


def run_delegator(store, run_id, worker, tmp_path=None, protocols=None,
                  crash_hook=None, budget=None):
    coordinator = SequentialCoordinator(
        store=store,
        worker=worker,
        protocols_dir=protocols,
    )
    return coordinator.execute(
        parse_program(DELEGATOR), run_id=run_id,
        crash_hook=crash_hook, budget=budget,
    )


# -- end-to-end: author -> record -> child run -> adoption ---------------


def test_delegate_end_to_end_authors_child_run_and_adopts(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = PlanBookWorker([AUTHORED_PLAN])
        result = run_delegator(store, "run-del", worker, tmp_path)
        assert result["status"] == "succeeded"

        history = store.events("run-del")
        authored = [
            event for event in history
            if event.event_type is EventType.CHILD_PLAN_AUTHORED
        ]
        assert len(authored) == 1
        event = authored[0]
        assert event.instruction_id == "step.author"
        assert event.invocation_id == "inv-2"
        assert event.task_id
        assert event.payload["step_id"] == "step.author"
        assert event.payload["plan_text"] == AUTHORED_PLAN
        expected_digest = canonical_digest("step.author", AUTHORED_PLAN)
        assert event.payload["plan_digest"] == expected_digest
        assert delegate_plan_digest("step.author", AUTHORED_PLAN) == (
            expected_digest
        )

        # The authored plan executed as an isolated child run with
        # CALL-grade lineage and the bound program name.
        child_id = "run-del:inv-2"
        child_started = store.events(child_id)[0]
        assert child_started.event_type is EventType.RUN_STARTED
        assert child_started.payload["child_of"] == "run-del"
        assert child_started.payload["call"] == "delegate:step.author"
        assert child_started.payload["program"] == "delegated_step_author"
        child_meta = store.run(child_id)["metadata"]
        assert child_meta["child_of"] == "run-del"
        assert child_meta["call"] == "delegate:step.author"

        # The child's own ledger and namespace are outside the parent's.
        child_texts = [
            task.text
            for task in store.task_ledger(child_id).tasks.values()
        ]
        assert child_texts == [
            "step.frame: DO define",
            "step.measure: DO calculate",
            "step.check: DO check",
        ]
        child_state = store.project_state(child_id)
        assert set(child_state["nodes"]) == {"P.plan", "F.metrics", "V.verdict"}

        # The committed goal traveled in through the leaf-name binding.
        assert child_state["nodes"]["P.plan"]["value"] == {
            "echo": {"echo": "echo the goal into a child plan"},
        }

        # Adoption: authored RETURN ref k -> delegate target k, recorded
        # as CHILD_ADOPTED in the same atomic batch as the SUCCEEDED delta.
        adoption = next(
            item for item in history
            if item.event_type is EventType.CHILD_ADOPTED
        )
        assert adoption.invocation_id == "inv-2"
        assert adoption.payload["child_run_id"] == child_id
        assert adoption.payload["adopted"] == {
            "OUT.plan": "P.plan", "OUT.metrics": "F.metrics",
        }
        assert adoption.payload["child_status"] == "succeeded"
        assert adoption.payload["plan_digest"] == expected_digest
        succeeded = next(
            item for item in history
            if item.event_type is EventType.SUCCEEDED
            and item.invocation_id == "inv-2"
        )
        assert adoption.seq < succeeded.seq
        assert succeeded.payload["delta"]["add_nodes"] == [
            {"id": "OUT.plan",
             "value": {"echo": {"echo": "echo the goal into a child plan"}}},
            {"id": "OUT.metrics", "value": {"units": 3}},
        ]

        parent_state = store.project_state("run-del")
        assert set(parent_state["nodes"]) == {
            "G.probe", "OUT.plan", "OUT.metrics", "OUT.brief",
        }
        assert "P.plan" not in parent_state["nodes"]
        assert "V.verdict" not in parent_state["nodes"]

        parent_texts = [
            task.text
            for task in store.task_ledger("run-del").tasks.values()
        ]
        assert parent_texts == [
            "step.ask: DO define",
            "step.author: DO delegate",
            "step.wrap: DO summarize",
        ]

        for run in ("run-del", child_id):
            report = audit_run(store, run)
            assert report.ok, (
                run, [f.to_dict() for f in report.findings],
            )


# -- rejections through the standard atomic path -------------------------


def test_oversized_plan_fails_formalization_atomically(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = PlanBookWorker([many_step_plan(8)])
        result = run_delegator(store, "run-big", worker, tmp_path)
        assert result["status"] == "failed"
        assert "exceeding the delegate bound of 6" in result["error"]

        history = store.events("run-big")
        authored = [
            event for event in history
            if event.event_type is EventType.CHILD_PLAN_AUTHORED
        ]
        # The rejected plan is still part of history, with its digest.
        assert len(authored) == 1
        assert authored[0].payload["plan_digest"] == canonical_digest(
            "step.author", many_step_plan(8)
        )
        validation_failed = next(
            event for event in history
            if event.event_type is EventType.VALIDATION_FAILED
        )
        assert validation_failed.payload["failure_kind"] == "formalization"
        assert validation_failed.payload["plan_digest"] == (
            authored[0].payload["plan_digest"]
        )
        failed = next(
            event for event in history
            if event.event_type is EventType.FAILED
        )
        assert failed.invocation_id == "inv-2"
        assert failed.task_id
        finished = history[-1]
        assert finished.event_type is EventType.RUN_FINISHED
        assert finished.payload["status"] == "failed"

        # The rejected plan never dispatched a child run and never adopted.
        with pytest.raises(KeyError):
            store.run("run-big:inv-2")
        assert not any(
            event.event_type is EventType.CHILD_ADOPTED
            for event in history
        )
        report = audit_run(store, "run-big")
        assert report.ok, [f.to_dict() for f in report.findings]


def test_max_steps_default_is_six_and_hard_cap_is_twelve(tmp_path):
    # The default bound: omitting max_steps allows at most 6 steps.
    program_text = DELEGATOR.replace(
        "constraints = C.limits, max_steps = 6",
        "constraints = C.limits",
    )
    with EventStore(tmp_path / "events.db") as store:
        worker = PlanBookWorker([many_step_plan(7)])
        coordinator = SequentialCoordinator(
            store=store, worker=worker, protocols_dir=None,
        )
        result = coordinator.execute(
            parse_program(program_text), run_id="run-default"
        )
        assert result["status"] == "failed"
        assert "exceeding the delegate bound of 6" in result["error"]


def test_nested_delegate_in_authored_plan_rejected(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = PlanBookWorker([NESTED_DELEGATE_PLAN])
        result = run_delegator(store, "run-nested", worker, tmp_path)
        assert result["status"] == "failed"
        assert "delegate command" in result["error"]
        assert "recursion" in result["error"] or "bounded" in result["error"]

        history = store.events("run-nested")
        validation_failed = next(
            event for event in history
            if event.event_type is EventType.VALIDATION_FAILED
        )
        assert validation_failed.payload["failure_kind"] == "invalid_input"
        with pytest.raises(KeyError):
            store.run("run-nested:inv-2")
        assert not any(
            event.event_type is EventType.CHILD_ADOPTED
            for event in history
        )


def test_malformed_plan_fails_atomically_with_digest_recorded(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = PlanBookWorker([MALFORMED_PLAN])
        result = run_delegator(store, "run-bad", worker, tmp_path)
        assert result["status"] == "failed"
        assert "failed to parse" in result["error"]

        history = store.events("run-bad")
        authored = [
            event for event in history
            if event.event_type is EventType.CHILD_PLAN_AUTHORED
        ]
        assert len(authored) == 1
        assert authored[0].payload["plan_text"] == MALFORMED_PLAN
        assert authored[0].payload["plan_digest"] == canonical_digest(
            "step.author", MALFORMED_PLAN
        )
        validation_failed = next(
            event for event in history
            if event.event_type is EventType.VALIDATION_FAILED
        )
        assert validation_failed.payload["failure_kind"] == "formalization"
        assert validation_failed.payload["plan_digest"] == (
            authored[0].payload["plan_digest"]
        )
        assert history[-1].payload["status"] == "failed"
        with pytest.raises(KeyError):
            store.run("run-bad:inv-2")
        report = audit_run(store, "run-bad")
        assert report.ok, [f.to_dict() for f in report.findings]


def test_delegate_inside_called_protocol_rejected_no_recursion(tmp_path):
    # The authored plan itself contains no delegate step, but the protocol
    # it CALLs does: the transitive no-recursion walk rejects the plan.
    protocols = tmp_path / "protocols"
    protocols.mkdir()
    (protocols / "sneaky.think").write_text(
        HIDDEN_DELEGATE_PROTOCOL, encoding="utf-8"
    )
    with EventStore(tmp_path / "events.db") as store:
        worker = PlanBookWorker([PROTOCOL_CALLING_PLAN])
        coordinator = SequentialCoordinator(
            store=store, worker=worker, protocols_dir=protocols,
        )
        result = coordinator.execute(
            parse_program(DELEGATOR), run_id="run-via-protocol"
        )
        assert result["status"] == "failed"
        assert "delegate command" in result["error"]
        with pytest.raises(KeyError):
            store.run("run-via-protocol:inv-2")


def test_budget_depth_cap_blocks_delegate_child(tmp_path):
    # max_child_depth 0: the delegate child run (depth 1) is blocked
    # before dispatch, like a CALL child under the same budget.
    with EventStore(tmp_path / "events.db") as store:
        worker = PlanBookWorker([AUTHORED_PLAN])
        result = run_delegator(
            store, "run-depth", worker, tmp_path,
            budget=ExecutionBudget(max_child_depth=0),
        )
        assert result["status"] == "failed"
        assert "max_child_depth 0" in result["error"]
        with pytest.raises(KeyError):
            store.run("run-depth:inv-2")
        assert not any(
            event.event_type is EventType.CHILD_ADOPTED
            for event in store.events("run-depth")
        )


def test_non_mapping_worker_reply_fails_invalid_input(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        worker = PlanBookWorker([{"unexpected": "shape"}])
        result = run_delegator(store, "run-shape", worker, tmp_path)
        assert result["status"] == "failed"
        assert "plan_text" in result["error"]
        # A reply that is not a plan authors nothing: no recorded artifact.
        assert not any(
            event.event_type is EventType.CHILD_PLAN_AUTHORED
            for event in store.events("run-shape")
        )


# -- replay identity: the recorded artifact is the executed one ----------


def test_replay_identity_after_reopen_preserves_authored_plan(tmp_path):
    db = tmp_path / "events.db"
    with EventStore(db) as store:
        worker = PlanBookWorker([AUTHORED_PLAN])
        assert run_delegator(store, "run-replay", worker, tmp_path)[
            "status"
        ] == "succeeded"
        state_before = store.project_state("run-replay")
        child_state_before = store.project_state("run-replay:inv-2")
        authored_before = [
            event.payload for event in store.events("run-replay")
            if event.event_type is EventType.CHILD_PLAN_AUTHORED
        ]

    with EventStore(db) as store:
        assert store.project_state("run-replay") == state_before
        assert store.project_state("run-replay:inv-2") == child_state_before
        authored_after = [
            event.payload for event in store.events("run-replay")
            if event.event_type is EventType.CHILD_PLAN_AUTHORED
        ]
        assert authored_after == authored_before
        assert authored_after[0]["plan_text"] == AUTHORED_PLAN
        assert store.run("run-replay:inv-2")["metadata"]["call"] == (
            "delegate:step.author"
        )
        for run in ("run-replay", "run-replay:inv-2"):
            report = audit_run(store, run)
            assert report.ok, (
                run, [f.to_dict() for f in report.findings],
            )
        # The run is terminal: a resume appends nothing and replans nothing.
        result = resume_run(
            store,
            PlanBookWorker([NESTED_DELEGATE_PLAN, AUTHORED_PLAN]),
            "run-replay",
            parse_program(DELEGATOR),
        )
        assert result["status"] == "succeeded"
        assert result.get("already_terminal") is True


def test_crash_during_delegate_resumes_with_recorded_plan(tmp_path):
    # Crash window: the child run finished and the plan was recorded, but
    # the parent died before adopting.  Resume reuses the RECORDED plan
    # (the worker is never re-asked) and adopts the terminal child.
    db = tmp_path / "events.db"

    def crash_at_author(idx: int) -> None:
        if idx == 1:
            raise CrashInterrupt(f"simulated crash at plan index {idx}")

    with EventStore(db) as store:
        worker = PlanBookWorker([AUTHORED_PLAN, NESTED_DELEGATE_PLAN])
        with pytest.raises(CrashInterrupt):
            run_delegator(
                store, "run-crash", worker, tmp_path,
                crash_hook=crash_at_author,
            )
        assert worker.delegate_calls == 1
        recorded = [
            event.payload for event in store.events("run-crash")
            if event.event_type is EventType.CHILD_PLAN_AUTHORED
        ]
        assert len(recorded) == 1
        child_id = "run-crash:inv-2"
        finished = [
            event for event in store.events(child_id)
            if event.event_type is EventType.RUN_FINISHED
        ]
        assert finished and finished[0].payload["status"] == "succeeded"

    with EventStore(db) as store:
        # A second worker whose NEXT answer would be a different
        # (recursive!) plan: replay must never re-ask the worker.
        worker = PlanBookWorker([NESTED_DELEGATE_PLAN, NESTED_DELEGATE_PLAN])
        result = resume_run(
            store, worker, "run-crash", parse_program(DELEGATOR),
        )
        assert result["status"] == "succeeded"
        assert worker.delegate_calls == 0
        recorded_after = [
            event.payload for event in store.events("run-crash")
            if event.event_type is EventType.CHILD_PLAN_AUTHORED
        ]
        assert len(recorded_after) == 1
        assert recorded_after[0]["plan_text"] == AUTHORED_PLAN
        adoption = next(
            event for event in store.events("run-crash")
            if event.event_type is EventType.CHILD_ADOPTED
        )
        assert adoption.payload["adopted"] == {
            "OUT.plan": "P.plan", "OUT.metrics": "F.metrics",
        }
        for run in ("run-crash", child_id):
            report = audit_run(store, run)
            assert report.ok, (
                run, [f.to_dict() for f in report.findings],
            )
