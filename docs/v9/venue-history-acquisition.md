# A7 venue-history acquisition

Implemented 2026-11-24 on draft PR #30. This is source acquisition and verification, not an accepted dataset or strategy study.

The [official Hyperliquid info endpoint documentation](https://hyperliquid.gitbook.io/Hyperliquid-docs/for-developers/api/info-endpoint) states that only the most recent 5,000 candles are available. At four hours this is approximately 833 days, not an unlimited paginated history. Earlier probe counts, delisted flags and observed daily starting dates cannot establish complete historical membership or listing inception. Current metadata itself can omit previously removed instruments. No historical funding or execution evidence is supplied by candle OHLCV.

## Acquisition

Run `python -m tools.v9.venue_candles acquire --out <new-directory> --start-ms <UTC-day-boundary> --end-ms <exclusive-UTC-day-boundary>` in an environment with access to the public endpoint. Both timestamps are milliseconds. The end must already have passed. No credentials or paid account are needed. The directory must not exist. No workflow activation or production wiring is included.

The raw metadata response defines the captured population, in original order. Every instrument, including those marked delisted, receives one request for each of 4h and 1d. Filenames use numeric ordinals, never instrument names. Exact request parameters and raw responses are retained with byte counts and SHA-256 hashes. Responses are not rewritten or normalized. A six-second interval bounds requests; there is no automatic retry, lookback widening or fictional pagination. Acquisition timing is not atomic across instruments.

Each request is recorded as STARTED before access. Malformed/failed responses are recorded as FAILED; response bytes are retained when available, and remaining instruments are attempted. Cancellation records INTERRUPTED and preserves the completed prefix, in-flight state and unattempted suffix. A killed host may leave STARTED rather than INTERRUPTED. The writer flushes files and atomically replaces its own progress manifest; this is not a hosted durable-storage guarantee.

Limits are 2,000 metadata instruments, 8 MiB per response and 512 MiB total raw responses. Exceeding the total budget stops acquisition; it does not silently drop instruments or launch a second attempt. The response crossing that cap is not retained and remains explicitly failed. A new attempt needs a new directory and separate provenance. Completed collection does not imply complete history.

## Offline verification

Run `python -m tools.v9.venue_candles verify --capture <directory>`. The verifier checks the retained metadata, deterministic request inventory, exact request windows, file paths, lengths and hashes. Every successful response is parsed again; recomputed coverage must match the collector's report. Missing/corrupt objects fail verification. Partial captures return INCOMPLETE_CAPTURE and disclose failed/interrupted and unattempted requests.

Candles must match the requested symbol and interval, appear in strictly increasing time order, fit the closed requested window and carry exact grid-aligned opening/closing timestamps. Decimal strings must be finite; positive OHLC geometry, nonnegative volume and integer nonnegative trade counts are required. Zero volume is preserved. Duplicate JSON keys, duplicate bars and unordered rows are refused.

Reports distinguish missing bars over the requested window from internal gaps between returned bars. An empty successful response reports all requested bars unavailable. A response at 5,000 bars is explicitly flagged; fewer rows do not prove completeness. Dataset acceptance, historical membership/listing-time verification and outcome authority are always false. Historical liquidity eligibility, symbol reuse, cross-venue identity, funding/costs and study preregistration require separate review before a cross-venue study.

Validation uses synthetic responses and local files only. No live acquisition, market outcome, promotion or evidence-history entry is claimed by these tests.
