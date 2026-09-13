"""Tests for benchmarks/runner_classic.py, the classic inference arm (A1)."""

import dataclasses
import importlib.util
import inspect
import os
import sys
import types
from types import SimpleNamespace
from unittest import mock

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_RUNNER_PATH = os.path.join(_ROOT, "benchmarks", "runner_classic.py")


def _load_runner_module():
    try:
        import benchmarks.runner_classic as module

        if os.path.abspath(module.__file__ or "") == os.path.abspath(_RUNNER_PATH):
            return module
    except Exception:
        pass
    spec = importlib.util.spec_from_file_location("runner_classic_under_test", _RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner_classic = _load_runner_module()
ClassicResult = runner_classic.ClassicResult
run = runner_classic.run


def _response(content=None, tool_calls=None, prompt_tokens=10, completion_tokens=5):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _tool_call(call_id="call_1", name="lookup", arguments='{"q": "x"}'):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def _fake_openai_module():
    fake = types.ModuleType("openai")
    fake.APIError = type("APIError", (Exception,), {})
    fake.APITimeoutError = type("APITimeoutError", (Exception,), {})
    return fake


def _install_client_factory(fake_openai, steps):
    created = []

    class _Completions:
        def __init__(self, script):
            self._script = list(script)
            self.calls = []

        def create(self, **kwargs):
            recorded = {}
            for key, value in kwargs.items():
                if key == "messages":
                    recorded[key] = [dict(item) for item in value]
                else:
                    recorded[key] = value
            self.calls.append(recorded)
            step = self._script.pop(0)
            if isinstance(step, BaseException):
                raise step
            return step

    def factory(**kwargs):
        completions = _Completions(steps)
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions),
            init_kwargs=dict(kwargs),
        )
        created.append(client)
        return client

    fake_openai.OpenAI = factory
    return created


def test_classic_result_dataclass_has_expected_fields():
    assert dataclasses.is_dataclass(ClassicResult)
    names = [field.name for field in dataclasses.fields(ClassicResult)]
    assert names == [
        "task_id",
        "arm",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "wall_seconds",
        "passed",
        "failure_class",
        "turns",
        "final_answer",
    ]
    result = ClassicResult(task_id="task-1")
    assert result.arm == "classic"
    assert result.failure_class == "none"
    assert result.final_answer == ""
    assert result.passed is False


def test_runner_module_is_importable():
    assert callable(runner_classic.run)
    assert dataclasses.is_dataclass(runner_classic.ClassicResult)
    assert runner_classic.ClassicResult is ClassicResult


def test_module_imports_without_openai_installed():
    class _OpenAIBlocker:
        def find_spec(self, name, path=None, target=None):
            if name == "openai" or name.startswith("openai."):
                raise ImportError("openai is blocked for this test")
            return None

    spec = importlib.util.spec_from_file_location("runner_classic_no_openai", _RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    blocker = _OpenAIBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.pop(spec.name, None)
    assert callable(module.run)


def test_run_signature_matches_spec():
    params = inspect.signature(run).parameters
    for name in (
        "task_id",
        "task_prompt",
        "model",
        "api_base",
        "api_key",
        "max_turns",
        "max_tokens",
        "timeout_seconds",
        "tools",
    ):
        assert name in params
    assert params["model"].default == "GLM-5.3-Flash_alexkay28/."
    assert params["api_base"].default == ""
    assert params["api_key"].default == ""
    assert params["max_turns"].default == 10
    assert params["max_tokens"].default == 4096
    assert params["timeout_seconds"].default == 120
    assert params["tools"].default is None


def test_missing_api_key_raises_value_error():
    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="TAHOE_API_KEY"):
            run("task-1", "do the task")


def test_single_turn_immediate_answer():
    fake_openai = _fake_openai_module()
    created = _install_client_factory(
        fake_openai,
        [_response(content="42", prompt_tokens=11, completion_tokens=7)],
    )
    with mock.patch.dict(sys.modules, {"openai": fake_openai}):
        result = run(
            "task-1",
            "What is the answer?",
            api_key="test-key",
            api_base="http://fake.local/v1",
        )
    assert isinstance(result, ClassicResult)
    assert result.task_id == "task-1"
    assert result.arm == "classic"
    assert result.passed is True
    assert result.failure_class == "none"
    assert result.turns == 1
    assert result.final_answer == "42"
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.total_tokens == 18
    assert result.wall_seconds >= 0.0
    assert len(created) == 1
    client = created[0]
    assert client.init_kwargs["api_key"] == "dummy"
    assert client.init_kwargs["default_headers"]["Authorization"] == "OAuth test-key"
    assert client.init_kwargs["base_url"] == "http://fake.local/v1"
    assert client.init_kwargs["timeout"] == 120
    calls = client.chat.completions.calls
    assert len(calls) == 1
    assert calls[0]["model"] == "GLM-5.3-Flash_alexkay28/."
    assert calls[0]["max_tokens"] == 4096
    assert calls[0]["messages"] == [{"role": "user", "content": "What is the answer?"}]
    assert "tools" not in calls[0]


