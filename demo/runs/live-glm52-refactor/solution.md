# Solution: Extract Target-Mapping Logic from SequentialCoordinator

## Refactor

Extracted the 36-line inline target-mapping block from
`SequentialCoordinator.execute` (coordinator.py:207-243) into a
standalone module-level pure function `map_results_to_targets(targets,
result)`.

## Changes

### `src/thinklang/runtime/coordinator.py`

- **Added** `map_results_to_targets(targets: tuple[str, ...], result: Any)
  -> tuple[dict[str, Any] | None, str | None]` as a module-level function
  (before the `DeterministicWorker` class).
- **Replaced** the 36-line inline block in `execute` with a single call:
  `target_values, validation_error = map_results_to_targets(
  statement.targets, result)`.
- **Added** `map_results_to_targets` to `__all__`.
- The function preserves the exact error-message wording for
  "non-mapping", "ambiguous result keys", and "missing result keys" paths
  that existing tests assert on.

### `tests/test_coordinator.py`

- **Added** 6 focused unit tests exercising `map_results_to_targets`
  directly:
  1. `test_single_target_accepts_any_type` — single target accepts
     int, str, list, dict, None.
  2. `test_multi_target_by_full_key` — full target reference match.
  3. `test_multi_target_by_leaf_name` — leaf-name match.
  4. `test_non_mapping_result_for_multi_target_fails` — non-mapping
     result for multi-target.
  5. `test_ambiguous_duplicate_leaf_fails` — duplicate leaf names
     without full-key match.
  6. `test_missing_key_fails` — missing key in result mapping.

## Test Results

- Targeted: `python3 -m pytest tests/test_coordinator.py -q` → 22 passed
- Full suite: `python3 -m pytest -q` → 163 passed

## Behavior Preservation

All 16 pre-existing coordinator tests pass unchanged. The function is
pure (no side effects, depends only on its arguments). The `execute`
method is now ~34 lines shorter.
