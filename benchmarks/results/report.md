# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success | RE | RC | RR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 550.20 | 510.00 | 519.00 | 576.00 | 2.42 | 550.20 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 786.40 | 777.00 | 786.00 | 793.00 | 0.43 | 786.40 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 287.60 | 229.00 | 247.00 | 346.00 | 1.29 | 287.60 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 831.20 | 824.00 | 829.00 | 832.00 | 0.60 | 831.20 | 0.0000 | 0.0000 | 0.0000 |
| plan-01 | classic | 5 | 1.00 | 1.00 | 622.20 | 589.00 | 634.00 | 674.00 | 3.21 | 622.20 | 0.0000 | 0.0000 | 0.0000 |
| plan-01 | tahoe | 5 | 1.00 | 1.00 | 1160.80 | 1156.00 | 1183.00 | 1197.00 | 2.44 | 1160.80 | 0.0000 | 0.0000 | 0.0000 |
| recover-01 | classic | 5 | 1.00 | 1.00 | 498.60 | 414.00 | 531.00 | 543.00 | 2.43 | 498.60 | 0.0000 | 0.0000 | 0.0000 |
| recover-01 | tahoe | 5 | 1.00 | 1.00 | 881.80 | 871.00 | 877.00 | 878.00 | 0.95 | 881.80 | 0.0000 | 0.0000 | 0.0000 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 341.80 | 318.00 | 353.00 | 360.00 | 1.17 | 341.80 | 0.0000 | 0.0000 | 0.0000 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 930.60 | 917.00 | 942.00 | 945.00 | 0.97 | 930.60 | 0.0000 | 0.0000 | 0.0000 |
| routing-02 | classic | 5 | 0.60 | 0.60 | 1038.80 | 1111.00 | 1111.00 | 1111.00 | 4.77 | 990.67 | 0.0000 | 0.0000 | 0.0000 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 1573.00 | 1587.00 | 1621.00 | 1633.00 | 3.67 | 1573.00 | 0.0000 | 0.0000 | 0.0000 |
| search-01 | classic | 5 | 1.00 | 1.00 | 197.40 | 188.00 | 195.00 | 198.00 | 0.73 | 197.40 | 0.0000 | 0.0000 | 0.0000 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 876.20 | 839.00 | 844.00 | 859.00 | 0.79 | 876.20 | 0.0000 | 0.0000 | 0.0000 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 1.00 |
| code-fix-01 | mean_tokens | 550.20 | 786.40 |
| code-fix-01 | p25_tokens | 510.00 | 777.00 |
| code-fix-01 | p75_tokens | 576.00 | 793.00 |
| code-fix-01 | mean_wall | 2.42 | 0.43 |
| code-fix-01 | mean_quality | 1.00 | 1.00 |
| code-fix-01 | tokens_per_success | 550.20 | 786.40 |
| code-fix-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| code-fix-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| code-fix-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 287.60 | 831.20 |
| code-fix-02 | p25_tokens | 229.00 | 824.00 |
| code-fix-02 | p75_tokens | 346.00 | 832.00 |
| code-fix-02 | mean_wall | 1.29 | 0.60 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 287.60 | 831.20 |
| code-fix-02 | re_reasoning_efficiency | 0.00 | 0.00 |
| code-fix-02 | rc_reasoning_concentration | 0.00 | 0.00 |
| code-fix-02 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 1.00 | 1.00 |
| plan-01 | mean_tokens | 622.20 | 1160.80 |
| plan-01 | p25_tokens | 589.00 | 1156.00 |
| plan-01 | p75_tokens | 674.00 | 1197.00 |
| plan-01 | mean_wall | 3.21 | 2.44 |
| plan-01 | mean_quality | 1.00 | 1.00 |
| plan-01 | tokens_per_success | 622.20 | 1160.80 |
| plan-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| plan-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| plan-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 1.00 | 1.00 |
| recover-01 | mean_tokens | 498.60 | 881.80 |
| recover-01 | p25_tokens | 414.00 | 871.00 |
| recover-01 | p75_tokens | 543.00 | 878.00 |
| recover-01 | mean_wall | 2.43 | 0.95 |
| recover-01 | mean_quality | 1.00 | 1.00 |
| recover-01 | tokens_per_success | 498.60 | 881.80 |
| recover-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| recover-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| recover-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 341.80 | 930.60 |
| routing-01 | p25_tokens | 318.00 | 917.00 |
| routing-01 | p75_tokens | 360.00 | 945.00 |
| routing-01 | mean_wall | 1.17 | 0.97 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 341.80 | 930.60 |
| routing-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| routing-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| routing-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.60 | 1.00 |
| routing-02 | mean_tokens | 1038.80 | 1573.00 |
| routing-02 | p25_tokens | 1111.00 | 1587.00 |
| routing-02 | p75_tokens | 1111.00 | 1633.00 |
| routing-02 | mean_wall | 4.77 | 3.67 |
| routing-02 | mean_quality | 0.60 | 1.00 |
| routing-02 | tokens_per_success | 990.67 | 1573.00 |
| routing-02 | re_reasoning_efficiency | 0.00 | 0.00 |
| routing-02 | rc_reasoning_concentration | 0.00 | 0.00 |
| routing-02 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 197.40 | 876.20 |
| search-01 | p25_tokens | 188.00 | 839.00 |
| search-01 | p75_tokens | 198.00 | 859.00 |
| search-01 | mean_wall | 0.73 | 0.79 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 197.40 | 876.20 |
| search-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| search-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| search-01 | rr_redundancy_rate | 0.00 | 0.00 |