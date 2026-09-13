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
    Gather,
    Invocation,
    Loop,
    Par,
    Program,
    Return,
    Scatter,
    Stop,
)

if TYPE_CHECKING:
    from .registry.registry import Registry

SUBLATTICE: dict[str, str] = {
    "E": "F",
    "F": "V",
    "A": "H",
    "H": "F",
    "U": "Q",
    "Q": "G",
    "C": "G",
}

ORTHOGONAL: frozenset[str] = frozenset({
    "CTX", "K", "X", "R", "OUT", "ART", "PR", "PF", "D", "O", "P",
})

ALL_TYPES: frozenset[str] = frozenset(
    SUBLATTICE.keys() | SUBLATTICE.values() | ORTHOGONAL
)


def is_subtype(t1: str, t2: str) -> bool:
    """True if t1 ⊑ t2 (t1 can be used where t2 is expected)."""
    if t1 == t2:
        return True
    if t1 in ORTHOGONAL or t2 in ORTHOGONAL:
        return t1 == t2
    current = t1
    while current in SUBLATTICE:
        current = SUBLATTICE[current]
        if current == t2:
            return True
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
