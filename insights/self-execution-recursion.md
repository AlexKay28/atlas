# Self-Execution and Recursion: Closest Precedents

> The literature on models calling themselves into fresh contexts — the
> mechanism TAHOE-VM relies on. Dated 2026-09-14.

## Recursion of Thought — arXiv:2306.06891 (Lee & Kim)
"A Divide-and-Conquer Approach to Multi-Context Reasoning with Language Models"
- Special tokens (THINK/RETURN) let the model **spawn sub-contexts recursively**:
  mid-reasoning it emits THINK, the harness opens a FRESH context window for the
  subproblem, solves it, returns the result into the parent context.
- **Proof: solves problems requiring hundreds of thousands of tokens** on
  GPT-3-era models — models far too weak to hold such problems in context.
- **The existence proof for TAHOE-VM's core mechanism:** models CAN reliably
  self-subcall into fresh contexts.
- **Differs:** no program language, no typed state, no protocols, no RL,
  hand-crafted trigger tokens. Decomposition is ad-hoc, not a compiled artifact.

## LAMBADA — arXiv:2211.02010 (Kazemi et al.)
"Backward Chaining for Automated Reasoning in Natural Language"
- Solve the goal by recursively deriving subgoal modules backward; each module
  solved by a separate LLM call with its own context.
- **Steal:** recursive modular decomposition with per-module fresh contexts.
- **Differs:** backward chaining only; no forward program; untyped.

## Least-to-Most — arXiv:2205.10625
- Decompose into a sequence of subproblems of increasing complexity; each
  sub-answer is fed forward into the next subproblem's context.
- **Steal:** decomposition granularity drives BOTH accuracy and context size —
  the dial TAHOE protocols (Compute/Select/Deduce) set explicitly.
- **Differs:** sequential only; no parallelism; no typed refs.

## Atom of Thoughts (AOT) — arXiv 2025
"Atom of Thoughts for Markov LLM Test-Time Scaling"
- Reasoning trajectories decompose into **Markov-atomic units**: each unit
  depends only on its immediately available state, not the full history.
- **→ The theoretical validation of state-slice subcalls:** if steps are
  Markov-atomic, each subcall needs ONLY its ref slice — exactly the TAHOE-VM
  context injection model. Our typed refs make the Markov state explicit.

## Synthesis

The self-execution idea has a 2023 pedigree (RoT) that predates tool-calling
agents. What was missing then — and what TAHOE adds now:
1. A real language the program is written in (parser, typecheck, semantics)
2. Typed refs as the explicit Markov state between subcalls
3. Machine-verified steps (DONE predicates) instead of trusting the model
4. The whole recursive execution being ONE RL-trainable trajectory
