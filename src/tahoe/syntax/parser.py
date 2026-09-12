"""Parser and sealing helpers for the sequential TAHOE subset."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .model import (
    Argument,
    Call,
    Conditional,
    Declaration,
    DonePredicate,
    Gather,
    Invocation,
    Par,
    ParBranch,
    Program,
    Return,
    Scatter,
    Stop,
)

_NAME = r"[a-z][a-z0-9_]*"
# Program header names allow hyphens after the first character (issue #15).
# Everything else — step ids, typed-reference leaf segments, command names,
# argument names, STOP kinds — keeps the underscore-only _NAME pattern.
_PROGRAM_NAME = r"[a-z][a-z0-9_-]*"
_PREFIX = r"(?:G|Q|CTX|C|P|F|E|A|H|O|K|D|X|V|R|U|OUT|ART|KB)"
_REF_PATTERN = rf"{_PREFIX}\.{_NAME}(?:\.{_NAME})*"
_REF_RE = re.compile(rf"^{_REF_PATTERN}$")
_HEADER_RE = re.compile(rf"^PROGRAM\s+(?P<name>{_PROGRAM_NAME})\s+VERSION\s+(?P<version>\d+(?:\.\d+)*)$")
_DECL_RE = re.compile(rf"^(?P<ref>{_REF_PATTERN})\s*=\s*(?P<value>.+)$")
_STEP_RE = re.compile(
    rf"^(?P<step>step\.{_NAME}):\s*DO\s+(?P<command>{_NAME})"
    rf"\((?P<args>.*)\)\s*->\s*(?P<targets>.+)$"
)
# Correction clause (issue #7): an invocation line may end with an
# optional trailing `REVISE r1, r2 | RETIRE r3, r4` clause — either or
# both pipe-separated groups; when both appear the REVISE group precedes
# the RETIRE group.  Each group is a comma-separated list of typed
# references.  REVISEd refs are set to the step's single target value at
# commit time (so REVISE requires exactly one target); RETIREd refs are
# removed from the projection.  The clause sits after the targets, which
# are pure refs, so the anchored match cannot reach into quoted argument
# text.
_REF_LIST_PATTERN = rf"{_REF_PATTERN}(?:\s*,\s*{_REF_PATTERN})*"
_CORRECTIONS_RE = re.compile(
    rf"\s+(?:(?:REVISE\s+(?P<revise>{_REF_LIST_PATTERN})"
    rf"(?:\s*\|\s*RETIRE\s+(?P<retire_after_revise>{_REF_LIST_PATTERN}))?)"
    rf"|(?:RETIRE\s+(?P<retire>{_REF_LIST_PATTERN})))\s*$"
)
_STOP_RE = re.compile(
    rf"^STOP\s+(?P<kind>{_NAME})\((?P<ref>{_REF_PATTERN})?\)$"
)
# Protocol call (issue #12): CALL protocol.<segments>(args) -> targets.
# The "protocol." prefix is mandatory (docs/spec/01-language-and-state.md:
# protocol = "protocol.", name); the remaining dot-separated segments are
# the protocol file stem under the protocols directory.
_CALL_RE = re.compile(
    rf"^CALL\s+(?P<protocol>protocol\.{_NAME}(?:\.{_NAME})*)"
    rf"\((?P<args>.*)\)\s*->\s*(?P<targets>.+)$"
)
_PROTOCOL_PREFIX = "protocol."
# Bounded recursion (issue #12): at most 8 nested protocol-call levels.
_MAX_PROTOCOL_DEPTH = 8
_PROTOCOLS_DIR_DEFAULT = "protocols"
# Issue #3: IF is no longer reserved — it parses a single-line deterministic
# conditional.  FIRST/LOOP/TRY/AWAIT/APPROVE stay unsupported.  Issue #4:
# SCATTER/GATHER are no longer reserved — they parse bounded fan-out blocks.
_UNSUPPORTED = frozenset({"FIRST", "LOOP", "TRY", "AWAIT", "APPROVE"})
# Issue #4: SCATTER/GATHER block grammar.  The SCATTER line is followed by
# exactly one indented body step line; the GATHER line names that body step
# and optionally a judge step, itself defined by the following indented line.
_SCATTER_RE = re.compile(
    rf"^SCATTER\s+(?P<item>{_REF_PATTERN})\s+IN\s+"
    rf"(?P<collection>{_REF_PATTERN})\s+MAX\s+(?P<max>\d+)$"
)
_GATHER_RE = re.compile(
    rf"^GATHER\s+(?P<step_id>(?:step\.)?{_NAME})\s+AS\s+(?P<alias>{_REF_PATTERN})\s+"
    rf"USING\s+(?P<mode>{_NAME})(?:\s+JUDGE\s+step\.(?P<judge_id>{_NAME}))?$"
)
# Issue #24: PAR block grammar.  The header is ``PAR MAX <n>`` followed by
# two or more indented branch lines (each a full DO invocation or a CALL
# line) and terminated by a matching-dedent BARRIER line that optionally
# declares the published targets.
_PAR_RE = re.compile(rf"^PAR\s+MAX\s+(?P<max>\d+)$")
_BARRIER_RE = re.compile(
    rf"^BARRIER(?:\s*->\s*(?P<targets>{_REF_LIST_PATTERN}))?$"
)
# Canonical join rules (issue #27 naming resolution): the draft spec's
# all/any/ranked are canonical; the issue body's first/best are accepted
# aliases (first == any, best == ranked) normalized at parse time so both
# spellings parse and seal identically.
_GATHER_MODES = frozenset({"all", "any", "ranked"})
_GATHER_MODE_ALIASES = {"first": "any", "best": "ranked"}
_STOP_KINDS = frozenset({"completed", "failed", "blocked", "denied", "cancelled", "unresolved"})
_DONE_OPS = frozenset({"equals", "in", "matched", "ne", "eq_ref", "ne_ref", "count"})
_DONE_MATCHED_RE = re.compile(r"^matched\((?P<inner>.*)\)$", re.DOTALL)
# Issue #3: block forms of the conditional (ELSE, ELSE IF) are out of scope
# and rejected with a dedicated message; the keyword check sees the line's
# first word, so both bare ELSE and "ELSE IF ..." report the ELSE construct.
_ELSE_KEYWORDS = frozenset({"ELSE"})
# Condition grammar (issue #3): ordering operators are only valid on
# count(<ref>); the combined match list is longest-first so "<=" is not
# read as "<".
_CONDITION_ORDER_OPS = ("<=", ">=")
_CONDITION_EQUALITY_OPS = ("==", "!=")
_CONDITION_ALL_OPS = _CONDITION_EQUALITY_OPS + _CONDITION_ORDER_OPS + ("<", ">")
_CONDITION_STEP_RE = re.compile(rf"step\.{_NAME}\s*:")
_JSON_DECODER = json.JSONDecoder()


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


def _strip_trailing_comment(raw: str) -> str:
    """Strip a trailing ``#`` comment outside quotes (issue #37).

    Scans the raw line character by character; when a ``#`` is found
    outside any quote (and not preceded by a non-whitespace character that
    is part of a ref or token), everything from that ``#`` to end-of-line
    is removed.  Quoted-string tracking handles both ``"`` and ``'`` with
    ``\\`` escapes.  A ``#`` inside a JSON literal string is preserved.
    """
    quote: str | None = None
    escaped = False
    for index, char in enumerate(raw):
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
        elif char == "#":
            return raw[:index].rstrip()
    return raw


def _is_unbalanced(text: str) -> bool:
    """Whether *text* has unbalanced brackets or unclosed quotes (issue #37).

    Used to detect multi-line INPUT declarations: when a declaration
    value has open brackets (e.g. ``{"a": [``), the parser accumulates
    subsequent indented lines until brackets and quotes balance.
    """
    quote: str | None = None
    escaped = False
    depth = 0
    for char in text:
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
    return quote is not None or depth != 0


def _done_ref_matches_targets(ref: str, targets: tuple[str, ...]) -> bool:
    """Whether *ref* or its longest dotted prefix matches a target (issue #36).

    A DONE ref like ``V.quality.status`` is valid when ``V.quality`` is a
    target, per the spec's immutable field selection.  The exact ref
    itself may also match a target directly.
    """
    segments = ref.split(".")
    while segments:
        if ".".join(segments) in targets:
            return True
        segments.pop()
    return False


def _resolve_done_target(
    statement: object, line_no: int
) -> tuple[Invocation | None, object]:
    """Find the invocation a DONE line should attach to (issue #36).

    Returns ``(invocation, replace_fn)`` where ``replace_fn(new_invocation)``
    produces the statement object that should replace ``statement`` in the
    program's statement list.  ``None`` means DONE cannot attach here.

    - A bare ``Invocation`` attaches directly.
    - A ``Conditional`` whose embedded statement is an ``Invocation``
      attaches to that embedded invocation.
    - A ``Scatter`` attaches to its body invocation.
    """
    if isinstance(statement, Invocation):
        return statement, lambda inv: inv
    if isinstance(statement, Conditional) and isinstance(statement.statement, Invocation):
        return statement.statement, lambda inv: dataclasses.replace(statement, statement=inv)
    if isinstance(statement, Scatter):
        body = statement.body
        return body, lambda inv: dataclasses.replace(statement, body=inv)
    return None, lambda inv: inv


def parse_program(text: str) -> Program:
    """Parse the canonical one-line sequential MVP syntax."""
    if not isinstance(text, str):
        raise ParseError("source must be text")

    source = []
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = _strip_trailing_comment(raw)
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            continue
        source.append((number, stripped, stripped.strip()))
    if not source:
        raise ParseError("missing PROGRAM header", 1, 1)

    header_line, _, header = source[0]
    match = _HEADER_RE.fullmatch(header)
    if match is None:
        raise ParseError("malformed PROGRAM header", header_line, 1)

    declarations: list[Declaration] = []
    statements: list[Invocation | Return | Stop | Conditional | Scatter | Gather] = []
    in_input = False
    terminal_seen = False

    lines = iter(source[1:])
    while True:
        try:
            line_no, raw, line = next(lines)
        except StopIteration:
            break
        if line == "INPUT":
            if declarations or statements or in_input:
                raise ParseError("INPUT must appear once before statements", line_no, 1)
            in_input = True
            continue

        if in_input and raw[:1].isspace():
            # Issue #37: accumulate multi-line bracket-balanced INPUT
            # values.  A declaration value may span multiple indented
            # lines when it contains bracketed JSON (objects, arrays).
            # We accumulate until brackets and quotes balance, then
            # parse the whole value as one JSON literal.
            decl_line_no = line_no
            decl_raw = raw
            decl_line = line
            while _is_unbalanced(decl_line):
                try:
                    next_line_no, next_raw, next_line = next(lines)
                except StopIteration:
                    raise ParseError(
                        "unbalanced bracket in INPUT declaration",
                        decl_line_no,
                        1,
                    ) from None
                if not next_raw[:1].isspace():
                    raise ParseError(
                        "unbalanced bracket in INPUT declaration"
                        " (continuation line must be indented)",
                        next_line_no,
                        1,
                    )
                decl_raw = decl_raw + "\n" + next_raw
                decl_line = decl_line + " " + next_line
            declaration = _DECL_RE.fullmatch(decl_line.strip())
            if declaration is None:
                raise ParseError(
                    "malformed INPUT declaration",
                    decl_line_no,
                    len(decl_raw) - len(decl_raw.lstrip()) + 1,
                )
            raw_value = declaration.group("value")
            if _detect_single_quoted_string(raw_value):
                raise ParseError(
                    "single-quoted strings are not supported; use double quotes",
                    decl_line_no,
                    1,
                )
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                raise ParseError(
                    f"invalid JSON input value: {exc.msg}",
                    decl_line_no,
                    exc.colno,
                ) from exc
            declarations.append(Declaration(declaration.group("ref"), value))
            continue
        in_input = False

        keyword = line.split(None, 1)[0]
        if keyword in _UNSUPPORTED:
            raise ParseError(f"unsupported control construct {keyword}", line_no, 1)
        if keyword in _ELSE_KEYWORDS:
            # Issue #3: block conditionals (ELSE, ELSE IF) are out of scope.
            raise ParseError("unsupported control construct ELSE", line_no, 1)
        if terminal_seen:
            raise ParseError("statement appears after terminal", line_no, 1)

        if re.match(r"IF\b", line):
            statements.append(_parse_conditional_line(line, line_no))
            continue

        if re.match(r"DONE\b", line):
            expression = line[4:].strip()
            if not expression or not statements:
                raise ParseError("DONE must follow an invocation", line_no, 1)
            # Issue #36: DONE may attach to an Invocation, a Conditional
            # (attaching to the embedded DO invocation), or a Scatter
            # (attaching to the body invocation).  Resolve the target
            # invocation and its parent statement for replacement.
            target_invocation, replace_fn = _resolve_done_target(
                statements[-1], line_no
            )
            if target_invocation is None:
                raise ParseError("DONE must follow an invocation", line_no, 1)
            if target_invocation.done is not None:
                raise ParseError("invocation has more than one DONE expression", line_no, 1)
            predicate = _parse_done_expression(expression, line_no)
            # Issue #36: field-path refs (e.g. V.q.status) are valid when
            # the longest prefix matches one of the step's targets, per
            # the spec's immutable field selection.
            if not _done_ref_matches_targets(predicate.ref, target_invocation.targets):
                raise ParseError(
                    f"DONE reference {predicate.ref} must be one of the step's"
                    f" targets ({', '.join(target_invocation.targets)})",
                    line_no,
                    5,
                )
            updated = dataclasses.replace(target_invocation, done=predicate)
            statements[-1] = replace_fn(updated)
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

        if re.match(r"CALL\b", line):
            call = _CALL_RE.fullmatch(line)
            if call is None:
                raise ParseError("malformed CALL", line_no, 1)
            args = tuple(_parse_argument(item, line_no) for item in _split_top_level(call.group("args"), line_no))
            targets = _parse_refs(call.group("targets"), line_no, "target")
            statements.append(
                Call(call.group("protocol"), args, targets, line_no)
            )
            continue

        # Issue #4: bounded fan-out block.  The SCATTER line consumes the
        # immediately following indented line as its single per-candidate
        # body step; the join is a separate GATHER statement that must
        # directly follow (validated in validate_program).
        if re.match(r"SCATTER\b", line):
            statements.append(_parse_scatter_block(line, line_no, lines))
            continue

        if re.match(r"GATHER\b", line):
            statements.append(_parse_gather_line(line, line_no, lines))
            continue

        # Issue #24: bounded heterogeneous parallel block.  The PAR line
        # consumes the following indented branch lines plus the terminating
        # (matching-dedent) BARRIER line; a stray BARRIER outside a PAR
        # block is rejected here and by validation.
        if re.match(r"PAR\b", line):
            statements.append(_parse_par_block(line, line_no, lines))
            continue

        if re.match(r"BARRIER\b", line):
            raise ParseError(
                "BARRIER is only valid as the terminator of a PAR block",
                line_no,
                1,
            )

        # Issue #7: strip the optional trailing REVISE/RETIRE clause before
        # matching the invocation itself; the clause only ever follows the
        # target refs, so an unmatched clause falls through to the ordinary
        # malformed-invocation / target errors below.  Issue #3 shares the
        # exact same line parser with IF-embedded DO invocations.
        statements.append(_parse_invocation_text(line, line_no))

    program = Program(
        match.group("name"),
        match.group("version"),
        tuple(declarations),
        tuple(statements),
    )
    return program


def _parse_invocation_text(line: str, line_no: int) -> Invocation:
    """Parse one full invocation line (issue #3 extracted the shared body).

    ``step.<id>: DO <command>(args) -> targets`` with the optional trailing
    REVISE/RETIRE correction clause (issue #7).  The clause only ever
    follows the target refs, so an unmatched clause falls through to the
    ordinary malformed-invocation / target errors.
    """
    revisions: tuple[str, ...] = ()
    retirements: tuple[str, ...] = ()
    corrections = _CORRECTIONS_RE.search(line)
    if corrections is not None:
        line = line[:corrections.start()]
        revise_text = corrections.group("revise")
        retire_text = (
            corrections.group("retire_after_revise")
            or corrections.group("retire")
        )
        if revise_text:
            revisions = tuple(
                ref.strip() for ref in revise_text.split(",")
            )
        if retire_text:
            retirements = tuple(
                ref.strip() for ref in retire_text.split(",")
            )
    step = _STEP_RE.fullmatch(line)
    if step is None:
        raise ParseError("malformed invocation", line_no, 1)
    args = tuple(_parse_argument(item, line_no) for item in _split_top_level(step.group("args"), line_no))
    targets = _parse_refs(step.group("targets"), line_no, "target")
    return Invocation(
        step.group("step"),
        step.group("command"),
        args,
        targets,
        revisions=revisions,
        retirements=retirements,
    )


def _parse_conditional_line(line: str, line_no: int) -> Conditional:
    """Parse one ``IF <expr> <statement>`` line (issue #3).

    ``<statement>`` is exactly one of ``STOP <kind>(<ref?>)``, ``RETURN
    <refs>``, or a full ``step.<id>: DO ...`` invocation line.  The raw
    condition text is kept verbatim on the model; the coordinator re-parses
    it with :func:`parse_condition` at evaluation time.
    """
    rest = line[2:].strip()
    _condition_ast, statement_start = _parse_condition_head(rest, line_no)
    # The raw condition text is kept on the model verbatim; validation and
    # the coordinator re-parse it with parse_condition.
    condition = rest[:statement_start].strip()
    statement_text = rest[statement_start:].strip()
    if not statement_text:
        raise ParseError(
            "IF requires a statement (STOP, RETURN, or a DO invocation)",
            line_no,
            len(rest) + 3,
        )
    if re.match(r"STOP\b", statement_text):
        stop = _STOP_RE.fullmatch(statement_text)
        if stop is None:
            raise ParseError("malformed STOP in IF statement", line_no, 1)
        embedded: object = Stop(stop.group("kind"), stop.group("ref"))
    elif re.match(r"RETURN\b", statement_text):
        embedded = Return(_parse_refs(statement_text[6:].strip(), line_no, "RETURN"))
    elif _CONDITION_STEP_RE.match(statement_text):
        embedded = _parse_invocation_text(statement_text, line_no)
    else:
        raise ParseError(
            "IF statement must be STOP, RETURN, or a DO invocation"
            " (step.<id>: DO ...)",
            line_no,
            1,
        )
    return Conditional(condition, embedded, line_no)


def _consume_block_line(
    lines, construct: str, line_no: int
) -> tuple[int, str]:
    """Consume the block line following a SCATTER/GATHER header (issue #4).

    The next significant source line must exist and be indented (mirroring
    INPUT declarations); returns ``(line_no, stripped_text)``.
    """
    try:
        next_line_no, next_raw, next_line = next(lines)
    except StopIteration:
        raise ParseError(
            f"{construct} requires an indented step line", line_no, 1
        ) from None
    if not next_raw[:1].isspace():
        raise ParseError(
            f"{construct} requires an indented step line", next_line_no, 1
        )
    return next_line_no, next_line


def _parse_scatter_block(line: str, line_no: int, lines) -> Scatter:
    """Parse one ``SCATTER <item> IN <collection> MAX <n>`` block (issue #4).

    The header is followed by exactly one indented body step line — the
    per-candidate ``step.<id>: DO ... -> <target>`` invocation.
    """
    match = _SCATTER_RE.fullmatch(line)
    if match is None:
        raise ParseError(
            "malformed SCATTER (expected SCATTER <ref> IN <ref> MAX <int>)",
            line_no,
            1,
        )
    max_count = int(match.group("max"))
    if max_count < 1:
        raise ParseError(
            "SCATTER MAX must be a positive integer", line_no, 1
        )
    body_line_no, body_line = _consume_block_line(
        lines, "SCATTER body step", line_no
    )
    body = _parse_invocation_text(body_line, body_line_no)
    return Scatter(
        match.group("item"),
        match.group("collection"),
        max_count,
        body,
        line_no,
    )


def _parse_gather_line(line: str, line_no: int, lines) -> Gather:
    """Parse one ``GATHER <step-id> AS <alias> USING <rule>`` line (issue #4).

    ``USING`` accepts the canonical rules ``all`` / ``any`` / ``ranked``
    and the aliases ``first`` (== any) and ``best`` (== ranked), normalized
    at parse time.  ``JUDGE step.<id>`` is declared on the line for ranked
    joins and the judge step itself is the immediately following indented
    line, whose step id must match the declared one.
    """
    match = _GATHER_RE.fullmatch(line)
    if match is None:
        raise ParseError(
            "malformed GATHER (expected GATHER <step-id> AS <ref> USING"
            " all|any|ranked [JUDGE step.<id>])",
            line_no,
            1,
        )
    written_mode = match.group("mode")
    mode = _GATHER_MODE_ALIASES.get(written_mode, written_mode)
    if mode not in _GATHER_MODES:
        raise ParseError(
            f"unknown GATHER USING mode {written_mode!r} (expected all,"
            " any, ranked, or the aliases first, best)",
            line_no,
            1,
        )
    # The body step id normalizes to its canonical "step.<id>" spelling;
    # both `GATHER draft AS ...` and `GATHER step.draft AS ...` parse (the
    # draft spec writes the prefixed form, the ADR the bare one).
    body_step_id = match.group("step_id")
    if not body_step_id.startswith("step."):
        body_step_id = f"step.{body_step_id}"
    judge: Invocation | None = None
    judge_id = match.group("judge_id")
    if judge_id is not None:
        judge_line_no, judge_line = _consume_block_line(
            lines, f"GATHER judge step step.{judge_id}", line_no
        )
        judge = _parse_invocation_text(judge_line, judge_line_no)
        if judge.step_id != f"step.{judge_id}":
            raise ParseError(
                f"GATHER JUDGE declares step.{judge_id} but the following"
                f" line defines {judge.step_id}",
                judge_line_no,
                1,
            )
    return Gather(
        body_step_id,
        match.group("alias"),
        mode,
        judge,
        line_no,
    )


def _parse_par_block(line: str, line_no: int, lines) -> Par:
    """Parse one ``PAR MAX <n>`` block (issue #24).

    The header is followed by two or more indented branch lines — each a
    full ``step.<id>: DO ... -> <targets>`` invocation or a
    ``CALL protocol.name(...) -> targets`` line — and terminated by the
    matching-dedent ``BARRIER`` line, which optionally declares the
    published targets (``BARRIER -> t1, t2``).  Branch ids (``par<k>``)
    are positional in source order and assigned by the runtime.
    """
    match = _PAR_RE.fullmatch(line)
    if match is None:
        raise ParseError(
            "malformed PAR (expected PAR MAX <int>)", line_no, 1
        )
    max_count = int(match.group("max"))
    if max_count < 1:
        raise ParseError("PAR MAX must be a positive integer", line_no, 1)
    branches: list[ParBranch] = []
    barrier_targets: tuple[str, ...] = ()
    while True:
        try:
            next_line_no, next_raw, next_line = next(lines)
        except StopIteration:
            raise ParseError(
                "PAR block requires a terminating BARRIER line", line_no, 1
            ) from None
        if next_raw[:1].isspace():
            if re.match(r"CALL\b", next_line):
                call = _CALL_RE.fullmatch(next_line)
                if call is None:
                    raise ParseError("malformed CALL in PAR branch", next_line_no, 1)
                args = tuple(
                    _parse_argument(item, next_line_no)
                    for item in _split_top_level(call.group("args"), next_line_no)
                )
                targets = _parse_refs(call.group("targets"), next_line_no, "target")
                branches.append(
                    ParBranch(call=Call(call.group("protocol"), args, targets, next_line_no))
                )
            else:
                invocation = _parse_invocation_text(next_line, next_line_no)
                branches.append(ParBranch(invocation=invocation, line=next_line_no))
            continue
        barrier = _BARRIER_RE.fullmatch(next_line)
        if barrier is None:
            raise ParseError(
                "PAR block must be terminated by a BARRIER line (bare or"
                " 'BARRIER -> <refs>')",
                next_line_no,
                1,
            )
        if barrier.group("targets") is not None:
            barrier_targets = _parse_refs(
                barrier.group("targets"), next_line_no, "BARRIER target"
            )
        break
    if len(branches) < 2:
        raise ParseError(
            "PAR block requires at least two branch lines", line_no, 1
        )
    return Par(max_count, tuple(branches), barrier_targets, line_no)


def parse_condition(text: str, line_no: int = 0) -> tuple:
    """Parse a deterministic IF-condition expression (issue #3).

    Grammar — comparisons over committed node refs and JSON literals only,
    no worker calls, no parentheses:

    - ``<ref> == <json-literal>``
    - ``<ref> != <json-literal>``
    - ``count(<ref>) <op> <int>``  (op in ``== != < <= > >=``; count reads a
      list-valued reference)
    - ``<term> AND <term>``, ``<term> OR <term>``  (left-associative)
    - ``NOT <term>``  (prefix, repeatable)

    Returns a plain-tuple AST: ``("eq", ref, value)``, ``("ne", ref,
    value)``, ``("count", ref, op, value)``, ``("and", left, right)``,
    ``("or", left, right)``, ``("not", inner)``.  Raises ParseError on
    parentheses, ordering operators on bare refs, and any malformed form.
    The whole text must be one condition — a trailing STOP/RETURN/step
    statement is rejected here (the IF-line parser splits it off first).
    """
    if not isinstance(text, str):
        raise ParseError("IF condition must be text", line_no, 1)
    scanner = _ConditionScanner(text, line_no)
    if not scanner.source:
        raise ParseError("IF condition is empty", line_no, 4)
    return scanner.parse_full_condition()


class _ConditionScanner:
    """Scanner for deterministic IF-condition expressions (issue #3).

    Comparisons over committed node refs and JSON literals, combined with
    left-associative AND/OR and prefix NOT; no parentheses, no worker
    calls.  Two entry points: :meth:`parse_full_condition` requires the
    whole text to be one condition (:func:`parse_condition`), and
    :meth:`parse_condition_prefix` stops at the embedded statement's
    keyword (the IF-line parser).  JSON literals are consumed whole by
    :meth:`parse_comparison`, so statement keywords inside quoted strings
    never confuse the split.
    """

    def __init__(self, text: str, line_no: int) -> None:
        self.source = text.strip()
        self.line_no = line_no
        self.n = len(self.source)
        self.pos = 0

    def skip_spaces(self) -> None:
        while self.pos < self.n and self.source[self.pos].isspace():
            self.pos += 1

    def at_word(self, word: str) -> bool:
        """Whether keyword ``word`` starts at ``pos`` with a word boundary."""
        if not self.source.startswith(word, self.pos):
            return False
        end = self.pos + len(word)
        return end == self.n or self.source[end].isspace()

    def parse_full_condition(self) -> tuple:
        """Parse the whole text as one condition; trailing text is an error."""
        node = self.parse_expression()
        self.skip_spaces()
        if self.pos < self.n:
            raise ParseError(
                f"malformed IF condition near {self.source[self.pos:]!r}",
                self.line_no,
                self.pos + 1,
            )
        return node

    def parse_condition_prefix(self) -> tuple:
        """Parse one condition, stopping at the embedded statement keyword.

        Returns ``(ast, index)`` with ``index`` at the first character of
        the STOP / RETURN / ``step.<id>:`` statement that follows.
        """
        node = self.parse_expression(stop_at_statement=True)
        return node, self.pos

    def parse_expression(self, stop_at_statement: bool = False) -> tuple:
        node = self.parse_term()
        while True:
            self.skip_spaces()
            if self.at_word("AND"):
                self.pos += 3
                node = ("and", node, self.parse_term())
            elif self.at_word("OR"):
                self.pos += 2
                node = ("or", node, self.parse_term())
            else:
                break
        self.skip_spaces()
        if stop_at_statement and self.at_statement_start():
            return node
        if self.pos < self.n:
            raise ParseError(
                f"malformed IF condition near {self.source[self.pos:]!r}",
                self.line_no,
                self.pos + 1,
            )
        return node

    def at_statement_start(self) -> bool:
        """Whether the embedded statement's keyword starts at ``pos``."""
        if self.at_word("STOP") or self.at_word("RETURN"):
            return True
        return _CONDITION_STEP_RE.match(self.source, self.pos) is not None

    def parse_term(self) -> tuple:
        # Each prefix NOT wraps the comparison, so the AST preserves the
        # written structure (NOT NOT x == 1 nests two "not" nodes; its
        # evaluated value is still the comparison's own).
        negations = 0
        while True:
            self.skip_spaces()
            if self.at_word("NOT"):
                negations += 1
                self.pos += 3
            else:
                break
        node = self.parse_comparison()
        for _ in range(negations):
            node = ("not", node)
        return node

    def parse_comparison(self) -> tuple:
        self.skip_spaces()
        if self.pos >= self.n:
            raise ParseError(
                "IF condition requires a comparison", self.line_no, self.pos + 1
            )
        if self.source[self.pos] == "(":
            raise ParseError(
                "parentheses are not supported in IF conditions",
                self.line_no,
                self.pos + 1,
            )
        if self.source.startswith("count(", self.pos):
            return self.parse_count_comparison()
        ref_match = re.compile(_REF_PATTERN).match(self.source, self.pos)
        if ref_match is None:
            raise ParseError(
                "IF condition requires a comparison over a typed reference"
                " or count(<ref>)",
                self.line_no,
                self.pos + 1,
            )
        ref = ref_match.group(0)
        self.pos = ref_match.end()
        self.skip_spaces()
        op = None
        for candidate in _CONDITION_EQUALITY_OPS:
            if self.source.startswith(candidate, self.pos):
                op = candidate
                break
        if op is None:
            for candidate in _CONDITION_ORDER_OPS:
                if self.source.startswith(candidate, self.pos):
                    raise ParseError(
                        f"ordering comparison {candidate} is only supported"
                        " on count(<ref>), not on a bare reference",
                        self.line_no,
                        self.pos + 1,
                    )
            raise ParseError(
                "IF comparison requires == or != on a typed reference",
                self.line_no,
                self.pos + 1,
            )
        self.pos += len(op)
        self.skip_spaces()
        # Issue #36: ref-to-ref comparison — if the RHS is a typed
        # reference, produce an eq_ref/ne_ref node so the coordinator
        # knows to resolve both sides against committed state.
        ref_match = re.compile(_REF_PATTERN).match(self.source, self.pos)
        if ref_match is not None:
            rhs_ref = ref_match.group(0)
            self.pos = ref_match.end()
            return ("eq_ref" if op == "==" else "ne_ref", ref, rhs_ref)
        value, end = _decode_condition_literal(
            self.source, self.pos, self.line_no
        )
        self.pos = end
        return ("eq" if op == "==" else "ne", ref, value)

    def parse_count_comparison(self) -> tuple:
        self.pos += len("count(")
        self.skip_spaces()
        ref_match = re.compile(_REF_PATTERN).match(self.source, self.pos)
        if ref_match is None:
            raise ParseError(
                "count requires a typed reference: count(<ref>)",
                self.line_no,
                self.pos + 1,
            )
        ref = ref_match.group(0)
        self.pos = ref_match.end()
        self.skip_spaces()
        if self.pos >= self.n or self.source[self.pos] != ")":
            raise ParseError(
                "count requires a closing parenthesis: count(<ref>)",
                self.line_no,
                self.pos + 1,
            )
        self.pos += 1
        self.skip_spaces()
        op = _match_condition_op(self.source, self.pos)
        if op is None:
            raise ParseError(
                "count comparison requires one of ==, !=, <, <=, >, >=",
                self.line_no,
                self.pos + 1,
            )
        self.pos += len(op)
        self.skip_spaces()
        value, end = _decode_condition_literal(
            self.source, self.pos, self.line_no
        )
        if isinstance(value, bool) or not isinstance(value, int):
            raise ParseError(
                "count comparison requires an integer literal",
                self.line_no,
                self.pos + 1,
            )
        self.pos = end
        return ("count", ref, op, value)


def _match_condition_op(source: str, pos: int) -> str | None:
    for op in _CONDITION_ALL_OPS:
        if source.startswith(op, pos):
            return op
    return None


def _decode_condition_literal(source: str, pos: int, line_no: int) -> tuple[Any, int]:
    try:
        return _JSON_DECODER.raw_decode(source, pos)
    except json.JSONDecodeError as exc:
        raise ParseError(
            f"invalid JSON literal in IF condition: {exc.msg}", line_no, pos + 1
        ) from exc


def _parse_condition_head(text: str, line_no: int) -> tuple[tuple, int]:
    """Parse the condition prefix of an IF line.

    Returns ``(ast, index)`` where ``index`` points at the embedded
    statement's first keyword (STOP, RETURN, or ``step.<id>:``) in ``text``.
    """
    scanner = _ConditionScanner(text, line_no)
    if not scanner.source:
        raise ParseError("IF condition is empty", line_no, 4)
    return scanner.parse_condition_prefix()


def _condition_refs(node: tuple) -> tuple[str, ...]:
    """Typed references read by a condition AST (issue #3).

    Conditions are evaluated over committed run state, so every ref must
    resolve before the conditional's source position — validation checks
    them like DONE-predicate refs (declared INPUT or an earlier step's
    target), with the spec's immutable field selection: a trailing dotted
    segment may address a field of a committed node.
    """
    kind = node[0]
    if kind in ("eq", "ne", "count"):
        return (node[1],)
    if kind in ("eq_ref", "ne_ref"):
        return (node[1], node[2])
    if kind == "not":
        return _condition_refs(node[1])
    if kind in ("and", "or"):
        return _condition_refs(node[1]) + _condition_refs(node[2])
    raise ParseError(f"unknown condition node {kind!r}")


def _condition_ref_resolvable(ref: str, available: set[str]) -> bool:
    """Whether a condition ref addresses an existing node or a field of one.

    A dotted ref either names a committed node outright or names a field
    path into the longest committed prefix of itself (``V.tests.status``
    reads field ``status`` of node ``V.tests``, per the spec's immutable
    field selection).  Validation therefore accepts a ref when any dotted
    prefix of it is available at the conditional's source position.
    """
    segments = ref.split(".")
    while segments:
        if ".".join(segments) in available:
            return True
        segments.pop()
    return False


def _detect_single_quoted_string(text: str) -> bool:
    """Whether *text* starts with a single-quoted string (issue #37).

    The splitters honor single quotes as quote delimiters, but the value
    decoder uses ``json.loads`` which rejects them.  Detecting a leading
    ``'`` lets us give the author a precise ``use double quotes`` message
    instead of a misleading ``invalid JSON literal`` error.
    """
    stripped = text.strip()
    return stripped.startswith("'")


def _parse_argument(text: str, line_no: int) -> Argument:
    if "=" not in text:
        raise ParseError("argument must be name = value", line_no, 1)
    name, raw_value = (part.strip() for part in text.split("=", 1))
    if re.fullmatch(_NAME, name) is None or not raw_value:
        raise ParseError("malformed named argument", line_no, 1)
    if _REF_RE.fullmatch(raw_value):
        value: Any = raw_value
    elif _detect_single_quoted_string(raw_value):
        raise ParseError(
            "single-quoted strings are not supported; use double quotes",
            line_no,
            1,
        )
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

    Supported forms (issue #36 extends the DONE operators to parity with
    IF-condition comparisons):

    - ``<ref> == <json-literal-or-ref>``  (spec infix equality; ref-to-ref
      via ``eq_ref`` op)
    - ``<ref> != <json-literal-or-ref>``  (not-equals; ref-to-ref via
      ``ne_ref`` op)
    - ``<ref> IN [<json-literal>, ...]``   (spec infix set membership)
    - ``matched(<ref>, "<regex>")``       (deterministic regex predicate)
    - ``count(<ref>) <op> <int>``         (op in ``== != < <= > >=``;
      reuses the condition machinery)

    Field paths (e.g. ``V.quality.status``) are valid typed references;
    the caller validates that the longest prefix of the ref matches one of
    the step's targets (per the spec's immutable field selection).
    """
    text = expression.strip()
    if not text:
        raise ParseError("DONE expression is empty", line_no, 5)

    matched = _DONE_MATCHED_RE.fullmatch(text)
    if matched is not None:
        return _parse_matched_predicate(matched.group("inner"), line_no)

    # Issue #36: count() comparison reuses the condition machinery.
    if text.startswith("count("):
        return _parse_done_count(text, line_no)

    # Issue #36: != operator (not-equals).
    ne_index = _find_top_level(text, "!=")
    if ne_index != -1:
        return _parse_done_comparison(text, ne_index, "!=", "ne", line_no)

    eq_index = _find_top_level(text, "==")
    if eq_index != -1:
        return _parse_done_comparison(text, eq_index, "==", "eq", line_no)

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


def _parse_done_comparison(
    text: str, op_index: int, op_sym: str, op_name: str, line_no: int
) -> DonePredicate:
    """Parse a DONE ``==`` or ``!=`` comparison (issue #36).

    The LHS must be a typed reference (which may be a field path like
    ``V.q.status``).  The RHS is either a JSON literal (``equals`` /
    ``ne`` ops) or a typed reference (``eq_ref`` / ``ne_ref`` ops for
    ref-to-ref comparison).
    """
    lhs = text[:op_index].strip()
    rhs = text[op_index + len(op_sym):].strip()
    if _REF_RE.fullmatch(lhs) is None:
        raise ParseError(
            f"DONE {op_sym} requires a typed reference on the left", line_no, 5
        )
    if not rhs:
        raise ParseError(
            f"DONE {op_sym} requires a JSON literal or typed reference on the right",
            line_no,
            5,
        )
    if _REF_RE.fullmatch(rhs):
        return DonePredicate(
            f"{op_name}_ref" if op_name in ("eq", "ne") else op_name,
            lhs,
            rhs,
            line_no,
        )
    if _detect_single_quoted_string(rhs):
        raise ParseError(
            "single-quoted strings are not supported; use double quotes",
            line_no,
            5,
        )
    try:
        value = json.loads(rhs)
    except json.JSONDecodeError as exc:
        raise ParseError(
            f"invalid JSON literal in DONE expression: {exc.msg}",
            line_no,
            exc.colno,
        ) from exc
    return DonePredicate("equals" if op_name == "eq" else "ne", lhs, value, line_no)


def _parse_done_count(text: str, line_no: int) -> DonePredicate:
    """Parse a DONE ``count(<ref>) <op> <int>`` comparison (issue #36).

    Reuses the condition scanner for consistent parsing, then wraps the
    result as a ``DonePredicate`` with ``op="count"``.
    """
    try:
        ast = parse_condition(text, line_no)
    except ParseError:
        raise ParseError(
            f"unsupported DONE expression: {text}", line_no, 5
        )
    if ast[0] != "count":
        raise ParseError(
            f"unsupported DONE expression: {text}", line_no, 5
        )
    _, ref, op, value = ast
    return DonePredicate("count", ref, (op, value), line_no)


def _parse_matched_predicate(inner: str, line_no: int) -> DonePredicate:
    try:
        items = _split_top_level(inner, line_no)
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
    for item in _split_top_level(inner, line_no):
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
    refs = tuple(part.strip() for part in _split_top_level(text, line_no))
    if not refs:
        raise ParseError(f"{context} requires typed references", line_no, 1)
    for ref in refs:
        if _REF_RE.fullmatch(ref) is not None:
            continue
        # Issue #36: indexed element access (e.g. V.items[0]) is
        # spec-promised but not implemented; give a precise error.
        if "[" in ref and _REF_RE.fullmatch(ref.split("[")[0]) is not None:
            raise ParseError(
                f"indexed element access ({ref}) is not supported;"
                " use a SCATTER to iterate over the collection instead",
                line_no,
                1,
            )
        raise ParseError(f"{context} requires typed references", line_no, 1)
    return refs


def _split_top_level(text: str, line_no: int = 0) -> tuple[str, ...]:
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
                raise ParseError("unbalanced delimiter", line_no, index + 1)
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    if quote is not None or depth != 0:
        raise ParseError("unbalanced argument value", line_no, len(text) + 1)
    parts.append(text[start:].strip())
    if any(not part for part in parts):
        raise ParseError("empty comma-separated item", line_no, 1)
    return tuple(parts)


def validate_program(
    program: Program,
    known_commands: Iterable[str] | None = None,
    protocols_dir: str | Path | None = None,
    _protocol_stack: tuple[str, ...] = (),
) -> bool:
    """Validate names, reference ordering, commands, and terminal structure.

    Programs containing CALL statements additionally validate every
    referenced protocol (issue #12): the protocol file must exist under
    ``protocols_dir`` (default ``protocols/``), parse, and itself validate;
    CALL arguments must resolve like invocation arguments and exactly cover
    the protocol's INPUT leaf names; CALL targets must be a subset of the
    protocol's RETURN refs; and protocols must not call themselves directly
    or transitively, with nested protocol-call chains bounded at depth 8.

    Conditional statements (issue #3) validate their condition's refs at
    the conditional's source position (declared INPUT or an earlier step's
    target) and their embedded statement with the same rules as its bare
    form.  A conditional DO invocation must come after every unconditional
    invocation line; a bare terminal RETURN/STOP is still required (a
    conditional STOP/RETURN is a possible exit, not a guaranteed one).
    """
    if not isinstance(program, Program):
        raise ParseError("expected Program")
    known = set(known_commands) if known_commands is not None else None
    available: set[str] = set()
    for declaration in program.declarations:
        # KB.* is cross-run semantic memory, not run-local state: it cannot
        # be declared in INPUT and resolves from the KnowledgeBase at runtime.
        if declaration.ref.startswith("KB."):
            raise ParseError(
                f"KB reference {declaration.ref} cannot be declared in INPUT:"
                " semantic memory is durable across runs and is read with"
                " recall, not run-local state"
            )
        if declaration.ref in available:
            raise ParseError(f"duplicate declaration {declaration.ref}")
        available.add(declaration.ref)

    steps: set[str] = set()
    conditional_targets: set[str] = set()
    conditional_invocation_seen = False
    terminal = False
    # Issue #4: a SCATTER block must be directly followed by its GATHER.
    pending_scatter: Scatter | None = None
    for statement in program.statements:
        if terminal:
            raise ParseError("statement appears after terminal")
        if pending_scatter is not None and not isinstance(statement, Gather):
            raise ParseError(
                f"SCATTER block for {pending_scatter.body.step_id} must"
                " be directly followed by its GATHER"
            )
        if isinstance(statement, Scatter):
            # Issue #4: the scatter body is an unconditional invocation
            # line, so it cannot follow an IF ... DO conditional.
            if conditional_invocation_seen:
                raise ParseError(
                    f"SCATTER block for {statement.body.step_id}"
                    " appears after an IF ... DO conditional: a conditional"
                    " DO invocation must come after every unconditional"
                    " invocation line"
                )
            _validate_scatter_statement(statement, known, available, steps)
            pending_scatter = statement
        elif isinstance(statement, Par):
            if conditional_invocation_seen:
                raise ParseError(
                    "PAR block appears after an IF ... DO conditional: a"
                    " conditional DO invocation must come after every"
                    " unconditional invocation line"
                )
            _validate_par_statement(
                statement, known, available, steps, protocols_dir,
                _protocol_stack,
            )
            # The branches' targets commit only at the barrier (all-success
            # adoption); after the join, later statements may read them.
            for branch in statement.branches:
                targets = (
                    branch.invocation.targets
                    if branch.invocation is not None
                    else branch.call.targets
                )
                for target in targets:
                    available.add(target)
        elif isinstance(statement, Gather):
            _validate_gather_statement(
                statement, pending_scatter, known, available, steps
            )
            # The alias is the join's committed node: later statements may
            # read it.  The item ref and body/judge targets never join the
            # final namespace (candidate scoping), so they are not added.
            available.add(statement.alias_ref)
            pending_scatter = None
        elif isinstance(statement, Invocation):
            # Issue #3 pragmatic rule: a conditional DO invocation must come
            # after every unconditional invocation line, so an invocation
            # following one is rejected.
            if conditional_invocation_seen:
                raise ParseError(
                    f"unconditional invocation {statement.step_id} appears"
                    " after an IF ... DO conditional: a conditional DO"
                    " invocation must come after every unconditional"
                    " invocation line"
                )
            _validate_invocation_statement(statement, known, available, steps)
        elif isinstance(statement, Call):
            if conditional_invocation_seen:
                raise ParseError(
                    "CALL appears after an IF ... DO conditional: a"
                    " conditional DO invocation must come after every"
                    " unconditional invocation line"
                )
            for argument in statement.args:
                for ref in _references_in(argument.value):
                    # KB.* refs resolve from the KnowledgeBase at dispatch
                    # time, so they need no run-local definition.
                    if ref.startswith("KB."):
                        continue
                    if ref not in available:
                        raise ParseError(
                            f"reference {ref} used before definition",
                            argument.line,
                            1,
                        )
            for target in statement.targets:
                if target.startswith("KB."):
                    raise ParseError(
                        f"KB reference {target} cannot be a CALL target:"
                        " semantic memory is written with the remember command,"
                        " not produced as a state node"
                    )
                if target in available:
                    raise ParseError(f"duplicate target {target}")
                available.add(target)
            _validate_call_contract(
                statement, known, protocols_dir, _protocol_stack
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
        elif isinstance(statement, Conditional):
            # Issue #3: the condition's refs must exist at the conditional's
            # source position — declared INPUT or an earlier step's target —
            # exactly like DONE-predicate refs.  The embedded statement is
            # validated with the same rules as its bare form; a conditional
            # DO invocation's targets are recorded for duplicate detection
            # but never added to `available`, because statically the branch
            # may not run and later statements cannot rely on its nodes.
            condition_ast = parse_condition(statement.condition, statement.line)
            for ref in _condition_refs(condition_ast):
                if not _condition_ref_resolvable(ref, available):
                    raise ParseError(
                        f"IF condition reference {ref} used before definition:"
                        " conditions read committed nodes (a declared INPUT or"
                        " an earlier step's target, or a field of one)",
                        statement.line,
                        1,
                    )
            embedded = statement.statement
            if isinstance(embedded, Invocation):
                _validate_invocation_statement(
                    embedded,
                    known,
                    available,
                    steps,
                    extra_claimed=conditional_targets,
                    commit_targets=False,
                )
                conditional_invocation_seen = True
            elif isinstance(embedded, Return):
                for ref in embedded.refs:
                    if ref not in available:
                        raise ParseError(
                            f"unresolved return reference {ref}",
                            statement.line,
                            1,
                        )
            elif isinstance(embedded, Stop):
                if embedded.kind not in _STOP_KINDS:
                    raise ParseError(
                        f"invalid STOP kind {embedded.kind}", statement.line, 1
                    )
                if embedded.ref is not None and embedded.ref not in available:
                    raise ParseError(
                        f"unresolved STOP reference {embedded.ref}",
                        statement.line,
                        1,
                    )
            else:
                raise ParseError(
                    "IF statement must embed STOP, RETURN, or a DO invocation"
                )
        else:
            raise ParseError(f"unknown statement {type(statement).__name__}")
    if pending_scatter is not None:
        raise ParseError(
            f"SCATTER block for {pending_scatter.body.step_id} must"
            " be directly followed by its GATHER"
        )
    if not terminal:
        raise ParseError("program requires a terminal RETURN or STOP")
    return True


def _validate_invocation_statement(
    statement: Invocation,
    known: set[str] | None,
    available: set[str],
    steps: set[str],
    extra_claimed: set[str] | None = None,
    *,
    commit_targets: bool = True,
) -> None:
    """Validate one invocation statement (issue #3 extracted the shared body).

    Used for bare invocations and for invocations embedded in an ``IF``
    conditional.  ``commit_targets=False`` (the IF-DO case) checks a
    conditional target for duplicates against ``available`` and
    ``extra_claimed`` (targets of earlier conditional invocations) but never
    adds it to ``available``: statically the branch may not run, so later
    statements cannot rely on its nodes.  Step ids are recorded in
    ``steps`` either way, keeping ids unique across bare and conditional
    invocations.
    """
    if statement.step_id in steps:
        raise ParseError(f"duplicate step {statement.step_id}")
    steps.add(statement.step_id)
    if known is not None and statement.command not in known:
        raise ParseError(f"unknown command {statement.command}")
    for argument in statement.args:
        for ref in _references_in(argument.value):
            # KB.* refs resolve from the KnowledgeBase at dispatch
            # time, so they need no run-local definition.
            if ref.startswith("KB."):
                continue
            if ref not in available:
                raise ParseError(
                    f"reference {ref} used before definition",
                    argument.line,
                    1,
                )
    # Issue #7: correction-clause validation, kept pragmatic:
    # every revised/retired ref must be an existing node (declared
    # in INPUT or produced by an earlier step), may not be the
    # step's own target, and no ref may appear in both groups;
    # KB.* refs are cross-run semantic memory, never run-local
    # nodes.  REVISE pins the step to a single target because the
    # revised nodes receive that target's value.  Whether a
    # RETIREd ref is still RETURNed on this path remains the
    # programmer's responsibility.
    if statement.revisions and len(statement.targets) != 1:
        raise ParseError(
            f"REVISE on {statement.step_id} requires exactly one"
            " target (revised nodes are set to the step's single"
            f" target value); got {len(statement.targets)}"
        )
    for kind, refs in (
        ("REVISE", statement.revisions),
        ("RETIRE", statement.retirements),
    ):
        for ref in refs:
            if ref.startswith("KB."):
                raise ParseError(
                    f"{kind} reference {ref} cannot correct KB.*"
                    " nodes: semantic memory is durable across runs"
                    " and is written with remember, not revised"
                )
            if ref in statement.targets:
                raise ParseError(
                    f"{kind} reference {ref} is one of the step's"
                    " own targets; corrections apply to earlier"
                    " nodes only"
                )
            if ref not in available:
                raise ParseError(
                    f"{kind} reference {ref} used before definition:"
                    " corrections must name an existing node"
                    " (a declared INPUT or an earlier step's target)"
                )
    overlap = sorted(
        set(statement.revisions) & set(statement.retirements)
    )
    if overlap:
        raise ParseError(
            f"reference(s) {', '.join(overlap)} appear in both"
            " REVISE and RETIRE"
        )
    for target in statement.targets:
        if target.startswith("KB."):
            raise ParseError(
                f"KB reference {target} cannot be an invocation target:"
                " semantic memory is written with the remember command,"
                " not produced as a state node"
            )
        if target in available or (
            extra_claimed is not None and target in extra_claimed
        ):
            raise ParseError(f"duplicate target {target}")
        if commit_targets:
            available.add(target)
        elif extra_claimed is not None:
            extra_claimed.add(target)
    if statement.done is not None:
        if statement.done.op not in _DONE_OPS:
            raise ParseError(
                f"unknown DONE predicate {statement.done.op}",
                statement.done.line,
                5,
            )
        # Issue #36: field-path refs (e.g. V.q.status) are valid when
        # the longest prefix matches one of the step's targets.
        if not _done_ref_matches_targets(statement.done.ref, statement.targets):
            raise ParseError(
                f"DONE reference {statement.done.ref} must be one of the"
                f" step's targets ({', '.join(statement.targets)})",
                statement.done.line,
                5,
            )
        # Issue #36: ref-to-ref DONE ops (eq_ref, ne_ref) — the RHS ref
        # must resolve like any other typed reference at the step's
        # position.  The count op stores (op, value) as its value, so
        # no ref validation is needed for count or the standard ops.
        if statement.done.op in ("eq_ref", "ne_ref"):
            rhs_ref = statement.done.value
            if isinstance(rhs_ref, str) and _REF_RE.fullmatch(rhs_ref):
                if rhs_ref.startswith("KB."):
                    pass
                elif not _condition_ref_resolvable(rhs_ref, available):
                    raise ParseError(
                        f"DONE reference {rhs_ref} used before definition:"
                        " ref-to-ref DONE comparisons read committed nodes"
                        " (a declared INPUT or an earlier step's target,"
                        " or a field of one)",
                        statement.done.line,
                        5,
                    )


def _validate_scatter_statement(
    statement: Scatter,
    known: set[str] | None,
    available: set[str],
    steps: set[str],
) -> None:
    """Validate one SCATTER block (issue #4).

    The collection ref must name an existing committed node (declared
    INPUT or an earlier step's target) — its runtime list-ness is checked
    at execution.  The item ref is a fresh loop variable: it binds inside
    the body step only, never collides with an existing node, and never
    joins the final namespace.  The body step validates like a normal
    invocation over ``available | {item_ref}`` but its targets are
    candidate-scoped (never committed to the raw names), so they are
    checked for freshness only; REVISE/RETIRE corrections are undefined
    per candidate and rejected, and duplicate target leaves would collide
    in the ``alias.c<k>.<leaf>`` namespace and are rejected too.
    """
    if statement.max_count < 1:
        raise ParseError("SCATTER MAX must be a positive integer")
    for name, ref in (("item", statement.item_ref), ("collection", statement.collection_ref)):
        if ref.startswith("KB."):
            raise ParseError(
                f"SCATTER {name} reference {ref} cannot address KB.*"
                " nodes: semantic memory is durable across runs and is"
                " read with recall, not scattered over"
            )
    if statement.collection_ref not in available:
        raise ParseError(
            f"SCATTER collection {statement.collection_ref} used before"
            " definition: it must name a committed node (a declared INPUT"
            " or an earlier step's target)"
        )
    if statement.item_ref in available:
        raise ParseError(
            f"SCATTER item reference {statement.item_ref} is already"
            " defined: the item ref is a fresh loop-scoped name"
        )
    if statement.item_ref == statement.collection_ref:
        raise ParseError(
            f"SCATTER item reference {statement.item_ref} must differ from"
            " the collection reference"
        )
    body = statement.body
    if statement.item_ref in body.targets:
        raise ParseError(
            f"SCATTER body target {statement.item_ref} cannot overwrite the"
            " item reference"
        )
    _validate_invocation_statement(
        body,
        known,
        available | {statement.item_ref},
        steps,
        commit_targets=False,
    )
    if body.revisions or body.retirements:
        raise ParseError(
            f"SCATTER body step {body.step_id} cannot use REVISE/RETIRE:"
            " corrections are undefined for per-candidate execution"
        )
    leaves = [target.split(".")[-1] for target in body.targets]
    duplicate_leaves = sorted({leaf for leaf in leaves if leaves.count(leaf) > 1})
    if duplicate_leaves:
        raise ParseError(
            f"SCATTER body step {body.step_id} has duplicate target leaves"
            f" ({', '.join(duplicate_leaves)}): candidate nodes are scoped"
            " as alias.c<k>.<leaf> and must not collide"
        )


def _validate_gather_statement(
    statement: Gather,
    pending_scatter: Scatter | None,
    known: set[str] | None,
    available: set[str],
    steps: set[str],
) -> None:
    """Validate one GATHER join (issue #4).

    The GATHER must directly follow its SCATTER block and name that block's
    body step id.  The alias is a fresh committed node name.  ``USING
    ranked`` requires the judge step; the judge is invalid for the other
    rules.  The judge step validates like an invocation over ``available |
    {item_ref} | body targets`` (the judge reads the candidate's item value
    and produced values), must have exactly one target (the score), and
    never commits nodes — its targets stay template-scoped.
    """
    if pending_scatter is None:
        raise ParseError(
            f"GATHER of {statement.body_step_id} must directly follow"
            " its SCATTER block"
        )
    scatter = pending_scatter
    if statement.body_step_id != scatter.body.step_id:
        raise ParseError(
            f"GATHER names {statement.body_step_id} but the preceding"
            f" SCATTER body is {scatter.body.step_id}"
        )
    if statement.mode not in _GATHER_MODES:
        raise ParseError(
            f"unknown GATHER USING mode {statement.mode!r} (expected all,"
            " any, ranked, or the aliases first, best)"
        )
    alias = statement.alias_ref
    if alias.startswith("KB."):
        raise ParseError(
            f"GATHER alias {alias} cannot address KB.* nodes: semantic"
            " memory is written with the remember command, not produced"
            " as a state node"
        )
    if alias in available:
        raise ParseError(f"duplicate target {alias}")
    if alias == scatter.item_ref or alias in scatter.body.targets:
        raise ParseError(
            f"GATHER alias {alias} collides with the scatter's item or"
            " body target references"
        )
    if statement.mode == "ranked" and statement.judge is None:
        raise ParseError(
            "GATHER USING ranked requires JUDGE step.<id>"
        )
    if statement.mode != "ranked" and statement.judge is not None:
        raise ParseError(
            "GATHER JUDGE is only valid with USING ranked (or its alias"
            " best)"
        )
    if statement.judge is not None:
        judge = statement.judge
        bindings = (
            available | {scatter.item_ref} | set(scatter.body.targets)
        )
        _validate_invocation_statement(
            judge, known, bindings, steps, commit_targets=False
        )
        if judge.revisions or judge.retirements:
            raise ParseError(
                f"GATHER judge step {judge.step_id} cannot use"
                " REVISE/RETIRE: the judge is a scoring template"
            )
        if len(judge.targets) != 1:
            raise ParseError(
                f"GATHER judge step {judge.step_id} must have exactly one"
                f" target (the score); got {len(judge.targets)}"
            )
        if judge.targets[0] == scatter.item_ref or (
            judge.targets[0] in scatter.body.targets
        ):
            raise ParseError(
                f"GATHER judge target {judge.targets[0]} collides with the"
                " scatter's item or body target references"
            )


def _validate_par_statement(
    statement: Par,
    known: set[str] | None,
    available: set[str],
    steps: set[str],
    protocols_dir: str | Path | None,
    stack: tuple[str, ...],
) -> None:
    """Validate one PAR block (issue #24).

    Every branch line validates like its bare form against the namespace
    available BEFORE the block (sibling-output reads before the join are
    rejected: branch targets never join ``available`` during branch
    validation).  Branch DO invocations may not use REVISE/RETIRE —
    corrections address parent-namespace nodes while a branch's state is
    isolated.  Target checks: every branch target is a fresh name (no
    collision with the parent namespace, no two branches producing the
    same target — "duplicate parent output targets" fail validation), and
    a declared ``BARRIER -> ...`` target list must equal the union of the
    branches' targets exactly, pinning the explicit adoption mapping.
    """
    if statement.max_count < 1:
        raise ParseError("PAR MAX must be a positive integer")
    if len(statement.branches) < 2:
        raise ParseError("PAR block requires at least two branch lines")
    produced: list[tuple[int, tuple[str, ...]]] = []
    for position, branch in enumerate(statement.branches, 1):
        if branch.invocation is not None:
            if branch.invocation.revisions or branch.invocation.retirements:
                raise ParseError(
                    f"PAR branch {branch.invocation.step_id} cannot use"
                    " REVISE/RETIRE: corrections address parent-namespace"
                    " nodes while a branch's state is isolated"
                )
            _validate_invocation_statement(
                branch.invocation, known, available, steps,
                commit_targets=False,
            )
            produced.append((position, branch.invocation.targets))
        else:
            call = branch.call
            for argument in call.args:
                for ref in _references_in(argument.value):
                    if ref.startswith("KB."):
                        continue
                    if ref not in available:
                        raise ParseError(
                            f"reference {ref} used before definition"
                            f" (PAR branch {position})",
                            argument.line,
                            1,
                        )
            _validate_call_contract(call, known, protocols_dir, stack)
            produced.append((position, call.targets))
    seen: dict[str, int] = {}
    for position, targets in produced:
        for target in targets:
            if target.startswith("KB."):
                raise ParseError(
                    f"PAR branch {position} target {target} cannot address"
                    " KB.* nodes: semantic memory is written with the"
                    " remember command, not produced as a state node"
                )
            if target in available:
                raise ParseError(f"duplicate target {target}")
            if target in seen:
                raise ParseError(
                    f"duplicate target {target}: branches {seen[target]}"
                    f" and {position} both produce it; duplicate parent"
                    " output targets are rejected"
                )
            seen[target] = position
    if statement.barrier_targets:
        union = sorted(seen)
        declared = sorted(statement.barrier_targets)
        if declared != union:
            raise ParseError(
                "BARRIER targets must be exactly the union of the PAR"
                f" branches' targets ({', '.join(union)}); declared:"
                f" {', '.join(declared)}"
            )


def _validate_call_contract(
    call: Call,
    known_commands: Iterable[str] | None,
    protocols_dir: str | Path | None,
    stack: tuple[str, ...],
) -> None:
    """Validate one CALL statement against its protocol file (issue #12).

    Enforces, in order: bounded recursion (no direct or transitive
    self-call, nesting depth at most 8), protocol existence, the protocol
    itself linting/validating, argument arity against the protocol's INPUT
    leaf names, and CALL targets being a subset of the protocol's RETURN
    refs.
    """
    if call.protocol in stack:
        chain = " -> ".join(stack + (call.protocol,))
        raise ParseError(
            f"recursive protocol call: {call.protocol} calls itself directly"
            f" or transitively ({chain})"
        )
    if len(stack) >= _MAX_PROTOCOL_DEPTH:
        chain = " -> ".join(stack + (call.protocol,))
        raise ParseError(
            f"protocol call depth exceeds limit {_MAX_PROTOCOL_DEPTH} ({chain})"
        )

    protocol = load_protocol(call.protocol, protocols_dir)
    try:
        validate_program(
            protocol,
            known_commands=known_commands,
            protocols_dir=protocols_dir,
            _protocol_stack=stack + (call.protocol,),
        )
    except ParseError as exc:
        raise ParseError(f"protocol {call.protocol} is invalid: {exc}") from exc

    return_statement = next(
        (
            statement
            for statement in protocol.statements
            if isinstance(statement, Return)
        ),
        None,
    )
    if return_statement is None:
        raise ParseError(
            f"protocol {call.protocol} must end with RETURN (a CALL commits"
            " the protocol's RETURN refs to the caller's targets)"
        )
    if not any(
        isinstance(statement, (Invocation, Scatter, Par))
        for statement in protocol.statements
    ):
        raise ParseError(
            f"protocol {call.protocol} contains no invocations to execute"
        )

    # Argument arity: CALL args bind the protocol's INPUT declarations by
    # leaf name (argument names are plain identifiers, INPUT refs are typed),
    # so every INPUT must be bound exactly once and no unknown args may exist.
    input_leaves = [declaration.ref.split(".")[-1] for declaration in protocol.declarations]
    ambiguous = sorted({leaf for leaf in input_leaves if input_leaves.count(leaf) > 1})
    if ambiguous:
        raise ParseError(
            f"protocol {call.protocol} INPUT declarations have ambiguous leaf"
            f" names: {', '.join(ambiguous)}"
        )
    arg_names = [argument.name for argument in call.args]
    duplicated = sorted({name for name in arg_names if arg_names.count(name) > 1})
    if duplicated:
        raise ParseError(
            f"CALL {call.protocol} has duplicate arguments: {', '.join(duplicated)}"
        )
    missing = [leaf for leaf in input_leaves if leaf not in arg_names]
    if missing:
        raise ParseError(
            f"CALL {call.protocol} is missing arguments for protocol INPUT:"
            f" {', '.join(missing)}"
        )
    unknown = [name for name in arg_names if name not in input_leaves]
    if unknown:
        raise ParseError(
            f"CALL {call.protocol} has arguments matching no protocol INPUT:"
            f" {', '.join(unknown)}"
        )

    # Target contract: CALL targets are a subset of the protocol's RETURN
    # refs, so each committed target is a ref the protocol actually returns.
    uncovered = [target for target in call.targets if target not in return_statement.refs]
    if uncovered:
        raise ParseError(
            f"CALL {call.protocol} targets must be a subset of the protocol"
            f" RETURN refs ({', '.join(return_statement.refs)}):"
            f" uncovered {', '.join(uncovered)}"
        )


def protocol_file_path(
    name: str, protocols_dir: str | Path | None = None
) -> Path:
    """Filesystem path of the protocol referenced as ``protocol.<stem>``.

    The ``protocol.`` prefix is mandatory; the remaining dot-separated
    segments form the file stem, so ``protocol.framing`` maps to
    ``<protocols_dir>/framing.think`` and ``protocol.ops.framing`` maps to
    ``<protocols_dir>/ops.framing.think``.  ``protocols_dir`` defaults to
    ``protocols/`` under the current working directory.
    """
    if not isinstance(name, str) or not name.startswith(_PROTOCOL_PREFIX):
        raise ParseError(
            f"protocol reference {name!r} must start with {_PROTOCOL_PREFIX!r}"
        )
    stem = name[len(_PROTOCOL_PREFIX):]
    directory = (
        Path(protocols_dir)
        if protocols_dir is not None
        else Path(_PROTOCOLS_DIR_DEFAULT)
    )
    return directory / f"{stem}.think"


def load_protocol(name: str, protocols_dir: str | Path | None = None) -> Program:
    """Deterministically load and parse a protocol program by reference name.

    Loading is deterministic: the same name and protocols directory always
    yield the same parsed program.  A caller's seal composition changes when
    a protocol changes (composite seal hashing is deliberately not
    implemented); callers must re-seal after editing a protocol.
    """
    path = protocol_file_path(name, protocols_dir)
    if not path.is_file():
        raise ParseError(f"protocol {name} not found: expected file {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParseError(f"cannot read protocol {name} from {path}: {exc}") from exc
    try:
        return parse_program(text)
    except ParseError as exc:
        raise ParseError(f"protocol {name} failed to parse: {exc}") from exc


def is_typed_reference(value: object) -> bool:
    """Whether ``value`` is a syntactically valid typed reference.

    Exported for the coordinator's dispatch guard (issue #7): a ref-shaped
    argument string that no longer resolves must fail the invocation
    clearly instead of passing the raw ref string through as a literal.
    """
    return isinstance(value, str) and _REF_RE.fullmatch(value) is not None


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
        # canonical form, exactly like comments and blank lines.  The
        # issue #7 correction clause joins the canonical form only when
        # present, keeping every pre-existing seal digest unchanged.
        entry: dict[str, Any] = {
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
        if statement.revisions:
            entry["revisions"] = list(statement.revisions)
        if statement.retirements:
            entry["retirements"] = list(statement.retirements)
        return entry
    if isinstance(statement, Call):
        # Like invocations, the source line is not part of the canonical form.
        return {
            "kind": "call",
            "protocol": statement.protocol,
            "args": [
                {"name": argument.name, "value": argument.value}
                for argument in statement.args
            ],
            "targets": list(statement.targets),
        }
    if isinstance(statement, Return):
        return {"kind": "return", **dataclasses.asdict(statement)}
    if isinstance(statement, Stop):
        return {"kind": "stop", **dataclasses.asdict(statement)}
    if isinstance(statement, Conditional):
        # Issue #3: the source line is not part of the canonical form (like
        # invocations and calls), so pre-IF programs seal byte-identically
        # and a conditional's seal depends only on its condition text and
        # embedded statement.
        return {
            "kind": "conditional",
            "condition": statement.condition,
            "statement": _statement_dict(statement.statement),
        }
    if isinstance(statement, Scatter):
        # Issue #4: the source line is not part of the canonical form; the
        # block seals as its header fields plus the body invocation.
        return {
            "kind": "scatter",
            "item_ref": statement.item_ref,
            "collection_ref": statement.collection_ref,
            "max": statement.max_count,
            "body": _statement_dict(statement.body),
        }
    if isinstance(statement, Par):
        # Issue #24: the source line is not part of the canonical form;
        # the block seals as its header fields, the branch statements in
        # source order (branch ids are positional), and the declared
        # barrier targets in their written order.
        return {
            "kind": "par",
            "max": statement.max_count,
            "branches": [
                _statement_dict(
                    branch.invocation if branch.invocation is not None
                    else branch.call
                )
                for branch in statement.branches
            ],
            "barrier": list(statement.barrier_targets),
        }
    if isinstance(statement, Gather):
        # Issue #4: the mode serializes in its canonical spelling (first/
        # best normalize to any/ranked at parse time), so both spellings
        # of the same rule seal identically.
        return {
            "kind": "gather",
            "step_id": statement.body_step_id,
            "alias": statement.alias_ref,
            "mode": statement.mode,
            "judge": (
                _statement_dict(statement.judge)
                if statement.judge is not None
                else None
            ),
        }
    raise ParseError(f"unknown statement {type(statement).__name__}")


def seal_digest(program: Program, version: int = 1) -> str:
    if version == 1:
        return hashlib.sha256(canonical_json(program).encode("utf-8")).hexdigest()
    if version == 2:
        return hashlib.sha256(canonical_json_v2(program).encode("utf-8")).hexdigest()
    raise ParseError(f"unknown seal digest version {version}")


def _condition_ast_to_canonical(node: tuple) -> list:
    """Serialize a condition AST tuple into a canonical JSON-serializable list.

    The AST is already plain tuples of strings and JSON literals; we convert
    each node to a list tagged by its operation name so ``json.dumps`` with
    ``sort_keys=True`` produces a deterministic byte sequence independent of
    source-text spacing or keyword capitalization.
    """
    kind = node[0]
    if kind == "eq":
        return ["eq", node[1], node[2]]
    if kind == "ne":
        return ["ne", node[1], node[2]]
    if kind == "eq_ref":
        return ["eq_ref", node[1], node[2]]
    if kind == "ne_ref":
        return ["ne_ref", node[1], node[2]]
    if kind == "count":
        return ["count", node[1], node[2], node[3]]
    if kind == "not":
        return ["not", _condition_ast_to_canonical(node[1])]
    if kind in ("and", "or"):
        return [kind, _condition_ast_to_canonical(node[1]), _condition_ast_to_canonical(node[2])]
    raise ParseError(f"unknown condition node {kind!r}")


def _statement_dict_v2(statement: object) -> dict[str, Any]:
    """V2 canonical serialization: condition AST instead of raw text,
    barrier normalized to the sorted branch-target union."""
    if isinstance(statement, Conditional):
        ast = parse_condition(statement.condition)
        condition_repr = _condition_ast_to_canonical(ast)
        return {
            "kind": "conditional",
            "condition": condition_repr,
            "statement": _statement_dict_v2(statement.statement),
        }
    if isinstance(statement, Par):
        branch_targets: list[str] = []
        for branch in statement.branches:
            inner = branch.invocation if branch.invocation is not None else branch.call
            branch_targets.extend(inner.targets)
        normalized_barrier = sorted(branch_targets)
        return {
            "kind": "par",
            "max": statement.max_count,
            "branches": [
                _statement_dict_v2(
                    branch.invocation if branch.invocation is not None
                    else branch.call
                )
                for branch in statement.branches
            ],
            "barrier": normalized_barrier,
        }
    if isinstance(statement, Invocation):
        entry: dict[str, Any] = {
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
        if statement.revisions:
            entry["revisions"] = list(statement.revisions)
        if statement.retirements:
            entry["retirements"] = list(statement.retirements)
        return entry
    if isinstance(statement, Call):
        return {
            "kind": "call",
            "protocol": statement.protocol,
            "args": [
                {"name": argument.name, "value": argument.value}
                for argument in statement.args
            ],
            "targets": list(statement.targets),
        }
    if isinstance(statement, Return):
        return {"kind": "return", **dataclasses.asdict(statement)}
    if isinstance(statement, Stop):
        return {"kind": "stop", **dataclasses.asdict(statement)}
    if isinstance(statement, Scatter):
        return {
            "kind": "scatter",
            "item_ref": statement.item_ref,
            "collection_ref": statement.collection_ref,
            "max": statement.max_count,
            "body": _statement_dict_v2(statement.body),
        }
    if isinstance(statement, Gather):
        return {
            "kind": "gather",
            "step_id": statement.body_step_id,
            "alias": statement.alias_ref,
            "mode": statement.mode,
            "judge": (
                _statement_dict_v2(statement.judge)
                if statement.judge is not None
                else None
            ),
        }
    raise ParseError(f"unknown statement {type(statement).__name__}")


def canonical_json_v2(program: Program) -> str:
    """V2 canonical JSON: serializes the parsed condition AST (instead of
    raw condition text) and normalizes barrier spelling to the sorted union
    of branch targets, so programs differing only in condition spacing or
    barrier spelling seal identically."""
    if not isinstance(program, Program):
        raise ParseError("expected Program")
    payload = {
        "name": program.name,
        "version": program.version,
        "declarations": [dataclasses.asdict(item) for item in program.declarations],
        "statements": [_statement_dict_v2(item) for item in program.statements],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
