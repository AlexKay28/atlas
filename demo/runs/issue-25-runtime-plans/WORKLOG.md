# WORKLOG — issue-25-runtime-plans

Seal: b64c4e8cc17369ebd7f29513d805f487d59a85acc1099b241a711815c1191105
Program: demo/runs/issue-25-runtime-plans/program.think (linted valid and sealed 2026-09-12T18:01:09Z before any source edit; uses only the grammar that exists at seal time — all 22 registered commands as plain DO steps. The new delegate command is deliberately absent from the sealed program; the runtime flow it enables is validated by tests/test_delegate.py against this same sealed source.)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed issue #25 into five change areas: (1) a new `delegate` CommandSpec (READ_ONLY authoring; routing minimum T2 / preferred T3 / validator T0; failures INVALID_INPUT, FORMALIZATION, UNAVAILABLE); (2) a CHILD_PLAN_AUTHORED EventType recording the authored artifact (step_id, plan digest, raw plan text) BEFORE validation or execution; (3) a coordinator delegate plan-entry flow: worker reply = authored plan text, parse + registry validation, delegation bounds (step count <= max_steps, default 6, hard cap 12; no delegate command anywhere in the plan, transitively through called protocols), sealed-like program-name binding `delegated_<parent_step_id>`, isolated child run `<parent_run_id>:<invocation_id>` on the CALL machinery, positional adoption of authored RETURN refs onto the delegate targets; (4) resume reuses the recorded plan instead of re-asking the worker; (5) a deterministic fixed-sample-plan handler so tests/CI need no model.
Outputs: G.plan = implement events.py (CHILD_PLAN_AUTHORED) -> builtins.py (delegate spec) -> coordinator.py (delegate flow) -> cli.py (deterministic handler) -> worker_adapter.py (authoring prompt) -> tests.
Evidence: /tmp/issue25.md; epic #27 step 5; src/tikhon/runtime/coordinator.py CALL child machinery (issue #20) reused as-is.

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located every integration point: registry/builtins.py BUILTIN_FACTORIES (append _delegate); runtime/events.py EventType (one new member, no projection change — the event carries no delta); runtime/coordinator.py `_drive_plan` plain-invocation path (intercept after INVOCATION_DISPATCHED when command == "delegate", before the generic worker-result handling), `_execute_program` concurrency decision (delegate programs force the sequential loop like scatter/PAR), `_bind_child_inputs`/`_execute_program_child`/`_apply_committed_deltas` (reused verbatim for the authored child); cli.py `_deterministic_handlers` (add the fixed-sample delegate handler); worker_adapter.py `_build_prompt` (authoring instruction for the delegate envelope); audit.py (CHILD_PLAN_AUTHORED is not in _INVOCATION_BOUND_TYPES — no false positives expected, zero changes); tests/test_registry.py (additive BUILTIN_NAMES/DELEGATE_COMMANDS updates).
Outputs: E.sites = the anchor points above.
Evidence: src/tikhon/runtime/coordinator.py:_drive_plan; src/tikhon/syntax/parser.py _PREFIX (typed-reference namespaces already enforce the allowed target namespaces at parse time — zero syntax changes).

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read the touched-region sources in full: the CALL branch's lifecycle shape (READY/DISPATCHED/child/RESULT_RECEIVED/CHILD_ADOPTED+SUCCEEDED atomic batch), `_execute_program_child`'s three resume branches (missing -> fresh, terminal -> read back, non-terminal -> re-drive), `_bind_child_inputs`' leaf-name binding rule, events.py append_batch invariants (gapless seq, dup-SUCCEEDED guard, CAS state versions), parser validate_program contract (terminal RETURN/STOP required, protocols acyclic and depth-bounded at 8), audit.py invocation-bound event checks, worker_adapter.py envelope/prompt/response pipeline.
Outputs: ART.sources = the read sources.
Evidence: files listed in C.scope.

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Pinned the correctness constraints: (a) the ACCEPTED artifact is the RECORDED one — resume must reuse the CHILD_PLAN_AUTHORED payload instead of re-dispatching the worker, so a crash never triggers unrecorded replanning; (b) the plan digest must exist even for plans that fail to parse (it is computed from the step id + raw text alone), so rejected authoring attempts stay diagnosable in history; (c) the authored plan's RETURN refs are unknown to the parent program at seal time, so adoption is positional (authored RETURN ref k -> delegate target k) with a count mismatch rejected as FORMALIZATION — exact-string adoption (CALL's rule) is impossible for runtime-authored plans; (d) the no-recursion rule must walk CALLed protocol files transitively (a sealed static protocol could hide a delegate step behind an otherwise-clean authored plan); (e) the bound program name replaces the authored text's own header name (a model cannot know the parent step id), making the lineage label part of the executed artifact and of its digest; (f) delegate programs force the sequential plan loop (like scatter/PAR) so the concurrent frontier never has to understand delegate entries.
Outputs: E.findings = the constraint list above.
Evidence: this analysis; tests/test_delegate.py asserts each constraint.

