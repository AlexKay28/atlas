# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 446.20 | 427.00 | 478.00 | 506.00 | 1.98 | 446.20 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 853.40 | 761.00 | 784.00 | 784.00 | 3.27 | 853.40 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 301.20 | 272.00 | 282.00 | 283.00 | 1.32 | 301.20 |
| code-fix-02 | tahoe | 5 | 0.80 | 0.80 | 756.60 | 695.00 | 738.00 | 817.00 | 2.88 | 741.50 |
| plan-01 | classic | 5 | 1.00 | 1.00 | 536.60 | 522.00 | 549.00 | 549.00 | 2.48 | 536.60 |
| plan-01 | tahoe | 5 | 0.00 | 0.00 | 912.80 | 891.00 | 910.00 | 912.00 | 2.87 | 0.00 |
| recover-01 | classic | 5 | 0.80 | 0.80 | 465.40 | 402.00 | 438.00 | 552.00 | 2.21 | 443.75 |
| recover-01 | tahoe | 5 | 0.00 | 0.00 | 973.00 | 898.00 | 914.00 | 1069.00 | 3.40 | 0.00 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 333.80 | 330.00 | 333.00 | 333.00 | 1.11 | 333.80 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 789.20 | 721.00 | 809.00 | 811.00 | 2.51 | 789.20 |
| routing-02 | classic | 5 | 0.40 | 0.40 | 599.00 | 599.00 | 599.00 | 599.00 | 2.59 | 599.00 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 873.60 | 891.00 | 899.00 | 899.00 | 2.92 | 873.60 |
| search-01 | classic | 5 | 1.00 | 1.00 | 208.60 | 190.00 | 204.00 | 229.00 | 0.77 | 208.60 |
| search-01 | tahoe | 5 | 0.20 | 0.20 | 1449.40 | 933.00 | 1450.00 | 1884.00 | 5.82 | 1884.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 1.00 |
| code-fix-01 | mean_tokens | 446.20 | 853.40 |
| code-fix-01 | p25_tokens | 427.00 | 761.00 |
| code-fix-01 | p75_tokens | 506.00 | 784.00 |
| code-fix-01 | mean_wall | 1.98 | 3.27 |
| code-fix-01 | mean_quality | 1.00 | 1.00 |
| code-fix-01 | tokens_per_success | 446.20 | 853.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 0.80 |
| code-fix-02 | mean_tokens | 301.20 | 756.60 |
| code-fix-02 | p25_tokens | 272.00 | 695.00 |
| code-fix-02 | p75_tokens | 283.00 | 817.00 |
| code-fix-02 | mean_wall | 1.32 | 2.88 |
| code-fix-02 | mean_quality | 1.00 | 0.80 |
| code-fix-02 | tokens_per_success | 301.20 | 741.50 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 1.00 | 0.00 |
| plan-01 | mean_tokens | 536.60 | 912.80 |
| plan-01 | p25_tokens | 522.00 | 891.00 |
| plan-01 | p75_tokens | 549.00 | 912.00 |
| plan-01 | mean_wall | 2.48 | 2.87 |
| plan-01 | mean_quality | 1.00 | 0.00 |
| plan-01 | tokens_per_success | 536.60 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 0.80 | 0.00 |
| recover-01 | mean_tokens | 465.40 | 973.00 |
| recover-01 | p25_tokens | 402.00 | 898.00 |
| recover-01 | p75_tokens | 552.00 | 1069.00 |
| recover-01 | mean_wall | 2.21 | 3.40 |
| recover-01 | mean_quality | 0.80 | 0.00 |
| recover-01 | tokens_per_success | 443.75 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 333.80 | 789.20 |
| routing-01 | p25_tokens | 330.00 | 721.00 |
| routing-01 | p75_tokens | 333.00 | 811.00 |
| routing-01 | mean_wall | 1.11 | 2.51 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 333.80 | 789.20 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.40 | 1.00 |
| routing-02 | mean_tokens | 599.00 | 873.60 |
| routing-02 | p25_tokens | 599.00 | 891.00 |
| routing-02 | p75_tokens | 599.00 | 899.00 |
| routing-02 | mean_wall | 2.59 | 2.92 |
| routing-02 | mean_quality | 0.40 | 1.00 |
| routing-02 | tokens_per_success | 599.00 | 873.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 0.20 |
| search-01 | mean_tokens | 208.60 | 1449.40 |
| search-01 | p25_tokens | 190.00 | 933.00 |
| search-01 | p75_tokens | 229.00 | 1884.00 |
| search-01 | mean_wall | 0.77 | 5.82 |
| search-01 | mean_quality | 1.00 | 0.20 |
| search-01 | tokens_per_success | 208.60 | 1884.00 |