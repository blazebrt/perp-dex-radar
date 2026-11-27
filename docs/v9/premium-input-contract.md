# D4 premium-index input contract

Implemented 2026-11-16 in draft PR #30. This is offline data preparation, not a strategy definition, accepted dataset, outcome study or production collector.

## Source interpretation

The [official premium-index endpoint](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Premium-Index-Kline-Data) defines separate premium-index OHLC bars, including negative observations. Its twelve-field response uses open/close times and premium OHLC; the other fields are marked ignored. They must not become traded volume, executable prices or observed funding. The importer therefore emits named premium fields only, retaining decimal strings rather than rounding through binary floats.

Binance's [public-data instructions](https://github.com/binance/binance-public-data#checksum) describe SHA-256 sidecar verification and note that archived files may later be corrected. A historical candle close therefore does not establish when a particular archived version became available. This implementation checks supplied raw-file bindings; it does not fetch or authenticate the source or its sidecar. Real acquisition must retain and independently verify that provenance before dataset acceptance. Only documentation and synthetic examples were used here; no market archive was downloaded or studied.

## Supported input

`tools/v9/premium_inputs.py` accepts daily USD-M `premiumIndexKlines` ZIP files at the 4h interval. It supports ASCII uppercase/digit/underscore symbol codes and rejects unsupported layouts rather than guessing. Monthly files, other intervals, other products and other header variants need separately reviewed adapters.

```sh
python -m tools.v9.premium_inputs --manifest manifest.json --root captures --as-of 1794787200 --out reports/premium-inputs.json
```

The manifest schema is `v9.premium-input/1` with:

- `segments`: a nonempty array of objects containing unique `segment_id`, `symbol`, `start` and `end`. Bounds are UTC seconds on the 4h grid, end-exclusive, no later than the explicit audit cutoff. Same-symbol segments must not overlap. These caller-supplied intervals are not certified instrument identities or a survivorship-free population.
- `files`: an array of objects containing `symbol`, `day` (YYYY-MM-DD), `source_key`, `path`, `bytes`, `sha256` and `retrieved_at` (UTC seconds). The exact supported source-key layout is `data/futures/um/daily/premiumIndexKlines/SYMBOL/4h/SYMBOL-4h-YYYY-MM-DD.zip`. Paths stay within the capture root. The capture must not precede any retained bar's closure or exceed the audit cutoff.

Each ZIP must contain exactly one ordinary, unencrypted file named `SYMBOL-4h-YYYY-MM-DD.csv`. Rows have twelve columns with millisecond open/close timestamps. The optional supported header is `open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore`; those volume/count labels do not override the premium endpoint's ignored-field semantics. Unknown headers fail. Every open time must fall on that day's 4h grid; close time must be the final millisecond of that bar. Nonfinite or malformed premium values, impossible OHLC ranges, duplicate bars and wrong units fail the entire import. Zero and negative premium values are valid observations.

## Coverage, availability and meaning

Every requested segment retains its own ordered rows, expected/observed/missing counts and compressed missing intervals. Missing files or bars never become zero and are never interpolated. A file's bars outside the requested intervals are counted explicitly. Separate archive segments are not joined across a gap. Same-source-day duplicates and overlapping segment definitions fail rather than selecting a preferred revision.

Each row carries `bar_open`, `closed_at`, `captured_at`, a source path and `historical_publication_time: null`. `known_at` requires both closure and capture at or before the requested decision time. This is conservative availability relative to supplied capture metadata, not independent timestamp authentication or a freshness guarantee. It does not infer old publication from the filename, a one-day lag or candle close. A retrospective study using a modeled lag needs its own preregistered assumption and disclosure; this importer does not silently supply one.

Reports state CONTENT_BINDINGS_VERIFIED only when files were supplied and reconciled; an empty file inventory reports NO_SOURCE_FILES with the entire grid missing. Both retain study_eligible=false and trade_authorization=false. Complete requested-grid coverage alone cannot establish source authenticity, historical population completeness, funding availability or a trading edge. No price, funding, P&L or strategy signal is computed.

## Limits and immutability

Limits are 4 MiB compressed and expanded per ZIP, 128 MiB aggregate compressed input, 10,000 files, 20,000 segments and 500,000 requested bar cells. Larger collections require explicit reviewed batching. No truncation occurs. Empty/malformed archives, unsafe paths, escaping symlinks, wrong source labels, changed bytes, duplicate JSON keys or invalid source metadata fail. Output must be outside the capture root and distinct from the manifest; exclusive creation refuses to overwrite an earlier report. Source files are read only. An interrupted report write must not be treated as a complete JSON audit.

## Remaining D4 acceptance

Acquire and retain the real raw archives and official checksums; pin the eligible population and file versions; audit coverage, revisions and publication availability; freeze hypotheses, lag, selection, windows, costs and multiple-testing rules before outcomes are examined; implement and independently verify the outcome runner; then obtain authorization for the one recorded study. Existing research definitions, registrations and evidence records remain unchanged. The importer is complete software preparation; D4 research remains open.

## Validation

All 1,462 Linux regression tests passed in 366.149 seconds, including eight synthetic importer cases. No market dataset or outcome study was run.
