"""Tests for the task/result envelope protocol and external driver (issue #18).

Contract under test (tahoe.envelope + its bindings):

- TaskEnvelope / ResultEnvelope dataclasses round trip through canonical
  JSON with strict validation and clear errors (unknown fields, missing
  fields, wrong schema version, empty identity, non-object payloads,
  bad status/error combinations, non-JSON-serializable values).
- ModelWorker builds its prompt FROM a TaskEnvelope (the envelope's
  canonical JSON is embedded; the transport seam is unchanged) and parses
  the reply INTO a validated ResultEnvelope whose receipt distinguishes
  unavailable telemetry (``None``) from a measured zero.
- ``tahoe next`` renders the next ready invocation's envelope from the
  event store; ``tahoe submit`` accepts a result file and commits
  RESULT_RECEIVED / VALIDATION / SUCCEEDED through the same coordinator
  machinery.  A 2-step program drives to a succeeded run externally, the
  event-type sequence matches a coordinator-driven run of the same
  program, ``audit_run`` is clean afterwards, and duplicate / stale /
  malformed / failed / blocked submissions behave without false
  completion.

No test touches a real network or an external worker process.
"""

import json

import pytest

from tahoe.audit import audit_run
from tahoe.cli import main
from tahoe.envelope import (
    DIRECT_DISPATCH_RUN_ID,
    ENVELOPE_SCHEMA_VERSION,
    DriverError,
    EnvelopeValidationError,
    ExternalDriver,
    ResultEnvelope,
    TaskEnvelope,
    build_task_envelope,
)
from tahoe.registry import builtin_registry
from tahoe.runtime import EventStore, EventType, SequentialCoordinator
from tahoe.syntax import parse_program, seal_digest
from tahoe.worker_adapter import ModelWorker


TWO_STEP_PROGRAM = """\
PROGRAM envelope_round_trip VERSION 1.0
INPUT
    G.topic = "envelopes"
    G.left = 5
    G.right = 7
step.frame: DO define(request = G.topic) -> G.plan
step.total: DO calculate(left = G.left, right = G.right) -> OUT.total
DONE OUT.total == 12
RETURN G.plan, OUT.total
"""


def _make_task_envelope() -> TaskEnvelope:
    return build_task_envelope(
        builtin_registry(),
        run_id="run-1",
        invocation_id="inv-1",
        task_id="task-1",
        attempt=1,
        idempotency_key="run-1:inv-1",
        command="define",
        arguments={"request": "frame the goal"},
        targets=("G.plan",),
        done=None,
        program={"name": "prog", "version": "1.0"},
        seal_digest="abc123",
    )


def _make_result_envelope(**overrides: object) -> ResultEnvelope:
    fields: dict[str, object] = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "run_id": "run-1",
        "invocation_id": "inv-1",
        "task_id": "task-1",
        "attempt": 1,
        "idempotency_key": "run-1:inv-1",
        "command": "define",
        "status": "succeeded",
        "payload": {"plan": "framed"},
        "evidence": ("artifact-1",),
        "error": None,
        "receipt": {"worker": "stub", "usage": {"tokens": 11}},
    }
    fields.update(overrides)
    return ResultEnvelope(**fields)


def _result_file(
    task_envelope: TaskEnvelope,
    payload: object,
    tmp_path,
    *,
    status: str = "succeeded",
    error: str | None = None,
    attempt: int | None = None,
    idempotency_key: str | None = None,
    name: str = "result.json",
) -> str:
    data = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "run_id": task_envelope.run_id,
        "invocation_id": task_envelope.invocation_id,
        "task_id": task_envelope.task_id,
        "attempt": task_envelope.attempt if attempt is None else attempt,
        "idempotency_key": (
            task_envelope.idempotency_key
            if idempotency_key is None
            else idempotency_key
        ),
        "command": task_envelope.command,
        "status": status,
        "payload": payload,
        "evidence": [],
        "error": error if error is not None else (
            None if status == "succeeded" else "worker reported failure"
        ),
        "receipt": {
            "worker": "external",
            "usage": {"tokens": 25, "cost": 0.0, "retries": 0,
                      "elapsed_seconds": 1.5},
        },
    }
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ------------------------------------------------------------- round trips


