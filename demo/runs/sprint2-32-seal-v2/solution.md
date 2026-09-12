# Solution — issue #32: Seal is not canonical

## Problem

The TAHOE seal digest was not canonical with respect to two semantically irrelevant source-text variations:

1. **IF-condition whitespace**: The raw condition text (e.g., `V.flag == "go"`) was stored verbatim on the `Conditional` model and serialized directly into the canonical JSON. Programs differing only in spacing (e.g., `V.flag  ==  "go"`) produced different seals, even though they parse to the same AST.

2. **BARRIER spelling**: A bare `BARRIER` produced `barrier_targets = ()`, while `BARRIER -> E.a, E.b` produced `barrier_targets = ("E.a", "E.b")`. These serialized differently in the canonical JSON even though validation (parser.py:1647-1655) forces them to be semantically equal.

## Solution

Implemented a **versioned digest** system that keeps v1 byte-compatible while adding a canonical v2:

### v1 (default, unchanged)

- `seal_digest(program)` and `seal_digest(program, version=1)` produce the same digest as before.
- `canonical_json(program)` is unchanged — still serializes raw condition text and written-order barrier.
- All 42 historical seals still verify.

### v2 (new)

- `seal_digest(program, version=2)` produces a canonical digest.
- `canonical_json_v2(program)` serializes:
  - **Condition**: re-parses the raw condition text via `parse_condition` to get the AST, then serializes it as a structured list, e.g., `["and", ["eq", "V.flag", "go"], ["count", "E.items", ">=", 2]]` instead of the raw string `"V.flag == \"go\" AND count(E.items) >= 2"`.
  - **Barrier**: the sorted union of branch targets, e.g., `["E.a", "E.b"]` regardless of whether the source wrote `BARRIER`, `BARRIER -> E.a, E.b`, or `BARRIER -> E.b, E.a`.
- All other statement types serialize identically to v1.

### Design decision: re-derive AST at sealing time

The `Conditional` model (in `model.py`) stores the raw condition text. Since `model.py` is not an owned file, the v2 path re-derives the AST from the raw text using `parse_condition` (already in `parser.py`) at sealing time. This avoids any model changes while still producing a spacing-invariant canonical form.

### Files Changed

| File | Change |
|------|--------|
| `src/tahoe/syntax/parser.py` | Added `canonical_json_v2`, `_statement_dict_v2`, `_condition_ast_to_canonical`; updated `seal_digest` to accept `version` param |
| `src/tahoe/syntax/__init__.py` | Exported `canonical_json_v2` |
| `tests/test_syntax.py` | Added 5 tests for v2 exports, v1 backward compat, and AST re-derivation |
| `tests/test_seal_v2.py` | New file: 16 tests covering all 5 acceptance criteria |

### Test Results

- Baseline: 864 passed
- Final: 885 passed (21 new tests, 0 regressions)

### Protocol Deviations

1. **CLI --v2 flag**: The issue requests `CLI 'tahoe seal --v2'` but `src/tahoe/cli.py` is not in the owned files. The v2 API is fully exposed via `seal_digest(program, version=2)` and `canonical_json_v2(program)` in `tahoe.syntax`, but the CLI flag is not added. Documented in evaluation.json.
2. **Run verification**: The issue requests "run verification accepts both versions" but `cli.py` is not owned. Documented in evaluation.json.
3. **Model change**: The issue suggests storing the condition AST on `Conditional`, but `model.py` is not owned. The v2 path re-derives the AST from raw text instead. Functionally equivalent.