def test_tool_call_then_answer_two_turns():
    fake_openai = _fake_openai_module()
    created = _install_client_factory(
        fake_openai,
        [
            _response(
                tool_calls=[_tool_call(name="lookup", arguments='{"q": "x"}')],
                prompt_tokens=10,
                completion_tokens=4,
            ),
            _response(content="done", prompt_tokens=12, completion_tokens=6),
        ],
    )
    tool_schema = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
        }
    ]
    with mock.patch.dict(sys.modules, {"openai": fake_openai}):
        result = run(
            "task-2",
            "use the lookup tool",
            api_key="test-key",
            tools=tool_schema,
            tool_implementations={"lookup": lambda q: f"result:{q}"},
        )
    assert result.passed is True
    assert result.failure_class == "none"
    assert result.turns == 2
    assert result.final_answer == "done"
    assert result.input_tokens == 22
    assert result.output_tokens == 10
    assert result.total_tokens == 32
    client = created[0]
    calls = client.chat.completions.calls
    assert len(calls) == 2
    assert calls[0]["tools"] == tool_schema
    second_messages = calls[1]["messages"]
    assert [m["role"] for m in second_messages] == ["user", "assistant", "tool"]
    assert second_messages[1]["tool_calls"][0]["function"]["name"] == "lookup"
    assert second_messages[2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "lookup",
        "content": "result:x",
    }


def test_max_turns_exceeded_fails():
    fake_openai = _fake_openai_module()
    created = _install_client_factory(
        fake_openai,
        [_response(tool_calls=[_tool_call(name="spin", arguments="{}")]) for _ in range(3)],
    )
    with mock.patch.dict(sys.modules, {"openai": fake_openai}):
        result = run(
            "task-3",
            "keep calling the tool",
            api_key="test-key",
            max_turns=3,
            tool_implementations={"spin": lambda: "tick"},
        )
    assert result.passed is False
    assert result.failure_class == "max_turns"
    assert result.turns == 3
    assert result.final_answer == ""
    assert result.input_tokens == 30
    assert result.output_tokens == 15
    assert result.total_tokens == 45
    assert len(created[0].chat.completions.calls) == 3


def test_api_error_is_reported():
    fake_openai = _fake_openai_module()
    _install_client_factory(fake_openai, [fake_openai.APIError("boom")])
    with mock.patch.dict(sys.modules, {"openai": fake_openai}):
        result = run("task-4", "hello", api_key="test-key")
    assert result.passed is False
    assert result.failure_class == "api_error"
    assert result.turns == 0
    assert result.final_answer == ""


def test_timeout_error_is_reported():
    fake_openai = _fake_openai_module()
    _install_client_factory(fake_openai, [fake_openai.APITimeoutError("too slow")])
    with mock.patch.dict(sys.modules, {"openai": fake_openai}):
        result = run("task-5", "hello", api_key="test-key")
    assert result.passed is False
    assert result.failure_class == "timeout"
    assert result.turns == 0


def test_env_fallback_for_api_key_and_base():
    fake_openai = _fake_openai_module()
    created = _install_client_factory(fake_openai, [_response(content="hi")])
    env = {"TAHOE_API_KEY": "env-key", "TAHOE_API_BASE": "http://env.local/v1"}
    with mock.patch.dict(os.environ, env, clear=True):
        with mock.patch.dict(sys.modules, {"openai": fake_openai}):
            result = run("task-6", "hello")
    assert result.passed is True
    assert result.final_answer == "hi"
    assert created[0].init_kwargs["api_key"] == "dummy"
    assert created[0].init_kwargs["default_headers"]["Authorization"] == "OAuth env-key"
    assert created[0].init_kwargs["base_url"] == "http://env.local/v1"


def test_missing_usage_is_tolerated():
    fake_openai = _fake_openai_module()
    response = _response(content="ok")
    response.usage = None
    _install_client_factory(fake_openai, [response])
    with mock.patch.dict(sys.modules, {"openai": fake_openai}):
        result = run("task-7", "hello", api_key="test-key")
    assert result.passed is True
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.total_tokens == 0
