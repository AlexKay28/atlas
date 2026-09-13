"""Tests for the live-model worker adapter (``LiveModelWorker`` / ``make_worker``).

Covers the T1+ real-model adapter that calls an OpenAI-compatible
chat-completions endpoint through the ``openai`` package (imported
lazily), the ``make_worker`` tier factory (T0 -> deterministic worker,
T1+ -> live worker gated on ``TAHOE_API_BASE``/``TAHOE_API_KEY``) and
the graceful failure path.  The ``openai`` client is mocked with
``unittest.mock.patch`` — no network access happens in these tests.
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

from tahoe.runtime.coordinator import DeterministicWorker
from tahoe.worker_adapter import (
    DEFAULT_LIVE_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    LiveModelWorker,
    LiveResult,
    make_worker,
)

TAHOE_ENV_KEYS = ("TAHOE_API_BASE", "TAHOE_API_KEY", "TAHOE_MODEL")

API_BASE = "https://api.example.test/v1"
API_KEY = "k-test"


def _scrubbed_env():
    """Full environment copy without any TAHOE_* worker configuration."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in TAHOE_ENV_KEYS
    }


def _fake_openai_module(response=None, error=None):
    """A fake ``openai`` module whose ``OpenAI`` client dispatch is staged.

    The lazy ``import openai`` inside ``LiveModelWorker._get_client``
    picks this module up from ``sys.modules`` when it is patch-dicted in.
    """
    fake_module = mock.MagicMock()
    client = fake_module.OpenAI.return_value
    if error is not None:
        client.chat.completions.create.side_effect = error
    else:
        client.chat.completions.create.return_value = response
    return fake_module, client


def _fake_response(content, prompt_tokens=11, completion_tokens=7):
    response = mock.MagicMock()
    choice = mock.MagicMock()
    choice.message.content = content
    response.choices = [choice]
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = completion_tokens
    return response


class LiveModelWorkerImportTest(unittest.TestCase):
    def test_live_model_worker_class_exists_and_imports(self):
        from tahoe import worker_adapter
        from tahoe.worker_adapter import LiveModelWorker as LMW

        self.assertIs(LMW, worker_adapter.LiveModelWorker)
        self.assertTrue(hasattr(LMW, "dispatch"))
        self.assertTrue(hasattr(LMW, "execute"))
        worker = LMW(api_base=API_BASE, api_key=API_KEY)
        self.assertIsInstance(worker, LiveModelWorker)
        self.assertIsInstance(worker.commands, set)
        self.assertTrue(len(worker.commands) > 0)

    def test_module_import_does_not_import_openai(self):
        # Requirement: the openai import is lazy, so importing the module
        # must succeed in a fresh interpreter even though we exercise no
        # dispatch there.
        code = (
            "import sys; import tahoe.worker_adapter;"
            " assert 'openai' not in sys.modules,"
            " 'openai was imported eagerly by tahoe.worker_adapter'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "PYTHONPATH": "src"},
        )
        self.assertEqual(
            result.returncode, 0, msg=result.stderr or result.stdout
        )


class MakeWorkerTest(unittest.TestCase):
    def test_tier0_returns_the_deterministic_worker(self):
        with mock.patch.dict(os.environ, _scrubbed_env(), clear=True):
            worker = make_worker(0)
        self.assertIsInstance(worker, DeterministicWorker)
        self.assertEqual(worker.commands, set())

    def test_tier0_accepts_t0_string_and_handlers(self):
        def handler(**_kwargs):
            return "ok"

        with mock.patch.dict(os.environ, _scrubbed_env(), clear=True):
            worker = make_worker("T0", handlers={"echo": handler})
        self.assertIsInstance(worker, DeterministicWorker)

    def test_missing_env_raises_value_error(self):
        with mock.patch.dict(os.environ, _scrubbed_env(), clear=True):
            with self.assertRaises(ValueError) as ctx:
                make_worker(1)
        message = str(ctx.exception)
        self.assertIn("TAHOE_API_BASE", message)
        self.assertIn("TAHOE_API_KEY", message)

    def test_higher_tier_missing_env_also_raises(self):
        with mock.patch.dict(os.environ, _scrubbed_env(), clear=True):
            with self.assertRaises(ValueError):
                make_worker("T3")

    def test_live_worker_returned_when_env_set(self):
        env = _scrubbed_env()
        env.update(
            {
                "TAHOE_API_BASE": API_BASE,
                "TAHOE_API_KEY": API_KEY,
            }
        )
        with mock.patch.dict(os.environ, env, clear=True):
            worker = make_worker("T1")
        self.assertIsInstance(worker, LiveModelWorker)
        self.assertEqual(worker.api_base, API_BASE)
        self.assertEqual(worker.api_key, API_KEY)
        self.assertEqual(worker.model, DEFAULT_LIVE_MODEL)

    def test_tahoe_model_env_overrides_default_model(self):
        env = _scrubbed_env()
        env.update(
            {
                "TAHOE_API_BASE": API_BASE,
                "TAHOE_API_KEY": API_KEY,
                "TAHOE_MODEL": "glm-custom-model",
            }
        )
        with mock.patch.dict(os.environ, env, clear=True):
            worker = make_worker(2)
        self.assertIsInstance(worker, LiveModelWorker)
        self.assertEqual(worker.model, "glm-custom-model")


