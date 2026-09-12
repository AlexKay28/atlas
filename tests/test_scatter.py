"""Tests specifying the SCATTER/GATHER bounded fan-out contract (issue #4).

Covers the block grammar and its validation (fresh item/alias refs, existing
committed collection, MAX >= 1, directly-following GATHER, judge exactly when
USING ranked, first/best aliases normalizing to any/ranked), the runtime
expansion (one ledger task per candidate, candidate-scoped
``<alias>.c<k>.<leaf>`` commits, deterministic candidate-order semantics),
loser cancellation under USING any, judge ranking with lowest-index
tie-break under USING ranked, the MAX total-work bound, crash/resume with
at-least-once candidates and replay identity, per-candidate ledger tasks,
and a research-style program (decompose -> SCATTER -> gather -> summarize)
with deterministic workers.
"""

import os
from typing import Any

import pytest

from tikhon.audit import audit_run
from tikhon.resume import resume_run
from tikhon.runtime import EventStore, EventType
from tikhon.runtime.coordinator import (
    CrashInterrupt,
    DeterministicWorker,
    SequentialCoordinator,
    judge_score,
)
from tikhon.runtime.tasks import TaskStatus
from tikhon.syntax import (
    ParseError,
    canonical_json,
    parse_program,
    seal_digest,
    validate_program,
)

SCATTER_ALL_PROGRAM = """\
PROGRAM fanout VERSION 1.0
INPUT
    Q.parts = ["alpha", "beta", "gamma"]
step.prepare: DO define(goal = Q.parts) -> G.goal
SCATTER X.part IN Q.parts MAX 3
  step.draft: DO summarize(source_refs = X.part) -> E.draft
GATHER draft AS E.all USING all
step.final: DO report(inputs = E.all) -> OUT.report
RETURN OUT.report, E.all
"""

SCATTER_ANY_PROGRAM = """\
PROGRAM picker VERSION 1.0
INPUT
    Q.parts = ["bad", "good", "spare"]
SCATTER X.part IN Q.parts MAX 3
  step.draft: DO summarize(source_refs = X.part) -> E.draft
GATHER draft AS E.pick USING any
RETURN E.pick
"""

SCATTER_RANKED_PROGRAM = """\
PROGRAM ranked VERSION 1.0
INPUT
    Q.parts = ["a", "b", "c"]
SCATTER X.part IN Q.parts MAX 3
  step.draft: DO summarize(source_refs = X.part) -> E.draft
GATHER draft AS E.best USING ranked JUDGE step.judge
  step.judge: DO check(artifact = E.draft) -> V.score
RETURN E.best
"""


def summarize_handler(source_refs):
    return f"summary-of-{source_refs}"


def draft_summarize(source_refs):
    return f"draft-{source_refs}"


def report_handler(inputs):
    return {"count": len(inputs), "first": inputs[0]}


def make_worker(**extra):
    handlers = {
        "define": lambda goal: {"goal": goal},
        "summarize": summarize_handler,
        "report": report_handler,
    }
    handlers.update(extra)
    return DeterministicWorker(handlers=handlers)


def event_shapes(store, run_id):
    """Replay-comparable event sequence (wall-clock fields excluded)."""
    return [
        (
            event.event_type.value,
            event.invocation_id,
            event.instruction_id,
            event.task_id,
        )
        for event in store.events(run_id)
    ]


# ---------------------------------------------------------------------------
# Grammar: parse forms
# ---------------------------------------------------------------------------


def test_scatter_block_parses_into_frozen_statements():
    program = parse_program(SCATTER_ALL_PROGRAM)
    scatter = program.statements[1]
    gather = program.statements[2]
    assert type(scatter).__name__ == "Scatter"
    assert type(gather).__name__ == "Gather"
    assert scatter.item_ref == "X.part"
    assert scatter.collection_ref == "Q.parts"
    assert scatter.max_count == 3
    assert scatter.body.step_id == "step.draft"
    assert scatter.body.command == "summarize"
    assert scatter.body.targets == ("E.draft",)
    assert gather.body_step_id == "step.draft"
    assert gather.alias_ref == "E.all"
    assert gather.mode == "all"
    assert gather.judge is None
    # Frozen dataclasses.
    with pytest.raises(Exception):
        scatter.item_ref = "X.other"


def test_gather_accepts_prefixed_step_id_and_seals_identically():
    prefixed = SCATTER_ALL_PROGRAM.replace(
        "GATHER draft AS", "GATHER step.draft AS"
    )
    assert seal_digest(parse_program(prefixed)) == seal_digest(
        parse_program(SCATTER_ALL_PROGRAM)
    )


