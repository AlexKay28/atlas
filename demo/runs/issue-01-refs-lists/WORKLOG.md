# Worklog: issue-01-refs-lists

Seal: `a27d8f0757967d37fb7be7fc7d5429587e5c7c8aa05fc3619dea6bfb3a7005af`

GitHub issue #1: support lists of typed references in arguments, `[E.a, E.b]`.

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to argument parsing/validation and coordinator argument resolution; confirmed baseline `python3 -m pytest -q` = 163 passed before any edits.
Outputs: `G.plan` = parse bracket refs into a list value, validate list refs, resolve lists in the coordinator, keep seals stable.
Evidence: Baseline run output `163 passed in 0.47s`; issue text and `demo/runs/chat-runtime-refactor/program.think` reviewed for protocol format.

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Located the argument parser, the reference-validation walk, and the coordinator resolution site.
Outputs: `E.sites` = parser.py `_parse_argument` (was line 136), parser.py `validate_program` argument loop (was line 216), parser.py `canonical_json`/`_statement_dict` (was line 264), coordinator.py `resolved_kwargs` loop (was line 222), model.py `Argument`.
Evidence: Old parser JSON-parsed any non-ref bracket (`[E.a, E.b]` -> JSONDecodeError); `_references_in` already recursed lists; coordinator only resolved top-level string args.

## step.read
Status: succeeded
Inputs: `E.sites`
Actions: Read parser, model, coordinator, both test files, cli.py, and existing demo run artifacts (seal/WORKLOG/evaluation format).
Outputs: `ART.sources` = full context of syntax and runtime argument handling.
Evidence: `tikhon lint` validates against builtin commands {define, search, fetch, extract, summarize, report, verify, calculate, check} (cli.py `_builtin_command_names`); sealed digests of all demo runs exist in `seal.txt` files and must stay stable.

## step.analyze
Status: succeeded
Inputs: `ART.sources`
Actions: Reproduced the defect and mapped the constraint surface: AST value as a plain Python list of ref strings (no model change needed for the value itself); a `line` field on `Argument` for validation locations; canonical JSON must stay byte-identical for old programs.
Outputs: `E.findings` = defect reproduced; design constraints fixed.
Evidence: `json.loads("[E.a, E.b]")` raises `Expecting value` (the reported failure); `dataclasses.asdict` on invocations would leak a new field into sealed JSON, so `_statement_dict` is built field-by-field; `[]` is unused as an argument value anywhere in tests/demos/src (grep), so rejecting empty brackets breaks nothing.

## step.design
Status: succeeded
Inputs: `E.findings`
Actions: Designed the bracket rule: non-empty bracket containing a ref outside quotes must be a flat pure ref list; empty/nested/mixed rejected with distinct clear messages; no-ref brackets stay JSON literals; coordinator resolves each list item through the shared `values` mapping.
Outputs: `P.design` = implementation plan across parser.py, model.py, coordinator.py.
Evidence: Program sealed before edits: `a27d8f0757967d37fb7be7fc7d5429587e5c7c8aa05fc3619dea6bfb3a7005af` (written to seal.txt); `program.think` contains no ref arrays per protocol, so it parses under both old and new grammar with an identical digest.

## step.patch
Status: succeeded
Inputs: `P.design`
Actions: Implemented the parser bracket rule (`_parse_bracket_value`, `_contains_ref`), threaded `line` through `Argument`, added locations to reference validation, made `_statement_dict` explicit for digest stability, and added ref-list resolution in the coordinator.
Outputs: `ART.patch` = edits to parser.py, model.py, coordinator.py.
Evidence: parser.py:136-205 (`_parse_argument`/`_parse_bracket_value`/`_contains_ref`), parser.py:275-283 (validation with `argument.line`), parser.py:328-346 (explicit `_statement_dict`), model.py:16 (`line: int = 0`), coordinator.py:222-233 (list resolution).

## step.check
Status: succeeded
Inputs: `ART.patch`, `C.behavior`
Actions: Added 16 tests (13 syntax, 3 coordinator), ran the full suite, re-sealed every existing demo program, and ran sealed programs end-to-end through the CLI.
Outputs: `V.tests` = all checks passed.
Evidence: `python3 -m pytest -q` -> `216 passed` (200 pre-existing after the concurrent registry work landed, which subsumes the 163 baseline, plus 16 new); all seven `demo/runs/*/program.think` seals byte-identical to their `seal.txt`; `python3 -m tikhon run ... --seal ...` -> `succeeded` for both the sealed issue-01 program and a ref-list program.

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Re-verified the seal of program.think against seal.txt after all edits and checked every acceptance criterion against the goal.
Outputs: `V.result` = goal satisfied.
Evidence: `tikhon seal demo/runs/issue-01-refs-lists/program.think` = `a27d8f0757967d37fb7be7fc7d5429587e5c7c8aa05fc3619dea6bfb3a7005af` (matches seal.txt, digest unchanged after implementation); ref-list digest deterministic across parses and comment decoration; `[G.right, G.left]` yields a different digest; single-ref args, JSON literals, and `-> t1, t2` targets unchanged (existing tests green).
