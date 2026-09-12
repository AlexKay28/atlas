# solution.md — sprint1-43-telemetry

GitHub issue #43: widen the transport seam so usage reaches receipts.

## Files changed

| File | Change |
|---|---|
| `src/tikhon/worker_adapter.py` | Added `TransportResult` dataclass, widened `Transport` type alias, added `_unwrap_transport` method, updated `execute()` and `_build_result_envelope()` to map usage into receipt, updated module docstring with seam contract |
| `tests/test_worker_adapter.py` | Added 6 acceptance tests for the transport usage seam |
| `demo/runs/sprint1-43-telemetry/` | This run: program.think, seal.txt, WORKLOG.md, solution.md, evaluation.json |

## Tests added + final count

6 new tests:
1. `test_transport_result_carries_usage_tokens_into_receipt` — TransportResult(text, {"tokens": 123}) → receipt tokens == 123
2. `test_legacy_str_transport_yields_none_tokens` — legacy str → receipt tokens None
3. `test_transport_result_with_none_usage_yields_none_tokens` — TransportResult with usage=None
4. `test_transport_result_with_non_integer_tokens_yields_none` — non-int tokens ignored
5. `test_transport_result_payload_parsed_correctly` — text parsed as JSON + tokens mapped
6. `test_transport_result_with_json_fence_stripped` — fence stripping works with TransportResult

**Final count: 766 passed** (760 baseline + 6 new) in 20.68s.

## Run ID + seal digest

- Run ID: `sprint1-43-telemetry`
- Seal: `5053afe18472cb7b109553c35231a63ca7b9d3dc1697409ab04d2799d2486689`

## Acceptance items

| # | Criterion | Pass/Fail | Evidence |
|---|---|---|---|
| 1 | Stub transport returning TransportResult(text, {"tokens": 123}) → receipt tokens == 123 | **Pass** | `test_transport_result_carries_usage_tokens_into_receipt`: `worker.last_result_envelope.receipt["usage"]["tokens"] == 123` |
| 2 | Legacy str-returning transport → receipt tokens None | **Pass** | `test_legacy_str_transport_yields_none_tokens`: `receipt["usage"]["tokens"] is None` |
| 3 | Existing adapter tests pass | **Pass** | All 25 pre-existing test_worker_adapter.py tests pass unmodified; full suite 766 passed |
| 4 | Full pytest suite green | **Pass** | `766 passed in 20.68s` |
| 5 | git status shows only owned files | **Pass** | `M src/tikhon/worker_adapter.py`, `M tests/test_worker_adapter.py`, `?? demo/runs/sprint1-43-telemetry/` |

## Deviations

None. The implementation follows the issue spec exactly: TransportResult with text + usage fields, back-compat with bare str, cost stays None, no envelope changes.

## cli.py wiring instructions for the orchestrator

The CLI HTTP transport (in `cli.py`, which must NOT be touched in this PR) currently
discards `body["usage"]` from the HTTP response. The wiring change is trivial — exactly
one place to modify:

### Current (cli.py, approximately line 293-295, DO NOT EDIT — described for the orchestrator)

The HTTP transport closure currently looks like:

```python
def transport(model: str, prompt: str) -> str:
    # ... HTTP request, gets `body` as parsed JSON ...
    return body["text"]  # discards body["usage"]
```

### After wiring (one change, return TransportResult instead of str)

```python
from tikhon.worker_adapter import TransportResult

def transport(model: str, prompt: str) -> TransportResult:
    # ... HTTP request, gets `body` as parsed JSON ...
    return TransportResult(
        text=body["text"],
        usage=body.get("usage"),  # passes the usage dict through, or None
    )
```

That's it. `ModelWorker.execute` calls `self._unwrap_transport(raw)` which detects
`TransportResult`, extracts `text` for JSON parsing and `usage` for the receipt.
The `_build_result_envelope` method reads `usage.get("tokens")` and maps it into
`receipt["usage"]["tokens"]`. The downstream `envelope._recorded_usage` consumer
already reads that field.

For the `exec` transport (subprocess), no change is needed — it returns `stdout`
as a bare `str`, which yields `None` tokens (correct: subprocess stdout has no
structured usage).
