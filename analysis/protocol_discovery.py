"""Protocol discovery — mine successful trajectories for emergent reasoning patterns.

Parses 300 TAHOE-arm trials from public_benchmarks.json, extracts reasoning
patterns from final_answer fields, clusters by usage patterns, identifies
emergent refs and protocol sequences, and correlates with pass/fail.

Outputs:
    analysis/protocol_discovery.json       — full structured report
    analysis/protocol_discovery_report.md   — human-readable summary

Usage:
    PYTHONPATH=src python3 analysis/protocol_discovery.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from analysis.trajectory_score import score_trajectory, TrajectoryScore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BENCHMARK_FILE = Path(__file__).resolve().parent.parent / "benchmarks" / "results" / "public_benchmarks.json"
REPORT_JSON = Path(__file__).resolve().parent / "protocol_discovery.json"
REPORT_MD = Path(__file__).resolve().parent / "protocol_discovery_report.md"

SKILL_VOCAB_REFS = {"G", "C", "E", "H", "U", "O", "K", "D", "P", "V", "OUT", "PF", "PR", "F"}

CANONICAL_PROTOCOLS = {
    "compute": ["G", "E", "P", "OUT"],
    "select": ["G", "E", "D", "OUT"],
    "deduce": ["G", "C", "P", "OUT"],
}

# Ref extraction: lines starting with UPPERCASE.word: or UPPERCASE.word =
REF_LINE_PATTERN = re.compile(r"^([A-Z]+)\.\w+\s*[:=]", re.MULTILINE)
# Also catch inline refs (not at line start) for robustness
REF_INLINE_PATTERN = re.compile(r"\b([A-Z]{1,4})\.(\w+)\s*[:=]")

# Reasoning pattern markers (natural-language patterns in final_answer)
REASONING_MARKERS = {
    "deduction": re.compile(r"\b(therefore|thus|hence|so\b|consequently)\b", re.IGNORECASE),
    "verification": re.compile(r"\b(check|verify|DONE|confirmed|valid)\b", re.IGNORECASE),
    "elimination": re.compile(r"\b(eliminat|rule out|cannot be|not possible)\b", re.IGNORECASE),
    "sequence": re.compile(r"\b(first|second|third|step \d|then|next|finally)\b", re.IGNORECASE),
    "assumption": re.compile(r"\b(assum|given|premise|basis|let us|suppose)\b", re.IGNORECASE),
    "compute": re.compile(r"\b(calculat|comput|sum|total|subtract|add|multiply|divide|=)\b", re.IGNORECASE),
    "ordering": re.compile(r"\b(position|order|arrange|leftmost|rightmost|rank)\b", re.IGNORECASE),
    "tracking": re.compile(r"\b(track|swap|start|end up|ends with)\b", re.IGNORECASE),
    "table": re.compile(r"\|.*\|.*\|", re.MULTILINE),
    "formula": re.compile(r"\b(integr|deriv|limit|series|product|sum_)", re.IGNORECASE),
}

# Answer extraction
ANSWER_LETTER = re.compile(r"\(([A-Z])\)")
ANSWER_BOLD_LETTER = re.compile(r"\*\*([A-Z])\*\*")
ANSWER_PLAIN_LETTER = re.compile(r"^\s*([A-Z])\s*$", re.MULTILINE)
ANSWER_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TrialAnalysis:
    trial_index: int
    task_id: str
    benchmark: str
    passed: bool
    final_answer: str
    final_answer_length: int
    refs_found: list[str]
    ref_sequence: list[str]
    ref_count: int
    distinct_refs: int
    reasoning_patterns: list[str]
    emergent_refs: list[str]
    protocol_sequence: list[str]
    is_emergent_sequence: bool
    trajectory_overall: float
    trajectory_protocol_match: float
    trajectory_ref_usage: float
    trajectory_verification: float
    trajectory_token_efficiency: float
    trajectory_completeness: float
    trajectory_answer_correct: float
    answer_format: str
    failure_class: str


@dataclass
class ClusterSummary:
    name: str
    size: int
    pass_rate: float
    mean_score: float
    common_refs: list[str]
    common_patterns: list[str]
    benchmark_distribution: dict[str, int]


@dataclass
class DiscoveryReport:
    total_trials: int
    passed: int
    failed: int
    pass_rate: float
    all_refs_found: list[str]
    emergent_refs: list[str]
    vocab_refs_found: list[str]
    clusters: list[dict]
    protocol_sequences: list[dict]
    emergent_sequences: list[dict]
    pattern_pass_rate: dict[str, float]
    score_correlation: dict[str, float]
    benchmark_pass_rates: dict[str, float]
    answer_format_distribution: dict[str, int]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def extract_refs(text: str) -> tuple[list[str], list[str]]:
    """Extract typed refs from text. Returns (all_refs_in_order, distinct_refs)."""
    refs = []
    seen = set()
    for m in REF_LINE_PATTERN.finditer(text):
        ref = m.group(1)
        refs.append(ref)
        seen.add(ref)
    # Also try inline pattern for robustness
    if not refs:
        for m in REF_INLINE_PATTERN.finditer(text):
            ref = m.group(1)
            if len(ref) <= 4 and ref.isupper():
                refs.append(ref)
                seen.add(ref)
    return refs, list(seen)


def extract_reasoning_patterns(text: str) -> list[str]:
    """Detect natural-language reasoning patterns in the final_answer text."""
    found = []
    for name, pattern in REASONING_MARKERS.items():
        if pattern.search(text):
            found.append(name)
    return found


def identify_emergent_refs(refs: set[str]) -> list[str]:
    """Identify refs not in the skill prompt vocabulary."""
    return sorted(refs - SKILL_VOCAB_REFS)


def identify_protocol_sequence(refs: list[str]) -> list[str]:
    """Map ref sequence to protocol steps."""
    return refs  # The ref sequence IS the protocol sequence


def is_emergent_sequence(refs: list[str]) -> bool:
    """Check if a ref sequence doesn't match any canonical protocol."""
    if not refs:
        return False
    for protocol_name, canonical in CANONICAL_PROTOCOLS.items():
        # Check if the refs are a subsequence of the canonical protocol
        if _is_subsequence(refs, canonical):
            return False
    return True


