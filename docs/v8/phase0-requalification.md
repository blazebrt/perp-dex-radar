# Phase 0 requalification - NON-AUTHORITATIVE — IMPLEMENTATION RECOMMENDATION ONLY

> **NON-AUTHORITATIVE — IMPLEMENTATION RECOMMENDATION ONLY.**
> Nothing in the code reads this file. No engine, page, threshold or status depends on it, and Phase 1 did not
> create any runtime governance file. These are notes for a later, separately authorised phase. Where this note
> and the Phase 0 report accepted by the owner differ, the Phase 0 report governs. Not financial advice.

## Purpose

Phase 0 asked which parts of the current product have earned the right to be shown as actionable. v8's governance
vocabulary is PROVEN / ACTIVE / DEGRADED / PROBATION / PAPER ONLY / REJECTED. Below is the recommended starting
status for each signal source, with the evidence already in this repository. A status would only take effect in a
later phase that implements governance, with its own tests and the owner's approval.

## Recommended starting statuses

| Signal source | Evidence in the repository | Recommended status | Why not higher |
|---|---|---|---|
| Quant XSMOM (cross-sectional momentum, daily) | `quant_research.json`: 3 years 909 trades, +0.14R per trade, PF 1.35, t 2.6; positive in both halves of the last year | ACTIVE (candidate) | one parameter set, backtest only, no live record yet |
| Quant TREND_EMA (4h EMA cross) | 3 years 2,424 trades, +0.09R, PF 1.20, t 1.75 | PROBATION | t below 2 over three years |
| Quant TSMOM (daily trend) | 3 years 1,181 trades, +0.06R, PF 1.16, t 1.32 | PROBATION | weak statistical support |
| Quant variants marked rejected in the research file (XSMOM_7D, XSMOM_14D_7, TREND_DC20/55, DC20_D, DC55_D, EMA5_20_D, EMA10_50_D, TSMOM_FAST/SLOW, SQZ_4H, SQZ_D, RS_BRK, XSREV_1D, LIQ_FLUSH) | the research file's own verdicts | REJECTED | no edge after costs or not stable |
| Radar 15-minute strategies | published only once their live journal status is "passed"; a new journal starts with all of them in test | PAPER ONLY until each beats its random twins in the live journal | the live record decides; backtests of 2-30 days are too short |
| Coin picks, swing, Ready/Strong (80+) | `picks_research.json` (Oct 2023 - Oct 2026, after fees): longs 80-89 about +2.8% per trade, 90+ about +4.4%; shorts 80-89 about +2.5%, 90+ about +5.1% | PROBATION | backtest only; the live paper record is small |
| Coin picks, swing, below 80 | same file: longs below 60 lose on average (-2.2% to -4.1% per trade), 60-79 mixed; shorts positive on average | information only | no clear tested edge for longs |
| Coin picks, day trade (all scores) | same file: every score band of longs and of shorts has a negative average result (longs: all -0.13R, 90+ -0.05R per trade; shorts: all -0.05R, 90+ -0.10R) | REJECTED as a signal; information only | no edge in the repository's own test |
| Smart money, short crowds (2+ proven traders shorting within 24h) | `smart_research.json`: 31 trades on 11 coins over 18 days, 61% winners, +2.3% vs the market, first half negative | PAPER ONLY | too few trades; halves not both positive |
| Smart money, long crowds | same file: no edge (52% right, +0.1% vs the market) | REJECTED as a signal; information only | no edge |
| Coin analyzer | v7.3: calls only from tested signals with tested exits; the chart read is context | inherits the status of the signal it shows | - |

## Recommended order of work (for the owner to authorise phase by phase)

1. Keep the Phase 1 audit running for at least two weeks of real scans so the ledger and registry show how many
   coins each legacy filter removes and why (the snapshot's coverage section).
2. Fix the universe defects that hide real crypto coins (tradfi ticker collisions; missing volume counted as 0) in
   a phase of their own, with a deliberate parity break and before/after evidence.
3. Only then introduce governance statuses as data the engines read, starting from the table above, with every
   status change logged and tested.

No execution features: no wallet connection, no order placement, no automatic leverage, no deposits or
withdrawals, no automatic trading. v8 stays a decision-support tool; trades are placed manually.
