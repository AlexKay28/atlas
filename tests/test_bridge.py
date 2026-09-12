"""Tests for the external-driver claim bridge (issue #19).

Contract under test (tikhon.bridge + its CLI bindings):

- ``ready``/``claim`` render the next ready invocation's TaskEnvelope and
  record an INVOCATION_CLAIMED event (fencing token, claimed_at, envelope
  digest, claimant, 1-based claim attempt) on top of the Wave 8 external
  driver; a claimed-but-unsubmitted invocation is not handed out again
  while the claim is fresh.
- A claim older than the timeout is dead: ready re-issues it (fresh
  INVOCATION_DISPATCHED so the envelope attempt increments, plus a new
  INVOCATION_CLAIMED with a new token and claim_attempt+1); the old
  token and the old envelope attempt then reject at submit.
- ``submit --claim-token`` validates the open claim (existence, token,
  freshness) and only then commits through the unchanged Wave 8 path
  (RESULT_RECEIVED -> VALIDATION/SUCCEEDED or the atomic failure batch).
  Rejections append nothing.
- A terminal run answers ready with the recorded terminal status and
  accepts no further submissions.
- The coordinator-driven path is unaffected: resume re-executes a
  claimed-but-unsubmitted invocation (claims are an additive overlay)
  and the bridge-driven run's projection matches a coordinator-driven
  run for equivalent inputs.

No test touches a real network or an external worker process.
"""

import json

import pytest

from tikhon.audit import audit_run
from tikhon.bridge import ClaimBridge, claim_from_event
from tikhon.cli import main
from tikhon.envelope import (
    ENVELOPE_SCHEMA_VERSION,
    DriverError,
    ExternalDriver,
    ResultEnvelope,
)
from tikhon.registry import builtin_registry
from tikhon.resume import resume_run
from tikhon.runtime import (
    DeterministicWorker,
    EventStore,
    EventType,
    SequentialCoordinator,
)
from tikhon.syntax import parse_program, seal_digest


TWO_STEP_PROGRAM = """\
PROGRAM bridge_round_trip VERSION 1.0
INPUT
    G.topic = "claims"
    G.left = 5
    G.right = 7
step.frame: DO define(request = G.topic) -> G.plan
step.total: DO calculate(left = G.left, right = G.right) -> OUT.total
DONE OUT.total == 12
RETURN G.plan, OUT.total
"""


def _result_for(
    envelope, payload, *, status="succeeded", error=None, attempt=None
) -> ResultEnvelope:
    return ResultEnvelope(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        run_id=envelope.run_id,
        invocation_id=envelope.invocation_id,
        task_id=envelope.task_id,
        attempt=envelope.attempt if attempt is None else attempt,
        idempotency_key=envelope.idempotency_key,
        command=envelope.command,
        status=status,
        payload=payload,
        evidence=(),
        error=error if error is not None else (
            None if status == "succeeded" else "worker reported failure"
        ),
        receipt={"worker": "fake-agent", "usage": {"tokens": 7}},
    )


def _drive_step(bridge: ClaimBridge, payload) -> dict:
    """One fake-agent step: ready -> craft result -> submit."""
    handout = bridge.ready()
    assert handout["ready"] is True
    envelope = handout["envelope"]
    from tikhon.envelope import TaskEnvelope

    task = TaskEnvelope.from_dict(envelope)
    return bridge.submit(
        _result_for(task, payload), claim_token=handout["claim"]["claim_token"]
    )


def _events_of_type(store: EventStore, run_id: str, event_type: EventType):
    return [
        event
        for event in store.events(run_id)
        if event.event_type is event_type
    ]


