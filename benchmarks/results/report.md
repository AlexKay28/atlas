# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success |
|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 477.20 | 408.00 | 495.00 | 540.00 | 2.53 | 477.20 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 623.40 | 616.00 | 618.00 | 627.00 | 0.50 | 623.40 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 279.40 | 233.00 | 252.00 | 264.00 | 1.33 | 279.40 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 659.40 | 648.00 | 654.00 | 663.00 | 0.59 | 659.40 |
| plan-01 | classic | 5 | 1.00 | 1.00 | 727.20 | 685.00 | 742.00 | 846.00 | 3.66 | 727.20 |
| plan-01 | tahoe | 5 | 0.40 | 0.40 | 849.40 | 719.00 | 833.00 | 961.00 | 2.37 | 897.00 |
| recover-01 | classic | 5 | 1.00 | 1.00 | 390.00 | 350.00 | 401.00 | 449.00 | 2.35 | 390.00 |
| recover-01 | tahoe | 5 | 1.00 | 1.00 | 751.00 | 731.00 | 756.00 | 783.00 | 1.36 | 751.00 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 365.80 | 353.00 | 356.00 | 398.00 | 1.61 | 365.80 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 701.60 | 694.00 | 701.00 | 710.00 | 0.95 | 701.60 |
| routing-02 | classic | 5 | 1.00 | 1.00 | 921.40 | 762.00 | 890.00 | 1110.00 | 4.35 | 921.40 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 1175.40 | 979.00 | 1054.00 | 1295.00 | 3.21 | 1175.40 |
| search-01 | classic | 5 | 1.00 | 1.00 | 215.00 | 198.00 | 215.00 | 228.00 | 1.24 | 215.00 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 663.00 | 659.00 | 663.00 | 681.00 | 0.67 | 663.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 1.00 |
| code-fix-01 | mean_tokens | 477.20 | 623.40 |
| code-fix-01 | p25_tokens | 408.00 | 616.00 |
| code-fix-01 | p75_tokens | 540.00 | 627.00 |
| code-fix-01 | mean_wall | 2.53 | 0.50 |
| code-fix-01 | mean_quality | 1.00 | 1.00 |
| code-fix-01 | tokens_per_success | 477.20 | 623.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 279.40 | 659.40 |
| code-fix-02 | p25_tokens | 233.00 | 648.00 |
| code-fix-02 | p75_tokens | 264.00 | 663.00 |
| code-fix-02 | mean_wall | 1.33 | 0.59 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 279.40 | 659.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 1.00 | 0.40 |
| plan-01 | mean_tokens | 727.20 | 849.40 |
| plan-01 | p25_tokens | 685.00 | 719.00 |
| plan-01 | p75_tokens | 846.00 | 961.00 |
| plan-01 | mean_wall | 3.66 | 2.37 |
| plan-01 | mean_quality | 1.00 | 0.40 |
| plan-01 | tokens_per_success | 727.20 | 897.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 1.00 | 1.00 |
| recover-01 | mean_tokens | 390.00 | 751.00 |
| recover-01 | p25_tokens | 350.00 | 731.00 |
| recover-01 | p75_tokens | 449.00 | 783.00 |
| recover-01 | mean_wall | 2.35 | 1.36 |
| recover-01 | mean_quality | 1.00 | 1.00 |
| recover-01 | tokens_per_success | 390.00 | 751.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 365.80 | 701.60 |
| routing-01 | p25_tokens | 353.00 | 694.00 |
| routing-01 | p75_tokens | 398.00 | 710.00 |
| routing-01 | mean_wall | 1.61 | 0.95 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 365.80 | 701.60 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 1.00 | 1.00 |
| routing-02 | mean_tokens | 921.40 | 1175.40 |
| routing-02 | p25_tokens | 762.00 | 979.00 |
| routing-02 | p75_tokens | 1110.00 | 1295.00 |
| routing-02 | mean_wall | 4.35 | 3.21 |
| routing-02 | mean_quality | 1.00 | 1.00 |
| routing-02 | tokens_per_success | 921.40 | 1175.40 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 215.00 | 663.00 |
| search-01 | p25_tokens | 198.00 | 659.00 |
| search-01 | p75_tokens | 228.00 | 681.00 |
| search-01 | mean_wall | 1.24 | 0.67 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 215.00 | 663.00 |