"""TAHOE reasoning trajectory scoring.

Scores a model's reasoning output against TAHOE language patterns.
Each trajectory receives a score from 0.0 to 1.0 based on:
- Protocol adherence (did it use the right pattern?)
- Typed ref discipline (G/C/E/H/V/OUT used correctly?)
- Verification quality (DONE check present?)
- Token efficiency (concrete values, no narrative?)
- Completeness (all protocol artifacts present?)
- Answer correctness (final answer matches expected?)

Usage:
    from analysis.trajectory_score import score_trajectory
    score = score_trajectory(reasoning_text, task_type="compute", expected_answer="21")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

TYPED_REFS = (
    r"\bG\.", r"\bC\.", r"\bE\.", r"\bH\.", r"\bU\.", r"\bO\.",
    r"\bK\.", r"\bD\.", r"\bP\.", r"\bV\.", r"\bX\.", r"\bR\.",
    r"\bART\.", r"\bOUT\.",
)
TYPED_REF_PATTERN = re.compile("|".join(TYPED_REFS))

DONE_PATTERN = re.compile(r"\bDONE\b", re.IGNORECASE)
STEP_PATTERN = re.compile(r"step\.\w+:", re.IGNORECASE)
CONCRETE_NUMBER_PATTERN = re.compile(r"\b\d+\s*[+\-*/]\s*\d+\s*=\s*\d+")
NARRATIVE_MARKERS = re.compile(
    r"\b(let me think|well,|as i was saying|i need to consider|"
    r"first, let me|now i should|let's work through)\b",
    re.IGNORECASE,
)

PROTOCOL_KEYWORDS = {
    "compute": ["calculate", "check", "report", "subtotal", "total", "tax", "sum"],
    "select": ["eliminate", "choose", "select", "option", "choice"],
    "deduce": ["position", "constraint", "order", "arrange", "leftmost", "rightmost"],
    "decide": ["option", "criteria", "decision", "choose", "alternative"],
    "plan": ["decompose", "subtask", "step", "order", "ordered"],
    "debug": ["hypothesis", "cause", "verify", "reproduce", "root"],
    "explore": ["evidence", "unknown", "question", "finding", "explore"],
    "review": ["defect", "finding", "evidence", "severity", "review"],
    "learn": ["recall", "transfer", "model", "prediction", "learn"],
}


@dataclass
class TrajectoryScore:
    overall: float
    protocol_match: float
    ref_usage: float
    verification: float
    token_efficiency: float
    completeness: float
    answer_correct: float
    details: list[str] = field(default_factory=list)


def _score_protocol_match(text: str, task_type: str) -> tuple[float, str]:
    keywords = PROTOCOL_KEYWORDS.get(task_type, [])
    if not keywords:
        return 1.0, "unknown task type — no protocol match check"
    found = sum(1 for kw in keywords if kw in text.lower())
    ratio = found / len(keywords)
    return ratio, f"matched {found}/{len(keywords)} protocol keywords"


def _score_ref_usage(text: str) -> tuple[float, str]:
    refs_found = set(TYPED_REF_PATTERN.findall(text))
    if not refs_found:
        return 0.0, "no typed refs found"
    distinct = len(refs_found)
    score = min(distinct / 5.0, 1.0)
    return score, f"{distinct} distinct typed refs used"


def _score_verification(text: str) -> tuple[float, str]:
    has_done = bool(DONE_PATTERN.search(text))
    has_step = bool(STEP_PATTERN.search(text))
    has_concrete_check = bool(CONCRETE_NUMBER_PATTERN.search(text))
    score = 0.0
    details = []
    if has_done:
        score += 0.5
        details.append("DONE predicate present")
    if has_concrete_check:
        score += 0.3
        details.append("concrete verification")
    if has_step:
        score += 0.2
        details.append("step structure")
    if score == 0:
        details.append("no verification found")
    return score, "; ".join(details)


def _score_token_efficiency(text: str) -> tuple[float, str]:
    narrative_count = len(NARRATIVE_MARKERS.findall(text))
    has_concrete = bool(CONCRETE_NUMBER_PATTERN.search(text))
    score = 1.0
    score -= min(narrative_count * 0.2, 0.6)
    if has_concrete:
        score += 0.1
    score = max(min(score, 1.0), 0.0)
    markers = f"{narrative_count} narrative markers"
    if has_concrete:
        markers += ", concrete values present"
    return score, markers


def _score_completeness(text: str, task_type: str) -> tuple[float, str]:
    required = {
        "compute": ["G", "OUT"],
        "select": ["G", "D", "OUT"],
        "deduce": ["G", "C", "OUT"],
        "decide": ["G", "C", "O", "K", "D", "OUT"],
        "plan": ["G", "OUT"],
        "debug": ["G", "E", "H", "OUT"],
        "explore": ["G", "E", "OUT"],
        "review": ["G", "E", "OUT"],
        "learn": ["G", "H", "OUT"],
    }
    needed = required.get(task_type, ["G", "OUT"])
    found = set()
    for ref in needed:
        if re.search(rf"\b{re.escape(ref)}\.", text):
            found.add(ref)
    ratio = len(found) / len(needed) if needed else 1.0
    return ratio, f"{len(found)}/{len(needed)} required refs present"


def _score_answer(text: str, expected: Optional[str]) -> tuple[float, str]:
    if expected is None:
        return 1.0, "no expected answer to check"
    expected_clean = expected.strip()
    text_clean = text.strip()
    if expected_clean in text_clean:
        return 1.0, "expected answer found in output"
    nums = re.findall(r"\d+", text_clean)
    expected_nums = re.findall(r"\d+", expected_clean)
    if nums and expected_nums and nums[-1] == expected_nums[-1]:
        return 1.0, "final number matches expected"
    return 0.0, f"expected {expected_clean!r}, not found"


def score_trajectory(
    reasoning_text: str,
    task_type: str = "compute",
    expected_answer: Optional[str] = None,
) -> TrajectoryScore:
    score = TrajectoryScore(
        overall=0.0,
        protocol_match=0.0,
        ref_usage=0.0,
        verification=0.0,
        token_efficiency=0.0,
        completeness=0.0,
        answer_correct=0.0,
    )

    score.protocol_match, d = _score_protocol_match(reasoning_text, task_type)
    score.details.append(f"protocol: {d}")
    score.ref_usage, d = _score_ref_usage(reasoning_text)
    score.details.append(f"refs: {d}")
    score.verification, d = _score_verification(reasoning_text)
    score.details.append(f"verification: {d}")
    score.token_efficiency, d = _score_token_efficiency(reasoning_text)
    score.details.append(f"efficiency: {d}")
    score.completeness, d = _score_completeness(reasoning_text, task_type)
    score.details.append(f"completeness: {d}")
    score.answer_correct, d = _score_answer(reasoning_text, expected_answer)
    score.details.append(f"answer: {d}")

    score.overall = (
        0.20 * score.protocol_match
        + 0.15 * score.ref_usage
        + 0.20 * score.verification
        + 0.15 * score.token_efficiency
        + 0.15 * score.completeness
        + 0.15 * score.answer_correct
    )
    return score
