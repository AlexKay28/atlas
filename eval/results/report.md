# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 446.40 | 391.00 | 483.00 | 504.00 | 1.98 | 446.40 |
| code-fix-01 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.92 | 0.00 |
| code-fix-01 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 341.40 | 254.00 | 281.00 | 478.00 | 1.55 | 341.40 |
| code-fix-02 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.90 | 0.00 |
| code-fix-02 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| plan-01 | classic | 5 | 0.00 | 0.00 | 526.60 | 538.00 | 549.00 | 549.00 | 2.50 | 0.00 |
| plan-01 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.91 | 0.00 |
| plan-01 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| recover-01 | classic | 5 | 0.80 | 0.80 | 348.20 | 289.00 | 311.00 | 323.00 | 1.84 | 297.25 |
| recover-01 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.90 | 0.00 |
| recover-01 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| routing-01 | classic | 5 | 0.00 | 0.00 | 351.80 | 334.00 | 335.00 | 375.00 | 1.21 | 0.00 |
| routing-01 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.92 | 0.00 |
| routing-01 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| routing-02 | classic | 5 | 0.00 | 0.00 | 599.00 | 599.00 | 599.00 | 599.00 | 2.39 | 0.00 |
| routing-02 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.96 | 0.00 |
| routing-02 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| search-01 | classic | 5 | 0.00 | 0.00 | 208.20 | 187.00 | 190.00 | 236.00 | 0.73 | 0.00 |
| search-01 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.88 | 0.00 |
| search-01 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 0.00 | 0.00 |
| code-fix-01 | mean_tokens | 446.40 | 0.00 | 0.00 |
| code-fix-01 | p25_tokens | 391.00 | 0.00 | 0.00 |
| code-fix-01 | p75_tokens | 504.00 | 0.00 | 0.00 |
| code-fix-01 | mean_wall | 1.98 | 1.92 | 0.00 |
| code-fix-01 | mean_quality | 1.00 | 0.00 | 0.00 |
| code-fix-01 | tokens_per_success | 446.40 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 0.00 | 0.00 |
| code-fix-02 | mean_tokens | 341.40 | 0.00 | 0.00 |
| code-fix-02 | p25_tokens | 254.00 | 0.00 | 0.00 |
| code-fix-02 | p75_tokens | 478.00 | 0.00 | 0.00 |
| code-fix-02 | mean_wall | 1.55 | 1.90 | 0.00 |
| code-fix-02 | mean_quality | 1.00 | 0.00 | 0.00 |
| code-fix-02 | tokens_per_success | 341.40 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| plan-01 | pass_rate | 0.00 | 0.00 | 0.00 |
| plan-01 | mean_tokens | 526.60 | 0.00 | 0.00 |
| plan-01 | p25_tokens | 538.00 | 0.00 | 0.00 |
| plan-01 | p75_tokens | 549.00 | 0.00 | 0.00 |
| plan-01 | mean_wall | 2.50 | 1.91 | 0.00 |
| plan-01 | mean_quality | 0.00 | 0.00 | 0.00 |
| plan-01 | tokens_per_success | 0.00 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| recover-01 | pass_rate | 0.80 | 0.00 | 0.00 |
| recover-01 | mean_tokens | 348.20 | 0.00 | 0.00 |
| recover-01 | p25_tokens | 289.00 | 0.00 | 0.00 |
| recover-01 | p75_tokens | 323.00 | 0.00 | 0.00 |
| recover-01 | mean_wall | 1.84 | 1.90 | 0.00 |
| recover-01 | mean_quality | 0.80 | 0.00 | 0.00 |
| recover-01 | tokens_per_success | 297.25 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| routing-01 | pass_rate | 0.00 | 0.00 | 0.00 |
| routing-01 | mean_tokens | 351.80 | 0.00 | 0.00 |
| routing-01 | p25_tokens | 334.00 | 0.00 | 0.00 |
| routing-01 | p75_tokens | 375.00 | 0.00 | 0.00 |
| routing-01 | mean_wall | 1.21 | 1.92 | 0.00 |
| routing-01 | mean_quality | 0.00 | 0.00 | 0.00 |
| routing-01 | tokens_per_success | 0.00 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| routing-02 | pass_rate | 0.00 | 0.00 | 0.00 |
| routing-02 | mean_tokens | 599.00 | 0.00 | 0.00 |
| routing-02 | p25_tokens | 599.00 | 0.00 | 0.00 |
| routing-02 | p75_tokens | 599.00 | 0.00 | 0.00 |
| routing-02 | mean_wall | 2.39 | 1.96 | 0.00 |
| routing-02 | mean_quality | 0.00 | 0.00 | 0.00 |
| routing-02 | tokens_per_success | 0.00 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| search-01 | pass_rate | 0.00 | 0.00 | 0.00 |
| search-01 | mean_tokens | 208.20 | 0.00 | 0.00 |
| search-01 | p25_tokens | 187.00 | 0.00 | 0.00 |
| search-01 | p75_tokens | 236.00 | 0.00 | 0.00 |
| search-01 | mean_wall | 0.73 | 1.88 | 0.00 |
| search-01 | mean_quality | 0.00 | 0.00 | 0.00 |
| search-01 | tokens_per_success | 0.00 | 0.00 | 0.00 |