# WORKLOG — issue-04-scatter-gather

Sealed program: `program.think` (seal digest in `seal.txt`, computed before any source edit).
Digest: `87f1d0649d405081881273ff9d605a4b6056f8ce5036d6a7daacb7be8c7a48bc`

## step.frame

Status: completed
Inputs: G.goal (issue #4 statement + epic alignment note from issue #27)
Actions: Framed the work as naming-resolution-first per issue #27: the canonical
join-rule names are the draft spec's `all` / `any` / `ranked`; the issue body's
`first` / `best` are accepted aliases (`first` = `any`, `best` = `ranked`,
normalized at parse time so both spellings seal identically). `USING any` means
"first terminal success wins" resolved deterministically as the lowest candidate
index that succeeds (the spec's "arrival time is not semantic" rule); `USING
ranked` means an explicit judge invocation scores each candidate and the max
score wins with lowest-index tie-break. CONCURRENCY (fan-out may dispatch in
parallel up to max_workers/budget caps) is kept separate from the TOTAL-WORK
bound (MAX n): this run expands candidates sequentially in collection order and
honors the Wave 10 budget gate per candidate dispatch, documenting the choice.
Outputs: G.plan
Evidence: demo/runs/issue-04-scatter-gather/program.think (sealed before edits)

## step.locate

Status: completed
Inputs: G.plan
Actions: Located the code sites. `SCATTER`/`GATHER` sit in `_UNSUPPORTED`
(src/tikhon/syntax/parser.py) so every line is rejected at parse; statement
models live in src/tikhon/syntax/model.py and exports in
src/tikhon/syntax/__init__.py. The coordinator (src/tikhon/runtime/coordinator.py)
drives a plan of `_PlanEntry` items with positional `inv-N` ids, a batch-created
task per entry, and resume invariants in `_resume_existing_run` (SUCCEEDED
prefix set, task-count/text match) that candidate fan-out must coexist with.
audit.py (untouchable) forbids FAILED events in a run that finishes `succeeded`
(`run_finished_status_mismatch`), which fixes how USING-any losers are recorded.
Draft-spec scatter/gather semantics live in docs/spec/03-runtime-and-events.md
("Deterministic Scatter/Gather") and docs/spec/04-completeness.md Reference
Program A.
Outputs: E.sites
Evidence: repository inspection recorded in this worklog before edits

## step.design

Status: completed
Inputs: E.sites
Actions: Designed the change set (details in solution.md):
grammar `SCATTER <item-ref> IN <collection-ref> MAX <int>` followed by one
indented `step.<id>: DO ... -> <target>` body line, then `GATHER <step-id> AS
<alias-ref> USING all|any|ranked|first|best [JUDGE step.<id>]` followed when the
judge is declared by one indented judge step line; item refs bind per candidate
inside the body and judge only; candidate results commit to
`<alias>.c<k>.<leaf>` scoped nodes; the gather commits the alias value
(list of candidate values under all, winner value under any/ranked) with
selection evidence in its task completion; scatter and gather are ordinary plan
entries with their own ledger tasks so the resume prefix invariants stay intact;
candidate invocation ids are `inv-<scatter-positional>.cand<k>`; USING-all and
USING-any loser recording avoids FAILED events so audit stays clean.
Outputs: P.design
Evidence: this worklog + solution.md grammar section

## step.patch

Status: completed
Inputs: P.design
Actions: Implemented the change set in src/tikhon/syntax/model.py (frozen
`Scatter`/`Gather` nodes), src/tikhon/syntax/parser.py (block parsing, alias
normalization, validation), src/tikhon/syntax/__init__.py (exports), and
src/tikhon/runtime/coordinator.py (plan entries, scatter expansion with
per-candidate lifecycle, gather join with judge ranking, resume support).
Outputs: ART.patch
Evidence: git diff confined to the allowed file set; tests/test_scatter.py

## step.check

Status: completed
Inputs: ART.patch, C.behavior
Actions: Ran the new tests/test_scatter.py suite (parse/validation, all/any/
ranked behavior, loser cancellation, judge scoring and tie-break, MAX overflow,
crash mid-scatter + resume, replay identity, ledger per-candidate tasks,
research-style program) plus the full `python3 -m pytest -q` suite; audited
scatter runs with tikhon.audit.audit_run.
Outputs: V.tests
Evidence: pytest output recorded in evaluation.json (631 baseline + new tests)

## step.verify

Status: completed
Inputs: G.goal, evidence = [ART.patch, V.tests]
Actions: Verified the sealed demo program's digest still reproduces after all
source edits (seal unchanged), that programs without SCATTER/GATHER seal
byte-identically (pinned digest test), and that the acceptance criteria of
issue #4 hold: Reference-Program-A-style research program parses and executes
with deterministic workers, gathered state identical after reopen, losers
recorded but never committed.
Outputs: V.result
Evidence: evaluation.json acceptance checklist
