# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success | RE | RC | RR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 361.20 | 310.00 | 352.00 | 362.00 | 1.54 | 361.20 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 281.00 | 244.00 | 314.00 | 317.00 | 0.54 | 281.00 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 307.20 | 242.00 | 252.00 | 265.00 | 1.36 | 307.20 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 260.80 | 260.00 | 267.00 | 272.00 | 0.43 | 260.80 | 0.0000 | 0.0000 | 0.0000 |
| plan-01 | classic | 5 | 1.00 | 1.00 | 730.00 | 682.00 | 763.00 | 767.00 | 3.47 | 730.00 | 0.0000 | 0.0000 | 0.0000 |
| plan-01 | tahoe | 5 | 0.20 | 0.20 | 486.80 | 410.00 | 419.00 | 527.00 | 1.69 | 410.00 | 0.0000 | 0.0000 | 0.0000 |
| recover-01 | classic | 5 | 1.00 | 1.00 | 604.20 | 516.00 | 537.00 | 733.00 | 2.94 | 604.20 | 0.0000 | 0.0000 | 0.0000 |
| recover-01 | tahoe | 5 | 1.00 | 1.00 | 337.00 | 319.00 | 328.00 | 358.00 | 0.87 | 337.00 | 0.0000 | 0.0000 | 0.0000 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 383.20 | 382.00 | 382.00 | 384.00 | 1.29 | 383.20 | 0.0000 | 0.0000 | 0.0000 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 320.80 | 322.00 | 324.00 | 324.00 | 0.55 | 320.80 | 0.0000 | 0.0000 | 0.0000 |
| routing-02 | classic | 5 | 0.80 | 0.80 | 946.00 | 867.00 | 884.00 | 1111.00 | 4.12 | 904.75 | 0.0000 | 0.0000 | 0.0000 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 427.60 | 417.00 | 420.00 | 427.00 | 1.03 | 427.60 | 0.0000 | 0.0000 | 0.0000 |
| search-01 | classic | 5 | 1.00 | 1.00 | 227.60 | 195.00 | 210.00 | 240.00 | 0.85 | 227.60 | 0.0000 | 0.0000 | 0.0000 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 253.40 | 248.00 | 248.00 | 257.00 | 0.39 | 253.40 | 0.0000 | 0.0000 | 0.0000 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 1.00 |
| code-fix-01 | mean_tokens | 361.20 | 281.00 |
| code-fix-01 | p25_tokens | 310.00 | 244.00 |
| code-fix-01 | p75_tokens | 362.00 | 317.00 |
| code-fix-01 | mean_wall | 1.54 | 0.54 |
| code-fix-01 | mean_quality | 1.00 | 1.00 |
| code-fix-01 | tokens_per_success | 361.20 | 281.00 |
| code-fix-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| code-fix-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| code-fix-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 307.20 | 260.80 |
| code-fix-02 | p25_tokens | 242.00 | 260.00 |
| code-fix-02 | p75_tokens | 265.00 | 272.00 |
| code-fix-02 | mean_wall | 1.36 | 0.43 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 307.20 | 260.80 |
| code-fix-02 | re_reasoning_efficiency | 0.00 | 0.00 |
| code-fix-02 | rc_reasoning_concentration | 0.00 | 0.00 |
| code-fix-02 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 1.00 | 0.20 |
| plan-01 | mean_tokens | 730.00 | 486.80 |
| plan-01 | p25_tokens | 682.00 | 410.00 |
| plan-01 | p75_tokens | 767.00 | 527.00 |
| plan-01 | mean_wall | 3.47 | 1.69 |
| plan-01 | mean_quality | 1.00 | 0.20 |
| plan-01 | tokens_per_success | 730.00 | 410.00 |
| plan-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| plan-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| plan-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 1.00 | 1.00 |
| recover-01 | mean_tokens | 604.20 | 337.00 |
| recover-01 | p25_tokens | 516.00 | 319.00 |
| recover-01 | p75_tokens | 733.00 | 358.00 |
| recover-01 | mean_wall | 2.94 | 0.87 |
| recover-01 | mean_quality | 1.00 | 1.00 |
| recover-01 | tokens_per_success | 604.20 | 337.00 |
| recover-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| recover-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| recover-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 383.20 | 320.80 |
| routing-01 | p25_tokens | 382.00 | 322.00 |
| routing-01 | p75_tokens | 384.00 | 324.00 |
| routing-01 | mean_wall | 1.29 | 0.55 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 383.20 | 320.80 |
| routing-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| routing-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| routing-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.80 | 1.00 |
| routing-02 | mean_tokens | 946.00 | 427.60 |
| routing-02 | p25_tokens | 867.00 | 417.00 |
| routing-02 | p75_tokens | 1111.00 | 427.00 |
| routing-02 | mean_wall | 4.12 | 1.03 |
| routing-02 | mean_quality | 0.80 | 1.00 |
| routing-02 | tokens_per_success | 904.75 | 427.60 |
| routing-02 | re_reasoning_efficiency | 0.00 | 0.00 |
| routing-02 | rc_reasoning_concentration | 0.00 | 0.00 |
| routing-02 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 227.60 | 253.40 |
| search-01 | p25_tokens | 195.00 | 248.00 |
| search-01 | p75_tokens | 240.00 | 257.00 |
| search-01 | mean_wall | 0.85 | 0.39 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 227.60 | 253.40 |
| search-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| search-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| search-01 | rr_redundancy_rate | 0.00 | 0.00 |