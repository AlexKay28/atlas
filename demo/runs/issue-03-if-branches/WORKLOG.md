# WORKLOG — issue-03-if-branches

Sealed program: `program.think` (seal digest in `seal.txt`, computed before any source edit).
Digest: `e039349fee95f52648bc5d4b52c2eaf744176a0ceb9808d9be94b1effe8fc0bd`

## step.frame

Status: completed
Inputs: G.goal (issue #3 statement)
Actions: Framed the work as a grammar-plus-runtime feature: the reserved `IF`
keyword becomes a single-line deterministic conditional `IF <expr> <statement>`
where `<statement>` is exactly one STOP, RETURN, or a full `step.<id>: DO ...`
invocation line. Block forms (ELSE, ELSE IF) stay out of scope and are rejected
with the clear "unsupported control construct ELSE" ParseError.
Outputs: G.plan
Evidence: demo/runs/issue-03-if-branches/program.think (sealed before edits)

## step.locate

Status: completed
Inputs: G.plan
Actions: Located the code sites: `IF` sits in `_UNSUPPORTED` in
`src/tikhon/syntax/parser.py` (line ~58) so every IF line is rejected at
parse; statement models live in `src/tikhon/syntax/model.py`; the coordinator
drives a plan of invocation entries only (`_build_plan`/`_drive_plan` in
`src/tikhon/runtime/coordinator.py`) and handles bare RETURN/STOP terminals in
a post-loop scan; reference Program B (docs/spec/04-completeness.md) needs
`IF V.tests.status != "passed" STOP failed(V.tests)` flattened onto one line.
Outputs: E.sites
Evidence: repository inspection recorded in this worklog before edits

## step.design

Status: completed
Inputs: E.sites
Actions: Designed the change set: frozen `Conditional(condition, statement,
line)` model node; parser-side condition grammar (ref ==/!= JSON literal,
count(ref) with == != < <= > >=, left-associative AND/OR, prefix NOT,
parentheses and ELSE rejected) with the embedded statement parsed by the
existing STOP/RETURN/invocation parsers; `validate_program` checks condition
refs against the available set at the conditional's source position (declared
INPUT or an earlier step's target) and enforces the pragmatic rule that an
IF DO conditional appears after every unconditional invocation line;
coordinator appends conditional-DO invocations to the plan with their
condition attached (task created lazily only when the condition fires, so
false branches create no ledger tasks), evaluates STOP/RETURN conditionals at
their source anchor after the preceding invocation commits, and reuses the
existing terminal handling (reason resolution, unreached-task cancellation)
for fired STOP/RETURN; canonical JSON serializes conditionals without source
lines so pre-IF programs seal byte-identically.
Outputs: P.design
Evidence: this worklog + solution.md grammar section

## step.patch

Status: completed
Inputs: P.design
Actions: Implemented the change set. Grammar: removed IF from `_UNSUPPORTED`,
added the condition scanner (`_ConditionScanner` + `parse_condition`), the
IF-line parser (`_parse_conditional_line` reusing the extracted
`_parse_invocation_text` for embedded DO lines), the ELSE rejection, and the
frozen `Conditional` model node serialized into canonical JSON without
source lines. Validation: `_validate_invocation_statement` extracted and
shared with embedded DO invocations (conditional targets checked for
duplicates but never added to the available set); condition refs validated
at the conditional's source position with the spec's immutable field
selection (longest committed prefix + trailing field path); IF-DO-after-
all-unconditional-invocations rule enforced. Coordinator: conditional-DO
invocations are plan entries carrying their condition with lazily created
ledger tasks; STOP/RETURN conditionals are source-anchored and evaluated by
`_run_conditionals` after the preceding invocation commits (anchor 0 before
the loop, anchor len(plan) after it); fired terminals reuse the extracted
`_terminal_stop`/`_terminal_return` handling and cancel unreached tasks;
`evaluate_condition` evaluates the AST purely over committed values with
JSON-strict equality.
Outputs: ART.patch
Evidence: git-visible edits to src/tikhon/syntax/{model,parser,__init__}.py,
src/tikhon/runtime/coordinator.py, tests/test_syntax.py,
tests/test_coordinator.py

## step.check

Status: completed
Inputs: ART.patch, C.behavior
Actions: Ran `python3 -m pytest -q`; full suite green (baseline 484 passed;
final 540 passed including 29 new issue-#3 tests and the concurrent issue-#8
wave's tests). Also smoke-tested end to end through the repo sources: lint,
seal, and run of a Program-B-style program (failed check -> STOP with reason
payload; passed check with blocking review -> the IF-DO branch executed the
full invocation lifecycle and committed its node).
Outputs: V.tests
Evidence: final test run output reported in solution.md / evaluation.json

## step.verify

Status: completed
Inputs: V.tests
Actions: Verified every acceptance criterion of issue #3 against the tests
and the sealed program; confirmed program.think and seal.txt predate all
source edits (program.think 19:21:22, parser.py first edit 19:30:49) and
that the pre-IF demo seal digest still reproduces byte-identically after all
edits; no prohibited files touched by this run; no git commit made.
Outputs: V.result
Evidence: evaluation.json acceptance checklist

