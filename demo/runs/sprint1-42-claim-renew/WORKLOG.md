# WORKLOG — sprint1-42-claim-renew

## Step 0 — Context Gathering
- Status: done
- Inputs: issue #42, bridge.py, claims.py, events.py, audit.py, cli.py, test_bridge.py, envelope.py
- Actions: Read all spec files, understood claim lifecycle, heartbeat event type (dead at events.py:43), audit whitelist (audit.py:34), CLI ready/claim/submit wiring, TaskEnvelope contract.budget.max_attempts
- Outputs: Full understanding of the claim bridge, submit path, and CLI structure
- Evidence: bridge.py 353 lines, claims.py 88 lines, EventType.HEARTBEAT exists but never emitted, audit.py:34 whitelists HEARTBEAT in _INVOCATION_BOUND_TYPES

## Step 1 — Tikhon Protocol
- Status: done
- Inputs: program.think, seal command
- Actions: Wrote program.think using registered commands, lint valid, sealed
- Outputs: seal.txt with digest 6d6122da94c952f28bcf8c81fab9802474f2bcc7aa092d936aff7e046b781705
- Evidence: `PYTHONPATH=src python3 -m tikhon lint` → valid; seal → 6d6122da...

## Step 2 — Implementation: ClaimBridge.renew + _is_fresh + _last_heartbeat
- Status: done
- Inputs: bridge.py, events.py
- Actions: Added _token_fingerprint helper, renew() method (validates token, appends HEARTBEAT with fingerprint+ts), _claim_freshness_base (max of claimed_at and last heartbeat), _last_heartbeat, updated _is_fresh to use _claim_freshness_base
- Outputs: bridge.py with renew/heartbeat support
- Evidence: renew appends HEARTBEAT event, _is_fresh reads max(claimed_at, last_hb), submit honors extended freshness

## Step 3 — Implementation: max_attempts reissue cap
- Status: done
- Inputs: bridge.py, envelope.py
- Actions: Added _envelope_max_attempts to read contract.budget.max_attempts off TaskEnvelope, added cap check in ready() using strict > (claim_attempt > max_attempts), passed max_attempts to _issue_claim
- Outputs: ready() stops reissuing when claim_attempt > max_attempts
- Evidence: test_reissue_respects_max_attempts passes; existing test_stale_claim_is_reissued passes with max_attempts=1 (1 > 1 false → one reissue allowed)

## Step 4 — Implementation: CLI renew + fencing
- Status: done
- Inputs: cli.py
- Actions: Added _cmd_renew function, added renew subparser with --db/--run-id/--program/--seal/--workspace/--invocation-id/--claim-token/--claim-timeout, added DriverError import, added fencing guard in _cmd_submit token-less path (checks _open_claim + _is_fresh), updated module docstring
- Outputs: cli.py with renew subcommand and fencing guard
- Evidence: test_cli_renew_extends_freshness passes, test_tokenless_submit_against_open_claim_is_rejected passes, test_tokenless_submit_without_open_claim_still_works passes

## Step 5 — Tests
- Status: done
- Inputs: test_bridge.py
- Actions: Added 10 tests covering all 6 acceptance items (renew extends freshness + delayed submit, stale/foreign token rejects, token-less submit fencing, CLI renew E2E, coordinator-driven unchanged, reissue max_attempts cap, unlimited when absent)
- Outputs: 25 total bridge tests (15 original + 10 new), all passing
- Evidence: `PYTHONPATH=src python3 -m pytest tests/test_bridge.py -q` → 25 passed

## Step 6 — Full Suite Verification
- Status: done
- Inputs: full pytest suite
- Actions: Ran `PYTHONPATH=src python3 -m pytest -q`
- Outputs: 770 passed (760 original + 10 new) in ~20s
- Evidence: `PYTHONPATH=src python3 -m pytest -q` → 770 passed in 20.36s

## Step 7 — Final Artifacts
- Status: done
- Inputs: solution.md, evaluation.json
- Actions: Wrote solution.md and evaluation.json with full acceptance checklist
- Outputs: demo/runs/sprint1-42-claim-renew/{program.think, seal.txt, WORKLOG.md, solution.md, evaluation.json}
- Evidence: All 6 acceptance items pass, git status shows only owned files modified
