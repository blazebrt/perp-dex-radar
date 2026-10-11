# Phase 7: full-universe discovery and the hierarchical scan

> **Discovery sees everything. Execution remains selective.**

Before Phase 7 the system *recorded* every coin (every asset has a ledger record), but it only *looked at* the coins
that survived its gates: the radar's published table shows the 1h-charted verified-crypto coins, and identity,
liquidity, history and the stage-2 shortlist decided what the rest of the system could see. Phase 7 separates the two
questions. Every active perpetual of every venue whose market list loaded gets one **discovery record** per asset,
whatever its identity, liquidity or history. What an engine may *do* with an asset is unchanged: the same identity gate,
the same $1M execution-liquidity gate, the same history gates, the same top 40 + 16 deep-research shortlist, the same
strategies, thresholds, stops, targets, sizing and output Top-N.

Phase 7 is **audit-only**. No engine reads anything it adds; every legacy output is byte-identical to the base (the
differential parity manifest allows no delta at all); `v8.identity/4` and its config hash are unchanged.

## Three levels, one record per asset

| Level | What | Cost |
|---|---|---|
| 0 Registry | every contract the eight market lists returned (`v8.registry`, unchanged) | the market-list requests the scan already makes |
| 1 Light discovery | every asset with an active perpetual on a healthy venue: identity, exposures, contracts, venues, price and its cross-venue dispersion, volume, execution liquidity, open interest, funding, first seen, listing age, wrapper and economic evidence, exposure-check state, research flags, lane, Decision Trace | **zero extra requests**: built from the market lists already fetched and the ledgers already written |
| 2 Deep research | the radar's bounded stage 2: the stage-1 top 40 that pass execution liquidity, plus 16 extras (unchanged) | the radar's own 15m requests (unchanged) |

Where it is built:

* `v8.discovery.scan_part()` runs inside the scanner process (through `v8.audit_radar.audit`, after the scan's own
  outputs are written) and keeps what only that process knows: each coin record's reference price, volumes and
  execution liquidity, and the radar's stage-1 metrics and stage-2 membership. It writes `data/v8/parts/discovery.json`.
* `v8.discovery.build()` runs in the snapshot step and joins that part with the registry (with first-seen history) and
  every engine's ledger into **`data/v8/discovery.json`** (schema `v8.discovery/1`) and the snapshot's `discovery`
  section. A missing or failed scan part still gives every asset a record (light values from the registry only; the
  problem is named).

## The denominator

Every **active perpetual** (registry type `perp`, active) of a venue whose market list loaded is in exactly one discovery
record. Counted apart, by reason, never silently dropped:

| Outside the denominator | Why |
|---|---|
| active perps on an unavailable venue | the market list did not load: the venue is `VENUE_UNAVAILABLE`, health `DATA_DEGRADED`, reason `VENUE_MARKET_LIST_UNAVAILABLE` (`accounting.active_perps_on_unavailable_venues`) |
| active perps the adapters skip as unusable | an empty symbol, a Hyperliquid builder-deployed market (`accounting.active_perps_unsupported`, by contract state) |

Venue states: `OK` (has active perps, all in discovery), `VENUE_UNAVAILABLE`, `NO_MARKETS` (the list loaded and was
empty), `ZERO_ACTIVE_MARKETS` (the list loaded, nothing in it is an active perpetual).

Registry assets without an active perpetual on a healthy venue are listed in `registry_only` with their reason
(`NO_ACTIVE_PERP_CONTRACT`, `VENUE_ADAPTER_FAILED`). `canonical_assets = discovery_assets + registry_only_assets`.

Coverage: `coverage_state` is `FULL` (every venue loaded), `DEGRADED` (a venue is unavailable; its markets are named
outside the denominator) or `FALLBACK` (no market list loaded; the built-in coin list was used).
Two qualifications, apart:

