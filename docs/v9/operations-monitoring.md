# Source health monitoring and audit loading

## G1: all active v9 market sources

`v9/source_health.py` reads the collector's document without modifying it. The Scan workflow runs it in a separate `always()` step after collection, including when collection fails, and passes the collector step outcome. An old but still recent file cannot conceal a failed collector. The monitor emits GitHub Actions warning annotations, an all-source job summary and a JSON report retained for 14 days. Its nonzero status on alerts does not prevent the rest of Scan from publishing. No external messages are sent.

The registry covers all 16 currently active market-context sources. Missing or unregistered sources, unavailable responses, invalid/future fetch timestamps, fetch age over two hours, document expiration and malformed/ambiguous JSON alert. An absent optional CoinGecko key is explicitly NOT_CONFIGURED, not a healthy response. Gate coverage checks requested versus answered counts, retained asset coverage and every retained asset's observation time; one successful answer cannot hide a partial batch.

Fresh downloads do not establish fresh observations. Retained upstream timestamps are checked separately for Deribit DVOL (two hours), Fear & Greed/stablecoin supply (two days), CoinGecko global and Bitfinex margin (two hours), Gate assets (two hours), and ETF observations (seven calendar days, allowing weekends/holidays). Future timestamps beyond five minutes alert. These are operational budgets, not trading or research thresholds. Sources lacking independently retained upstream timestamps are labelled FETCH_ONLY; the monitor does not claim their market observations are fresh or correct. The job summary states this limitation.

Raw exception messages and API payloads are not copied into alerts. Source names are escaped for workflow annotations and summaries. Tests cover every source's error/omission, stale and future observations despite fresh fetches, age boundaries, partial coverage, missing/malformed files, duplicate JSON keys, collector failure behind a recent file, optional keys, and hostile source labels. The existing market document, trading decisions and pages are unchanged; no parity golden was regenerated.

Implementation and workflow wiring are complete in draft PR #30. Production activation awaits merge authorization and a post-merge Scan check. This is monitoring of the active v9 market layer, not every surveyed but unused service, an independent price-quality audit, or an external watchdog for a workflow that never starts.

## G2: verified existing compressed, page-specific loading

No new page behavior is claimed here. The existing snapshot producer writes compact JSON and deterministic gzip. Its existing regression verifies byte reproducibility and decompressed equality. `DESK.loadAudit()` requests gzip when decompression is supported and falls back to JSON if unavailable/corrupt or unsupported. New runtime tests exercise these paths with actual compressed bytes.

The Today page requests decision and market context only; it never loads the audit. Portfolio renders the decision summary before awaiting audit detail. New page-script runtime checks use a deliberately unresolved audit request to prove that order. The full audit remains available for inspection; no records are discarded to reduce size. G2's existing implementation is now explicitly verified and recorded complete.

## Remaining delivery plan

There are 12 unchecked major roadmap items: 10 core plus two optional (after B9 follow-up dispositions and Emerging-authority correction). This is a count of major acceptance items, not estimated days or remaining coding tasks.

| Items | What actually remains |
|---|---|
| A4, A5, D3 | Complete-return evidence is unavailable under the frozen hourly definitions/coverage. No zero substitution, retroactive definition edits or invented funding can close them. |
| A6 | Full-workload feasibility, bounded hosted resources/publication, independent qualification, and the one registered outcome run; small benchmarks are not acceptance. |
| A7, D4, D6 | Source/coverage review, immutable preregistration, implementation and independently verified studies. Archive first observation must not be presented as verified listing inception. D4 has an offline source-bound premium-index importer and three verified real ZIP/checksum samples (18 bars); the directory chain reaches its terminal page with 1,011 observed prefixes and five explicitly unsupported symbols. The traversal is not atomic and historical coverage remains unverified. See `premium-source-assessment.md`. D6 source-contract review and an offline content-bound observation checker are implemented; verified event/identity coverage and the preregistered study remain. |
| D5, E3 | Preregistered regime research and confirmed evidence before any regime gating. |
| F4 | The retained-ledger page is implemented; durable observation capture is implemented but inactive; archive browsing is implemented; entry-time attribution and production qualification remain. F3 current-source context is complete. See `product-context-ledger.md`. |
| C4, D1b (optional) | Owner-provided optional credentials; optional prospective registration/collection respectively. |

F3 and the retained F4 page are now implemented. F4 closure needs prospective entry attribution/full-history retention; do not infer it from current policy. Do not resume serial small A6 benchmarks as the default next task. An A6 continuation must have a concrete feasibility decision or implementation target. Missing scientific evidence remains visible separately from completed software. No merge, deployment, new strategy promotion or market study was performed in this change.

E1 ranking and E2 tier/covariance sizing plus whole-book reduction-only targets are implemented in the draft. E2 includes modeled turnover costs, post-cost caps and Phase 10 verification, with a read-only Portfolio display. Activation awaits merge review; no execution-ready order list is claimed. See `whole-book-balancing.md`.

B9 follow-ups are now dispositioned in `b9-followup-dispositions.md`. The draft Emerging-authority correction removes unsupported signal evidence without changing directional decisions or research authority.
