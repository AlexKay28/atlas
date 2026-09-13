# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 350.80 | 331.00 | 335.00 | 357.00 | 1.53 | 350.80 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 815.80 | 770.00 | 832.00 | 861.00 | 2.95 | 815.80 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 370.20 | 257.00 | 296.00 | 489.00 | 1.65 | 370.20 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 721.60 | 671.00 | 688.00 | 748.00 | 2.69 | 721.60 |
| plan-01 | classic | 5 | 0.80 | 0.80 | 526.20 | 526.00 | 528.00 | 549.00 | 2.44 | 520.50 |
| plan-01 | tahoe | 5 | 0.00 | 0.00 | 1099.60 | 962.00 | 993.00 | 1290.00 | 4.14 | 0.00 |
| recover-01 | classic | 5 | 0.80 | 0.80 | 400.40 | 339.00 | 383.00 | 429.00 | 1.90 | 362.50 |
| recover-01 | tahoe | 5 | 0.00 | 0.00 | 1084.80 | 857.00 | 952.00 | 1221.00 | 4.09 | 0.00 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 362.20 | 325.00 | 355.00 | 391.00 | 1.25 | 362.20 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 889.60 | 804.00 | 877.00 | 880.00 | 3.10 | 889.60 |
| routing-02 | classic | 5 | 0.20 | 0.20 | 599.00 | 599.00 | 599.00 | 599.00 | 2.39 | 599.00 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 829.40 | 735.00 | 797.00 | 823.00 | 2.70 | 829.40 |
| search-01 | classic | 5 | 1.00 | 1.00 | 211.60 | 196.00 | 199.00 | 235.00 | 0.75 | 211.60 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 523.60 | 495.00 | 511.00 | 565.00 | 1.70 | 523.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 1.00 |
| code-fix-01 | mean_tokens | 350.80 | 815.80 |
| code-fix-01 | p25_tokens | 331.00 | 770.00 |
| code-fix-01 | p75_tokens | 357.00 | 861.00 |
| code-fix-01 | mean_wall | 1.53 | 2.95 |
| code-fix-01 | mean_quality | 1.00 | 1.00 |
| code-fix-01 | tokens_per_success | 350.80 | 815.80 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 370.20 | 721.60 |
| code-fix-02 | p25_tokens | 257.00 | 671.00 |
| code-fix-02 | p75_tokens | 489.00 | 748.00 |
| code-fix-02 | mean_wall | 1.65 | 2.69 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 370.20 | 721.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 0.80 | 0.00 |
| plan-01 | mean_tokens | 526.20 | 1099.60 |
| plan-01 | p25_tokens | 526.00 | 962.00 |
| plan-01 | p75_tokens | 549.00 | 1290.00 |
| plan-01 | mean_wall | 2.44 | 4.14 |
| plan-01 | mean_quality | 0.80 | 0.00 |
| plan-01 | tokens_per_success | 520.50 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 0.80 | 0.00 |
| recover-01 | mean_tokens | 400.40 | 1084.80 |
| recover-01 | p25_tokens | 339.00 | 857.00 |
| recover-01 | p75_tokens | 429.00 | 1221.00 |
| recover-01 | mean_wall | 1.90 | 4.09 |
| recover-01 | mean_quality | 0.80 | 0.00 |
| recover-01 | tokens_per_success | 362.50 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 362.20 | 889.60 |
| routing-01 | p25_tokens | 325.00 | 804.00 |
| routing-01 | p75_tokens | 391.00 | 880.00 |
| routing-01 | mean_wall | 1.25 | 3.10 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 362.20 | 889.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.20 | 1.00 |
| routing-02 | mean_tokens | 599.00 | 829.40 |
| routing-02 | p25_tokens | 599.00 | 735.00 |
| routing-02 | p75_tokens | 599.00 | 823.00 |
| routing-02 | mean_wall | 2.39 | 2.70 |
| routing-02 | mean_quality | 0.20 | 1.00 |
| routing-02 | tokens_per_success | 599.00 | 829.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 211.60 | 523.60 |
| search-01 | p25_tokens | 196.00 | 495.00 |
| search-01 | p75_tokens | 235.00 | 565.00 |
| search-01 | mean_wall | 0.75 | 1.70 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 211.60 | 523.60 |