def _is_subsequence(seq: list[str], template: list[str]) -> bool:
    it = iter(template)
    return all(item in it for item in seq)


def detect_answer_format(text: str) -> str:
    """Classify the format of the final answer."""
    text = text.strip()
    if ANSWER_LETTER.search(text):
        return "letter_paren"
    if ANSWER_BOLD_LETTER.search(text):
        return "letter_bold"
    if ANSWER_PLAIN_LETTER.search(text):
        return "letter_plain"
    if re.match(r"^-?\d+(?:\.\d+)?$", text):
        return "number"
    if re.match(r"^\$", text):
        return "dollar"
    if len(text) > 100:
        return "extended_reasoning"
    if re.match(r"^-?\d+(?:\.\d+)?$", text.split("\n")[0].strip()):
        return "number"
    return "short_text"


def determine_task_type(benchmark: str) -> str:
    """Map benchmark name to task type for trajectory scoring."""
    mapping = {
        "mmlu_math": "compute",
        "gsm8k": "compute",
        "bbh_arith": "compute",
        "mmlu_acct": "compute",
        "arc": "select",
        "race": "select",
        "mmlu_logic": "deduce",
        "bbh": "deduce",
        "bbh_track": "deduce",
        "lsat": "deduce",
    }
    return mapping.get(benchmark, "compute")


def parse_trial(trial: dict, index: int) -> TrialAnalysis:
    """Parse a single trial into a TrialAnalysis."""
    fa = trial.get("final_answer", "")
    refs_in_order, distinct_refs = extract_refs(fa)
    reasoning_patterns = extract_reasoning_patterns(fa)
    emergent = identify_emergent_refs(set(distinct_refs))
    protocol_seq = identify_protocol_sequence(refs_in_order)
    emergent_seq = is_emergent_sequence(refs_in_order)
    task_type = determine_task_type(trial.get("benchmark", ""))

    # Score trajectory
    expected = _extract_expected(trial)
    ts = score_trajectory(fa, task_type, expected)

    return TrialAnalysis(
        trial_index=index,
        task_id=trial.get("task_id", ""),
        benchmark=trial.get("benchmark", ""),
        passed=trial.get("passed", False),
        final_answer=fa,
        final_answer_length=len(fa),
        refs_found=refs_in_order,
        ref_sequence=refs_in_order,
        ref_count=len(refs_in_order),
        distinct_refs=len(distinct_refs),
        reasoning_patterns=reasoning_patterns,
        emergent_refs=emergent,
        protocol_sequence=protocol_seq,
        is_emergent_sequence=emergent_seq,
        trajectory_overall=ts.overall,
        trajectory_protocol_match=ts.protocol_match,
        trajectory_ref_usage=ts.ref_usage,
        trajectory_verification=ts.verification,
        trajectory_token_efficiency=ts.token_efficiency,
        trajectory_completeness=ts.completeness,
        trajectory_answer_correct=ts.answer_correct,
        answer_format=detect_answer_format(fa),
        failure_class=trial.get("failure_class", ""),
    )


