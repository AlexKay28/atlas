# WORKLOG — sprint2-32-seal-v2

Seal: 2be6fa9bcecc3bab1d7a9f279ad0485575cc3d2e26f8742f7226a3a4e56f25af
Program: demo/runs/sprint2-32-seal-v2/program.think (linted valid and sealed 2026-09-12T19:30:00Z before any source edit; the final code re-seals to the identical digest recorded in seal.txt)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed issue #32 into a versioned-digest design: keep v1 byte-compatible (all historical seals must verify), add v2 canonical form serializing parsed condition AST (re-derived from raw text via parse_condition) and normalizing barrier to sorted branch-target union; expose seal_digest(program, version=2) + canonical_json_v2; v1 path stays byte-identical.
Outputs: G.plan = the versioned-digest design above.

## step.search
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located every sealing touchpoint: canonical_json (parser.py:1821), _statement_dict (parser.py:1833), seal_digest (parser.py:1935), _parse_conditional_line (parser.py:319) where condition AST is computed-and-discarded, _parse_par_block (parser.py:465) where barrier_targets are set, _validate_par_statement (parser.py:1575) where barrier validation forces bare=union, Conditional model (model.py:76), parse_condition (parser.py:529) which produces JSON-serializable AST tuples.
Outputs: E.sites = the touchpoints above.

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read the full sealing pipeline: canonical_json builds payload {name, version, declarations, statements} where each statement is _statement_dict'd; Conditional serializes raw condition text (the bug); Par serializes barrier_targets in written order (bare vs explicit differ); _parse_condition_head returns (ast, statement_start) but the AST is discarded; parse_condition produces plain tuples ("eq", ref, value) etc that are already JSON-serializable; the condition AST can be re-derived from the raw condition text at sealing time.
Outputs: ART.sources = the sealing pipeline trace.

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Pinned the design constraints: (a) all changes must fit in owned files (parser.py, __init__.py, tests, demo run); (b) model.py is NOT owned, so condition_ast cannot be added to the Conditional dataclass — the v2 path re-derives the AST from the raw condition text using parse_condition at sealing time; (c) cli.py is NOT owned, so the --v2 CLI flag and dual-version run verification are documented as protocol deviations; (d) parser.py: add canonical_json_v2, _statement_dict_v2, _condition_ast_to_canonical; update seal_digest to accept version param; (e) __init__.py: export canonical_json_v2; (f) v1 path must stay byte-identical.
Outputs: E.findings = the design constraints above.

## step.plan
Status: succeeded
Inputs: G.plan
Actions: Split into 5 subtasks: (1) parser.py: add v2 functions, update seal_digest signature; (2) __init__.py: export canonical_json_v2; (3) tests: test_seal_v2.py (new) + test_syntax.py (extend); (4) demo run artifacts (WORKLOG, solution.md, evaluation.json); (5) verify git status shows only owned files.
Outputs: G.subgoals = the 5 subtasks.

## step.patch
Status: succeeded
Inputs: C.scope, G.subgoals
Actions: Applied all patches. parser.py: added _condition_ast_to_canonical, _statement_dict_v2 (re-derives condition AST via parse_condition, normalizes barrier to sorted branch-target union), canonical_json_v2; updated seal_digest to accept version param (default 1 = unchanged v1 behavior). __init__.py: exported canonical_json_v2. No changes to model.py, cli.py, or any other files.
Outputs: ART.patch = the applied changes.

## step.test
Status: succeeded
Inputs: tests/, 900s timeout
Actions: Ran PYTHONPATH=src python3 -m pytest -q: 885 passed (864 baseline + 21 new). All historical seals verify under v1. v2 spacing-invariant for conditions. v2 barrier-normalized. v2 canonical JSON has no raw condition string. v1 and v2 differ for IF/PAR programs but are same for plain programs.
Outputs: V.tests = 885 passed, 0 failed.

## step.review
Status: succeeded
Inputs: ART.patch, V.tests, C.done
Actions: Verified all 5 acceptance criteria: (1) v2 seals equal for programs differing only in condition spacing — pass (test_v2_condition_spacing_invariant); (2) bare-BARRIER vs explicit-union seal identically under v2 — pass (test_v2_bare_barrier_matches_explicit_barrier, test_v2_reordered_barrier_matches_bare); (3) all 42 historical seals verify under v1 — pass (test_all_historical_seals_verify_v1); (4) v2 canonical json contains no raw condition string — pass (test_v2_canonical_json_has_no_raw_condition_string); (5) docs deltas reported in evaluation.json — pass.
Outputs: V.review = all acceptance criteria satisfied.

## step.check
Status: succeeded
Inputs: V.review, C.done
Actions: Confirmed C.done = "seals equal for programs differing only in condition spacing and barrier spelling with no raw condition string in canonical json" is met.
Outputs: V.verdict = satisfied.

## step.verify
Status: succeeded
Inputs: G.goal, V.verdict, V.tests, E.findings
Actions: Verified the goal "canonicalize seals" is achieved: v2 canonical form is spacing-invariant and barrier-normalized; v1 is unchanged for backward compatibility.
Outputs: V.result = resolved.

## step.report
Status: succeeded
Inputs: V.result, V.verdict
Actions: Wrote WORKLOG.md, solution.md, evaluation.json.
Outputs: ART.report = the demo run artifacts.