@pytest.fixture()
def two_step(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    program = parse_program(TWO_STEP_PROGRAM)
    driver = ExternalDriver(store, program, "r1", registry=builtin_registry())
    yield store, driver
    store.close()


# ------------------------------------------------------- claim -> submit


def test_claim_submit_round_trip_drives_two_step_program(two_step):
    store, driver = two_step
    bridge = ClaimBridge(driver)
    first = _drive_step(bridge, {"plan": "framed externally"})
    assert first == {
        "run_id": "r1", "invocation_id": "inv-1",
        "recorded": True, "run_status": "in_progress",
    }
    second = _drive_step(bridge, 12)
    assert second["run_status"] == "succeeded"

    events = store.events("r1")
    assert events[-1].event_type is EventType.RUN_FINISHED
    assert events[-1].payload == {"status": "succeeded"}
    # The external fake agent performed the reasoning steps: no worker
    # executed anything in-process, yet the run is terminal succeeded
    # with the coordinator's exact validation/commit event shapes.
    assert audit_run(store, "r1").ok
    ledger = store.task_ledger("r1")
    assert all(
        task.status.value == "completed" for task in ledger.tasks.values()
    )
    state = store.project_state("r1")
    assert state["nodes"]["G.plan"]["value"] == {"plan": "framed externally"}
    assert state["nodes"]["OUT.total"]["value"] == 12


def test_ready_records_claim_event_with_token_digest_and_attempt(two_step):
    store, driver = two_step
    bridge = ClaimBridge(driver)
    handout = bridge.ready(claimant="opencode-agent")
    assert handout["ready"] is True
    claim = handout["claim"]
    assert claim["claimant"] == "opencode-agent"
    assert claim["claim_attempt"] == 1
    assert len(claim["claim_token"]) == 32
    assert claim["claimed_at"].endswith("+00:00")
    assert (
        handout["envelope"]["invocation_id"] == claim["invocation_id"]
    )

    claimed = _events_of_type(store, "r1", EventType.INVOCATION_CLAIMED)
    assert len(claimed) == 1
    event = claimed[0]
    assert event.invocation_id == "inv-1"
    assert event.attempt == 1
    parsed = claim_from_event(event)
    assert parsed.claim_token == claim["claim_token"]
    assert parsed.claimant == "opencode-agent"
    assert parsed.claim_attempt == 1
    assert parsed.invocation_id == "inv-1"
    assert len(parsed.envelope_digest) == 64


def test_fresh_claim_is_not_handed_out_twice(two_step):
    store, driver = two_step
    bridge = ClaimBridge(driver)
    first = bridge.ready()
    second = bridge.ready()
    assert second["ready"] is False
    assert second["invocation_id"] == first["claim"]["invocation_id"]
    assert (
        second["claim"]["claim_token"]
        == first["claim"]["claim_token"]
    )
    assert "envelope" not in second
    # No second claim, no second dispatch, nothing new at all.
    assert len(_events_of_type(store, "r1", EventType.INVOCATION_CLAIMED)) == 1
    before = len(store.events("r1"))
    assert bridge.ready()["ready"] is False
    assert len(store.events("r1")) == before


def test_anonymous_ready_records_null_claimant(two_step):
    _, driver = two_step
    handout = ClaimBridge(driver).ready()
    assert handout["claim"]["claimant"] is None


# --------------------------------------------------------- stale claims


def test_stale_claim_is_reissued_with_new_token_and_attempt(two_step):
    store, driver = two_step
    stale_bridge = ClaimBridge(driver, claim_timeout_seconds=0.0)
    first = stale_bridge.ready()
    assert first["ready"] is True

    second = stale_bridge.ready()
    assert second["ready"] is True
    assert (
        second["claim"]["claim_token"]
        != first["claim"]["claim_token"]
    )
    assert second["claim"]["claim_attempt"] == 2
    assert second["envelope"]["attempt"] == 2
    assert len(_events_of_type(store, "r1", EventType.INVOCATION_CLAIMED)) == 2
    assert len(_events_of_type(
        store, "r1", EventType.INVOCATION_DISPATCHED
    )) == 2

    # The old token rejects against the re-issued open claim...
    from tikhon.envelope import TaskEnvelope

    old_task = TaskEnvelope.from_dict(first["envelope"])
    before = len(store.events("r1"))
    with pytest.raises(DriverError, match="claim token mismatch"):
        stale_bridge.submit(
            _result_for(old_task, {"plan": "late"}), claim_token=(
                first["claim"]["claim_token"]
            )
        )
    # ...and the old envelope's echoed attempt rejects even with the
    # new claimant's token.  Neither rejection appended anything.
    fresh_bridge = ClaimBridge(driver)
    with pytest.raises(DriverError, match="stale attempt"):
        fresh_bridge.submit(
            _result_for(old_task, {"plan": "late"}),
            claim_token=second["claim"]["claim_token"],
        )
    assert len(store.events("r1")) == before

    # The new claimant submits with the new token and attempt echo.
    new_task = TaskEnvelope.from_dict(second["envelope"])
    outcome = fresh_bridge.submit(
        _result_for(new_task, {"plan": "fresh"}),
        claim_token=second["claim"]["claim_token"],
    )
    assert outcome["run_status"] == "in_progress"
    assert audit_run(store, "r1").ok


def test_expired_claim_rejected_at_submit_with_nothing_appended(two_step):
    store, driver = two_step
    stale_bridge = ClaimBridge(driver, claim_timeout_seconds=0.0)
    handout = stale_bridge.ready()
    token = handout["claim"]["claim_token"]
    from tikhon.envelope import TaskEnvelope

    task = TaskEnvelope.from_dict(handout["envelope"])
    before = len(store.events("r1"))
    with pytest.raises(DriverError, match="expired"):
        stale_bridge.submit(_result_for(task, {"plan": "x"}), claim_token=token)
    assert len(store.events("r1")) == before


# --------------------------------------------------------- fencing rejections


def test_wrong_token_rejected_and_nothing_appended(two_step):
    store, driver = two_step
    bridge = ClaimBridge(driver)
    handout = bridge.ready()
    from tikhon.envelope import TaskEnvelope

    task = TaskEnvelope.from_dict(handout["envelope"])
    before = len(store.events("r1"))
    with pytest.raises(DriverError, match="claim token mismatch"):
        bridge.submit(
            _result_for(task, {"plan": "ok"}), claim_token="f" * 32
        )
    assert len(store.events("r1")) == before
    # Nothing corrupted: the real claimant still completes the step.
    outcome = bridge.submit(
        _result_for(task, {"plan": "ok"}),
        claim_token=handout["claim"]["claim_token"],
    )
    assert outcome["recorded"] is True


def test_submit_without_open_claim_rejected(two_step):
    _, driver = two_step
    bridge = ClaimBridge(driver)
    task = driver.next_envelope()  # dispatched by the claim-less Wave 8 path
    with pytest.raises(DriverError, match="no open claim"):
        bridge.submit(
            _result_for(task, {"plan": "ok"}), claim_token="whatever"
        )


def test_empty_claim_token_rejected(two_step):
    _, driver = two_step
    bridge = ClaimBridge(driver)
    from tikhon.envelope import TaskEnvelope

    handout = bridge.ready()
    task = TaskEnvelope.from_dict(handout["envelope"])
    with pytest.raises(DriverError, match="nonempty"):
        bridge.submit(_result_for(task, {"plan": "ok"}), claim_token="")


# ------------------------------------------------------------- terminal runs


def test_terminal_run_reports_terminal_and_accepts_nothing(two_step):
    store, driver = two_step
    bridge = ClaimBridge(driver)
    _drive_step(bridge, {"plan": "framed"})
    _drive_step(bridge, 12)

    terminal = bridge.ready()
    assert terminal == {
        "terminal": True, "run_id": "r1", "status": "succeeded",
    }
    late_result = ResultEnvelope(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        run_id="r1", invocation_id="inv-2", task_id="task-2",
        attempt=1, idempotency_key="r1:inv-2", command="calculate",
        status="succeeded", payload=12, evidence=(), error=None,
        receipt={},
    )
    with pytest.raises(DriverError, match="terminal"):
        bridge.submit(late_result, claim_token="x")
    before = len(store.events("r1"))
    assert bridge.ready()["terminal"] is True
    assert len(store.events("r1")) == before


# ----------------------------------------------------------- CLI bindings


def _write(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _ready(tmp_path, program, digest, db, capsys, *extra):
    rc = main([
        "ready", "--db", db, "--run-id", "r1",
        "--program", program, "--seal", digest, *extra,
    ])
    assert rc == 0, capsys.readouterr().err
    return json.loads(capsys.readouterr().out)


def _result_file(envelope, payload, tmp_path, name="result.json") -> str:
    data = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "run_id": envelope["run_id"],
        "invocation_id": envelope["invocation_id"],
        "task_id": envelope["task_id"],
        "attempt": envelope["attempt"],
        "idempotency_key": envelope["idempotency_key"],
        "command": envelope["command"],
        "status": "succeeded",
        "payload": payload,
        "evidence": [],
        "error": None,
        "receipt": {"worker": "fake-agent", "usage": {"tokens": 9}},
    }
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _submit_cli(tmp_path, db, envelope, payload, token, capsys):
    result = _result_file(envelope, payload, tmp_path)
    rc = main([
        "submit", "--db", db, "--run-id", envelope["run_id"],
        "--invocation-id", envelope["invocation_id"],
        "--result-file", result, "--claim-token", token,
    ])
    assert rc == 0, capsys.readouterr().err
    return json.loads(capsys.readouterr().out)


def test_cli_ready_claim_submit_round_trip(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")

    first = _ready(tmp_path, program, digest, db, capsys)
    assert first["ready"] is True
    assert first["envelope"]["command"] == "define"
    assert first["claim"]["claimant"] is None
    outcome = _submit_cli(
        tmp_path, db, first["envelope"], {"plan": "framed"},
        first["claim"]["claim_token"], capsys,
    )
    assert outcome["run_status"] == "in_progress"

    second = _ready(tmp_path, program, digest, db, capsys)
    assert second["envelope"]["invocation_id"] == "inv-2"
    outcome = _submit_cli(
        tmp_path, db, second["envelope"], 12,
        second["claim"]["claim_token"], capsys,
    )
    assert outcome["run_status"] == "succeeded"

    # A terminal run answers ready with the recorded status, exit 0.
    terminal = _ready(tmp_path, program, digest, db, capsys)
    assert terminal == {"terminal": True, "run_id": "r1",
                        "status": "succeeded"}

    store = EventStore(db)
    try:
        assert audit_run(store, "r1").ok
        assert len(
            _events_of_type(store, "r1", EventType.INVOCATION_CLAIMED)
        ) == 2
    finally:
        store.close()


def test_cli_claim_records_claimant_and_double_claim_waits(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")

    first = _ready(tmp_path, program, digest, db, capsys)
    # Second driver claims by name while the first claim is fresh.
    rc = main([
        "claim", "--db", db, "--run-id", "r1",
        "--program", program, "--seal", digest,
        "--claimant", "competitor-agent",
    ])
    assert rc == 0, capsys.readouterr().err
    second = json.loads(capsys.readouterr().out)
    assert second["ready"] is False
    assert second["claim"]["claimant"] is None  # the FRESH claim holder
    assert second["claim"]["claim_token"] == first["claim"]["claim_token"]

    # The named claimant path records the name once it holds the claim.
    outcome = _submit_cli(
        tmp_path, db, first["envelope"], {"plan": "framed"},
        first["claim"]["claim_token"], capsys,
    )
    assert outcome["recorded"] is True
    rc = main([
        "claim", "--db", db, "--run-id", "r1",
        "--program", program, "--seal", digest,
        "--claimant", "worker-2",
    ])
    assert rc == 0, capsys.readouterr().err
    named = json.loads(capsys.readouterr().out)
    assert named["ready"] is True
    assert named["invocation_id"] == "inv-2"
    assert named["claim"]["claimant"] == "worker-2"
    store = EventStore(db)
    try:
        claims = _events_of_type(store, "r1", EventType.INVOCATION_CLAIMED)
        assert len(claims) == 2
        assert claim_from_event(claims[1]).claimant == "worker-2"
    finally:
        store.close()


def test_cli_submit_wrong_token_rejected_without_appending(tmp_path, capsys):
    program = _write(tmp_path, "prog.think", TWO_STEP_PROGRAM)
    digest = seal_digest(parse_program(TWO_STEP_PROGRAM))
    db = str(tmp_path / "events.db")
    handout = _ready(tmp_path, program, digest, db, capsys)
    result = _result_file(handout["envelope"], {"plan": "ok"}, tmp_path)

    store = EventStore(db)
    try:
        before = len(store.events("r1"))
    finally:
        store.close()

    rc = main([
        "submit", "--db", db, "--run-id", "r1",
        "--invocation-id", "inv-1", "--result-file", result,
        "--claim-token", "not-the-token",
    ])
    assert rc == 1
    assert "claim token mismatch" in capsys.readouterr().err

    store = EventStore(db)
    try:
        assert len(store.events("r1")) == before
    finally:
        store.close()


# ------------------------------------------------- coordinator-path overlay


def test_resume_reexecutes_claimed_invocation(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    try:
        program = parse_program(TWO_STEP_PROGRAM)
        driver = ExternalDriver(
            store, program, "r1", registry=builtin_registry()
        )
        bridge = ClaimBridge(driver)
        handout = bridge.ready()
        assert handout["ready"] is True  # claimed, never submitted

        result = resume_run(
            store,
            DeterministicWorker({
                "define": lambda **kwargs: {"plan": "resumed"},
                "calculate": lambda **kwargs: 12,
            }),
            "r1",
            program,
        )
        assert result["status"] == "succeeded"
        assert result.get("already_terminal") is not True
        # Claims are an additive overlay: the coordinator ignored them,
        # re-executed the claimed invocation, and the run is truthful.
        events = store.events("r1")
        assert any(
            event.event_type is EventType.INVOCATION_CLAIMED
            for event in events
        )
        assert events[-1].payload == {"status": "succeeded"}
        assert audit_run(store, "r1").ok
        state = store.project_state("r1")
        assert state["nodes"]["OUT.total"]["value"] == 12
    finally:
        store.close()


def test_bridge_projection_matches_coordinator_path(tmp_path):
    program = parse_program(TWO_STEP_PROGRAM)

    store1 = EventStore(str(tmp_path / "coordinator.db"))
    try:
        worker = DeterministicWorker({
            "define": lambda **kwargs: {"plan": "same"},
            "calculate": lambda **kwargs: 12,
        })
        SequentialCoordinator(store1, worker).execute(program, run_id="r1")
        coordinator_state = store1.project_state("r1")
    finally:
        store1.close()

    store2 = EventStore(str(tmp_path / "bridge.db"))
    try:
        driver = ExternalDriver(
            store2, program, "r1", registry=builtin_registry()
        )
        bridge = ClaimBridge(driver)
        _drive_step(bridge, {"plan": "same"})
        _drive_step(bridge, 12)
        bridge_state = store2.project_state("r1")
        assert bridge_state["nodes"] == coordinator_state["nodes"]
        assert bridge_state["state_version"] == (
            coordinator_state["state_version"]
        )
        assert audit_run(store2, "r1").ok
    finally:
        store2.close()
