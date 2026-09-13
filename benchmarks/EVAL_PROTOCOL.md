# Benchmark Evaluation — Frozen Protocol

> The evaluation pipeline for each benchmark is frozen. We never change
> graders, answer extraction, or prompt construction per arm. The ONLY
> variable we change is the TAHOE thinking skill (system prompt).

## Evaluation invariant

Both arms (classic and tahoe) receive:
- The **same task prompt** (from the benchmark dataset)
- The **same API parameters** (max_turns, max_tokens, timeout)
- The **same grader** (answer extraction + comparison)
- The **same model** (TAHOE_MODEL env var)

The ONLY difference: tahoe arm gets `system_prompt = tahoe_skill_prompt.txt`.
Classic arm gets `system_prompt = ""`.

Never branch grading logic on arm identity. Never use different extraction
for one arm vs the other. If the grader needs fixing, fix it for BOTH arms.

## GSM8K

- Source: `gsm8k` dataset, `main` split, `test` partition
- Gold extraction: number after `#### ` in the gold answer
- Model extraction: #### pattern → short answer number → "answer is N" → last number
- Grading: exact numeric match

## ARC-Challenge

- Source: `allenai/ai2_arc`, `ARC-Challenge`, `test` partition
- Gold: `answerKey` field (letter A/B/C/D)
- Model extraction: first A-D letter found in answer
- Grading: exact letter match

## BBH (logical_deduction_seven_objects)

- Source: `lukaemon/bbh`, `logical_deduction_seven_objects`, `test` partition
- Gold: `target` field (format `(X)`)
- Model extraction: letter in `(X)` format, fallback to bare letter
- Grading: exact letter match

## Custom tasks (7 tasks)

- Source: `benchmarks/tasks/*.yaml`
- Gold: `expected_state` in YAML manifest
- Graders: `numeric` (extract number), `contains` (substring match)
- Grading: task-specific, same for both arms
