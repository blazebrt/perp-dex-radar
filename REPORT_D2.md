# Phase D2: pre-registered positioning hypotheses (Binance metrics) on the survivorship-free archive

Pre-registration: `docs/v9/phase-d2-preregistration.md` (sha256 a60699b3e7a1). 750 coins, 2020-04 to 2026-10. Holm over the four sides in the holdout. Signals use the metrics through the previous UTC day (6 bars of lag).

Data: dataset sha256 cd4651ebb5d6 (the same candles and funding as phase B); metrics for 748 coins (sha256 d753e910b704, 532738 daily files).

- XS_TOP_DIV: a signal value on 333710 of 421615 eligible coin-days (79%), from 2020-09-04.
- XS_CROWD_FADE: a signal value on 374654 of 421615 eligible coin-days (89%), from 2020-09-04.

| Side | Verdict | Trades | All | Holdout (Holm p) | Design window (p) | Recent third | Cost x1.5 | Twin edge | Top-80 holdout / design | Late 4h/8h/12h/24h | Failing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| XS_TOP_DIV long | NOT_CONFIRMED | 1069 | -0.006 | +0.025 (0.490) | -0.032 (0.857) | +0.010 | -0.019 | -0.018 | +0.044 / -0.006 | -0.00 / +0.00 / -0.01 / -0.01 | b_holdout_holm, c_design_window, e_cost_stress, f_twin_edge, g_concentration, i_deployable_universe, j_late_entry |
| XS_TOP_DIV short | NOT_CONFIRMED | 1282 | -0.069 | -0.021 (0.877) | -0.093 (1.000) | -0.061 | -0.082 | -0.038 | -0.009 / -0.062 | -0.07 / -0.07 / -0.07 / -0.07 | b_holdout_holm, c_design_window, d_recent_third, e_cost_stress, f_twin_edge, g_concentration, i_deployable_universe, j_late_entry |
| XS_CROWD_FADE long | NOT_CONFIRMED | 1050 | +0.023 | +0.041 (0.155) | -0.005 (0.569) | -0.008 | +0.010 | -0.009 | +0.026 / -0.015 | +0.03 / +0.03 / +0.02 / +0.00 | b_holdout_holm, c_design_window, d_recent_third, f_twin_edge, i_deployable_universe |
| XS_CROWD_FADE short | NOT_CONFIRMED | 1373 | -0.008 | +0.004 (0.877) | -0.019 (0.791) | +0.036 | -0.019 | -0.001 | +0.020 / -0.036 | -0.00 / +0.00 / -0.00 / -0.01 | b_holdout_holm, c_design_window, e_cost_stress, f_twin_edge, g_concentration, i_deployable_universe, j_late_entry |

A CONFIRMED side is a candidate for the probation tier only: it needs a runtime implementation (reading the daily metrics files with the same one-day lag), re-bound evidence, a forward-test registration before its first trade and the owner's merge.
