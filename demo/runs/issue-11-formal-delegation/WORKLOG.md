# WORKLOG — issue-11-formal-delegation

## seal
Status: done
Inputs: docs/spec/02-command-catalog.md shape, demo/runs/issue-01-refs-lists/program.think as canonical-grammar precedent.
Actions: Wrote program.think using only registered commands (define, search, fetch, extract, summarize, report, check, verify) in plain steps frame/locate/read/analyze/design/patch/check/verify; solve/prove intentionally absent from the sealed program because they do not exist yet. Ran `tikhon lint` (valid) then `tikhon seal`; digest captured to seal.txt. No source file touched before sealing.
Outputs: seal.txt = 7ecc95893c7d916ee1f48c83419ad8e5667add8ef1ed976ebd1d90ab6fa48405; program.think mtime 2026-09-12 19:06:56 predates every source edit in this run.
Evidence: `tikhon lint` -> "valid"; seal.txt content matches `tikhon seal` stdout.

## formalization-kind
Status: done
Inputs: src/tikhon/registry/enums.py (FailureKind closed set, ADR-0002 "Failure Semantics").
Actions: Added `FORMALIZATION = "formalization"` to FailureKind, placed with the semantic failure kinds before UNKNOWN; no existing member renamed or reordered.
Outputs: FailureKind.FORMALIZATION with value "formalization".
Evidence: tests/test_registry.py::test_formalization_kind_exists_with_expected_value passes.

## solve-contract
Status: done
Inputs: issue #11 spec; search/fetch routing precedent (minimum above validator tier, fetch permits T0..T3 with minimum T1 and validator T0).
Actions: Added `_solve()` CommandSpec factory to src/tikhon/registry/builtins.py with the full 18-field contract: inputs problem:text + domain:descriptor(pddl/smt); outputs solution:artifact + formalization:artifact; effects external_read_only; READ_ONLY; failures INVALID_INPUT (nonretryable), FORMALIZATION (retryable, recovery "request a new formalization attempt, not a blind retry"), UNAVAILABLE (retryable); evidence formalization_digest + solver_result; routing minimum T1, permitted T0..T3, preferred T2, validator T0, escalation_on (FORMALIZATION, UNAVAILABLE), fallback_chain empty; budget max_attempts=3 so a new formalization attempt fits the retry budget.
Outputs: solve registered in BUILTIN_FACTORIES at version 1.0.0.
Evidence: tests/test_registry.py solve tests pass.

## prove-contract
Status: done
Inputs: issue #11 spec; same routing precedent.
Actions: Added `_prove()` CommandSpec factory: inputs statement:text + language:descriptor(lean4/isabelle); outputs proof:artifact + checker_result:artifact; READ_ONLY; failures INVALID_INPUT (nonretryable), FORMALIZATION (retryable, new-formalization-attempt recovery), UNAVAILABLE (retryable); evidence proof_digest + checker_result; routing minimum T2, permitted T0/T2/T3, preferred T3, validator T0, escalation_on (FORMALIZATION, UNAVAILABLE), fallback_chain empty; budget max_seconds=300 for heavy proof synthesis.
Outputs: prove registered in BUILTIN_FACTORIES at version 1.0.0.
Evidence: tests/test_registry.py prove tests pass.

## tests
Status: done
Inputs: tests/test_registry.py parametrized invariants (BUILTIN_NAMES drives completeness/routing/roundtrip).
Actions: Added "prove" and "solve" to BUILTIN_NAMES (alphabetical, matching Registry.names() sorted order) so all registry-wide parametrized invariants cover them; added FORMAL_COMMANDS tuple and an issue-#11 test section (kind existence/value, retryable on both specs, routing tiers, recovery wording, INVALID_INPUT nonretryable, evidence keys); updated test_decision_commands_extend_the_nine_originals additively to include FORMAL_COMMANDS in the catalog delta.
Outputs: 21 parametrized invariant tests now also run for solve/prove; 10 new issue-specific tests.
Evidence: python3 -m pytest tests/test_registry.py -q green.

## evidence-scratch
Status: done
Inputs: the post-implementation registry (solve/prove now resolvable).
Actions: Linted a scratch program inside the run dir that dispatches solve and prove steps, proving the sealed language accepts the new commands once registered.
Outputs: scratch-solve-prove.think lints valid against the repo parser.
Evidence: `PYTHONPATH=src python3 -m tikhon lint demo/runs/issue-11-formal-delegation/scratch-solve-prove.think` -> "valid".

## verify-suite
Status: done
Inputs: full test suite, baseline 444 passed.
Actions: Ran python3 -m pytest -q; re-verified seal.txt digest still matches `tikhon seal` on the untouched program.think.
Outputs: suite green; seal stable.
Evidence: pytest output recorded in solution.md; seal digest byte-identical before and after all edits.
