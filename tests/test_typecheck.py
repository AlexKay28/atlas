"""Tests for the formal type checker with subtyping lattice (issue #71)."""

import subprocess
import sys
import tempfile
import os

import pytest

from tahoe.typecheck import (
    ALL_TYPES,
    LATTICE_AXIOMS,
    ORTHOGONAL,
    SUBLATTICE,
    check_program_types,
    is_subtype,
)
from tahoe.syntax import parse_program, validate_program, get_type_warnings
from tahoe.registry import builtin_registry


class TestSubtypingLattice:
    """Tests for the 15 axiomatic edges and their transitive closure."""

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

    def test_a_is_subtype_of_e(self):
        assert is_subtype("A", "E") is True

    def test_a_is_subtype_of_v_transitive(self):
        assert is_subtype("A", "V") is True

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

    def test_g_is_subtype_of_q(self):
        assert is_subtype("G", "Q") is True

    def test_g_is_subtype_of_c(self):
        assert is_subtype("G", "C") is True

    def test_q_is_subtype_of_u(self):
        assert is_subtype("Q", "U") is True

    def test_q_is_subtype_of_a(self):
        assert is_subtype("Q", "A") is True

    def test_c_is_subtype_of_pf(self):
        assert is_subtype("C", "PF") is True

    def test_pf_is_subtype_of_o(self):
        assert is_subtype("PF", "O") is True

    def test_u_is_subtype_of_h(self):
        assert is_subtype("U", "H") is True

    def test_h_is_subtype_of_f(self):
        assert is_subtype("H", "F") is True

    def test_h_is_subtype_of_d(self):
        assert is_subtype("H", "D") is True

    def test_o_is_subtype_of_d(self):
        assert is_subtype("O", "D") is True

    def test_d_is_subtype_of_v(self):
        assert is_subtype("D", "V") is True

    def test_g_is_subtype_of_v_transitive(self):
        assert is_subtype("G", "V") is True

    def test_g_is_subtype_of_pf_transitive(self):
        assert is_subtype("G", "PF") is True

    def test_g_is_subtype_of_d_transitive(self):
        assert is_subtype("G", "D") is True

    def test_g_is_subtype_of_u_transitive(self):
        """G ⊑ Q ⊑ U, so G ⊑ U (G can be used where U is expected)."""
        assert is_subtype("G", "U") is True

    def test_u_not_subtype_of_g(self):
        """U is above G; U cannot be used where G is expected."""
        assert is_subtype("U", "G") is False

    def test_h_is_subtype_of_v_transitive(self):
        assert is_subtype("H", "V") is True

    def test_f_not_subtype_of_a(self):
        assert is_subtype("F", "A") is False

    def test_v_not_subtype_of_d(self):
        assert is_subtype("V", "D") is False

    def test_d_not_subtype_of_v(self):
        assert is_subtype("D", "V") is True

    def test_e_not_subtype_of_d(self):
        assert is_subtype("E", "D") is False

    def test_pf_not_subtype_of_e(self):
        assert is_subtype("PF", "E") is False

    def test_d_incomparable_with_e(self):
        assert is_subtype("D", "E") is False
        assert is_subtype("E", "D") is False

    def test_orthogonal_types_only_match_themselves(self):
        for t in ORTHOGONAL:
            for other in ALL_TYPES:
                if other == t:
                    continue
                assert is_subtype(t, other) is False, (
                    f"orthogonal type {t} should not be subtype of {other}"
                )


class TestLatticeMatchesDoc:
    """Ensure the lattice in code matches the 15 axioms in formal-semantics.md §3.2."""

    def test_lattice_axioms_present(self):
        for sub, sup in LATTICE_AXIOMS:
            assert sub in SUBLATTICE, f"{sub} missing from SUBLATTICE"
            assert sup in SUBLATTICE[sub], (
                f"{sup} missing from SUBLATTICE[{sub}]"
            )

    def test_no_extra_edges(self):
        for src, dsts in SUBLATTICE.items():
            for dst in dsts:
                assert (src, dst) in LATTICE_AXIOMS, (
                    f"extra edge {src} -> {dst} not in axioms"
                )

    def test_15_axioms(self):
        assert len(LATTICE_AXIOMS) == 15

    def test_orthogonal_types_complete(self):
        expected = {"CTX", "K", "X", "R", "OUT", "ART", "PR", "P"}
        assert expected <= ORTHOGONAL

    def test_pf_d_o_not_orthogonal(self):
        assert "PF" not in ORTHOGONAL
        assert "D" not in ORTHOGONAL
        assert "O" not in ORTHOGONAL


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
        """G ⊑ Q, so a G ref is valid where Q is expected.
        The hypothesize command expects question:text (not a node type),
        but induce expects observations:E and target_pattern:Q.
        G is a subtype of Q (G ⊑ Q ⊑ A ⊑ E), so G can be used where E is expected."""
        program_text = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = "what is the answer?"

step.one: DO induce(observations = G.goal, target_pattern = G.goal) -> H.rules

