"""Classic inference arm (A1) runner for the ablation study.

A thin OpenAI-compatible chat-completions loop with tool-schema support and
token tracking. No sealed program, no structured state.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_MODEL = "GLM-5.3-Flash_alexkay28/."
ENV_API_BASE = "TAHOE_API_BASE"
ENV_API_KEY = "TAHOE_API_KEY"

FAILURE_NONE = "none"
FAILURE_API_ERROR = "api_error"
FAILURE_TIMEOUT = "timeout"
FAILURE_MAX_TURNS = "max_turns"


@dataclass
class ClassicResult:
    """Outcome of a single classic-arm run."""

    task_id: str
    arm: str = "classic"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    wall_seconds: float = 0.0
    passed: bool = False
    failure_class: str = "none"
    turns: int = 0
    final_answer: str = ""


def _parse_tool_arguments(raw: Any) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _is_timeout(exc: BaseException, openai_module: Any) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    timeout_type = getattr(openai_module, "APITimeoutError", None)
    return isinstance(timeout_type, type) and isinstance(exc, timeout_type)


def run(
    task_id: str,
    task_prompt: str,
    model: str = DEFAULT_MODEL,
    api_base: str = "",
    api_key: str = "",
    max_turns: int = 10,
    max_tokens: int = 4096,
    timeout_seconds: int = 120,
    tools: list[dict] | None = None,
    tool_implementations: dict[str, Callable[..., Any]] | None = None,
    system_prompt: str = "",
) -> ClassicResult:
    """Run one task through a plain chat-completions loop and return a ClassicResult."""
    resolved_key = api_key or os.environ.get(ENV_API_KEY, "")
    if not resolved_key:
        raise ValueError(
            "no API key available: pass api_key or set the TAHOE_API_KEY environment variable"
        )
    resolved_base = api_base or os.environ.get(ENV_API_BASE, "")

    import openai

    client_kwargs: dict[str, Any] = {"api_key": "dummy", "timeout": timeout_seconds}
    if resolved_base:
        client_kwargs["base_url"] = resolved_base
    client_kwargs["default_headers"] = {
        "Authorization": f"OAuth {resolved_key}",
        **({"Ya-Pool": os.environ["TAHOE_API_POOL"]} if os.environ.get("TAHOE_API_POOL") else {}),
    }
    client = openai.OpenAI(**client_kwargs)

    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": task_prompt})
    request_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        request_kwargs["tools"] = tools

    implementations = tool_implementations or {}
    input_tokens = 0
    output_tokens = 0
    turns = 0
    started = time.monotonic()
    deadline = started + max(timeout_seconds, 0)
    failure_class = FAILURE_NONE
    final_answer = ""

    def finish(passed: bool) -> ClassicResult:
        return ClassicResult(
            task_id=task_id,
            arm="classic",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            wall_seconds=time.monotonic() - started,
            passed=passed,
            failure_class=failure_class,
            turns=turns,
            final_answer=final_answer,
        )

    while turns < max_turns:
        if time.monotonic() >= deadline:
            failure_class = FAILURE_TIMEOUT
            return finish(False)
        try:
            response = client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            failure_class = (
                FAILURE_TIMEOUT if _is_timeout(exc, openai) else FAILURE_API_ERROR
            )
            return finish(False)
        turns += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": getattr(message, "content", None) or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": getattr(call.function, "arguments", "") or "",
                            },
                        }
                        for call in tool_calls
                    ],
                }
            )
            for call in tool_calls:
                name = call.function.name
                arguments = _parse_tool_arguments(getattr(call.function, "arguments", None))
                implementation = implementations.get(name)
                if implementation is None:
                    output = f"error: no implementation registered for tool {name!r}"
                else:
                    try:
                        output = implementation(**arguments)
                    except Exception as exc:
                        output = f"error: tool {name!r} failed: {exc}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": name,
                        "content": str(output),
                    }
                )
            continue
        final_answer = getattr(message, "content", None) or ""
        return finish(True)

    failure_class = FAILURE_MAX_TURNS
    return finish(False)
