"""VMExecutor — compile task to program, execute steps via self-subcalls.

The model-callable is injected (``call_model``), so tests are hermetic and
the benchmark runner stays thin: in production ``call_model`` wraps the same
OpenAI-compatible endpoint used by the classic/prompt-tahoe arms (GLM-5.3-Flash
via Eliza), keeping the eval invariant intact.

Token economics (insights/token-economics.md):
- compiler call: 1 per episode (~200-400 tokens) — this IS the compressed reasoning
- interpreter subcalls: static prefix (cache-eligible) + step + ref slice
- calculate/check steps: ZERO model tokens (local, deterministic)
- subcall contexts are discarded after each step (folding) — main context
  grows O(refs), not O(history)
"""

from __future__ import annotations

import ast
import json
import operator
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from tahoe.syntax.parser import ParseError, parse_program

# ---------------------------------------------------------------------------
# Static prompts — byte-identical across subcalls (prefix-cache eligible)
# ---------------------------------------------------------------------------

COMPILER_SYSTEM = """You are a planning compiler for the TAHOE reasoning language.
Given a task, emit a program that structures its solution. You do NOT solve the task here.

Canonical example (follow this shape EXACTLY):
PROGRAM task VERSION 1.0
INPUT
    G.task = "A train leaves at 14:20 and travels 90 km at 60 km/h. When does it arrive?"
step.hours: DO calculate(km = 90, speed = 60) -> E.hours
step.arrive: DO reason(base_time = "14:20", hours_needed = E.hours) -> E.arrival
step.answer: DO reason(directive = "state the arrival time as HH:MM only") -> OUT.answer
RETURN OUT.answer

Format rules (violations break the parser):
- Steps look EXACTLY like: step.<lowercase_id>: DO <op>(<name> = <value>, ...) -> <TARGET>
- step ids are lowercase words (hours, arrive) — NEVER numbers, never STEP/DEFINE/assign syntax.
- No comments (// or #), no blank keys, no markdown fences.
- Ops: reason(<name> = <value>...) one reasoning step; calculate(...) exact arithmetic
  (numbers are summed; ONE quoted expression allowed: calculate(total = "90 / 60 * 60"));
  check(left = ..., op = "eq|ne|gt|ge|lt|le", right = ...) comparison.
- <value> is a typed ref (G.task, E.hours) or a short quoted literal.
- Targets are typed refs: OUT.x, E.x, T.x, G.x. Final step writes OUT.answer.
- MARKOV CLOSURE: every ref a step needs MUST be one of its arguments —
  the interpreter sees only the args. reason(question = G.task) not reason("...").
- 2 to 8 steps. Decompose; do not answer in the program.
Output ONLY the program text."""

INTERPRETER_SYSTEM = """You are the TAHOE interpreter. Execute EXACTLY the step you are given.
Emit one single line: <target> = <value>
- <value> is a short fact (max 25 words), a number, or a choice letter.
- Use ONLY the provided refs and the step's own instruction. No explanations, no extra lines."""

REPAIR_SYSTEM = """You are a planning compiler for the TAHOE reasoning language.
Your previous program failed to parse. Rewrite it in the EXACT canonical shape below and
output ONLY the corrected program text (no fences, no comments, no DEFINE/assign syntax).

Canonical shape:
PROGRAM task VERSION 1.0
INPUT
    G.task = "<task>"
step.<lowercase_id>: DO <op>(<name> = <value>, ...) -> <TARGET>
RETURN OUT.answer
Ops: reason(...) one reasoning step; calculate(...) numbers summed or one quoted expression;
check(left, op = "eq|ne|gt|ge|lt|le", right). Final step writes OUT.answer."""

_REF_RE = re.compile(r"^[A-Z]+\.[a-z0-9_]+$")
_TARGET_RE = re.compile(r"^([A-Z]+\.[a-z0-9_]+)\s*=\s*(.+)$", re.S)

_COMPARE_OPS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "ge": operator.ge,
    "lt": operator.lt,
    "le": operator.le,
}

_AST_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Mod: operator.mod,
}


def _is_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_REF_RE.match(value.strip()))


def _safe_arith(expr: str) -> float:
    """Evaluate a pure arithmetic expression (no names, no calls)."""

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _AST_OPS:
            return _AST_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _AST_OPS:
            return _AST_OPS[type(node.op)](_eval(node.operand))
        raise ValueError(f"unsupported arithmetic node: {ast.dump(node)}")

    return _eval(ast.parse(expr.strip(), mode="eval"))


