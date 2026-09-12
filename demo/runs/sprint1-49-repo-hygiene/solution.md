# Solution — issue #49 repo hygiene

## Files changed

| File | Action | Description |
| --- | --- | --- |
| `pyproject.toml` | Modified | Dynamic version via `tool.setuptools.dynamic`, authors, MIT license with license-files, classifiers, keywords, project.urls |
| `CHANGELOG.md` | New | Keep-a-Changelog format; [0.1.0] backfilled from git history (#1–#27); [Unreleased] listing #28–#49; registry vocabulary section |
| `README.md` | Modified | CLI Reference table with all 13 subcommands; links to CHANGELOG and design doc |
| `docs/design/01-reasoning-language-foundation.md` | Modified | Fixed "22 commands" → "23 commands" in both places (line 54 and line 261) |
| `docs/cli-reference.md` | New | Full CLI reference page with subcommand catalog, command groups, and registry vocabulary |
| `docs/README.md` | Modified | Added link to CLI reference page |
| `tests/test_docs.py` | New | 6 tests: subcommand coverage in README, design-doc count matches registry, CHANGELOG existence/format/vocabulary, README links CHANGELOG |
| `demo/runs/sprint1-49-repo-hygiene/` | New | Tikhon run artifacts: program.think, seal.txt, WORKLOG.md, solution.md, evaluation.json |

## pyproject.toml changes

- `version = "0.1.0"` → `dynamic = ["version"]`
- Added `[tool.setuptools.dynamic]` with `version = {attr = "tikhon.__version__"}`
- Added `authors = [{name = "AlexKay28", email = "..."}]`
- Changed `license = {text = "MIT"}` → `license = "MIT"` + `license-files = ["LICENSE"]`
- Added classifiers: Development Status 3-Alpha, Python 3.10- 3.13, Topic
- Added project.urls: Changelog, Issues
- Kept existing: keywords, console script, deps, pytest config

## CHANGELOG.md

- Format: Keep-a-Changelog v1.1.0
- [0.1.0]: backfilled from 15 git commits mapping to issues #1–#27
- [Unreleased]: lists sprint issues #28–#49 by title
- Registry vocabulary section: documents the 23-command registry with all command names listed

## CLI Reference table (README)

All 13 subcommands from `_build_parser()`:

`lint`, `seal`, `run`, `resume`, `status`, `events`, `audit`, `learn`,
`bench`, `next`, `submit`, `ready`, `claim`

Each row includes: subcommand name, required flags, purpose.

## Design doc fix

- Line 54: "frozen at 22 commands" → "frozen at 23 commands"
- Line 261: "22-command registry" → "23-command registry"
- Verified: `len(builtin_registry().names()) == 23`

## Tests

- 6 new tests in `tests/test_docs.py`
- Full suite: **766 passed** (760 baseline + 6 new) in 21.01s
- New tests cover: (1) all CLI subcommands in README, (2) design-doc count
  matches registry, (3) CHANGELOG exists, (4) CHANGELOG has Keep-a-Changelog
  format, (5) CHANGELOG references registry vocabulary, (6) README links
  CHANGELOG

## Constraints honored

- Only owned files touched (pyproject.toml, CHANGELOG.md, README.md, docs/**,
  tests/test_docs.py, demo/runs/sprint1-49-repo-hygiene/)
- No src/tikhon/ files edited (cli.py read-only for subcommand extraction)
- No .opencode/, .claude/, .git/ files touched
- No git commit/push
- Program sealed before any edit; seal verified after all edits
