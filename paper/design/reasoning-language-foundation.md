# Reasoning Language Foundation

- Status: Draft 0.1
- Source: issue #17 (design and research); implementation sequencing lives in #16
- Scope: design thesis, source-to-mechanism mapping, falsifiable experiment register,
  notation policy, and non-goals. Claims about current behavior are checked against
  `src/` and cited by path.

## 1. Design Thesis

TAHOE optimizes **useful reasoning per token**, not visual brevity. A compact trace
that omits a distinction the runtime needs — observation vs assumption vs derivation, or
`motivated-by` vs entailment — is a failure even when it is short. Three commitments
follow:

1. **Preserve decision-relevant distinctions.** The state namespace already separates
   observation (`E.*`), hypothesis (`H.*`), assumption (`A.*`), decision (`D.*`), and
   verification (`V.*`) as typed references (`src/tahoe/syntax/parser.py:19`). This
   separation is the payload of the language; compression must never merge it.
2. **Expand difficult steps on demand.** Compact form is the default, but every compact
   construct has a recoverable expanded form: a `CALL protocol.x` line expands to the
   protocol file it names (`protocols/framing.think`), a `DONE matched(...)` predicate
   expands to the criteria text the worker was given, and a sealed program expands to its
   event log via replay.
3. **Historical inspiration is not evidence.** Every mechanism borrowed below becomes a
   numbered, falsifiable experiment before any grammar change. The experiment register in
   §3 is the contract; nothing lands in `src/` without its experiment.

The runtime's role is fixed: it owns state, evidence, validation, and measurement around
model-interpreted operations. The LLM owns judgment inside command contracts. Nothing in
this document changes that boundary.

## 2. Mechanism Table

One row per source in issue #17. "Exists" means the construct is implemented today with
the cited file; "motivates" means a new construct this source argues for, with a syntax
sketch in the implemented grammar style (see `docs/spec/01-language-and-state.md` for the
full canonical sketch; SCATTER/GATHER and envelopes are planned via issues #4 and #18 and
marked as such).

