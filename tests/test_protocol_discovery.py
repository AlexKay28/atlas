"""Tests for protocol discovery parsing and clustering logic."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from pathlib import Path

from analysis.protocol_discovery import (
    extract_refs,
    extract_reasoning_patterns,
    identify_emergent_refs,
    identify_protocol_sequence,
    is_emergent_sequence,
    detect_answer_format,
    determine_task_type,
    parse_trial,
    cluster_trials,
    compute_pattern_pass_rates,
    compute_score_correlation,
    compute_benchmark_pass_rates,
    identify_emergent_sequences,
    compute_answer_format_distribution,
    generate_json_report,
    generate_markdown_report,
    TrialAnalysis,
    SKILL_VOCAB_REFS,
    CANONICAL_PROTOCOLS,
)


# ---------------------------------------------------------------------------
# extract_refs
# ---------------------------------------------------------------------------

def test_extract_refs_from_typed_ref_text():
    text = "G.goal: compute total\nE.price = 12\nP.total: 36\nOUT.answer: 36"
    refs_in_order, distinct = extract_refs(text)
    assert refs_in_order == ["G", "E", "P", "OUT"]
    assert set(distinct) == {"G", "E", "P", "OUT"}


def test_extract_refs_from_empty_text():
    refs_in_order, distinct = extract_refs("")
    assert refs_in_order == []
    assert distinct == []


def test_extract_refs_from_plain_answer():
    refs_in_order, distinct = extract_refs("(D)")
    assert refs_in_order == []
    assert distinct == []


def test_extract_refs_preserves_order():
    text = "C.constraint: x\nG.goal: y\nP.step: z\nOUT.answer: w"
    refs_in_order, distinct = extract_refs(text)
    assert refs_in_order == ["C", "G", "P", "OUT"]


def test_extract_refs_inline_fallback():
    text = "The answer uses G.goal: compute and P.step: add"
    refs_in_order, distinct = extract_refs(text)
    assert "G" in refs_in_order
    assert "P" in refs_in_order


# ---------------------------------------------------------------------------
# extract_reasoning_patterns
# ---------------------------------------------------------------------------

def test_extract_reasoning_patterns_deduction():
    text = "Therefore the answer is (D). Thus we can conclude."
    patterns = extract_reasoning_patterns(text)
    assert "deduction" in patterns


def test_extract_reasoning_patterns_verification():
    text = "Let me check the answer. DONE verified."
    patterns = extract_reasoning_patterns(text)
    assert "verification" in patterns


def test_extract_reasoning_patterns_elimination():
    text = "We can eliminate option A. Rule out B."
    patterns = extract_reasoning_patterns(text)
    assert "elimination" in patterns


def test_extract_reasoning_patterns_sequence():
    text = "First, compute x. Second, check y. Finally, output z."
    patterns = extract_reasoning_patterns(text)
    assert "sequence" in patterns


def test_extract_reasoning_patterns_empty():
    patterns = extract_reasoning_patterns("(D)")
    assert patterns == []


def test_extract_reasoning_patterns_multiple():
    text = "First, assume the premise. Therefore, compute the total. Check: DONE."
    patterns = extract_reasoning_patterns(text)
    assert "assumption" in patterns
    assert "deduction" in patterns
    assert "verification" in patterns


# ---------------------------------------------------------------------------
# identify_emergent_refs
# ---------------------------------------------------------------------------

def test_identify_emergent_refs_none():
    refs = {"G", "C", "E", "OUT"}
    emergent = identify_emergent_refs(refs)
    assert emergent == []


def test_identify_emergent_refs_found():
    refs = {"G", "C", "ZZ", "WIDGET", "OUT"}
    emergent = identify_emergent_refs(refs)
    assert "ZZ" in emergent
    assert "WIDGET" in emergent
    assert "G" not in emergent
    assert "OUT" not in emergent


def test_identify_emergent_refs_empty_set():
    emergent = identify_emergent_refs(set())
    assert emergent == []


# ---------------------------------------------------------------------------
# is_emergent_sequence
# ---------------------------------------------------------------------------

def test_is_emergent_sequence_empty():
    assert not is_emergent_sequence([])


def test_is_emergent_sequence_canonical_compute():
    # G -> E -> P -> OUT matches compute
    assert not is_emergent_sequence(["G", "E", "P", "OUT"])


def test_is_emergent_sequence_canonical_select():
    # G -> E -> D -> OUT matches select
    assert not is_emergent_sequence(["G", "E", "D", "OUT"])


def test_is_emergent_sequence_canonical_deduce():
    # G -> C -> P -> OUT matches deduce
    assert not is_emergent_sequence(["G", "C", "P", "OUT"])


def test_is_emergent_sequence_emergent():
    assert is_emergent_sequence(["X", "Y", "Z"])


def test_is_emergent_sequence_partial_canonical():
    # Subsequence of compute
    assert not is_emergent_sequence(["G", "P", "OUT"])


def test_is_emergent_sequence_reordered():
    # Not a subsequence of any canonical protocol
    assert is_emergent_sequence(["OUT", "G"])


# ---------------------------------------------------------------------------
# detect_answer_format
# ---------------------------------------------------------------------------

def test_detect_answer_format_letter_paren():
    assert detect_answer_format("(D)") == "letter_paren"
    assert detect_answer_format("**(C)**\n\nReasoning...") == "letter_paren"


def test_detect_answer_format_letter_plain():
    assert detect_answer_format("D") == "letter_plain"
    assert detect_answer_format("C") == "letter_plain"


def test_detect_answer_format_number():
    assert detect_answer_format("42") == "number"
    assert detect_answer_format("-17") == "number"
    assert detect_answer_format("3.14") == "number"


def test_detect_answer_format_dollar():
    assert detect_answer_format("$145") == "dollar"
    assert detect_answer_format("$12") == "dollar"


def test_detect_answer_format_extended():
    text = "The answer is the result of extensive reasoning that goes on for quite a while. " * 3
    assert detect_answer_format(text) == "extended_reasoning"


def test_detect_answer_format_short_text():
    assert detect_answer_format("5 hours") == "short_text"


# ---------------------------------------------------------------------------
# determine_task_type
# ---------------------------------------------------------------------------

def test_determine_task_type_compute():
    assert determine_task_type("mmlu_math") == "compute"
    assert determine_task_type("gsm8k") == "compute"
    assert determine_task_type("bbh_arith") == "compute"
    assert determine_task_type("mmlu_acct") == "compute"


def test_determine_task_type_select():
    assert determine_task_type("arc") == "select"
    assert determine_task_type("race") == "select"


def test_determine_task_type_deduce():
    assert determine_task_type("mmlu_logic") == "deduce"
    assert determine_task_type("bbh") == "deduce"
    assert determine_task_type("bbh_track") == "deduce"
    assert determine_task_type("lsat") == "deduce"


def test_determine_task_type_unknown():
    assert determine_task_type("unknown_benchmark") == "compute"


# ---------------------------------------------------------------------------
# parse_trial
# ---------------------------------------------------------------------------

def test_parse_trial_short_answer():
    trial = {
        "arm": "tahoe",
        "benchmark": "mmlu_math",
        "final_answer": "(D)",
        "passed": True,
        "task_id": "test-001",
        "grader_detail": "expected=D, got=D",
        "failure_class": "none",
    }
    ta = parse_trial(trial, 0)
    assert ta.trial_index == 0
    assert ta.task_id == "test-001"
    assert ta.benchmark == "mmlu_math"
    assert ta.passed is True
    assert ta.final_answer == "(D)"
    assert ta.refs_found == []
    assert ta.ref_count == 0
    assert ta.answer_format == "letter_paren"
    assert ta.failure_class == "none"


def test_parse_trial_with_reasoning():
    trial = {
        "arm": "tahoe",
        "benchmark": "bbh",
        "final_answer": "**(C)**\n\nFirst, arrange the books. Therefore, the answer is C.",
        "passed": True,
        "task_id": "test-002",
        "grader_detail": "expected=C, got=C",
        "failure_class": "none",
    }
    ta = parse_trial(trial, 1)
    assert "sequence" in ta.reasoning_patterns
    assert "deduction" in ta.reasoning_patterns
    assert ta.answer_format == "letter_paren"


def test_parse_trial_with_typed_refs():
    trial = {
        "arm": "tahoe",
        "benchmark": "gsm8k",
        "final_answer": "G.goal: compute total\nE.price = 12\nP.total: 36\nOUT.answer: 36",
        "passed": True,
        "task_id": "test-003",
        "grader_detail": "expected=36, got=36",
        "failure_class": "none",
    }
    ta = parse_trial(trial, 2)
    assert ta.refs_found == ["G", "E", "P", "OUT"]
    assert ta.ref_count == 4
    assert ta.distinct_refs == 4
    assert not ta.is_emergent_sequence


def test_parse_trial_failed():
    trial = {
        "arm": "tahoe",
        "benchmark": "gsm8k",
        "final_answer": "$145",
        "passed": False,
        "task_id": "test-004",
        "grader_detail": "expected=$130, got=$145",
        "failure_class": "wrong_answer",
    }
    ta = parse_trial(trial, 3)
    assert ta.passed is False
    assert ta.failure_class == "wrong_answer"
    assert ta.trajectory_answer_correct == 0.0


def test_parse_trial_emergent_ref():
    trial = {
        "arm": "tahoe",
        "benchmark": "mmlu_math",
        "final_answer": "ZZ.discover: found new pattern\nG.goal: compute\nOUT.answer: 42",
        "passed": True,
        "task_id": "test-005",
        "grader_detail": "expected=42, got=42",
        "failure_class": "none",
    }
    ta = parse_trial(trial, 4)
    assert "ZZ" in ta.emergent_refs
    assert ta.is_emergent_sequence


# ---------------------------------------------------------------------------
# cluster_trials
# ---------------------------------------------------------------------------

def test_cluster_trials_groups_by_pattern():
    trials = [
        TrialAnalysis(
            trial_index=0, task_id="t1", benchmark="mmlu_math", passed=True,
            final_answer="(A)", final_answer_length=3, refs_found=[], ref_sequence=[],
            ref_count=0, distinct_refs=0, reasoning_patterns=["deduction"],
            emergent_refs=[], protocol_sequence=[], is_emergent_sequence=False,
            trajectory_overall=0.8, trajectory_protocol_match=0.5, trajectory_ref_usage=0.0,
            trajectory_verification=0.0, trajectory_token_efficiency=1.0,
            trajectory_completeness=0.5, trajectory_answer_correct=1.0,
            answer_format="letter_paren", failure_class="none",
        ),
        TrialAnalysis(
            trial_index=1, task_id="t2", benchmark="mmlu_math", passed=False,
            final_answer="(B)", final_answer_length=3, refs_found=[], ref_sequence=[],
            ref_count=0, distinct_refs=0, reasoning_patterns=["deduction"],
            emergent_refs=[], protocol_sequence=[], is_emergent_sequence=False,
            trajectory_overall=0.3, trajectory_protocol_match=0.5, trajectory_ref_usage=0.0,
            trajectory_verification=0.0, trajectory_token_efficiency=1.0,
            trajectory_completeness=0.5, trajectory_answer_correct=0.0,
            answer_format="letter_paren", failure_class="wrong_answer",
        ),
        TrialAnalysis(
            trial_index=2, task_id="t3", benchmark="arc", passed=True,
            final_answer="(C)", final_answer_length=3, refs_found=[], ref_sequence=[],
            ref_count=0, distinct_refs=0, reasoning_patterns=["elimination"],
            emergent_refs=[], protocol_sequence=[], is_emergent_sequence=False,
            trajectory_overall=0.7, trajectory_protocol_match=0.5, trajectory_ref_usage=0.0,
            trajectory_verification=0.0, trajectory_token_efficiency=1.0,
            trajectory_completeness=0.5, trajectory_answer_correct=1.0,
            answer_format="letter_paren", failure_class="none",
        ),
    ]
    clusters = cluster_trials(trials)
    # At least one cluster with "deduction" pattern
    deduction_clusters = [c for c in clusters if "deduction" in c.common_patterns]
    assert len(deduction_clusters) >= 1
    dc = deduction_clusters[0]
    assert dc.size == 2
    assert dc.pass_rate == 0.5


def test_cluster_trials_empty():
    clusters = cluster_trials([])
    assert clusters == []


def test_cluster_trials_single_trial():
    ta = TrialAnalysis(
        trial_index=0, task_id="t1", benchmark="mmlu_math", passed=True,
        final_answer="(A)", final_answer_length=3, refs_found=[], ref_sequence=[],
        ref_count=0, distinct_refs=0, reasoning_patterns=["deduction"],
        emergent_refs=[], protocol_sequence=[], is_emergent_sequence=False,
        trajectory_overall=0.8, trajectory_protocol_match=0.5, trajectory_ref_usage=0.0,
        trajectory_verification=0.0, trajectory_token_efficiency=1.0,
        trajectory_completeness=0.5, trajectory_answer_correct=1.0,
        answer_format="letter_paren", failure_class="none",
    )
    clusters = cluster_trials([ta])
    # Single-item clusters are filtered (size >= 2)
    assert clusters == []


# ---------------------------------------------------------------------------
# compute_pattern_pass_rates
# ---------------------------------------------------------------------------

def test_compute_pattern_pass_rates():
    trials = [
        _make_trial(0, True, ["deduction"]),
        _make_trial(1, True, ["deduction"]),
        _make_trial(2, False, ["deduction"]),
        _make_trial(3, True, ["elimination"]),
    ]
    rates = compute_pattern_pass_rates(trials)
    assert rates["deduction"] == 2/3
    assert rates["elimination"] == 1.0


def test_compute_pattern_pass_rates_no_patterns():
    trials = [
        _make_trial(0, True, []),
        _make_trial(1, False, []),
    ]
    rates = compute_pattern_pass_rates(trials)
    assert "no_patterns" in rates
    assert rates["no_patterns"] == 0.5


# ---------------------------------------------------------------------------
# compute_score_correlation
# ---------------------------------------------------------------------------

def test_compute_score_correlation():
    trials = [
        _make_trial(0, True, [], overall=0.9),
        _make_trial(1, True, [], overall=0.8),
        _make_trial(2, False, [], overall=0.3),
        _make_trial(3, False, [], overall=0.4),
    ]
    corr = compute_score_correlation(trials)
    assert "trajectory_overall" in corr
    assert corr["trajectory_overall"] > 0  # passed > failed


def test_compute_score_correlation_no_failures():
    trials = [_make_trial(0, True, [])]
    corr = compute_score_correlation(trials)
    assert "note" in corr


# ---------------------------------------------------------------------------
# compute_benchmark_pass_rates
# ---------------------------------------------------------------------------

def test_compute_benchmark_pass_rates():
    trials = [
        _make_trial(0, True, benchmark="mmlu_math"),
        _make_trial(1, False, benchmark="mmlu_math"),
        _make_trial(2, True, benchmark="arc"),
    ]
    rates = compute_benchmark_pass_rates(trials)
    assert rates["mmlu_math"] == 0.5
    assert rates["arc"] == 1.0


# ---------------------------------------------------------------------------
# identify_emergent_sequences
# ---------------------------------------------------------------------------

def test_identify_emergent_sequences_empty():
    trials = [_make_trial(0, True, [])]
    seqs = identify_emergent_sequences(trials)
    assert seqs == []


def test_identify_emergent_sequences_with_refs():
    trials = [
        _make_trial(0, True, [], refs=["G", "E", "P", "OUT"]),
        _make_trial(1, False, [], refs=["G", "X", "OUT"]),
    ]
    seqs = identify_emergent_sequences(trials)
    assert len(seqs) == 2
    # Find the emergent one
    emergent = [s for s in seqs if s["is_emergent"]]
    assert len(emergent) == 1
    assert emergent[0]["sequence"] == "G->X->OUT"


# ---------------------------------------------------------------------------
# compute_answer_format_distribution
# ---------------------------------------------------------------------------

def test_answer_format_distribution():
    trials = [
        _make_trial(0, True, fmt="letter_paren"),
        _make_trial(1, True, fmt="letter_paren"),
        _make_trial(2, False, fmt="number"),
    ]
    dist = compute_answer_format_distribution(trials)
    assert dist["letter_paren"] == 2
    assert dist["number"] == 1


# ---------------------------------------------------------------------------
# generate_json_report / generate_markdown_report
# ---------------------------------------------------------------------------

def test_generate_json_report():
    trials = [
        _make_trial(0, True, [], refs=["G", "E", "P", "OUT"]),
        _make_trial(1, False, [], refs=["G", "X", "OUT"]),
        _make_trial(2, True, []),
    ]
    report = generate_json_report(trials)
    assert report["total_trials"] == 3
    assert report["passed"] == 2
    assert report["failed"] == 1
    assert "G" in report["all_refs_found"]
    assert "X" in report["all_refs_found"]
    assert "X" in report["emergent_refs"]
    assert "G" not in report["emergent_refs"]


def test_generate_markdown_report():
    trials = [
        _make_trial(0, True, []),
        _make_trial(1, False, []),
    ]
    json_report = generate_json_report(trials)
    md = generate_markdown_report(json_report)
    assert "# Protocol Discovery Report" in md
    assert "Pass rate" in md
    assert "Key Findings" in md


# ---------------------------------------------------------------------------
# Integration: parse from actual benchmark data
# ---------------------------------------------------------------------------

def test_parse_from_benchmark_data():
    bench_file = Path(__file__).resolve().parent.parent / "benchmarks" / "results" / "public_benchmarks.json"
    if not bench_file.exists():
        return  # skip if not available
    with open(bench_file) as f:
        data = json.load(f)
    tahoe = [d for d in data if d.get("arm") == "tahoe"]
    assert len(tahoe) == 300
    trials = [parse_trial(t, i) for i, t in enumerate(tahoe)]
    assert len(trials) == 300
    passed = sum(1 for t in trials if t.passed)
    assert passed == 267
    assert 0.85 < passed / 300 < 0.95  # ~89%


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trial(
    idx: int,
    passed: bool,
    patterns: list[str] | None = None,
    benchmark: str = "mmlu_math",
    refs: list[str] | None = None,
    overall: float = 0.5,
    fmt: str = "letter_paren",
) -> TrialAnalysis:
    refs = refs or []
    patterns = patterns or []
    return TrialAnalysis(
        trial_index=idx,
        task_id=f"test-{idx:04d}",
        benchmark=benchmark,
        passed=passed,
        final_answer="(D)",
        final_answer_length=3,
        refs_found=refs,
        ref_sequence=refs,
        ref_count=len(refs),
        distinct_refs=len(set(refs)),
        reasoning_patterns=patterns,
        emergent_refs=identify_emergent_refs(set(refs)),
        protocol_sequence=refs,
        is_emergent_sequence=is_emergent_sequence(refs),
        trajectory_overall=overall,
        trajectory_protocol_match=0.5,
        trajectory_ref_usage=0.3 if refs else 0.0,
        trajectory_verification=0.2,
        trajectory_token_efficiency=0.9,
        trajectory_completeness=0.5,
        trajectory_answer_correct=1.0 if passed else 0.0,
        answer_format=fmt,
        failure_class="none" if passed else "wrong_answer",
    )
