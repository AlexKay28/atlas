# WORKLOG — issue-12-protocol-calls

Seal: bd4df5450292ac433cd8069773022123e70106a20d7c950671f50dc4a5db013f
Program: demo/runs/issue-12-protocol-calls/program.think (linted valid and sealed before any source edit; CALL is deliberately absent because it does not exist in the grammar at seal time)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed issue #12 into four change areas: (1) a Call AST node plus CALL grammar in the parser with protocol-name and argument/target parsing, (2) validate_program contract for protocol existence, argument binding, RETURN-subset targets and acyclic bounded recursion (depth 8), (3) coordinator inline expansion of protocol steps with prefixed ledger tasks and parent-continuing invocation ids, (4) the example protocol protocols/framing.think plus syntax and coordinator tests.
Outputs: G.plan = implement in the order model.py -> parser.py -> syntax/__init__.py -> coordinator.py -> tests, with protocols/framing.think created before tests so validation has a real artifact.
Evidence: issue #12 text; docs/spec/01-language-and-state.md grammar sketch (call = "CALL", protocol, "(", arguments?, ")", "->", targets); docs/spec/03-runtime-and-events.md "Protocol Calls" section.

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located the integration points: parser._UNSUPPORTED already lists CALL (line 31) so the keyword parse path exists as an error; the statement loop dispatches on DONE/RETURN/STOP/step regexes; validate_program walks statements with an `available` ref set; coordinator.execute collects Invocation statements until the first non-Invocation and batches task creation up front; TaskLedger.create_task takes free text so protocol task texts need only a prefix; audit_run requires every invocation-bound event to carry task_id/instruction_id and one RUN_FINISHED, which inline expansion preserves automatically by reusing the per-invocation loop.
Outputs: E.patterns = the anchor points above.
Evidence: src/tikhon/syntax/parser.py:30-32 (_UNSUPPORTED), :95-139 (statement loop), :428-509 (validate_program); src/tikhon/runtime/coordinator.py:235-265 (invocation collection + task batch), :339+ (per-invocation loop); src/tikhon/audit.py:31-45 (_INVOCATION_BOUND_TYPES); tests/test_coordinator.py replay test at line 526.

## step.design
Status: succeeded
Inputs: E.patterns
Actions: Chose the design. Model: frozen dataclass Call(protocol, args, targets, line). Grammar: CALL protocol.<name>(args) -> refs, protocol name = "protocol." + dot-separated [a-z][a-z0-9_]* segments, file = protocols_dir/<rest>.think. Validation: validate_program gains protocols_dir (default protocols/ under cwd); every CALLed protocol must parse and validate (recursively, sharing known_commands); CALL args must resolve like invocation args and exactly cover the protocol INPUT leaf names; CALL targets must be a subset (string equality) of the protocol RETURN refs; recursion rejected via a protocol stack during validation (direct and transitive self-calls) and a depth limit of 8 nested protocol calls. Runtime: coordinator builds a flat execution plan — caller invocations plus, at each CALL, the protocol's invocations appended with task text prefixed "protocol.name:" and invocation ids continuing the parent sequence; the LAST plan entry of each protocol expansion carries a finalize closure committing the protocol RETURN refs to the caller's CALL targets (identity under the subset rule, presence-checked) by merging them into that step's SUCCEEDED delta; failures reuse the existing atomic failure path so pending protocol and caller tasks are cancelled together. Protocol INPUT binding: resolved CALL args replace the protocol's declared INPUT values at expansion time.
Outputs: E.design = the design above, recorded before implementation.
Evidence: this design; cross-checked against docs/spec/03-runtime-and-events.md (child namespace pinned versions are out of scope for the MVP; deterministic loading is required, composite seal hashing is not).

## step.patch
Status: succeeded
Inputs: E.design
Actions: Implemented: model.py gains Call; parser.py removes CALL from _UNSUPPORTED, adds _CALL_RE and the CALL branch in the statement loop, canonical-JSON support for calls, validate_program(protocols_dir=...) with protocol loading, arg/target contract checks, cycle detection and depth limit, plus load_protocol/protocol_file_path helpers; syntax/__init__.py exports Call, load_protocol; coordinator.py gains protocols_dir on SequentialCoordinator, plan-based expansion (invocation collection walks Invocation and Call statements), task-text prefixes, finalize commits, unchanged failure path; tests/test_syntax.py gains the CALL block; tests/test_coordinator.py gains protocol-call execution, ledger, replay, audit and failure tests.
Outputs: P.patch = diffs in src/tikhon/syntax/model.py, src/tikhon/syntax/parser.py, src/tikhon/syntax/__init__.py, src/tikhon/runtime/coordinator.py, tests/test_syntax.py, tests/test_coordinator.py; new protocols/framing.think and demo/runs/issue-12-protocol-calls/.
Evidence: git diff after implementation; sealing protocols/framing.think yields 5bbf9fbab5b863199794ddc5c86152153fb60bacd89f931a6feaf4906412bf80.

## step.check
Status: succeeded
Inputs: P.patch, C.done
Actions: Ran python3 -m pytest -q (full suite): 397 passed (baseline 314; +26 from this issue — 19 syntax tests and 7 coordinator tests — the remainder from the concurrent issue-#9 agent's test_effectful.py and registry tests, all green alongside). Targeted: tests/test_syntax.py 88 passed, tests/test_coordinator.py 53 passed. Re-sealed demo/runs/issue-12-protocol-calls/program.think with the changed code: digest identical to seal.txt (program predates source edits). lint/seal of protocols/framing.think reproduced 5bbf9fbab5b863199794ddc5c86152153fb60bacd89f931a6feaf4906412bf80. Live CLI end-to-end: sealed demo/runs/issue-12-protocol-calls/call-demo.think, ran it via tikhon run (status succeeded, 100%, 6/6 tasks), tikhon audit returned OK, event log shows each protocol step bound to its own task with continuing invocation ids.
Outputs: V.tests = full-suite pass, seal-stability checks, and the CLI run/audit/status evidence above.
Evidence: pytest output "397 passed in 6.14s"; seal outputs identical to seal.txt and to 5bbf9fbab5b863199794ddc5c86152153fb60bacd89f931a6feaf4906412bf80; tikhon run/audit/status transcript for call-demo-1.

## step.verify
Status: succeeded
Inputs: G.goal, V.tests
Actions: Verified every acceptance criterion against evidence: CALL grammar parses and seals (canonical JSON gains a "call" kind); unknown protocol, arg-arity and target-subset violations rejected at validation; direct and transitive self-calls and depth>8 chains rejected via the dependency walk; program calling protocol.framing executes with protocol tasks in the ledger (text prefixed protocol.framing:), caller targets receiving protocol RETURN values, identical replay after reopen, and a clean audit; a failing protocol step fails the caller through the standard atomic failure path (FAILED on the protocol step, remaining protocol and caller tasks cancelled, RUN_FINISHED failed, no false completion); no files outside the allowed set touched; concurrent agent #9 edits (idempotency payload, workspace_root, effectful commands) left intact and green.
Outputs: V.result = all criteria passed; see evaluation.json.
Evidence: tests listed in step.check; git status showing only allowed files modified by this issue plus the concurrent agent's own files.
