# Solution: Issues #36 + #37 (Parser Language + Ergonomics Bundle)

## Summary

Implemented 9 purely-additive grammar changes across two issues in
`src/tahoe/syntax/parser.py`, with 25 new tests in `tests/test_syntax.py`
and grammar notes in `docs/spec/01-language-and-state.md`.

## Files Changed

| File | Change |
|------|-------|
| `src/tahoe/syntax/parser.py` | +272 lines (additive): trailing comment stripping, single-quote detection, multi-line INPUT, located `_split_top_level`, DONE parity operators, DONE attachment to IF/SCATTER, ref-to-ref comparison, indexed-target error |
| `tests/test_syntax.py` | +281 lines: 25 new tests + 2 updated tests |
| `docs/spec/01-language-and-state.md` | +15 lines: DONE predicate grammar notes, comment/quote handling notes |

## Issue #36: Language Expressiveness

### (a) DONE condition-parity operators
- `!=` (not-equals) — new `ne` op
- Field paths like `V.q.status` — valid when the longest prefix matches a step target (via `_done_ref_matches_targets`)
- `count()` comparisons — new `count` op reusing the condition machinery
- Ref-to-ref DONE (`DONE E.result == V.b`) — new `eq_ref`/`ne_ref` ops

### (b) DONE attaches inside embedded-invocation parse
- `_resolve_done_target` handles `Conditional` (attaches to embedded `Invocation`) and `Scatter` (attaches to body `Invocation`)
- DONE after `IF V.flag == "go" step.x: DO ...` now attaches to `step.x`
- DONE after a SCATTER body step now attaches to the body invocation

### (c) Ref-to-ref comparison
- `parse_comparison` in `_ConditionScanner` now checks for a typed ref on the RHS before trying JSON literal decode
- Produces `eq_ref`/`ne_ref` AST nodes instead of `eq`/`ne`
- `_condition_refs` returns both refs for validation
- `_condition_ast_to_canonical` serializes the new node types for v2 seals
- Validation resolves the RHS ref with `_condition_ref_resolvable`

### (d) Misleading error fix
- `IF V.a == V.b` no longer produces "invalid JSON literal"; it parses as `eq_ref`
- Single-quoted strings produce "use double quotes" instead of misleading JSON errors

### (e) Indexed targets
- `V.items[0]` now produces "indexed element access (V.items[0]) is not supported; use a SCATTER to iterate over the collection instead"

## Issue #37: Parser Ergonomics

### (a) Trailing comments
- `_strip_trailing_comment` strips `#` comments outside quotes from each raw line
- Applied in the source filtering step so all downstream parsing sees clean text
- Trailing-comment programs seal byte-identically to comment-free programs (v1)

### (b) Single-quoted strings
- `_detect_single_quoted_string` checks if a value starts with `'`
- Rejected with "single-quoted strings are not supported; use double quotes" in both argument values and INPUT declarations
- Documented: only JSON double-quoted strings are supported

### (c) Multi-line INPUT literals
- `_is_unbalanced` checks for unclosed brackets/quotes
- The INPUT parser accumulates continuation lines until brackets balance
- Multi-line and single-line forms of the same value seal identically

### (d) Located ParseErrors
- `_split_top_level` now accepts `line_no` parameter (default 0 for backward compat)
- All call sites updated to pass `line_no`
- Unbalanced delimiter and unbalanced argument errors now carry line and column

## Seal Verification

- Program seal: `4b3514963974df9483fdcbed2f3d276fa224b56459a69de52bac121237f1ac4f`
- CANONICAL seal: `39c3a47a8c5ef5828713eafe943b94fd365357cafb09ad199e330399b702447b` (unchanged)
- Trailing-comment program seals identically to comment-free (v1)

## Test Results

- Baseline: 938 passed
- Final: 963 passed (938 baseline + 25 new)
- 2 existing tests updated for intentional additive behavior change
