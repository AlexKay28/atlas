# WORKLOG — issue-26-benchmarks

Seal: 8ab5329a75c87b969d48f64f3545aea63a7b3e163193740766608d8ddee7ff68
Program: demo/runs/issue-26-benchmarks/program.think (linted valid and sealed 2026-09-12T18:12:14Z before any source edit; md5 a0ec1fc61a0233109759caf18e62f428 unchanged after all edits; the final code re-seals to the identical digest recorded in seal.txt. Uses the canonical grammar that exists at seal time: all 23 registered commands as DO steps, one SCATTER/GATHER fan-out, one PAR MAX 3 heterogeneous block, one runtime delegate authoring step, one CALL protocol.framing line.)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed issue #26 into three deliverables: (1) a benchmark harness module (src/tikhon/benchmarks.py) that runs the same program under a sequential baseline and a bounded-parallel variant in fresh temp EventStores with deterministic sleep-simulated workers; (2) a `tikhon bench` CLI subcommand printing/writing the markdown report; (3) committed deterministic evidence (benchmarks/report-2026-09-12.md) plus fast tests (tests/test_benchmarks.py). Live-model cost measurement needs TIKHON_* operator credentials, so the harness ships ready for live runs and the evidence committed now is deterministic sleep-simulated.
Outputs: G.plan = the three deliverables above.
Evidence: /tmp/issue26.md; epic #27 step 6 ("Validate live OpenCode speed, cost and quality; publish benchmark evidence and examples").

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located every reuse point (read-only): SequentialCoordinator.execute(max_workers=, budget=) — frontier for linear programs (issue #21), PAR branch pools bounded by the program's MAX and the budget's shared semaphore (issue #24); ExecutionBudget/BudgetGate (issue #22) — a 1-slot baseline budget serializes PAR branches without changing programs; DISPATCHED event payloads carry the resolved arguments ("args") for every real worker dispatch, giving an exact TaskEnvelope reconstruction seam via build_task_envelope (envelope.py, read-only); CHILD_PLAN_AUTHORED payloads carry the authored plan text for delegation-granularity accounting (issue #25); ledger task texts ("step: DO command") identify each dispatch's command.
Outputs: E.sites = the integration points above.
Evidence: src/tikhon/runtime/coordinator.py (execute, _execute_par_entry, dispatch payloads); src/tikhon/budgets.py; src/tikhon/envelope.py build_task_envelope.

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read the touched-region sources and the binding contracts: PAR pool sizing min(MAX, branches) with budget-gate capping; scatter's sequential candidate contract (fan-out never switches the frontier on — the measured "parallel not faster" data point); delegate's sequential authoring flow inside PAR branch synthetic programs (verified by prototype); CALL validation rules (argument leaves = protocol INPUT leaves; targets = subset of RETURN refs); event-store single-writer batch shapes.
Outputs: ART.sources = the read sources.
Evidence: files listed in C.scope plus protocols/framing.think (repo CALL fixture).

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Pinned the measurement design: (a) speedup = baseline mean wall / variant mean wall over repetitions, min..max spread published — never a single trial; (b) context-cost proxy = summed TaskEnvelope.to_json bytes over every real worker dispatch reconstructed from DISPATCHED "args", with run-id-shaped identity fields normalized to a fixed "run" placeholder so byte deltas compare context, not run-id length; PAR/CALL bookkeeping dispatches skipped (their real dispatches happen inside child runs); (c) delegation granularity = child runs (walk via child_run_id payloads), per-child task counts, authored plans and steps-per-authored-plan from CHILD_PLAN_AUTHORED; (d) baselines always run max_workers=1 under a 1-slot budget (uniform serialization, incl. PAR pools); (e) failed runs raise instead of producing a report — no false completion.
Outputs: E.findings = the design constraints above.
Evidence: this analysis; each constraint has a test in tests/test_benchmarks.py.

## step.decompose
Status: succeeded
Inputs: G.plan
Actions: Split into five subtasks: (1) benchmarks.py: sleep_worker (all 23 commands, fixed latency, fixed delegate sample plan), BenchmarkCase (program source or path, worker factory, max_workers/budget per side, protocols map, repetitions), _walk_run_tree/_envelope_proxy/_measure_run, run_benchmark + BenchmarkReport.to_markdown (three tables + honest caveats), builtin_cases (linear-independent-6, scatter-gather-8, par-heterogeneous-4 with 2 DO + 1 CALL + 1 delegate); (2) cli.py: bench subcommand (--repetitions, --out, plus --latency-seconds for fast smoke runs); (3) tests/test_benchmarks.py (19 tests, tiny latencies); (4) regenerate and commit benchmarks/report-2026-09-12.md; (5) demo run artifacts (this WORKLOG, solution.md, evaluation.json).
Outputs: G.subgoals = the five subtasks above.
Evidence: this decomposition.

## step.hypothesize
Status: succeeded
Inputs: G.goal, E.findings
Actions: Generated candidate designs for the envelope-size proxy: (H1) parse DISPATCHED payloads only — rejected: plain dispatches record no command field; (H2) mirror the coordinator's argument-resolution rules in the harness and re-resolve from replayed state — rejected: reimplements dispatch semantics (scatter items, PAR branch resolution) and drifts from the read-only modules; (H3) read the actual resolved arguments recorded on each DISPATCHED event ("args"), recover the command from the ledger task text, targets from the parsed program/authored plans, and render through the real build_task_envelope — chosen: zero reimplementation, exact per-dispatch fidelity. Also compared identity handling: raw run ids make byte totals differ between sides by run-id length alone; normalizing run-id-shaped fields to "run" makes the width-invariance exact.
Outputs: H.theses = three candidates with H3 selected.
Evidence: coordinator.py dispatch payload shapes; envelope.py build_task_envelope; tests/test_benchmarks.py::test_stable_counts_identical_across_two_benchmark_runs.

## step.calculate
Status: succeeded
Inputs: G.plan, E.findings
Actions: Pinned the numeric invariants: per-run totals under ~2s at the default 40ms latency (measured: linear ~0.27s+0.06s, scatter ~0.45s x2, PAR ~0.39s+0.25s per repetition pair); built-in bench wall ~6s for 3 repetitions; new tests add ~2.5s (tiny 3-20ms latencies, single repetitions); full suite 741 pre-existing + 19 new = 760 in ~20s (< 40s budget); scatter case = exactly 10 dispatches (1 prepare + 8 candidates + 1 final) with identical envelope bytes on both sides; PAR case = 5 child runs (par1..par4 + the delegate-authored child) with child tasks 1+1+2+1+3.
Outputs: F.metrics = {"suite_wall_seconds": 20.11, "tests_total": 760, "bench_wall_seconds": 5.9, "scatter_dispatches": 10, "par_child_runs": 5, "par_child_tasks": 8}.
Evidence: python3 -m pytest -q -> 760 passed in 20.11s; time tikhon bench -> 5.9s; benchmarks/report-2026-09-12.md.

## step.compare / step.rank / step.challenge / step.choose
Status: succeeded
Inputs: H.theses, C.done / V.compared / H.theses, E.findings / R.ranked, V.challenge
Actions: Compared H3 against H1/H2 on the fidelity dimension: H3 records what actually dispatched (the coordinator's own resolved arguments) while H1 guesses from event shapes and H2 re-derives semantics the harness must not own. Challenged the report's honesty surface: raw wall times vary run-to-run, so the markdown publishes mean with min..max spread and marks counts as the deterministic columns; the scatter-is-sequential result is presented as a measured finding (candidate-order contract), not suppressed; phase/token telemetry absent from the deterministic path is declared unknown rather than zero-filled. Chose H3 plus the normalized-identity rendering.
Outputs: V.compared, R.ranked, V.challenge, D.choice = H3 with identity normalization.
Evidence: src/tikhon/benchmarks.py _envelope_proxy; benchmarks/report-2026-09-12.md "Honest caveats".

## step.remember / step.recall
Status: succeeded
Inputs: D.choice / K.record
Actions: Recorded the durable lesson: a benchmark harness must reconstruct envelopes from the DISPATCHED events' recorded resolved arguments (the coordinator's own record), never re-derive them; identity fields must be normalized before byte comparison; a 1-slot ExecutionBudget is the uniform sequential baseline that also serializes PAR pools without touching programs.
Outputs: K.record, K.recalled.
Evidence: src/tikhon/benchmarks.py (module docstring carries the same lesson); stub verification run below (sleep_worker covers all 23 commands; its define passes a single argument's value through — worker policy recorded here, used by the sealed program's scatter_prepare).

## step.solve / step.prove
Status: succeeded
Inputs: G.goal / C.done
Actions: Formalized the harness as a pure measurement pipeline (case -> two sides x repetitions -> per-run tree metrics -> SideSummary -> CaseResult -> markdown) with no global state and fresh temp stores per run, and checked the contract invariants against it: report runs and succeeds only over succeeded runs (broken programs raise); markdown is a pure function of the report data (two renders identical); stable count columns identical across independent benchmark invocations; PAR speedup > 1 with sleep handlers; scatter width-invariant and not faster; delegation granularity 5 child runs / 1 authored 3-step plan.
Outputs: U.solution, A.proof.
Evidence: tests/test_benchmarks.py (19 tests); src/tikhon/benchmarks.py.

## step.review / step.design
Status: succeeded
Inputs: ART.sources / V.review
Actions: Reviewed the harness against issue #26's proposed resolution: sequential vs bounded-parallel vs coarse delegation vs fine per-DO branches are all represented (linear frontier case, scatter fan-out case, PAR case mixing DO/CALL/delegate branches); repeated trials with spread; independently checkable outcomes (succeeded-only, audit-clean stub run); missing telemetry declared unknown; no claim equates wall time with tokens. Designed the minimal diff: one new module, one CLI subcommand, one test file, one generated report, the demo run directory — no changes to syntax/, runtime/, registry/, budgets.py, envelope.py, worker_adapter.py.
Outputs: P.design = the implementation design.
Evidence: /tmp/issue26.md resolution list; git-status-equivalent file list in solution.md.

## step.scatter_prepare / step.sample_rank / GATHER
Status: succeeded
Inputs: Q.samples / R.samples
Actions: Ranked the four benchmark dimensions by evidence value for the committed report: critical-path speedup first (the latency story), context-cost envelope bytes second (the cost story), delegation granularity third (the granularity recommendation), and honest caveats fourth (the anti-overclaim guard). The fan-out ranked each case sample through the scatter body and the USING all gather committed every candidate.
Outputs: Q.parts, R.sample candidates, R.samples.
Evidence: benchmarks/report-2026-09-12.md tables; stub verification run (terminal succeeded, 296 events, audit clean).

## step.par_sites / step.par_check / CALL protocol.framing
Status: succeeded
Inputs: G.plan, C.scope, V.review / V.review
Actions: Ran the three parallel evidence branches concurrently in the stub verification run: (par1) re-verified the live-run path — TIKHON_WORKER_TRANSPORT/TIKHON_MODEL/TIKHON_API_* feed the same run_benchmark via worker_factory, so live OpenCode numbers are one command away; (par2) checked the committed evidence carries the required labeling ("deterministic sleep-simulated evidence; live OpenCode/model numbers require operator credentials (TIKHON_* env)"); (par3, CALL) framed the delegation-granularity recommendation from the PAR measurements.
Outputs: E.par_sites, V.par_verdict, E.context, V.analysis.
Evidence: benchmarks/report-2026-09-12.md header; src/tikhon/cli.py _build_model_worker (unchanged, reused).

## step.author
Status: succeeded
Inputs: G.plan, C.scope
Actions: Authored the delegated child plan for the granularity recommendation: fine per-DO PAR branches for short homogeneous work (largest measured win, bounded by the longest branch), runtime delegate authoring for coarse bounded subtasks (measured 3-step child plan on 2 declared inputs; the delegate branch is the PAR critical path, so delegation buys context narrowness at a latency cost), SCATTER fan-out for context amplification studies only (measured 1.00x — sequential by contract).
Outputs: OUT.plan, OUT.metrics.
Evidence: benchmarks/report-2026-09-12.md (speedup 1.58x PAR with delegate branch as critical path; delegation table 5 child runs, 1.60 tasks/child, 3-step authored plan).

## step.patch / step.test / step.check
Status: succeeded
Inputs: P.design / ART.patch / V.tests
Actions: Applied the patch across the five allowed paths: src/tikhon/benchmarks.py (new, ~600 lines), src/tikhon/cli.py (bench subcommand + parser entry + import), tests/test_benchmarks.py (new, 19 tests), benchmarks/report-2026-09-12.md (regenerated measured output), demo/runs/issue-26-benchmarks/ (this run). Test matrix: report runs/shape; linear frontier speedup > 1; PAR speedup > 1 with envelope equality; scatter width-invariance and no speedup; dependency-chain no-speedup (< 1.6); delegation granularity accounting; stable counts across two invocations; markdown purity and labels; spread brackets mean; constructor validation; failed-run refusal; from_path; worker factory call count; CLI --out writing and bad-repetitions rejection; zero-latency accounting.
Outputs: ART.patch, V.tests = 19/19 green; full suite 760 passed (741 baseline + 19 new).
Evidence: python3 -m pytest -q -> 760 passed in 20.11s (baseline 741 passed in 18.02s).

## step.report / step.verify
Status: succeeded
Inputs: V.verdict / G.goal, V.tests, R.samples
Actions: Rendered the run report (solution.md + evaluation.json) and verified the acceptance conditions: deterministic fake-worker tests verify overlap and dependency behavior (PAR/linear speedup, chain no-speedup tests); the harness produces reproducible configs, artifacts and usage-shape reports with live runs one command away (same harness behind worker_factory); report publishes repeated-run variation (min..max) and predeclared quality criteria (succeeded-only, labeled proxies); no claim equates wall time with tokens (caveats block); recommended default granularity documented with measurements. The sealed demo program was executed end-to-end by the stub worker (terminal succeeded, 296 events, 33 tasks, audit clean) after all source edits, re-sealing to the identical digest.
Outputs: ART.report, V.result, and this WORKLOG/solution.md/evaluation.json.
Evidence: python3 /var/tmp/opencode/scratch26/verify26.py -> terminal_status: succeeded, audit_ok: True; seal re-verification 8ab5329a... after all source edits (program.think md5 a0ec1fc61a0233109759caf18e62f428 unchanged since seal time).
