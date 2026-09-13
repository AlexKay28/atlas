"""Deterministic local execution for pure-computation DO steps (issue #61).

Intercepts ``calculate``, ``check``, ``choose`` and ``rank`` commands
whose resolved kwargs are concrete values and evaluates them locally,
skipping the API worker call entirely.  Returns ``None`` to signal
"cannot compute deterministically — fall back to API dispatch".

The ``DeterministicStepExecutor`` is enabled when:
- the environment variable ``TAHOE_DETERMINISTIC`` is set to ``"1"``, or
- the program carries a ``deterministic`` annotation (issue #61 plan, P.step_4).

When disabled, ``try_execute`` always returns ``None`` (fall back to API).
"""

from __future__ import annotations

import ast
import operator
import os
from typing import Any

__all__ = ["DeterministicStepExecutor"]


_SAFE_BINOPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_SAFE_UNARYOPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_SAFE_CMPOPS: dict[type, Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _is_enabled() -> bool:
    """Check whether deterministic execution is enabled (issue #61)."""
    return os.environ.get("TAHOE_DETERMINISTIC", "") == "1"


def _is_concrete(value: Any) -> bool:
    """Return True if *value* is a concrete, locally-evaluable value.

    Strings that look like typed references (``G.foo``, ``OUT.bar``) are
    not concrete — they should have been resolved by the driver already,
    so their presence means something went wrong and we must fall back.
    """
    if isinstance(value, str):
        if not value:
            return True
        typed_ref = value[0:1].isupper() and "." in value
        if typed_ref:
            return False
        return True
    if isinstance(value, (int, float, bool, type(None))):
        return True
    if isinstance(value, list):
        return all(_is_concrete(v) for v in value)
    if isinstance(value, dict):
        return all(_is_concrete(v) for v in value.values())
    return False


def _safe_eval_expr(node: ast.AST, values: dict[str, Any] | None = None) -> Any:
    """Evaluate a restricted Python AST expression node."""
    if isinstance(node, ast.Expression):
        return _safe_eval_expr(node.body, values)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if values is not None and node.id in values:
            return values[node.id]
        raise ValueError(f"unknown name {node.id!r}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_BINOPS:
            raise ValueError(f"unsafe binop {op_type.__name__}")
        left = _safe_eval_expr(node.left, values)
        right = _safe_eval_expr(node.right, values)
        return _SAFE_BINOPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_UNARYOPS:
            raise ValueError(f"unsafe unaryop {op_type.__name__}")
        operand = _safe_eval_expr(node.operand, values)
        return _SAFE_UNARYOPS[op_type](operand)
    if isinstance(node, ast.Compare):
        left = _safe_eval_expr(node.left, values)
        for op, comp in zip(node.ops, node.comparators):
            op_type = type(op)
            if op_type not in _SAFE_CMPOPS:
                raise ValueError(f"unsafe cmpop {op_type.__name__}")
            right = _safe_eval_expr(comp, values)
            if not _SAFE_CMPOPS[op_type](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_safe_eval_expr(v, values) for v in node.values)
        if isinstance(node.op, ast.Or):
            return any(_safe_eval_expr(v, values) for v in node.values)
        raise ValueError("unsafe boolop")
    if isinstance(node, ast.IfExp):
        test = _safe_eval_expr(node.test, values)
        if test:
            return _safe_eval_expr(node.body, values)
        return _safe_eval_expr(node.orelse, values)
    raise ValueError(f"unsafe node {type(node).__name__}")


def _eval_calculate(kwargs: dict[str, Any]) -> Any:
    """Evaluate a ``calculate`` command locally.

    The ``calculate`` command accepts ``expression`` (a string arithmetic
    expression) and ``values`` (a mapping of variable names to numbers).
    We parse the expression with :func:`ast.parse` and evaluate it through
    a restricted AST walker — no ``eval``, no builtins, no attribute access.
    """
    expression = kwargs.get("expression")
    if expression is None:
        return None
    if not isinstance(expression, str):
        return None
    values = kwargs.get("values")
    if values is not None and not isinstance(values, dict):
        return None
    if not _is_concrete(expression):
        return None
    if values is not None:
        for v in values.values():
            if not _is_concrete(v):
                return None
    try:
        tree = ast.parse(expression, mode="eval")
        return _safe_eval_expr(tree, values or {})
    except Exception:
        return None


def _eval_check(kwargs: dict[str, Any]) -> Any:
    """Evaluate a ``check`` command locally.

    The ``check`` command accepts ``artifact`` and ``predicate`` kwargs.
    We support simple predicate patterns:
    - ``predicate`` is a dict with ``op`` and ``value`` keys (e.g.
      ``{"op": "eq", "value": 42}``) compared against ``artifact``.
    - ``predicate`` is a comparison string like ``"== 42"``, ``"> 5"``,
      ``"< 10"``, ``"!= 0"``.
    Returns ``{"verdict": True/False}`` on success, ``None`` on fallback.
    """
    artifact = kwargs.get("artifact")
    predicate = kwargs.get("predicate")
    if artifact is None or predicate is None:
        return None
    if not _is_concrete(artifact):
        return None
    if not _is_concrete(predicate):
        return None
    if isinstance(predicate, dict):
        op = predicate.get("op", "eq")
        val = predicate.get("value")
        ops = {
            "eq": operator.eq,
            "ne": operator.ne,
            "lt": operator.lt,
            "le": operator.le,
            "gt": operator.gt,
            "ge": operator.ge,
            "==": operator.eq,
            "!=": operator.ne,
            "<": operator.lt,
            "<=": operator.le,
            ">": operator.gt,
            ">=": operator.ge,
        }
        if op not in ops:
            return None
        try:
            verdict = bool(ops[op](artifact, val))
        except Exception:
            return None
        return {"verdict": verdict}
    if isinstance(predicate, str):
        p = predicate.strip()
        ops = [
            ("==", operator.eq),
            ("!=", operator.ne),
            ("<=", operator.le),
            (">=", operator.ge),
            ("<", operator.lt),
            (">", operator.gt),
        ]
        for token, fn in ops:
            if p.startswith(token):
                try:
                    rhs = ast.literal_eval(p[len(token):].strip())
                    verdict = bool(fn(artifact, rhs))
                except Exception:
                    return None
                return {"verdict": verdict}
        return None
    return None


def _eval_choose(kwargs: dict[str, Any]) -> Any:
    """Evaluate a ``choose`` command locally.

    Supports selecting the min or max from a list of concrete values:
    - ``valid_options`` is a list of concrete values.
    - ``decision_policy`` is ``"min"`` or ``"max"``.
    Returns ``{"decision": selected_value}`` on success, ``None`` on fallback.
    """
    options = kwargs.get("valid_options")
    if options is None:
        return None
    if not isinstance(options, list) or len(options) == 0:
        return None
    if not all(_is_concrete(v) for v in options):
        return None
    policy = kwargs.get("decision_policy")
    if not isinstance(policy, str):
        return None
    if policy == "min":
        try:
            return {"decision": min(options)}
        except TypeError:
            return None
    if policy == "max":
        try:
            return {"decision": max(options)}
        except TypeError:
            return None
    return None


def _eval_rank(kwargs: dict[str, Any]) -> Any:
    """Evaluate a ``rank`` command locally.

    Supports sorting a list by a simple key:
    - ``options`` is a list of concrete values.
    - ``criteria`` is a string ``"asc"`` or ``"desc"``.
    Returns ``{"ordering": sorted_list}`` on success, ``None`` on fallback.
    """
    options = kwargs.get("options")
    if options is None:
        return None
    if not isinstance(options, list) or len(options) == 0:
        return None
    if not all(_is_concrete(v) for v in options):
        return None
    criteria = kwargs.get("criteria")
    if not isinstance(criteria, str):
        return None
    if criteria == "asc":
        try:
            return {"ordering": sorted(options)}
        except TypeError:
            return None
    if criteria == "desc":
        try:
            return {"ordering": sorted(options, reverse=True)}
        except TypeError:
            return None
    return None


_EVALUATORS = {
    "calculate": _eval_calculate,
    "check": _eval_check,
    "choose": _eval_choose,
    "rank": _eval_rank,
}


class DeterministicStepExecutor:
    """Intercept pure-computation DO steps for local execution (issue #61).

    ``try_execute`` maps the command to a local evaluator.  If the
    evaluator returns a non-``None`` result, the driver skips the API
    worker call.  If it returns ``None``, the driver falls back to API
    dispatch unchanged.
    """

    @staticmethod
    def is_enabled() -> bool:
        """Return True when deterministic execution is active."""
        return _is_enabled()

    @staticmethod
    def try_execute(
        command: str,
        resolved_kwargs: dict[str, Any],
    ) -> Any:
        """Attempt to execute *command* locally.

        Returns the result value on success, or ``None`` to signal
        "fall back to API dispatch".
        """
        if not _is_enabled():
            return None
        evaluator = _EVALUATORS.get(command)
        if evaluator is None:
            return None
        try:
            return evaluator(resolved_kwargs)
        except Exception:
            return None
