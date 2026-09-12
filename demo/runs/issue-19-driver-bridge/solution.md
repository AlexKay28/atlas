# Solution: issue-19-driver-bridge (GitHub issue #19, epic #27)

## What was built

An agent-executable bridge on top of the Wave 8 sequential external
driver: a ready/claim/submit lifecycle with fencing claim tokens so an
external agent (e.g. an OpenCode agent) can execute Tikhon invocations
with its own tools while Tikhon maintains state and validates results —
the agent process never holds the event store open beyond one command.
All changes are inside the five allowed paths (`src/tikhon/bridge.py`
new, `src/tikhon/cli.py`, `src/tikhon/runtime/events.py` one additive
EventType, `tests/test_bridge.py` new,
`demo/runs/issue-19-driver-bridge/`).

### 1. Claim bridge (`src/tikhon/bridge.py`)

- **Claim lifecycle** (additive overlay on the event store; the
  coordinator-driven path ignores it): per invocation
  `UNCLAIMED -> CLAIMED-FRESH -> CLAIMED-STALE -> SETTLED`.  A claim is
  *open* while the latest `INVOCATION_CLAIMED` event for the invocation
  has no `RESULT_RECEIVED` after it; it is *fresh* while
  `now < claimed_at + claim_timeout_seconds` (default 900, CLI
  `--claim-timeout`).
- **`ClaimBridge.ready(claimant=None)`** — used by both `tikhon ready`
  and `tikhon claim`: renders the next ready invocation's
  `TaskEnvelope` through the unchanged
  `ExternalDriver.next_envelope()` (fresh-start / READY / DISPATCHED
  bookkeeping reused verbatim), then:
  - terminal run: `{"terminal": true, "run_id", "status": ...}`,
    nothing appended, exit 0;
  - fresh open claim held by another driver:
    `{"ready": false, "claim": ...}` — nothing appended, no envelope
    handed out;
  - otherwise records `INVOCATION_CLAIMED` (payload:
    `claim_token` uuid4 hex, `claimed_at` UTC, `claimant`,
    `envelope_digest` sha256 over the envelope's canonical JSON,
    `claim_attempt` 1-based; event `attempt` column = envelope
    attempt) and returns
    `{"ready": true, "claim": ..., "envelope": ...}`.
- **Stale-claim re-issue (fencing)**: when the open claim is stale,
  ready appends a fresh `INVOCATION_DISPATCHED` (same binding) before
  the new `INVOCATION_CLAIMED`, so the re-rendered envelope carries
  attempt+1.  The old driver's token rejects (no longer the open
  claim) AND its old envelope's echoed attempt rejects through the
  Wave 8 `attempt == len(dispatched)` check.  The attempt counter
  persists in both the envelope and the CLAIMED events.
- **`ClaimBridge.submit(result, claim_token)`**: rejects with nothing
  appended on unknown run, terminal run, no open claim, token
  mismatch, or expired claim; otherwise delegates to the unchanged
  `ExternalDriver.submit_result` (RESULT_RECEIVED -> VALIDATION_PASSED
  + atomic SUCCEEDED batch, or the failed/blocked atomic cancellation
  path).  No separate DONE/mapping/validation logic was written — the
  coordinator machinery owns all of it.
- All store invariants inherited unchanged: gapless seq via
  `append`/`append_batch`, atomic batches, no false completion.

### 2. CLI (`src/tikhon/cli.py`)

- `tikhon ready --db --run-id --program --seal [--workspace]
  [--claim-timeout]` and `tikhon claim ... [--claimant NAME]`: print
  the structured JSON handout (or terminal/claimed status), exit 0.
- `tikhon submit` gains `--claim-token [--claim-timeout]`: with a
  token, the claim-validated path; without, the exact Wave 8
  behavior (coordinator-driven and claim-less runs unchanged).
- Shared store/KB/driver construction refactored into
  `_open_external_driver`/`_close_driver`, reused by next/ready/claim.

### 3. Event type (`src/tikhon/runtime/events.py`)

- One additive enum member: `INVOCATION_CLAIMED = "invocation.claimed"`.
  No other events.py change; the coordinator, audit and resume paths
  are untouched (audit's per-invocation checks only inspect
  FAILED/VALIDATION/SUCCEEDED orderings, so CLAIMED events keep
  `audit_run` clean with no audit.py edit).

### 4. What needed NO change

- `resume.py`: resume already re-executes any invocation without a
  SUCCEEDED event, so a claimed-but-unsubmitted invocation is treated
  as non-terminal and re-executed (verified by test) — the
  "claimed invocation guard on resume" was not needed; claims are a
  pure additive overlay.
- `coordinator.py`, `envelope.py`, `worker_adapter.py`, `audit.py`,
  `syntax/`, `registry/`: untouched.

### 5. Demo run

`demo/runs/issue-19-driver-bridge/program.think` (6 plain sequential
steps: frame, locate, design, produce patch, check, verify) was sealed
BEFORE any source edit and driven end-to-end by
`artifacts/external_driver_session.py` through the CLI only:
`claim --claimant opencode-agent` -> result file ->
`submit --claim-token`, with the fencing semantics demonstrated on
step 1 (a second `ready` while fresh is refused with the same claim
token; a wrong-token submit appends nothing).  Terminal: `succeeded`,
`tikhon audit` OK, `tikhon status` 100% completed 6/6, and a terminal
`ready` answers `{"terminal": true, "status": "succeeded"}` with exit
0.

## Agent loop (documented per the issue)

1. `tikhon ready --db ... --run-id ... --program ... --seal ...`
2. If `terminal` — done.  If `ready: false` — another driver holds a
   fresh claim; poll again.  If `ready: true` — take `claim_token`
   and `envelope`.
3. Execute the envelope's command with the agent's own tools; craft a
   `ResultEnvelope` echoing the envelope identity.
4. `tikhon submit ... --claim-token <token> --result-file <path>`.
5. Repeat from 1.  On a crash/timeout, the claim expires after
   `--claim-timeout` and the next ready re-issues it with a new token
   and attempt+1; the dead attempt cannot submit.

## Verification

- `tests/test_bridge.py`: 15 tests — external fake agent completes a
  sealed program via claims (no deterministic handler performs its
  reasoning steps); fresh double-claim refused; stale claim re-issued
  with new token and attempt+1; old token and old attempt both
  rejected with nothing appended; wrong token rejected with nothing
  appended; submit without open claim rejected; terminal run reports
  terminal and accepts nothing (module + CLI); `audit_run` clean after
  the claim-driven run; resume re-executes a claimed invocation;
  bridge-driven projection matches a coordinator-driven run for
  equivalent inputs.
- Full suite after this run's edits: 589 passed (baseline 571 + 15
  here + 3 from the concurrent #20 child-runs agent).  No git commits.
