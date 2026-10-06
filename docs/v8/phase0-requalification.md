# Phase 0 requalification - NON-AUTHORITATIVE — IMPLEMENTATION RECOMMENDATION ONLY

> **NON-AUTHORITATIVE — IMPLEMENTATION RECOMMENDATION ONLY.**
> Nothing in the code reads this file. No engine, page, threshold or status depends on it, and Phase 1 did not
> create any runtime governance file or status list. Current production behaviour is unchanged. Dynamic strategy
> governance (statuses as data, with evidence and logged changes) belongs to a later, separately authorised phase.
> Not financial advice.

## Recommendations accepted with Phase 0 (for a later phase to implement)

| Signal source | Recommended status | Note |
|---|---|---|
| Quant TSMOM | ACTIVE, pending requalification | its "live" verdict was pre-assigned (below); requalify on evidence |
| Quant TREND_EMA | PROBATION | |
| Quant XSMOM | PAPER ONLY | |
| Coin picks, swing | ACTIVE but unqualified | requalification still owed |
| Coin picks, day trade | retire from production | the repository's own research shows no edge in any score band |
| Radar, 15-minute strategies | retire from production | |
| Smart money, short crowds | PAPER until enough prospective trades | 31 trades over 18 days so far |

## Why the current "live" labels are not evidence

* `tools/research/qexport.py` contains `FINAL = ("TSMOM", "TREND_EMA", "XSMOM")` and its `verdict()` returns
  "live" for those three **before** any evidence test runs. The "live" verdicts in `quant_research.json` are
  therefore assigned, not earned.
* `quant.py` separately runs `ORDER = ("TSMOM", "TREND_EMA", "XSMOM")` regardless of any verdict.
* Phase 1 does not change either. It exposes them: every audit snapshot's manifest carries
  `strategy_authority` (the runtime order, the research FINAL tuple, whether the verdict is pre-assigned, the
  research file's verdicts and the hashes of the files involved).

## Historical-evidence weaknesses found in Phase 0 (not corrected)

* Quant historical slippage is computed from today's DEX volume.
* The swing backtest uses a fixed 0.19% round-trip cost and no funding.
* The historical research universe is selected from today's surviving, liquid contracts (survivorship bias).
* Quant funding is partly assumed and taken from a reference exchange.
* The portfolio simulation is realised-equity only, with no correlation or beta clustering.

Requalification in a later phase must fix these first, or its results inherit the same bias.