## step.decompose
Status: succeeded
Inputs: G.plan
Actions: Split the work into six subtasks: (1) events.py: add CHILD_PLAN_AUTHORED = "child_plan.authored"; (2) builtins.py: the delegate CommandSpec + factory registration; (3) coordinator.py: DELEGATE_COMMAND constants, delegate_plan_name/delegate_plan_digest/count_plan_steps/_extract_plan_text helpers, _uses_delegate, _recorded_delegate_plan, _plan_contains_delegate, _execute_delegate_entry, the _drive_plan interception, the sequential-force; (4) cli.py: the deterministic fixed-sample-plan handler; (5) worker_adapter.py: the delegate authoring prompt section; (6) tests/test_delegate.py (new, 10 tests) + tests/test_registry.py (additive).
Outputs: G.subgoals = the six subtasks above.
Evidence: this decomposition.

## step.hypothesize
Status: succeeded
Inputs: G.goal, E.findings
Actions: Generated candidate designs for the child-run input binding: (H1) the authored plan embeds the resolved goal/constraints as literal text — rejected: the author would have to serialize worker results into program text, and the binding would escape the sealed-like record; (H2) the coordinator injects the resolved delegate arguments into the child state namespace under synthetic names — rejected: two namespace conventions for one mechanism; (H3) reuse CALL's `_bind_child_inputs` leaf-name rule: the authored plan declares INPUT placeholders (G.goal, C.constraints) and the coordinator overwrites them with the resolved delegate arguments by leaf name — chosen: zero new machinery, and the deterministic fixed sample plan echoes the committed goal without knowing any run identity.
Outputs: H.theses = the three candidates with H3 selected.
Evidence: coordinator.py `_bind_child_inputs`; tests/test_delegate.py::test_delegate_end_to_end_authors_child_run_and_adopts asserts the bound value.

## step.calculate
Status: succeeded
Inputs: G.plan, E.findings
Actions: Pinned the numeric invariants: max_steps default 6, hard cap 12 (requested values above the cap clamp to 12; non-integer or < 1 is INVALID_INPUT); one child run per delegate invocation; one CHILD_PLAN_AUTHORED event per accepted-or-rejected authoring attempt (recorded before validation); the parent's state version bumps exactly once per delegate step (the adoption batch); CHILD_PLAN_AUTHORED carries no delta so it never moves the version itself; protocol-call depth for the transitive no-recursion walk stays bounded by validation's existing depth-8 rule.
Outputs: F.metrics = {"default_max_steps": 6, "hard_cap_steps": 12, "state_bumps_per_delegate": 1, "plan_events_per_authoring": 1}.
Evidence: src/tikhon/runtime/coordinator.py DELEGATE_* constants; tests/test_delegate.py::test_max_steps_default_is_six_and_hard_cap_is_twelve.

## step.compare / step.rank / step.challenge / step.choose
Status: succeeded
Inputs: H.theses, C.done / V.compared / H.theses, E.findings / R.ranked, V.challenge
Actions: Compared H3 against H1/H2 on the replay dimension: H3 keeps the authored text the ONLY input to the child run (declarations + leaf-name binding), so the recorded plan text plus the recorded DISPATCHED args replay byte-identically; H1/H2 make replay depend on serialization choices outside the record. Challenged H3 for the conditional-DO and PAR-branch positions: delegate stays a plain invocation command, so PAR-branch DO lines and IF-embedded DO lines resolve arguments exactly like any other command — but only the sequential plan loop executes the authoring flow, and delegate programs force that loop.
Outputs: V.compared, R.ranked, V.challenge, D.choice = H3 (leaf-name binding via _bind_child_inputs).
Evidence: coordinator.py `_uses_delegate`; tests/test_delegate.py.

