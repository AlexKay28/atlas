"""Tests for the model worker adapter with tier-based routing (issue #8).

Contract under test (tikhon.worker_adapter.ModelWorker):

- Duck-type compatibility with ``DeterministicWorker``: ``.commands``
  (the registry's command names) and ``.execute(command, resolved_kwargs)``.
- Tier routing: the command contract's ``RoutingPolicy.preferred_tier``
  selects ``tier_models[tier]`` (string "T0".."T3" or ``RoutingTier``
  keys), falling back to ``default_model``.
- Prompt construction: contract preamble (purpose, inputs, outputs, done),
  resolved kwargs as JSON, and the strict reply-with-ONLY-JSON rule.
- Response handling: plain JSON, a single optional ```json fence, strict
  failure otherwise — ``WorkerError`` carrying the raw response tail
  (last 500 chars).
- Multi-target responses validated with the coordinator's own
  ``map_results_to_targets`` rules when targets are known.
- CLI: ``--worker model`` without environment configuration exits 1 with
  a clear error BEFORE run creation; ``--worker deterministic`` (the
  default) is unchanged.

All transports in this module are in-process stubs or local subprocesses;
no test touches a real network.
"""

import json
import subprocess
import sys

import pytest

from tikhon.cli import DETERMINISTIC_UNDER_MODEL, _HybridModelWorker, _build_model_worker, main
from tikhon.registry import builtin_registry
from tikhon.registry.enums import RoutingTier
from tikhon.runtime import EventStore, SequentialCoordinator
from tikhon.runtime.coordinator import map_results_to_targets
from tikhon.syntax import parse_program, seal_digest
from tikhon.worker_adapter import (
    DEFAULT_TIMEOUT_SECONDS,
    ModelWorker,
    TransportResult,
    WorkerError,
)

TIKHON_ENV_VARS = (
    "TIKHON_WORKER_TRANSPORT",
    "TIKHON_MODEL",
    "TIKHON_TIER_MODELS",
    "TIKHON_API_BASE",
    "TIKHON_API_KEY",
    "TIKHON_EXEC_COMMAND",
)


@pytest.fixture(autouse=True)
def _clean_tikhon_env(monkeypatch):
    for name in TIKHON_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def recording_transport(response='{"plan": "ok"}'):
    """Stub transport capturing (model, prompt) and returning a canned body."""
    calls: list[tuple[str, str]] = []

    def transport(model: str, prompt: str) -> str:
        calls.append((model, prompt))
        return response

    transport.calls = calls  # type: ignore[attr-defined]
    return transport


# ---------------------------------------------------------------- routing


def test_preferred_tier_selects_model_from_tier_models():
    transport = recording_transport()
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        tier_models={"T2": "model-t2", "T0": "model-t0", "T1": "model-t1"},
        default_model="fallback-model",
    )
    # define's contract declares preferred_tier T2.
    worker.execute("define", {"request": "frame this"})
    model, _ = transport.calls[-1]
    assert model == "model-t2"


def test_tier_models_accepts_enum_keys():
    transport = recording_transport()
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        tier_models={RoutingTier.T2: "enum-keyed-model"},
        default_model="fallback-model",
    )
    worker.execute("define", {"request": "frame this"})
    model, _ = transport.calls[-1]
    assert model == "enum-keyed-model"


def test_unmapped_tier_falls_back_to_default_model():
    transport = recording_transport()
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        tier_models={"T3": "only-t3"},
        default_model="fallback-model",
    )
    # search's contract declares preferred_tier T1, which is unmapped.
    worker.execute("search", {"query": "q"})
    model, _ = transport.calls[-1]
    assert model == "fallback-model"


def test_missing_model_everywhere_raises_worker_error():
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport(),
        tier_models={},
        default_model=None,
    )
    with pytest.raises(WorkerError, match="T1"):
        worker.execute("search", {"query": "q"})


def test_commands_property_returns_registry_names():
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport(),
        default_model="m",
    )
    assert worker.commands == set(builtin_registry().names())


# ----------------------------------------------------------------- prompt