def test_task_envelope_round_trips_through_json():
    envelope = _make_task_envelope()
    restored = TaskEnvelope.from_json(envelope.to_json())
    assert restored == envelope


def test_result_envelope_round_trips_through_json():
    envelope = _make_result_envelope()
    restored = ResultEnvelope.from_json(envelope.to_json())
    assert restored == envelope


def test_result_envelope_round_trip_keeps_failed_and_blocked():
    for status in ("failed", "blocked"):
        envelope = _make_result_envelope(
            status=status, payload=None, error="backend unavailable"
        )
        assert ResultEnvelope.from_json(envelope.to_json()) == envelope


def test_blocked_result_payload_still_validates():
    envelope = _make_result_envelope(status="blocked", payload=None,
                                     error="waiting on credentials")
    envelope.validate()


# ----------------------------------------------------- strict validation


def test_task_envelope_rejects_unknown_and_missing_fields():
    data = json.loads(_make_task_envelope().to_json())
    unknown = dict(data)
    unknown["extra"] = 1
    with pytest.raises(EnvelopeValidationError, match="unknown fields: extra"):
        TaskEnvelope.from_dict(unknown)
    missing = {key: value for key, value in data.items() if key != "task_id"}
    with pytest.raises(EnvelopeValidationError,
                       match="missing fields: task_id"):
        TaskEnvelope.from_dict(missing)


def test_task_envelope_rejects_wrong_schema_version():
    envelope = _make_task_envelope()
    broken = replace_field(envelope, schema_version="2")
    with pytest.raises(EnvelopeValidationError, match="schema_version"):
        broken.validate()


def test_task_envelope_rejects_empty_identity():
    envelope = replace_field(_make_task_envelope(), run_id="")
    with pytest.raises(EnvelopeValidationError, match="run_id"):
        envelope.validate()
    envelope = replace_field(_make_task_envelope(), idempotency_key="")
    with pytest.raises(EnvelopeValidationError, match="idempotency_key"):
        envelope.validate()


def test_task_envelope_rejects_non_object_arguments():
    envelope = replace_field(_make_task_envelope(), arguments=["not", "a", "map"])
    with pytest.raises(EnvelopeValidationError, match="arguments"):
        envelope.validate()


def test_task_envelope_rejects_non_string_targets():
    envelope = replace_field(_make_task_envelope(), targets=(7,))
    with pytest.raises(EnvelopeValidationError, match="targets"):
        envelope.validate()


def test_task_envelope_rejects_bad_done_predicate():
    envelope = replace_field(
        _make_task_envelope(),
        done={"op": "approximates", "ref": "G.plan", "value": 1},
    )
    with pytest.raises(EnvelopeValidationError, match="done.op"):
        envelope.validate()


def test_task_envelope_rejects_non_json_serializable_arguments():
    envelope = replace_field(
        _make_task_envelope(), arguments={"request": {1, 2}}
    )
    with pytest.raises(EnvelopeValidationError, match="JSON-serializable"):
        envelope.validate()


def test_envelope_from_json_rejects_invalid_json_and_non_objects():
    with pytest.raises(EnvelopeValidationError, match="not valid JSON"):
        TaskEnvelope.from_json("definitely not json")
    with pytest.raises(EnvelopeValidationError, match="must be a JSON object"):
        TaskEnvelope.from_json("[1, 2, 3]")
    with pytest.raises(EnvelopeValidationError, match="must be a JSON object"):
        ResultEnvelope.from_json('"succeeded"')


def test_result_envelope_rejects_unknown_status():
    envelope = _make_result_envelope(status="kind-of-fine")
    with pytest.raises(EnvelopeValidationError, match="status"):
        envelope.validate()


def test_result_envelope_requires_error_for_failed_and_blocked():
    for status in ("failed", "blocked"):
        envelope = _make_result_envelope(status=status, error=None)
        with pytest.raises(EnvelopeValidationError, match="error"):
            envelope.validate()


def test_result_envelope_rejects_error_on_succeeded():
    envelope = _make_result_envelope(error="boom")
    with pytest.raises(EnvelopeValidationError, match="error"):
        envelope.validate()