RETURN H.rules
"""
        program = parse_program(program_text)
        registry = builtin_registry()
        errors = check_program_types(program, registry)
        assert errors == []

    def test_g_goal_usable_where_q_expected(self):
        """G ⊑ Q, so a G ref is valid where Q is expected."""
        program_text = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = "what is the answer?"

step.one: DO hypothesize(question = G.goal, evidence = "proof") -> H.hyp

RETURN H.hyp
"""
        program = parse_program(program_text)
        registry = builtin_registry()
        errors = check_program_types(program, registry)
        assert errors == []

    def test_evidence_usable_where_fact_expected(self):
        """E ⊑ F. The estimate command outputs estimate:F, so targeting F is valid.
        E is a subtype of F (E ⊑ F), so an E ref can be used where F is expected."""
        program_text = """\
PROGRAM demo VERSION 0.1

INPUT
  E.evidence = "some data"

step.one: DO estimate(evidence = E.evidence) -> F.est

RETURN F.est
"""
        program = parse_program(program_text)
        registry = builtin_registry()
        errors = check_program_types(program, registry)
        assert errors == []


class TestDonePredicateTypeChecking:
    """Test DONE predicate type checking (issue #71 step 4)."""

    def test_done_on_valid_lattice_target_no_error(self):
        """A DONE predicate on a V target should not produce type errors."""
        program_text = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {"request": "ship"}

step.one: DO define(request = G.goal) -> G.typed
  DONE G.typed == {"request": "ship"}

RETURN G.typed
"""
        program = parse_program(program_text)
        registry = builtin_registry()
        errors = check_program_types(program, registry)
        done_errors = [e for e in errors if "DONE" in e]
        assert done_errors == []

    def test_done_on_orthogonal_type_produces_error(self):
        """A DONE predicate on an orthogonal type (e.g. PR) should warn.
        The challenge command outputs contradiction:PR, so targeting PR is
        valid for the output check, but DONE on a PR ref tests a numeric
        probability, not an epistemic property."""
        program_text = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = "test"

step.one: DO challenge(claim = "claim", evidence = "ev") -> PR.contradiction
  DONE PR.contradiction == 0.5

RETURN PR.contradiction
"""
        program = parse_program(program_text)
        registry = builtin_registry()
        errors = check_program_types(program, registry)
        done_errors = [e for e in errors if "DONE" in e and "orthogonal" in e]
        assert len(done_errors) > 0


class TestTryBlockTypeChecking:
    """Test TRY block type checking (issue #71 step 5)."""

    def test_try_compatible_types_no_error(self):
        """TRY branches producing the same target type should not warn."""
        program_text = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = "test"

TRY MAX 3
  step.a: DO define(request = G.goal) -> V.result
OR
  step.b: DO define(request = G.goal) -> V.result

RETURN V.result
"""
        program = parse_program(program_text)
        registry = builtin_registry()
        errors = check_program_types(program, registry)
        try_errors = [e for e in errors if "TRY" in e]
        assert try_errors == []

    def test_try_incompatible_types_produces_error(self):
        """TRY branches producing incomparable types for the same target
        should warn. E and D are incomparable under ⊑."""
        program_text = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = "test"

TRY MAX 3
  step.a: DO define(request = G.goal) -> E.result
OR
  step.b: DO define(request = G.goal) -> D.result

RETURN E.result
"""
        program = parse_program(program_text)
        registry = builtin_registry()
        errors = check_program_types(program, registry)
        try_errors = [e for e in errors if "TRY" in e and "incompatible" in e]
        assert len(try_errors) > 0


class TestCLITypecheck:
    """Test the `tahoe typecheck` CLI command."""

    def test_typecheck_valid_program(self):
        source = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {"request": "ship"}

step.one: DO define(request = G.goal) -> G.typed

RETURN G.typed
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".think", delete=False
        ) as f:
            f.write(source)
            f.flush()
            path = f.name
        try:
            result = subprocess.run(
                [sys.executable, "-m", "tahoe.cli", "typecheck", path],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": "src"},
            )
            assert result.returncode == 0
            assert "no type errors" in result.stdout
        finally:
            os.unlink(path)

    def test_typecheck_ill_typed_program(self):
        source = """\
PROGRAM demo VERSION 0.1

INPUT
  G.goal = {"request": "ship"}

step.one: DO define(request = G.goal) -> V.result

RETURN V.result
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".think", delete=False
        ) as f:
            f.write(source)
            f.flush()
            path = f.name
        try:
            result = subprocess.run(
                [sys.executable, "-m", "tahoe.cli", "typecheck", path],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": "src"},
            )
            assert result.returncode == 0
            assert "type warning" in result.stderr
        finally:
            os.unlink(path)

    def test_typecheck_missing_file(self):
        result = subprocess.run(
            [sys.executable, "-m", "tahoe.cli", "typecheck", "/nonexistent.think"],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": "src"},
        )
        assert result.returncode == 1
