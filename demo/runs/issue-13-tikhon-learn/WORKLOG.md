# Worklog: issue-13-tikhon-learn

Seal: `20af411f0e592e132d7b88b1d56abdc64b31935753b6afad161dfc23fe338926`

GitHub issue #13: tikhon learn — mine runs into protocol candidates and failure clusters (wake-sleep, human-gated).

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to a new review-only mining module, one CLI subcommand, and their tests; confirmed baseline `python3 -m pytest -q` = 397 passed before any edits; confirmed learn never writes to protocols/ or src/ (only the optional --out file).
Outputs: `G.plan` = mine_run_directory -> LearnReport (candidates + failure clusters + telemetry + deterministic to_markdown), tikhon learn --runs PATH [--out PATH], exit 0 always / 1 on unreadable runs dir.
Evidence: Baseline run output `397 passed in 6.52s`; issue text; existing run artifacts surveyed for artifact shapes (program.think, evaluation.json, WORKLOG.md, seal.txt).

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Located the read-only surfaces to build on: tikhon.syntax.parse_program/ParseError for command sequences, tikhon.runtime.events.EventStore/EventType for optional FAILED payloads, tikhon.cli argparse wiring, and the demo/runs artifact conventions (12 run dirs at task start, all with evaluation.json keys task/run_id/seal/terminal_status/steps_planned/steps_executed/acceptance/unresolved/protocol_deviations).
Outputs: `E.sites` = src/tikhon/learn.py (new), src/tikhon/cli.py `_build_parser`/`main`, tests/test_learn.py (new), src/tikhon/runtime/events.py (read-only import).
Evidence: `grep` over src/tikhon/syntax/parser.py (_STEP_RE, CALL grammar), src/tikhon/runtime/events.py (EventType.FAILED, append/create_run signatures); `tikhon seal` and repo parser agreed byte-for-byte on a pre-existing program.

## step.read
Status: succeeded
Inputs: `E.sites`
Actions: Read the syntax model (Invocation/Call statement shapes), the event-store API (create_run/append/events/close), cli.py subcommand conventions, and several demo evaluation.json files including their protocol_deviations/unresolved phrasing to design keyword buckets.
Outputs: `ART.sources` = full context for mining: command sequences are Invocation.command in source order; CALL is a bare statement; event stores are optional per-run `*.db` files; deviations are free-text strings needing normalization.
Evidence: model.py Invocation/Call dataclasses; events.py EventType enum and EventStore.run/events KeyError behavior; demo/runs/*/evaluation.json key survey (13 dirs, uniform schema).

## step.analyze
Status: succeeded
Inputs: `ART.sources`
Actions: Reproduced the corpus shape by extracting DO-command sequences from all programs (define search fetch extract ... dominates); fixed the candidate rule as maximal contiguous command n-grams (n>=2) with support >= 2 distinct programs, where a candidate is dropped when another candidate with equal-or-higher support contains it; fixed five failure buckets (missing_commands, reference_arrays, identifier_syntax, path_errors, other) with priority-ordered keyword matching and 200-char quote truncation; decided the miner reads only and writes nothing.
Outputs: `E.findings` = candidate rule, bucket taxonomy, determinism strategy (sorted keys everywhere, no timestamps), CALL-programs excluded from candidate mining to avoid nesting candidates that would violate recursion rules.
Evidence: Command-sequence survey of 13 then 15 run dirs (concurrent agent added issue-07-revise-retire mid-task); define_search_fetch_extract support 10 in the final corpus; report determinism check `deterministic: True`.

## step.design
Status: succeeded
Inputs: `E.findings`
Actions: Designed LearnReport as a frozen dataclass (runs_dir, run_ids, candidates, clusters, terminal_status_counts, steps_planned_total, steps_executed_total, parse_error_runs, call_skipped_runs, worklogs_present, event_stores_found) with to_markdown() rendering evidence-linked sections; CLI `_cmd_learn` prints markdown, optionally writes --out, exits 0 always and 1 only on OSError/ValueError from an unreadable runs dir; tolerance rules: parse failures recorded per-run, missing/invalid evaluation.json -> unknown status, absent event stores contribute zero.
Outputs: `P.design` = implementation plan across learn.py, cli.py, test_learn.py.
Evidence: Program sealed before edits: `20af411f0e592e132d7b88b1d56abdc64b31935753b6afad161dfc23fe338926` (written to seal.txt via `tikhon lint` -> valid, `tikhon seal`); digest re-verified identical after all edits and after concurrent parser/model/coordinator changes landed.

## step.patch
Status: succeeded
Inputs: `P.design`
Actions: Implemented src/tikhon/learn.py (mine_run_directory, ProtocolCandidate/FailureCluster/LearnReport, maximal-contiguous-sequence miner, keyword buckets, optional EventStore FAILED-payload reader); added the `learn` subcommand to src/tikhon/cli.py; added tests/test_learn.py with synthetic fixtures, a write-isolation test, an event-store test, a tolerant real-corpus test, and three CLI tests.
Outputs: `ART.patch` = learn.py (~380 lines), cli.py (+30 lines), test_learn.py (~230 lines).
Evidence: `python3 -m pytest tests/test_learn.py -q` -> 13 passed after fixing two fixture bugs (CALL is a bare statement, run_ids counts directories only); file-touch audit `git status --porcelain` shows only cli.py modified by me plus new learn.py/test_learn.py/run dir (parser.py/model.py/coordinator.py modifications belong to the concurrent agent).

## step.check
Status: succeeded
Inputs: `ART.patch`, `C.behavior`
Actions: Ran the full suite; mined the real demo/runs corpus through the CLI both to stdout and via --out; verified two consecutive reports are byte-identical; verified the miner writes nothing (directory snapshot before/after in test_miner_writes_nothing); re-verified the seal.
Outputs: `V.tests` = all checks passed.
Evidence: `python3 -m pytest -q` -> `410 passed in 6.16s` (397 baseline + 13 new); `PYTHONPATH=src python3 -m tikhon learn --runs demo/runs --out demo/runs/issue-13-tikhon-learn/report.md` wrote the 91-line report; report.md contains the define_search_fetch_pipeline candidate with support 10 and five failure clusters mined from real evaluation.json deviations.

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Checked every acceptance criterion against the goal: candidates with support/sequence/names, CALL exclusion, cluster buckets with counts and 200-char-truncated representatives, telemetry totals, deterministic markdown, CLI exit codes and --out, write isolation, full suite green, protocol order (program.think sealed before source edits, never modified after).
Outputs: `V.result` = goal satisfied; promotion to protocols/ or the registry explicitly left to human-approved PR (this report is review-only evidence).
Evidence: seal.txt `20af411f0e592e132d7b88b1d56abdc64b31935753b6afad161dfc23fe338926` byte-identical pre- and post-edits; evaluation.json acceptance table filled from the checks above.
