# Runtime Failure Refactor

The coordinator now uses one atomic failure-finalization path for worker and
result-shape failures. It records `FAILED`, invocation metrics, cancellation of
the active task, cancellation of every unreached task, and `RUN_FINISHED` in one
batch.

Result shape validation now precedes `VALIDATION_PASSED`. Multi-target mappings
prefer exact typed target keys; leaf aliases remain supported only when the leaf
is unique among the invocation targets. Ambiguous aliases fail without state
mutation.

Verification: `157 passed in 0.47s`, including five new focused regressions.