def test_first_and_best_are_aliases_for_any_and_ranked():
    any_program = parse_program(SCATTER_ANY_PROGRAM)
    assert any_program.statements[1].mode == "any"

    first_program = parse_program(
        SCATTER_ANY_PROGRAM.replace("USING any", "USING first")
    )
    assert first_program.statements[1].mode == "any"
    assert seal_digest(first_program) == seal_digest(any_program)

    ranked = parse_program(SCATTER_RANKED_PROGRAM)
    assert ranked.statements[1].mode == "ranked"
    best = parse_program(
        SCATTER_RANKED_PROGRAM.replace("USING ranked", "USING best")
    )
    assert best.statements[1].mode == "ranked"
    assert seal_digest(best) == seal_digest(ranked)


def test_unknown_using_mode_rejected():
    with pytest.raises(ParseError, match="unknown GATHER USING mode"):
        parse_program(SCATTER_ALL_PROGRAM.replace("USING all", "USING most"))


def test_canonical_json_serializes_scatter_and_gather():
    payload = canonical_json(parse_program(SCATTER_RANKED_PROGRAM))
    assert '"kind":"scatter"' in payload
    assert '"kind":"gather"' in payload
    assert '"mode":"ranked"' in payload
    assert '"judge"' in payload
    # Deterministic across parses.
    assert payload == canonical_json(parse_program(SCATTER_RANKED_PROGRAM))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_max_must_be_positive():
    with pytest.raises(ParseError, match="MAX must be a positive integer"):
        parse_program(SCATTER_ALL_PROGRAM.replace("MAX 3", "MAX 0"))


def test_collection_ref_must_exist():
    source = SCATTER_ALL_PROGRAM.replace(
        "SCATTER X.part IN Q.parts", "SCATTER X.part IN Q.missing"
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="used before definition"):
        validate_program(program, known_commands={"define", "summarize", "report"})


def test_item_ref_must_be_fresh():
    source = SCATTER_ALL_PROGRAM.replace("X.part IN", "G.goal IN")
    program = parse_program(source)
    with pytest.raises(ParseError, match="already defined"):
        validate_program(program, known_commands={"define", "summarize", "report"})


def test_alias_must_be_fresh():
    source = SCATTER_ALL_PROGRAM.replace(
        "GATHER draft AS E.all", "GATHER draft AS G.goal"
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="duplicate target"):
        validate_program(program, known_commands={"define", "summarize", "report"})


def test_gather_must_directly_follow_scatter():
    source = SCATTER_ALL_PROGRAM.replace(
        "GATHER draft AS E.all USING all",
        "step.between: DO define(goal = G.goal) -> G.extra\n"
        "GATHER draft AS E.all USING all",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="directly followed by its GATHER"):
        validate_program(program, known_commands={"define", "summarize", "report"})


def test_gather_without_preceding_scatter_rejected():
    source = """\
PROGRAM lonely VERSION 1.0
INPUT
    Q.parts = ["a"]
GATHER draft AS E.all USING all
RETURN E.all
"""
    program = parse_program(source)
    with pytest.raises(ParseError, match="must directly follow"):
        validate_program(program, known_commands={"summarize"})


def test_scatter_without_gather_rejected():
    source = SCATTER_ALL_PROGRAM.replace(
        "GATHER draft AS E.all USING all\n", ""
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="directly followed by its GATHER"):
        validate_program(program, known_commands={"define", "summarize", "report"})


def test_ranked_requires_judge_step():
    source = SCATTER_RANKED_PROGRAM.replace(
        " USING ranked JUDGE step.judge", " USING ranked"
    ).replace(
        "GATHER draft AS E.best USING ranked\n  step.judge: DO check(artifact = E.draft) -> V.score\n",
        "GATHER draft AS E.best USING ranked\n",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="requires JUDGE"):
        validate_program(program, known_commands={"summarize", "check"})


def test_judge_invalid_for_all_and_any():
    source = SCATTER_ALL_PROGRAM.replace(
        "GATHER draft AS E.all USING all",
        "GATHER draft AS E.all USING all JUDGE step.judge",
    ).replace(
        "step.final: DO report",
        "  step.judge: DO check(artifact = E.draft) -> V.score\n"
        "step.final: DO report",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="JUDGE is only valid with USING ranked"):
        validate_program(
            program, known_commands={"define", "summarize", "check", "report"}
        )


def test_judge_line_must_match_declared_id():
    with pytest.raises(ParseError, match="declares step.judge"):
        parse_program(
            SCATTER_RANKED_PROGRAM.replace(
                "  step.judge: DO check(artifact = E.draft) -> V.score",
                "  step.other: DO check(artifact = E.draft) -> V.score",
            )
        )