| Field | True only when |
|---|---|
| `available_venue_discovery_qualified` | not the fallback universe, discovery `unaccounted` is 0 and the accounting has no problem: every active perpetual returned by every supported venue whose market list loaded is in discovery |
| `full_discovery_qualified` | `available_venue_discovery_qualified` **and** `venues_failed` is 0: every expected supported venue's market list loaded |

Complete accounting over the venues that answered does not prove full discovery while a supported venue is missing, so
a `DEGRADED` scan is never `full_discovery_qualified` (with edgeX unavailable: `DEGRADED`, available `true`, full
`false`); nothing is invented or carried over for the missing venue. The fallback universe is neither
(`fallback_universe: true`, both `false`, `FALLBACK`).

## The record (`data/v8/discovery.json` -> `assets[]`)

| Field | Meaning |
|---|---|
| `asset`, `name` | canonical ticker, venue name when one is published |
| `identity`, `identity_reason`, `identity_authority`, `identity_decision` | the `v8.identity/4` state and why (unchanged) |
| `exposures` | each price-coherent exposure: id, class, reason, anchor price, contract count, whether it is in the coin record |
| `contracts` | every active contract of the asset in the denominator, with its contract state |
| `venues`, `record_venues` | all venues with an active market; the venues of the coin record (its admitted exposure) |
| `price`, `price_basis` | the coin record's reference price (`COIN_REFERENCE`, anchored on its most traded venue), else the contracts' median (`CONTRACT_MEDIAN`), else `null` / `MISSING` |
| `cross_venue_price_dispersion` | (max - min) / median of the coin record's prices per coin; `null` with fewer than two prices |
| `best_volume`, `trade_volume`, `total_volume` | 24h volumes as the coin record holds them; `null` when nothing was reported (never 0) |
| `liquidity_state`, `liquidity_value` | `v8.liquidity`: `KNOWN` / `MISSING` / `NOT_ON_TRADE_DEX` and the value |
| `execution_liquidity` | `{state, observed_value, threshold, passes}` - its own field; it never controls visibility |
| `open_interest` | sum over the coin record's markets, venues reporting, basis `OBSERVED_SUM` / `PARTIAL_SUM` / `MISSING`; `oi_to_volume`: open interest over 24h volume on the same venues only (those reporting both), with their count |
| `funding` | median, min, max, spread of the venues' 8h-equivalent funding as each venue reports it; venues reporting |
| `first_seen`, `listing_age` | earliest first-seen of its active contracts; age `KNOWN` only when first seen after tracking started (`FIRST_SEEN_AFTER_TRACKING_START`), else `UNKNOWN` (`BEFORE_TRACKING_START`, `NO_HISTORY`) |
| `wrapper_evidence`, `economic_evidence`, `exposure_check_state` | the identity's two evidence paths (Phase 5) and whether its exposure checks ran cleanly (`OK`, `DEGRADED`, `NOT_APPLICABLE`) |
| `data_quality` | `HEALTHY`, or `DATA_DEGRADED` when a contract's values are missing or conflicted |
| `anomaly_flags`, `research_priority`, `priority_lane` | research flags, their points (authority `NONE`) and the lane |
| `discovery_stage`, `stage_path` | how far down the hierarchical scan the asset went |
| `deep_research_state` | selected or not, via `TOP_N` / `EXTRA`, completed, and the reason |
| `discovery_visible` | always `true`: every record is visible whatever its gates |
| `shared_execution_gates` | `{identity_ok, liquidity_ok, passes, reasons}`: only whether the asset passes the common gates every crypto engine applies first (crypto execution identity, known trade-DEX volume >= the legacy minimum). Passing them is **not** model eligibility and **not** a trade |
| `model_eligibility` | per engine (radar, quant, swing, day, smart), that engine's own final ledger record as written: `{disposition, code, stage, steps}`; an engine without a record for the asset is absent. Nothing is inferred; there is no global "executable" field |
| `final_disposition` | the radar's (or the universe's) final ledger record: engine, code, disposition, stage - the existing vocabulary |
| `decision_trace` | nine steps, each `[step, input, rule, result, effect]` (the rule texts are in `vocabulary.trace_rules`); the execution-gate step's result is `SHARED_GATES_PASSED` / `SHARED_GATES_BLOCKED` and its effect names each engine's ledger result |

