"""Focused tests for the canonical tikhon syntax.

Grammar under test (the API expected from tikhon.syntax):

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

import pytest

from tikhon.syntax import (
    Call,
    DonePredicate,
    Invocation,
    ParseError,
    Program,
    Return,
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
CALL protocol.framing(request = G.probe, scope = "src/tikhon") -> G.plan, V.analysis
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
        ("scope", "src/tikhon"),
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
        "CALL protocol.framing(request = G.probe, scope = \"src/tikhon\") -> G.plan, V.analysis",
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
        "CALL protocol.framing(request = G.probe, scope = \"src/tikhon\") -> G.plan, V.analysis",
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
        "CALL protocol.framing(request = G.probe, scope = \"src/tikhon\")",
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
        "CALL protocol.framing(request = G.probe, scope = \"src/tikhon\")",
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
        "CALL protocol.framing(request = G.probe, scope = \"src/tikhon\") -> G.plan, V.analysis",
        "CALL protocol.loop(request = G.probe, scope = \"src/tikhon\") -> G.plan, E.context",
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
        "CALL protocol.framing(request = G.probe, scope = \"src/tikhon\") -> G.plan, V.analysis",
        "CALL protocol.a1(request = G.probe, scope = \"src/tikhon\") -> G.plan, E.child",
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