def test_scatter_body_must_be_indented_step_line():
    with pytest.raises(ParseError, match="indented"):
        parse_program(
            SCATTER_ALL_PROGRAM.replace(
                "  step.draft: DO summarize",
                "step.draft: DO summarize",
            )
        )


def test_scatter_body_targets_never_join_the_final_namespace():
    program = parse_program(SCATTER_ALL_PROGRAM)
    validate_program(
        program, known_commands={"define", "summarize", "report"}
    )
    # E.draft (the raw body target) is not validated as available: a later
    # step referencing it fails validation.
    source = SCATTER_ALL_PROGRAM.replace(
        "step.final: DO report(inputs = E.all) -> OUT.report",
        "step.final: DO report(inputs = E.draft) -> OUT.report",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="used before definition"):
        validate_program(
            program, known_commands={"define", "summarize", "report"}
        )


def test_scatter_body_revise_retire_rejected():
    source = SCATTER_ALL_PROGRAM.replace(
        "  step.draft: DO summarize(source_refs = X.part) -> E.draft",
        "  step.draft: DO summarize(source_refs = X.part) -> E.draft"
        " REVISE G.goal",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="REVISE/RETIRE"):
        validate_program(
            program, known_commands={"define", "summarize", "report"}
        )


def test_judge_must_have_single_target():
    source = SCATTER_RANKED_PROGRAM.replace(
        "  step.judge: DO check(artifact = E.draft) -> V.score",
        "  step.judge: DO check(artifact = E.draft) -> V.score, V.other",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="exactly one target"):
        validate_program(program, known_commands={"summarize", "check"})


def test_item_ref_not_visible_after_the_block():
    source = SCATTER_ALL_PROGRAM.replace(
        "step.final: DO report(inputs = E.all) -> OUT.report",
        "step.final: DO report(inputs = X.part) -> OUT.report",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="used before definition"):
        validate_program(
            program, known_commands={"define", "summarize", "report"}
        )


def test_pre_scatter_programs_seal_byte_identically():
    # Programs without SCATTER/GATHER serialize exactly as before issue #4.
    plain = """\
PROGRAM plain VERSION 1.0
INPUT
    G.note = "no fanout"
step.mark: DO define(goal = G.note) -> G.marked
RETURN G.marked
"""
    assert '"kind":"scatter"' not in canonical_json(parse_program(plain))
    assert '"kind":"gather"' not in canonical_json(parse_program(plain))


def test_sealed_demo_program_digest_reproduces():
    # The demo program was sealed before any source edit; its digest must
    # still reproduce after the implementation.
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "demo",
        "runs",
        "issue-04-scatter-gather",
        "program.think",
    )
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    assert seal_digest(parse_program(source)) == (
        "87f1d0649d405081881273ff9d605a4b6056f8ce5036d6a7daacb7be8c7a48bc"
    )


# ---------------------------------------------------------------------------
# Runtime: USING all
# ---------------------------------------------------------------------------


