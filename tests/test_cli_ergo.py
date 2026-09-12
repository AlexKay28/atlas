"""CLI ergonomics tests for issue #48.

Tests:
  (1) --json outputs parse with python3 -m json.tool for all five commands;
  (2) one test per exit code (0/1/2/3/4);
  (3) run without --seal fails at argparse (exit 2, usage shown);
  (4) seal --check correct -> 0, tampered -> 4;
  (5) existing suite green (this file is part of it).
"""

import json
import re
import subprocess
import sys

import pytest

from atlas.cli import _deterministic_handlers, main
from atlas.runtime import (
    DeterministicWorker,
    EventStore,
    EventType,
    SequentialCoordinator,
)
from atlas.syntax import parse_program

CANONICAL = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {"request": "ship"}

step.one: DO define(value = G.goal) -> E.result

RETURN E.result
"""

TWO_STEP = """\
PROGRAM demo2 VERSION 0.1

INPUT
  G.goal = "test"

step.one: DO define(value = G.goal) -> E.result
step.two: DO verify(goal = G.goal, evidence = E.result) -> V.result

RETURN E.result, V.result
"""

DIGEST_RE = re.compile(r"\b[0-9a-f]{64}\b")

RUN_ID = "run-ergo-1"

# Inlined from test_audit.py for self-contained violation tests.
_RAISE_PROGRAM = """\
PROGRAM audit_boom VERSION 1.0

step.boom: DO boom(x = 1) -> E.r

RETURN E.r
"""

_SUCCEED_PROGRAM = """\
PROGRAM audit_ok VERSION 1.0

INPUT
    G.goal = "produce two clean results"

step.frame: DO define(request = G.goal) -> G.plan
step.act: DO search(query = G.plan) -> E.hits

RETURN G.plan, E.hits
"""

_AUDIT_RUN_ID = "run-1"


def _boom_handlers():
    handlers = _deterministic_handlers()
    def _boom(**kwargs):
        raise RuntimeError("kaput")
    handlers["boom"] = _boom
    return handlers


def _execute(store, program_text, run_id=_AUDIT_RUN_ID, handlers=None):
    program = parse_program(program_text)
    worker = DeterministicWorker(
        handlers if handlers is not None else _deterministic_handlers()
    )
    coordinator = SequentialCoordinator(store, worker)
    return coordinator.execute(program, run_id=run_id)


def _events_of_type(store, run_id, event_type):
    return [ev for ev in store.events(run_id) if ev.event_type is event_type]


def _write(tmp_path, text=CANONICAL, name="demo.think"):
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


def _run_program(tmp_path, capsys, text=CANONICAL):
    program = _write(tmp_path, text)
    db = tmp_path / "events.db"
    digest = _seal_of(tmp_path, capsys)
    rc = main([
        "run", str(program), "--db", str(db),
        "--run-id", RUN_ID, "--seal", digest,
    ])
    assert rc == 0
    capsys.readouterr()
    return db, digest


# -- (1) --json outputs parse for all five commands ---------------------


def test_json_status_parses(tmp_path, capsys):
    db, _ = _run_program(tmp_path, capsys)
    rc = main(["status", "--db", str(db), "--run-id", RUN_ID, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "percent_complete" in data
    assert data["percent_complete"] == 100.0
    assert data["run_id"] == RUN_ID
    assert data["completed"] == 1
    assert data["total"] == 1


def test_json_audit_parses(tmp_path, capsys):
    db, _ = _run_program(tmp_path, capsys)
    rc = main(["audit", "--db", str(db), "--run-id", RUN_ID, "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["ok"] is True
    assert data["run_id"] == RUN_ID
    assert "findings" in data
    assert data["event_count"] > 0


def test_json_bench_parses(capsys):
    rc = main([
        "bench", "--repetitions", "1", "--latency-seconds", "0.003",
        "--json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "cases" in data
    assert "repetitions" in data
    assert len(data["cases"]) == 3


def test_json_run_parses(tmp_path, capsys):
    program = _write(tmp_path)
    db = tmp_path / "events.db"
    digest = _seal_of(tmp_path, capsys)
    rc = main([
        "run", str(program), "--db", str(db), "--run-id", "json-run",
        "--seal", digest, "--json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "succeeded"
    assert data["run_id"] == "json-run"
    assert data["percent_complete"] == 100


def test_json_learn_parses(tmp_path, capsys):
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    run_sub = run_dir / "myrun"
    run_sub.mkdir()
    prog = run_sub / "program.think"
    prog.write_text(CANONICAL, encoding="utf-8")
    rc = main(["learn", "--runs", str(run_dir), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "runs_dir" in data
    assert "run_ids" in data
    assert "myrun" in data["run_ids"]
    assert "candidates" in data
    assert "clusters" in data


# -- (2) one test per exit code (0/1/2/3/4) -----------------------------


def test_exit_code_0_success(tmp_path, capsys):
    """Exit 0: successful operation."""
    program = _write(tmp_path)
    rc = main(["lint", str(program)])
    assert rc == 0


def test_exit_code_1_usage_error(tmp_path, capsys):
    """Exit 1: usage / input error (malformed program)."""
    bad = "step.one: DO define(value = G.goal) -> E.result\n"
    program = _write(tmp_path, bad, name="broken.think")
    rc = main(["lint", str(program)])
    assert rc == 1


def test_exit_code_2_run_failed(tmp_path, capsys):
    """Exit 2: program execution failed (run coordinator raised)."""
    broken = """\
