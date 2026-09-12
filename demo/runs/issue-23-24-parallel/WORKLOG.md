# WORKLOG — issue-23-24-parallel

Seal: 5f166a324a93bd67faabd2f35a473f227f90923e13cfb07cfd7868b8d470669c
Program: demo/runs/issue-23-24-parallel/program.think (linted valid and sealed 2026-09-12T17:42Z before any source edit; plain DO steps over all 22 registered commands plus one standalone CALL protocol.framing line; the issues' proposed branch/PAR syntax appears nowhere in the sealed program by design — the sealed program is the plan of record, not a demo of the syntax being added). Re-sealed after all source edits: identical digest. The sealed program was executed through the runtime with stub handlers into run.sqlite (210 parent events, 38 child events for issue-23-24-parallel:inv-22, both runs audit clean, ledger 23/23 completed).

Baseline: `python3 -m pytest -q` = 687 passed (unmodified).

---

## Issue #23 — Branch workspaces, resource claims, explicit artifact merge

### step.frame (#23)
Status: succeeded
Inputs: /tmp/issue23.md, epic #27 step 4 tail ("then heterogeneous PAR; establish effect/workspace isolation before concurrent editing")
Actions: Framed #23 as three layers to land BEFORE #24: (1) branch workspaces — an effectful command inside any branch (PAR branch or scatter candidate) writes into `<workspace_root>/branches/<branch_id>/` via the existing `_workspace_root` injection; read-only dispatches keep the main root; (2) `src/tikhon/claims.py` — an in-process `ResourceLedger` with exclusive `claim`/`release`, wired without new syntax (branch effectful dispatches claim `workspace:<branch identity>`, the merge claims `merge:<run_id>`, DISPATCHED payloads annotated with `resource_claims` — no new event types); (3) an explicit deterministic artifact merge after every join that integrates disjoint branch artifacts and fails the run atomically on a cross-branch path collision.
Outputs: G.plan = claims.py -> parser validation -> coordinator branch plumbing -> merge -> tests/test_claims.py.
Evidence: /tmp/issue23.md; baseline suite 687 passed.

### step.locate (#23)
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located the injection points: coordinator effectful-injection sites (sequential drive plain-invocation path, scatter candidate path, frontier path — the latter needs nothing because PAR/scatter programs never drive the frontier); registry contract lookup `_effectful_commands()` (durable writes: edit=IRREVERSIBLE_WRITE, remember=REVERSIBLE_WRITE) as the effect-class source of truth; `registry.resolve(name).effect_class`; the merge's natural home after a join (gather entry terminal batch, PAR barrier); resume's task-position alignment (`_resume_existing_run` zips task ids positionally against plan entries, which PAR entries must join without a block task).
Outputs: E.sites = the anchor points above.
Evidence: src/tikhon/runtime/coordinator.py (injection sites), src/tikhon/registry/enums.py, src/tikhon/runtime/tasks.py transition rules.

### step.read (#23)
Status: succeeded
Inputs: E.sites
Actions: Read the touched regions in full: the `_workspace_root` injection contract (handler `_workspace_for`), TaskLedger transition legality (task_completed requires IN_PROGRESS; start->complete can be batched atomically), the store's batch validation (dup-SUCCEEDED per invocation id), audit's five invariant checks, resume's positional task mapping and extra-task guard.
Outputs: ART.sources = the read sources.
Evidence: files in C.scope.

### step.analyze (#23)
Status: succeeded
Inputs: ART.sources
Actions: Analyzed the correctness constraints: (a) ledger strictness — PAR branches run concurrently, so branch tasks must NOT be IN_PROGRESS simultaneously under the strict ledger; the established scatter-entry pattern applies: branch tasks stay PENDING while their child runs execute, and start+complete commit in one batch at completion; (b) claim scoping — simple `par<k>`/`cand<k>` ids are ambiguous across multiple blocks, so the claim resource embeds the run-scoped branch identity (`workspace:<run_id>:par<k>`, `workspace:<run_id>:inv-K.cand<k>`) while the DIRECTORY nests hierarchically under the enclosing branch (`<base>/branches/<branch_id>`); (c) merge collision semantics — an ART.* node's string value is a workspace-relative path; the same relative path produced by two different branches is the issue's "overlapping patches produce an explicit conflict" case and must fail the run atomically, never last-writer-wins; (d) merge claims must release on every path (finally), and the merge is workspace-gated so pre-#23 programs (no workspace declared, or no ART targets) are untouched; (e) "reads still see the main workspace root" = read-only dispatches are never re-rooted (only effectful commands receive `_workspace_root` at all).
Outputs: E.findings = the constraint list above.
Evidence: this analysis; the #23 issue body.

### step.decompose (#23)
Status: succeeded
Inputs: G.plan
Actions: Split into six subtasks: (1) src/tikhon/claims.py (ResourceLedger); (2) coordinator claims threading (execute() mints one run-scoped ledger; keyword-threaded like the #22 gate); (3) branch workspace injection in the sequential drive + scatter candidates; (4) `_merge_branch_artifacts` (claim -> collision check -> copy -> accounting) hooked into the gather entry; (5) resume alignment accepting branch task texts; (6) tests/test_claims.py.
Outputs: G.subgoals = the six subtasks.
Evidence: final git status matches the allowed file list.

### step.hypothesize (#23)
Status: succeeded
Inputs: G.goal, E.findings
Actions: Candidate designs for merge accounting: (H1) a new MERGE event type — rejected: the issue prefers no new event types and PAR_JOINED (#24) plus CHILD_ADOPTED payloads already give the accounting homes; (H2) fold the accounting into the gather's SUCCEEDED payload (`"merge": {"artifacts": [...]}`) and into per-branch CHILD_ADOPTED payloads + PAR_JOINED for PAR — chosen: zero new event types, deterministic payload shapes; (H3) branch-scoped node renames in the parent (`ART.left.par1`) — rejected: rename merging silently rewrites program-level names; the explicit mapping is the adoption itself. For claims: (H4) claim failure blocks with retries — rejected: a hang is a worse failure mode than a loud error, and within one block branch identities are unique so contention cannot arise; the ledger test proves the serialization property at the primitive level.
Outputs: H.theses = the candidates with H2 chosen.
Evidence: tests/test_claims.py accounting assertions.

### step.calculate (#23)
Status: succeeded
Inputs: G.goal, E.findings
Actions: Pinned the numeric/identity invariants: branch dir `<base>/branches/<branch_id>` with `par<k>`/`cand<k>` ids (nested blocks nest under the enclosing branch dir); claim resources `workspace:<run_id>:par<k>`, `workspace:<run_id>:<cand-inv-id>`, `merge:<run_id>`; owner = `<run_id>:<invocation_id>` of the dispatching invocation; DISPATCHED annotation key `resource_claims` present only when claims are actually held (keeps non-branch event streams byte-identical).
Outputs: F.metrics = the identity scheme above.
Evidence: src/tikhon/runtime/coordinator.py helpers (`branch_workspace_dir`, claim sites).

### step.compare (#23)
Status: succeeded
Inputs: H.theses, C.done
Actions: Compared merge timing options: merge inside the gather entry before the terminal batch (scatter) and inside the PAR barrier before the entry-terminal batch (PAR) — both keep the join atomic (accounting rides the join's own commit) and make resume re-derive the merge deterministically from committed branch state.
Outputs: V.compared = the chosen timing.
Evidence: `_execute_gather_entry`, `_execute_par_entry` merge sites.

### step.rank (#23)
Status: succeeded
Inputs: V.compared, C.done
Actions: Ranked: (1) claims.py, (2) claims threading, (3) branch workspace injection, (4) scatter merge, (5) resume guard, (6) test_claims.py. Full suite re-run green after each.
Outputs: R.ranked = the order above.
Evidence: session history.

### step.challenge (#23)
Status: succeeded
Inputs: H.theses, E.findings
Actions: Attacked the design: (C1) the merge could copy stale leftovers from reused `cand<k>` dirs across sequential blocks — challenged: the merge copies only paths declared in the joining block's own ART values, so leftovers are never integrated (documented limitation: dirs are reused, contents per-block); (C2) a merge failure must not leak the `merge:<run_id>` hold — release in `finally` (asserted by a spy test); (C3) a join-level merge failure has no owning branch — attributing it to one branch would be false; instead the FAILED event carries the PAR entry's positional id with the `par` payload marker (audit exempts exactly marked events; the pre-existing `_fail_run` path shows the invocation-less-failure shape); (C4) live demonstration of the failure mode this issue prevents: an early dogfood execution of the sealed program ran its `edit` step with no declared workspace root and the stub handler wrote relative to the repository root, clobbering the untracked src/tikhon/claims.py mid-session — restored by hand and re-verified; the re-run declared a scratch workspace.
Outputs: V.challenge = the four attacks and resolutions.
Evidence: tests/test_claims.py (spy test, collision tests); session history.

### step.choose (#23)
Status: succeeded
Inputs: R.ranked, V.challenge
Actions: Chose: ResourceLedger (exclusive, strict re-claim rejection, holder introspection); claims threaded as keywords like the budget gate; branch dirs nested under the enclosing branch root; merge = claim -> cross-branch collision check in branch/target order -> file copy -> accounting list; DISPATCHED annotation only when held; workspace-gated merge for scatter (back-compat), always-computed for PAR (new construct).
Outputs: D.choice = the architecture above.
Evidence: src/tikhon/claims.py, src/tikhon/runtime/coordinator.py.

### step.remember (#23)
Status: succeeded
Inputs: D.choice
Actions: Recorded durable lessons: (1) an effectful dispatch without a declared workspace root can clobber the working tree (lived it — see step.challenge C4); (2) strict ledgers and concurrency mix via the scatter-entry PENDING pattern; (3) joins need explicit conflict semantics, not last-writer-wins.
Outputs: K.record = the lessons.
Evidence: claims.py docstring note; WORKLOG.

### step.recall (#23)
Status: succeeded
Inputs: K.record
Actions: Applied the lessons: the dogfood re-run declared a scratch workspace; the PAR entry keeps branch tasks PENDING until their completion batch; the merge fails loudly on collisions.
Outputs: K.recalled = the applied lessons.
Evidence: coordinator code; this WORKLOG.

### step.solve (#23)
Status: succeeded
Inputs: G.goal, V.challenge
Actions: Implemented: `src/tikhon/claims.py` (ResourceLedger with claim/release/holder, threading.Lock, argument validation); coordinator claims minted in `execute()` and threaded through `_execute_program`/`_drive_plan`/`_resume_existing_run`/`_execute_call_child`; branch workspace injection at the sequential-drive and scatter-candidate dispatch sites (root = branch_root or workspace_root; claim held for exactly the handler's duration, released in `finally`); `_merge_branch_artifacts` hooked into the gather entry (workspace-gated) with `"merge"` accounting in the join SUCCEEDED payload; resume's extra-task guard accepts `PAR branch <k>: ...` texts (added for #24's ledger, landed here).
Outputs: U.solution = the implementation above.
Evidence: src/tikhon/claims.py; src/tikhon/runtime/coordinator.py.

### step.prove (#23)
Status: succeeded
Inputs: C.done, U.solution
Actions: Proved every #23 clause by a named test in tests/test_claims.py (15 tests): claim exclusivity + release semantics (test_claim_is_exclusive_and_release_frees_the_hold); independent resources concurrently (test_independent_resources_are_claimed_concurrently); serialization across threads (test_claims_serialize_conflicting_work_across_threads); argument validation; PAR branches editing the same relative path produce separate branch-dir files, parent root untouched, merge sees both and refuses (test_par_branches_editing_the_same_relative_path_stay_isolated); disjoint PAR artifacts integrate with full accounting (test_disjoint_branch_artifacts_integrate_into_the_parent_workspace); scatter candidate isolation (test_scatter_candidates_get_isolated_branch_workspaces) and disjoint integration (test_scatter_disjoint_candidate_artifacts_integrate); claim wiring + annotation (test_effectful_branch_dispatches_claim_and_annotate); top-level dispatch unclaimed/unannotated (test_top_level_effectful_dispatch_stays_unclaimed_and_unannotated); merge-claim release on failure (test_merge_failure_releases_the_merge_claim); collision atomic failure without partial publication (test_collision_fails_the_run_atomically_without_partial_publication); no-branch behavior unchanged (test_no_branch_program_behavior_unchanged); custom commands with unknown effect metadata treated as undeclared — no injection, no claim (test_custom_command_without_registry_effect_metadata_is_undeclared); shared KB writes from branches recorded and claimed via the durable-write effect class (test_shared_kb_writes_from_branches_are_recorded_and_isolated).
Outputs: A.proof = the test-to-clause mapping above.
Evidence: tests/test_claims.py (15 passed); full suite 725 passed.

### step.review (#23)
Status: succeeded
Inputs: U.solution, A.proof
Actions: Reviewed the diff against the hard constraints: only the allowed files changed (git status verified); registry/, budgets.py, cli.py, envelope.py, resume.py, worker_adapter.py, memory.py untouched; audit.py touched ONLY for the PAR false-positive fix (#24 scope, verified by diff).
Outputs: V.review = the constraint checklist, clean.
Evidence: git status/diff.

### step.design (#23)
Status: succeeded
Inputs: V.review
Actions: Summarized the #23 design for solution.md (three layers: branch workspaces, claims, explicit merge).
Outputs: P.design = solution.md section for #23.
Evidence: solution.md.

### step.patch (#23)
Status: succeeded
Inputs: P.design
Actions: Applied the source changes within scope.
Outputs: ART.patch = the applied diff.
Evidence: git status --short.

### step.test (#23)
Status: succeeded
Inputs: ART.patch
Actions: Ran the full suite (725 passed = 687 baseline + 38 new) and the two new files 5 consecutive times for flake resistance.
Outputs: V.tests = 725 passed; 5x stable; seal digest unchanged.
Evidence: pytest output; seal.txt.

### step.check (#23)
Status: succeeded
Inputs: V.tests
Actions: Checked the #23 acceptance list item by item (evaluation.json); all pass.
Outputs: V.verdict = #23 acceptance satisfied.
Evidence: evaluation.json.

### step.report (#23)
Status: succeeded
Inputs: V.verdict
Actions: Produced the #23 sections of solution.md and evaluation.json.
Outputs: ART.report = the artifacts.
Evidence: the files themselves.

### CALL protocol.framing (#23/#24 shared)
Status: succeeded
Inputs: G.goal, C.scope
Actions: Executed the sealed CALL protocol.framing(request = G.goal, scope = C.scope) as an isolated child run (run_id issue-23-24-parallel:inv-22 in demo/runs/issue-23-24-parallel/run.sqlite) per the program; E.context and V.analysis adopted onto the CALL targets.
Outputs: E.context = framing analysis; V.analysis = adopted verdict.
Evidence: run.sqlite (210 parent events, 38 child events, CHILD_ADOPTED {E.context, V.analysis}, both runs audit clean, ledger 23/23 completed).

### step.verify (#23)
Status: succeeded
Inputs: G.goal, V.tests
Actions: Final verification: baseline 687 -> 723 with zero existing tests modified; seal re-verified identical post-edit; scope cross-checked; #24 acceptance transcribed (see the #24 section below).
Outputs: V.result = both issues implemented, sealed, tested, reported.
Evidence: this WORKLOG, solution.md, evaluation.json, seal.txt.

---

## Issue #24 — PAR blocks with an explicit barrier (layered on #23)

### step.frame (#24)
Status: succeeded
Inputs: /tmp/issue24.md, #23 foundations
Actions: Framed #24 as: grammar (`PAR MAX n` + 2+ indented branch lines, each a full `step.<id>: DO ...` line or a `CALL protocol.name(...) -> targets` line, terminated by a matching-dedent `BARRIER` optionally declaring targets); deterministic branch ids `par<k>` in source order; runtime = branches as isolated child-scoped runs `<run_id>:par<k>` dispatched concurrently (pool capped at min(MAX, branch count), further capped tree-wide by the budget semaphore); all-success barrier adopting branch outputs (CHILD_ADOPTED per branch, one PAR_JOINED, one entry-terminal SUCCEEDED committing all adopted targets atomically in branch order); any branch failure = standard atomic failure with sibling cancellation.
Outputs: G.plan (continued) = model -> parser -> events.PAR_JOINED -> coordinator PAR entry -> tests/test_par.py.
Evidence: /tmp/issue24.md.

### step.locate (#24)
Status: succeeded
Inputs: G.plan
Actions: Located the integration points: syntax/model.py (Par, ParBranch), parser (block parse + validation + canonical seal), events.py (PAR_JOINED), coordinator (_build_plan one entry per PAR block; _collect_anchors counts it; _create_plan_tasks skips it — one task per branch, no block task; _drive_plan dispatches it; _resume_existing_run excludes PAR entries from static task positions and accepts branch task texts as extras; par<k> ids excluded from the positional success set), audit.py (false-positive fix for the block-task-less PAR commit).
Outputs: E.sites = the anchor points above.
Evidence: git diff.

### step.read (#24)
Status: succeeded
Inputs: E.sites
Actions: Read the scatter/candidate machinery as the template for per-branch task creation and the CALL child-run machinery as the template for branch child runs (`_execute_call_child` extracted into `_execute_program_child`, shared by DO branches via a synthetic single-invocation program whose INPUT declarations carry the dispatch-resolved arguments).
Outputs: ART.sources = the read sources.
Evidence: coordinator diff.

### step.analyze (#24)
Status: succeeded
Inputs: ART.sources
Actions: Analyzed: (a) single-writer discipline — the PAR pool executes child runs only; every parent-side commit happens on the coordinator thread, mirroring the #21 frontier; (b) barrier semantics — the entry blocks until every branch is terminal; adoption is all-success; a failed branch commits FAILED(par<k>) + task settlement + cancellation of every unsettled sibling task + RUN_FINISHED in one atomic batch, in-flight child runs drain and their results are discarded uncommitted; (c) atomic publication — branch targets commit in ONE entry-terminal SUCCEEDED delta (branch order), matching the issue's "atomically published declared outputs"; (d) determinism — completion order may interleave branch events, but the terminal delta order, final projection, and replay are deterministic (proven by a permutation test); (e) validation teeth — branch lines validate against the pre-PAR namespace so sibling-output reads fail ("used before definition"), duplicate parent output targets fail, and a declared BARRIER list must equal the union of branch targets; (f) REVISE/RETIRE rejected on branch lines (corrections address parent-namespace nodes; branch state is isolated); (g) nested PAR is expressed by a CALL branch whose protocol contains its own PAR block, bounded by the budget's colon-count child-depth cap; (h) resume — PAR entries carry no block task, so resume aligns tasks with non-PAR plan positions ("static positions"), accepts branch task texts as ledger extras, excludes par<k> ids from the positional success set, and re-drives a crashed PAR entry by skipping branches whose tasks are already completed (re-reading their committed child state).
Outputs: E.findings = the constraint list above.
Evidence: this analysis.

### step.decompose (#24)
Status: succeeded
Inputs: G.plan
Actions: Split into five subtasks: (1) model + parser + validation + canonical seal; (2) events.py PAR_JOINED; (3) coordinator: plan/anchor/task-text plumbing, `_execute_par_entry`, `_execute_par_branch`, `_build_branch_program`, `_resolve_branch_arguments`, `_adopt_branch_nodes`, `_par_branch_task_ids`; (4) resume adaptations; (5) audit false-positive fix + tests/test_par.py.
Outputs: G.subgoals = the five subtasks.
Evidence: git diff; tests/test_par.py.

### step.hypothesize (#24)
Status: succeeded
Inputs: G.goal, E.findings
Actions: Candidate designs for branch execution: (H1) branches execute inline in the parent run with scoped node names — rejected: no state isolation; two branches producing the same target name would need renaming (silent rewriting); (H2) branches as isolated child runs `<run_id>:par<k>` reusing the #20 child-run machinery — chosen: state isolation for free, deterministic run ids, resume/read-back for free; (H3) barrier as a separate plan entry — rejected: the BARRIER terminates the PAR block syntactically; one plan entry keeps anchor indexing and failure attribution simple. For DO branches: (H4) run the invocation directly in the parent — rejected (see H1); (H5) synthetic single-invocation child program with dispatch-resolved arguments bound as INPUT declarations — chosen.
Outputs: H.theses = the candidates with H2/H5 selected.
Evidence: coordinator implementation.

### step.calculate (#24)
Status: succeeded
Inputs: G.goal, E.findings
Actions: Pinned the numbers: branch ids par1..parN in source order; branch run id `<parent_run_id>:par<k>`; parent-side branch invocation id `par<k>`; branch task text `PAR branch <k>: <summary>`; pool size max(1, min(MAX, branch count)); entry-terminal SUCCEEDED instruction id `par.inv-<K>`; CHILD_ADOPTED/PAR_JOINED payloads carrying branch statuses, adopted maps, artifact accounting, and the declared targets.
Outputs: F.metrics = the identity scheme above.
Evidence: coordinator helpers (`par_branch_invocation_id`, `par_branch_run_id`, `par_branch_task_text`).

### step.compare (#24)
Status: succeeded
Inputs: H.theses, C.done
Actions: Compared adoption shapes: per-branch SUCCEEDED deltas (CALL-style) vs one entry-terminal delta — chose the single terminal delta: one atomic publication of all declared outputs at the barrier, no par<k> ids in the SUCCEEDED success set (resume prefix invariant untouched), and a clean crash window (crash_hook after all adoptions, before the terminal batch; resume re-derives everything from committed branch state).
Outputs: V.compared = the chosen shape.
Evidence: `_execute_par_entry` terminal batch.

### step.rank (#24)
Status: succeeded
Inputs: V.compared, C.done
Actions: Ranked: (1) grammar+validation, (2) events, (3) runtime entry, (4) resume, (5) audit fix, (6) tests. Suite green after each.
Outputs: R.ranked = the order above.
Evidence: session history.

### step.challenge (#24)
Status: succeeded
Inputs: H.theses, E.findings
Actions: Attacked: (C1) the strict ledger would reject concurrent branch task_starts — resolved with the PENDING-until-completion batch pattern (the scatter-entry precedent); (C2) the audit's invocation-bound task_id requirement fires on the PAR entry-terminal SUCCEEDED (no block task by design) — resolved with the scoped false-positive fix in audit.py (marked "par" payloads only; instruction_id still required); (C3) a join-level merge failure initially finished the run failed with no FAILED event (truthfulness violation, the same shape as the pre-existing `_fail_run` path) — resolved by emitting the FAILED on the entry's positional id with the `par` marker; (C4) the framing protocol's arg contract (CALL targets must be the protocol's RETURN refs) initially tripped the demo programs — a test-authoring lesson, not a code change; (C5) branch CALL targets rename nothing: a CALL branch adopts under the CALL's targets exactly like a top-level CALL.
Outputs: V.challenge = the five attacks and resolutions.
Evidence: audit.py diff; tests/test_par.py.

### step.choose (#24)
Status: succeeded
Inputs: R.ranked, V.challenge
Actions: Chose the final architecture: one plan entry per PAR block; per-branch child runs; completion-processed adoptions on the main thread; single entry-terminal delta; PAR_JOINED recording branch statuses + merged artifacts; barrier target declaration pinned to the branch union; MAX as the pool ceiling bounded by the budget gate.
Outputs: D.choice = the architecture above.
Evidence: src/tikhon/syntax/{model,parser}.py, src/tikhon/runtime/{events,coordinator}.py.

### step.remember (#24)
Status: succeeded
Inputs: D.choice
Actions: Recorded durable lessons: (1) a parallel construct on a strict ledger keeps its ledger tasks PENDING until settlement; (2) atomic publication = one terminal delta in deterministic order, not per-branch commits; (3) new block constructs need their resume story decided up front (task alignment, extra-task guards, success-set exclusions).
Outputs: K.record = the lessons.
Evidence: this WORKLOG; code docstrings.

### step.recall (#24)
Status: succeeded
Inputs: K.record
Actions: Applied the lessons in `_execute_par_entry` and `_resume_existing_run`.
Outputs: K.recalled = the applied lessons.
Evidence: coordinator code.

### step.solve (#24)
Status: succeeded
Inputs: G.goal, V.challenge
Actions: Implemented: Par/ParBranch models; `_parse_par_block` (branch lines + terminating BARRIER, stray-BARRIER rejection); `_validate_par_statement` (sibling reads, duplicate targets, parent collisions, barrier union, REVISE/RETIRE ban, CALL contract per branch); canonical seal (`"kind": "par"`); EventType.PAR_JOINED; `_execute_par_entry` (branch task creation by text, depth-capped concurrent dispatch, READY/DISPATCHED per branch, completion-processed CHILD_ADOPTED + task settlement, drain-and-discard on failure, merge, PAR_JOINED + entry-terminal SUCCEEDED); `_execute_par_branch` (CALL branch = protocol child run; DO branch = synthetic single-invocation child program); resume adaptations (static task positions, branch-task extras accepted, par<k> success-set exclusion, completed-branch skip on re-drive); audit false-positive fix; protocol validation counting PAR blocks as executable statements.
Outputs: U.solution = the implementation above.
Evidence: src/tikhon/syntax/model.py, src/tikhon/syntax/parser.py, src/tikhon/runtime/events.py, src/tikhon/runtime/coordinator.py, src/tikhon/audit.py.

### step.prove (#24)
Status: succeeded
Inputs: C.done, U.solution
Actions: Proved every #24 clause by a named test in tests/test_par.py (23 tests): grammar/canonical seal (test_par_block_parses_heterogeneous_branches_and_barrier, test_par_seals_deterministically_and_canonically, test_pre_par_programs_seal_byte_identically); validation rejections (sibling reads, duplicate targets, barrier subset, parent collision, REVISE/RETIRE, <2 branches, missing BARRIER, stray BARRIER, MAX<1); heterogeneous DO+CALL execution with adoption + audit (test_heterogeneous_do_and_call_branches_execute_and_combine); ledger shape (test_ledger_has_one_task_per_branch_and_no_block_task); barrier waits (test_barrier_waits_for_the_slow_branch_before_adopting — neither output adoptable while the slow branch holds the barrier); completion-order permutations (test_completion_order_permutations_preserve_the_final_state); atomic failure + sibling cancellation (test_branch_failure_cancels_sibling_and_fails_run_atomically); MAX cap observed (test_max_cap_observed_via_peak == 1, test_branches_overlap_up_to_the_max — a 2-party barrier only met by true overlap); replay identity after reopen (test_replay_identity_after_reopen); workspace isolation inside branches (test_workspace_isolation_active_inside_par_branches); nested PAR + depth bound (test_nested_par_bounded_by_budget_child_depth — default succeeds, max_child_depth=1 fails atomically); non-PAR behavior unchanged (test_non_par_programs_behave_identically).
Outputs: A.proof = the test-to-clause mapping above (23 tests).
Evidence: tests/test_par.py (23 passed); full suite 725 passed.

### step.review (#24)
Status: succeeded
Inputs: U.solution, A.proof
Actions: Reviewed #24's diff against the hard constraints: events.py gained only PAR_JOINED (+ comment); audit.py only the false-positive fix; cli.py/registry//budgets.py/resume.py/envelope.py/worker_adapter.py/memory.py untouched; PAR-resume gaps recorded as protocol deviations rather than resume.py changes.
Outputs: V.review = the constraint checklist, clean.
Evidence: git status/diff.

### step.design (#24)
Status: succeeded
Inputs: V.review
Actions: Summarized the #24 design for solution.md.
Outputs: P.design = solution.md section for #24.
Evidence: solution.md.

### step.patch (#24)
Status: succeeded
Inputs: P.design
Actions: Applied the #24 source changes within scope.
Outputs: ART.patch = the applied diff.
Evidence: git status --short.

### step.test (#24)
Status: succeeded
Inputs: ART.patch
Actions: Full suite 725 passed; tests/test_par.py + tests/test_claims.py stable across 5 consecutive runs; seal digest re-verified identical after all edits.
Outputs: V.tests = 725 passed, 5x stable, digest stable.
Evidence: pytest output; seal.txt.

### step.check (#24)
Status: succeeded
Inputs: V.tests
Actions: Checked the #24 acceptance list item by item (evaluation.json); all pass.
Outputs: V.verdict = #24 acceptance satisfied.
Evidence: evaluation.json.

### step.report (#24)
Status: succeeded
Inputs: V.verdict
Actions: Produced the #24 sections of solution.md and evaluation.json with run_id issue-23-24-parallel.
Outputs: ART.report = the artifacts.
Evidence: the files themselves.

### step.verify (final, #24)
Status: succeeded
Inputs: G.goal, V.tests
Actions: Final pass: seal identical; scope clean; both issue acceptance lists transcribed with evidence; deviations recorded (see evaluation.json protocol_deviations).
Outputs: V.result = session complete.
Evidence: this WORKLOG, solution.md, evaluation.json, seal.txt.
