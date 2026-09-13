"""Arm A2 of the ablation study: run a task through a headless opencode session.

Spawns ``opencode run`` as a subprocess, parses token usage out of its
output and reports a normalized :class:`OpencodeResult` for the eval
aggregation layer.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass

RAW_OUTPUT_LIMIT = 10 * 1024

DEFAULT_MODEL = "GLM-5.3-Flash_alexkay28/."
DEFAULT_AGENT = "build"

_QUOTE_CLASS = "['\"]"


@dataclass
class OpencodeResult:
    """Normalized outcome of one headless opencode session."""

    task_id: str
    arm: str = "opencode"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    wall_seconds: float = 0.0
    passed: bool = False
    failure_class: str = "none"
    final_answer: str = ""
    raw_output: str = ""


def _kv_pattern(key: str) -> re.Pattern:
    """Match ``key: 42``, ``key=42`` and JSON-ish ``"key": "42"`` spellings."""
    return re.compile(
        rf"{key}{_QUOTE_CLASS}?\s*[:=]\s*{_QUOTE_CLASS}?(\d+)",
        re.IGNORECASE,
    )


_INPUT_PATTERNS = (
    _kv_pattern("input_tokens"),
    _kv_pattern("prompt_tokens"),
    re.compile(r"""['"]?input['"]?\s*[:=]\s*['"]?(\d+)""", re.IGNORECASE),
)
_OUTPUT_PATTERNS = (
    _kv_pattern("output_tokens"),
    _kv_pattern("completion_tokens"),
    re.compile(r"""['"]?output['"]?\s*[:=]\s*['"]?(\d+)""", re.IGNORECASE),
)
_TOTAL_PATTERNS = (
    _kv_pattern("total_tokens"),
    re.compile(r"""tokens\s+used\s*[:=]?\s*(\d+)""", re.IGNORECASE),
)


def _extract_first(patterns, text):
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def parse_token_usage(text: str) -> tuple[int, int, int]:
    """Extract ``(input_tokens, output_tokens, total_tokens)`` from output text.

    Heuristic parser covering the usual opencode/LLM usage spellings:
    ``key: value`` / ``key=value`` / JSON ``"key": value`` for
    ``input_tokens``/``prompt_tokens`` and ``output_tokens``/
    ``completion_tokens``, a nested ``{"tokens": {"input": ..., "output":
    ...}}`` object, and a bare ``tokens used: N`` line. Unrecognized output
    yields zeros; an explicit ``total_tokens`` wins over the input+output sum.
    """
    text = text or ""
    input_tokens = _extract_first(_INPUT_PATTERNS, text) or 0
    output_tokens = _extract_first(_OUTPUT_PATTERNS, text) or 0
    explicit_total = _extract_first(_TOTAL_PATTERNS, text)
    total_tokens = (
        explicit_total if explicit_total is not None else input_tokens + output_tokens
    )
    return input_tokens, output_tokens, total_tokens


def _to_text(data) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def run(
    task_id: str,
    task_prompt: str,
    model: str = DEFAULT_MODEL,
    agent: str = DEFAULT_AGENT,
    cwd: str = ".",
    max_turns: int = 10,
    timeout_seconds: int = 300,
    token_session_file: str = "",
) -> OpencodeResult:
    """Run one headless ``opencode run`` session for ``task_id``.

    If ``token_session_file`` is set, reads accumulated token counts from
    that JSON file (written by ``eval/token_proxy.py``) instead of parsing
    stdout.
    """
    started = time.monotonic()

    env = None
    if token_session_file:
        token_file_before = token_session_file
        try:
            with open(token_file_before) as f:
                before_data = json.load(f)
            inp_before = before_data.get("input_tokens", 0)
            out_before = before_data.get("output_tokens", 0)
        except Exception:
            inp_before = out_before = 0
        env = dict(os.environ)
        env["OPENAI_API_KEY"] = "dummy"
        env["OPENAI_BASE_URL"] = f"http://127.0.0.1:18888"

    command = [
        "opencode",
        "run",
        "--model", model,
        "--agent", agent,
        "--dir", cwd,
        "--title", task_id,
        task_prompt,
    ]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        wall_seconds = time.monotonic() - started
        return OpencodeResult(
            task_id=task_id,
            wall_seconds=wall_seconds,
            passed=False,
            failure_class="timeout",
            raw_output=_to_text(exc.stdout)[:RAW_OUTPUT_LIMIT],
        )
    except Exception:
        wall_seconds = time.monotonic() - started
        return OpencodeResult(
            task_id=task_id,
            wall_seconds=wall_seconds,
            passed=False,
            failure_class="error",
        )

    wall_seconds = time.monotonic() - started
    stdout = _to_text(proc.stdout)
    stderr = _to_text(proc.stderr)

    if token_session_file:
        try:
            with open(token_session_file) as f:
                after_data = json.load(f)
            input_tokens = after_data.get("input_tokens", 0) - inp_before
            output_tokens = after_data.get("output_tokens", 0) - out_before
            total_tokens = input_tokens + output_tokens
        except Exception:
            input_tokens, output_tokens, total_tokens = 0, 0, 0
    else:
        input_tokens, output_tokens, total_tokens = parse_token_usage(stdout + "\n" + stderr)

    passed = proc.returncode == 0
    return OpencodeResult(
        task_id=task_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        wall_seconds=wall_seconds,
        passed=passed,
        failure_class="none" if passed else "nonzero_exit",
        final_answer=_last_nonempty_line(stdout),
        raw_output=stdout[:RAW_OUTPUT_LIMIT],
    )
