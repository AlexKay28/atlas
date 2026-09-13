"""Shared helpers for the TAHOE coordinator and driver (issue #38).

Registry lookups, condition evaluation, DONE predicates, and the
invocation-id regexes — extracted from coordinator.py so both
coordinator.py and driver.py can import them without circularity.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping

from tahoe.syntax import is_typed_reference, parse_condition
from tahoe.syntax.model import (
    Call,
    Conditional,
    Gather,
    Invocation,
    Loop,
    Par,
    Reformulate,
    Scatter,
    Try,
)

DELEGATE_COMMAND = "delegate"

if TYPE_CHECKING:
    pass


_CANDIDATE_INVOCATION_RE = re.compile(r"^inv-(\d+)\.cand(\d+)$")
_PAR_INVOCATION_RE = re.compile(r"^par(\d+)$")


_BUILTIN_REGISTRY_DIGEST: str | None = None
_EFFECTFUL_COMMANDS: frozenset[str] | None = None


def _builtin_registry_digest() -> str:
    """Digest of the builtin command registry, computed once per process."""
    global _BUILTIN_REGISTRY_DIGEST
    if _BUILTIN_REGISTRY_DIGEST is None:
        from tahoe.registry.registry import builtin_registry, registry_digest

        _BUILTIN_REGISTRY_DIGEST = registry_digest(builtin_registry())
    return _BUILTIN_REGISTRY_DIGEST


def _effectful_commands() -> frozenset[str]:
    """Names of builtin commands whose effect class is a durable write.

    Resolved from the builtin registry (the contract source of truth), once
    per process.  Commands unknown to the builtin registry (custom worker
    handlers) are never treated as effectful.
    """
    global _EFFECTFUL_COMMANDS
    if _EFFECTFUL_COMMANDS is None:
        from tahoe.registry.enums import EffectClass
        from tahoe.registry.registry import builtin_registry

        durable = {EffectClass.REVERSIBLE_WRITE, EffectClass.IRREVERSIBLE_WRITE}
        registry = builtin_registry()
        _EFFECTFUL_COMMANDS = frozenset(
            name
            for name in registry.names()
            if registry.resolve(name).effect_class in durable
        )
    return _EFFECTFUL_COMMANDS


_COMMAND_MAX_ATTEMPTS: dict[str, int] | None = None


def _command_max_attempts(command: str) -> int | None:
    """The registry's ``contract.budget.max_attempts`` for *command*.

    Returns ``None`` for commands unknown to the builtin registry
    (custom worker handlers), so the attempt cap is never enforced
    on commands the registry does not govern (issue #41).
    """
    global _COMMAND_MAX_ATTEMPTS
    if _COMMAND_MAX_ATTEMPTS is None:
        from tahoe.registry.registry import builtin_registry

        registry = builtin_registry()
        _COMMAND_MAX_ATTEMPTS = {
            name: registry.resolve(name).budget.max_attempts
            for name in registry.names()
        }
    return _COMMAND_MAX_ATTEMPTS.get(command)


def _uses_kb_refs(program: Program) -> bool:
    """Whether any invocation argument mentions a ``KB.`` reference."""
    for statement in program.statements:
        # Issue #24: PAR branch DO lines resolve their arguments on the
        # parent at dispatch, so their KB.* references count too.
        if isinstance(statement, Par):
            for branch in statement.branches:
                if branch.invocation is not None and _invocation_uses_kb_refs(
                    branch.invocation
                ):
                    return True
            continue
        if not isinstance(statement, Invocation):
            continue
        if _invocation_uses_kb_refs(statement):
            return True
    return False


def _invocation_uses_kb_refs(invocation: Invocation) -> bool:
    for arg in invocation.args:
        if isinstance(arg.value, str) and arg.value.startswith("KB."):
            return True
        if isinstance(arg.value, list) and any(
            isinstance(item, str) and item.startswith("KB.")
            for item in arg.value
        ):
            return True
    return False


def _uses_scatter(program: Program) -> bool:
    """Whether the program contains SCATTER/GATHER blocks (issue #4)."""
    return any(
        isinstance(statement, (Scatter, Gather))
        for statement in program.statements
    )


def _uses_par(program: Program) -> bool:
    """Whether the program contains PAR blocks (issue #24)."""
    return any(isinstance(statement, Par) for statement in program.statements)


def _uses_loop(program: "Program") -> bool:
    """Whether the program contains LOOP blocks (issue #68)."""
    return any(isinstance(statement, Loop) for statement in program.statements)


def _uses_try(program: "Program") -> bool:
    """Whether the program contains TRY blocks (issue #69)."""
    return any(isinstance(statement, Try) for statement in program.statements)


def _uses_delegate(program: Program) -> bool:
    """Whether the program contains a delegate invocation (issue #25).

    Delegate authoring executes only on the sequential plan loop (like
    scatter and PAR entries, it is a single positional entry with its own
    child-run machinery); a delegate program never switches the concurrent
    frontier on.
    """
    for statement in program.statements:
        if isinstance(statement, Invocation):
            if statement.command == DELEGATE_COMMAND:
                return True
        elif isinstance(statement, Conditional):
            embedded = statement.statement
            if isinstance(embedded, Invocation) and (
                embedded.command == DELEGATE_COMMAND
            ):
                return True
    return False


def _uses_reformulate(program: "Program") -> bool:
    """Whether the program contains REFORMULATE blocks (issue #80)."""
    return any(
        isinstance(statement, Reformulate)
        for statement in program.statements
    )


from tahoe.runtime.planning import map_results_to_targets


def _json_equal(left: Any, right: Any) -> bool:
    """JSON-strict equality: a bool never equals 0/1 (Python int/bool blur)."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, dict):
        return (
            isinstance(right, dict)
            and set(left) == set(right)
            and all(_json_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, list):
        return (
            isinstance(right, list)
            and len(left) == len(right)
            and all(_json_equal(item, other) for item, other in zip(left, right))
        )
    if isinstance(right, (dict, list)):
        return False
    return left == right


def evaluate_done_predicate(
    done: "DonePredicate",
    target_values: Mapping[str, Any],
) -> tuple[bool, str]:
    """Purely and deterministically evaluate a DONE predicate.

    Evaluates only over the committed ``target_values`` mapping: no worker
    calls, no clocks, no randomness, no I/O.  Returns ``(passed, detail)``
    where ``detail`` explains the failure and is empty on success.
    """
    actual = target_values.get(done.ref)
    if done.op == "equals":
        if _json_equal(actual, done.value):
            return True, ""
        return False, f"expected {done.value!r}, got {actual!r}"
    if done.op == "in":
        options = done.value if isinstance(done.value, list) else []
        if any(_json_equal(actual, option) for option in options):
            return True, ""
        return False, f"value {actual!r} not in {options!r}"
    if done.op == "matched":
        if not isinstance(actual, str):
            return False, (
                f"matched predicate requires a string value,"
                f" got {type(actual).__name__}"
            )
        if re.fullmatch(done.value, actual) is not None:
            return True, ""
        return False, f"value {actual!r} does not match pattern {done.value!r}"
    if done.op in ("every", "any"):
        if not isinstance(actual, list):
            return False, (
                f"{done.op} predicate requires a list-valued reference"
                f", got {type(actual).__name__}"
            )
        pred = done.value
        pred_func = pred[0]
        if pred_func == "has":
            field = pred[1]
            results = [
                isinstance(item, Mapping) and field in item
                for item in actual
            ]
        elif pred_func == "eq":
            field, value = pred[1], pred[2]
            results = [
                isinstance(item, Mapping)
                and field in item
                and _json_equal(item[field], value)
                for item in actual
            ]
        elif pred_func == "ne":
            field, value = pred[1], pred[2]
            results = [
                isinstance(item, Mapping)
                and field in item
                and not _json_equal(item[field], value)
                for item in actual
            ]
        else:
            raise ValueError(f"unknown quantifier predicate {pred_func!r}")
        if done.op == "every":
            passed = all(results)
            if passed:
                return True, ""
            return False, f"not every element satisfies {pred_func}({pred[1:]})"
        else:
            passed = any(results)
            if passed:
                return True, ""
            return False, f"no element satisfies {pred_func}({pred[1:]})"
    raise ValueError(f"unknown DONE predicate {done.op!r}")


def evaluate_condition(condition: str, values: Mapping[str, Any]) -> bool:
    """Purely and deterministically evaluate an IF condition (issue #3).

    Parses ``condition`` (the raw text stored on the ``Conditional``) and
    evaluates the AST over the committed ``values`` mapping: no worker
    calls, no clocks, no randomness, no I/O.  Equality is JSON-strict (a
    bool never equals 0/1, matching DONE predicates).  Refs resolve like
    invocation nodes with the spec's immutable field selection (a trailing
    dotted segment reads a field of the committed node).  ``count``
    requires a list-valued operand.  A ref that no longer resolves (or a
    field selection that misses) raises ValueError — static validation
    cannot see mid-run retirements or value shapes.
    """
    ast = parse_condition(condition)
    return _eval_condition_node(ast, values)


def _eval_condition_node(node: tuple, values: Mapping[str, Any]) -> bool:
    kind = node[0]
    if kind == "eq":
        return _json_equal(_condition_operand(node[1], values), node[2])
    if kind == "ne":
        return not _json_equal(_condition_operand(node[1], values), node[2])
    if kind == "count":
        operand = _condition_operand(node[1], values)
        if not isinstance(operand, list):
            raise ValueError(
                f"count condition requires a list-valued reference"
                f" ({node[1]}), got {type(operand).__name__}"
            )
        return _compare(len(operand), node[2], node[3])
    if kind in ("every", "any"):
        operand = _condition_operand(node[1], values)
        if not isinstance(operand, list):
            raise ValueError(
                f"{kind} condition requires a list-valued reference"
                f" ({node[1]}), got {type(operand).__name__}"
            )
        pred = node[2]
        pred_func = pred[0]
        if pred_func == "has":
            field = pred[1]
            results = [
                isinstance(item, Mapping) and field in item
                for item in operand
            ]
        elif pred_func == "eq":
            field, value = pred[1], pred[2]
            results = [
                isinstance(item, Mapping)
                and field in item
                and _json_equal(item[field], value)
                for item in operand
            ]
        elif pred_func == "ne":
            field, value = pred[1], pred[2]
            results = [
                isinstance(item, Mapping)
                and field in item
                and not _json_equal(item[field], value)
                for item in operand
            ]
        else:
            raise ValueError(f"unknown quantifier predicate {pred_func!r}")
        if kind == "every":
            return all(results)
        return any(results)
    if kind == "not":
        return not _eval_condition_node(node[1], values)
    if kind == "and":
        return _eval_condition_node(node[1], values) and _eval_condition_node(
            node[2], values
        )
    if kind == "or":
        return _eval_condition_node(node[1], values) or _eval_condition_node(
            node[2], values
        )
    raise ValueError(f"unknown condition node {kind!r}")


def _condition_operand(ref: str, values: Mapping[str, Any]) -> Any:
    """Resolve a condition ref against committed state (issue #3).

    A ref either names a committed node outright or — per the spec's
    immutable field selection — addresses a field path into the longest
    committed prefix of itself (``V.tests.status`` reads field ``status``
    of node ``V.tests``).  Reading a field of a non-mapping node or a
    missing field raises ValueError: conditions never guess.
    """
    if ref in values:
        return values[ref]
    segments = ref.split(".")
    while len(segments) > 1:
        segments.pop()
        prefix = ".".join(segments)
        if prefix in values:
            operand: Any = values[prefix]
            for field in ref.split(".")[len(segments):]:
                if not isinstance(operand, Mapping):
                    raise ValueError(
                        f"condition field selection {ref!r} requires a"
                        f" mapping at {prefix!r}, got"
                        f" {type(operand).__name__}"
                    )
                if field not in operand:
                    raise ValueError(
                        f"condition field selection {ref!r} failed:"
                        f" node {prefix!r} has no field {field!r}"
                    )
                operand = operand[field]
            return operand
    raise ValueError(
        f"reference {ref} is not in run state (retired or undefined);"
        " conditions read committed nodes only"
    )


def _compare(left: Any, op: str, right: Any) -> bool:
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    raise ValueError(f"unknown comparison operator {op!r}")


