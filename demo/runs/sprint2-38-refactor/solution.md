# solution.md — sprint2-38-refactor

GitHub issue #38: decompose the 6k-line coordinator — one failure-finalization
module, a planning module, child/par/scatter/delegate engines, and drive-loop
extraction.

## What was built

**`src/tahoe/runtime/finalize.py` (new, 413 lines)** — unified failure-record
assembly. One parametrized `fail_invocation` / `fail_invocation_concurrent` /
`fail_run` / `fail_global_deadline_sequential` / `fail_global_deadline_concurrent`
/ `fail_run_from_exception` consumed by all assembly sites. Eliminates the
six+ duplicated failure-record builders that forced every bugfix to be applied
twice (the PAR resume bug #29 lived only in the sequential path).

**`src/tahoe/runtime/planning.py` (new, 323 lines)** — plan-entry dataclass
(`PlanEntry`), `build_plan`, `task_text`, `collect_anchors`,
`map_results_to_targets`, and the concurrent-frontier DAG helpers
(`scan_arg_refs`, `condition_refs`, `entry_refs`, `refs_overlap`,
`build_dependency_dag`).

**`src/tahoe/runtime/children.py` (new, 289 lines)** — `ChildEngine` mixin:
CALL child-run machinery (start/resume/read-back), child-result adoption,
PAR branch program synthesis, explicit artifact merge.

**`src/tahoe/runtime/par.py` (new, 641 lines)** — `ParEngine` mixin: PAR
branch task creation, PAR entry execution (branch dispatch/join/barrier),
PAR branch child-run execution, branch argument resolution. Plus the
par-helper functions (`par_branch_invocation_id`, `par_branch_run_id`, etc).

**`src/tahoe/runtime/scatter.py` (new, 1388 lines)** — `ScatterEngine`
mixin: scatter entry execution, per-candidate lifecycle, gather entry
execution (all/any/ranked modes), candidate failure handlers. Plus
scatter-helper functions (`candidate_invocation_id`, `candidate_node_id`,
`judge_score`, etc).

**`src/tahoe/runtime/delegate.py` (new, 563 lines)** — `DelegateEngine`
mixin: delegate plan authoring, validation, bounded execution, positional
adoption. Plus delegate constants and helper functions
(`delegate_plan_name`, `delegate_plan_digest`, `count_plan_steps`, etc).

**`src/tahoe/runtime/driver.py` (new, 1871 lines)** — `DriveEngine` mixin:
the sequential and concurrent plan-drive loops, worker-call dispatch,
budget-deadline enforcement, and the concurrent frontier's scheduling logic.

**`src/tahoe/runtime/helpers.py` (new, 308 lines)** — shared registry
lookups, condition evaluation, DONE predicates, and invocation-id regexes —
extracted to avoid circular imports between coordinator.py and driver.py.

**`src/tahoe/runtime/coordinator.py` (modified, 6420 → 929 lines)** — now
contains only `SequentialCoordinator` (driver + wiring, inheriting all
engine mixins), `DeterministicWorker`, `CrashInterrupt`, and re-exports for
backward compatibility.

## Per-step test counts

| Step | New module(s) | coordinator.py lines | Tests |
|------|-------------|---------------------|-------|
| Baseline | — | 6420 | 938 pass |
| 1: finalize.py | finalize.py (413) | 6083 | 938 pass |
| 2: planning.py | planning.py (323) | 5816 | 938 pass |
| 3: engines | children.py, par.py, scatter.py, delegate.py | 4945 | 938 pass |
| 4: driver | driver.py, helpers.py | 929 | 938 pass |

## Acceptance criteria

1. **Golden-event tests pass byte-identically after each extraction** —
   938/938 at every step, no golden-event divergence.
2. **Failure-record assembly exists in exactly one module** — `finalize.py`
   contains all parametrized failure-record builders; coordinator and
   engines delegate to it.
3. **coordinator.py shrinks to driver + wiring (<1500 lines)** — achieved
   929 lines (target <1500).
4. **All seals unaffected** — program.think seal
   `d424dad6d1fd65b42a4ec2c2a0fe3a908cb763f213e9444b7d5f2f67d2f81e3c`
   re-verified after all edits.

## Constraints honored

- Touched only: `src/tahoe/runtime/coordinator.py` (modified), new runtime
  modules (finalize.py, planning.py, children.py, par.py, scatter.py,
  delegate.py, driver.py, helpers.py), `demo/runs/sprint2-38-refactor/` (new).
- No test files modified.
- No git commit made.
- Full suite: **938 passed** in ~24s.

## Deviations

- The two drive loops (_drive_plan and _drive_plan_concurrent) were extracted
  into driver.py as-is rather than collapsed into one loop with a
  scheduling-strategy object. The extraction achieves the <1500 line target
  (929 lines) and isolates the drive loops so a future collapse is a local
  change. The scheduling-strategy collapse was deferred because the two loops
  have subtle behavioral differences (resume handling, in-flight tracking,
  conditional evaluation timing, crash-hook semantics) that require careful
  unification beyond a structural refactor's risk budget.
- helpers.py was created as an additional module beyond the issue's named
  modules to avoid circular imports between coordinator.py and driver.py.
- The issue mentions six failure-assembly sites; post-#31 there are fewer
  unique shapes (some were already consolidated), but all remaining sites
  now delegate to finalize.py.
