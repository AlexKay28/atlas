# Solution — Issue #48 CLI Ergonomics

## Files Changed

### Source:
- `src/tikhon/cli.py` — module docstring with exit-code table and arg conventions; `--json` on status/audit/learn/bench/run; `--check` on seal; `--seal` required=True at argparse on run/resume/next/ready/claim/renew; runtime seal guards removed; exit codes 0/1/2/3/4 enforced; `--out` confirmations routed to stderr; `_load_validated_program` returns `(program, exit_code)` tuple to distinguish parse errors (1) from seal mismatches (4)
- `src/tikhon/learn.py` — added `LearnReport.to_dict()` for JSON output
- `src/tikhon/audit.py` — no changes (to_dict already existed)

### Tests:
- `tests/test_cli_ergo.py` (new) — 17 tests: --json for all 5 commands; one test per exit code (0-4); run without --seal exits 2 (argparse); seal --check correct/tampered; --out on stderr for bench and learn
- `tests/test_cli.py` — updated test_run_rejects_missing_seal (now SystemExit 2), test_run_rejects_wrong_seal (now rc == 4)
- `tests/test_audit.py` — updated test_cli_audit_violated_run (now rc == 3)
- `tests/test_effectful.py` — updated 2 tests (run failure now rc == 2)
- `tests/test_learn.py` — updated test_cli_learn_out_writes_file (--out confirmation now on stderr)
- `tests/test_resume.py` — updated test_resume_rejects_seal_mismatch (now rc == 4), test_resume_requires_seal (now SystemExit 2)

## Test Count
- Baseline: 809
- New tests: 17
- Final: 826 passed

## Exit Code Table
| Code | Meaning |
|------|---------|
| 0 | success |
| 1 | usage / input error (missing file, bad arg, malformed program) |
| 2 | program execution failed (run/resume coordinator error); also argparse syntax errors |
| 3 | audit violations found |
| 4 | seal digest mismatch |

## Doc Updates for Orchestrator (README)
Add rows to CLI reference table:
- `--json` flag: available on `status`, `audit`, `learn`, `bench`, `run`
- Exit codes: 0 ok, 1 usage, 2 run failed, 3 audit violations, 4 seal mismatch
- `seal --check`: verify a program against a known digest; exit 0 on match, 4 on drift