def test_using_all_commits_list_of_values_in_candidate_order(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(store, make_worker()).execute(
            parse_program(SCATTER_ALL_PROGRAM), run_id="r"
        )
        assert result["status"] == "succeeded"
        assert result["outputs"]["E.all"] == [
            "summary-of-alpha",
            "summary-of-beta",
            "summary-of-gamma",
        ]
        state = store.project_state("r")
        # Candidate-scoped nodes committed, raw body target never committed.
        assert state["nodes"]["E.all.c1.draft"]["value"] == "summary-of-alpha"
        assert state["nodes"]["E.all.c2.draft"]["value"] == "summary-of-beta"
        assert state["nodes"]["E.all.c3.draft"]["value"] == "summary-of-gamma"
        assert "E.draft" not in state["nodes"]
        assert "OUT.report" in state["nodes"]
        assert audit_run(store, "r").ok


def test_ledger_shows_per_candidate_tasks(tmp_path):
    with EventStore(tmp_path / "events.db") as store:
        SequentialCoordinator(store, make_worker()).execute(
            parse_program(SCATTER_ALL_PROGRAM), run_id="r"
        )
        ledger = store.task_ledger("r")
        candidate_tasks = [
            task
            for task in ledger.tasks.values()
            if "[candidate" in task.text
        ]
        assert [task.text for task in candidate_tasks] == [
            "step.draft: DO summarize [candidate 1]",
            "step.draft: DO summarize [candidate 2]",
            "step.draft: DO summarize [candidate 3]",
        ]
        assert all(
            task.status is TaskStatus.COMPLETED for task in candidate_tasks
        )
        # One child task per candidate plus the plan's own entries
        # (prepare, scatter, gather, final).
        assert ledger.profile()["counts"]["completed"] == 7
        assert ledger.profile()["counts"]["cancelled"] == 0
        # Candidate invocation ids hang off the scatter's positional id.
        candidate_ids = {
            event.invocation_id
            for event in store.events("r")
            if event.event_type is EventType.SUCCEEDED
            and ".cand" in event.invocation_id
        }
        assert candidate_ids == {"inv-2.cand1", "inv-2.cand2", "inv-2.cand3"}


def test_runtime_list_longer_than_max_fails_the_run(tmp_path):
    source = SCATTER_ALL_PROGRAM.replace("MAX 3", "MAX 2")
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(store, make_worker()).execute(
            parse_program(source), run_id="r"
        )
        assert result["status"] == "failed"
        assert "exceeding MAX 2" in result["error"]
        assert audit_run(store, "r").ok


def test_runtime_list_shorter_than_max_iterates_actual(tmp_path):
    source = SCATTER_ALL_PROGRAM.replace(
        'Q.parts = ["alpha", "beta", "gamma"]', 'Q.parts = ["alpha"]'
    )
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(store, make_worker()).execute(
            parse_program(source), run_id="r"
        )
        assert result["status"] == "succeeded"
        assert result["outputs"]["E.all"] == ["summary-of-alpha"]


def test_candidate_body_receives_the_item_value(tmp_path):
    seen = []

    def recording_summarize(source_refs):
        seen.append(source_refs)
        return f"summary-of-{source_refs}"

    with EventStore(tmp_path / "events.db") as store:
        SequentialCoordinator(
            store, make_worker(summarize=recording_summarize)
        ).execute(parse_program(SCATTER_ALL_PROGRAM), run_id="r")
        assert seen == ["alpha", "beta", "gamma"]


def test_candidate_failure_under_all_fails_run_atomically(tmp_path):
    def failing_summarize(source_refs):
        if source_refs == "beta":
            raise RuntimeError("draft exploded")
        return f"summary-of-{source_refs}"

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store, make_worker(summarize=failing_summarize)
        ).execute(parse_program(SCATTER_ALL_PROGRAM), run_id="r")
        assert result["status"] == "failed"
        assert "candidate 2 failed: draft exploded" in result["error"]
        state = store.project_state("r")
        # The failed candidate never commits; earlier candidates stay
        # recorded in state but the alias is never joined.
        assert "E.all.c1.draft" in state["nodes"]
        assert "E.all.c2.draft" not in state["nodes"]
        assert "E.all" not in state["nodes"]
        ledger = store.task_ledger("r")
        assert ledger.profile()["counts"]["cancelled"] >= 1
        assert audit_run(store, "r").ok


def test_using_all_with_empty_collection_commits_empty_list(tmp_path):
    source = SCATTER_ALL_PROGRAM.replace(
        'Q.parts = ["alpha", "beta", "gamma"]', "Q.parts = []"
    )
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store,
            make_worker(report=lambda inputs: inputs),
        ).execute(parse_program(source), run_id="r")
        assert result["status"] == "succeeded"
        assert result["outputs"]["E.all"] == []


# ---------------------------------------------------------------------------
# Runtime: USING any (losers cancelled, first candidate-order success wins)
# ---------------------------------------------------------------------------


def test_using_any_first_success_wins_and_losers_are_cancelled(tmp_path):
    def flaky_summarize(source_refs):
        if source_refs == "bad":
            raise RuntimeError("boom on bad")
        return f"ok-{source_refs}"

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store, make_worker(summarize=flaky_summarize)
        ).execute(parse_program(SCATTER_ANY_PROGRAM), run_id="r")
        assert result["status"] == "succeeded"
        assert result["outputs"]["E.pick"] == "ok-good"
        state = store.project_state("r")
        # Only the winner's candidate node exists; losers stay recorded via
        # their cancelled tasks and the gather evidence, never committed.
        assert state["nodes"]["E.pick"]["value"] == "ok-good"
        assert "E.pick.c1.draft" not in state["nodes"]
        assert "E.pick.c2.draft" in state["nodes"]
        ledger = store.task_ledger("r")
        statuses = {
            task.text: task.status for task in ledger.tasks.values()
        }
        assert statuses["step.draft: DO summarize [candidate 1]"] is (
            TaskStatus.CANCELLED
        )
        assert statuses["step.draft: DO summarize [candidate 2]"] is (
            TaskStatus.COMPLETED
        )
        # Candidates after the winner are cancelled without being started.
        assert statuses["step.draft: DO summarize [candidate 3]"] is (
            TaskStatus.CANCELLED
        )
        # Audit truthfulness: no FAILED events in a succeeding run; the
        # loser failure is recorded in the gather's selection evidence.
        assert not [
            event
            for event in store.events("r")
            if event.event_type is EventType.FAILED
        ]
        gather_task = next(
            task
            for task in ledger.tasks.values()
            if task.text.startswith("GATHER")
        )
        assert "winner candidate 2" in gather_task.evidence[-1]
        assert "boom on bad" in gather_task.evidence[-1]
        assert audit_run(store, "r").ok


