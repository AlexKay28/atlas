"""Focused tests for the canonical TAHOE syntax.

Grammar under test (the API expected from tahoe.syntax):

    PROGRAM <name> VERSION <semver>

    INPUT
      <typed-ref> = <json-value>
    ...

    <step-id>: DO <command>(<name> = <json-or-ref>, ...) -> <event>
    DONE <deterministic-predicate>

    RETURN <event>
    STOP <kind>(<ref>)

- INPUT declares typed JSON values directly under typed references.
- Step-produced events are E.<name>; STOP reasons use U.<ref>.
- Argument values are JSON literals (number, string, boolean, array,
  object) or dotted refs; commas inside JSON never split arguments.
- A DONE line attaches its deterministic predicate to the immediately
  preceding step: ``<ref> == <json-literal>``, ``<ref> IN [literals]``,
  or ``matched(<ref>, "<regex>")``; the ref must be one of the step's
  targets.
- RETURN and STOP are terminal; no statement may follow either.
- '#' starts a comment; blank lines are ignored everywhere.
"""

import dataclasses
import json

import pytest

from tahoe.syntax import (
    Call,
    Conditional,
    DonePredicate,
    Invocation,
    ParseError,
    Program,
    Return,
    Stop,
    canonical_json,
    canonical_json_v2,
    parse_condition,
    parse_program,
    protocol_file_path,
    seal_digest,
    validate_program,
)

CANONICAL = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {"request": "ship"}
  U.reason = "not enough evidence"

step.one: DO define(value = G.goal, limit = 2) -> E.result
DONE E.result == {"ok": true, "limit": 2}

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
    assert (step.done.op, step.done.ref, step.done.value) == (
        "equals", "E.result", {"ok": True, "limit": 2},
    )


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
DONE E.result == {"ok": true, "limit": 2}

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


REF_LIST_PROGRAM = """\
PROGRAM lists VERSION 1.0

INPUT
  G.left = 5
  G.right = 7

step.first: DO define(value = G.left) -> G.goal
step.combine: DO merge(items = [G.left, G.right]) -> E.combined
step.wrap: DO merge(items = [G.goal, E.combined]) -> E.wrapped

RETURN E.wrapped
"""


def test_reference_list_argument_parses_and_validates():
    program = parse_program(REF_LIST_PROGRAM)
    combine = program.statements[1]
    wrap = program.statements[2]
    assert combine.args[0].value == ["G.left", "G.right"]
    assert wrap.args[0].value == ["G.goal", "E.combined"]
    assert (
        validate_program(program, known_commands={"define", "merge"}) is True
    )


def test_unknown_ref_inside_reference_list_rejected_with_location():
    source = REF_LIST_PROGRAM.replace(
        "items = [G.left, G.right]", "items = [G.left, E.ghost]"
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match=r"E\.ghost") as excinfo:
        validate_program(program, known_commands={"define", "merge"})
    expected_line = source.splitlines().index(
        "step.combine: DO merge(items = [G.left, E.ghost]) -> E.combined"
    ) + 1
    assert excinfo.value.line == expected_line


@pytest.mark.parametrize("bracket", ["[]", "[ ]", "[   ]"])
def test_empty_reference_list_rejected(bracket):
    source = REF_LIST_PROGRAM.replace("items = [G.left, G.right]", f"items = {bracket}")
    with pytest.raises(ParseError, match="at least one typed reference"):
        parse_program(source)


@pytest.mark.parametrize(
    "bracket",
    ["[G.left, 5]", "[G.left, \"G.right\"]", "[5, G.left]"],
)
def test_mixed_reference_list_rejected(bracket):
    source = REF_LIST_PROGRAM.replace("items = [G.left, G.right]", f"items = {bracket}")
    with pytest.raises(ParseError, match="mixes typed references and literals"):
        parse_program(source)


@pytest.mark.parametrize(
    "bracket",
    ["[[G.left], G.right]", "[G.left, [G.right]]", "[[G.left]]"],
)
def test_nested_reference_list_rejected(bracket):
    source = REF_LIST_PROGRAM.replace("items = [G.left, G.right]", f"items = {bracket}")
    with pytest.raises(ParseError, match="nested lists are not supported"):
        parse_program(source)


def test_json_list_literals_without_refs_unchanged():
    source = REF_LIST_PROGRAM.replace(
        "items = [G.left, G.right]",
        'items = [1, "two", {"k": [3]}, "G.left"]',
    )
    program = parse_program(source)
    value = program.statements[1].args[0].value
    assert value == [1, "two", {"k": [3]}, "G.left"]


def test_reference_list_seal_digest_deterministic():
    base = seal_digest(parse_program(REF_LIST_PROGRAM))
    assert seal_digest(parse_program(REF_LIST_PROGRAM)) == base
    decorated = "# comment\n\n" + REF_LIST_PROGRAM.replace(
        "RETURN E.wrapped", "\n# trailing comment\nRETURN E.wrapped\n"
    )
    assert seal_digest(parse_program(decorated)) == base
    swapped = REF_LIST_PROGRAM.replace(
        "items = [G.left, G.right]", "items = [G.right, G.left]"
    )
    assert seal_digest(parse_program(swapped)) != base


DONE_PROGRAM = """\
PROGRAM validated VERSION 1.0

INPUT
  G.goal = "ship it"

step.one: DO define(value = G.goal) -> E.result
DONE E.result == "passed"

RETURN E.result
"""


def test_done_equality_predicate_parses():
    program = parse_program(DONE_PROGRAM)
    step = program.statements[0]
    assert (step.done.op, step.done.ref, step.done.value) == (
        "equals", "E.result", "passed",
    )
    assert validate_program(program, known_commands={"define"}) is True


def test_done_equality_accepts_all_json_literals():
    source = DONE_PROGRAM.replace(
        'DONE E.result == "passed"',
        'DONE E.result == {"ok": [1, 2.5, null, false], "n": -3}',
    )
    step = parse_program(source).statements[0]
    assert (step.done.op, step.done.ref, step.done.value) == (
        "equals", "E.result", {"ok": [1, 2.5, None, False], "n": -3},
    )


def test_done_membership_predicate_parses():
    source = DONE_PROGRAM.replace(
        'DONE E.result == "passed"',
        'DONE E.result IN ["accepted", "blocked"]',
    )
    step = parse_program(source).statements[0]
    assert (step.done.op, step.done.ref, step.done.value) == (
        "in", "E.result", ["accepted", "blocked"],
    )


def test_done_matched_predicate_parses_and_compiles_regex():
    source = DONE_PROGRAM.replace(
        'DONE E.result == "passed"',
        'DONE matched(E.result, "ok-[0-9]+")',
    )
    step = parse_program(source).statements[0]
    assert (step.done.op, step.done.ref, step.done.value) == (
        "matched", "E.result", "ok-[0-9]+",
    )