Values are observed or `null`; a missing value is never written as 0. Floats are rounded deterministically; two builds
from the same inputs are byte-identical.

### Stages

`DISCOVERED` (in discovery without a coin record: fallback, or every venue's price dropped as a conflict) ->
`LIGHT_ONLY` (light record only: not verified crypto, or verified crypto without enough 1h candles) -> `CHARTED_1H`
(stage 1; not deep-researched) -> `DEEP_RESEARCH` (selected; the 15m deep dive could not run) -> `STRATEGY_EVALUATED`
(deep-researched, every active strategy evaluated, nothing published) -> `EXECUTION_BLOCKED` (a strategy fired, a
publishing gate blocked it) / `SURFACED` (radar pick) / `WATCHED` (radar watch list). The stage comes from the radar's
final ledger record; the scanner's own stage membership is cross-checked against it (a disagreement is a named
problem).

### Why an asset was not deep-researched

`IDENTITY_NOT_CRYPTO`, `INSUFFICIENT_1H_DATA`, `EXECUTION_LIQUIDITY_BELOW_MIN`, `EXECUTION_LIQUIDITY_UNKNOWN` (listed on
your trade DEXs, no volume reported), `NOT_ON_TRADE_DEX`, `DEEP_BUDGET_NOT_SELECTED` (passes liquidity, outside the top 40
and not an extra), `NO_COIN_RECORD`; deep-researched ones are `DEEP_COMPLETED` or `DEEP_HISTORY_INSUFFICIENT`.

## Research flags, lanes and research priority (no trade authority)

| Flag | Rule | Points |
|---|---|---|
| `NEW_LISTING` | first seen after tracking started, within 7 days | 3 |
| `FUNDING_EXTREME` | median funding >= 0.1% per 8h, either sign | 2 |
| `FUNDING_DISAGREEMENT` | venues' funding >= 0.05% per 8h apart | 1 |
| `PRICE_DISPERSION` | admitted markets >= 2% apart per coin | 2 |
| `SINGLE_VENUE` / `MULTI_VENUE` | one / two or more venues in the coin record | 0 / 1 |
| `OI_HIGH_RELATIVE_TO_VOLUME` | open interest >= 20x 24h volume on the same venues | 1 |
| `THIN_LIQUIDITY` | execution liquidity known and below $1M | 0 |
| `LIQUIDITY_MISSING` | listed on your trade DEXs, no volume reported | 0 |
| `IDENTITY_UNVERIFIED` | `UNVERIFIED` or `AMBIGUOUS` | 1 |
| `ECONOMIC_EXPOSURE_CONFLICT` | a ticker collision or conflicting contract evidence | 2 |
| `EXPOSURE_METADATA_DEGRADED` | an exposure check did not run cleanly | 1 |
| `STAGE1_EXTREME` | charted with a 24h move >= 15%, either direction | 2 |

