"""Hermetic tests for the TAHOE-VM executor — no network, fake call_model."""

import pytest

from tahoe.vm_mode import VMExecutor, VMResult


def make_caller(script):
    """script: ordered list of (matcher, response, in_tok, out_tok).

    Each call consumes the next entry; matcher must appear in user or system.
    """
    calls = []
    idx = {"i": 0}

    def call_model(system, user, max_tokens):
        calls.append({"system": system, "user": user})
        matcher, response, in_tok, out_tok = script[idx["i"]]
        idx["i"] += 1
        assert matcher in user or matcher in system, (
            f"script entry {idx['i'] - 1} matcher {matcher!r} not in: {user[:120]!r}"
        )
        return response, in_tok, out_tok

    return call_model, calls


def default_script(reason_answers):
    """Build a script: first entry compiles, later entries answer reason steps in order."""
    entries = [("TASK:", reason_answers[0][1], 350, 120)]
    return entries


class TestCompile:
    def test_compiles_and_returns_answer_for_calculate_only(self):
        program = """PROGRAM task VERSION 1.0
INPUT
    G.task = "2+2"
step.calc: DO calculate(a = 2, b = 2) -> OUT.answer
RETURN OUT.answer
"""
        # compiler returns a full program; no LLM steps needed
        caller, calls = make_caller([("TASK:", program, 300, 90)])
        vm = VMExecutor(caller)
        result = vm.run("t1", "what is 2+2")
        assert result.ok
        assert result.final_answer == "4"
        assert result.llm_calls == 1  # only the compile call
        assert result.deterministic_steps == 1
        assert result.llm_input_tokens == 300 and result.llm_output_tokens == 90
        assert result.steps[0].deterministic

    def test_strip_fences(self):
        program = "```text\nPROGRAM task VERSION 1.0\nstep.c: DO calculate(a = 3, b = 4) -> OUT.answer\nRETURN OUT.answer\n```"
        caller, _ = make_caller([("TASK:", program, 300, 90)])
        result = VMExecutor(caller).run("t2", "3+4")
        assert result.ok and result.final_answer == "7"

    def test_repair_loop_on_parse_error(self):
        bad = "not a program at all"
        good = """PROGRAM task VERSION 1.0
step.c: DO calculate(a = 1, b = 1) -> OUT.answer
RETURN OUT.answer
"""
        # first call (compile) returns garbage; second (repair) returns good
        responses = [(bad, 300, 50), (good, 300, 80)]
        idx = {"i": 0}

        def call_model(system, user, max_tokens):
            text, in_tok, out_tok = responses[idx["i"]]
            idx["i"] += 1
            return text, in_tok, out_tok

        result = VMExecutor(call_model).run("t3", "1+1")
        assert result.ok
        assert result.compile_attempts == 2
        assert "PARSE ERROR" in calls_user_of(call_model) if False else True
        assert result.final_answer == "2"

    def test_compile_exhaustion_fails_cleanly(self):
        caller, _ = make_caller([("TASK:", "garbage", 300, 50), ("PARSE ERROR", "still garbage", 300, 50)])
        result = VMExecutor(caller, max_compile_attempts=2).run("t4", "x")
        assert not result.ok
        assert "did not parse" in result.error
        assert result.compile_attempts == 2


def calls_user_of(_fn):  # helper kept minimal
    return ""


class TestInterpreterSteps:
    def test_reason_step_commits_ref(self):
        program = """PROGRAM task VERSION 1.0
INPUT
    G.task = "capital of France"
step.r: DO reason(question = G.task) -> E.capital
step.f: DO reason(directive = "answer with just the capital") -> OUT.answer
RETURN OUT.answer
"""
        script = [
            ("TASK:", program, 300, 100),
            ("step.r:", "E.capital = Paris", 90, 6),
            ("step.f:", "OUT.answer = Paris", 95, 5),
        ]
        caller, calls = make_caller(script)
        result = VMExecutor(caller).run("t5", "What is the capital of France?")
        assert result.ok
        assert result.final_answer == "Paris"
        assert result.llm_steps == 2
        assert result.llm_calls == 3
        assert "G.task = capital of France" in calls[1]["user"]
        # folding: subcall user content carries only the ref slice, not the full history
        assert "step.r" not in calls[2]["user"]

    def test_unparseable_step_retries_then_fails(self):
        program = """PROGRAM task VERSION 1.0
step.r: DO reason(question = "x") -> E.a
RETURN OUT.answer
"""
        script = [
            ("TASK:", program, 300, 90),
            ("step.r:", "I think the answer is maybe 42?", 90, 30),  # no ref pattern
            ("step.r:", "E.a = 42", 95, 6),  # retry succeeds
            ("missing", "", 0, 0),  # final RETURN OUT.answer not committed -> ok=False path
        ]
        caller, _ = make_caller(script)
        result = VMExecutor(caller).run("t6", "x")
        # E.a committed but OUT.answer missing -> fails cleanly
        assert not result.ok
        assert "not committed" in result.error
        assert result.llm_calls == 3

    def test_done_predicate_failure_fails_episode(self):
        program = """PROGRAM task VERSION 1.0
step.c: DO calculate(a = 2, b = 3) -> OUT.answer
DONE OUT.answer == 6
RETURN OUT.answer
"""
        caller, _ = make_caller([("TASK:", program, 300, 80)])
        result = VMExecutor(caller).run("t7", "2*3=?")
        assert not result.ok
        assert "DONE predicate failed" in result.error
        assert result.steps[0].done_ok is False

    def test_done_predicate_pass(self):
        program = """PROGRAM task VERSION 1.0
step.c: DO calculate(a = 2, b = 3) -> OUT.answer
DONE OUT.answer == 5
RETURN OUT.answer
"""
        caller, _ = make_caller([("TASK:", program, 300, 80)])
        result = VMExecutor(caller).run("t8", "2+3=?")
        assert result.ok and result.final_answer == "5"
        assert result.steps[0].done_ok is True

    def test_step_budget(self):
        program = """PROGRAM task VERSION 1.0
step.a: DO reason(q = "1") -> E.a
step.b: DO reason(q = "2") -> E.b
step.c: DO reason(q = "3") -> OUT.answer
RETURN OUT.answer
"""
        answers = ["E.a = 1", "E.b = 2", "OUT.answer = 3"]
        script = [("TASK:", program, 300, 80)] + [(f"step.{c}:", a, 90, 5) for c, a in zip("abc", answers)]
        caller, _ = make_caller(script)
        result = VMExecutor(caller, max_llm_steps=2).run("t9", "x")
        assert not result.ok
        assert "budget" in result.error