| # | Source | Mechanism borrowed | Maps onto TAHOE | Syntax sketch |
| --- | --- | --- | --- | --- |
| 1 | Iverson, *Notation as a Tool of Thought* (1980) | Composability, economy, suggestiveness; subordinating detail with recoverable definitions | Exists: commands compose through typed refs (`step.x: DO hypothesize(evidence = E.m) -> H.c`); `DONE` predicates subordinate detail (`DONE count(H.c) >= 2`, `src/tahoe/syntax/parser.py:590-647`) | New compact forms only with recoverable expansion, e.g. `DONE every(H.c, has("falsifier"))`; each alias documented with its expanded reading, adopted only after E1 |
| 2 | Leibniz, *characteristica universalis / calculus ratiocinator* (17th c.) | Separate representation of claims from operations on them | Exists: three namespaces — uppercase keywords (`IF`, `DONE`, `CALL`), lowercase commands (`hypothesize`, `verify`), typed refs (`H.*`, `E.*`) (`docs/spec/01-language-and-state.md:13-17`) | Claims stay in typed state; control stays keyword-only. Motivates a lint rule rejecting control logic smuggled into argument prose |
| 3 | Pospelov, *Ситуационное управление* (1986); semiotic models | Situation recognition selects applicable knowledge/action without a complete fixed model; representations are revisable | Exists: single-line `IF <cond> <stmt>` selects actions from committed state (`==`,`!=`,`count()`,`AND`,`OR`,`NOT`; no parentheses, `src/tahoe/syntax/parser.py:263-289`); `REVISE`/`RETIRE` clause revises the situation (`parser.py:29-41`) | Planned conditional re-planning step: `IF count(E.tests) == 0 DO decompose(goal = G.goal, protocol = "replan") -> G.plan2` |
| 4 | Turchin, Refal / supercompilation, *The Phenomenon of Science* (1977) | Specialize general processes into named abstractions with preserved applicability conditions | Exists: `CALL protocol.name(args) -> targets` loads `protocols/<name>.think`, expands inline, bounded depth 8, no recursion (`src/tahoe/syntax/parser.py:50-54`, `src/tahoe/runtime/coordinator.py:57-67`, `protocols/framing.think`) | Motivates protocol specialization: a general `protocol.diagnose` variant pinned to a task family with applicability stated in its INPUT block and checked before expansion |
| 5 | Vygotsky, *Мышление и речь* (1934) | Compact expression depends on shared context and recoverable references; emit updates, not re-narration | Exists: typed refs are the recoverable context; cross-run `KB.*` memory via `remember`/`recall` (`src/tahoe/memory.py`); event log replays full state (`src/tahoe/runtime/events.py`) | No new syntax. E5 tests whether ref-based updates survive truncation/handoff better than prose narration |
| 6 | McCarthy, *Programs with Common Sense* (1959), Advice Taker | Declarative goals, constraints, knowledge; partially specified problems | Exists: `INPUT` block declares `G.*` goals and `C.*` constraints before any step; `STOP unresolved(D.x)` terminates on undischarged goals (`parser.py:43,63`) | Motivates leaving preconditions partially declared and letting workers gather evidence before the path is fixed |
| 7 | Kowalski, *Algorithm = Logic + Control* (1979) | Separate what the problem is from how the search proceeds | Exists: deterministic control expressions vs worker judgment (`docs/spec/01-language-and-state.md:117-131`); per-command `RoutingPolicy` and `Budget` are control metadata, invisible to semantics (`src/tahoe/registry/spec.py`) | Motivates running identical programs under different `RoutingPolicy` settings and asserting identical committed state |
| 8 | Peirce (abduction); Doyle, TMS (1979); de Kleer, ATMS (1986) | Distinguish observation/assumption/hypothesis/derivation/refutation; track support; on retraction invalidate dependents | Exists: `H.*` hypotheses from `hypothesize`, `challenge` command takes claim + evidence, `RETIRE refs` clause retires conclusions (`parser.py:29-41`); `A.*` assumptions are a reserved type | Motivates explicit dependency links: `RETIRE A.deploy` should mark conclusions that cite it stale; DELTA already carries `retire_nodes` with reasons (`docs/spec/01-language-and-state.md:202-217`) |
| 9 | Russell & Wefald, *Do the Right Thing* (1991) | Computation itself is a decision with cost and expected benefit; cheap tests before expensive exploration | Exists: `Budget` per command (seconds, tokens, cost, attempts, output bytes); tier routing sends cheap checks to T0 executors (`src/tahoe/registry/enums.py:56-64`) | Motivates explicit expand/stop steps: `step.deepen: IF V.review.status == "low" DO challenge(claim = H.cause, evidence = E.tests) -> V.challenge` |
| 10 | Newell, Soar / *Unified Theories of Cognition* (1990) | Impasse → subproblem → resolution → reusable rule, stored with applicability conditions | Exists: failure kinds per command with declared recovery (`FailureSpec`, `src/tahoe/registry/builtins.py`); `tahoe learn` mines recurring command sequences into protocol candidates, review-only promotion (`src/tahoe/learn.py:1-11`) | Motivates storing failure cases next to each promoted protocol in `protocols/` |
| 11 | Ellis et al., DreamCoder (2021) | Solve → mine traces for abstractions → evaluate on held-out data → promote measured improvements | Exists: `tahoe learn` produces `ProtocolCandidate` (support >= 2 distinct programs) and `FailureCluster` reports; nothing self-promotes (`src/tahoe/learn.py`) | Motivates a dev/test split for candidate protocols: promote only on dev improvement, keep a test set untouched |
| 12 | Rissanen, Minimum Description Length (1978) | Charge abstractions for definition, retrieval, ambiguity, and maintenance cost; prefer a small vocabulary | Exists: the builtin registry is frozen at 23 commands v1.0.0 with a stable `registry_digest` recorded at RUN_STARTED (`src/tahoe/registry/builtins.py`, `src/tahoe/runtime/coordinator.py`) | Motivates E12: amortized cost accounting for any new protocol, including prompt overhead of its definition |
| 13 | Xu et al., *Chain of Draft* (2025) | Concise natural-language intermediate reasoning is the mandatory baseline to beat | No syntax change. E13 requires TAHOE to demonstrate value beyond asking the model to be brief; the paper's 7.6%-token result is not a guarantee | Baseline arm in the evaluation harness: same tasks, CoD-style prompt |
| 14 | Pfau, Merrill, Bowman, *Let's Think Dot by Dot* (2024) | Extra tokens can add computation independent of readable content; do not infer ability from visible traces | Exists: runtime measures outcomes and audit checks, never claims to read internal reasoning; `tahoe audit` verifies truthfulness of events only (`src/tahoe/audit.py:133+`) | Motivates difficulty-stratified evaluation and adaptive expansion (shared with row 9 in E9) |
| 15 | Yao et al., ReAct (2022/2023) | Interleave reasoning, action, observation, update; observations carry provenance | Exists: each step is one command with committed targets; external results land as digested artifacts (`ART.*` content-addressed, `docs/spec/01-language-and-state.md:141-157`) | No new syntax; E14 measures redundant searches and recovery under the step-interleaved protocol vs free-form tool loops |
| 16 | Geng et al., grammar-constrained decoding (2023) | Constrained generation for structural validity; valid syntax is not valid reasoning | Exists: `tahoe lint` gates sealing; `DONE` predicates and deterministic `IF` conditions are checked without a model call; `tahoe audit` re-verifies persisted runs (`src/tahoe/cli.py`) | Motivates E15: constrained vs unconstrained generation for parse-validity, latency, repair overhead, with semantic checks kept separate |