The points add up to `research_priority.points`. They order research attention (the shadow queue, the lanes' lists)
and nothing else: they are not a forecast, not a quality score and carry no trade authority (`authority: NONE`).
Funding is compared as the venues report it, 8h-equivalent; venues settle on different intervals, so a disagreement is
an observation to check, not a finding. Open interest against volume is venue-dependent (in the census scan the
same-venue ratio has a median of about 3x, and 1-16x for the liquid majors), so the flag marks outliers only (20x); the
first Research run of this branch used 2x on mismatched venues and flagged 317 of 853 assets, which is why the ratio
now uses the same venues for both sides and the threshold was raised. A ratio relative to each asset's own history
needs the point-in-time universe (Phase 8).

Lanes: `NON_CRYPTO` (verified tradfi), `IDENTITY_RESEARCH` (unverified or ambiguous), and for verified crypto
`EMERGING` (new, or below execution liquidity: thin, missing, not on a trade DEX), `STRUCTURAL_ANOMALY` (passes
execution liquidity and carries a structural flag: funding, price dispersion, open interest, stage-1 move), else `CORE`.

## The shadow deep-research queue (observational)

The same budget as the legacy stage 2 (40 + 16 = 56 slots), filled from verified crypto with crypto execution identity by
research-priority points, then known execution liquidity, then ticker - **regardless of the liquidity gate**. It makes
no request (`shadow_requests_made: 0`), cannot publish or trade, and never changes a disposition. `legacy_vs_shadow`
compares it with what the radar actually deep-researched: overlap, legacy-only, shadow-only (with flags, lane, liquidity
and why the legacy funnel skipped it), and the request budget it would need if it ran (`budget_ratio`, `within_budget`).

## Emerging census

`emerging.verified_crypto` and `emerging.unverified`: assets outside stage 2 that are below execution liquidity, on one
venue or newly listed - counts by cause, liquidity buckets, flags and the top 25 by points. Census only: `trade_promotion`
is `NONE`.

## Accounting (unaccounted 0)

`accounting` proves every contract and asset is in exactly one place: active perps = denominator + unsupported + on
unavailable venues; every denominator contract is in a discovery record; canonical assets = discovery + registry-only;
every discovery asset has exactly one stage, one deep-research reason, one lane and one final disposition.
`unaccounted_by_scope` lists each scope; `unaccounted` is their sum and must be 0. The snapshot's `discovery` section
carries the same counts (`coverage`, `venues`, `stages`, `identity_breakdown`, `liquidity_breakdown`,
`shared_execution_gates`, `model_eligibility` (per engine, by ledger disposition), `priority_lanes`, `anomaly_flags`, `deep_research`, `visibility`, `emerging`, `shadow_queue`,
`legacy_vs_shadow`, `scan_stages`, `requests`, `unaccounted`, `problems`).

## The bounded quant-audit fix

Production snapshots since Phase 3 carried the audit warning "published quant signals/positions differ from the ledger's
SURFACED". Cause: `quant.py` follows every open paper position to its stop or time exit and publishes it in
`quant.json` whatever the coin's liquidity now, but the audit recorded a coin below the $1M new-entry minimum as
`NOT_EXECUTABLE` before looking at its open positions (production scan gh-38083078861-1: HBAR, RENDER, TRUMP, XLM).

Phase 7 records what is published. For an open position on a coin that fails a new-entry gate this scan (execution
liquidity; or 4h candles):

* final disposition `SURFACED` (`QUANT_POSITION_OPEN`, stage `lifecycle`), action `HOLD / MANAGE EXISTING POSITION`;
* `new_entry_executable: false`, `execution_reason` the gate (`DEX_VOLUME_BELOW_LEGACY_MIN`, `DEX_VOLUME_MISSING`,
  `NOT_ON_TRADE_DEX`, or the 4h candle reason), the observed liquidity and the threshold;
* step `POSITION_LIFECYCLE_ONLY`.

A new signal on a coin below execution liquidity stays `NOT_EXECUTABLE` (and is named as a problem: the engine never
produces one). The journal is untouched, no strategy, P&L, stop or exit changes. Replaying production's open positions
through the fixed audit gives the four coins `SURFACED` / `POSITION_LIFECYCLE_ONLY` and no problem.

## Stage A: the coverage census before Phase 7 (production scan gh-38083078861-1, main 61960d9)

| | |
|---|---|
| Venues | 7 of 8 market lists loaded; edgeX unavailable (HTTP 503) |
| Contracts | 12,292 raw; 2,017 active perpetuals (aster 593, variational 568, extended 326, lighter 213, hyperliquid 178, dydx 73, paradex 66); 1,994 in coin records, 12 duplicates, 7 price conflicts, 4 in separate non-admitted exposures |
| Assets | 1,040 canonical; 853 with an active perpetual (433 VERIFIED_CRYPTO, 267 VERIFIED_TRADFI, 153 UNVERIFIED, 0 AMBIGUOUS); 187 without one (Paradex options and dated markets, delisted) |
| Execution liquidity, verified crypto | >= $5M 33, $1-5M 39, $100k-1M 97, < $100k 264 (72 pass the $1M gate) |
| Radar pipeline | 433 1h requests, 428 charted (5 without candles); 72 liquid; 56 deep-researched (40 top + 16 extras); 16 liquid not selected; 356 below $1M; 43 signals on 34 coins; 0 picks, 0 watch |
| Not in the published radar table | 425 of 853: 267 tradfi, 153 unverified, 5 verified crypto without 1h candles |
| Values present (853 coins) | price 853, volume 853, funding 831, open interest 701 |
| Venue count | one venue 343, two 236, three or more 274 |
| Emerging (verified crypto outside stage 2) | 362: 361 below $1M, 90 on one venue, 0 new (first-seen history only 4 days old) |
| Unverified | 153: 112 on one venue, 2 newly listed, 123 below $100k |
| Audit problem | quant: published positions differ from the ledger's SURFACED (HBAR, RENDER, TRUMP, XLM) |

Reproduce: `python tools/v8/discovery_report.py <audit_latest.json.gz>`. A dry run of `v8.discovery.build()` on that
snapshot (no scan part) accounts for all 2,017 active perps and 1,040 assets with unaccounted 0 in 0.14 s; the file is
about 3 MB (140 kB gzip).

## Resource budget

Discovery adds no request (`requests.discovery_extra: 0`, `network_requests_added: 0`): the light records reuse the
market lists the scanner already fetched; the deep research is the radar's own stage 2 (433 1h and 56 15m requests in
the census scan); the shadow queue only ranks. CPU: the build is linear in the number of contracts (well under a second
at production size).

