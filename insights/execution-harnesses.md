# Execution Harnesses: Plan-Then-Execute Lineage

> What the published harness literature proves, what to steal, what differs
> from TAHOE-VM. Dated 2026-09-14. All numbers from paper abstracts (verified).

## ReWOO — arXiv:2305.18323
"Decoupling Reasoning from Observations for Efficient Augmented Language Models"
- Planner emits plan with **variable substitution** → workers fill variables →
  solver reads only results. Reasoning fully decoupled from tool observations.
- **Proof: 5x token efficiency, +4% accuracy on HotpotQA.** Offloaded reasoning
  from 175B GPT-3.5 into 7B LLaMA.
- **Steal:** variable refs instead of resending context = the anti-context-growth
  trick (TAHOE typed refs already do this).
- **Differs:** plan is untyped text; harness is Python; model never executes its
  own plan; no RL story.

## LLMCompiler — arXiv:2312.04511
"An LLM Compiler for Parallel Function Calling"
- LLM emits a DAG of function calls; task-fetching unit + parallel executor.
- **Proof: 3.7x speedup, 6.7x cost reduction, +9% accuracy vs ReAct;**
  1.35x vs OpenAI native parallel calling.
- **Steal:** the cost win comes from FEWER LLM invocations, not smaller ones —
  validates batching multiple steps per call. TAHOE language already has
  PAR/TRY for DAG structure.
- **Differs:** nodes are tool calls, not reasoning steps; no typed semantic state.

## StateFlow — arXiv:2403.11322
"Enhancing LLM Task-Solving through State-Driven Workflows"
- Task-solving as explicit state machine; separates "process grounding"
  (states/transitions) from "sub-task solving" (actions within a state).
- **Proof: +13-28% success vs ReAct at 3-5x lower cost** (InterCode SQL, ALFWorld).
- **Steal:** the vocabulary — the TAHOE coordinator already IS a state machine;
  formal-semantics.md documents its transition rules.
- **Differs:** states hand-designed by engineers, not model-emitted programs.

## CodeAct — arXiv:2402.01030
"Executable Code Actions Elicit Better LLM Agents"
- Code as the single unified action space beats many narrow JSON tools.
- **Steal:** one rich action space; supports making TAHOE deterministic steps
  plain Python execution.

## SGLang — arXiv:2312.07104
"Efficient Execution of Structured Language Model Programs"
- Programming primitives (gen/select/fork) + RadixAttention (KV cache reuse)
  + FSM-constrained decoding for structured output.
- **Steal (two production levers):** static prefixes become nearly free via
  KV/prefix reuse (verified live on our Eliza endpoint: cached_tokens in usage);
  ref emission can be grammar-guaranteed via constrained decoding.
- **Differs:** SGLang constrains decoding, has no semantic reasoning state.

## PAL — arXiv:2211.10435
"Program-aided Language Models"
- Model writes a program; EXTERNAL Python interpreter executes it.
- The opposite pole of TAHOE-VM: never self-executes. Confirms the spectrum:
  harness-executed (PAL/ReWOO/LLMCompiler) ←→ self-executed (TAHOE-VM).

## TapeAgents — arXiv:2410.01062
"A Holistic Framework for Agent Development and Optimization" (ServiceNow)
- Agent session = structured, replayable tape; every step logged; tapes can be
  resumed, inspected, and **directly converted into training data**.
- **Steal:** trajectory-as-artifact. The TAHOE event store is already
  tape-shaped — make RL export a first-class artifact, not an afterthought.

## Agent Lightning — arXiv:2508.06722 (Microsoft, 2025)
"Train ANY AI Agents with Reinforcement Learning"
- Fully decouples agent execution from RL training; LightningRL hierarchical
  credit assignment splits arbitrary agent trajectories into training steps.
- Works with LangChain / OpenAI SDK / AutoGen unchanged.
- **Implication:** we may not need a custom RL loop — TAHOE-VM mode can plug in
  as a client. Alternative to verl GRPO (we lean verl for control + existing infra).

## DSPy — arXiv:2310.03714
- Programs-over-prompts; compile-time prompt optimization.
- **Differs:** optimizes prompt text at compile time; no execution-time typed
  state, no self-execution, no verifiable steps.