def test_prompt_contains_contract_kwargs_and_json_only_instruction():
    transport = recording_transport()
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        tier_models={"T2": "m2"},
        default_model="m",
    )
    spec = builtin_registry().resolve("define")
    worker.execute("define", {"request": "frame the goal"})
    _, prompt = transport.calls[-1]
    assert spec.purpose in prompt
    assert "request:text" in prompt  # declared inputs
    assert spec.outputs[0] in prompt
    assert spec.done in prompt
    assert json.dumps({"request": "frame the goal"}, sort_keys=True) in prompt
    assert "Reply with ONLY a JSON object" in prompt


def test_prompt_names_target_refs_when_known():
    transport = recording_transport('{"a": 1, "b": 2}')
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        default_model="m",
    )
    worker.execute("search", {"query": "q"}, targets=("E.a", "E.b"))
    _, prompt = transport.calls[-1]
    assert "E.a" in prompt and "E.b" in prompt
    assert "unique leaf names" in prompt


# ------------------------------------------------------- response parsing


def test_plain_json_response_is_returned_parsed():
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport('{"k": [1, 2]}'),
        default_model="m",
    )
    assert worker.execute("define", {"request": "x"}) == {"k": [1, 2]}


def test_single_optional_json_fence_is_stripped():
    fenced = '```json\n{"a": 1}\n```'
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport(fenced),
        default_model="m",
    )
    assert worker.execute("define", {"request": "x"}) == {"a": 1}


def test_bare_fence_is_stripped():
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport('```\n[1, 2, 3]\n```'),
        default_model="m",
    )
    assert worker.execute("define", {"request": "x"}) == [1, 2, 3]


def test_invalid_json_raises_worker_error_with_raw_tail():
    tail_body = "x" * 700 + "FINAL-TAIL"
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport(f"almost {tail_body}"),
        default_model="m",
    )
    with pytest.raises(WorkerError) as excinfo:
        worker.execute("define", {"request": "x"})
    assert len(excinfo.value.tail) == 500
    assert excinfo.value.tail.endswith("FINAL-TAIL")
    assert "not valid JSON" in str(excinfo.value)


def test_non_string_response_raises_worker_error():
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=lambda model, prompt: None,  # type: ignore[return-value]
        default_model="m",
    )
    with pytest.raises(WorkerError, match="not text"):
        worker.execute("define", {"request": "x"})


# ----------------------------------------------------------- multi-target


def test_multi_target_leaf_keys_pass_map_results_to_targets():
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport('{"alpha": 1, "beta": 2}'),
        default_model="m",
    )
    targets = ("E.alpha", "E.beta")
    result = worker.execute("search", {"query": "q"}, targets=targets)
    target_values, error = map_results_to_targets(targets, result)
    assert error is None
    assert target_values == {"E.alpha": 1, "E.beta": 2}


def test_multi_target_missing_key_raises_worker_error():
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport('{"alpha": 1}'),
        default_model="m",
    )
    with pytest.raises(WorkerError) as excinfo:
        worker.execute("search", {"query": "q"}, targets=("E.alpha", "E.beta"))
    assert "missing result keys: E.beta" in str(excinfo.value)
    assert excinfo.value.tail == '{"alpha": 1}'


def test_multi_target_full_ref_keys_also_accepted():
    worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport('{"E.alpha": 10, "E.beta": 20}'),
        default_model="m",
    )
    result = worker.execute(
        "search", {"query": "q"}, targets=("E.alpha", "E.beta")
    )
    assert result == {"E.alpha": 10, "E.beta": 20}


# ------------------------------------------------------------ CLI: guard


def _write_program(tmp_path, text):
    path = tmp_path / "prog.think"
    path.write_text(text, encoding="utf-8")
    return path


SMALL_PROGRAM = """\
PROGRAM small VERSION 1.0
INPUT
    G.left = 5
    G.right = 7
step.calc: DO calculate(left = G.left, right = G.right) -> OUT.total
RETURN OUT.total
"""


