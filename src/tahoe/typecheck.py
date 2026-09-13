"""Static type checker with subtyping lattice (issue #71).

The node types form a subtyping lattice under ⊑ (read "is a subtype of").
The lattice captures epistemic strength: a stronger type can be used where
a weaker type is expected, because it carries more epistemic warrant.

The lattice is implemented here and referenced from
``paper/design/formal-semantics.md`` §3.1–3.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .syntax.model import (
    Call,
    Conditional,
    Declaration,
    DonePredicate,
    Gather,
    Invocation,
    Loop,
    Par,
    Program,
    Reformulate,
    Return,
    Scatter,
    Stop,
    Try,
)

if TYPE_CHECKING:
    from .registry.registry import Registry

#: Subtyping edges from the 15 axioms in formal-semantics.md §3.2.
#: Each entry ``src: [dst1, dst2, ...]`` means ``src ⊑ dst`` (src is a
#: subtype of dst).  The lattice is a DAG — G has two parents (Q and C),
#: A has two parents (H and E), H has two parents (F and D), F and D
#: share the top V.
SUBLATTICE: dict[str, list[str]] = {
    "G": ["Q", "C"],
    "Q": ["U", "A"],
    "C": ["PF"],
    "PF": ["O"],
    "U": ["H"],
    "A": ["H", "E"],
    "E": ["F"],
    "H": ["F", "D"],
    "O": ["D"],
    "F": ["V"],
    "D": ["V"],
}

#: Types orthogonal to the main lattice — no subtyping with lattice
#: types (or each other) beyond reflexivity.
ORTHOGONAL: frozenset[str] = frozenset({
    "CTX", "K", "X", "R", "OUT", "ART", "PR", "P",
})

ALL_TYPES: frozenset[str] = frozenset(
    set(SUBLATTICE.keys()) | {d for dsts in SUBLATTICE.values() for d in dsts} | ORTHOGONAL
)

#: The 15 axiomatic edges from formal-semantics.md §3.2, as (subtype, supertype) pairs.
LATTICE_AXIOMS: frozenset[tuple[str, str]] = frozenset({
    ("G", "Q"), ("G", "C"), ("Q", "U"), ("Q", "A"), ("C", "PF"),
    ("PF", "O"), ("U", "H"), ("A", "H"), ("A", "E"), ("E", "F"),
    ("H", "F"), ("H", "D"), ("O", "D"), ("F", "V"), ("D", "V"),
})


def is_subtype(t1: str, t2: str) -> bool:
    """True if t1 ⊑ t2 (t1 can be used where t2 is expected).

    Computes the reflexive-transitive closure of SUBLATTICE via BFS.
    Orthogonal types are subtypes only of themselves.
    """
    if t1 == t2:
        return True
    if t1 in ORTHOGONAL or t2 in ORTHOGONAL:
        return t1 == t2
    visited: set[str] = set()
    queue: list[str] = [t1]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for parent in SUBLATTICE.get(current, []):
            if parent == t2:
                return True
            queue.append(parent)
    return False


def _ref_type(ref: str) -> str:
    """Extract the type prefix from a typed reference like 'E.result'."""
    return ref.split(".")[0]


def _parse_type_spec(type_str: str) -> str | None:
    """Parse a contract type string and return its node-type prefix.

    Contract entries use ``name:type`` where ``type`` may be:
    - a node-type prefix (single uppercase letter or ``OUT``)
    - a slash compound like ``G/C/P/K/OUT``
    - a primitive like ``text``, ``json``, ``refs``, etc.

    Returns the first node-type prefix found, or ``None`` for non-node types.
    """
    if not type_str:
        return None
    if "/" in type_str:
        for seg in type_str.split("/"):
            if seg in ALL_TYPES:
                return seg
        return None
    if type_str in ALL_TYPES:
        return type_str
    return None


def _parse_type_specs(type_str: str) -> list[str]:
    """Parse a contract type string and return all node-type prefixes.

    For slash compounds like ``G/C/P/K/OUT`` returns ``["G", "C", "P", "K", "OUT"]``.
    For single node types returns ``[type]``.
    For non-node types returns ``[]``.
    """
    if not type_str:
        return []
    if "/" in type_str:
        return [seg for seg in type_str.split("/") if seg in ALL_TYPES]
    if type_str in ALL_TYPES:
        return [type_str]
    return []


def _parse_input_spec(entry: str) -> tuple[str, str | None]:
    """Parse ``name:type`` from a contract input/parameter entry."""
    if ":" not in entry:
        return entry, None
    name, type_part = entry.split(":", 1)
    return name.strip(), _parse_type_spec(type_part.strip())


def _parse_input_spec_full(entry: str) -> tuple[str, str | None, str]:
    """Parse ``name:type`` returning (name, first_node_type, raw_type_str)."""
    if ":" not in entry:
        return entry, None, ""
    name, type_part = entry.split(":", 1)
    type_part = type_part.strip()
    return name.strip(), _parse_type_spec(type_part), type_part


def _collect_invocation_errors(
    command: str,
    args: tuple,
    targets: tuple[str, ...],
    state: dict[str, str],
    registry: Registry | None,
) -> list[str]:
    """Check that argument types match the command contract."""
    if registry is None:
        return []
    try:
        spec = registry.resolve(command)
    except Exception:
        return [f"unknown command: {command}"]

    errors: list[str] = []
    input_types: dict[str, str | None] = {}
    for entry in spec.inputs:
        name, node_type = _parse_input_spec(entry)
        input_types[name] = node_type

    for arg in args:
        expected_type = input_types.get(arg.name)
        if expected_type is None:
            continue
        if isinstance(arg.value, str) and "." in arg.value:
            ref_prefix = arg.value.split(".")[0]
            if ref_prefix in ALL_TYPES:
                actual_type = ref_prefix
                if not is_subtype(actual_type, expected_type):
                    errors.append(
                        f"type mismatch: argument {arg.name} expects {expected_type}"
                        f" but got {actual_type}"
                    )
                continue
        if isinstance(arg.value, str) and _ref_type(arg.value) in ALL_TYPES:
            actual_type = _ref_type(arg.value)
            if not is_subtype(actual_type, expected_type):
                errors.append(
                    f"type mismatch: argument {arg.name} expects {expected_type}"
                    f" but got {actual_type}"
                )

    output_types: dict[str, list[str]] = {}
    for entry in spec.outputs:
        name, _, type_part = _parse_input_spec_full(entry)
        output_types[name] = _parse_type_specs(type_part)

    for target in targets:
        if target.startswith("KB."):
            continue
        target_type = _ref_type(target)
        output_names = list(output_types.keys())
        if output_names:
            out_name = output_names[0]
            out_type_list = output_types[out_name]
            if out_type_list and not any(
                is_subtype(target_type, ot) for ot in out_type_list
            ):
                errors.append(
                    f"type mismatch: output {out_name} produces"
                    f" {'/'.join(out_type_list)}"
                    f" but target {target} expects {target_type}"
                )

    return errors


def _collect_done_errors(
    invocation: Invocation,
    state: dict[str, str],
) -> list[str]:
    """Check that a DONE predicate references a valid target ref type.

    A DONE predicate's ``ref`` must be one of the invocation's own targets
    (or a previously committed ref).  The ref's type must be a lattice
    type (not orthogonal) — DONE tests epistemic properties, not artifacts
    or context.
    """
    if invocation.done is None:
        return []
    errors: list[str] = []
    done: DonePredicate = invocation.done
    done_ref = done.ref

    target_set = set(invocation.targets)
    if done_ref not in target_set and done_ref not in state:
        errors.append(
            f"type error: DONE predicate references {done_ref}"
            f" which is not a target of step {invocation.step_id}"
            f" or a previously committed ref"
        )
        return errors

    done_type = _ref_type(done_ref)
    if done_type in ORTHOGONAL:
        errors.append(
            f"type error: DONE predicate on {done_ref} has orthogonal type {done_type};"
            f" DONE tests epistemic properties, not orthogonal types"
        )

    return errors


def _collect_try_errors(
    statement: Try,
    state: dict[str, str],
    registry: Registry | None,
) -> list[str]:
    """Check that TRY branch targets have compatible types.

    All branches in a TRY block should produce compatible target types.
    If one branch produces V.result and another produces H.guess, the
    type mismatch is reported as a warning.  Comparison is by leaf name
    (the part after the dot) — if two branches target the same leaf name
    with different type prefixes, those types must be compatible under ⊑.
    """
    errors: list[str] = []

    branch_target_types: list[dict[str, str]] = []
    for branch in statement.branches:
        branch_state = dict(state)
        branch_types: dict[str, str] = {}
        for stmt in branch:
            _collect_statement_errors(stmt, branch_state, registry)
            if isinstance(stmt, Invocation):
                for target in stmt.targets:
                    if not target.startswith("KB."):
                        leaf = target.split(".", 1)[1] if "." in target else target
                        branch_types[leaf] = _ref_type(target)
            elif isinstance(stmt, Call):
                for target in stmt.targets:
                    if not target.startswith("KB."):
                        leaf = target.split(".", 1)[1] if "." in target else target
                        branch_types[leaf] = _ref_type(target)
        branch_target_types.append(branch_types)

    if len(branch_target_types) < 2:
        return errors

    all_leaves: set[str] = set()
    for bt in branch_target_types:
        all_leaves |= set(bt.keys())

    for leaf in sorted(all_leaves):
        types_seen = []
        for bt in branch_target_types:
            if leaf in bt:
                types_seen.append(bt[leaf])
        if len(types_seen) < 2:
            continue
        for i in range(len(types_seen)):
            for j in range(i + 1, len(types_seen)):
                if (
                    not is_subtype(types_seen[i], types_seen[j])
                    and not is_subtype(types_seen[j], types_seen[i])
                ):
                    errors.append(
                        f"type mismatch: TRY branch target *.{leaf}"
                        f" has incompatible types: {types_seen[i]}"
                        f" and {types_seen[j]}"
                    )

    return errors


def _collect_statement_errors(
    statement: object,
    state: dict[str, str],
    registry: Registry | None,
) -> list[str]:
    """Collect type errors from a single statement, mutating ``state``."""
    errors: list[str] = []

    if isinstance(statement, Invocation):
        errors.extend(
            _collect_invocation_errors(
                statement.command,
                statement.args,
                statement.targets,
                state,
                registry,
            )
        )
        errors.extend(_collect_done_errors(statement, state))
        for target in statement.targets:
            if not target.startswith("KB."):
                state[target] = _ref_type(target)
    elif isinstance(statement, Call):
        for target in statement.targets:
            if not target.startswith("KB."):
                state[target] = _ref_type(target)
    elif isinstance(statement, Return):
        pass
    elif isinstance(statement, Stop):
        pass
    elif isinstance(statement, Conditional):
        errors.extend(
            _collect_statement_errors(statement.statement, state, registry)
        )
        if statement.else_branch is not None:
            for else_stmt in statement.else_branch:
                errors.extend(
                    _collect_statement_errors(else_stmt, state, registry)
                )
        if statement.if_branch_extra:
            for extra_stmt in statement.if_branch_extra:
                errors.extend(
                    _collect_statement_errors(extra_stmt, state, registry)
                )
    elif isinstance(statement, Scatter):
        errors.extend(
            _collect_statement_errors(statement.body, state, registry)
        )
    elif isinstance(statement, Gather):
        if not statement.alias_ref.startswith("KB."):
            state[statement.alias_ref] = _ref_type(statement.alias_ref)
    elif isinstance(statement, Par):
        for branch in statement.branches:
            if branch.invocation is not None:
                errors.extend(
                    _collect_statement_errors(
                        branch.invocation, state, registry
                    )
                )
            elif branch.call is not None:
                for target in branch.call.targets:
                    if not target.startswith("KB."):
                        state[target] = _ref_type(target)
        for target in statement.barrier_targets:
            if not target.startswith("KB."):
                state[target] = _ref_type(target)
    elif isinstance(statement, Loop):
        for body_stmt in statement.body:
            errors.extend(
                _collect_statement_errors(body_stmt, state, registry)
            )
    elif isinstance(statement, Try):
        errors.extend(_collect_try_errors(statement, state, registry))
        for branch in statement.branches:
            for stmt in branch:
                if isinstance(stmt, Invocation):
                    for target in stmt.targets:
                        if not target.startswith("KB."):
                            state[target] = _ref_type(target)
                elif isinstance(stmt, Call):
                    for target in stmt.targets:
                        if not target.startswith("KB."):
                            state[target] = _ref_type(target)
    elif isinstance(statement, Reformulate):
        errors.extend(
            _collect_statement_errors(statement.diagnose, state, registry)
        )
        errors.extend(
            _collect_statement_errors(statement.replan, state, registry)
        )
        continue_type = _ref_type(statement.continue_ref)
        replan_targets = statement.replan.targets
        if replan_targets:
            replan_output_type = _ref_type(replan_targets[0])
            if not is_subtype(replan_output_type, continue_type):
                errors.append(
                    f"type mismatch: REPLAN output {replan_targets[0]}"
                    f" has type {replan_output_type} but CONTINUE ref"
                    f" {statement.continue_ref} expects {continue_type}"
                )
        state[statement.continue_ref] = continue_type

    return errors


def check_program_types(
    program: Program,
    registry: Registry | None = None,
) -> list[str]:
    """Type-check an entire program. Returns list of type error strings."""
    errors: list[str] = []
    state: dict[str, str] = {}

    for decl in program.declarations:
        state[decl.ref] = _ref_type(decl.ref)

    for stmt in program.statements:
        errors.extend(_collect_statement_errors(stmt, state, registry))

    return errors
