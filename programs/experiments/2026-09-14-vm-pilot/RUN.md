# TAHOE-VM Pilot — 2026-09-14 (SHELVED BRANCH)

**Claim evaluated**: the language as an execution protocol beats the language
as a thinking skill.

## Reproduction

```bash
export PYTHONPATH=src:benchmarks N_WORKERS=5 VM_STEP_EFFORT=low VM_COMPILE_EFFORT=low
python3 benchmarks/run_vm_bench.py gsm8k 30
python3 benchmarks/run_vm_bench.py lsat 30
```

## Data

`benchmarks/results/2026-09-14-vm-pilot/` (+ `docs/TAHOE_VM.md` for the full
analysis with mermaid diagrams and threats-to-validity).

## Result

Both token gates FAILED: VM quality 40–60% vs prompt-tahoe 83–97% at 1.9–3.4×
tokens. Mechanism works (episodes execute, deterministic offload, folding) —
prompted multi-call execution is the wrong deployment of the language. Kept as
RL infrastructure: trajectories are machine-labeled by DONE predicates.

## Caveats

- Results may be implementation-bound (truncated task context, forced
  granularity) — see the threats-to-validity section of `docs/TAHOE_VM.md`
  before citing as a fundamental negative.
