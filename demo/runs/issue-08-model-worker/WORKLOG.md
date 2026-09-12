# Worklog: issue-08-model-worker

Seal: `d9e8e127e4fca46808beaedbda8fe65683682523663574a33ccac9a7fa79cd0a`

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to the model worker adapter only: a new `ModelWorker` duck-typed against `DeterministicWorker` (`.commands`, `.execute`), tier-based model routing from each command contract's `RoutingPolicy`, a strict-JSON prompt/response protocol, a `--worker model|deterministic` CLI flag on run/resume wired from `TIKHON_*` environment variables, and new tests with stub transports only. No changes to coordinator.py (import `map_results_to_targets` only), syntax/, registry/, events.py, tasks.py, resume.py, audit.py, or other demo runs.
Outputs: `G.plan` = confirm baseline, seal program, read registry/coordinator/CLI, design the transport seam, implement adapter + CLI flag, add tests, run full suite.
Evidence: Baseline `python3 -m pytest -q` showed `484 passed in 6.86s` before any edit.

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Read registry/spec.py (`CommandSpec`, `RoutingPolicy` fields), registry/enums.py (`RoutingTier` values are the strings "T0".."T3"), registry/registry.py (`Registry.resolve/names`), runtime/coordinator.py (`DeterministicWorker` duck-type, `map_results_to_targets` full-ref-or-unique-leaf mapping rules, exception-to-failed-run path), and cli.py (`_deterministic_handlers`, `--seal` guard style, run/resume worker construction).
Outputs: `E.patterns` = the integration points.
Evidence: The coordinator calls `worker.execute(statement.command, resolved_kwargs)` with exactly two positional arguments, so `ModelWorker.execute` must accept an optional `targets` for direct callers while the coordinator path validates through its own `map_results_to_targets` call; `RoutingTier` is a str-valued enum so `tier_models` can key by either "T0".."T3" or enum members.

## step.design
Status: succeeded
Inputs: `E.patterns`
Actions: Designed the transport seam: `transport(model, prompt) -> str` where ALL network/subprocess detail lives (OpenAI-compatible HTTP POST or argv-template subprocess behind CLI builders, plain callables in tests). Model routing: `tier_models[spec.routing.preferred_tier]` first (string or enum keys), falling back to `default_model`; a missing model raises `WorkerError`. Prompt: contract preamble (purpose, inputs, outputs, done) + resolved kwargs as JSON + strict reply-with-ONLY-JSON instruction including the coordinator's multi-target keying rule. Response handling: strip a single optional ```json fence, `json.loads` strictly, and when targets are known validate through the imported `map_results_to_targets`; any unparseable/invalid response raises `WorkerError` carrying the raw response tail (last 500 chars) so the coordinator's existing exception path records a coherent failed run. CLI requirement 4 (test/edit/review handlers stay deterministic) is met by wrapping the ModelWorker with a small hybrid duck-type in cli.py: those three commands dispatch to the existing deterministic handlers, everything else routes to the model.
Outputs: `V.design` = seam, routing, prompt, and failure semantics fixed.
Evidence: Issue text: "ALL network/subprocess detail is behind this seam"; "reuse `map_results_to_targets` from runtime.coordinator for the check — import it; do NOT modify coordinator.py"; "The `test`/`edit`/`review` handlers stay deterministic".

## step.patch
Status: succeeded
Inputs: `V.design`
Actions: Added `src/tikhon/worker_adapter.py` (`WorkerError`, `ModelWorker` with `.commands` from the registry, tier routing, contract prompt construction, fenced-JSON parsing, target validation, timeout_seconds retained on the instance); added `_build_model_worker` plus http/exec transport builders and the `_HybridModelWorker` wrapper to `src/tikhon/cli.py`, with the `--worker` flag on both `run` and `resume` (default `deterministic`) and the env guard firing before `EventStore` creation, matching the `--seal` guard style. Sealed program.think predates all of these edits.
Outputs: `P.patch` = changes confined to src/tikhon/worker_adapter.py (new), src/tikhon/cli.py, tests/test_worker_adapter.py (new), demo/runs/issue-08-model-worker/.
Evidence: `git status` shows exactly those paths; coordinator.py, syntax/, registry/, events.py, tasks.py, resume.py, audit.py untouched.

## step.check
Status: succeeded
Inputs: `P.patch`, `C.done`
Actions: Added tests/test_worker_adapter.py: tier routing (preferred tier selects the model, string and enum keys, default fallback, missing-model error), prompt content (purpose, inputs, done, resolved-kwargs JSON, JSON-only instruction, named targets), response parsing (plain JSON, fenced JSON, invalid JSON raising WorkerError with a 500-char tail), multi-target mapping (leaf-name keys pass map_results_to_targets, missing key raises WorkerError), CLI guard (`--worker model` without env exits 1 with a clear error before run creation and zero events in the db; `--worker deterministic` unchanged), hybrid edit/test/review determinism, and the end-to-end two-step program through SequentialCoordinator with a stub transport. Then ran the full suite.
Outputs: `V.tests` = full suite green.
Evidence: `python3 -m pytest -q` output recorded in solution.md.

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Recomputed the seal after all edits and diffed against seal.txt; verified none of the forbidden paths were touched; confirmed the deterministic CI baseline is unchanged (default flag value, handler code untouched).
Outputs: `V.result` = issue #8 acceptance met; seal intact; no commits made.
Evidence: `PYTHONPATH=src python3 -m tikhon seal demo/runs/issue-08-model-worker/program.think` matches seal.txt.
