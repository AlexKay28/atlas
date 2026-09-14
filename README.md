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

10 public benchmarks, **full test sets**, 3 trials. Two models, 63,348 trials total.

**GLM-5.3-Flash** (31,524 trials):

| Benchmark | N | Classic | TAHOE | Ratio |
|---|---|---|---|---|
| GSM8K | 1319 | 71.3% | **79.0%** | 0.38x |
| ARC | 1172 | **96.0%** | 95.7% | 0.48x |
| BBH | 250 | **99.5%** | 98.8% | 0.61x |
| BBH-track | 250 | **99.9%** | 99.5% | 0.52x |
| BBH-arith | 200 | **100%** | 99.8% | 0.83x |
| MMLU-math | 100 | 94.3% | 94.3% | 0.80x |
| MMLU-logic | 126 | **95.2%** | 93.1% | 0.84x |
| MMLU-acct | 282 | 96.1% | **96.3%** | 0.58x |
| LSAT | 510 | 93.4% | **94.9%** | 0.49x |
| RACE | 1045 | **94.1%** | 93.8% | 0.53x |
| **OVERALL** | — | **89.6%** | **91.5%** | **0.51x** |

**gpt-oss-120b** (31,824 trials):

| Benchmark | N | Classic | TAHOE | Ratio |
|---|---|---|---|---|
| GSM8K | 1319 | 77.9% | **79.4%** | 0.40x |
| ARC | 1172 | **94.4%** | 94.1% | 0.71x |
| BBH | 250 | 99.1% | **99.7%** | 0.83x |
| BBH-track | 250 | **100%** | 99.6% | 0.83x |
| BBH-arith | 250 | **99.9%** | 99.6% | 0.88x |
| MMLU-math | 100 | 96.7% | 96.7% | 0.83x |
| MMLU-logic | 126 | **95.5%** | 95.0% | 0.84x |
| MMLU-acct | 282 | 89.6% | 89.6% | 0.82x |
| LSAT | 510 | **85.4%** | 83.1% | 0.72x |
| RACE | 1045 | **89.8%** | 88.7% | 0.85x |
| **OVERALL** | — | **89.1%** | **88.9%** | **0.68x** |

**TAHOE saves 49% (GLM) / 32% (gpt-oss) reasoning tokens** while improving quality
+1.9% on GLM and matching on gpt-oss. HM: 1.247 vs 0.945 (GLM), 1.107 vs 0.942 (gpt-oss).

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
