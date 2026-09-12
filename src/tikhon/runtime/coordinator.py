"""Deterministic sequential coordinator for tikhon programs.

Implements the runtime contract from docs/spec/03-runtime-and-events.md:
sequential invocation lifecycle, durable task ledger per invocation,
deterministic state commits, and failure handling without false
completion.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import hashlib
import os
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from tikhon.budgets import BudgetDeadlineExceeded, BudgetGate, ExecutionBudget
from tikhon.claims import ResourceLedger
from tikhon.runtime.events import (
    EventStore,
    EventType,
    _Record,
    canonical_json as _canonical_event_json,
)
from tikhon.runtime.tasks import TaskLedger, TaskLedgerError, TaskStatus
from tikhon.state import StateDelta
from tikhon.syntax import (
    ParseError,
    is_typed_reference,
    load_protocol,
    parse_condition,
    parse_program,
    validate_program,
)
from tikhon.syntax.model import (
    Argument,
    Call,
    Conditional,
    Declaration,
    Gather,
    Invocation,
    Par,
    ParBranch,
    Program,
    Return,
    Scatter,
    Stop,
)

if TYPE_CHECKING:
    from tikhon.memory import KnowledgeBase
    from tikhon.syntax.model import DonePredicate

__all__ = [
    "CrashInterrupt",
    "DeterministicWorker",
    "SequentialCoordinator",
    "evaluate_condition",
    "evaluate_done_predicate",
    "judge_score",
    "map_results_to_targets",
]


class CrashInterrupt(Exception):
    """Raised by a ``crash_hook`` to abort ``execute`` mid-run (issue #10).

    The hook site lives outside every ``try``/``except`` in the
    coordinator, so this exception propagates out of ``execute`` uncaught
    and the run keeps exactly its committed event prefix — a true crash
    window, not a failed run (no FAILED, no RUN_FINISHED).
    """


def _monotonic() -> float:
    """Monotonic clock for budget deadlines (issue #22)."""
    return time.monotonic()


# Issue #4: per-candidate invocation ids hang off their scatter entry's
# positional id ("inv-<K>" -> "inv-<K>.cand<k>", 1-based k), keeping every
# candidate invocation distinct from the plan's positional ids while staying
# derivable from the plan alone (resume reconstructs scatter progress from
# these ids).
_CANDIDATE_INVOCATION_RE = re.compile(r"^inv-(\d+)\.cand(\d+)$")

# Issue #24: PAR branch invocations on the parent run carry ids "par<k>"
# (1-based source order).  Like candidate ids they are excluded from the
# positional success-set invariants (the PAR entry itself is the positional
# unit), and resume validates them against the plan's PAR entries.
_PAR_INVOCATION_RE = re.compile(r"^par(\d+)$")

# Issue #25: runtime-authored child plans (delegate).
#
# ``delegate`` is a plain registered command executed through the standard
# DO machinery: the worker reply is the AUTHORED child program text, which
# the coordinator validates against the registry, records as a
# CHILD_PLAN_AUTHORED event, and executes as an isolated child run using
# the same child machinery as CALL.  The authored plan's step count is
# bounded (default 6, hard cap 12) and recursion is rejected: the authored
# plan may not contain a delegate command, directly or through any
# transitively called protocol file.
DELEGATE_COMMAND = "delegate"
DELEGATE_DEFAULT_MAX_STEPS = 6
DELEGATE_HARD_MAX_STEPS = 12
# Protocol-call chains are already validated to be acyclic and bounded at
# depth 8 (issue #12); the transitive no-recursion walk uses the same cap
# defensively.
DELEGATE_PROTOCOL_DEPTH_LIMIT = 8


def delegate_plan_name(step_id: str) -> str:
    """The bound program name of a delegate-authored child plan (issue #25).

    ``delegated_<parent_step_id>`` with the step id's dot normalized to an
    underscore (``step.author`` -> ``delegated_step_author``) so the name
    satisfies the canonical ``PROGRAM`` header charset.  The coordinator
    binds this name onto the accepted plan before executing it, making the
    lineage label part of the executed artifact (and of its digest).
    """
    return "delegated_" + step_id.replace(".", "_")


def delegate_plan_digest(step_id: str, plan_text: str) -> str:
    """Digest pinning one authored child plan (issue #25).

    sha256 over the canonical JSON of ``{"name": <bound plan name>,
    "plan_text": <raw authored text>}`` — computed from the step id and
    the raw text alone, so it exists even for plans that later fail to
    parse (the CHILD_PLAN_AUTHORED event records it either way).
    """
    payload = {
        "name": delegate_plan_name(step_id),
        "plan_text": plan_text,
    }
    return hashlib.sha256(
        _canonical_event_json(payload).encode("utf-8")
    ).hexdigest()


def count_plan_steps(program: Program) -> int:
    """The number of executable plan entries an authored plan would create.

    Mirrors :meth:`SequentialCoordinator._build_plan`'s counting: every
    bare or conditional DO invocation, CALL, SCATTER, GATHER and PAR block
    occupies one plan entry.  The delegate step bound (``max_steps``,
    default 6, hard cap 12) applies to this count.
    """
    count = 0
    for statement in program.statements:
        if isinstance(statement, Invocation):
            count += 1
        elif isinstance(statement, Conditional):
            if isinstance(statement.statement, Invocation):
                count += 1
        elif isinstance(statement, (Call, Scatter, Par, Gather)):
            count += 1
    return count


def _iter_invocations_and_calls(program: Program):
    """Yield every ``(invocation, call)`` pair an authored plan can dispatch.

    Walks plain statements plus every nested holder: conditional embedded
    statements, SCATTER bodies, PAR branches (DO or CALL) and GATHER judge
    templates.
    """
    for statement in program.statements:
        yield from _walk_invocation_holder(statement)


def _walk_invocation_holder(statement: object):
    if isinstance(statement, Invocation):
        yield statement, None
    elif isinstance(statement, Conditional):
        if isinstance(statement.statement, Invocation):
            yield statement.statement, None
    elif isinstance(statement, Scatter):
        yield statement.body, None
    elif isinstance(statement, Gather):
        if statement.judge is not None:
            yield statement.judge, None
    elif isinstance(statement, Par):
        for branch in statement.branches:
            if branch.invocation is not None:
                yield branch.invocation, None
            else:
                yield None, branch.call
    elif isinstance(statement, Call):
        yield None, statement


def _extract_plan_text(result: Any) -> str:
    """Normalize a delegate worker reply into the authored plan text.

    The handler contract: the reply IS the plan text (a string) — that is
    what deterministic handlers return.  A model worker parses its strict
    JSON reply into a mapping, so the issue-specified shape
    ``{"plan_text": "..."}`` is accepted too.  Anything else is an
    INVALID_INPUT-class defect.
    """
    if isinstance(result, str) and result.strip():
        return result
    if isinstance(result, Mapping):
        plan_text = result.get("plan_text")
        if isinstance(plan_text, str) and plan_text.strip():
            return plan_text
    raise ValueError(
        "delegate worker reply must be the authored plan text (a"
        ' nonempty string) or a mapping with a nonempty "plan_text"'
        f" string field; got {type(result).__name__}"
    )


def candidate_invocation_id(scatter_invocation_id: str, candidate: int) -> str:
    """The invocation id of one candidate of a scatter entry (issue #4)."""
    return f"{scatter_invocation_id}.cand{candidate}"


def candidate_node_id(alias_ref: str, candidate: int, target_leaf: str) -> str:
    """The candidate-scoped node id for one body target (issue #4).

    Candidate results commit to ``<alias>.c<k>.<leaf>`` — never to the
    body step's raw target names — so losers stay recorded in state while
    only the gather's alias carries the join's committed value.
    """
    return f"{alias_ref}.c{candidate}.{target_leaf}"


def candidate_task_text(body: Invocation, candidate: int) -> str:
    """The ledger task text for one candidate of a scatter entry (issue #4: ``[candidate k]``)."""
    return f"{body.step_id}: DO {body.command} [candidate {candidate}]"


def par_branch_invocation_id(branch: int) -> str:
    """The parent-side invocation id of one PAR branch (issue #24)."""
    return f"par{branch}"


def par_branch_run_id(parent_run_id: str, branch: int) -> str:
    """The isolated child run id of one PAR branch (issue #24)."""
    return f"{parent_run_id}:{par_branch_invocation_id(branch)}"


def par_branch_summary(branch: ParBranch) -> str:
    """The canonical summary text of one PAR branch (task texts, events)."""
    if branch.invocation is not None:
        return f"{branch.invocation.step_id}: DO {branch.invocation.command}"
    return f"CALL {branch.call.protocol}"


def par_branch_task_text(branch: ParBranch, position: int) -> str:
    """The ledger task text for one PAR branch (issue #24: one per branch)."""
    return f"PAR branch {position}: {par_branch_summary(branch)}"


def branch_workspace_dir(base: str | None, branch_id: str) -> str | None:
    """The isolated workspace subdirectory for one branch (issue #23).

    ``<base>/branches/<branch_id>/`` — nested branches (a PAR inside a
    branch run) nest under the enclosing branch's own directory, keeping
    each branch tree disjoint.  ``None`` base (no workspace declared)
    means no branch isolation.
    """
    if base is None:
        return None
    return os.path.join(base, "branches", branch_id)


def judge_score(result: Any) -> float:
    """Deterministically extract a ranked-gather score from a judge result.

    A number (or bool) scores directly; the string ``"passed"`` scores 1.0
    and any other string 0.0; a mapping prefers a numeric ``score`` field
    and falls back to ``status == "passed"`` -> 1.0 / 0.0.  Anything else
    raises ValueError (the gather fails through the standard path rather
    than guessing a score).
    """
    if isinstance(result, bool):
        return 1.0 if result else 0.0
    if isinstance(result, (int, float)):
        return float(result)
    if isinstance(result, str):
        return 1.0 if result == "passed" else 0.0
    if isinstance(result, Mapping):
        score = result.get("score")
        if isinstance(score, bool):
            return 1.0 if score else 0.0
        if isinstance(score, (int, float)):
            return float(score)
        status = result.get("status")
        if isinstance(status, str):
            return 1.0 if status == "passed" else 0.0
        raise ValueError(
            "judge result has no scorable field: expected a number, the"
            ' string "passed", or a mapping with a numeric "score" field'
            ' or a "status" field'
        )
    raise ValueError(
        f"judge result is not scorable: {type(result).__name__}"
    )


@dataclasses.dataclass(frozen=True)
class _PlanEntry:
    """One flattened execution-plan entry.

    A plain (or conditional) ``Invocation`` step carries ``invocation``;
    a ``CALL protocol.name(...)`` statement (issue #20) carries ``call``
    and executes as an isolated child run (``_execute_call``) instead of
    being expanded inline.

    ``task_prefix`` prefixes the ledger task text — always empty since
    #20 (protocol steps run in their own child run with unprefixed
    texts); ``binds``/``finalizes`` are vestiges of the pre-#20 inline
    CALL expansion and are retained only so the external driver's plan
    inspection (envelope.py, which this module must not change the plan
    shape for) keeps working: they are always empty now, and the driver
    rejects CALL programs before plan entries are inspected.
    ``condition`` is the raw condition text for a DO invocation embedded
    in an ``IF`` conditional (issue #3): ``None`` for unconditional
    entries.  Conditional entries sit after every unconditional entry in
    the plan (validation enforces the source rule) and create their
    ledger task lazily, only when the condition actually fires — a false
    branch performs no work.  A ``call`` entry is never conditional
    (CALL cannot be embedded in IF).
    """

    invocation: Invocation | None = None
    call: "Call | None" = None
    # Issue #4: a SCATTER block occupies one plan entry (its per-candidate
    # expansion happens at execution time over the committed collection);
    # its GATHER is the next plan entry and commits the alias node.
    scatter: "Scatter | None" = None
    gather: "Gather | None" = None
    # Issue #24: a PAR block (branches + BARRIER) occupies one plan entry;
    # its per-branch tasks and child runs are created during execution.
    par: "Par | None" = None
    task_prefix: str = ""
    binds: tuple[tuple[str, tuple[Argument, ...], tuple[Declaration, ...]], ...] = ()
    finalizes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # Issue #3: raw condition text for a DO invocation embedded in an ``IF``
    # conditional.  ``None`` for unconditional entries.  Conditional entries
    # sit after every unconditional entry in the plan (validation enforces
    # the source rule) and create their ledger task lazily, only when the
    # condition actually fires — a false branch performs no work.
    condition: str | None = None

_BUILTIN_REGISTRY_DIGEST: str | None = None
_EFFECTFUL_COMMANDS: frozenset[str] | None = None


def _builtin_registry_digest() -> str:
    """Digest of the builtin command registry, computed once per process."""
    global _BUILTIN_REGISTRY_DIGEST
    if _BUILTIN_REGISTRY_DIGEST is None:
        from tikhon.registry.registry import builtin_registry, registry_digest

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
        from tikhon.registry.enums import EffectClass
        from tikhon.registry.registry import builtin_registry

        durable = {EffectClass.REVERSIBLE_WRITE, EffectClass.IRREVERSIBLE_WRITE}
        registry = builtin_registry()
        _EFFECTFUL_COMMANDS = frozenset(
            name
            for name in registry.names()
            if registry.resolve(name).effect_class in durable
        )
    return _EFFECTFUL_COMMANDS


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


def map_results_to_targets(
    targets: tuple[str, ...],
    result: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Map a worker result to step target references.

    Returns ``(target_values, None)`` on success or ``(None, error_msg)``
    on failure.  Single-target invocations accept any result type.
    Multi-target invocations require a mapping whose keys match either
    the full target reference or the leaf name (the last ``.``-segment),
    with duplicate leaf names resolved only by full-key match.
    """
    if len(targets) == 1:
        return {targets[0]: result}, None

    if not isinstance(result, Mapping):
        return None, (
            f"handler returned non-mapping for multiple targets"
        )

    leaves = [target.split(".")[-1] for target in targets]
    duplicate_leaves = {leaf for leaf in leaves if leaves.count(leaf) > 1}

    target_values: dict[str, Any] = {}
    missing_keys: list[str] = []
    ambiguous_keys: list[str] = []

    for target, leaf in zip(targets, leaves):
        if target in result:
            target_values[target] = result[target]
        elif leaf in result and leaf not in duplicate_leaves:
            target_values[target] = result[leaf]
        elif leaf in result:
            ambiguous_keys.append(leaf)
        else:
            missing_keys.append(target)

    errors: list[str] = []
    if ambiguous_keys:
        errors.append(
            "ambiguous result keys: " + ", ".join(sorted(set(ambiguous_keys)))
        )
    if missing_keys:
        errors.append("missing result keys: " + ", ".join(missing_keys))
    if errors:
        return None, "; ".join(errors)

    return target_values, None


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


class DeterministicWorker:
    """Wraps a mapping of command-name -> handler callable."""

    def __init__(self, handlers: Mapping[str, Callable[..., Any]]):
        self._handlers: dict[str, Callable[..., Any]] = dict(handlers)

    @property
    def commands(self) -> set[str]:
        return set(self._handlers)

    def execute(self, command: str, resolved_kwargs: dict[str, Any]) -> Any:
        handler = self._handlers[command]
        return handler(**resolved_kwargs)


class SequentialCoordinator:
    """Drives a tikhon program sequentially through an EventStore.

    ``workspace_root`` is the WorkspacePolicy hook (issue #9): when set,
    every dispatch of an effectful command (durable-write class per the
    builtin registry, e.g. ``edit``) injects a resolved ``_workspace_root``
    kwarg so handlers can sandbox their writes; when ``None``, effectful
    commands still dispatch but no root is provided and handlers decide
    whether that is acceptable.
    """

    def __init__(
        self,
        store: EventStore,
        worker: DeterministicWorker,
        memory: "KnowledgeBase | None" = None,
        workspace_root: str | None = None,
        protocols_dir: str | Path | None = None,
    ):
        self.store = store
        self.worker = worker
        self.memory = memory
        self.workspace_root = workspace_root
        # Issue #12: directory holding sealed protocol files.  ``None``
        # means the default ``protocols/`` under the current working
        # directory (resolved lazily, only when a program CALLs a protocol).
        self.protocols_dir = protocols_dir

    def _resolve_kb_ref(self, ref: str) -> Any:
        """Resolve a ``KB.<name>`` reference from the knowledge base."""
        if self.memory is None:
            raise ValueError(
                f"KB reference {ref} requires a knowledge base:"
                " construct SequentialCoordinator with"
                " memory=KnowledgeBase(path)"
            )
        key = "kb." + ref.split(".", 1)[1]
        if key not in self.memory:
            raise ValueError(f"KB key {key!r} not found (reference {ref})")
        return self.memory.get(key)

    @staticmethod
    def _reject_unresolved_refs(value: Any, values: Mapping[str, Any]) -> None:
        """Fail ref-shaped arguments that no longer resolve (issue #7).

        Validation guarantees every ref inside an argument resolves at
        dispatch time — except refs retired by an earlier step's RETIRE
        clause.  Passing such a ref through as a literal would silently
        feed the raw ref string to the worker, so the invocation must
        fail clearly instead.  Purely additive: before retirement existed
        this guard was unreachable for validated programs, so it cannot
        change the behavior of any pre-#7 program.
        """
        if isinstance(value, str):
            if (
                value not in values
                and not value.startswith("KB.")
                and is_typed_reference(value)
            ):
                raise ValueError(
                    f"reference {value} is not in run state (retired or"
                    " undefined); retired nodes cannot be read by later"
                    " steps"
                )
        elif isinstance(value, list):
            for item in value:
                SequentialCoordinator._reject_unresolved_refs(item, values)

    def _resolve_arg_value(self, value: Any, values: Mapping[str, Any]) -> Any:
        """Resolve one raw argument value against run state (issue #12).

        Same resolution rules as invocation arguments: a bare typed ref
        resolves from ``values``, a ``KB.*`` ref from the knowledge base,
        reference lists resolve item-wise, literals pass through.
        """
        if isinstance(value, str) and value in values:
            return values[value]
        if isinstance(value, str) and value.startswith("KB."):
            return self._resolve_kb_ref(value)
        if isinstance(value, list):
            return [
                values[item] if isinstance(item, str) and item in values
                else self._resolve_kb_ref(item)
                if isinstance(item, str) and item.startswith("KB.")
                else item
                for item in value
            ]
        return value

    def _resolve_call_arguments(
        self,
        call: Call,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Resolve a CALL's arguments against the caller's run state (issue #20).

        Returns a ``protocol INPUT leaf name -> resolved value`` mapping:
        each argument is guarded by :meth:`_reject_unresolved_refs` and
        resolved like an invocation argument (bare ref from ``values``,
        ``KB.*`` from the knowledge base, reference lists item-wise,
        literals pass through).  Validation guarantees the argument names
        exactly cover the protocol's INPUT leaf names.
        """
        resolved: dict[str, Any] = {}
        for arg in call.args:
            self._reject_unresolved_refs(arg.value, values)
            resolved[arg.name] = self._resolve_arg_value(arg.value, values)
        return resolved

    def _bind_child_inputs(
        self,
        protocol: Program,
        resolved: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Seed the child run's initial state from resolved CALL args (issue #20).

        The child's state namespace starts from the protocol's INPUT
        declarations — the protocol file's declared literal values first
        (they are lint placeholders), then every declared ref overwritten
        by the CALL argument bound to its leaf name.  The caller's own
        ``values`` are NOT visible to the child beyond these explicit
        bindings.
        """
        child_values: dict[str, Any] = {
            declaration.ref: declaration.value
            for declaration in protocol.declarations
        }
        for declaration in protocol.declarations:
            leaf = declaration.ref.split(".")[-1]
            if leaf in resolved:
                child_values[declaration.ref] = resolved[leaf]
        return child_values

    @staticmethod
    def _apply_committed_deltas(values: dict[str, Any], events: Any) -> None:
        """Replay committed SUCCEEDED deltas onto a values mapping in seq order.

        Shared by resume (issue #10) and child adoption (issue #20):
        add/revise write, retire pops — reproducing the values mapping the
        coordinator held at any committed point of the run.
        """
        for event in events:
            if event.event_type is not EventType.SUCCEEDED:
                continue
            payload = event.payload
            if not isinstance(payload, dict) or "delta" not in payload:
                continue
            delta = StateDelta.from_dict(payload["delta"])
            for node in delta.add_nodes:
                values[node["id"]] = node["value"]
            for node in delta.revise_nodes:
                values[node["id"]] = node["value"]
            for ref in delta.retire_nodes:
                values.pop(ref, None)

    def _execute_call_child(
        self,
        call: Call,
        resolved: Mapping[str, Any],
        parent_run_id: str,
        invocation_id: str,
        gate: "BudgetGate | None" = None,
        claims: "ResourceLedger | None" = None,
        branch_workspace: str | None = None,
        branch_claim: str | None = None,
    ) -> dict[str, Any]:
        """Start, resume, or read back the CALL's isolated child run (issue #20).

        The child run id is ``"<parent_run_id>:<invocation_id>"`` —
        deterministic from the plan alone, collision-free in the run tree
        (repeated calls and nested calls get distinct ids), and identical
        across resume attempts.  Issue #24: PAR CALL branches reuse this
        machinery with ``invocation_id="par<k>"``; issue #23: a child run
        inside a branch inherits the branch's isolated workspace root and
        claim resource (``branch_workspace``/``branch_claim``).

        - Missing run: started fresh through :meth:`_execute_program` —
          same store/worker/memory/protocols_dir/workspace_root, its own
          RUN_STARTED marked ``child_of``/``call``, its own task ledger,
          and a state namespace seeded only from the resolved CALL
          arguments (the parent's ``values`` are not visible otherwise).
        - Existing terminal run: returned verbatim without re-executing
          anything (the caller adopts from the child's committed state).
        - Existing non-terminal run (parent crashed mid-child):
          re-driven through :meth:`_resume_existing_run` — at-least-once,
          with the child's DISPATCHED idempotency key as the dedup
          contract for effectful steps.
        """
        protocol = load_protocol(call.protocol, self.protocols_dir)
        child_run_id = f"{parent_run_id}:{invocation_id}"
        child_values = self._bind_child_inputs(protocol, resolved)
        result = self._execute_program_child(
            protocol,
            child_run_id,
            parent_run_id,
            call.protocol,
            child_values,
            gate,
            claims=claims,
            branch_workspace=branch_workspace,
            branch_claim=branch_claim,
        )
        result["protocol"] = protocol
        return result

    def _execute_program_child(
        self,
        program: Program,
        child_run_id: str,
        parent_run_id: str,
        call_name: str | None,
        child_values: Mapping[str, Any],
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None" = None,
        branch_workspace: str | None = None,
        branch_claim: str | None = None,
    ) -> dict[str, Any]:
        """Start, resume, or read back one isolated child run (issue #24).

        Shared by CALL child runs (:meth:`_execute_call_child`) and PAR
        branch child runs (a DO branch executes as a synthetic
        single-invocation program): missing runs start fresh, terminal
        runs read back without re-execution, non-terminal runs resume
        at-least-once.
        """
        try:
            self.store.run(child_run_id)
        except KeyError:
            result = self._execute_program(
                program,
                child_run_id,
                child_of=parent_run_id,
                call_name=call_name,
                initial_values=dict(child_values),
                gate=gate,
                claims=claims,
                branch_workspace=branch_workspace,
                branch_claim=branch_claim,
            )
            result["child_values"] = dict(child_values)
            return result
        events = self.store.events(child_run_id)
        finished = [
            event for event in events
            if event.event_type is EventType.RUN_FINISHED
        ]
        if finished:
            # Already terminal (crash between child completion and parent
            # adoption, or a repeated resume): adopt without re-executing.
            payload = (
                finished[-1].payload
                if isinstance(finished[-1].payload, dict)
                else {}
            )
            result: dict[str, Any] = {
                "run_id": child_run_id,
                "status": payload.get("status", "unknown"),
                "outputs": {},
                "child_values": dict(child_values),
            }
            if "error" in payload:
                result["error"] = payload["error"]
            return result
        result = self._resume_existing_run(
            program,
            child_run_id,
            initial_values=dict(child_values),
            gate=gate,
            claims=claims,
            branch_workspace=branch_workspace,
            branch_claim=branch_claim,
        )
        result["child_values"] = dict(child_values)
        return result

    def _adopt_child_result(
        self,
        call: Call,
        child: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Map the child's RETURN refs onto the CALL targets (issue #20).

        The mapping is exact-string, like the pre-#20 inline finalizes:
        each CALL target (validation pins targets to a subset of the
        protocol's RETURN refs) adopts the value the child held under the
        same reference.  The source is the child's committed state —
        seeded INPUT bindings plus replayed SUCCEEDED deltas — so a fresh
        adoption and a resume-after-crash adoption are identical, and a
        ref the child retired is (correctly) not adoptable.  Returns
        ``(adopted_nodes, adopted_map)``: the parent-side ``{"id",
        "value"}`` nodes for the CALL's SUCCEEDED delta and the
        ``{target: ref}`` payload for the CHILD_ADOPTED event.  A missing
        ref raises; the caller fails the run through the standard atomic
        path.
        """
        child_run_id = child["run_id"]
        values: dict[str, Any] = dict(child["child_values"])
        self._apply_committed_deltas(values, self.store.events(child_run_id))
        adopted_nodes: list[dict[str, Any]] = []
        adopted_map: dict[str, str] = {}
        for target in call.targets:
            if target not in values:
                raise ValueError(
                    f"child run {child_run_id} for {call.protocol} did not"
                    f" commit RETURN reference {target}"
                )
            adopted_nodes.append({"id": target, "value": values[target]})
            adopted_map[target] = target
        return adopted_nodes, adopted_map

    def _adopt_branch_nodes(
        self,
        child_run_id: str,
        child_values: Mapping[str, Any],
        targets: tuple[str, ...],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Map a PAR branch child's committed refs onto the parent (issue #24).

        Same exact-string adoption as :meth:`_adopt_child_result`, reading
        the branch run's committed state (seeded inputs plus replayed
        SUCCEEDED deltas) so a fresh adoption and a resume-after-crash
        adoption are identical.  A missing ref raises; the caller fails
        the run through the standard atomic path.
        """
        values: dict[str, Any] = dict(child_values)
        self._apply_committed_deltas(values, self.store.events(child_run_id))
        adopted_nodes: list[dict[str, Any]] = []
        adopted_map: dict[str, str] = {}
        for target in targets:
            if target not in values:
                raise ValueError(
                    f"branch run {child_run_id} did not commit reference"
                    f" {target}"
                )
            adopted_nodes.append({"id": target, "value": values[target]})
            adopted_map[target] = target
        return adopted_nodes, adopted_map

    def _build_branch_program(
        self,
        branch_invocation: Invocation,
        resolved_kwargs: Mapping[str, Any],
    ) -> Program:
        """The synthetic single-invocation child program for a DO branch.

        The branch executes in an isolated child run whose state namespace
        is seeded only from its dispatch-resolved arguments: every
        argument is rebound to a declared ``Q.<name>`` INPUT node carrying
        the resolved value, so the child validates and executes without
        seeing any parent state beyond the explicit bindings (the same
        isolation rule as CALL child runs).  The branch's DONE predicate,
        targets and corrections (the latter rejected at validation) ride
        along unchanged.
        """
        declarations = tuple(
            Declaration(f"Q.{name}", value)
            for name, value in resolved_kwargs.items()
        )
        args = tuple(
            Argument(name, f"Q.{name}", argument.line)
            for name, argument in (
                (argument.name, argument) for argument in branch_invocation.args
            )
        )
        invocation = dataclasses.replace(branch_invocation, args=args)
        return Program(
            "par_branch",
            "1.0",
            declarations,
            (invocation, Return(invocation.targets)),
        )

    # ------------------------------------------------------------------
    # Explicit artifact merge (issue #23)
    # ------------------------------------------------------------------

    def _merge_branch_artifacts(
        self,
        run_id: str,
        owner: str,
        claims: "ResourceLedger | None",
        artifacts: list[dict[str, Any]],
        branch_dirs: Mapping[str, str | None],
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Integrate branch-produced artifacts into the parent workspace.

        Deterministic: artifacts are visited in branch order, then target
        order.  The merge holds the exclusive ``merge:<run_id>`` claim for
        its duration (so merges serialize by contract).  A relative path
        produced by two different branches is an explicit conflict: the
        caller fails the run atomically instead of silently overwriting
        (no last-writer-wins).  Each artifact file found in its branch
        workspace is copied to the same relative path under the parent
        workspace root; the returned accounting lists every adopted
        artifact path with whether its file was integrated.
        """
        if not artifacts:
            return [], None
        resource = f"merge:{run_id}"
        if claims is not None:
            if not claims.claim(resource, owner):
                return [], (
                    f"resource claim failed: {resource} is held by"
                    f" {claims.holder(resource)!r}"
                )
        try:
            seen: dict[str, str] = {}
            for artifact in artifacts:
                path = artifact["path"]
                prior = seen.get(path)
                if prior is not None and prior != artifact["branch"]:
                    return [], (
                        f"artifact merge collision: relative path"
                        f" {path!r} was produced by branches"
                        f" {prior!r} and {artifact['branch']!r}; refusing"
                        " to overwrite — integrate the branches explicitly"
                    )
                seen[path] = artifact["branch"]
            merged: list[dict[str, Any]] = []
            for artifact in artifacts:
                entry: dict[str, Any] = {
                    "branch": artifact["branch"],
                    "node": artifact["node"],
                    "path": artifact["path"],
                }
                branch_dir = branch_dirs.get(artifact["branch"])
                if self.workspace_root is not None and branch_dir is not None:
                    source = Path(branch_dir) / artifact["path"]
                    if source.is_file():
                        destination = Path(self.workspace_root) / artifact["path"]
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, destination)
                        entry["copied"] = True
                    else:
                        entry["copied"] = False
                merged.append(entry)
            return merged, None
        finally:
            if claims is not None:
                claims.release(resource, owner)

    # ------------------------------------------------------------------
    # PAR blocks (issue #24)
    # ------------------------------------------------------------------

    def _par_branch_task_ids(self, run_id: str, par: Par) -> list[str]:
        """Branch-order ledger task ids for a PAR block's branches.

        One task per branch, no block task (issue #24).  Existing tasks
        (a resume after a crash inside the block) are found by their
        canonical text; missing ones are created in one batch with the
        same record shape as the plan's task-creation batch.
        """
        ledger = self.store.task_ledger(run_id)
        by_text = {
            task.text: task_id for task_id, task in ledger.tasks.items()
        }
        mapping: list[str] = []
        create_records: list[_Record] = []
        create_ledger = self.store.task_ledger(run_id)
        for position, branch in enumerate(par.branches, 1):
            text = par_branch_task_text(branch, position)
            existing = by_text.get(text)
            if existing is not None:
                mapping.append(existing)
                continue
            task = create_ledger.create_task(text=text, creator="coordinator")
            mapping.append(task.id)
            create_records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task.id,
                payload={
                    "kind": "task_created", "id": task.id, "text": task.text,
                    "priority": task.priority, "parent": task.parent,
                    "dependencies": task.dependencies, "creator": task.creator,
                },
                store=self.store,
            ))
        if create_records:
            self.store.append_batch(run_id, create_records)
        return mapping

    def _execute_par_entry(
        self,
        program: Program,
        run_id: str,
        entry: _PlanEntry,
        idx: int,
        invocation_id: str,
        values: dict[str, Any],
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
    ) -> dict[str, Any] | None:
        """Execute one PAR plan entry (issue #24): branches + barrier.

        Branches dispatch concurrently onto a pool capped at
        ``min(MAX, branch count)`` (further capped tree-wide by the
        budget's shared semaphore); each branch executes as an isolated
        child-scoped run ``<run_id>:par<k>`` (state isolation for free
        from the child-run machinery) whose effectful dispatches write
        into the branch's isolated workspace subdirectory and hold the
        branch's ``workspace:<branch run id>`` claim (issue #23).  Every
        commit happens on the coordinator's single-writer thread.

        The barrier blocks until every branch is terminal.  All
        succeeded: the branch outputs are adopted by explicit target
        mapping — one CHILD_ADOPTED per branch at its completion, then a
        single entry-terminal SUCCEEDED committing every adopted target
        in branch order (atomically published declared outputs) — the
        explicit artifact merge integrates branch-produced ART.* paths,
        and a PAR_JOINED event records the branch statuses and the merge
        accounting.  Any branch failure: the standard atomic failure path
        (one FAILED, sibling tasks cancelled, in-flight pool work drained
        and discarded, RUN_FINISHED failed); sibling results are never
        adopted.
        """
        par = entry.par
        instruction_id = f"par.inv-{idx + 1}"
        base = branch_root if branch_root is not None else self.workspace_root
        branch_tasks = self._par_branch_task_ids(run_id, par)
        branch_targets = [
            (
                branch.invocation.targets
                if branch.invocation is not None
                else branch.call.targets
            )
            for branch in par.branches
        ]
        published = list(par.barrier_targets) or [
            target for targets in branch_targets for target in targets
        ]

        def fail_par(error: str, failed_position: int | None = None) -> dict[str, Any]:
            """Fail the run at the PAR entry (standard atomic path).

            A branch-attributable failure carries the branch's FAILED
            event (invocation id ``par<k>``); a join-level failure (the
            artifact merge) carries the PAR entry's positional invocation
            id with the ``"par"`` payload marker — the PAR block owns no
            ledger task of its own, so neither carries a task_id (the
            audit exempts exactly these marked events).
            """
            records: list[_Record] = []
            if failed_position is not None:
                task_id = branch_tasks[failed_position - 1]
                records.extend([
                    _Record(
                        event_type=EventType.FAILED,
                        instruction_id=par_branch_summary(
                            par.branches[failed_position - 1]
                        ),
                        invocation_id=par_branch_invocation_id(failed_position),
                        task_id=task_id,
                        payload={"error": error},
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={"kind": "task_started", "id": task_id},
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={
                            "kind": "invocation_recorded", "id": task_id,
                            "tokens": 0, "cost": 0.0, "retries": 0,
                            "elapsed_seconds": 0.0,
                        },
                        store=self.store,
                    ),
                ])
            else:
                records.append(_Record(
                    event_type=EventType.FAILED,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    payload={"error": error, "par": True},
                    store=self.store,
                ))
            for position, task_id in enumerate(branch_tasks, 1):
                self._cancel_task_if_unsettled(
                    run_id, task_id, records,
                    reason=(
                        f"[branch {position}] {error}"
                        if failed_position is not None
                        and position != failed_position
                        else None
                    ),
                )
            for pending_idx in range(idx + 1, len(plan)):
                if pending_idx in statement_to_task:
                    records.append(_Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=statement_to_task[pending_idx],
                        payload={
                            "kind": "task_cancelled",
                            "id": statement_to_task[pending_idx],
                        },
                        store=self.store,
                    ))
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": error},
                store=self.store,
            ))
            self.store.append_batch(run_id, records)
            return {
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "outputs": {},
            }

        # Branch tasks already terminal from a crashed earlier drive keep
        # their accounting; their outputs are re-read from the committed
        # child state instead of re-dispatching (at-least-once, and the
        # store's dup-SUCCEEDED guard stays untouched).
        ledger = self.store.task_ledger(run_id)
        already_joined: dict[int, list[dict[str, Any]]] = {}
        pending_positions: list[int] = []
        for position, task_id in enumerate(branch_tasks, 1):
            task = ledger.tasks.get(task_id)
            if task is not None and task.status is TaskStatus.COMPLETED:
                already_joined[position] = []
            else:
                pending_positions.append(position)

        adopted_by_branch: dict[int, list[dict[str, Any]]] = dict(already_joined)
        branch_dirs: dict[str, str | None] = {
            f"par{position}": branch_workspace_dir(base, f"par{position}")
            for position in range(1, len(par.branches) + 1)
        }
        failure: dict[str, Any] | None = None
        max_at_once = max(1, min(par.max_count, len(par.branches)))

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_at_once
        ) as pool:
            in_flight: dict[int, concurrent.futures.Future] = {}
            queue = list(pending_positions)

            def dispatch_branch(position: int) -> dict[str, Any] | None:
                """Dispatch one branch; returns a failure result or None."""
                branch = par.branches[position - 1]
                branch_invocation_id = par_branch_invocation_id(position)
                child_run_id = par_branch_run_id(run_id, position)
                task_id = branch_tasks[position - 1]
                summary = par_branch_summary(branch)
                if gate is not None and gate.depth_exceeded(child_run_id):
                    return fail_par(
                        f"branch run {child_run_id} depth"
                        f" {gate.depth_of(child_run_id)} exceeds budget"
                        f" max_child_depth {gate.budget.max_child_depth}",
                        failed_position=position,
                    )
                try:
                    if branch.call is not None:
                        resolved = self._resolve_call_arguments(branch.call, values)
                    else:
                        resolved = self._resolve_branch_arguments(
                            branch.invocation, values
                        )
                except Exception as exc:
                    return fail_par(
                        f"PAR branch {position} ({summary}) failed to"
                        f" resolve arguments: {exc}",
                        failed_position=position,
                    )
                branch_workspace = branch_dirs[f"par{position}"]
                branch_claim = (
                    f"workspace:{child_run_id}"
                    if branch_workspace is not None
                    else None
                )
                self.store.append_batch(run_id, [
                    _Record(
                        event_type=EventType.INVOCATION_READY,
                        instruction_id=summary,
                        invocation_id=branch_invocation_id,
                        task_id=task_id,
                        payload={"command": summary},
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.INVOCATION_DISPATCHED,
                        instruction_id=summary,
                        invocation_id=branch_invocation_id,
                        task_id=task_id,
                        payload={
                            "child_run_id": child_run_id,
                            "branch_id": f"par{position}",
                        },
                        store=self.store,
                    ),
                ])
                in_flight[position] = pool.submit(
                    self._execute_par_branch,
                    branch,
                    resolved,
                    run_id,
                    position,
                    gate,
                    claims,
                    branch_workspace,
                    branch_claim,
                )
                return None

            while queue or in_flight:
                if failure is not None:
                    break
                while queue and len(in_flight) < max_at_once:
                    position = queue.pop(0)
                    failure = dispatch_branch(position)
                    if failure is not None:
                        break
                if failure is not None or not in_flight:
                    break
                owner = {future: pos for pos, future in in_flight.items()}
                done, _ = concurrent.futures.wait(
                    list(in_flight.values()),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    position = owner[future]
                    del in_flight[position]
                    if failure is not None:
                        continue
                    branch = par.branches[position - 1]
                    task_id = branch_tasks[position - 1]
                    child_run_id = par_branch_run_id(run_id, position)
                    summary = par_branch_summary(branch)
                    try:
                        child = future.result()
                    except Exception as exc:
                        failure = fail_par(
                            f"PAR branch {position} ({summary}) failed:"
                            f" {exc}",
                            failed_position=position,
                        )
                        continue
                    child_status = child.get("status", "unknown")
                    if child_status != "succeeded":
                        child_error = child.get("error")
                        error = (
                            f"branch run {child_run_id} for"
                            f" {summary} finished with status"
                            f" {child_status!r}; the PAR branch cannot"
                            " adopt its outputs"
                        )
                        if child_error:
                            error = f"{error}: {child_error}"
                        failure = fail_par(error, failed_position=position)
                        continue
                    targets = branch_targets[position - 1]
                    try:
                        adopted_nodes, adopted_map = self._adopt_branch_nodes(
                            child_run_id, child["child_values"], targets
                        )
                    except Exception as exc:
                        failure = fail_par(str(exc), failed_position=position)
                        continue
                    branch_artifacts = [
                        {"branch": f"par{position}", "node": node["id"],
                         "path": node["value"]}
                        for node in adopted_nodes
                        if node["id"].startswith("ART.")
                        and isinstance(node["value"], str)
                    ]
                    self.store.append_batch(run_id, [
                        _Record(
                            event_type=EventType.RESULT_RECEIVED,
                            instruction_id=summary,
                            invocation_id=par_branch_invocation_id(position),
                            task_id=task_id,
                            payload={
                                "child_run_id": child_run_id,
                                "status": child_status,
                            },
                            store=self.store,
                        ),
                        _Record(
                            event_type=EventType.CHILD_ADOPTED,
                            instruction_id=summary,
                            invocation_id=par_branch_invocation_id(position),
                            task_id=task_id,
                            payload={
                                "child_run_id": child_run_id,
                                "adopted": adopted_map,
                                "child_status": child_status,
                                "artifacts": branch_artifacts,
                            },
                            store=self.store,
                        ),
                        _Record(
                            event_type=EventType.TASK_UPDATED,
                            task_id=task_id,
                            payload={"kind": "task_started", "id": task_id},
                            store=self.store,
                        ),
                        _Record(
                            event_type=EventType.TASK_UPDATED,
                            task_id=task_id,
                            payload={
                                "kind": "invocation_recorded", "id": task_id,
                                "tokens": 0, "cost": 0.0, "retries": 0,
                                "elapsed_seconds": 0.0,
                            },
                            store=self.store,
                        ),
                        _Record(
                            event_type=EventType.TASK_UPDATED,
                            task_id=task_id,
                            payload={
                                "kind": "task_completed", "id": task_id,
                                "evidence": (
                                    f"PAR branch {position} ({child_run_id})"
                                    f" -> {list(targets)}"
                                ),
                            },
                            store=self.store,
                        ),
                    ])
                    adopted_by_branch[position] = adopted_nodes

        if failure is not None:
            # In-flight branches are cancelled: not-yet-started branches
            # were never dispatched; started child runs run to completion
            # in their own histories while the pool drains, and their
            # results are discarded uncommitted (never adopted).
            return failure

        # -- barrier: all branches terminal and succeeded ------------------
        artifacts: list[dict[str, Any]] = []
        for position in range(1, len(par.branches) + 1):
            artifacts.extend(
                {
                    "branch": f"par{position}",
                    "node": node["id"],
                    "path": node["value"],
                }
                for node in adopted_by_branch.get(position, [])
                if node["id"].startswith("ART.")
                and isinstance(node["value"], str)
            )
        merged, merge_error = self._merge_branch_artifacts(
            run_id,
            f"{run_id}:{invocation_id}",
            claims,
            artifacts,
            branch_dirs,
        )
        if merge_error is not None:
            return fail_par(merge_error)

        if crash_hook is not None:
            # Crash window after every branch joined and the merge is
            # decided, before the entry's terminal batch: resume re-derives
            # the adoptions and the merge from committed state.
            crash_hook(idx)

        ordered_nodes: list[dict[str, Any]] = []
        branch_statuses: dict[str, str] = {}
        for position in range(1, len(par.branches) + 1):
            branch_statuses[f"par{position}"] = "succeeded"
            ordered_nodes.extend(adopted_by_branch.get(position, []))
        for node in ordered_nodes:
            values[node["id"]] = node["value"]

        par_record = {
            "max": par.max_count,
            "branches": branch_statuses,
            "targets": published,
            "merged_artifacts": merged,
        }
        expected_sv = self.store._current_state_version(run_id)
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.PAR_JOINED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                payload={
                    "branches": branch_statuses,
                    "targets": published,
                    "merged_artifacts": merged,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                expected_state_version=expected_sv,
                payload={
                    "delta": StateDelta(add_nodes=tuple(ordered_nodes)),
                    "par": par_record,
                },
                store=self.store,
            ),
        ])
        return None

    def _execute_par_branch(
        self,
        branch: ParBranch,
        resolved: Mapping[str, Any],
        parent_run_id: str,
        position: int,
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_workspace: str | None,
        branch_claim: str | None,
    ) -> dict[str, Any]:
        """Execute one PAR branch as an isolated child run (issue #24).

        A CALL branch loads its protocol and binds the resolved arguments
        (exactly like a CALL child run); a DO branch executes a synthetic
        single-invocation program whose INPUT declarations carry the
        dispatch-resolved argument values.  Both run under the
        deterministic child id ``<parent_run_id>:par<position>`` and
        inherit the branch's isolated workspace root and claim resource.
        """
        child_run_id = par_branch_run_id(parent_run_id, position)
        if branch.call is not None:
            protocol = load_protocol(branch.call.protocol, self.protocols_dir)
            child_values = self._bind_child_inputs(protocol, resolved)
            result = self._execute_program_child(
                protocol,
                child_run_id,
                parent_run_id,
                branch.call.protocol,
                child_values,
                gate,
                claims=claims,
                branch_workspace=branch_workspace,
                branch_claim=branch_claim,
            )
            result["protocol"] = protocol
            return result
        child_program = self._build_branch_program(
            branch.invocation, resolved
        )
        child_values = {
            declaration.ref: declaration.value
            for declaration in child_program.declarations
        }
        return self._execute_program_child(
            child_program,
            child_run_id,
            parent_run_id,
            f"par:{branch.invocation.command}",
            child_values,
            gate,
            claims=claims,
            branch_workspace=branch_workspace,
            branch_claim=branch_claim,
        )

    def _resolve_branch_arguments(
        self,
        invocation: Invocation,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Resolve a DO branch's arguments against the parent state.

        Same resolution rules as a plain invocation dispatch (guard first,
        bare refs and reference lists from ``values``, ``KB.*`` from the
        knowledge base, literals through) — pinned at dispatch time so the
        branch child observes exactly the committed state the PAR
        dispatch saw.
        """
        resolved: dict[str, Any] = {}
        for arg in invocation.args:
            self._reject_unresolved_refs(arg.value, values)
            if isinstance(arg.value, str) and arg.value in values:
                resolved[arg.name] = values[arg.value]
            elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                resolved[arg.name] = self._resolve_kb_ref(arg.value)
            elif isinstance(arg.value, list):
                resolved[arg.name] = [
                    values[item] if isinstance(item, str) and item in values
                    else self._resolve_kb_ref(item)
                    if isinstance(item, str) and item.startswith("KB.")
                    else item
                    for item in arg.value
                ]
            else:
                resolved[arg.name] = arg.value
        return resolved

    # ------------------------------------------------------------------
    # Runtime-authored child plans (issue #25)
    # ------------------------------------------------------------------

    def _recorded_delegate_plan(self, run_id: str, invocation_id: str):
        """The CHILD_PLAN_AUTHORED event recorded for one delegate step.

        Replay identity (issue #25): the ACCEPTED artifact is the recorded
        one.  A resumed in-flight delegate step reuses the recorded plan
        text instead of re-asking the worker, so a crash can never trigger
        unrecorded replanning; a plan whose authoring crashed BEFORE the
        event committed was never accepted and re-authors (at-least-once).
        """
        for event in self.store.events(run_id):
            if (
                event.event_type is EventType.CHILD_PLAN_AUTHORED
                and event.invocation_id == invocation_id
            ):
                return event
        return None

    def _plan_contains_delegate(self, program: Program, seen: tuple[str, ...] = ()) -> bool:
        """Whether an authored plan reaches a delegate command at any depth.

        Rejects the delegate command in every dispatchable position of the
        authored program (plain steps, conditional DO lines, SCATTER
        bodies, GATHER judges, PAR branches) and transitively through every
        CALLed protocol file.  ``validate_program`` has already guaranteed
        the protocol call graph is acyclic and bounded at depth 8, so the
        walk terminates; ``seen`` only prunes diamond re-visits.
        """
        for invocation, call in _iter_invocations_and_calls(program):
            if invocation is not None and invocation.command == DELEGATE_COMMAND:
                return True
            if call is not None:
                if call.protocol in seen:
                    continue
                protocol = load_protocol(call.protocol, self.protocols_dir)
                if self._plan_contains_delegate(protocol, seen + (call.protocol,)):
                    return True
        return False

    def _execute_delegate_entry(
        self,
        run_id: str,
        idx: int,
        invocation_id: str,
        task_id: str,
        statement: Invocation,
        resolved_kwargs: dict[str, Any],
        values: dict[str, Any],
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        prior_types: set[EventType],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None",
        branch_root: str | None,
        branch_claim: str | None,
        fail_invocation: Callable[..., None],
    ) -> dict[str, Any] | None:
        """Execute one delegate plan entry (issue #25).

        The step's worker call returns the AUTHORED child plan text (the
        deterministic handler replies with a fixed sample plan; the model
        worker is prompted for a canonical-grammar child program).  The
        coordinator then:

        1. records the authored artifact as a CHILD_PLAN_AUTHORED event
           (payload ``{step_id, plan_digest, plan_text}``) BEFORE any
           validation or execution — the authored plan is part of history,
           never ephemeral, and stays recorded even when rejected;
        2. validates the plan with ``parse_program`` +
           ``validate_program`` against the worker's registry, and
           enforces the delegation bounds: step count <= ``max_steps``
           (default 6, hard cap 12) and no delegate command anywhere in
           the plan, directly or through called protocols (no recursion).
           Namespaces are already enforced by the parser's typed-reference
           grammar; the executed program's name is bound to
           ``delegated_<parent_step_id>``;
        3. executes the accepted plan as an isolated child run under the
           deterministic id ``<parent_run_id>:<invocation_id>`` — the same
           machinery as a CALL child (own ledger, own namespace seeded
           from the resolved delegate arguments, budget depth gate) — and
           adopts the plan's RETURN refs ONTO the delegate step's targets
           positionally (ref k -> target k); a count mismatch is a
           validation failure.

        Any rejection or non-succeeded child terminal fails the parent
        through the standard atomic path (``fail_invocation``).  Returns
        the terminal failure result dict, or ``None`` when the entry
        committed successfully and the plan loop should continue.
        """

        def fail_delegate(
            error: str,
            validation: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            fail_invocation(
                idx, statement.step_id, invocation_id, task_id, error,
                validation=validation,
            )
            return {
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "outputs": {},
            }

        def plan_defect(
            kind: str, detail: str
        ) -> dict[str, Any]:
            return fail_delegate(
                f"authored child plan rejected ({kind}): {detail}",
                validation={
                    "step_id": statement.step_id,
                    "plan_digest": plan_digest,
                    "failure_kind": kind,
                    "detail": detail,
                },
            )

        # -- the max_steps bound --------------------------------------
        raw_max = resolved_kwargs.get("max_steps", DELEGATE_DEFAULT_MAX_STEPS)
        if (
            isinstance(raw_max, bool)
            or not isinstance(raw_max, int)
            or raw_max < 1
        ):
            return fail_delegate(
                f"delegate requires an integer max_steps >= 1, got {raw_max!r}",
                validation={
                    "step_id": statement.step_id,
                    "failure_kind": "invalid_input",
                    "detail": f"max_steps={raw_max!r}",
                },
            )
        max_steps = min(int(raw_max), DELEGATE_HARD_MAX_STEPS)

        # -- the authored plan text (reused verbatim on resume) --------
        recorded = self._recorded_delegate_plan(run_id, invocation_id)
        if recorded is not None:
            payload = recorded.payload if isinstance(recorded.payload, dict) else {}
            plan_text = payload.get("plan_text")
            plan_digest = payload.get("plan_digest")
            if not isinstance(plan_text, str) or not isinstance(plan_digest, str):
                return fail_delegate(
                    "recorded CHILD_PLAN_AUTHORED event for this delegate"
                    " step carries no usable plan text/digest; cannot"
                    " replay the accepted artifact"
                )
        else:
            try:
                reply = self._execute_worker_call(
                    DELEGATE_COMMAND, resolved_kwargs, gate
                )
            except Exception as exc:
                return fail_delegate(str(exc))
            try:
                plan_text = _extract_plan_text(reply)
            except ValueError as exc:
                return fail_delegate(
                    str(exc),
                    validation={
                        "step_id": statement.step_id,
                        "failure_kind": "invalid_input",
                        "detail": str(exc),
                    },
                )
            plan_digest = delegate_plan_digest(statement.step_id, plan_text)
            if EventType.CHILD_PLAN_AUTHORED not in prior_types:
                self.store.append(
                    run_id,
                    EventType.CHILD_PLAN_AUTHORED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={
                        "step_id": statement.step_id,
                        "plan_digest": plan_digest,
                        "plan_text": plan_text,
                    },
                )

        # -- validation: parse, registry, bounds -----------------------
        try:
            authored = parse_program(plan_text)
        except ParseError as exc:
            return plan_defect("formalization", f"plan failed to parse: {exc}")
        try:
            validate_program(
                authored,
                known_commands=self.worker.commands,
                protocols_dir=self.protocols_dir,
            )
        except ParseError as exc:
            return plan_defect("formalization", f"plan is invalid: {exc}")
        try:
            contains_delegate = self._plan_contains_delegate(authored)
        except Exception as exc:
            return plan_defect("formalization", str(exc))
        if contains_delegate:
            return plan_defect(
                "invalid_input",
                "the plan contains a delegate command (directly or through"
                " a called protocol): nested dynamic delegation is"
                " rejected, plans stay bounded",
            )
        plan_steps = count_plan_steps(authored)
        if plan_steps > max_steps:
            return plan_defect(
                "formalization",
                f"the plan has {plan_steps} steps, exceeding the delegate"
                f" bound of {max_steps} (default"
                f" {DELEGATE_DEFAULT_MAX_STEPS}, hard cap"
                f" {DELEGATE_HARD_MAX_STEPS})",
            )

        # -- sealed-like binding and isolated child execution ----------
        bound = dataclasses.replace(
            authored, name=delegate_plan_name(statement.step_id)
        )
        child_run_id = f"{run_id}:{invocation_id}"
        if gate is not None and gate.depth_exceeded(child_run_id):
            return fail_delegate(
                f"child run {child_run_id} depth"
                f" {gate.depth_of(child_run_id)} exceeds budget"
                f" max_child_depth {gate.budget.max_child_depth}"
            )
        child_values = self._bind_child_inputs(bound, resolved_kwargs)
        try:
            child_result = self._execute_program_child(
                bound,
                child_run_id,
                run_id,
                f"delegate:{statement.step_id}",
                child_values,
                gate,
                claims=claims,
                branch_workspace=branch_root,
                branch_claim=branch_claim,
            )
        except Exception as exc:
            return fail_delegate(str(exc))
        child_status = child_result.get("status", "unknown")
        if child_status != "succeeded":
            child_error = child_result.get("error")
            error = (
                f"child run {child_run_id} for delegate"
                f" {statement.step_id} finished with status"
                f" {child_status!r}; the delegate step cannot adopt its"
                " outputs"
            )
            if child_error:
                error = f"{error}: {child_error}"
            return fail_delegate(error)

        if EventType.RESULT_RECEIVED not in prior_types:
            self.store.append(
                run_id,
                EventType.RESULT_RECEIVED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={
                    "child_run_id": child_run_id,
                    "plan_digest": plan_digest,
                    "plan_steps": plan_steps,
                    "status": child_status,
                },
            )

        # -- positional adoption: authored RETURN ref k -> target k ----
        return_statement = next(
            (
                item
                for item in bound.statements
                if isinstance(item, Return)
            ),
            None,
        )
        if return_statement is None:
            return plan_defect(
                "formalization",
                "the plan has no RETURN statement; the delegate step"
                " cannot adopt its outputs",
            )
        return_refs = return_statement.refs
        if len(return_refs) != len(statement.targets):
            return plan_defect(
                "formalization",
                "the plan's RETURN refs ("
                f"{', '.join(return_refs)}) do not map one-to-one onto the"
                f" delegate step's targets ({', '.join(statement.targets)})",
            )
        child_committed: dict[str, Any] = dict(
            child_result.get("child_values") or {}
        )
        self._apply_committed_deltas(
            child_committed, self.store.events(child_run_id)
        )
        adopted_nodes: list[dict[str, Any]] = []
        adopted_map: dict[str, str] = {}
        for target, ref in zip(statement.targets, return_refs):
            if ref not in child_committed:
                return fail_delegate(
                    f"child run {child_run_id} did not commit authored"
                    f" RETURN reference {ref}"
                )
            adopted_nodes.append({"id": target, "value": child_committed[ref]})
            adopted_map[target] = ref
        target_values: dict[str, Any] = {
            node["id"]: node["value"] for node in adopted_nodes
        }

        if statement.done is not None:
            passed, detail = evaluate_done_predicate(
                statement.done, target_values
            )
            if not passed:
                return fail_delegate(
                    f"DONE predicate failed for {statement.step_id}: {detail}",
                    validation={
                        "step_id": statement.step_id,
                        "plan_digest": plan_digest,
                        "predicate": {
                            "op": statement.done.op,
                            "ref": statement.done.ref,
                            "value": statement.done.value,
                        },
                        "detail": detail,
                    },
                )

        if crash_hook is not None:
            # Issue #25: crash window after the child is terminal but
            # before the parent adopts — resume reuses the recorded plan,
            # finds the terminal child, and adopts without re-executing.
            crash_hook(idx)

        self.store.append(
            run_id,
            EventType.VALIDATION_PASSED,
            instruction_id=statement.step_id,
            invocation_id=invocation_id,
            task_id=task_id,
            payload={},
        )

        for node in adopted_nodes:
            values[node["id"]] = node["value"]

        delta = StateDelta(add_nodes=tuple(adopted_nodes))
        expected_sv = self.store._current_state_version(run_id)

        # batch: CHILD_ADOPTED + SUCCEEDED + invocation_recorded
        # + task_completed — one atomic append, exactly like a CALL
        # adoption (the store's duplicate-SUCCEEDED guard makes a
        # re-adoption of the same delegate invocation impossible).
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.CHILD_ADOPTED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={
                    "child_run_id": child_run_id,
                    "adopted": adopted_map,
                    "child_status": child_status,
                    "plan_digest": plan_digest,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                expected_state_version=expected_sv,
                payload={"delta": delta},
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "invocation_recorded", "id": task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "task_completed", "id": task_id,
                    "evidence": (
                        f"delegate {statement.step_id} ({child_run_id})"
                        f" -> {list(statement.targets)}"
                    ),
                },
                store=self.store,
            ),
        ])
        return None

    def _build_plan(self, program: Program) -> list[_PlanEntry]:
        """Flatten the program into an execution plan.

        Caller invocations keep their positions; each CALL becomes its
        own plan entry (issue #20).  A CALL no longer expands the
        protocol's steps inline: executing the entry spawns an isolated
        child run whose plan is built from the protocol's own statements
        by the child's coordinator, and the child's RETURN refs are
        adopted onto the CALL targets when the child finishes succeeded.
        """
        entries: list[_PlanEntry] = []

        def walk(statements: tuple[object, ...]) -> None:
            for statement in statements:
                if isinstance(statement, Invocation):
                    entries.append(_PlanEntry(invocation=statement))
                elif isinstance(statement, Conditional):
                    # Issue #3: a conditional DO invocation occupies a plan
                    # entry carrying its condition; STOP/RETURN conditionals
                    # are not plan entries (no task, no worker call) and are
                    # evaluated at their source anchor by _collect_anchors.
                    if isinstance(statement.statement, Invocation):
                        entries.append(
                            _PlanEntry(
                                invocation=statement.statement,
                                condition=statement.condition,
                            )
                        )
                elif isinstance(statement, Call):
                    entries.append(_PlanEntry(call=statement))
                elif isinstance(statement, Scatter):
                    # Issue #4: the scatter block is one plan entry; its
                    # per-candidate tasks and invocations are created during
                    # execution (invocation ids hang off this entry's
                    # positional id as "inv-<K>.cand<k>").
                    entries.append(_PlanEntry(scatter=statement))
                elif isinstance(statement, Par):
                    # Issue #24: the PAR block (branches + barrier) is one
                    # plan entry; its per-branch tasks and child runs are
                    # created during execution (branch ids are "par<k>").
                    entries.append(_PlanEntry(par=statement))
                elif isinstance(statement, Gather):
                    entries.append(_PlanEntry(gather=statement))

        walk(program.statements)
        return entries

    def _create_plan_tasks(
        self, run_id: str, plan: list[_PlanEntry]
    ) -> dict[int, str]:
        """Batch-create one ledger task per plan entry (crash window W0b).

        Returns the ``plan index -> task_id`` mapping.  Kept separate from
        :meth:`_drive_plan` so resume (issue #10) can recreate tasks
        missing after a crash before the creation batch (W0a) and reuse
        the identical mapping rule (creation order == plan order).
        """
        statement_to_task: dict[int, str] = {}
        create_records: list[_Record] = []
        create_ledger = self.store.task_ledger(run_id)
        for idx, entry in enumerate(plan):
            if entry.condition is not None:
                # Issue #3: conditional entries are not part of the up-front
                # creation batch — a false branch performs no work, so its
                # ledger task exists only when the condition fires (created
                # lazily in _drive_plan).
                continue
            if entry.par is not None:
                # Issue #24: a PAR block creates no task of its own — the
                # ledger carries one task per branch, created when the
                # entry executes (_par_branch_task_ids).
                continue
            task = create_ledger.create_task(
                text=self._task_text(entry),
                creator="coordinator",
            )
            task_id = task.id
            statement_to_task[idx] = task_id

            create_records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "task_created", "id": task_id, "text": task.text,
                    "priority": task.priority, "parent": task.parent,
                    "dependencies": task.dependencies, "creator": task.creator,
                },
                store=self.store,
            ))

        if create_records:
            self.store.append_batch(run_id, create_records)
        return statement_to_task

    def _task_text(self, entry: _PlanEntry) -> str:
        """The canonical ledger task text for one plan entry."""
        if entry.call is not None:
            return f"CALL {entry.call.protocol}"
        if entry.scatter is not None:
            scatter = entry.scatter
            return (
                f"SCATTER {scatter.item_ref} IN {scatter.collection_ref}"
                f" MAX {scatter.max_count}"
            )
        if entry.par is not None:
            par = entry.par
            return f"PAR MAX {par.max_count} BARRIER"
        if entry.gather is not None:
            gather = entry.gather
            return (
                f"GATHER {gather.body_step_id} AS {gather.alias_ref}"
                f" USING {gather.mode}"
            )
        statement = entry.invocation
        return (
            f"{entry.task_prefix}{statement.step_id}:"
            f" DO {statement.command}"
        )

    def _collect_anchors(self, program: Program) -> dict[int, list]:
        """Map plan index -> STOP/RETURN conditionals at that source anchor.

        An anchor value is the number of plan entries preceding the
        conditional in source order, so anchor ``a`` conditionals are
        evaluated right after plan entry ``a - 1`` commits (anchor 0 before
        the loop starts, anchor ``len(plan)`` after it ends).  Conditional
        DO invocations are plan entries themselves and are never anchors.
        Computed per drive so the resume path (which drives the plan
        directly) evaluates the same anchors.
        """
        anchors: dict[int, list] = {}

        def walk(statements: tuple[object, ...]) -> int:
            count = 0
            for statement in statements:
                if isinstance(statement, Invocation):
                    count += 1
                elif isinstance(statement, Conditional):
                    if isinstance(statement.statement, Invocation):
                        count += 1
                    else:
                        anchors.setdefault(count, []).append(statement)
                elif isinstance(statement, Call):
                    # Issue #20: a CALL occupies exactly one plan entry (its
                    # isolated child run), so anchors after it index on that
                    # single entry.
                    count += 1
                elif isinstance(statement, (Scatter, Gather, Par)):
                    # Issue #4/#24: scatter, gather and PAR entries are
                    # ordinary plan entries for anchor indexing.
                    count += 1
            return count

        walk(program.statements)
        return anchors

    def _create_single_plan_task(self, run_id: str, entry: _PlanEntry) -> str:
        """Create one ledger task for a lazily reached conditional entry.

        The task text and creation record mirror ``_create_plan_tasks``
        exactly, so a fired conditional step is indistinguishable in the
        ledger from an unconditional one (issue #3).
        """
        statement = entry.invocation
        ledger = self.store.task_ledger(run_id)
        task = ledger.create_task(
            text=self._task_text(entry),
            creator="coordinator",
        )
        self.store.append(
            run_id,
            EventType.TASK_UPDATED,
            task_id=task.id,
            payload={
                "kind": "task_created", "id": task.id, "text": task.text,
                "priority": task.priority, "parent": task.parent,
                "dependencies": task.dependencies, "creator": task.creator,
            },
        )
        return task.id

    def _cancel_pending_after(
        self,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        from_idx: int,
    ) -> None:
        """Cancel every created-but-unreached plan task from ``from_idx``.

        Fired conditional STOP/RETURN terminals leave later invocations
        unreached; their batch-created tasks are cancelled exactly like the
        failure path.  Conditional tasks are created lazily, so absent
        mappings are skipped — no task exists for work that never started.
        """
        records = [
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=statement_to_task[pending_idx],
                payload={
                    "kind": "task_cancelled",
                    "id": statement_to_task[pending_idx],
                },
                store=self.store,
            )
            for pending_idx in range(from_idx, len(plan))
            if pending_idx in statement_to_task
        ]
        if records:
            self.store.append_batch(run_id, records)

    def _terminal_return(
        self, run_id: str, refs: tuple[str, ...], values: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Finish a run through a RETURN terminal (bare or conditional)."""
        outputs: dict[str, Any] = {ref: values.get(ref) for ref in refs}
        self.store.append(
            run_id,
            EventType.RUN_FINISHED,
            payload={"status": "succeeded"},
        )
        return {"run_id": run_id, "status": "succeeded", "outputs": outputs}

    def _terminal_stop(
        self, run_id: str, stop: Stop, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Finish a run through a STOP terminal (bare or conditional).

        ``completed`` maps to a succeeded run; every other kind is recorded
        verbatim, with the referenced node's value as the reason payload
        when the ref resolves.
        """
        if stop.kind == "completed":
            run_status = "succeeded"
        else:
            run_status = stop.kind
        reason = values.get(stop.ref) if stop.ref else None
        finished_payload: dict[str, Any] = {"status": run_status}
        if reason is not None:
            finished_payload["reason"] = reason
        self.store.append(
            run_id,
            EventType.RUN_FINISHED,
            payload=finished_payload,
        )
        return {"run_id": run_id, "status": run_status, "outputs": {}}

    def _fail_run(
        self,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        from_idx: int,
        error: str,
    ) -> dict[str, Any]:
        """Fail a run without an owning invocation (issue #3).

        A condition referencing a node retired mid-run cannot be tied to an
        invocation task, so the run fails through a reduced batch: pending
        tasks are cancelled and RUN_FINISHED carries the error.
        """
        self._cancel_pending_after(run_id, plan, statement_to_task, from_idx)
        self.store.append(
            run_id,
            EventType.RUN_FINISHED,
            payload={"status": "failed", "error": error},
        )
        return {"run_id": run_id, "status": "failed", "error": error, "outputs": {}}

    def _run_conditionals(
        self,
        run_id: str,
        conditionals: list,
        values: dict[str, Any],
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        cancel_from_idx: int,
    ) -> dict[str, Any] | None:
        """Evaluate source-anchored STOP/RETURN conditionals in order.

        A false condition skips the embedded statement and execution
        continues; a fired STOP/RETURN cancels the unreached plan tasks and
        finishes the run through the existing terminal handling.  Returns
        the terminal result dict, or ``None`` when no conditional fired.
        Conditional DO invocations never appear here — they are plan
        entries evaluated inside the loop itself.
        """
        for conditional in conditionals:
            try:
                fired = evaluate_condition(conditional.condition, values)
            except ValueError as exc:
                return self._fail_run(
                    run_id, plan, statement_to_task, cancel_from_idx, str(exc)
                )
            if not fired:
                continue
            embedded = conditional.statement
            self._cancel_pending_after(
                run_id, plan, statement_to_task, cancel_from_idx
            )
            if isinstance(embedded, Stop):
                return self._terminal_stop(run_id, embedded, values)
            if isinstance(embedded, Return):
                return self._terminal_return(run_id, embedded.refs, values)
        return None

    # ------------------------------------------------------------------
    # Deterministic scatter/gather (issue #4)
    # ------------------------------------------------------------------

    @staticmethod
    def _gather_for(program: Program, scatter: Scatter) -> Gather:
        """The GATHER statement directly following ``scatter`` (validated)."""
        statements = program.statements
        for position, statement in enumerate(statements):
            if statement is scatter:
                if position + 1 < len(statements):
                    following = statements[position + 1]
                    if isinstance(following, Gather) and (
                        following.body_step_id == scatter.body.step_id
                    ):
                        return following
                break
        raise ValueError(
            f"SCATTER block for {scatter.body.step_id} has no directly"
            " following GATHER"
        )

    @staticmethod
    def _scatter_for(program: Program, gather: Gather) -> Scatter:
        """The SCATTER statement directly preceding ``gather`` (validated)."""
        statements = program.statements
        for position, statement in enumerate(statements):
            if statement is gather:
                if position > 0:
                    preceding = statements[position - 1]
                    if isinstance(preceding, Scatter) and (
                        preceding.body.step_id == gather.body_step_id
                    ):
                        return preceding
                break
        raise ValueError(
            f"GATHER of {gather.body_step_id} has no directly preceding"
            " SCATTER block"
        )

    def _cancel_task_if_unsettled(
        self, run_id: str, task_id: str, records: list[_Record], reason: str | None = None
    ) -> None:
        """Queue a task_cancelled record when the task is not yet terminal."""
        ledger = self.store.task_ledger(run_id)
        task = ledger.tasks.get(task_id)
        if task is None or task.status in (
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
        ):
            return
        payload: dict[str, Any] = {"kind": "task_cancelled", "id": task_id}
        if reason:
            payload["reason"] = reason
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=task_id,
            payload=payload,
            store=self.store,
        ))

    def _candidate_task_ids(
        self,
        run_id: str,
        body: Invocation,
        count: int,
    ) -> dict[int, str]:
        """Map candidate number -> ledger task id, creating missing tasks.

        Existing candidate tasks (a resume after a crash inside the
        scatter) are found by their canonical text; missing ones are
        created in one batch with the same record shape as the plan's
        task-creation batch (crash window W0a for candidates).
        """
        ledger = self.store.task_ledger(run_id)
        by_text = {
            task.text: task_id for task_id, task in ledger.tasks.items()
        }
        mapping: dict[int, str] = {}
        create_records: list[_Record] = []
        create_ledger = self.store.task_ledger(run_id)
        for k in range(1, count + 1):
            text = candidate_task_text(body, k)
            existing = by_text.get(text)
            if existing is not None:
                mapping[k] = existing
                continue
            task = create_ledger.create_task(text=text, creator="coordinator")
            mapping[k] = task.id
            create_records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task.id,
                payload={
                    "kind": "task_created", "id": task.id, "text": task.text,
                    "priority": task.priority, "parent": task.parent,
                    "dependencies": task.dependencies, "creator": task.creator,
                },
                store=self.store,
            ))
        if create_records:
            self.store.append_batch(run_id, create_records)
        return mapping

    def _candidate_cancel_reasons(
        self, run_id: str, task_ids: dict[int, str]
    ) -> dict[int, str]:
        """Candidate number -> recorded loser reason (resume reconstruction)."""
        reasons: dict[int, str] = {}
        task_to_k = {task_id: k for k, task_id in task_ids.items()}
        for event in self.store.events(run_id):
            if event.event_type is not EventType.TASK_UPDATED:
                continue
            payload = event.payload
            if not isinstance(payload, dict):
                continue
            if payload.get("kind") != "task_cancelled":
                continue
            k = task_to_k.get(payload.get("id"))
            if k is not None and isinstance(payload.get("reason"), str):
                reasons[k] = payload["reason"]
        return reasons

    def _execute_scatter_entry(
        self,
        program: Program,
        run_id: str,
        entry: _PlanEntry,
        idx: int,
        invocation_id: str,
        task_id: str,
        values: dict[str, Any],
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None" = None,
        branch_root: str | None = None,
    ) -> dict[str, Any] | None:
        """Execute one SCATTER plan entry (issue #4).

        Expands the committed collection into candidates (bounded by MAX;
        a longer list fails the run), runs the body step once per candidate
        in collection order through the normal invocation machinery, and
        commits each candidate's delta to candidate-scoped nodes
        ``<alias>.c<k>.<leaf>``.  Returns a terminal/failed result dict, or
        ``None`` when execution continues with the next plan entry.
        Issue #23: each candidate is a branch — its effectful dispatches
        write into ``<base>/branches/cand<k>/`` and hold the candidate's
        exclusive workspace claim.
        """
        scatter = entry.scatter
        gather = self._gather_for(program, scatter)
        body = scatter.body
        alias = gather.alias_ref
        instruction_id = f"scatter.{body.step_id}"

        def cancel_pending_plan(from_idx: int, records: list[_Record]) -> None:
            records.extend(
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                )
                for pending_idx in range(from_idx, len(plan))
                if pending_idx in statement_to_task
            )

        def fail_scatter(error: str) -> dict[str, Any]:
            """Fail the run at the scatter entry (collection-level failure)."""
            records = [
                _Record(
                    event_type=EventType.FAILED,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={"error": error},
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "invocation_recorded", "id": task_id,
                        "tokens": 0, "cost": 0.0, "retries": 0,
                        "elapsed_seconds": 0.0,
                    },
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={"kind": "task_cancelled", "id": task_id},
                    store=self.store,
                ),
            ]
            cancel_pending_plan(idx + 1, records)
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": error},
                store=self.store,
            ))
            self.store.append_batch(run_id, records)
            return {
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "outputs": {},
            }

        # The scatter entry's own ledger task stays PENDING while the
        # candidates run: the strict single-in-progress ledger invariant
        # (no concurrent IN_PROGRESS tasks in a sequential run) forbids
        # overlapping it with the per-candidate tasks that carry the live
        # lifecycle.  The task starts and completes when the expansion
        # finalizes, in the entry's terminal batch below.
        ledger = self.store.task_ledger(run_id)
        task = ledger.tasks.get(task_id)
        if task is not None and task.status not in (
            TaskStatus.PENDING,
            TaskStatus.IN_PROGRESS,
        ):
            raise TaskLedgerError(
                f"task {task_id} for non-terminal step"
                f" {instruction_id} is {task.status.value};"
                " cannot resume"
            )

        collection_value = values.get(scatter.collection_ref)
        if not isinstance(collection_value, list):
            return fail_scatter(
                f"SCATTER collection {scatter.collection_ref} is"
                f" {type(collection_value).__name__} at runtime;"
                " it must be a list"
            )
        if len(collection_value) > scatter.max_count:
            return fail_scatter(
                f"SCATTER collection {scatter.collection_ref} has"
                f" {len(collection_value)} items, exceeding MAX"
                f" {scatter.max_count}"
            )
        count = len(collection_value)

        candidate_tasks = self._candidate_task_ids(run_id, body, count)

        # Candidates already committed before a crash: their invocation ids
        # are "inv-<K>.cand<k>" and their scoped nodes replayed into values.
        scatter_invocation = f"inv-{idx + 1}"
        prior_success: dict[int, dict[str, Any]] = {}
        for event in self.store.events(run_id):
            if event.event_type is not EventType.SUCCEEDED:
                continue
            match = _CANDIDATE_INVOCATION_RE.fullmatch(event.invocation_id)
            if match is None or int(match.group(1)) != idx + 1:
                continue
            k = int(match.group(2))
            leaf_values: dict[str, Any] = {}
            for target in body.targets:
                node = candidate_node_id(
                    alias, k, target.split(".")[-1]
                )
                if node not in values:
                    return fail_scatter(
                        f"candidate {k} committed a SUCCEEDED event but"
                        f" node {node} is missing from the replayed state"
                    )
                leaf_values[target] = values[node]
            prior_success[k] = leaf_values

        candidate_values: dict[int, dict[str, Any]] = {}
        loser_errors: dict[int, str] = {}
        winner: int | None = None
        for k in range(1, count + 1):
            if k in prior_success:
                candidate_values[k] = prior_success[k]
                if gather.mode == "any" and winner is None:
                    # Deterministic first-success rule (issue #27): the
                    # lowest candidate index with a committed success.
                    winner = k
                continue
            if gather.mode == "any" and winner is not None:
                records: list[_Record] = []
                self._cancel_task_if_unsettled(
                    run_id, candidate_tasks[k], records
                )
                if records:
                    self.store.append_batch(run_id, records)
                continue
            cand_task_id = candidate_tasks[k]
            outcome = self._execute_scatter_candidate(
                run_id=run_id,
                scatter=scatter,
                alias=alias,
                candidate=k,
                invocation_id=candidate_invocation_id(scatter_invocation, k),
                task_id=cand_task_id,
                item_value=collection_value[k - 1],
                values=values,
                scatter_idx=idx,
                crash_hook=crash_hook,
                gate=gate,
                claims=claims,
                branch_root=branch_root,
            )
            status, payload_outcome, validation = outcome
            if status == "succeeded":
                candidate_values[k] = payload_outcome
                if gather.mode == "any":
                    winner = k
                    records = []
                    for rest in range(k + 1, count + 1):
                        self._cancel_task_if_unsettled(
                            run_id, candidate_tasks[rest], records
                        )
                    if records:
                        self.store.append_batch(run_id, records)
                    break
                continue
            # Candidate failure.
            if gather.mode in ("all", "ranked"):
                return self._fail_scatter_candidate(
                    run_id=run_id,
                    plan=plan,
                    statement_to_task=statement_to_task,
                    idx=idx,
                    scatter_task_id=task_id,
                    body=body,
                    candidate_tasks=candidate_tasks,
                    candidate=k,
                    invocation_id=candidate_invocation_id(
                        scatter_invocation, k
                    ),
                    error=payload_outcome,
                    validation=validation,
                )
            # USING any: the candidate is a loser — cancelled and recorded,
            # never a FAILED event (audit truthfulness: a run that may yet
            # succeed cannot carry FAILED events).
            loser_errors[k] = payload_outcome
            records = []
            self._cancel_task_if_unsettled(
                run_id,
                cand_task_id,
                records,
                reason=f"[candidate {k}] {payload_outcome}",
            )
            if records:
                self.store.append_batch(run_id, records)

        if gather.mode == "any" and winner is None:
            return self._fail_scatter_all_losers(
                run_id=run_id,
                plan=plan,
                statement_to_task=statement_to_task,
                idx=idx,
                scatter_invocation=scatter_invocation,
                scatter_task_id=task_id,
                body=body,
                candidate_tasks=candidate_tasks,
                loser_errors=loser_errors,
            )

        if crash_hook is not None:
            # Crash window after the fan-out completed, before the scatter
            # entry's own terminal batch: resume re-derives the expansion
            # from the committed candidate events without re-running any
            # committed candidate (at-least-once per candidate).
            crash_hook(idx)

        evidence = (
            f"SCATTER {scatter.item_ref} IN {scatter.collection_ref}:"
            f" expanded {count} candidate(s)"
        )
        if gather.mode == "any" and winner is not None:
            evidence += f"; first success at candidate {winner}"
        if loser_errors:
            evidence += (
                f"; losers recorded: {len(loser_errors)}"
            )
        expected_sv = self.store._current_state_version(run_id)
        # Terminal batch: the entry's compressed task lifecycle (start
        # after the candidates settled — see the note at the top) plus the
        # empty-delta SUCCEEDED that marks the entry terminal for resume.
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={"kind": "task_started", "id": task_id},
                store=self.store,
            ),
            _Record(
                event_type=EventType.INVOCATION_READY,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={
                    "command": (
                        f"SCATTER {scatter.item_ref} IN"
                        f" {scatter.collection_ref} MAX"
                        f" {scatter.max_count}"
                    )
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.VALIDATION_PASSED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={},
                store=self.store,
            ),
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                expected_state_version=expected_sv,
                payload={
                    "delta": StateDelta(),
                    "scatter": {
                        "item_ref": scatter.item_ref,
                        "collection_ref": scatter.collection_ref,
                        "max": scatter.max_count,
                        "alias": alias,
                        "mode": gather.mode,
                        "candidates": count,
                        "winner": winner,
                        "losers": {
                            str(k): loser_errors[k] for k in sorted(loser_errors)
                        },
                    },
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "invocation_recorded", "id": task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "task_completed", "id": task_id,
                    "evidence": evidence,
                },
                store=self.store,
            ),
        ])
        return None

    def _execute_scatter_candidate(
        self,
        *,
        run_id: str,
        scatter: Scatter,
        alias: str,
        candidate: int,
        invocation_id: str,
        task_id: str,
        item_value: Any,
        values: dict[str, Any],
        scatter_idx: int,
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None" = None,
        branch_root: str | None = None,
    ) -> tuple[str, Any, Any]:
        """Run one per-candidate body step through the invocation machinery.

        Emits the full candidate lifecycle (READY, DISPATCHED,
        RESULT_RECEIVED, VALIDATION_PASSED, the atomic SUCCEEDED batch with
        the candidate-scoped delta).  Failures return
        ``("failed", error, validation_payload)`` without emitting failure
        events — the caller decides the mode-specific failure recording.
        Issue #23: the candidate is a branch — its effectful dispatch
        writes into its isolated workspace subdirectory and holds the
        candidate's exclusive claim for the handler's duration.
        """
        body = scatter.body
        instruction_id = body.step_id
        ledger = self.store.task_ledger(run_id)
        task = ledger.tasks.get(task_id)
        prior_types: set[EventType] = set()
        if task is not None and task.status is TaskStatus.IN_PROGRESS:
            prior_types = {
                event.event_type
                for event in self.store.events(run_id)
                if event.invocation_id == invocation_id
            }
        elif task is not None and task.status is not TaskStatus.PENDING:
            raise TaskLedgerError(
                f"candidate task {task_id} for {instruction_id}"
                f" [candidate {candidate}] is {task.status.value};"
                " cannot resume"
            )
        if EventType.INVOCATION_READY not in prior_types:
            if task is not None and task.status is TaskStatus.IN_PROGRESS:
                self.store.append(
                    run_id,
                    EventType.INVOCATION_READY,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={"command": body.command},
                )
            else:
                ledger.start_task(task_id)
                self.store.append_batch(run_id, [
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={"kind": "task_started", "id": task_id},
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.INVOCATION_READY,
                        instruction_id=instruction_id,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={"command": body.command},
                        store=self.store,
                    ),
                ])

        candidate_state = dict(values)
        candidate_state[scatter.item_ref] = item_value
        try:
            resolved_kwargs: dict[str, Any] = {}
            for arg in body.args:
                self._reject_unresolved_refs(arg.value, candidate_state)
                if isinstance(arg.value, str) and arg.value in candidate_state:
                    resolved_kwargs[arg.name] = candidate_state[arg.value]
                elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                    resolved_kwargs[arg.name] = self._resolve_kb_ref(arg.value)
                elif isinstance(arg.value, list):
                    resolved_kwargs[arg.name] = [
                        candidate_state[item]
                        if isinstance(item, str) and item in candidate_state
                        else self._resolve_kb_ref(item)
                        if isinstance(item, str) and item.startswith("KB.")
                        else item
                        for item in arg.value
                    ]
                else:
                    resolved_kwargs[arg.name] = arg.value
        except Exception as exc:
            return ("failed", str(exc), None)

        # Issue #23: the candidate is a branch — its effectful dispatch
        # writes into its isolated workspace subdirectory and holds the
        # candidate's exclusive workspace claim for the handler's
        # duration (annotated on the DISPATCHED payload).
        dispatch_root = branch_root or self.workspace_root
        branch_claim_held: str | None = None
        if (
            dispatch_root is not None
            and body.command in _effectful_commands()
        ):
            resolved_kwargs["_workspace_root"] = branch_workspace_dir(
                dispatch_root, f"cand{candidate}"
            )
            if claims is not None:
                candidate_claim = f"workspace:{run_id}:{invocation_id}"
                if claims.claim(candidate_claim, f"{run_id}:{invocation_id}"):
                    branch_claim_held = candidate_claim
                else:
                    return (
                        "failed",
                        f"resource claim failed: {candidate_claim} is held"
                        f" by {claims.holder(candidate_claim)!r}",
                        None,
                    )

        if EventType.INVOCATION_DISPATCHED not in prior_types:
            dispatched_payload: dict[str, Any] = {
                "args": resolved_kwargs,
                "idempotency_key": f"{run_id}:{invocation_id}",
                "candidate": candidate,
            }
            if branch_claim_held is not None:
                dispatched_payload["resource_claims"] = [branch_claim_held]
            self.store.append(
                run_id,
                EventType.INVOCATION_DISPATCHED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload=dispatched_payload,
            )

        try:
            result = self._execute_worker_call(body.command, resolved_kwargs, gate)
        except Exception as exc:
            return ("failed", str(exc), None)
        finally:
            if branch_claim_held is not None:
                claims.release(
                    branch_claim_held, f"{run_id}:{invocation_id}"
                )

        self.store.append(
            run_id,
            EventType.RESULT_RECEIVED,
            instruction_id=instruction_id,
            invocation_id=invocation_id,
            task_id=task_id,
            payload={"result": result},
        )

        target_values, validation_error = map_results_to_targets(
            body.targets, result
        )
        if validation_error is not None:
            return ("failed", validation_error, None)

        validation_payload: dict[str, Any] | None = None
        if body.done is not None:
            passed, detail = evaluate_done_predicate(body.done, target_values)
            if not passed:
                validation_payload = {
                    "step_id": body.step_id,
                    "candidate": candidate,
                    "predicate": {
                        "op": body.done.op,
                        "ref": body.done.ref,
                        "value": body.done.value,
                    },
                    "detail": detail,
                }
                return (
                    "failed",
                    f"DONE predicate failed for {body.step_id}"
                    f" [candidate {candidate}]: {detail}",
                    validation_payload,
                )

        add_nodes = [
            {
                "id": candidate_node_id(
                    alias, candidate, target.split(".")[-1]
                ),
                "value": target_values[target],
            }
            for target in body.targets
        ]
        for node in add_nodes:
            values[node["id"]] = node["value"]

        if crash_hook is not None:
            # Crash window before the candidate's terminal batch: resume
            # re-executes exactly this candidate (at-least-once; the
            # DISPATCHED idempotency key is the dedup contract).
            crash_hook(scatter_idx)

        self.store.append(
            run_id,
            EventType.VALIDATION_PASSED,
            instruction_id=instruction_id,
            invocation_id=invocation_id,
            task_id=task_id,
            payload={},
        )

        delta = StateDelta(add_nodes=tuple(add_nodes))
        expected_sv = self.store._current_state_version(run_id)
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                expected_state_version=expected_sv,
                payload={
                    "delta": delta,
                    "candidate": candidate,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "invocation_recorded", "id": task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "task_completed", "id": task_id,
                    "evidence": (
                        f"{body.command} ->"
                        f" {[node['id'] for node in add_nodes]}"
                        f" [candidate {candidate}]"
                    ),
                },
                store=self.store,
            ),
        ])
        return ("succeeded", dict(target_values), None)

    def _fail_scatter_candidate(
        self,
        *,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        idx: int,
        scatter_task_id: str,
        body: Invocation,
        candidate_tasks: dict[int, str],
        candidate: int,
        invocation_id: str,
        error: str,
        validation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Fail the run atomically on a candidate failure (all/ranked)."""
        records: list[_Record] = []
        if validation is not None:
            records.append(_Record(
                event_type=EventType.VALIDATION_FAILED,
                instruction_id=body.step_id,
                invocation_id=invocation_id,
                task_id=candidate_tasks[candidate],
                payload=validation,
                store=self.store,
            ))
        records.append(_Record(
            event_type=EventType.FAILED,
            instruction_id=body.step_id,
            invocation_id=invocation_id,
            task_id=candidate_tasks[candidate],
            payload={"error": error},
            store=self.store,
        ))
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=candidate_tasks[candidate],
            payload={
                "kind": "invocation_recorded",
                "id": candidate_tasks[candidate],
                "tokens": 0, "cost": 0.0, "retries": 0,
                "elapsed_seconds": 0.0,
            },
            store=self.store,
        ))
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=candidate_tasks[candidate],
            payload={"kind": "task_cancelled", "id": candidate_tasks[candidate]},
            store=self.store,
        ))
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=scatter_task_id,
            payload={"kind": "task_cancelled", "id": scatter_task_id},
            store=self.store,
        ))
        for k in range(candidate + 1, len(candidate_tasks) + 1):
            self._cancel_task_if_unsettled(
                run_id, candidate_tasks[k], records
            )
        for pending_idx in range(idx + 1, len(plan)):
            if pending_idx in statement_to_task:
                records.append(_Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                ))
        records.append(_Record(
            event_type=EventType.RUN_FINISHED,
            payload={
                "status": "failed",
                "error": f"candidate {candidate} failed: {error}",
            },
            store=self.store,
        ))
        self.store.append_batch(run_id, records)
        return {
            "run_id": run_id,
            "status": "failed",
            "error": f"candidate {candidate} failed: {error}",
            "outputs": {},
        }

    def _fail_scatter_all_losers(
        self,
        *,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        idx: int,
        scatter_invocation: str,
        scatter_task_id: str,
        body: Invocation,
        candidate_tasks: dict[int, str],
        loser_errors: dict[int, str],
    ) -> dict[str, Any]:
        """Fail the run when every candidate lost under USING any.

        Losers carried no FAILED events while the run could still succeed
        (audit truthfulness: a succeeding run may not contain FAILED
        events); now that the join cannot succeed, each loser records its
        FAILED event and the run finishes failed through the standard
        shape.
        """
        records: list[_Record] = []
        for k in sorted(loser_errors):
            cand_task_id = candidate_tasks[k]
            records.append(_Record(
                event_type=EventType.FAILED,
                instruction_id=body.step_id,
                invocation_id=candidate_invocation_id(scatter_invocation, k),
                task_id=cand_task_id,
                payload={"error": loser_errors[k]},
                store=self.store,
            ))
            records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=cand_task_id,
                payload={
                    "kind": "invocation_recorded", "id": cand_task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ))
        records.append(_Record(
            event_type=EventType.TASK_UPDATED,
            task_id=scatter_task_id,
            payload={"kind": "task_cancelled", "id": scatter_task_id},
            store=self.store,
        ))
        for pending_idx in range(idx + 1, len(plan)):
            if pending_idx in statement_to_task:
                records.append(_Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                ))
        if loser_errors:
            error = (
                f"USING any gather failed: all {len(loser_errors)}"
                f" candidate(s) failed; last error:"
                f" {loser_errors[max(loser_errors)]}"
            )
        else:
            error = (
                "USING any gather failed: the collection produced no"
                " candidates to select from"
            )
        records.append(_Record(
            event_type=EventType.RUN_FINISHED,
            payload={"status": "failed", "error": error},
            store=self.store,
        ))
        self.store.append_batch(run_id, records)
        return {
            "run_id": run_id,
            "status": "failed",
            "error": error,
            "outputs": {},
        }

    def _candidate_state_values(
        self,
        values: Mapping[str, Any],
        alias: str,
        body: Invocation,
        candidate: int,
    ) -> dict[str, Any] | None:
        """One candidate's committed target values, or None if incomplete."""
        leaf_values: dict[str, Any] = {}
        for target in body.targets:
            node = candidate_node_id(alias, candidate, target.split(".")[-1])
            if node not in values:
                return None
            leaf_values[target] = values[node]
        return leaf_values

    def _execute_gather_entry(
        self,
        program: Program,
        run_id: str,
        entry: _PlanEntry,
        idx: int,
        invocation_id: str,
        task_id: str,
        values: dict[str, Any],
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        crash_hook: "Callable[[int], None] | None",
        gate: "BudgetGate | None",
        claims: "ResourceLedger | None" = None,
        branch_root: str | None = None,
    ) -> dict[str, Any] | None:
        """Execute one GATHER plan entry (issue #4): the explicit join.

        Reads the preceding scatter's expansion record and the
        candidate-scoped nodes from committed state, evaluates the join
        rule, and commits the alias node with the selection evidence in
        the task's completion.  ``all`` joins every candidate's value in
        candidate order; ``any`` takes the first candidate-order success;
        ``ranked`` executes the judge step once per candidate (item and
        body-target bindings) and commits the max score, ties breaking to
        the lowest candidate index.  Issue #23: when the body produced
        ART.* artifacts inside branch workspaces, the explicit artifact
        merge integrates the disjoint paths into the parent workspace and
        records the accounting in the join's SUCCEEDED payload; a
        cross-branch path collision fails the run atomically.
        """
        gather = entry.gather
        scatter = self._scatter_for(program, gather)
        body = scatter.body
        alias = gather.alias_ref
        instruction_id = f"gather.{gather.body_step_id}"
        scatter_invocation = f"inv-{idx}"

        def fail_gather(error: str) -> dict[str, Any]:
            records = [
                _Record(
                    event_type=EventType.FAILED,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={"error": error},
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "invocation_recorded", "id": task_id,
                        "tokens": 0, "cost": 0.0, "retries": 0,
                        "elapsed_seconds": 0.0,
                    },
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={"kind": "task_cancelled", "id": task_id},
                    store=self.store,
                ),
            ]
            for pending_idx in range(idx + 1, len(plan)):
                if pending_idx in statement_to_task:
                    records.append(_Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=statement_to_task[pending_idx],
                        payload={
                            "kind": "task_cancelled",
                            "id": statement_to_task[pending_idx],
                        },
                        store=self.store,
                    ))
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": error},
                store=self.store,
            ))
            self.store.append_batch(run_id, records)
            return {
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "outputs": {},
            }

        ledger = self.store.task_ledger(run_id)
        task = ledger.tasks.get(task_id)
        prior_types: set[EventType] = set()
        if task is not None and task.status is TaskStatus.IN_PROGRESS:
            prior_types = {
                event.event_type
                for event in self.store.events(run_id)
                if event.invocation_id == invocation_id
            }
        elif task is not None and task.status is not TaskStatus.PENDING:
            raise TaskLedgerError(
                f"task {task_id} for non-terminal step"
                f" {instruction_id} is {task.status.value};"
                " cannot resume"
            )
        if EventType.INVOCATION_READY not in prior_types:
            if task is not None and task.status is TaskStatus.IN_PROGRESS:
                self.store.append(
                    run_id,
                    EventType.INVOCATION_READY,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={
                        "command": (
                            f"GATHER {gather.body_step_id} AS {alias}"
                            f" USING {gather.mode}"
                        )
                    },
                )
            else:
                ledger.start_task(task_id)
                self.store.append_batch(run_id, [
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={"kind": "task_started", "id": task_id},
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.INVOCATION_READY,
                        instruction_id=instruction_id,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "command": (
                                f"GATHER {gather.body_step_id} AS {alias}"
                                f" USING {gather.mode}"
                            )
                        },
                        store=self.store,
                    ),
                ])

        # The scatter's expansion record is the single source of truth for
        # the candidate count, the any-winner and the loser errors — read
        # from the committed event, so a fresh run and a resume derive the
        # join identically.
        scatter_record: dict[str, Any] | None = None
        for event in self.store.events(run_id):
            if (
                event.event_type is EventType.SUCCEEDED
                and event.invocation_id == scatter_invocation
                and isinstance(event.payload, dict)
                and isinstance(event.payload.get("scatter"), dict)
            ):
                scatter_record = event.payload["scatter"]
        if scatter_record is None:
            return fail_gather(
                f"GATHER of {gather.body_step_id} found no expansion record"
                f" for {scatter_invocation}: the scatter entry has not"
                " committed"
            )
        count = int(scatter_record.get("candidates", 0))
        collection_value = values.get(scatter.collection_ref)
        if not isinstance(collection_value, list) or len(collection_value) != count:
            return fail_gather(
                f"GATHER of {gather.body_step_id}: collection"
                f" {scatter.collection_ref} disagrees with the scatter's"
                f" expansion record ({count} candidates)"
            )

        selection: dict[str, Any] = {"mode": gather.mode, "candidates": count}
        evidence: str
        winner: int | None = None
        alias_value: Any

        if gather.mode == "all":
            joined: list[Any] = []
            for k in range(1, count + 1):
                leaf_values = self._candidate_state_values(
                    values, alias, body, k
                )
                if leaf_values is None:
                    return fail_gather(
                        f"GATHER USING all: candidate {k} has no committed"
                        f" result nodes under {alias}.c{k}"
                    )
                if len(body.targets) == 1:
                    joined.append(leaf_values[body.targets[0]])
                else:
                    joined.append(
                        {
                            target.split(".")[-1]: value
                            for target, value in leaf_values.items()
                        }
                    )
            alias_value = joined
            evidence = (
                f"join all: committed {alias} from {count} candidate(s)"
                " in collection order"
            )

        elif gather.mode == "any":
            winner = scatter_record.get("winner")
            if not isinstance(winner, int) or not (
                1 <= winner <= count
            ):
                return fail_gather(
                    f"GATHER USING any: the scatter recorded no winning"
                    " candidate"
                )
            leaf_values = self._candidate_state_values(
                values, alias, body, winner
            )
            if leaf_values is None:
                return fail_gather(
                    f"GATHER USING any: winner candidate {winner} has no"
                    f" committed result nodes under {alias}.c{winner}"
                )
            if len(body.targets) == 1:
                alias_value = leaf_values[body.targets[0]]
            else:
                alias_value = {
                    target.split(".")[-1]: value
                    for target, value in leaf_values.items()
                }
            losers = scatter_record.get("losers", {})
            selection["winner"] = winner
            selection["losers"] = losers
            if losers:
                evidence = (
                    f"join any: winner candidate {winner}; losers recorded"
                    f" (cancelled, not committed): {losers}"
                )
            else:
                evidence = (
                    f"join any: winner candidate {winner}; no losers"
                )

        else:  # ranked
            judge = gather.judge
            if judge is None:
                return fail_gather(
                    "GATHER USING ranked requires a JUDGE step"
                )
            if judge.done is not None:
                return fail_gather(
                    "GATHER judge steps do not support DONE predicates"
                )
            scores: dict[int, float] = {}
            for k in range(1, count + 1):
                leaf_values = self._candidate_state_values(
                    values, alias, body, k
                )
                if leaf_values is None:
                    return fail_gather(
                        f"GATHER USING ranked: candidate {k} has no"
                        f" committed result nodes under {alias}.c{k}"
                    )
                judge_state = dict(values)
                judge_state[scatter.item_ref] = collection_value[k - 1]
                judge_state.update(leaf_values)
                try:
                    resolved_kwargs: dict[str, Any] = {}
                    for arg in judge.args:
                        self._reject_unresolved_refs(arg.value, judge_state)
                        if isinstance(arg.value, str) and (
                            arg.value in judge_state
                        ):
                            resolved_kwargs[arg.name] = judge_state[arg.value]
                        elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                            resolved_kwargs[arg.name] = self._resolve_kb_ref(
                                arg.value
                            )
                        elif isinstance(arg.value, list):
                            resolved_kwargs[arg.name] = [
                                judge_state[item]
                                if isinstance(item, str) and item in judge_state
                                else self._resolve_kb_ref(item)
                                if isinstance(item, str) and item.startswith("KB.")
                                else item
                                for item in arg.value
                            ]
                        else:
                            resolved_kwargs[arg.name] = arg.value
                    result = self._execute_worker_call(
                        judge.command, resolved_kwargs, gate
                    )
                    scores[k] = judge_score(result)
                except Exception as exc:
                    return fail_gather(
                        f"GATHER judge for candidate {k} failed: {exc}"
                    )
            best = max(scores.values())
            winner = min(
                k for k, score in scores.items() if score == best
            )
            leaf_values = self._candidate_state_values(
                values, alias, body, winner
            )
            if len(body.targets) == 1:
                alias_value = leaf_values[body.targets[0]]
            else:
                alias_value = {
                    target.split(".")[-1]: value
                    for target, value in leaf_values.items()
                }
            selection["winner"] = winner
            selection["scores"] = {str(k): scores[k] for k in sorted(scores)}
            evidence = (
                f"join ranked: winner candidate {winner}"
                f" (score {scores[winner]}); scores:"
                f" {selection['scores']}; judge {judge.command}"
            )

        if crash_hook is not None:
            # Crash window after the join is decided, before the alias
            # commits: resume re-derives the join deterministically.
            crash_hook(idx)

        # Issue #23: explicit artifact merge for branch-produced ART.*
        # nodes (workspace-gated, so pre-#23 programs without a declared
        # workspace behave exactly as before).
        merge_payload: dict[str, Any] | None = None
        merge_base = branch_root or self.workspace_root
        if merge_base is not None and any(
            target.startswith("ART.") for target in body.targets
        ):
            merge_artifacts: list[dict[str, Any]] = []
            merge_dirs: dict[str, str | None] = {}
            for k in range(1, count + 1):
                merge_dirs[f"cand{k}"] = branch_workspace_dir(
                    merge_base, f"cand{k}"
                )
                for target in body.targets:
                    if not target.startswith("ART."):
                        continue
                    node = candidate_node_id(alias, k, target.split(".")[-1])
                    node_value = values.get(node)
                    if isinstance(node_value, str):
                        merge_artifacts.append({
                            "branch": f"cand{k}",
                            "node": node,
                            "path": node_value,
                        })
            merged, merge_error = self._merge_branch_artifacts(
                run_id,
                f"{run_id}:{invocation_id}",
                claims,
                merge_artifacts,
                merge_dirs,
            )
            if merge_error is not None:
                return fail_gather(merge_error)
            merge_payload = {"artifacts": merged}

        self.store.append(
            run_id,
            EventType.VALIDATION_PASSED,
            instruction_id=instruction_id,
            invocation_id=invocation_id,
            task_id=task_id,
            payload={},
        )

        expected_sv = self.store._current_state_version(run_id)
        delta = StateDelta(add_nodes=({"id": alias, "value": alias_value},))
        values[alias] = alias_value
        gather_succeeded_payload: dict[str, Any] = {
            "delta": delta,
            "gather": selection,
        }
        if merge_payload is not None:
            gather_succeeded_payload["merge"] = merge_payload
        self.store.append_batch(run_id, [
            _Record(
                event_type=EventType.SUCCEEDED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                expected_state_version=expected_sv,
                payload=gather_succeeded_payload,
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "invocation_recorded", "id": task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ),
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "task_completed", "id": task_id,
                    "evidence": evidence,
                },
                store=self.store,
            ),
        ])
        return None

    def execute(
        self,
        program: Program,
        run_id: str = "run-1",
        *,
        crash_hook: "Callable[[int], None] | None" = None,
        max_workers: int = 1,
        budget: "ExecutionBudget | None" = None,
    ) -> dict[str, Any]:
        """Execute one program run.

        ``max_workers`` (issue #21) selects the execution strategy: the
        default ``1`` keeps the historical blocking sequential loop
        untouched; any value ``> 1`` dispatches dependency-free ready
        invocations concurrently on a thread pool of that size while
        every commit stays on the single-writer atomic batch path (see
        :meth:`_drive_plan_concurrent`).  CALL child runs always execute
        their own plans sequentially.

        ``budget`` (issue #22) installs an :class:`ExecutionBudget`
        shared across the run's whole execution tree: it caps active
        workers and child step executions (one semaphore), enforces a
        global and per-invocation deadline, and caps child-run nesting
        depth.  A budget only caps — it never enables concurrency on
        its own — and ``None`` (the default) keeps the historical
        behavior unchanged.
        """
        if not isinstance(max_workers, int) or isinstance(max_workers, bool):
            raise ValueError(
                f"max_workers must be an integer, got {max_workers!r}"
            )
        if max_workers < 1:
            raise ValueError(
                f"max_workers must be >= 1, got {max_workers}"
            )
        if budget is not None and not isinstance(budget, ExecutionBudget):
            raise TypeError(
                f"budget must be an ExecutionBudget or None,"
                f" got {type(budget).__name__}"
            )
        gate = BudgetGate(budget) if budget is not None else None
        # Issue #23: one run-scoped resource ledger shared across the
        # run's whole execution tree (branch workspace claims, merge
        # claims).
        claims = ResourceLedger()
        return self._execute_program(
            program,
            run_id,
            crash_hook=crash_hook,
            max_workers=max_workers,
            gate=gate,
            claims=claims,
        )

    def _execute_program(
        self,
        program: Program,
        run_id: str,
        *,
        crash_hook: "Callable[[int], None] | None" = None,
        child_of: str | None = None,
        call_name: str | None = None,
        initial_values: Mapping[str, Any] | None = None,
        max_workers: int = 1,
        gate: "BudgetGate | None" = None,
        claims: "ResourceLedger | None" = None,
        branch_workspace: str | None = None,
        branch_claim: str | None = None,
    ) -> dict[str, Any]:
        """Start and drive one run (issue #20 parameterized start).

        ``execute`` is the top-level entry point.  A CALL's child run
        reuses this same machinery with ``child_of``/``call_name`` set
        (recorded in the run's metadata and RUN_STARTED payload for
        lineage) and ``initial_values`` seeding the child's isolated
        state namespace from the resolved CALL arguments.

        Issue #21: ``max_workers > 1`` marks the run's metadata
        ``concurrent`` (the flag the task-ledger replay reads to permit
        multiple IN_PROGRESS tasks) and drives the plan through the
        concurrent frontier instead of the sequential loop.

        Issue #23: ``claims`` is the run tree's shared resource ledger
        and ``branch_workspace``/``branch_claim`` carry the enclosing
        branch's isolated workspace root and claim resource into child
        runs (a PAR branch CALLing a protocol keeps the branch sandbox).
        """
        validate_program(
            program,
            known_commands=self.worker.commands,
            protocols_dir=self.protocols_dir,
        )
        if self.memory is None and _uses_kb_refs(program):
            raise ValueError(
                "program uses KB.* references but no knowledge base was"
                " provided: construct SequentialCoordinator with"
                " memory=KnowledgeBase(path)"
            )

        program_version = f"{program.name}@{program.version}"
        registry_digest = _builtin_registry_digest()
        metadata: dict[str, Any] = {
            "program": program.name,
            "registry_digest": registry_digest,
        }
        started_payload: dict[str, Any] = {
            "program": program.name,
            "version": program.version,
            "registry_digest": registry_digest,
        }
        concurrent_run = (
            max_workers > 1
            and not _uses_scatter(program)
            and not _uses_par(program)
            and not _uses_delegate(program)
        )
        if concurrent_run:
            metadata["concurrent"] = True
            metadata["max_workers"] = max_workers
        elif max_workers > 1:
            # Issue #4: scatter programs always drive the sequential plan
            # loop (candidate fan-out semantics, loser cancellation and the
            # resume invariants are defined over candidate order); the
            # requested width is recorded but does not switch the plan
            # frontier on.  Issue #24: PAR programs likewise drive the
            # sequential plan loop — a PAR entry brings its own bounded
            # branch pool.  Issue #25: delegate programs drive the
            # sequential loop for the same reason — a delegate entry brings
            # its own authoring + child-run machinery.
            metadata["max_workers"] = max_workers
        if child_of is not None:
            metadata["child_of"] = child_of
            metadata["call"] = call_name
            started_payload["child_of"] = child_of
            started_payload["call"] = call_name
        self.store.create_run(run_id, program_version, metadata=metadata)

        self.store.append(
            run_id,
            EventType.RUN_STARTED,
            payload=started_payload,
        )

        values: dict[str, Any] = {}
        for decl in program.declarations:
            values[decl.ref] = decl.value
        if initial_values:
            values.update(initial_values)

        # Issue #20: flatten caller invocations and CALL statements into
        # one sequential plan.  Protocol steps execute in their own
        # isolated child run; a CALL entry drives the child and adopts
        # its RETURN refs (see _execute_call).
        plan: list[_PlanEntry] = self._build_plan(program)

        statement_to_task = self._create_plan_tasks(run_id, plan)

        if concurrent_run:
            return self._drive_plan_concurrent(
                program,
                run_id,
                plan,
                values,
                statement_to_task,
                crash_hook=crash_hook,
                max_workers=max_workers,
                gate=gate,
            )

        return self._drive_plan(
            program,
            run_id,
            plan,
            values,
            statement_to_task,
            start_idx=0,
            crash_hook=crash_hook,
            gate=gate,
            claims=claims,
            branch_root=branch_workspace,
            branch_claim=branch_claim,
        )

    def _resume_existing_run(
        self,
        program: Program,
        run_id: str,
        *,
        initial_values: Mapping[str, Any] | None = None,
        gate: "BudgetGate | None" = None,
        claims: "ResourceLedger | None" = None,
        branch_workspace: str | None = None,
        branch_claim: str | None = None,
    ) -> dict[str, Any]:
        """Continue a non-terminal run (issue #10 core, shared with #20).

        Rebuilds run state (declarations — overridden by
        ``initial_values`` for child runs' resolved CALL inputs — then
        committed SUCCEEDED deltas in seq order), verifies the
        SUCCEEDED-invocation prefix invariant, ensures the plan's tasks
        exist with the canonical texts, and drives the remaining plan
        through :meth:`_drive_plan`.  Used by ``tikhon.resume.resume_run``
        for a crashed parent and by ``_execute_call`` to re-drive a
        non-terminal child (at-least-once; the DISPATCHED idempotency key
        is the dedup contract for effectful workers).
        """
        events = self.store.events(run_id)

        values: dict[str, Any] = {}
        for decl in program.declarations:
            values[decl.ref] = decl.value
        if initial_values:
            values.update(initial_values)
        # INPUT declarations seed the mapping exactly like a fresh start;
        # committed SUCCEEDED deltas then replay in seq order (add/revise
        # write, retire pops) so the reconstruction matches the values the
        # coordinator held at the crash point — including declarations no
        # step ever targeted and refs retired by a REVISE/RETIRE correction.
        self._apply_committed_deltas(values, events)

        plan = self._build_plan(program)

        # -- find the first non-terminal step ------------------------------
        # Invocation ids are positional (inv-1..inv-N in plan order), so a
        # step is terminal exactly when its invocation id carries a
        # SUCCEEDED event.  Dispatch alone never implies success.
        # Issue #21: a concurrent run commits SUCCEEDED events in
        # completion order, so its terminal set is generally NOT a
        # prefix; such runs validate the set against the plan instead
        # and re-drive every remaining entry through the frontier.
        concurrent_run = self.store._run_allows_concurrent(run_id)
        succeeded_all = {
            event.invocation_id
            for event in events
            if event.event_type is EventType.SUCCEEDED and event.invocation_id
        }
        # Issue #4: per-candidate SUCCEEDED events carry composite ids
        # ("inv-<K>.cand<k>") hanging off their scatter entry's positional
        # id; they are validated against the plan's scatter entries and
        # excluded from the positional prefix invariant.  Issue #24: PAR
        # branch parent-side events carry "par<k>" invocation ids but no
        # SUCCEEDED events (branch adoptions commit under the PAR entry's
        # positional id), so par<k> ids are defensively excluded from the
        # positional set as well.
        candidate_success_ids: set[str] = set()
        positional_success_ids: set[str] = set()
        for invocation in succeeded_all:
            if _CANDIDATE_INVOCATION_RE.fullmatch(invocation):
                candidate_success_ids.add(invocation)
            elif _PAR_INVOCATION_RE.fullmatch(invocation):
                continue
            else:
                positional_success_ids.add(invocation)
        scatter_positions = {
            idx + 1
            for idx, entry in enumerate(plan)
            if entry.scatter is not None
        }
        for invocation in candidate_success_ids:
            match = _CANDIDATE_INVOCATION_RE.fullmatch(invocation)
            if int(match.group(1)) not in scatter_positions:
                raise ValueError(
                    f"run {run_id!r} has SUCCEEDED candidate invocation"
                    f" {invocation!r} but plan entry {match.group(1)} is"
                    " not a SCATTER block; impossible for the sequential"
                    " coordinator"
                )
        succeeded = positional_success_ids
        if concurrent_run:
            terminal_indices: set[int] = set()
            for inv in succeeded:
                match = re.fullmatch(r"inv-(\d+)", inv)
                if match is None or not (1 <= int(match.group(1)) <= len(plan)):
                    raise ValueError(
                        f"run {run_id!r} has SUCCEEDED invocation {inv!r}"
                        f" outside the {len(plan)}-entry plan; impossible"
                        " for the concurrent coordinator"
                    )
                terminal_indices.add(int(match.group(1)) - 1)
        else:
            start_idx = len(plan)
            for idx in range(len(plan)):
                if f"inv-{idx + 1}" not in succeeded:
                    start_idx = idx
                    break
            expected_terminal = {f"inv-{i + 1}" for i in range(start_idx)}
            if succeeded != expected_terminal:
                raise ValueError(
                    f"run {run_id!r} has a non-prefix set of SUCCEEDED"
                    f" invocations {sorted(succeeded)}; impossible for the"
                    " sequential coordinator"
                )

        # -- ensure tasks exist (W0a: crash before the creation batch) -----
        # Issue #24: PAR entries create no plan task of their own (the
        # ledger carries one task per branch, created during execution),
        # so resume aligns task ids with the plan positions that DO carry
        # static tasks — every entry except PAR blocks.  Conditional
        # entries keep their historical positional treatment (they trail
        # the plan and their tasks are created here when missing).
        ledger = self.store.task_ledger(run_id)
        task_ids = list(ledger.tasks)
        static_positions = [
            idx for idx, entry in enumerate(plan) if entry.par is None
        ]
        if len(task_ids) > len(static_positions):
            # Issue #4: tasks beyond the plan's own entries are per-candidate
            # fan-out tasks ("step.<id>: DO <command> [candidate k]") created
            # while a scatter entry executed; issue #24 adds the PAR
            # branches' per-branch tasks ("PAR branch <k>: <summary>");
            # anything else means the program does not match the run.
            scatter_body_ids = sorted(
                {
                    entry.scatter.body.step_id
                    for entry in plan
                    if entry.scatter is not None
                }
            )
            candidate_text_res = [
                re.compile(
                    rf"^{re.escape(body_id)}: DO [a-z][a-z0-9_]*"
                    rf" \[candidate \d+\]$"
                )
                for body_id in scatter_body_ids
            ]
            par_branch_text_res = [
                re.compile(
                    rf"^PAR branch \d+: (?:step\.[a-z][a-z0-9_]*: DO"
                    rf" [a-z][a-z0-9_]*|CALL protocol\.[a-z][a-z0-9_.]*)$"
                )
                for _entry in plan
                if _entry.par is not None
            ]
            for extra_id in task_ids[len(static_positions):]:
                text = ledger.tasks[extra_id].text
                if not any(
                    pattern.fullmatch(text)
                    for pattern in candidate_text_res + par_branch_text_res
                ):
                    raise ValueError(
                        f"run {run_id!r} has {len(task_ids)} tasks but the"
                        f" program plans {len(plan)} and task {extra_id!r}"
                        f" ({text!r}) is not a scatter candidate or PAR"
                        " branch task; refusing to resume a mismatched"
                        " program"
                    )
        for position, task_id in enumerate(task_ids[: len(static_positions)]):
            plan_idx = static_positions[position]
            expected_text = self._task_text(plan[plan_idx])
            if ledger.tasks[task_id].text != expected_text:
                raise ValueError(
                    f"task {task_id!r} ({ledger.tasks[task_id].text!r}) does"
                    f" not match plan step {plan_idx} ({expected_text!r});"
                    " refusing to resume with a mismatched program"
                )
        if len(task_ids) < len(static_positions):
            create_records: list[_Record] = []
            create_ledger = self.store.task_ledger(run_id)
            for plan_idx in static_positions[len(task_ids):]:
                entry = plan[plan_idx]
                task = create_ledger.create_task(
                    text=self._task_text(entry),
                    creator="coordinator",
                )
                create_records.append(_Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task.id,
                    payload={
                        "kind": "task_created", "id": task.id, "text": task.text,
                        "priority": task.priority, "parent": task.parent,
                        "dependencies": task.dependencies,
                        "creator": task.creator,
                    },
                    store=self.store,
                ))
            self.store.append_batch(run_id, create_records)
            task_ids = list(self.store.task_ledger(run_id).tasks)
        statement_to_task = {
            static_positions[position]: task_id
            for position, task_id in enumerate(task_ids[: len(static_positions)])
        }

        if concurrent_run:
            max_workers = int(
                self.store.run(run_id)["metadata"].get("max_workers") or 2
            )
            return self._drive_plan_concurrent(
                program,
                run_id,
                plan,
                values,
                statement_to_task,
                initial_terminal=frozenset(terminal_indices),
                max_workers=max_workers,
                gate=gate,
            )

        return self._drive_plan(
            program,
            run_id,
            plan,
            values,
            statement_to_task,
            start_idx=start_idx,
            gate=gate,
            claims=claims,
            branch_root=branch_workspace,
            branch_claim=branch_claim,
        )

    def _dispatch_worker_call(
        self,
        command: str,
        resolved_kwargs: dict[str, Any],
        gate: "BudgetGate | None" = None,
    ) -> Any:
        """Pool-side handler execution under the budget gate (issue #22).

        Runs on a frontier worker thread: with a gate it holds one of
        the tree's shared concurrency slots for the handler's duration
        (waiting CALL frames hold no slot — their children's step
        executions acquire their own, so a one-worker budget cannot
        deadlock a parent awaiting a child).  Per-invocation deadlines
        are enforced by the frontier's future timeouts, not here.
        """
        if gate is None:
            return self.worker.execute(command, resolved_kwargs)
        gate.acquire_slot()
        try:
            return self.worker.execute(command, resolved_kwargs)
        finally:
            gate.release_slot()

    @staticmethod
    def _frontier_wait_timeout(
        gate: "BudgetGate | None",
        in_flight: "dict[int, concurrent.futures.Future]",
        dispatched_at: Mapping[int, float],
    ) -> float | None:
        """Wait horizon: the nearest budget deadline among in-flight work."""
        if gate is None or not in_flight:
            return None
        candidates: list[float] = []
        global_remaining = gate.global_remaining()
        if global_remaining is not None:
            candidates.append(global_remaining)
        per_invocation = gate.budget.per_invocation_deadline_seconds
        if per_invocation is not None:
            now = _monotonic()
            remainders = [
                dispatched_at[idx] + per_invocation - now
                for idx in in_flight
                if idx in dispatched_at
            ]
            if remainders:
                candidates.append(max(0.0, min(remainders)))
        return min(candidates) if candidates else None

    def _execute_worker_call(
        self,
        command: str,
        resolved_kwargs: dict[str, Any],
        gate: "BudgetGate | None" = None,
    ) -> Any:
        """One sequential handler dispatch under the budget gate (issue #22).

        ``gate=None`` dispatches exactly as before.  With a gate, the
        call holds one of the tree's shared concurrency slots and a
        per-invocation deadline is checked after the handler returns —
        a running handler cannot be interrupted, so an overrunning
        result is discarded by failing the invocation (the DISPATCHED
        idempotency key keeps the at-least-once contract honest).
        """
        if gate is None:
            return self.worker.execute(command, resolved_kwargs)
        per_invocation = gate.budget.per_invocation_deadline_seconds
        started_at = _monotonic()
        gate.acquire_slot()
        try:
            result = self.worker.execute(command, resolved_kwargs)
        finally:
            gate.release_slot()
        if per_invocation is not None and (
            _monotonic() - started_at
        ) > per_invocation:
            raise BudgetDeadlineExceeded("deadline exceeded")
        return result

    def _fail_global_deadline(
        self,
        run_id: str,
        plan: list[_PlanEntry],
        statement_to_task: dict[int, str],
        from_idx: int,
    ) -> dict[str, Any]:
        """Fail a run whose global budget deadline expired (issue #22).

        The invocation that was about to dispatch carries a FAILED event
        with the recorded reason (keeping the audit's failed-status
        truthfulness invariant), every unreached task is cancelled, and
        RUN_FINISHED records ``"global deadline exceeded"`` — one atomic
        batch, mirroring :meth:`_fail_run`.
        """
        entry = plan[from_idx]
        instruction_id = (
            entry.call.protocol
            if entry.call is not None
            else (entry.invocation.step_id if entry.invocation else "")
        )
        task_id = statement_to_task.get(from_idx)
        records: list[_Record] = []
        if task_id is not None:
            records.extend([
                _Record(
                    event_type=EventType.FAILED,
                    instruction_id=instruction_id,
                    invocation_id=f"inv-{from_idx + 1}",
                    task_id=task_id,
                    payload={"error": "global deadline exceeded"},
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "invocation_recorded", "id": task_id,
                        "tokens": 0, "cost": 0.0, "retries": 0,
                        "elapsed_seconds": 0.0,
                    },
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={"kind": "task_cancelled", "id": task_id},
                    store=self.store,
                ),
            ])
        records.extend(
            _Record(
                event_type=EventType.TASK_UPDATED,
                task_id=statement_to_task[pending_idx],
                payload={
                    "kind": "task_cancelled",
                    "id": statement_to_task[pending_idx],
                },
                store=self.store,
            )
            for pending_idx in range(from_idx + 1, len(plan))
            if pending_idx in statement_to_task
        )
        records.append(_Record(
            event_type=EventType.RUN_FINISHED,
            payload={"status": "failed", "error": "global deadline exceeded"},
            store=self.store,
        ))
        self.store.append_batch(run_id, records)
        return {
            "run_id": run_id,
            "status": "failed",
            "error": "global deadline exceeded",
            "outputs": {},
        }

    def _drive_plan(
        self,
        program: Program,
        run_id: str,
        plan: list[_PlanEntry],
        values: dict[str, Any],
        statement_to_task: dict[int, str],
        *,
        start_idx: int = 0,
        crash_hook: "Callable[[int], None] | None" = None,
        gate: "BudgetGate | None" = None,
        claims: "ResourceLedger | None" = None,
        branch_root: str | None = None,
        branch_claim: str | None = None,
    ) -> dict[str, Any]:
        """Drive the plan's per-invocation loop from ``start_idx`` on.

        ``start_idx > 0`` is the resume path (issue #10): every plan entry
        before it already committed a SUCCEEDED terminal event, so its
        task is COMPLETED and its deltas are already folded into
        ``values``.  The entry at ``start_idx`` may be mid-flight from
        before a crash (task IN_PROGRESS): its committed lifecycle events
        are never re-emitted, but its worker call is re-executed
        (at-least-once; the DISPATCHED idempotency key is the dedup
        contract for effectful workers).

        ``gate`` (issue #22) enforces an :class:`ExecutionBudget` at the
        dispatch boundaries: the global deadline before each dispatch
        (which is also "before a child starts" for CALL entries), the
        child-depth cap before a CALL dispatches, and a concurrency slot
        plus per-invocation deadline around each worker call.
        ``gate=None`` (the default) leaves every code path untouched.

        ``claims``/``branch_root``/``branch_claim`` (issue #23/#24) carry
        the run tree's resource ledger and the enclosing branch context:
        inside a branch, effectful dispatches write into the branch
        workspace subdirectory, hold the branch's claim for the handler's
        duration, and annotate their DISPATCHED payload with the held
        claims; a PAR entry nests its branches under the current branch
        root.
        """
        # -- batch all task-creation records --------------------------

        def finish_failed_invocation(
            idx: int,
            instruction_id: str,
            invocation_id: str,
            task_id: str,
            error: str,
            validation: dict[str, Any] | None = None,
        ) -> None:
            records = []
            if validation is not None:
                records.append(
                    _Record(
                        event_type=EventType.VALIDATION_FAILED,
                        instruction_id=instruction_id,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload=validation,
                        store=self.store,
                    )
                )
            records.append(
                _Record(
                    event_type=EventType.FAILED,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={"error": error},
                    store=self.store,
                )
            )
            records.append(
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "invocation_recorded", "id": task_id,
                        "tokens": 0, "cost": 0.0, "retries": 0,
                        "elapsed_seconds": 0.0,
                    },
                    store=self.store,
                )
            )
            records.append(
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={"kind": "task_cancelled", "id": task_id},
                    store=self.store,
                )
            )
            records.extend(
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                )
                for pending_idx in range(idx + 1, len(plan))
                # Issue #3: conditional tasks are created lazily, so an
                # unreached conditional entry may have no task to cancel.
                if pending_idx in statement_to_task
            )
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": error},
                store=self.store,
            ))
            self.store.append_batch(run_id, records)

        failed = False
        error_msg: str | None = None

        # Issue #3: conditionals anchored before the first invocation (their
        # refs can only be declared INPUT nodes) are evaluated up front.  On
        # resume every anchor before start_idx was already handled before
        # the crash and is deliberately not re-evaluated.
        anchors = self._collect_anchors(program)
        if start_idx == 0:
            anchor_result = self._run_conditionals(
                run_id,
                anchors.get(0, ()),
                values,
                plan,
                statement_to_task,
                cancel_from_idx=0,
            )
            if anchor_result is not None:
                return anchor_result

        for idx in range(start_idx, len(plan)):
            entry = plan[idx]
            statement = entry.invocation
            call = entry.call
            # Issue #4: scatter and gather entries execute through their own
            # machinery (candidate expansion / explicit join) and never fall
            # through to the plain invocation path below.  Issue #24: a PAR
            # entry executes its branches concurrently through the child-run
            # machinery and joins at its barrier.
            if (
                entry.scatter is not None
                or entry.gather is not None
                or entry.par is not None
            ):
                # Issue #22: the global deadline is checked before each
                # dispatch, mirroring the other entry kinds.
                if gate is not None and gate.global_expired():
                    return self._fail_global_deadline(
                        run_id, plan, statement_to_task, idx
                    )
                invocation_id = f"inv-{idx + 1}"
                task_id = statement_to_task.get(idx)
                if entry.scatter is not None:
                    result = self._execute_scatter_entry(
                        program,
                        run_id,
                        entry,
                        idx,
                        invocation_id,
                        task_id,
                        values,
                        plan,
                        statement_to_task,
                        crash_hook,
                        gate,
                        claims,
                        branch_root,
                    )
                elif entry.gather is not None:
                    result = self._execute_gather_entry(
                        program,
                        run_id,
                        entry,
                        idx,
                        invocation_id,
                        task_id,
                        values,
                        plan,
                        statement_to_task,
                        crash_hook,
                        gate,
                        claims,
                        branch_root,
                    )
                else:
                    result = self._execute_par_entry(
                        program,
                        run_id,
                        entry,
                        idx,
                        invocation_id,
                        values,
                        plan,
                        statement_to_task,
                        crash_hook,
                        gate,
                        claims,
                        branch_root,
                    )
                if result is not None:
                    return result
                anchor_result = self._run_conditionals(
                    run_id,
                    anchors.get(idx + 1, ()),
                    values,
                    plan,
                    statement_to_task,
                    cancel_from_idx=idx + 1,
                )
                if anchor_result is not None:
                    return anchor_result
                continue
            # Issue #20: a CALL entry's instruction id is the protocol
            # reference (the CALL statement's AST anchor); a DO step's is
            # its step id.  Both are nonempty, keeping the audit invariant.
            instruction_id = (
                call.protocol if call is not None else statement.step_id
            )
            invocation_id = f"inv-{idx + 1}"
            if entry.condition is not None:
                # Issue #3: a conditional DO invocation executes only when
                # its condition holds over the committed state; a false
                # condition skips the statement entirely — no task, no
                # events, no state change.  A fired branch creates its
                # ledger task here and then runs the exact same lifecycle
                # as an unconditional entry below.
                try:
                    fired = evaluate_condition(entry.condition, values)
                except ValueError as exc:
                    return self._fail_run(
                        run_id, plan, statement_to_task, idx, str(exc)
                    )
                if not fired:
                    continue
                task_id = statement_to_task.get(idx)
                if task_id is None:
                    task_id = self._create_single_plan_task(run_id, entry)
                    statement_to_task[idx] = task_id
            else:
                task_id = statement_to_task[idx]

            # Issue #22: the global deadline is checked before each
            # dispatch — which for a CALL entry is also "before the
            # child starts".  Exceeding it fails the run coherently
            # through the recorded global-deadline path.
            if gate is not None and gate.global_expired():
                return self._fail_global_deadline(
                    run_id, plan, statement_to_task, idx
                )

            # Issue #10: a resumed in-flight step carries pre-crash
            # lifecycle events.  Its task is already IN_PROGRESS
            # (`start_task` requires PENDING), and task_started,
            # INVOCATION_READY and INVOCATION_DISPATCHED may already be
            # committed — they are never re-emitted.  Dispatching does
            # NOT imply success: the worker call below always re-runs.
            prior_types: set[EventType] = set()
            ledger = self.store.task_ledger(run_id)
            task = ledger.tasks.get(task_id)
            if task is not None and task.status is TaskStatus.IN_PROGRESS:
                prior_types = {
                    event.event_type
                    for event in self.store.events(run_id)
                    if event.invocation_id == invocation_id
                }
            elif task is not None and task.status is not TaskStatus.PENDING:
                # Impossible state: a non-terminal step whose task is
                # neither PENDING (fresh) nor IN_PROGRESS (in flight).
                raise TaskLedgerError(
                    f"task {task_id} for non-terminal step"
                    f" {instruction_id} is {task.status.value};"
                    " cannot resume"
                )
            ready_command = (
                f"CALL {call.protocol}" if call is not None else statement.command
            )
            if EventType.INVOCATION_READY not in prior_types:
                if task is not None and task.status is TaskStatus.IN_PROGRESS:
                    # Impossible per the atomic task_started+READY batch;
                    # recorded defensively so the log stays truthful.
                    self.store.append(
                        run_id,
                        EventType.INVOCATION_READY,
                        instruction_id=instruction_id,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={"command": ready_command},
                    )
                else:
                    ledger.start_task(task_id)

                    # batch: task_started + INVOCATION_READY
                    self.store.append_batch(run_id, [
                        _Record(
                            event_type=EventType.TASK_UPDATED,
                            task_id=task_id,
                            payload={"kind": "task_started", "id": task_id},
                            store=self.store,
                        ),
                        _Record(
                            event_type=EventType.INVOCATION_READY,
                            instruction_id=instruction_id,
                            invocation_id=invocation_id,
                            task_id=task_id,
                            payload={"command": ready_command},
                            store=self.store,
                        ),
                    ])

            if call is not None:
                # Issue #20: a CALL executes an isolated child run instead
                # of expanding the protocol inline (the pre-#20 behavior).
                # The child lives in the same EventStore under the
                # deterministic id "<parent_run_id>:<invocation_id>", owns
                # its own ledger and state namespace (seeded only from the
                # explicitly passed CALL arguments), and its RETURN refs
                # are adopted onto the CALL targets on success — recorded
                # as CHILD_ADOPTED in the same atomic batch as the CALL's
                # SUCCEEDED delta.  Any non-succeeded child terminal fails
                # the parent through the standard atomic path.
                child_run_id = f"{run_id}:{invocation_id}"
                # Issue #22: the execution-tree child-depth cap is checked
                # before the child is dispatched at all.
                if gate is not None and gate.depth_exceeded(child_run_id):
                    failed = True
                    error_msg = (
                        f"child run {child_run_id} depth"
                        f" {gate.depth_of(child_run_id)} exceeds budget"
                        f" max_child_depth {gate.budget.max_child_depth}"
                    )
                    finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, error_msg
                    )
                    break
                try:
                    resolved_call_args = self._resolve_call_arguments(
                        call, values
                    )
                except Exception as exc:
                    failed = True
                    error_msg = str(exc)
                    finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, error_msg
                    )
                    break

                if EventType.INVOCATION_DISPATCHED not in prior_types:
                    self.store.append(
                        run_id,
                        EventType.INVOCATION_DISPATCHED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "args": resolved_call_args,
                            "idempotency_key": f"{run_id}:{invocation_id}",
                            "child_run_id": child_run_id,
                        },
                    )

                child_result = self._execute_call_child(
                    call,
                    resolved_call_args,
                    run_id,
                    invocation_id,
                    gate=gate,
                    claims=claims,
                    branch_workspace=branch_root,
                    branch_claim=branch_claim,
                )
                child_status = child_result.get("status", "unknown")
                if child_status != "succeeded":
                    # Failed/blocked/cancelled children never publish
                    # partial caller outputs: the parent fails at the
                    # CALL's invocation and the child stays terminal in
                    # its own history.
                    child_error = child_result.get("error")
                    failed = True
                    error_msg = (
                        f"child run {child_run_id} for {call.protocol}"
                        f" finished with status {child_status!r}; the CALL"
                        " cannot adopt its outputs"
                    )
                    if child_error:
                        error_msg = f"{error_msg}: {child_error}"
                    finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, error_msg
                    )
                    break

                if EventType.RESULT_RECEIVED not in prior_types:
                    self.store.append(
                        run_id,
                        EventType.RESULT_RECEIVED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "child_run_id": child_run_id,
                            "status": child_status,
                        },
                    )

                try:
                    adopted_nodes, adopted_map = self._adopt_child_result(
                        call, child_result
                    )
                except Exception as exc:
                    failed = True
                    error_msg = str(exc)
                    finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, error_msg
                    )
                    break

                if crash_hook is not None:
                    # Issue #10/#20: crash window after the child is
                    # terminal but before the parent adopts — resume
                    # detects the terminal child and adopts without
                    # re-executing it.
                    crash_hook(idx)

                self.store.append(
                    run_id,
                    EventType.VALIDATION_PASSED,
                    instruction_id=call.protocol,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={},
                )

                for node in adopted_nodes:
                    values[node["id"]] = node["value"]

                delta = StateDelta(add_nodes=tuple(adopted_nodes))
                expected_sv = self.store._current_state_version(run_id)

                # batch: CHILD_ADOPTED + SUCCEEDED + invocation_recorded
                # + task_completed — one atomic append so an adoption is
                # never split from its state commit (the store's
                # duplicate-SUCCEEDED guard then makes a re-adoption of
                # the same invocation impossible).
                self.store.append_batch(run_id, [
                    _Record(
                        event_type=EventType.CHILD_ADOPTED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "child_run_id": child_run_id,
                            "adopted": adopted_map,
                            "child_status": child_status,
                        },
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.SUCCEEDED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        expected_state_version=expected_sv,
                        payload={"delta": delta},
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={
                            "kind": "invocation_recorded", "id": task_id,
                            "tokens": 0, "cost": 0.0, "retries": 0,
                            "elapsed_seconds": 0.0,
                        },
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={
                            "kind": "task_completed", "id": task_id,
                            "evidence": (
                                f"CALL {call.protocol} ({child_run_id})"
                                f" -> {list(call.targets)}"
                            ),
                        },
                        store=self.store,
                    ),
                ])

                # Issue #3: conditionals anchored directly after this entry
                # in source order are evaluated over the state it just
                # committed (including the adopted values).
                anchor_result = self._run_conditionals(
                    run_id,
                    anchors.get(idx + 1, ()),
                    values,
                    plan,
                    statement_to_task,
                    cancel_from_idx=idx + 1,
                )
                if anchor_result is not None:
                    return anchor_result
                continue

            try:
                resolved_kwargs: dict[str, Any] = {}
                for arg in statement.args:
                    # Issue #7: guard first so a ref retired by an earlier
                    # step fails the invocation clearly instead of passing
                    # the raw ref string through as a literal.
                    self._reject_unresolved_refs(arg.value, values)
                    if isinstance(arg.value, str) and arg.value in values:
                        resolved_kwargs[arg.name] = values[arg.value]
                    elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                        # KB.<name> resolves from the cross-run knowledge base
                        # at dispatch time, never from run-local state.
                        resolved_kwargs[arg.name] = self._resolve_kb_ref(arg.value)
                    elif isinstance(arg.value, list):
                        # Reference-list argument ([E.a, E.b]): each listed ref
                        # resolves through the same values mapping as single
                        # refs; literal items (validation guarantees ref-shaped
                        # strings always resolve) pass through untouched.
                        resolved_kwargs[arg.name] = [
                            values[item] if isinstance(item, str) and item in values
                            else self._resolve_kb_ref(item)
                            if isinstance(item, str) and item.startswith("KB.")
                            else item
                            for item in arg.value
                        ]
                    else:
                        resolved_kwargs[arg.name] = arg.value
            except Exception as exc:
                # KB resolution errors (no memory, unknown key) fail the
                # invocation through the standard failure path.
                failed = True
                error_msg = str(exc)
                finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id, error_msg
                )
                break

            # WorkspacePolicy (issue #9) + branch isolation (issue #23):
            # effectful dispatches learn the declared workspace root so
            # handlers can sandbox their writes; inside a branch the root
            # is the branch's isolated subdirectory and the dispatch holds
            # the branch's exclusive claim for the handler's duration,
            # annotated on the DISPATCHED payload (no new event types).
            dispatch_root = branch_root or self.workspace_root
            branch_claim_held: str | None = None
            if (
                dispatch_root is not None
                and statement.command in _effectful_commands()
            ):
                resolved_kwargs["_workspace_root"] = dispatch_root
                if branch_root is not None and claims is not None:
                    branch_claim_held = branch_claim
                    owner = f"{run_id}:{invocation_id}"
                    if not claims.claim(branch_claim_held, owner):
                        failed = True
                        error_msg = (
                            f"resource claim failed: {branch_claim_held} is"
                            f" held by {claims.holder(branch_claim_held)!r}"
                        )
                        finish_failed_invocation(
                            idx, statement.step_id, invocation_id, task_id,
                            error_msg,
                        )
                        break

            if EventType.INVOCATION_DISPATCHED not in prior_types:
                dispatched_payload: dict[str, Any] = {
                    "args": resolved_kwargs,
                    "idempotency_key": f"{run_id}:{invocation_id}",
                }
                if branch_claim_held is not None:
                    dispatched_payload["resource_claims"] = [branch_claim_held]
                self.store.append(
                    run_id,
                    EventType.INVOCATION_DISPATCHED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload=dispatched_payload,
                )

            if statement.command == DELEGATE_COMMAND:
                # Issue #25: a delegate step AUTHORS a child plan at
                # runtime.  The worker reply is the authored plan text;
                # the coordinator records it (CHILD_PLAN_AUTHORED),
                # validates and bounds it, then executes it as an isolated
                # child run and adopts its RETURN refs onto the step's
                # targets — all inside _execute_delegate_entry, which
                # fails the run atomically through the standard path on
                # any rejection or non-succeeded child.
                delegate_result = self._execute_delegate_entry(
                    run_id,
                    idx,
                    invocation_id,
                    task_id,
                    statement,
                    resolved_kwargs,
                    values,
                    plan,
                    statement_to_task,
                    prior_types,
                    crash_hook,
                    gate,
                    claims,
                    branch_root,
                    branch_claim,
                    finish_failed_invocation,
                )
                if delegate_result is not None:
                    return delegate_result
                anchor_result = self._run_conditionals(
                    run_id,
                    anchors.get(idx + 1, ()),
                    values,
                    plan,
                    statement_to_task,
                    cancel_from_idx=idx + 1,
                )
                if anchor_result is not None:
                    return anchor_result
                continue

            try:
                result = self._execute_worker_call(
                    statement.command, resolved_kwargs, gate
                )
            except Exception as exc:
                failed = True
                error_msg = str(exc)
                finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id, error_msg
                )
                break
            finally:
                # The branch claim covers exactly the handler's duration;
                # releasing twice is a no-op (only the holder can release).
                if branch_claim_held is not None:
                    claims.release(
                        branch_claim_held, f"{run_id}:{invocation_id}"
                    )
                    branch_claim_held = None

            self.store.append(
                run_id,
                EventType.RESULT_RECEIVED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={"result": result},
            )

            target_values, validation_error = map_results_to_targets(
                statement.targets, result
            )

            if validation_error is not None:
                if validation_error == "handler returned non-mapping for multiple targets":
                    validation_error = (
                        f"handler {statement.command} returned non-mapping"
                        " for multiple targets"
                    )
                failed = True
                error_msg = validation_error
                finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id, validation_error
                )
                break

            if statement.done is not None:
                passed, detail = evaluate_done_predicate(statement.done, target_values)
                if not passed:
                    validation_payload = {
                        "step_id": statement.step_id,
                        "predicate": {
                            "op": statement.done.op,
                            "ref": statement.done.ref,
                            "value": statement.done.value,
                        },
                        "detail": detail,
                    }
                    failed = True
                    error_msg = (
                        f"DONE predicate failed for {statement.step_id}: {detail}"
                    )
                    finish_failed_invocation(
                        idx, statement.step_id, invocation_id, task_id, error_msg,
                        validation=validation_payload,
                    )
                    break

            # Issue #7: resolve the step's REVISE/RETIRE corrections here,
            # before VALIDATION_PASSED, so a malformed (unvalidated)
            # invocation fails through the standard atomic path.  REVISE
            # refs are set to the step's single target value (validation
            # pins REVISE to single-target steps); RETIRE refs are removed
            # from the projection.  Both commit inside the same SUCCEEDED
            # delta as the step's adds, so later steps observe the
            # corrected state and the version bumps once per step.
            revision_nodes: list[dict[str, Any]] = []
            retired_nodes: list[str] = []
            try:
                if statement.revisions:
                    if len(statement.targets) != 1 or (
                        statement.targets[0] not in target_values
                    ):
                        raise ValueError(
                            f"REVISE on {statement.step_id} requires the"
                            " step's single target value"
                        )
                    revised_value = target_values[statement.targets[0]]
                    revision_nodes = [
                        {"id": ref, "value": revised_value}
                        for ref in statement.revisions
                    ]
                retired_nodes = list(statement.retirements)
            except Exception as exc:
                failed = True
                error_msg = str(exc)
                finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id, error_msg
                )
                break

            if crash_hook is not None:
                # Issue #10: crash-window hook.  Called with the plan
                # index right before VALIDATION_PASSED is appended; an
                # exception raised here propagates out of the coordinator
                # uncaught (this site is outside every try/except),
                # leaving the committed prefix exactly at the
                # RESULT_RECEIVED-persisted window.
                crash_hook(idx)

            self.store.append(
                run_id,
                EventType.VALIDATION_PASSED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={},
            )

            add_nodes: list[dict[str, Any]] = []
            for target, val in target_values.items():
                values[target] = val
                add_nodes.append({"id": target, "value": val})
            # Issue #7: keep the run-state values mapping in lockstep with
            # the corrections so later steps resolve revised values and
            # fail coherently on retired refs.
            for node in revision_nodes:
                values[node["id"]] = node["value"]
            for ref in retired_nodes:
                values.pop(ref, None)

            delta = StateDelta(
                add_nodes=tuple(add_nodes),
                revise_nodes=tuple(revision_nodes),
                retire_nodes=tuple(retired_nodes),
            )

            expected_sv = self.store._current_state_version(run_id)

            # batch: SUCCEEDED + invocation_recorded + task_completed
            self.store.append_batch(run_id, [
                _Record(
                    event_type=EventType.SUCCEEDED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    expected_state_version=expected_sv,
                    payload={"delta": delta},
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "invocation_recorded", "id": task_id,
                        "tokens": 0, "cost": 0.0, "retries": 0,
                        "elapsed_seconds": 0.0,
                    },
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "task_completed", "id": task_id,
                        "evidence": f"{statement.command} -> {statement.targets}",
                    },
                    store=self.store,
                ),
            ])

            # Issue #3: conditionals anchored directly after this entry in
            # source order are evaluated over the state it just committed;
            # a fired STOP/RETURN ends the run here, so later entries never
            # execute and their tasks stay cancelled.
            anchor_result = self._run_conditionals(
                run_id,
                anchors.get(idx + 1, ()),
                values,
                plan,
                statement_to_task,
                cancel_from_idx=idx + 1,
            )
            if anchor_result is not None:
                return anchor_result

        outputs: dict[str, Any] = {}
        if not failed:
            # Issue #3: conditionals anchored after the last invocation run
            # before the bare terminal scan (source order).
            if len(plan) > 0:
                anchor_result = self._run_conditionals(
                    run_id,
                    anchors.get(len(plan), ()),
                    values,
                    plan,
                    statement_to_task,
                    cancel_from_idx=len(plan),
                )
                if anchor_result is not None:
                    return anchor_result
            for statement in program.statements:
                if isinstance(statement, Return):
                    return self._terminal_return(run_id, statement.refs, values)
                if isinstance(statement, Stop):
                    return self._terminal_stop(run_id, statement, values)

        if failed:
            return {"run_id": run_id, "status": "failed", "error": error_msg or "", "outputs": {}}

        self.store.append(
            run_id,
            EventType.RUN_FINISHED,
            payload={"status": "succeeded"},
        )
        return {"run_id": run_id, "status": "succeeded", "outputs": outputs}

    # ------------------------------------------------------------------
    # Concurrent execution frontier (issue #21)
    # ------------------------------------------------------------------

    _TYPED_REF_CANDIDATE_RE = re.compile(
        r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+"
    )

    @staticmethod
    def _scan_arg_refs(value: Any) -> frozenset[str]:
        """Typed refs an argument value reads (issue #21 DAG input).

        Mirrors the dispatch guard's scan: bare ref strings and list
        items (``KB.*`` refs resolve from the knowledge base, never from
        run state, so they create no plan dependencies); JSON literals
        pass through untouched, exactly as in ``_reject_unresolved_refs``.
        """
        found: set[str] = set()
        if isinstance(value, str):
            if not value.startswith("KB.") and is_typed_reference(value):
                found.add(value)
        elif isinstance(value, list):
            for item in value:
                found |= SequentialCoordinator._scan_arg_refs(item)
        return frozenset(found)

    def _condition_refs(self, condition: str) -> frozenset[str]:
        """Refs an IF condition reads (issue #21 DAG input).

        Ref-shaped tokens filtered through ``is_typed_reference``.  This
        is a deliberate over-approximation: a ref-shaped string inside a
        JSON literal also counts.  Extra dependencies only serialize the
        frontier further — they never change results.
        """
        return frozenset(
            candidate
            for candidate in self._TYPED_REF_CANDIDATE_RE.findall(condition)
            if is_typed_reference(candidate)
        )

    def _entry_refs(
        self, entry: _PlanEntry
    ) -> tuple[frozenset[str], frozenset[str]]:
        """The refs one plan entry reads and writes (issue #21).

        ``writes`` are the refs the entry mutates: targets, REVISE'd
        refs (overwritten with the step's target value) and RETIRE'd
        refs (removed from the projection).  ``reads`` are the refs it
        observes: arguments and condition operands.  A retirement is a
        write, not a read — ordering it after earlier readers and
        writers is what keeps the frontier's outcomes identical to the
        sequential plan's.
        """
        writes: set[str] = set()
        reads: set[str] = set()
        if entry.call is not None:
            for arg in entry.call.args:
                reads |= self._scan_arg_refs(arg.value)
            writes |= set(entry.call.targets)
        else:
            statement = entry.invocation
            for arg in statement.args:
                reads |= self._scan_arg_refs(arg.value)
            writes |= set(statement.targets)
            writes |= set(statement.revisions)
            writes |= set(statement.retirements)
            if entry.condition is not None:
                reads |= self._condition_refs(entry.condition)
        return frozenset(writes), frozenset(reads)

    @staticmethod
    def _refs_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
        """Whether two ref sets touch (field-selection aware, issue #21).

        ``V.tests.status`` overlaps ``V.tests``: a condition reading a
        field of a node depends on the node's producer.
        """
        for x in a:
            for y in b:
                if x == y or x.startswith(y + ".") or y.startswith(x + "."):
                    return True
        return False

    def _build_dependency_dag(
        self, plan: list[_PlanEntry]
    ) -> list[frozenset[int]]:
        """Plan index -> indices that must be terminal before it dispatches.

        Edge rules (issue #21): an entry depends on every earlier entry
        that produces a ref it consumes (RAW), on every earlier producer
        of a ref it itself writes (WAW), and — as a writer — on every
        earlier reader or writer of any ref it writes (WAR, so a
        retirement or revision can never invalidate an in-flight
        reader's pinned inputs).  Two entries that only read the same
        ref carry no edge.  Every entry therefore observes exactly the
        committed state its sequential execution would have seen;
        read-read pairs and ref-disjoint entries may run concurrently.
        The DAG is acyclic by construction (edges point backwards).
        """
        ref_pairs = [self._entry_refs(entry) for entry in plan]
        deps: list[frozenset[int]] = []
        for idx in range(len(plan)):
            writes_i, reads_i = ref_pairs[idx]
            edges: set[int] = set()
            for j in range(idx):
                writes_j, reads_j = ref_pairs[j]
                if self._refs_overlap(writes_i, writes_j | reads_j) or (
                    self._refs_overlap(reads_i, writes_j)
                ):
                    edges.add(j)
            deps.append(frozenset(edges))
        return deps

    def _drive_plan_concurrent(
        self,
        program: Program,
        run_id: str,
        plan: list[_PlanEntry],
        values: dict[str, Any],
        statement_to_task: dict[int, str],
        *,
        initial_terminal: frozenset[int] = frozenset(),
        crash_hook: "Callable[[int], None] | None" = None,
        max_workers: int = 2,
        gate: "BudgetGate | None" = None,
    ) -> dict[str, Any]:
        """Drive the plan through a ready-task frontier (issue #21).

        Ready = every plan entry sharing a ref with this one is already
        terminal (dependency DAG from ref usage) and every source-anchored
        conditional at or before its position is evaluated.  Ready
        entries dispatch in stable plan order onto a thread pool; the
        pool executes worker handlers and CALL child runs only — every
        commit (READY, DISPATCHED, RESULT_RECEIVED, the atomic SUCCEEDED
        batch, failures) happens on the coordinator's single-writer
        path in this thread, so the event shapes per invocation are
        identical to the sequential loop and the run's CAS state
        versions stay uncontended.

        Conditional DO entries and CALL entries execute only when all
        refs they consume are terminal: the frontier naturally
        serializes them behind their producers.  A conditional whose
        condition does not fire is terminal without work; later
        consumers of its targets then fail exactly like the sequential
        coordinator (unresolved reference at dispatch).

        Completion order — not plan order — fixes commit order; the
        projection is order-independent because interacting entries are
        serialized by the DAG and ref-disjoint deltas commute.
        ``crash_hook`` fires at the same site as the sequential loop
        (before VALIDATION_PASSED) and propagates uncaught, leaving the
        committed prefix intact while in-flight pool work is discarded.

        Resume (``initial_terminal``): entries already SUCCEEDED before
        a crash are terminal from the start; in-flight entries
        re-dispatch through the same prior-lifecycle-event guards as the
        sequential resume (committed READY/DISPATCHED are never
        re-emitted; the worker call is re-executed, at-least-once).

        ``gate`` (issue #22) enforces an :class:`ExecutionBudget`: a
        loop-top global-deadline check (failing the run and cancelling
        in-flight invocations), a per-invocation deadline via future
        timeouts, the child-depth cap at CALL dispatch, and a shared
        concurrency slot around every handler execution (waiting CALL
        frames hold no slot, so a one-worker budget cannot deadlock a
        parent awaiting a child).
        """
        deps = self._build_dependency_dag(plan)
        anchors = self._collect_anchors(program)

        terminal: set[int] = set(initial_terminal)
        in_flight: dict[int, concurrent.futures.Future] = {}
        anchor_evaluated: set[int] = set()
        dispatched_at: dict[int, float] = {}
        executor: concurrent.futures.ThreadPoolExecutor | None = None

        def drain_in_flight() -> None:
            """Discard outstanding pool work (issue #21 cancellation rule).

            Not-yet-started futures are cancelled; started handlers
            cannot be interrupted, so they run to completion and their
            results are dropped uncommitted — a late result can never
            overwrite an accepted output or resurrect a failed run.
            """
            for future in in_flight.values():
                future.cancel()
            if in_flight:
                concurrent.futures.wait(list(in_flight.values()))
            in_flight.clear()

        def cancel_all_unsettled(exclude: int | None = None) -> list[_Record]:
            return [
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                )
                for pending_idx in range(len(plan))
                if pending_idx != exclude
                and pending_idx not in terminal
                and pending_idx in statement_to_task
            ]

        def finish_failed_invocation(
            idx: int,
            instruction_id: str,
            invocation_id: str,
            task_id: str,
            error: str,
            validation: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Fail one invocation and the run (mirrors the sequential batch)."""
            records = []
            if validation is not None:
                records.append(_Record(
                    event_type=EventType.VALIDATION_FAILED,
                    instruction_id=instruction_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload=validation,
                    store=self.store,
                ))
            records.append(_Record(
                event_type=EventType.FAILED,
                instruction_id=instruction_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={"error": error},
                store=self.store,
            ))
            records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={
                    "kind": "invocation_recorded", "id": task_id,
                    "tokens": 0, "cost": 0.0, "retries": 0,
                    "elapsed_seconds": 0.0,
                },
                store=self.store,
            ))
            records.append(_Record(
                event_type=EventType.TASK_UPDATED,
                task_id=task_id,
                payload={"kind": "task_cancelled", "id": task_id},
                store=self.store,
            ))
            records.extend(cancel_all_unsettled(exclude=idx))
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": error},
                store=self.store,
            ))
            self.store.append_batch(run_id, records)
            return {
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "outputs": {},
            }

        def fail_global_deadline(
            trigger_idx: int | None = None,
            reason: str = "global deadline exceeded",
        ) -> dict[str, Any]:
            """Run-level failure when the global budget deadline expired.

            In-flight invocations are marked FAILED with
            ``"cancelled: <reason>"`` (their pool work is drained and
            discarded — no adoption from cancelled children), the
            not-yet-dispatched trigger invocation (if any) carries the
            plain reason, remaining tasks are cancelled, and RUN_FINISHED
            records the failure — one atomic batch, audit-truthful.
            """
            records: list[_Record] = []

            def fail_one(idx: int, error: str) -> None:
                entry = plan[idx]
                instruction_id = (
                    entry.call.protocol
                    if entry.call is not None
                    else entry.invocation.step_id
                )
                task_id = statement_to_task[idx]
                records.extend([
                    _Record(
                        event_type=EventType.FAILED,
                        instruction_id=instruction_id,
                        invocation_id=f"inv-{idx + 1}",
                        task_id=task_id,
                        payload={"error": error},
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={
                            "kind": "invocation_recorded", "id": task_id,
                            "tokens": 0, "cost": 0.0, "retries": 0,
                            "elapsed_seconds": 0.0,
                        },
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={"kind": "task_cancelled", "id": task_id},
                        store=self.store,
                    ),
                ])

            if (
                trigger_idx is not None
                and trigger_idx not in terminal
                and trigger_idx not in in_flight
                and trigger_idx in statement_to_task
            ):
                fail_one(trigger_idx, reason)
            for idx in list(in_flight):
                fail_one(idx, f"cancelled: {reason}")
            records.extend(
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=statement_to_task[pending_idx],
                    payload={
                        "kind": "task_cancelled",
                        "id": statement_to_task[pending_idx],
                    },
                    store=self.store,
                )
                for pending_idx in range(len(plan))
                if pending_idx not in terminal
                and pending_idx not in in_flight
                and pending_idx != trigger_idx
                and pending_idx in statement_to_task
            )
            records.append(_Record(
                event_type=EventType.RUN_FINISHED,
                payload={"status": "failed", "error": reason},
                store=self.store,
            ))
            self.store.append_batch(run_id, records)
            return {
                "run_id": run_id,
                "status": "failed",
                "error": reason,
                "outputs": {},
            }

        def evaluate_reached_anchors() -> dict[str, Any] | None:
            """Evaluate source-anchored STOP/RETURN conditionals in order.

            An anchor at position ``pos`` is reached once every earlier
            entry is terminal; dispatch gating keeps later entries
            undispatched until it has been evaluated, so a fired
            terminal never races past in-flight work (in-flight is
            necessarily empty when an anchor evaluates).
            """
            for pos in sorted(anchors):
                if pos in anchor_evaluated:
                    continue
                if any(i not in terminal for i in range(pos)):
                    continue
                anchor_evaluated.add(pos)
                result = self._run_conditionals(
                    run_id,
                    anchors[pos],
                    values,
                    plan,
                    statement_to_task,
                    cancel_from_idx=pos,
                )
                if result is not None:
                    return result
            return None

        def next_ready() -> int | None:
            for idx in range(len(plan)):
                if idx in terminal or idx in in_flight:
                    continue
                if any(dep not in terminal for dep in deps[idx]):
                    continue
                if any(
                    pos not in anchor_evaluated
                    for pos in anchors
                    if pos <= idx
                ):
                    continue
                return idx
            return None

        def dispatch_entry(idx: int) -> tuple[str, Any]:
            """Run a ready entry's dispatch phase; submit its execution.

            Returns ``("dispatched", future)``, ``("skipped", None)`` for
            a conditional whose condition is false, or
            ``("run_failed", result)`` when the dispatch itself failed
            the run through the standard atomic path.
            """
            entry = plan[idx]
            statement = entry.invocation
            call = entry.call
            instruction_id = (
                call.protocol if call is not None else statement.step_id
            )
            invocation_id = f"inv-{idx + 1}"
            if entry.condition is not None:
                try:
                    fired = evaluate_condition(entry.condition, values)
                except ValueError as exc:
                    records = cancel_all_unsettled()
                    records.append(_Record(
                        event_type=EventType.RUN_FINISHED,
                        payload={"status": "failed", "error": str(exc)},
                        store=self.store,
                    ))
                    self.store.append_batch(run_id, records)
                    return (
                        "run_failed",
                        {
                            "run_id": run_id,
                            "status": "failed",
                            "error": str(exc),
                            "outputs": {},
                        },
                    )
                if not fired:
                    return ("skipped", None)
                task_id = statement_to_task.get(idx)
                if task_id is None:
                    task_id = self._create_single_plan_task(run_id, entry)
                    statement_to_task[idx] = task_id
            else:
                task_id = statement_to_task[idx]

            # Resume guard: an in-flight (crashed mid-dispatch) step keeps
            # its committed lifecycle events; the worker call re-runs.
            prior_types: set[EventType] = set()
            ledger = self.store.task_ledger(run_id)
            task = ledger.tasks.get(task_id)
            if task is not None and task.status is TaskStatus.IN_PROGRESS:
                prior_types = {
                    event.event_type
                    for event in self.store.events(run_id)
                    if event.invocation_id == invocation_id
                }
            elif task is not None and task.status is not TaskStatus.PENDING:
                raise TaskLedgerError(
                    f"task {task_id} for non-terminal step"
                    f" {instruction_id} is {task.status.value};"
                    " cannot resume"
                )
            ready_command = (
                f"CALL {call.protocol}" if call is not None else statement.command
            )
            if EventType.INVOCATION_READY not in prior_types:
                if task is not None and task.status is TaskStatus.IN_PROGRESS:
                    self.store.append(
                        run_id,
                        EventType.INVOCATION_READY,
                        instruction_id=instruction_id,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={"command": ready_command},
                    )
                else:
                    ledger.start_task(task_id)
                    self.store.append_batch(run_id, [
                        _Record(
                            event_type=EventType.TASK_UPDATED,
                            task_id=task_id,
                            payload={"kind": "task_started", "id": task_id},
                            store=self.store,
                        ),
                        _Record(
                            event_type=EventType.INVOCATION_READY,
                            instruction_id=instruction_id,
                            invocation_id=invocation_id,
                            task_id=task_id,
                            payload={"command": ready_command},
                            store=self.store,
                        ),
                    ])

            if call is not None:
                child_run_id = f"{run_id}:{invocation_id}"
                # Issue #22: child-depth cap, checked before dispatch.
                if gate is not None and gate.depth_exceeded(child_run_id):
                    return (
                        "run_failed",
                        finish_failed_invocation(
                            idx,
                            call.protocol,
                            invocation_id,
                            task_id,
                            f"child run {child_run_id} depth"
                            f" {gate.depth_of(child_run_id)} exceeds budget"
                            f" max_child_depth"
                            f" {gate.budget.max_child_depth}",
                        ),
                    )
                try:
                    resolved_call_args = self._resolve_call_arguments(
                        call, values
                    )
                except Exception as exc:
                    return (
                        "run_failed",
                        finish_failed_invocation(
                            idx, call.protocol, invocation_id, task_id, str(exc)
                        ),
                    )
                if EventType.INVOCATION_DISPATCHED not in prior_types:
                    self.store.append(
                        run_id,
                        EventType.INVOCATION_DISPATCHED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "args": resolved_call_args,
                            "idempotency_key": f"{run_id}:{invocation_id}",
                            "child_run_id": child_run_id,
                        },
                    )
                assert executor is not None
                future: concurrent.futures.Future = executor.submit(
                    self._execute_call_child,
                    call,
                    resolved_call_args,
                    run_id,
                    invocation_id,
                    gate,
                )
                return ("dispatched", future)

            try:
                resolved_kwargs: dict[str, Any] = {}
                for arg in statement.args:
                    self._reject_unresolved_refs(arg.value, values)
                    if isinstance(arg.value, str) and arg.value in values:
                        resolved_kwargs[arg.name] = values[arg.value]
                    elif isinstance(arg.value, str) and arg.value.startswith("KB."):
                        resolved_kwargs[arg.name] = self._resolve_kb_ref(arg.value)
                    elif isinstance(arg.value, list):
                        resolved_kwargs[arg.name] = [
                            values[item] if isinstance(item, str) and item in values
                            else self._resolve_kb_ref(item)
                            if isinstance(item, str) and item.startswith("KB.")
                            else item
                            for item in arg.value
                        ]
                    else:
                        resolved_kwargs[arg.name] = arg.value
            except Exception as exc:
                return (
                    "run_failed",
                    finish_failed_invocation(
                        idx, statement.step_id, invocation_id, task_id, str(exc)
                    ),
                )

            if (
                self.workspace_root is not None
                and statement.command in _effectful_commands()
            ):
                resolved_kwargs["_workspace_root"] = self.workspace_root

            if EventType.INVOCATION_DISPATCHED not in prior_types:
                self.store.append(
                    run_id,
                    EventType.INVOCATION_DISPATCHED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={
                        "args": resolved_kwargs,
                        "idempotency_key": f"{run_id}:{invocation_id}",
                    },
                )

            assert executor is not None
            future = executor.submit(
                self._dispatch_worker_call,
                statement.command,
                resolved_kwargs,
                gate,
            )
            return ("dispatched", future)

        def process_completion(
            idx: int, future: concurrent.futures.Future
        ) -> dict[str, Any] | None:
            """Commit one completed invocation (single-writer path)."""
            entry = plan[idx]
            statement = entry.invocation
            call = entry.call
            instruction_id = (
                call.protocol if call is not None else statement.step_id
            )
            invocation_id = f"inv-{idx + 1}"
            task_id = statement_to_task[idx]

            try:
                outcome = future.result()
            except Exception as exc:
                return finish_failed_invocation(
                    idx, instruction_id, invocation_id, task_id, str(exc)
                )

            if call is not None:
                child_run_id = f"{run_id}:{invocation_id}"
                child_status = outcome.get("status", "unknown")
                if child_status != "succeeded":
                    child_error = outcome.get("error")
                    error_msg = (
                        f"child run {child_run_id} for {call.protocol}"
                        f" finished with status {child_status!r}; the CALL"
                        " cannot adopt its outputs"
                    )
                    if child_error:
                        error_msg = f"{error_msg}: {child_error}"
                    return finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, error_msg
                    )
                self.store.append(
                    run_id,
                    EventType.RESULT_RECEIVED,
                    instruction_id=call.protocol,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={
                        "child_run_id": child_run_id,
                        "status": child_status,
                    },
                )
                try:
                    adopted_nodes, adopted_map = self._adopt_child_result(
                        call, outcome
                    )
                except Exception as exc:
                    return finish_failed_invocation(
                        idx, call.protocol, invocation_id, task_id, str(exc)
                    )
                if crash_hook is not None:
                    # Same crash window as the sequential loop: after the
                    # child is terminal, before the parent adopts.
                    crash_hook(idx)
                self.store.append(
                    run_id,
                    EventType.VALIDATION_PASSED,
                    instruction_id=call.protocol,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    payload={},
                )
                for node in adopted_nodes:
                    values[node["id"]] = node["value"]
                delta = StateDelta(add_nodes=tuple(adopted_nodes))
                expected_sv = self.store._current_state_version(run_id)
                self.store.append_batch(run_id, [
                    _Record(
                        event_type=EventType.CHILD_ADOPTED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        payload={
                            "child_run_id": child_run_id,
                            "adopted": adopted_map,
                            "child_status": child_status,
                        },
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.SUCCEEDED,
                        instruction_id=call.protocol,
                        invocation_id=invocation_id,
                        task_id=task_id,
                        expected_state_version=expected_sv,
                        payload={"delta": delta},
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={
                            "kind": "invocation_recorded", "id": task_id,
                            "tokens": 0, "cost": 0.0, "retries": 0,
                            "elapsed_seconds": 0.0,
                        },
                        store=self.store,
                    ),
                    _Record(
                        event_type=EventType.TASK_UPDATED,
                        task_id=task_id,
                        payload={
                            "kind": "task_completed", "id": task_id,
                            "evidence": (
                                f"CALL {call.protocol} ({child_run_id})"
                                f" -> {list(call.targets)}"
                            ),
                        },
                        store=self.store,
                    ),
                ])
                terminal.add(idx)
                return None

            result = outcome
            self.store.append(
                run_id,
                EventType.RESULT_RECEIVED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={"result": result},
            )

            target_values, validation_error = map_results_to_targets(
                statement.targets, result
            )
            if validation_error is not None:
                if validation_error == "handler returned non-mapping for multiple targets":
                    validation_error = (
                        f"handler {statement.command} returned non-mapping"
                        " for multiple targets"
                    )
                return finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id,
                    validation_error,
                )

            if statement.done is not None:
                passed, detail = evaluate_done_predicate(
                    statement.done, target_values
                )
                if not passed:
                    validation_payload = {
                        "step_id": statement.step_id,
                        "predicate": {
                            "op": statement.done.op,
                            "ref": statement.done.ref,
                            "value": statement.done.value,
                        },
                        "detail": detail,
                    }
                    return finish_failed_invocation(
                        idx, statement.step_id, invocation_id, task_id,
                        f"DONE predicate failed for {statement.step_id}:"
                        f" {detail}",
                        validation=validation_payload,
                    )

            revision_nodes: list[dict[str, Any]] = []
            retired_nodes: list[str] = []
            try:
                if statement.revisions:
                    if len(statement.targets) != 1 or (
                        statement.targets[0] not in target_values
                    ):
                        raise ValueError(
                            f"REVISE on {statement.step_id} requires the"
                            " step's single target value"
                        )
                    revised_value = target_values[statement.targets[0]]
                    revision_nodes = [
                        {"id": ref, "value": revised_value}
                        for ref in statement.revisions
                    ]
                retired_nodes = list(statement.retirements)
            except Exception as exc:
                return finish_failed_invocation(
                    idx, statement.step_id, invocation_id, task_id, str(exc)
                )

            if crash_hook is not None:
                # Same crash window as the sequential loop (issue #10):
                # outside every try/except, so the exception propagates
                # uncaught and the committed prefix stays untouched.
                crash_hook(idx)

            self.store.append(
                run_id,
                EventType.VALIDATION_PASSED,
                instruction_id=statement.step_id,
                invocation_id=invocation_id,
                task_id=task_id,
                payload={},
            )

            for target, val in target_values.items():
                values[target] = val
            for node in revision_nodes:
                values[node["id"]] = node["value"]
            for ref in retired_nodes:
                values.pop(ref, None)

            delta = StateDelta(
                add_nodes=tuple(
                    {"id": target, "value": value}
                    for target, value in target_values.items()
                ),
                revise_nodes=tuple(revision_nodes),
                retire_nodes=tuple(retired_nodes),
            )
            expected_sv = self.store._current_state_version(run_id)
            self.store.append_batch(run_id, [
                _Record(
                    event_type=EventType.SUCCEEDED,
                    instruction_id=statement.step_id,
                    invocation_id=invocation_id,
                    task_id=task_id,
                    expected_state_version=expected_sv,
                    payload={"delta": delta},
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "invocation_recorded", "id": task_id,
                        "tokens": 0, "cost": 0.0, "retries": 0,
                        "elapsed_seconds": 0.0,
                    },
                    store=self.store,
                ),
                _Record(
                    event_type=EventType.TASK_UPDATED,
                    task_id=task_id,
                    payload={
                        "kind": "task_completed", "id": task_id,
                        "evidence": (
                            f"{statement.command} -> {statement.targets}"
                        ),
                    },
                    store=self.store,
                ),
            ])
            terminal.add(idx)
            return None

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers
        ) as pool:
            executor = pool
            while True:
                # Issue #22: the global deadline is checked before each
                # dispatch cycle; work remaining + expired deadline fails
                # the run coherently.  An all-terminal run finishes
                # normally — the deadline limits work, not completion.
                if gate is not None and gate.global_expired() and not all(
                    idx in terminal for idx in range(len(plan))
                ):
                    # record the failure (marking in-flight invocations
                    # cancelled) BEFORE draining the pool work
                    result = fail_global_deadline(next_ready())
                    drain_in_flight()
                    return result

                anchor_result = evaluate_reached_anchors()
                if anchor_result is not None:
                    drain_in_flight()
                    return anchor_result

                while len(in_flight) < max_workers:
                    idx = next_ready()
                    if idx is None:
                        break
                    kind, payload = dispatch_entry(idx)
                    if kind == "run_failed":
                        drain_in_flight()
                        return payload
                    if kind == "skipped":
                        terminal.add(idx)
                        anchor_result = evaluate_reached_anchors()
                        if anchor_result is not None:
                            drain_in_flight()
                            return anchor_result
                        continue
                    in_flight[idx] = payload
                    dispatched_at[idx] = _monotonic()

                if not in_flight:
                    if all(idx in terminal for idx in range(len(plan))):
                        break
                    raise RuntimeError(
                        f"frontier stalled on run {run_id!r}: ready and"
                        " in-flight sets are empty with entries remaining"
                    )

                owner = {future: idx for idx, future in in_flight.items()}
                done, _ = concurrent.futures.wait(
                    in_flight.values(),
                    timeout=self._frontier_wait_timeout(gate, in_flight, dispatched_at),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    idx = owner[future]
                    del in_flight[idx]
                    del dispatched_at[idx]
                    # Issue #22: a completion arriving after the global
                    # deadline is discarded uncommitted (a cancellation
                    # request is never mistaken for confirmed
                    # termination — the pool work is drained, not joined
                    # into the run's outcome).
                    if gate is not None and gate.global_expired():
                        result = fail_global_deadline()
                        drain_in_flight()
                        return result
                    failure = process_completion(idx, future)
                    if failure is not None:
                        drain_in_flight()
                        return failure

                # Issue #22: per-invocation deadlines of still-running
                # futures — an overrunning invocation fails through the
                # standard atomic path; its late result is discarded.
                if (
                    gate is not None
                    and in_flight
                    and gate.budget.per_invocation_deadline_seconds
                    is not None
                ):
                    now = _monotonic()
                    per_invocation = (
                        gate.budget.per_invocation_deadline_seconds
                    )
                    expired = [
                        idx
                        for idx in in_flight
                        if now - dispatched_at[idx] >= per_invocation
                    ]
                    if expired:
                        idx = expired[0]
                        entry = plan[idx]
                        instruction_id = (
                            entry.call.protocol
                            if entry.call is not None
                            else entry.invocation.step_id
                        )
                        in_flight.pop(idx)
                        del dispatched_at[idx]
                        drain_in_flight()
                        return finish_failed_invocation(
                            idx,
                            instruction_id,
                            f"inv-{idx + 1}",
                            statement_to_task[idx],
                            "deadline exceeded",
                        )

        for statement in program.statements:
            if isinstance(statement, Return):
                return self._terminal_return(run_id, statement.refs, values)
            if isinstance(statement, Stop):
                return self._terminal_stop(run_id, statement, values)

        self.store.append(
            run_id,
            EventType.RUN_FINISHED,
            payload={"status": "succeeded"},
        )
        return {"run_id": run_id, "status": "succeeded", "outputs": {}}
