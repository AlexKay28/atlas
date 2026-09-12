# Worklog: issue-05-kb-memory

Seal: `05ce785668d65695c213329ffb6bf989f695b604ed7416d2bf5f2c0b4f6d8a1c`

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to the cross-run semantic-memory layer: a new KnowledgeBase module (own SQLite file), `KB.` reference prefix with three validation rules, `remember`/`recall` command contracts, coordinator KB-ref resolution with an optional constructor `memory`, and CLI wiring rooted at `<db dir>/kb.sqlite`. No changes to events.py, tasks.py, audit.py, or other run dirs.
Outputs: `G.plan` = confirm baseline, seal program, add memory module, grammar, commands, coordinator, CLI, tests, scratch lint, full suite.
Evidence: Baseline `python3 -m pytest -q` showed `265 passed in 0.86s` before any edit.

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Located the reference grammar in syntax/parser.py (`_PREFIX`, `_REF_RE`, `validate_program`), the CommandSpec factory pattern in registry/builtins.py with the closed EffectClass enum (REVERSIBLE_WRITE already exists), the dispatch/arg-resolution path in runtime/coordinator.py, and the handler factory + `_cmd_run` wiring in cli.py.
Outputs: `E.patterns` = parser validation points, builtin factory style, coordinator resolved_kwargs loop, cli handler closure pattern.
Evidence: CoALA memory taxonomy mapped: working memory = run-local G/C/E nodes, episodic = event store, semantic = new KnowledgeBase, procedural = the sealed programs themselves.

## step.read
Status: succeeded
Inputs: `E.patterns`
Actions: Read parser.py, builtins.py, enums.py, coordinator.py, cli.py, registry.py, and the four test files end to end; confirmed `Registry.names()` returns sorted names (so tests/test_registry.py BUILTIN_NAMES must grow in sort order) and that tests/test_audit.py calls `_deterministic_handlers()` with no arguments (signature must stay zero-arg compatible).
Outputs: `ART.sources` = complete integration context.
Evidence: tests/test_registry.py:142 asserts exact catalog equality; tests/test_audit.py:77 passes no arguments to the handler factory.

## step.design
Status: succeeded
Inputs: `ART.sources`
Actions: Designed the layer: keys are stored internally without the `kb.` prefix and validated as `kb.[a-z][a-z0-9_]*` at the API boundary; values stored as canonical JSON text with source_run and UTC updated_at; `KB.<name>` program refs resolve at dispatch time via `memory.get("kb.<name>")`; remember maps to the existing `EffectClass.REVERSIBLE_WRITE` (overwrite/delete is a natural compensation) instead of adding a new enum value; a coordinator constructed without `memory` raises before run creation when the program uses `KB.` refs.
Outputs: `E.design` = module schema, grammar rules, command contracts, resolution and error semantics.
Evidence: No EffectClass value needs adding, so no enum-vocabulary deviation exists; REVERSIBLE_WRITE is the closest existing class and was chosen deliberately.

## step.patch
Status: succeeded
Inputs: `E.design`
Actions: Wrote src/tikhon/memory.py (KnowledgeBase over its own SQLite file), added `KB` to the parser `_PREFIX` set with the three validation rules, added the `remember` and `recall` CommandSpec factories to builtins.py, added KB-ref resolution plus the `memory` constructor parameter and pre-run guard to SequentialCoordinator, and wired `_deterministic_handlers(memory, run_id)` with a KnowledgeBase opened next to the events db in `_cmd_run`.
Outputs: `P.patch` = five source files edited or created.
Evidence: program.think and seal.txt (05ce785668d65695c213329ffb6bf989f695b604ed7416d2bf5f2c0b4f6d8a1c) were written and hashed before the first source edit; program.think was never modified afterwards.

## step.apply
Status: succeeded
Inputs: `P.patch`
Actions: Extended tests: new tests/test_memory.py (roundtrip, persistence across reopen, prefix filter, key and value validation), test_syntax.py KB cases (refs parse, target rejected, INPUT declaration rejected), test_coordinator.py cross-run remember/recall cases and the missing-memory error, and test_registry.py catalog growth with parametrized remember/recall contract tests.
Outputs: `ART.patch` = updated source and test files.
Evidence: Diffs confined to the files allowed by issue #5.

## step.check
Status: succeeded
Inputs: `ART.patch`, `C.done`
Actions: Linted the scratch program exercising remember/recall inside this run dir, executed a real two-run CLI demo through kb.sqlite, and ran the full pytest suite.
Outputs: `V.tests` = all checks passed.
Evidence: `scratch-remember-recall.think` lints `valid`; the run-1/run-2 CLI pair shows the value remembered in run 1 recalled in run 2; full suite green (count recorded in evaluation.json).

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Recomputed the program seal and checked every acceptance condition against the goal.
Outputs: `V.result` = goal satisfied.
Evidence: Seal digest recomputed after all edits equals seal.txt (05ce785668d65695c213329ffb6bf989f695b604ed7416d2bf5f2c0b4f6d8a1c); program.think unchanged since sealing; all acceptance criteria in evaluation.json hold.
