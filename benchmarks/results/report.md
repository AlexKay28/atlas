# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success | RE | RC | RR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 368.00 | 302.00 | 323.00 | 423.00 | 1.59 | 368.00 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 767.20 | 744.00 | 753.00 | 760.00 | 0.66 | 767.20 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 306.40 | 235.00 | 256.00 | 384.00 | 1.38 | 306.40 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 766.40 | 760.00 | 772.00 | 776.00 | 0.64 | 766.40 | 0.0000 | 0.0000 | 0.0000 |
| plan-01 | classic | 5 | 1.00 | 1.00 | 678.80 | 582.00 | 658.00 | 748.00 | 3.14 | 678.80 | 0.0000 | 0.0000 | 0.0000 |
| plan-01 | tahoe | 5 | 0.00 | 0.00 | 1087.00 | 976.00 | 1165.00 | 1190.00 | 2.51 | 0.00 | 0.0000 | 0.0000 | 0.0000 |
| recover-01 | classic | 5 | 1.00 | 1.00 | 460.20 | 390.00 | 394.00 | 576.00 | 2.26 | 460.20 | 0.0000 | 0.0000 | 0.0000 |
| recover-01 | tahoe | 5 | 1.00 | 1.00 | 827.40 | 784.00 | 842.00 | 853.00 | 0.99 | 827.40 | 0.0000 | 0.0000 | 0.0000 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 340.20 | 324.00 | 348.00 | 352.00 | 1.46 | 340.20 | 0.0000 | 0.0000 | 0.0000 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 861.40 | 822.00 | 838.00 | 882.00 | 0.95 | 861.40 | 0.0000 | 0.0000 | 0.0000 |
| routing-02 | classic | 5 | 0.60 | 0.60 | 1000.00 | 921.00 | 1111.00 | 1111.00 | 4.05 | 926.00 | 0.0000 | 0.0000 | 0.0000 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 1260.40 | 1126.00 | 1241.00 | 1391.00 | 2.46 | 1260.40 | 0.0000 | 0.0000 | 0.0000 |
| search-01 | classic | 5 | 1.00 | 1.00 | 229.20 | 195.00 | 223.00 | 264.00 | 0.83 | 229.20 | 0.0000 | 0.0000 | 0.0000 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 814.00 | 814.00 | 825.00 | 835.00 | 0.78 | 814.00 | 0.0000 | 0.0000 | 0.0000 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 1.00 |
| code-fix-01 | mean_tokens | 368.00 | 767.20 |
| code-fix-01 | p25_tokens | 302.00 | 744.00 |
| code-fix-01 | p75_tokens | 423.00 | 760.00 |
| code-fix-01 | mean_wall | 1.59 | 0.66 |
| code-fix-01 | mean_quality | 1.00 | 1.00 |
| code-fix-01 | tokens_per_success | 368.00 | 767.20 |
| code-fix-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| code-fix-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| code-fix-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 306.40 | 766.40 |
| code-fix-02 | p25_tokens | 235.00 | 760.00 |
| code-fix-02 | p75_tokens | 384.00 | 776.00 |
| code-fix-02 | mean_wall | 1.38 | 0.64 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 306.40 | 766.40 |
| code-fix-02 | re_reasoning_efficiency | 0.00 | 0.00 |
| code-fix-02 | rc_reasoning_concentration | 0.00 | 0.00 |
| code-fix-02 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 1.00 | 0.00 |
| plan-01 | mean_tokens | 678.80 | 1087.00 |
| plan-01 | p25_tokens | 582.00 | 976.00 |
| plan-01 | p75_tokens | 748.00 | 1190.00 |
| plan-01 | mean_wall | 3.14 | 2.51 |
| plan-01 | mean_quality | 1.00 | 0.00 |
| plan-01 | tokens_per_success | 678.80 | 0.00 |
| plan-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| plan-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| plan-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 1.00 | 1.00 |
| recover-01 | mean_tokens | 460.20 | 827.40 |
| recover-01 | p25_tokens | 390.00 | 784.00 |
| recover-01 | p75_tokens | 576.00 | 853.00 |
| recover-01 | mean_wall | 2.26 | 0.99 |
| recover-01 | mean_quality | 1.00 | 1.00 |
| recover-01 | tokens_per_success | 460.20 | 827.40 |
| recover-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| recover-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| recover-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 340.20 | 861.40 |
| routing-01 | p25_tokens | 324.00 | 822.00 |
| routing-01 | p75_tokens | 352.00 | 882.00 |
| routing-01 | mean_wall | 1.46 | 0.95 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 340.20 | 861.40 |
| routing-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| routing-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| routing-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 0.60 | 1.00 |
| routing-02 | mean_tokens | 1000.00 | 1260.40 |
| routing-02 | p25_tokens | 921.00 | 1126.00 |
| routing-02 | p75_tokens | 1111.00 | 1391.00 |
| routing-02 | mean_wall | 4.05 | 2.46 |
| routing-02 | mean_quality | 0.60 | 1.00 |
| routing-02 | tokens_per_success | 926.00 | 1260.40 |
| routing-02 | re_reasoning_efficiency | 0.00 | 0.00 |
| routing-02 | rc_reasoning_concentration | 0.00 | 0.00 |
| routing-02 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 229.20 | 814.00 |
| search-01 | p25_tokens | 195.00 | 814.00 |
| search-01 | p75_tokens | 264.00 | 835.00 |
| search-01 | mean_wall | 0.83 | 0.78 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 229.20 | 814.00 |
| search-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| search-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| search-01 | rr_redundancy_rate | 0.00 | 0.00 |