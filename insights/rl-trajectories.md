# RL Over Multi-Turn Reasoning Trajectories

> What the RL literature proves about training on step-structured reasoning,
> and why TAHOE's process rewards are a structural advantage. Dated 2026-09-14.

## Let's Verify Step by Step — arXiv:2305.20050 (OpenAI)
- Process supervision (reward each reasoning step) decisively beats outcome
  supervision: **78.2% on MATH** representative subset.
- Cost: **PRM800K — 800,000 human labels** for step-level supervision.
- **→ TAHOE's structural answer:** DONE predicates, parse validation, and
  typecheck give machine-computed step labels for FREE. Every VM trajectory
  self-labels: step passed its predicate or didn't, ref was well-typed or not.
  No PRM training, no annotation. This is the moat.

## RAGEN / StarPO — arXiv:2504.20073
"Understanding Self-Evolution in LLM Agents via Multi-Turn Reinforcement Learning"
- Trajectory-level policy optimization (State-Thinking-Actions-Reward).
- **Key finding: multi-turn agent RL is UNSTABLE** — reward variance, gradient
  spikes, the "echo trap" (model repeats its own hallucinated thoughts).
- StarPO-S stabilizers: trajectory filtering, critic, split clipping.
- **→ Design consequences for us:**
  1. Don't hand-roll the RL loop — use proven frameworks (verl GRPO or
     Agent Lightning).
  2. TAHOE's verifiable steps directly counter the echo trap: a hallucinated
     step FAILS its DONE predicate and gets negative process reward — the
     language grounds the model, exactly what RAGEN says is needed.

## MURPHY — arXiv 2025
"Multi-Turn GRPO for Self Correcting Code Generation"
- Extends GRPO to multi-turn: feedback-conditioned rollout trees +
  trajectory-level credit assignment + cost truncation.
- Up to +8% absolute over baseline GRPO on code benchmarks.
- **Steal:** credit assignment across turns is the crux; our per-step process
  rewards make credit assignment trivial (each step is its own labeled unit).

## FoldGRPO / Context-Folding — arXiv:2510.11967
"Scaling Long-Horizon LLM Agent via Context-Folding"  ← NEAREST COMPETITOR
- Agents RL-trained to **branch into sub-trajectories and fold them** on
  completion, retaining only outcome summaries. Process rewards encourage
  task decomposition and context management.
- **Proof: matches/outperforms ReAct on Deep Research and SWE with 10x
  smaller active context.**
- **What they have:** learned folding behavior (proves folding must be
  REWARDED, not just implemented — include fold-events in our reward).
- **What they lack:** a formal language (ad-hoc behavior), typed refs, verifiable
  DONE predicates, model self-execution, cross-model transferable protocol.
- **Risk:** this group could add a language next — window is months, not years.

## Agent Lightning — arXiv:2508.06722 (Microsoft)
- Decouples ANY agent framework from RL; LightningRL hierarchical credit splits
  arbitrary trajectories into training steps. Pluggable alternative to verl.

## Synthesis for TAHOE-VM RL phase

```
reward(step_i)  = w_parse * parsed_ok            (free — real parser)
                + w_type  * typecheck_ok          (free — real typecheck)
                + w_done  * done_predicate_ok     (free — language semantics)
reward(episode) = grader(final_answer)            (frozen bench graders)
                − λ * total_tokens                (L1-style length control)
```
Trainer: verl GRPO (control, existing experiments skill + Eliza GPUs), with
StarPO-S stabilizers if instability appears. Folding events get bonus process
reward (FoldGRPO lesson). Need-trigger routing emerges from the −λ·tokens term.
