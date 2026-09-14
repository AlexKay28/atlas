# Token Economics of TAHOE-VM (Our Analysis)

> The hard constraint: token consumption must go DOWN. Harnesses usually
> increase it. Dated 2026-09-14. All baselines measured in this repo.

## The trap, quantified

Naive 1-step-1-call VM overhead per subcall:
```
per subcall = sys(~50) + step line(~25) + ref slice(~20-50) + model output(~30-60)
             ≈ 145-185 tokens
6-step program ≈ 1,100-1,300 total
```
Measured baselines (full test sets, GLM-5.3-Flash):
```
classic      ≈ 246 avg output tokens
prompt-tahoe ≈ 125 avg output tokens
```
**Naive VM = ~5-10x token REGRESSION on easy tasks.** Every ReAct-style
harness dies exactly here. This constraint killed the naive design and forced
the four levers below.

## The four levers

### 1. Refs are cheap; prose is expensive — the language saves what the harness spends
Classic burns ~246 output tokens on narration ("Well, let me think...").
A TAHOE step emission is a ref line: `E.minutes = 90` — 5-15 tokens.
```
net = verbosity_saved − calls × 145
break-even ≈ classic ≥ 400 output tokens/task
```
LSAT (432 avg) and BBH (472) are at or above break-even; GSM8K easy items are
below it → need-trigger must route those away (learned in RL).

### 2. Deterministic steps cost ZERO model tokens
`calculate/check/choose/rank` execute locally (DeterministicStepExecutor,
driver.py — built in issue #61). A GSM8K program: 1 LLM call to emit the
program (~150 tok — this IS the compressed reasoning) + 0 for compute steps +
1 tiny final emission ≈ 200 model tokens.

### 3. Prefix caching makes scaffolding nearly free
Verified live on the Eliza endpoint: `usage.prompt_tokens_details.cached_tokens`
is populated. If the interpreter prefix (system + protocol header) is
byte-identical static text, every subcall after the first hits the cache —
input tokens for steps 2..N cost ~nothing. Implementation rule: static
interpreter prefix, dynamic step suffix only. (SGLang's RadixAttention is the
same lever at serving depth.)

### 4. RL learns the need-trigger — the real token reduction
The VM is not for every task; it's a MODE the model routes into.
Reward = quality − λ·tokens makes Rule 15 (need-trigger) LEARNED behavior:
trivial task → direct answer; medium → program + batching; hard/long-horizon
→ full VM. L1/LCPO proved length/routing is RL-learnable.

## Where VM genuinely wins on tokens (honest table)

| Task class | Classic context | VM context | Token verdict |
|---|---|---|---|
| Single-shot easy (GSM8K avg) | 241 out | ~200 model tokens | parity (RL: route away) |
| Single-shot verbose (LSAT/BBH) | 432-472 out | ~400-500 | parity-ish |
| **Multi-turn / long-horizon** | **history re-sent every turn → quadratic growth** | **flat: program + ref table only** | **2-5x, compounds** |
| Retry-heavy (backtrack) | full CoT re-sent | re-execute one step; refs unchanged | step-level repair = pennies |

Single-shot benchmarks prove protocol CORRECTNESS; the token-reduction headline
for VM lives in long-horizon settings where growing context is the enemy
(multi-turn eval infra from issue #91 measures this).

## Hard gates for the pilot (kill-switches)

```
GATE 1: VM tokens ≤ prompt-tahoe tokens on ≥2 of 3 pilot benches
GATE 2: context growth O(refs), not O(history) — measured, not assumed
If either fails → redesign (batching, program size, prefix shape) — not thresholds.
```

## Measured fix (2026-09-14): reasoning_effort kills the thinking burn

Token anatomy on a lean gsm8k episode (compile + 1 step): compile burned
955 output tokens (hidden reasoning solving the task it was only supposed to
structure), step subcall 133. The A/B on 10 gsm8k episodes (GLM-5.3-Flash):

| Config | Episodes OK | Passed | avg in | avg out | wall/ep |
|---|---|---|---|---|---|
| no effort param | 9/10 | 5/10 | 1,216 | 2,655 | 13.2s |
| **reasoning_effort=low (steps + compile)** | 7/10 | **5/10** | **948** | **300** | **1.9s** |
| step=low, compile=default | 4/10 | 4/10 | 729 | 440 | 2.5s |

**8.9x output-token reduction at identical pass rate, 7x faster.** The
`reasoning_effort` API param (2026-standard, verified live on Eliza GLM:
30 → 6 completion tokens on trivial queries) is the single biggest
prompted-VM cost lever. Stage-3 RL can treat effort as a per-step action:
the policy learns which steps deserve thinking.

Remaining gap vs prompt-tahoe (70 out tokens on gsm8k): VM/low ≈ 4.3x —
the compile call floor (~300-400 out even at low effort) is the irreducible
per-episode cost. Need-trigger routing (Stage 3) decides when that floor
buys enough verifiability to be worth it.
