# Quant paper execution evidence (A05)

This correction changes paper execution accounting only. Strategy signals, parameters, ranking, deployment states,
statistical gates and numerical risk limits retain their existing authorities.

## Clock and price path

The deadline is `t_in + hold_h * 3600`. A new paper entry can be filled only from the candle whose start is exactly
the recorded entry time. A later returned candle cannot silently replace a missing entry candle.

Replay requires every closed hourly candle from that entry until the stop, trailing stop or deadline. At the first
missing interval it reports `pending_history`, `MISSING_CANDLE_PATH`, the missing hour, and no qualified R or exit.
Recovery can replay the same entry against recovered history. It never extends the holding period by counting later
returned candles. A forming hour cannot supply a realized exit. Open diagnostic marks use the last completed replayed
hour, and `hours` describes replayed hours rather than the length of all returned history.

Complete contiguous paths retain the original stop-first rule, adverse opening-price gap execution, close-based
trailing updates, fees, slippage and observed funding formula. Stored historical outcomes are never recomputed.

## Funding observations

Missing funding is distinct from `OBSERVED_ZERO` and `OBSERVED`. A plain simulator funding map must supply an explicit
observation for every evaluated hourly boundary after entry. Production MEXC history additionally retains the
exchange's per-settlement `collectCycle` metadata. The [official MEXC funding history documentation](https://www.mexc.io/api-docs/futures/market-endpoints/get-funding-rate-history)
defines `collectCycle` as the funding cycle in hours.

An observed settlement and its explicit cycle provide the interval ending at that settlement: interior hourly
boundaries are `NOT_SCHEDULED`, and the endpoint remains the actual observed payment, including a literal zero.
There is no inferred cadence, assumed zero, extension beyond the last evidenced interval, or use of a future
settlement. Missing/invalid cycle metadata cannot supply non-settlement coverage. A missing required observation
produces `MISSING_FUNDING`, `r: null`, and `fund: null`. A separately named diagnostic R using only known funding can
remain visible for audit; it is never counted in qualified performance or promotion evidence.

The legacy research Panel contains assumed funding values. The simulator parity helper explicitly supplies those
same hourly values to compare arithmetic, labels the exercise a legacy diagnostic, and does not make the Panel
observed or governed evidence.

## Historical records and consumers

Qualified closed performance requires both complete entry-time crypto identity proof and `quant.execution/1` evidence
with qualified path and funding. `live_stats()` enforces that rule by default. Its explicit `include_unqualified=True`
mode is used only for labelled diagnostic totals. Journal/audit/portfolio consumers use the combined gate.

An existing closed row without corrected execution proof receives `LEGACY_EXECUTION_UNQUALIFIED` metadata, with
historical path and funding explicitly `UNKNOWN`. Its original fields, timestamps and returns stay unchanged. The
full journal retains all closed rows; the browser's recent-history list remains bounded. Unknown history is not
retrospectively claimed to have a missing candle, missing funding, or a known complete path without archived proof.

Regression coverage includes absolute deadlines, stop/trailing gaps, absent entry/tail history, observed-zero versus
missing funding, finite-rate validation, explicit cycle coverage, future-settlement exclusion, unchanged complete-path
arithmetic, combined identity/execution qualification and immutable journal retention. Actual guard-removal checks
record failing behavioral assertions separately from normal passing validation.
