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
