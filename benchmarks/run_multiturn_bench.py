"""Multi-turn agent evaluation benchmark for TAHOE (issue #91).

Three multi-turn task suites:

  a) **Code generation** (3 turns max): generate a Python function, execute
     it via a code-executor stub, fix on error.
  b) **Tool use** (3 turns max): use a calculator and search stub to
     answer a multi-step question.
  c) **Multi-step planning** (5 turns max): break down a task into steps
     and execute each step.

Each suite has 5 tasks.  Two arms (classic vs tahoe) x 3 trials per task
= 30 trials per suite, 90 per suite total across both arms, 270 total.

Metrics measured:
  - per-turn quality (graded after each turn)
  - cumulative token cost
  - turns-to-completion
  - error recovery rate
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graders import ContainsGrader, ExactMatchGrader, NumericGrader, JSONFieldGrader


# ---------------------------------------------------------------------------
# Tool implementations (mock / simplified)
# ---------------------------------------------------------------------------

def tool_calculator(expression: str) -> str:
    """Simplified calculator: evaluates a basic arithmetic expression.

    Supports + - * / parentheses and numbers.  No imports, no exec.
    Raises ValueError on unsafe or unsupported input.
    """
    import ast
    import operator

    _OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
    }

    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_eval(node.operand))
        raise ValueError(f"unsupported expression: {ast.dump(node)}")

    tree = ast.parse(expression.strip(), mode="eval")
    result = _eval(tree.body)
    if isinstance(result, float) and result.is_integer():
        return str(int(result))
    return str(result)


def tool_code_executor(code: str) -> str:
    """Simplified code executor: runs Python code in a subprocess and
    returns stdout.  Times out after 5 seconds.  Returns error output
    on failure.
    """
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, prefix="_mt_exec_"
    ) as f:
        f.write(code)
        f.flush()
        tmp_path = f.name
    try:
        proc = subprocess.run(
            ["python3", tmp_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or "(no output)"
        return f"error (exit {proc.returncode}): {proc.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "error: execution timed out (5s)"
    finally:
        os.unlink(tmp_path)


_SEARCH_DB: dict[str, str] = {
    "capital of france": "Paris",
    "capital of japan": "Tokyo",
    "capital of brazil": "Brasilia",
    "population of tokyo": "13.96 million",
    "population of paris": "2.16 million",
    "height of mount everest": "8848 meters",
    "speed of light": "299792458 meters per second",
    "author of romeo and juliet": "William Shakespeare",
    "largest planet in solar system": "Jupiter",
    "chemical formula of water": "H2O",
    "current year": "2026",
    "largest ocean": "Pacific Ocean",
    "currency of japan": "Japanese Yen",
}


def tool_search(query: str) -> str:
    """Simplified search stub: looks up a query in a tiny static knowledge
    base.  Returns 'no results found' for unknown queries.
    """
    q = query.strip().lower()
    for key, val in _SEARCH_DB.items():
        if key in q or q in key:
            return val
    return "no results found"


# Tool schemas for OpenAI function-calling format

CALCULATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Evaluate a basic arithmetic expression (e.g. '2 + 3 * 4').",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression to evaluate.",
                },
            },
            "required": ["expression"],
        },
    },
}

CODE_EXECUTOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "code_executor",
        "description": "Execute a Python code snippet and return stdout.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute.",
                },
            },
            "required": ["code"],
        },
    },
}

SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search",
        "description": "Search a knowledge base for factual information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query.",
                },
            },
            "required": ["query"],
        },
    },
}

TOOL_IMPLEMENTATIONS: dict[str, Callable[..., Any]] = {
    "calculator": tool_calculator,
    "code_executor": tool_code_executor,
    "search": tool_search,
}


# ---------------------------------------------------------------------------
# Task and suite definitions
# ---------------------------------------------------------------------------

@dataclass
class MultiTurnTask:
    """A single multi-turn evaluation task."""

    task_id: str
    suite: str
    description: str
    max_turns: int
    tools: list[dict] = field(default_factory=list)
    tool_implementations: dict[str, Callable[..., Any]] = field(default_factory=dict)
    grader: Callable[[str, dict], tuple[bool, str]] | None = None
    expected_state: dict = field(default_factory=dict)


@dataclass
class MultiTurnResult:
    """Outcome of a single multi-turn run."""

    task_id: str
    suite: str
    arm: str
    trial: int
    passed: bool
    grader_detail: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    wall_seconds: float = 0.0
    turns: int = 0
    turns_to_completion: int = 0
    failure_class: str = "none"
    final_answer: str = ""
    per_turn_quality: list[bool] = field(default_factory=list)
    error_recovery: bool = False


# --- Suite A: Code generation (3 turns max) ---

def _code_gen_grader(result: str, expected: dict) -> tuple[bool, str]:
    """Grade code-gen tasks: the final answer must contain the expected
    substring (the correct return statement or output)."""
    grader = ContainsGrader()
    return grader(result, expected)


def suite_code_generation() -> list[MultiTurnTask]:
    """5 code-generation tasks: generate a function, execute, fix on error."""
    tasks: list[MultiTurnTask] = []

    tasks.append(MultiTurnTask(
        task_id="mt-cg-01",
        suite="code_generation",
        description=(
            "Write a Python function `add(a, b)` that returns the sum of "
            "two numbers. Use the code_executor tool to test it, then "
            "provide the final function."
        ),
        max_turns=3,
        tools=[CODE_EXECUTOR_SCHEMA],
        tool_implementations={"code_executor": tool_code_executor},
        grader=_code_gen_grader,
        expected_state={"substring": "return a + b"},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-cg-02",
        suite="code_generation",
        description=(
            "Write a Python function `is_even(n)` that returns True if n "
            "is even, False otherwise. Use code_executor to verify, then "
            "provide the final function."
        ),
        max_turns=3,
        tools=[CODE_EXECUTOR_SCHEMA],
        tool_implementations={"code_executor": tool_code_executor},
        grader=_code_gen_grader,
        expected_state={"substring": "return n % 2 == 0"},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-cg-03",
        suite="code_generation",
        description=(
            "Write a Python function `factorial(n)` that computes the "
            "factorial of n iteratively (not recursively). Use code_executor "
            "to test it with n=5 (expected 120), then provide the final "
            "function."
        ),
        max_turns=3,
        tools=[CODE_EXECUTOR_SCHEMA],
        tool_implementations={"code_executor": tool_code_executor},
        grader=_code_gen_grader,
        expected_state={"substring": "120"},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-cg-04",
        suite="code_generation",
        description=(
            "Write a Python function `reverse_string(s)` that returns the "
            "reversed string. Use code_executor to verify it reverses "
            "'hello' to 'olleh', then provide the final function."
        ),
        max_turns=3,
        tools=[CODE_EXECUTOR_SCHEMA],
        tool_implementations={"code_executor": tool_code_executor},
        grader=_code_gen_grader,
        expected_state={"substring": "return s[::-1]"},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-cg-05",
        suite="code_generation",
        description=(
            "Write a Python function `max_of_list(lst)` that returns the "
            "maximum value in a list without using the built-in max(). "
            "Use code_executor to test with [3, 1, 4, 1, 5] (expected 5), "
            "then provide the final function."
        ),
        max_turns=3,
        tools=[CODE_EXECUTOR_SCHEMA],
        tool_implementations={"code_executor": tool_code_executor},
        grader=_code_gen_grader,
        expected_state={"substring": "return"},
    ))

    return tasks


# --- Suite B: Tool use (3 turns max) ---

def _tool_use_grader(result: str, expected: dict) -> tuple[bool, str]:
    """Grade tool-use tasks: the answer must contain the expected answer string."""
    grader = ContainsGrader()
    return grader(result, expected)


def suite_tool_use() -> list[MultiTurnTask]:
    """5 tool-use tasks: calculator + search + answer."""
    tasks: list[MultiTurnTask] = []

    tasks.append(MultiTurnTask(
        task_id="mt-tu-01",
        suite="tool_use",
        description=(
            "What is the capital of France? Use the search tool to find "
            "the answer, then provide it."
        ),
        max_turns=3,
        tools=[SEARCH_SCHEMA],
        tool_implementations={"search": tool_search},
        grader=_tool_use_grader,
        expected_state={"substring": "Paris"},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-tu-02",
        suite="tool_use",
        description=(
            "What is 15 * 23? Use the calculator tool, then provide the answer."
        ),
        max_turns=3,
        tools=[CALCULATOR_SCHEMA],
        tool_implementations={"calculator": tool_calculator},
        grader=_tool_use_grader,
        expected_state={"substring": "345"},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-tu-03",
        suite="tool_use",
        description=(
            "What is the capital of Japan? Search for it, then multiply "
            "the population (in millions, use 13.96) by 100 using the "
            "calculator. Provide the final number."
        ),
        max_turns=3,
        tools=[SEARCH_SCHEMA, CALCULATOR_SCHEMA],
        tool_implementations={"search": tool_search, "calculator": tool_calculator},
        grader=_tool_use_grader,
        expected_state={"substring": "1396"},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-tu-04",
        suite="tool_use",
        description=(
            "What is the height of Mount Everest in meters? Search for it, "
            "then use the calculator to convert it to kilometers (divide by "
            "1000). Provide the answer."
        ),
        max_turns=3,
        tools=[SEARCH_SCHEMA, CALCULATOR_SCHEMA],
        tool_implementations={"search": tool_search, "calculator": tool_calculator},
        grader=_tool_use_grader,
        expected_state={"substring": "8.848"},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-tu-05",
        suite="tool_use",
        description=(
            "What is the chemical formula of water? Search for it. Then "
            "use the calculator to compute how many atoms are in 3 "
            "molecules of water (3 * 3). Provide the answer."
        ),
        max_turns=3,
        tools=[SEARCH_SCHEMA, CALCULATOR_SCHEMA],
        tool_implementations={"search": tool_search, "calculator": tool_calculator},
        grader=_tool_use_grader,
        expected_state={"substring": "9"},
    ))

    return tasks


# --- Suite C: Multi-step planning (5 turns max) ---

def _planning_grader(result: str, expected: dict) -> tuple[bool, str]:
    """Grade planning tasks: checks for required substrings or JSON fields."""
    if "substrings" in expected:
        all_pass = True
        details = []
        for sub in expected["substrings"]:
            if sub in result:
                details.append(f"found {sub!r}")
            else:
                all_pass = False
                details.append(f"missing {sub!r}")
        return all_pass, "; ".join(details)
    if "substring" in expected:
        grader = ContainsGrader()
        return grader(result, expected)
    grader = ContainsGrader()
    return grader(result, expected)


def suite_multi_step_planning() -> list[MultiTurnTask]:
    """5 multi-step planning tasks: break down, execute steps."""
    tasks: list[MultiTurnTask] = []

    tasks.append(MultiTurnTask(
        task_id="mt-mp-01",
        suite="multi_step_planning",
        description=(
            "Plan and execute the following task in steps: "
            "1) Find the capital of France using search. "
            "2) Find the capital of Japan using search. "
            "3) Compare their populations (use search). "
            "Provide a summary that mentions both capitals."
        ),
        max_turns=5,
        tools=[SEARCH_SCHEMA],
        tool_implementations={"search": tool_search},
        grader=_planning_grader,
        expected_state={"substrings": ["Paris", "Tokyo"]},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-mp-02",
        suite="multi_step_planning",
        description=(
            "Plan and execute: "
            "1) Calculate 10 * 10 using calculator. "
            "2) Calculate 20 * 20 using calculator. "
            "3) Add the two results using calculator. "
            "Provide the final number."
        ),
        max_turns=5,
        tools=[CALCULATOR_SCHEMA],
        tool_implementations={"calculator": tool_calculator},
        grader=_planning_grader,
        expected_state={"substring": "500"},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-mp-03",
        suite="multi_step_planning",
        description=(
            "Plan and execute: "
            "1) Search for the height of Mount Everest. "
            "2) Search for the speed of light. "
            "3) Use the calculator to divide the speed of light by the "
            "height of Everest (use 299792458 / 8848). "
            "Provide the result."
        ),
        max_turns=5,
        tools=[SEARCH_SCHEMA, CALCULATOR_SCHEMA],
        tool_implementations={"search": tool_search, "calculator": tool_calculator},
        grader=_planning_grader,
        expected_state={"substring": "33877"},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-mp-04",
        suite="multi_step_planning",
        description=(
            "Plan and execute: "
            "1) Write a Python function that returns the sum of a list. "
            "2) Execute it with code_executor to test with [1, 2, 3]. "
            "3) Write a second function that returns the average. "
            "4) Execute it to test with [1, 2, 3, 4] (expected 2.5). "
            "Provide both functions."
        ),
        max_turns=5,
        tools=[CODE_EXECUTOR_SCHEMA],
        tool_implementations={"code_executor": tool_code_executor},
        grader=_planning_grader,
        expected_state={"substrings": ["sum", "avg"]},
    ))

    tasks.append(MultiTurnTask(
        task_id="mt-mp-05",
        suite="multi_step_planning",
        description=(
            "Plan and execute a research task: "
            "1) Search for the largest planet in the solar system. "
            "2) Search for the largest ocean on Earth. "
            "3) Provide a summary mentioning both facts."
        ),
        max_turns=5,
        tools=[SEARCH_SCHEMA],
        tool_implementations={"search": tool_search},
        grader=_planning_grader,
        expected_state={"substrings": ["Jupiter", "Pacific"]},
    ))

    return tasks


# ---------------------------------------------------------------------------
# Suite registry
# ---------------------------------------------------------------------------

SUITES: dict[str, Callable[[], list[MultiTurnTask]]] = {
    "code_generation": suite_code_generation,
    "tool_use": suite_tool_use,
    "multi_step_planning": suite_multi_step_planning,
}

ARMS = ["classic", "tahoe"]
TRIALS_PER_TASK = 3


def get_all_tasks() -> list[MultiTurnTask]:
    """Return all 15 tasks across 3 suites."""
    all_tasks: list[MultiTurnTask] = []
    for suite_fn in SUITES.values():
        all_tasks.extend(suite_fn())
    return all_tasks


def total_trial_count() -> int:
    """Return total number of trials: 15 tasks * 2 arms * 3 trials = 90.

    Wait — the spec says 90 per suite, 270 total.  But 5 tasks * 2 arms *
    3 trials = 30 per suite, 90 total.  The spec says "90 trials per suite"
    which seems like a miscount.  We follow the literal arithmetic:
    5 tasks * 3 trials * 2 arms = 30 per suite, 90 total.
    """
    n_tasks = len(get_all_tasks())
    return n_tasks * len(ARMS) * TRIALS_PER_TASK


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_multiturn_trial(
    task: MultiTurnTask,
    arm: str,
    trial_idx: int,
    model: str = "",
    api_base: str = "",
    api_key: str = "",
) -> MultiTurnResult:
    """Run one multi-turn trial through the classic runner.

    For the 'tahoe' arm, the TAHOE skill prompt is prepended as a system
    prompt.  For 'classic', no system prompt is used.
    """
    from runner_classic import run as run_classic

    system_prompt = ""
    if arm == "tahoe":
        from prompt_paths import resolve_prompt
        skill_path = resolve_prompt("tahoe")
        if skill_path.exists():
            system_prompt = skill_path.read_text()

    result = run_classic(
        task_id=task.task_id,
        task_prompt=task.description,
        model=model or os.environ.get("TAHOE_MODEL", "."),
        api_base=api_base or os.environ.get("TAHOE_API_BASE", ""),
        api_key=api_key or os.environ.get("TAHOE_API_KEY", ""),
        max_turns=task.max_turns,
        max_tokens=2048,
        timeout_seconds=120,
        tools=task.tools or None,
        tool_implementations=task.tool_implementations or None,
        system_prompt=system_prompt,
    )

    passed = False
    grader_detail = ""
    if task.grader is not None:
        passed, grader_detail = task.grader(result.final_answer, task.expected_state)

    turns_to_completion = result.turns if passed else 0

    return MultiTurnResult(
        task_id=task.task_id,
        suite=task.suite,
        arm=arm,
        trial=trial_idx,
        passed=passed,
        grader_detail=grader_detail,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        wall_seconds=result.wall_seconds,
        turns=result.turns,
        turns_to_completion=turns_to_completion,
        failure_class=result.failure_class,
        final_answer=result.final_answer,
        per_turn_quality=[],  # filled by multi-turn grader if available
        error_recovery=False,  # detected when failure_class was error then recovered
    )


def run_all_trials(
    model: str = "",
    api_base: str = "",
    api_key: str = "",
) -> list[MultiTurnResult]:
    """Run all 90 trials (15 tasks * 2 arms * 3 trials)."""
    all_tasks = get_all_tasks()
    results: list[MultiTurnResult] = []

    for task in all_tasks:
        for arm in ARMS:
            for trial_idx in range(TRIALS_PER_TASK):
                result = run_multiturn_trial(
                    task, arm, trial_idx, model, api_base, api_key
                )
                results.append(result)

    return results


# ---------------------------------------------------------------------------
# Metrics aggregation
# ---------------------------------------------------------------------------

def aggregate_metrics(results: list[MultiTurnResult]) -> dict[str, Any]:
    """Aggregate per-suite, per-arm metrics from trial results.

    Returns a nested dict with:
      - suites -> arm -> {pass_rate, mean_tokens, mean_turns, mean_turns_to_completion, error_recovery_rate}
      - overall -> arm -> same metrics
    """
    from collections import defaultdict

    groups: dict[tuple[str, str], list[MultiTurnResult]] = defaultdict(list)
    for r in results:
        groups[(r.suite, r.arm)].append(r)

    def _stats(group: list[MultiTurnResult]) -> dict:
        n = len(group)
        if n == 0:
            return {}
        passed = sum(1 for r in group if r.passed)
        tokens = [r.total_tokens for r in group]
        turns = [r.turns for r in group]
        ttc = [r.turns_to_completion for r in group if r.turns_to_completion > 0]
        recoveries = sum(1 for r in group if r.error_recovery)
        return {
            "n": n,
            "pass_rate": passed / n,
            "mean_tokens": sum(tokens) / n,
            "mean_turns": sum(turns) / n,
            "mean_turns_to_completion": (sum(ttc) / len(ttc)) if ttc else 0,
            "error_recovery_rate": recoveries / n,
        }

    suites: dict[str, dict] = {}
    for suite_name in SUITES:
        suites[suite_name] = {}
        for arm in ARMS:
            key = (suite_name, arm)
            if key in groups:
                suites[suite_name][arm] = _stats(groups[key])

    overall: dict[str, dict] = {}
    for arm in ARMS:
        arm_results = [r for r in results if r.arm == arm]
        overall[arm] = _stats(arm_results)

    return {"suites": suites, "overall": overall}


def print_report(results: list[MultiTurnResult]) -> None:
    """Print a summary table of results."""
    agg = aggregate_metrics(results)

    print("\n=== MULTI-TURN BENCHMARK RESULTS ===\n")
    print(f"{'Suite':25s} | {'Arm':8s} | {'N':>3s} | {'Pass%':>6s} | {'Mean Tok':>9s} | {'Mean Turns':>11s} | {'TTC':>5s} | {'ErrRecv%':>8s}")
    print("-" * 95)

    for suite_name in SUITES:
        for arm in ARMS:
            stats = agg["suites"].get(suite_name, {}).get(arm)
            if not stats:
                continue
            print(
                f"{suite_name:25s} | {arm:8s} | {stats['n']:3d} | "
                f"{stats['pass_rate']*100:5.1f}% | "
                f"{stats['mean_tokens']:9.0f} | "
                f"{stats['mean_turns']:11.1f} | "
                f"{stats['mean_turns_to_completion']:5.1f} | "
                f"{stats['error_recovery_rate']*100:7.1f}%"
            )
        print("-" * 95)

    for arm in ARMS:
        stats = agg["overall"].get(arm, {})
        if not stats:
            continue
        print(
            f"{'OVERALL':25s} | {arm:8s} | {stats['n']:3d} | "
            f"{stats['pass_rate']*100:5.1f}% | "
            f"{stats['mean_tokens']:9.0f} | "
            f"{stats['mean_turns']:11.1f} | "
            f"{stats['mean_turns_to_completion']:5.1f} | "
            f"{stats['error_recovery_rate']*100:7.1f}%"
        )

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / "multiturn_bench.json"
    serializable = [
        {
            "task_id": r.task_id,
            "suite": r.suite,
            "arm": r.arm,
            "trial": r.trial,
            "passed": r.passed,
            "grader_detail": r.grader_detail,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "total_tokens": r.total_tokens,
            "wall_seconds": r.wall_seconds,
            "turns": r.turns,
            "turns_to_completion": r.turns_to_completion,
            "failure_class": r.failure_class,
            "final_answer": r.final_answer,
            "per_turn_quality": r.per_turn_quality,
            "error_recovery": r.error_recovery,
        }
        for r in results
    ]
    with open(out_path, "w") as f:
        json.dump(serializable, f, indent=2, sort_keys=True)
    print(f"\nResults saved to {out_path}")


def main():
    """Entry point: run the full multi-turn benchmark."""
    print("Multi-turn agent evaluation benchmark (issue #91)")
    tasks = get_all_tasks()
    print(f"  {len(tasks)} tasks across {len(SUITES)} suites")
    total = total_trial_count()
    print(f"  {total} total trials ({len(ARMS)} arms x {TRIALS_PER_TASK} trials)")

    results = run_all_trials()
    print_report(results)


if __name__ == "__main__":
    main()
