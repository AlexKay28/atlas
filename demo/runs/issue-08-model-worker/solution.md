# Solution: issue #8 — model worker adapter with tier-based routing (T0–T3)

Run id: `issue-08-model-worker` · Seal: `d9e8e127e4fca46808beaedbda8fe65683682523663574a33ccac9a7fa79cd0a` · Terminal status: succeeded

## What was built

`DeterministicWorker` is no longer the only dispatch backend. A new
`ModelWorker` duck-types it (`.commands` property + `.execute(command,
resolved_kwargs)`) but produces DO results by sending a contract prompt to a
language model through a pluggable transport seam, with tier-based model
routing driven by each command contract's existing (previously unused)
`RoutingPolicy`.

### 1. `src/tikhon/worker_adapter.py` (new)

- **`ModelWorker(registry, transport, tier_models=None, default_model=None,
  timeout_seconds=120.0)`** — `registry` is the builtin `Registry`, used for
  contract lookup only; `transport` is a callable `transport(model, prompt)
  -> str`; `timeout_seconds` is retained on the instance for callers that
  build transports around the worker (the transport itself owns all I/O).
- **Routing**: `tier_models[spec.routing.preferred_tier]` first — keys may be
  the strings `"T0".."T3"` or `RoutingTier` members (the enum's values are
  exactly those strings, so both lookup shapes are supported) — falling back
  to `default_model`; when neither is configured a `WorkerError` names the
  tier and command.
- **Prompt**: a system-style preamble carrying the command contract (name +
  version, purpose, declared inputs, declared outputs, done condition) plus
  the resolved kwargs as canonical JSON, closing with the strict reply rule:
  "Reply with ONLY a JSON object …"; for multi-target steps the keys must be
  the full target refs or their unique leaf names (the coordinator's mapping
  rules), for a single target any JSON value. When the caller passes
  `targets=` to `execute`, the exact refs are named in the prompt.
- **Response handling**: strip a single optional ```` ```json ```` (or bare
  ```` ``` ````) fence, `json.loads` strictly, and — when targets are known —
  validate with `map_results_to_targets` imported from `runtime.coordinator`
  (coordinator.py itself untouched). Unparseable/invalid/non-text responses
  and target-mapping failures raise **`WorkerError`** carrying the raw
  response tail (last 500 chars, also exposed as `.tail`); the coordinator's
  existing exception path records it as a coherent failed run.
- **`.commands`** returns the registry's command names.

### 2. `src/tikhon/cli.py`

- `--worker model|deterministic` (default `deterministic` — CI baseline
  unchanged) on both `tikhon run` and `tikhon resume`.
- With `model`, the worker is built from environment configuration:
  `TIKHON_WORKER_TRANSPORT` (`http`|`exec`), `TIKHON_MODEL`,
  `TIKHON_TIER_MODELS` (JSON object tier→model), `TIKHON_API_BASE` +
  `TIKHON_API_KEY` (http), `TIKHON_EXEC_COMMAND` (argv template with
  `{model}`/`{prompt}` placeholders, JSON array or shell-word string). Any
  missing/malformed required env prints `error: …` and exits 1 **before**
  `EventStore` is even opened — the same guard style as `--seal`, verified
  by asserting zero events in the db.
- **http transport**: stdlib-only `POST {TIKHON_API_BASE}/chat/completions`
  with the OpenAI-compatible shape (`model`, `messages:
  [{role: "user", content: prompt}]`, `temperature: 0`), returning
  `choices[0].message.content`.
- **exec transport**: `subprocess.run` of the substituted argv template with
  a 120 s timeout; nonzero exit raises with the stderr tail.
- No retries: the coordinator contract governs retries.
- Requirement 4 (test/edit/review stay deterministic): under `--worker
  model` a small `_HybridModelWorker` wrapper dispatches `edit`/`test`/
  `review` to the existing deterministic handlers (an effectful file write
  or a pytest run cannot be truthfully performed by a model) and everything
  else routes to the model. The deterministic handler code itself is
  untouched.

### 3. `tests/test_worker_adapter.py` (new, 28 tests)

Stub/local transports only — no test touches a real network:
routing (preferred tier, enum keys, default fallback, missing-model error),
prompt content (purpose, inputs, done, kwargs JSON, JSON-only instruction,
named targets), response parsing (plain JSON, ```` ```json ```` fence, bare
fence, invalid JSON → `WorkerError` with exactly-500-char tail, non-text),
multi-target mapping via the imported `map_results_to_targets` (leaf keys
pass, missing key → `WorkerError`, full-ref keys accepted), CLI guard
(exit 1 with clear error and zero events before run creation; resume guard;
deterministic default unchanged; env validation), `_HybridModelWorker`
(edit writes deterministically, other commands route to the model), and one
end-to-end: a 2-step program (define + calculate with a DONE predicate)
driven through `SequentialCoordinator` by a `ModelWorker` with a stub
transport → succeeded, outputs committed, events recorded — proving
duck-type compatibility.

## Transport seam design

The seam is a single callable, `transport(model: str, prompt: str) -> str`:
`ModelWorker` knows nothing about HTTP, subprocesses, retries, or vendors —
it only resolves *which* model to call and *what* to send, while the
transport answers *how*. Real transports (OpenAI-compatible HTTP, argv-template
subprocess) are constructed in the CLI from `TIKHON_*` env configuration; the
repo's tests inject recording stubs, which keeps the adapter fully testable
offline.

## Verification

- Baseline before edits: `python3 -m pytest -q` → **484 passed**.
- Final: `python3 -m pytest -q` → **512 passed** (484 + 28 new; a transient
  red wave from the concurrent parser agent's mid-edit state was re-run to
  green per the wave protocol).
- Seal recomputed after all edits matches `seal.txt`
  (`d9e8e127…79cd0a`), written before the first source edit; `program.think`
  was never modified afterwards.
- `git status` confirms only `src/tikhon/cli.py` (modified), the new
  `src/tikhon/worker_adapter.py` and `tests/test_worker_adapter.py`, and
  `demo/runs/issue-08-model-worker/` were touched by this run; `syntax/`,
  `registry/`, `runtime/coordinator.py`, `runtime/events.py`, `tasks.py`,
  `resume.py`, `audit.py`, and other demo runs are untouched (the
  `syntax/*` modifications in the worktree belong to the concurrent parser
  agent).

## Limitations

- `remember`/`recall` route to the model under `--worker model` (only
  test/edit/review are pinned deterministic per the issue); a run using them
  with a model worker would need the hybrid set extended.
- `timeout_seconds` is stored on `ModelWorker` and used as the shared
  default (120 s) by the CLI-built transports; per-command contract budgets
  (`Budget.max_seconds`) are not yet enforced against the transport deadline.
- The CLI http/exec transports raise transport errors (connection, timeout,
  nonzero exit) rather than retrying, by design ("no retries").
