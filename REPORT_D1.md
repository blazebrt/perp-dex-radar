# Phase D1: pre-registered funding and taker-flow hypotheses on the survivorship-free archive

Pre-registration: `docs/v9/phase-d1-preregistration.md` (sha256 bff1cd1acc5e). 750 coins, 2020-04 to 2026-10. Holm over the four sides in the holdout.

Data: dataset sha256 cd4651ebb5d6 (the same dataset as phase B); taker volume on 3494080 of 3494080 traded bars; 2585286 funding settlements.

| Side | Verdict | Trades | All | Holdout (Holm p) | Design window (p) | Recent third | Cost x1.5 | Twin edge | Top-80 holdout / design | Late 4h/8h/12h/24h | Failing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| XS_FUND_FADE long | NOT_CONFIRMED | 916 | +0.031 | +0.064 (0.303) | -0.020 (0.613) | -0.052 | +0.017 | -0.008 | +0.088 / +0.099 | +0.02 / +0.04 / +0.05 / +0.06 | b_holdout_holm, c_design_window, d_recent_third, f_twin_edge |
| XS_FUND_FADE short | NOT_CONFIRMED | 871 | -0.094 | -0.071 (0.989) | -0.164 (0.998) | -0.151 | -0.104 | -0.001 | -0.037 / -0.196 | -0.09 / -0.08 / -0.08 / -0.09 | b_holdout_holm, c_design_window, d_recent_third, e_cost_stress, f_twin_edge, g_concentration, i_deployable_universe, j_late_entry |
| XS_FLOW_MOM long | NOT_CONFIRMED | 2715 | +0.027 | +0.042 (0.201) | +0.010 (0.336) | +0.020 | +0.013 | +0.081 | +0.048 / +0.004 | +0.02 / +0.02 / +0.02 / +0.01 | b_holdout_holm, c_design_window |
| XS_FLOW_MOM short | NOT_CONFIRMED | 2116 | -0.018 | +0.001 (0.950) | -0.040 (0.978) | -0.024 | -0.029 | +0.018 | -0.007 / -0.031 | -0.02 / -0.02 / -0.03 / -0.03 | b_holdout_holm, c_design_window, d_recent_third, e_cost_stress, g_concentration, i_deployable_universe, j_late_entry |

A CONFIRMED side is a candidate for the probation tier only: it needs a runtime implementation, re-bound evidence, a forward-test registration before its first trade and the owner's merge.
