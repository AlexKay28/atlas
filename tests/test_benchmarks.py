"""Tests for the deterministic benchmark harness (issue #26).

Fast by construction: tests use tiny per-step latencies (milliseconds)
and single repetitions, never the built-in cases' default 40ms latency.
The suite must stay well under its ~40s budget with these added.
"""

import pytest

from tikhon import cli
from tikhon.benchmarks import (
    BenchmarkCase,
    builtin_cases,
    run_benchmark,
    sleep_worker,
)
from tikhon.budgets import ExecutionBudget
from tikhon.runtime import EventStore, SequentialCoordinator
from tikhon.runtime.coordinator import DeterministicWorker
from tikhon.syntax import parse_program

TINY_LATENCY = 0.003

_LINEAR_SOURCE = """\
PROGRAM bench_linear VERSION 1.0
INPUT
    G.goal = "benchmark the concurrent frontier"
step.frame: DO define(request = G.goal) -> P.frame
step.locate: DO search(query = G.goal, scope = "src/") -> E.sites
step.read: DO fetch(resource_refs = G.goal) -> ART.sources
step.analyze: DO extract(artifact = G.goal, schema = "bench") -> E.findings
step.hypothesize: DO hypothesize(question = G.goal, evidence = G.goal) -> H.theses
step.report: DO report(committed_refs = G.goal, format = "markdown") -> ART.report
RETURN P.frame, E.sites, ART.sources, E.findings, H.theses, ART.report
"""

_DEPENDENT_SOURCE = """\
PROGRAM bench_chain VERSION 1.0
INPUT
    G.goal = "a dependency chain cannot overlap"
step.frame: DO define(request = G.goal) -> P.frame
step.locate: DO search(query = P.frame, scope = "src/") -> E.sites
step.read: DO fetch(resource_refs = E.sites) -> ART.sources
step.analyze: DO extract(artifact = ART.sources, schema = "bench") -> E.findings
step.hypothesize: DO hypothesize(question = E.findings, evidence = E.findings) -> H.theses
step.report: DO report(committed_refs = H.theses, format = "markdown") -> ART.report
RETURN P.frame, E.sites, ART.sources, E.findings, H.theses, ART.report
"""


def _linear_case(**overrides) -> BenchmarkCase:
    defaults = dict(
        name="t-linear",
        program=_LINEAR_SOURCE,
        max_workers=3,
        latency_seconds=TINY_LATENCY,
        repetitions=1,
    )
    defaults.update(overrides)
    return BenchmarkCase(**defaults)


# -- happy path ---------------------------------------------------------


def test_run_benchmark_produces_report_for_linear_case():
    report = run_benchmark([_linear_case()], repetitions=1)
    assert len(report.cases) == 1
    case = report.cases[0]
    assert case.name == "t-linear"
    assert case.baseline.repetitions == 1
    assert case.baseline.dispatches == 6
    assert case.variant.dispatches == 6
    assert case.baseline.events > 0
    assert case.baseline.tasks == 6
    assert case.baseline.child_runs == 0
    assert case.baseline.envelope_bytes > 0


def test_frontier_case_speedup_exceeds_one_with_sleep_handlers():
    report = run_benchmark(
        [_linear_case(latency_seconds=0.01)], repetitions=1
    )
    # Six independent 10ms steps: sequential ~60ms of handler time, the
    # 3-worker frontier overlaps them into two waves.
    assert report.cases[0].speedup > 1.0


def test_par_builtin_case_speedup_exceeds_one_with_sleep_handlers():
    par = builtin_cases(latency_seconds=0.02)[2]
    report = run_benchmark([par], repetitions=1)
    case = report.cases[0]
    # The 1-slot baseline budget serializes the four branches; the
    # 4-slot variant overlaps them.  The delegate branch bounds the
    # critical path, so the speedup is real but sub-linear.
    assert case.speedup > 1.0
    assert case.baseline.envelope_bytes == case.variant.envelope_bytes


def test_scatter_case_is_width_invariant_and_not_faster():
    scatter = builtin_cases(latency_seconds=TINY_LATENCY)[1]
    report = run_benchmark([scatter], repetitions=1)
    case = report.cases[0]
    # One prepare + 8 candidates + one final dispatch per side.
    assert case.baseline.dispatches == 10
    assert case.variant.dispatches == 10
    assert case.baseline.envelope_bytes == case.variant.envelope_bytes
    assert case.baseline.envelope_bytes > 8 * 300
    # Scatter drives the sequential plan loop by contract: no meaningful
    # speedup from width (honest 'parallel is not faster here' data).
    assert 0.5 < case.speedup < 1.5


def test_dependency_chain_case_shows_no_speedup():
    case = BenchmarkCase(
        name="t-chain",
        program=_DEPENDENT_SOURCE,
        max_workers=6,
        latency_seconds=0.01,
        repetitions=1,
    )
    report = run_benchmark([case], repetitions=1)
    # Every step consumes the previous step's output: the frontier has
    # nothing ready to overlap beyond the first entry.
    assert report.cases[0].speedup < 1.6


# -- accounting ---------------------------------------------------------


def test_delegation_granularity_from_par_case():
    par = builtin_cases(latency_seconds=TINY_LATENCY)[2]
    report = run_benchmark([par], repetitions=1)
    variant = report.cases[0].variant
    # par1..par4 branch runs + the delegate-authored child run.
    assert variant.child_runs == 5
    assert variant.authored_plans == 1
    assert variant.authored_steps == 3
    assert variant.child_tasks == 1 + 1 + 2 + 1 + 3
    assert variant.child_events > variant.child_runs
    assert variant.avg_steps_per_child == pytest.approx(8 / 5)


