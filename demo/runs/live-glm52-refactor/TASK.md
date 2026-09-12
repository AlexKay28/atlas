# Task: Extract Target-Mapping Logic from SequentialCoordinator

## Refactor

Extract the inline target-mapping logic (lines 207-243 of
`src/thinklang/runtime/coordinator.py`) from the `execute` method into a
standalone pure function `map_results_to_targets(targets, result)`.

## Problem

The `SequentialCoordinator.execute` method is 70 lines long. Buried inside
it is a 36-line inline block that maps a worker's return value to step
target references. The logic handles four cases with complex branching:

1. Single target: assign the entire result directly.
2. Multi-target with full-key match: `result[target]` wins.
3. Multi-target with leaf-name match: `result[leaf]` when unambiguous.
4. Error paths: non-mapping result for multi-target, ambiguous leaves,
   missing keys.

This logic has no dedicated unit tests; it is only exercised through
end-to-end coordinator tests. It cannot be tested in isolation because
it is inline closure code with no function boundary.

## Constraints

- Preserve all public behavior: event order, state projection, error
  messages, task ledger transitions, and output mapping must remain
  identical.
- Do not change the `SequentialCoordinator` public API.
- Do not change event types, payload shapes, or the `EventStore` interface.
- Do not edit unrelated files or existing demo attempts.
- Add focused unit tests for the extracted function.
- All existing tests must pass unchanged.

## Acceptance Criteria

1. `map_results_to_targets` is a module-level function in
   `coordinator.py` that accepts `(targets: tuple[str, ...], result: Any)`
   and returns `(dict[str, Any] | None, str | None)` — either
   `(target_values, None)` on success or `(None, error_message)` on
   failure.
2. The `execute` method calls `map_results_to_targets` instead of the
   inline block.
3. All existing tests in `test_coordinator.py` pass unchanged.
4. New focused tests in `test_coordinator.py` exercise:
   - Single-target mapping (any result type)
   - Multi-target mapping by full key
   - Multi-target mapping by leaf name
   - Non-mapping result for multi-target fails
   - Ambiguous duplicate leaf names fail
   - Missing keys fail
5. `python3 -m pytest -q` exits 0.

## Rollback

Revert `coordinator.py` and `test_coordinator.py` to their pre-refactor
state. No other files are touched.