def _extract_expected(trial: dict) -> Optional[str]:
    """Extract expected answer from grader_detail."""
    gd = trial.get("grader_detail", "")
    m = re.search(r"expected=([^,]+)", gd)
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def cluster_trials(trials: list[TrialAnalysis]) -> list[ClusterSummary]:
    """Cluster trials by ref-type usage patterns and reasoning patterns."""
    clusters: dict[str, list[TrialAnalysis]] = defaultdict(list)

    for t in trials:
        # Cluster key: combination of reasoning patterns + ref presence
        ref_key = "+".join(sorted(set(t.refs_found))) if t.refs_found else "no_refs"
        pattern_key = "+".join(sorted(t.reasoning_patterns)) if t.reasoning_patterns else "no_patterns"
        key = f"{ref_key}|{pattern_key}"
        clusters[key].append(t)

    # Also cluster by benchmark + pattern
    benchmark_pattern_clusters: dict[str, list[TrialAnalysis]] = defaultdict(list)
    for t in trials:
        pattern_key = "+".join(sorted(t.reasoning_patterns)) if t.reasoning_patterns else "no_patterns"
        key = f"{t.benchmark}|{pattern_key}"
        benchmark_pattern_clusters[key].append(t)

    summaries = []
    for name, group in clusters.items():
        if len(group) < 2:
            continue
        summaries.append(_make_cluster_summary(name, group))

    for name, group in benchmark_pattern_clusters.items():
        if len(group) < 2:
            continue
        summaries.append(_make_cluster_summary(f"bench:{name}", group))

    # Sort by size descending
    summaries.sort(key=lambda c: c.size, reverse=True)
    return summaries


def _make_cluster_summary(name: str, group: list[TrialAnalysis]) -> ClusterSummary:
    passed = sum(1 for t in group if t.passed)
    total = len(group)
    mean_score = sum(t.trajectory_overall for t in group) / total

    ref_counter = Counter()
    pattern_counter = Counter()
    bench_counter = Counter()
    for t in group:
        ref_counter.update(t.refs_found)
        pattern_counter.update(t.reasoning_patterns)
        bench_counter[t.benchmark] += 1

    return ClusterSummary(
        name=name,
        size=total,
        pass_rate=passed / total,
        mean_score=mean_score,
        common_refs=[r for r, _ in ref_counter.most_common(5)],
        common_patterns=[p for p, _ in pattern_counter.most_common(5)],
        benchmark_distribution=dict(bench_counter),
    )


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def compute_pattern_pass_rates(trials: list[TrialAnalysis]) -> dict[str, float]:
    """Compute pass rate for each reasoning pattern."""
    pattern_trials: dict[str, list[bool]] = defaultdict(list)
    for t in trials:
        for p in t.reasoning_patterns:
            pattern_trials[p].append(t.passed)
        if not t.reasoning_patterns:
            pattern_trials["no_patterns"].append(t.passed)

    result = {}
    for pattern, passed_list in pattern_trials.items():
        if passed_list:
            result[pattern] = sum(1 for p in passed_list if p) / len(passed_list)
    return dict(sorted(result.items(), key=lambda x: x[1], reverse=True))


def compute_score_correlation(trials: list[TrialAnalysis]) -> dict[str, float]:
    """Correlate trajectory score components with pass/fail."""
    passed = [t for t in trials if t.passed]
    failed = [t for t in trials if not t.passed]

    if not passed or not failed:
        return {"note": "insufficient data for correlation"}

    result = {}
    components = [
        "trajectory_overall",
        "trajectory_protocol_match",
        "trajectory_ref_usage",
        "trajectory_verification",
        "trajectory_token_efficiency",
        "trajectory_completeness",
        "trajectory_answer_correct",
    ]
    for comp in components:
        pass_mean = sum(getattr(t, comp) for t in passed) / len(passed)
        fail_mean = sum(getattr(t, comp) for t in failed) / len(failed)
        result[comp] = round(pass_mean - fail_mean, 4)
    return result


def compute_benchmark_pass_rates(trials: list[TrialAnalysis]) -> dict[str, float]:
    """Compute pass rate per benchmark."""
    bench_trials: dict[str, list[bool]] = defaultdict(list)
    for t in trials:
        bench_trials[t.benchmark].append(t.passed)
    return {b: sum(1 for p in ps if p) / len(ps) for b, ps in bench_trials.items()}


