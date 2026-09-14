# Token-Efficient Reasoning: The Training-Target Literature

> The field already trains models to reason shorter. TAHOE's angle: the
> language does it without training, RL then optimizes routing. Dated 2026-09-14.

## Chain of Draft — arXiv:2502.18600
"Thinking Faster by Writing Less"
- Concise intermediate drafts (≤5 words per step) instead of verbose CoT.
- **Proof: matches/exceeds CoT accuracy using 7.6% of the tokens.**
- **Implication:** brevity alone captures most of the win on standard benchmarks.
  Our E13 experiment (run_e13_cod_parity.py) tests exactly this baseline —
  TAHOE must beat CoD to prove STRUCTURE > BREVITY.
- **Differs:** no typed state, no verifiability, no protocol selection —
  it's compression without structure.

## L1 / LCPO — arXiv:2503.04697
"Controlling How Long A Reasoning Model Thinks With Reinforcement Learning"
- Length-Controlled Policy Optimization: reward shaping makes the model produce
  reasoning of a TARGET length given in the prompt.
- **Proof: L1 beats GPT-4o at equivalent reasoning lengths.**
- **→ Direct precedent for our reward = quality − λ·tokens.** Length is not just
  controllable, it's a policy variable. Supports treating need-trigger routing
  (when to enter VM mode) as learnable.

## CoT-Valve — arXiv:2501.12570
- A tunable knob for reasoning-chain length; compress long chains progressively.
- Confirms chain length is a manipulable dimension post-training.

## TALE — arXiv:2412.18547
"Token-Budget-Aware LLM Reasoning"
- Estimate a token budget BEFORE solving; prompt the model to stay within it.
- **Steal:** program-level token budgets map naturally onto TAHOE's Budget
  fields (enforced in runtime since issue #85) — the VM can pass a budget into
  the reward and into the interpreter prompt.

## Stop Overthinking — arXiv:2503.16419 (survey)
"A Survey on Efficient Reasoning for Large Language Models"
- Taxonomy of efficiency methods:
  1. **model-based** — train shorter/faster reasoners
  2. **reasoning-output-based** — dynamically cut/shorten during inference
  3. **prompt-based** — efficiency via prompt properties (CoD lives here)
- **Our lane is a 4th category they don't name: PROTOCOL-based** — a typed
  reasoning language that structurally produces short reasoning, plus RL
  routing into it. Unoccupied in their taxonomy = good paper positioning.

## Kimi k1.5 long2short (industry)
- RL stage specifically to shorten long-CoT into short-CoT with retained
  accuracy. Confirms frontier labs treat token length as a first-class
  training objective.

## Synthesis

The literature proves: (a) brevity alone gets ~92% of the way on standard
benchmarks (CoD), (b) length is RL-controllable (L1, CoT-Valve, Kimi),
(c) budgets can be declared upfront (TALE). What is missing: a STRUCTURED
language where brevity comes from typed refs rather than vague conciseness —
giving verifiable steps for free and letting RL optimize not just length but
WHEN structured execution pays at all.
