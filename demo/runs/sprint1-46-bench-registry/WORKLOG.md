# WORKLOG — sprint1-46-bench-registry

Seal: 861a39c3a64fe5d767d964bb11d9f32f23298060233dc4bb81bdb9da5bfa0712
Program: demo/runs/sprint1-46-bench-registry/program.think (linted valid and sealed 2026-09-12T22:35:00Z before any source edit; uses only registered commands and the canonical sequential grammar).

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed issue #46 into four deliverables: (1) case registry — builtin_cases() becomes a registry of name→factory that callers can extend, existing three cases stay as defaults; (2) BenchmarkReport.to_json() — JSON-serializable form that roundtrips through json.loads with numbers matching to_markdown; (3) optional usage block on RunMetrics — default None/zero-shaped, sourced from RESULT_RECEIVED receipt usage when a worker factory reports it; (4) tests — custom case list, to_json roundtrip, usage-reporting worker factory, existing three cases unchanged.
Outputs: G.plan = the four deliverables above.
Evidence: GitHub issue #46; benchmarks.py (read-only at this point).

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located the integration points in benchmarks.py (read-only): builtin_cases() at lines 751-787 returns a hardcoded list; RunMetrics at lines 168-182 is a frozen dataclass with 10 fields; SideSummary at lines 184-209; CaseResult at lines 212-229; BenchmarkReport.to_markdown at lines 239-359; _summarize at lines 589-617; _measure_run at lines 488-586; run_benchmark at lines 620-691. The RESULT_RECEIVED event payload for regular DO steps carries {"result": result} where result is the worker's return value (coordinator.py:4899-4906). For scatter/call/delegate paths, RESULT_RECEIVED carries child_run_id and status only. So usage from a usage-reporting worker factory appears in the "result" dict of regular DO-step RESULT_RECEIVED events.
Outputs: E.sites = the integration points above.
Evidence: src/tikhon/benchmarks.py; src/tikhon/runtime/coordinator.py; src/tikhon/runtime/events.py.

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read the full benchmarks.py (787 lines), tests/test_benchmarks.py (317 lines), and the relevant coordinator.py RESULT_RECEIVED event paths. Confirmed: (a) builtin_cases() is a hardcoded list of three BenchmarkCase instances; (b) RunMetrics is a frozen dataclass with no usage field; (c) RESULT_RECEIVED for regular DO steps has payload {"result": result} where result is the worker's return value (coordinator.py:4901); (d) the deterministic sleep_worker returns {"command": name, "echo": kwargs} — no usage key; (e) to_markdown renders three tables + caveats; (f) _summarize takes the first run's deterministic counts.
Outputs: ART.sources = the read sources and integration plan.
Evidence: src/tikhon/benchmarks.py (full read); src/tikhon/runtime/coordinator.py lines 4880-4910; tests/test_benchmarks.py (full read).

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Pinned the implementation design: (1) UsageStats dataclass (frozen, zero-shaped, from_result classmethod) added before sleep_worker; (2) RunMetrics gains optional `usage: UsageStats | None = None`; (3) SideSummary gains optional `usage: UsageStats | None = None`; (4) CaseResult gains `usage_delta_tokens` property; (5) _measure_run walks RESULT_RECEIVED events extracting usage from result dicts; (6) _summarize aggregates usage across repetitions; (7) BenchmarkReport.to_json() produces JSON with the same numbers as to_markdown; (8) CaseRegistry class with register/build/build_all/names; (9) three default factories registered at module load; (10) builtin_cases() delegates to _default_registry.build_all(); (11) register_case() and builtin_registry_names() module-level functions.
Outputs: E.findings = the design above.
Evidence: this analysis; benchmarks.py current structure.

## step.decompose
Status: succeeded
Inputs: G.plan
Actions: Split into: (1) add UsageStats + usage fields to RunMetrics/SideSummary/CaseResult; (2) add usage extraction to _measure_run; (3) add usage aggregation to _summarize; (4) add BenchmarkReport.to_json() + helpers (_round1, _usage_json); (5) add CaseRegistry class + three default factories + register_case + builtin_registry_names; (6) update builtin_cases() to use registry; (7) update __all__; (8) add 10 new tests covering all four acceptance criteria.
Outputs: G.subgoals = the eight subtasks above.
Evidence: this decomposition.

## step.hypothesize
Status: succeeded
Inputs: G.goal, E.findings
Actions: Considered usage extraction strategies: (H1) parse usage from worker result dicts on RESULT_RECEIVED events — chosen: non-invasive, the worker factory's result dict carries "usage" when it reports, UsageStats.from_result extracts it; (H2) add a usage callback to BenchmarkCase — rejected: over-engineered, the result dict is the natural carrier; (H3) parse usage from TASK_UPDATED events — rejected: those carry "tokens": 0, "cost": 0 as hardcoded zeros (coordinator.py:1480-1481). For JSON export: (H1) produce a dict and json.dumps it — chosen: simple, roundtrips through json.loads, numbers match markdown by construction.
Outputs: H.theses = H1 for usage, H1 for JSON.
Evidence: coordinator.py RESULT_RECEIVED payloads; UsageStats.from_result design.

## step.calculate
Status: succeeded
Inputs: G.plan, E.findings
Actions: Estimated: 10 new tests (4 acceptance + 6 supporting), each <0.5s with tiny latencies. Full suite 760 + 10 = 770, wall ~21s (< 40s budget). Deterministic counts unchanged: linear 6 dispatches / 5406 bytes, scatter 10 / 8993, PAR 9 / 8293 / 5 child runs / 1 authored / 3 steps.
Outputs: F.metrics = {"baseline": 760, "new": 10, "total": 770, "wall_estimate_s": 21}.
Evidence: prior run 760 in 20.79s; new tests use 0.003s latency and 1 repetition.