PROGRAM broken VERSION 0.1

INPUT
  G.goal = "x"

step.one: DO define(value = G.goal) -> E.result
step.broken: DO verify(goal = G.missing, evidence = E.result) -> V.result

RETURN E.result, V.result
"""
    program = _write(tmp_path, broken, name="broken.think")
    db = tmp_path / "events.db"
    digest = _seal_of(tmp_path, capsys, text=broken)
    rc = main([
        "run", str(program), "--db", str(db), "--run-id", "fail-run",
        "--seal", digest,
    ])
    assert rc == 2


def test_exit_code_3_audit_violations(tmp_path, capsys):
    """Exit 3: audit violations found (unknown run is exit 1)."""
    db = tmp_path / "events.db"
    with EventStore(str(db)) as store:
        _execute(store, _SUCCEED_PROGRAM)
    rc = main(["audit", "--db", str(db), "--run-id", "no-such-run"])
    assert rc == 1


def test_exit_code_3_real_audit_violation(tmp_path, capsys):
    """Exit 3: actual audit violations found (not just unknown run)."""
    db = tmp_path / "events.db"
    with EventStore(str(db)) as store:
        _execute(store, _RAISE_PROGRAM, handlers=_boom_handlers())
        failed = _events_of_type(store, _AUDIT_RUN_ID, EventType.FAILED)[0]
        store.append(
            _AUDIT_RUN_ID, EventType.VALIDATION_PASSED,
            instruction_id=failed.instruction_id,
            invocation_id=failed.invocation_id,
            task_id=failed.task_id,
            payload={},
        )
    rc = main(["audit", "--db", str(db), "--run-id", _AUDIT_RUN_ID])
    assert rc == 3


def test_exit_code_4_seal_mismatch(tmp_path, capsys):
    """Exit 4: seal digest mismatch on run."""
    program = _write(tmp_path)
    db = tmp_path / "events.db"
    wrong = "0" * 64
    rc = main([
        "run", str(program), "--db", str(db), "--run-id", RUN_ID,
        "--seal", wrong,
    ])
    assert rc == 4
    assert "seal digest mismatch" in capsys.readouterr().err


# -- (3) run without --seal fails at argparse (exit 2) -----------------


def test_run_without_seal_fails_at_argparse(tmp_path, capsys):
    """run without --seal exits 2 (argparse) with usage shown."""
    program = _write(tmp_path)
    db = tmp_path / "events.db"
    with pytest.raises(SystemExit) as exc_info:
        main(["run", str(program), "--db", str(db), "--run-id", RUN_ID])
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--seal" in err or "required" in err


# -- (4) seal --check correct -> 0, tampered -> 4 -----------------------


def test_seal_check_correct(tmp_path, capsys):
    """seal --check with correct digest exits 0 and prints 'seal matches'."""
    program = _write(tmp_path)
    # Get the correct digest
    rc = main(["seal", str(program)])
    assert rc == 0
    digest = capsys.readouterr().out.strip()
    # Now verify
    rc = main(["seal", str(program), "--check", digest])
    assert rc == 0
    out = capsys.readouterr().out
    assert "seal matches" in out


def test_seal_check_tampered(tmp_path, capsys):
    """seal --check with wrong digest exits 4 with drift message."""
    program = _write(tmp_path)
    wrong = "0" * 64
    rc = main(["seal", str(program), "--check", wrong])
    assert rc == 4
    err = capsys.readouterr().err
    assert "drifted" in err


# -- --out confirmation routed to stderr -------------------------------


def test_bench_out_confirmation_on_stderr(tmp_path, capsys):
    """--out file-path confirmation goes to stderr, not stdout."""
    out = tmp_path / "bench.md"
    rc = main([
        "bench", "--repetitions", "1", "--latency-seconds", "0.003",
        "--out", str(out),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert str(out) not in captured.out
    assert str(out) in captured.err


def test_learn_out_confirmation_on_stderr(tmp_path, capsys):
    """--out file-path confirmation goes to stderr, not stdout."""
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    run_sub = run_dir / "myrun"
    run_sub.mkdir()
    prog = run_sub / "program.think"
    prog.write_text(CANONICAL, encoding="utf-8")
    out = tmp_path / "learn.md"
    rc = main(["learn", "--runs", str(run_dir), "--out", str(out)])
    assert rc == 0
    captured = capsys.readouterr()
    assert str(out) not in captured.out
    assert str(out) in captured.err


# -- --json on audit with violations gives structured output ------------


def test_json_audit_with_violations(tmp_path, capsys):
    """--json on a violated audit shows findings in JSON."""
    db = tmp_path / "events.db"
    with EventStore(str(db)) as store:
        _execute(store, _RAISE_PROGRAM, handlers=_boom_handlers())
        failed = _events_of_type(store, _AUDIT_RUN_ID, EventType.FAILED)[0]
        store.append(
            _AUDIT_RUN_ID, EventType.VALIDATION_PASSED,
            instruction_id=failed.instruction_id,
            invocation_id=failed.invocation_id,
            task_id=failed.task_id,
            payload={},
        )
    rc = main(["audit", "--db", str(db), "--run-id", _AUDIT_RUN_ID, "--json"])
    assert rc == 3
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["ok"] is False
    assert len(data["findings"]) > 0
    assert any(f["code"] == "validation_passed_after_failed" for f in data["findings"])
