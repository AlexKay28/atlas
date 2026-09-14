# TAHOE — Task-Aware Language Harness for Orchestrated Execution

*A structured reasoning language that makes LLM thinking better.*

TAHOE teaches LLMs to reason in typed protocols — Compute, Select, Deduce,
Decide, Plan, Debug — instead of free-form chain-of-thought. The model learns
the framework from a thinking skill (system prompt), applies it internally
during reasoning, and produces better answers. Same single inference call,
structured thinking.

```
classic:  Q → {thinking} → answer
tahoe:    Q + skill → {thinking · tahoe} → answer
```

## Repository structure

```
textbook/          Thinking recipes — the language, rules, protocols
├── 01-smart-thinking-rules.md    15 rules for structured reasoning
├── 02-token-economy.md           Token optimization without quality loss
├── 03-reasoning-protocols.md     9 protocols (Compute, Select, Deduce, ...)
├── 04-graph-construction.md      How to build reasoning graphs
├── 05-quality-control.md         Evidence quality, verification, confidence
├── 06-personal-profile.md        Agent profiles and defaults
└── ARCHITECTURE.md               Machine-readable map of all TAHOE concepts

src/               TAHOE language runtime (parser, coordinator, events)
├── tahoe/                        Python package
└── spec/                          Language specification (5 docs)

benchmarks/        Evaluation code and results
├── run_trials.py                 Custom task ablation runner
├── run_public_bench.py           Public benchmark runner (GSM8K, ARC, BBH)
├── tahoe_skill_prompt.txt         The TAHOE thinking skill (system prompt)
├── tasks/                         7 custom task manifests with graders
├── results/                       Trial data and reports
├── graders.py                     Programmatic graders
└── report.py                      Token distribution report generator

tests/             Tests
├── reasoning/                    Tests that verify model understands TAHOE
└── test_*.py                      Unit tests for runtime, parser, etc.

analysis/          Reasoning trajectory analysis
├── trajectory_score.py            Score reasoning quality against TAHOE rules
└── README.md                      Scoring methodology

paper/             Research paper (arxiv draft)
├── TAHOE.md                       Paper draft
├── design/                        Architecture decision records
└── research-*.md                  Related work survey

demo/              Demo tasks and sealed runs
examples/          Example .think programs
protocols/         Learned protocol candidates
archive/           Historical files (old reports, build artifacts)
```

## Results

10 public benchmarks, **full test sets**, 3 trials, 31,524 trials total (GLM-5.3-Flash).

| Benchmark | N | Classic | TAHOE | Cl out | Tah out | Ratio |
|---|---|---|---|---|---|---|
| GSM8K | 1319 | 71.3% | **79.0%** | 241 | 91 | 0.38x |
| ARC | 1172 | **96.0%** | 95.7% | 121 | 58 | 0.48x |
| BBH | 250 | 78.1% | 77.9% | 472 | 288 | 0.61x |
| BBH-track | 250 | **89.7%** | 75.9% | 521 | 270 | 0.52x |
| BBH-arith | 200 | **100%** | 99.8% | 117 | 97 | 0.83x |
| MMLU-math | 100 | 94.3% | 94.3% | 399 | 318 | 0.80x |
| MMLU-logic | 126 | **95.2%** | 93.1% | 312 | 263 | 0.84x |
| MMLU-acct | 282 | 96.1% | **96.3%** | 238 | 138 | 0.58x |
| LSAT | 510 | 93.4% | **94.9%** | 432 | 210 | 0.49x |
| RACE | 1045 | **94.1%** | 93.8% | 189 | 100 | 0.53x |
| **OVERALL** | — | **88.1%** | **89.4%** | **246** | **125** | **0.51x** |

**TAHOE saves 49% reasoning tokens** while improving quality +1.3% (89.4% vs 88.1%).
HM: 1.227 (TAHOE) vs 0.937 (classic) — TAHOE wins decisively.

## Quick start

```bash
# Install
pip install -e .

# Lint and seal a program
tahoe lint examples/demo.think
tahoe seal examples/demo.think

# Run benchmarks
export TAHOE_API_BASE="https://your-api-endpoint/v1"
export TAHOE_API_KEY="your-api-key"
# export SSL_CERT_FILE if your endpoint uses a custom CA
PYTHONPATH=src python3 benchmarks/run_public_bench.py
```

## The thinking skill

The TAHOE thinking skill (`benchmarks/tahoe_skill_prompt.txt`) is a distilled
version of the textbook. It teaches the model:

- **Typed refs**: G (goal), C (constraint), E (evidence), H (hypothesis),
  V (verified), OUT (answer) — prevents assumptions from becoming facts
- **Protocols**: Compute (math), Select (multiple choice), Deduce (ordering)
  — matches reasoning pattern to task type
- **Rules**: Name outcome before method, verify before returning, match
  rigor to consequence
- **Token economy**: Use concrete values, output the answer not the story

## For researchers

- **Paper draft**: `paper/TAHOE.md`
- **Architecture map**: `textbook/ARCHITECTURE.md`
- **Trajectory scoring**: `analysis/trajectory_score.py` — scores reasoning
  quality for RL reward signals
- **Raw results**: `benchmarks/results/`

## License

MIT. See [CHANGELOG.md](CHANGELOG.md) for release history.