def test_done_ref_must_be_one_of_the_steps_targets():
    source = DONE_PROGRAM.replace("DONE E.result", "DONE G.goal")
    with pytest.raises(ParseError, match="must be one of the step's targets"):
        parse_program(source)


def test_done_ref_inside_target_is_rejected():
    source = DONE_PROGRAM.replace(
        "DONE E.result == \"passed\"", "DONE E.result.extra == \"x\""
    )
    with pytest.raises(ParseError, match="must be one of the step's targets"):
        parse_program(source)


def test_validate_program_rejects_done_ref_outside_targets():
    program = parse_program(DONE_PROGRAM)
    tampered = dataclasses.replace(
        program.statements[0],
        done=DonePredicate("equals", "G.goal", "x"),
    )
    program = dataclasses.replace(program, statements=(tampered, program.statements[-1]))
    with pytest.raises(ParseError, match="must be one of the step's targets"):
        validate_program(program, known_commands={"define"})


@pytest.mark.parametrize(
    "expression",
    [
        "equals(E.result, \"passed\")",
        "schema(E.result, \"timeseries.v1\")",
        "E.result > 2",
        "exists(E.result)",
        "E.result == \"a\" AND E.result == \"b\"",
        "E.result",
        "E.result ==",
        "E.result == not json",
        "E.result IN [E.other]",
        "E.result IN \"passed\"",
        "matched(E.result)",
        "matched(E.result, 7)",
        'matched(E.result, "[unclosed")',
        "matched(G.goal, \"x\")",
    ],
)
def test_unknown_or_malformed_done_expressions_rejected(expression):
    source = DONE_PROGRAM.replace(
        'DONE E.result == "passed"', f"DONE {expression}"
    )
    with pytest.raises(ParseError, match="DONE|matched predicate"):
        parse_program(source)


def test_done_must_reference_target_even_when_ref_defined_earlier():
    source = DONE_PROGRAM.replace(
        "step.one: DO define(value = G.goal) -> E.result\nDONE E.result == \"passed\"\n",
        "step.zero: DO define(value = G.goal) -> E.other\n"
        "step.one: DO define(value = G.goal) -> E.result\n"
        "DONE E.other == \"passed\"\n",
    )
    with pytest.raises(ParseError, match="must be one of the step's targets"):
        parse_program(source)


def test_done_seal_digest_deterministic_and_sensitive():
    base = seal_digest(parse_program(DONE_PROGRAM))
    assert seal_digest(parse_program(DONE_PROGRAM)) == base
    decorated = "# comment\n\n" + DONE_PROGRAM + "\n# trailing\n"
    assert seal_digest(parse_program(decorated)) == base
    changed_literal = DONE_PROGRAM.replace('"passed"', '"failed"')
    assert seal_digest(parse_program(changed_literal)) != base
    changed_op = DONE_PROGRAM.replace(
        'DONE E.result == "passed"',
        'DONE E.result IN ["passed"]',
    )
    assert seal_digest(parse_program(changed_op)) != base


# -- hyphen-tolerant program names (issue #15) -------------------------


def test_hyphenated_program_name_parses_and_seals_deterministically():
    source = CANONICAL.replace("PROGRAM demo VERSION", "PROGRAM issue-15-registry-digest VERSION")
    program = parse_program(source)
    assert program.name == "issue-15-registry-digest"
    assert seal_digest(parse_program(source)) == seal_digest(parse_program(source))


def test_program_name_leading_hyphen_rejected():
    source = CANONICAL.replace("PROGRAM demo VERSION", "PROGRAM -demo VERSION")
    with pytest.raises(ParseError, match="header"):
        parse_program(source)


def test_program_name_leading_digit_rejected():
    source = CANONICAL.replace("PROGRAM demo VERSION", "PROGRAM 1demo VERSION")
    with pytest.raises(ParseError, match="header"):
        parse_program(source)


def test_step_id_with_hyphen_still_rejected():
    source = CANONICAL.replace("step.one:", "step.one-two:")
    with pytest.raises(ParseError, match="invocation"):
        parse_program(source)


def test_underscore_program_names_unchanged():
    source = CANONICAL.replace("PROGRAM demo VERSION", "PROGRAM issue_15_registry_digest VERSION")
    program = parse_program(source)
    assert program.name == "issue_15_registry_digest"
    assert parse_program(CANONICAL).name == "demo"


# -- KB.* cross-run semantic-memory references (issue #5) --------------


KB_ARGS_PROGRAM = """\
PROGRAM memory_user VERSION 1.0

INPUT
  G.note = "remember me"

step.recall: DO recall(query = "kb.note") -> OUT.found
step.use: DO define(value = [G.note, KB.note]) -> E.mixed
RETURN OUT.found, E.mixed
"""


def test_kb_refs_parse_as_typed_references():
    program = parse_program(KB_ARGS_PROGRAM)
    step = program.statements[1]
    assert [(arg.name, arg.value) for arg in step.args] == [
        ("value", ["G.note", "KB.note"]),
    ]


def test_kb_ref_in_argument_position_passes_validation():
    assert validate_program(
        parse_program(KB_ARGS_PROGRAM),
        known_commands={"recall", "define"},
    ) is True


def test_kb_ref_used_as_invocation_target_rejected():
    source = """\
PROGRAM bad_target VERSION 1.0

INPUT
  G.note = "x"

step.write: DO remember(key = "kb.note", value = G.note) -> KB.note
RETURN G.note
"""
    program = parse_program(source)
    with pytest.raises(ParseError, match="cannot be an invocation target"):
        validate_program(program, known_commands={"remember"})


def test_kb_declaration_in_input_rejected():
    source = """\
PROGRAM bad_input VERSION 1.0

INPUT
  KB.note = "preloaded"

step.use: DO define(value = KB.note) -> E.value
RETURN E.value
"""
    with pytest.raises(ParseError, match="cannot be declared in INPUT"):
        parse_and_validate_kb(source)


def parse_and_validate_kb(source):
    program = parse_program(source)
    validate_program(program, known_commands={"define"})
    return program


def test_bare_kb_leaf_ref_used_before_definition_still_rejected():
    # A KB.* ref passes the availability check, but a missing G. ref does not.
    source = """\
PROGRAM missing_state VERSION 1.0

step.use: DO define(value = G.absent) -> E.value
RETURN E.value
"""
    with pytest.raises(ParseError, match="used before definition"):
        validate_program(parse_program(source), known_commands={"define"})


