# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 0.80 | 0.80 | 411.20 | 350.00 | 476.00 | 503.00 | 1.80 | 374.75 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 923.60 | 880.00 | 922.00 | 1039.00 | 3.54 | 923.60 |
| code-fix-02 | classic | 5 | 0.80 | 0.80 | 361.80 | 267.00 | 344.00 | 425.00 | 1.63 | 311.00 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 728.60 | 678.00 | 698.00 | 817.00 | 2.77 | 728.60 |
| plan-01 | classic | 5 | 0.00 | 0.00 | 532.00 | 549.00 | 549.00 | 549.00 | 2.50 | 0.00 |
| plan-01 | tahoe | 5 | 0.00 | 0.00 | 1014.60 | 950.00 | 1041.00 | 1088.00 | 3.30 | 0.00 |
| recover-01 | classic | 5 | 0.80 | 0.80 | 541.00 | 529.00 | 552.00 | 552.00 | 2.68 | 538.25 |
| recover-01 | tahoe | 5 | 0.00 | 0.00 | 1063.00 | 850.00 | 1114.00 | 1126.00 | 3.83 | 0.00 |
| routing-01 | classic | 5 | 0.00 | 0.00 | 364.20 | 354.00 | 357.00 | 375.00 | 1.26 | 0.00 |
| routing-01 | tahoe | 5 | 0.00 | 0.00 | 795.80 | 708.00 | 794.00 | 798.00 | 2.58 | 0.00 |
| routing-02 | classic | 5 | 0.00 | 0.00 | 594.60 | 599.00 | 599.00 | 599.00 | 2.50 | 0.00 |
| routing-02 | tahoe | 5 | 0.00 | 0.00 | 891.40 | 863.00 | 896.00 | 918.00 | 2.88 | 0.00 |
| search-01 | classic | 5 | 0.00 | 0.00 | 200.20 | 193.00 | 203.00 | 206.00 | 0.70 | 0.00 |
| search-01 | tahoe | 5 | 0.00 | 0.00 | 1746.80 | 1492.00 | 1627.00 | 1775.00 | 7.08 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 0.80 | 1.00 |
| code-fix-01 | mean_tokens | 411.20 | 923.60 |
| code-fix-01 | p25_tokens | 350.00 | 880.00 |
| code-fix-01 | p75_tokens | 503.00 | 1039.00 |
| code-fix-01 | mean_wall | 1.80 | 3.54 |
| code-fix-01 | mean_quality | 0.80 | 1.00 |
| code-fix-01 | tokens_per_success | 374.75 | 923.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 0.80 | 1.00 |
| code-fix-02 | mean_tokens | 361.80 | 728.60 |
| code-fix-02 | p25_tokens | 267.00 | 678.00 |
| code-fix-02 | p75_tokens | 425.00 | 817.00 |
| code-fix-02 | mean_wall | 1.63 | 2.77 |
| code-fix-02 | mean_quality | 0.80 | 1.00 |
| code-fix-02 | tokens_per_success | 311.00 | 728.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 0.00 | 0.00 |
| plan-01 | mean_tokens | 532.00 | 1014.60 |
| plan-01 | p25_tokens | 549.00 | 950.00 |
| plan-01 | p75_tokens | 549.00 | 1088.00 |
| plan-01 | mean_wall | 2.50 | 3.30 |
| plan-01 | mean_quality | 0.00 | 0.00 |
| plan-01 | tokens_per_success | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 0.80 | 0.00 |
| recover-01 | mean_tokens | 541.00 | 1063.00 |
| recover-01 | p25_tokens | 529.00 | 850.00 |
| recover-01 | p75_tokens | 552.00 | 1126.00 |
| recover-01 | mean_wall | 2.68 | 3.83 |
| recover-01 | mean_quality | 0.80 | 0.00 |
| recover-01 | tokens_per_success | 538.25 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 0.00 | 0.00 |
| routing-01 | mean_tokens | 364.20 | 795.80 |
| routing-01 | p25_tokens | 354.00 | 708.00 |
| routing-01 | p75_tokens | 375.00 | 798.00 |
| routing-01 | mean_wall | 1.26 | 2.58 |
| routing-01 | mean_quality | 0.00 | 0.00 |
| routing-01 | tokens_per_success | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.00 | 0.00 |
| routing-02 | mean_tokens | 594.60 | 891.40 |
| routing-02 | p25_tokens | 599.00 | 863.00 |
| routing-02 | p75_tokens | 599.00 | 918.00 |
| routing-02 | mean_wall | 2.50 | 2.88 |
| routing-02 | mean_quality | 0.00 | 0.00 |
| routing-02 | tokens_per_success | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 0.00 | 0.00 |
| search-01 | mean_tokens | 200.20 | 1746.80 |
| search-01 | p25_tokens | 193.00 | 1492.00 |
| search-01 | p75_tokens | 206.00 | 1775.00 |
| search-01 | mean_wall | 0.70 | 7.08 |
| search-01 | mean_quality | 0.00 | 0.00 |
| search-01 | tokens_per_success | 0.00 | 0.00 |