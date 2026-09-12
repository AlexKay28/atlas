"""Tests for the v2 canonical seal digest (issue #32).

Acceptance criteria:
  (1) v2 seals equal for programs differing only in condition spacing;
  (2) bare-BARRIER vs explicit-union seal identically under v2;
  (3) ALL 39 historical seals still verify under the default v1 path
      (regression test looping demo/runs/*/seal.txt);
  (4) v2 canonical json contains no raw condition string;
  (5) v1 and v2 digest versions produce different digests when programs
      contain IF conditionals or PAR blocks (sanity), but the same digest
      for programs with neither (no change).
"""

import json
from pathlib import Path

import pytest

from tahoe.syntax import (
    canonical_json,
    canonical_json_v2,
    parse_program,
    seal_digest,
)

# A program with an IF conditional (varying spacing in condition text).
BASE_IF = """\
PROGRAM gated VERSION 0.1

INPUT
  V.flag = "go"
  E.items = [1, 2, 3]

step.one: DO define(value = V.flag) -> V.out
IF V.flag == "go" AND count(E.items) >= 2 STOP blocked(V.out)
RETURN V.out
"""

SPACED_IF = """\
PROGRAM gated VERSION 0.1

INPUT
  V.flag = "go"
  E.items = [1, 2, 3]

step.one: DO define(value = V.flag) -> V.out
IF V.flag  ==  "go"  AND  count(E.items)  >=  2  STOP blocked(V.out)
RETURN V.out
"""

# A PAR program with bare BARRIER (no explicit target declaration).
PAR_BARE_BARRIER = """\
PROGRAM par VERSION 1.0
INPUT
    G.goal = "test"
PAR MAX 2
    step.a: DO define(x = 1) -> E.a
    step.b: DO define(x = 2) -> E.b
BARRIER
RETURN E.a
"""

# The same PAR program with explicit BARRIER -> matching the union.
PAR_EXPLICIT_BARRIER = """\
PROGRAM par VERSION 1.0
INPUT
    G.goal = "test"
PAR MAX 2
    step.a: DO define(x = 1) -> E.a
    step.b: DO define(x = 2) -> E.b
BARRIER -> E.a, E.b
RETURN E.a
"""

# The same PAR program with explicit BARRIER -> in a different order.
PAR_REORDERED_BARRIER = """\
PROGRAM par VERSION 1.0
INPUT
    G.goal = "test"
PAR MAX 2
    step.a: DO define(x = 1) -> E.a
    step.b: DO define(x = 2) -> E.b
BARRIER -> E.b, E.a
RETURN E.a
"""


# ---------------------------------------------------------------------------
# Acceptance (1): v2 seals equal for programs differing only in condition
# spacing.
# ---------------------------------------------------------------------------


def test_v2_condition_spacing_invariant():
    """Programs differing only in condition spacing seal identically under v2."""
    base = parse_program(BASE_IF)
    spaced = parse_program(SPACED_IF)
    assert seal_digest(base, version=2) == seal_digest(spaced, version=2)


def test_v1_condition_spacing_sensitive():
    """Under v1, spacing changes the seal (the bug we are fixing)."""
    base = parse_program(BASE_IF)
    spaced = parse_program(SPACED_IF)
    assert seal_digest(base, version=1) != seal_digest(spaced, version=1)


# ---------------------------------------------------------------------------
# Acceptance (2): bare-BARRIER vs explicit-union seal identically under v2.
# ---------------------------------------------------------------------------


def test_v2_bare_barrier_matches_explicit_barrier():
    """Bare BARRIER and BARRIER -> <union> seal identically under v2."""
    bare = parse_program(PAR_BARE_BARRIER)
    explicit = parse_program(PAR_EXPLICIT_BARRIER)
    assert seal_digest(bare, version=2) == seal_digest(explicit, version=2)


def test_v2_reordered_barrier_matches_bare():
    """BARRIER -> in a different order also seals identically under v2."""
    bare = parse_program(PAR_BARE_BARRIER)
    reordered = parse_program(PAR_REORDERED_BARRIER)
    assert seal_digest(bare, version=2) == seal_digest(reordered, version=2)


def test_v1_bare_barrier_differs_from_explicit():
    """Under v1, bare vs explicit barrier produce different seals (the bug)."""
    bare = parse_program(PAR_BARE_BARRIER)
    explicit = parse_program(PAR_EXPLICIT_BARRIER)
    assert seal_digest(bare, version=1) != seal_digest(explicit, version=1)


# ---------------------------------------------------------------------------
# Acceptance (3): ALL 39 historical seals still verify under the default v1
# path.
# ---------------------------------------------------------------------------

DEMO_RUNS = Path(__file__).resolve().parent.parent / "demo" / "runs"


def _historical_seal_dirs():
    """Return all demo/runs/*/ directories that have a seal.txt."""
    if not DEMO_RUNS.exists():
        return []
    result = []
    for entry in sorted(DEMO_RUNS.iterdir()):
        seal_file = entry / "seal.txt"
        if seal_file.is_file():
            result.append(entry)
    return result


