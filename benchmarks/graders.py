"""Programmatic graders for the ablation study.

A grader is a callable that receives ``(result, expected_state)`` and returns
``(passed: bool, detail: str)`` where:

- ``result`` is the final answer/output produced by the arm runner;
- ``expected_state`` is the dict from the task manifest (grader-specific
  fields, optionally merged with ``grader.params`` by the runner).
"""

from __future__ import annotations

import json
import subprocess

__all__ = [
    "ExactMatchGrader",
    "ContainsGrader",
    "JSONFieldGrader",
    "TestPassGrader",
    "CompositeGrader",
    "NumericGrader",
    "make_grader",
]

_TEST_CMD_TIMEOUT_SECONDS = 60


class ExactMatchGrader:
    """Passes when ``result == expected_state["answer"]`` (string match)."""

    def __call__(self, result, expected_state: dict) -> tuple[bool, str]:
        expected = expected_state.get("answer")
        if result == expected:
            return True, f"exact match: {expected!r}"
        return False, f"expected {expected!r}, got {result!r}"


class ContainsGrader:
    """Passes when ``expected_state["substring"]`` occurs in ``result``."""

    def __call__(self, result, expected_state: dict) -> tuple[bool, str]:
        substring = expected_state.get("substring")
        if substring is None:
            return False, "expected_state is missing 'substring'"
        text = result if isinstance(result, str) else str(result)
        if substring in text:
            return True, f"found substring {substring!r}"
        return False, f"substring {substring!r} not found in result"


class JSONFieldGrader:
    """Parses ``result`` as JSON and checks that the field named by
    ``expected_state["field"]`` equals ``expected_state["value"]``."""

    def __call__(self, result, expected_state: dict) -> tuple[bool, str]:
        field = expected_state.get("field")
        value = expected_state.get("value")
        if isinstance(result, dict):
            data = result
        else:
            text = result if isinstance(result, str) else str(result)
            try:
                data = json.loads(text)
            except ValueError as exc:
                return False, f"result is not valid JSON: {exc}"
        if not isinstance(data, dict):
            return False, f"parsed JSON is {type(data).__name__}, expected an object"
        if field not in data:
            return False, f"field {field!r} missing from JSON"
        if data[field] == value:
            return True, f"field {field!r} == {value!r}"
        return False, f"field {field!r}: expected {value!r}, got {data[field]!r}"


class TestPassGrader:
    """Runs the shell command ``expected_state["test_cmd"]`` and passes when
    it exits with code 0."""

    def __call__(self, result, expected_state: dict) -> tuple[bool, str]:
        cmd = expected_state.get("test_cmd")
        if not cmd:
            return False, "expected_state is missing 'test_cmd'"
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=_TEST_CMD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return False, (
                f"test command timed out after {_TEST_CMD_TIMEOUT_SECONDS}s: {cmd}"
            )
        if proc.returncode == 0:
            return True, f"test command exited 0: {cmd}"
        detail = f"test command exited {proc.returncode}: {cmd}"
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if output:
            detail += f" | last output line: {output.splitlines()[-1]}"
        return False, detail


class CompositeGrader:
    """Runs multiple sub-graders; all must pass.

    Sub-graders come from the constructor (grader instances, type-name strings
    or ``{"type": ..., "params": {...}}`` dicts) or, when the constructor got
    nothing, from ``expected_state["graders"]`` in the same three forms. A
    dict spec's ``params`` are merged over a copy of ``expected_state`` for
    that sub-grader only.
    """

    def __init__(self, graders=None):
        if graders is not None and callable(graders):
            graders = [graders]
        self._graders = graders

    def __call__(self, result, expected_state: dict) -> tuple[bool, str]:
        try:
            resolved = list(self._resolve(expected_state))
        except ValueError as exc:
            return False, str(exc)
        if not resolved:
            return False, "composite grader has no sub-graders"
        details = []
        passed = True
        for name, grader, state in resolved:
            ok, detail = grader(result, state)
            passed = passed and ok
            details.append(f"{name}: {'PASS' if ok else 'FAIL'} ({detail})")
        return passed, "; ".join(details)

    def _resolve(self, expected_state: dict):
        specs = self._graders
        if specs is None:
            specs = expected_state.get("graders") or []
        for spec in specs:
            if callable(spec):
                yield type(spec).__name__, spec, expected_state
            elif isinstance(spec, str):
                grader = make_grader(spec)
                yield type(grader).__name__, grader, expected_state
            elif isinstance(spec, dict):
                grader = make_grader(spec.get("type", ""))
                merged = dict(expected_state)
                merged.update(spec.get("params") or {})
                yield type(grader).__name__, grader, merged
            else:
                raise ValueError(f"invalid sub-grader spec: {spec!r}")


class NumericGrader:
    """Extracts the first number from the answer and compares to expected.

    Handles markdown tables, sentences, JSON wrappers, and TAHOE metadata.
    """

    def __init__(self):
        import re
        self._re = re.compile(r"(?<!\d)(\d+)(?!\d)")

    def __call__(self, result, expected_state: dict) -> tuple[bool, str]:
        expected = expected_state.get("value")
        if expected is None:
            return False, "expected_state is missing 'value'"
        text = result if isinstance(result, str) else str(result)
        numbers = self._re.findall(text)
        if not numbers:
            return False, f"no number found in result: {text[:100]!r}"
        if str(expected) in numbers:
            return True, f"found expected number {expected}"
        return False, f"expected {expected}, found numbers: {numbers}"


_GRADER_TYPES = {
    "exact_match": ExactMatchGrader,
    "contains": ContainsGrader,
    "json_field": JSONFieldGrader,
    "test_pass": TestPassGrader,
    "composite": CompositeGrader,
    "numeric": NumericGrader,
}


def make_grader(grader_type: str):
    """Build a grader instance from a manifest ``grader.type`` string."""
    try:
        return _GRADER_TYPES[grader_type]()
    except KeyError:
        known = ", ".join(sorted(_GRADER_TYPES))
        raise ValueError(
            f"unknown grader type: {grader_type!r} (known types: {known})"
        ) from None
