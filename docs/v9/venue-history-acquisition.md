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

## Completed capture and assessment (2026-11-25)

The capture made on 2026-11-24 is retained in research/v9/a7_source_assessment/: manifest.json binds each request and available raw response; metadata.json is the exact instrument response; coverage.json is the offline verifier output; assessment.json aggregates coverage and reproduces failure reasons. Every planned request was attempted once. The public endpoint was reachable locally, so no new hosted workflow or account was needed.

| Measure | Result |
|---|---:|
| Captured instruments / flagged delisted | 235 / 56 |
| Planned / attempted requests | 470 / 470 |
| Validated / failed responses | 462 / 8 |
| Validated 4h / daily candles | 923,327 / 223,276 |
| Validated 4h responses at 5,000-bar cap | 14 |
| Complete requested 4h / daily windows | 0 / 36 |

The fixed requested range was 2022-01-01 00:00 UTC to exclusive 2026-11-24 00:00 UTC. Seven responses fail OHLC geometry (135 rows across HPOS, RLB, UNIBOT, OX and PANDORA); DASH 4h failed with URLError and has no retained response. Raw failures remain unchanged. No retry, repair or selection of successful rows into an accepted dataset occurred. Zero internal gaps in successful responses does not cover absent prefixes/suffixes, failed instruments or missing historical membership.

The full raw capture (158,958,647 bytes) and its verified ZIP (33,608,428 bytes) remain in the task workspace under outputs/a7-capture-2026-11-24 and outputs/a7-capture-2026-11-24.zip. The archive hash is recorded in assessment.json. Raw candles are not uploaded to this PR; reports and hashes alone do not establish remote raw-data availability.

The source decision is NOT ACCEPTED. Collection/assessment is complete, while historical identity/membership, funding/cost evidence, failed responses, durable research input retention and preregistration still prevent a qualified cross-venue study. No outcome computation or activation follows from this capture.
