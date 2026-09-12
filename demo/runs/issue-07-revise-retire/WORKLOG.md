# Worklog: issue-07-revise-retire

Seal: `b731e3e0d9be477d6a1a28a9e44ad837ca09dfe44b45199ae8fac4c381fa2c61`

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to the revise/retire wiring only: optional trailing `REVISE r1, r2 | RETIRE r3` clause on invocation lines (syntax), corrections committed inside the step's own StateDelta (coordinator), projection/versioning/replay consistency, and no changes to cli.py, registry, memory, or audit.
Outputs: `G.plan` = confirm baseline, seal program, read grammar/runtime, design clause semantics, patch parser+model+coordinator, extend three test files, run full suite.
Evidence: Baseline `python3 -m pytest -q` showed `397 passed in 6.24s` before any edit.

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Read parser.py (line grammar, `_STEP_RE`, ref lists, validation flow, `_statement_dict` canonical form), model.py (frozen Invocation), state/delta.py, runtime/events.py (`_Record`/`append_batch` CAS flow, `project_state`), and coordinator.py end to end (waves 3–4 idempotency/CALL/workspace logic included).
Outputs: `E.patterns` = the correction hook points.
Evidence: `StateDelta` already models `revise_nodes`/`retire_nodes` and `apply_to` already merges/retires; `project_state` replays any SUCCEEDED delta via `StateDelta.from_dict(...).apply_to`, and `append_batch` bumps `state_version` for any SUCCEEDED carrying a delta — so delta.py and events.py need zero changes; only the grammar and the delta emission were missing.

## step.design
Status: succeeded
Inputs: `E.patterns`
Actions: Designed the minimal sound clause: anchored end-of-line regex cannot reach into quoted argument text (targets are pure refs); `Invocation` gains defaulted `revisions`/`retirements` tuples; validation is pragmatic per the issue — existence (declared INPUT or an earlier step's target), not-own-target, no REVISE/RETIRE overlap, KB.* rejected; REVISE pinned to single-target steps because revised refs receive the step's single target value (positional mapping was explicitly rejected as too magical); RETURN of a retired ref stays the programmer's responsibility; canonical JSON carries the clause only when non-empty so every pre-existing seal digest stays byte-identical.
Outputs: `V.design` = semantics fixed and documented in the grammar comment (parser.py, model.py docstrings).
Evidence: issue text "REVISE refs are set to the step's single target value when there is exactly one target; RETIRE refs are removed".

## step.patch
Status: succeeded
Inputs: `V.design`
Actions: Extended `_STEP_RE` handling with `_CORRECTIONS_RE` and built `Invocation(..., revisions=..., retirements=...)`; added the validation block to `validate_program`'s Invocation branch; emitted `StateDelta(add_nodes=..., revise_nodes=..., retire_nodes=...)` in `SequentialCoordinator`, resolving corrections inside the pre-VALIDATION_PASSED try block so a malformed unvalidated invocation fails through the standard atomic path, and updating the run-state `values` mapping in lockstep (revised refs re-resolve, retired refs fail). Sealed program.think predates all of these edits.
Outputs: `P.patch` = changes confined to src/tikhon/syntax/parser.py, src/tikhon/syntax/model.py, src/tikhon/syntax/__init__.py (one minimal export), src/tikhon/runtime/coordinator.py.
Evidence: `git diff --stat` shows exactly those four sources; `src/tikhon/state/delta.py` untouched because application logic already existed.

## step.check
Status: succeeded
Inputs: `P.patch`, `C.done`
Actions: Added 39 tests: clause shapes (both/either/neither, comma lists, whitespace, malformed), validation rejections (unknown/own-target/overlap/KB/late-defined/multi-target REVISE), seal determinism and canonical-form stability; coordinator revise-replaces/retire-removes in one delta, version bump, revised value visible to later steps incl. DONE, retired ref failing coherently, protocol-internal retire, replay identity + clean audit; event-store projection of revise/retire, reopen replay, history retention, retire-of-absent no-op. Also lints `scratch-program.think` exercising the clause.
Outputs: `V.tests` = full suite green; scratch program lints `valid`.
Evidence: `python3 -m pytest -q` → `444 passed` (397 baseline + 39 new + 8 from the concurrent issue-13 agent's tests, which pass and share no files with this change).

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Recomputed the seal after all edits and diffed against seal.txt; verified the concurrent agent's files (cli.py, learn.py, test_learn.py, issue-13 run dir) were never touched; confirmed coordinator diff is purely additive around the wave 3–4 idempotency/CALL/workspace logic.
Outputs: `V.result` = issue #7 acceptance met; seal intact; no commits made.
Evidence: `tikhon seal demo/runs/issue-07-revise-retire/program.think` → `b731e3e0d9be477d6a1a28a9e44ad837ca09dfe44b45199ae8fac4c381fa2c61`, identical to seal.txt written before the first source edit.