def test_using_any_all_candidates_failing_fails_the_run(tmp_path):
    def failing_summarize(source_refs):
        raise RuntimeError(f"no luck {source_refs}")

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store, make_worker(summarize=failing_summarize)
        ).execute(parse_program(SCATTER_ANY_PROGRAM), run_id="r")
        assert result["status"] == "failed"
        assert "all 3 candidate(s) failed" in result["error"]
        assert audit_run(store, "r").ok


def test_using_any_with_empty_collection_fails(tmp_path):
    source = SCATTER_ANY_PROGRAM.replace(
        'Q.parts = ["bad", "good", "spare"]', "Q.parts = []"
    )
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(store, make_worker()).execute(
            parse_program(source), run_id="r"
        )
        assert result["status"] == "failed"


def test_using_alias_first_behaves_like_any(tmp_path):
    source = SCATTER_ANY_PROGRAM.replace("USING any", "USING first")

    def flaky_summarize(source_refs):
        if source_refs == "bad":
            raise RuntimeError("boom on bad")
        return f"ok-{source_refs}"

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store, make_worker(summarize=flaky_summarize)
        ).execute(parse_program(source), run_id="r")
        assert result["status"] == "succeeded"
        assert result["outputs"]["E.pick"] == "ok-good"


# ---------------------------------------------------------------------------
# Runtime: USING ranked (explicit judge, max score, lowest-index tie-break)
# ---------------------------------------------------------------------------


def test_ranked_picks_max_score_with_lowest_index_tie_break(tmp_path):
    def scoring_check(artifact):
        scores = {"draft-a": 0.5, "draft-b": 0.9, "draft-c": 0.9}
        return {"score": scores[artifact]}

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store, make_worker(summarize=draft_summarize, check=scoring_check)
        ).execute(parse_program(SCATTER_RANKED_PROGRAM), run_id="r")
        assert result["status"] == "succeeded"
        # Tie between candidates 2 and 3 breaks to the lowest index.
        assert result["outputs"]["E.best"] == "draft-b"
        ledger = store.task_ledger("r")
        gather_task = next(
            task
            for task in ledger.tasks.values()
            if task.text.startswith("GATHER")
        )
        evidence = gather_task.evidence[-1]
        assert "winner candidate 2" in evidence
        assert "judge check" in evidence
        assert audit_run(store, "r").ok


def test_ranked_judge_status_passed_scores_binary(tmp_path):
    def status_check(artifact):
        return {"status": "passed" if artifact == "draft-c" else "rejected"}

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store, make_worker(summarize=draft_summarize, check=status_check)
        ).execute(parse_program(SCATTER_RANKED_PROGRAM), run_id="r")
        assert result["status"] == "succeeded"
        assert result["outputs"]["E.best"] == "draft-c"


def test_ranked_judge_number_and_bool_results(tmp_path):
    def number_check(artifact):
        return {"draft-a": 1, "draft-b": 3, "draft-c": 2}[artifact]

    source = SCATTER_RANKED_PROGRAM
    with EventStore(tmp_path / "number.db") as store:
        result = SequentialCoordinator(
            store, make_worker(summarize=draft_summarize, check=number_check)
        ).execute(parse_program(source), run_id="r")
        assert result["outputs"]["E.best"] == "draft-b"

    def bool_check(artifact):
        return artifact == "draft-c"

    with EventStore(tmp_path / "bool.db") as store:
        result = SequentialCoordinator(
            store, make_worker(summarize=draft_summarize, check=bool_check)
        ).execute(parse_program(source), run_id="r")
        assert result["outputs"]["E.best"] == "draft-c"


def test_judge_scores_extracted_deterministically():
    assert judge_score(0.5) == 0.5
    assert judge_score(2) == 2.0
    assert judge_score(True) == 1.0
    assert judge_score(False) == 0.0
    assert judge_score("passed") == 1.0
    assert judge_score("failed") == 0.0
    assert judge_score({"score": 0.75}) == 0.75
    assert judge_score({"status": "passed"}) == 1.0
    assert judge_score({"status": "rejected"}) == 0.0
    with pytest.raises(ValueError, match="no scorable field"):
        judge_score({"verdict": "maybe"})