@dataclass
class StepRecord:
    """One trajectory step — the unit of RL process reward (Stage 3)."""

    step_id: str
    command: str
    targets: tuple[str, ...]
    deterministic: bool = False
    parsed_ok: bool = True
    done_ok: bool | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    value: Any = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "command": self.command,
            "targets": list(self.targets),
            "deterministic": self.deterministic,
            "parsed_ok": self.parsed_ok,
            "done_ok": self.done_ok,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "value": self.value,
            "detail": self.detail,
        }


@dataclass
class VMResult:
    """Outcome of one VM episode — same accounting shape as ClassicResult."""

    task_id: str
    final_answer: str = ""
    ok: bool = True
    error: str = ""
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_calls: int = 0
    compile_attempts: int = 0
    deterministic_steps: int = 0
    llm_steps: int = 0
    wall_seconds: float = 0.0
    program_text: str = ""
    steps: list[StepRecord] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.llm_input_tokens + self.llm_output_tokens

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "final_answer": self.final_answer,
            "ok": self.ok,
            "error": self.error,
            "llm_input_tokens": self.llm_input_tokens,
            "llm_output_tokens": self.llm_output_tokens,
            "total_tokens": self.total_tokens,
            "llm_calls": self.llm_calls,
            "compile_attempts": self.compile_attempts,
            "deterministic_steps": self.deterministic_steps,
            "llm_steps": self.llm_steps,
            "wall_seconds": self.wall_seconds,
            "program_text": self.program_text,
            "steps": [s.to_dict() for s in self.steps],
        }