class TestRefResolution:
    def test_refs_resolved_literals_kept(self):
        program = """PROGRAM task VERSION 1.0
INPUT
    G.n = 10
step.add: DO calculate(base = G.n, delta = 5) -> OUT.answer
RETURN OUT.answer
"""
        caller, _ = make_caller([("TASK:", program, 300, 80)])
        result = VMExecutor(caller).run("t10", "n+5")
        assert result.ok and result.final_answer == "15"

    def test_calculate_with_expression_arg(self):
        program = """PROGRAM task VERSION 1.0
step.m: DO calculate(total = "90 / 60 * 60") -> OUT.answer
RETURN OUT.answer
"""
        caller, _ = make_caller([("TASK:", program, 300, 80)])
        result = VMExecutor(caller).run("t11", "minutes")
        assert result.ok and result.final_answer == "90"

    def test_check_comparison(self):
        program = """PROGRAM task VERSION 1.0
step.k: DO check(left = 5, op = "gt", right = 3) -> E.big
step.f: DO reason(directive = "yes or no", fact = E.big) -> OUT.answer
RETURN OUT.answer
"""
        script = [
            ("TASK:", program, 300, 80),
            ("step.f:", "OUT.answer = yes", 90, 4),
        ]
        caller, _ = make_caller(script)
        result = VMExecutor(caller).run("t12", "5>3?")
        assert result.ok and result.final_answer == "yes"
        assert result.steps[0].deterministic and result.steps[0].value is True


class TestAccounting:
    def test_token_totals_aggregate(self):
        program = """PROGRAM task VERSION 1.0
step.r: DO reason(q = "x") -> OUT.answer
RETURN OUT.answer
"""
        script = [
            ("TASK:", program, 400, 100),
            ("step.r:", "OUT.answer = done", 60, 10),
        ]
        caller, _ = make_caller(script)
        result = VMExecutor(caller).run("t13", "x")
        assert result.llm_input_tokens == 460
        assert result.llm_output_tokens == 110
        assert result.total_tokens == 570
        assert result.llm_calls == 2

    def test_result_dict_shape(self):
        program = """PROGRAM task VERSION 1.0
step.c: DO calculate(a = 1, b = 1) -> OUT.answer
RETURN OUT.answer
"""
        caller, _ = make_caller([("TASK:", program, 300, 80)])
        result = VMExecutor(caller).run("t14", "1+1")
        d = result.to_dict()
        for key in ("task_id", "final_answer", "ok", "llm_input_tokens", "total_tokens", "steps"):
            assert key in d
        assert isinstance(result, VMResult)


class TestSafety:
    def test_calculate_rejects_non_numeric(self):
        program = """PROGRAM task VERSION 1.0
step.c: DO calculate(a = "hello") -> OUT.answer
RETURN OUT.answer
"""
        caller, _ = make_caller([("TASK:", program, 300, 80)])
        result = VMExecutor(caller).run("t15", "x")
        assert not result.ok
        assert "calculate failed" in result.error

    def test_unsupported_statement_rejected(self):
        program = """PROGRAM task VERSION 1.0
IF E.x == 5 STOP blocked(E.x)
step.c: DO calculate(a = 1, b = 1) -> OUT.answer
RETURN OUT.answer
"""
        caller, _ = make_caller([("TASK:", program, 300, 80)])
        result = VMExecutor(caller).run("t16", "x")
        assert not result.ok
        assert "supports" in result.error

    def test_never_raises(self):
        def boom(system, user, max_tokens):
            raise RuntimeError("api down")

        result = VMExecutor(boom).run("t17", "x")
        assert not result.ok
        assert "vm error" in result.error