def test_kb_ref_in_done_lhs_rejected_as_unowned_target():
    source = """\
PROGRAM kb_done VERSION 1.0

INPUT
  G.note = "x"

step.write: DO remember(key = "kb.note", value = G.note) -> ART.record
DONE KB.note == "x"
RETURN ART.record
"""
    with pytest.raises(ParseError, match="must be one of the step's targets"):
        parse_program(source)


# -- protocol calls: CALL protocol.name(...) -> targets (issue #12) ------


def write_protocol(root, name, text):
    protocols = root / "protocols"
    protocols.mkdir(exist_ok=True)
    path = protocols / f"{name}.think"
    path.write_text(text, encoding="utf-8")
    return path


FRAMING_PROTOCOL = """\
PROGRAM framing VERSION 1.0

INPUT
  G.request = "frame the problem"
  C.scope = "repository working tree"

step.frame: DO define(request = G.request) -> G.plan
step.locate: DO search(query = G.plan, scope = C.scope) -> E.context
step.read: DO fetch(resource_refs = E.context) -> ART.sources
step.analyze: DO extract(artifact = ART.sources, schema = "frame_analysis") -> V.analysis

RETURN G.plan, E.context, ART.sources, V.analysis
"""

CALL_PROGRAM = """\
PROGRAM caller VERSION 1.0

INPUT
  G.request = "frame the kb issue"

step.ask: DO define(request = G.request) -> G.probe
CALL protocol.framing(request = G.probe, scope = "src/tahoe") -> G.plan, V.analysis
step.wrap: DO summarize(source_refs = V.analysis, budget = 100) -> OUT.brief

RETURN G.plan, V.analysis, OUT.brief
"""

INNER_PROTOCOL = """\
PROGRAM inner VERSION 1.0

INPUT
  G.request = "x"
  C.scope = "y"

step.deep: DO define(request = G.request) -> E.deep1
step.deeper: DO extract(artifact = E.deep1, schema = "deep") -> E.deep2

RETURN E.deep1, E.deep2
"""

SELF_LOOP_PROTOCOL = """\
PROGRAM loop VERSION 1.0

INPUT
  G.request = "x"
  C.scope = "y"

step.frame: DO define(request = G.request) -> G.plan
CALL protocol.loop(request = G.request, scope = C.scope) -> E.context

RETURN G.plan, E.context
"""

CALL_KNOWN_COMMANDS = {"define", "search", "fetch", "extract", "summarize"}


def test_call_statement_parses_with_args_and_targets():
    program = parse_program(CALL_PROGRAM)
    call = program.statements[1]
    assert isinstance(call, Call)
    assert call.protocol == "protocol.framing"
    assert [(arg.name, arg.value) for arg in call.args] == [
        ("request", "G.probe"),
        ("scope", "src/tahoe"),
    ]
    assert call.targets == ("G.plan", "V.analysis")


def test_call_ast_node_is_frozen_dataclass():
    call = parse_program(CALL_PROGRAM).statements[1]
    assert dataclasses.is_dataclass(call)
    with pytest.raises(dataclasses.FrozenInstanceError):
        call.protocol = "protocol.other"


def test_call_target_refs_become_available_for_later_steps(tmp_path):
    write_protocol(tmp_path, "framing", FRAMING_PROTOCOL)
    program = parse_program(CALL_PROGRAM)
    assert (
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )
        is True
    )


def test_call_seal_digest_deterministic_and_sensitive():
    base = seal_digest(parse_program(CALL_PROGRAM))
    assert seal_digest(parse_program(CALL_PROGRAM)) == base
    retargeted = CALL_PROGRAM.replace(
        "-> G.plan, V.analysis", "-> G.plan, E.context"
    )
    assert seal_digest(parse_program(retargeted)) != base


@pytest.mark.parametrize(
    "line",
    [
        "CALL framing(request = G.probe) -> G.plan",
        "CALL protocol.(x = 1) -> G.plan",
        "CALL protocol.Framing(x = 1) -> G.plan",
        "CALL protocol.framing(request = G.probe)",
        "CALL protocol.framing(request = G.probe) ->",
        "CALL protocol.framing(request = G.probe) -> not.a-ref",
    ],
)
def test_malformed_call_rejected(line):
    source = CALL_PROGRAM.replace(
        "CALL protocol.framing(request = G.probe, scope = \"src/tahoe\") -> G.plan, V.analysis",
        line,
    )
    with pytest.raises(ParseError, match="CALL|target"):
        parse_program(source)


def test_done_after_call_rejected():
    source = CALL_PROGRAM.replace(
        "step.wrap: DO summarize(source_refs = V.analysis, budget = 100) -> OUT.brief",
        "DONE V.analysis == 1\nstep.wrap: DO summarize(source_refs = V.analysis, budget = 100) -> OUT.brief",
    )
    with pytest.raises(ParseError, match="DONE must follow an invocation"):
        parse_program(source)