## step.remember / step.recall
Status: succeeded
Inputs: D.choice / K.record
Actions: Recorded the lesson (key "issue25.runtime_plans": authored plans bind inputs by leaf name and replay from the recorded artifact) and read it back.
Outputs: K.record, K.recalled.
Evidence: demo verification run (stub harness records the lesson in-run; the real KnowledgeBase key grammar rejects dotted keys — pre-existing demo convention shared with issue-20's sealed program).

## step.solve / step.prove
Status: succeeded
Inputs: G.goal / C.done
Actions: Formalized the delegate flow as a bounded state machine (author -> record -> validate -> bind -> execute child -> adopt, every rejection exiting through the standard atomic failure path) and checked the contract invariants against it: no adoption without a terminal-succeeded child; no SUCCEEDED without adoption nodes; no CHILD_PLAN_AUTHORED after the first for the same invocation; replay == record.
Outputs: U.solution, A.proof.
Evidence: tests/test_delegate.py (10 tests, all green); audit clean on succeeded, failed, and crashed-then-resumed trees.

## step.review / step.design
Status: succeeded
Inputs: ART.sources / V.review
Actions: Reviewed the flow against issue #25's proposed resolution line by line: explicit model invocation producing a program artifact (the worker reply IS the artifact), parse/validate/seal-like/pin before dispatch (CHILD_PLAN_AUTHORED + bound name), same lineage/namespaces/adoption/budgets as static CALL (child machinery reused verbatim), typed diagnostics for invalid plans (VALIDATION_FAILED payloads carry failure_kind + plan_digest + detail), bounded authoring charged to the root budget (delegate dispatch holds a budget slot like any worker call; the child inherits the gate), recovery reuses the accepted artifact and recorded execution handle (resume reads CHILD_PLAN_AUTHORED and the terminal child). Designed the minimal diff: zero syntax changes, delegate dispatched as a normal command.
Outputs: P.design = the implementation design.
Evidence: /tmp/issue25.md resolution list; src/tikhon/worker_adapter.py delegate prompt section.

## step.patch / step.test / step.check
Status: succeeded
Inputs: P.design / ART.patch / V.tests
Actions: Applied the patch across the six allowed source files and wrote tests/test_delegate.py. Test matrix: end-to-end author->record->child->adoption (with ledger/namespace isolation, digest formula pinned independently, audit clean); oversized plan -> FORMALIZATION atomic failure with recorded digest and no child run; default/hard-cap step bounds; nested delegate in the authored plan rejected; malformed plan -> atomic failure with digest recorded; delegate hidden inside a CALLed protocol rejected by the transitive walk; budget max_child_depth 0 blocks the delegate child; non-mapping worker reply -> INVALID_INPUT with no recorded artifact; replay identity after reopen (state, child state, and recorded payload identical; already-terminal resume); crash during delegate resumes with the recorded plan and never re-asks the worker (flip-flop worker proves it).
Outputs: ART.patch, V.tests = 10/10 green; full suite 741 passed (725 baseline + 16 new).
Evidence: python3 -m pytest -q -> 741 passed.

## step.report / step.verify
Status: succeeded
Inputs: V.verdict / G.goal, V.tests
Actions: Rendered the run report (solution.md + evaluation.json) and verified the original acceptance conditions: runtime-authored plans execute and return validated outputs (end-to-end test); invalid or over-budget plans cannot dispatch and emit actionable diagnostics (atomic-failure tests); nested dynamic delegation has observable lineage and respects root limits (no-recursion + depth-cap tests); replay pins the exact accepted artifact (reopen + crash-resume tests); the sealed demo program demonstrates the protocol run (stub-worker execution: terminal succeeded, 200 events, audit clean).
Outputs: ART.report, V.result, and this WORKLOG/solution.md/evaluation.json.
Evidence: python3 /var/tmp/opencode/issue25_verify.py -> terminal_status: succeeded, audit_ok: True; seal re-verification b64c4e8c... after all source edits (program.think md5 33e001fa24240446cdefc6dff6f69128 unchanged since seal time).
