"""Tests for the formal type checker with subtyping lattice (issue #71)."""

import pytest

from tahoe.typecheck import (
    ALL_TYPES,
    ORTHOGONAL,
    SUBLATTICE,
    check_program_types,
    is_subtype,
)
from tahoe.syntax import parse_program, validate_program, get_type_warnings
from tahoe.registry import builtin_registry


class TestSubtypingLattice:
    def test_e_is_subtype_of_f(self):
        assert is_subtype("E", "F") is True

    def test_f_is_subtype_of_v(self):
        assert is_subtype("F", "V") is True

    def test_e_is_subtype_of_v_transitive(self):
        assert is_subtype("E", "V") is True

    def test_v_is_not_subtype_of_e(self):
        assert is_subtype("V", "E") is False

    def test_a_is_subtype_of_h(self):
        assert is_subtype("A", "H") is True

    def test_a_is_subtype_of_f_transitive_through_h(self):
        assert is_subtype("A", "F") is True

    def test_ctx_same_type(self):
        assert is_subtype("CTX", "CTX") is True

    def test_ctx_not_subtype_of_g(self):
        assert is_subtype("CTX", "G") is False

    def test_pr_same_type(self):
        assert is_subtype("PR", "PR") is True

    def test_pr_not_subtype_of_f(self):
        assert is_subtype("PR", "F") is False

    def test_reflexivity(self):
        for t in ALL_TYPES:
            assert is_subtype(t, t) is True, f"{t} should be a subtype of itself"

    def test_g_is_supertype_of_q_and_c(self):
        assert is_subtype("Q", "G") is True
        assert is_subtype("C", "G") is True

    def test_u_is_subtype_of_g_transitive(self):
        assert is_subtype("U", "G") is True

    def test_c_is_subtype_of_g(self):
        assert is_subtype("C", "G") is True

    def test_h_is_subtype_of_v_transitive(self):
        assert is_subtype("H", "V") is True

    def test_f_not_subtype_of_a(self):
        assert is_subtype("F", "A") is False

    def test_v_not_subtype_of_d(self):
        assert is_subtype("V", "D") is False

    def test_d_not_subtype_of_v(self):
        assert is_subtype("D", "V") is False

    def test_e_not_subtype_of_d(self):
        assert is_subtype("E", "D") is False

    def test_orthogonal_types_only_match_themselves(self):
        for t in ORTHOGONAL:
            for other in ALL_TYPES:
                if other == t:
                    continue
                assert is_subtype(t, other) is False, (
                    f"orthogonal type {t} should not be subtype of {other}"
                )


class TestProgramTypeChecking:
    """Test that check_program_types produces warnings for ill-typed programs
    and no warnings for well-typed programs."""

    WELL_TYPED = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {"request": "ship"}

step.one: DO define(request = G.goal) -> G.typed

RETURN G.typed
"""

    ILL_TYPED_OUTPUT = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {"request": "ship"}

step.one: DO define(request = G.goal) -> V.result

RETURN V.result
"""

    def test_well_typed_program_no_warnings(self):
        program = parse_program(self.WELL_TYPED)
        registry = builtin_registry()
        errors = check_program_types(program, registry)
        assert errors == []

    def test_ill_typed_program_produces_warnings(self):
        program = parse_program(self.ILL_TYPED_OUTPUT)
        registry = builtin_registry()
        errors = check_program_types(program, registry)
        assert len(errors) > 0

    def test_validate_program_collects_type_warnings(self):
        program = parse_program(self.ILL_TYPED_OUTPUT)
        validate_program(program)
        warnings = get_type_warnings()
        assert len(warnings) > 0

    def test_validate_program_no_warnings_for_well_typed(self):
        program = parse_program(self.WELL_TYPED)
        validate_program(program)
        warnings = get_type_warnings()
        assert warnings == []

    def test_subtyping_allows_stronger_input(self):
        """A Q ref should be usable where G is expected (Q ⊑ G)."""
        program_text = """\
PROGRAM demo VERSION 0.1

INPUT
  Q.question = "what is the answer?"

step.one: DO verify(goal = Q.question, evidence = "proof") -> V.verdict

RETURN V.verdict
"""
        program = parse_program(program_text)
        registry = builtin_registry()
        errors = check_program_types(program, registry)
        assert errors == []


class TestSubtypingLatticeMatchesDoc:
    """Ensure the lattice in code matches the lattice in the formal-semantics doc."""

    def test_lattice_axioms_present(self):
        expected_edges = {
            "E": "F",
            "F": "V",
            "A": "H",
            "H": "F",
            "U": "Q",
            "Q": "G",
            "C": "G",
        }
        for src, dst in expected_edges.items():
            assert src in SUBLATTICE, f"{src} missing from SUBLATTICE"
            assert SUBLATTICE[src] == dst, (
                f"SUBLATTICE[{src}] = {SUBLATTICE[src]!r}, expected {dst!r}"
            )

    def test_orthogonal_types_complete(self):
        expected = {"CTX", "K", "X", "R", "OUT", "ART", "PR", "PF", "D", "O", "P"}
        assert expected <= ORTHOGONAL