## 3. Falsifiable Experiment Register

Fifteen experiments, at least one per borrowed mechanism. Common measurement ground:
total input+output tokens across all calls (including language definition, retrieval,
retries, repairs, and judges), wall time, correctness against an external checker (never
self-report), syntax-failure rate, semantic/protocol-violation rate, and audit pass rate.
Baseline for every experiment: an ordinary natural-language prompt of the same task with
the same model, tools, and sampling settings. Repeated trials (n >= 5) for stability.
Predeclared quality non-inferiority margin: zero, unless stated otherwise.

### E1 — Keywords vs symbols under real tokenizers (Iverson)

| Field | Value |
| --- | --- |
| Hypothesis | A symbolic form of the core operators saves tokens without raising syntax or interpretation errors, per model tokenizer |
| Independent variable | Notation form: current lowercase keywords vs candidate symbolic forms, held fixed across the battery |
| Dependent variables | Total tokens; syntax-failure rate; interpretation-error rate (grader-judged); task correctness |
| Measurement | Tokenizer-level count per model family + end-to-end run; n >= 5 per task x form x model |
| Baseline | Current keyword grammar (identical tasks) |
| Pass threshold | Adopt a symbol only if median total tokens drop >= 10% on >= 2 model families with no correctness drop and syntax-failure rate unchanged (two-sided CI) |

### E2 — Claim/control separation ablation (Leibniz)

| Field | Value |
| --- | --- |
| Hypothesis | Programs that keep claims in typed refs and control in keywords are revised more safely than programs mixing both |
| Independent variable | Program style: separated (current grammar) vs deliberately mixed (control logic embedded in argument prose) |
| Dependent variables | Revision success rate after an injected requirement change; stale-conclusion count; total tokens |
| Measurement | Seeded-revision task battery; diff review of committed state after each revision |
| Baseline | Natural-language prompt with the same revision request |
| Pass threshold | Separated form: strictly fewer stale conclusions and no correctness loss; else reject the separation claim |

### E3 — Recovery after plan invalidation (Pospelov)

