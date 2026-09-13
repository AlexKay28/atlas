"""Planning helpers for the TAHOE coordinator (issue #38).

Extracted from coordinator.py: the plan-entry dataclass, the DAG/ref
helpers for the concurrent frontier, and the plan/anchor/task-text
builders that are pure logic over the program AST.

These are pure functions over the ``Program`` AST — no store, no worker,
no side effects.  The coordinator methods that previously inlined them now
delegate here.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Any, Mapping

from tahoe.syntax import is_typed_reference
from tahoe.syntax.model import (
    Await,
    Approve,
    Call,
    Conditional,
    Declaration,
    First,
    Gather,
    Invocation,
    Loop,
    Par,
    ParBranch,
    Program,
    Reformulate,
    Return,
    Scatter,
    Stop,
    Try,
)

if TYPE_CHECKING:
    pass


@dataclasses.dataclass(frozen=True)
class PlanEntry:
    """One flattened execution-plan entry.

    A plain (or conditional) ``Invocation`` step carries ``invocation``;
    a ``CALL protocol.name(...)`` statement (issue #20) carries ``call``
    and executes as an isolated child run instead of being expanded inline.

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
    scatter: "Scatter | None" = None
    gather: "Gather | None" = None
    par: "Par | None" = None
    loop: "Loop | None" = None
    try_: "Try | None" = None
    reformulate: "Reformulate | None" = None
    first: "First | None" = None
    await_: "Await | None" = None
    approve: "Approve | None" = None
    task_prefix: str = ""
    binds: tuple[tuple[str, tuple, tuple], ...] = ()
    finalizes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    condition: str | None = None
    else_condition: str | None = None


# Backward-compatible alias — coordinator re-exports this as _PlanEntry.
_PlanEntry = PlanEntry


def build_plan(program: Program) -> list[PlanEntry]:
    """Flatten the program into an execution plan.

    Caller invocations keep their positions; each CALL becomes its own
    plan entry (issue #20).  A CALL no longer expands the protocol's
    steps inline: executing the entry spawns an isolated child run whose
    plan is built from the protocol's own statements by the child's
    coordinator, and the child's RETURN refs are adopted onto the CALL
    targets when the child finishes succeeded.
    """
    entries: list[PlanEntry] = []

    def walk(statements: tuple[object, ...]) -> None:
        for statement in statements:
            if isinstance(statement, Invocation):
                entries.append(PlanEntry(invocation=statement))
            elif isinstance(statement, Conditional):
                if isinstance(statement.statement, Invocation):
                    entries.append(
                        PlanEntry(
                            invocation=statement.statement,
                            condition=statement.condition,
                        )
                    )
                elif isinstance(statement.statement, Reformulate):
                    entries.append(
                        PlanEntry(
                            reformulate=statement.statement,
                            condition=statement.condition,
                        )
                    )
                if statement.else_branch is not None:
                    for else_stmt in statement.else_branch:
                        if isinstance(else_stmt, Invocation):
                            entries.append(
                                PlanEntry(
                                    invocation=else_stmt,
                                    condition=None,
                                    else_condition=statement.condition,
                                )
                            )
            elif isinstance(statement, Call):
                entries.append(PlanEntry(call=statement))
            elif isinstance(statement, Scatter):
                entries.append(PlanEntry(scatter=statement))
            elif isinstance(statement, Par):
                entries.append(PlanEntry(par=statement))
            elif isinstance(statement, Loop):
                entries.append(PlanEntry(loop=statement))
            elif isinstance(statement, Try):
                entries.append(PlanEntry(try_=statement))
            elif isinstance(statement, Reformulate):
                entries.append(PlanEntry(reformulate=statement))
            elif isinstance(statement, First):
                entries.append(PlanEntry(first=statement))
            elif isinstance(statement, Await):
                entries.append(PlanEntry(await_=statement))
            elif isinstance(statement, Approve):
                entries.append(PlanEntry(approve=statement))
            elif isinstance(statement, Gather):
                entries.append(PlanEntry(gather=statement))

    walk(program.statements)
    return entries


def task_text(entry: PlanEntry) -> str:
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
    if entry.loop is not None:
        loop = entry.loop
        return f"LOOP {loop.name} MAX {loop.max_iterations}"
    if entry.try_ is not None:
        try_block = entry.try_
        max_str = f" MAX {try_block.max_count}" if try_block.max_count else ""
        return f"TRY{max_str} ({len(try_block.branches)} branches)"
    if entry.reformulate is not None:
        return "REFORMULATE"
    if entry.first is not None:
        return f"FIRST ({len(entry.first.selectors)} selectors)"
    if entry.await_ is not None:
        return f"AWAIT {entry.await_.selector}"
    if entry.approve is not None:
        return f"APPROVE {entry.approve.policy}"
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


def collect_anchors(program: Program) -> dict[int, list]:
    """Map plan index -> STOP/RETURN conditionals at that source anchor.

    An anchor value is the number of plan entries preceding the
    conditional in source order, so anchor ``a`` conditionals are
    evaluated right after plan entry ``a - 1`` commits (anchor 0 before
    the loop starts, anchor ``len(plan)`` after it ends).  Conditional
    DO invocations are plan entries themselves and are never anchors.
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
                    # Extra if-branch statements (RETURN/STOP after the
                    # Invocation) become anchors at this position — they
                    # fire when the condition is true.
                    for extra in statement.if_branch_extra:
                        anchors.setdefault(count, []).append(
                            _IfExtraAnchor(statement, extra)
                        )
                else:
                    anchors.setdefault(count, []).append(statement)
                if statement.else_branch is not None:
                    for else_stmt in statement.else_branch:
                        if isinstance(else_stmt, Invocation):
                            count += 1
                        else:
                            anchors.setdefault(count, []).append(
                                _ElseAnchor(statement, else_stmt)
                            )
            elif isinstance(statement, Call):
                count += 1
            elif isinstance(statement, (Scatter, Gather, Par, Loop, Try, Reformulate, First, Await, Approve)):
                count += 1
        return count

    walk(program.statements)
    return anchors


@dataclasses.dataclass(frozen=True)
class _ElseAnchor:
    """An else-branch terminal (STOP/RETURN) evaluated when condition is false."""
    conditional: Conditional
    statement: object


@dataclasses.dataclass(frozen=True)
class _IfExtraAnchor:
    """An extra if-branch terminal (RETURN/STOP) evaluated when condition is true."""
    conditional: Conditional
    statement: object


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


# ------------------------------------------------------------------
# Concurrent frontier DAG helpers (issue #21)
# ------------------------------------------------------------------

_TYPED_REF_CANDIDATE_RE = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+"
)


def scan_arg_refs(value: Any) -> frozenset[str]:
    """Typed refs an argument value reads (issue #21 DAG input).

    Mirrors the dispatch guard's scan: bare ref strings and list items
    (``KB.*`` refs resolve from the knowledge base, never from run state,
    so they create no plan dependencies); JSON literals pass through
    untouched, exactly as in ``_reject_unresolved_refs``.
    """
    found: set[str] = set()
    if isinstance(value, str):
        if not value.startswith("KB.") and is_typed_reference(value):
            found.add(value)
    elif isinstance(value, list):
        for item in value:
            found |= scan_arg_refs(item)
    return frozenset(found)


def condition_refs(condition: str) -> frozenset[str]:
    """Refs an IF condition reads (issue #21 DAG input).

    Ref-shaped tokens filtered through ``is_typed_reference``.  This is
    a deliberate over-approximation: a ref-shaped string inside a JSON
    literal also counts.  Extra dependencies only serialize the frontier
    further — they never change results.
    """
    return frozenset(
        candidate
        for candidate in _TYPED_REF_CANDIDATE_RE.findall(condition)
        if is_typed_reference(candidate)
    )


def entry_refs(entry: PlanEntry) -> tuple[frozenset[str], frozenset[str]]:
    """The refs one plan entry reads and writes (issue #21).

    ``writes`` are the refs the entry mutates: targets, REVISE'd refs
    (overwritten with the step's target value) and RETIRE'd refs (removed
    from the projection).  ``reads`` are the refs it observes: arguments
    and condition operands.  A retirement is a write, not a read.
    """
    writes: set[str] = set()
    reads: set[str] = set()
    if entry.call is not None:
        for arg in entry.call.args:
            reads |= scan_arg_refs(arg.value)
        writes |= set(entry.call.targets)
    else:
        statement = entry.invocation
        for arg in statement.args:
            reads |= scan_arg_refs(arg.value)
        writes |= set(statement.targets)
        writes |= set(statement.revisions)
        writes |= set(statement.retirements)
        if entry.condition is not None:
            reads |= condition_refs(entry.condition)
    return frozenset(writes), frozenset(reads)


def refs_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    """Whether two ref sets touch (field-selection aware, issue #21).

    ``V.tests.status`` overlaps ``V.tests``: a condition reading a field
    of a node depends on the node's producer.
    """
    for x in a:
        for y in b:
            if x == y or x.startswith(y + ".") or y.startswith(x + "."):
                return True
    return False


def build_dependency_dag(plan: list[PlanEntry]) -> list[frozenset[int]]:
    """Plan index -> indices that must be terminal before it dispatches.

    Edge rules (issue #21): an entry depends on every earlier entry that
    produces a ref it consumes (RAW), on every earlier producer of a ref
    it itself writes (WAW), and — as a writer — on every earlier reader
    or writer of any ref it writes (WAR).  Two entries that only read the
    same ref carry no edge.  The DAG is acyclic by construction (edges
    point backwards).
    """
    ref_pairs = [entry_refs(entry) for entry in plan]
    deps: list[frozenset[int]] = []
    for idx in range(len(plan)):
        writes_i, reads_i = ref_pairs[idx]
        edges: set[int] = set()
        for j in range(idx):
            writes_j, reads_j = ref_pairs[j]
            if refs_overlap(writes_i, writes_j | reads_j) or (
                refs_overlap(reads_i, writes_j)
            ):
                edges.add(j)
        deps.append(frozenset(edges))
    return deps
