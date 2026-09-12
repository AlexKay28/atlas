# Tikhon

Tikhon is an executable text harness for durable AI-agent work. It turns a
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
and state mutation. Tikhon makes those decisions inspectable and replayable:

- programs are linted and sealed before execution;
- each `DO` instruction is one bounded task;
- worker outputs become immutable state deltas;
- task completion requires evidence;
- terminal failures cannot commit partial multi-target state;
- SQLite event replay reconstructs state and task progress.

## Quick Start

Tikhon requires Python 3.10 or newer and has no runtime dependencies.

```bash
python3 -m pip install .
tikhon lint examples/demo.think
SEAL=$(tikhon seal examples/demo.think)
tikhon run examples/demo.think --db demo.db --run-id demo-1 --seal "$SEAL"
tikhon status --db demo.db --run-id demo-1
tikhon events --db demo.db --run-id demo-1
```

The bundled CLI currently uses deterministic demonstration handlers. Real model
workers can implement the same coordinator contract; model dispatch adapters are
the next integration layer.

## Agent Demo

`demo/tasks/` contains hard evaluation tasks. The project-local skill at
`.opencode/skills/tikhon-demo/SKILL.md` instructs OpenCode agents to author and
seal a Tikhon plan before solving a task, then record step-level evidence under
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
