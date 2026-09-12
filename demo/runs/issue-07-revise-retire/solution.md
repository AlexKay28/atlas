# Solution: issue-07-revise-retire

Implements GitHub issue #7: `SequentialCoordinator` now emits the
`revise_nodes`/`retire_nodes` deltas that `StateDelta` already modeled, and
the grammar gains the clause that declares them.

## What changed

- `src/tikhon/syntax/parser.py` — invocation lines may end with an optional
  trailing correction clause `REVISE r1, r2 | RETIRE r3, r4` (either or both,
  pipe-separated groups; when both appear REVISE precedes RETIRE; each list is
  comma-separated refs). The clause is stripped by an end-of-line-anchored
  regex (`_CORRECTIONS_RE`) that cannot reach into quoted argument text, then
  the line parses as before. `validate_program` enforces, pragmatically per
  the issue: every revised/retired ref must be an existing node (declared
  INPUT or an earlier step's target — not the current step's own target, not
  a KB.* ref), no ref may appear in both groups, and REVISE requires a
  single-target step (see semantics below). `canonical_json` includes
  `revisions`/`retirements` only when non-empty, so every pre-existing seal
  digest is byte-identical. New minimal export `is_typed_reference`.
- `src/tikhon/syntax/model.py` — frozen `Invocation` gains
  `revisions: tuple[str, ...] = ()` and `retirements: tuple[str, ...] = ()`
  with the semantics documented on the class.
- `src/tikhon/syntax/__init__.py` — exports `is_typed_reference` (the allowed
  minimal export).
- `src/tikhon/runtime/coordinator.py` — after mapping results to targets, the
  step's corrections are resolved inside the pre-VALIDATION_PASSED try block
  (so a malformed, unvalidated invocation still fails through the standard
  atomic path) and committed in the SAME `StateDelta` as the step's adds:
  `StateDelta(add_nodes=..., revise_nodes=..., retire_nodes=...)`. The
  run-state `values` mapping is updated in lockstep so later steps resolve
  revised values and fail coherently on retired refs. An additive
  `_reject_unresolved_refs` guard fails any ref-shaped argument that no
  longer resolves (i.e. was retired) clearly, instead of the pre-existing
  passthrough silently handing the raw ref string to the worker; the guard
  is unreachable for every pre-#7 validated program. Idempotency keys,
  workspace injection, CALL expansion, lifecycle ordering: untouched.
- `src/tikhon/state/delta.py` and `src/tikhon/runtime/events.py`: **no
  changes** — read first, as instructed: `apply_to` already merges revise
  entries and pops retired ids, `project_state` replays any SUCCEEDED delta,
  and `append_batch` bumps `state_version` for any SUCCEEDED carrying one.
  Projection and replay identity therefore hold without new code.
- `tests/test_syntax.py` (+28 tests), `tests/test_coordinator.py` (+7),
  `tests/test_event_store.py` (+4).

## Exact REVISE/RETIRE semantics implemented

- `REVISE r1, r2` — each listed ref (an existing earlier node) is set to the
  step's **single target value**: the step must have exactly one target
  (validation rejects REVISE on multi-target steps; positional mapping was
  explicitly rejected as too magical in the issue). Emitted as
  `revise_nodes=[{"id": ref, "value": <target value>}, ...]`; `apply_to`
  merges it over the old node, replacing `value`. Later steps observe the
  revised value (including DONE predicates over later targets).
- `RETIRE r3, r4` — each listed ref is removed from the projection
  (`retire_nodes=[...]`, popped by `apply_to`) while the event history
  retains the original add. A later step referencing a retired ref fails the
  invocation through the standard atomic path with a clear "not in run state
  (retired or undefined)" error. Allowed on multi-target steps (no value
  needed). Whether a retired ref is still RETURNed on that path is the
  programmer's responsibility (validation deliberately does not check it).
- Both corrections ride in the same SUCCEEDED delta as the step's adds, so
  the state version bumps exactly once for the step, and replay after
  reopen is identical (audit-clean).

## Tikhon protocol

- `program.think` written first, in the pre-existing grammar, and sealed
  before any source edit: `b731e3e0d9be477d6a1a28a9e44ad837ca09dfe44b45199ae8fac4c381fa2c61`
  (seal.txt). Recomputed after all edits: identical. Never modified after sealing.
- `scratch-program.think` (written after landing, not sealed) exercises the
  clause — both groups, comma-separated refs — and lints `valid` with the
  local source (`PYTHONPATH=src python3 -m tikhon lint`).
- `WORKLOG.md` carries one section per planned step.

## Verification

- Full suite: `python3 -m pytest -q` → **444 passed** (baseline 397 + 39 new
  tests from this issue + 8 tests belonging to the concurrent issue-13
  agent, which pass and share no files with this change). No git commit made.
