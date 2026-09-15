# Stage-1 Full Evaluation — 2026-09-13

**Claim evaluated**: the tahoe-93 thinking skill reduces reasoning tokens ≥40%
at quality parity or better, on full test sets, cross-model.

## Reproduction

```bash
cd /home/alexkay28/projects/pseudolanguage
export TAHOE_API_BASE=... TAHOE_API_KEY=... TAHOE_MODEL="."
export SSL_CERT_FILE=/etc/ssl/certs/yandex-ca.pem TAHOE_API_POOL=notelm
export PYTHONPATH=src N_WORKERS=6

# GLM arm (31,524 trials, ~2.5 h sequential chain)
for bench in "gsm8k 1319" "arc 1172" "bbh 250" "bbh_track 250" "bbh_arith 250" \
             "mmlu_math 100" "mmlu_logic 126" "mmlu_acct 282" "lsat 510" "race 1045"; do
  python3 benchmarks/run_single_bench.py $bench
done

# gpt-oss arm (31,824 trials; 5-inflight pool quota — sequential chain, 5 workers)
export TAHOE_API_BASE=https://api.eliza.yandex.net/raw/internal/gpt-oss-120b/v1
export TAHOE_MODEL=gpt-oss-120b N_WORKERS=5
# (same loop; worker_fn retries on 429/empty)
```

## Data

`benchmarks/results/2026-09-13-stage1-full/` — `full_test_eval.json` (GLM),
`oss_full_eval.json`, per-bench `single_*.json`, summaries.

## Result

GLM 88.9% → **91.8%** @ 0.51× tokens (HM 1.250 vs 0.941); gpt-oss
92.8% → 92.5% @ 0.68×. gsm8k rows re-graded with the v3 extractor
(68.5% / 80.3%) — see the correction note in `insights/compact-language.md`.

## Caveats

- gsm8k quality ladder from the earlier 200-sample run was an extraction
  artifact; only the v3-graded numbers here are citable.
- Letter-based graders were not re-audited for prose-format bias (flagged in
  paper Limitations).
