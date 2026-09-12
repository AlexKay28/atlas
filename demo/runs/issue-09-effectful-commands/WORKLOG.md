# Worklog: issue-09-effectful-commands

Seal: `b37f564cdf29fff23e88b7f57559fc05b871c15c3e78894a764b7f0c1010a970`

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to the effectful-command layer: three new CommandSpecs (edit, test, review) in the builtin registry, a uniform `idempotency_key` (`<run_id>:<invocation_id>`) on every INVOCATION_DISPATCHED payload, a WorkspacePolicy hook (`workspace_root` on SequentialCoordinator with `_workspace_root` injected into effectful dispatches), and real deterministic CLI handlers for edit/test/review plus a `--workspace` argument defaulting to the db's directory. No changes to syntax/, events.py, tasks.py, audit.py, or other run dirs.
Outputs: `G.plan` = baseline, seal program, registry specs, coordinator keys + workspace policy, CLI handlers, tests, scratch lint/run, full suite.
Evidence: Baseline `python3 -m pytest -q` showed `314 passed in 1.14s` before any edit.

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Located the CommandSpec factory pattern in registry/builtins.py, the closed EffectClass enum in registry/enums.py (IRREVERSIBLE_WRITE already exists), the DISPATCHED append site in runtime/coordinator.py, the `_deterministic_handlers` closure pattern in cli.py, and the catalog-equality test in tests/test_registry.py.
Outputs: `E.patterns` = spec style, dispatch payload path, handler closure pattern, test update points.
Evidence: enums.py declares `IRREVERSIBLE_WRITE = "irreversible_write"` (line 19), so no enum change is needed for edit.

## step.read
Status: succeeded
Inputs: `E.patterns`
Actions: Read builtins.py, enums.py, coordinator.py, cli.py, registry/spec.py (reserved names exclude edit/test/review) and the test files; confirmed existing tests only index `payload["args"]` on DISPATCHED events, so adding a uniform `idempotency_key` breaks nothing; confirmed `_deterministic_handlers()` must stay zero-arg compatible (tests/test_audit.py calls it bare).
Outputs: `ART.sources` = complete integration context.
Evidence: tests/test_coordinator.py:641,1048 read `event.payload["args"]`; tests/test_audit.py:77 calls `_deterministic_handlers()` with no arguments.

## step.design
Status: succeeded
Inputs: `ART.sources`
Actions: Designed the layer: edit = IRREVERSIBLE_WRITE (durable filesystem mutation; compensation restores prior content, refusals leave nothing to compensate), test = READ_ONLY (subprocess pytest, bounded tail), review = READ_ONLY (returns artifact refs); idempotency key computed uniformly at dispatch for every invocation; WorkspacePolicy resolves effectful commands from the builtin registry (durable-write classes) rather than a hardcoded name list, so custom handlers and pure commands are untouched; CLI handlers resolve paths through an absolute+normpath+realpath containment check refusing absolute paths and `..` escapes before any bytes are written.
Outputs: `E.design` = command contracts, key format, injection rule, path-security rule.
Evidence: edit refused paths raise ValueError before `open()`; the failure batch leaves zero state nodes and cancels all remaining tasks.

## step.patch
Status: succeeded
Inputs: `E.design`
Actions: Added `_edit`, `_test`, `_review` factories to builtins.py and appended them to BUILTIN_FACTORIES; added the `_effectful_commands()` resolver, the `workspace_root` constructor parameter, `_workspace_root` injection for effectful dispatches, and `idempotency_key` in the DISPATCHED payload to coordinator.py; added `_resolve_workspace_path`, the edit/test/review handlers, the `workspace_root` parameter of `_deterministic_handlers`, `--workspace` argument, and the run wiring to cli.py.
Outputs: `P.patch` = three source files edited.
Evidence: program.think and seal.txt (b37f564cdf29fff23e88b7f57559fc05b871c15c3e78894a764b7f0c1010a970) were written and hashed before the first source edit; the digest recomputed after all edits matches and program.think was never modified afterwards.

## step.apply
Status: succeeded
Inputs: `P.patch`
Actions: Extended tests: test_registry.py catalog growth plus parametrized EFFECTFUL_COMMANDS contract/presence/effect-class/input-shape tests and a non-placeholder compensation check; test_coordinator.py idempotency-key format tests (success, explicit run id, failed invocation) and workspace injection/no-injection tests; new tests/test_effectful.py with sealed-program CLI end-to-end runs (edit→test→review succeeds, default workspace = db dir, absolute and `../` refusals fail coherently) and handler-level security unit tests.
Outputs: `ART.patch` = updated and new test files.
Evidence: Diffs confined to src/tikhon/registry/builtins.py, src/tikhon/runtime/coordinator.py, src/tikhon/cli.py, tests/test_registry.py, tests/test_coordinator.py, tests/test_effectful.py, and demo/runs/issue-09-effectful-commands/.

## step.check
Status: succeeded
Inputs: `ART.patch`, `C.done`
Actions: Linted and ran the scratch program through the real CLI (edit writes scratch/test_scratch.py, test executes it under pytest with DONE exit_code == 0, review returns the refs), audited the run, and ran the full pytest suite.
Outputs: `V.tests` = all checks passed.
Evidence: `scratch-edit-test-review.think` lints `valid`; the CLI run prints `succeeded/100%`; the three DISPATCHED payloads carry `issue-09-scratch:inv-1/2/3` and only inv-1 (edit) carries `_workspace_root`; `tikhon audit` prints OK; full suite green (count recorded in evaluation.json).

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Recomputed the program seal and checked every acceptance condition against the goal.
Outputs: `V.result` = goal satisfied.
Evidence: Seal digest recomputed after all edits equals seal.txt (b37f564cdf29fff23e88b7f57559fc05b871c15c3e78894a764b7f0c1010a970); program.think unchanged since sealing; all acceptance criteria in evaluation.json hold.
