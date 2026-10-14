# Survivorship-free evidence (v9.archive-evidence/2)

Data: data.binance.vision (Binance USD-M futures public archive); 750 coins in the research panel (170 delisted), 4h bars 2020-01-01 to 2026-09-30. Costs: taker 0.045% + slippage 0.10% each way, observed funding. R = net result in units of the stop distance.

Pre-design = before Oct 2023 (the legacy strategies were designed on Oct 2023 to Oct 2026 data, on coins that survived): out of sample in time. Twin edge = trade minus the same order on a random eligible coin.

| Strategy | TF | Trades | Mean R | 95% low | Pre-design | Design window | OOS (last third) | Long | Short | Delisted coins | Twin edge | x1.5 cost | Legacy claim (3y) | Measured gate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TSMOM | 1d | 6792 | +0.059 | +0.009 | +0.092 | +0.040 | -0.002 | +0.047 | +0.076 | +0.041 | +0.041 | +0.042 | +0.056 | fails: by_q, dsr_probability, oos_mean_R, pbo |
| TREND_EMA | 4h | 18832 | +0.004 | -0.055 | -0.012 | +0.012 | -0.003 | -0.052 | +0.066 | -0.004 | +0.015 | -0.022 | +0.095 | fails: by_q, dsr_probability, matched_lower_95, mean_R_lower_95 |
| XSMOM | 1d | 1817 | +0.099 | +0.030 | +0.116 | +0.076 | +0.102 | +0.197 | -0.009 | -0.110 | +0.092 | +0.080 | +0.136 | fails: by_q, dsr_probability, pbo, spa_p |
| XSMOM_7D | 1d | 3794 | +0.007 | -0.018 | +0.013 | -0.002 | +0.001 | +0.029 | -0.021 | -0.013 | +0.039 | -0.006 | +0.001 | fails: by_q, dsr_probability, mean_R_lower_95, pbo |
| XSMOM_14D_7 | 1d | 2223 | +0.015 | -0.023 | +0.054 | -0.039 | -0.052 | +0.068 | -0.041 | -0.086 | +0.040 | +0.000 | +0.047 | fails: by_q, dsr_probability, matched_lower_95, mean_R_lower_95 |
| TREND_DC55 | 4h | 41259 | -0.059 | -0.120 | -0.076 | -0.051 | -0.053 | -0.133 | +0.033 | -0.089 | -0.017 | -0.091 | +0.021 | fails: by_q, dsr_probability, leave_one_asset_out_min_mean_R, matched_edge |
| TREND_DC20 | 4h | 64682 | -0.026 | -0.081 | -0.029 | -0.024 | -0.017 | -0.100 | +0.058 | -0.043 | +0.004 | -0.057 | +0.039 | fails: by_q, dsr_probability, leave_one_asset_out_min_mean_R, matched_lower_95 |
| DC20_D | 1d | 9315 | -0.014 | -0.096 | +0.100 | -0.064 | -0.083 | -0.047 | +0.061 | -0.025 | -0.020 | -0.039 | +0.008 | fails: by_q, dsr_probability, leave_one_asset_out_min_mean_R, matched_edge |
| DC55_D | 1d | 5085 | -0.032 | -0.124 | +0.010 | -0.051 | +0.007 | -0.069 | +0.059 | -0.076 | +0.029 | -0.058 | -0.032 | fails: by_q, dsr_probability, leave_one_asset_out_min_mean_R, matched_lower_95 |
| EMA5_20_D | 1d | 8665 | +0.028 | -0.052 | +0.123 | -0.016 | -0.068 | -0.007 | +0.095 | +0.025 | +0.019 | +0.007 | +0.063 | fails: by_q, dsr_probability, matched_lower_95, mean_R_lower_95 |
| EMA10_50_D | 1d | 5338 | +0.053 | -0.030 | +0.205 | -0.014 | -0.088 | -0.029 | +0.228 | +0.072 | +0.039 | +0.030 | +0.065 | fails: by_q, dsr_probability, matched_lower_95, mean_R_lower_95 |
| TSMOM_FAST | 1d | 14981 | +0.002 | -0.040 | +0.054 | -0.024 | -0.062 | -0.010 | +0.020 | +0.006 | +0.025 | -0.015 | +0.001 | fails: by_q, dsr_probability, mean_R_lower_95, oos_mean_R |
| TSMOM_SLOW | 1d | 4237 | +0.115 | +0.033 | +0.051 | +0.149 | +0.087 | +0.188 | +0.044 | +0.179 | +0.104 | +0.091 | +0.027 | fails: by_q, dsr_probability, pbo, spa_p |
| SQZ_4H | 4h | 17426 | +0.007 | -0.076 | -0.063 | +0.051 | +0.041 | -0.086 | +0.114 | -0.078 | +0.018 | -0.027 | +0.084 | fails: by_q, dsr_probability, matched_lower_95, mean_R_lower_95 |
| SQZ_D | 1d | 3532 | +0.029 | -0.100 | -0.002 | +0.047 | -0.071 | -0.042 | +0.239 | -0.023 | +0.044 | +0.004 | +0.136 | fails: by_q, dsr_probability, matched_lower_95, mean_R_lower_95 |
| RS_BRK | 4h | 13352 | -0.074 | -0.137 | -0.063 | -0.079 | -0.078 | -0.099 | -0.036 | -0.083 | -0.028 | -0.102 | -0.029 | fails: by_q, dsr_probability, leave_one_asset_out_min_mean_R, matched_edge |
| XSREV_1D | 1d | 4730 | -0.020 | -0.033 | -0.027 | -0.006 | +0.034 | -0.031 | -0.014 | +0.004 | -0.002 | -0.032 | -0.016 | fails: by_q, dsr_probability, leave_one_asset_out_min_mean_R, matched_edge |