## Versions

| | |
|---|---|
| Discovery | `v8.discovery/1` (new, independent of the identity version) |
| Audit snapshot | `v8.audit/5`, `v8-phase7.0` (new top-level `discovery` section; manifest `discovery_version`, `discovery_file`) |
| Identity | `v8.identity/4`, config hash `96a10dc22e22d0bcf2c6ed1970ea1de72307426dfad2b53020a2b998c125d12c` - **unchanged** |
| Taxonomy | step `POSITION_LIFECYCLE_ONLY` added; no reason code added, renamed or retired |

## Parity and tests

* Differential parity: base production main `61960d9` (tree `5d3c622`), manifest
  `tests/fixtures/v8/phase7_expected_deltas.json` with **no allowed delta** (universe, DEX status, notes, code, decisions,
  files all empty; every identity state pinned; no counterfactual projection). Head golden
  `legacy_parity_golden_phase7.json` = the Phase 6 legacy digests (it lists one more audit file).
* `tests/test_v8_phase7.py`: the fifteen synthetic discovery tests (denominator, failed venue, venue states, fallback,
  identity / liquidity / history / Top-N never gating visibility, first-seen-only new listings, flag thresholds, lanes,
  Decision Trace, accounting, determinism and no authority, stages from the ledger), the qualification tests (FULL needs
  every venue; DEGRADED is never full; fallback and accounting problems qualify nothing), the shared-gates vs
  model-eligibility tests (eligibility is each engine's ledger record, unchanged by research priority), the shadow-queue
  tests, the quant
  lifecycle tests (journal preserved, ledger SURFACED, no new entry, published == ledger, a new signal on an illiquid
  coin stays NOT_EXECUTABLE), versions, and the fixture pipeline end to end.
* `ScanGateInvariants` runs in every scheduled scan's core-test gate.
* Research (`research.yml`) runs `tools/v8/discovery_report.py` on the exact head's live discovery file, the latest
  production snapshot, and the published quant journal replayed by the head and by the base.

## What Phase 7 does not do

No new data provider; no point-in-time universe (Phase 8); no change to which coins are deep-researched, evaluated,
published or traded; no trading claim. The shadow queue is a comparison, not a proposal to swap the funnel: whether any
of its candidates deserves deep research is a decision for a later, separately authorized phase with its own evidence.
