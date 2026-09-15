"""Every experiment/plan program must parse with the reference grammar.

The programs/ directory is the project's experiment record; a program that no
longer parses is a broken record. This test keeps the guarantee honest.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tahoe.syntax.parser import ParseError, parse_program

PROGRAMS = sorted((ROOT / "programs").rglob("*.think"))


def test_programs_exist():
    assert PROGRAMS, "no .think programs found under programs/"


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: str(p.relative_to(ROOT)))
def test_program_parses(path):
    text = path.read_text()
    with pytest.raises(ParseError):
        parse_program("garbage that must fail")
    try:
        program = parse_program(text)
    except ParseError as exc:
        raise AssertionError(f"{path.relative_to(ROOT)} does not parse: {exc}")
    invocations = [s for s in program.statements if type(s).__name__ == "Invocation"]
    assert invocations, f"{path.relative_to(ROOT)} has no steps"
    assert program.declarations or program.statements