def test_result_envelope_rejects_non_json_payload():
    envelope = _make_result_envelope(payload={"weird": {1, 2}})
    with pytest.raises(EnvelopeValidationError, match="JSON-serializable"):
        envelope.validate()


def replace_field(envelope: TaskEnvelope, **changes: object) -> TaskEnvelope:
    """Rebuild a task envelope with one field replaced (validation tests)."""
    data = envelope.to_dict()
    for key, value in changes.items():
        data[key] = value
    return TaskEnvelope(
        schema_version=data["schema_version"],
        run_id=data["run_id"],
        invocation_id=data["invocation_id"],
        task_id=data["task_id"],
        attempt=data["attempt"],
        idempotency_key=data["idempotency_key"],
        command=data["command"],
        command_version=data["command_version"],
        arguments=data["arguments"],
        input_digest=data["input_digest"],
        targets=tuple(data["targets"]),
        done=data["done"],
        contract=data["contract"],
        workspace_root=data["workspace_root"],
        program=data["program"],
        seal_digest=data["seal_digest"],
        deadline_seconds=data["deadline_seconds"],
    )


# ----------------------------------------------- ModelWorker envelope binding


def test_model_worker_prompt_is_built_from_task_envelope():
    calls: list[tuple[str, str]] = []

    def transport(model: str, prompt: str) -> str:
        calls.append((model, prompt))
        return '{"plan": "ok"}'

    worker = ModelWorker(
        registry=builtin_registry(), transport=transport, default_model="m"
    )
    result = worker.execute("define", {"request": "frame it"}, targets=("G.plan",))
    assert result == {"plan": "ok"}

    envelope = worker.last_task_envelope
    assert envelope is not None
    assert envelope.command == "define"
    assert envelope.run_id == DIRECT_DISPATCH_RUN_ID
    assert envelope.arguments == {"request": "frame it"}
    assert envelope.targets == ("G.plan",)
    assert envelope.idempotency_key.startswith("direct:")
    assert envelope.contract["purpose"] == builtin_registry().resolve(
        "define"
    ).purpose

    prompt = calls[-1][1]
    assert envelope.to_json() in prompt
    assert '"idempotency_key":"' + envelope.idempotency_key + '"' in prompt
    assert "Command: define (version 1.0.0)" in prompt
    assert "Reply with ONLY a JSON object" in prompt


def test_model_worker_parses_reply_into_result_envelope():
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=lambda model, prompt: '{"plan": "ok"}',
        default_model="m",
    )
    worker.execute("define", {"request": "x"})
    result_envelope = worker.last_result_envelope
    assert isinstance(result_envelope, ResultEnvelope)
    assert result_envelope.status == "succeeded"
    assert result_envelope.payload == {"plan": "ok"}
    assert result_envelope.run_id == DIRECT_DISPATCH_RUN_ID
    assert result_envelope.idempotency_key == (
        worker.last_task_envelope.idempotency_key
    )
    # Unavailable telemetry is None, never a fabricated measured zero.
    assert result_envelope.receipt["usage"]["tokens"] is None


def test_direct_dispatch_task_envelope_round_trips():
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=lambda model, prompt: "12",
        default_model="m",
    )
    worker.execute("calculate", {"left": 5, "right": 7})
    envelope = worker.last_task_envelope
    assert TaskEnvelope.from_json(envelope.to_json()) == envelope


# --------------------------------------------- external driver: next/submit


