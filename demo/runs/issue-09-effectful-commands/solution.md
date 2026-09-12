# Solution: issue-09-effectful-commands

GitHub issue #9 — **Effectful commands: edit, test, review with idempotency keys**.

## Seal

`b37f564cdf29fff23e88b7f57559fc05b871c15c3e78894a764b7f0c1010a970`
(`seal.txt`; program.think was linted, sealed and hashed before the first
source edit and never modified afterwards.)

## What was implemented

### 1. Complete CommandSpecs (`src/tikhon/registry/builtins.py`)

Three new factories appended to `BUILTIN_FACTORIES`, in the existing spec
style (purpose, inputs, parameters, preconditions, outputs, effects, done,
typed failures, effect_class, execution, capabilities, evidence, budget,
idempotency, compensation, routing):

| command | effect_class | rationale |
|---------|--------------|-----------|
| `edit`  | `EffectClass.IRREVERSIBLE_WRITE` | a filesystem write is a durable mutation with no transactional rollback; the enum already supports the class (no new value needed). Compensation note required and present: *restore the previous file content from the pre-write backup; a refused path leaves nothing to compensate*. |
| `test`  | `EffectClass.READ_ONLY` | executes test cases in a subprocess and records the outcome; declares no durable effect. |
| `review`| `EffectClass.READ_ONLY` | inspects declared artifacts and records findings; no durable effect. |

### 2. Idempotency keys + WorkspacePolicy (`src/tikhon/runtime/coordinator.py`)

- Every `INVOCATION_DISPATCHED` payload now carries
  `"idempotency_key": "<run_id>:<invocation_id>"` — cheap and uniform, on
  success and failure paths alike.
- `SequentialCoordinator` gained `workspace_root: str | None = None`
  (the WorkspacePolicy hook). When set, dispatches of effectful commands —
  resolved from the builtin registry as the durable-write effect classes
  (`REVERSIBLE_WRITE`, `IRREVERSIBLE_WRITE`), so `edit` and `remember` —
  inject a resolved `_workspace_root` kwarg into the resolved args (and
  therefore into the DISPATCHED payload). When `None`, dispatch is
  unchanged and no root is provided.

### 3. Deterministic handlers + `--workspace` (`src/tikhon/cli.py`)

- `_deterministic_handlers(memory=None, run_id="", workspace_root=None)`
  (still zero-arg compatible) now implements:
  - `edit(path, content)`: resolves the path under the workspace root via
    `_resolve_workspace_path` — refuses absolute paths, `..` escapes, and
    symlink-escaping realizations with `ValueError` **before any bytes are
    written** — creates parent directories, writes UTF-8, returns the
    workspace-relative path (so a downstream `test(path = E.written)`
    chains naturally).
  - `test(path, timeout_seconds=60)`: runs
    `python3 -m pytest -q <path>` (via `sys.executable`) in a subprocess
    with a timeout and returns `{"exit_code", "tail"}` with the tail
    bounded to the last 40 lines; timeouts raise a typed `ValueError`.
  - `review(artifact_refs, ...)`: READ_ONLY placeholder returning the
    artifact refs.
- `tikhon run` gained `--workspace PATH`, defaulting to the `--db`
  directory; the root is passed both to the handlers (closure fallback for
  direct calls) and to the coordinator (dispatch injection).

### 4. Tests

- `tests/test_registry.py`: catalog grew to 20 commands (sorted);
  parametrized EFFECTFUL_COMMANDS contract/presence/effect-class/input-shape
  tests; edit's compensation must not be a placeholder.
- `tests/test_coordinator.py`: idempotency key format on every dispatched
  payload (default run id, explicit run id, failed invocation); workspace
  root injected only for effectful commands; no injection when
  `workspace_root` is None.
- `tests/test_effectful.py` (new): sealed-program end-to-end through the
  real CLI — edit→test→review run succeeds with `DONE OUT.exit_code == 0`,
  default workspace (db dir) works, absolute-path and `../` refusals fail
  coherently (FAILED + RUN_FINISHED, zero state nodes, all tasks
  cancelled, nothing written inside or outside the workspace); handler-level
  security units reject every traversal shape; tail bounded to 40 lines;
  review returns refs.

## Results

- Full suite: **363 passed** (baseline 314; +49 new or extended tests).
- Live demo: `scratch-edit-test-review.think` ran through the real CLI
  (`succeeded/100%`, `tikhon audit` OK); the three DISPATCHED payloads
  carry `issue-09-scratch:inv-1/2/3`, and only the effectful edit dispatch
  carries `_workspace_root`.

## Deviations / notes

- The issue offered REVERSIBLE_WRITE-or-IRREVERSIBLE for `edit`; the enum
  already contained `IRREVERSIBLE_WRITE`, so the stronger, more accurate
  class was chosen (see the in-source comment above the field).
- The coordinator still dispatches effectful commands when
  `workspace_root` is None (no injection — custom handlers may ignore the
  concept entirely), but the *CLI* edit/test handlers treat an undeclared
  workspace as a precondition failure: writing to an undeclared root would
  be a security hole, and `tikhon run` always declares one (default: the
  db's directory), so CLI runs are unaffected.
- `test` uses `sys.executable -m pytest` rather than the literal
  `python3` token so venv-based environments execute the same interpreter
  that hosts the run; behavior is identical here.
- Issue #12 ran concurrently on `src/tikhon/syntax/`; no edits were made
  in that tree, and the combined suite is green.
