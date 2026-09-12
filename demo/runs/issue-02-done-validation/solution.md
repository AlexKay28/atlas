# Solution — issue #2: Truthful validation (DONE predicates → VALIDATION_FAILED)

Run: `issue-02-done-validation` · Seal: `0c3260d3f351b32383f553917c99d06d51a662b6f86b3e130dc5ae5c96b92194`
(program.think and seal.txt were written before any source edit; digest re-verified after)

## Spec conformance of the DONE grammar

docs/spec/01-language-and-state.md ("Deterministic Expressions") is authoritative.
It defines DONE expressions with **infix operators**, not named predicates
(`equals`/`matched` are not in the spec). Following the spec:

```text
DONE <target-ref> == <json-literal>        # spec infix equality, e.g. DONE V.quality.status == "passed"
DONE <target-ref> IN [json, json, ...]     # spec infix set membership, e.g. DONE D.cause.status IN ["accepted", "blocked"]
DONE matched(<target-ref>, "<regex>")      # deterministic regex predicate
```

- `<target-ref>` must be exactly one of the owning invocation's targets
  (validated at parse time with source location, and re-checked in
  `validate_program`). Field paths into a target (`E.result.ok` where the
  target is `E.result`) are rejected.
- `matched(<ref>, "<regex>")` keeps the issue's suggested name: the spec defines
  no regex operator, so there was no spec name to fall back to. The pattern is
  compile-checked at parse time; evaluation uses `re.fullmatch` (deterministic,
  locale/time independent). A non-string committed value is a predicate failure
  (payload detail says so), not a crash.
- `==` uses JSON-strict equality: `true` never equals `1` (Python bool/int
  blur is deliberately broken); dicts/lists compare recursively.
- `IN` right-hand side must be a JSON array literal (members are JSON literals;
  refs inside are rejected at parse time).
- The predicate is parsed into a structured `DonePredicate(op, ref, value, line)`
  on `Invocation.done` (replacing the previously-ignored raw string) and is part
  of the canonical JSON, so the seal digest covers the predicate.
- Everything else in a DONE line (bare refs, `AND`/`OR`, comparison operators
  other than `==`, unknown predicate names like `schema(...)`/`equals(...)`,
  `exists(...)`, `>`, unclosed regexes) is rejected with `ParseError`.

## Files changed

- `src/tikhon/syntax/model.py` — added frozen `DonePredicate` dataclass; `Invocation.done` is now `DonePredicate | None`.
- `src/tikhon/syntax/parser.py` — DONE lines parse into the three predicate forms (`_parse_done_expression`, `_parse_matched_predicate`, top-level quote/bracket-aware `==`/`IN` scanners); parse-time target-ref validation; `validate_program` re-checks ref-∈-targets and known op; canonical JSON serializes the predicate.
- `src/tikhon/syntax/__init__.py` — exported `DonePredicate`.
- `src/tikhon/runtime/events.py` — **no change needed**: `EventType.VALIDATION_FAILED = "invocation.validation_failed"` already existed (unused); coverage added in tests instead.
- `src/tikhon/runtime/coordinator.py` — pure `evaluate_done_predicate` + `_json_equal` (no worker calls, no clocks, no I/O); after target mapping succeeds, an attached predicate is evaluated over the committed target values; on failure `finish_failed_invocation` now prepends a `VALIDATION_FAILED` record (payload: `step_id`, `predicate {op, ref, value}`, `detail`) to the existing atomic failure batch (FAILED, invocation_recorded, task_cancelled, unreached cancellations, RUN_FINISHED failed). Success keeps the exact old lifecycle; no-DONE invocations are byte-for-byte unchanged.
- `tests/test_syntax.py` — canonical fixture moved to a real predicate; new tests: equals/IN/matched parsing, all JSON literal shapes, ref-must-be-target (parse + validate levels, including earlier-defined refs and field paths), 14 malformed/unknown-expression rejections, seal determinism/sensitivity.
- `tests/test_coordinator.py` — new tests: passing equals+matched keep `LIFECYCLE` (READY→DISPATCHED→RESULT_RECEIVED→VALIDATION_PASSED→SUCCEEDED) and commit; failing equals and failing matched each yield exactly READY→DISPATCHED→RESULT_RECEIVED→**VALIDATION_FAILED**→FAILED, no state commit, run failed, ledger clean (no pending/in-progress, unreached tasks cancelled), payload explains which predicate failed; JSON-strict bool-vs-int equality; matched rejects non-string values; no-DONE invocations unchanged.
- `tests/test_event_store.py` — VALIDATION_FAILED round-trip coverage (envelope fields + payload survive the store).
- `demo/runs/issue-02-done-validation/` — sealed program, seal.txt, WORKLOG.md, this solution, evaluation.json.

## Acceptance checklist

| Criterion | Result |
| --- | --- |
| DONE grammar implemented in parser, attached to invocations | yes — `DonePredicate` on `Invocation.done`, three forms above |
| Predicate names follow the spec | yes — spec infix `==` / `IN`; `matched` kept from the issue (spec has no regex name) |
| `ref` must be a step target, validated | yes — parse time (with location) + `validate_program` |
| Unknown predicate name rejected | yes — `ParseError: unsupported DONE expression` (parse) / `unknown DONE predicate` (validate) |
| `EventType.VALIDATION_FAILED` = "invocation.validation_failed" | yes (already present; now actually emitted, with store round-trip test) |
| Coordinator evaluates after target mapping, purely/deterministically | yes — `evaluate_done_predicate` over committed target values only |
| Failure → VALIDATION_FAILED + standard atomic failure batch, no state commit, run failed, ledger clean | yes — asserted in `test_failing_equals_predicate_fails_run_without_commit` / `test_failing_matched_predicate_fails_run_without_commit` |
| Success → VALIDATION_PASSED as now; no-DONE unchanged | yes — lifecycle and no-DONE regression tests |
| Full suite green | yes — 265 passed (baseline 216) |
| cli.py / registry / other demo runs / docs untouched | yes — cli.py diffs are the concurrent issue-#14 work, not this run |

## Deviations / limitations

1. **Grammar naming**: the issue suggested `DONE equals(ref = JSON-literal)` /
   `DONE matched(ref = "regex")`; the spec (authoritative per the issue) defines
   infix `==` and `IN` instead of named predicates, so those were implemented
   for equality/membership. `matched` has no spec counterpart; the issue's name
   was kept, with positional args `matched(<ref>, "<regex>")` (the issue's
   `matched(ref = "regex")` shape mixes the ref and pattern into one argument
   and could not be honored literally).
2. **Minimal subset**: only `==`, `IN`, `matched` are supported. The spec's
   larger deterministic expression language (`AND`/`OR`, `exists`, `count`,
   `schema`, `covers`, ordered comparison, field selection into targets) is
   intentionally out of scope and rejected clearly.
3. **`matched` semantics**: `re.fullmatch` against the string form; non-string
   values fail the predicate (with a type-naming detail) rather than raising.
4. **Environment note**: the `tikhon` binary on PATH is a stale site-packages
   install predating this change; verification used the repo sources
   (`PYTHONPATH=src`). Repo tests are unaffected.
5. Concurrent issue-#14 work landed `tests/test_audit.py` / `src/tikhon/audit.py`
   mid-run; a transient failure of its injected-violation test self-resolved in
   a later run and the final full suite (including it) is green. No #14 file was
   touched by this run.