| Field | Value |
| --- | --- |
| Hypothesis | Situation-conditioned `IF` + `REVISE`/`RETIRE` recover from invalidated plans at lower cost than re-planning from scratch in prose |
| Independent variable | Recovery mechanism: in-program IF/REVISE vs fresh natural-language restart |
| Dependent variables | Tokens to recovery; wall time; final correctness; number of wasted steps after invalidation |
| Measurement | Task battery where the initial plan is invalidated mid-run by injected observations |
| Baseline | Same tasks, plain-prompt agent that must notice and re-plan itself |
| Pass threshold | TAHOE recovery cost <= 50% of restart cost with equal final correctness on the hardest stratum |

### E4 — Protocol specialization (Turchin)

| Field | Value |
| --- | --- |
| Hypothesis | Specializing a general protocol to a recurring task family saves total cost without overgeneralization failures |
| Independent variable | General `protocol.diagnose` vs specialized variant with applicability conditions |
| Dependent variables | Total tokens; correctness; out-of-applicability failure rate on held-out tasks |
| Measurement | Run both on the family's tasks and on held-out near-family tasks; check applicability gate behavior |
| Baseline | Unspecialized general protocol |
| Pass threshold | >= 20% token saving in-family, no correctness loss out-of-family, zero silent applicability violations |

### E5 — Reference recovery after context loss (Vygotsky)

| Field | Value |
| --- | --- |
| Hypothesis | Typed refs + KB memory restore working state after truncation/handoff cheaper than prose narration |
| Independent variable | State carrier: typed refs + `recall` vs prose summary block |
| Dependent variables | Tokens to restored correct continuation; continuation correctness; contradiction count vs pre-truncation state |
| Measurement | Truncate at fixed step; resume via worker handoff; diff restored state against replayed state from the event log |
| Baseline | Prose-summary handoff of equal content |
| Pass threshold | >= 30% token saving with zero state contradictions introduced by the ref-based resume |

### E6 — Partial specification (McCarthy)

| Field | Value |
| --- | --- |
| Hypothesis | Declarative `G.*`/`C.*` inputs without a fixed path generalize to tasks whose useful actions cannot be known in advance |
| Independent variable | Program specificity: declarative goal+constraints vs enumerated step plan |
| Dependent variables | Task completion on surprise-action tasks; correctness; tokens |
| Measurement | Battery where the required tool/action is only discoverable mid-task |
| Baseline | Natural-language declarative instruction of equal content |
| Pass threshold | TAHOE completion rate >= NL baseline minus declared margin (zero) with no token increase; else the declarative layer adds nothing |

### E7 — Control-policy swap invariance (Kowalski)

| Field | Value |
| --- | --- |
| Hypothesis | Changing `RoutingPolicy`/`Budget` (search order, tier, attempts) over an identical program does not alter committed goals or assumptions |
| Independent variable | Control policy: preferred-tier vs minimum-tier vs tightened budget, same program text |
| Dependent variables | Committed-state diff across policies; final correctness; cost |
| Measurement | Run identical sealed programs under 3 policies; compare committed graphs via projection determinism check |
| Baseline | Default policy of the same program |
| Pass threshold | Zero semantic drift across policies (byte-equal committed claims, modulo artifact digests of equivalent values); otherwise the logic/control separation is leaky |

### E8 — Dependency-aware retraction (Peirce / Doyle / de Kleer)

| Field | Value |
| --- | --- |
| Hypothesis | Explicit dependency tracking on retraction prevents stale-conclusion reuse and cuts recovery cost |
| Independent variable | Revision mechanism: `RETIRE` + dependent revalidation vs untracked overwrite |
| Dependent variables | Stale conclusions reused; recovery tokens; cascading-revision correctness |
| Measurement | Battery with contradictory evidence injected after initial hypotheses; count stale reuse via event-log replay |
| Baseline | Same tasks with overwrite-in-place semantics |
| Pass threshold | Stale-reuse count strictly lower; recovery tokens not worse; correctness equal or better |

### E9 — Adaptive expansion and stopping on difficulty strata (Russell & Wefald; Pfau)

