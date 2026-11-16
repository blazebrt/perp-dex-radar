# D6 listing-observation evidence contract

Implemented 2026-11-16 in draft PR #30. This is offline evidence preparation, not a listing-effect study, event-date certification, live collector or production activation.

## Corrected research premise

An archive segment's first candle is its first retained observation. Missing history, truncated responses, relisting, changed symbols and source coverage can all move that boundary. It is not independently verified listing inception. The D6 roadmap now requires event-time and identity evidence before a listing-effect study can proceed. Existing A6 archive-age definitions and registered studies are untouched.

Primary source review on 2026-11-16:

- [Binance USD-M exchange information](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information) describes current symbol information and includes onboardDate, status, contractType, baseAsset and quoteAsset. We retain onboardDate as exchange-reported metadata, with its availability at the supplied capture time; it is not independently authenticated historical inception. Future values remain scheduled metadata and never imply that trading began.
- [Upbit Korea pair inventory](https://docs.upbit.com/kr/reference/list-trading-pairs) returns supported trading pairs from api.upbit.com. This inventory supplies observation membership, not verified historical listing events. Global/regional Upbit hosts are deliberately excluded from this Korean-market adapter. Market presence is not treated as proof that a trade can execute.

These documents establish the adapter contract, not actual response completeness or historical coverage. No market payload or outcome dataset was fetched for this implementation.

## Input and output

`tools/v9/listing_observations.py` reads a supplied JSON manifest and raw response files. It performs no network requests, credentials access, orders or publication. Use:

```sh
python -m tools.v9.listing_observations --manifest manifest.json --root captures --as-of 1794787200 --out reports/listing-audit.json
```

The manifest schema is `v9.listing-observation-input/1`. Its nonempty `captures` array contains one object per capture with all these fields:

| Field | Contract |
|---|---|
| source | BINANCE_USDM_EXCHANGE_INFO or UPBIT_KR_MARKETS |
| retrieved_at | Positive integer UTC seconds, no later than the explicit audit cutoff |
| request_url | Exact configured public endpoint; Upbit also accepts its is_details=true URL |
| http_status | Integer 200; caller-supplied metadata, not independently authenticated |
| path | Unique normalized relative path under the supplied source root |
| bytes | Exact raw byte length |
| sha256 | Lowercase SHA-256 of those exact raw bytes |

Each source has an independent ordered capture series. Source/time duplicates are rejected. Markets are keyed by source and venue market code, retaining separate quote markets and contract types; no ticker-based cross-venue asset matching occurs. Baseline members, newly observed members, reobserved members, response absences and metadata changes are recorded. Reappearance retains the first observed time in the supplied series rather than creating a second alleged new listing. The gap between observations is recorded; it is not an interval proving a real listing event. Metadata comparison includes the scheduled-versus-reported classification as time passes.

Every alleged event has null listing_time/delisting_time. Identity is unverified. The report always states zero verified listing events, historical coverage UNVERIFIED, listing_study_eligible=false and trade_authorization=false. Its CONTENT_BINDINGS_VERIFIED status means only that supplied file hashes, sizes and schemas reconcile. It does not authenticate the endpoint, capture timestamp or upstream completeness. It binds the supplied manifest by a canonical JSON hash; changing manifest order changes that binding even though ordered capture analysis is deterministic.

Missing/invalid onboardDate values remain unavailable, including booleans, zero and negative times. Future valid metadata is retained as scheduled, not silently dropped or asserted active. Existing snapshots cannot establish when the metadata was originally published, so availability is never backdated to onboardDate.

## Failure and resource behavior

Duplicate JSON keys, nonfinite values including numeric overflow, malformed response envelopes, empty inventories, duplicate market identities, future captures, changed source bytes, unsafe paths and escaping symlinks fail the whole audit. Empty responses are not mass-delisting evidence. Supported limits are 16 MiB per file, 128 MiB aggregate response bytes, 1,000 captures and 20,000 rows per capture. Larger jobs require separately designed batching; there is no truncation. Raw source files are never modified. Reports must be outside the source directory and distinct from the manifest, and exclusive creation refuses to overwrite an existing report. Consumers must parse the complete report; an interrupted filesystem write is not a valid completed audit.

## D6 acceptance still outstanding

Before outcome research: acquire and retain source material with independently reviewable retrieval provenance, reconcile instrument identity and symbol reuse, verify event times from suitable official evidence, account for corrections/cancellations/delistings and missing history, then preregister the event definition, eligible population, exclusions, windows, costs, controls and multiple-testing treatment. Only afterward may an authorized study run once and be recorded/reconciled. A present-day market list is not a survivorship-free historical population.

The observation checker and source-contract review are complete implementation subtasks. D6 remains open. No existing signal, portfolio decision, published page, research definition, evidence record or legacy parity golden changes.

## Validation

All 1,454 Linux regression tests passed in 371.223 seconds, including seven synthetic cases for the observation checker. No market outcome or live-source collection was run.
