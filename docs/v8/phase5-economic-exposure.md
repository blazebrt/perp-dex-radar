# v8 Phase 5: economic exposure safety and tokenized-RWA hardening

Phase 5 separates two questions the identity resolver used to mix:

* **Wrapper.** How is the instrument represented? For example, a crypto-native token or perpetual.
* **Economic exposure.** What price risk does a position on it carry: crypto, or a stock, commodity, index or rate?

A venue can file a tokenized gold coin under "Crypto". The Perp Decision Desk cares about the exposure being traded, so the identity now follows the economic exposure only.

The identity version is **`v8.identity/3`**. Phase 5 does not touch any of the following:

* Strategies, FINAL/ORDER, scores, stops, targets, sizing and holding periods.
* The $1M DEX and $5M reference gates.
* The history requirements and the Top-N limits.
* The discovery universe (full-universe discovery is still not implemented).

## 1. What changed (v8.identity/2 -> v8.identity/3)

| Rule | v8.identity/2 | v8.identity/3 |
|---|---|---|
| Extended `category = "Crypto"` | Crypto contract evidence (`VENUE_CATEGORY:Crypto`) | Wrapper evidence only (`CRYPTO_WRAPPER`): recorded and traced, never consulted |
| Lighter token list `asset_type = "RWA"` | Not read | Tradfi evidence on that Lighter contract (`VENUE_ASSET_TYPE:RWA`) |
| Lighter token list `asset_type = "CRYPTO"` | Not read | No evidence (recorded as candidate evidence) |
| Pending exposure, known-crypto ticker, every contract on a venue whose exposure check did not run this scan | CRYPTO (ticker list) | UNVERIFIED (`EXPOSURE_CHECK_UNAVAILABLE`) |
| Pending exposure with a crypto wrapper and no economic evidence | UNVERIFIED (`NO_POSITIVE_IDENTITY_EVIDENCE`) | UNVERIFIED (`WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE`) |
| Crypto wrapper and tradfi economic evidence in one exposure | AMBIGUOUS (`CONFLICTING_CONTRACT_EVIDENCE`) | VERIFIED_TRADFI: they answer different questions |
| Two economic sources that disagree in one exposure | AMBIGUOUS | AMBIGUOUS (unchanged) |

Nothing else changed. In particular these stay as they were:

* Every Phase 3 tradfi rule: Aster `underlyingType` other than COIN, the Aster tradfi subtypes, Variational `Swap on`, Extended `RWA` and `_24_5`, the ticker tradfi and FX lists, the parsed symbols and coherent tradfi inheritance.
* The known-crypto list and the price-coherent exposures.
* The four public states.

`QUALIFIED_CRYPTO_RULES` is still empty. Phase 5 adds no positive crypto rule.

`v8.identity.resolve()` also resolves the same contracts under the /2 rules. It records the result per asset as `identity.previous` (state, decision, reason, authority). As a result, every audit shows which assets the version change moved and why. Only `/3` decides.

## 2. Stage A: crypto-authority inventory (before any resolver change)

Stage A used `tools/v8/exposure_safety.py`, read-only, through the real resolver. It was run on three observations:

* Production scan `gh-37887949009-1` (main d011bcb).
* Research `gh-37904572317-1` (Phase 4 head f3d21a8).
* The latest production scan, `gh-37943330492-1` (main 3288b15). The live check of this scan ran in the browser on its published audit.

The two reproduced observations give identical results and reproduce every recorded state (0 differences on 853 assets).

```text
VERIFIED_CRYPTO total:                    467
known-crypto list only:                   274
Extended Crypto + known crypto:           160
Extended Crypto only:                      33   (31 of them reach their other contracts by price-coherent inheritance)
other positive authority:                   0
multiple authority (= list + Extended):   160
```

On `gh-37943330492-1` the same 33 assets hold crypto authority from Extended Crypto alone. The 124th UNVERIFIED asset in that scan is **PEARL**: a newly listed Aster-only perp with no evidence, not a transition.

