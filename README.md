# TAHOE — a structured reasoning language for LLMs

*Logic-level pseudocode for how a model should think.*

TAHOE is a compact reasoning language: typed epistemic references
(`G` goal, `E` evidence, `H` hypothesis, `V` verified, `OUT` answer), named
protocols (`Compute`, `Select`, `Deduce`), and economy rules. Delivered to an
LLM as a 93-token thinking skill (system prompt), it disciplines the model's
reasoning **without changing its output format** — the visible answer shrinks
to the answer itself.

```
classic:  Q → {wandering narrative} → answer        (337 output tokens avg)
tahoe:    Q + skill → {bounded, typed derivation} → answer   (141 avg)
```

## Headline results (63,348 trials, full test sets, two models)

| Model | Classic | TAHOE | Token ratio | HM |
|---|---|---|---|---|
| GLM-5.3-Flash | 88.9% | **91.8%** | **0.51×** | 1.250 vs 0.941 |
| gpt-oss-120b | 92.8% | 92.5% | **0.68×** | 1.054 vs 0.911 |

Largest quality gain: GSM8K **+11.8pp** at 0.38× tokens. Skill-size
insensitive (33–162 words ≈ same quality). Full data: `docs/EVALUATION.md`,
paper: `paper/tahoe.pdf`.

## The design law

> **A reasoning language must shape thought, never constrain output.**

Visible notation taxes every token; internalized notation taxes nothing.
Three experiments established this (explicit notation collapsed LSAT to 23%;
a protocol-execution VM lost 40+ points at 2–35× tokens; the skill's median
visible output is the answer alone). Details: `insights/compact-language.md`,
`docs/TAHOE_VM.md`.

## Repository structure

```
language/          THE LANGUAGE AS ARTIFACT
├── README.md              what the language is, skill catalog, design law
├── skills/
│   ├── tahoe-93.txt       canonical thinking skill (93 tokens)
│   ├── triz-implicit.txt  variant: ideal-first search bounding
│   └── variants/          size ablations + the explicit-notation negative artifact
└── baselines/             cot / cod / tot / react prompts

src/               THE LANGUAGE RUNTIME
├── tahoe/                 grammar, parser, type-checker, coordinator, events
│   └── vm_mode/           SHELVED: step-by-step execution protocol (STATUS.md)
└── spec/                  formal language specification

benchmarks/        EVALUATION INFRA
├── README.md              runner catalog, env, grading rules
├── run_skill_compare.py   canonical arm-comparison runner
├── run_single_bench.py    one benchmark, parallel, full-test-set support
├── run_parallel_bench.py  all benchmarks + bootstrap CIs
├── results/               frozen study archives (dated dirs — never overwrite)
└── EVAL_PROTOCOL.md       frozen invariants

textbook/          thinking recipes — the language, rules, protocols (human-facing)
analysis/          trajectory scoring, protocol discovery
paper/             tahoe.pdf + LaTeX source + figures
docs/              EVALUATION.md (results record), TAHOE_VM.md (shelved branch)
insights/          research journal — findings, corrections, landscape surveys
tests/             1,711 tests
examples/ demo/ protocols/ archive/
```

## Quick start

```bash
pip install -e .

# evaluate a skill on a benchmark
export TAHOE_API_BASE=... TAHOE_API_KEY=... TAHOE_MODEL="."
PYTHONPATH=src python3 benchmarks/run_skill_compare.py gsm8k 100 \
    tahoe-93.txt triz-implicit.txt
```

## For researchers

- **Paper**: `paper/tahoe.pdf` (+ LaTeX) — language, mechanism, semantics, proofs
- **Results record**: `docs/EVALUATION.md` + `benchmarks/results/` (per-study)
- **Research journal**: `insights/` — including the grader-format lessons and
  the correction history
- **Skills**: `language/skills/` — the deployable artifact

## License

MIT. See [CHANGELOG.md](CHANGELOG.md).
