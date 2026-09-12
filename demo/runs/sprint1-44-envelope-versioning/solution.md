# Solution — Issue #44: Envelope additive versioning policy

## Policy chosen: (a) read-side tolerance, writers strict

Within `schema_version "1"`, the read side (`from_json`) tolerates unknown
fields by **dropping** them. Writers (`to_json` / `to_dict`) stay strict and
never emit unknown fields. Breaking changes require a version bump to `"2"`.

## Implementation

### src/tikhon/envelope.py

1. **Module docstring** (lines 1-16): Added "Additive versioning policy (v1.x)"
   section documenting: readers tolerate unknown fields (dropped on parse),
   writers stay strict, breaking changes require version bump to "2".

2. **`_load_envelope_object`** (lines ~549-562): The wire-parse helper used
   only by `from_json` now drops unknown fields instead of passing them through
   to the strict `_check_envelope_fields`. The strict `from_dict` path is
   unchanged — it still rejects unknown fields via `_check_envelope_fields`.

3. **`validate()` error messages** (TaskEnvelope ~line 291, ResultEnvelope
   ~line 459): Changed `"expected {VERSION!r}"` to `"supported version:
   {VERSION!r}"` so a version mismatch names the supported version.

4. **`from_json` docstrings**: Both `TaskEnvelope.from_json` and
   `ResultEnvelope.from_json` now document the additive v1.x drop-unknown
   policy.

### tests/test_envelope.py

Added 4 acceptance tests (lines ~752-807):

- `test_task_envelope_from_json_tolerates_unknown_field` — v1 task envelope
  with a `future_field` parses via `from_json`; unknown field is dropped;
  restored envelope equals the original.
- `test_result_envelope_from_json_tolerates_unknown_field` — same for result
  envelopes with a `future_usage_detail` field.
- `test_schema_version_2_fails_with_versioned_error` — `schema_version "2"`
  fails with an error message containing `"supported version"` and `"'1'"`.
- `test_strict_writer_roundtrip_unchanged` — strict `to_json()` output
  round-trips identically through `from_json()` for task, succeeded result,
  and failed result envelopes.

### Key design decision: `from_json` tolerant, `from_dict` strict

`from_json` is the wire/parse path (external data). `from_dict` is the
internal API (trusted mappings). By dropping unknowns in
`_load_envelope_object` (called only by `from_json`), we get read-side
tolerance without weakening the internal `from_dict` contract. The existing
test `test_task_envelope_rejects_unknown_and_missing_fields` (which tests
`from_dict` directly) passes unchanged.

## Test results

- Baseline: 760 passed
- After changes: 764 passed (760 + 4 new)
- All existing tests pass unchanged

## Bridge.py note

The bridge outcome `protocol_version` line (bridge.py) is the orchestrator's
post-merge addition — `bridge.py` was not touched. The envelope module's
additive policy is independent of that wire-level version key.
