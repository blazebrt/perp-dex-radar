# D4 public premium archive: fixed-sample source assessment

On 2026-11-16, seven public requests succeeded: one directory page and three predetermined daily ZIP/checksum pairs. The samples were BTCUSDT 2020-01-01, BTCUSDT 2026-09-01 and BLZUSDT 2022-01-01. The local plan was written before acquisition; it was not independently timestamped or committed before acquisition. This is source-format assessment, not preregistered outcome research.

All response bodies are retained exactly as base64 in `research/v9/premium_source_assessment/responses.json`, with request/completion times, lengths and SHA-256 bindings. Each ZIP matched its accompanying checksum and expected filename. All three parsed through the existing premium importer without changes: six closed four-hour bars per sample, 18 total, with no within-day missing bars. No returns, strategy selection, profitability or predictive statistics were calculated. Parsing nevertheless exposes real premium observations; future preregistration must disclose these samples.

The directory response contains 1,000 prefixes and **IsTruncated=true**. It is only the first page, not a complete symbol population or coverage survey. No historical completeness, delisted-population completeness, symbol identity, historical publication latency or original-vintage guarantee follows. BLZUSDT is merely the fixed second symbol, not a verified delisting example. A matching mutable upstream checksum is integrity evidence, not an independent authenticated signature. Captures establish present retrieval, not historical availability.

The retained bundle can be checked offline by `tests/test_v9_premium_source_assessment.py`. Verification checks every response binding, fixed URLs, sidecar bindings, archive parsing and full sample-day grids. No network is used by the test.

D4 remains open: acquire and reconcile the intended complete historical population; accept identity, coverage and availability limits; commit hypotheses, lags and costs before outcome testing; implement the runner; obtain authorization and independently reconcile one recorded study. No strategy or trade authority is granted. No production changes occurred.
