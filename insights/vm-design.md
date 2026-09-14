# TAHOE-VM Design: Model as Compiler + Executor of Its Own Program

> Design locked 2026-09-14 after brainstorm + deep search. Implementation
> target: src/tahoe/vm_mode/ + benchmarks/run_vm_bench.py.

## The architecture

```
┌─────────────────────────────────────────────────┐
│ HARNESS (dumb plumbing, no intelligence)        │
│  • ref store + event log (RAM/registers)        │
│  • program validator (real parser, free)        │
│  • step router + DONE checker                   │
│  • deterministic executors: calculate/check/    │
│    choose/rank (real ALU — zero model tokens)   │
│  • context folder (slices refs per subcall)     │
└──────────────┬──────────────────────────────────┘
               │ tool-calling loop
               ▼
┌─────────────────────────────────────────────────┐
│ MODEL (plays every smart role, via self-calls)  │
│  call 0: COMPILER    — task → program.think     │
│  call N: INTERPRETER — step + refs → ref value  │
│          (the "tool" it calls is itself)        │
└─────────────────────────────────────────────────┘
```

- In tool-calling terms: a normal agent loop where the tool list has exactly
  one entry — the model itself, invoked per atomic step with a state slice.
- The TAHOE program IS the calling convention.
- Compiler and executor are the same weights at different moments; the executor
  never sees the compiler's context (that's the sparse part).
- One-line version: *a model that compiles its task into TAHOE code, then runs
  that code on itself, one typed-ref step per call, with a dumb harness holding
  state.*

## What one execution looks like

```
CALL 0 (compile):
  SYSTEM: You are the TAHOE executor. Given the task, emit a program.think.
  USER:   [task]
  MODEL → PROGRAM (validated by real parser before execution; invalid → repair subcall)

CALL k (interpret step k, fresh context):
  SYSTEM: [STATIC interpreter prefix — byte-identical for cache hits]
  USER:   step.calc: DO calculate(minutes = 90/60*60) -> E.minutes
          [refs: only what this step reads]
  MODEL → E.minutes = 90            (5-15 tokens, not 50-200 of narration)

Deterministic steps (calculate/check/choose/rank): ZERO model tokens —
local executor computes them; model sees only the committed ref.

DONE: harness checks predicate locally; episode ends.
Main context growth: task + program + ref table (~O(refs) lines total).
Subcall contexts: discarded after each step (folding).
```

## The dual-mode property

The same protocol runs two ways:
1. **Self-interpreting (VM mode)** — model plays the interpreter; works on any
   OpenAI-compatible API; this is what gets RL-trained.
2. **Hard runtime** — the existing Python coordinator (src/tahoe/runtime/)
   executes the same program, model only backs LLM-ops.
Compiler/executor decoupling means RL on mode 1 transfers to mode 2 — same
language, same refs, same rewards. (Verifiable claim for the paper.)

## Trajectory = RL episode

```
episode = [program_emission, step_1, ..., step_N, final_answer]
step_i  = {static_prefix, step_text, ref_slice, model_output, verdict}
verdict = parsed_ok, typecheck_ok, done_predicate_ok   (machine-computed)
reward(step_i) = w·verdict terms          (free process rewards — PRM800K needed 800K human labels)
reward(episode) = grader(answer) − λ·total_tokens   (L1-style length control)
```
Fold events get process bonus (FoldGRPO lesson: folding must be rewarded to
be learned). Need-trigger routing emerges from the −λ·tokens term.

## Implementation levers (locked)

1. **Static interpreter prefix** — byte-identical across subcalls → prefix
   cache hits (verified live: Eliza returns cached_tokens in usage).
2. **Deterministic steps always ON initially** — RL learns to route later;
   start with free exactness (issue #61 executor).
3. **Parse-validate-retry** for program and steps (endpoint lacks constrained
   decoding; cite SGLang/OpenAI strict mode as production path).
4. **1-step-1-call for the RL pilot** (clean per-step credit); batching
   allowed later (LLMCompiler: fewer invocations is where cost wins come from).
5. **Repair-via-subcall** when program fails to parse — keeps model-as-executor
   purity.
6. **Trajectory export first-class** (TapeAgents lesson): event store →
   verl-ready format from day one.

## Open items

- Name: "TAHOE-VM" is a loose metaphor. Alternatives: TAHOE-Runtime,
  SI-TAHOE (self-interpreting). Decide before paper.
- Multi-turn suite for the token story: reuse #91 infra (code-gen, tool-use,
  planning suites) — VM should dominate there where context growth is the enemy.
