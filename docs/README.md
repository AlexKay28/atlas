# TAHOE Documentation

This documentation defines a compact language and a set of operating protocols for
high-quality human-AI thinking with less repeated context and lower token consumption.

The objective is not to make every message as short as possible. The objective is to
minimize **total cost to a verified result**:

```text
total_cost = input_tokens + output_tokens + clarification + rework + error_cost
```

A short prompt that causes an incorrect answer or several repair turns is less
efficient than a slightly longer prompt that produces a correct, verifiable result.

## Document Map

| Document | Purpose |
| --- | --- |
| [ADR-0001](adr/0001-ai-thinking-language.md) | Architectural decision and core vocabulary |
| [ADR-0002](adr/0002-executable-thinking-language.md) | Executable language, event manager, and worker-agent model |
| [ADR-0003](adr/0003-live-text-harness.md) | Live text authoring, execution gates, and tiered workers |
| [Smart Thinking Rules](language/01-smart-thinking-rules.md) | General rules for framing and solving problems |
| [Token Economy](language/02-token-economy.md) | Reduce context and output without losing meaning |
| [Reasoning Protocols](language/03-reasoning-protocols.md) | Reusable procedures for common task classes |
| [Graph Construction](language/04-graph-construction.md) | Convert thoughts into useful nodes and links |
| [Quality Control](language/05-quality-control.md) | Preserve correctness, evidence, and safety |
| [Personal Profile](language/06-personal-profile.md) | Convert personal thinking habits into protocol rules |
| [Enhancement Plan](PLAN.md) | Prioritized path from ADRs to a working runtime |
| [Related Systems](research/related-systems.md) | External inspirations and explicitly adopted ideas |
| [Reasoning Language Foundation](design/01-reasoning-language-foundation.md) | Design thesis, source-to-mechanism mapping, falsifiable experiment register, notation policy, and non-goals |
| [CLI Reference](cli-reference.md) | CLI subcommand catalog with required flags and purposes |
| [Language and State](spec/01-language-and-state.md) | Canonical syntax, expressions, artifacts, memory, and deltas |
| [Command Catalog](spec/02-command-catalog.md) | Atomic command contracts and standard operations |
| [Runtime and Events](spec/03-runtime-and-events.md) | Lifecycle, replay, retries, approval, and concurrency |
| [Completeness](spec/04-completeness.md) | Developer-work matrix and reference programs |
| [Live Authoring](spec/05-live-authoring-and-routing.md) | Draft/seal/run gates and quality-preserving model routing |
| [Text Harness Precedents](research/text-harness-precedents.md) | Live-document and AI-language comparisons |

## CLI Quickstart

Install the package and run the sealed example:

```bash
python3 -m pip install .
tahoe lint examples/demo.think
seal=$(tahoe seal examples/demo.think)
tahoe run examples/demo.think --db demo.db --run-id demo-1 --seal "$seal"
tahoe status --db demo.db --run-id demo-1
tahoe events --db demo.db --run-id demo-1
```

`run` rejects a missing or stale seal before creating a run. The SQLite event
store can then reconstruct both graph state and the session task ledger.

## Recommended Reading Order

1. Read ADR-0001 for graph semantics and ADR-0002 for executable semantics.
2. Read ADR-0003 for the live text-harness and model-tier boundary.
3. Use Smart Thinking Rules as the default operating model.
4. Apply Token Economy when preparing a prompt or response.
5. Select one Reasoning Protocol for the current task.
6. Use Graph Construction when dependencies or branches become complex.
7. Read the five specifications before implementing an interpreter or worker.
8. Run Quality Control before accepting an important result.
9. Complete Personal Profile only after observing real working sessions.

## Minimal Daily Use

For ordinary tasks, use this compact request envelope:

```text
G: <desired outcome>
C: <hard boundaries>
CTX: <only facts that can change the result>
ASK: <operation the AI should perform>
OUT: <required artifact and detail level>
V: <how success will be checked>
BUDGET: <optional time, token, or cost bound>
```

Add `A` for assumptions, `U` for unknowns, and `D` for decisions only when needed.
Complex tasks should use one of the protocols described in this documentation.

## Governing Principle

Structure is valuable only when it removes ambiguity, repetition, or rework. Do not
encode casual conversation as a graph when ordinary language is faster and equally
reliable.