Family tests over 17 candidates, 2345 days: White RC p 0.7584483103379324, Hansen SPA p 0.14997000599880023, PBO 0.2815850815850816; DSR uses 199 trials (the census lower bound).

## Year by year (candidates whose 95% lower bound is above zero)

| Strategy | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| TSMOM | +0.137 (208) | +0.241 (99) | -0.007 (694) | +0.111 (2118) | +0.083 (1434) | -0.033 (1098) | +0.031 (1141) |
| XSMOM | +0.175 (218) | +0.572 (88) | -0.002 (292) | +0.039 (577) | +0.157 (283) | +0.058 (165) | +0.075 (194) |
| TSMOM_SLOW | +0.269 (123) | -0.139 (65) | -0.005 (398) | +0.074 (1232) | +0.380 (944) | -0.003 (747) | +0.022 (728) |

## Coin-picks swing score on the survivorship-free universe

720 coins, round-trip cost 0.29% plus funding while held.

| Side | Band | Coin-days | Mean R | 95% low | Pre-design | Design window |
|---|---|---|---|---|---|---|
| long | 0-60 | 319905 | -0.104 | -0.138 | -0.023 | -0.147 |
| long | 60-70 | 33875 | -0.006 | -0.057 | -0.089 | +0.042 |
| long | 70-80 | 17749 | +0.062 | -0.010 | -0.153 | +0.180 |
| long | 80-90 | 8196 | +0.143 | +0.056 | -0.182 | +0.311 |
| long | 90-101 | 2697 | +0.263 | +0.133 | -0.123 | +0.455 |
| long | 80+ one at a time | 2094 trades | +0.144 | +0.020 | -0.128 | +0.303 |
| short | 0-60 | 237198 | +0.001 | -0.035 | +0.018 | -0.009 |
| short | 60-70 | 47375 | +0.071 | +0.024 | +0.059 | +0.077 |
| short | 70-80 | 74318 | +0.074 | +0.034 | -0.025 | +0.120 |
| short | 80-90 | 21623 | +0.089 | +0.022 | +0.022 | +0.123 |
| short | 90-101 | 2570 | +0.118 | +0.008 | -0.014 | +0.190 |
| short | 80+ one at a time | 6928 trades | +0.123 | +0.048 | +0.069 | +0.148 |

Long 80+ one at a time, by year: 2020 +1.203 (45), 2021 -0.186 (25), 2022 -0.176 (233), 2023 +0.133 (674), 2024 +0.449 (399), 2025 -0.090 (356), 2026 +0.158 (362).
Short 80+ one at a time, by year: 2020 -0.329 (113), 2021 +0.059 (603), 2022 +0.225 (772), 2023 -0.117 (781), 2024 +0.102 (1625), 2025 +0.274 (2173), 2026 +0.016 (861).

