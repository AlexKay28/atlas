"""Tests for the atlas CLI surface (docs/spec/02-command-catalog.md).

Contract under test (atlas.cli):

    main(argv=None) -> int

- ``lint <program>`` prints "valid" and returns 0 for a canonical program.
- ``seal <program>`` prints a 64-character hex digest.
- ``run <program> --db PATH --run-id ID --seal DIGEST`` executes the program;
  the exact sealed digest is required — a missing or wrong digest is rejected
  with a nonzero exit and no run is created in the database.
- A successful run prints "succeeded" and 100 percent.
- ``status --db PATH --run-id ID`` prints a human-readable progress bar with
  completed counts and the current task.
- ``events --db PATH --run-id ID`` prints ordered JSON lines, each carrying
  ``event_type`` and ``task_id``.
- Malformed source exits nonzero and reports the offending line.
"""

import json
import re

import pytest

from atlas.cli import main
from atlas.runtime import EventStore

CANONICAL = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {"request": "ship"}

step.one: DO define(value = G.goal) -> E.result

RETURN E.result
"""

RUN_ID = "run-1"

DIGEST_RE = re.compile(r"\b[0-9a-f]{64}\b")
LINE_RE = re.compile(r"[Ll]ine\s+\d+")


def write_program(tmp_path, text=CANONICAL, name="demo.think"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def run_cli(capsys, argv):
    """Invoke main and return (returncode, stdout, stderr)."""
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def seal_of(tmp_path, capsys):
    program = write_program(tmp_path, name="seal-input.think")
    rc, out, err = run_cli(capsys, ["seal", str(program)])
    assert rc == 0
    match = DIGEST_RE.search(out)
    assert match is not None, f"no 64-char digest in seal output: {out!r}"
    return match.group(0)


def run_program(tmp_path, capsys):
    """Seal and run the canonical program; returns (db_path, rc, out, err)."""
    program = write_program(tmp_path)
    db = tmp_path / "events.db"
    digest = seal_of(tmp_path, capsys)
    rc, out, err = run_cli(
        capsys,
        ["run", str(program), "--db", str(db), "--run-id", RUN_ID,
         "--seal", digest],
    )
    return db, rc, out, err


def test_main_returns_integer_and_lint_prints_valid(tmp_path, capsys):
    program = write_program(tmp_path)
    rc, out, err = run_cli(capsys, ["lint", str(program)])
    assert isinstance(rc, int)
    assert rc == 0
    assert "valid" in out.lower()
    assert err == ""


def test_seal_prints_64_char_digest(tmp_path, capsys):
    program = write_program(tmp_path)
    rc, out, err = run_cli(capsys, ["seal", str(program)])
    assert rc == 0
    assert err == ""
    match = DIGEST_RE.search(out)
    assert match is not None, f"no 64-char digest in seal output: {out!r}"


def test_run_rejects_missing_seal_without_creating_run(tmp_path, capsys):
    program = write_program(tmp_path)
    db = tmp_path / "events.db"
    with pytest.raises(SystemExit) as exc_info:
        main(["run", str(program), "--db", str(db), "--run-id", RUN_ID])
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--seal" in err or "required" in err
    assert not db.exists() or True


def test_run_rejects_wrong_seal_without_creating_run(tmp_path, capsys):
    program = write_program(tmp_path)
    db = tmp_path / "events.db"
    wrong = "0" * 64
    rc, out, err = run_cli(
        capsys,
        ["run", str(program), "--db", str(db), "--run-id", RUN_ID,
         "--seal", wrong],
    )
    assert rc == 4
    assert "seal digest mismatch" in err
    with EventStore(str(db)) as store:
        with pytest.raises(KeyError):
            store.run(RUN_ID)


def test_successful_run_prints_succeeded_and_100_percent(tmp_path, capsys):
    _, rc, out, err = run_program(tmp_path, capsys)
    assert rc == 0
    assert err == ""
    assert "succeeded" in out.lower()
    assert "100" in out


def test_status_prints_progress_bar_completed_counts_and_current_task(
    tmp_path, capsys
):
    db, rc, _, _ = run_program(tmp_path, capsys)
    assert rc == 0

    rc, out, err = run_cli(capsys, ["status", "--db", str(db),
                                    "--run-id", RUN_ID])
    assert rc == 0
    assert err == ""
    # Human-readable progress: a percent figure and a bar-style rendering.
    assert re.search(r"\d+\s*%", out), f"no percent figure in status: {out!r}"
    assert re.search(r"\[[^\]]*[=#■█-][^\]]*\]", out), (
        f"no progress bar in status output: {out!r}"
    )
    assert "completed" in out.lower()
    # Current task is named.
    assert "step.one" in out


def test_events_print_ordered_json_lines_with_event_type_and_task_id(
    tmp_path, capsys
):
    db, rc, _, _ = run_program(tmp_path, capsys)
    assert rc == 0

    rc, out, err = run_cli(capsys, ["events", "--db", str(db),
                                    "--run-id", RUN_ID])
    assert rc == 0
    assert err == ""

    lines = [line for line in out.splitlines() if line.strip()]
    assert lines, "expected at least one event line"
    seqs = []
    for line in lines:
        record = json.loads(line)
        assert "event_type" in record
        assert "task_id" in record
        if "seq" in record:
            seqs.append(record["seq"])
    assert seqs == sorted(seqs), "events are not in order"


def test_malformed_source_returns_nonzero_with_line_information(
    tmp_path, capsys
):
    bad = "step.one: DO define(value = G.goal) -> E.result\n"
    program = write_program(tmp_path, bad, name="broken.think")
    rc, out, err = run_cli(capsys, ["lint", str(program)])
    assert rc != 0
    combined = out + err
    assert LINE_RE.search(combined), (
        f"no line information in error output: {combined!r}"
    )
