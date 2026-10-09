# Phase 4: positive crypto identity evidence (Stage A: qualification)

**Outcome: `PHASE 4 NO SAFE POSITIVE-EVIDENCE RULE QUALIFIED`.** No venue field qualified as positive crypto
evidence, so Stage B promoted nothing. The identity rules, `v8.identity/2`, every identity state and every legacy
output are unchanged (the Phase 4 differential manifest allows no delta at all). What Phase 4 adds is the evidence
itself: a candidate-field census with a qualification gate (`tools/v8/candidate_census.py`, run by Research on
every push), and candidate evidence recorded in every audit snapshot, kept apart from authoritative evidence.

## The question

Phase 3 retired "no evidence = crypto": a contract with no positive evidence is `UNVERIFIED`, visible but never
executable. Many of the 123 `UNVERIFIED` assets are probably real crypto tokens on venues whose metadata is not
accepted as crypto authority. Phase 4 asked which deterministic venue metadata fields can safely be **positive
crypto evidence**, assuming none is trustworthy until proven.

## Method

1. **Census.** Every audit snapshot keeps every kept venue contract with the raw identity fields its venue sends
   (`vmeta`: Aster `underlyingType`, `underlyingSubType`, `quoteAsset`, `marginAsset`; Lighter `strategy_index`,
   `market_flags`, insurance fund, trading hours; Extended `category`; the Variational and Extended names), its
   own evidence, its price-coherent exposure and the asset's state. The census cross-tabulates every field/value
   against exposure state and asset state, with unique assets, exposures, unpriced contracts and every
   contradictory example.
2. **Rules.** Every value becomes candidate rules: `field == value`, and for Aster's tag list `contains value`,
   `== only value` and `== only value AND underlyingType == COIN`. Each rule is evaluated on its own.
3. **Projection.** `tools/v8/rescore_identity.py` rebuilds each snapshot's adapter rows and re-runs this checkout's
   resolver. It reproduces every observation's recorded states exactly (0 differences on 853 assets each), so adding
   a rule as crypto venue evidence gives that rule's exact impact before anything is activated.
4. **Gate.** A rule qualifies only if all of these hold in every observation:
   * **A, deterministic semantics:** the venue documents, or the value itself states, a crypto asset class.
   * **B, no tradfi contamination:** zero selected contracts on a VERIFIED_TRADFI exposure or asset.
   * **C, no unresolved conflict:** zero selected contracts on an AMBIGUOUS exposure or asset.
   * **D, negative controls:** no selected contract carries its own tradfi evidence, and no tradfi or ambiguous
     asset would change state (including the controls PAXG, SAMSUNGUSD, HYUNDAIUSD, US10Y, BYD, XIAOMI, QNT, PURR,
     BB, SPY, XAU, US500, NVDA, TSLA, EURUSD; these are controls only, never rules).
   * **E, exposure coherence:** the projection changes only the selected contracts' own exposures.
   * **F, fail closed:** an implementation property, covered by the tests.

## Observations

| Observation | Source | Code | Raw contracts |
|---|---|---|---|
| `gh-37833625441-1` | Research, 2026-10-08 ~19:40 UTC (live) | 7732369 | 11,558 |
| `gh-37883045144-1` | Research, 2026-10-09 04:29 UTC (live) | 0557926 | 12,588 |
| `gh-37887949009-1` | production scan, 2026-10-09 05:19 UTC | d011bcb | 12,588 |
| `gh-37895463141-1` | production scan, 2026-10-09 06:48 UTC (read by this branch's Research) | d011bcb | 12,588 |
| `gh-37903026421-1` | this branch's Research: the exact head on live data, 2026-10-09 ~08:08 UTC | c0b12c8 | 12,782 |

Every Research run of this branch adds its own live observation, plus the latest production audit and the previous
Research audit (`research_candidate_census.json` on the research branch). Every per-value count and every gate result
was identical in all five observations, and the resolver reproduced each one's 853 recorded asset states exactly.
That shows stability over about 12 hours of one listing set. It is not independent evidence over time: the research
branch keeps one commit, and Actions artifacts last 14 days but cannot be read from the review environment.

**What the venues send** (live payloads read on 2026-10-09):
* **Lighter** `orderBookDetails` has no asset-class field. `strategy_index` is **absent from Lighter's published
  OpenAPI schema**. Insurance fund, operator account, margin fractions, `base_interest_rate` and
  `funding_premium_multiplier` are risk and funding parameters, which gate A excludes.
* **Hyperliquid** core universe: `szDecimals`, `maxLeverage`, `marginTableId`, `onlyIsolated`, `marginMode`,
  `isDelisted`. Its stock and commodity markets are on builder DEXs (`xyz:…`), which the adapter already drops.
* **dYdX:** `marketType` CROSS/ISOLATED (margin mode) and risk parameters.
* **Paradex** summary: prices, greeks, funding. It also lists stock options (SPCX).
* **Variational:** ticker, free-text name, prices, funding interval, quotes.
* **Extended:** `category` (already authority).
* **Aster:** its API was refused from the review network, so the census uses the fields every snapshot records.
  Aster's API documentation shows `underlyingType`/`underlyingSubType` only in one example (`"COIN"`,
  `["STORAGE"]`), with no definition or enum.
