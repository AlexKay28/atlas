# Issue #53: Rebrand ATLAS → TAHOE

## Summary

Rebranded the project from ATLAS (Agent Task Language & Audit System) to
TAHOE (Task-Aware Language Harness for Orchestrated Execution). The rename
is mechanical: package, CLI, imports, docstrings, help strings, error
messages, env var names, URLs, and documentation references are updated.
The language grammar itself is unchanged.

## Files Changed

- **67 files changed** (31 src, 29 tests, 4 docs, README.md, pyproject.toml, CHANGELOG.md, .opencode/skills/tahoe-demo/SKILL.md)
- **Key renames:**
  - `src/atlas/` → `src/tahoe/` (git mv, history preserved)
  - `.opencode/skills/atlas-demo/` → `.opencode/skills/tahoe-demo/` (git mv)
  - All imports: `from atlas.X` → `from tahoe.X`
  - CLI prog: `prog="atlas"` → `prog="tahoe"`
  - Env vars: `ATLAS_*` → `TAHOE_*`
  - Package name: `atlas` → `tahoe`
  - Script entry: `atlas = "atlas.cli:main"` → `tahoe = "tahoe.cli:main"`
  - URLs: `github.com/AlexKay28/atlas` → `github.com/AlexKay28/tahoe`

## Verification

- **pytest:** 857 passed in 22.28s
- **SEALS:** 40/40 verified (39 historical + 1 new, all byte-identical)
- **Grep gate:** `git grep -i atlas` over src/ tests/ README.md docs/ pyproject.toml .opencode/ (excluding test_branding.py) returns ZERO
- **Smoke test:** `tahoe lint demo/runs/issue-26-benchmarks/program.think` → valid (exit 0)

## What's Left for the Orchestrator

- GitHub repo rename: `AlexKay28/atlas` → `AlexKay28/tahoe` (with redirect)
- Local remote URL update
- Repo description update on GitHub
- ahood-side copies of the skill (if any)
