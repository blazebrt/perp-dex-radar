# Known legacy behaviour, deliberately NOT fixed in Phase 1

Phase 1 observes; it does not correct. Each item below is now visible in the registry, the ledger or the data
health section of the snapshot, and is left for a later, separately authorised phase. Fixing any of them changes
what the engines decide, so it needs its own parity break, its own evidence and the owner's approval.

| # | Behaviour | Effect | Where it shows in the audit |
|---|---|---|---|
| 1 | The tradfi flag is OR-ed over **every** adapter row of a ticker - duplicates and markets later dropped as price conflicts included - and then over the name check | A crypto coin whose ticker is also a stock, an equity market or a 24/5 market on another venue (BB, PURR, QNT class) is excluded from every engine, even when the tradfi market is itself dropped as a price conflict | `TRADFI_TICKER_COLLISION` with `tradfi_rows`; registry `assets[t].collision` |
| 2 | `liq_of(c) or 0`: a venue volume of exactly 0 and a missing volume both become 0; volume on DEXs outside your trade DEXs counts as 0 | Coins with missing volume look illiquid; coins listed only on dYdX, Paradex, edgeX or Extended are never executable | `DEX_VOLUME_MISSING_LEGACY_ZERO`, `NOT_ON_TRADE_DEX`, basis `OBSERVED_ZERO` |
| 3 | The $1M liquidity gate runs before discovery (radar stage 2, quant, picks) | Small and newly listed coins are never evaluated by those engines | `DEX_VOLUME_BELOW_LEGACY_MIN` with the observed volume |
| 4 | The universe is built three times per scan (scanner, quant desk, coin picks), each fetching all eight market lists again | Duplicate requests to every DEX, and the three engines can see slightly different universes within one scan | `coverage.summary.engine_universe_differences` |
| 5 | History gates: 30 closed 1h candles (radar), 30 days (quant), 90 daily candles (swing), 170 hourly candles (day) | New listings are invisible to the longer-horizon engines for weeks | `INSUFFICIENT_*_HISTORY` |
| 6 | Radar paper costs assume `fund_default` (0.01% per 8h) when no DEX sends funding | Paper results of those coins use an assumed cost | step `FUNDING_ASSUMED_DEFAULT` |
| 7 | Quant paper trades count a missing funding settlement as 0 | Paper results can understate funding costs | documented here (the settlement map is local to the replay) |
| 8 | Quant acts only on newly closed bars | A coin in signal state on a bar processed earlier is not surfaced again | `QUANT_SIGNAL_NOT_ACTED` |
| 9 | Picks day-trade scores: the repository's own research file (`picks_research.json`, 119 coins, Oct 2025 - Oct 2026) shows a negative average result in every score band, longs and shorts (longs: all -0.13R, 90+ -0.05R per trade; shorts: all -0.05R, 90+ -0.10R), yet day lists are published with "Good/Best conditions" labels | Day-trade listings read as actionable without a tested edge | `DAY_READY` / `DAY_SETTING_UP` records (they mirror what is published) |
| 10 | The radar's `coverage.nodata` lumps different causes together | No-data coins could not be told apart | `NO_SUPPORTED_CANDLES`, `INSUFFICIENT_1H_HISTORY`, `PRICE_SCALE_CONFLICT` |
| 11 | Error notes are collected by parallel threads (order varies) and capped (80 kept, 60 or 40 published) | Notes can be lost silently on a bad scan | the audit does not depend on them |
| 12 | The Hyperliquid adapter pairs markets and contexts with `zip()`; a longer list is cut silently | A market without a context row would vanish | registry venue counts (`unmatched_rows`) |
| 13 | The Aster adapter does not skip an empty symbol | A nameless Aster market would become a coin named "" | registry contract with `asset` "" |
| 14 | edgeX market lists carry no price or volume | Every edgeX contract is `MISSING` in data health; edgeX never counts for liquidity or price checks | `data_health.contracts_by_venue.edgex` |
| 15 | No DEX market list sends a venue timestamp | Staleness of DEX data cannot be measured at the source | `src_ts` null on every contract |
| 16 | Smart money reads Hyperliquid only and ignores positions under $10k | Coins not on Hyperliquid can never have a smart-money signal | `SMART_VENUE_NOT_COVERED`, `SMART_POSITIONS_BELOW_MIN` |
| 17 | The Scan workflow is scheduled 72 times a day (minutes 7, 27, 47) but GitHub runs it about 4 times a day | Fewer scans than the settings assume (`every_min` 20) | storage projections use both figures |
| 18 | Other pre-analysis gates: $5M reference (CEX) volume for quant and swing, the radar's top-40 + 16 extras deep-dive shortlist, the top-50 day-trade candidate list, top-10/8-watch publication cut-offs, candles only from MEXC, Gate.io, Bitget, Hyperliquid or Aster | Coins are dropped before or during analysis for reasons unrelated to their setup | `REF_VOLUME_BELOW_LEGACY_MIN`, `RADAR_STAGE2_NOT_SELECTED`, `DAY_CANDIDATE_NOT_SELECTED`, `OUTPUT_TOP_N_CUTOFF`, `NO_SUPPORTED_CANDLES` |
| 19 | Hard-coded strategy authority: `tools/research/qexport.py` has `FINAL = ("TSMOM", "TREND_EMA", "XSMOM")` and `verdict()` returns "live" for them before any evidence test; `quant.py` runs `ORDER = ("TSMOM", "TREND_EMA", "XSMOM")` regardless of verdicts | The quant desk's "live" strategies are assigned, not earned | manifest `strategy_authority` |
| 20 | Survivorship bias: the historical research universe is selected from today's surviving, liquid contracts | Backtests overstate results | documented (research tools are outside the scan) |
| 21 | Quant historical slippage uses today's DEX volume | Historical costs are understated for coins that were thinner then | documented |
| 22 | Swing backtest: fixed 0.19% round-trip cost, no funding | Swing results omit funding and real spread variation | documented (`picks_research.json` rules) |
| 23 | Quant funding is partly assumed and taken from a reference exchange (MEXC), not the DEX traded | Paper and backtest funding can differ from what a DEX position pays | documented; item 7 |
| 24 | Portfolio simulation is realised-equity only, with no correlation or beta clustering | Portfolio risk of several same-direction positions is understated | documented |

Nothing in this list was changed by Phase 1, and Phase 1 instrumentation is not a claim that any of it is solved.
The parity check proves the legacy outputs unchanged on the fixture.
