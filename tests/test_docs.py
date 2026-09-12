"""Documentation consistency tests (issue #49).

Verifies that:
1. Every subcommand name from ``tahoe.cli._build_parser()`` appears in the
   README's CLI reference section.
2. The design-doc command count matches ``len(builtin_registry().names())``.
3. CHANGELOG.md exists and references the registry vocabulary.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tahoe.cli import _build_parser
from tahoe.registry import builtin_registry

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    full = REPO_ROOT / path
    return full.read_text(encoding="utf-8")


def _cli_subcommand_names() -> list[str]:
    """Extract subcommand names registered in the argparse parser."""
    import argparse

    parser = _build_parser()
    names: list[str] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            names = sorted(action.choices.keys())
    return names


def _readme_cli_table_names() -> set[str]:
    """Extract subcommand names from the README CLI Reference table."""
    readme = _read("README.md")
    # The table has rows like: | `lint` | ... |
    pattern = re.compile(r"^\|\s*`([a-z]+)`\s*\|", re.MULTILINE)
    matches = pattern.findall(readme)
    return set(matches)


def test_all_cli_subcommands_in_readme():
    """Every subcommand from _build_parser() appears in the README table."""
    cli_names = set(_cli_subcommand_names())
    readme_names = _readme_cli_table_names()
    missing = cli_names - readme_names
    assert not missing, (
        f"CLI subcommands missing from README CLI Reference: {sorted(missing)}"
    )


def test_design_doc_command_count_matches_registry():
    """The design doc command count matches len(builtin_registry().names())."""
    doc = _read("docs/design/01-reasoning-language-foundation.md")
    actual_count = len(builtin_registry().names())
    # Look for "frozen at N commands" pattern
    pattern = re.compile(r"frozen at (\d+) commands")
    matches = pattern.findall(doc)
    assert matches, "Design doc does not contain 'frozen at N commands' pattern"
    for match in matches:
        doc_count = int(match)
        assert doc_count == actual_count, (
            f"Design doc says {doc_count} commands but registry has {actual_count}"
        )
    # Also check "N-command registry" pattern
    pattern2 = re.compile(r"(\d+)-command registry")
    matches2 = pattern2.findall(doc)
    for match in matches2:
        doc_count = int(match)
        assert doc_count == actual_count, (
            f"Design doc says {doc_count}-command registry but registry has {actual_count}"
        )


def test_changelog_exists():
    """CHANGELOG.md exists at the repo root."""
    changelog = REPO_ROOT / "CHANGELOG.md"
    assert changelog.exists(), "CHANGELOG.md not found at repo root"


def test_changelog_has_keep_a_changelog_format():
    """CHANGELOG.md follows Keep-a-Changelog format with version sections."""
    content = _read("CHANGELOG.md")
    assert "Keep a Changelog" in content, (
        "CHANGELOG.md does not reference Keep a Changelog format"
    )
    # Must have at least [Unreleased] and [0.1.0] sections
    assert re.search(r"##\s*\[Unreleased\]", content), (
        "CHANGELOG.md missing [Unreleased] section"
    )
    assert re.search(r"##\s*\[0\.1\.0\]", content), (
        "CHANGELOG.md missing [0.1.0] section"
    )


def test_changelog_references_registry_vocabulary():
    """CHANGELOG.md references the registry vocabulary / command names."""
    content = _read("CHANGELOG.md")
    # The CHANGELOG should mention the registry or command vocabulary
    assert re.search(r"registry|command|vocab", content, re.IGNORECASE), (
        "CHANGELOG.md does not reference the registry vocabulary"
    )
    # Should mention at least some command names from the registry
    registry_names = builtin_registry().names()
    mentioned = 0
    for name in registry_names:
        if name in content:
            mentioned += 1
    assert mentioned >= 5, (
        f"CHANGELOG.md mentions only {mentioned} registry command names; "
        f"expected at least 5"
    )


def test_readme_links_changelog():
    """README links to CHANGELOG.md."""
    readme = _read("README.md")
    assert "CHANGELOG" in readme, "README does not link to CHANGELOG.md"


def test_skill_md_has_step0_inventory_gate():
    """tahoe-demo SKILL.md contains Step 0 skill/MCP inventory gate."""
    skill = _read(".opencode/skills/tahoe-demo/SKILL.md")
    assert "Step 0" in skill, "SKILL.md missing 'Step 0' heading"
    assert "skill/mcp" in skill.lower(), (
        "SKILL.md missing 'skill/MCP' in Step 0"
    )
    # Decision rule must be present
    assert "local match" in skill.lower(), (
        "SKILL.md missing the decision rule ('local match')"
    )
    assert "ahood skill search" in skill, (
        "SKILL.md missing 'ahood skill search' command"
    )
    assert "ahood skill add" in skill, (
        "SKILL.md missing 'ahood skill add' command"
    )
    assert "skills.lock.json" in skill, (
        "SKILL.md missing lockfile verification reference"
    )


def test_worker_adapter_t3_prompt_has_inventory_check():
    """worker_adapter.py T3 delegate prompt includes the inventory check."""
    adapter = _read("src/tahoe/worker_adapter.py")
    # The T3 delegate authoring block must mention the inventory check
    assert "Step 0" in adapter, (
        "worker_adapter.py T3 prompt missing 'Step 0' reference"
    )
    assert "ahood skill search" in adapter, (
        "worker_adapter.py T3 prompt missing 'ahood skill search'"
    )
    assert "ahood skill add" in adapter, (
        "worker_adapter.py T3 prompt missing 'ahood skill add'"
    )
    assert "skills.lock.json" in adapter, (
        "worker_adapter.py T3 prompt missing lockfile reference"
    )