| Field | Value |
| --- | --- |
| Hypothesis | Value-of-computation gating (expand only when confidence is low) beats both fixed-depth and fixed-budget reasoning, and gains concentrate on hard strata without hurting easy ones |
| Independent variable | Expansion policy: confidence-gated `challenge`/`decompose` vs fixed budget vs fixed depth |
| Dependent variables | Total tokens; correctness per difficulty stratum; wall time; meta-decision overhead tokens |
| Measurement | Difficulty-stratified battery (easy/medium/hard), n >= 5 per stratum; track tokens spent deciding whether to think |
| Baseline | Fixed-budget natural-language CoT of equal task |
| Pass threshold | Pareto-dominant: no stratum worse beyond zero margin, hard-stratum tokens -20% at equal correctness; reject if meta-decisions cost more than they save |

### E10 — Library ablation (Newell / Soar chunking)

| Field | Value |
| --- | --- |
| Hypothesis | Programs using a protocol library outperform library-disabled runs on unseen tasks |
| Independent variable | Library availability: `CALL protocol.*` enabled vs the same programs with calls inlined or disabled |
| Dependent variables | Correctness; total tokens; syntax/protocol violation rate |
| Measurement | Unseen-task battery (tasks not used when the library was built), library-on vs library-off arms |
| Baseline | Library-disabled arm |
| Pass threshold | Library arm: correctness non-inferior and tokens -15% on unseen tasks; else the library is not earning its prompt overhead |

### E11 — Protocol mining with held-out promotion (DreamCoder)

| Field | Value |
| --- | --- |
| Hypothesis | `tahoe learn` candidates promoted on dev data improve dev-set cost, and the improvement transfers to a never-touched test set |
| Independent variable | Library state: pre-mining vs post-promotion |
| Dependent variables | Dev-set tokens/correctness; test-set tokens/correctness; overfitting gap (dev gain minus test gain) |
| Measurement | Mine demo/runs history; promote per `learn.py` review process; evaluate both sets before/after |
| Baseline | Pre-mining library |
| Pass threshold | Promote only candidates with dev-set improvement and test-set gain >= 50% of dev gain; candidates failing this are rejected |

### E12 — Abstraction amortization (Rissanen / MDL)

| Field | Value |
| --- | --- |
| Hypothesis | An abstraction pays for its definition, retrieval, ambiguity, and repair costs over a declared reuse horizon |
| Independent variable | Using macro/protocol vs repeating the expanded steps, over k reuse events |
| Dependent variables | Cumulative tokens over the horizon; repair cost when the macro is wrong; ambiguity-induced violation rate |
| Measurement | Instrument every use: definition tokens in prompt, retrieval tokens, failure repairs; sweep k = 1..N |
| Baseline | Expanded form repeated k times |
| Pass threshold | Break-even k reported; abstraction adopted only if k* <= declared horizon and repair cost < 2x inline repair cost |

### E13 — Parity with concise-reasoning prompting (Xu et al., Chain of Draft)

| Field | Value |
| --- | --- |
| Hypothesis | TAHOE's structure adds value beyond merely instructing the model to be brief |
| Independent variable | Prompting regime: TAHOE program vs Chain-of-Draft-style instruction vs ordinary NL |
| Dependent variables | Total tokens; correctness; revision stability across trials |
| Measurement | Same battery, same models, n >= 5; include at least one task class where CoD is reported strong |
| Baseline | Chain-of-Draft instruction (the strongest cheap baseline) |
| Pass threshold | TAHOE correct-rate within zero margin of CoD and total tokens <= CoD, or correctness strictly better at any token cost; otherwise do not claim token-efficiency superiority over concise prompting |

### E14 — Interleaving with provenance (Yao et al., ReAct)