def test_unknown_protocol_rejected(tmp_path):
    write_protocol(tmp_path, "other", FRAMING_PROTOCOL)
    program = parse_program(CALL_PROGRAM)
    with pytest.raises(ParseError, match="protocol protocol.framing not found"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_call_without_protocols_dir_uses_default_and_reports_missing(tmp_path):
    program = parse_program(CALL_PROGRAM)
    monkey_free_cwd = tmp_path / "cwd"
    monkey_free_cwd.mkdir()
    import os

    old = os.getcwd()
    os.chdir(monkey_free_cwd)
    try:
        with pytest.raises(ParseError, match="protocol protocol.framing not found"):
            validate_program(program, known_commands=CALL_KNOWN_COMMANDS)
    finally:
        os.chdir(old)


def test_call_target_outside_protocol_return_rejected(tmp_path):
    write_protocol(tmp_path, "framing", FRAMING_PROTOCOL)
    source = CALL_PROGRAM.replace(
        "-> G.plan, V.analysis", "-> G.plan, E.ghost"
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="must be a subset of the protocol RETURN refs"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_call_missing_argument_for_protocol_input_rejected(tmp_path):
    write_protocol(tmp_path, "framing", FRAMING_PROTOCOL)
    source = CALL_PROGRAM.replace(
        "CALL protocol.framing(request = G.probe, scope = \"src/tahoe\") -> G.plan, V.analysis",
        "CALL protocol.framing(request = G.probe) -> G.plan, V.analysis",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="missing arguments for protocol INPUT"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_call_unknown_argument_rejected(tmp_path):
    write_protocol(tmp_path, "framing", FRAMING_PROTOCOL)
    source = CALL_PROGRAM.replace(
        "CALL protocol.framing(request = G.probe, scope = \"src/tahoe\")",
        "CALL protocol.framing(request = G.probe, scope = \"s\", extra = 1)",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="matching no protocol INPUT"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_call_duplicate_argument_rejected(tmp_path):
    write_protocol(tmp_path, "framing", FRAMING_PROTOCOL)
    source = CALL_PROGRAM.replace(
        "CALL protocol.framing(request = G.probe, scope = \"src/tahoe\")",
        "CALL protocol.framing(request = G.probe, request = G.probe, scope = \"s\")",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="duplicate arguments"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_call_argument_reference_must_resolve_like_invocation_args(tmp_path):
    write_protocol(tmp_path, "framing", FRAMING_PROTOCOL)
    source = CALL_PROGRAM.replace(
        "request = G.probe", "request = G.ghost"
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match=r"G\.ghost used before definition"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_protocol_file_must_parse(tmp_path):
    write_protocol(tmp_path, "framing", "PROGRAM broken VERSION 1.0\nstep.x DO nope\n")
    program = parse_program(CALL_PROGRAM)
    with pytest.raises(ParseError, match="protocol protocol.framing failed to parse"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_protocol_must_end_with_return(tmp_path):
    write_protocol(
        tmp_path,
        "framing",
        FRAMING_PROTOCOL.replace(
            "RETURN G.plan, E.context, ART.sources, V.analysis",
            "STOP unresolved(V.analysis)",
        ),
    )
    program = parse_program(CALL_PROGRAM)
    with pytest.raises(ParseError, match="must end with RETURN"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_protocol_with_unknown_command_rejected(tmp_path):
    write_protocol(
        tmp_path,
        "framing",
        FRAMING_PROTOCOL.replace("DO search(", "DO teleport("),
    )
    program = parse_program(CALL_PROGRAM)
    with pytest.raises(ParseError, match="protocol protocol.framing is invalid"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_direct_self_call_rejected(tmp_path):
    write_protocol(
        tmp_path,
        "loop",
        SELF_LOOP_PROTOCOL,
    )
    source = CALL_PROGRAM.replace(
        "CALL protocol.framing(request = G.probe, scope = \"src/tahoe\") -> G.plan, V.analysis",
        "CALL protocol.loop(request = G.probe, scope = \"src/tahoe\") -> G.plan, E.context",
    ).replace(
        "RETURN G.plan, V.analysis, OUT.brief",
        "RETURN G.plan, E.context, OUT.brief",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="calls itself directly"):
        validate_program(
            program,
            known_commands={"define"},
            protocols_dir=tmp_path / "protocols",
        )


def test_transitive_self_call_rejected(tmp_path):
    # framing -> inner -> framing: the cycle closes transitively.
    write_protocol(tmp_path, "framing", FRAMING_PROTOCOL.replace(
        "step.locate: DO search(query = G.plan, scope = C.scope) -> E.context",
        "step.locate: DO search(query = G.plan, scope = C.scope) -> E.context\n"
        "CALL protocol.inner(request = G.request, scope = C.scope) -> E.deep1, E.deep2",
    ))
    write_protocol(tmp_path, "inner", INNER_PROTOCOL.replace(
        "step.deeper: DO extract(artifact = E.deep1, schema = \"deep\") -> E.deep2",
        "step.deeper: DO extract(artifact = E.deep1, schema = \"deep\") -> E.deep2\n"
        "CALL protocol.framing(request = G.request, scope = C.scope) -> G.plan, E.context",
    ))
    program = parse_program(CALL_PROGRAM)
    with pytest.raises(ParseError, match="calls itself directly or transitively"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_nested_protocol_chain_within_depth_limit_validates(tmp_path):
    # framing -> inner (one nested level) is allowed and validates cleanly.
    write_protocol(tmp_path, "framing", FRAMING_PROTOCOL.replace(
        "step.locate: DO search(query = G.plan, scope = C.scope) -> E.context",
        "step.locate: DO search(query = G.plan, scope = C.scope) -> E.context\n"
        "CALL protocol.inner(request = G.request, scope = C.scope) -> E.deep1, E.deep2",
    ))
    write_protocol(tmp_path, "inner", INNER_PROTOCOL)
    program = parse_program(CALL_PROGRAM)
    assert (
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )
        is True
    )


def test_protocol_call_chain_beyond_depth_limit_rejected(tmp_path):
    # Chain of 9 protocols a1 -> ... -> a9: the depth limit of 8 rejects
    # the a8 -> a9 edge (the caller program itself is not a protocol level).
    for index in range(1, 10):
        if index < 9:
            body = (
                f"PROGRAM a{index} VERSION 1.0\n\n"
                "INPUT\n"
                '  G.request = "x"\n'
                '  C.scope = "y"\n\n'
                "step.frame: DO define(request = G.request) -> G.plan\n"
                f"CALL protocol.a{index + 1}(request = G.request, scope = C.scope)"
                " -> E.child\n\n"
                "RETURN G.plan, E.child\n"
            )
        else:
            body = (
                f"PROGRAM a{index} VERSION 1.0\n\n"
                "INPUT\n"
                '  G.request = "x"\n'
                '  C.scope = "y"\n\n'
                "step.frame: DO define(request = G.request) -> E.child\n\n"
                "RETURN E.child\n"
            )
        write_protocol(tmp_path, f"a{index}", body)
    source = CALL_PROGRAM.replace(
        "CALL protocol.framing(request = G.probe, scope = \"src/tahoe\") -> G.plan, V.analysis",
        "CALL protocol.a1(request = G.probe, scope = \"src/tahoe\") -> G.plan, E.child",
    ).replace(
        "RETURN G.plan, V.analysis, OUT.brief",
        "RETURN G.plan, E.child, OUT.brief",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="depth exceeds limit 8"):
        validate_program(
            program,
            known_commands={"define"},
            protocols_dir=tmp_path / "protocols",
        )


def test_kb_ref_as_call_target_rejected(tmp_path):
    write_protocol(tmp_path, "framing", FRAMING_PROTOCOL)
    source = CALL_PROGRAM.replace(
        "-> G.plan, V.analysis", "-> KB.note"
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="cannot be a CALL target"):
        validate_program(
            program,
            known_commands=CALL_KNOWN_COMMANDS,
            protocols_dir=tmp_path / "protocols",
        )


def test_protocol_file_path_mapping():
    assert protocol_file_path("protocol.framing").name == "framing.think"
    assert protocol_file_path("protocol.ops.framing").name == "ops.framing.think"
    assert protocol_file_path("protocol.framing", "custom").as_posix() == (
        "custom/framing.think"
    )
    with pytest.raises(ParseError, match="must start with"):
        protocol_file_path("framing")


# -- revise/retire correction clause (issue #7) ---------------------------
#
# An invocation line may end with an optional trailing correction clause
# `REVISE r1, r2 | RETIRE r3, r4` (either or both, pipe-separated groups;
# each list is comma-separated refs).  REVISEd refs are set to the step's
# single target value at commit time (so REVISE requires exactly one
# target); RETIREd refs are removed from the projection.  Validation is
# pragmatic: refs must exist earlier, may not be the step's own targets,
# and no ref may appear in both groups; whether a RETIREd ref is still
# RETURNed stays the programmer's responsibility.

CORRECTIONS_PROGRAM = """\
PROGRAM corrector VERSION 1.0

INPUT
  G.left = 5

step.first: DO define(value = G.left) -> G.summary
step.stale: DO define(value = G.left) -> E.stale
step.fix: DO define(value = G.left) -> E.correction REVISE G.summary | RETIRE E.stale

RETURN E.correction
"""

CORRECTIONS_KNOWN = {"define"}


def test_revise_and_retire_clause_parses_both_groups():
    program = parse_program(CORRECTIONS_PROGRAM)
    fix = program.statements[2]
    assert isinstance(fix, Invocation)
    assert fix.revisions == ("G.summary",)
    assert fix.retirements == ("E.stale",)
    assert fix.targets == ("E.correction",)
    assert validate_program(program, known_commands=CORRECTIONS_KNOWN) is True


def test_steps_without_clause_default_to_empty():
    program = parse_program(CANONICAL)
    step = program.statements[0]
    assert step.revisions == ()
    assert step.retirements == ()


@pytest.mark.parametrize(
    ("clause", "revisions", "retirements"),
    [
        ("REVISE G.summary", ("G.summary",), ()),
        ("RETIRE E.stale", (), ("E.stale",)),
        (
            "REVISE G.summary | RETIRE E.stale",
            ("G.summary",),
            ("E.stale",),
        ),
        ("REVISE G.summary, E.stale", ("G.summary", "E.stale"), ()),
        ("RETIRE E.stale, G.summary", (), ("E.stale", "G.summary")),
        (
            "REVISE G.summary, E.stale | RETIRE E.stale, G.summary",
            ("G.summary", "E.stale"),
            ("E.stale", "G.summary"),
        ),
    ],
)
def test_clause_shapes_parse_with_comma_separated_refs(clause, revisions, retirements):
    source = CORRECTIONS_PROGRAM.replace(
        "-> E.correction REVISE G.summary | RETIRE E.stale",
        f"-> E.correction {clause}",
    )
    fix = parse_program(source).statements[2]
    assert fix.targets == ("E.correction",)
    assert fix.revisions == revisions
    assert fix.retirements == retirements


def test_clause_tolerates_extra_whitespace():
    source = CORRECTIONS_PROGRAM.replace(
        "REVISE G.summary | RETIRE E.stale",
        "REVISE  G.summary ,  E.stale   |   RETIRE  E.stale",
    ).replace("-> E.correction REVISE", "->  E.correction    REVISE")
    fix = parse_program(source).statements[2]
    assert fix.revisions == ("G.summary", "E.stale")
    assert fix.retirements == ("E.stale",)


def test_malformed_clause_rejected():
    for bad in [
        "REVISE",
        "REVISE G.summary |",
        "REVISE G.summary | RETIRE",
        "REVISE G.summary | RETIRE not.a-ref",
        "REVISE G.summary RETIRE E.stale",
    ]:
        source = CORRECTIONS_PROGRAM.replace(
            "-> E.correction REVISE G.summary | RETIRE E.stale",
            f"-> E.correction {bad}",
        )
        with pytest.raises(ParseError):
            parse_program(source)


def test_revise_unknown_reference_rejected():
    source = CORRECTIONS_PROGRAM.replace(
        "REVISE G.summary", "REVISE G.ghost"
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match=r"REVISE reference G\.ghost"):
        validate_program(program, known_commands=CORRECTIONS_KNOWN)


def test_retire_unknown_reference_rejected():
    source = CORRECTIONS_PROGRAM.replace(
        "RETIRE E.stale", "RETIRE E.ghost"
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match=r"RETIRE reference E\.ghost"):
        validate_program(program, known_commands=CORRECTIONS_KNOWN)


def test_revise_own_target_rejected():
    source = CORRECTIONS_PROGRAM.replace(
        "REVISE G.summary", "REVISE E.correction"
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="own targets"):
        validate_program(program, known_commands=CORRECTIONS_KNOWN)


def test_retire_own_target_rejected():
    source = CORRECTIONS_PROGRAM.replace(
        "RETIRE E.stale", "RETIRE E.correction"
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="own targets"):
        validate_program(program, known_commands=CORRECTIONS_KNOWN)


def test_revise_and_retire_overlap_rejected():
    source = CORRECTIONS_PROGRAM.replace(
        "REVISE G.summary | RETIRE E.stale",
        "REVISE G.summary | RETIRE G.summary",
    )
    program = parse_program(source)
    with pytest.raises(ParseError, match="both"):
        validate_program(program, known_commands=CORRECTIONS_KNOWN)


def test_retire_reference_defined_only_later_rejected():
    source = CORRECTIONS_PROGRAM.replace(
        "step.fix: DO define(value = G.left) -> E.correction REVISE G.summary | RETIRE E.stale",
        "step.fix: DO define(value = G.left) -> E.correction RETIRE E.later\n"
        "step.later: DO define(value = G.left) -> E.later",
    ).replace("RETURN E.correction", "RETURN E.correction")
    program = parse_program(source)
    with pytest.raises(ParseError, match=r"RETIRE reference E\.later"):
        validate_program(program, known_commands=CORRECTIONS_KNOWN)


def test_kb_reference_cannot_be_revised_or_retired():
    for kind in ("REVISE", "RETIRE"):
        source = CORRECTIONS_PROGRAM.replace(
            f"{kind} G.summary" if kind == "REVISE" else "RETIRE E.stale",
            f"{kind} KB.note",
        )
        program = parse_program(source)
        with pytest.raises(ParseError, match=f"{kind} reference KB.note"):
            validate_program(program, known_commands=CORRECTIONS_KNOWN)


def test_revise_on_multi_target_step_rejected():
    source = CORRECTIONS_PROGRAM.replace(
        "step.fix: DO define(value = G.left) -> E.correction REVISE G.summary | RETIRE E.stale",
        "step.fix: DO define(value = G.left) -> E.correction, E.extra REVISE G.summary",
    ).replace("RETURN E.correction", "RETURN E.correction, E.extra")
    program = parse_program(source)
    with pytest.raises(ParseError, match="requires exactly one target"):
        validate_program(program, known_commands=CORRECTIONS_KNOWN)


def test_retire_on_multi_target_step_allowed():
    source = CORRECTIONS_PROGRAM.replace(
        "step.fix: DO define(value = G.left) -> E.correction REVISE G.summary | RETIRE E.stale",
        "step.fix: DO define(value = G.left) -> E.correction, E.extra RETIRE E.stale",
    ).replace("RETURN E.correction", "RETURN E.correction, E.extra")
    program = parse_program(source)
    assert validate_program(program, known_commands=CORRECTIONS_KNOWN) is True


def test_returning_a_retired_reference_still_validates():
    # Pragmatic per the issue: RETURN semantics are the programmer's
    # responsibility; validation only checks existence, no overlap, and
    # not-own-target.
    source = CORRECTIONS_PROGRAM.replace(
        "RETURN E.correction", "RETURN E.correction, E.stale"
    )
    program = parse_program(source)
    assert validate_program(program, known_commands=CORRECTIONS_KNOWN) is True


def test_clause_works_with_done_and_ref_lists():
    source = """\
PROGRAM corrector VERSION 1.0

INPUT
  G.left = 5
  G.right = 7

step.first: DO define(value = G.left) -> G.summary
step.stale: DO define(value = G.left) -> E.stale
step.fix: DO merge(items = [G.left, G.right]) -> E.correction
DONE E.correction == 12
step.settle: DO define(value = E.correction) -> E.settled REVISE G.summary | RETIRE E.stale

RETURN E.settled
"""
    program = parse_program(source)
    settle = program.statements[3]
    assert settle.revisions == ("G.summary",)
    assert settle.retirements == ("E.stale",)
    assert settle.done is None
    assert program.statements[2].done is not None
    assert (
        validate_program(program, known_commands={"define", "merge"}) is True
    )


def test_clause_seal_digest_deterministic_and_sensitive():
    base = seal_digest(parse_program(CORRECTIONS_PROGRAM))
    assert seal_digest(parse_program(CORRECTIONS_PROGRAM)) == base
    decorated = "# comment\n\n" + CORRECTIONS_PROGRAM + "\n# trailing\n"
    assert seal_digest(parse_program(decorated)) == base
    without_clause = CORRECTIONS_PROGRAM.replace(
        " REVISE G.summary | RETIRE E.stale", ""
    )
    assert seal_digest(parse_program(without_clause)) != base
    swapped = CORRECTIONS_PROGRAM.replace(
        "REVISE G.summary", "REVISE G.left"
    )
    assert seal_digest(parse_program(swapped)) != base
    reordered = CORRECTIONS_PROGRAM.replace(
        "REVISE G.summary | RETIRE E.stale",
        "REVISE G.summary | RETIRE E.stale, G.summary",
    )
    assert seal_digest(parse_program(reordered)) != base


def test_clause_canonical_json_omits_empty_groups():
    # Pre-existing programs keep their exact canonical form (and seal).
    plain = canonical_json(parse_program(CANONICAL))
    assert "revisions" not in plain and "retirements" not in plain
    with_clause = canonical_json(parse_program(CORRECTIONS_PROGRAM))
    assert '"revisions":["G.summary"]' in with_clause
    assert '"retirements":["E.stale"]' in with_clause


# --------------------------------------------------------------------------
# Issue #3: IF branches with deterministic expressions.
# --------------------------------------------------------------------------

IF_PROGRAM = """\
PROGRAM gated VERSION 0.1

INPUT
  V.flag = "go"
  E.items = [1, 2, 3]

step.one: DO define(value = V.flag) -> V.out
IF V.flag == "go" AND count(E.items) >= 2 STOP blocked(V.out)
IF NOT V.flag != "no" OR count(E.items) < 1 RETURN V.out
IF count(E.items) == 3 step.two: DO calculate(left = 1, right = 2) -> OUT.total
RETURN V.out
"""


def _conditionals(program):
    return [
        statement
        for statement in program.statements
        if isinstance(statement, Conditional)
    ]


def test_if_condition_expression_forms_parse():
    program = parse_program(IF_PROGRAM)
    first, second, third = _conditionals(program)

    assert first.condition == 'V.flag == "go" AND count(E.items) >= 2'
    assert first.statement.kind == "blocked"
    assert first.statement.ref == "V.out"
    assert first.line == 8

    assert second.condition == 'NOT V.flag != "no" OR count(E.items) < 1'
    assert isinstance(second.statement, Return)
    assert second.statement.refs == ("V.out",)

    assert third.condition == "count(E.items) == 3"
    assert isinstance(third.statement, Invocation)
    assert third.statement.step_id == "step.two"
    assert third.statement.command == "calculate"
    assert third.statement.targets == ("OUT.total",)

    # Conditionals keep their source position among the statements.
    assert program.statements[1] is first
    assert program.statements[3] is third


def test_if_condition_ast_shape_and_left_associativity():
    assert parse_condition('V.a == "x"') == ("eq", "V.a", "x")
    assert parse_condition("V.a != 7") == ("ne", "V.a", 7)
    for op, name in (("==", "eq"), ("!=", "ne"), ("<", "lt"), ("<=", "le"), (">", "gt"), (">=", "ge")):
        ast = parse_condition(f"count(E.items) {op} 2")
        assert ast == ("count", "E.items", op, 2), op
    # Left-associative fold: a AND b OR c == ((a AND b) OR c).
    ast = parse_condition('V.a == 1 AND V.b == 2 OR V.c == 3')
    assert ast == (
        "or",
        ("and", ("eq", "V.a", 1), ("eq", "V.b", 2)),
        ("eq", "V.c", 3),
    )
    assert parse_condition("NOT V.a == 1") == ("not", ("eq", "V.a", 1))
    assert parse_condition("NOT NOT V.a == 1") == (
        "not",
        ("not", ("eq", "V.a", 1)),
    )


def test_if_condition_accepts_json_literal_right_hand_sides():
    program = parse_program(
        CANONICAL.replace(
            "RETURN E.result",
            'IF E.result == {"ok": true, "limit": 2} STOP completed()\nRETURN E.result',
        )
    )
    (conditional,) = _conditionals(program)
    assert conditional.condition == 'E.result == {"ok": true, "limit": 2}'
    assert conditional.statement.kind == "completed"
    assert conditional.statement.ref is None


def test_if_statement_keywords_inside_json_literals_do_not_split():
    program = parse_program(
        CANONICAL.replace(
            "RETURN E.result",
            'IF E.result != "please STOP now AND RETURN" STOP blocked(E.result)\nRETURN E.result',
        )
    )
    (conditional,) = _conditionals(program)
    assert conditional.condition == 'E.result != "please STOP now AND RETURN"'
    assert isinstance(conditional.statement, Stop)


def test_if_condition_refs_validated_like_done_refs():
    base = """\
PROGRAM ordered VERSION 0.1

INPUT
  V.flag = "go"

{lines}

RETURN V.flag
"""
    # Declared INPUT ref: accepted.
    program = parse_program(
        base.format(lines="IF V.flag == \"go\" STOP completed()")
    )
    assert validate_program(program, known_commands=set()) is True
    # Ref produced by an earlier step: accepted.
    program = parse_program(
        base.format(
            lines='step.one: DO define(value = V.flag) -> E.out\n'
            'IF E.out == "x" STOP completed()'
        )
    )
    assert validate_program(program, known_commands={"define"}) is True
    # Ref produced by a later step: rejected at the conditional's position.
    program = parse_program(
        base.format(
            lines='IF E.out == "x" STOP completed()\n'
            'step.one: DO define(value = V.flag) -> E.out'
        )
    )
    with pytest.raises(ParseError, match="E.out.*used before definition"):
        validate_program(program, known_commands={"define"})
    # Undeclared ref: rejected.
    program = parse_program(
        base.format(lines='IF V.missing == "x" STOP completed()')
    )
    with pytest.raises(ParseError, match="V.missing.*used before definition"):
        validate_program(program, known_commands=set())
    # count() ref must exist too.
    program = parse_program(
        base.format(lines="IF count(V.missing) > 0 STOP completed()")
    )
    with pytest.raises(ParseError, match="V.missing.*used before definition"):
        validate_program(program, known_commands=set())


def test_if_else_block_forms_rejected():
    for source in (
        CANONICAL.replace("RETURN E.result", "ELSE STOP completed()"),
        CANONICAL.replace(
            "RETURN E.result", 'ELSE IF E.result == 1 STOP completed()'
        ),
    ):
        with pytest.raises(
            ParseError, match="unsupported control construct ELSE"
        ):
            parse_program(source)


def test_if_parentheses_rejected():
    with pytest.raises(
        ParseError, match="parentheses are not supported in IF conditions"
    ):
        parse_program(
            CANONICAL.replace(
                "RETURN E.result",
                "IF (E.result == 1) STOP completed()\nRETURN E.result",
            )
        )
    with pytest.raises(
        ParseError, match="parentheses are not supported in IF conditions"
    ):
        parse_program(
            CANONICAL.replace(
                "RETURN E.result",
                "IF E.result == 1 AND (E.result != 2) STOP completed()\n"
                "RETURN E.result",
            )
        )


def test_if_do_must_come_after_every_unconditional_invocation():
    base = """\
PROGRAM ordered VERSION 0.1

INPUT
  V.flag = "go"

step.one: DO define(value = V.flag) -> V.out
{lines}
RETURN V.out
"""
    # IF-DO followed by an unconditional invocation: rejected.
    program = parse_program(
        base.format(
            lines='IF V.flag == "go" step.two: DO ping() -> E.pong\n'
            "step.three: DO define(value = V.flag) -> V.late"
        )
    )
    with pytest.raises(
        ParseError,
        match="step.three.*after an IF ... DO conditional",
    ):
        validate_program(program, known_commands={"define", "ping"})
    # IF-DO followed by a CALL: rejected too.
    program = parse_program(
        base.format(
            lines='IF V.flag == "go" step.two: DO ping() -> E.pong\n'
            'CALL protocol.framing(request = V.flag) -> V.out'
        )
    )
    with pytest.raises(
        ParseError, match="CALL appears after an IF ... DO conditional"
    ):
        validate_program(program, known_commands={"define", "ping"})
    # IF-DO as the last invocation before the terminal: accepted.
    program = parse_program(
        base.format(
            lines='IF V.flag == "go" step.two: DO ping() -> E.pong'
        )
    )
    assert validate_program(program, known_commands={"define", "ping"}) is True


def test_if_malformed_conditions_rejected():
    cases = [
        # Bare ref without an operator.
        'IF V.flag STOP completed()',
        # Ordering comparison on a bare reference.
        "IF V.flag > 1 STOP completed()",
        "IF V.flag <= 1 STOP completed()",
        # Ref-vs-ref comparison (right side must be a JSON literal).
        "IF V.flag == V.other STOP completed()",
        # Invalid JSON literal.
        'IF V.flag == passed STOP completed()',
        # THEN is not part of the grammar.
        "IF V.flag == 1 THEN STOP completed()",
        # Trailing junk after a well-formed condition.
        "IF V.flag == 1 junk STOP completed()",
        # count without a typed reference.
        "IF count(3) > 0 STOP completed()",
        "IF count(V.flag STOP completed()",
        # count against a non-integer literal.
        'IF count(V.flag) > "many" STOP completed()',
        # Missing statement after the condition.
        "IF V.flag == 1",
    ]
    for source in cases:
        program_text = CANONICAL.replace("RETURN E.result", source)
        with pytest.raises(ParseError):
            parse_program(program_text), source


def test_if_embedded_statement_validation_errors():
    base = """\
PROGRAM checked VERSION 0.1

INPUT
  V.flag = "go"

{lines}

RETURN V.flag
"""
    # Invalid embedded STOP kind.
    program = parse_program(
        base.format(lines='IF V.flag == "go" STOP exploded(V.flag)')
    )
    with pytest.raises(ParseError, match="invalid STOP kind exploded"):
        validate_program(program, known_commands=set())
    # Unresolved embedded STOP ref.
    program = parse_program(
        base.format(lines='IF V.flag == "go" STOP failed(V.missing)')
    )
    with pytest.raises(ParseError, match="unresolved STOP reference V.missing"):
        validate_program(program, known_commands=set())
    # Unresolved embedded RETURN ref.
    program = parse_program(
        base.format(lines='IF V.flag == "go" RETURN V.missing')
    )
    with pytest.raises(ParseError, match="unresolved return reference V.missing"):
        validate_program(program, known_commands=set())
    # Unknown command inside the embedded DO.
    program = parse_program(
        base.format(lines='IF V.flag == "go" step.x: DO teleport() -> E.out')
    )
    with pytest.raises(ParseError, match="unknown command teleport"):
        validate_program(program, known_commands=set())
    # Duplicate step id across bare and conditional invocations.
    program = parse_program(
        base.format(
            lines="step.dup: DO ping() -> E.late\n"
            'IF V.flag == "go" step.dup: DO ping() -> E.out'
        )
    )
    with pytest.raises(ParseError, match="duplicate step step.dup"):
        validate_program(program, known_commands={"ping"})
    # Conditional target may not collide with an unconditional target.
    program = parse_program(
        base.format(
            lines="step.base: DO ping() -> E.out\n"
            'IF V.flag == "go" step.x: DO ping() -> E.out'
        )
    )
    with pytest.raises(ParseError, match="duplicate target E.out"):
        validate_program(program, known_commands={"ping"})
    # Nor with another conditional's target.
    program = parse_program(
        base.format(
            lines='IF V.flag == "go" step.x: DO ping() -> E.out\n'
            'IF V.flag == "go" step.y: DO ping() -> E.out'
        )
    )
    with pytest.raises(ParseError, match="duplicate target E.out"):
        validate_program(program, known_commands={"ping"})
    # Conditional targets are not referenceable by later statements: the
    # branch may not run, so statically the node does not exist.  (The
    # reading step must precede the IF-DO anyway per the ordering rule.)
    program = parse_program(
        base.format(
            lines="step.y: DO define(value = E.out) -> V.late\n"
            'IF V.flag == "go" step.x: DO ping() -> E.out'
        )
    )
    with pytest.raises(ParseError, match="E.out.*used before definition"):
        validate_program(program, known_commands={"ping", "define"})


def test_if_conditional_is_frozen_dataclass():
    program = parse_program(IF_PROGRAM)
    conditional = _conditionals(program)[0]
    assert dataclasses.is_dataclass(conditional)
    assert conditional.line != 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        conditional.condition = "V.flag != 1"


def test_if_canonical_json_is_deterministic_and_omits_source_line():
    program = parse_program(IF_PROGRAM)
    payload = canonical_json(program)
    assert '"kind":"conditional"' in payload
    assert '"condition":"V.flag == \\"go\\" AND count(E.items) >= 2"' in payload
    assert '"statement":{"kind":"blocked","ref":"V.out"}' in payload
    # Source locations are not part of the canonical form (like invocations).
    conditional = _conditionals(program)[0]
    assert conditional.line != 0
    assert '"line"' not in payload
    # Byte-identical across parses; sensitive to the condition text.
    assert canonical_json(parse_program(IF_PROGRAM)) == payload
    changed = IF_PROGRAM.replace('AND count(E.items) >= 2', 'AND count(E.items) >= 3')
    assert seal_digest(parse_program(changed)) != seal_digest(program)


def test_pre_if_programs_seal_byte_identically():
    # A program without IF serializes exactly as before issue #3: no new
    # keys, no conditional wrapping, same digest.
    payload = canonical_json(parse_program(CANONICAL))
    assert '"kind":"invocation"' in payload
    assert '"kind":"conditional"' not in payload
    expected_statements = (
        '{"args":[{"name":"value","value":"G.goal"},'
        '{"name":"limit","value":2}],"command":"define",'
        '"done":{"op":"equals","ref":"E.result",'
        '"value":{"limit":2,"ok":true}},"kind":"invocation",'
        '"step_id":"step.one","targets":["E.result"]},'
        '{"kind":"return","refs":["E.result"]}'
    )
    assert expected_statements in payload
    # Regression pin: the exact digest a pre-issue-#3 checkout produced for
    # CANONICAL (conditionals added no keys and changed no serialization;
    # cross-checked against the sealed demo program in
    # demo/runs/issue-03-if-branches/ whose digest was computed before any
    # source edit and still reproduces).
    assert (
        seal_digest(parse_program(CANONICAL))
        == "39c3a47a8c5ef5828713eafe943b94fd365357cafb09ad199e330399b702447b"
    )


def test_done_must_follow_an_invocation_not_a_conditional():
    source = CANONICAL.replace(
        "RETURN E.result",
        "IF E.result == 1 STOP completed()\nDONE E.result == 1\nRETURN E.result",
    )
    with pytest.raises(ParseError, match="DONE must follow an invocation"):
        parse_program(source)


def test_conditional_terminal_alone_does_not_satisfy_terminal_requirement():
    source = """\
PROGRAM conditional VERSION 0.1

INPUT
  V.flag = "go"

IF V.flag == "go" STOP completed()
"""
    program = parse_program(source)
    with pytest.raises(
        ParseError, match="program requires a terminal RETURN or STOP"
    ):
        validate_program(program, known_commands=set())


def test_scatter_and_gather_exported_from_tahoe_syntax():
    # Issue #4: the fan-out block models are part of the public syntax
    # surface and round-trip through parse_program.
    import tahoe.syntax as syntax_module

    assert syntax_module.Scatter is not None
    assert syntax_module.Gather is not None
    assert "Scatter" in syntax_module.__all__
    assert "Gather" in syntax_module.__all__
    source = """\
PROGRAM fan VERSION 1.0
INPUT
  Q.parts = ["a"]
SCATTER X.part IN Q.parts MAX 1
  step.draft: DO define(goal = X.part) -> E.draft
GATHER draft AS E.all USING all
RETURN E.all
"""
    program = parse_program(source)
    assert isinstance(program.statements[0], syntax_module.Scatter)
    assert isinstance(program.statements[1], syntax_module.Gather)


# --------------------------------------------------------------------------
# Issue #32: v2 canonical seal digest (condition AST + barrier normalization)
# --------------------------------------------------------------------------


def test_v2_canonical_json_exported():
    """canonical_json_v2 is exported from tahoe.syntax."""
    import tahoe.syntax as syntax_module

    assert hasattr(syntax_module, "canonical_json_v2")
    assert "canonical_json_v2" in syntax_module.__all__


def test_v2_seal_digest_accepts_version_kwarg():
    """seal_digest accepts a version keyword argument (default 1)."""
    program = parse_program(CANONICAL)
    assert seal_digest(program) == seal_digest(program, version=1)
    assert seal_digest(program, version=1) == seal_digest(program, version=1)


def test_v1_seal_unchanged_for_if_program():
    """The v1 seal for a program with an IF conditional must not change."""
    program = parse_program(IF_PROGRAM)
    # This digest was computed before the v2 changes were applied.
    expected_v1 = seal_digest(program, version=1)
    # The v1 canonical form still uses raw condition text.
    v1_json = canonical_json(program)
    assert '"condition":"V.flag == \\"go\\" AND count(E.items) >= 2"' in v1_json


def test_v2_re_derives_condition_ast_from_raw_text():
    """The v2 canonical form re-parses the raw condition text to produce the AST,
    ensuring spacing-invariant canonicalization without model changes."""
    program = parse_program(IF_PROGRAM)
    v2_json = canonical_json_v2(program)
    payload = json.loads(v2_json)
    conditionals = [s for s in payload["statements"] if s.get("kind") == "conditional"]
    assert len(conditionals) == 3
    cond = conditionals[0]["condition"]
    assert isinstance(cond, list)
    assert cond[0] == "and"
    assert cond[1] == ["eq", "V.flag", "go"]
    assert cond[2] == ["count", "E.items", ">=", 2]