The 195 Extended contracts filed under Crypto (on kept contracts, `gh-37887949009-1`) split as follows:

* 160 are on known-crypto tickers.
* 33 are on no list.
* 2 are tokenized gold: **PAXG and XAUT**, VERIFIED_TRADFI. They are safe only because the ticker tradfi list and their own names ("PAX Gold", "Tether Gold" match the tradfi name pattern) settle them.

### The Extended-Crypto-only assets

Stage A projected model 2 (wrapper only) and model 3 (wrapper plus the known-crypto list) through the real resolver. Both give exactly 33 transitions, every one **VERIFIED_CRYPTO → UNVERIFIED**. None goes to TRADFI or AMBIGUOUS. States change from 467 / 263 / 0 / 123 to **434 / 263 / 0 / 156**.

The outputs below are those of production `gh-37943330492-1` (journal-data 0905f2e).

| Asset | Venues | Inherited | Best 24h vol ($) | ≥ $1M | Production outputs |
|---|---|---|---|---|---|
| AGT | aster, extended | yes | 131,342 | no | radar table |
| AIA | aster, extended | yes | 236,722 | no | radar table |
| AIGENSYN | aster, extended | yes | 114,347 | no | radar table |
| B | aster, extended | yes | 254,946 | no | radar table |
| BAS | aster, extended | yes | 199,939 | no | radar table |
| BILL | aster, extended | yes | 116,468 | no | radar table |
| BTW | aster, extended | yes | 204,322 | no | radar table |
| CFG | aster, extended | yes | 154,859 | no | radar table |
| COLLECT | aster, extended | yes | 130,122 | no | radar table |
| DATA | extended, lighter | yes | 4,820 | no | radar table |
| DOGS | aster, extended | yes | 7,144 | no | radar table |
| EVAA | aster, extended | yes | 97,655 | no | radar table |
| FHE | aster, extended | yes | 62,554 | no | radar table |
| **GRAM** | aster, extended, hyperliquid, lighter, paradex | yes | **5,241,132** | **yes** | radar table (rank 6, analysed, no setup), smart row (no crowd) |
| GTC | aster, extended | yes | 173,828 | no | radar table |
| HIVE | extended | no | 118,272 | no | radar table |
| INX | aster, extended | yes | 136,690 | no | radar table |
| JELLYJELLY | aster, extended | yes | 185,113 | no | radar table |
| KAT | aster, extended | yes | 144,796 | no | radar table |
| LUNC | aster, extended, hyperliquid | yes | 108,810 | no | radar table |
| LYN | aster, extended | yes | 962,248 | no | radar table |
| MARS | extended | no | 69,622 | no | none |
| OPEN | aster, extended | yes | 186,646 | no | radar table |
| PLAY | aster, extended | yes | 428,605 | no | radar table |
| PRL | aster, extended | yes | 103,224 | no | radar table |
| PROM | aster, extended | yes | 284,770 | no | radar table |
| RE | aster, extended | yes | 77,240 | no | radar table |
| SWARMS | aster, extended | yes | 99,315 | no | radar table |
| TRIA | aster, extended | yes | 119,930 | no | radar table |
| TRUTH | aster, extended | yes | 44,818 | no | radar table |
| TST | aster, extended | yes | 156,544 | no | radar table |
| TURBO | aster, extended, hyperliquid | yes | 104,080 | no | radar table |
| XEC | aster, extended | yes | 2,550 | no | radar table |

Impact on outputs and positions:

* **Radar:** 32 rows leave the full table. None of the 33 is a pick or watch.
* **Quant, swing, day:** no signal, position or listing.
* **Smart:** no signal and no information crowd. GRAM's row becomes identity-blocked.
* **Dashboard and Analyzer:** nothing (they aggregate only the above).
* **Open paper positions:** none in quant, smart, radar or picks.
* **Closed history:** GRAM has one closed live radar row with `VERIFIED_CRYPTO` entry proof (missed). It stays qualified history (no hindsight). All other radar rows of the 33 are closed or backtest.

