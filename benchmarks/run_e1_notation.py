"""Experiment E1 — Notation Efficiency.

Measures token cost of expressing the same reasoning across three notations:
  1. verbose_english — full natural-language sentences
  2. tahoe_typed_refs — TAHOE canonical keywords + typed refs
  3. minimal_symbols — mathematical/symbolic shorthand

The tokenizer is a simple whitespace + punctuation splitter so the script
runs with zero external dependencies.  Results are written to
``benchmarks/results/e1_notation.json`` and printed as a table to stdout.

Usage::

    PYTHONPATH=src python3 benchmarks/run_e1_notation.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Dict, List

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[\w'+-]+|[^\w\s]")


def tokenize(text: str) -> List[str]:
    """Split on whitespace and punctuation, keeping punctuation as tokens."""
    return _TOKEN_RE.findall(text)


def token_count(text: str) -> int:
    return len(tokenize(text))


# ---------------------------------------------------------------------------
# Snippets — 10 reasoning tasks across 5 categories
# ---------------------------------------------------------------------------

@dataclass
class Snippet:
    id: str
    category: str
    description: str
    verbose_english: str
    tahoe_typed_refs: str
    minimal_symbols: str


SNIPPETS: List[Snippet] = [
    # --- arithmetic ---
    Snippet(
        id="arith_1",
        category="arithmetic",
        description="Add two numbers and check parity",
        verbose_english=(
            "If the sum of three and five is even, then return true. "
            "Otherwise return false."
        ),
        tahoe_typed_refs=(
            "IF (3+5)%2=0 THEN\n"
            "  V.result: true\n"
            "DONE"
        ),
        minimal_symbols=(
            "(3+5)%2=0 → ⊤"
        ),
    ),
    Snippet(
        id="arith_2",
        category="arithmetic",
        description="Multiply and compare to threshold",
        verbose_english=(
            "Compute six times seven. If the result is greater than forty, "
            "return the result; otherwise return zero."
        ),
        tahoe_typed_refs=(
            "x = 6*7\n"
            "IF x>40 THEN\n"
            "  V.result: x\n"
            "ELSE\n"
            "  V.result: 0\n"
            "DONE"
        ),
        minimal_symbols=(
            "x=6×7; x>40 ? x : 0"
        ),
    ),
    # --- logical deduction ---
    Snippet(
        id="logic_1",
        category="logical_deduction",
        description="Modus ponens",
        verbose_english=(
            "All humans are mortal. Socrates is a human. "
            "Therefore Socrates is mortal."
        ),
        tahoe_typed_refs=(
            "P.fact: all(human → mortal)\n"
            "P.fact: human(socrates)\n"
            "V.conclusion: mortal(socrates)\n"
            "DONE"
        ),
        minimal_symbols=(
            "∀x H(x)→M(x); H(S) ⊢ M(S)"
        ),
    ),
    Snippet(
        id="logic_2",
        category="logical_deduction",
        description="Contrapositive reasoning",
        verbose_english=(
            "If it rains, the ground is wet. The ground is not wet. "
            "Therefore it did not rain."
        ),
        tahoe_typed_refs=(
            "P.rule: rain → wet(ground)\n"
            "P.fact: ¬wet(ground)\n"
            "V.conclusion: ¬rain\n"
            "DONE"
        ),
        minimal_symbols=(
            "R→W(g); ¬W(g) ⊢ ¬R"
        ),
    ),
    # --- planning ---
    Snippet(
        id="plan_1",
        category="planning",
        description="Two-step plan with dependency",
        verbose_english=(
            "First, gather the required data from the database. "
            "Then, once the data is ready, process it and write the output."
        ),
        tahoe_typed_refs=(
            "G.step1: gather_data(db)\n"
            "G.step2: process(data) → write_output\n"
            "G.dep: step2 needs step1\n"
            "DONE"
        ),
        minimal_symbols=(
            "1: gather(db) → 2: process → write"
        ),
    ),
    Snippet(
        id="plan_2",
        category="planning",
        description="Conditional branching plan",
        verbose_english=(
            "If the file exists, read it and parse the contents. "
            "If the file does not exist, create it with default values."
        ),
        tahoe_typed_refs=(
            "IF exists(file) THEN\n"
            "  G.step1: read(file)\n"
            "  G.step2: parse(contents)\n"
            "ELSE\n"
            "  G.step1: create(file, defaults)\n"
            "DONE"
        ),
        minimal_symbols=(
            "∃f ? (read→parse) : create(f,⊥)"
        ),
    ),
    # --- selection ---
    Snippet(
        id="select_1",
        category="selection",
        description="Choose the maximum of three values",
        verbose_english=(
            "Given three values, select the one that is largest. "
            "If there is a tie, pick the first one encountered."
        ),
        tahoe_typed_refs=(
            "V.max: a\n"
            "IF b>V.max THEN V.max: b\n"
            "IF c>V.max THEN V.max: c\n"
            "DONE"
        ),
        minimal_symbols=(
            "max = a; b>max → max=b; c>max → max=c"
        ),
    ),
    Snippet(
        id="select_2",
        category="selection",
        description="Filter a list by predicate",
        verbose_english=(
            "From the list of items, keep only those that satisfy the predicate "
            "and discard the rest."
        ),
        tahoe_typed_refs=(
            "V.filtered: []\n"
            "FOR each item IN items\n"
            "  IF predicate(item) THEN append(V.filtered, item)\n"
            "DONE"
        ),
        minimal_symbols=(
            "L = [x ∈ items | p(x)]"
        ),
    ),
    # --- multi-step reasoning ---
    Snippet(
        id="multi_1",
        category="multi_step_reasoning",
        description="Transitive dependency chain",
        verbose_english=(
            "A depends on B. B depends on C. C depends on D. "
            "To compute A, we must first compute D, then C, then B."
        ),
        tahoe_typed_refs=(
            "P.dep: A→B, B→C, C→D\n"
            "G.order: [D, C, B, A]\n"
            "V.computed: resolve(A)\n"
            "DONE"
        ),
        minimal_symbols=(
            "A→B→C→D; order=[D,C,B,A]; A✓"
        ),
    ),
    Snippet(
        id="multi_2",
        category="multi_step_reasoning",
        description="Iterative refinement until convergence",
        verbose_english=(
            "Start with an initial guess. Repeat: compute the next approximation. "
            "If the change is smaller than epsilon, stop and return the result."
        ),
        tahoe_typed_refs=(
            "V.guess: initial\n"
            "LOOP\n"
            "  V.next: approximate(V.guess)\n"
            "  IF |V.next - V.guess| < ε THEN\n"
            "    V.result: V.next\n"
            "    STOP\n"
            "  V.guess: V.next\n"
            "DONE"
        ),
        minimal_symbols=(
            "x=x₀; x'=f(x); |x'-x|<ε → return x'; x=x'"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

NOTATIONS = ("verbose_english", "tahoe_typed_refs", "minimal_symbols")


@dataclass
class SnippetResult:
    id: str
    category: str
    description: str
    tokens: Dict[str, int] = field(default_factory=dict)


@dataclass
class E1Report:
    snippets: List[SnippetResult] = field(default_factory=list)
    totals: Dict[str, int] = field(default_factory=dict)
    averages: Dict[str, float] = field(default_factory=dict)
    ratios: Dict[str, Dict[str, float]] = field(default_factory=dict)


def run_experiment() -> E1Report:
    report = E1Report()
    totals = {n: 0 for n in NOTATIONS}

    for snip in SNIPPETS:
        sr = SnippetResult(id=snip.id, category=snip.category, description=snip.description)
        for nat in NOTATIONS:
            text = getattr(snip, nat)
            tc = token_count(text)
            sr.tokens[nat] = tc
            totals[nat] += tc
        report.snippets.append(sr)

    n = len(SNIPPETS)
    report.totals = totals
    report.averages = {nat: round(totals[nat] / n, 2) for nat in NOTATIONS}

    baseline = "verbose_english"
    report.ratios = {}
    for nat in NOTATIONS:
        if nat == baseline:
            report.ratios[nat] = {"vs_verbose": 1.0}
        else:
            ratio = round(totals[nat] / totals[baseline], 4) if totals[baseline] else 0.0
            report.ratios[nat] = {"vs_verbose": ratio}

    return report


def print_table(report: E1Report) -> None:
    header = f"{'ID':<12} {'Category':<22} {'Verbose':>8} {'TAHOE':>8} {'Minimal':>8}"
    print(header)
    print("-" * len(header))
    for sr in report.snippets:
        print(
            f"{sr.id:<12} {sr.category:<22} "
            f"{sr.tokens['verbose_english']:>8} "
            f"{sr.tokens['tahoe_typed_refs']:>8} "
            f"{sr.tokens['minimal_symbols']:>8}"
        )
    print("-" * len(header))
    print(
        f"{'TOTAL':<12} {'':<22} "
        f"{report.totals['verbose_english']:>8} "
        f"{report.totals['tahoe_typed_refs']:>8} "
        f"{report.totals['minimal_symbols']:>8}"
    )
    print()
    print("Averages:")
    for nat in NOTATIONS:
        print(f"  {nat:>18}: {report.averages[nat]}")
    print()
    print("Ratios vs verbose English:")
    for nat in NOTATIONS:
        print(f"  {nat:>18}: {report.ratios[nat]['vs_verbose']}")


def main() -> int:
    report = run_experiment()
    print_table(report)

    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    out_path = os.path.join(results_dir, "e1_notation.json")
    payload = {
        "experiment": "E1_notation_efficiency",
        "snippets": [asdict(sr) for sr in report.snippets],
        "totals": report.totals,
        "averages": report.averages,
        "ratios": report.ratios,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nResults saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
