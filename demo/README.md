# Tikhon Agent Demo

This directory tests whether an agent can use Tikhon as a disciplined work
protocol for difficult tasks.

- `tasks/` contains immutable task descriptions.
- `runs/` contains one isolated directory per agent attempt.
- `.opencode/skills/tikhon-demo/SKILL.md` defines the required protocol.

Each run must contain `program.think`, `seal.txt`, `WORKLOG.md`, `solution.md`,
and `evaluation.json`. Compare attempts on acceptance-criteria coverage,
evidence quality, unnecessary steps, reseals, and unresolved claims.

The current runtime has deterministic demonstration handlers. This experiment
therefore tests the language as an agent planning and execution protocol: the
agent uses `tikhon lint` and `tikhon seal`, then executes each sealed instruction
with its ordinary tools and records evidence in `WORKLOG.md`.
