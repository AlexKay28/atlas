# Solution — sprint3-94-triz-ideation (issue #94)

**Shipped:** `protocol.triz` — a TRIZ-guided ideation protocol for tahoe agents.

- `protocols/triz.think` — contradiction-driven brainstorm as a composable child run:
  challenge (state the physical contradiction) → IFR → two search branches
  (the discipline's own hits + one deliberately remote field) → candidate moves →
  classification (pattern | compromise | antipattern) → ideality ranking →
  KB.triz persistence under the caller's key → report.
- `tests/test_triz_protocol.py` — 6 tests: end-to-end CALL execution, the
  formulate-before-generating contract asserted from the ordered event log,
  both spectrum branches consumed, KB round-trip, parent+child audit clean,
  full return adoption.
- `demo/runs/sprint3-94-triz-ideation/` — sealed evidence run (deterministic
  coordinator): tool thrash mined into 5 patterns / 1 compromise / 1 antipattern,
  spectrum persisted under `triz/ai-harness` and recalled by prefix.

**The demo's own verdict, as TRIZ would want it stated:** "retry harder" is an
antipattern (widens the contradiction); exponential backoff alone is a compromise
(keeps it); the patterns remove it — poka-yoke identical retries (9), feed the
error text back as input (23), idempotency key at the callee (13), circuit
breaker (11), retry budget with escalation (16).

**Verification:** full suite 1711 passed / 9 skipped (baseline 1705 + 6 new);
seal sweep green including the new run; parent and child audit clean.
