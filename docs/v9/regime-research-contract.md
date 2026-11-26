# D5 regime mechanics and E3 activation boundary

Implemented 2026-11-25 in draft PR #30. All validation before this commit uses invented observations and returns. No market regime/outcome study has been run. This fixes the mechanical diagnostic definitions; it is not a completed study preregistration, accepted source dataset, statistical confirmation or E3 activation.

## Fixed definitions

Each predicate partitions a supplied frozen baseline into ON, OFF and UNKNOWN. These are five separate hypotheses, not a combined filter or a parameter search. ON does not mean favorable, tradable or profitable.

| Diagnostic | ON definition | Maximum observation age |
|---|---|---|
| BTC_ABOVE_SMA200 | Latest daily BTC close strictly above its 200-close arithmetic mean, including that close; all 200 consecutive UTC daily observations required | 2 days |
| DVOL_AT_LEAST_60 | Latest DVOL value in percentage points is at least 60 | 1 day |
| ETF_POSITIVE_FLOW | Latest reported daily aggregate ETF net flow in USD is strictly positive | 4 days |
| STABLECOIN_30D_GROWTH | Latest daily aggregate supply exceeds supply exactly 30 UTC days earlier | 2 days |
| FEAR_GREED_AT_LEAST_50 | Latest index value on the 0–100 scale is at least 50 | 2 days |

Thresholds and ages are design choices fixed before market evaluation, not measured optimal cutoffs. The ETF rule uses one published daily observation, not an inferred five-session sum or trading calendar. BTC equality and zero ETF flow are OFF. Zero stablecoin growth is OFF. Missing inputs, stale observations, incomplete BTC windows and missing stablecoin baselines are UNKNOWN. No source is substituted for another.

## Time and source contract

Observations carry feature, period_end, available_at, value and source_sha256. All times are integer UTC seconds. Values are fixed-point decimal strings, not floats. BTC closes and stablecoin supply must be positive and lie on the daily UTC grid; DVOL is nonnegative; sentiment is between 0 and 100; ETF flows may be negative or zero.

An observation and its publication/revision must both precede the baseline signal time strictly. Equality is excluded. For a period with revisions, only the latest version actually available before the cutoff wins. Duplicate feature/period/publication keys fail rather than choosing an arbitrary value. A late revision never changes an earlier classification. Freshness uses observation period end, not download time; a newly fetched old value cannot appear current.

These mechanics do not authenticate a supplied hash or publication timestamp. Historical availability, revisions, feature units, instrument identity and source-population consistency need independent source acceptance. Current collected context, capture time alone and retrospectively downloaded revised values cannot establish historical availability. Unknown historical publication times must remain unavailable, not be filled with period end. The live market collector is not adapted automatically by this module.

## Diagnostic report and limits

Use tools.v9.regime_research.Inputs for causal classifications and report for an offline diagnostic partition. The report binds the supplied protocol, observations and baseline by SHA-256. It preserves each unique baseline trade in exactly one state for every definition. Missing returns have separate counts and are never replaced with zero. Sums describe observed supplied net-R values only, not qualified performance. No trade is re-simulated and no portfolio, cost, exit or capital path is recomputed.

All five hypotheses remain visible even when every row is UNKNOWN. There are no p-values, winning-regime selection, combined gates or live imports. statistical_confirmation and live_regime_gating_authorized are always false. A caller cannot enable either through a report argument. The existing decision engine remains unchanged.

Inputs are capped at 100,000 observations and 100,000 trades, with an additional 5,000,000 observation-by-trade work budget. Exceeding it fails before processing; no rows are truncated. This is a bounded diagnostic implementation, not demonstrated full-scale research execution. Decimal accumulation uses sufficient explicit precision for the accepted input bounds, independent of the caller's decimal context.

## Remaining D5/E3 acceptance

Before any market evaluation: accept source/publication histories, bind the confirmed baseline strategy/side and complete baseline evidence, commit exact dataset digests and a full study registration, and independently review the execution/resource plan. The registration must fix the comparison, all five tests, sample sufficiency, missingness treatment, dependence-aware resampling, family correction, untouched forward/holdout window and stopping rule. Existing archive results are already observed; they cannot be relabelled an untouched holdout. An exploratory retrospective result cannot confirm a live gate.

Run only the registered study once, retain failures and unavailable hypotheses, reconcile its complete accounting independently and append the research evidence record. E3 may change decisions only after qualified evidence, a bound policy change, reviewed output deltas and authorized release. Until then, this module stays offline. D5 and E3 remain open acceptance items; the complete five-regime mechanics and diagnostic reporting batch is delivered.

## Prospective history adapter (2026-11-26)