They are real tokens, but their only claim to crypto exposure was the wrapper label. Phase 5 does not add them to `KNOWN_CRYPTO` to keep the count up. They remain discoverable (UNVERIFIED: discovery yes, execution no).

### KNOWN_CRYPTO audit

`KNOWN_CRYPTO` is not redesigned. It was only audited against the tokenized-RWA controls:

* It has 436 entries.
* None is also on the tradfi list.
* None is an RWA-like name (PAXG, XAU, GOLD, XAG, USDY, OUSG, BUIDL, TSLA, NVDA, SPY).
* Live, the only known-crypto ticker that a Lighter RWA market shares is **BB**. Lighter's BB is the BlackBerry stock at ~$8.7, a separate exposure from BounceBit at ~$0.009.

## 3. Models 1, 2, 3 and the decision

| Model | Meaning | Projection | Verdict |
|---|---|---|---|
| 1 | `category=Crypto` is economic crypto authority (v8.identity/2) | today: 467 / 263 / 0 / 123 | **Rejected.** The field is not exposure-level: 2 of the 195 markets filed under it are tokenized gold, kept out only by other rules. An unknown tokenized commodity or equity under it, with a new ticker and a neutral name, would be VERIFIED_CRYPTO (test `test_newgold...` shows /2 would have done exactly that). No extraordinary justification exists: the field is also absent from Extended's documented market schema. |
| 2 | wrapper evidence only | 33 × CRYPTO→UNVERIFIED | **Adopted** (`v8.identity/3`). |
| 3 | wrapper evidence, crypto only with independent corroboration (the known-crypto list) | identical to model 2 on every observation | Rejected. The only corroborating authority (the known-crypto list) verifies those tickers on its own, so the label adds nothing. Keeping it as crypto contract evidence would make a crypto wrapper beside tradfi economic evidence AMBIGUOUS again, contrary to the economic-precedence rule. |

## 4. Venue metadata investigation and the qualification gate

Live checks ran on 2026-10-09 (UTC) through the public endpoints, with no credentials. Gate: **A** documented semantics, **B** zero known-crypto contamination, **C** same exposure only, **D** reproducible, **E** failure-safe, **F** no ticker guessing.

### Qualified: Lighter token list `asset_type = RWA` → tradfi evidence

**The source.** `GET /api/v1/tokenlist` is one bulk request with no parameters.

**A (documented semantics).**

* Lighter's OpenAPI schema documents `Token.asset_type` with the enum **`CRYPTO | RWA`**, and `market` with `SPOT | PERPS`.
* It also documents `backend_symbol`.
* Lighter's documentation defines its RWAs: "RWAs ... include commodities, equities, and fixed income markets".

**Mapping.** A market's entry is the `PERPS` entry whose `backend_symbol` (when set, e.g. `kPEPE` → `1000PEPE`) or `symbol` equals the `orderBookDetails` market symbol.

* Live: 213 of the 213 active Lighter perps map exactly (5 through `backend_symbol`).
* There are 0 duplicates and 0 out-of-enum values.
* The list has 261 tokens: 244 PERPS and 17 SPOT.

**B (contamination).** Live coverage of the 213 active perps against the identity of production `gh-37943330492-1`:

* **RWA: 95 perps.**
  * 91 are already VERIFIED_TRADFI: 71 by the ticker tradfi list, 8 by FX, 12 by contract evidence.
  * 4 are UNVERIFIED and become tradfi: STABLECOINX (STOCK), BYD (NEW), H100 (COMPUTE), US10Y (BONDS).
  * **0 sit in a VERIFIED_CRYPTO exposure.**
