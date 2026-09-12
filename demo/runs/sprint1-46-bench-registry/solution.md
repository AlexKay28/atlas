# solution.md — sprint1-46-bench-registry

GitHub issue #46: benchmark harness extensibility — case registry, JSON
export, usage metrics.

## What was built

### 1. Case registry (issue #46 acceptance 1)

`src/tikhon/benchmarks.py` now has a `CaseRegistry` class — a name →
factory registry that callers can extend without editing the module's
internals. The three built-in cases from issue #26
(`linear-independent-6`, `scatter-gather-8`, `par-heterogeneous-4`)
remain the defaults, registered at module load via private factory
functions.

- `CaseRegistry` — `register(name, factory)`, `build(name, **kwargs)`,
  `build_all(**kwargs)`, `names()`.
- `register_case(name, factory, *, registry=None)` — module-level
  convenience function; targets the default registry or a private one.
- `builtin_registry_names()` — lists the default registry's names.
- `builtin_cases(latency_seconds=0.04)` — now delegates to
  `_default_registry.build_all()`, producing the same three cases as
  before.

`run_benchmark(cases, ...)` continues to accept an explicit list of
`BenchmarkCase` instances, unchanged. Callers who want a custom case
list construct `BenchmarkCase` objects directly; callers who want to
extend the registry use `register_case` or their own `CaseRegistry`.

### 2. JSON export (issue #46 acceptance 2)

`BenchmarkReport.to_json()` returns a JSON string that roundtrips
through `json.loads`. Every number in the JSON output is identical to
the number rendered in `to_markdown()`:

- Wall times: `_round1(seconds)` matches `_ms(seconds)` formatting
  (both produce milliseconds with 1 decimal place).
- Speedup: `round(speedup, 2)` matches the markdown `**{:.2f}x**`.
- Context cost: dispatches, envelope bytes, delta — identical integers.
- Delegation granularity: child_runs, child_events, tasks_per_child,
  authored_plans, authored_steps — identical.
- Usage: `None` when no worker reports usage; a structured block
  with prompt/completion/total tokens and cost when a worker does.

### 3. Usage metrics (issue #46 acceptance 3)

`UsageStats` is a frozen dataclass (`prompt_tokens`, `completion_tokens`,
`total_tokens`, `cost_usd`, all defaulting to 0/0.0). It has:

- `UsageStats.zero()` — a zero-shaped sentinel.
- `UsageStats.from_result(result)` — extracts usage from a worker's
  result dict when it contains a `"usage"` key; returns `None` otherwise
  (the deterministic sleep-simulated path).

`RunMetrics` gains `usage: UsageStats | None = None`. In `_measure_run`,
the tree walk scans `invocation.result_received` events and calls
`UsageStats.from_result` on each result payload. Aggregated usage sums
across all dispatches in the run tree.

`SideSummary` gains `usage: UsageStats | None = None`. In `_summarize`,
usage is aggregated across repetitions (summing per-run totals).

`CaseResult` gains `usage_delta_tokens` property
(variant.total_tokens - baseline.total_tokens).

The deterministic sleep-simulated workers return
`{"command": name, "echo": kwargs}` — no `"usage"` key — so
`UsageStats.from_result` returns `None` and the existing numbers are
unchanged. A usage-reporting worker factory includes a `"usage"` key in
its result dict; the harness extracts and aggregates it.

### 4. Determinism (issue #46 acceptance 4)

The existing three built-in cases produce identical deterministic
counts as the committed evidence
(`benchmarks/report-2026-09-12.md`):

| case | dispatches | envelope_bytes | child_runs | authored_plans | authored_steps |
|---|---|---|---|---|---|
| linear-independent-6 | 6 | 5406 | 0 | 0 | 0 |
| scatter-gather-8 | 10 | 8993 | 0 | 0 | 0 |
| par-heterogeneous-4 | 9 | 8293 | 5 | 1 | 3 |

Verified by running `builtin_cases(latency_seconds=0.04)` through
`run_benchmark(cases, repetitions=3)`.

## Tests added (10 new, 760 → 770)

1. `test_builtin_registry_names_has_three_defaults` — registry has the
   three canonical names in insertion order.
2. `test_builtin_cases_from_registry_match_expected_names` —
   `builtin_cases()` returns cases with the expected names.
3. `test_custom_case_runs_via_explicit_list_without_editing_internals` —
   acceptance (1): a custom BenchmarkCase runs and reports without
   editing benchmarks.py.
4. `test_case_registry_extend_and_build` — a private CaseRegistry can
   be extended with custom factories and built.
5. `test_register_case_adds_to_default_registry` — `register_case()`
   adds a factory to a registry.
6. `test_to_json_roundtrips_with_numbers_matching_markdown` —
   acceptance (2): `to_json()` roundtrips through `json.loads` with
   numbers matching `to_markdown`.
7. `test_to_json_is_valid_json_and_deterministic` — `to_json()` is
   valid JSON and a pure function (two calls match).
8. `test_usage_reporting_worker_factory_shows_nonzero_usage` —
   acceptance (3): a usage-reporting worker factory shows non-zero
   usage in both JSON and markdown outputs.
9. `test_usage_zero_shaped_default_when_worker_does_not_report` —
   usage is `None` in JSON when no worker reports usage.
10. `test_existing_three_cases_unchanged` — acceptance (4): existing
    three cases unchanged (dispatches, envelope, child runs, authored).

## Constraints honored

- Touched only: `src/tikhon/benchmarks.py`, `tests/test_benchmarks.py`,
  `demo/runs/sprint1-46-bench-registry/`.
- No git commit made.
- Full suite: **770 passed** (760 baseline + 10 new) in **21.4s**
  (< 40s budget).
- Seal: `861a39c3a64fe5d767d964bb11d9f32f23298060233dc4bb81bdb9da5bfa0712`
  (program.think unchanged after sealing).

## Deviations

- `register_case` test uses a private `CaseRegistry` to avoid polluting
  the shared module-level default registry (the registry has no
  `unregister` method; a shared-registry test would break other tests
  that rely on the default's three-case count).
- The `to_markdown` output does not add a usage table — usage is
  visible in `to_json` and the `CaseResult.usage_delta_tokens` property;
  the markdown report's "Honest caveats" section already states usage
  is recorded as unknown in the deterministic path. A future live-model
  run would show usage in the JSON output.