* **edgeX:** returned 503 and was down in production too, so there is nothing to observe.

## Census (contracts by exposure state; identical in all five observations)

| Venue field = value | Contracts | VERIFIED_CRYPTO | VERIFIED_TRADFI | UNVERIFIED |
|---|---|---|---|---|
| aster underlyingType = COIN | 592 | 346 | **136** | 110 |
| aster underlyingSubType = [AI] | 40 | 34 | 0 | 6 |
| aster underlyingSubType = [Meme] | 57 | 31 | **1** (CAT) | 25 |
| aster underlyingSubType = [Top] | 16 | 16 | 0 | 0 |
| aster underlyingSubType = [AOS2] | 2 | 2 | 0 | 0 |
| aster underlyingSubType contains AOS2 | 16 | 2 | 14 | 0 |
| aster underlyingSubType contains pre-launch | 5 | 0 | 5 | 0 |
| lighter strategy_index = 2 | 113 | 107 | **1** (PAXG) | 5 |
| lighter strategy_index = 3 / 4 / 5 / 6 | 9 / 9 / 55 / 17 | 0 | 8 / 9 / 55 / 16 | 1 / 0 / 0 / 1 |
| lighter strategy_index = 7 | 10 | 0 | 3 | 7 (incl. US10Y) |
| lighter insurance fund …654 / …655 | 105 / 108 | 9 / 98 | 86 / 6 | 10 / 4 |
| lighter market_flags = 0 | 213 | 107 | 92 | 14 |
| extended category = Crypto (authority) | 195 | 193 | 2 (PAXG, XAUT) | 0 |

## Rules rejected

| Rule | Failed | Why |
|---|---|---|
| Aster `underlyingSubType == [AI]` (also with `COIN`) | A | Data-clean (B to E pass in every observation), but "AI" is a sector/theme tag that applies to tokens and companies alike. A crypto reading rests on an undocumented convention (that Aster adds STOCK/ETF/… to every tradfi listing), and Aster's own type field already breaks it: all 136 tradfi Aster contracts are sent as `COIN`. Projected impact if activated: 6 assets UNVERIFIED → VERIFIED_CRYPTO (GRIFFAIN $1.82-1.99M, SKYAI ~$100k, SENT ~$55k, AVAAI $22k, PUNDIAI $7k, AIW3 $3-4k); only GRIFFAIN would pass the $1M gate. |
| Aster `[Meme]` / contains Meme | A, B | A theme tag. It selects the memecoin CAT (1000CAT at about $0.000002), whose ticker is on the tradfi list (Caterpillar), so it sits on a VERIFIED_TRADFI asset. |
| Aster `[Top]`, `[AOS2]` | A | A tier tag and a programme tag. They are data-clean but have **no impact**: every contract carrying them is already verified crypto. |
| Aster contains AOS2 / pre-launch / Semiconductor / STOCK / ETF / Commodities / USD1-RWA | A, B, D | They appear on tradfi listings. As crypto evidence they would turn tradfi assets AMBIGUOUS or UNVERIFIED. The tradfi tags stay tradfi evidence (Phase 3). |
| Aster `underlyingType == COIN` | B, D | Sent for all 136 tradfi Aster contracts. |
| Aster `quoteAsset` / `marginAsset` | A, B, D | The settlement or margin currency, not the underlying. |
| Lighter `strategy_index == 2` | A, B | Undocumented (absent from the API schema). Its meaning is only inferred from data: 2 = tokens, 3 = commodities, 4 = FX, 5 = US equities, 6 = non-US equities, 7 = mixed. It includes the tokenized gold PAXG (tradfi exposure). Would promote CTR, RAIL, ROBO, SKR, STONK. |
| Lighter `strategy_index == 3 / 4 / 5 / 6 / 7` | A, B (and D where tradfi assets would move) | Commodities, FX and equity groups. Group 7 mixes tokens with US10Y, OPENAI and ANTHROPIC. |
| Lighter insurance fund, market_flags | A, B, D | A risk pool and a constant: both mix stocks and tokens. |
| Hyperliquid core listing, dYdX, Paradex, Variational, edgeX | n/a | No asset-class field. Venue membership is not a field, and the core Hyperliquid list and dYdX both list PAXG, WTI or XAG. |