* **CRYPTO: 118 perps.** 107 are crypto, 10 UNVERIFIED, and 1 tradfi: USDHKD, an FX pair that Lighter files under CRYPTO.
* So `CRYPTO` is not evidence. Positive rules are out of scope anyway, and `asset_type=CRYPTO` is contaminated. Lighter also files XAUT spot under CRYPTO.
* RWA categories seen: STOCK, ETF, COMMODITIES, FX, BONDS, KRW, PRE_IPO, COMPUTE, NEW, MAJOR.

**C (same exposure only).** The evidence is on the Lighter contract itself and can reach only its own price-coherent exposure. Live BB: Lighter BB (BlackBerry, $8.72) has its own tradfi evidence, and the BounceBit exposure ($0.0088) stays crypto.

**D (reproducible).** It is a pure function of the payload (`v8.identity.lighter_tokenlist_index`).

**E (failure-safe).** Explicit health states:

* `OK` / `FAILED` (network, timeout, 429/5xx after the fetcher's retries) / `UNAVAILABLE` (another HTTP error) / `MALFORMED` (not the documented TokenList).
* Per market: `NO_ENTRY` / `MALFORMED_ENTRY` / `NOT_REQUESTED`.

A market whose check did not run gets no evidence. An exposure made only of such markets is not verified by the ticker list (`EXPOSURE_CHECK_UNAVAILABLE`), so a failure can never make a market crypto. The Lighter market list itself never fails because of the token list. Live, no VERIFIED_CRYPTO exposure is Lighter-only, so an outage changes no crypto coin today.

**F (no ticker guessing).** It is an exact symbol match on a documented field.

**Request budget.** One extra request per universe build, sequential inside the Lighter adapter. That is three per scan: scanner, quant and picks each build the universe.

### Rejected

| Candidate | Why |
|---|---|
| Lighter `syntheticSpotInfo` | Per-symbol only, with no bulk form. Live, only `US500` (→ `EMU6`, source pythlazer) and `US100` (→ `NMU6`) return data; XAU, US10Y, NVDA, SPY, PAXG, SAMSUNGUSD, EURUSD and BTC all answer 400 "market does not have a synthetic spot info". It is the index-futures roll of two index markets that are already tradfi. Its absence means nothing, and discovering presence would cost ~213 requests per scan. Not an asset-class field (gate A, budget). |
| Lighter `assetDetails` | 12 spot/collateral assets (LIT, AAVE, AZTEC, rhSPY, USDC, rhQQQ, ETH, LINK, UNI, SKY, LDO, XAUT), with no asset-class field. Not exposure metadata. |
| Lighter token list `categories` | Sub-labels beside `asset_type`. Undocumented values with no enum, recorded as candidate evidence. |
| Extended `subCategory` | **Not in Extended's documented market schema** (gate A). Live, 326 active perps: Crypto/{AI 25, **Commodity 2 = PAXG, XAUT**, DeFi 38, Infra 35, L1 46, L2 12, Meme 37}; RWA/{Commodity 7, ETF/Index 8, Equity 112, FX 2, Pre-market 2}; "TradFi" only on inactive markets. It would add nothing beyond `category=RWA` except on PAXG/XAUT, which other rules already settle. Recorded as candidate evidence for a later census. |
| Extended `category` (both values) | Also undocumented. `RWA` stays tradfi evidence as the brief requires: 131/131 live markets non-crypto. `Crypto` is demoted (section 3). |
| Extended `tradingHours`, `isRfq`, `isOffHours`, `_24_5` as new rules | Trading schedule and execution mode, not asset class. Extended's own docs warn against inferring it from "the market name, asset class or isRfq". Never evidence (test `test_trading_schedule_and_rfq_are_never_evidence`). The Phase 2 `_24_5` rule is kept, since negative evidence is not weakened: live, all 32 `_24_5` markets are `RWA`, so it is never the only evidence. |
| Extended `referenceMarket` | Undocumented; null for PAXG/XAUT. |
| Paradex `/v1/markets` `tags` | Documented only as "Market tags", a free-form string array with no enum (gate A). Live, of 66 perps: RWA 23 (all already VERIFIED_TRADFI by the ticker list), DEFI 16 (**including PAXG**), LAYER-1 16, MEME 5, AI 3, LAYER-2 1, none 2. The endpoint also returns ~10,000 option markets, and the rule would change no identity today. |
| Hyperliquid `meta` | `szDecimals`, `name`, `maxLeverage`, `marginTableId`: no asset class. |
| dYdX `perpetualMarkets` | `marketType` CROSS/ISOLATED is the margin mode, not asset class. |
| Variational `metadata/stats` | No class field beyond the name (the Phase 3 `Swap on` rule stays). |
| Aster `exchangeInfo` | No new field. `underlyingType` and `underlyingSubType` stay as qualified in Phase 3/4 (Phase 4 rejected AI/Meme/Top/AOS2; not promoted). |
| edgeX | Market list unavailable in production (`data_sources.dex_market_lists.edgex = false`). |

## 5. Decision Trace

Every asset's identity block in the audit carries:

* `evidence`: economic evidence only.
* `wrapper_evidence`.
* `exposure_checks`.
* `wrapper_only`.
* `previous`: the /2 state.
* `exposure_trace`: both paths, their effect, the final state and whether crypto execution is allowed.

Every exposure carries its `wrapper` labels beside its class. Every contract record carries `wrapper` and `xcheck`. The engines' ledger records add `wrapper` (with its effect) and any `exposure_checks` that did not run.

```text
NEWTOKEN (Extended Crypto only)
  wrapper evidence:   extended:NEWTOKEN-USD  VENUE_CATEGORY:Crypto      effect: WRAPPER_ONLY
  economic evidence:  none
  final:              UNVERIFIED (WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE)   discovery: yes   crypto execution: BLOCKED
  previous (/2):      VERIFIED_CRYPTO (CRYPTO_VENUE_METADATA)

NEWGOLD (Extended Crypto wrapper + Lighter RWA COMMODITIES at a coherent price)
  wrapper evidence:   extended:NEWGOLD-USD   VENUE_CATEGORY:Crypto      effect: WRAPPER_ONLY
  economic evidence:  lighter:NEWGOLD        TRADFI  VENUE_ASSET_TYPE:RWA  (VENUE_METADATA)
  final:              VERIFIED_TRADFI (TRADFI_CONTRACT_EVIDENCE)        crypto execution: BLOCKED
  previous (/2):      VERIFIED_CRYPTO
```

## 6. Audit coverage

`registry.counts.exposure_safety`, summarised in `coverage.summary.identity.exposure_safety`, contains:

* `wrapper_crypto_assets` and `wrapper_crypto_by_state`, with `wrapper_unaccounted` = 0.
* `economic_crypto_verified` and `economic_tradfi_verified`.
* `wrapper_only_unverified`, `wrapper_with_economic_tradfi`, `wrapper_with_ticker_list_crypto` and `wrapper_ambiguous`.
* `economic_conflicts`.
* `exposure_check_unavailable_assets` and `exposure_check_blocked`.
* `previous_states`, `changed_vs_previous`, `transitions_vs_previous` and `changed_vs_previous_detail`: per asset, the contracts, exposures, old state/reason/authority, new economic and wrapper evidence and new state.

`data_health.exposure_metadata.LIGHTER_TOKENLIST` contains:

* The state and what the list returned.
* Markets by check and by asset type.
* Markets without a check.
* The tradfi-evidence markets.

The manifest names the source state in `data_sources.exposure_metadata`. The audit schema is `v8.audit/4` (columns `wrapper` and `xcheck`), version `v8-phase5.0`. Unaccounted stays 0 in every scope.

## 7. Versions, provenance, open positions

* **Version and config.** `VERSION = "v8.identity/3"`. The identity config hash changes, since `provenance.identity_config()` gains `extended_crypto_wrapper`, `lighter_tradfi_asset_types`, `lighter_asset_types`, `exposure_checks` and `exposure_check_ok`.
* **Smart money.** It accepts only a same-scan authority of the same version. A `v8.identity/2` authority file now fails with `OTHER_IDENTITY_VERSION:v8.identity/2`.
* **Entry-time proof (no hindsight).** New quant, smart and radar trades record `identity_version: v8.identity/3`. A trade proven `VERIFIED_CRYPTO` under /2 stays qualified history: `qualified()` checks the proof, not today's version.
* **Current actionability** uses the current identity. The Phase 3 gates block a downgraded coin at once:
  * quant `blocked_open`;
  * the dashboard aggregation;
  * the smart identity block;
  * the Analyzer.

  Tests: `DowngradeGates`. Nothing is force-closed.
* **Open positions.** At Stage A, no open paper position in any journal is on an asset Phase 5 moves.

## 8. Differential parity

The manifest is `tests/fixtures/v8/phase5_expected_deltas.json`, with base production main **3288b15** (tree d56ef75) and base golden `legacy_parity_golden_phase4.json`. The head golden is `legacy_parity_golden_phase5.json`, and the counterfactual is `exclude_without_execution_identity`.

The fixture gains only what the base never reads: Extended `subCategory` and a Lighter token-list response at a URL the base never requests. The base reproduces its golden.

Approved deltas:

* **Universe.**
  * EXTONLY and PRLX: VERIFIED_CRYPTO → UNVERIFIED (wrapper only).
  * BYD, HYUNDAIUSD and US10Y: UNVERIFIED → VERIFIED_TRADFI.
  * XIAOMI: AMBIGUOUS → VERIFIED_TRADFI (Lighter RWA).
* **DEX crypto counts:** Aster 5→4, Extended 3→1.
* **Notes:** one price-check note returns. PRLX's Lighter market is left out of its now-unverified record.
* **Published lists:** the unverified/tradfi split in `latest.json` coverage and the radar decisions.
* **Entry proof:** `identity_version` v2→v3 on every paper trade the run opens: 22 radar rows, 11 quant trades and 2 smart trades (`quant.json` and `smart.json` repeat their journals' open trades).

Zero unexpected deltas. The Phase 2, 3, closure and 4 manifests are kept for the record. Their identity states are the /2 states, which every run reproduces as `previous`.

## 9. Tests

* **`tests/test_v8_phase5.py`:**
  * NEWTOKEN, NEWGOLD and NEWSTOCK (three equity sources), the unknown index and rate.
  * PAXG/XAUT by exposure with the ticker lists removed.
  * The negative controls (PAXG, XAUT, SPY, NVDA, TSLA, XAU, US500, US10Y, BYD, SAMSUNGUSD, HYUNDAIUSD, XIAOMI) and the positive controls (BTC, ETH, SOL, QNT, PURR, BB) in live shapes.
  * The BB stock without Extended.
  * A true economic conflict.
  * Price-separated exposures.
  * Schedule and RFQ never being evidence.
  * Token-list semantics, adapter health (one request; 503/429/404/403/bad JSON/malformed/connection/timeout) and fail-closed behaviour.
  * Registry coverage.
  * Version, config hash, v2 authority rejection, and entry proof under /2.
  * Downgrade gates (quant, dashboard, smart).
* **Scan gate.** `ScanGateInvariants` runs in the Scan workflow's pre-publication core tests.
* **Changed earlier tests.** The Phase 3/4 tests that pinned Extended Crypto as crypto evidence now pin the /3 result and the /2 result (`previous`) side by side.

## 10. Live Research on the implementation head

Research run `37982448561` on head `1cec534` (scan `gh-37982448561-1`, 2026-10-09 ~19:46 UTC) passed: 346 tests OK. The observation itself:

* 12,297 raw contracts, 2,018 active perps, 1,040 assets.
* `v8.identity/3`, identity config hash `3ceec43e...`, audit `v8.audit/4` / `v8-phase5.0`.
* Unaccounted 0 in every scope.

**States: 434 VERIFIED_CRYPTO / 267 VERIFIED_TRADFI / 0 AMBIGUOUS / 153 UNVERIFIED.** The same contracts under /2 give 467 / 263 / 0 / 124. The transitions are:

* **33 × VERIFIED_CRYPTO → UNVERIFIED**, exactly the Stage A list (`WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE`; PRL's deciding exposure is its unlabeled Lighter market). GRAM ($11.4M) and LYN ($1.43M) were ≥ $1M at this scan.
* **4 × UNVERIFIED → VERIFIED_TRADFI**: BYD, H100, STABLECOINX, US10Y (Lighter token-list RWA).
* Nothing became crypto or ambiguous.

**Wrapper vs economic evidence:**

* `wrapper_crypto_assets` = 195: 160 crypto by the known-crypto list, 33 wrapper-only UNVERIFIED, 2 tradfi by economic evidence (PAXG, XAUT).
* `economic_crypto_verified` = 434 and `economic_tradfi_verified` = 267.
* `economic_conflicts` = [] and `wrapper_unaccounted` = 0.

**Lighter token list:** state OK, 261 tokens (244 PERPS). All 213 kept Lighter markets were checked: RWA 95, CRYPTO 118, none without a check. Exposure-check-blocked assets: none.

**Controls:**

* PAXG and XAUT are VERIFIED_TRADFI. Their wrapper `VENUE_CATEGORY:Crypto` is recorded beside the economic evidence: name `gold`, the tradfi list and, for PAXG, Lighter RWA and the Aster Commodities subtype.
* SPY, NVDA, TSLA, XAU, US500, US10Y, BYD, SAMSUNGUSD, HYUNDAIUSD and XIAOMI are VERIFIED_TRADFI.
* BTC, ETH, SOL, QNT, PURR and BB are VERIFIED_CRYPTO. QNT, PURR and BB select their crypto exposure. The Lighter BB stock carries its own `VENUE_ASSET_TYPE:RWA`.

**Engines:**

* The 33 assets are `IDENTITY_UNVERIFIED` in radar, quant, swing and day.
* The 4 new tradfi assets are `TRADFI_CLASSIFIED`.
* Smart money read the same-scan v3 authority (854 coins); no crowd was blocked by identity.
* Quant analysed 85 coins against the base's 87 (GRAM and LYN). The quant signals are identical to the base's.
* The radar published no pick or watch on either side.
* Swing/day: 2 listings differ each way (DOGE day and CRV swing out; UNI day and ASTER swing in). All four are VERIFIED_CRYPTO on both sides. The picks universe was 61 coins on both sides (no transitioned asset was in it), and every score moved by about ±2 between the two runs, which were ~3 minutes apart. That is a market move at the top-10 cut-off, not an identity effect.

The exposure-safety report on the three observations (this head, production `gh-37981368889-1` on main 3288b15, the previous Research `gh-37904572317-1`) reproduces every recorded state (0 differences). It gives the same inventory every time: 274 / 33 / 160 / 0. The candidate census qualifies no positive rule.

## 11. Known limits

These are also in [known-legacy-behavior.md](known-legacy-behavior.md):

* The known-crypto list is now the only positive crypto authority, and it is maintained by hand. A real coin on no list is UNVERIFIED.
* Several price-separated exposures of one known-crypto ticker that carry no evidence all receive ticker-list authority (pre-existing). The token list closes this for Lighter stocks (BB); other unlabeled venues remain.
* Extended's `category` (both values) and `subCategory` are undocumented. `RWA` is kept on the strength of the data.
* Lighter's RWA label is trusted for the tradfi direction only. Mislabelling a crypto token RWA would make it tradfi, the safe direction.
