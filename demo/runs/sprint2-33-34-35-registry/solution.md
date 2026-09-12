# Solution — sprint2-33-34-35-registry

## Run identity
- **Run ID**: sprint2-33-34-35-registry
- **Seal**: `4d9eb3ea0f9a18da42a9fb2e5f6adaaba1e6ab235c7111123ab2d8e0e2106701`
- **Program**: `demo/runs/sprint2-33-34-35-registry/program.think` — the ATLAS resolution plan from issue #33's comment, with `src/atlas/` string literals updated to `src/tahoe/` (#53 rebrand). Linted valid and sealed before any source edit. Never edited after sealing. Re-verified: seal matches.

## Files changed
| File | Change |
|------|--------|
| `src/tahoe/registry/registry.py` | `registry_digest` hashes `spec.to_dict()` per `(name, version)`; `_version_sort_key` parses prerelease identifiers numerically (semver §11) |
| `src/tahoe/registry/spec.py` | Added `_tier_rank`, type grammar validation (`_validate_type_entry`), `SchemaError` import; `RoutingPolicy` rejects `permitted_tiers` below `minimum_tier` |
| `src/tahoe/registry/builtins.py` | Fixed 4 builtin profiles (fetch, prove, delegate, solve): removed T0 from `permitted_tiers`, raised `validator_tier` to >= `minimum_tier` |
| `src/tahoe/worker_adapter.py` | `_resolve_model` checks `preferred_tier >= minimum_tier`, raises `WorkerError` if below |
| `tests/test_registry.py` | Updated assertions for changed `validator_tier` values (solve T0→T1, prove T0→T2, delegate T0→T2) |
| `tests/test_registry_correctness.py` | New: 28 tests for all three issues' acceptance items |
| `tests/test_worker_adapter.py` | Extended: 1 test for minimum_tier dispatch enforcement |
| `demo/runs/sprint2-33-34-35-registry/**` | Run artifacts (program.think, seal.txt, WORKLOG.md, solution.md, evaluation.json) |

## Tests added
- `tests/test_registry_correctness.py` — 28 tests
- `tests/test_worker_adapter.py` — 1 test (extended)
- **Total new**: 29 tests
- **Final count**: 893 passed (864 baseline + 29 new) in 22.10s

## Issue #33 — registry_digest hashes full specs
- `registry_digest` now hashes `spec.to_dict()` per `(name, version)` instead of the 5-field summary `(name, version, effect_class, execution, minimum_tier)`.
- Capability, budget, failure, idempotency, and any other spec change now changes the digest.
- Order-invariant: sorted by `(name, version)`.
- The builtin digest changed from `24edbbe6...` to `6e28fe3d...` (expected — the digest formula changed).
- **Committed artifact report**: the old digest `9160b5ecc029cd02da9c109fe578c7e1ec1714c6b82267bc17157addb73381b7` is embedded in `demo/runs/issue-15-registry-digest/` (evaluation.json, WORKLOG.md, solution.md). These are read-only committed artifacts from a previous run and are not broken — they record what was true at that time. The `demo/runs/` directory is append-only evidence storage.

## Issue #34 — prerelease ordering and minimum_tier enforcement
- `_version_sort_key` now parses prerelease identifiers: numeric identifiers compare numerically (alpha.10 > alpha.2), alphabetic identifiers compare lexicographically, numeric < alphabetic for mixed comparisons (semver §11). Release (no prerelease) beats prerelease.
- `RoutingPolicy.__post_init__` rejects `permitted_tiers` entries below `minimum_tier` (tier ranking: T0 < T1 < T2 < T3).
- Worker `_resolve_model` checks `preferred_tier >= minimum_tier` and raises `WorkerError` if below.
- Fixed 4 builtin profiles: `fetch` (min T1, was permitting T0), `prove` (min T2, was permitting T0), `delegate` (min T2, was permitting T0), `solve` (min T1, was permitting T0). The issue named fetch, prove, delegate; solve had the same violation and was fixed too.

## Issue #35 — type grammar validation and SchemaError
- Added `_validate_type_entry(entry, field_name)` called from `CommandSpec.__post_init__` for both `inputs` and `parameters`.
- Validates `name:type` format (name matches `^[a-z][a-z0-9_]*$`).
- Validates the type against the closed type grammar: primitive atoms, artifact types, KB types, workspace types, descriptor types, node-type prefixes (G, Q, C, K, OUT, V, D, H, U, E, R, F, P, ART), slash compound types (each segment must be a valid atom), and int with bound (`int<=N`, `int>N`, `int>=N`, `int<N`).
- Raises `SchemaError` (previously dead code) for: unknown type, unbounded int parameter, missing colon, empty type, bad name, unknown compound segment.
- All 23 builtins register successfully with the validation in place.

## Deviations
- Fixed `solve` in addition to the three named builtins (fetch, prove, delegate) — it had the same minimum_tier violation and would fail to register with the new validation.
- The program.think was adapted from issue #33's sealed ATLAS plan with `src/atlas/` → `src/tahoe/` path updates only (no logic changes); this is recorded as a protocol note in evaluation.json.

## Blockers
- None.
