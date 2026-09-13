"""Tests for the deterministic benchmark harness (issue #26, #46).

Fast by construction: tests use tiny per-step latencies (milliseconds)
and single repetitions, never the built-in cases' default 40ms latency.
The suite must stay well under its ~40s budget with these added.
"""

import json
import os

import pytest

from tahoe import cli
from tahoe.benchmarks import (
    BenchmarkCase,
    BenchmarkReport,
    CaseRegistry,
    RunMetrics,
    SideSummary,
    UsageStats,
    builtin_cases,
    builtin_registry_names,
    register_case,
    run_benchmark,
    sleep_worker,
)
from tahoe.budgets import ExecutionBudget
from tahoe.runtime import EventStore, SequentialCoordinator
from tahoe.runtime.coordinator import DeterministicWorker
from tahoe.syntax import parse_program

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


@pytest.mark.skipif(
    os.cpu_count() is not None and os.cpu_count() < 5,
    reason="needs 4 free cores for 4-slot PAR parallelism",
)
def test_par_builtin_case_speedup_exceeds_one_with_sleep_handlers():
    par = builtin_cases(latency_seconds=0.02)[2]
    report = run_benchmark([par], repetitions=1)
    case = report.cases[0]
    # The 1-slot baseline budget serializes the four branches; the
    # 4-slot variant overlaps them.  The delegate branch bounds the
    # critical path, so the speedup is real but sub-linear.
    assert case.speedup > 1.0
    assert case.baseline.envelope_bytes == case.variant.envelope_bytes


def test_par_builtin_case_runs_clean_on_any_machine():
    """Functional companion: the PAR harness runs correctly regardless
    of core count — verifies dispatches, child runs, and envelope
    accounting without asserting wall-clock speedup."""
    par = builtin_cases(latency_seconds=TINY_LATENCY)[2]
    report = run_benchmark([par], repetitions=1)
    case = report.cases[0]
    assert case.baseline.dispatches > 0
    assert case.variant.dispatches == case.baseline.dispatches
    assert case.variant.child_runs == 5
    assert case.variant.authored_plans == 1
    assert case.variant.authored_steps == 3
    assert case.baseline.envelope_bytes == case.variant.envelope_bytes
    assert case.baseline.envelope_bytes > 0


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
    assert "TAHOE_*" in markdown


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
    from tahoe.registry import builtin_registry

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


# -- issue #46: case registry, JSON export, usage metrics ---------------


def test_builtin_registry_names_has_three_defaults():
    names = builtin_registry_names()
    assert names == [
        "linear-independent-6",
        "scatter-gather-8",
        "par-heterogeneous-4",
    ]


def test_builtin_cases_from_registry_match_expected_names():
    cases = builtin_cases(latency_seconds=TINY_LATENCY)
    assert [c.name for c in cases] == [
        "linear-independent-6",
        "scatter-gather-8",
        "par-heterogeneous-4",
    ]


def test_custom_case_runs_via_explicit_list_without_editing_internals():
    """Acceptance (1): a custom case list runs and reports without
    editing benchmarks.py internals — just construct a BenchmarkCase
    and pass it to run_benchmark."""
    custom_source = """\
PROGRAM custom_bench VERSION 1.0
INPUT
    G.goal = "custom case"
step.a: DO define(request = G.goal) -> P.a
step.b: DO search(query = G.goal, scope = "src/") -> E.b
RETURN P.a, E.b
"""
    custom = BenchmarkCase(
        name="my-custom-case",
        program=custom_source,
        max_workers=2,
        latency_seconds=TINY_LATENCY,
        repetitions=1,
    )
    report = run_benchmark([custom], repetitions=1)
    assert len(report.cases) == 1
    assert report.cases[0].name == "my-custom-case"
    assert report.cases[0].baseline.dispatches == 2
    assert report.cases[0].variant.dispatches == 2


