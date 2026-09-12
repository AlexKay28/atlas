# Solution: tikhon learn — mine runs into protocol candidates and failure clusters (issue #13)

## What was built

`tikhon learn --runs PATH [--out PATH]` is the sleep phase of the wake-sleep
loop: it compresses the experience accumulated in `demo/runs/*` into a
deterministic, human-readable review report. Promotion to `protocols/` or the
registry is deliberately out of scope — the miner is read-only; the only file
it can ever produce is the optional `--out` report.

## src/tikhon/learn.py (new)

- `mine_run_directory(runs_dir: Path) -> LearnReport` scans every
  subdirectory of `runs_dir` and, per run, tolerantly reads:
  - `program.think` — parsed with the canonical parser; parse failures are
    recorded per-run and never abort the sweep. The DO-command sequence is
    the `Invocation.command` list in source order. Programs containing any
    `CALL` statement are excluded from candidate mining entirely (avoiding
    candidates that would nest into protocols and violate the recursion
    rules), but still counted in telemetry.
  - `evaluation.json` — missing or invalid files degrade to `unknown`
    terminal status and zero executed steps; `protocol_deviations` and
    `unresolved` arrays feed failure clustering.
  - `WORKLOG.md` — optional; only its presence is counted.
  - `*.db` event stores sitting next to the artifacts (optional) — FAILED
    payloads are mined as quotes; unreadable stores or unknown run ids are
    tolerated silently.
- **Candidate rule**: a contiguous command n-gram (n ≥ 2) of a program's
  DO-command sequence is a candidate when it appears in ≥ 2 distinct
  non-CALL programs. A candidate is *maximal*: it is dropped if another
  candidate with equal or higher support contains it as a contiguous
  subsequence. Each candidate carries the command sequence, support (number
  of programs), sorted example run ids, and a suggested protocol name
  (`snake_case` from the first three commands + `_pipeline`, e.g.
  `define_search_fetch_pipeline`). Output sorted by (-support, -length,
  commands) — fully deterministic.
- **Failure clusters**: every deviation/unresolved/FAILED quote is
  lowercased and matched against priority-ordered keyword buckets —
  `missing_commands`, `reference_arrays`, `identifier_syntax`,
  `path_errors`, `other` (fallback). Clusters carry occurrence counts,
  up to 3 representative quotes truncated to 200 chars, and the sorted run
  ids that contributed.
- `LearnReport` is a frozen dataclass with `to_markdown()` producing a
  stable, evidence-linked report (source path, run count, routing telemetry,
  ranked candidates with run-id lists, clusters with quotes and runs, and a
  promotion-requires-human-PR footer). Two invocations over the same
  directory produce byte-identical text.

## src/tikhon/cli.py

New `learn` subcommand: prints the markdown report to stdout; with `--out`
writes the file and prints its path. Exit 0 always (it is a reporting
command) except 1 when the runs dir is unreadable. No other writes.

## tests/test_learn.py (13 tests)

Synthetic fixtures (overlapping step sequences, CALL program, missing/invalid
evaluation.json, real event store with a FAILED payload), plus a tolerant
real-corpus test against the repo's `demo/runs/` (skips only if the
directory is absent; asserts ≥ 1 candidate otherwise), a write-isolation
test (directory snapshot unchanged), markdown-determinism, telemetry counts,
and the three CLI behaviors.

## Result

- `python3 -m pytest -q` → **410 passed** (397 baseline + 13 new).
- Real corpus mined: `define -> search -> fetch -> extract` candidate with
  support 10, `search -> fetch -> extract` support 11, five failure clusters
  covering 34 real deviation/unresolved quotes (report saved as
  `demo/runs/issue-13-tikhon-learn/report.md`).

## Protocol

`demo/runs/issue-13-tikhon-learn/program.think` was linted (`valid`) and
sealed (`20af411f0e592e132d7b88b1d56abdc64b31935753b6afad161dfc23fe338926`,
written to `seal.txt`) **before** any source edit and never modified after;
the digest was re-verified byte-identical after all edits and after the
concurrent parser/model/coordinator changes landed in the tree.
