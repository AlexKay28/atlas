# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 327.60 | 254.00 | 306.00 | 409.00 | 1.40 | 327.60 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 629.00 | 598.00 | 608.00 | 672.00 | 0.54 | 629.00 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 247.00 | 225.00 | 244.00 | 296.00 | 1.05 | 247.00 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 635.40 | 619.00 | 629.00 | 640.00 | 0.52 | 635.40 |
| plan-01 | classic | 5 | 0.20 | 0.20 | 549.00 | 549.00 | 549.00 | 549.00 | 2.56 | 549.00 |
| plan-01 | tahoe | 5 | 0.40 | 0.40 | 726.20 | 711.00 | 724.00 | 734.00 | 1.05 | 731.00 |
| recover-01 | classic | 5 | 0.80 | 0.80 | 464.00 | 431.00 | 506.00 | 506.00 | 2.25 | 442.00 |
| recover-01 | tahoe | 5 | 1.00 | 1.00 | 695.40 | 646.00 | 716.00 | 725.00 | 0.86 | 695.40 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 338.20 | 328.00 | 343.00 | 350.00 | 1.15 | 338.20 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 700.60 | 685.00 | 685.00 | 704.00 | 0.68 | 700.60 |
| routing-02 | classic | 5 | 0.20 | 0.20 | 599.00 | 599.00 | 599.00 | 599.00 | 2.43 | 599.00 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 1072.00 | 974.00 | 1002.00 | 1125.00 | 2.19 | 1072.00 |
| search-01 | classic | 5 | 1.00 | 1.00 | 198.20 | 189.00 | 192.00 | 193.00 | 0.70 | 198.20 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 620.80 | 616.00 | 627.00 | 628.00 | 0.43 | 620.80 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 1.00 |
| code-fix-01 | mean_tokens | 327.60 | 629.00 |
| code-fix-01 | p25_tokens | 254.00 | 598.00 |
| code-fix-01 | p75_tokens | 409.00 | 672.00 |
| code-fix-01 | mean_wall | 1.40 | 0.54 |
| code-fix-01 | mean_quality | 1.00 | 1.00 |
| code-fix-01 | tokens_per_success | 327.60 | 629.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 247.00 | 635.40 |
| code-fix-02 | p25_tokens | 225.00 | 619.00 |
| code-fix-02 | p75_tokens | 296.00 | 640.00 |
| code-fix-02 | mean_wall | 1.05 | 0.52 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 247.00 | 635.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 0.20 | 0.40 |
| plan-01 | mean_tokens | 549.00 | 726.20 |
| plan-01 | p25_tokens | 549.00 | 711.00 |
| plan-01 | p75_tokens | 549.00 | 734.00 |
| plan-01 | mean_wall | 2.56 | 1.05 |
| plan-01 | mean_quality | 0.20 | 0.40 |
| plan-01 | tokens_per_success | 549.00 | 731.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 0.80 | 1.00 |
| recover-01 | mean_tokens | 464.00 | 695.40 |
| recover-01 | p25_tokens | 431.00 | 646.00 |
| recover-01 | p75_tokens | 506.00 | 725.00 |
| recover-01 | mean_wall | 2.25 | 0.86 |
| recover-01 | mean_quality | 0.80 | 1.00 |
| recover-01 | tokens_per_success | 442.00 | 695.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 338.20 | 700.60 |
| routing-01 | p25_tokens | 328.00 | 685.00 |
| routing-01 | p75_tokens | 350.00 | 704.00 |
| routing-01 | mean_wall | 1.15 | 0.68 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 338.20 | 700.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.20 | 1.00 |
| routing-02 | mean_tokens | 599.00 | 1072.00 |
| routing-02 | p25_tokens | 599.00 | 974.00 |
| routing-02 | p75_tokens | 599.00 | 1125.00 |
| routing-02 | mean_wall | 2.43 | 2.19 |
| routing-02 | mean_quality | 0.20 | 1.00 |
| routing-02 | tokens_per_success | 599.00 | 1072.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 198.20 | 620.80 |
| search-01 | p25_tokens | 189.00 | 616.00 |
| search-01 | p75_tokens | 193.00 | 628.00 |
| search-01 | mean_wall | 0.70 | 0.43 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 198.20 | 620.80 |