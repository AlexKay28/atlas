# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 0.80 | 0.80 | 413.80 | 351.00 | 406.00 | 472.00 | 1.91 | 378.00 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 547.00 | 510.00 | 521.00 | 559.00 | 1.37 | 547.00 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 274.60 | 208.00 | 295.00 | 337.00 | 2.74 | 274.60 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 447.20 | 398.00 | 410.00 | 496.00 | 0.78 | 447.20 |
| plan-01 | classic | 5 | 0.20 | 0.20 | 549.00 | 549.00 | 549.00 | 549.00 | 2.54 | 549.00 |
| plan-01 | tahoe | 5 | 0.80 | 0.80 | 760.80 | 744.00 | 770.00 | 777.00 | 2.59 | 784.75 |
| recover-01 | classic | 5 | 0.80 | 0.80 | 404.60 | 358.00 | 393.00 | 445.00 | 2.21 | 367.75 |
| recover-01 | tahoe | 5 | 1.00 | 1.00 | 536.40 | 560.00 | 571.00 | 576.00 | 1.33 | 536.40 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 326.60 | 308.00 | 320.00 | 335.00 | 1.11 | 326.60 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 527.40 | 517.00 | 531.00 | 535.00 | 1.09 | 527.40 |
| routing-02 | classic | 5 | 0.20 | 0.20 | 599.00 | 599.00 | 599.00 | 599.00 | 2.63 | 599.00 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 1044.20 | 975.00 | 976.00 | 1146.00 | 2.95 | 1044.20 |
| search-01 | classic | 5 | 1.00 | 1.00 | 208.40 | 203.00 | 206.00 | 207.00 | 0.76 | 208.40 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 515.20 | 462.00 | 476.00 | 581.00 | 1.25 | 515.20 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 0.80 | 1.00 |
| code-fix-01 | mean_tokens | 413.80 | 547.00 |
| code-fix-01 | p25_tokens | 351.00 | 510.00 |
| code-fix-01 | p75_tokens | 472.00 | 559.00 |
| code-fix-01 | mean_wall | 1.91 | 1.37 |
| code-fix-01 | mean_quality | 0.80 | 1.00 |
| code-fix-01 | tokens_per_success | 378.00 | 547.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 274.60 | 447.20 |
| code-fix-02 | p25_tokens | 208.00 | 398.00 |
| code-fix-02 | p75_tokens | 337.00 | 496.00 |
| code-fix-02 | mean_wall | 2.74 | 0.78 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 274.60 | 447.20 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 0.20 | 0.80 |
| plan-01 | mean_tokens | 549.00 | 760.80 |
| plan-01 | p25_tokens | 549.00 | 744.00 |
| plan-01 | p75_tokens | 549.00 | 777.00 |
| plan-01 | mean_wall | 2.54 | 2.59 |
| plan-01 | mean_quality | 0.20 | 0.80 |
| plan-01 | tokens_per_success | 549.00 | 784.75 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 0.80 | 1.00 |
| recover-01 | mean_tokens | 404.60 | 536.40 |
| recover-01 | p25_tokens | 358.00 | 560.00 |
| recover-01 | p75_tokens | 445.00 | 576.00 |
| recover-01 | mean_wall | 2.21 | 1.33 |
| recover-01 | mean_quality | 0.80 | 1.00 |
| recover-01 | tokens_per_success | 367.75 | 536.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 326.60 | 527.40 |
| routing-01 | p25_tokens | 308.00 | 517.00 |
| routing-01 | p75_tokens | 335.00 | 535.00 |
| routing-01 | mean_wall | 1.11 | 1.09 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 326.60 | 527.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.20 | 1.00 |
| routing-02 | mean_tokens | 599.00 | 1044.20 |
| routing-02 | p25_tokens | 599.00 | 975.00 |
| routing-02 | p75_tokens | 599.00 | 1146.00 |
| routing-02 | mean_wall | 2.63 | 2.95 |
| routing-02 | mean_quality | 0.20 | 1.00 |
| routing-02 | tokens_per_success | 599.00 | 1044.20 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 208.40 | 515.20 |
| search-01 | p25_tokens | 203.00 | 462.00 |
| search-01 | p75_tokens | 207.00 | 581.00 |
| search-01 | mean_wall | 0.76 | 1.25 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 208.40 | 515.20 |