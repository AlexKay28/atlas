# solution.md — issue-26-benchmarks

GitHub issue #26 (epic #27 step 6): benchmark harness + measured evidence for the
tikhon execution model — "Validate live OpenCode speed, cost and quality; publish
benchmark evidence and examples."

## What was built

**`src/tikhon/benchmarks.py` (new)** — the deterministic benchmark harness.

- `sleep_worker(latency_seconds)` — a `DeterministicWorker` covering all 23
  registered commands; every handler sleeps a fixed per-step latency and returns a
  deterministic echo; `delegate` returns the fixed canonical 3-step sample plan.
- `BenchmarkCase` — name, program source (or `from_path`), per-side runner config
  (`max_workers`/`budget` for the variant, `baseline_max_workers`/`baseline_budget`
  for the sequential baseline, default 1 worker under a 1-slot `ExecutionBudget`),
  a `protocols` map for programs that CALL, a `worker_factory` hook, per-case
  latency and repetitions.
- `run_benchmark(cases, repetitions=3) -> BenchmarkReport` — executes sequential
  baseline vs configured variant for each case in fresh temp `EventStore`s (fresh
  dir per invocation, own db + protocols per run), measures wall time
  (`perf_counter`), tree-wide event/task counts, worker-dispatch count, the
  CONTEXT cost proxy (summed `TaskEnvelope.to_json` bytes over every real worker
  dispatch reconstructed from DISPATCHED events' recorded resolved arguments), and
  delegation granularity (child runs, per-child steps/events,
  `CHILD_PLAN_AUTHORED` plans and their step counts). All wall numbers averaged
  over repetitions with min/max spread; deterministic ordering; failed runs raise
  instead of reporting.
- `BenchmarkReport.to_markdown()` — deterministic rendering: configuration,
  critical-path speedup, context-cost, delegation-granularity tables plus honest
  caveats (including the required label that these are deterministic
  sleep-simulated numbers and live OpenCode/model numbers need TIKHON_* operator
  credentials and run through the same harness).
- `builtin_cases(latency_seconds=0.04)` — the three built-in cases:
  1. `linear-independent-6` — six independent steps; the concurrent frontier
     overlaps them.
  2. `scatter-gather-8` — eight fan-out candidates; scatter drives the sequential
     plan loop by contract, so this case measures context-cost fan-out, not
     latency.
  3. `par-heterogeneous-4` — `PAR MAX 4` with two DO branches, one CALL branch
     (`protocol.framing`, self-contained protocol text) and one delegate branch;
     the 1-slot baseline budget serializes the pool, the 4-slot variant overlaps.

**`src/tikhon/cli.py`** — `tikhon bench [--repetitions N] [--out PATH]
[--latency-seconds S]`: runs the built-in cases, prints the markdown report,
writes it with `--out`, exits 0 on success. (`--latency-seconds` is an extra knob
beyond the issue's two flags so the test suite can smoke-run the CLI in
milliseconds; default 0.04 keeps per-run totals under ~2s.)

**`tests/test_benchmarks.py` (new, 19 tests)** — overlap and dependency behavior
with deterministic fake workers (PAR + frontier speedup > 1, dependency-chain
no-speedup, scatter width-invariance), report shape/purity/labels, stable count
columns across independent invocations, delegation-granularity accounting,
constructor/argument validation, failed-run refusal, CLI `--out` writing and
error handling. Tiny latencies keep the added suite time at ~2.4s.

**`benchmarks/report-2026-09-12.md` (new)** — the committed evidence, regenerated
by the actual command
`PYTHONPATH=src python3 -m tikhon bench --repetitions 3 --out benchmarks/report-2026-09-12.md`
(wall ~5.9s) on this machine.

**`demo/runs/issue-26-benchmarks/`** — this run: `program.think` (all 23 commands
+ SCATTER/GATHER + PAR + CALL + delegate), `seal.txt`, `WORKLOG.md`,
`solution.md`, `evaluation.json`.

## Measured headline numbers (deterministic, sleep-simulated, 3 repetitions)

| measurement | value |
|---|---|
| Critical-path speedup, `linear-independent-6` (frontier, 6 workers) | **4.60x** (266.3 ms → 57.9 ms mean) |
| Critical-path speedup, `par-heterogeneous-4` (PAR MAX 4, 4 slots) | **1.57x** (392.5 ms → 249.4 ms mean; the delegate branch bounds the critical path) |
| Critical-path speedup, `scatter-gather-8` | **1.00x** — sequential by contract; the measured "parallel is NOT faster here" data point |
| Context-cost delta per run (envelope bytes, variant − sequential) | **+0 bytes on all three cases** (width changes latency, not per-run context; per-case totals 5406 / 8993 / 8293 bytes) |
| Delegation granularity | 5 child runs per PAR tree, 1.60 tasks/child mean, one authored 3-step plan on 2 declared inputs |

Granularity recommendation from the measurements (recorded in the report and
WORKLOG): fine per-DO PAR branches for short homogeneous work (largest win,
bounded by the longest branch); runtime `delegate` authoring for coarse bounded
subtasks (narrow declared-input child context — measured 3 steps / 2 inputs — at
a critical-path latency cost); SCATTER fan-out for context-amplification studies,
not latency.

## Live runs are one command away

The same harness takes any worker through `BenchmarkCase.worker_factory`; a live
OpenCode/model worker is the existing `TIKHON_*` configuration
(`TIKHON_WORKER_TRANSPORT`, `TIKHON_MODEL`/`TIKHON_TIER_MODELS`,
`TIKHON_API_BASE`/`TIKHON_API_KEY` or `TIKHON_EXEC_COMMAND`) feeding
`ModelWorker` — no harness changes needed, only operator credentials, which this
session does not hold. Everything measured live will flow into the same report
tables (plus the usage/cost columns the deterministic path deliberately reports
as unknown).

## Constraints honored

- Touched only: `src/tikhon/benchmarks.py` (new), `src/tikhon/cli.py` (bench),
  `tests/test_benchmarks.py` (new), `benchmarks/report-2026-09-12.md` (new),
  `demo/runs/issue-26-benchmarks/` (new).
- Read-only modules used, never modified: `syntax/`, `runtime/`, `registry/`,
  `budgets.py`, `envelope.py`, `worker_adapter.py`.
- Full suite: **760 passed** (741 pre-existing, unmodified + 19 new) in **20.1s**
  (< 40s budget; baseline was 741 passed in 18.0s).
- No git commit made.

## Deviations / limitations

- `tikhon bench` carries an extra optional `--latency-seconds` flag beyond the
  issue's `[--repetitions N] [--out PATH]` (default 0.04); it exists so tests and
  smoke runs stay fast, and the committed report used the default.
- The demo run's stub verification worker passes a single `define` argument's
  value through (worker policy, needed by `step.scatter_prepare` committing the
  INPUT list back out); all other handlers are the harness's sleep+echo. The run
  is audit-clean and terminal `succeeded` (296 events, 33 tasks).
- Fine-grained phase telemetry (queue/startup/worker/join split, peak
  concurrency, token/usage/cost accounting, retries, cancellation waste) is not
  measurable without live-model runs and is reported as unknown — never
  zero-filled.
- Wall times are machine-specific by nature; the report publishes mean with
  min..max spread over 3 repetitions and marks count columns as the
  deterministic ones.
