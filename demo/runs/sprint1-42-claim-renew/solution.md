# solution.md — sprint1-42-claim-renew

GitHub issue #42: claim renew/heartbeat + close the token-less submit bypass.

## What was built

### `src/tikhon/bridge.py` (modified)

**`ClaimBridge.renew(invocation_id, claim_token) -> dict`** — validates the
caller's claim token against the invocation's open claim (same checks as
`submit`: nonempty token, run exists, run not terminal, open claim exists,
token matches). On success, appends a `HEARTBEAT` event
(`EventType.HEARTBEAT`, already defined at `events.py:43` but previously
dead) carrying `{invocation_id, claim_token_fingerprint, ts}` where
`claim_token_fingerprint` is a SHA-256 hex of the raw token (never the raw
token itself). Returns `{renewed, run_id, invocation_id, claim_attempt,
heartbeat_seq, freshness_ts}`.

**`_is_fresh()` now reads `max(claimed_at, last_heartbeat)`** — the
freshness origin is the later of the claim's `claimed_at` and the most
recent `HEARTBEAT` event's `ts` for the same invocation. This means a
`renew` at t+50s extends the lease to t+50s+timeout, so a claimant
working >900s can renew and their eventual `submit` succeeds.

**`_last_heartbeat(events, invocation_id)`** — new static method that
scans events for `HEARTBEAT` records matching the invocation and returns
the latest parsed `ts` (or `None`).

**`_claim_freshness_base(claim)`** — new method that computes the
effective freshness origin from the store's events.

**`_envelope_max_attempts(envelope)`** — new static method that reads
`contract.budget.max_attempts` off the `TaskEnvelope`. Returns `None`
when absent or unparseable (preserving unlimited reissue behavior).

**Reissue cap in `ready()`** — when a stale claim is detected and
`max_attempts` is set, the bridge checks `claim_attempt > max_attempts`
(strict `>`) and if true, returns `{"ready": false, ...}` with a reason
naming the cap, without reissuing. The `>` semantics means
`max_attempts=1` allows one reissue (2 total claims), `max_attempts=3`
allows 3 total claims, etc.

**`_token_fingerprint(token)`** — module-level helper for SHA-256
fingerprinting.

### `src/tikhon/cli.py` (modified)

**`tikhon renew` subcommand** — `--db`, `--run-id`, `--program`, `--seal`,
`--workspace`, `--invocation-id`, `--claim-token`, `--claim-timeout`.
Follows the same arg style as `ready`/`claim`/`submit`. Calls
`ClaimBridge.renew()` and prints the JSON outcome.

**Fencing guard on token-less submit** — the legacy `driver.submit_result()`
path (no `--claim-token`) now checks for an open, non-expired claim on the
target invocation via `ClaimBridge._open_claim` + `_is_fresh`. If an open
fresh claim exists, the submit is rejected with a `DriverError` mentioning
"fenced" and nothing is appended. Coordinator-driven runs (no CLAIMED
events) are unaffected because `_open_claim` returns `None`.

**Module docstring** — updated command list to include `renew`.

**Import** — added `DriverError` to the `tikhon.envelope` import block.

### `tests/test_bridge.py` (modified)

10 new tests covering all 6 acceptance items:

1. `test_renew_with_correct_token_extends_freshness_and_delayed_submit_succeeds` — renew with correct token extends freshness past timeout, delayed submit succeeds
2. `test_renew_with_stale_foreign_token_appends_nothing` — wrong/empty/unknown token appends nothing
3. `test_renew_on_terminal_run_rejected` — renew on terminal run rejected
4. `test_tokenless_submit_against_open_claim_is_rejected` — token-less submit against open claim fenced, nothing appended
5. `test_tokenless_submit_without_open_claim_still_works` — token-less submit without open claim still works (Wave 8 path)
6. `test_cli_renew_extends_freshness_and_delayed_submit_succeeds` — CLI renew end-to-end + delayed submit
7. `test_cli_renew_wrong_token_rejected` — CLI renew with wrong token exits 1
8. `test_coordinator_driven_no_claim_runs_unchanged` — coordinator-driven runs have no claims/heartbeats, unchanged behavior
9. `test_reissue_respects_max_attempts` — reissue stops at max_attempts
10. `test_reissue_unlimited_when_max_attempts_absent` — unlimited reissue when max_attempts absent

## Test results

Full suite: **770 passed** (760 pre-existing + 10 new) in ~20s.

## Constraints honored

- Touched only: `src/tikhon/bridge.py`, `src/tikhon/cli.py`,
  `tests/test_bridge.py`, `demo/runs/sprint1-42-claim-renew/`.
- No git commit made.
- `git status --porcelain` shows changes only in owned files.

## Deviations

- **`max_attempts` semantics**: the cap uses `claim_attempt > max_attempts`
  (strict `>`), not `>=`. This means `max_attempts=1` allows one reissue
  (2 total claims), preserving the existing test
  `test_stale_claim_is_reissued_with_new_token_and_attempt` which expects
  a reissue with `define` (max_attempts=1). The interpretation: `max_attempts`
  is the max number of retries after the initial attempt, so
  `max_attempts + 1` total claims are allowed.
- `events.py` was not modified — `EventType.HEARTBEAT` already existed and
  was already whitelisted in `audit.py`'s `_INVOCATION_BOUND_TYPES`.
- `claims.py` was not modified — the issue mentions it as a possible file
  but the implementation lives entirely in `bridge.py` and `cli.py`.
