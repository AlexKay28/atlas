# STATUS: SHELVED (2026-09-14)

TAHOE-VM — the language as an execution protocol (model compiles a program,
executes it on itself one atomic subcall per step, harness validates) — was
built, piloted, and shelved.

## Why

Prompted multi-step execution lost to the single-call skill on both axes for
single-shot QA: 40+ quality points worse at 2–35× tokens across two
configurations. Over-decomposition fragments holistic reasoning; the compile
call double-solves the task. Full analysis, mermaid diagrams, pilot tables and
implementation-threats-to-validity: `docs/TAHOE_VM.md`.

## Why the code stays

- It works mechanically (episodes execute end-to-end; deterministic arithmetic
  costs zero model tokens) and is fully tested (`tests/test_vm_mode.py`).
- Every step is machine-labeled (parse/type/DONE verdicts) — the trajectory
  recorder is a ready-made RL dataset generator if Stage-3 RL is revived.
- `reasoning_effort` per phase is a per-step action knob the RL policy could
  learn.

## Entry points

- `tahoe.vm_mode.VMExecutor` — compile-and-execute one task
- `benchmarks/run_vm_bench.py` — 3-arm pilot runner
- `benchmarks/results/2026-09-14-vm-pilot/` — pilot data (gsm8k rows under
  v1 grader — see correction note in `insights/compact-language.md`)

Do not extend without re-reading the threats-to-validity section first.