No rule qualified. `QUALIFIED_CRYPTO_RULES` in `v8/identity.py` is empty.

## A finding: venues label the wrapper, this system classifies the exposure

Every contradictory example has the same cause. PAXG and XAUT (tokenized gold) are "Crypto" on Extended and
`strategy_index 2` on Lighter, and are listed on Hyperliquid's core and dYdX. CAT the memecoin shares its ticker
with Caterpillar. Venues classify the **instrument** ("it is a token"); this system classifies the **price
exposure** (gold is tradfi). Even the trusted Extended `Crypto` category relies on the repository's tradfi list and
the tradfi name rule to keep PAXG and XAUT out. A venue's crypto label is therefore never sufficient on its own; it
is safe only beside the existing precedence (a tradfi list, a tradfi name or tradfi venue evidence wins, and
conflicting evidence is AMBIGUOUS).

## UNVERIFIED inventory (base `d011bcb`, production scan `gh-37887949009-1`)

```text
Base UNVERIFIED:           123
Promoted to VERIFIED_CRYPTO: 0
Promoted to VERIFIED_TRADFI: 0
Moved to AMBIGUOUS:          0
Remain UNVERIFIED:         123
```

By venue: 98 assets are on Aster only, 6 on Aster and Lighter, 6 on Lighter only, 5 on Variational only, 3 on
Hyperliquid only, 3 on Aster and Hyperliquid, 1 on Aster and Variational, and 1 on Aster, Hyperliquid and Lighter.

By candidate evidence:

| Candidate evidence | Assets |
|---|---|
| Nothing beyond Aster's `COIN` (no subtype tag), so no field rule can reach them | 72 |
| Aster [Meme] | 24 (+1 that also has Lighter `strategy_index 2`) |
| Aster [AI] | 6 |
| A Variational name only | 5 (+1 with Aster `COIN`) |
| Aster `COIN` plus Lighter `strategy_index` 7 / 2 | 3 / 3 |
| Lighter `strategy_index` only (7, 6, 3, 2) | 3, 1, 1, 1 |
| No venue field at all (BANANA, BSV) | 2 |

Liquid at ≥ $1M on a trade DEX: AIN, GRIFFAIN, 龙虾. The full per-asset inventory (venues, raw symbols, candidate
evidence, liquidity, matching rules, final state) is in the census JSON.

## Candidate evidence in the audit trace

* `v8/identity.py`: `CANDIDATE_FIELDS` (the Aster type and subtype tags, and Lighter's strategy index, insurance
  fund and market flags), `candidate_evidence(venue, vmeta)`, `QUALIFIED_CRYPTO_RULES = ()`, and
  `CANDIDATE_STATUS = "OBSERVED_NOT_AUTHORITY"`. Values that are already authority (an Aster type other than COIN,
  the Aster tradfi subtypes) are not repeated as candidates. None of this enters `identity_config()`, so the identity
  config hash is unchanged.
* **Registry:** every contract has `candidate` (its observed candidate values). Every asset has `candidate_evidence`
  `{observed, authority: false, status, qualified_rules}`, apart from `identity.evidence` (authoritative only).
  `registry.counts.candidate_evidence` is a per-scan cross-tab: venue.field=value by exposure state, plus the
  unverified assets with and without candidate evidence.
* The audit version is `v8-phase4.0`; the schema stays `v8.audit/3` (one additive contract column).

Each production audit snapshot therefore records one more observation of how every candidate value lines up with
verified identity. That is the time series a future qualification needs.

## Not changed

* The identity rules, `v8.identity/2`, the authority file and same-scan compatibility, and every identity state.
* `KNOWN_CRYPTO` and the tradfi lists.
* Every strategy, gate ($1M, $5M, 30/90-day history, Top-N, extras), FINAL/ORDER, stops, targets, sizing and smart
  money thresholds.
* Every Phase 3 invariant: discovery visibility, the execution gate, smart same-scan authority, quant
  current-identity actionability, entry-time provenance, legacy evidence quarantine, Analyzer defence and
  unaccounted = 0.

## What could qualify a rule later

A rule would need either venue documentation that defines a value as a crypto asset class, or a retained time series
of the census across many listing changes. The latter now accumulates in every audit snapshot. A positive crypto
rule should also always be combined with the existing tradfi precedence.