class VMExecutor:
    """Compile-and-execute one task through model self-subcalls."""

    def __init__(
        self,
        call_model: Callable[[str, str, int], tuple[str, int, int]],
        max_llm_steps: int = 12,
        max_compile_attempts: int = 3,
        step_retries: int = 1,
        max_tokens: int = 512,
        compile_max_tokens: int = 1500,
    ):
        """
        call_model(system, user, max_tokens) -> (text, input_tokens, output_tokens).

        compile_max_tokens gets extra headroom: thinking models spend output
        budget on reasoning before emitting the program.
        """
        self._call = call_model
        self._max_llm_steps = max_llm_steps
        self._max_compile_attempts = max_compile_attempts
        self._step_retries = step_retries
        self._max_tokens = max_tokens
        self._compile_max_tokens = compile_max_tokens

    # -- token/call bookkeeping ------------------------------------------------

    def _invoke(self, result: VMResult, system: str, user: str, max_tokens: int | None = None) -> str:
        budget = max_tokens or self._max_tokens
        text, in_tok, out_tok = self._call(system, user, budget)
        result.llm_input_tokens += in_tok
        result.llm_output_tokens += out_tok
        result.llm_calls += 1
        if not text.strip():
            # thinking models can exhaust the budget on reasoning and return
            # empty content — one retry with the same budget
            text, in_tok, out_tok = self._call(system, user, budget)
            result.llm_input_tokens += in_tok
            result.llm_output_tokens += out_tok
            result.llm_calls += 1
        return text

    # -- compile phase -----------------------------------------------------------

    def _compile(self, result: VMResult, task: str) -> Any:
        user = f"TASK: {task[:1200]}"
        last_error = ""
        for attempt in range(self._max_compile_attempts):
            result.compile_attempts = attempt + 1
            system = COMPILER_SYSTEM if attempt == 0 else REPAIR_SYSTEM
            if attempt > 0:
                user = (
                    f"TASK: {task[:1200]}\n\nPREVIOUS PROGRAM:\n{result.program_text[:2000]}\n\n"
                    f"PARSE ERROR: {last_error}"
                )
            text = self._invoke(result, system, user, max_tokens=self._compile_max_tokens)
            result.program_text = text.strip()
            cleaned = self._normalize(self._strip_fences(result.program_text))
            try:
                program = parse_program(cleaned)
                result.program_text = cleaned
                return program
            except ParseError as exc:
                last_error = str(exc)
        result.ok = False
        result.error = f"program did not parse after {self._max_compile_attempts} attempts: {last_error}"
        return None

    @staticmethod
    def _strip_fences(text: str) -> str:
        match = re.search(r"```\w*\n(.*?)```", text, re.S)
        return match.group(1).strip() if match else text.strip()

    @staticmethod
    def _normalize(text: str) -> str:
        """Mechanical text hygiene (deterministic, no intelligence):
        strip // comments outside quotes, fix numeric step ids."""
        lines = []
        for line in text.splitlines():
            out, in_quote = [], False
            quote_char = ""
            i = 0
            while i < len(line):
                ch = line[i]
                if in_quote:
                    if ch == quote_char:
                        in_quote = False
                elif ch in ('"', "'"):
                    in_quote = True
                    quote_char = ch
                elif line[i:i + 2] == "//":
                    break
                out.append(ch)
                i += 1
            lines.append("".join(out).rstrip())
        text = "\n".join(lines)
        text = re.sub(r"\bstep\.(\d+)\b", r"step.s\1", text)
        text = re.sub(r"\bSTEP\.(\d+)\b", r"step.s\1", text)
        return text

    # -- execution phase ---------------------------------------------------------

    def _resolve(self, store: dict[str, Any], value: Any) -> Any:
        if _is_ref(value):
            return store.get(value.strip(), value.strip())
        return value

    def _ref_slice(self, store: dict[str, Any], needed: set[str]) -> str:
        """Compact state slice — folding in action: only needed refs, one line each."""
        lines = []
        for ref in sorted(needed):
            if ref in store:
                lines.append(f"{ref} = {store[ref]}")
        return "\n".join(lines) if lines else "(none)"

    def _needed_refs(self, args: tuple) -> set[str]:
        return {a.value.strip() for a in args if _is_ref(a.value)}

    def _parse_step_output(self, text: str, targets: tuple[str, ...]) -> Any | None:
        """Extract '<target> = <value>' from the interpreter output."""
        match = _TARGET_RE.search(text.strip())
        if not match:
            # bare-value fallback: strict shapes only (number, bool, JSON,
            # quoted string, or a single punctuation-free token)
            lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
            if lines:
                candidate = lines[-1].strip()
                if candidate and self._looks_like_value(candidate):
                    return self._coerce(candidate)
            return None
        target, raw = match.group(1).strip(), match.group(2).strip()
        if targets and target not in targets:
            return None
        return self._coerce(raw)

    @staticmethod
    def _looks_like_value(candidate: str) -> bool:
        if candidate.endswith((".", "!", "?", ":", ";", ",")):
            return False
        if candidate.startswith(('"', "'")) and candidate.endswith(('"', "'")):
            return True
        try:
            json.loads(candidate)
            return True
        except (ValueError, json.JSONDecodeError):
            pass
        return " " not in candidate

    @staticmethod
    def _coerce(raw: str) -> Any:
        raw = raw.strip().strip('"').strip("'").rstrip(".")
        try:
            return json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return raw

    def _check(self, args: dict[str, Any]) -> Any:
        left = args.get("left")
        op = args.get("op", "eq")
        right = args.get("right")
        try:
            return _COMPARE_OPS.get(str(op), operator.eq)(left, right)
        except TypeError:
            return _COMPARE_OPS.get(str(op), operator.eq)(str(left), str(right))

    def _calculate(self, args: dict[str, Any], store: dict[str, Any] | None = None) -> Any:
        parts = []
        for name, value in args.items():
            if isinstance(value, (int, float)):
                parts.append(f"({value})")
            elif isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value):
                parts.append(f"({value})")
            elif isinstance(value, str) and any(sym in value for sym in "+-*/"):
                expr = value
                if store:
                    # resolve ref names inside quoted expressions: "E.packs * 3"
                    def _sub(match: re.Match) -> str:
                        ref = match.group(0)
                        ref_value = store.get(ref)
                        return f"({ref_value})" if isinstance(ref_value, (int, float)) else ref

                    expr = _REF_RE.sub(_sub, expr)
                parts.append(f"({_safe_arith(expr)})")
            else:
                raise ValueError(f"non-numeric argument {name}={value!r} for calculate")
        if not parts:
            raise ValueError("calculate needs at least one argument")
        return _safe_arith("+".join(parts))

    def _run_step(
        self,
        result: VMResult,
        store: dict[str, Any],
        invocation: Any,
        task: str,
    ) -> bool:
        """Execute one invocation; commit targets; return False on fatal failure."""
        record = StepRecord(
            step_id=invocation.step_id,
            command=invocation.command,
            targets=invocation.targets,
        )
        args = {a.name: self._resolve(store, a.value) for a in invocation.args}

        value: Any = None
        if invocation.command == "check":
            value = self._check(args)
            record.deterministic = True
        elif invocation.command == "calculate":
            try:
                value = self._calculate(args, store)
                if isinstance(value, float) and value.is_integer():
                    value = int(value)
            except (ValueError, SyntaxError) as exc:
                record.detail = f"calculate failed: {exc}"
                result.steps.append(record)
                result.ok = False
                result.error = record.detail
                return False
            record.deterministic = True
        else:
            # LLM subcall — the model executes its own step
            if result.llm_steps >= self._max_llm_steps:
                record.detail = "step budget exhausted"
                result.steps.append(record)
                result.ok = False
                result.error = record.detail
                return False
            step_line = self._render_invocation(invocation)
            refs_text = self._ref_slice(store, self._needed_refs(invocation.args))
            user = f"{step_line}\n\nrefs:\n{refs_text}\n\ntask context: {task[:400]}"
            text = self._invoke(result, INTERPRETER_SYSTEM, user)
            record.input_tokens = 0  # already aggregated on result
            value = self._parse_step_output(text, invocation.targets)
            retries = 0
            while value is None and retries < self._step_retries:
                retries += 1
                user_retry = (
                    f"{step_line}\n\nrefs:\n{refs_text}\n\n"
                    f"Your previous output was invalid: {text[:200]!r}\n"
                    f"Respond with exactly one line: {invocation.targets[0]} = <value>"
                )
                text = self._invoke(result, INTERPRETER_SYSTEM, user_retry)
                value = self._parse_step_output(text, invocation.targets)
            if value is None:
                record.parsed_ok = False
                record.detail = f"unparseable step output: {text[:200]!r}"
                result.steps.append(record)
                result.ok = False
                result.error = record.detail
                return False
            result.llm_steps += 1

        for target in invocation.targets:
            store[target] = value
        record.value = value

        # DONE predicate — machine-verifiable process reward (free PRM)
        if invocation.done is not None:
            record.done_ok = self._evaluate_done(invocation.done, value)
            if not record.done_ok:
                record.detail = f"DONE predicate failed: {invocation.done.op} {invocation.done.value!r}"
                result.steps.append(record)
                result.ok = False
                result.error = record.detail
                return False

        if record.deterministic:
            result.deterministic_steps += 1
        result.steps.append(record)
        return True

    @staticmethod
    def _render_invocation(invocation: Any) -> str:
        args_text = ", ".join(f"{a.name} = {a.value}" for a in invocation.args)
        targets_text = ", ".join(invocation.targets)
        return f"step.{invocation.step_id}: DO {invocation.command}({args_text}) -> {targets_text}"

    @staticmethod
    def _evaluate_done(done: Any, value: Any) -> bool:
        try:
            if done.op == "equals":
                return value == done.value or str(value) == str(done.value)
            if done.op == "in":
                return value in done.value or str(value) in [str(v) for v in done.value]
            if done.op == "matched":
                return bool(re.search(str(done.value), str(value)))
        except Exception:
            return False
        return False

    # -- public entry ------------------------------------------------------------

    def run(self, task_id: str, task: str) -> VMResult:
        """One VM episode: compile → execute → answer. Never raises."""
        result = VMResult(task_id=task_id)
        t0 = time.time()
        try:
            program = self._compile(result, task)
            if program is None:
                return result

            store: dict[str, Any] = {}
            for declaration in program.declarations:
                store[declaration.ref] = declaration.value

            return_refs: tuple[str, ...] = ()
            for statement in program.statements:
                kind = type(statement).__name__
                if kind == "Invocation":
                    if not self._run_step(result, store, statement, task):
                        return result
                elif kind == "Return":
                    return_refs = statement.refs
                elif kind == "Stop":
                    break
                else:
                    result.ok = False
                    result.error = f"VM pilot supports Invocation/Return/Stop only, got {kind}"
                    return result

            answer_ref = "OUT.answer"
            if return_refs and any(r.startswith("OUT.") for r in return_refs):
                answer_ref = next(r for r in return_refs if r.startswith("OUT."))
            if answer_ref in store:
                result.final_answer = self._stringify(store[answer_ref])
            else:
                result.ok = False
                result.error = f"answer ref {answer_ref} not committed"
        except Exception as exc:  # never raise — record and return
            result.ok = False
            result.error = f"vm error: {exc}"
        finally:
            result.wall_seconds = time.time() - t0
        return result

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
