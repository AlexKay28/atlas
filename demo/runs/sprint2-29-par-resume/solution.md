# Solution — issue #29: PAR resume drops completed branches' outputs

## Problem

In `_execute_par_entry`'s resume path, the `already_joined` branch (coordinator.py:1320) stored `already_joined[position] = []` for completed branch tasks. The comment promised "re-reading committed child state" but the code stored an empty list. The barrier then committed PAR SUCCEEDED with `ordered_nodes` drawn from `adopted_by_branch.get(position, [])` — which was `[]` for already-joined branches. Since `_apply_committed_deltas` replays only SUCCEEDED deltas and CHILD_ADOPTED carries no delta, completed-branch targets existed nowhere after resume, bricking the run.

Additionally, `dispatch_branch` always emitted INVOCATION_READY and INVOCATION_DISPATCHED without checking whether they were already committed from a pre-crash dispatch, creating duplicates on resume for already-dispatched branches.

## Fix

### 1. Re-derive adoption in the already_joined branch (coordinator.py ~line 1320)

Replaced `already_joined[position] = []` with a call to `_adopt_branch_nodes(child_run_id, {}, targets)` — the exact same adoption the live path uses (coordinator.py:1453). This is a pure read of the child run's committed state: seeds from an empty dict, applies the child's SUCCEEDED deltas, and maps the branch's targets. A fresh adoption and a resume adoption are now identical.

### 2. Add prior_types resume guard to dispatch_branch (coordinator.py ~line 1380)

Added the same `prior_types` guard the plain-invocation path uses (coordinator.py:4551): before emitting INVOCATION_READY and INVOCATION_DISPATCHED, check if the branch task is IN_PROGRESS and if those event types are already committed for the branch's invocation_id (`par<k>`). If so, skip re-emitting them.

## Tests (tests/test_par_resume.py)

Four new tests:

1. `test_crash_after_branch_adoption_resume_succeeds_with_barrier_refs` — Acceptance 1: crash at PAR crash_hook (after all branches adopted, before SUCCEEDED) + resume → succeeded, PAR SUCCEEDED delta contains all barrier refs.
2. `test_project_state_after_resume_contains_every_barrier_ref` — Acceptance 2: project_state after resume contains every barrier ref.
3. `test_no_duplicate_invocation_ready_for_dispatched_par_branch` — Acceptance 3: no duplicate INVOCATION_READY/INVOCATION_DISPATCHED for par<k> ids after resume.
4. `test_resume_projection_equals_normal_full_run` — Regression: crash + resume projection equals a crash-free full run's projection.

## Results

- **Baseline**: 857 passed
- **After fix**: 861 passed (857 + 4 new)
- **Suite wall**: 22.24s
- **Files changed**: src/tahoe/runtime/coordinator.py, tests/test_par_resume.py (new), demo/runs/sprint2-29-par-resume/** (new)