## step.compare / step.rank / step.challenge / step.choose
Status: succeeded
Inputs: H.theses, C.done / V.compared / H.theses, E.findings / R.ranked, V.challenge
Actions: Compared the design against C.done's four acceptance criteria: (1) custom case list runs without editing internals — BenchmarkCase is already constructible externally, and CaseRegistry adds extensibility; (2) to_json roundtrips with numbers matching markdown — verified by construction (_round1 matches _ms, same dispatches/bytes/counts); (3) usage-reporting worker factory shows non-zero usage — UsageStats.from_result extracts from result dict, _measure_run walks RESULT_RECEIVED events; (4) existing three cases unchanged — default factories produce identical BenchmarkCase instances, deterministic counts verified. Chose the minimal-diff approach.
Outputs: V.compared, R.ranked, V.challenge, D.choice.
Evidence: this comparison; C.done acceptance criteria.

## step.remember / step.recall
Status: succeeded
Inputs: D.choice / K.record
Actions: Recorded: a benchmark case registry should use factory functions (not class references) so callers can customize per-case parameters (latency, repetitions) at build time; usage telemetry flows through the worker's result dict and is extracted from RESULT_RECEIVED events — never from TASK_UPDATED which carries hardcoded zeros; JSON export should use the same rounding as markdown (_round1 matches _ms) to ensure number-for-number equality.
Outputs: K.record, K.recalled.
Evidence: this design rationale.

## step.solve / step.prove
Status: succeeded
Inputs: G.goal / C.done
Actions: Implemented all four features in benchmarks.py: (1) UsageStats dataclass with from_result classmethod; (2) RunMetrics.usage, SideSummary.usage, CaseResult.usage_delta_tokens; (3) _measure_run extracts usage from RESULT_RECEIVED events; (4) _summarize aggregates usage across repetitions; (5) BenchmarkReport.to_json() with _round1 and _usage_json helpers; (6) CaseRegistry class with register/build/build_all/names; (7) three default factories (_linear_factory, _scatter_factory, _par_factory) registered at module load; (8) builtin_cases() delegates to _default_registry.build_all(); (9) register_case() and builtin_registry_names() module-level functions. Proved invariants: deterministic counts unchanged (verified by running the three cases and comparing to committed report), JSON roundtrips through json.loads, usage is None for deterministic path and non-None for usage-reporting workers.
Outputs: U.solution, A.proof.
Evidence: PYTHONPATH=src python3 -m pytest tests/test_benchmarks.py -q -> 29 passed; full suite 770 passed in 21.41s; deterministic counts verified (6/5406, 10/8993, 9/8293, 5 child runs, 1 authored, 3 steps).

## step.review / step.check
Status: succeeded
Inputs: ART.sources / V.review
Actions: Reviewed against acceptance criteria: (1) custom case list runs via explicit BenchmarkCase construction + run_benchmark — test_custom_case_runs_via_explicit_list_without_editing_internals; (2) to_json roundtrips — test_to_json_roundtrips_with_numbers_matching_markdown and test_to_json_is_valid_json_and_deterministic; (3) usage-reporting worker — test_usage_reporting_worker_factory_shows_nonzero_usage; (4) existing three cases — test_existing_three_cases_unchanged verifies dispatches/envelope/child_runs/authored unchanged. Checked: only OWNED files modified (src/tikhon/benchmarks.py, tests/test_benchmarks.py, demo/runs/sprint1-46-bench-registry/). Seal unchanged.
Outputs: V.review, V.verdict = acceptance covered.
Evidence: git status --porcelain shows only M src/tikhon/benchmarks.py, M tests/test_benchmarks.py, ?? demo/runs/sprint1-46-bench-registry/.

## step.test
Status: succeeded
Inputs: tests/test_benchmarks.py
Actions: Ran full pytest suite: PYTHONPATH=src python3 -m pytest -q -> 770 passed in 21.41s (760 baseline + 10 new). New tests: test_builtin_registry_names_has_three_defaults, test_builtin_cases_from_registry_match_expected_names, test_custom_case_runs_via_explicit_list_without_editing_internals, test_case_registry_extend_and_build, test_register_case_adds_to_default_registry, test_to_json_roundtrips_with_numbers_matching_markdown, test_to_json_is_valid_json_and_deterministic, test_usage_reporting_worker_factory_shows_nonzero_usage, test_usage_zero_shaped_default_when_worker_does_not_report, test_existing_three_cases_unchanged.
Outputs: V.tests = 770/770 green.
Evidence: python3 -m pytest -q -> 770 passed in 21.41s.

## step.report / step.verify
Status: succeeded
Inputs: V.verdict / G.goal, V.tests, F.metrics
Actions: Rendered the run report (solution.md + evaluation.json) and verified all four acceptance criteria pass: (1) custom case list runs and reports without editing benchmarks.py internals; (2) to_json() roundtrips through json.loads with numbers matching to_markdown; (3) a usage-reporting worker factory shows non-zero usage in both JSON and markdown outputs; (4) existing three cases unchanged (dispatches, envelope bytes, child-run accounting identical to committed report). Seal re-verified: 861a39c3a64fe5d767d964bb11d9f32f23298060233dc4bb81bdb9da5bfa0712 (program.think unchanged after sealing).
Outputs: ART.report, V.result.
Evidence: git status --porcelain; pytest output; seal verification.
