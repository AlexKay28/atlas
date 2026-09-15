# Ablation results — GLM-5.3-Flash

| task_id | arm | trials | pass_rate | mean_quality | mean_tokens | p25 | p50 | p75 | mean_wall | tokens/success | RE | RC | RR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| code-fix-01 | classic | 5 | 1.00 | 1.00 | 385.00 | 323.00 | 390.00 | 405.00 | 1.75 | 385.00 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-01 | tahoe | 5 | 1.00 | 1.00 | 328.20 | 330.00 | 331.00 | 331.00 | 0.57 | 328.20 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-02 | classic | 5 | 1.00 | 1.00 | 348.20 | 281.00 | 302.00 | 374.00 | 1.55 | 348.20 | 0.0000 | 0.0000 | 0.0000 |
| code-fix-02 | tahoe | 5 | 1.00 | 1.00 | 314.60 | 294.00 | 305.00 | 321.00 | 0.45 | 314.60 | 0.0000 | 0.0000 | 0.0000 |
| plan-01 | classic | 5 | 1.00 | 1.00 | 699.80 | 642.00 | 681.00 | 778.00 | 3.45 | 699.80 | 0.0000 | 0.0000 | 0.0000 |
| plan-01 | tahoe | 5 | 0.00 | 0.00 | 491.20 | 450.00 | 495.00 | 515.00 | 1.38 | 0.00 | 0.0000 | 0.0000 | 0.0000 |
| recover-01 | classic | 5 | 1.00 | 1.00 | 468.80 | 437.00 | 468.00 | 481.00 | 2.28 | 468.80 | 0.0000 | 0.0000 | 0.0000 |
| recover-01 | tahoe | 5 | 1.00 | 1.00 | 385.00 | 369.00 | 370.00 | 411.00 | 0.85 | 385.00 | 0.0000 | 0.0000 | 0.0000 |
| routing-01 | classic | 5 | 1.00 | 1.00 | 360.80 | 337.00 | 339.00 | 376.00 | 1.20 | 360.80 | 0.0000 | 0.0000 | 0.0000 |
| routing-01 | tahoe | 5 | 1.00 | 1.00 | 368.20 | 348.00 | 376.00 | 376.00 | 0.52 | 368.20 | 0.0000 | 0.0000 | 0.0000 |
| routing-02 | classic | 5 | 1.00 | 1.00 | 825.80 | 694.00 | 781.00 | 861.00 | 3.44 | 825.80 | 0.0000 | 0.0000 | 0.0000 |
| routing-02 | tahoe | 5 | 1.00 | 1.00 | 485.60 | 445.00 | 490.00 | 536.00 | 0.95 | 485.60 | 0.0000 | 0.0000 | 0.0000 |
| search-01 | classic | 5 | 1.00 | 1.00 | 208.00 | 187.00 | 189.00 | 228.00 | 0.77 | 208.00 | 0.0000 | 0.0000 | 0.0000 |
| search-01 | tahoe | 5 | 1.00 | 1.00 | 311.60 | 304.00 | 313.00 | 316.00 | 0.41 | 311.60 | 0.0000 | 0.0000 | 0.0000 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-01 | pass_rate | 1.00 | 1.00 |
| code-fix-01 | mean_tokens | 385.00 | 328.20 |
| code-fix-01 | p25_tokens | 323.00 | 330.00 |
| code-fix-01 | p75_tokens | 405.00 | 331.00 |
| code-fix-01 | mean_wall | 1.75 | 0.57 |
| code-fix-01 | mean_quality | 1.00 | 1.00 |
| code-fix-01 | tokens_per_success | 385.00 | 328.20 |
| code-fix-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| code-fix-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| code-fix-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| code-fix-02 | pass_rate | 1.00 | 1.00 |
| code-fix-02 | mean_tokens | 348.20 | 314.60 |
| code-fix-02 | p25_tokens | 281.00 | 294.00 |
| code-fix-02 | p75_tokens | 374.00 | 321.00 |
| code-fix-02 | mean_wall | 1.55 | 0.45 |
| code-fix-02 | mean_quality | 1.00 | 1.00 |
| code-fix-02 | tokens_per_success | 348.20 | 314.60 |
| code-fix-02 | re_reasoning_efficiency | 0.00 | 0.00 |
| code-fix-02 | rc_reasoning_concentration | 0.00 | 0.00 |
| code-fix-02 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| plan-01 | pass_rate | 1.00 | 0.00 |
| plan-01 | mean_tokens | 699.80 | 491.20 |
| plan-01 | p25_tokens | 642.00 | 450.00 |
| plan-01 | p75_tokens | 778.00 | 515.00 |
| plan-01 | mean_wall | 3.45 | 1.38 |
| plan-01 | mean_quality | 1.00 | 0.00 |
| plan-01 | tokens_per_success | 699.80 | 0.00 |
| plan-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| plan-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| plan-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| recover-01 | pass_rate | 1.00 | 1.00 |
| recover-01 | mean_tokens | 468.80 | 385.00 |
| recover-01 | p25_tokens | 437.00 | 369.00 |
| recover-01 | p75_tokens | 481.00 | 411.00 |
| recover-01 | mean_wall | 2.28 | 0.85 |
| recover-01 | mean_quality | 1.00 | 1.00 |
| recover-01 | tokens_per_success | 468.80 | 385.00 |
| recover-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| recover-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| recover-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-01 | pass_rate | 1.00 | 1.00 |
| routing-01 | mean_tokens | 360.80 | 368.20 |
| routing-01 | p25_tokens | 337.00 | 348.00 |
| routing-01 | p75_tokens | 376.00 | 376.00 |
| routing-01 | mean_wall | 1.20 | 0.52 |
| routing-01 | mean_quality | 1.00 | 1.00 |
| routing-01 | tokens_per_success | 360.80 | 368.20 |
| routing-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| routing-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| routing-01 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| routing-02 | pass_rate | 1.00 | 1.00 |
| routing-02 | mean_tokens | 825.80 | 485.60 |
| routing-02 | p25_tokens | 694.00 | 445.00 |
| routing-02 | p75_tokens | 861.00 | 536.00 |
| routing-02 | mean_wall | 3.44 | 0.95 |
| routing-02 | mean_quality | 1.00 | 1.00 |
| routing-02 | tokens_per_success | 825.80 | 485.60 |
| routing-02 | re_reasoning_efficiency | 0.00 | 0.00 |
| routing-02 | rc_reasoning_concentration | 0.00 | 0.00 |
| routing-02 | rr_redundancy_rate | 0.00 | 0.00 |

| task_id | metric | classic | tahoe |
|---|---|---|---|
| search-01 | pass_rate | 1.00 | 1.00 |
| search-01 | mean_tokens | 208.00 | 311.60 |
| search-01 | p25_tokens | 187.00 | 304.00 |
| search-01 | p75_tokens | 228.00 | 316.00 |
| search-01 | mean_wall | 0.77 | 0.41 |
| search-01 | mean_quality | 1.00 | 1.00 |
| search-01 | tokens_per_success | 208.00 | 311.60 |
| search-01 | re_reasoning_efficiency | 0.00 | 0.00 |
| search-01 | rc_reasoning_concentration | 0.00 | 0.00 |
| search-01 | rr_redundancy_rate | 0.00 | 0.00 |