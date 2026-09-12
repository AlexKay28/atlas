# WORKLOG — issue-20-child-runs

Seal: 1b71e0f8b79375f8fd47d99e499724b6b35e72a72b87111531da902fe945c3da
Program: demo/runs/issue-20-child-runs/program.think (linted valid and sealed 2026-09-12T16:48Z before any source edit; uses the current standalone CALL syntax — the issue's proposed `CALL ... AS child(...)` form is not implemented and deliberately absent)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed issue #20 into four change areas: (1) coordinator `_build_plan` stops flattening CALL inline — a CALL becomes its own plan entry whose execution spawns an isolated child run `"<parent_run_id>:<invocation_id>"` in the same EventStore with `child_of`/`call` lineage in RUN_STARTED; (2) parent output adoption: child RETURN refs map onto CALL targets by exact string, recorded as a new CHILD_ADOPTED event in the parent batch that commits the CALL's SUCCEEDED delta; (3) child failure (any non-succeeded terminal status) fails the parent through the standard atomic path with no adoption; (4) resume: terminal child adopted without re-execution, non-terminal child re-driven through the same machinery.
Outputs: G.plan = implement events.py (EventType.CHILD_ADOPTED) -> coordinator.py (plan rework + child execution + adoption) -> resume.py (delegate core to a coordinator resume method, child-aware) -> tests.
Evidence: issue #20 body; docs/spec/03-runtime-and-events.md "Protocol Calls" (child event namespace, pinned version, outputs visible only after the child terminal return contract validates); envelope.py ExternalDriver constraint (must keep `_PlanEntry.binds`/`finalizes` fields readable — CALL programs are rejected up front there, plain programs must keep working).

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located every integration point: coordinator.py `_build_plan` walk (CALL recursion at lines ~519-541), `_collect_anchors` (counts protocol steps inline), `_create_plan_tasks`/`_task_text` (task text), `_drive_plan` loop (binds/finalizes/DONE/finalize machinery), `execute` (create_run + RUN_STARTED seeding); events.py EventType (add CHILD_ADOPTED; projection needs nothing since the adoption event carries no delta); resume.py (binds replay block becomes obsolete; core reusable for child resume); audit.py (CHILD_ADOPTED is not in `_INVOCATION_BOUND_TYPES` so invocation-bound checks stay satisfied — zero audit changes expected); test_coordinator.py inline-CALL tests (assert parent-ledger protocol tasks and protocol-internal parent state — must be rewritten for isolation); test_learn.py counts a Call as one planned step independent of the coordinator (unaffected).
Outputs: E.sites = the anchor points above.
Evidence: src/tikhon/runtime/coordinator.py:494-544, 599-630, 1041-1058, 1176-1214; src/tikhon/runtime/events.py:32-57, 452-474; src/tikhon/resume.py:222-231; src/tikhon/audit.py:31-46; src/tikhon/envelope.py:664-687; tests/test_learn.py:20-28.

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read the touched-region sources in full: coordinator plan/driver structure (frozen `_PlanEntry`, closure-based `finish_failed_invocation`, prior_types resume guard, crash_hook site before VALIDATION_PASSED), events.py append_batch invariants (gapless seq, dup-SUCCEEDED guard per invocation, CAS state versions, TASK_UPDATED ledger validation), resume.py windows W0a-W12 and the task-text identity checks, audit.py five invariant checks, framing.think protocol (RETURN G.plan, E.context, ART.sources, V.analysis — pins the exact-string target contract used by the sealed program's CALL).
Outputs: ART.sources = the read sources.
Evidence: files listed in C.scope; framing.think RETURN line 30.

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Analyzed the correctness constraints the new semantics must satisfy: (a) child run ids must be deterministic and collision-free — `parent:inv-N` chains uniquely identify every invocation in the run tree, so repeated calls and nested calls never collide and resume re-derives the same id; (b) parent values must stay invisible to the child except through explicitly passed CALL args — the child seeds its state from the protocol's INPUT declarations with values resolved against the PARENT values mapping at the call site; (c) adoption must be replay-safe — read the child's RETURN values from the child's deterministic state projection (not from a transient result dict) so fresh and resumed adoptions are identical; (d) CHILD_ADOPTED and the CALL's SUCCEEDED delta must share one append_batch so a crash can never split an adoption from its state commit (the store's dup-SUCCEEDED guard then makes double adoption impossible); (e) envelope.py (untouchable) reads `_PlanEntry.binds`/`finalizes` — those fields stay, always empty, with CALL programs rejected by the driver's own statement scan.
Outputs: E.findings = the constraint list above.
Evidence: this analysis; events.py append_batch docstring; envelope.py:664-687.

## step.decompose
Status: succeeded
Inputs: G.plan
Actions: Split the work into five subtasks: (1) events.py: add CHILD_ADOPTED = "child.adopted"; (2) coordinator.py: `_PlanEntry.call` field, `_build_plan`/`_collect_anchors` one-entry-per-CALL, `_task_text` CALL form, `_resolve_call_arguments`, `_execute_program` parameterized start (child_of/call_name/initial_values), `_execute_call_child` (fresh start / terminal adopt / non-terminal re-drive), `_resume_existing_run` shared resume core, `_drive_plan` CALL branch with adoption batch; (3) resume.py: delegate to `_resume_existing_run`, drop the binds replay, document child semantics; (4) tests/test_child_runs.py: isolation, adoption event, atomic failure, reopen replay, audit, resume, nested depth; (5) tests/test_coordinator.py: rewrite the inline-CALL tests for isolated semantics.
Outputs: G.subgoals = the five subtasks above.
Evidence: this decomposition.

## step.hypothesize
Status: succeeded
Inputs: G.goal, E.findings
Actions: Generated candidate designs for the child identity and adoption mechanism: (H1) child run keyed by protocol name + call counter — rejected: not stable across resume re-derivations with conditionals; (H2) child run keyed by parent seq of the CALL's DISPATCHED event — rejected: requires reading events to name a run before creating it; (H3) child run id = `<parent_run_id>:<invocation_id>` where invocation_id is the positional plan index `inv-N` — chosen: deterministic from the plan alone, collision-free in the run tree, identical on resume, and the idempotency key `run_id:invocation_id` already uses the same coordinates.
Outputs: H.theses = the three candidates with H3 selected.
Evidence: coordinator.py invocation-id rule (inv-{idx+1}), DISPATCHED idempotency key format.

## step.calculate
Status: succeeded
Inputs: G.goal, E.findings
Actions: Pinned the numeric invariants: max protocol-call nesting depth stays 8 (static validation, unchanged); one child run per CALL invocation; the parent's state version bumps exactly once per CALL (the adoption batch); CHILD_ADOPTED carries no delta so it never moves the version itself.
Outputs: F.metrics = {"depth_bound": 8, "state_bumps_per_call": 1, "adoption_events_per_call": 1}.
Evidence: src/tikhon/syntax/parser.py _MAX_PROTOCOL_DEPTH; the CALL branch's single append_batch in coordinator.py.

## step.compare
Status: succeeded
Inputs: H.theses, C.done
Actions: Compared H3 (positional child run ids) against H1/H2 on the resume dimension: H3 re-derives the identical child id from the rebuilt plan without reading events, so crash-before/during/after-child windows all converge on the same run; H1 breaks under conditionals; H2 needs a seq lookup before the run exists.
Outputs: V.compared = H3 wins on determinism and resume-identity.
Evidence: the resume tests in tests/test_child_runs.py exercise all three windows.

## step.rank
Status: succeeded
Inputs: V.compared, C.done
Actions: Ranked the remaining design decisions: (1) adoption source = child's committed state (seeded INPUT bindings + replayed SUCCEEDED deltas) so fresh and resumed adoptions are byte-identical and a retired RETURN ref is correctly non-adoptable; (2) CHILD_ADOPTED + SUCCEEDED + invocation_recorded + task_completed in ONE append_batch; (3) RESULT_RECEIVED records the child's terminal contract in the parent before VALIDATION_PASSED, keeping the CALL's lifecycle uniform with DO steps; (4) keep _PlanEntry.binds/finalizes as always-empty vestiges because envelope.py (owned by another wave) reads them.
Outputs: R.ranked = the order above.
Evidence: coordinator.py _adopt_child_result docstring; envelope.py:664-687.

## step.challenge
Status: succeeded
Inputs: H.theses, E.findings
Actions: Adversarially probed the design: (a) could a resumed parent adopt twice? No — the store's duplicate-SUCCEEDED guard per invocation_id plus the atomic batch; (b) could a failed child leak partial outputs? No — the adoption helper never runs on a non-succeeded child and the FAILED path cancels pending tasks; (c) could a retired child RETURN ref publish a phantom? No — the delta replay pops retired refs before the target lookup; (d) could repeated CALLs collide? No — ids embed the plan position.
Outputs: V.challenge = no attack found; the four probes became regression tests.
Evidence: tests/test_child_runs.py::test_failed_child_fails_parent_atomically_with_no_adoption, ::test_retire_inside_child_is_child_local_and_blocks_adoption (test_coordinator.py), ::test_repeated_calls_stay_isolated_and_map_returns_per_target.

## step.choose
Status: succeeded
Inputs: R.ranked, V.challenge
Actions: Chose the final design: child run id "<parent_run_id>:<invocation_id>"; fresh start via _execute_program(child_of=..., call_name=..., initial_values=resolved args); terminal child adopted without re-execution; non-terminal child re-driven via _resume_existing_run; adoption read from the child's committed state; one atomic adoption batch.
Outputs: D.choice = the design above.
Evidence: src/tikhon/runtime/coordinator.py (_execute_call_child, _adopt_child_result, _resume_existing_run).

## step.remember
Status: succeeded
Inputs: D.choice
Actions: Recorded the durable lesson for future waves: isolated child runs need (1) deterministic ids derivable from the plan alone, (2) an adoption event that carries no delta, and (3) idempotent re-entry (start / adopt / re-drive) keyed on the child's own terminality — the same three-part pattern any future parallel or async CALL variant will need.
Outputs: K.record = the lesson above (key "issue20.child_runs").
Evidence: this WORKLOG; tests/test_child_runs.py resume windows.

## step.recall
Status: succeeded
Inputs: K.record
Actions: Re-called the recorded lesson against the implemented code: all three parts are present and tested; the async/parallel variant remains future work (CALL stays synchronous, per the issue).
Outputs: K.recalled = lesson confirmed applicable.
Evidence: tests/test_child_runs.py pass list.

## step.solve
Status: succeeded
Inputs: G.goal
Actions: Implemented the solution: events.py gains EventType.CHILD_ADOPTED ("child.adopted"; projection needs nothing since the event carries no delta); coordinator.py reworks the plan (one entry per CALL), executes children through the same machinery (_execute_program/_drive_plan/_resume_existing_run), and adopts through the atomic batch; resume.py delegates its core to _resume_existing_run and drops the inline-binds replay; audit.py needed ZERO changes (CHILD_ADOPTED is not invocation-bound-checked, and parent+child ledgers settle cleanly); parser.py needed ZERO changes (the current CALL grammar suffices).
Outputs: U.solution = the diff in src/tikhon/runtime/{coordinator,events}.py, src/tikhon/resume.py, tests/test_coordinator.py, tests/test_child_runs.py (new), demo/runs/issue-20-child-runs/ (new).
Evidence: git diff; full suite green.

## step.prove
Status: succeeded
Inputs: C.done
Actions: Verified each clause of C.done against executed tests: child run id/lineage (test_child_run_started_marks_child_of_and_call), parent state = adopted targets only (test_child_sees_only_passed_arguments_not_parent_values), CHILD_ADOPTED before the SUCCEEDED delta in one atomic batch (test_child_adopted_event_precedes_the_call_succeeded_delta), atomic failure without adoption (test_failing_child_fails_parent_atomically_with_no_adoption, test_blocked_child_fails_parent_and_stays_terminal_blocked), replay+audit on both runs (test_parent_and_child_replay_identically_after_reopen, test_parent_and_child_runs_audit_clean, test_failed_tree_audits_clean_parent_and_child), resume windows (test_crash_after_child_completion_resumes_by_adoption_only, test_crash_during_child_execution_rerives_nonterminal_child, test_crash_before_child_creation_starts_the_child_fresh, test_crash_after_adoption_does_not_duplicate_outputs, test_failed_child_then_resume_stays_failed_and_never_adopts), depth bound (test_nested_call_chain_beyond_depth_eight_still_rejected, two-level nesting in test_two_level_nested_calls_chain_child_run_ids), full suite green (607 passed).
Outputs: A.proof = the acceptance checklist in evaluation.json.
Evidence: pytest output "607 passed"; every clause maps to a named test.

## step.review
Status: succeeded
Inputs: ART.sources
Actions: Re-read the final coordinator/resume/events diffs for correctness and convention: no unreachable code, no forbidden-file edits (cli.py's working-tree modification belongs to the concurrent #19 agent; envelope.py/memory.py/registry/worker_adapter.py/protocols//docs/ untouched), ExternalDriver plan-shape compatibility preserved (binds/finalizes kept as always-empty fields), module docstrings updated to describe the #20 semantics.
Outputs: V.review = clean; two documentation-level notes carried into evaluation.json deviations.
Evidence: git status; the diff review.

## step.design
Status: succeeded
Inputs: V.review
Actions: Summarized the implemented design for solution.md: child identity scheme, state seeding, adoption semantics, failure semantics, resume windows, compatibility notes.
Outputs: P.design = demo/runs/issue-20-child-runs/solution.md.
Evidence: solution.md.

## step.patch
Status: succeeded
Inputs: P.design
Actions: Finalized the change set: coordinator.py (plan rework, _execute_program/_resume_existing_run/_execute_call_child/_adopt_child_result/_apply_committed_deltas, CALL branch with the atomic adoption batch), events.py (+CHILD_ADOPTED), resume.py (delegation + child-window documentation), tests/test_coordinator.py (inline-CALL tests rewritten for isolation), tests/test_child_runs.py (18 new tests), demo/runs/issue-20-child-runs/.
Outputs: ART.patch = the final diff (uncommitted, per instructions).
Evidence: git status/diff --stat.

## step.test
Status: succeeded
Inputs: ART.patch
Actions: Ran the full suite repeatedly during development and at the end: python3 -m pytest -q -> 607 passed (baseline 571 before this issue; +36 from this issue's new and rewritten tests). Targeted: tests/test_child_runs.py 18 passed; tests/test_resume.py 19 passed; tests/test_coordinator.py 76 passed; test_syntax/test_event_store/test_envelope/test_cli all green untouched.
Outputs: V.tests = full-suite pass, no regressions outside the deliberately rewritten inline-CALL tests.
Evidence: pytest output "607 passed in 8.25s".

## step.check
Status: succeeded
Inputs: V.tests
Actions: Verified the sealed artifact end to end with stub workers: re-sealed program.think with the final code -> digest identical to seal.txt (1b71e0f8b79375f8fd47d99e499724b6b35e72a72b87111531da902fe945c3da); executed the 22-command + CALL demo through SequentialCoordinator against protocols/framing.think -> terminal succeeded, parent ledger 23 tasks (22 DO + 1 CALL), child run demo-20:inv-22 with framing's 4 tasks, CHILD_ADOPTED payload {"adopted": {"E.context": "E.context", "V.analysis": "V.analysis"}, "child_run_id": "demo-20:inv-22", "child_status": "succeeded"}, audit ok for parent and child, replay identical after reopen.
Outputs: V.verdict = the sealed program executes under the new semantics with every acceptance property observable.
Evidence: the end-to-end transcript in step.check of WORKLOG; seal reproduction.

## step.report
Status: succeeded
Inputs: V.verdict
Actions: Wrote solution.md and evaluation.json (task, run_id, seal, terminal_status, steps, acceptance with per-criterion evidence, unresolved, protocol_deviations).
Outputs: ART.report = demo/runs/issue-20-child-runs/{solution.md, evaluation.json}.
Evidence: both files exist and parse as JSON.

## step.verify
Status: succeeded
Inputs: G.goal, V.tests
Actions: Final acceptance sweep: every criterion in evaluation.json passed=true with named evidence; no unresolved items; deviations documented (synchronous CALL only, envelope child_of skipped, adopted-event payload carries ref mapping not values, parent invocation-id sequence no longer continues across the CALL boundary by design, returned-but-retired child refs are non-adoptable by design).
Outputs: V.result = issue #20 implemented; epic #27 step 2 delivered.
Evidence: evaluation.json; the full-suite count.
