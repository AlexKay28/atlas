import dataclasses
import inspect
import subprocess
from unittest import mock

import pytest

from eval.runner_opencode import OpencodeResult, parse_token_usage, run


def _fake_completed(returncode=0, stdout="", stderr=""):
    proc = mock.Mock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


class TestOpencodeResultDataclass:
    def test_has_expected_fields(self):
        field_names = {field.name for field in dataclasses.fields(OpencodeResult)}
        expected = {
            "task_id",
            "arm",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "wall_seconds",
            "passed",
            "failure_class",
            "final_answer",
            "raw_output",
        }
        assert field_names == expected

    def test_defaults(self):
        result = OpencodeResult(task_id="t1")
        assert result.arm == "opencode"
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.total_tokens == 0
        assert result.wall_seconds == 0.0
        assert result.passed is False
        assert result.failure_class == "none"
        assert result.final_answer == ""
        assert result.raw_output == ""


class TestImportAndSignature:
    def test_runner_importable(self):
        import eval.runner_opencode as runner_module

        assert callable(runner_module.run)
        assert dataclasses.is_dataclass(runner_module.OpencodeResult)

    def test_run_signature(self):
        signature = inspect.signature(run)
        assert list(signature.parameters) == [
            "task_id",
            "task_prompt",
            "model",
            "agent",
            "cwd",
            "max_turns",
            "timeout_seconds",
            "token_session_file",
        ]
        assert signature.parameters["model"].default == "GLM-5.3-Flash_alexkay28/."
        assert signature.parameters["agent"].default == "build"
        assert signature.parameters["cwd"].default == "."
        assert signature.parameters["max_turns"].default == 10
        assert signature.parameters["timeout_seconds"].default == 300
        assert signature.return_annotation in (OpencodeResult, "OpencodeResult")


class TestRunSuccess:
    def test_exit_zero_with_token_output(self):
        proc = _fake_completed(
            returncode=0,
            stdout=(
                "Reading repository...\n"
                "Editing eval/runner_opencode.py\n"
                "input_tokens: 500\n"
                "output_tokens: 120\n"
                "total_tokens: 620\n"
                "All finished"
            ),
            stderr="",
        )
        with mock.patch("subprocess.run", return_value=proc) as mocked:
            result = run(task_id="task-1", task_prompt="do things")

        assert result.task_id == "task-1"
        assert result.arm == "opencode"
        assert result.passed is True
        assert result.failure_class == "none"
        assert result.input_tokens == 500
        assert result.output_tokens == 120
        assert result.total_tokens == 620
        assert result.final_answer == "All finished"
        assert result.wall_seconds >= 0.0
        assert "input_tokens: 500" in result.raw_output

        command = mocked.call_args.args[0]
        assert command[:2] == ["opencode", "run"]
        expected_flags = {
            "--model": "GLM-5.3-Flash_alexkay28/.",
            "--agent": "build",
            "--dir": ".",
            "--title": "task-1",
        }
        for flag, value in expected_flags.items():
            assert flag in command
            assert command[command.index(flag) + 1] == value
        assert command[-1] == "do things"
        assert mocked.call_args.kwargs["timeout"] == 300

    def test_model_agent_and_dir_overrides(self):
        proc = _fake_completed(returncode=0, stdout="done\n", stderr="")
        with mock.patch("subprocess.run", return_value=proc) as mocked:
            result = run(
                task_id="task-2",
                task_prompt="p",
                model="mymodel",
                agent="plan",
                cwd="/tmp/somewhere",
            )

        command = mocked.call_args.args[0]
        assert command[command.index("--model") + 1] == "mymodel"
        assert command[command.index("--agent") + 1] == "plan"
        assert command[command.index("--dir") + 1] == "/tmp/somewhere"
        assert result.passed is True

    def test_empty_stdout_gives_empty_final_answer(self):
        proc = _fake_completed(returncode=0, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=proc):
            result = run(task_id="task-3", task_prompt="p")

        assert result.passed is True
        assert result.final_answer == ""

    def test_raw_output_truncated_to_10kb(self):
        proc = _fake_completed(returncode=0, stdout="x" * (20 * 1024), stderr="")
        with mock.patch("subprocess.run", return_value=proc):
            result = run(task_id="task-4", task_prompt="p")

        assert len(result.raw_output) == 10 * 1024


class TestRunFailures:
    def test_timeout(self):
        with mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="opencode", timeout=5),
        ) as mocked:
            result = run(task_id="task-5", task_prompt="slow", timeout_seconds=5)

        assert result.task_id == "task-5"
        assert result.passed is False
        assert result.failure_class == "timeout"
        assert result.arm == "opencode"
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert mocked.call_args.kwargs["timeout"] == 5

    def test_nonzero_exit(self):
        proc = _fake_completed(
            returncode=3,
            stdout="partial output\ninput_tokens: 42\noutput_tokens: 7",
            stderr="boom",
        )
        with mock.patch("subprocess.run", return_value=proc):
            result = run(task_id="task-6", task_prompt="break")

        assert result.passed is False
        assert result.failure_class == "nonzero_exit"
        assert result.input_tokens == 42
        assert result.output_tokens == 7
        assert result.total_tokens == 49

    def test_generic_exception(self):
        with mock.patch("subprocess.run", side_effect=OSError("opencode not found")):
            result = run(task_id="task-7", task_prompt="p")

        assert result.passed is False
        assert result.failure_class == "error"
        assert result.final_answer == ""
        assert result.raw_output == ""


class TestTokenParsing:
    @pytest.mark.parametrize(
        "text, expected_input, expected_output",
        [
            ("input_tokens: 500 output_tokens: 200", 500, 200),
            ("input_tokens=500\noutput_tokens=200", 500, 200),
            ('{"usage": {"input_tokens": 500, "output_tokens": 200}}', 500, 200),
            ('input_tokens: "500"\noutput_tokens: "200"', 500, 200),
            ('{"tokens": {"input": 500, "output": 200}}', 500, 200),
            ("tokens(input=500, output=200)", 500, 200),
            ("prompt_tokens: 10\ncompletion_tokens: 4", 10, 4),
            ("no token information at all", 0, 0),
            ("", 0, 0),
            ("input_tokens: 0", 0, 0),
        ],
    )
    def test_various_output_formats(self, text, expected_input, expected_output):
        input_tokens, output_tokens, total_tokens = parse_token_usage(text)
        assert input_tokens == expected_input
        assert output_tokens == expected_output
        assert total_tokens == expected_input + expected_output

    def test_explicit_total_tokens_wins(self):
        _, _, total_tokens = parse_token_usage(
            '{"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}'
        )
        assert total_tokens == 15

    def test_tokens_used_fallback_counts_as_total(self):
        input_tokens, output_tokens, total_tokens = parse_token_usage("Tokens used: 700")
        assert input_tokens == 0
        assert output_tokens == 0
        assert total_tokens == 700
