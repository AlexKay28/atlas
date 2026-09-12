# WORKLOG — issue-15-registry-digest

Seal: 3f2c99f04e430fd6b82ea10ecf3a1e924e3e9fafb88ec9e0c7e34edc6eeb5c16
Program: demo/runs/issue-15-registry-digest/program.think (sealed before any source edit; underscore program name required because sealing precedes the grammar change)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed issue #15 into three change areas: (1) deterministic builtin-registry digest helper + RUN_STARTED metadata/payload recording, (2) audit compatibility with legacy runs lacking a digest, (3) hyphen-tolerant PROGRAM name pattern with underscore-only step ids, plus doc and test updates.
Outputs: G.plan = implement digest helper in src/tikhon/registry/registry.py, extend SequentialCoordinator.execute create_run metadata and RUN_STARTED payload with "registry_digest", confirm audit.py (read-only) ignores RUN_STARTED, relax _HEADER_RE name group only, update SKILL.md sentence, add tests in test_syntax.py / test_coordinator.py / test_audit.py.
Evidence: issue text; src/tikhon/runtime/coordinator.py:160-166 (create_run + RUN_STARTED payload); src/tikhon/audit.py (audit_run checks gapless/truthfulness/invocation-ids/ledger/projection only — no RUN_STARTED read); src/tikhon/syntax/parser.py:13-17 (_NAME, _HEADER_RE).

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located the exact integration points: Registry stores specs keyed (name, version); CommandSpec exposes effect_class/execution enums and routing.minimum_tier; builtins BUILTIN_FACTORIES load 15 commands at 1.0.0; EventStore.create_run canonical-JSONs the metadata dict; coordinator RUN_STARTED payload currently {"program", "version"}; parser _NAME regex feeds header, step ids, refs, commands, arg names, STOP kinds — so the header needs its own pattern. Existing tests assert history[0].event_type is RUN_STARTED but no payload-key assertions would break from adding a key.
Outputs: E.patterns = the anchor lines above.
Evidence: src/tikhon/registry/registry.py:22-64; src/tikhon/registry/spec.py:96-318 (to_dict, frozen dataclass); src/tikhon/registry/builtins.py:818-825 (load_builtin_registry); src/tikhon/runtime/coordinator.py:156-166; src/tikhon/runtime/events.py:192-225; src/tikhon/syntax/parser.py:13-22; tests/test_coordinator.py:234-246.

## step.design
Status: succeeded
Inputs: E.patterns
Actions: Chose the digest formula: sorted list of (name, version, effect_class, execution, minimum_tier) tuples — each enum rendered as its .value string — serialized as canonical JSON (ensure_ascii=False, separators=(",",":"), sort_keys=True) and hashed with sha256. Cheap (one pass over the registry, no full-spec dumps), deterministic regardless of registration order. Placement: registry_digest(registry) in src/tikhon/registry/registry.py; coordinator resolves the builtin registry lazily and caches the digest at module level so every run start costs one dict lookup. Parser gets a dedicated _PROGRAM_NAME = [a-z][a-z0-9_-]* used only by _HEADER_RE; step ids/refs/commands/args keep _NAME. Legacy-audit compatibility needs no audit.py change since audit_run never reads RUN_STARTED; the test proves it with a hand-built pre-digest run.
Outputs: E.design = formula + file/anchor plan above.
Evidence: this design; validated against CommandSpec.to_dict field names and RoutingTier enum values in src/tikhon/registry/enums.py.

## step.patch
Status: succeeded
Inputs: E.design
Actions: Implemented the design: registry_digest(registry) added to src/tikhon/registry/registry.py (sorted (name, version, effect_class, execution, minimum_tier) summaries -> canonical JSON -> sha256); SequentialCoordinator.execute computes the builtin digest once per process (lazy module-level cache) and records it in create_run metadata and the RUN_STARTED payload key "registry_digest"; parser gets _PROGRAM_NAME = [a-z][a-z0-9_-]* used only by _HEADER_RE while _NAME stays underscore-only for step ids, refs, commands, args, STOP kinds; SKILL.md PROGRAM-name sentence replaced (underscore rule kept for step ids and refs). src/tikhon/audit.py untouched by design.
Outputs: P.patch = diffs in src/tikhon/registry/registry.py, src/tikhon/runtime/coordinator.py, src/tikhon/syntax/parser.py, .opencode/skills/tikhon-demo/SKILL.md, plus new tests in tests/test_syntax.py (5), tests/test_coordinator.py (3), tests/test_audit.py (1).
Evidence: git diff of the four tracked files; registry_digest formula in src/tikhon/registry/registry.py:22-45; coordinator RUN_STARTED block at src/tikhon/runtime/coordinator.py:175-189.

## step.check
Status: succeeded
Inputs: P.patch, C.done
Actions: Ran python3 -m pytest -q (full suite): 274 passed (baseline 265 + 9 new). Ran targeted suites: tests/test_syntax.py 55 passed, tests/test_coordinator.py 35 passed, tests/test_audit.py 19 passed. Re-sealed program.think with repo code (PYTHONPATH=src python3 -m tikhon seal): digest identical to seal.txt. Sealed a hyphenated-name program (PROGRAM a-b-c) via repo CLI: lints valid and seals deterministically across two runs. Cross-process builtin digest stability checked: 9160b5ecc029cd02da9c109fe578c7e1ec1714c6b82267bc17157addb73381b7, equal on repeated computation.
Outputs: V.tests = full-suite pass + seal-stability + CLI hyphen checks above.
Evidence: pytest output "274 passed in 0.97s"; seal outputs in the shell transcript; tests/test_coordinator.py::test_run_started_carries_stable_registry_digest, ::test_two_coordinators_same_registry_same_digest, ::test_extra_spec_changes_registry_digest; tests/test_syntax.py hyphen block; tests/test_audit.py::test_audit_clean_on_legacy_run_without_registry_digest.

## step.verify
Status: succeeded
Inputs: G.goal, V.tests
Actions: Verified every acceptance criterion against evidence: (1) digest helper exists, is cheap (one summary tuple per registered (name, version)) and deterministic; (2) RUN_STARTED payload carries registry_digest beside program/version without breaking existing payload-key assertions; (3) create_run metadata carries the same digest; (4) two coordinators on the same registry produce equal digests; (5) a registry extended via the Registry API (dataclasses.replace of a builtin spec, re-registered under a new name) changes the digest; (6) a hand-built legacy run whose RUN_STARTED lacks registry_digest and whose metadata lacks it audits clean (audit.py never reads RUN_STARTED — confirmed by reading src/tikhon/audit.py, unchanged); (7) hyphenated program names parse and seal deterministically, leading hyphen/digit and hyphenated step ids rejected, underscore names unchanged; (8) SKILL.md updated with the single-sentence rule change; (9) full suite green; no files outside the allowed set touched (untracked demo/runs/issue-05-kb-memory/ and src/tikhon/memory.py belong to the concurrent agent and were left alone).
Outputs: V.result = all criteria passed; see evaluation.json.
Evidence: each criterion maps to the test names and CLI checks recorded in step.check; git status shows only the allowed tracked files modified.