def test_ranked_judge_failure_fails_the_run(tmp_path):
    def broken_check(artifact):
        raise RuntimeError("judge unavailable")

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store, make_worker(summarize=draft_summarize, check=broken_check)
        ).execute(parse_program(SCATTER_RANKED_PROGRAM), run_id="r")
        assert result["status"] == "failed"
        assert "judge for candidate 1 failed" in result["error"]
        assert audit_run(store, "r").ok


def test_ranked_candidate_failure_fails_the_run(tmp_path):
    def flaky_summarize(source_refs):
        if source_refs == "b":
            raise RuntimeError("candidate b died")
        return f"draft-{source_refs}"

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store,
            make_worker(summarize=flaky_summarize, check=lambda artifact: 1.0),
        ).execute(parse_program(SCATTER_RANKED_PROGRAM), run_id="r")
        assert result["status"] == "failed"
        assert "candidate 2 failed" in result["error"]
        assert audit_run(store, "r").ok


def test_ranked_judge_reads_candidate_item_and_result(tmp_path):
    seen = []

    def judging_check(artifact):
        seen.append(artifact)
        return 1.0

    source = SCATTER_RANKED_PROGRAM.replace(
        "  step.judge: DO check(artifact = E.draft) -> V.score",
        "  step.judge: DO check(artifact = E.draft) -> V.score",
    )
    with EventStore(tmp_path / "events.db") as store:
        SequentialCoordinator(
            store, make_worker(summarize=draft_summarize, check=judging_check)
        ).execute(parse_program(source), run_id="r")
        # The judge bound the body target per candidate.
        assert seen == ["draft-a", "draft-b", "draft-c"]


def test_best_alias_runs_ranked_join(tmp_path):
    source = SCATTER_RANKED_PROGRAM.replace("USING ranked", "USING best")

    def scoring_check(artifact):
        return {"score": {"draft-a": 0.2, "draft-b": 0.4, "draft-c": 0.3}[artifact]}

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store, make_worker(summarize=draft_summarize, check=scoring_check)
        ).execute(parse_program(source), run_id="r")
        assert result["outputs"]["E.best"] == "draft-b"


# ---------------------------------------------------------------------------
# Determinism, replay and crash/resume
# ---------------------------------------------------------------------------


def test_replay_identity_across_two_fresh_runs(tmp_path):
    shapes = []
    for index in (1, 2):
        with EventStore(tmp_path / f"events{index}.db") as store:
            result = SequentialCoordinator(store, make_worker()).execute(
                parse_program(SCATTER_ALL_PROGRAM), run_id="r"
            )
            assert result["status"] == "succeeded"
            shapes.append(
                (
                    event_shapes(store, "r"),
                    store.project_state("r")["nodes"],
                    store.task_ledger("r").profile()["counts"],
                )
            )
    assert shapes[0] == shapes[1]


def test_gathered_state_identical_after_reopen(tmp_path):
    path = tmp_path / "events.db"
    with EventStore(path) as store:
        SequentialCoordinator(store, make_worker()).execute(
            parse_program(SCATTER_ALL_PROGRAM), run_id="r"
        )
        nodes_before = store.project_state("r")["nodes"]
    with EventStore(path) as reopened:
        nodes_after = reopened.project_state("r")["nodes"]
    assert nodes_before == nodes_after


class _CountingCrash:
    """crash_hook that raises CrashInterrupt on its n-th call."""

    def __init__(self, fire_on: int) -> None:
        self.calls = 0
        self.fire_on = fire_on

    def __call__(self, idx: int) -> None:
        self.calls += 1
        if self.calls == self.fire_on:
            raise CrashInterrupt("simulated crash")


CRASH_PROGRAM = """\
PROGRAM crashy VERSION 1.0
INPUT
    Q.parts = ["alpha", "beta", "gamma"]
SCATTER X.part IN Q.parts MAX 3
  step.draft: DO summarize(source_refs = X.part) -> E.draft
GATHER draft AS E.all USING all
step.final: DO report(inputs = E.all) -> OUT.report
RETURN OUT.report, E.all
"""


