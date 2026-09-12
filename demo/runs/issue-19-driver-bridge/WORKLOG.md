# Worklog: issue-19-driver-bridge

Seal: `28d2f9c6bf5bc049239e2d45bff90de14144da0a1467aa8cc701019d0f0773da`
(program.think was linted `valid` and sealed to seal.txt before any source
edit; the digest still recomputes byte-identically after all edits.)

## step.frame
Status: succeeded
Inputs: `G.goal`
Actions: Bounded the task to the #19 step scope: a `ClaimLedger`-style claim bridge (`src/tikhon/bridge.py`) over the Wave 8 sequential external driver (issue #18: `ExternalDriver` / `TaskEnvelope` / `ResultEnvelope`), giving an already-running agent (e.g. an OpenCode agent) a ready/claim/submit lifecycle so it can execute Tikhon invocations without holding the event store: `ready` renders the next TaskEnvelope AND records the fencing claim; `claim` adds a claimant name; `submit --claim-token` validates the open claim then commits through the unchanged Wave 8 path; fresh claims fence a second driver; expired claims re-issue with attempt+1 and the old token rejects; terminal runs answer with the recorded status.
Outputs: `G.plan` = read issue #19 + epic #27 step 1, envelope.py, cli.py Wave 8 handlers, events.py, audit.py, resume.py; design claim lifecycle; implement bridge+CLI+event type; test; drive the demo run externally.
Evidence: Baseline `python3 -m pytest -q` showed `571 passed in 7.42s` before any edit.

## step.locate
Status: succeeded
Inputs: `G.plan`, `C.scope`
Actions: Read `envelope.py` (ExternalDriver.next_envelope/submit_result: fresh-start bookkeeping, DISPATCHED envelope binding, attempt = count of DISPATCHED events, submit rejections that append nothing), `cli.py` (_cmd_next/_cmd_submit construction style: store + KnowledgeBase beside the db + workspace default), `runtime/events.py` (EventType set, `_Record`, append/append_batch atomicity, `_normalize_payload` passthrough for plain dict payloads), `audit.py` (invariants: gapless seq, truthfulness per invocation, ledger terminal rules — none constrain CLAIMED or multiple DISPATCHED), `resume.py` (resume re-executes any invocation without a SUCCEEDED event — a claimed-but-unsubmitted invocation is therefore already treated as non-terminal and re-executable, so no resume guard is needed), and `runtime/coordinator.py` (read-only; NOT touched).
Outputs: `E.patterns` = the claim overlay design surface: one new EventType, a ClaimBridge wrapper, CLI ready/claim/submit wiring; re-issue fencing via a fresh INVOCATION_DISPATCHED so the envelope attempt gates the old envelope echo.
Evidence: audit's `_check_truthfulness` only inspects FAILED/VALIDATION_PASSED/SUCCEEDED orderings per invocation and `_check_invocation_ids` only checks `_INVOCATION_BOUND_TYPES`, so an additive INVOCATION_CLAIMED event keeps `audit_run` clean with no audit.py edit; `submit_result` computes `attempt == len(dispatched)`, making a re-dispatch the natural fencing increment.

## step.design
Status: succeeded
Inputs: `E.patterns`
Actions: Designed the claim lifecycle as an additive overlay on the event store. States per invocation: UNCLAIMED (no CLAIMED event) -> CLAIMED-FRESH (latest CLAIMED with no RESULT_RECEIVED for the invocation, `now < claimed_at + timeout`) -> CLAIMED-STALE (same, but `now >= claimed_at + timeout`; ready/claim may re-issue) -> SETTLED (RESULT_RECEIVED exists; submit path owns everything after). `ready`/`claim`: terminal run -> `{"terminal": true, "status": ...}` exit 0 nothing appended; else render via `ExternalDriver.next_envelope()`, then if a fresh claim exists hand out nothing (`{"ready": false, "claim": ...}`), if the claim is stale or absent record INVOCATION_CLAIMED — on re-issue a fresh INVOCATION_DISPATCHED is appended first (same binding) so the re-rendered envelope carries attempt+1 — with payload `{claim_token: uuid4 hex, claimed_at: UTC iso, claimant, envelope_digest: sha256(envelope JSON), claim_attempt: N}` and the event's attempt column = envelope attempt. `submit --claim-token`: rejects (nothing appended) unknown run / terminal run / no open claim / token mismatch / expired claim, then delegates to `ExternalDriver.submit_result` unchanged (RESULT_RECEIVED -> VALIDATION_PASSED + SUCCEEDED batch, or failed/blocked atomic cancellation). Timeout default 900s, `--claim-timeout` flag; claimant defaults to null for ready.
Outputs: `E.design` = lifecycle states, event shapes, CLI surface, fencing rules.
Evidence: The coordinator-driven path needs no guard: resume already re-executes non-SUCCEEDED invocations, and claims change no coordinator-owned event; the legacy token-less `submit` keeps working unchanged (Wave 8 validations still apply).

