# TAHOE Architecture Map

> Machine-readable index for AI model consumption. Every TAHOE doc, protocol,
> command, and rule is linked here. The model reads this to understand TAHOE's
> thinking framework and applies it during reasoning.

## Hierarchy

```
TAHOE
├── Language (how to think)
│   ├── Smart Thinking Rules     → docs/language/01-smart-thinking-rules.md
│   ├── Token Economy            → docs/language/02-token-economy.md
│   ├── Reasoning Protocols      → docs/language/03-reasoning-protocols.md
│   ├── Graph Construction       → docs/language/04-graph-construction.md
│   ├── Quality Control          → docs/language/05-quality-control.md
│   └── Personal Profile         → docs/language/06-personal-profile.md
├── Specification (what the language is)
│   ├── Language and State       → docs/spec/01-language-and-state.md
│   ├── Command Catalog          → docs/spec/02-command-catalog.md
│   ├── Runtime and Events       → docs/spec/03-runtime-and-events.md
│   ├── Completeness             → docs/spec/04-completeness.md
│   └── Live Authoring           → docs/spec/05-live-authoring-and-routing.md
├── Design (why the language works)
│   └── Reasoning Foundation     → docs/design/01-reasoning-language-foundation.md
├── Research (what informed it)
│   ├── Related Systems          → docs/research/related-systems.md
│   └── Text Harness Precedents  → docs/research/text-harness-precedents.md
└── ADRs (what changed and why)
    ├── ADR-0001 AI Thinking     → docs/adr/0001-ai-thinking-language.md
    ├── ADR-0002 Executable      → docs/adr/0002-executable-thinking-language.md
    └── ADR-0003 Live Harness    → docs/adr/0003-live-text-harness.md
```

## Typed Refs (knowledge states)

| Ref | Meaning | Role in reasoning |
|---|---|---|
| `G.` | Goal | The outcome that should be true after solving |
| `C.` | Constraint | Hard limit that invalidates options |
| `P.` | Preference | Soft ranking criterion for valid options |
| `E.` | Evidence | Observed, verifiable facts |
| `F.` | Finding | Derived from evidence, less raw |
| `A.` | Assumption | Unverified but currently treated as true |
| `H.` | Hypothesis | Unverified causal or explanatory claim |
| `U.` | Unknown | Not yet measured or resolved |
| `O.` | Option | Alternative choice for a decision |
| `K.` | Criteria | Ranking keys chosen before evaluation |
| `D.` | Decision | Chosen option with recorded reason |
| `P.` | Plan | Intermediate computed results |
| `V.` | Verified | Result that passed a DONE check |
| `X.` | Action | Executable step with observable result |
| `R.` | Risk | Failure mode with probability and impact |
| `ART.` | Artifact | Durable output (report, code, document) |
| `OUT.` | Output | Final answer returned to the caller |

## Protocols (thinking patterns)

| Protocol | When to use | Required artifacts | Doc |
|---|---|---|---|
| **Compute** | Arithmetic, algebra, numeric answer | G + E → P.steps → V.check → OUT | 03 §Compute |
| **Select** | Multiple choice, one correct option | G + E.options → P.elimination → D → V → OUT | 03 §Select |
| **Deduce** | Logical deduction, ordering, positions | G + C → P.positions → V.all_met → OUT | 03 §Deduce |
| **Explore** | Unclear problem space | Q → CTX → F/E/A/U → H → OUT | 03 §Explore |
| **Decide** | Choice among approaches | G + C + P → O → K → D → R → V → OUT | 03 §Decide |
| **Plan** | Decompose into steps | G + C + D → X(links) → V → OUT | 03 §Plan |
| **Debug** | Observed ≠ expected | Q + F + E → H → V → D/X → V.regression → OUT | 03 §Debug |
| **Review** | Evaluate an artifact | CTX + C → E + R → D/X → OUT | 03 §Review |
| **Learn** | Transferable understanding | Q → H → E → V.recall + V.transfer → OUT | 03 §Learn |

## Protocol selection rule

Match the protocol to the task type, not to preference:

```
if task asks for a number or computation:     → Compute
if task has options A/B/C/D to choose:         → Select
if task requires ordering or position tracking: → Deduce
if task is unclear, needs exploration:          → Explore
if task has competing approaches:               → Decide
if task needs decomposition into steps:         → Plan
if task has a bug or mismatch:                  → Debug
if task evaluates an artifact:                   → Review
if task builds transferable knowledge:          → Learn
```

## Command catalog (17 commands)

| Command | Purpose | Effect class |
|---|---|---|
| `define` | State goal or concept clearly | pure |
| `calculate` | Compute concrete result | pure |
| `search` | Find items in data | read_only |
| `choose` | Pick best option by criterion | pure |
| `check` | Verify condition is met | pure |
| `decompose` | Break goal into subtasks | pure |
| `rank` | Order items by criteria | pure |
| `compare` | Evaluate alternatives against criteria | pure |
| `verify` | Confirm result is correct | pure |
| `summarize` | Condense findings | pure |
| `report` | Format final answer | pure |
| `edit` | Produce corrected version | reversible_write |
| `solve` | Work through problem to answer | pure |
| `recall` | Recover prior state | read_only |
| `hypothesize` | Propose testable claim | pure |
| `prove` | Establish claim from evidence | pure |
| `delegate` | Dispatch subtask to worker | effectful |

## Thinking rules (15 rules, summarized)

1. Name the outcome before the method
2. Separate constraints from preferences
3. Include only decision-shaping facts
4. Distinguish facts, assumptions, hypotheses, unknowns
5. Resolve the highest-value unknown first
6. Generate alternatives before committing
7. Define criteria before ranking
8. Prefer reversible steps under uncertainty
9. Make causal claims testable
10. Use the smallest action that produces evidence
11. Define completion before starting
12. Stop when marginal value becomes low
13. Preserve dissent and contradictions
14. Update locally, not globally
15. Match rigor to consequence

Full text: `docs/language/01-smart-thinking-rules.md`

## Token economy rules

- Optimize total conversation cost, not just response length
- Use concrete values, not variable names, in computation steps
- Each ref = one semantic unit (atomic, referenceable)
- Protocol selection eliminates exploratory preamble
- Output the answer, not the story of finding the answer
- Match rigor to consequence: Fast / Standard / Critical

Full text: `docs/language/02-token-economy.md`

## Quality control

- Two independent checks: graph well-formed? conclusion well-supported?
- Evidence ladder: E0 (assertion) → E4 (independent replication)
- Assumption budget: probability_wrong × impact_if_wrong
- Confidence must have visible basis

Full text: `docs/language/05-quality-control.md`

## Protocol exit contract

Every protocol returns:
```
OUT.result:   requested artifact
OUT.basis:    decisive evidence or criteria
OUT.unknowns: unresolved items that could change the result
OUT.next:     smallest useful next action, or stop
OUT.check:    acceptance result or verification method
```

## Rigor levels

| Level | Use when | Required structure |
|---|---|---|
| Fast | Reversible, low-impact | G, OUT, optional V |
| Standard | Normal work | G, C, facts, action, V |
| Critical | Irreversible, expensive | Evidence, alternatives, risks, decision, independent checks |

## Graph construction

- Nodes are typed refs (G., C., E., etc.)
- Links: supports, contradicts, depends_on, precedes, mitigates, selects
- One semantic unit per node
- Stable identifiers for reuse across updates

Full text: `docs/language/04-graph-construction.md`

## RL integration hook

This architecture map is designed to serve as:
1. **Curriculum** — the model learns protocols as reasoning patterns
2. **Reward signal** — DONE predicates define success criteria
3. **Trajectory structure** — each protocol defines a valid reasoning path
4. **Constraint** — typed refs prevent reasoning shortcuts (assumptions ≠ facts)
5. **Verification** — quality control rules check conclusion support

The map links every concept to its source doc. When a model reasons in TAHOE,
each step maps to a protocol, command, and rule. This makes the reasoning
auditable and the learning signal clean.