def test_cli_model_worker_without_env_exits_before_run(tmp_path, capsys):
    program = _write_program(tmp_path, SMALL_PROGRAM)
    digest = seal_digest(parse_program(program.read_text(encoding="utf-8")))
    db = tmp_path / "events.db"
    rc = main(
        [
            "run", str(program), "--db", str(db), "--run-id", "r1",
            "--seal", digest, "--worker", "model",
        ]
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert "TIKHON_WORKER_TRANSPORT" in captured.err
    # Guard fired before run creation: the db carries zero events.
    store = EventStore(str(db))
    try:
        assert store.events("r1") == ()
    finally:
        store.close()


def test_cli_model_worker_resume_guard_exits_before_store(tmp_path, capsys):
    program = _write_program(tmp_path, SMALL_PROGRAM)
    digest = seal_digest(parse_program(program.read_text(encoding="utf-8")))
    rc = main(
        [
            "resume", "--db", str(tmp_path / "events.db"), "--run-id", "r1",
            "--program", str(program), "--seal", digest,
            "--worker", "model",
        ]
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert "TIKHON_WORKER_TRANSPORT" in captured.err


def test_cli_deterministic_baseline_unchanged(tmp_path, capsys):
    program = _write_program(tmp_path, SMALL_PROGRAM)
    digest = seal_digest(parse_program(program.read_text(encoding="utf-8")))
    db = tmp_path / "events.db"
    rc = main(
        [
            "run", str(program), "--db", str(db), "--run-id", "r1",
            "--seal", digest,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "succeeded" in captured.out
    # Explicit --worker deterministic behaves identically.
    db2 = tmp_path / "events2.db"
    rc2 = main(
        [
            "run", str(program), "--db", str(db2), "--run-id", "r2",
            "--seal", digest, "--worker", "deterministic",
        ]
    )
    assert rc2 == 0
    assert "succeeded" in capsys.readouterr().out


def test_cli_model_worker_rejects_bad_transport_env(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TIKHON_WORKER_TRANSPORT", "carrier-pigeon")
    program = _write_program(tmp_path, SMALL_PROGRAM)
    digest = seal_digest(parse_program(program.read_text(encoding="utf-8")))
    rc = main(
        [
            "run", str(program), "--db", str(tmp_path / "events.db"),
            "--run-id", "r1", "--seal", digest, "--worker", "model",
        ]
    )
    assert rc == 1
    assert "TIKHON_WORKER_TRANSPORT" in capsys.readouterr().err


def test_build_model_worker_http_requires_credentials(monkeypatch):
    monkeypatch.setenv("TIKHON_WORKER_TRANSPORT", "http")
    monkeypatch.setenv("TIKHON_MODEL", "m")
    with pytest.raises(ValueError, match="TIKHON_API_BASE"):
        _build_model_worker()


def test_build_model_worker_requires_some_model(monkeypatch):
    monkeypatch.setenv("TIKHON_WORKER_TRANSPORT", "exec")
    monkeypatch.setenv("TIKHON_EXEC_COMMAND", "true")
    with pytest.raises(ValueError, match="TIKHON_MODEL"):
        _build_model_worker()


def test_build_model_worker_exec_transport_runs_subprocess(monkeypatch):
    monkeypatch.setenv("TIKHON_WORKER_TRANSPORT", "exec")
    monkeypatch.setenv("TIKHON_MODEL", "stub-model")
    monkeypatch.setenv(
        "TIKHON_TIER_MODELS",
        json.dumps({"T0": "tier-zero-model"}),
    )
    printer = (
        "import json,sys; m=sys.argv[1]; p=sys.argv[2];"
        "print(json.dumps({'model_seen': m, 'prompt_len': len(p),"
        " 'prompt_tail': p[-100:]}))"
    )
    monkeypatch.setenv(
        "TIKHON_EXEC_COMMAND",
        json.dumps([sys.executable, "-c", printer, "{model}", "{prompt}"]),
    )
    worker = _build_model_worker()
    assert isinstance(worker, ModelWorker)
    result = worker.execute("calculate", {"left": 20, "right": 22})
    assert result["model_seen"] == "tier-zero-model"  # calculate prefers T0
    assert result["prompt_len"] > 200
    assert "single target any JSON value is acceptable" in result["prompt_tail"]


def test_exec_transport_nonzero_exit_raises(monkeypatch):
    monkeypatch.setenv("TIKHON_WORKER_TRANSPORT", "exec")
    monkeypatch.setenv("TIKHON_MODEL", "m")
    monkeypatch.setenv(
        "TIKHON_EXEC_COMMAND",
        json.dumps([sys.executable, "-c", "raise SystemExit(3)"]),
    )
    worker = _build_model_worker()
    with pytest.raises(RuntimeError, match="exited with 3"):
        worker.execute("define", {"request": "x"})


def test_build_model_worker_rejects_non_string_tier_mapping(monkeypatch):
    monkeypatch.setenv("TIKHON_WORKER_TRANSPORT", "exec")
    monkeypatch.setenv("TIKHON_MODEL", "m")
    monkeypatch.setenv("TIKHON_EXEC_COMMAND", "true")
    monkeypatch.setenv("TIKHON_TIER_MODELS", json.dumps({"T1": 42}))
    with pytest.raises(ValueError, match="TIKHON_TIER_MODELS"):
        _build_model_worker()


# --------------------------------------------------- deterministic hybrid


def test_hybrid_worker_routes_edit_deterministically(tmp_path):
    model_calls: list[str] = []

    def transport(model: str, prompt: str) -> str:
        model_calls.append(prompt)
        return "{}"

    model_worker = ModelWorker(
        registry=builtin_registry(), transport=transport, default_model="m"
    )
    from tikhon.cli import _deterministic_handlers
    from tikhon.runtime import DeterministicWorker

    workspace = tmp_path / "ws"
    workspace.mkdir()
    deterministic = DeterministicWorker(
        _deterministic_handlers(workspace_root=str(workspace))
    )
    hybrid = _HybridModelWorker(model_worker, deterministic)

    result = hybrid.execute(
        "edit",
        {"path": "note.txt", "content": "deterministic write"},
    )
    assert result == "note.txt"
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "deterministic write"
    assert model_calls == []  # the model was never consulted for edit


def test_hybrid_worker_routes_other_commands_to_model():
    model_worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport('{"plan": "from-model"}'),
        default_model="m",
    )
    from tikhon.cli import _deterministic_handlers
    from tikhon.runtime import DeterministicWorker

    hybrid = _HybridModelWorker(
        model_worker, DeterministicWorker(_deterministic_handlers())
    )
    assert hybrid.commands == model_worker.commands | set(
        _deterministic_handlers()
    )
    assert hybrid.execute("define", {"request": "x"}) == {"plan": "from-model"}
    assert "edit" in DETERMINISTIC_UNDER_MODEL


def test_hybrid_worker_falls_back_to_model_for_unknown_deterministic_command():
    model_worker = ModelWorker(
        registry=builtin_registry(),
        transport=recording_transport('"model-result"'),
        default_model="m",
    )
    from tikhon.runtime import DeterministicWorker

    hybrid = _HybridModelWorker(model_worker, DeterministicWorker({}))
    # A command the deterministic side lacks routes to the model even if it
    # is in the deterministic-under-model set.
    assert hybrid.execute("review", {"artifact_refs": []}) == "model-result"


# -------------------------------------------------------------------- e2e


E2E_PROGRAM = """\
PROGRAM model_worker_e2e VERSION 1.0
INPUT
    G.topic = "tier routing"
    G.left = 5
    G.right = 7
step.frame: DO define(request = G.topic) -> G.plan
step.total: DO calculate(left = G.left, right = G.right) -> OUT.total
DONE OUT.total == 12
RETURN G.plan, OUT.total
"""


def test_model_worker_drives_two_step_program_through_coordinator(tmp_path):
    def transport(model: str, prompt: str) -> str:
        if "Command: define" in prompt:
            assert model == "tier-two-model"
            # Single-target step: the response is the value itself (the
            # coordinator's mapping binds any JSON value to the target).
            return '```json\n"two steps"\n```'
        if "Command: calculate" in prompt:
            assert model == "tier-zero-model"
            return "12"
        raise AssertionError(f"unexpected prompt: {prompt[:80]}")

    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        tier_models={"T2": "tier-two-model", "T0": "tier-zero-model"},
        default_model="unused",
    )
    store = EventStore(str(tmp_path / "events.db"))
    try:
        coordinator = SequentialCoordinator(store, worker)
        program = parse_program(E2E_PROGRAM)
        result = coordinator.execute(program, run_id="e2e")
        assert result["status"] == "succeeded"
        assert result["outputs"] == {"G.plan": "two steps", "OUT.total": 12}

        events = store.events("e2e")
        types = [event.event_type.value for event in events]
        assert types[0] == "run.started"
        assert types[-1] == "run.finished"
        assert types.count("invocation.succeeded") == 2
        assert types.count("invocation.validation_passed") == 2
        results = [
            event.payload["result"]
            for event in events
            if event.event_type.value == "invocation.result_received"
        ]
        assert results[0] == "two steps"
        assert 12 in results
        assert DEFAULT_TIMEOUT_SECONDS == 120.0
    finally:
        store.close()


# ------------------------------------------ issue #43: transport usage seam

def test_transport_result_carries_usage_tokens_into_receipt():
    """Acceptance (1): TransportResult(text, {"tokens": 123}) → receipt tokens == 123."""

    def transport(model: str, prompt: str) -> TransportResult:
        return TransportResult(text='{"k": 1}', usage={"tokens": 123})

    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        default_model="m",
    )
    worker.execute("define", {"request": "x"})
    assert worker.last_result_envelope is not None
    receipt = worker.last_result_envelope.receipt
    assert receipt["usage"]["tokens"] == 123


def test_legacy_str_transport_yields_none_tokens():
    """Acceptance (2): legacy str-returning transport → receipt tokens None."""

    def transport(model: str, prompt: str) -> str:
        return '{"k": 1}'

    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        default_model="m",
    )
    worker.execute("define", {"request": "x"})
    assert worker.last_result_envelope is not None
    receipt = worker.last_result_envelope.receipt
    assert receipt["usage"]["tokens"] is None
    assert receipt["usage"]["cost"] is None


def test_transport_result_with_none_usage_yields_none_tokens():
    """TransportResult with usage=None should behave like legacy str."""

    def transport(model: str, prompt: str) -> TransportResult:
        return TransportResult(text='{"k": 1}', usage=None)

    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        default_model="m",
    )
    worker.execute("define", {"request": "x"})
    assert worker.last_result_envelope is not None
    receipt = worker.last_result_envelope.receipt
    assert receipt["usage"]["tokens"] is None


