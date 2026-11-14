# Analyzer context and retained paper ledger

## F3: currently collected source coverage

The Analyzer now exposes all asset fields already collected (mark/oracle, venue maximum leverage, funding, volume/change, premium, OI/cap state, Gate positioning/OI/liquidations), all source response/fetch times, retained observation times, and broader market context separately. Stablecoin supply/change is included. Binance/Bybit predicted funding is attributed to the Hyperliquid feed, not described as an independent venue observation. Unknown cap state is no longer rendered as not-at-cap; missing Gate values remain unavailable rather than zero.

A missing asset row no longer asserts that a coin is unlisted. It says only that the snapshot has no asset-level observation. Missing/malformed context remains explicitly unavailable. Upstream observation time is unknown where not retained; snapshot freshness is not evidence that every upstream value is fresh. Macro context is labelled not coin-specific. Source labels and values are escaped.

F3's interface for the currently collected sources is complete in draft PR #30. This does not claim that all 102 surveyed services or the deferred C1/C2 feeds are integrated. New sources still require collection and provenance work.

## F4: page implemented; complete historical attribution remains open

Portfolio links to `performance.html`. The page displays the decision's current FULL/PROBATION sides, their available registered expectations and forward-test diagnostics, then every retained open/closed journal record with strategy/state filters. It loads the full retained journal rather than quant.json's last-150 view. Before displaying anything, it verifies exact byte lengths and SHA-256 hashes of both decision and journal against one audit snapshot. Missing, mismatched, malformed or ambiguous bindings fail closed with a reload message. The browser must support Web Crypto; inability to verify means no ledger is displayed.

Current tiers are never assigned retrospectively to old entries. Entry-time tier is explicitly unrecorded. The journal prunes old closed records (configured retention is 400), so the page explicitly denies complete lifetime coverage. Reported journal R is not described as qualified net performance; unknown R is unavailable, and open positions have no realized R in this page. The decision's forward mean may contain unqualified paper outcomes; it is labelled as the registered diagnostic. Archive confidence intervals are not relabelled as live prediction intervals. Stale snapshots remain labelled historical, never current trade authority.

The usable page is implemented, but F4's stronger requirement of every tier's complete historical live trade record remains unchecked. Closure needs immutable entry-time authority attribution and durable full-history capture. Those cannot be reconstructed honestly from current policy or a pruned journal. No historic journal record or evidence-bound engine has been rewritten.

## Validation and publication scope

New tests exercise missing-versus-unlisted behavior, source/observation distinctions, null/zero handling, escaped labels, unchanged inputs, exact hash bindings, mixed-scan rejection, duplicate identities/references, current-versus-entry tier separation, filtering, unknown returns and publication wiring. Existing audit-loading tests prove Today still does not request the large audit. The deterministic output comparison found exactly four changed/added files: desk.js, portfolio.html, performance.html and performance.js. All numerical JSON outputs, engine decisions and audit-file inventory stayed unchanged. The new golden was accepted only after this explicit comparison; all four file changes are pinned in the delta manifest. All 1,402 Linux regression tests passed in 358.287 seconds after updating the obsolete missing-coin assertion to enforce the corrected wording. Differential parity passed with zero unexpected differences; the original base and current head each reproduce their pinned golden outputs. The retained differential report is `docs/v9/product-delta-report.json`.

A local synthetic preview was prepared outside the repository, but the available in-app browser could not connect to the local server. Interactive visual inspection is therefore not claimed. Runtime rendering, loader and publication checks provide the automated UI coverage. No merge, deployment, market study, new trade authority or evidence-history append occurred.

## Durable capture follow-up (2026-11-14)

The append-only observation recorder and archive-content verifier are implemented and wired into Scan in draft PR #30; see `paper-observation-history.md`. They preserve record versions after later journal pruning without inferring entry tiers. Production activation/verification and historical archive browsing remain outstanding. The original historical attribution and pre-capture completeness limitations remain unchanged.