def _write(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _next(tmp_path, program, digest, db, capsys):
    rc = main(
        [
            "next", "--db", db, "--run-id", "r1",
            "--program", program, "--seal", digest,
        ]
    )
    assert rc == 0, capsys.readouterr().err
    return TaskEnvelope.from_json(capsys.readouterr().out.strip())


def test_next_submit_cli_round_trip_finishes_run(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")

    envelope1 = _next(tmp_path, program, digest, db, capsys)
    assert envelope1.command == "define"
    assert envelope1.invocation_id == "inv-1"
    assert envelope1.task_id == "task-1"
    assert envelope1.attempt == 1
    assert envelope1.idempotency_key == "r1:inv-1"
    assert envelope1.targets == ("G.plan",)
    assert envelope1.arguments == {"request": "envelopes"}
    assert envelope1.run_id == "r1"
    assert envelope1.seal_digest == digest
    assert envelope1.program == {"name": "envelope_round_trip", "version": "1.0"}

    result1 = _result_file(envelope1, {"plan": "frame and locate"}, tmp_path,
                           name="result1.json")
    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-1", "--result-file", result1,
    ])
    assert rc == 0, capsys.readouterr().err
    outcome = json.loads(capsys.readouterr().out)
    assert outcome == {
        "run_id": "r1", "invocation_id": "inv-1",
        "recorded": True, "run_status": "in_progress",
    }

    envelope2 = _next(tmp_path, program, digest, db, capsys)
    assert envelope2.command == "calculate"
    assert envelope2.invocation_id == "inv-2"
    assert envelope2.arguments == {"left": 5, "right": 7}
    assert envelope2.done == {"op": "equals", "ref": "OUT.total", "value": 12}

    result2 = _result_file(envelope2, 12, tmp_path, name="result2.json")
    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-2", "--result-file", result2,
    ])
    assert rc == 0, capsys.readouterr().err
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["run_status"] == "succeeded"

    store = EventStore(db)
    try:
        events = store.events("r1")
        assert events[-1].event_type is EventType.RUN_FINISHED
        assert events[-1].payload == {"status": "succeeded"}
        types = [event.event_type.value for event in events]
        assert types.count("invocation.succeeded") == 2
        assert types.count("invocation.result_received") == 2
        # The atomic SUCCEEDED batch: succeeded, invocation_recorded,
        # task_completed — identical shape to a coordinator-driven run.
        succeeded_tail = types[-4:-1]
        assert succeeded_tail == [
            "invocation.succeeded", "task.updated", "task.updated",
        ]
        report = audit_run(store, "r1")
        assert report.ok, report.to_dict()
        ledger = store.task_ledger("r1")
        assert all(
            task.status.value == "completed" for task in ledger.tasks.values()
        )
        state = store.project_state("r1")
        assert state["nodes"]["G.plan"]["value"] == {"plan": "frame and locate"}
        assert state["nodes"]["OUT.total"]["value"] == 12
    finally:
        store.close()


def test_next_is_idempotent_while_awaiting_result(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")

    envelope1 = _next(tmp_path, program, digest, db, capsys)
    envelope1b = _next(tmp_path, program, digest, db, capsys)
    assert envelope1b == envelope1

    store = EventStore(db)
    try:
        dispatches = [
            event for event in store.events("r1")
            if event.event_type is EventType.INVOCATION_DISPATCHED
        ]
        assert len(dispatches) == 1
    finally:
        store.close()


def test_external_round_trip_event_sequence_matches_coordinator(tmp_path):
    program = parse_program(TWO_STEP_PROGRAM)

    store1 = EventStore(str(tmp_path / "coordinator.db"))
    try:
        from tahoe.runtime import DeterministicWorker

        worker = DeterministicWorker({
            "define": lambda **kwargs: {"plan": "frame and locate"},
            "calculate": lambda **kwargs: 12,
        })
        SequentialCoordinator(store1, worker).execute(program, run_id="r1")
        coordinator_types = [
            event.event_type.value for event in store1.events("r1")
        ]
    finally:
        store1.close()

    store2 = EventStore(str(tmp_path / "driver.db"))
    try:
        driver = ExternalDriver(store2, program, "r1")
        envelope = driver.next_envelope()
        driver.submit_result(ResultEnvelope(
            schema_version=ENVELOPE_SCHEMA_VERSION,
            run_id=envelope.run_id,
            invocation_id=envelope.invocation_id,
            task_id=envelope.task_id,
            attempt=envelope.attempt,
            idempotency_key=envelope.idempotency_key,
            command=envelope.command,
            status="succeeded",
            payload={"plan": "frame and locate"},
            evidence=(),
            error=None,
            receipt={},
        ))
        envelope = driver.next_envelope()
        driver.submit_result(ResultEnvelope(
            schema_version=ENVELOPE_SCHEMA_VERSION,
            run_id=envelope.run_id,
            invocation_id=envelope.invocation_id,
            task_id=envelope.task_id,
            attempt=envelope.attempt,
            idempotency_key=envelope.idempotency_key,
            command=envelope.command,
            status="succeeded",
            payload=12,
            evidence=(),
            error=None,
            receipt={},
        ))
        driver_types = [
            event.event_type.value for event in store2.events("r1")
        ]
        assert driver_types == coordinator_types
        # RESULT_RECEIVED carries the driver's additive receipt/evidence
        # keys alongside the coordinator's result payload.
        received = [
            event.payload for event in store2.events("r1")
            if event.event_type is EventType.RESULT_RECEIVED
        ]
        assert received[0]["result"] == {"plan": "frame and locate"}
        assert received[1]["result"] == 12
    finally:
        store2.close()


def test_submit_rejects_duplicate_result(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")
    envelope = _next(tmp_path, program, digest, db, capsys)
    result = _result_file(envelope, {"plan": "ok"}, tmp_path)
    assert main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-1", "--result-file", result,
    ]) == 0
    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-1", "--result-file", result,
    ])
    assert rc == 1
    assert "duplicate submission" in capsys.readouterr().err