def test_stable_counts_identical_across_two_benchmark_runs():
    first = run_benchmark([_linear_case()], repetitions=1)
    second = run_benchmark([_linear_case()], repetitions=1)
    left, right = first.cases[0], second.cases[0]
    for side in ("baseline", "variant"):
        a = getattr(left, side)
        b = getattr(right, side)
        assert (
            a.events,
            a.tasks,
            a.dispatches,
            a.envelope_bytes,
            a.child_runs,
        ) == (
            b.events,
            b.tasks,
            b.dispatches,
            b.envelope_bytes,
            b.child_runs,
        )


def test_markdown_rendering_is_deterministic():
    report = run_benchmark([_linear_case()], repetitions=1)
    assert report.to_markdown() == report.to_markdown()


def test_markdown_contains_labeled_tables_and_evidence_label():
    report = run_benchmark([_linear_case()], repetitions=1)
    markdown = report.to_markdown()
    assert "Critical-path speedup" in markdown
    assert "Context cost" in markdown
    assert "Delegation granularity" in markdown
    assert "sleep-simulated" in markdown
    assert "TIKHON_*" in markdown


def test_report_spread_brackets_the_mean():
    report = run_benchmark(
        [_linear_case(latency_seconds=0.005)], repetitions=2
    )
    case = report.cases[0]
    assert case.baseline.repetitions == 2
    assert case.baseline.wall_min_seconds <= case.baseline.wall_mean_seconds
    assert case.baseline.wall_mean_seconds <= case.baseline.wall_max_seconds


# -- construction / validation ------------------------------------------


def test_sleep_worker_covers_every_registered_command():
    worker = sleep_worker(0.0)
    from tikhon.registry import builtin_registry

    assert worker.commands == set(builtin_registry().names())
    result = worker.execute("define", {"request": "x"})
    assert result == {"command": "define", "echo": {"request": "x"}}


def test_benchmark_case_rejects_bad_config():
    with pytest.raises(ValueError):
        BenchmarkCase(name="", program=_LINEAR_SOURCE)
    with pytest.raises(ValueError):
        BenchmarkCase(name="t", program="   ")
    with pytest.raises(ValueError):
        BenchmarkCase(name="t", program=_LINEAR_SOURCE, max_workers=0)


def test_run_benchmark_rejects_empty_cases_and_bad_repetitions():
    with pytest.raises(ValueError):
        run_benchmark([])
    with pytest.raises(ValueError):
        run_benchmark([_linear_case()], repetitions=0)
    with pytest.raises(ValueError):
        run_benchmark(["not-a-case"])


def test_failed_run_raises_instead_of_reporting():
    # A program whose second step cannot resolve its reference fails the
    # run; the harness must refuse to report a broken benchmark.
    broken = """\
PROGRAM bench_broken VERSION 1.0
INPUT
    G.goal = "x"
step.frame: DO define(request = G.goal) -> P.frame
step.broken: DO verify(goal = G.missing, evidence = P.frame) -> V.result
RETURN P.frame, V.result
"""
    case = BenchmarkCase(
        name="t-broken",
        program=broken,
        latency_seconds=0.0,
        repetitions=1,
    )
    with pytest.raises(ValueError, match="failed to execute"):
        run_benchmark([case], repetitions=1)


def test_case_from_path_loads_program(tmp_path):
    source_file = tmp_path / "case.think"
    source_file.write_text(_LINEAR_SOURCE, encoding="utf-8")
    case = BenchmarkCase.from_path(
        "t-from-path",
        source_file,
        max_workers=2,
        latency_seconds=0.0,
        repetitions=1,
    )
    report = run_benchmark([case], repetitions=1)
    assert report.cases[0].baseline.dispatches == 6


def test_worker_factory_is_used_per_run():
    calls = []

    def factory():
        calls.append(1)
        return sleep_worker(0.0)

    case = BenchmarkCase(
        name="t-factory",
        program=_LINEAR_SOURCE,
        max_workers=2,
        worker_factory=factory,
        repetitions=1,
    )
    run_benchmark([case], repetitions=1)
    assert len(calls) == 2  # one baseline run + one variant run


# -- CLI ----------------------------------------------------------------


def test_cli_bench_writes_report_file(tmp_path, capsys):
    out = tmp_path / "bench-report.md"
    rc = cli.main(
        [
            "bench",
            "--repetitions",
            "1",
            "--latency-seconds",
            "0.003",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert text in capsys.readouterr().out
    assert "Critical-path speedup" in text
    assert "linear-independent-6" in text
    assert "scatter-gather-8" in text
    assert "par-heterogeneous-4" in text
    assert "sleep-simulated" in text


def test_cli_bench_rejects_nonpositive_repetitions(capsys):
    rc = cli.main(["bench", "--repetitions", "0"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


# -- deterministic worker smoke (overlap without sleeps) ----------------


def test_zero_latency_benchmark_still_succeeds_and_counts():
    report = run_benchmark(
        [_linear_case(latency_seconds=0.0)], repetitions=1
    )
    case = report.cases[0]
    assert case.baseline.dispatches == 6
    assert case.baseline.envelope_bytes == case.variant.envelope_bytes
    # Sanity: the harness executed real coordinators over real stores.
    assert case.baseline.events >= 6 * 8
