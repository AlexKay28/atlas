# WORKLOG — sprint1-44-envelope-versioning

Seal: 7549d39061ecbf472bf9663a950f0daec510b6c1cf9ac743198d62ec3577bf10
Task: GitHub issue #44 — Envelope additive versioning policy

## step.frame
Status: succeeded
Inputs: G.task = "Implement additive versioning policy for envelope schema"
Actions: Defined the goal — read-side tolerates unknown fields within v1, writers stay strict, schema_version != 1 fails with versioned error
Outputs: G.plan = "implement (a) read-side tolerance with drop-unknown policy"
Evidence: issue #44 text: "pick and document one policy: (a) read-side tolerates unknown fields within v1 (writers stay strict)"

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Searched the codebase for envelope validation paths
Outputs: E.candidates = [src/tikhon/envelope.py, tests/test_envelope.py]
Evidence: grep for _check_envelope_fields, from_json, schema_version in envelope.py

## step.read
Status: succeeded
Inputs: E.candidates
Actions: Read envelope.py (1336 lines) and test_envelope.py (750 lines)
Outputs: ART.sources = full source of both files
Evidence: Read tool output, line references: ENVELOPE_SCHEMA_VERSION ~line 88, _check_envelope_fields ~563-577, schema_version checks ~289-293 and ~457-461

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Analyzed the validation flow:
  - from_json -> _load_envelope_object (just json.loads + type check) -> from_dict
  - from_dict -> _check_envelope_fields (rejects unknown + missing fields) -> constructor -> validate()
  - validate() checks schema_version == "1" with "expected" wording
  - Existing test test_task_envelope_rejects_unknown_and_missing_fields (line 168) tests from_dict directly
  - Key insight: from_json is the wire/parse path; from_dict is the internal API
  - Strategy: drop unknowns in _load_envelope_object (used only by from_json), keep from_dict strict
  - This preserves all existing tests unchanged
Outputs: E.findings = "drop unknowns in _load_envelope_object, keep _check_envelope_fields strict for from_dict"
Evidence: envelope.py:547-560 (_load_envelope_object), 563-577 (_check_envelope_fields), 397-402 (from_json), 404-428 (from_dict)

## step.design
Status: succeeded
Inputs: E.findings
Actions: Designed the implementation:
  1. Update module docstring with v1.x additive policy
  2. Update ENVELOPE_SCHEMA_VERSION comment
  3. Modify _load_envelope_object to drop unknown fields before returning
  4. Update validate() error messages: "expected" -> "supported version"
  5. Update from_json docstrings to mention additive policy
  6. Add 4 acceptance tests
  7. Keep _check_envelope_fields unchanged (from_dict stays strict)
Outputs: P.design = the 7-step plan above
Evidence: Design derived from source analysis

## step.implement
Status: succeeded
Inputs: P.design
Actions: Applied edits to src/tikhon/envelope.py:
  - Lines 1-16: expanded module docstring with additive v1.x policy section
  - Line 88: updated ENVELOPE_SCHEMA_VERSION comment
  - Lines 291-292: "expected" -> "supported version" in TaskEnvelope.validate()
  - Lines 459-460: same in ResultEnvelope.validate()
  - Lines 398-402: updated TaskEnvelope.from_json docstring
  - Lines 519-523: updated ResultEnvelope.from_json docstring
  - Lines 549-562: modified _load_envelope_object to drop unknown fields
  Added 4 tests to tests/test_envelope.py (lines 752-807):
  - test_task_envelope_from_json_tolerates_unknown_field
  - test_result_envelope_from_json_tolerates_unknown_field
  - test_schema_version_2_fails_with_versioned_error
  - test_strict_writer_roundtrip_unchanged
Outputs: ART.patch = edited envelope.py and test_envelope.py
Evidence: git diff shows 6 edited sections + 56 new test lines

## step.test
Status: succeeded
Inputs: tests/test_envelope.py
Actions: Ran PYTHONPATH=src python3 -m pytest -q
Outputs: V.tests = "764 passed in 21.14s"
Evidence: pytest output: 764 passed (760 baseline + 4 new)

## step.check
Status: succeeded
Inputs: V.tests
Actions: Verified suite green and only owned files changed
Outputs: V.verdict = "suite_green"
Evidence: git status --porcelain shows only envelope.py, test_envelope.py, demo/runs/sprint1-44-envelope-versioning/

## step.report
Status: succeeded
Inputs: ART.patch
Actions: Wrote solution.md
Outputs: OUT.solution = solution.md
Evidence: solution.md written

## step.verify
Status: succeeded
Inputs: G.task, V.tests
Actions: Verified all 4 acceptance criteria:
  (1) v1 envelope + one unknown field parses — test_task_envelope_from_json_tolerates_unknown_field PASS
  (2) schema_version "2" fails with versioned error — test_schema_version_2_fails_with_versioned_error PASS
  (3) all existing envelope tests pass unchanged — 760 baseline tests still pass, test_task_envelope_rejects_unknown_and_missing_fields unchanged PASS
  (4) roundtrip: strict writer output identical — test_strict_writer_roundtrip_unchanged PASS
Outputs: V.result = "all acceptance criteria pass"
Evidence: pytest -q output: 764 passed
