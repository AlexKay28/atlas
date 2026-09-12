# tikhon learn — mined run report

Source: demo/runs
Runs scanned: 15

## Routing telemetry

- terminal statuses: succeeded=13, unknown=2
- steps planned (from programs): 110
- steps executed (from evaluation.json): 88
- programs with parse errors: 0
- programs skipped for CALL nesting: 0
- worklogs present: 13
- event stores found: 0

## Protocol candidates (12)

1. define -> search
   suggested protocol name: define_search_pipeline
   support: 14 programs
   runs: chat-runtime-refactor, crash-recovery-glm52, issue-01-refs-lists, issue-02-done-validation, issue-05-kb-memory, issue-06-decision-commands, issue-07-revise-retire, issue-09-effectful-commands, issue-12-protocol-calls, issue-13-tikhon-learn, issue-14-tikhon-audit, issue-15-registry-digest, routing-optimization-glm52, runtime-review-glm52
2. check -> verify
   suggested protocol name: check_verify_pipeline
   support: 12 programs
   runs: chat-runtime-refactor, issue-01-refs-lists, issue-02-done-validation, issue-05-kb-memory, issue-06-decision-commands, issue-07-revise-retire, issue-09-effectful-commands, issue-12-protocol-calls, issue-13-tikhon-learn, issue-14-tikhon-audit, issue-15-registry-digest, live-glm52-refactor
3. extract -> summarize
   suggested protocol name: extract_summarize_pipeline
   support: 12 programs
   runs: chat-runtime-refactor, issue-01-refs-lists, issue-02-done-validation, issue-05-kb-memory, issue-06-decision-commands, issue-07-revise-retire, issue-09-effectful-commands, issue-12-protocol-calls, issue-13-tikhon-learn, issue-14-tikhon-audit, issue-15-registry-digest, live-glm52-refactor
4. search -> fetch -> extract
   suggested protocol name: search_fetch_extract_pipeline
   support: 11 programs
   runs: chat-runtime-refactor, crash-recovery-glm52, issue-01-refs-lists, issue-02-done-validation, issue-05-kb-memory, issue-06-decision-commands, issue-09-effectful-commands, issue-13-tikhon-learn, live-glm52-refactor, routing-optimization-glm52, runtime-review-glm52
5. define -> search -> fetch -> extract
   suggested protocol name: define_search_fetch_pipeline
   support: 10 programs
   runs: chat-runtime-refactor, crash-recovery-glm52, issue-01-refs-lists, issue-02-done-validation, issue-05-kb-memory, issue-06-decision-commands, issue-09-effectful-commands, issue-13-tikhon-learn, routing-optimization-glm52, runtime-review-glm52
6. extract -> summarize -> report -> check -> verify
   suggested protocol name: extract_summarize_report_pipeline
   support: 9 programs
   runs: chat-runtime-refactor, issue-01-refs-lists, issue-02-done-validation, issue-05-kb-memory, issue-06-decision-commands, issue-09-effectful-commands, issue-13-tikhon-learn, issue-14-tikhon-audit, live-glm52-refactor
7. search -> fetch -> extract -> summarize -> report -> check -> verify
   suggested protocol name: search_fetch_extract_pipeline
   support: 8 programs
   runs: chat-runtime-refactor, issue-01-refs-lists, issue-02-done-validation, issue-05-kb-memory, issue-06-decision-commands, issue-09-effectful-commands, issue-13-tikhon-learn, live-glm52-refactor
8. define -> search -> fetch -> extract -> summarize -> report -> check -> verify
   suggested protocol name: define_search_fetch_pipeline
   support: 7 programs
   runs: chat-runtime-refactor, issue-01-refs-lists, issue-02-done-validation, issue-05-kb-memory, issue-06-decision-commands, issue-09-effectful-commands, issue-13-tikhon-learn
