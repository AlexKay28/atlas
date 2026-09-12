"""Focused tests for the canonical tikhon syntax.

Grammar under test (the API expected from tikhon.syntax):

    PROGRAM <name> VERSION <semver>

    INPUT
      <typed-ref> = <json-value>
    ...

    <step-id>: DO <command>(<name> = <json-or-ref>, ...) -> <event>
    DONE <expression>

    RETURN <event>
    STOP <kind>(<ref>)

- INPUT declares typed JSON values directly under typed references.
- Step-produced events are E.<name>; STOP reasons use U.<ref>.
- Argument values are JSON literals (number, string, boolean, array,
  object) or dotted refs; commas inside JSON never split arguments.
- A DONE line attaches its expression to the immediately preceding step.
- RETURN and STOP are terminal; no statement may follow either.
- '#' starts a comment; blank lines are ignored everywhere.
"""

import dataclasses

import pytest

from tikhon.syntax import (
    Invocation,
    ParseError,
    Program,
    Return,
    parse_program,
    seal_digest,
    validate_program,
)

CANONICAL = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {"request": "ship"}
  U.reason = "not enough evidence"

step.one: DO define(value = G.goal, limit = 2) -> E.result
DONE E.result.ok

RETURN E.result
"""

STOP_PROGRAM = """\
PROGRAM guard VERSION 0.1

INPUT
  G.reason = "guard failed"
  U.reason = "not enough evidence"

step.one: DO define(value = G.reason) -> E.detail
STOP blocked(U.reason)
"""


def test_canonical_program_header_and_typed_inputs():
    program = parse_program(CANONICAL)
    assert isinstance(program, Program)
    assert program.name == "demo"
    assert program.version == "0.1"
    assert [(item.ref, item.value) for item in program.declarations] == [
        ("G.goal", {"request": "ship"}),
        ("U.reason", "not enough evidence"),
    ]


def test_ast_nodes_are_frozen_dataclasses():
    program = parse_program(CANONICAL)
    step = program.statements[0]
    stop = parse_program(STOP_PROGRAM).statements[-1]
    assert dataclasses.is_dataclass(program)
    assert dataclasses.is_dataclass(step)
    assert dataclasses.is_dataclass(stop)
    with pytest.raises(dataclasses.FrozenInstanceError):
        program.name = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        step.command = "other"


def test_one_line_step_and_done_expression():
    program = parse_program(CANONICAL)
    step = program.statements[0]
    assert isinstance(step, Invocation)
    assert step.step_id == "step.one"
    assert step.command == "define"
    assert [(arg.name, arg.value) for arg in step.args] == [
        ("value", "G.goal"),
        ("limit", 2),
    ]
    assert step.targets == ("E.result",)
    assert step.done == "E.result.ok"


def test_return_statement_refs():
    program = parse_program(CANONICAL)
    ret = program.statements[-1]
    assert isinstance(ret, Return)
    assert ret.refs == ("E.result",)


def test_stop_statement_kind_and_ref():
    program = parse_program(STOP_PROGRAM)
    stop = program.statements[-1]
    assert type(stop).__name__ == "Stop"
    assert stop.kind == "blocked"
    assert stop.ref == "U.reason"


def test_seal_digest_ignores_comments_and_blank_lines():
    decorated = """\
# demo program

PROGRAM demo VERSION 0.1

# inputs
INPUT
  G.goal = {"request": "ship"}

  U.reason = "not enough evidence"

# one step
step.one: DO define(value = G.goal, limit = 2) -> E.result
DONE E.result.ok

RETURN E.result
"""
    base = seal_digest(parse_program(CANONICAL))
    assert seal_digest(parse_program(decorated)) == base
    tweaked = CANONICAL.replace("limit = 2", "limit = 3")
    assert seal_digest(parse_program(tweaked)) != base


def test_malformed_header_error_location():
    with pytest.raises(ParseError, match="header") as excinfo:
        parse_program("# lead comment\n\nPROGRAMM demo VERSION 0.1\nRETURN E.result\n")
    assert excinfo.value.line == 3
    with pytest.raises(ParseError, match="header") as excinfo:
        parse_program("step.one: DO ping() -> E.pong\n")
    assert excinfo.value.line == 1


def test_unsupported_if_construct():
    source = CANONICAL.replace(
        "RETURN E.result",
        "IF G.goal THEN RETURN E.result",
    )
    with pytest.raises(ParseError, match=r"\bIF\b"):
        parse_program(source)


def test_unknown_command_rejected_by_validation():
    source = CANONICAL.replace("DO define(", "DO fizz(")
    program = parse_program(source)
    with pytest.raises(ParseError, match="fizz"):
        validate_program(program, known_commands={"define"})


def test_duplicate_step_id_rejected_by_validation():
    source = CANONICAL.replace(
        "RETURN E.result",
        "step.one: DO ping() -> E.pong\n\nRETURN E.result",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="duplicate"):
        validate_program(program)


def test_unresolved_typed_reference_rejected_by_validation():
    source = CANONICAL.replace("value = G.goal", "value = G.nope")
    program = parse_program(source)
    with pytest.raises(ParseError, match="nope"):
        validate_program(program)


def test_commas_inside_json_arguments_do_not_split():
    source = CANONICAL.replace(
        "DO define(value = G.goal, limit = 2)",
        'DO define(items = [1, 2], label = "a, b", flag = true)',
    )
    program = parse_program(source)
    step = program.statements[0]
    assert [(arg.name, arg.value) for arg in step.args] == [
        ("items", [1, 2]),
        ("label", "a, b"),
        ("flag", True),
    ]


@pytest.mark.parametrize("terminal", ["RETURN E.result", "STOP blocked(U.reason)"])
def test_statement_after_terminal_rejected(terminal):
    source = f"""\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {{"request": "ship"}}
  U.reason = "not enough evidence"

step.one: DO define(value = G.goal) -> E.result
{terminal}

step.two: DO ping() -> E.pong
"""
    with pytest.raises(ParseError, match="terminal"):
        parse_program(source)
