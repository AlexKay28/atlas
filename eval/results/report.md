# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 411.60 | 371.00 | 426.00 | 428.00 | 1.72 | 411.60 |
| code-fix-01 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.90 | 0.00 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 6.51 | 0.00 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 226.20 | 213.00 | 217.00 | 241.00 | 0.94 | 226.20 |
| code-fix-02 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.90 | 0.00 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 8.06 | 0.00 |
| plan-01 | classic | 5 | 0.00 | 0.00 | 549.00 | 549.00 | 549.00 | 549.00 | 2.59 | 0.00 |
| plan-01 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.89 | 0.00 |
| plan-01 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 9.59 | 0.00 |
| recover-01 | classic | 5 | 0.80 | 0.80 | 373.00 | 267.00 | 290.00 | 501.00 | 1.83 | 328.25 |
| recover-01 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.92 | 0.00 |
| recover-01 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 10.25 | 0.00 |
| routing-01 | classic | 5 | 0.00 | 0.00 | 331.00 | 321.00 | 327.00 | 339.00 | 1.11 | 0.00 |
| routing-01 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.92 | 0.00 |
| routing-01 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 12.25 | 0.00 |
| routing-02 | classic | 5 | 0.00 | 0.00 | 599.00 | 599.00 | 599.00 | 599.00 | 2.56 | 0.00 |
| routing-02 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.92 | 0.00 |
| routing-02 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 11.22 | 0.00 |
| search-01 | classic | 5 | 0.00 | 0.00 | 203.00 | 192.00 | 193.00 | 199.00 | 0.68 | 0.00 |
| search-01 | opencode | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.99 | 0.00 |
| search-01 | tahoe | 5 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 9.72 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 0.00 | 1.00 |
| code-fix-01 | mean_tokens | 411.60 | 0.00 | 0.00 |
| code-fix-01 | p25_tokens | 371.00 | 0.00 | 0.00 |
| code-fix-01 | p75_tokens | 428.00 | 0.00 | 0.00 |
| code-fix-01 | mean_wall | 1.72 | 1.90 | 6.51 |
| code-fix-01 | mean_quality | 1.00 | 0.00 | 1.00 |
| code-fix-01 | tokens_per_success | 411.60 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 0.00 | 1.00 |
| code-fix-02 | mean_tokens | 226.20 | 0.00 | 0.00 |
| code-fix-02 | p25_tokens | 213.00 | 0.00 | 0.00 |
| code-fix-02 | p75_tokens | 241.00 | 0.00 | 0.00 |
| code-fix-02 | mean_wall | 0.94 | 1.90 | 8.06 |
| code-fix-02 | mean_quality | 1.00 | 0.00 | 1.00 |
| code-fix-02 | tokens_per_success | 226.20 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| plan-01 | pass_rate | 0.00 | 0.00 | 0.00 |
| plan-01 | mean_tokens | 549.00 | 0.00 | 0.00 |
| plan-01 | p25_tokens | 549.00 | 0.00 | 0.00 |
| plan-01 | p75_tokens | 549.00 | 0.00 | 0.00 |
| plan-01 | mean_wall | 2.59 | 1.89 | 9.59 |
| plan-01 | mean_quality | 0.00 | 0.00 | 0.00 |
| plan-01 | tokens_per_success | 0.00 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| recover-01 | pass_rate | 0.80 | 0.00 | 0.00 |
| recover-01 | mean_tokens | 373.00 | 0.00 | 0.00 |
| recover-01 | p25_tokens | 267.00 | 0.00 | 0.00 |
| recover-01 | p75_tokens | 501.00 | 0.00 | 0.00 |
| recover-01 | mean_wall | 1.83 | 1.92 | 10.25 |
| recover-01 | mean_quality | 0.80 | 0.00 | 0.00 |
| recover-01 | tokens_per_success | 328.25 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| routing-01 | pass_rate | 0.00 | 0.00 | 0.00 |
| routing-01 | mean_tokens | 331.00 | 0.00 | 0.00 |
| routing-01 | p25_tokens | 321.00 | 0.00 | 0.00 |
| routing-01 | p75_tokens | 339.00 | 0.00 | 0.00 |
| routing-01 | mean_wall | 1.11 | 1.92 | 12.25 |
| routing-01 | mean_quality | 0.00 | 0.00 | 0.00 |
| routing-01 | tokens_per_success | 0.00 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| routing-02 | pass_rate | 0.00 | 0.00 | 0.00 |
| routing-02 | mean_tokens | 599.00 | 0.00 | 0.00 |
| routing-02 | p25_tokens | 599.00 | 0.00 | 0.00 |
| routing-02 | p75_tokens | 599.00 | 0.00 | 0.00 |
| routing-02 | mean_wall | 2.56 | 1.92 | 11.22 |
| routing-02 | mean_quality | 0.00 | 0.00 | 0.00 |
| routing-02 | tokens_per_success | 0.00 | 0.00 | 0.00 |

| task_id | metric | classic | opencode | tahoe |
|---|---|---|---|---|
| search-01 | pass_rate | 0.00 | 0.00 | 0.00 |
| search-01 | mean_tokens | 203.00 | 0.00 | 0.00 |
| search-01 | p25_tokens | 192.00 | 0.00 | 0.00 |
| search-01 | p75_tokens | 199.00 | 0.00 | 0.00 |
| search-01 | mean_wall | 0.68 | 1.99 | 9.72 |
| search-01 | mean_quality | 0.00 | 0.00 | 0.00 |
| search-01 | tokens_per_success | 0.00 | 0.00 | 0.00 |