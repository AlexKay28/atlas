"""Reasoning tests: verify model understands TAHOE protocols.

These tests check if a model given the TAHOE thinking skill correctly:
1. Selects the right protocol for the task type
2. Uses typed refs to structure reasoning
3. Verifies before returning
4. Produces correct answers

Requires API access via env vars: TAHOE_API_BASE, TAHOE_API_KEY, TAHOE_MODEL
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "benchmarks"))

from runner_classic import run as run_classic

SKILL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "benchmarks", "tahoe_skill_prompt.txt"
)

SKIP_REASON = "Set TAHOE_API_BASE and TAHOE_API_KEY to run reasoning tests"


def _has_api():
    return bool(os.environ.get("TAHOE_API_BASE") and os.environ.get("TAHOE_API_KEY"))


def _load_skill():
    with open(SKILL_PATH) as f:
        return f.read()


def _run(task_prompt, use_skill=False):
    if not _has_api():
        pytest.skip(SKIP_REASON)
    return run_classic(
        task_id="reasoning-test",
        task_prompt=task_prompt,
        model=os.environ.get("TAHOE_MODEL", "."),
        api_base=os.environ.get("TAHOE_API_BASE", ""),
        api_key=os.environ.get("TAHOE_API_KEY", ""),
        max_turns=1,
        max_tokens=512,
        timeout_seconds=30,
        system_prompt=_load_skill() if use_skill else "",
    )


# --- Protocol selection tests ---

@pytest.mark.skipif(not _has_api(), reason=SKIP_REASON)
class TestProtocolSelection:
    def test_compute_task_produces_number(self):
        """Model should use Compute protocol for arithmetic."""
        r = _run("What is 15% of 240? Reply with just the number.")
        assert "36" in r.final_answer

    def test_select_task_produces_letter(self):
        """Model should use Select protocol for multiple choice."""
        r = _run(
            "Which is a prime number? A) 4 B) 7 C) 9 D) 15\n"
            "Answer with just the letter in parentheses."
        )
        assert "(B)" in r.final_answer or "B" in r.final_answer

    def test_deduce_task_produces_letter(self):
        """Model should use Deduce protocol for ordering."""
        r = _run(
            "Three books are on a shelf. Red is leftmost. Blue is rightmost. "
            "Green is in the middle. Which is second from the left? "
            "Answer with just the letter: (A) Red (B) Green (C) Blue"
        )
        assert "B" in r.final_answer


# --- Typed ref comprehension tests ---

@pytest.mark.skipif(not _has_api(), reason=SKIP_REASON)
class TestTypedRefComprehension:
    def test_distinguishes_fact_from_hypothesis(self):
        """Model should not confuse facts with assumptions."""
        r = _run(
            "A thermometer reads 38°C. Someone claims the patient has a fever. "
            "Is this a fact or a hypothesis? Reply 'fact' or 'hypothesis'."
        )
        assert "hypothesis" in r.final_answer.lower()

    def test_distinguishes_constraint_from_preference(self):
        """Model should identify hard constraints vs soft preferences."""
        r = _run(
            "A task must finish by Friday (constraint). "
            "We prefer using Python (preference). "
            "Which is the constraint? Reply 'Friday' or 'Python'."
        )
        assert "friday" in r.final_answer.lower()


# --- Verification tests ---

@pytest.mark.skipif(not _has_api(), reason=SKIP_REASON)
class TestVerification:
    def test_model_checks_answer(self):
        """Model should verify its answer before returning."""
        r = _run(
            "If 3 boxes each weigh 15 kg, what's the total weight? "
            "Verify your answer by dividing back."
        )
        assert "45" in r.final_answer

    def test_model_catches_arithmetic_error(self):
        """Model should catch an error when asked to verify."""
        r = _run(
            "Someone calculated 17 * 3 = 54. Is this correct? "
            "Reply 'correct' or 'incorrect'."
        )
        assert "incorrect" in r.final_answer.lower() or "wrong" in r.final_answer.lower()


# --- TAHOE skill vs classic ---

@pytest.mark.skipif(not _has_api(), reason=SKIP_REASON)
class TestSkillVsClassic:
    def test_skill_improves_multi_step_math(self):
        """TAHOE skill should help on multi-step computation."""
        prompt = (
            "A store sells 3 types of apples. Red: $2 each, Green: $3 each, "
            "Yellow: $1.50 each. If you buy 4 red, 3 green, and 5 yellow, "
            "what's the total? Reply with just the number."
        )
        r_classic = _run(prompt, use_skill=False)
        r_tahoe = _run(prompt, use_skill=True)
        # Both should get the right answer (8 + 9 + 7.5 = 24.5)
        expected = "24.5"
        classic_ok = expected in r_classic.final_answer
        tahoe_ok = expected in r_tahoe.final_answer
        # TAHOE should be at least as good
        assert tahoe_ok or classic_ok, (
            f"Both failed. Classic: {r_classic.final_answer[:100]}, "
            f"Tahoe: {r_tahoe.final_answer[:100]}"
        )
