# WORKLOG — sprint1-43-telemetry

Seal: 5053afe18472cb7b109553c35231a63ca7b9d3dc1697409ab04d2799d2486689
Program: demo/runs/sprint1-43-telemetry/program.think (linted valid and sealed before any source edit)

## step.frame
Status: succeeded
Inputs: G.goal, C.scope, C.done from program.think INPUT block
Actions: Framed issue #43 into the task: widen the transport seam in worker_adapter.py so transport callables may return either a bare str (legacy) or a TransportResult(text, usage) dataclass; ModelWorker.execute maps non-None usage into the receipt; str-returning transports keep tokens/cost None.
Outputs: G.plan = the implementation plan.
Evidence: gh issue view 43; issue body describes the closed seam (Transport = Callable[[str, str], str], no usage channel) and the fix (TransportResult with text + usage).

## step.locate
Status: succeeded
Inputs: G.plan, C.scope
Actions: Located the integration points: (1) Transport type alias at worker_adapter.py:64 (was Callable[[str, str], str]); (2) execute() at line 188 calls self._transport(model, prompt) and stores result in `raw`; (3) _build_result_envelope at line 290 hardcodes usage tokens/cost to None at lines 315-318; (4) _parse_response at line 331 checks isinstance(raw, str); (5) downstream consumer _recorded_usage in envelope.py:1290-1310 already reads receipt["usage"]["tokens"] and receipt["usage"]["cost"] — no envelope changes needed.
Outputs: E.sites = the integration points above.
Evidence: src/tikhon/worker_adapter.py (full read, 345 lines); src/tikhon/envelope.py:1290-1310 (read-only).

## step.read
Status: succeeded
Inputs: E.sites
Actions: Read the full worker_adapter.py (345 lines), the full test_worker_adapter.py (536 lines, 25 existing tests), and the envelope.py usage consumer (lines 1290-1310, read-only). Confirmed: (a) _recorded_usage already handles int tokens via isinstance check; (b) existing tests use `recording_transport` helper returning bare str; (c) the _parse_response method's isinstance(raw, str) guard handles the non-string error case.
Outputs: ART.sources = the read sources.
Evidence: files listed in C.scope plus envelope.py (read-only).

## step.analyze
Status: succeeded
Inputs: ART.sources
Actions: Designed the minimal diff: (1) Add TransportResult dataclass with text:str + usage:dict|None fields; (2) Widen Transport type alias to Callable[[str, str], "str | TransportResult"]; (3) Add _unwrap_transport method that splits raw into (text, usage) — TransportResult returns (result.text, result.usage), everything else returns (raw, None); (4) Update execute() to call _unwrap_transport and pass usage to _build_result_envelope; (5) Update _build_result_envelope signature to accept usage param and map integer tokens from usage dict into receipt; (6) Update module docstring with seam contract note; (7) Update __all__ to export TransportResult.
Outputs: E.findings = the design above.
Evidence: this analysis; each design point verified against the source.

## step.design
Status: succeeded
Inputs: E.findings
Actions: Summarized the design into the implementation plan: TransportResult is a frozen-style dataclass (using @dataclasses.dataclass), the _unwrap_transport method is the single unwrapping point (so _parse_response still receives a str), the token extraction uses isinstance(value, int) and not isinstance(value, bool) guard to match envelope._recorded_usage's _int helper, and cost stays None (no price table configured).
Outputs: P.design = the implementation plan.
Evidence: design analysis above.

## step.implement
Status: succeeded
Inputs: P.design
Actions: Applied the patch to src/tikhon/worker_adapter.py: (1) Updated module docstring with issue #43 transport seam contract (transport may return str | TransportResult; execute maps usage tokens into receipt; CLI HTTP transport wiring described); (2) Added TransportResult dataclass (text: str, usage: dict | None = None); (3) Widened Transport type alias; (4) Updated __all__ to include TransportResult; (5) Added _unwrap_transport method; (6) Updated execute() to call _unwrap_transport and pass usage to _build_result_envelope; (7) Updated _build_result_envelope signature + body to extract integer tokens from usage dict; (8) Updated WorkerError call in execute() target mapping to use raw_text directly.
Outputs: ART.patch = src/tikhon/worker_adapter.py (modified).
Evidence: git diff src/tikhon/worker_adapter.py shows the changes.

## step.test_write
Status: succeeded
Inputs: P.design
Actions: Added 6 tests to tests/test_worker_adapter.py: (1) test_transport_result_carries_usage_tokens_into_receipt — TransportResult(text, {"tokens": 123}) → receipt tokens == 123; (2) test_legacy_str_transport_yields_none_tokens — legacy str → receipt tokens None; (3) test_transport_result_with_none_usage_yields_none_tokens — TransportResult with usage=None; (4) test_transport_result_with_non_integer_tokens_yields_none — non-int tokens ignored; (5) test_transport_result_payload_parsed_correctly — text parsed as JSON + tokens mapped; (6) test_transport_result_with_json_fence_stripped — fence stripping still works with TransportResult.
Outputs: ART.tests = tests/test_worker_adapter.py (modified, +6 tests).
Evidence: git diff tests/test_worker_adapter.py shows the new tests.

## step.test_run
Status: succeeded
Inputs: ART.tests
Actions: Ran the full test suite: PYTHONPATH=src python3 -m pytest -q
Outputs: V.tests = 766 passed (760 baseline + 6 new) in 20.68s.
Evidence: pytest output: 766 passed in 20.68s.

## step.check
Status: succeeded
Inputs: V.tests
Actions: Verified: (a) full suite green at 766 passed; (b) all 6 new tests pass; (c) all 760 baseline tests pass unmodified; (d) git status --porcelain shows only owned files (worker_adapter.py, test_worker_adapter.py, demo/runs/sprint1-43-telemetry/).
Outputs: V.verdict = suite green, only owned files touched.
Evidence: pytest -q → 766 passed; git status --porcelain → M worker_adapter.py, M test_worker_adapter.py, ?? demo/runs/sprint1-43-telemetry/.

## step.report
Status: succeeded
Inputs: P.design
Actions: Rendered the run report (solution.md) with: files changed, tests added + final count, acceptance evidence, cli.py wiring instructions.
Outputs: OUT.solution = solution.md.
Evidence: demo/runs/sprint1-43-telemetry/solution.md.

## step.verify
Status: succeeded
Inputs: G.goal, V.verdict
Actions: Verified every acceptance criterion: (1) TransportResult(text, {"tokens": 123}) → receipt tokens == 123 ✓; (2) legacy str → receipt tokens None ✓; (3) existing adapter tests pass ✓ (all 25 pre-existing tests pass); (4) full suite 766 passed ✓; (5) only owned files touched ✓.
Outputs: V.result = all acceptance criteria passed.
Evidence: pytest output, git status --porcelain, individual test assertions.
