# Solution: issue-01-refs-lists

Support lists of typed references in step arguments: `items = [E.a, E.b]`.

## What changed

### src/tikhon/syntax/parser.py
- `_parse_argument` (parser.py:136): bracket-shaped argument values (starting and
  ending with `[...]`) are routed to the new `_parse_bracket_value`; every
  `Argument` now records its source line.
- `_parse_bracket_value` (parser.py:154): a non-empty bracket that mentions a
  typed reference anywhere outside quotes must be a flat, pure reference list
  and parses to a Python list of ref strings. Empty brackets, nested lists, and
  mixed refs-and-literals are rejected with distinct, located messages. A
  non-empty bracket without any reference stays an ordinary JSON literal
  (`[1, 2]`, `[{"k": [3]}]`, `["G.left"]` behave exactly as before).
- `_contains_ref` (parser.py:192): quote-aware scan deciding whether a bracket
  mentions a typed reference (quoted `"E.a"` strings do not count).
- `validate_program` (parser.py:275): every ref inside an argument value —
  including each entry of a reference list — must resolve to a declared INPUT
  node or a node produced by an earlier step; failures now carry the source
  line via `argument.line`.
- `_statement_dict` (parser.py:328): invocation dicts are built field-by-field
  instead of `dataclasses.asdict` so the new `Argument.line` metadata never
  enters the sealed canonical JSON — all previously sealed programs keep their
  exact digests (verified against every `demo/runs/*/seal.txt`).

### src/tikhon/syntax/model.py
- `Argument` (model.py:16): added `line: int = 0` (frozen dataclass extended
  minimally, default keeps hand-constructed ASTs compatible) so validation
  errors can report a location.

### src/tikhon/runtime/coordinator.py
- Argument resolution (coordinator.py:222): a list-valued argument becomes a
  Python list in which each ref-shaped item is resolved through the same
  `values` mapping used for single refs; non-ref items pass through untouched.
  Workers receive a real list (`sum` over `[G.left, G.right]` = 12 in tests).

## Tests added (16)
- tests/test_syntax.py: parsing+validation of `[G.left, G.right]` and
  produced-node lists; unknown list ref rejected with the step's line number;
  empty brackets (`[]`, `[ ]`, `[   ]`) rejected; mixed (`[G.left, 5]`,
  `[5, G.left]`, `[G.left, "G.right"]`) rejected; nested (`[[G.left], ...]`,
  `[[G.left]]`) rejected; JSON list literals unchanged; seal digest
  deterministic across parses and comment/blank-line decoration, sensitive to
  listed refs and their order.
- tests/test_coordinator.py: ref-list program executes to outputs
  `{OUT.total: 12, OUT.wrapped: 17}`; dispatch events carry the resolved real
  lists (`[5, 7]`, `[12, 5]`); JSON literal list arguments pass through
  unchanged while a single ref in the same invocation still resolves.

## Result
`python3 -m pytest -q`: **216 passed** (200 pre-existing — the baseline moved
from 163 to 200 mid-task when the concurrent registry work landed — plus 16
new). No previously sealed program's digest changed. The sealed run program
`demo/runs/issue-01-refs-lists/program.think` still executes to `succeeded`
via `tikhon run --seal`.