def test_transport_result_with_non_integer_tokens_yields_none():
    """Non-integer tokens in usage dict should not corrupt the receipt."""

    def transport(model: str, prompt: str) -> TransportResult:
        return TransportResult(text='{"k": 1}', usage={"tokens": "not-a-number"})

    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        default_model="m",
    )
    worker.execute("define", {"request": "x"})
    assert worker.last_result_envelope is not None
    receipt = worker.last_result_envelope.receipt
    assert receipt["usage"]["tokens"] is None


def test_transport_result_payload_parsed_correctly():
    """TransportResult text is parsed as JSON, same as legacy str."""

    def transport(model: str, prompt: str) -> TransportResult:
        return TransportResult(text='{"answer": 42}', usage={"tokens": 7})

    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        default_model="m",
    )
    result = worker.execute("define", {"request": "x"})
    assert result == {"answer": 42}
    assert worker.last_result_envelope is not None
    assert worker.last_result_envelope.receipt["usage"]["tokens"] == 7


def test_transport_result_with_json_fence_stripped():
    """TransportResult text with json fence is stripped, same as legacy str."""

    def transport(model: str, prompt: str) -> TransportResult:
        return TransportResult(text='```json\n{"a": 1}\n```', usage={"tokens": 99})

    worker = ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        default_model="m",
    )
    assert worker.execute("define", {"request": "x"}) == {"a": 1}
    assert worker.last_result_envelope is not None
    assert worker.last_result_envelope.receipt["usage"]["tokens"] == 99