def test_all_historical_seals_verify_v1():
    """Every historical seal.txt must still verify under the default v1 path."""
    dirs = _historical_seal_dirs()
    assert len(dirs) >= 39, f"expected >=39 historical seals, found {len(dirs)}"
    failures = []
    for run_dir in dirs:
        seal_text = (run_dir / "seal.txt").read_text().strip()
        program_file = run_dir / "program.think"
        if not program_file.is_file():
            continue
        program = parse_program(program_file.read_text())
        computed = seal_digest(program, version=1)
        if computed != seal_text:
            failures.append(f"{run_dir.name}: expected {seal_text}, got {computed}")
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Acceptance (4): v2 canonical json contains no raw condition string.
# ---------------------------------------------------------------------------


def test_v2_canonical_json_has_no_raw_condition_string():
    """The v2 canonical JSON must not contain the raw condition text."""
    program = parse_program(BASE_IF)
    v2_json = canonical_json_v2(program)
    payload = json.loads(v2_json)
    for stmt in payload["statements"]:
        if stmt.get("kind") == "conditional":
            condition = stmt["condition"]
            assert isinstance(condition, list), (
                "v2 condition must be a list (AST), not a raw string"
            )
            assert not isinstance(condition, str), (
                "v2 condition must not be a raw string"
            )
    assert '"condition":"V.flag' not in v2_json, (
        "v2 canonical JSON must not contain raw condition text"
    )


def test_v2_canonical_json_condition_is_ast_list():
    """The v2 canonical JSON serializes the condition as a structured AST list."""
    program = parse_program(BASE_IF)
    v2_json = canonical_json_v2(program)
    payload = json.loads(v2_json)
    conditionals = [s for s in payload["statements"] if s.get("kind") == "conditional"]
    assert len(conditionals) == 1
    cond = conditionals[0]["condition"]
    assert isinstance(cond, list)
    assert cond[0] == "and"
    assert cond[1] == ["eq", "V.flag", "go"]
    assert cond[2] == ["count", "E.items", ">=", 2]


# ---------------------------------------------------------------------------
# Acceptance (5): v1 and v2 produce different digests when programs contain
# IF or PAR, but the same digest for plain programs.
# ---------------------------------------------------------------------------


def test_v1_and_v2_differ_for_if_program():
    program = parse_program(BASE_IF)
    assert seal_digest(program, version=1) != seal_digest(program, version=2)


def test_v1_and_v2_differ_for_par_program():
    program = parse_program(PAR_BARE_BARRIER)
    assert seal_digest(program, version=1) != seal_digest(program, version=2)


def test_v1_and_v2_same_for_plain_program():
    """A program with no IF and no PAR produces the same digest under both versions."""
    plain = """\
PROGRAM plain VERSION 1.0
INPUT
    G.goal = "test"
step.one: DO define(value = G.goal) -> E.result
RETURN E.result
"""
    program = parse_program(plain)
    assert seal_digest(program, version=1) == seal_digest(program, version=2)


# ---------------------------------------------------------------------------
# CLI --v2 flag (requires cli.py edit; not in owned files — tested via API)
# ---------------------------------------------------------------------------


def test_v2_seal_digest_api_matches_v1_for_plain():
    """For programs without IF/PAR, v1 and v2 produce the same digest (API-level)."""
    plain = """\
PROGRAM plain VERSION 1.0
INPUT
    G.goal = "test"
step.one: DO define(value = G.goal) -> E.result
RETURN E.result
"""
    program = parse_program(plain)
    assert seal_digest(program, version=1) == seal_digest(program, version=2)


# ---------------------------------------------------------------------------
# v2 canonical_json is deterministic
# ---------------------------------------------------------------------------


def test_v2_canonical_json_is_deterministic():
    """Parsing the same program twice produces identical v2 canonical JSON."""
    program = parse_program(BASE_IF)
    assert canonical_json_v2(program) == canonical_json_v2(parse_program(BASE_IF))


def test_v2_seal_digest_is_deterministic():
    """Parsing the same program twice produces identical v2 seal digests."""
    program = parse_program(BASE_IF)
    assert seal_digest(program, version=2) == seal_digest(
        parse_program(BASE_IF), version=2
    )


# ---------------------------------------------------------------------------
# v2 barrier normalization: sorted union of branch targets
# ---------------------------------------------------------------------------


def test_v2_barrier_is_sorted_union():
    """The v2 canonical JSON serializes barrier as the sorted branch-target union."""
    program = parse_program(PAR_EXPLICIT_BARRIER)
    v2_json = canonical_json_v2(program)
    payload = json.loads(v2_json)
    par_stmt = payload["statements"][0]
    assert par_stmt["kind"] == "par"
    assert par_stmt["barrier"] == ["E.a", "E.b"]


def test_v2_barrier_empty_when_no_targets():
    """A program without PAR still produces valid v2 canonical JSON."""
    plain = """\
PROGRAM plain VERSION 1.0
INPUT
    G.goal = "test"
step.one: DO define(value = G.goal) -> E.result
RETURN E.result
"""
    program = parse_program(plain)
    v2_json = canonical_json_v2(program)
    payload = json.loads(v2_json)
    assert payload["statements"][0]["kind"] == "invocation"
    assert payload["statements"][1]["kind"] == "return"


# ---------------------------------------------------------------------------
# Invalid version raises
# ---------------------------------------------------------------------------


def test_seal_digest_invalid_version_raises():
    program = parse_program(BASE_IF)
    with pytest.raises(Exception):
        seal_digest(program, version=3)
