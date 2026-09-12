# WORKLOG — sprint2-29-par-resume

Seal: f7b2c86a33b599ca6488942d7dfa175c36d83b4fdcd9f72902d049a70919a831
Program: demo/runs/sprint2-29-par-resume/program.think (linted valid and sealed before any source edit; the #53 TAHOE rebrand renamed src/atlas/ paths to src/tahoe/ — two string literals updated in the copied program, logic identical; protocol deviation recorded in evaluation.json).

## step.frame
Status: succeeded
Inputs: G.goal from program.think INPUT block
Actions: Framed issue #29 as a two-part fix: (1) re-derive branch adoption from terminal child runs in the already_joined resume path via _adopt_branch_nodes (the live path's exact adoption); (2) add prior_types resume guard to dispatch_branch to prevent duplicate INVOCATION_READY/INVOCATION_DISPATCHED for already-dispatched par<k> ids.
Outputs: G.plan = the two-part fix above.

## step.search
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located the bug at coordinator.py:1320 (already_joined[position] = []), the live adoption path at coordinator.py:1453 (_adopt_branch_nodes call), the dispatch_branch function at coordinator.py:1347, and the plain-invocation prior_types pattern at coordinator.py:4551.
Outputs: E.sites = the four code locations above.

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read the already_joined branch (lines 1310-1324), the live adoption path (lines 1449-1459), _adopt_branch_nodes (lines 1001-1027), dispatch_branch (lines 1347-1429), the plain-invocation prior_types guard (lines 4551-4653), test_par.py conventions, test_resume.py conventions, and the demo/runs/issue-26-benchmarks/ format.
Outputs: ART.sources = the read sources.

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Pinned the defect: already_joined[position] = [] stores an empty list where the comment promises re-reading committed child state. The barrier then commits PAR SUCCEEDED with ordered_nodes from adopted_by_branch.get(position, []) — which is [] for already-joined branches. _apply_committed_deltas replays only SUCCEEDED deltas; CHILD_ADOPTED carries no delta. So completed-branch targets exist nowhere after resume. Fix: call _adopt_branch_nodes(child_run_id, {}, targets) for each completed branch — a pure read of committed child state (seeds from empty dict, applies child's SUCCEEDED deltas, maps targets). Also identified that dispatch_branch always emits INVOCATION_READY + INVOCATION_DISPATCHED without checking prior_types — on resume for an already-dispatched (IN_PROGRESS) branch task, this creates duplicates.
Outputs: E.findings = the defect analysis above.

## step.plan
Status: succeeded
Inputs: G.plan
Actions: Split into two edits and one test file: (1) coordinator.py already_joined branch: replace `already_joined[position] = []` with _adopt_branch_nodes re-derivation; (2) coordinator.py dispatch_branch: add prior_types guard checking branch task status and committed event types before emitting READY/DISPATCHED; (3) tests/test_par_resume.py: four tests covering the three acceptance items plus a projection-equality regression.
Outputs: G.subgoals = the three deliverables above.

## step.patch
Status: succeeded
Inputs: C.scope, G.subgoals
Actions: Applied both coordinator.py edits and wrote tests/test_par_resume.py. Edit 1 (already_joined, ~line 1320): replaced `already_joined[position] = []` with a call to _adopt_branch_nodes(child_run_id, {}, targets) that re-derives adoption from the child run's committed state. Edit 2 (dispatch_branch, ~line 1380): added branch_prior_types check — if the branch task is IN_PROGRESS and INVOCATION_READY/INVOCATION_DISPATCHED are already committed, they are not re-emitted. Tests: 4 new tests in test_par_resume.py.
Outputs: ART.patch = the edits above.

## step.test
Status: succeeded
Inputs: tests/, timeout_seconds=900
Actions: Ran PYTHONPATH=src python3 -m pytest -q
Outputs: V.tests = 861 passed in 22.24s (857 baseline + 4 new)
Evidence: 861 passed, 0 failed, 0 errors.

## step.review
Status: succeeded
Inputs: ART.patch, V.tests
Actions: Reviewed both edits against the issue's acceptance criteria. All three acceptance items have named tests. The already_joined fix mirrors the live path exactly (_adopt_branch_nodes on the terminal child run). The prior_types guard follows the same pattern as the plain-invocation path.
Outputs: V.review = reviewed and accepted.

## step.check
Status: succeeded
Inputs: V.review, C.done
Actions: Verified: (1) crash after branch-1 CHILD_ADOPTED + resume yields succeeded with all barrier refs in PAR SUCCEEDED delta — test_crash_after_branch_adoption_resume_succeeds_with_barrier_refs PASS; (2) project_state after resume contains every barrier ref — test_project_state_after_resume_contains_every_barrier_ref PASS; (3) no duplicate INVOCATION_READY for already-dispatched par<k> — test_no_duplicate_invocation_ready_for_dispatched_par_branch PASS.
Outputs: V.verdict = all acceptance items pass.

## step.verify
Status: succeeded
Inputs: V.verdict, V.tests, E.findings
Actions: Confirmed the fix resolves the issue: resume after crash in PAR re-derives branch outputs from committed child state, the run succeeds with all barrier targets present, and lifecycle events are not duplicated.
Outputs: V.result = "resolved"

## step.report
Status: succeeded
Inputs: V.result, V.verdict
Actions: Wrote solution.md and evaluation.json summarizing the fix, tests, and acceptance.
Outputs: ART.report = solution.md + evaluation.json.
