# A5 aggregation clarification after acquisition attempt 1

The original acquisition protocol remains unchanged. This note records a
collector correction, not a change to selection, strategies, costs, price
tolerance or acceptance of unexplained price differences. No strategy has run.

Attempt 1, run `38871226842` on `8ffb61d`, failed closed with no completion
manifest. Its partial results are preserved at
`149da2f8d5e5fc796fcb6060cc0ce8b9b4200df5` on `hourly-a5-results`.
The plan covered 2,345 days and selected 690 distinct segments across time.

## Observed source behavior

For 1000BONKUSDT, at Unix timestamp `1730145600`, the hourly source has
open/high/low/close `0.020703`, base volume 0, quote volume 0 and trade count 0.
The next hour has an opening price of `0.020881`. The pinned four-hour candle's
opening price is `0.020881`: the first actual trade, not the earlier no-trade
hour's carried price. The three traded hours' quote volumes sum to the pinned
four-hour volume within its export precision.

Source files checked directly:

- Pinned `h4/1000BONK.csv.gz` at archive `4828a2d`, SHA-256
  `5c1aac7e5e959dc45520b2ebdc729f51c0c5b7cde483bb1281ec89ecd0b863eb`.
- Binance public monthly `1000BONKUSDT-1h-2024-10.zip`, SHA-256
  `4ad9f056ca013d3c6b53644a0c7ead82c4639f6cf231e3eb2c3be702aa3bea29`.

## Correction and limits

For a complete group of four observed hours, derive OHLC only from hours with
actual trading activity; sum volume across all four. A zero-quote-volume hour
must also have zero base volume and zero trades, otherwise parsing rejects it
as ambiguous. Retain zero-trade hours unchanged in the dataset and coverage.
Missing hours remain missing, not zero-trade observations.

Price comparison still uses relative tolerance 1e-8 with no absolute allowance.
Any remaining disagreement fails closed and now reports the segment, field and
both values. Regression tests cover leading and trailing no-trade hours,
stale prices outside the traded price range, inconsistent activity fields and
a true traded-price mismatch. The completion manifest binds this note's hash.

The hourly replay adapter must treat no-trade hours explicitly when deciding
whether an entry or exit can be executed; collecting them does not imply they
are executable prices.