def identify_emergent_sequences(trials: list[TrialAnalysis]) -> list[dict]:
    """Identify emergent protocol sequences (not matching canonical patterns)."""
    seq_counter: Counter = Counter()
    seq_pass: dict[str, list[bool]] = defaultdict(list)

    for t in trials:
        if t.protocol_sequence:
            seq = "->".join(t.protocol_sequence)
            seq_counter[seq] += 1
            seq_pass[seq].append(t.passed)

    result = []
    for seq, count in seq_counter.most_common():
        passes = seq_pass[seq]
        pr = sum(1 for p in passes if p) / len(passes)
        is_emerg = is_emergent_sequence(seq.split("->"))
        result.append({
            "sequence": seq,
            "count": count,
            "pass_rate": round(pr, 4),
            "is_emergent": is_emerg,
        })
    return result


def compute_answer_format_distribution(trials: list[TrialAnalysis]) -> dict[str, int]:
    dist = Counter(t.answer_format for t in trials)
    return dict(dist)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_json_report(trials: list[TrialAnalysis]) -> dict:
    all_refs = set()
    for t in trials:
        all_refs.update(t.refs_found)

    vocab_refs = all_refs & SKILL_VOCAB_REFS
    emergent_refs = all_refs - SKILL_VOCAB_REFS

    clusters = cluster_trials(trials)
    pattern_rates = compute_pattern_pass_rates(trials)
    score_corr = compute_score_correlation(trials)
    bench_rates = compute_benchmark_pass_rates(trials)
    emergent_seqs = identify_emergent_sequences(trials)
    fmt_dist = compute_answer_format_distribution(trials)

    passed = sum(1 for t in trials if t.passed)

    report = DiscoveryReport(
        total_trials=len(trials),
        passed=passed,
        failed=len(trials) - passed,
        pass_rate=passed / len(trials),
        all_refs_found=sorted(all_refs),
        emergent_refs=sorted(emergent_refs),
        vocab_refs_found=sorted(vocab_refs),
        clusters=[{
            "name": c.name,
            "size": c.size,
            "pass_rate": round(c.pass_rate, 4),
            "mean_score": round(c.mean_score, 4),
            "common_refs": c.common_refs,
            "common_patterns": c.common_patterns,
            "benchmark_distribution": c.benchmark_distribution,
        } for c in clusters],
        protocol_sequences=[s for s in emergent_seqs if not s["is_emergent"]],
        emergent_sequences=[s for s in emergent_seqs if s["is_emergent"]],
        pattern_pass_rate=pattern_rates,
        score_correlation=score_corr,
        benchmark_pass_rates={k: round(v, 4) for k, v in bench_rates.items()},
        answer_format_distribution=fmt_dist,
    )

    return asdict(report)


