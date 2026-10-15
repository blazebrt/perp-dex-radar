# v9 handover: from a governed desk with no trades to a data-driven desk that earns its trades

The owner's brief (2026-10-14) asked for four things:

- The v8 desk's interface is clean, but its data use, signal quality and evaluation methods are worse than the
  legacy product's.
- It recommends no trades at all.
- Rebuild it from the legacy product using every free crypto data source, with a data-driven decision engine. It
  should be "world class", the kind of tool someone would pay $1,000 for.
- Leave a plan so that later sessions do not get lost.

Work autonomously, and ask the owner only when a login is needed.

This file is that plan. Keep it current.

## 0. How to resume

1. Read `CLAUDE.md`. It covers environment facts, the results branches and the rules.
2. v9 is merged into `main` (PR #28, merge commit `f58c058`), so start from `main` and work on a new `v9/...`
   branch with a draft PR. #25, #26 and #27 are closed as merged through #28. PR #24 (the v8 desk) was merged on
   2026-10-14. The local clone fetches `v9/*` branches; results branches still need an explicit refspec.
3. Read the latest evidence. Fetch each results branch with an explicit refspec (see `CLAUDE.md`), then:
   - `git show origin/evidence-results:REPORT.md` (phase A/B: the legacy strategies);
   - `git show origin/evidence-d1-results:REPORT_D1.md` and `origin/evidence-d2-results:REPORT_D2.md` (phase D);
   - `research/v9/evidence_runs.jsonl` (every run, hash-chained).
4. Pick the first unchecked item in section 6 that is not blocked, and work on it.

## 1. Where things stand

| Area | State | Where |
|---|---|---|
| Release | **v9 is merged into `main`** (PR #28, merge commit `f58c058`, 2026-10-15, at the owner's request), carrying #25, #26 and #27; those three are closed. The first production Scan on `main` published the v9 desk and the first market-history record. | PR #28 |
| v8 desk (Today, Analyzer, Funding, Portfolio, Research) | **Merged into main** (PR #24, 2026-10-14, with the owner's accuracy fixes). | `today.html`, `desk.js`, `desk.css` |
| Data-source survey | **Done.** 102 sources probed from the Actions runner; 81 answer. | `docs/v9/data-sources.md`, branch `probe-results` |
| Known-trial replay (A4) | **In progress (2026-10-15).** Validated inventory: 199 trials; 192 use the existing 4h archive, seven require A5. No new market-data replay has run. | `tools/v9/census_plan.py`, `research/v9/census_replay_plan.json` |
| Survivorship-free evidence engine | **v1 done.** 17 daily/4h strategies plus the coin-picks swing score, on 750 coins (170 delisted), 2020-01 to 2026-09. Every run is recorded, hash-chained and pinned to its dataset (A8). | `tools/v9/archive_fetch.py`, `tools/v9/evidence.py`, `research/v9/evidence_runs.jsonl`, branch `evidence-results` |
| Probation tier (first governed trades) | **Implemented** (`dada154`, in PR #28). XSMOM long is CONFIRMED on (a)–(j). It trades at half size inside a 24h window. Its forward test `V9-PROBATION-XSMOM-LONG-1` starts 2026-10-15 00:00 UTC. The live check is B8. | `docs/v9/phase-b-probation.md`, `research/v9/probation_evidence.json` |
| Live multi-venue data layer | **C1–C3 built** (in PR #28): `v9/market.py`, `data/v9/market.json`, an hourly history on `v9-market-history`, a Today panel and Analyzer context. 16 of 16 sources answered from Actions. | `docs/v9/market-context.md`, branch `market-results` |
| Trade alerts | **Built** (F5, in PR #28): Telegram and/or Discord on every new TRADE, with the full plan. Sends nothing until the owner adds the secrets. | `v9/alerts.py` |
| New signal research (positioning, funding, OI, liquidations, basis, regime) | **D1 and D2 done, D7 answered.** Four strategies (funding fade, taker flow, top-trader divergence, crowd fade) were pre-registered and each tested once on the phase B dataset. **None is confirmed.** XSMOM long remains the only tradable side. | `docs/v9/phase-d1-preregistration.md`, `docs/v9/phase-d2-preregistration.md`, branches `evidence-d1-results`, `evidence-d2-results` |
| Decision engine v2 (expected-R ranking, regime, sizing) | **E4 done**: the forward test is evaluated every scan, shown on Today and demotes a side automatically. E1–E3 not started. | section 6, phase E |
| Pro UX (rich trade plans, market board, performance ledger, alerts) | **F1 done** (full trade plan: entry, stop, trailing stop, time exit, size on the page account and in the trader's own dollars, evidence, forward test). F2 first version, F5 alerts. F3 and F4 not started. | section 6, phase F |

## 2. Diagnosis: why there are no trades, and what got worse

### Why the desk shows zero TRADE

All three causes come from the v8 design itself, not from the market.

1. **The strategy-authority gate cannot be passed.**
   - A strategy may produce a TRADE only when its policy row says `ACTIVE_REQUALIFIED` / `REQUALIFIED`.
   - Requalification needs every check in `v8/strategy_authority.py`, and two of them cannot pass:
     - `trial_census_complete` must be true, but `tools/research/strategy_census.build()` always returns
       `complete: False`. The historical research was imported as one commit, so earlier trials can never be
       counted.
     - A 180-day prospective registration must also pass, and none has been registered.
   - So no strategy can ever be requalified under v8 rules.
   - The three runtime strategies (TSMOM, TREND_EMA, XSMOM) are `LEGACY_HOLDOVER`, so their signals cap at WATCH.
     The other 21 candidates are `DISABLED`.
2. **The paper book is over its limits.**
   - The quant desk's legacy-holdover paper positions put the Phase 10 portfolio in `LIMIT_BREACHED`.
   - Every new directional signal is therefore AVOID (`PORTFOLIO_LIMIT_BREACHED`), even one that would otherwise
     qualify.
   - The book being measured holds positions the desk never recommended.
3. **The other legacy signals were never decision candidates.** The coin-picks swing score, the 15-minute radar
   and smart money only appear as "diagnostic" pages. Emerging and funding opportunities are capped at WATCH by
   policy.

### What got worse compared with the legacy product

- **Signals.**
  - The legacy picks gave entry, stop, three targets, size and 18 explained checks.
  - It also used OI, liquidations, the top-trader long/short ratio, funding, unlocks and smart money as score inputs.
  - v8 uses none of these market inputs in its decision (only funding, as a cost).
- **Evaluation.**
  - The legacy research tested today's coin list, which carries survivorship bias. v8 labelled those results
    `LEGACY_SURVIVORSHIP_UNQUALIFIED`, which was correct.
  - But v8 then waited for its own point-in-time history: 0 days on 2026-10-13, 180 needed. That left nothing to
    qualify with.
  - A survivorship-free public archive already existed. That is the gap phase A closes.
- **Data.**
  - v8 publishes a 9.8 MB audit per scan, yet the decision shows little market insight per coin.
  - Binance and Bybit APIs are blocked from the US runners, so the legacy fetchers fell back to MEXC, Gate and
    Hyperliquid for history, again on the current coin list only.

## 3. Evidence so far (survivorship-free, run of 2026-10-14)

The full table is in `docs/v9/evidence-2026-10-14.md`; the latest run is on the `evidence-results` branch.

**Setup.**

- Universe: every Binance USD-M perpetual that ever traded, 2020-01 to 2026-09. That is 750 coins in the panel, 170
  of them delisted. TradFi, index and stablecoin contracts are excluded.
- Costs: 0.045% taker fee plus 0.10% slippage on each side, and observed funding.
- Eligibility is point-in-time: $5M or more a day over the last 7 days, and at least 30 days listed.
- The legacy strategies were designed on Oct 2023 to Oct 2026 data. So **Jan 2020 to Sep 2023 is a holdout** they
  never saw, out of sample in time, and the delisted coins are out of sample in the cross-section.

**What holds up.** R is the net result in units of the stop distance, per trade.

| Hypothesis | Holdout 2020-01..2023-09 | Design window 2023-10..2026-09 | Since 2025-01 |
|---|---|---|---|
| **XSMOM long** (momentum rotation, longs) | **+0.167R, 95% low +0.030, p=0.009, 503 trades** | **+0.231R, 95% low +0.014, p=0.018, 443 trades** | +0.139R, p=0.15, 206 trades |
| XSMOM short | +0.068R (p=0.06) | **−0.131R (significantly negative)** | −0.029R |
| TSMOM short | +0.163R (p=0.001) | −0.001R | +0.106R (p=0.03) |
| TSMOM long | +0.009R | +0.062R | −0.064R |
| TREND_EMA (both sides) | −0.012R | +0.012R | −0.001R |
| Swing score, short 80+, one trade per coin at a time | +0.069R | +0.148R | 2024 +0.10, 2025 +0.27 |
| Swing score, long 80+ | **−0.128R** | +0.303R | mixed |

**What it means.**

- **Most legacy claims do not survive.**
  - TREND_EMA (legacy claim +0.095R) is flat.
  - The swing score's long side only works in the window it was built on; it loses in the holdout, a classic sign of
    overfitting.
  - 14 of 17 candidates have no positive 95% lower bound (only TSMOM, XSMOM and TSMOM_SLOW do).
- **XSMOM longs are the strongest result.** They are positive and significant in two independent windows.
  - In the holdout, among the 6 side-level hypotheses of the 3 runtime strategies, Holm-adjusted: TSMOM short
    p=0.006 and XSMOM long p=0.043 survive.
  - Only XSMOM long is also confirmed in the design window.
- **The family-wide tests do not pass.** Across all 17 candidates, White Reality Check p=0.76, Hansen SPA p=0.16 and
  PBO 0.28 (the gate needs ≤ 0.20).
  - Those tests ask whether the best of 17 in-sample is real.
  - The holdout test asks a different question: does a strategy chosen on other data work on unseen data? That is
    the right test for strategies whose selection happened in 2023-2026.
- **Caveat.** The side-level gate in phase B was written after this first look. Its protection is therefore the
  forward test (registered before any probation trade) and a reduced size, not the backtest alone.

## 4. Target product: what "world class" means here

A trader opens Today and, in ten seconds, knows:

- **What can be traded now**, as at most five trades. Each has its evidence tier (Validated or Probation), a full
  plan (entry zone, stop, trailing rule, time stop, size for the user's own account), and the expected R with its
  confidence interval from survivorship-free tests.
- **Why**, from the decision trace in plain words.
- **What the market regime is:** trend, volatility (DVOL), funding and OI crowding, liquidations, ETF and stablecoin
  flows, fear and greed.
- **What to watch next:** WATCH opportunities with the exact change that would make them trades.
- **How the desk itself is doing:** the live record of every tier against its backtest expectation, with automatic
  demotion when live results fall outside the expected band.

Plus:

- a coin deep-dive with every data source;
- Telegram alerts (the hook already exists in `scanner.py`);
- a funding desk with multi-venue spreads;
- a portfolio console for the governed book.

Everything is honest about uncertainty and nothing places orders.

## 5. Architecture (v9)

```
  data layer (Actions, every scan)          evidence engine (Actions, daily/weekly)        decision engine
  ─────────────────────────────────         ──────────────────────────────────────        ───────────────
  venues: HL, OKX, Gate, Bitget, MEXC,       archive_fetch.py  ──►  md_bn (archive-data)    v8/decision.py + v9 tiers
  HTX, KuCoin, Kraken, dYdX, Aster,          evidence.py       ──►  evidence-results         (TRADE needs a tier:
  Deribit, CoinGecko derivatives             confirm.py (B)    ──►  research/v9/*.json         FULL or PROBATION)
  market: DVOL, F&G, ETF flows,              + new signal studies (phase D)                  governed book only
  stablecoins, DefiLlama OI,                                                                 sizing x tier multiplier
  Coinbase/Korea premium                                                                     ─► decision.json ─► desk
  → data/v9/market.json (phase C)
```

## 6. Roadmap (in order; tick items as they land, with the commit)

### Phase A: evidence engine (survivorship-free)

- [x] A1. Probe every free source from Actions (`probe.yml`, `docs/v9/data-sources.md`).
- [x] A2. Binance archive fetcher, point-in-time universe including delisted coins (`archive_fetch.py`).
  - Only bars with volume count.
  - A gap of more than 7 days splits a coin into separate lives.
  - Non-ASCII tickers are URL-quoted.
- [x] A3. Re-test the 17 4h/daily candidates and the swing score (`evidence.py`), with Phase 9 statistics.
- [ ] A4. Run all census trials (the qgrid grids, 199 or more) on the archive. That gives a complete known-trial
  return matrix, so DSR uses measured across-trial Sharpe variance and PBO covers the known family.
  - [x] A4.1 (2026-10-15, `v9/census-evidence`). Validate and pin all 199 trial IDs, expanded parameters, required timeframes and replay code hash. Three tests cover reproduction and corrupted identities/counts/parameters.
  - [ ] A4.2. Implement and synthetically validate the replay runner and common daily return matrix; commit its protocol before reading new market results.
  - [ ] A4.3. Run the 192 4h/daily definitions on phase B's pinned dataset, preserving each trial and explicit errors.
  - [ ] A4.4. After A5, run the seven hourly definitions and assemble all 199 columns; calculate DSR/PBO with explicit unavailable cases, record the evidence run, and review the report.
  - **Dependency correction:** A4 cannot finish before A5. A4.1 discovers seven hourly trials: BTC_LEAD, FAIL_BRK, FUND_CARRY, FUND_FADE, LIQ_FLUSH, PULLBACK and VOL_SPIKE.
  - **Interpretation:** these are new replays of known definitions under a pinned simulator, not recovered historical returns. The unknown historical trial census remains incomplete, even after all known columns are populated. No new promotion authority follows from this inventory.
- [ ] A5. Run the 1h candidates on an hourly archive for the liquid subset (top 150 by point-in-time volume).
- [ ] A6. Use 50 matched controls per signal (time, liquidity bucket, listing-age bucket; listing age is known from
  the archive) to meet the Phase 9 matched-control gate.
- [ ] A7. Cross-check on the execution venue: Hyperliquid candles, delisted coins included (56 of 234 perps are
  `isDelisted` and their candles still load). Daily from 2022, 4h for about 830 days.
- [x] A8. Pin the evidence run to a dataset hash and keep the history of evidence runs.
  - `research/v9/evidence_runs.jsonl` holds one record per run: phase A/B, D1 and D2 so far. Each record pins the code
    commit, the dataset digest, the data branches read, the sha256 of the evidence, report and trades files, the
    pre-registration hash and what was confirmed.
  - Records are hash-chained, so an edited or removed record breaks the chain.
  - `tests/test_v9_evidence_runs.py` (in CI) verifies the following:
    - the chain is intact;
    - the phase A/B record is the run the probation tier is bound to;
    - every study ran on phase B's candles and funding;
    - no pre-registration document changed after its run.
  - After every new evidence run, append its record with `python tools/v9/record_run.py --study <A/B|D1|D2>`. Fetch the
    results branch first.

### Phase B: evidence tiers, the first governed trades (next session's main task)

Probation gate, per (strategy, side). All of these must hold on archive evidence:

- (a) The definition was fixed before the holdout was examined. This is true for the three runtime strategies.
- (b) Holdout mean R > 0, Holm-adjusted one-sided p < 0.05 over all side-hypotheses submitted.
- (c) Design-window mean R > 0, one-sided p < 0.10 (consistent, not contradicted).
- (d) The most recent third has mean R > 0.
- (e) Cost stress ×1.5 keeps mean R > 0.
- (f) The edge over the random twin is positive.
- (g) The Phase 9 concentration limits hold.
- (h) At least 500 trades in total and 100 in the holdout.

Added on 2026-10-14, before the evidence run that first measures them (`evidence.py` v9.archive-evidence/2,
`runtime_robustness`):

- (i) Deployable universe. The live desk ranks about 80 coins, while the archive ranks every eligible Binance perp.
  On a point-in-time proxy (the 80 eligible coins with the largest trailing 7-day volume at each bar), the side's mean
  R must be > 0 in both the holdout and the design window.
- (j) Late entry. A daily signal stays on the desk for up to a day, so a trader may enter hours after the open the
  backtest assumes. The same signals entered 4h, 8h, 12h and 24h late are tested. A delay passes when the side's mean
  R over all windows is > 0 and its holdout mean R is > 0.
  - The probation TRADE window is the longest tested delay such that it and every shorter tested delay pass. After
    the window, the signal is WATCH (`PROBATION_ENTRY_WINDOW_PASSED`).
  - If the 4h delay fails, the side is not confirmed.

Result (evidence run `fd03198`, `tools/v9/confirm.py`):

- **XSMOM long is CONFIRMED on every check (a)–(j).**
  - Top-80 universe: +0.19R in the holdout, +0.21R in the design window.
  - Entered 4h, 8h, 12h or 24h late: +0.18R to +0.20R, so the TRADE window is 24h.
- Every other side is NOT_CONFIRMED.

- [x] B1 (`59faf14`). `tools/v9/confirm.py` writes `research/v9/probation_evidence.json`. It is hash-bound to the archive dataset
  hash, the research code hash and `runtime_implementation_hash`, and carries per-hypothesis statistics and verdicts.
- [x] B2 (`ac74168`, record 2 `V9-PROBATION-XSMOM-LONG-1`, evaluation from 2026-10-15 00:00 UTC). Register the
  forward test in the shadow ledger (`v8/shadow_ledger.py`) **before** any probation trade.
  Primary metric: live net R of probation trades. Demotion rule: after 30 or more trades, demote if the live mean R
  falls below the archive's 5th-percentile band (bootstrap); promotion to full after the Phase 9 gate's 180 days.
- [x] B3 (`dada154`). Policy changes:
  - `quant_strategy_policy.json`: XSMOM becomes `ACTIVE_PROBATION` / `PROBATION`, with `probation: {sides: ["long"],
    risk_multiplier: 0.5, evidence, evidence_hash}`.
  - `v8/strategy_policy.py` validates it fail-closed: the evidence file must exist, its hash must match, its verdict
    must be CONFIRMED, and the runtime hash must be equal.
- [x] B4 (`dada154`). Decision engine (also: ENTERED signals, `strategy_tiers`, the unconfirmed side is not emerging
  evidence):
  - `decision_policy.json` gains `probation_deployment_states` and `probation_research_states`.
  - The `v8/decision.py` STRATEGY_AUTHORITY gate passes with `tier: PROBATION` for a confirmed side, and caps the
    other side at WATCH (`STRATEGY_SIDE_NOT_CONFIRMED`).
  - PROPOSED_TRADE risk becomes `risk_per_trade × risk_multiplier`.
  - Candidates carry `authority_tier`.
- [x] B5 (`dada154`). Governed book:
  - The Phase 10 gates evaluate only the positions of trade-authorized strategy sides.
  - The legacy-holdover positions stay visible as a "legacy diagnostic book" on Portfolio.
  - Keep the audit binding consistent: compare full-book states for consistency, and gate on the governed book.
- [x] B6 (`dada154`). Desk:
  - The TRADE card shows a probation tag, the engine's plan, the archive expectation and the forward test.
  - Today names the authorized sides, and Portfolio separates the governed book from the legacy paper book.
  - The Research page and its publication logic are pinned by the owner's PR #24 scope test, so they were left
    unchanged. Showing the tiers there is a follow-up (F4).
- [x] B7 (`dada154`; `tests/test_v9_decision.py`, `tests/test_v9_scope.py`, v9b golden and manifest). Tests:
  - New invariants: only ACTIVE_REQUALIFIED/REQUALIFIED or ACTIVE_PROBATION/PROBATION can TRADE.
  - Probation requires a bound CONFIRMED record.
  - The unconfirmed side is WATCH.
  - Size is halved.
  - The governed book excludes holdovers.
  - Update the Phase 9, 10, 11 and 12 tests and goldens, with a delta manifest that pins the decision changes.
- [x] B8. Live check, after the 2026-10-15 00:00 UTC close (Research run 38661431562 on `45e387a`, the same tree
  as `main` `f58c058`; results `ee107d4` on the `research` branch).
  - Every mandatory step passed. The forward test is in effect.
  - The close produced fresh signals, all shorts:
    - XSMOM short on ETH, SOL and XLM: WATCH with `STRATEGY_SIDE_NOT_CONFIRMED`, as designed;
    - five TSMOM and TREND_EMA shorts: WATCH with `STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT`;
    - one TREND_EMA short: AVOID for an economic-exposure conflict.
  - Nothing became TRADE (24 WATCH, 336 AVOID). The governed book was WITHIN_LIMITS while the legacy paper book was
    LIMIT_BREACHED, which is diagnostic only.
  - quant.py emitted **no XSMOM long signal** at this close, so the live TRADE path has not fired yet. At the
    previous close the cause was that all top-5 coins needed stops wider than 20% (the archive's rule). The path is
    covered by `tests/test_v9_decision.py`, and the first live one will show on Today, in the journal and in the
    alerts.
  - Next session: on the first close with an XSMOM long signal, confirm it is TRADE, tier PROBATION, at 0.5× size.
- [ ] B9. Known follow-ups:
  - TREND_EMA has no edge in the archive. A reviewed policy change could mark it REJECTED (AVOID).
  - Legacy WATCH signals still feed Emerging.
  - Forward-test trades count as "qualified" only when the journal has execution and funding proof (see
    `quant.py` `qualified_trade`). The demotion rule uses every closed trade.
  - XSMOM long only fires when a top-5 coin's stop fits within 20%. On volatile days there is honestly no trade. More
    trades must come from more confirmed strategies (phase D), never from loosening this rule after the fact.

### Phase C: live multi-venue data layer

- [x] C1 (`v9/market.py`, branch `v9/market-data`). Hyperliquid funding, OI and premium; Binance and Bybit funding
  through Hyperliquid's predicted-funding feed; Gate OI, long/short ratios and liquidations for the 30 most traded
  coins. The rest of this item's list is left for C1b. The Scan workflow runs it on every scan and publishes
  `data/v9/market.json`, context only:
  - funding from HL, OKX, Gate, Bitget, MEXC, dYdX, Kraken and Bitfinex, plus CoinGecko derivatives for
    Binance/Bybit values;
  - OI (OKX, Gate, Bitget, HTX, HL);
  - long/short ratios (OKX, Gate, Bitget, HTX);
  - liquidations (OKX, Gate public orders);
  - basis / premium (HL `metaAndAssetCtxs`).
- [x] C2 (`v9/market.py`). Deribit DVOL, Fear & Greed, stablecoin supply, Coinbase and Korea premiums, Bitfinex BTC
  margin, CoinGecko global and Farside ETF flows. Options summary and Upbit listings remain open. Market regime
  inputs:
  - Deribit DVOL and options summary;
  - alternative.me Fear & Greed;
  - Farside ETF flows (HTML table);
  - DefiLlama stablecoin supply and OI;
  - CoinGecko global;
  - Coinbase premium (Coinbase versus `data-api.binance.vision` spot);
  - Korea premium (Upbit/Bithumb plus FX);
  - Upbit new KRW listings.
- [x] C3 (`v9-market-history`, one record per UTC hour from the first scan after the market branch is merged). An
  append-only history of C1 and C2 on a data branch, so that forward history accumulates from day one (each record
  keeps the source and fetch time).
- [x] F2 (first version): Today's "Market context" panel and the Analyzer's per-coin market context (`desk.js`
  `views.market` / `views.marketAsset`).
- [ ] C4. Optional keys (owner action, free): `COINALYZE_API_KEY` (aggregated liquidation, OI and funding history),
  `CRYPTOPANIC_API_KEY`, `FRED_API_KEY`. The probe already checks for them.

### Phase D: signal research on the new data (each through the evidence engine; only survivors become strategies)

How every phase D study runs (D1 set the pattern):

1. Write the definitions and a pre-registration document, and commit them **before** any run on market data.
   Synthetic-archive checks are allowed; they test mechanics, not hypotheses.
2. Test once, with phase B's gate (b)–(j), and a Holm family per study.
3. Record the result as is. A confirmed side is a probation candidate: it still needs a runtime implementation,
   re-bound evidence, a forward-test registration and the owner's merge. A failed side is never adjusted; a changed
   definition is a new hypothesis with a new name.
4. Use names that do not collide with the legacy catalogue (`tools/research/qstrat.py`, `qexport.py`).

- [x] D1 (`8ca3f55`; result `03e596f` on `evidence-d1-results`). Funding crowding and taker flow, cross-sectional,
  on data the archive already holds: XS_FUND_FADE and XS_FLOW_MOM.
  - Pre-registered in `docs/v9/phase-d1-preregistration.md`, committed before any run on market data.
  - Code: `tools/v9/d1.py`, `tools/v9/evidence_d1.py`, `tests/test_v9_d1.py` (rankings and no look-ahead).
  - Tested once by `evidence_d1.yml` on the `archive-data` dataset: digest `cd4651eb…`, the same as phase B's.
  - **Result: no side is confirmed. Nothing deploys, and no definition will be changed.**

  | Side | Trades | Holdout R (Holm p) | Design window R (p) | Fails |
  |---|---|---|---|---|
  | XS_FUND_FADE long | 916 | +0.064 (0.30) | −0.020 (0.61) | b, c, d, f |
  | XS_FUND_FADE short | 871 | −0.071 (0.99) | −0.164 (1.00) | b, c, d, e, f, g, i, j |
  | XS_FLOW_MOM long | 2715 | +0.042 (0.20; raw p 0.050) | +0.010 (0.34) | b, c |
  | XS_FLOW_MOM short | 2116 | +0.001 (0.95) | −0.040 (0.98) | b, c, d, e, g, i, j |

  - Shorting the coins whose longs paid the most funding lost money in both windows: crowded longs kept rising more
    often than they unwound. That is an observation, not a tested hypothesis. Going long those coins would also pay
    the highest funding.
  - XS_FLOW_MOM long is positive in every window, at a 1.5× cost stress (+0.013R) and against its random twin
    (+0.081R), but too small to be significant. It is not a strategy. It may be worth recording forward, since the
    live data exists (D1b).
- [ ] D1b (optional). A forward-only record of XS_FLOW_MOM long, registered in the shadow ledger before its first
  observation, with no decision authority. It would need the live 4h candles to carry taker-buy volume, which
  quant.py's candles may not; check that first.
- [x] D2 (pre-registered in `aa6f75a`; result `950d75d` on `evidence-d2-results`). Binance positioning: XS_TOP_DIV
  (follow the top traders where they disagree with the crowd) and XS_CROWD_FADE (fade the crowd's own long/short
  ratio). Both use a one-day lag, because a live desk can only read the previous day's file.
  - Data: `tools/v9/metrics_fetch.py` (`6d088bf`) through `metrics.yml` to `archive-metrics`: 532,738 daily files and
    778 coins, with none failed, in 2.7 hours. The metrics start in 2020-09. The survey and log are on
    `metrics-results`.
  - Order of events: the download finished at 18:37 UTC and the pre-registration was committed at 18:40, with nothing
    from the dataset fetched or read. The study ran once, at 18:41, triggered by that commit. The document's line
    "its download was still running" was true when written, not at commit time. The document is left unedited because
    its hash is in the result.
  - It used the same candles and funding as phase B (digest `cd4651eb…`). Signal coverage was 79% / 89% of eligible
    coin-days, from 2020-09-04.
  - **Result: no side is confirmed. Nothing deploys, and no definition will be changed.**

  | Side | Trades | Holdout R (Holm p) | Design window R (p) | Fails |
  |---|---|---|---|---|
  | XS_TOP_DIV long | 1069 | +0.025 (0.49) | −0.032 (0.86) | b, c, e, f, g, i, j |
  | XS_TOP_DIV short | 1282 | −0.021 (0.88) | −0.093 (1.00) | b, c, d, e, f, g, i, j |
  | XS_CROWD_FADE long | 1050 | +0.041 (0.16; raw p 0.039) | −0.005 (0.57) | b, c, d, f, i |
  | XS_CROWD_FADE short | 1373 | +0.004 (0.88) | −0.019 (0.79) | b, c, e, f, g, i, j |

  - Neither definition shows an edge after costs in either window. The legacy picks used these ratios as score inputs;
    as daily rotations on survivorship-free data, they do not hold up. Open interest and the taker ratio are in the
    dataset but were not part of this study.
- [ ] D3. The legacy 1-hour funding strategies, FUND_FADE (absolute thresholds) and FUND_CARRY. They need hourly
  candles, so they wait for A5's hourly archive.
- [ ] D4. Basis / premium (archive `premiumIndexKlines`).
- [ ] D5. Regime filters for the confirmed strategies: BTC trend, DVOL, ETF flows, stablecoin growth, Fear & Greed.
  Report each as a conditional result, never tuned in-sample without a holdout.
- [ ] D6. Listing effects: Binance and Upbit new listings (archive first bar = listing time).
- [x] D7 (answered by the phase A numbers; nothing to run). Swing-score short side, 80+, one trade per coin at a
  time: holdout +0.069R with a one-sided p of 0.099 before any correction (2167 trades), design window +0.148R. It
  fails check (b), holdout Holm p < 0.05, on its face. The design window is where the score was built, so it cannot
  rescue it. Not a candidate.

### Phase E: decision engine v2

- [ ] E1. Rank TRADE candidates by expected net R with intervals, calibrated from the evidence engine. No opaque
  scores.
- [ ] E2. Size by tier and volatility (risk parity across open trades), within the Phase 10 limits.
- [ ] E3. Regime-aware gating from D5, only where it is confirmed.
- [x] E4. Monitor live tiers against archive expectation and demote automatically (B2's rule, then generalised).
  - Every scan, the engine evaluates each probation side's live forward test against its archive demotion band
    (`strategy_tiers`, `_forward_test`). A side below the band is capped at WATCH automatically
    (`PROBATION_FORWARD_TEST_FAILED`).
  - Today's "Authorized to trade" note shows the live record against the band on every scan, signal or not, e.g.
    "live forward test: 40 closed, mean +0.20R, demoted below …R at 30 trades". TRADE cards show the same.
  - "Generalised": the rule applies to every probation side that is registered. A full-tier (ACTIVE_REQUALIFIED)
    side is governed by Phase 9's requalification, which carries its own 180-day prospective registration. No
    full-tier side exists today.

### Phase F: product UX

- [x] F1. Rich TRADE card: entry zone, stop, trailing rule, time stop, size for the user's account (settings stored
  locally), expected R with interval, tier, and its live record.
  - The tier, the expected R with its interval and the live forward test came with B6.
  - The engine's plan shows: entry near the mark, inside the entry window that the late-entry checks confirmed (the
    entry zone); stop; risk; size on the page account.
  - The time exit, "exit at the stop or 14 days after you enter" (`6dfc56b`), and the trailing stop when the signal
    has one (`trailing_stop_pct`).
  - The plan in the trader's own dollars, from the account size saved in the Analyzer: a labelled unit conversion of
    the same fractions.
  - Shown on the desk, in the Analyzer's governed card (exits only, as the owner's exact-proposal rule keeps that card
    fixed) and in the alerts.
- [x] F2 (first version; see phase C). Market board on Today: regime, funding and OI heatmap, liquidations, flows.
  Today's Market context panel shows the regime inputs, funding extremes, liquidations and flows. A funding/OI
  heatmap was not built.
- [ ] F3. Coin deep-dive in the Analyzer, with every data source (context clearly labelled).
- [ ] F4. Performance ledger page: every tier's live trades against expectation.
- [x] F5 (`v9/alerts.py`, branch `v9/market-data`). A Telegram and/or Discord message for every new TRADE decision,
  with the engine's plan and the valid-until time. The owner adds the secrets `TELEGRAM_BOT_TOKEN` +
  `TELEGRAM_CHAT_ID` and/or `DISCORD_WEBHOOK_URL`; without them nothing is sent.

### Phase G: quality and operations

- [ ] G1. Freshness monitors and failure alerts for every source.
- [ ] G2. Keep the published artifacts small (gzip, compact JSON); trim the 9.8 MB audit or load it lazily.
- [x] G3. CI covers every v9 module; parity manifests for every published change.
  - Every module in `v9/` and `tools/v9/` has tests in CI:
    - main job: market, alerts, metrics_fetch, record_run (`test_v9_evidence_runs`), and register_forward_test with
      the probe tools (`test_v9_tools`);
    - research-checks job (numba): evidence and archive_fetch (`test_v9_evidence`), d1, d2, and confirm with the D1
      and D2 runners (`test_v9_research_tools`).
  - `test_v9_tools` proves the committed forward-test registration is exactly what the tool computes from the bound
    evidence, and that a probe never keeps an API key.
  - `test_v9_research_tools` checks the gate statistics (Holm, clustering, concentration, demotion band, every check
    (b)–(j)) on hand-checked values.
  - Every published change (desk.js, desk.css, analyze.js, analyze.html, quant.html, index.html and four quant.json
    leaves) is pinned in `v9b_expected_deltas.json`, and CI proves differential parity against main.

## 7. Owner actions (only these need you)

- Trade alerts (optional): add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, and/or `DISCORD_WEBHOOK_URL`, as
  repository secrets. Create the bot with Telegram's @BotFather and get your chat id from the bot's getUpdates.
- Optional, free API keys, added under GitHub repository Settings → Secrets → Actions:
  - `COINALYZE_API_KEY`: the best free liquidation history. Sign up at coinalyze.net, then API key.
  - `CRYPTOPANIC_API_KEY`: news.
  - `FRED_API_KEY`: macro.
- Nothing to merge. Watch the first XSMOM long TRADE: it appears only when a top-ranked coin's stop fits within 20%
  at a 00:00 UTC close. The alerts tell you when it does, once the secrets are in.
- No login-only sites are needed. Every source used is a public API or public page.

## 8. Session log

- **2026-10-14 (session 1 of v9).**
  - Probed 102 data sources from Actions.
  - Built the survivorship-free archive (900 USDT perpetual symbols, 781 research coins) and the evidence engine.
  - First results: XSMOM long confirmed out of sample; most legacy claims (TREND_EMA, the swing long score) do not
    survive. Diagnosis written.
  - Plan and this handover. Tests in `tests/test_v9_evidence.py`.
- **2026-10-14 (session 2 of v9): phase B.**
  - Merged main (PR #24 with the owner's accuracy fixes) into v9.
  - Evidence /2 added the pre-registered deployable-universe and late-entry checks (`fd03198`).
  - `confirm.py`: XSMOM long CONFIRMED, everything else not (`59faf14`).
  - Forward test registered in the ledger (`ac74168`).
  - Probation tier, governed book, entered signals, desk presentation, tests and parity (`dada154`).
  - Next: B8 after the 2026-10-15 00:00 UTC close, then phase C.
- **2026-10-14 (session 3 of v9): phases C and D1.**
  - Phase C on `v9/market-data` (draft PR #26): `v9/market.py` collects 16 free sources from Actions into
    `data/v9/market.json`, with an hourly append-only history. Today and the Analyzer show it as context only
    (`281776e`). Fixed after the first live run: live tickers for the Coinbase premium, funding extremes relative to
    the median, no partial ETF day (`9050bd8`).
  - F5: Telegram/Discord alerts on new TRADE decisions (`f0a4316`). They need the owner's secrets.
  - Phase D1 on `v9/research-d1`: two strategies pre-registered and committed before any market-data run
    (`8ca3f55`), then tested once on the phase B dataset. Neither is confirmed; the result is recorded as is.
    `FUND_FADE` was renamed `XS_FUND_FADE` before the commit, because the legacy catalogue already has a different
    FUND_FADE.
  - Phase D renumbered: D1 is this study, the Binance metrics study is D2, and the legacy hourly funding strategies
    are D3.
  - Every TRADE plan now states the strategy's time exit (`6dfc56b` on #25, merged up the stack). XSMOM's archive
    results assume it, and the governed Analyzer card had dropped it, where the legacy Analyzer always showed it.
  - D2: Binance metrics fetched (532,738 files) and two positioning strategies pre-registered and tested once. Neither
    is confirmed (see the D2 item).
  - D7 needs no run: it already fails the gate's holdout check on phase A's numbers.
  - The owner's instruction (2026-10-15 00:05 IST): do not start the 17 untouched items; finish the ones in progress,
    test, merge everything, then deliver the updated handover. Done that night:
    - A8: the evidence run history (`313e1eb`);
    - F1: the trailing stop and the plan in the trader's own account (`bc65436`);
    - G3: tests for every v9 module, including the gate statistics and the study runners;
    - E4: the forward test on Today every scan (`3fa4c91`);
    - D2 and D7, recorded above.
  - Tested on head `3fa4c91`: the full suite, CI on push and on the pull request, and live Research run 38621408999
    (every mandatory step green; four XSMOM shorts WATCH `STRATEGY_SIDE_NOT_CONFIRMED`, no XSMOM long signal yet).
  - PR #28 (`v9/research-d1` → `main`) carries #25, #26 and #27. The first merge API call was blocked by the session's
    automatic safety check; the owner then asked for the merge explicitly and it went through.
  - B8 ran after the 2026-10-15 00:00 UTC close (see below and the B8 item).
  - Merged at the owner's request (2026-10-15 01:35 IST): PR #28 into `main` as merge commit `f58c058`. #25 to #27
    closed. A Scan on `main` published the v9 desk; CI on `main` is green.
  - B8 after the 00:00 UTC close: the gates behave as designed live, nothing became TRADE, and there was no XSMOM long
    signal at that close (see B8).

- **2026-10-15 (Codex continuation): A4 inventory.**
  - Started from main `0953535` on `v9/census-evidence`; read CLAUDE.md and the three A/B, D1 and D2 result reports.
  - Completed A4.1: deterministic, fail-closed inventory of all 199 known definitions and the seven-trial dependency on A5. The plan retains historical and replay code identities separately.
  - A4 remains IN PROGRESS. No new market-data evidence run, strategy promotion, merge or deployment has occurred.
  - Next: A4.2 runner and synthetic validation, then A4.3; A5 is required before A4.4. All other unchecked roadmap items remain open.
