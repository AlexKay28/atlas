"""Parser and sealing helpers for the sequential Tikhon subset."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import Any, Iterable

from .model import Argument, Declaration, DonePredicate, Invocation, Program, Return, Stop

_NAME = r"[a-z][a-z0-9_]*"
_PREFIX = r"(?:G|Q|CTX|C|P|F|E|A|H|O|K|D|X|V|R|U|OUT|ART)"
_REF_PATTERN = rf"{_PREFIX}\.{_NAME}(?:\.{_NAME})*"
_REF_RE = re.compile(rf"^{_REF_PATTERN}$")
_HEADER_RE = re.compile(rf"^PROGRAM\s+(?P<name>{_NAME})\s+VERSION\s+(?P<version>\d+(?:\.\d+)*)$")
_DECL_RE = re.compile(rf"^(?P<ref>{_REF_PATTERN})\s*=\s*(?P<value>.+)$")
_STEP_RE = re.compile(
    rf"^(?P<step>step\.{_NAME}):\s*DO\s+(?P<command>{_NAME})"
    rf"\((?P<args>.*)\)\s*->\s*(?P<targets>.+)$"
)
_STOP_RE = re.compile(
    rf"^STOP\s+(?P<kind>{_NAME})\((?P<ref>{_REF_PATTERN})?\)$"
)
_UNSUPPORTED = frozenset(
    {"IF", "FIRST", "SCATTER", "GATHER", "LOOP", "TRY", "CALL", "AWAIT", "APPROVE"}
)
_STOP_KINDS = frozenset({"completed", "failed", "blocked", "denied", "cancelled", "unresolved"})
_DONE_OPS = frozenset({"equals", "in", "matched"})
_DONE_MATCHED_RE = re.compile(r"^matched\((?P<inner>.*)\)$", re.DOTALL)


class ParseError(Exception):
    """A syntax or validation error with a source location when available."""

    def __init__(self, message: str, line: int = 0, column: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column

    def __str__(self) -> str:
        if self.line:
            return f"{self.message} (line {self.line}, column {self.column})"
        return self.message


def parse_program(text: str) -> Program:
    """Parse the canonical one-line sequential MVP syntax."""
    if not isinstance(text, str):
        raise ParseError("source must be text")

    source = [
        (number, raw, raw.strip())
        for number, raw in enumerate(text.splitlines(), 1)
        if raw.strip() and not raw.lstrip().startswith("#")
    ]
    if not source:
        raise ParseError("missing PROGRAM header", 1, 1)

    header_line, _, header = source[0]
    match = _HEADER_RE.fullmatch(header)
    if match is None:
        raise ParseError("malformed PROGRAM header", header_line, 1)

    declarations: list[Declaration] = []
    statements: list[Invocation | Return | Stop] = []
    in_input = False
    terminal_seen = False

    for line_no, raw, line in source[1:]:
        if line == "INPUT":
            if declarations or statements or in_input:
                raise ParseError("INPUT must appear once before statements", line_no, 1)
            in_input = True
            continue

        if in_input and raw[:1].isspace():
            declaration = _DECL_RE.fullmatch(line)
            if declaration is None:
                raise ParseError("malformed INPUT declaration", line_no, len(raw) - len(raw.lstrip()) + 1)
            try:
                value = json.loads(declaration.group("value"))
            except json.JSONDecodeError as exc:
                raise ParseError(f"invalid JSON input value: {exc.msg}", line_no, exc.colno) from exc
            declarations.append(Declaration(declaration.group("ref"), value))
            continue
        in_input = False

        keyword = line.split(None, 1)[0]
        if keyword in _UNSUPPORTED:
            raise ParseError(f"unsupported control construct {keyword}", line_no, 1)
        if terminal_seen:
            raise ParseError("statement appears after terminal", line_no, 1)

        if re.match(r"DONE\b", line):
            expression = line[4:].strip()
            if not expression or not statements or not isinstance(statements[-1], Invocation):
                raise ParseError("DONE must follow an invocation", line_no, 1)
            if statements[-1].done is not None:
                raise ParseError("invocation has more than one DONE expression", line_no, 1)
            predicate = _parse_done_expression(expression, line_no)
            if predicate.ref not in statements[-1].targets:
                raise ParseError(
                    f"DONE reference {predicate.ref} must be one of the step's"
                    f" targets ({', '.join(statements[-1].targets)})",
                    line_no,
                    5,
                )
            statements[-1] = dataclasses.replace(statements[-1], done=predicate)
            continue

        if re.match(r"RETURN\b", line):
            refs = _parse_refs(line[6:].strip(), line_no, "RETURN")
            statements.append(Return(refs))
            terminal_seen = True
            continue

        if re.match(r"STOP\b", line):
            stop = _STOP_RE.fullmatch(line)
            if stop is None:
                raise ParseError("malformed STOP", line_no, 1)
            statements.append(Stop(stop.group("kind"), stop.group("ref")))
            terminal_seen = True
            continue

        step = _STEP_RE.fullmatch(line)
        if step is None:
            raise ParseError("malformed invocation", line_no, 1)
        args = tuple(_parse_argument(item, line_no) for item in _split_top_level(step.group("args")))
        targets = _parse_refs(step.group("targets"), line_no, "target")
        statements.append(
            Invocation(step.group("step"), step.group("command"), args, targets)
        )

    program = Program(
        match.group("name"),
        match.group("version"),
        tuple(declarations),
        tuple(statements),
    )
    return program


def _parse_argument(text: str, line_no: int) -> Argument:
    if "=" not in text:
        raise ParseError("argument must be name = value", line_no, 1)
    name, raw_value = (part.strip() for part in text.split("=", 1))
    if re.fullmatch(_NAME, name) is None or not raw_value:
        raise ParseError("malformed named argument", line_no, 1)
    if _REF_RE.fullmatch(raw_value):
        value: Any = raw_value
    elif raw_value.startswith("[") and raw_value.endswith("]"):
        value = _parse_bracket_value(raw_value, line_no)
    else:
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise ParseError(f"invalid argument value: {exc.msg}", line_no, exc.colno) from exc
    return Argument(name, value, line_no)


def _parse_done_expression(expression: str, line_no: int) -> DonePredicate:
    """Parse the deterministic DONE subset (docs/spec/01-language-and-state.md).

    Supported forms:

    - ``<ref> == <json-literal>``      (spec infix equality)
    - ``<ref> IN [<json-literal>, ...]`` (spec infix set membership)
    - ``matched(<ref>, "<regex>")``    (deterministic regex predicate; the
      spec defines no regex operator, so the issue's suggested name stands)

    The reference must still be validated against the owning step's
    targets by the caller.
    """
    text = expression.strip()
    if not text:
        raise ParseError("DONE expression is empty", line_no, 5)

    matched = _DONE_MATCHED_RE.fullmatch(text)
    if matched is not None:
        return _parse_matched_predicate(matched.group("inner"), line_no)

    eq_index = _find_top_level(text, "==")
    if eq_index != -1:
        lhs = text[:eq_index].strip()
        rhs = text[eq_index + 2:].strip()
        if _REF_RE.fullmatch(lhs) is None:
            raise ParseError(
                "DONE equality requires a typed reference on the left", line_no, 5
            )
        if not rhs:
            raise ParseError(
                "DONE equality requires a JSON literal on the right", line_no, 5
            )
        try:
            value = json.loads(rhs)
        except json.JSONDecodeError as exc:
            raise ParseError(
                f"invalid JSON literal in DONE expression: {exc.msg}", line_no, exc.colno
            ) from exc
        return DonePredicate("equals", lhs, value, line_no)

    in_index = _find_in_keyword(text)
    if in_index != -1:
        lhs = text[:in_index].strip()
        rhs = text[in_index + 2:].strip()
        if _REF_RE.fullmatch(lhs) is None:
            raise ParseError(
                "DONE membership requires a typed reference on the left", line_no, 5
            )
        try:
            value = json.loads(rhs)
        except json.JSONDecodeError as exc:
            raise ParseError(
                f"invalid JSON literal in DONE expression: {exc.msg}", line_no, exc.colno
            ) from exc
        if not isinstance(value, list):
            raise ParseError(
                "DONE membership requires a JSON array literal", line_no, 5
            )
        return DonePredicate("in", lhs, value, line_no)

    raise ParseError(f"unsupported DONE expression: {expression}", line_no, 5)


def _parse_matched_predicate(inner: str, line_no: int) -> DonePredicate:
    try:
        items = _split_top_level(inner)
    except ParseError:
        raise ParseError(
            'matched predicate requires exactly (ref, "regex") arguments', line_no, 5
        )
    if len(items) != 2:
        raise ParseError(
            'matched predicate requires exactly (ref, "regex") arguments', line_no, 5
        )
    ref, pattern_text = items
    if _REF_RE.fullmatch(ref) is None:
        raise ParseError(
            "matched predicate requires a typed reference as its first argument",
            line_no,
            5,
        )
    try:
        pattern = json.loads(pattern_text)
    except json.JSONDecodeError as exc:
        raise ParseError(
            f"invalid regex pattern in DONE matched predicate: {exc.msg}",
            line_no,
            exc.colno,
        ) from exc
    if not isinstance(pattern, str):
        raise ParseError(
            "matched predicate requires a quoted regex pattern string", line_no, 5
        )
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ParseError(
            f"invalid regex in DONE matched predicate: {exc.msg}", line_no, 5
        ) from exc
    return DonePredicate("matched", ref, pattern, line_no)


def _find_top_level(text: str, needle: str) -> int:
    """Index of the first ``needle`` outside quotes and brackets, or -1."""
    quote: str | None = None
    escaped = False
    depth = 0
    for index in range(len(text) - len(needle) + 1):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char in "[({":
            depth += 1
        elif char in "])}":
            depth -= 1
        elif depth == 0 and text.startswith(needle, index):
            return index
    return -1


def _find_in_keyword(text: str) -> int:
    """Index of a standalone uppercase ``IN`` at top level, or -1."""
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char in "[({":
            depth += 1
        elif char in "])}":
            depth -= 1
        elif (
            depth == 0
            and text.startswith("IN", index)
            and (index == 0 or text[index - 1].isspace())
            and index + 2 < len(text)
            and text[index + 2].isspace()
        ):
            return index
    return -1


def _parse_bracket_value(raw_value: str, line_no: int) -> Any:
    """Parse a bracketed argument value.

    A bracket containing at least one typed reference anywhere inside must
    be a flat, pure reference list: ``[E.a, E.b]``.  Empty brackets,
    nested lists, and mixed refs-and-literals are rejected.  A non-empty
    bracket without any typed reference stays an ordinary JSON literal
    (e.g. ``[1, 2]``).
    """
    inner = raw_value[1:-1].strip()
    if not inner:
        raise ParseError(
            "reference list requires at least one typed reference", line_no, 1
        )
    if not _contains_ref(raw_value):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise ParseError(f"invalid argument value: {exc.msg}", line_no, exc.colno) from exc
    refs: list[str] = []
    for item in _split_top_level(inner):
        if _REF_RE.fullmatch(item):
            refs.append(item)
        elif "[" in item or "]" in item:
            raise ParseError(
                f"nested lists are not supported inside a reference list: {item}",
                line_no,
                1,
            )
        else:
            raise ParseError(
                f"reference list mixes typed references and literals: {item}",
                line_no,
                1,
            )
    return refs


def _contains_ref(text: str) -> bool:
    """Whether ``text`` mentions a typed reference outside quoted strings."""
    quoted_stripped: list[str] = []
    quote: str | None = None
    escaped = False
    for char in text:
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        else:
            quoted_stripped.append(char)
    return re.search(rf"(?<![A-Za-z0-9_]){ _REF_PATTERN }(?![A-Za-z0-9_])", "".join(quoted_stripped)) is not None


def _parse_refs(text: str, line_no: int, context: str) -> tuple[str, ...]:
    refs = tuple(part.strip() for part in _split_top_level(text))
    if not refs or any(_REF_RE.fullmatch(ref) is None for ref in refs):
        raise ParseError(f"{context} requires typed references", line_no, 1)
    return refs


def _split_top_level(text: str) -> tuple[str, ...]:
    if not text.strip():
        return ()
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char in "[({":
            depth += 1
        elif char in "])}":
            depth -= 1
            if depth < 0:
                raise ParseError("unbalanced delimiter")
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    if quote is not None or depth != 0:
        raise ParseError("unbalanced argument value")
    parts.append(text[start:].strip())
    if any(not part for part in parts):
        raise ParseError("empty comma-separated item")
    return tuple(parts)


def validate_program(program: Program, known_commands: Iterable[str] | None = None) -> bool:
    """Validate names, reference ordering, commands, and terminal structure."""
    if not isinstance(program, Program):
        raise ParseError("expected Program")
    known = set(known_commands) if known_commands is not None else None
    available: set[str] = set()
    for declaration in program.declarations:
        if declaration.ref in available:
            raise ParseError(f"duplicate declaration {declaration.ref}")
        available.add(declaration.ref)

    steps: set[str] = set()
    terminal = False
    for statement in program.statements:
        if terminal:
            raise ParseError("statement appears after terminal")
        if isinstance(statement, Invocation):
            if statement.step_id in steps:
                raise ParseError(f"duplicate step {statement.step_id}")
            steps.add(statement.step_id)
            if known is not None and statement.command not in known:
                raise ParseError(f"unknown command {statement.command}")
            for argument in statement.args:
                for ref in _references_in(argument.value):
                    if ref not in available:
                        raise ParseError(
                            f"reference {ref} used before definition",
                            argument.line,
                            1,
                        )
            for target in statement.targets:
                if target in available:
                    raise ParseError(f"duplicate target {target}")
                available.add(target)
            if statement.done is not None:
                if statement.done.op not in _DONE_OPS:
                    raise ParseError(
                        f"unknown DONE predicate {statement.done.op}",
                        statement.done.line,
                        5,
                    )
                if statement.done.ref not in statement.targets:
                    raise ParseError(
                        f"DONE reference {statement.done.ref} must be one of the"
                        f" step's targets ({', '.join(statement.targets)})",
                        statement.done.line,
                        5,
                    )
        elif isinstance(statement, Return):
            for ref in statement.refs:
                if ref not in available:
                    raise ParseError(f"unresolved return reference {ref}")
            terminal = True
        elif isinstance(statement, Stop):
            if statement.kind not in _STOP_KINDS:
                raise ParseError(f"invalid STOP kind {statement.kind}")
            if statement.ref is not None and statement.ref not in available:
                raise ParseError(f"unresolved STOP reference {statement.ref}")
            terminal = True
        else:
            raise ParseError(f"unknown statement {type(statement).__name__}")
    if not terminal:
        raise ParseError("program requires a terminal RETURN or STOP")
    return True


def _references_in(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) and _REF_RE.fullmatch(value):
        return (value,)
    if isinstance(value, list):
        return tuple(ref for item in value for ref in _references_in(item))
    if isinstance(value, dict):
        return tuple(ref for item in value.values() for ref in _references_in(item))
    return ()


def canonical_json(program: Program) -> str:
    if not isinstance(program, Program):
        raise ParseError("expected Program")
    payload = {
        "name": program.name,
        "version": program.version,
        "declarations": [dataclasses.asdict(item) for item in program.declarations],
        "statements": [_statement_dict(item) for item in program.statements],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _statement_dict(statement: object) -> dict[str, Any]:
    if isinstance(statement, Invocation):
        # Built field-by-field (not via dataclasses.asdict) so the sealed
        # canonical JSON stays identical to pre-ref-list programs: the
        # Argument.line source location is deliberately not part of the
        # canonical form, exactly like comments and blank lines.
        return {
            "kind": "invocation",
            "step_id": statement.step_id,
            "command": statement.command,
            "args": [
                {"name": argument.name, "value": argument.value}
                for argument in statement.args
            ],
            "targets": list(statement.targets),
            "done": (
                {
                    "op": statement.done.op,
                    "ref": statement.done.ref,
                    "value": statement.done.value,
                }
                if statement.done is not None
                else None
            ),
        }
    if isinstance(statement, Return):
        return {"kind": "return", **dataclasses.asdict(statement)}
    if isinstance(statement, Stop):
        return {"kind": "stop", **dataclasses.asdict(statement)}
    raise ParseError(f"unknown statement {type(statement).__name__}")


def seal_digest(program: Program) -> str:
    return hashlib.sha256(canonical_json(program).encode("utf-8")).hexdigest()
