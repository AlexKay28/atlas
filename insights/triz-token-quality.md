# TRIZ Analysis: The Token-Quality Contradiction in TAHOE

> Applied 2026-09-14 (skill: alexkay/triz) to the session's central problem:
> structured reasoning that verifies costs tokens; cheap reasoning doesn't verify.
> While the prompt-ablation runs. Loop followed in writing per the skill.

## 1. Sharpen the contradictions

**Administrative form**: "TAHOE-VM consumes too many tokens."

**TC1 (the one we fought all session)**:
- Improving **verifiability** (protocol execution across calls, machine-checked steps)
- worsens **token cost** (per-call overhead, double-solving, decomposition granularity loss)

**PC1**: *The reasoning must be DECOMPOSED (for verification, Markov steps, process
rewards) and UNDECOMPOSED (for holistic quality, zero call overhead) at the same time.*

**TC2**: improving token economy (`reasoning_effort=low`) worsens answer quality
(shallow steps). **TC3**: improving verifiability (typed refs ≤ 25 words) worsens
expressiveness (logic chains don't fit). **TC4 (Stage 1's resolved TC)**: improving
quality (more reasoning) worsens cost — the skill prompt dissolved this one:
structure = both better AND cheaper.

## 2. IFR

"The model reasons with full structure and machine verification **by itself** —
without extra calls, without extra tokens, without new machinery."

**Obstacle named**: the verification layer lives OUTSIDE the generation, so we
made generation pay for it — a second call per step, and a second solving pass.
That is the real problem, and it is a *placement* problem, not a cost problem.

## 3. Resources already on site (free solutions hiding here)

| Resource | Status |
|---|---|
| Static prefix caching (input side ≈ free) | used |
| Deterministic executor (arithmetic = 0 tokens) | used |
| `reasoning_effort` per call | discovered this session |
| **The model's hidden reasoning — generated, paid for, thrown away** | **untapped** |
| Harness-side parsing (real parser, zero tokens) | built for VM, never applied to single-call |
| DONE predicates as offline checks | built, only used in VM loop |
| Stage-1 skill prompt (proven structure) | proven at 63K trials |

## 4. Attack — separations + principles

**Separation in SPACE** (resolves PC1): decomposition lives in the *output
structure*; holism lives *inside the generation*. Each reasoning step gets full
freedom and length — but commits its result as a typed ref line. The verifier
sees only refs; the reasoner sees everything. → Kills the 25-word constraint
that broke LSAT.

**Separation in STRUCTURE** (resolves PC1 from the other side): whole = one
cheap call (holistic); parts = refs *extracted from that same generation*.
→ **Single-call verified TAHOE: keep the Stage-1 skill prompt, change its
output contract so the harness can parse and verify it offline.** The "VM"
becomes an output grammar, not an execution loop. Verification moves to the
harness — zero extra calls, zero extra tokens.

**Separation in TIME**: decompose at t₁ (compile), execute holistically at t₂,
verify at t₃. We built exactly this — and paid per call. TRIZ says this
separation was the expensive one; the space/structure separations dominate.

**Principle hits (concrete applications)**:
- **#7 Nesting**: nest the whole protocol INSIDE one call — the program and its
  execution live in a single generation; the harness un-nests offline.
- **#10 Preliminary action**: compile-time reasoning IS the preliminary action —
  stop discarding it. (In multi-call VM this fixes double-solving by feeding
  reasoning forward; in single-call it's moot — one pass, one reasoning.)
- **#2 Taking out**: extract verification from the model's in-band duties.
  The model never self-checks in tokens; the harness checks for free.
- **#15 Dynamics**: `reasoning_effort` per phase/step = the adjustable parameter.
- **#23 Feedback**: offline parse/DONE verdicts → RL reward (already built).
- **#25 Self-service**: the model services verification with its own emissions —
  the refs it already wrote ARE the check targets.

**Su-Field read of the VM failure**: S1 (model reasoning) —F (per-call
mechanism)— S2 (verification). The field is INSUFFICIENT (cost) and HARMFUL
(granularity loss). Standard solution class: **replace the mechanical field
with an informational one** — output grammar + offline parse gives the same
verification effect at zero marginal tokens.

**AI caveat (skill trap #6)**: check what dissolves the contradiction for free —
`reasoning_effort` control already dissolves TC2 partially; stronger reasoning
models may make VM unnecessary entirely. Don't over-invest in multi-call.

## 5. Verify — does the contradiction disappear?

**The resolved direction: TAHOE as output grammar ("verified skill")**

```
Stage 1 (current):  Q + skill → structured free text → grader checks ANSWER only
Stage 2 (VM):       Q + spec → program → N calls → refs verified per call  ← dead
Stage 1.5 (new):    Q + skill+grammar → ONE call emitting typed refs + DONE line
                    → harness parses/verifies OFFLINE (0 extra tokens)
                    → verdicts become free process labels for RL
```

This dissolves PC1 rather than compromising: generation stays single-call
(Stage-1 economics — 67-267 out tokens), verification is complete and
machine-checked (Stage-2 goal), granularity is the model's choice (LSAT chains
stay long). The remaining question is empirical: does *forcing verifiable
format* onto the skill's output cost quality? Cheap experiment: 2 arms
(tahoe-free vs tahoe-grammar) × existing benches; measure quality, parse rate,
tokens. Parse rate IS the new process-reward signal for Stage 3.

**Adjacent-problem check (ARIZ 7-8)**: the same grammar arm gives us —
trajectory labels at scale without any VM calls, a strictness dial (strict
grammar → lenient), and a natural RL curriculum (reward = answer + parse + DONE).

## 6. Action items

1. Write `benchmarks/tahoe_skill_grammar.txt` — Stage-1 skill + output contract
   (typed refs allowed inline, `DONE OUT.answer = <final>` terminator).
2. Add `tahoe-grammar` arm to the pilot runner; offline verifier in
   `benchmarks/grammar_check.py` (parse refs, DONE, answer extraction).
3. Run 2-arm comparison on gsm8k + lsat (30 samples): quality vs Stage-1
   skill, parse rate, tokens.
4. If quality holds: this becomes the paper's Stage 1.5 — "verified skill" —
   and the Stage-3 RL dataset generator (labels for free).