def test_submit_rejects_malformed_result_without_appending(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")
    _next(tmp_path, program, digest, db, capsys)
    store = EventStore(db)
    try:
        before = len(store.events("r1"))
    finally:
        store.close()

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-1", "--result-file", str(bad),
    ])
    assert rc == 1
    assert "malformed result envelope" in capsys.readouterr().err

    store = EventStore(db)
    try:
        assert len(store.events("r1")) == before
    finally:
        store.close()


def test_submit_rejects_stale_idempotency_key(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")
    envelope = _next(tmp_path, program, digest, db, capsys)
    result = _result_file(
        envelope, {"plan": "ok"}, tmp_path, idempotency_key="r1:inv-9"
    )
    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-1", "--result-file", result,
    ])
    assert rc == 1
    assert "stale result" in capsys.readouterr().err


def test_submit_rejects_stale_attempt(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")
    envelope = _next(tmp_path, program, digest, db, capsys)
    result = _result_file(envelope, {"plan": "ok"}, tmp_path, attempt=2)
    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-1", "--result-file", result,
    ])
    assert rc == 1
    assert "stale attempt" in capsys.readouterr().err


def test_failed_result_fails_run_and_audit_stays_clean(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")
    envelope = _next(tmp_path, program, digest, db, capsys)
    result = _result_file(
        envelope, None, tmp_path, status="failed", error="backend 500"
    )
    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-1", "--result-file", result,
    ])
    assert rc == 0
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["run_status"] == "failed"

    store = EventStore(db)
    try:
        events = store.events("r1")
        assert events[-1].event_type is EventType.RUN_FINISHED
        assert events[-1].payload["status"] == "failed"
        assert events[-1].payload["error"] == "backend 500"
        assert any(
            event.event_type is EventType.FAILED for event in events
        )
        assert audit_run(store, "r1").ok
        ledger = store.task_ledger("r1")
        assert all(
            task.status.value in ("cancelled", "completed")
            for task in ledger.tasks.values()
        )
    finally:
        store.close()

    # A terminal run accepts neither further results nor further work.
    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-2", "--result-file", result,
    ])
    assert rc == 1
    assert "terminal" in capsys.readouterr().err
    rc = main([
        "next", "--db", db, "--run-id", "r1",
        "--program", program, "--seal", digest,
    ])
    assert rc == 1
    assert "terminal" in capsys.readouterr().err


def test_done_predicate_failure_fails_run_with_validation_event(
    tmp_path, capsys
):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")
    env1 = _next(tmp_path, program, digest, db, capsys)
    _write_result_and_submit(env1, {"plan": "ok"}, db, tmp_path, capsys)
    env2 = _next(tmp_path, program, digest, db, capsys)
    # Step 2's DONE predicate demands OUT.total == 12; submit 13.
    result = _result_file(env2, 13, tmp_path)
    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-2", "--result-file", result,
    ])
    assert rc == 0  # submission accepted; the RUN fails semantically
    store = EventStore(db)
    try:
        events = store.events("r1")
        types = [event.event_type for event in events]
        assert EventType.VALIDATION_FAILED in types
        assert EventType.FAILED in types
        assert events[-1].payload["status"] == "failed"
        assert "DONE predicate failed" in events[-1].payload["error"]
        assert audit_run(store, "r1").ok
    finally:
        store.close()


