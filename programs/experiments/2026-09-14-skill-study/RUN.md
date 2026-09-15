# Skill Comparison Study — 2026-09-14

**Claim evaluated**: skill variants (plain tahoe-93; goal-bounding variant)
against classic, 200 samples × 10 benchmarks, v3 arm-agnostic grader.

## Reproduction

```bash
export PYTHONPATH=src N_WORKERS=6
# (endpoint env as in stage1)
python3 benchmarks/run_skill_compare.py gsm8k 200 tahoe-93.txt triz-implicit.txt
# ... repeat per bench, or loop:
for bench in gsm8k arc bbh bbh_track bbh_arith mmlu_math mmlu_logic mmlu_acct lsat race; do
  python3 benchmarks/run_skill_compare.py $bench 200 tahoe-93.txt triz-implicit.txt
done
# output lands in benchmarks/results/runs/<ts>_skill-cmp-<bench>/trials.json
```

## Data

`benchmarks/results/2026-09-14-skill-study/skill_cmp_*.json` (GLM, v3 grader),
`prompt_ablation.json` (5 skill sizes), `e1_notation.json`.

## Result (v3-graded)

GLM: classic 95.2% / 308t · tahoe-93 96.7% / 178t · triz-implicit 96.6% / 132t.
Token savings −42/−57% with quality within noise of each other; gpt-oss
transfer: quality-neutral, −27% tokens (HM still favors the skills).

## Caveats

- The earlier "+23.5pp gsm8k ladder" (HM 1.362) was RETRACTED — extraction
  artifact; see `insights/compact-language.md` correction section.
- Skill-size insensitive (33–162 words ≈ same quality).
