# WORKLOG — sprint2-33-34-35-registry

Seal: 4d9eb3ea0f9a18da42a9fb2e5f6adaaba1e6ab235c7111123ab2d8e0e2106701
Program: demo/runs/sprint2-33-34-35-registry/program.think (linted valid and sealed before any source edit; re-verified after all edits: seal matches). The ATLAS resolution plan from issue #33's comment was copied verbatim; string literals mentioning `src/atlas/` were updated to `src/tahoe/` per the #53 TAHOE rebrand — logic stays identical; recorded as a protocol note in evaluation.json. program.think was never edited after sealing.

## step.frame — plan from the issue
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Read issues #33, #34, #35 via `gh issue view`. Copied the sealed ATLAS resolution plan from issue #33's comment into demo/runs/sprint2-33-34-35-registry/program.think. Updated `src/atlas/` string literals to `src/tahoe/` (#53 rebrand). Linted (`tahoe lint`) and sealed (`tahoe seal`) before any source edit.
Outputs: G.plan = the three-issue resolution bundle.
Evidence: `PYTHONPATH=src python3 -m tahoe lint demo/runs/sprint2-33-34-35-registry/program.think` → valid; `PYTHONPATH=src python3 -m tahoe seal ...` → 4d9eb3ea...; seal.txt written.

## step.search — locate the defect sites
Status: succeeded
Inputs: G.plan, C.scope
Actions: Read all context files: registry.py (digest ~34-41, _version_sort_key ~16-21, resolve ~76), spec.py (validation ~195-200, inputs/parameters ~237-240), errors.py (dead SchemaError ~8-9), worker_adapter.py (tier routing ~203-217), builtins.py (fetch/prove/delegate violate minimum_tier), tests/test_registry.py, tests/test_worker_adapter.py, demo/runs/issue-26-benchmarks/ (run format).
Outputs: E.sites = the defect sites and their surrounding code.
Evidence: file reads of all listed context files.

## step.read — fetch sources
Status: succeeded
Inputs: E.sites
Actions: Read the full content of registry.py, spec.py, errors.py, worker_adapter.py, builtins.py, enums.py, __init__.py, test_registry.py, test_worker_adapter.py, and the issue-26-benchmarks demo run format (WORKLOG.md, evaluation.json, seal.txt, program.think).
Outputs: ART.sources = the read sources.
Evidence: read tool outputs for all context files.

## step.analyze — extract findings
Status: succeeded
Inputs: ART.sources
Actions: Identified three distinct defects:
  (a) #33: registry_digest hashes only 5 summary fields (name, version, effect_class, execution, minimum_tier) — capability, budget, failures, idempotency changes don't change the digest.
  (b) #34: _version_sort_key tie-breaks on raw string (alpha.10 < alpha.2); RoutingPolicy validates minimum_tier only for membership in permitted_tiers, not for ranking; worker_adapter reads only preferred_tier, never checks minimum_tier; 4 builtin profiles (fetch, prove, delegate, solve) permit T0 below their minimum_tier.
  (c) #35: spec.py accepts free strings for inputs/parameters — the name:type grammar, int<=N bound syntax, and slash compound types are parsed by nothing; SchemaError (errors.py:8-9) is raised nowhere.
  Also identified the closed type grammar from all 23 builtins: 24 unique types including primitives (text, json, bool, map, tuple, numeric, enum, descriptor), artifact types (artifact, artifacts, immutable, refs, ranked_refs), KB types (kb_key, kb_key_or_prefix), workspace types (workspace_relative), descriptor types (deterministic, predicates, media_types, token_cap, bounded_types, pinned_ref), solver types (pddl/smt, lean4/isabelle), node-type prefixes (G, Q, C, K, OUT, V, D, H, U, E, R, F, P, ART), and int bounds (int<=N, int>N, int>=N, int<N).
  Also found the old registry digest (9160b5ecc...) embedded in committed artifacts demo/runs/issue-15-registry-digest/ — reported, not broken.
Outputs: E.findings = the defect analysis and type grammar.
Evidence: builtins type enumeration via Python; grep for old digests.

