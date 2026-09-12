"""Tests for atlas learn (issue #13): mining runs into protocol candidates
and failure clusters, with a review-only deterministic markdown report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.cli import main
from atlas.learn import mine_run_directory

REAL_RUNS = Path(__file__).resolve().parents[1] / "demo" / "runs"


def _write_program(
    run_dir: Path,
    commands: list[str],
    *,
    with_call: bool = False,
) -> None:
    lines = ["PROGRAM synthetic VERSION 1.0", "", "INPUT", '    A.src = "x"', ""]
    for index, command in enumerate(commands):
        lines.append(f"step.s{index}: DO {command}(artifact = A.src) -> E.out{index}")
    if with_call:
        lines.append("CALL protocol.framing(query = A.src) -> E.called")
    lines += ["", "RETURN E.out0", ""]
    (run_dir / "program.think").write_text("\n".join(lines), encoding="utf-8")


def _write_run(
    runs_dir: Path,
    name: str,
    commands: list[str],
    *,
    evaluation: dict | None = None,
    with_call: bool = False,
) -> Path:
    run_dir = runs_dir / name
    run_dir.mkdir(parents=True)
    _write_program(run_dir, commands, with_call=with_call)
    if evaluation is not None:
        (run_dir / "evaluation.json").write_text(
            json.dumps(evaluation, indent=2), encoding="utf-8"
        )
    return run_dir


@pytest.fixture()
def synthetic_runs(tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_run(
        runs,
        "run-a",
        ["define", "search", "fetch", "extract", "report", "verify"],
        evaluation={
            "run_id": "run-a",
            "terminal_status": "succeeded",
            "steps_planned": 6,
            "steps_executed": 6,
            "protocol_deviations": [
                "The registered command catalog has no edit or test command",
            ],
            "unresolved": [],
        },
    )
    _write_run(
        runs,
        "run-b",
        ["define", "search", "fetch", "extract", "summarize", "check", "verify"],
        evaluation={
            "run_id": "run-b",
            "terminal_status": "succeeded",
            "steps_planned": 7,
            "steps_executed": 7,
            "protocol_deviations": [
                "edit refused the absolute path outside the workspace root",
            ],
            "unresolved": ["unknown ref E.ghost inside a reference list"],
        },
    )
    _write_run(
        runs,
        "run-c",
        ["define", "search", "fetch", "extract", "report", "verify"],
        evaluation={"run_id": "run-c", "terminal_status": "failed", "steps_executed": 3},
    )
    _write_run(
        runs,
        "run-call",
        ["define", "search", "fetch", "extract"],
        with_call=True,
    )
    _write_run(runs, "run-bare", ["define", "search", "fetch", "extract"])
    (runs / "not-a-run.txt").write_text("skip me", encoding="utf-8")
    return runs


def test_candidate_found_with_support_and_sequence(synthetic_runs: Path) -> None:
    report = mine_run_directory(synthetic_runs)
    four = [
        c
        for c in report.candidates
        if c.commands == ("define", "search", "fetch", "extract")
    ]
    assert len(four) == 1
    candidate = four[0]
    assert candidate.support == 4  # run-a, run-b, run-c, run-bare
    assert candidate.example_run_ids == ("run-a", "run-b", "run-bare", "run-c")
    assert candidate.suggested_name == "define_search_fetch_pipeline"


def test_call_program_excluded_from_candidates(synthetic_runs: Path) -> None:
    report = mine_run_directory(synthetic_runs)
    assert "run-call" in report.call_skipped_runs
    for candidate in report.candidates:
        assert "run-call" not in candidate.example_run_ids
    # run-call's 4-command prefix must not inflate the candidate's support.
    four = [
        c
        for c in report.candidates
        if c.commands == ("define", "search", "fetch", "extract")
    ]
    assert four[0].support == 4


def test_failure_clusters_bucketed(synthetic_runs: Path) -> None:
    report = mine_run_directory(synthetic_runs)
    by_bucket = {c.bucket: c for c in report.clusters}
    assert set(by_bucket) == {
        "missing_commands",
        "path_errors",
        "reference_arrays",
    }
    missing = by_bucket["missing_commands"]
    assert missing.count == 1
    assert missing.quotes[0].startswith("The registered command catalog")
    assert missing.run_ids == ("run-a",)
    path_cluster = by_bucket["path_errors"]
    assert path_cluster.run_ids == ("run-b",)
    refs = by_bucket["reference_arrays"]
    assert "unknown ref E.ghost inside a reference list" in refs.quotes


def test_markdown_is_deterministic_and_evidence_linked(synthetic_runs: Path) -> None:
    first = mine_run_directory(synthetic_runs).to_markdown()
    second = mine_run_directory(synthetic_runs).to_markdown()
    assert first == second
    assert first.strip()
    assert "define -> search -> fetch -> extract" in first
    assert "define_search_fetch_pipeline" in first
    assert "run-a" in first


def test_telemetry_counts(synthetic_runs: Path) -> None:
    report = mine_run_directory(synthetic_runs)
    assert report.run_ids == ("run-a", "run-b", "run-bare", "run-c", "run-call")
    # The bare run has no evaluation.json -> tolerated as unknown status.
    assert report.terminal_status_counts == {"failed": 1, "succeeded": 2, "unknown": 2}
    assert report.steps_planned_total == 6 + 7 + 6 + 5 + 4  # incl. CALL step
    assert report.steps_executed_total == 6 + 7 + 3
    assert report.parse_error_runs == ()
    assert report.worklogs_present == 0


def test_parse_error_and_invalid_evaluation_tolerated(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    broken = runs / "broken"
    broken.mkdir()
    (broken / "program.think").write_text("THIS IS NOT A PROGRAM", encoding="utf-8")
    (broken / "evaluation.json").write_text("{not json", encoding="utf-8")
    report = mine_run_directory(runs)
    assert report.parse_error_runs == ("broken",)
    assert report.terminal_status_counts == {"unknown": 1}
    assert report.to_markdown().strip()


def test_miner_writes_nothing(synthetic_runs: Path) -> None:
    def snapshot(root: Path) -> set[str]:
        return sorted(str(p.relative_to(root)) for p in root.rglob("*"))

    before = snapshot(synthetic_runs)
    mine_run_directory(synthetic_runs)
    assert snapshot(synthetic_runs) == before


def test_unreadable_runs_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        mine_run_directory(tmp_path / "does-not-exist")


def test_event_store_failed_payloads_mined(tmp_path: Path) -> None:
    from atlas.runtime.events import EventStore, EventType

    runs = tmp_path / "runs"
    run_dir = runs / "run-db"
    run_dir.mkdir(parents=True)
    _write_program(run_dir, ["define", "search", "verify"])
    db_path = run_dir / "events.db"
    store = EventStore(str(db_path))
    try:
        store.create_run("run-db", "1.0")
        store.append("run-db", EventType.FAILED, payload={"error": "timeout exceeded"})
    finally:
        store.close()
    report = mine_run_directory(runs)
    assert report.event_stores_found == 1
    other = [c for c in report.clusters if c.bucket == "other"]
    assert len(other) == 1
    assert "timeout exceeded" in other[0].quotes[0]
    assert other[0].run_ids == ("run-db",)


@pytest.mark.skipif(not REAL_RUNS.is_dir(), reason="demo/runs directory is missing")
def test_real_corpus_yields_candidates() -> None:
    report = mine_run_directory(REAL_RUNS)
    assert len(report.run_ids) >= 1
    assert report.candidates, "expected at least one protocol candidate in demo/runs"
    markdown = report.to_markdown()
    assert markdown.strip()
    assert "Protocol candidates" in markdown


def test_cli_learn_prints_report(synthetic_runs: Path, capsys: pytest.CaptureFixture) -> None:
    rc = main(["learn", "--runs", str(synthetic_runs)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "atlas learn — mined run report" in out
    assert "Protocol candidates" in out


def test_cli_learn_out_writes_file(synthetic_runs: Path, capsys: pytest.CaptureFixture, tmp_path: Path) -> None:
    out_path = tmp_path / "report.md"
    rc = main(["learn", "--runs", str(synthetic_runs), "--out", str(out_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert str(out_path) in captured.err
    written = out_path.read_text(encoding="utf-8")
    assert "atlas learn — mined run report" in written
    assert written == mine_run_directory(synthetic_runs).to_markdown()


def test_cli_learn_unreadable_runs_dir(synthetic_runs: Path, capsys: pytest.CaptureFixture, tmp_path: Path) -> None:
    rc = main(["learn", "--runs", str(tmp_path / "missing")])
    assert rc == 1
    assert "error:" in capsys.readouterr().err