class DispatchTest(unittest.TestCase):
    def _worker(self):
        return LiveModelWorker(api_base=API_BASE, api_key=API_KEY)

    def test_dispatch_valid_response_returns_text_usage_and_success(self):
        fake_openai, client = _fake_openai_module(
            response=_fake_response(
                '{"answer": 42}', prompt_tokens=12, completion_tokens=34
            )
        )
        with mock.patch.dict(sys.modules, {"openai": fake_openai}):
            worker = self._worker()
            result = worker.dispatch("DO the thing")

        self.assertIsInstance(result, LiveResult)
        self.assertTrue(result.success)
        self.assertEqual(result.text, '{"answer": 42}')
        self.assertEqual(result.input_tokens, 12)
        self.assertEqual(result.output_tokens, 34)
        self.assertEqual(result.usage, {"input_tokens": 12, "output_tokens": 34})
        self.assertIsNone(result.failure_class)
        self.assertIsNone(result.error)

        fake_openai.OpenAI.assert_called_once_with(
            base_url=API_BASE, api_key="dummy", timeout=DEFAULT_TIMEOUT_SECONDS,
            default_headers={"Authorization": f"OAuth {API_KEY}", "Ya-Pool": "notelm"}
        )
        client.chat.completions.create.assert_called_once()
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], DEFAULT_LIVE_MODEL)
        self.assertEqual(
            kwargs["messages"],
            [{"role": "user", "content": "DO the thing"}],
        )

    def test_dispatch_api_error_returns_failure_not_raise(self):
        fake_openai, _client = _fake_openai_module(
            error=RuntimeError("boom: upstream exploded")
        )
        with mock.patch.dict(sys.modules, {"openai": fake_openai}):
            result = self._worker().dispatch("DO the thing")

        self.assertIsInstance(result, LiveResult)
        self.assertFalse(result.success)
        self.assertEqual(result.text, "")
        self.assertEqual(result.failure_class, "api_error")
        self.assertIn("boom", result.error)
        self.assertIsNone(result.input_tokens)
        self.assertIsNone(result.output_tokens)
        self.assertIsNone(result.usage)

    def test_dispatch_classifies_rate_limit_errors(self):
        RateLimitError = type("RateLimitError", (Exception,), {})
        fake_openai, _client = _fake_openai_module(
            error=RateLimitError("429 slow down")
        )
        with mock.patch.dict(sys.modules, {"openai": fake_openai}):
            result = self._worker().dispatch("DO the thing")

        self.assertFalse(result.success)
        self.assertEqual(result.failure_class, "rate_limit")

    def test_execute_renders_command_into_the_prompt(self):
        fake_openai, client = _fake_openai_module(
            response=_fake_response('{"ok": true}')
        )
        with mock.patch.dict(sys.modules, {"openai": fake_openai}):
            result = self._worker().execute("echo", {"value": 7})

        self.assertIsInstance(result, dict)
        self.assertEqual(result, {"ok": True})
        sent = client.chat.completions.create.call_args.kwargs
        self.assertEqual(sent["model"], DEFAULT_LIVE_MODEL)
        prompt = sent["messages"][0]["content"]
        self.assertIn("Command: echo", prompt)
        self.assertIn('"value": 7', prompt)

    def test_direct_construction_without_config_raises_value_error(self):
        with mock.patch.dict(os.environ, _scrubbed_env(), clear=True):
            with self.assertRaises(ValueError) as ctx:
                LiveModelWorker()
        self.assertIn("TAHOE_API_BASE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