def _write_result_and_submit(envelope, payload, db, tmp_path, capsys):
    result = _result_file(envelope, payload, tmp_path)
    rc = main([
        "submit", "--db", db, "--run-id", envelope.run_id,
        "--invocation-id", envelope.invocation_id,
        "--result-file", result,
    ])
    assert rc == 0, capsys.readouterr().err
    capsys.readouterr()  # drain the submit outcome from the capture


def test_blocked_result_finishes_run_blocked(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")
    envelope = _next(tmp_path, program, digest, db, capsys)
    result = _result_file(
        envelope, None, tmp_path, status="blocked", error="awaiting credentials"
    )
    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-1", "--result-file", result,
    ])
    assert rc == 0
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["run_status"] == "blocked"
    store = EventStore(db)
    try:
        events = store.events("r1")
        assert events[-1].payload["status"] == "blocked"
        assert events[-1].payload["reason"] == "awaiting credentials"
        assert any(
            event.event_type is EventType.BLOCKED for event in events
        )
        assert audit_run(store, "r1").ok
    finally:
        store.close()


def test_receipt_usage_is_recorded_in_the_ledger(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")
    envelope = _next(tmp_path, program, digest, db, capsys)
    _write_result_and_submit(envelope, {"plan": "ok"}, db, tmp_path, capsys)
    store = EventStore(db)
    try:
        profile = store.task_ledger("r1").profile()
        assert profile["tasks"]["task-1"]["tokens"] == 25
    finally:
        store.close()


def test_driver_rejects_non_plain_programs(tmp_path):
    program_text = """\
PROGRAM conditional_prog VERSION 1.0
INPUT
    G.flag = "on"
step.frame: DO define(request = G.flag) -> G.plan
IF G.plan == "stop" STOP blocked(G.plan)
RETURN G.plan
"""
    program = parse_program(program_text)
    store = EventStore(str(tmp_path / "events.db"))
    try:
        driver = ExternalDriver(store, program, "r1")
        with pytest.raises(DriverError, match="plain sequential DO steps"):
            driver.next_envelope()
    finally:
        store.close()


# --------------------------------------------------- additive versioning (#44)


def test_task_envelope_from_json_tolerates_unknown_field():
    """v1 envelope with an unknown field parses under the v1.x additive
    compat policy; unknown fields are dropped on read."""
    envelope = _make_task_envelope()
    data = json.loads(envelope.to_json())
    data["future_field"] = {"renewed_at": "2026-09-12T12:00:00Z"}
    restored = TaskEnvelope.from_json(json.dumps(data))
    assert restored == envelope


def test_result_envelope_from_json_tolerates_unknown_field():
    """v1 result envelope with an unknown field parses under the additive
    compat policy; unknown fields are dropped on read."""
    envelope = _make_result_envelope()
    data = json.loads(envelope.to_json())
    data["future_usage_detail"] = {"gpu_seconds": 42.0}
    restored = ResultEnvelope.from_json(json.dumps(data))
    assert restored == envelope


def test_schema_version_2_fails_with_versioned_error():
    """schema_version != '1' fails, naming the supported version."""
    data = json.loads(_make_task_envelope().to_json())
    data["schema_version"] = "2"
    with pytest.raises(
        EnvelopeValidationError, match="supported version"
    ) as exc_info:
        TaskEnvelope.from_json(json.dumps(data))
    assert "'1'" in str(exc_info.value)


def test_strict_writer_roundtrip_unchanged():
    """Strict writer output parses identically before and after the
    additive policy change."""
    for envelope in (
        _make_task_envelope(),
        _make_result_envelope(),
        _make_result_envelope(
            status="failed", payload=None, error="backend down"
        ),
    ):
        wire = envelope.to_json()
        if isinstance(envelope, TaskEnvelope):
            restored = TaskEnvelope.from_json(wire)
        else:
            restored = ResultEnvelope.from_json(wire)
        assert restored == envelope
        assert json.loads(restored.to_json()) == json.loads(wire)