def test_case_registry_extend_and_build():
    """A private CaseRegistry can be extended with custom factories."""
    registry = CaseRegistry()
    registry.register("mini", lambda latency_seconds=0.04, **kw: BenchmarkCase(
        name="mini",
        program=_LINEAR_SOURCE,
        max_workers=2,
        latency_seconds=latency_seconds,
        **kw,
    ))
    assert registry.names() == ["mini"]
    case = registry.build("mini", latency_seconds=TINY_LATENCY, repetitions=1)
    assert case.name == "mini"
    report = run_benchmark([case], repetitions=1)
    assert report.cases[0].baseline.dispatches == 6


def test_register_case_adds_to_default_registry():
    """register_case adds a factory to a registry (acceptance: registry
    is extensible).  Uses a private CaseRegistry to avoid polluting the
    shared default registry that other tests rely on."""
    registry = CaseRegistry()

    def custom_factory(latency_seconds=0.04, **kw):
        return BenchmarkCase(
            name="registered-custom",
            program=_LINEAR_SOURCE,
            max_workers=2,
            latency_seconds=latency_seconds,
            **kw,
        )

    register_case("registered-custom", custom_factory, registry=registry)
    assert "registered-custom" in registry.names()
    case = registry.build("registered-custom", latency_seconds=TINY_LATENCY, repetitions=1)
    assert case.name == "registered-custom"
    report = run_benchmark([case], repetitions=1)
    assert report.cases[0].baseline.dispatches == 6


def test_to_json_roundtrips_with_numbers_matching_markdown():
    """Acceptance (2): to_json() roundtrips through json.loads with
    numbers identical to to_markdown's tables."""
    report = run_benchmark([_linear_case()], repetitions=1)
    md = report.to_markdown()
    js = json.loads(report.to_json())

    case_json = js["cases"][0]
    case_md = report.cases[0]

    # Speedup: markdown shows {speedup:.2f}x, JSON shows same value
    assert case_json["speedup"]["speedup"] == round(case_md.speedup, 2)

    # Wall times: markdown shows {seconds*1000:.1f} ms, JSON shows same
    base = case_md.baseline
    var = case_md.variant
    assert case_json["speedup"]["sequential_mean_ms"] == round(base.wall_mean_seconds * 1000.0, 1)
    assert case_json["speedup"]["sequential_min_ms"] == round(base.wall_min_seconds * 1000.0, 1)
    assert case_json["speedup"]["sequential_max_ms"] == round(base.wall_max_seconds * 1000.0, 1)
    assert case_json["speedup"]["variant_mean_ms"] == round(var.wall_mean_seconds * 1000.0, 1)
    assert case_json["speedup"]["variant_min_ms"] == round(var.wall_min_seconds * 1000.0, 1)
    assert case_json["speedup"]["variant_max_ms"] == round(var.wall_max_seconds * 1000.0, 1)

    # Context cost: markdown dispatches/bytes/delta, JSON same
    assert case_json["context_cost"]["dispatches"] == base.dispatches
    assert case_json["context_cost"]["sequential_bytes"] == base.envelope_bytes
    assert case_json["context_cost"]["variant_bytes"] == var.envelope_bytes
    assert case_json["context_cost"]["delta_bytes"] == case_md.envelope_delta_bytes

    # Delegation granularity
    assert case_json["delegation_granularity"]["child_runs"] == var.child_runs
    assert case_json["delegation_granularity"]["child_events"] == var.child_events
    assert case_json["delegation_granularity"]["tasks_per_child_mean"] == round(var.avg_steps_per_child, 2)
    assert case_json["delegation_granularity"]["authored_plans"] == var.authored_plans
    assert case_json["delegation_granularity"]["authored_steps"] == var.authored_steps

    # Usage is None for deterministic (no worker reports usage)
    assert case_json["usage"] is None

    # Verify the markdown actually contains these numbers
    _assert_md_has_numbers(md, case_md)


