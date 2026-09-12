# WORKLOG — issue-02-done-validation

Sealed program: `program.think` (seal digest in `seal.txt`, computed before any source edit).
Digest: `0c3260d3f351b32383f553917c99d06d51a662b6f86b3e130dc5ae5c96b92194`

## step.frame

Status: completed
Inputs: G.goal (issue #2 statement)
Actions: Framed the work as truthful validation: DONE predicates attached to
invocations must actually be evaluated by the coordinator, and a failing
predicate must emit `invocation.validation_failed` and run the standard atomic
failure batch instead of unconditionally emitting `VALIDATION_PASSED`.
Outputs: G.plan
Evidence: demo/runs/issue-02-done-validation/program.think (sealed)

## step.locate

Status: completed
Inputs: G.plan
Actions: Located the code sites: `Invocation.done` is parsed as a raw string in
`src/tikhon/syntax/parser.py` (line ~95) but never evaluated;
`src/tikhon/runtime/coordinator.py` emits `VALIDATION_PASSED` unconditionally
after target mapping; `EventType.VALIDATION_FAILED` already exists in
`src/tikhon/runtime/events.py` but is never emitted.
Outputs: E.sites
Evidence: repository inspection recorded in this worklog before edits

## step.read

Status: completed
Inputs: E.sites
Actions: Read docs/spec/01-language-and-state.md ("Deterministic Expressions"):
DONE expressions use infix operators (`==` equality, `IN` membership) over
typed references and JSON literals; regex matching is not defined in the spec,
so the issue's suggested name `matched` is kept for that predicate. Read the
coordinator failure path (`finish_failed_invocation`) and the existing syntax
and coordinator tests.
Outputs: ART.sources
Evidence: spec section "Deterministic Expressions" (docs/spec/01-language-and-state.md)

## step.spec

Status: completed
Inputs: ART.sources
Actions: Extracted the deterministic DONE grammar to implement:
`DONE <ref> == <json-literal>`, `DONE <ref> IN [<json-literal>, ...]`,
`DONE matched(<ref>, "<regex>")`; ref must be one of the step's targets;
evaluation must be pure and deterministic over committed target values.
Outputs: E.findings
Evidence: this worklog + solution.md grammar section

## step.design

Status: completed
Inputs: E.findings
Actions: Designed the change set: structured `DonePredicate` model node
(op/ref/value/line) replacing the raw DONE string; parser-side predicate
parsing with parse-time target-ref validation; `validate_program` re-checks
the target-ref rule; pure evaluator in the coordinator; `VALIDATION_FAILED`
prepended to the existing atomic failure batch via an extended
`finish_failed_invocation`; no changes to cli.py or the registry.
Outputs: P.design
Evidence: this worklog + solution.md

## step.patch

Status: completed
Inputs: P.design
Actions: Implemented parser/model/coordinator changes and the new tests.
Outputs: ART.patch
Evidence: git-visible edits to src/tikhon/syntax/{model,parser}.py,
src/tikhon/runtime/coordinator.py, tests/test_syntax.py,
tests/test_coordinator.py, tests/test_event_store.py

## step.check

Status: completed
Inputs: ART.patch, C.behavior
Actions: Ran `python3 -m pytest -q`; full suite green (baseline 216 passed +
new validation tests).
Outputs: V.tests
Evidence: final test run output reported in solution.md / evaluation.json

## step.verify

Status: completed
Inputs: V.tests
Actions: Verified every acceptance criterion of issue #2 against the tests and
the sealed program; confirmed program.think and seal.txt predate all source
edits; no prohibited files touched; no git commit made.
Outputs: V.result
Evidence: evaluation.json acceptance checklist