| Field | Value |
| --- | --- |
| Hypothesis | Step-interleaved commands with digested observations reduce redundant searches and improve recovery vs free-form tool loops |
| Independent variable | Interaction regime: TAHOE steps with committed artifact refs vs free-form ReAct-style loop |
| Dependent variables | Redundant tool calls; recovery tokens after a failed call; observation-fabrication rate (claims without artifact digest) |
| Measurement | Tool-use investigation battery; count tool calls and digests in the event log |
| Baseline | Free-form ReAct prompting |
| Pass threshold | Redundant calls -30%, zero undigested observation claims, correctness non-inferior |

### E15 — Constrained decoding (Geng et al.)

| Field | Value |
| --- | --- |
| Hypothesis | Grammar-constrained generation raises parse-validity without lowering task accuracy, at acceptable latency |
| Independent variable | Decoding: constrained to program grammar vs unconstrained with `lint`-repair loop |
| Dependent variables | First-pass parse-validity; task accuracy; latency; repair-loop tokens |
| Measurement | Battery on models exposing constrained decoding; unconstrained arm uses the current lint-and-retry path |
| Baseline | Unconstrained generation + lint repair |
| Pass threshold | Constrained arm: parse-validity +20pp or more, accuracy within zero margin, repair tokens saved > latency cost in money terms |

## 4. Notation Policy

**Decision framework.** A notation change (symbol or keyword) is adopted only after E1
passes for it, per model family. The policy is tokenizer-empirical, never aesthetic:

1. Measure on the target model's actual tokenizer: tokens for the keyword form vs the
   symbolic form, in the exact context of a program line, not in isolation.
2. End-to-end check: syntax-failure rate and interpretation-error rate must not rise.
3. Cross-model check: a symbol that wins on one family but loses or fails on another is
   rejected or made a per-model presentation variant, never part of the canonical AST.
4. Recoverability: every adopted compact form must have a documented expanded reading
   that the grammar docs and `tahoe lint` agree on.

**Interim rule (in force until E1 evidence exists).** The canonical grammar uses
lowercase English keywords for commands (`define`, `hypothesize`, `challenge`, ...) and
uppercase ASCII keywords for control (`IF`, `DONE`, `CALL`, `RETURN`, `STOP`,
`REVISE`, `RETIRE`), exactly as implemented in `src/tahoe/syntax/parser.py`. The only
non-alphabetic syntax is structural, not notational: `.` in typed refs, `:` after a step
id, `=` for arguments, `,` for separators, `->` for targets, `|` between `REVISE` and
`RETIRE` groups. No new symbols enter the grammar on plausibility arguments. Structural
punctuation is exempt from E1: it delimits grammar, it does not abbreviate an operation.

## 5. Non-Goals

| Not borrowing | Why |
| --- | --- |
| Self-modifying grammar | The grammar and the 23-command registry are the audit base: `registry_digest` at RUN_STARTED pins what executed (`src/tahoe/runtime/coordinator.py`), and `tahoe audit` re-verifies persisted runs against fixed invariants (`src/tahoe/audit.py`). A grammar that rewrites itself has no fixed semantics to audit; TAHOE's differentiator is exactly this auditability. Language evolution happens through versioned specs and reviewed registry changes, never inside a run |
| Unverifiable heuristics | Every completion claim is a deterministic `DONE` predicate (`equals`/`in`/`matched`), a worker judgment recorded as an event with evidence, or a `STOP` with a kind. There is no "trust the model" shortcut that bypasses recorded evidence; `tahoe learn` outputs are review-only and promotion requires a human-approved PR (`src/tahoe/learn.py`) |
| A universal calculus of reasoning | Leibniz's goal is historical motivation. TAHOE encodes only distinctions that measurably pay for themselves in the register above |
| Reading internal reasoning from traces | Visible traces are artifacts, not evidence of computation (Pfau et al.); evaluation uses external correctness checks |
| Fine-tuning-first adoption | Mechanisms must earn adoption prompt-only first; any training experiment is charged separately and never mixed into token accounting |
| Uncontrolled macro accumulation | Every abstraction is charged for definition, retrieval, ambiguity, and repair (E12); the vocabulary stays small by policy, matching the frozen builtin registry |
