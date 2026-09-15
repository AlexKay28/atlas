# The TAHOE Language

TAHOE is a structured reasoning language: a notation of typed epistemic
references, named reasoning protocols, and economy rules that form a
logic-level pseudocode for how a model should think.

This directory holds the language as **delivered artifacts** — everything an
experiment or a deployment needs to give a model the language.

## Layout

```
language/
├── skills/                  # thinking skills (system prompts) — the deliverable
│   ├── tahoe-93.txt         # canonical skill (93 tokens) — used in all headline results
│   ├── triz-implicit.txt    # variant: adds ideal-first search bounding (83 words)
│   └── variants/            # ablation artifacts (kept as evidence)
│       ├── tahoe-50/150/200.txt   # size ablation
│       ├── triz-implicit-50/150.txt
│       └── triz-explicit.txt      # the FAILED explicit-notation variant (kept deliberately)
└── baselines/               # baseline prompts for arm comparisons
    ├── cot.txt  cod.txt  tot.txt  react.txt
```

## Design law (do not break)

**A reasoning language must shape thought, never constrain output.**

The skills are thinking disciplines: the model reasons with typed commitments
and protocols internally, and its visible answer shrinks to the answer itself.
Forcing the notation into the visible output measurably decreases quality and
increases tokens (see `insights/compact-language.md`; the explicit-notation
negative artifact is kept in `skills/variants/triz-explicit.txt`).

## Skill-size insensitivity

Quality is insensitive to skill size (33–162 words ≈ same results); the
discipline carries the effect, not the wording. The canonical skill is 93
tokens.

## Contract with the runtime

The skill prompt teaches the language; the runtime (`src/tahoe/`) provides the
reference grammar, parser, type-checker, and coordinator. At inference time
only the prompt is needed; the runtime validates, executes deterministically
where possible, and (optionally, `vm_mode/`) executes programs step-by-step.