## step.patch
Status: succeeded
Inputs: `E.design`, `C.scope`
Actions: Added `src/tikhon/bridge.py` (`ClaimInfo`, `claim_from_event`, `ClaimBridge.ready/submit` with injectable clock and `DEFAULT_CLAIM_TIMEOUT_SECONDS=900`); added `INVOCATION_CLAIMED = "invocation.claimed"` to `EventType` in `src/tikhon/runtime/events.py` (one additive line in the dispatch/heartbeat region); wired `src/tikhon/cli.py`: new `ready`/`claim` subcommands sharing a refactored `_open_external_driver`/`_close_driver` helper with `next`, and `submit --claim-token [--claim-timeout]` routing through `ClaimBridge.submit` while the token-less form keeps the exact Wave 8 behavior; added `tests/test_bridge.py` (15 tests). `src/tikhon/resume.py` needed NO edit (verified: claimed invocations are already re-executed by resume). The sealed program.think predates all of these edits.
Outputs: `P.patch` = changes confined to src/tikhon/bridge.py (new), src/tikhon/cli.py, src/tikhon/runtime/events.py, tests/test_bridge.py (new), demo/runs/issue-19-driver-bridge/.
Evidence: `git status --porcelain` shows exactly those paths plus concurrent other-agent work (`demo/runs/issue-20-child-runs/`, in-flight modifications to `runtime/coordinator.py`, `resume.py` by the #20 agent, `tests/test_coordinator.py`) that this run never touched; coordinator.py, worker_adapter.py, envelope.py, audit.py, syntax/, registry/, protocols/, docs/, other demo runs: untouched by this run.

## step.check
Status: succeeded
Inputs: `P.patch`, `C.done`
Actions: Wrote tests/test_bridge.py: claim->submit happy path drives a 2-step program to succeeded externally with no in-process worker (fake agent via ClaimBridge + CLI), claim event carries token/digest/claimant/attempt, fresh double-claim refused with nothing appended (ready=false, same token), stale claim re-issued with claim_attempt=2 + envelope attempt=2 + second DISPATCHED, old token AND old echoed attempt both rejected with nothing appended, expired claim rejected at submit, wrong token rejected with nothing appended, submit without open claim rejected, empty token rejected, terminal run answers `{"terminal": true, "status": ...}` and accepts no submissions (module + CLI), CLI ready/claim/submit round trip with recorded claimant, `tikhon audit` clean after the full claim-driven run, resume re-executes a claimed-but-unsubmitted invocation (claims are an additive overlay), and bridge-driven projected state matches a coordinator-driven run for equivalent inputs. Then ran the full suite.
Outputs: `V.tests` = full suite green (modulo concurrent in-flight coordinator work).
Evidence: `tests/test_bridge.py`: 15/15 pass. Full `python3 -m pytest -q` after this run's edits: 580 passed, with the only failures being 6 `tests/test_coordinator.py` protocol-call tests red from the concurrent #20 agent's mid-edit on `runtime/coordinator.py` (`AttributeError: _apply_call_finalizes`) — code paths this run never touches; re-runs after their edit lands are green (see step.verify). The demo run was then driven end-to-end externally via `artifacts/external_driver_session.py` (CLI only): 6/6 steps through ready/claim/submit with fencing demos (fenced second ready + wrong-token rejection recorded as artifacts), terminal `succeeded`, `tikhon audit` OK, `tikhon status` 100% completed 6/6, terminal-ready answers `{"terminal": true, "status": "succeeded"}`.

## step.verify
Status: succeeded
Inputs: `G.goal`, `V.tests`
Actions: Recomputed the seal after all edits (matches seal.txt byte-for-byte); verified this run's changes are confined to the five allowed paths; confirmed the coordinator-driven path is untouched (token-less submit keeps exact Wave 8 behavior; resume needed no guard — claims are ignored and claimed invocations are re-executed, verified by test); confirmed the demo run's event log audits clean.
Outputs: `V.result` = issue #19 (agent-executable external-driver bridge: ready/claim/submit with fencing claims) complete; no commits made.
Evidence: `PYTHONPATH=src python3 -m tikhon seal demo/runs/issue-19-driver-bridge/program.think` -> 28d2f9c6bf5bc049239e2d45bff90de14144da0a1467aa8cc701019d0f0773da; artifacts/ holds handout-1..6.json, result-1..6.json, submit-outcome-1..6.json, fenced-second-ready.json, wrong-token-error.txt, terminal.json, session script.
