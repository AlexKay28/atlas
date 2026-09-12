---
name: tahoe-demo
description: Execute hard tasks from demo/tasks through a sealed TAHOE work protocol and write isolated evidence-bearing attempts under demo/runs. Load BEFORE solving an TAHOE demo task, launching a demo agent, or handling prompts containing "demo/tasks", "TAHOE demo", "language experiment", or "solve with TAHOE". Do NOT use for developing the TAHOE runtime itself; use the repository specifications and normal engineering workflow instead.
---

# TAHOE Demo Runner

> **Author:** alexkay28
> **Source of truth:** this project-local file
> `skill-origin: project/tahoe-demo`

Use TAHOE to constrain and expose the reasoning workflow. The task result is
still produced by your normal tools; the current deterministic runtime does not
dispatch real model workers.

## Traps

- Do not use `tahoe run` as the task solver. Its handlers in
  `src/tahoe/cli.py` return deterministic placeholder transformations, so a
  successful run does not mean the hard task was solved.
- Do not write into `demo/tasks/`, `src/`, or `tests/`. Parallel attempts share
  those paths. Write only inside the run directory named in the prompt.
- Do not author the program after solving the task. That turns the language
  into retrospective narration and invalidates the experiment.
- Do not claim a step completed without evidence recorded in `WORKLOG.md`.
- Do not reconstruct the repository path from memory. Resolve it with `pwd -P`;
  one observed attempt changed `alexkay28` to `alexkay` and hit an external
  directory denial while sealing.

## Step 0 — Skill/MCP Inventory (MANDATORY, before plan authoring)

Before authoring `program.think`, the implementing agent runs a bounded
skill and tool inventory. This gate ensures skill selection is deliberate,
not accidental.

### Decision rule

> *Local match → load it; local miss → `ahood skill search` → read the
> candidate's SKILL.md → `ahood skill add owner/skill@version` → verify the
> pin in `.claude/skills.lock.json` → load; no match anywhere → proceed and
> say so in the plan.*

### Procedure

1. **Local skills** — scan the session's available skills
   (`.opencode/skills/`, `.claude/skills/`, built-ins) by task match against
   their descriptions. Match → load via the `skill` tool and follow it;
   record the choice.
2. **Local MCP/tools** — identify what servers are connected for this task
   (tracker, search, browser, etc.). A task needing one must declare it in
   the plan.
3. **Remote fallback — ahood** (`ahood` CLI / https://ahood.vercel.app):
   if no local skill matches, run `ahood skill search "<task keywords>"`;
   read the candidate's SKILL.md *before* installing; install a pinned
   snapshot with `ahood skill add owner/skill@version`; verify the pin
   landed in `.claude/skills.lock.json`; then use it. Local skills are the
   fast path; ahood is discovery + versioned distribution when the skill is
   not present locally.
4. **No match anywhere** — proceed without a skill and state that explicitly
   in the plan.

### ahood traps

- `ahood skill add` installs to `.claude/skills/{owner}@{skill}` — check the
  lockfile after add; a failed install must not be mistaken for an available
  skill.
- Publishing ≠ public: new registry skills are private until `--visibility
  public`.
- Versioned pins, not live-sync: update explicitly via `ahood skill update`;
  CI uses a scoped `AHOOD_TOKEN`.
- Worktree workers don't see untracked `.opencode/` — for them the inventory
  relies on globally installed skills + ahood fetch; the discovery gate must
  work in that reduced environment.

### Declaration convention

The sealed `program.think` records relied-on skills/MCPs via
`INPUT ctx_skill = "name"` entries (or any suitable `C.` binding), so a run's
audit trail names its tooling, not just its data. WORKLOG Inputs cite the
loaded skills per step.

## Required Workflow

1. Read the assigned file in `demo/tasks/` and no other task descriptions.
2. Create only the assigned `demo/runs/{run-id}/` directory.
3. **Run Step 0 (skill/MCP inventory)** — see above; record findings before
   authoring the plan.
4. Immediately write `program.think` using the canonical sequential grammar
   and only registered commands. Do not inspect task-related source, run a
   calculation, or delegate exploration before the program is written.
4. Run `tahoe lint program.think`, then `tahoe seal program.think`. Write the
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
