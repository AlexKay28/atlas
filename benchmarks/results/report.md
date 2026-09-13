# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 0.60 | 0.60 | 498.60 | 506.00 | 534.00 | 557.00 | 2.78 | 459.67 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 651.00 | 631.00 | 633.00 | 685.00 | 0.67 | 651.00 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 307.00 | 238.00 | 253.00 | 336.00 | 1.61 | 307.00 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 638.00 | 620.00 | 643.00 | 648.00 | 0.52 | 638.00 |
| plan-01 | classic | 5 | 0.40 | 0.40 | 543.00 | 549.00 | 549.00 | 549.00 | 2.69 | 534.00 |
| plan-01 | tahoe | 5 | 0.00 | 0.00 | 787.40 | 776.00 | 833.00 | 844.00 | 1.41 | 0.00 |
| recover-01 | classic | 5 | 1.00 | 1.00 | 419.00 | 365.00 | 430.00 | 490.00 | 2.43 | 419.00 |
| recover-01 | tahoe | 5 | 1.00 | 1.00 | 688.60 | 666.00 | 672.00 | 684.00 | 0.99 | 688.60 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 350.40 | 332.00 | 334.00 | 373.00 | 1.20 | 350.40 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 677.20 | 658.00 | 682.00 | 690.00 | 1.02 | 677.20 |
| routing-02 | classic | 5 | 0.40 | 0.40 | 590.40 | 599.00 | 599.00 | 599.00 | 2.56 | 577.50 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 938.40 | 887.00 | 1012.00 | 1023.00 | 1.94 | 938.40 |
| search-01 | classic | 5 | 1.00 | 1.00 | 214.40 | 196.00 | 207.00 | 234.00 | 0.82 | 214.40 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 642.60 | 626.00 | 639.00 | 643.00 | 0.56 | 642.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 0.60 | 1.00 |
| code-fix-01 | mean_tokens | 498.60 | 651.00 |
| code-fix-01 | p25_tokens | 506.00 | 631.00 |
| code-fix-01 | p75_tokens | 557.00 | 685.00 |
| code-fix-01 | mean_wall | 2.78 | 0.67 |
| code-fix-01 | mean_quality | 0.60 | 1.00 |
| code-fix-01 | tokens_per_success | 459.67 | 651.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 307.00 | 638.00 |
| code-fix-02 | p25_tokens | 238.00 | 620.00 |
| code-fix-02 | p75_tokens | 336.00 | 648.00 |
| code-fix-02 | mean_wall | 1.61 | 0.52 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 307.00 | 638.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 0.40 | 0.00 |
| plan-01 | mean_tokens | 543.00 | 787.40 |
| plan-01 | p25_tokens | 549.00 | 776.00 |
| plan-01 | p75_tokens | 549.00 | 844.00 |
| plan-01 | mean_wall | 2.69 | 1.41 |
| plan-01 | mean_quality | 0.40 | 0.00 |
| plan-01 | tokens_per_success | 534.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 1.00 | 1.00 |
| recover-01 | mean_tokens | 419.00 | 688.60 |
| recover-01 | p25_tokens | 365.00 | 666.00 |
| recover-01 | p75_tokens | 490.00 | 684.00 |
| recover-01 | mean_wall | 2.43 | 0.99 |
| recover-01 | mean_quality | 1.00 | 1.00 |
| recover-01 | tokens_per_success | 419.00 | 688.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 350.40 | 677.20 |
| routing-01 | p25_tokens | 332.00 | 658.00 |
| routing-01 | p75_tokens | 373.00 | 690.00 |
| routing-01 | mean_wall | 1.20 | 1.02 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 350.40 | 677.20 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.40 | 1.00 |
| routing-02 | mean_tokens | 590.40 | 938.40 |
| routing-02 | p25_tokens | 599.00 | 887.00 |
| routing-02 | p75_tokens | 599.00 | 1023.00 |
| routing-02 | mean_wall | 2.56 | 1.94 |
| routing-02 | mean_quality | 0.40 | 1.00 |
| routing-02 | tokens_per_success | 577.50 | 938.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 214.40 | 642.60 |
| search-01 | p25_tokens | 196.00 | 626.00 |
| search-01 | p75_tokens | 234.00 | 643.00 |
| search-01 | mean_wall | 0.82 | 0.56 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 214.40 | 642.60 |