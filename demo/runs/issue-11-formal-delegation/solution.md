# Solution — issue #11: Formal-language delegation (solve/prove + FailureKind.FORMALIZATION)

Run: demo/runs/issue-11-formal-delegation · Seal: 7ecc95893c7d916ee1f48c83419ad8e5667add8ef1ed976ebd1d90ab6fa48405 · Terminal status: succeeded

## What was implemented

LLM+P's lesson applied: the coordination language stays minimal, hard bounded reasoning is delegated to formal backends, and formalization failure is its own typed failure class.

1. **`FailureKind.FORMALIZATION`** (src/tikhon/registry/enums.py) — value `"formalization"`, placed with the semantic kinds before `UNKNOWN`. No existing member renamed; the closed set only grows.
2. **`solve` CommandSpec** (src/tikhon/registry/builtins.py, v1.0.0) — translate a bounded problem to a formal planning/SMT language (pddl/smt) and return the deterministic solver result. Inputs `problem:text`, `domain:descriptor`; outputs `solution:artifact`, `formalization:artifact`; `external_read_only` / `READ_ONLY`; evidence `formalization_digest` + `solver_result`; failures INVALID_INPUT (nonretryable), FORMALIZATION (retryable — recovery: "request a new formalization attempt, not a blind retry"), UNAVAILABLE (retryable); routing minimum T1 / preferred T2 / validator T0 (formalization needs a strong model; the validator is a deterministic T0 check of the solver artifact), permitted T0–T3 (fetch precedent: validator tier sits below minimum), escalation on FORMALIZATION/UNAVAILABLE, empty fallback chain; budget max_attempts=3 so a *new* formalization attempt fits the retry budget.
3. **`prove` CommandSpec** (same file, v1.0.0) — emit a proof artifact in lean4/isabelle and verify it with a deterministic checker. Inputs `statement:text`, `language:descriptor`; outputs `proof:artifact`, `checker_result:artifact`; same failure pattern incl. retryable FORMALIZATION; READ_ONLY; routing minimum T2 / preferred T3 (proof synthesis is heavy) / validator T0, permitted T0/T2/T3, empty fallback chain; max_seconds=300 for heavy proofs.
4. **Tests** (tests/test_registry.py, additive) — `prove`/`solve` added to `BUILTIN_NAMES`, so the three registry-wide parametrized invariants (full-contract shape, routing-tier consistency, JSON roundtrip) now run for both new names; new `FORMAL_COMMANDS` section pins the issue-#11 contracts (kind existence/value `formalization`, FORMALIZATION retryable with the new-attempt recovery wording on both specs, INVALID_INPUT nonretryable, UNAVAILABLE retryable, READ_ONLY, exact routing tiers, evidence keys); `test_decision_commands_extend_the_nine_originals` updated additively to include `FORMAL_COMMANDS` in the catalog delta.

## Tikhon protocol evidence

- program.think (frame/locate/read/analyze/design/patch/check/verify, registered commands only) was linted and sealed **before** any source edit; digest in seal.txt re-verified byte-identical after all edits.
- `scratch-solve-prove.think` inside the run dir dispatches `solve(...)` and `prove(...)` steps and lints valid against the repo parser — evidence the new commands are first-class in the sealed language.

## Full suite

`python3 -m pytest -q` → **465 passed** (baseline 444; +21: 15 new issue-#11 tests + 6 from the two new names entering the parametrized invariants).

## Contract summaries

| command | routing (min / preferred / validator) | failure kinds |
|---|---|---|
| solve | T1 / T2 / T0 | INVALID_INPUT (no-retry), FORMALIZATION (retry → new formalization attempt), UNAVAILABLE (retry) |
| prove | T2 / T3 / T0 | INVALID_INPUT (no-retry), FORMALIZATION (retry → new formalization attempt), UNAVAILABLE (retry) |
