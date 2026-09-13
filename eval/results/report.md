# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 410.20 | 374.00 | 418.00 | 428.00 | 1.95 | 410.20 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 603.60 | 583.00 | 611.00 | 617.00 | 1.06 | 603.60 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 303.20 | 225.00 | 272.00 | 320.00 | 1.31 | 303.20 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 635.20 | 570.00 | 603.00 | 632.00 | 1.26 | 635.20 |
| plan-01 | classic | 5 | 0.00 | 0.00 | 549.00 | 549.00 | 549.00 | 549.00 | 2.70 | 0.00 |
| plan-01 | tahoe | 5 | 0.60 | 0.60 | 812.40 | 713.00 | 768.00 | 799.00 | 2.33 | 922.33 |
| recover-01 | classic | 5 | 0.80 | 0.80 | 449.20 | 435.00 | 454.00 | 490.00 | 2.36 | 423.50 |
| recover-01 | tahoe | 5 | 1.00 | 1.00 | 656.20 | 574.00 | 629.00 | 727.00 | 1.45 | 656.20 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 374.60 | 371.00 | 384.00 | 390.00 | 1.41 | 374.60 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 636.20 | 630.00 | 638.00 | 639.00 | 0.96 | 636.20 |
| routing-02 | classic | 5 | 0.20 | 0.20 | 599.00 | 599.00 | 599.00 | 599.00 | 2.79 | 599.00 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 1165.40 | 1082.00 | 1083.00 | 1250.00 | 2.96 | 1165.40 |
| search-01 | classic | 5 | 1.00 | 1.00 | 218.40 | 187.00 | 209.00 | 252.00 | 0.85 | 218.40 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 575.80 | 551.00 | 570.00 | 595.00 | 0.81 | 575.80 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 1.00 |
| code-fix-01 | mean_tokens | 410.20 | 603.60 |
| code-fix-01 | p25_tokens | 374.00 | 583.00 |
| code-fix-01 | p75_tokens | 428.00 | 617.00 |
| code-fix-01 | mean_wall | 1.95 | 1.06 |
| code-fix-01 | mean_quality | 1.00 | 1.00 |
| code-fix-01 | tokens_per_success | 410.20 | 603.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 303.20 | 635.20 |
| code-fix-02 | p25_tokens | 225.00 | 570.00 |
| code-fix-02 | p75_tokens | 320.00 | 632.00 |
| code-fix-02 | mean_wall | 1.31 | 1.26 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 303.20 | 635.20 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 0.00 | 0.60 |
| plan-01 | mean_tokens | 549.00 | 812.40 |
| plan-01 | p25_tokens | 549.00 | 713.00 |
| plan-01 | p75_tokens | 549.00 | 799.00 |
| plan-01 | mean_wall | 2.70 | 2.33 |
| plan-01 | mean_quality | 0.00 | 0.60 |
| plan-01 | tokens_per_success | 0.00 | 922.33 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 0.80 | 1.00 |
| recover-01 | mean_tokens | 449.20 | 656.20 |
| recover-01 | p25_tokens | 435.00 | 574.00 |
| recover-01 | p75_tokens | 490.00 | 727.00 |
| recover-01 | mean_wall | 2.36 | 1.45 |
| recover-01 | mean_quality | 0.80 | 1.00 |
| recover-01 | tokens_per_success | 423.50 | 656.20 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 374.60 | 636.20 |
| routing-01 | p25_tokens | 371.00 | 630.00 |
| routing-01 | p75_tokens | 390.00 | 639.00 |
| routing-01 | mean_wall | 1.41 | 0.96 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 374.60 | 636.20 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.20 | 1.00 |
| routing-02 | mean_tokens | 599.00 | 1165.40 |
| routing-02 | p25_tokens | 599.00 | 1082.00 |
| routing-02 | p75_tokens | 599.00 | 1250.00 |
| routing-02 | mean_wall | 2.79 | 2.96 |
| routing-02 | mean_quality | 0.20 | 1.00 |
| routing-02 | tokens_per_success | 599.00 | 1165.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 218.40 | 575.80 |
| search-01 | p25_tokens | 187.00 | 551.00 |
| search-01 | p75_tokens | 252.00 | 595.00 |
| search-01 | mean_wall | 0.85 | 0.81 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 218.40 | 575.80 |