## Runtime strategies: deployable-universe proxy (top 80 by volume) and late entries

Pre-registered before these were seen. Late entry = the same signal entered N hours after the open the backtest assumes (the desk shows a daily signal for up to a day).

| Strategy | Variant | Side | Trades | All | 95% low | Holdout | Design window | Recent third |
|---|---|---|---|---|---|---|---|---|
| TSMOM | top80 | long | 1761 | +0.095 | +0.019 | +0.040 | +0.136 | +0.060 |
| TSMOM | top80 | short | 1163 | +0.040 | -0.034 | +0.123 | -0.058 | -0.025 |
| TSMOM | delay1 | long | 4013 | +0.045 | -0.030 | +0.001 | +0.062 | -0.006 |
| TSMOM | delay1 | short | 2824 | +0.085 | +0.016 | +0.178 | +0.002 | +0.029 |
| TSMOM | delay2 | long | 4044 | +0.040 | -0.037 | -0.018 | +0.062 | -0.012 |
| TSMOM | delay2 | short | 2845 | +0.086 | +0.016 | +0.182 | +0.001 | +0.030 |
| TSMOM | delay3 | long | 4060 | +0.042 | -0.034 | +0.018 | +0.051 | -0.006 |
| TSMOM | delay3 | short | 2843 | +0.089 | +0.021 | +0.191 | -0.001 | +0.029 |
| TSMOM | delay6 | long | 4364 | +0.048 | -0.027 | +0.011 | +0.062 | -0.013 |
| TSMOM | delay6 | short | 2902 | +0.072 | +0.005 | +0.181 | -0.025 | +0.003 |
| TREND_EMA | top80 | long | 3983 | -0.045 | -0.122 | -0.118 | +0.035 | +0.027 |
| TREND_EMA | top80 | short | 3629 | +0.063 | -0.017 | +0.104 | +0.021 | -0.036 |
| TREND_EMA | delay1 | long | 9863 | -0.058 | -0.130 | -0.105 | -0.034 | -0.022 |
| TREND_EMA | delay1 | short | 8801 | +0.061 | -0.032 | +0.103 | +0.041 | -0.003 |
| TREND_EMA | delay2 | long | 9753 | -0.057 | -0.130 | -0.095 | -0.037 | -0.025 |
| TREND_EMA | delay2 | short | 8696 | +0.063 | -0.026 | +0.097 | +0.048 | +0.008 |
| TREND_EMA | delay3 | long | 9682 | -0.058 | -0.130 | -0.073 | -0.051 | -0.043 |
| TREND_EMA | delay3 | short | 8603 | +0.068 | -0.021 | +0.087 | +0.058 | +0.018 |
| TREND_EMA | delay6 | long | 9522 | -0.060 | -0.132 | -0.056 | -0.063 | -0.059 |
| TREND_EMA | delay6 | short | 8375 | +0.074 | -0.025 | +0.029 | +0.095 | +0.048 |
| XSMOM | top80 | long | 837 | +0.200 | +0.082 | +0.193 | +0.211 | +0.186 |
| XSMOM | top80 | short | 860 | +0.037 | -0.032 | +0.070 | -0.007 | +0.042 |
| XSMOM | delay1 | long | 954 | +0.203 | +0.075 | +0.158 | +0.254 | +0.270 |
| XSMOM | delay1 | short | 869 | -0.019 | -0.085 | +0.060 | -0.147 | -0.101 |
| XSMOM | delay2 | long | 964 | +0.189 | +0.060 | +0.131 | +0.255 | +0.282 |
| XSMOM | delay2 | short | 873 | -0.008 | -0.075 | +0.068 | -0.132 | -0.086 |
| XSMOM | delay3 | long | 964 | +0.197 | +0.065 | +0.174 | +0.224 | +0.248 |
| XSMOM | delay3 | short | 874 | -0.013 | -0.081 | +0.057 | -0.127 | -0.080 |
| XSMOM | delay6 | long | 984 | +0.184 | +0.054 | +0.154 | +0.217 | +0.243 |
| XSMOM | delay6 | short | 884 | +0.001 | -0.065 | +0.066 | -0.102 | -0.032 |