@pytest.mark.parametrize("fire_on", [1, 2, 3, 4, 5])
def test_crash_mid_scatter_resume_completes_without_duplicate_commits(
    tmp_path, fire_on
):
    with EventStore(tmp_path / "crash.db") as store:
        coordinator = SequentialCoordinator(store, make_worker())
        with pytest.raises(CrashInterrupt):
            coordinator.execute(
                parse_program(CRASH_PROGRAM),
                run_id="r",
                crash_hook=_CountingCrash(fire_on),
            )
        result = resume_run(
            store, make_worker(), "r", parse_program(CRASH_PROGRAM)
        )
        assert result["status"] == "succeeded"
        # No duplicate commits: every invocation id SUCCEEDED exactly once.
        succeeded = [
            event.invocation_id
            for event in store.events("r")
            if event.event_type is EventType.SUCCEEDED
        ]
        assert len(succeeded) == len(set(succeeded))
        assert audit_run(store, "r").ok

    # The recovered state matches a fresh uninterrupted run exactly.
    with EventStore(tmp_path / "fresh.db") as store:
        SequentialCoordinator(store, make_worker()).execute(
            parse_program(CRASH_PROGRAM), run_id="r"
        )
        fresh_nodes = store.project_state("r")["nodes"]
    with EventStore(tmp_path / "crash.db") as store:
        assert store.project_state("r")["nodes"] == fresh_nodes


def test_crash_resume_is_at_least_once_for_the_interrupted_candidate(tmp_path):
    calls = {"count": 0}

    def counting_summarize(source_refs):
        calls["count"] += 1
        return f"summary-of-{source_refs}"

    with EventStore(tmp_path / "events.db") as store:
        coordinator = SequentialCoordinator(
            store, make_worker(summarize=counting_summarize)
        )
        with pytest.raises(CrashInterrupt):
            coordinator.execute(
                parse_program(CRASH_PROGRAM),
                run_id="r",
                crash_hook=_CountingCrash(2),
            )
        result = resume_run(
            store, make_worker(summarize=counting_summarize), "r",
            parse_program(CRASH_PROGRAM),
        )
        assert result["status"] == "succeeded"
        # Candidates 1 (re-run after the crash window), 2 (re-executed
        # in-flight) and 3 ran, plus the pre-crash candidate-1 attempt.
        assert calls["count"] == 4


def test_any_mode_resume_after_winner_committed_skips_remaining(tmp_path):
    calls = {"count": 0}

    def flaky_summarize(source_refs):
        calls["count"] += 1
        if source_refs == "bad":
            raise RuntimeError("boom on bad")
        return f"ok-{source_refs}"

    with EventStore(tmp_path / "events.db") as store:
        coordinator = SequentialCoordinator(
            store, make_worker(summarize=flaky_summarize)
        )
        # Crash right before the gather commits (after the winner): the
        # hook sites under any are the winner's terminal window, the
        # scatter's and the gather's — the loser never reaches one.
        with pytest.raises(CrashInterrupt):
            coordinator.execute(
                parse_program(SCATTER_ANY_PROGRAM),
                run_id="r",
                crash_hook=_CountingCrash(3),
            )
        result = resume_run(
            store, make_worker(summarize=flaky_summarize), "r",
            parse_program(SCATTER_ANY_PROGRAM),
        )
        assert result["status"] == "succeeded"
        assert result["outputs"]["E.pick"] == "ok-good"
        # The winner is not re-executed and later candidates are not
        # started on resume: bad(1) + good(2) ran exactly once each.
        assert calls["count"] == 2
        assert audit_run(store, "r").ok


def test_scatter_run_with_max_workers_stays_deterministic(tmp_path):
    """Scatter runs drive the sequential plan loop for any max_workers."""
    results = []
    for max_workers in (1, 4):
        with EventStore(tmp_path / f"mw{max_workers}.db") as store:
            result = SequentialCoordinator(store, make_worker()).execute(
                parse_program(SCATTER_ALL_PROGRAM),
                run_id="r",
                max_workers=max_workers,
            )
            assert result["status"] == "succeeded"
            results.append(
                (
                    result["outputs"],
                    event_shapes(store, "r"),
                    store.project_state("r")["nodes"],
                )
            )
    assert results[0] == results[1]


# ---------------------------------------------------------------------------
# Reference-Program-A-style research flow (issue #4 acceptance)
# ---------------------------------------------------------------------------


RESEARCH_PROGRAM = """\
PROGRAM research_flow VERSION 1.0
INPUT
    Q.choice = "Which option satisfies the constraints?"
step.parts: DO decompose(goal = Q.choice, limit = 3) -> Q.parts
SCATTER X.part IN Q.parts MAX 3
  step.search: DO search(query = X.part, scope = "web", limit = 8) -> E.urls
GATHER search AS E.all USING all
step.model: DO synthesize(findings = E.all) -> F.model
step.output: DO report(inputs = [F.model, Q.choice]) -> OUT.report
RETURN OUT.report, F.model
"""