9. define -> search -> extract -> summarize
   suggested protocol name: define_search_extract_pipeline
   support: 4 programs
   runs: issue-07-revise-retire, issue-12-protocol-calls, issue-14-tikhon-audit, issue-15-registry-digest
10. define -> search -> extract -> summarize -> check -> verify
   suggested protocol name: define_search_extract_pipeline
   support: 3 programs
   runs: issue-07-revise-retire, issue-12-protocol-calls, issue-15-registry-digest
11. report -> verify
   suggested protocol name: report_verify_pipeline
   support: 3 programs
   runs: crash-recovery-glm52, routing-optimization-glm52, runtime-review-glm52
12. define -> search -> fetch -> extract -> report -> verify
   suggested protocol name: define_search_fetch_pipeline
   support: 2 programs
   runs: crash-recovery-glm52, runtime-review-glm52

## Failure clusters (5)

- missing_commands: 2 quote(s)
  - "The executable catalog has no edit or test command, so report and check are used as the closest artifact-production and verification operations while ordinary repository tools perform the implementati"
  - "The registered command catalog has no edit or test command, so report and check stand in for artifact production and verification while ordinary repository tools perform the implementation."
  - runs: chat-runtime-refactor, issue-01-refs-lists
- reference_arrays: 1 quote(s)
  - "The installed `tikhon` CLI binary resolves to a stale non-editable site-packages copy while pytest uses the repo src (pyproject pythonpath). Lint/seal were run with the installed CLI as mandated; the "
  - runs: issue-01-refs-lists
- identifier_syntax: 8 quote(s)
  - "A DONE predicate over a KB.* ref is rejected at parse time by the pre-existing target-ownership rule rather than at validate_program; KB facts are observed by recalling them into a state node first."
  - "CALL targets are pinned to a subset of the protocol RETURN refs by exact ref-string equality (the issue's 'simplest sound rule'), so caller targets cannot rename protocol outputs; positional or leaf-n"
  - "DONE predicate names follow the spec's infix operators (== and IN) instead of the issue's suggested named forms equals(ref=...)/matched(ref=...); the issue delegates naming to the spec, which defines "
  - runs: issue-02-done-validation, issue-05-kb-memory, issue-09-effectful-commands, issue-12-protocol-calls, routing-optimization-glm52, runtime-review-glm52
- path_errors: 9 quote(s)
  - "Bare python3 -m tikhon resolves to a stale site-packages copy rather than src/ (pytest uses pythonpath=src); live CLI evidence was therefore produced with PYTHONPATH=src. No repo change was needed or "
  - "The coordinator still dispatches effectful commands when workspace_root is None (per the issue: edit-style commands still work, no root provided), but the CLI edit/test handlers treat an undeclared wo"
  - "The default protocols directory is protocols/ under the current working directory (repo root for CLI usage and pytest) rather than a git-anchored project root: Python cannot locate a repo root without"
  - runs: crash-recovery-glm52, issue-02-done-validation, issue-06-decision-commands, issue-09-effectful-commands, issue-12-protocol-calls, issue-14-tikhon-audit, issue-15-registry-digest
- other: 14 quote(s)
  - "A protocol must end with RETURN (not STOP) and contain at least one invocation — a STOP-terminated protocol has no defined value to commit to the caller's targets, so validation rejects it with a clea"
  - "Nested protocol-call task texts carry only the immediate protocol name prefix (protocol.inner: step.deep: ...) rather than the full call chain; the issue specifies only 'text prefixed protocol.name:'."
  - "No EffectClass enum value was added: REVERSIBLE_WRITE already exists and is the closest class for a durable-but-overwritable KB write, so the issue's fallback ('map to the closest existing effect clas"
  - runs: issue-02-done-validation, issue-05-kb-memory, issue-06-decision-commands, issue-09-effectful-commands, issue-12-protocol-calls, issue-14-tikhon-audit, issue-15-registry-digest, routing-optimization-glm52

Promotion to protocols/ or the registry requires a human-approved PR; this report never writes there.