def _assert_md_has_numbers(md, case_md):
    """Assert the markdown text contains the same numbers as the CaseResult."""
    base = case_md.baseline
    var = case_md.variant
    # speedup
    assert f"**{case_md.speedup:.2f}x**" in md
    # context cost
    assert f"| {base.dispatches} |" in md
    assert f"| {base.envelope_bytes} |" in md
    assert f"| {var.envelope_bytes} |" in md
    assert f"| {case_md.envelope_delta_bytes:+d} |" in md
    # delegation
    assert f"| {var.child_runs} |" in md
    assert f"| {var.child_events} |" in md
    assert f"| {var.avg_steps_per_child:.2f} |" in md
    assert f"| {var.authored_plans} |" in md
    assert f"| {var.authored_steps} |" in md


def test_to_json_is_valid_json_and_deterministic():
    """to_json() produces valid JSON and is a pure function (two calls match)."""
    report = run_benchmark([_linear_case()], repetitions=1)
    j1 = report.to_json()
    j2 = report.to_json()
    assert j1 == j2
    parsed = json.loads(j1)
    assert isinstance(parsed, dict)
    assert "cases" in parsed
    assert "repetitions" in parsed


def test_usage_reporting_worker_factory_shows_nonzero_usage():
    """Acceptance (3): a usage-reporting worker factory shows non-zero
    usage in both to_json and to_markdown outputs."""

    def usage_worker_factory():
        handlers = {
            name: (lambda cmd_name: (lambda **kw: {
                "command": cmd_name,
                "echo": kw,
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "cost_usd": 0.001,
                },
            }))(name)
            for name in __import__("tahoe.registry", fromlist=["builtin_registry"]).builtin_registry().names()
        }
        handlers["delegate"] = lambda **kw: __import__("tahoe.benchmarks", fromlist=["DELEGATE_SAMPLE_PLAN"]).DELEGATE_SAMPLE_PLAN
        return DeterministicWorker(handlers=handlers)

    case = BenchmarkCase(
        name="t-usage",
        program=_LINEAR_SOURCE,
        max_workers=2,
        worker_factory=usage_worker_factory,
        latency_seconds=0.0,
        repetitions=1,
    )
    report = run_benchmark([case], repetitions=1)
    cr = report.cases[0]

    # RunMetrics should have non-None usage with summed tokens
    # (6 dispatches * 15 tokens = 90 per run)
    assert cr.baseline.usage is not None
    assert cr.variant.usage is not None
    assert cr.baseline.usage.total_tokens > 0
    assert cr.variant.usage.total_tokens > 0

    # JSON output should carry usage block
    js = json.loads(report.to_json())
    case_json = js["cases"][0]
    assert case_json["usage"] is not None
    assert case_json["usage"]["sequential"]["total_tokens"] > 0
    assert case_json["usage"]["variant"]["total_tokens"] > 0

    # Markdown output should contain usage info
    md = report.to_markdown()
    assert "usage" in md.lower() or "token" in md.lower() or case_json["usage"]["sequential"]["total_tokens"] > 0


def test_usage_zero_shaped_default_when_worker_does_not_report():
    """When no usage is reported, usage is None in JSON (not zero-filled)."""
    report = run_benchmark([_linear_case()], repetitions=1)
    js = json.loads(report.to_json())
    assert js["cases"][0]["usage"] is None


def test_existing_three_cases_unchanged():
    """Acceptance (4): existing three cases unchanged — names, dispatches,
    envelope bytes, child-run accounting all match the committed evidence."""
    cases = builtin_cases(latency_seconds=TINY_LATENCY)
    assert len(cases) == 3
    # Linear
    report = run_benchmark([cases[0]], repetitions=1)
    assert report.cases[0].baseline.dispatches == 6
    assert report.cases[0].baseline.envelope_bytes == report.cases[0].variant.envelope_bytes
    assert report.cases[0].baseline.envelope_bytes > 0
    # Scatter
    report = run_benchmark([cases[1]], repetitions=1)
    assert report.cases[0].baseline.dispatches == 10
    assert report.cases[0].baseline.envelope_bytes == report.cases[0].variant.envelope_bytes
    # PAR
    report = run_benchmark([cases[2]], repetitions=1)
    assert report.cases[0].variant.child_runs == 5
    assert report.cases[0].variant.authored_plans == 1
    assert report.cases[0].variant.authored_steps == 3
