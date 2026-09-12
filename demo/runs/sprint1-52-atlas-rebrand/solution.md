# solution.md — sprint1-52-atlas-rebrand

GitHub issue #52: Rebranding tikhon → ATLAS (Agent Task Language & Audit System).

## What was done

A mechanical package rename from `tikhon` to `atlas` (ATLAS — Agent Task Language &
Audit System) across all live code, docs, tests, and branding.

### Key renames

| Before | After |
|---|---|
| `src/tikhon/` (30 files) | `src/atlas/` (30 files, git mv) |
| `from tikhon.` / `import tikhon.` | `from atlas.` / `import atlas.` |
| `TIKHON_*` env vars | `ATLAS_*` env vars |
| `prog="tikhon"` | `prog="atlas"` |
| `tikhon` CLI commands in help/error strings | `atlas` |
| `Tikhon` in docstrings/branding | `ATLAS` |
| `"tikhon"` arm kind in eval.py | `"atlas"` |
| `tikhon-core` arm name in tests | `atlas-core` |
| `.opencode/skills/tikhon-demo/` | `.opencode/skills/atlas-demo/` |
| `pyproject.toml: name = "tikhon"` | `name = "atlas"` |
| `pyproject.toml: tikhon = "tikhon.cli:main"` | `atlas = "atlas.cli:main"` |
| `pyproject.toml: version = {attr = "tikhon.__version__"}` | `version = {attr = "atlas.__version__"}` |
| `pyproject.toml: urls github.com/AlexKay28/tikhon` | `github.com/AlexKay28/atlas` |
| `README.md: # Tikhon` | `# ATLAS — Agent Task Language & Audit System` |
| `docs/**: Tikhon/tikhon references` | `ATLAS/atlas` |
| `protocols/framing.think: tikhon program` | `ATLAS program` |
| `CHANGELOG.md: [Unreleased]` | Added Changed/Renamed entry |

### Files changed

68 entries in `git status --porcelain`:
- 30 source files: `src/tikhon/` → `src/atlas/` (git mv + content edits)
- 28 test files: import/reference updates
- 5 doc files: `docs/README.md`, `docs/cli-reference.md`, `docs/design/01-reasoning-language-foundation.md`, `docs/eval-pilot.md`
- 1 pyproject.toml
- 1 README.md
- 1 CHANGELOG.md
- 1 protocols/framing.think
- 1 skill: `.opencode/skills/tikhon-demo/` → `.opencode/skills/atlas-demo/` (git mv + edit)
- 1 new: `tests/test_branding.py` (grep gate test)
- 1 new: `demo/runs/sprint1-52-atlas-rebrand/` (this run)

### Grep gate

`tests/test_branding.py` asserts `git grep -i -c tikhon -- src/ tests/ README.md docs/ pyproject.toml .opencode/` returns zero matches. Historical `demo/runs/**` are exempt (immutable evidence).

## Verification results

- **Full test suite**: 857 passed in 22.44s (baseline 854 + 1 branding + 2 from eval arm rename)
- **Seals**: 39/39 verified byte-identically (the rename's correctness proof — no sealed artifact changed meaning)
- **Grep gate**: passed (zero tikhon references in live code/docs)
- **Smoke test**: `PYTHONPATH=src python3 -m atlas lint demo/runs/issue-26-benchmarks/program.think` → valid
- **git status**: only in-scope paths changed; no forbidden paths touched

## What's left for the orchestrator

- GitHub repo rename: `AlexKay28/tikhon` → `AlexKay28/atlas`
- Update local git remote URL
- ahood-side copies of the skill (updated separately by the owner)

## Deviations

- `protocols/framing.think` comment was updated (`tikhon program` → `ATLAS program`) — not explicitly listed in the owned files or forbidden list, but it's a live code file with a branding reference.
- `benchmarks/report-2026-09-12.md` was NOT updated — it's a generated artifact not in the grep gate scope; regenerating it with `atlas bench` would produce the updated branding, but the issue doesn't list it as an owned file.

## Constraints honored

- No git commit/push
- No GitHub operations
- No forbidden paths touched (demo/runs/** except own, .claude/**, .git/**)
- CHANGELOG history sections untouched
- Program grammar unchanged (only branding, package names, CLI names)
- All sealed digests reproduce byte-identically
