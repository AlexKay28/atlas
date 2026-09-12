# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Sprint 1 — repository hygiene, documentation, and tooling improvements.

- **#28** — CLI reference documentation and README enhancement
- **#29** — CONTRIBUTING guide and developer onboarding docs
- **#30** — Issue templates and PR template
- **#31** — GitHub Actions CI workflow
- **#32** — Code coverage reporting
- **#33** — Pre-commit hooks and ruff configuration
- **#34** — Type checking with mypy
- **#35** — API stability and deprecation policy
- **#36** — Examples gallery and tutorial programs
- **#37** — Internationalization support for program text
- **#38** — Plugin discovery and third-party registry loading
- **#39** — Web dashboard for run status and event browsing
- **#40** — Export and import run archives
- **#41** — Replay diff tool for comparing runs
- **#42** — Program formatter and linter rules
- **#43** — Registry vocabulary documentation
- **#44** — Architecture decision records index
- **#45** — Security policy and disclosure process
- **#46** — Release automation and version bump tooling
- **#47** — Community guidelines and code of conduct
- **#48** — Seal check mode for CI integration
- **#49** — Repo hygiene: pyproject metadata, dynamic version, CHANGELOG, CLI reference docs

### Registry vocabulary

The builtin command registry defines the vocabulary for all `DO` steps in
Tikhon programs. As of v0.1.0 the registry is frozen at **23 commands**:
`calculate`, `challenge`, `check`, `choose`, `compare`, `decompose`, `define`,
`delegate`, `edit`, `extract`, `fetch`, `hypothesize`, `prove`, `rank`,
`recall`, `remember`, `report`, `review`, `search`, `solve`, `summarize`,
`test`, `verify`. See [docs/spec/02-command-catalog.md](docs/spec/02-command-catalog.md)
for the full command catalog and
[docs/design/01-reasoning-language-foundation.md](docs/design/01-reasoning-language-foundation.md)
for the design rationale behind the frozen vocabulary.

## [0.1.0] - 2026-09-12

Initial release of the Tikhon executable text harness for durable AI-agent
work. Programs are linted and sealed before execution; each `DO` instruction
is one bounded task; worker outputs become immutable state deltas; task
completion requires evidence; terminal failures cannot commit partial
multi-target state; SQLite event replay reconstructs state and task progress.

### Added

- **#1** — Reference lists in `DO` step arguments (`[E.a, E.b]` syntax)
- **#6** — Decision command contracts: `choose`, `compare`, `rank`, `hypothesize`, `challenge`, `decompose`
- **#2** — Truthful `DONE`-predicate validation (`equals`, `in`, `matched`)
- **#14** — `tikhon audit` replay verification against persisted invariants
- **#15** — Registry digest recorded at `RUN_STARTED`; hyphenated program names
- **#5** — KB semantic memory with `remember`/`recall` commands
- **#9** — Effectful `edit`/`test`/`review` commands with idempotency keys and workspace path validation
- **#12** — `CALL protocol.name(args)` protocol composition with bounded inline expansion
- **#7** — `REVISE`/`RETIRE` correction clauses for state revision
- **#13** — `tikhon learn` run directory miner producing protocol candidates and failure clusters
- **#10** — `tikhon resume` crash recovery for interrupted runs
- **#11** — `solve`/`prove` command contracts with `FailureKind.FORMALIZATION`
- **#3** — Deterministic `IF` conditionals (`==`, `!=`, `count()`, `AND`, `OR`, `NOT`)
- **#8** — Model worker adapter with tier routing (`T0`–`T3`) and `TIKHON_*` environment configuration
- **#4** — `SCATTER`/`GATHER` bounded fan-out with `all`/`any`/`ranked` joins
- **#21** — Concurrent execution frontier for independent steps
- **#22** — Execution-tree budgets, deadlines, and nested cancellation
- **#23** — Branch workspaces and resource claims
- **#24** — `PAR MAX N` blocks with explicit `BARRIER`
- **#25** — Runtime-authored child plans via `delegate` command
- **#26** — Execution benchmark harness with deterministic sleep-simulated evidence
- **#17** — Reasoning language design foundation document
- **#18** — Harness-neutral task/result envelopes and external driver `next`/`submit`
- **#19** — Claim/submit driver bridge with `ready`/`claim` commands
- **#20** — Isolated `CALL` child runs with parent adoption

### CLI subcommands

The CLI provides 13 subcommands: `lint`, `seal`, `run`, `resume`, `status`,
`events`, `audit`, `learn`, `bench`, `next`, `submit`, `ready`, `claim`.
See the [CLI Reference](README.md#cli-reference) in the README for the full
table of subcommands, required flags, and purposes.
