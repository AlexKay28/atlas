# TAHOE — Task-Aware Language Harness for Orchestrated Execution

*Make agent work executable.*

TAHOE is an executable text harness for durable AI-agent work. It turns a
human-readable program into a sealed sequence of atomic tasks, validates worker
results, and persists state, evidence, progress, and failures as an event log.

```text
PROGRAM demo VERSION 1.0
INPUT
    G.left = 5
    G.right = 7
step.define: DO define(goal = G.left) -> G.goal
step.calculate: DO calculate(left = G.left, right = G.right) -> OUT.total
RETURN G.goal, OUT.total
```

## Why

Natural-language agent prompts often hide control flow, completion conditions,
and state mutation. TAHOE makes those decisions inspectable and replayable:

- programs are linted and sealed before execution;
- each `DO` instruction is one bounded task;
- worker outputs become immutable state deltas;
- task completion requires evidence;
- terminal failures cannot commit partial multi-target state;
- SQLite event replay reconstructs state and task progress.

## Quick Start

TAHOE requires Python 3.10 or newer and has no runtime dependencies.

```bash
python3 -m pip install .
tahoe lint examples/demo.think
SEAL=$(tahoe seal examples/demo.think)
tahoe run examples/demo.think --db demo.db --run-id demo-1 --seal "$SEAL"
tahoe status --db demo.db --run-id demo-1
tahoe events --db demo.db --run-id demo-1
```

The bundled CLI currently uses deterministic demonstration handlers. Real model
workers can implement the same coordinator contract; model dispatch adapters are
the next integration layer.

## CLI Reference

| Subcommand | Required flags | Purpose |
| --- | --- | --- |
| `lint` | `program` | Parse and validate a `.think` program file |
| `seal` | `program` | Print the sealed SHA-256 digest of a program; `--check --seal <digest>` verifies a file against its seal (exit 0 = match, 4 = drifted) |
| `run` | `program`, `--db`, `--run-id`, `--seal` | Execute a sealed program; optional `--workspace`, `--worker` |
| `resume` | `--db`, `--run-id`, `--program`, `--seal` | Resume an interrupted run after a crash; optional `--workspace`, `--worker` |
| `status` | `--db`, `--run-id` | Print run status and progress bar |
| `events` | `--db`, `--run-id` | Print ordered event log as JSON lines |
| `audit` | `--db`, `--run-id` | Verify a persisted run against audit invariants |
| `learn` | `--runs` | Mine a runs directory into protocol candidates and failure clusters; optional `--out` |
| `bench` | — | Run the deterministic benchmark harness; optional `--repetitions`, `--out`, `--latency-seconds` |
| `next` | `--db`, `--run-id`, `--program`, `--seal` | Render the task envelope for the next ready invocation (external driver) |
| `submit` | `--db`, `--run-id`, `--invocation-id`, `--result-file` | Submit a result envelope for a dispatched invocation; optional `--program`, `--seal`, `--claim-token`, `--claim-timeout` |
| `ready` | `--db`, `--run-id`, `--program`, `--seal` | Render and claim the next ready invocation; optional `--workspace`, `--claim-timeout` |
| `claim` | `--db`, `--run-id`, `--program`, `--seal` | Like `ready` but records a claimant name; optional `--claimant`, `--workspace`, `--claim-timeout` |
| `renew` | `--db`, `--run-id`, `--program`, `--seal`, `--invocation-id`, `--claim-token` | Extend an open claim's freshness by a heartbeat so long work is not re-issued; optional `--claim-timeout` |

All commands print human-readable output by default; `status`, `audit`, `learn`, `bench` and `run` accept `--json` for machine-readable output (route `--out` confirmations to stderr). Exit codes: `0` ok, `1` usage/input error, `2` program execution failed, `3` audit violations found, `4` seal mismatch (argparse syntax errors exit `2`).

See the [design doc](docs/design/01-reasoning-language-foundation.md) for the
reasoning behind the frozen 23-command registry, the [CHANGELOG](CHANGELOG.md)
for release history, and the [command catalog](docs/spec/02-command-catalog.md)
for the full command contract specification.

## Agent Demo

`demo/tasks/` contains hard evaluation tasks. The project-local skill at
`.opencode/skills/tahoe-demo/SKILL.md` instructs OpenCode agents to author and
seal a TAHOE plan before solving a task, then record step-level evidence under
`demo/runs/`.

## Development

```bash
python3 -m pytest -q
```

The current suite covers syntax and seals, command contracts, transactional
event batches, state replay, task-ledger invariants, coordinator lifecycle, and
CLI behavior.

See [`docs/README.md`](docs/README.md) for the architecture decisions, language
specification, command catalog, and runtime semantics.

## License

MIT. See [`LICENSE`](LICENSE).