def test_research_style_program_executes_with_deterministic_workers(tmp_path):
    def decompose(goal, limit):
        return ["sub-question-1", "sub-question-2", "sub-question-3"]

    def search(query, scope, limit):
        return f"urls-for-{query}"

    def synthesize(findings):
        return {"findings": findings, "complete": True}

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store,
            make_worker(
                decompose=decompose,
                search=search,
                synthesize=synthesize,
            ),
        ).execute(parse_program(RESEARCH_PROGRAM), run_id="r")
        assert result["status"] == "succeeded"
        assert result["outputs"]["F.model"] == {
            "findings": [
                "urls-for-sub-question-1",
                "urls-for-sub-question-2",
                "urls-for-sub-question-3",
            ],
            "complete": True,
        }
        state = store.project_state("r")
        assert state["nodes"]["E.all"]["value"] == [
            "urls-for-sub-question-1",
            "urls-for-sub-question-2",
            "urls-for-sub-question-3",
        ]
        ledger = store.task_ledger("r")
        assert any(
            task.text == "step.search: DO search [candidate 2]"
            for task in ledger.tasks.values()
        )
        assert audit_run(store, "r").ok


def test_research_ranked_variant_picks_best_branch(tmp_path):
    program_source = """\
PROGRAM research_ranked VERSION 1.0
INPUT
    Q.choice = "Which option satisfies the constraints?"
step.parts: DO decompose(goal = Q.choice, limit = 3) -> Q.parts
SCATTER X.part IN Q.parts MAX 3
  step.search: DO search(query = X.part, scope = "web", limit = 8) -> E.urls
GATHER search AS E.all USING ranked JUDGE step.judge
  step.judge: DO verify(goal = X.part, evidence = E.urls) -> V.score
step.model: DO synthesize(findings = E.all) -> F.model
RETURN F.model
"""

    def decompose(goal, limit):
        return ["q1", "q2", "q3"]

    def search(query, scope, limit):
        return f"urls-for-{query}"

    def verify(goal, evidence):
        # q2's branch is the best; q3 ties nothing.
        return {"score": {"q1": 0.4, "q2": 0.9, "q3": 0.6}[goal]}

    def synthesize(findings):
        return {"winner": findings}

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store,
            make_worker(
                decompose=decompose,
                search=search,
                verify=verify,
                synthesize=synthesize,
            ),
        ).execute(parse_program(program_source), run_id="r")
        assert result["status"] == "succeeded"
        assert result["outputs"]["F.model"] == {"winner": "urls-for-q2"}


# ---------------------------------------------------------------------------
# Composed state interactions
# ---------------------------------------------------------------------------


def test_gather_alias_feeds_count_condition_and_later_steps(tmp_path):
    source = """\
PROGRAM gated VERSION 1.0
INPUT
    Q.parts = ["a", "b"]
SCATTER X.part IN Q.parts MAX 2
  step.draft: DO summarize(source_refs = X.part) -> E.draft
GATHER draft AS E.all USING all
IF count(E.all) == 2 STOP blocked(E.all)
step.final: DO report(inputs = E.all) -> OUT.report
RETURN OUT.report
"""
    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(store, make_worker()).execute(
            parse_program(source), run_id="r"
        )
        # The conditional fires (count == 2) and stops the run blocked.
        assert result["status"] == "blocked"
        run_finished = next(
            event
            for event in store.events("r")
            if event.event_type is EventType.RUN_FINISHED
        )
        assert run_finished.payload["reason"] == [
            "summary-of-a",
            "summary-of-b",
        ]
        assert audit_run(store, "r").ok


def test_multi_target_body_joins_list_of_mappings(tmp_path):
    source = """\
PROGRAM multi VERSION 1.0
INPUT
    Q.parts = ["a", "b"]
SCATTER X.part IN Q.parts MAX 2
  step.pair: DO split_pair(left = X.part, right = X.part) -> E.summary, E.detail
GATHER pair AS E.both USING all
RETURN E.both
"""

    def split_pair(left, right):
        return {"summary": f"S-{left}", "detail": f"D-{right}"}

    with EventStore(tmp_path / "events.db") as store:
        result = SequentialCoordinator(
            store, DeterministicWorker(handlers={"split_pair": split_pair})
        ).execute(parse_program(source), run_id="r")
        assert result["status"] == "succeeded"
        assert result["outputs"]["E.both"] == [
            {"summary": "S-a", "detail": "D-a"},
            {"summary": "S-b", "detail": "D-b"},
        ]
        state = store.project_state("r")
        assert state["nodes"]["E.both.c1.summary"]["value"] == "S-a"
        assert state["nodes"]["E.both.c2.detail"]["value"] == "D-b"
        assert audit_run(store, "r").ok