New market-history records additionally preserve captured_at and source_fetched_at. These are additive history fields; the published market document, regime values, daily source parsing and trading engine are unchanged. The capture time is recorded after collection when the compact history record is built. Existing immutable history is never rewritten. Activation awaits merge/release authorization; this is not a claim that production has accumulated the new fields.

The offline tools.v9.regime_history.adapt function reads the exact JSON bytes of one retained v9.market-history/1 record. It binds each emitted observation to those bytes and uses capture time as its conservative availability bound. Source status must be OK; scan, source-fetch and capture times must be ordered; a value dated after its fetch is unavailable. A source timestamp or the scan start alone cannot substitute for missing capture/fetch evidence. Older records therefore emit explicit unavailable dispositions rather than invented availability times.

Fear & Greed, daily stablecoin supply and the last completed ETF day are adapted. ETF values explicitly marked USD millions are converted to USD; its daily interval ends at the following UTC midnight and must precede the fetch. Negative and zero flows are preserved. Stablecoin timestamps must satisfy the registered daily grid. Values are the rounded public context projection, not authenticated upstream originals. Repeated captures do not establish independent observations or historical publication authenticity.

BTC is unavailable because a live mark/premium is not a daily close. DVOL is unavailable because the existing compact projection does not establish completion of its hourly candle; an in-progress close must not be labelled a completed-period value. The adapter does not change that public parser or invent a candle endpoint. It conserves all five features as emitted observations or explicit unavailable reasons, and cannot authorize a dataset or live gate.

Synthetic tests cover writer preservation, old-history refusal, strict capture-time cutoffs, failed and future fetches, source timestamps after fetch, ETF units/completed days, stablecoin daily alignment and the unavailable BTC/DVOL dispositions. No market data or return study was run for this batch.

## Separate completed-candle sources (2026-11-26)

The compact market-history adapter still refuses BTC/DVOL because those fields do not establish the required candles. A separate offline capture, tools/v9/regime_candles.py, now supplies those two paths without changing the public market parser or trading engine. BTC means Coinbase Exchange BTC-USD spot daily candles for this prospective source contract; DVOL means Deribit BTC volatility-index hourly candles. These explicit source choices require independent acceptance before a study and must not be silently substituted with another venue or metric.

Official references: [Coinbase product candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles) and [Deribit volatility-index candles](https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data). The bounded capture makes exactly one request per source, with 200 UTC days for BTC and eight days for hourly DVOL. It makes no retries or pagination. Both responses are retained unchanged with exact URLs, byte counts, hashes, receive/capture times and the collector's implementation digest. Existing directories cannot be reused; partial/failed attempts remain explicit. Each response has a 2 MiB cap and a 30-second timeout.

Use `python -m tools.v9.regime_candles capture --directory <new-directory>` and `python -m tools.v9.regime_candles verify --directory <retained-directory>`. The verifier requires the matching implementation, rechecks all raw bindings and parses numeric JSON with decimal precision. It refuses duplicate/off-grid candles, invalid OHLC/volume, nonfinite values and unresolved provider continuation. Current candles and rows outside the fixed completed request window are counted as excluded. No prices are repaired. BTC needs the exact 200 consecutive closes ending at the last UTC midnight; DVOL needs the most recent completed hour. An incomplete source emits no usable observations.

Every selected candle, including the historical lookback, becomes available only at the completed capture time. Original historical publication times are never inferred from bar timestamps. The existing diagnostic's strict cutoff means none of these rows can explain a signal at or before capture. This is prospective input preparation, not a historical backtest or proof that source data cannot later be revised. No source authenticity, dataset acceptance or live gating authority is granted.

The final bounded live capture on 2026-11-26 is retained in research/v9/regime_candle_capture/, including both exact raw responses. BTC returned 201 rows: 200 completed daily closes retained and one out-of-window/current row excluded. DVOL returned 192 rows: 190 completed in-window hours retained and two outside the completed request window excluded. Both required current windows are complete; all 390 observations share the conservative capture-time bound. Re-reading the saved files reproduced the report exactly. No trade returns, regime profitability or strategy outcomes were computed. The capture does not supply the other sources' long-term coverage or replace the remaining D5 registration/qualification and E3 release requirements.

Final parser review added a fixed numeric precision/exponent bound before formatting, preventing oversized decimal expansion. The first live capture remains unchanged locally under outputs/regime-candles-2026-11-26; after this correction, a separate two-request capture under outputs/regime-candles-2026-11-26-bounded-digits reverified successfully with the final implementation. The committed capture is this second attempt, not a rewritten first attempt. Counts remained 200 BTC closes and 190 DVOL hours. The initial test run is superseded and is not cited as final validation. The attempt to stop it was not confirmed because automatic approval review timed out; final validation uses a separate log.
