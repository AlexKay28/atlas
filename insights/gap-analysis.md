# Gap Analysis: Where TAHOE-VM Sits and What Could Kill It

> Dated 2026-09-14, after deep arxiv/web sweep. All competitor claims verified
> against paper abstracts.

## Capability matrix

| Capability | ReWOO (2305.18323) | LLMCompiler (2312.04511) | RoT (2306.06891) | FoldGRPO (2510.11967) | Chain of Draft (2502.18600) | **TAHOE-VM** |
|---|---|---|---|---|---|---|
| Typed program language | ✗ | ✗ | ✗ | ✗ | ✗ | **✓** (parser+typecheck exist) |
| Free machine-verified process rewards | ✗ | ✗ | ✗ | partial | ✗ | **✓** (DONE predicates) |
| Model executes own program | ✗ | ✗ | partial | ✗ | ✗ | **✓** |
| Sparse context | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ (O(refs)) |
| Transferable protocol (model-agnostic) | ✗ | ✗ | ✗ | ✗ | ✓ | **✓** (proven, 2 models) |
| Token reduction as objective | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ |
| One RL trajectory | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ |
| Deterministic steps = 0 model tokens | ✗ | ✗ | ✗ | ✗ | ✗ | **✓** |

## The novelty statement (paper-ready)

> No published system combines: (1) a typed reasoning language with
> machine-checkable semantics — making step-level process rewards FREE where
> the state of the art needed 800K human labels (PRM800K); (2) the model as
> interpreter of its own emitted program via atomic self-subcalls (Recursion
> of Thought showed self-subcalls work, but with no language, types, or
> verification); (3) context that grows O(refs) instead of O(history)
> (FoldGRPO learned ad-hoc folding with RL — we express it as language
> semantics); and (4) token economy as a first-class language property,
> transferable across models via a 93-token skill (proven on 63,348 trials).

## Risk register

| Risk | Source | Mitigation |
|---|---|---|
| Multi-turn RL instability (echo trap, gradient spikes) | RAGEN/StarPO 2504.20073 | Use verl GRPO + StarPO-S stabilizers; our verifiable steps ground the model (hallucinated step → predicate fails → negative reward) |
| Token overhead on easy tasks | Our own accounting (token-economics.md) | Need-trigger routing learned via −λ·tokens; L1 proves routing is learnable; deterministic steps + prefix caching cut overhead |
| Self-execution fidelity (model mis-executes steps) | RoT-era concern | Parse-validate-retry bounds damage; modern models far stronger than GPT-3; typed refs give explicit state |
| **Being scooped** | FoldGRPO group (2510.11967, Oct 2025) — one step from adding a language | Window ~6 months; pilot gates are fast; paper positioning already drafted |
| Protocol doesn't fix model limits | Apple "Illusion of Thinking" (2506.06941) | Honest scoping: MATH 0% both arms in pilots; claim compression + verification, not capability creation |
| Over-engineering | Anthropic "Building effective agents" | Need-trigger as learned policy; VM is a mode, not a mandate |

## What "done" looks like

Stage 2 gate passes (tokens ≤ prompt-tahoe, context O(refs)) →
Stage 3 shows RL-VM > prompted-VM on HM →
paper positions against the matrix above with the free-process-reward story
as the headline.
