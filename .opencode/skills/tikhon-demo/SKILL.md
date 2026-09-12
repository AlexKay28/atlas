---
name: tikhon-demo
description: Execute hard tasks from demo/tasks through a sealed Tikhon work protocol and write isolated evidence-bearing attempts under demo/runs. Load BEFORE solving a Tikhon demo task, launching a demo agent, or handling prompts containing "demo/tasks", "Tikhon demo", "language experiment", or "solve with Tikhon". Do NOT use for developing the Tikhon runtime itself; use the repository specifications and normal engineering workflow instead.
---

# Tikhon Demo Runner

> **Author:** alexkay28
> **Source of truth:** this project-local file
> `skill-origin: project/tikhon-demo`

Use Tikhon to constrain and expose the reasoning workflow. The task result is
still produced by your normal tools; the current deterministic runtime does not
dispatch real model workers.

## Traps

- Do not use `tikhon run` as the task solver. Its handlers in
  `src/tikhon/cli.py` return deterministic placeholder transformations, so a
  successful run does not mean the hard task was solved.
- Do not write into `demo/tasks/`, `src/`, or `tests/`. Parallel attempts share
  those paths. Write only inside the run directory named in the prompt.
- Do not author the program after solving the task. That turns the language
  into retrospective narration and invalidates the experiment.
- Do not claim a step completed without evidence recorded in `WORKLOG.md`.
- Do not reconstruct the repository path from memory. Resolve it with `pwd -P`;
  one observed attempt changed `alexkay28` to `alexkay` and hit an external
  directory denial while sealing.

## Required Workflow

1. Read the assigned file in `demo/tasks/` and no other task descriptions.
2. Create only the assigned `demo/runs/{run-id}/` directory.
3. Immediately write `program.think` using the canonical sequential grammar
   and only registered commands. Do not inspect task-related source, run a
   calculation, or delegate exploration before the program is written.
4. Run `tikhon lint program.think`, then `tikhon seal program.think`. Write the
   exact digest to `seal.txt`.
5. Execute the sealed invocations in source order with your ordinary read-only
   tools and calculations. Treat each `DO` line as one bounded task.
6. Append one section per invocation to `WORKLOG.md` with its step id, status,
   inputs, actions, output references, and concrete evidence.
7. Write the requested answer to `solution.md`.
8. Execute the final `verify` step against every acceptance criterion. Record
   failures honestly; never weaken the task requirements.
9. Write `evaluation.json` and stop. Do not modify the sealed program after its
   digest is recorded.

## Program Rules

Use this canonical subset:

```text
PROGRAM {name} VERSION 1.0
INPUT
    G.task = "bounded goal"
    C.scope = "task constraints"
step.frame: DO define(request = G.task) -> G.plan
step.locate: DO search(query = G.plan, scope = C.scope) -> E.candidates
step.read: DO fetch(resource_refs = E.candidates) -> ART.sources
step.analyze: DO extract(artifact = ART.sources, schema = "findings") -> E.findings
step.write: DO report(committed_refs = E.findings, format = "markdown") -> OUT.solution
step.verify: DO verify(goal = G.task, evidence = OUT.solution) -> V.result
RETURN OUT.solution, V.result
```

Adapt the steps to the task, but keep every operation atomic. Valid commands
are `define`, `search`, `fetch`, `extract`, `summarize`, `report`, `verify`,
`calculate`, and `check`. References produced by earlier steps may be consumed
by later steps. Every referenced node must exist on its path.

Program names match `[a-z][a-z0-9_-]*`: hyphens are allowed after the first
character, while step ids and reference leaf names still match
`[a-z][a-z0-9_]*` — use underscores, never hyphens, for those. An argument
value is either one typed reference or one JSON literal.
Arrays containing bare references such as `[E.a, E.b]` are not supported; add
an atomic summarization step that produces one aggregate reference instead.

## Worklog Contract

Start with the seal and task path. Then record each step as:

```markdown
## step.name
Status: succeeded | failed | blocked
Inputs: ...
Actions: ...
Outputs: REF = concise value or artifact path
Evidence: commands, calculations, source paths and lines, or observed output
```

A failed or blocked step terminates the attempt. Write the reason and use a
matching `STOP` terminal in a newly authored program only if failure occurred
before sealing; never rewrite an already sealed history.

## Evaluation Contract

`evaluation.json` must be valid JSON with these keys:

```json
{
  "task": "demo/tasks/assigned-task.md",
  "run_id": "assigned-run-id",
  "seal": "64 lowercase hexadecimal characters",
  "terminal_status": "succeeded",
  "steps_planned": 6,
  "steps_executed": 6,
  "acceptance": [{"criterion": "...", "passed": true, "evidence": "..."}],
  "unresolved": [],
  "protocol_deviations": []
}
```

Success requires all acceptance entries to pass, no unresolved correctness
claims, and matching planned/executed step counts.
