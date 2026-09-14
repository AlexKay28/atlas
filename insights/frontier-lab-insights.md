# Frontier Lab Insights (Anthropic / OpenAI)

> Public engineering research from frontier labs that validates or sharpens
> TAHOE-VM. Dated 2026-09-14.

## Anthropic

### "Code execution with MCP: building more efficient agents" (Nov 2025)
- Agents that write CODE orchestrating tool calls (vs direct tool calls) cut
  tokens **150K → 2K (98.7%)** in their worked example.
- Mechanism: direct tool calls drag tool definitions + intermediate results
  through context; code execution keeps data in the runtime, model sees only
  relevant results.
- **→ External validation of our token thesis.** The harness-bloat trap is real
  and measured. Our difference: their program is Python for tool orchestration;
  ours is a typed reasoning language with verifiable DONE predicates — which
  makes the same trick RL-trainable.

### "Effective context engineering for AI agents" (Sep 2025)
- Three mechanisms, all mapping onto TAHOE-VM constructs:
  | Anthropic term | TAHOE-VM construct |
  |---|---|
  | Compaction (summarize + restart) | Folding subcall contexts |
  | Structured note-taking (memory tool) | Typed ref table |
  | Sub-agent architectures (isolated contexts) | Atomic self-subcalls |
- Their version: ad-hoc engineering advice. Ours: language constructs
  (`RETIRE`, refs, step isolation) — formalized and RL-trainable.

### "Building effective agents" (Dec 2024)
- Core caution: **workflows** (deterministic scaffolds) for predictable tasks;
  free-form **agents** for open-ended; simplest thing that works.
- **→ Maps to need-trigger:** TAHOE-VM is a workflow MODE. The RL phase's job
  is learning when to route into it. Rule 15 becomes a trained policy.

## OpenAI

### Structured Outputs / strict mode
- Grammar-constrained decoding guarantees **100% schema adherence** — the model
  physically cannot emit invalid output for the declared schema.
- **→ Production path for ref emission:** if the serving stack supports it,
  every interpreter step is parse-guaranteed and the repair loop disappears.
  Our Eliza endpoint doesn't expose it → parse-validate-retry stays the
  fallback; cite as the deployment path in the paper.

### The o-series bet (internalized reasoning)
- OpenAI trains reasoning INTO weights (CoT as internal workspace, not
  inspectable).
- **→ Strategic framing:** OpenAI internalizes the protocol; TAHOE externalizes
  it. Externalization wins when (a) the model can't be retrained, (b) verifiable
  process rewards are needed, (c) long-horizon state must survive context limits.
- **Our cross-model data supports the substitution hypothesis:** reasoning-native
  gpt-oss-120b benefits less from the TAHOE skill (32% token savings) than
  verbose-narrative GLM-5.3-Flash (49%) — internalized and external protocols
  partially substitute.

## Net effect on design

| Lab insight | Decision it confirms |
|---|---|
| Anthropic 98.7% code-exec savings | Program-mediated execution is the right shape |
| Compaction / note-taking / sub-agents | Folding + ref table + step isolation as LANGUAGE constructs |
| Workflows-vs-agents caution | Need-trigger routing must be first-class (RL learns it) |
| OpenAI constrained decoding | Static prefix + grammar-gated refs = production path |
| o-series internalization | Long-horizon is our territory; single-shot edge will shrink |
