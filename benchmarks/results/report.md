# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success | RE | RC | RR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 522.60 | 333.00 | 683.00 | 684.00 | 2.33 | 522.60 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 260.00 | 253.00 | 258.00 | 264.00 | 0.31 | 260.00 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 302.00 | 255.00 | 301.00 | 348.00 | 1.64 | 302.00 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 286.80 | 282.00 | 283.00 | 289.00 | 0.43 | 286.80 | 0.0000 | 0.0000 | 0.0000 |
| plan-01 | classic | 5 | 1.00 | 1.00 | 650.80 | 651.00 | 667.00 | 708.00 | 3.01 | 650.80 | 0.0000 | 0.0000 | 0.0000 |
| plan-01 | tahoe | 5 | 0.20 | 0.20 | 484.20 | 484.00 | 484.00 | 486.00 | 1.48 | 574.00 | 0.0000 | 0.0000 | 0.0000 |
| recover-01 | classic | 5 | 1.00 | 1.00 | 441.00 | 403.00 | 426.00 | 486.00 | 2.16 | 441.00 | 0.0000 | 0.0000 | 0.0000 |
| recover-01 | tahoe | 5 | 1.00 | 1.00 | 369.80 | 345.00 | 368.00 | 373.00 | 0.93 | 369.80 | 0.0000 | 0.0000 | 0.0000 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 374.20 | 371.00 | 379.00 | 390.00 | 1.37 | 374.20 | 0.0000 | 0.0000 | 0.0000 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 344.40 | 351.00 | 355.00 | 356.00 | 0.55 | 344.40 | 0.0000 | 0.0000 | 0.0000 |
| routing-02 | classic | 5 | 0.80 | 0.80 | 916.20 | 817.00 | 900.00 | 944.00 | 3.64 | 867.50 | 0.0000 | 0.0000 | 0.0000 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 461.60 | 419.00 | 446.00 | 507.00 | 1.04 | 461.60 | 0.0000 | 0.0000 | 0.0000 |
| search-01 | classic | 5 | 1.00 | 1.00 | 196.80 | 188.00 | 190.00 | 202.00 | 0.72 | 196.80 | 0.0000 | 0.0000 | 0.0000 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 294.20 | 278.00 | 287.00 | 310.00 | 0.45 | 294.20 | 0.0000 | 0.0000 | 0.0000 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 1.00 |
| code-fix-01 | mean_tokens | 522.60 | 260.00 |
| code-fix-01 | p25_tokens | 333.00 | 253.00 |
| code-fix-01 | p75_tokens | 684.00 | 264.00 |
| code-fix-01 | mean_wall | 2.33 | 0.31 |
| code-fix-01 | mean_quality | 1.00 | 1.00 |
| code-fix-01 | tokens_per_success | 522.60 | 260.00 |
| code-fix-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| code-fix-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| code-fix-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 302.00 | 286.80 |
| code-fix-02 | p25_tokens | 255.00 | 282.00 |
| code-fix-02 | p75_tokens | 348.00 | 289.00 |
| code-fix-02 | mean_wall | 1.64 | 0.43 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 302.00 | 286.80 |
| code-fix-02 | re_reasoning_efficiency | 0.00 | 0.00 |
| code-fix-02 | rc_reasoning_concentration | 0.00 | 0.00 |
| code-fix-02 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 1.00 | 0.20 |
| plan-01 | mean_tokens | 650.80 | 484.20 |
| plan-01 | p25_tokens | 651.00 | 484.00 |
| plan-01 | p75_tokens | 708.00 | 486.00 |
| plan-01 | mean_wall | 3.01 | 1.48 |
| plan-01 | mean_quality | 1.00 | 0.20 |
| plan-01 | tokens_per_success | 650.80 | 574.00 |
| plan-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| plan-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| plan-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 1.00 | 1.00 |
| recover-01 | mean_tokens | 441.00 | 369.80 |
| recover-01 | p25_tokens | 403.00 | 345.00 |
| recover-01 | p75_tokens | 486.00 | 373.00 |
| recover-01 | mean_wall | 2.16 | 0.93 |
| recover-01 | mean_quality | 1.00 | 1.00 |
| recover-01 | tokens_per_success | 441.00 | 369.80 |
| recover-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| recover-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| recover-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 374.20 | 344.40 |
| routing-01 | p25_tokens | 371.00 | 351.00 |
| routing-01 | p75_tokens | 390.00 | 356.00 |
| routing-01 | mean_wall | 1.37 | 0.55 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 374.20 | 344.40 |
| routing-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| routing-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| routing-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.80 | 1.00 |
| routing-02 | mean_tokens | 916.20 | 461.60 |
| routing-02 | p25_tokens | 817.00 | 419.00 |
| routing-02 | p75_tokens | 944.00 | 507.00 |
| routing-02 | mean_wall | 3.64 | 1.04 |
| routing-02 | mean_quality | 0.80 | 1.00 |
| routing-02 | tokens_per_success | 867.50 | 461.60 |
| routing-02 | re_reasoning_efficiency | 0.00 | 0.00 |
| routing-02 | rc_reasoning_concentration | 0.00 | 0.00 |
| routing-02 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 196.80 | 294.20 |
| search-01 | p25_tokens | 188.00 | 278.00 |
| search-01 | p75_tokens | 202.00 | 310.00 |
| search-01 | mean_wall | 0.72 | 0.45 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 196.80 | 294.20 |
| search-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| search-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| search-01 | rr_redundancy_rate | 0.00 | 0.00 |