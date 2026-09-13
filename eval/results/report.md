# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 0.80 | 0.80 | 474.00 | 461.00 | 490.00 | 546.00 | 2.01 | 453.25 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 2439.00 | 2306.00 | 2574.00 | 2603.00 | 8.94 | 2439.00 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 288.80 | 251.00 | 267.00 | 271.00 | 1.28 | 288.80 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 1852.80 | 1660.00 | 1804.00 | 1819.00 | 7.31 | 1852.80 |
| plan-01 | classic | 5 | 0.00 | 0.00 | 546.60 | 549.00 | 549.00 | 549.00 | 2.61 | 0.00 |
| plan-01 | tahoe | 5 | 0.00 | 0.00 | 2094.40 | 1919.00 | 2112.00 | 2225.00 | 8.64 | 0.00 |
| recover-01 | classic | 5 | 0.60 | 0.60 | 478.80 | 496.00 | 552.00 | 552.00 | 2.41 | 430.00 |
| recover-01 | tahoe | 5 | 0.00 | 0.00 | 2295.60 | 2031.00 | 2241.00 | 2306.00 | 9.57 | 0.00 |
| routing-01 | classic | 5 | 0.00 | 0.00 | 362.60 | 323.00 | 370.00 | 397.00 | 1.18 | 0.00 |
| routing-01 | tahoe | 5 | 0.00 | 0.00 | 2340.20 | 2027.00 | 2359.00 | 2372.00 | 10.37 | 0.00 |
| routing-02 | classic | 5 | 0.00 | 0.00 | 599.00 | 599.00 | 599.00 | 599.00 | 2.33 | 0.00 |
| routing-02 | tahoe | 5 | 0.00 | 0.00 | 2351.40 | 2121.00 | 2130.00 | 2296.00 | 10.22 | 0.00 |
| search-01 | classic | 5 | 0.00 | 0.00 | 210.00 | 195.00 | 202.00 | 204.00 | 0.71 | 0.00 |
| search-01 | tahoe | 5 | 0.00 | 0.00 | 2039.60 | 1946.00 | 2076.00 | 2114.00 | 9.60 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 0.80 | 1.00 |
| code-fix-01 | mean_tokens | 474.00 | 2439.00 |
| code-fix-01 | p25_tokens | 461.00 | 2306.00 |
| code-fix-01 | p75_tokens | 546.00 | 2603.00 |
| code-fix-01 | mean_wall | 2.01 | 8.94 |
| code-fix-01 | mean_quality | 0.80 | 1.00 |
| code-fix-01 | tokens_per_success | 453.25 | 2439.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 288.80 | 1852.80 |
| code-fix-02 | p25_tokens | 251.00 | 1660.00 |
| code-fix-02 | p75_tokens | 271.00 | 1819.00 |
| code-fix-02 | mean_wall | 1.28 | 7.31 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 288.80 | 1852.80 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 0.00 | 0.00 |
| plan-01 | mean_tokens | 546.60 | 2094.40 |
| plan-01 | p25_tokens | 549.00 | 1919.00 |
| plan-01 | p75_tokens | 549.00 | 2225.00 |
| plan-01 | mean_wall | 2.61 | 8.64 |
| plan-01 | mean_quality | 0.00 | 0.00 |
| plan-01 | tokens_per_success | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 0.60 | 0.00 |
| recover-01 | mean_tokens | 478.80 | 2295.60 |
| recover-01 | p25_tokens | 496.00 | 2031.00 |
| recover-01 | p75_tokens | 552.00 | 2306.00 |
| recover-01 | mean_wall | 2.41 | 9.57 |
| recover-01 | mean_quality | 0.60 | 0.00 |
| recover-01 | tokens_per_success | 430.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 0.00 | 0.00 |
| routing-01 | mean_tokens | 362.60 | 2340.20 |
| routing-01 | p25_tokens | 323.00 | 2027.00 |
| routing-01 | p75_tokens | 397.00 | 2372.00 |
| routing-01 | mean_wall | 1.18 | 10.37 |
| routing-01 | mean_quality | 0.00 | 0.00 |
| routing-01 | tokens_per_success | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.00 | 0.00 |
| routing-02 | mean_tokens | 599.00 | 2351.40 |
| routing-02 | p25_tokens | 599.00 | 2121.00 |
| routing-02 | p75_tokens | 599.00 | 2296.00 |
| routing-02 | mean_wall | 2.33 | 10.22 |
| routing-02 | mean_quality | 0.00 | 0.00 |
| routing-02 | tokens_per_success | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 0.00 | 0.00 |
| search-01 | mean_tokens | 210.00 | 2039.60 |
| search-01 | p25_tokens | 195.00 | 1946.00 |
| search-01 | p75_tokens | 204.00 | 2114.00 |
| search-01 | mean_wall | 0.71 | 9.60 |
| search-01 | mean_quality | 0.00 | 0.00 |
| search-01 | tokens_per_success | 0.00 | 0.00 |