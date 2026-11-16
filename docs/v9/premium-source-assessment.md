# D4 public premium archive: fixed-sample source assessment

On 2026-11-16, seven public requests succeeded: one directory page and three predetermined daily ZIP/checksum pairs. The samples were BTCUSDT 2020-01-01, BTCUSDT 2026-09-01 and BLZUSDT 2022-01-01. The local plan was written before acquisition; it was not independently timestamped or committed before acquisition. This is source-format assessment, not preregistered outcome research.

All response bodies are retained exactly as base64 in `research/v9/premium_source_assessment/responses.json`, with request/completion times, lengths and SHA-256 bindings. Each ZIP matched its accompanying checksum and expected filename. All three parsed through the existing premium importer without changes: six closed four-hour bars per sample, 18 total, with no within-day missing bars. No returns, strategy selection, profitability or predictive statistics were calculated. Parsing nevertheless exposes real premium observations; future preregistration must disclose these samples.

The directory response contains 1,000 prefixes and **IsTruncated=true**. It is only the first page, not a complete symbol population or coverage survey. No historical completeness, delisted-population completeness, symbol identity, historical publication latency or original-vintage guarantee follows. BLZUSDT is merely the fixed second symbol, not a verified delisting example. A matching mutable upstream checksum is integrity evidence, not an independent authenticated signature. Captures establish present retrieval, not historical availability.

The retained bundle can be checked offline by `tests/test_v9_premium_source_assessment.py`. Verification checks every response binding, fixed URLs, sidecar bindings, archive parsing and full sample-day grids. No network is used by the test.

D4 remains open: acquire and reconcile the intended complete historical population; accept identity, coverage and availability limits; commit hypotheses, lags and costs before outcome testing; implement the runner; obtain authorization and independently reconcile one recorded study. No strategy or trade authority is granted. No production changes occurred.

## Directory pagination completed on 2026-11-16

`research/v9/premium_population_assessment/` retains the original first page, the continuation response, acquisition plan and reproducible report. The continuation request used the first response's exact NextMarker; the second response explicitly reports IsTruncated=false. The two pages contain 1,000 and 11 unique prefixes, respectively: 1,011 observed source symbols. This completes the observed marker chain, not an atomic snapshot: the page capture times differ by approximately 19 minutes, and intervening upstream changes cannot be excluded.

Five prefixes use non-ASCII symbols unsupported by the current premium importer. The report preserves their exact names in both the full symbol inventory and `importer_unsupported_symbols`; they are not silently excluded or normalized into other instruments. Importer restrictions remain unchanged pending explicit identity/path-contract acceptance.

`tools/v9/premium_inventory.py` verifies the retained response hashes, lengths, endpoint/query identity, marker continuity, strict XML fields, ordered distinct prefixes and terminal-page requirement. Missing pages, repeated/reordered pages, duplicate query/contract fields, changed bytes and unexpected source objects fail verification. Tests also reproduce the full retained report offline. No archive ZIPs or premium values were fetched in this pagination step.

Directory presence does not establish a perpetual instrument's historical eligibility, identity, delisting status, 4h availability, complete daily bars or original publication time. The report therefore keeps historical population acceptance, coverage verification and study/trade authority false. Full per-instrument/time coverage reconciliation and an authorized preregistered study remain outstanding.