## step.plan — decompose into subgoals
Status: succeeded
Inputs: G.plan
Actions: Split into three implementation tracks:
  (a) #33: Replace the 5-field summary hash with full spec.to_dict() per (name, version); keep sorted by (name, version) for order-invariance.
  (b) #34: Fix _version_sort_key to parse prerelease identifiers numerically (semver §11); add tier ranking to spec.py; validate permitted_tiers >= minimum_tier; fix 4 builtin profiles (fetch, prove, delegate, solve); add worker dispatch minimum_tier guard.
  (c) #35: Add _validate_type_entry function with closed type grammar; call it in CommandSpec.__post_init__ for inputs and parameters; raise SchemaError for violations.
  Plus: update existing tests that assert old validator_tier values; write 29 new tests covering all acceptance items.
Outputs: G.subgoals = the three tracks plus test updates.
Evidence: this decomposition.

## step.patch — apply edits
Status: succeeded
Inputs: C.scope, G.subgoals
Actions:
  (a) registry.py: registry_digest now hashes sorted (name, version, spec.to_dict()) tuples instead of 5-field summaries.
  (b) registry.py: _version_sort_key now parses prerelease into numeric/alphabetic identifiers (semver §11); release (prerelease=None) gets rank 1, prerelease gets rank 0.
  (b) spec.py: Added _TIER_ORDER, _tier_rank() helper; RoutingPolicy.__post_init__ now rejects permitted_tiers below minimum_tier.
  (b) builtins.py: Fixed fetch (T0 removed from permitted_tiers, validator T0→T1), prove (T0 removed, validator T0→T2), delegate (T0 removed, validator T0→T2), solve (T0 removed, validator T0→T1).
  (b) worker_adapter.py: _resolve_model now checks preferred_tier >= minimum_tier and raises WorkerError if below.
  (c) spec.py: Added _TYPE_ATOMS, _NODE_TYPE_PREFIXES, _INT_BOUND_PATTERN, _validate_type_entry(); called from CommandSpec.__post_init__ for inputs and parameters; raises SchemaError for unknown types, unbounded int, missing colon, empty type, bad name.
  (c) spec.py: Imported SchemaError from errors.
  Tests: Updated test_registry.py assertions for changed validator_tier values (solve, prove, delegate). Created test_registry_correctness.py with 28 tests. Extended test_worker_adapter.py with 1 test for minimum_tier enforcement.
Outputs: ART.patch = the applied edits.
Evidence: git diff of all touched files.

## step.test — run suite
Status: succeeded
Inputs: ART.patch
Actions: Ran full pytest suite.
Outputs: V.tests = 893 passed (864 baseline + 29 new) in 22.10s.
Evidence: `PYTHONPATH=src python3 -m pytest -q` → 893 passed in 22.10s.

## step.review — review against acceptance
Status: succeeded
Inputs: ART.patch, V.tests, C.done
Actions: Reviewed each acceptance criterion against evidence (see evaluation.json).
Outputs: V.review = the review.
Evidence: acceptance map in evaluation.json.

## step.check — check done condition
Status: succeeded
Inputs: V.review, C.done
Actions: Confirmed: digest differs on capability or budget change and stays invariant to registration order; all acceptance items for #33, #34, #35 have named tests and pass; suite green; only owned files touched.
Outputs: V.verdict = passed.
Evidence: evaluation.json acceptance map.

## step.verify — verify the goal
Status: succeeded
Inputs: G.goal, V.verdict, V.tests, E.findings
Actions: Verified the goal: registry_digest now hashes full specs; prerelease ordering follows semver §11; minimum_tier enforced at both validation and dispatch; type grammar validated; SchemaError raised; all 23 builtins register; suite green.
Outputs: V.result = "resolved".
Evidence: this WORKLOG, evaluation.json, solution.md.

## step.report — render report
Status: succeeded
Inputs: V.result, V.verdict
Actions: Rendered solution.md and evaluation.json.
Outputs: ART.report = the run report.
Evidence: demo/runs/sprint2-33-34-35-registry/solution.md, evaluation.json.
