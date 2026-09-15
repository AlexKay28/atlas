# Results Archive

**Rule: runs append to dated study directories — never overwrite.** Active
runners write to `results/runs/<UTC-timestamp>_<name>/` (created automatically);
at the end of a study, freeze its data into a dated directory below and index
it here.

| Directory | Study | Key files | Doc |
|---|---|---|---|
| `2026-09-13-pilot/` | 600-trial pilot (10 samples x 10 benches), legacy eval results | `public_benchmarks.json`, `trials.json`, `report.json` | `FULL_EVAL_SUMMARY.md` (in stage1-full) |
| `2026-09-13-stage1-full/` | Stage-1 full-test-set eval, both models (63,348 trials), grader-corrected | `full_test_eval.json` (GLM), `oss_full_eval.json`, `single_*.json`, `CROSS_MODEL_EVAL.md` | `docs/EVALUATION.md` |
| `2026-09-14-skill-study/` | Skill comparisons (GLM 200-sample, v3 grader) + prompt-size ablation + E1 notation | `skill_cmp_*.json`, `prompt_ablation.json`, `e1_notation.json` | `insights/compact-language.md` |
| `2026-09-14-vm-pilot/` | TAHOE-VM pilot (shelved branch) + oss-overwrite artifacts | `vm_pilot_*.json`, `full_200_eval.json` | `docs/TAHOE_VM.md` |

Note: files in `2026-09-14-vm-pilot/` include data whose gsm8k rows were
produced under the v1 grader; see the correction in
`insights/compact-language.md` before citing numbers from that directory.

## Current runners

- `run_skill_compare.py` — canonical single-call arm comparison (writes
  `results/runs/...`)
- `run_single_bench.py` — one benchmark, two arms, parallel
- `run_parallel_bench.py` — all benchmarks + bootstrap CIs
- `run_public_bench.py` — original frozen-protocol runner