def generate_markdown_report(report: dict) -> str:
    lines = []
    lines.append("# Protocol Discovery Report")
    lines.append("")
    lines.append(f"**Trials analyzed:** {report['total_trials']}  ")
    lines.append(f"**Passed:** {report['passed']} | **Failed:** {report['failed']}  ")
    lines.append(f"**Pass rate:** {report['pass_rate']:.1%}")
    lines.append("")

    lines.append("## Refs Found")
    lines.append("")
    lines.append(f"- **Vocabulary refs (in skill prompt):** {', '.join(report['vocab_refs_found']) or '(none)'}")
    lines.append(f"- **Emergent refs (not in vocabulary):** {', '.join(report['emergent_refs']) or '(none)'}")
    lines.append(f"- **All refs:** {', '.join(report['all_refs_found']) or '(none)'}")
    lines.append("")

    lines.append("## Benchmark Pass Rates")
    lines.append("")
    lines.append("| Benchmark | Pass Rate |")
    lines.append("|-----------|-----------|")
    for bench, rate in sorted(report["benchmark_pass_rates"].items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {bench} | {rate:.1%} |")
    lines.append("")

    lines.append("## Reasoning Pattern Pass Rates")
    lines.append("")
    lines.append("| Pattern | Pass Rate |")
    lines.append("|---------|-----------|")
    for pattern, rate in report["pattern_pass_rate"].items():
        lines.append(f"| {pattern} | {rate:.1%} |")
    lines.append("")

    lines.append("## Score Correlation (passed_mean - failed_mean)")
    lines.append("")
    lines.append("| Component | Delta |")
    lines.append("|-----------|-------|")
    for comp, delta in report["score_correlation"].items():
        lines.append(f"| {comp} | {delta:+.4f} |")
    lines.append("")

    lines.append("## Protocol Sequences")
    lines.append("")
    if report["protocol_sequences"]:
        lines.append("| Sequence | Count | Pass Rate |")
        lines.append("|----------|-------|-----------|")
        for s in report["protocol_sequences"]:
            lines.append(f"| {s['sequence']} | {s['count']} | {s['pass_rate']:.1%} |")
    else:
        lines.append("No canonical protocol sequences found in final_answer fields.")
    lines.append("")

    lines.append("## Emergent Sequences")
    lines.append("")
    if report["emergent_sequences"]:
        lines.append("| Sequence | Count | Pass Rate |")
        lines.append("|----------|-------|-----------|")
        for s in report["emergent_sequences"]:
            lines.append(f"| {s['sequence']} | {s['count']} | {s['pass_rate']:.1%} |")
    else:
        lines.append("No emergent protocol sequences found.")
    lines.append("")

    lines.append("## Clusters (size >= 2)")
    lines.append("")
    lines.append("| Cluster | Size | Pass Rate | Mean Score | Common Patterns |")
    lines.append("|---------|------|-----------|------------|-----------------|")
    for c in report["clusters"][:20]:
        pats = ", ".join(c["common_patterns"][:3])
        lines.append(f"| {c['name']} | {c['size']} | {c['pass_rate']:.1%} | {c['mean_score']:.3f} | {pats} |")
    lines.append("")

    lines.append("## Answer Format Distribution")
    lines.append("")
    lines.append("| Format | Count |")
    lines.append("|--------|-------|")
    for fmt, count in sorted(report["answer_format_distribution"].items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {fmt} | {count} |")
    lines.append("")

    lines.append("## Key Findings")
    lines.append("")
    lines.append(f"1. **Pass rate:** {report['pass_rate']:.1%} across {report['total_trials']} trials")
    if report["emergent_refs"]:
        lines.append(f"2. **Emergent refs discovered:** {', '.join(report['emergent_refs'])}")
    else:
        lines.append("2. **No emergent refs** — all refs found are within the skill vocabulary")
    lines.append(f"3. **Most predictive score component:** {_most_predictive(report['score_correlation'])}")
    lines.append(f"4. **Best benchmark:** {_best_benchmark(report['benchmark_pass_rates'])}")
    lines.append(f"5. **Worst benchmark:** {_worst_benchmark(report['benchmark_pass_rates'])}")
    lines.append("")

    return "\n".join(lines)


def _most_predictive(corr: dict) -> str:
    if "note" in corr:
        return corr["note"]
    if not corr:
        return "n/a"
    best = max(corr.items(), key=lambda x: x[1])
    return f"{best[0]} (delta={best[1]:+.4f})"


def _best_benchmark(rates: dict) -> str:
    if not rates:
        return "n/a"
    best = max(rates.items(), key=lambda x: x[1])
    return f"{best[0]} ({best[1]:.1%})"


def _worst_benchmark(rates: dict) -> str:
    if not rates:
        return "n/a"
    worst = min(rates.items(), key=lambda x: x[1])
    return f"{worst[0]} ({worst[1]:.1%})"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Loading benchmark data from {BENCHMARK_FILE}...")
    with open(BENCHMARK_FILE) as f:
        raw_data = json.load(f)

    tahoe_trials = [d for d in raw_data if d.get("arm") == "tahoe"]
    print(f"Found {len(tahoe_trials)} tahoe-arm trials")

    trials = [parse_trial(t, i) for i, t in enumerate(tahoe_trials)]
    print(f"Parsed {len(trials)} trial analyses")

    # Generate reports
    json_report = generate_json_report(trials)
    md_report = generate_markdown_report(json_report)

    # Save JSON
    with open(REPORT_JSON, "w") as f:
        json.dump(json_report, f, indent=2)
    print(f"JSON report saved to {REPORT_JSON}")

    # Save markdown
    with open(REPORT_MD, "w") as f:
        f.write(md_report)
    print(f"Markdown report saved to {REPORT_MD}")

    # Print summary to stdout
    print(f"\n{'='*60}")
    print(f"Protocol Discovery Summary")
    print(f"{'='*60}")
    print(f"Trials: {json_report['total_trials']}")
    print(f"Pass rate: {json_report['pass_rate']:.1%}")
    print(f"Refs found: {json_report['all_refs_found']}")
    print(f"Emergent refs: {json_report['emergent_refs']}")
    print(f"Emergent sequences: {len(json_report['emergent_sequences'])}")
    print(f"Clusters: {len(json_report['clusters'])}")


if __name__ == "__main__":
    main()
