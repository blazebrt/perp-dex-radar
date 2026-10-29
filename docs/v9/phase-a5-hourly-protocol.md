# A5 hourly archive protocol

Fixed before collecting hourly prices or running the seven hourly definitions.
This study is diagnostic. It cannot promote a strategy or alter production.

## Universe known at each decision

- Use the complete research universe, including delisted and relisted segments,
  from four-hour archive commit `4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7`.
  Preserve its segment identities and exclusions. Do not use current listings,
  archive-end volume, future returns, or the selected subset's performance.
- At each UTC midnight, rank segments by mean daily quote volume over the seven
  preceding complete UTC days. Require all 42 observed four-hour bars, at least
  30 calendar days since that segment's first bar, and at least $5M mean daily
  volume. Missing bars make that segment ineligible for this day's ranking;
  do not fill their volume. Zero volume is observed zero, not missing.
- Retain at most 150 segments. Break equal-volume ties by ascending segment ID.
  Freeze membership for the following UTC day. A candle opening at the cutoff
  cannot affect that day's membership. Entries still require the hourly
  simulator's ordinary eligibility checks; ranking never overrides them.
- Begin after the archive's 120-day warm-up, rounded up to UTC midnight, and
  stop at the pinned archive's exclusive end. Keep all days, including empty
  selections. The plan records eligibility counts and each selected volume.
- Fetch the union of ever-selected segments, plus BTC for the BTC_LEAD indicator.
  BTC's presence as a feature input does not grant trade eligibility. Fetch full
  segment history through the pinned end, so rolling features and exits are not
  truncated when a segment leaves the top 150. Keep relistings separate.

## Hourly acquisition and validation

- Source only Binance USD-M public monthly 1h kline archives. Pin the exact
  object keys and hashes, and retain the original four-hour funding files.
  Funding observations are not replaced with assumed rates.
- The source plan, every source four-hour file, the universe, protocol, collector,
  and each downloaded object are bound by SHA-256. Use the existing archive
  network helpers without editing evidence-bound files.
- Reject failed downloads, invalid/duplicate timestamps, nonfinite or invalid
  OHLC/volume, and ambiguous segment mapping. Record hourly coverage explicitly.
  Do not declare the dataset complete if required source months are missing.
- Preserve the original segment window: first four-hour open through final
  four-hour close, exclusive. Bars outside it are not assigned to that segment.
- Reconcile every complete group of four hourly candles against the pinned
  four-hour OHLC, quote volume and taker-buy quote volume. Allow only export
  rounding (relative tolerance 1e-8, no absolute price allowance); disagreement aborts collection.
  Count groups with missing hours separately. Gaps remain explicit and require
  conservative handling in the subsequent replay adapter, never silent fills.
- Publish a completion manifest only after all requested data validates. Failed
  attempts retain diagnostics and never become completed evidence. Research data
  goes to a separate results branch, never production or the existing archive.

## Subsequent replay and family assembly

A5 collection is not A5 strategy qualification. Before the hourly replay, commit
its execution adapter and synthetic tests for timestamps, funding, gaps, top-150
membership, signal timing and exits. Preserve the seven existing definitions and
parameters. Record all results, including failures, without outcome-driven tuning.

A4.4 must specify how the hourly subset joins the 192 previously replayed trials.
The top-150 hourly universe differs from A4's broad four-hour universe: a complete
column count alone is not proof of a homogeneous experiment. Label this scope
difference explicitly; do not silently replace previous columns or call a mixed
universe family a common-universe replay. Unknown historical trials remain unknown.

## Acceptance steps

1. A5.1: causal schedule and synthetic tests committed before any hourly fetch.
2. A5.2: hourly collector, coverage validation and completed pinned dataset.
3. A5.3: seven hourly definitions replayed under a committed adapter and protocol,
   independently checked and recorded. A5 stays open until this step completes.
