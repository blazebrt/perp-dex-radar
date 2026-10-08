# Contract identity

## Identity

A contract is **one market on one venue**: `venue:raw_symbol`, for example `hyperliquid:kPEPE`,
`aster:BBUSDT`, `extended:QNT_24_5-USD`, `paradex:BTC-USD-PERP`.

* Records are never collapsed by ticker. The same ticker on two venues is two contracts; two markets of one venue
  that map to the same asset (`hyperliquid:FAKE05` and `hyperliquid:kFAKE05`) are two contracts.
* If a venue sends the same raw symbol twice in one payload, the second gets `#2` (`variational:ABC#2`).
* The registry is built from the payloads the legacy adapters already fetched. It adds no request to any exchange.

## Fields of a registry contract

| Field | Meaning |
|---|---|
| `id` | `venue:raw_symbol` |
| `venue`, `raw` | the venue and the symbol exactly as the venue sent it |
| `norm` | the symbol the legacy code canonicalises (Aster `baseAsset`, the part before `-` on dYdX and Paradex, ...) |
| `asset`, `mult` | canonical underlying and price multiplier, from the legacy `canon()` (`kPEPE` -> `PEPE` x1000) |
| `canon` | why: `IDENTITY`, `UPPERCASE`, `MULTIPLIER:x1000`, `ALIAS:VANATOKEN`, `MULTIPLIER_ALIAS:...` |
| `type`, `active`, `status` | market type (`perp`, `current_quarter`, `spot`, `other`), whether the venue reports it active, and its raw status |
| `tradfi`, `tradfi_reason` | the adapter's own row label (Phase 1 field, unchanged) and the rule behind it: `TRADFI_LIST`, `FX_PAIR`, `KNOWN_CRYPTO`, `NAME_PATTERN:<word>`, `DEFAULT_CRYPTO`, `VENUE_UNDERLYING:<type>`, `VENUE_CATEGORY:<category>`, `VENUE_24_5_MARKET`. Since Phase 2 it no longer decides anything: the identity columns below do |
| `price`, `vol`, `oi`, `fund8h` | as the legacy adapter computes them (funding per 8 hours) |
| `fund_iv_h` | the venue's funding interval in hours where known (Hyperliquid and dYdX: 1), else null |
| `src_ts` | venue timestamp: none of the eight market lists sends one today, so it is null |
| `rcv_ts` | when the payload was received |
| `first_seen` | the first scan this contract was seen in, from our own registry history (`data/v8/first_seen.json`) |
| `basis` | how each value was observed when not simply `OBSERVED`: `OBSERVED_ZERO` or `MISSING` |
| `health` | `HEALTHY`, `MISSING` (price or volume missing), `CONFLICTED` (dropped as a price conflict), `STALE` (venue timestamp older than 15 minutes) |
| `legacy` | what the universe did with it (below) |
| `cls`, `cls_reason`, `cls_auth` | Phase 2: the contract's own classification (`CRYPTO`, `TRADFI`, `AMBIGUOUS`, `UNLABELED`), the evidence (`VENUE_CATEGORY:RWA`, `VENUE_CATEGORY:Crypto`, `VENUE_CATEGORY_UNRECOGNIZED:<c>`, `VENUE_24_5_MARKET`, `VENUE_UNDERLYING:<t>`, `NAME_PATTERN:<word>`, `CONFLICTING_CONTRACT_EVIDENCE:...`, `NO_CONTRACT_EVIDENCE`) and its authority (`VENUE_METADATA`, `CONTRACT_NAME`, `NONE`) |
| `meta` | the raw venue metadata behind it: Aster `underlying` (underlyingType) and, since Phase 3, `subtypes` (underlyingSubType), Extended `category` |
| `npx` | price per 1 coin (multiplier removed): what exposures are compared on |
| `exposure`, `exp_class`, `exp_reason` | the price-coherent exposure of its ticker the contract belongs to (`QNT#1`, `QNT#2`; `FAKE13#u1` for a contract without price), the exposure's class and why (`TRADFI_CONTRACT_EVIDENCE`, `TICKER_KNOWN_CRYPTO`, `TICKER_TRADFI_LIST`, `CRYPTO_VENUE_METADATA`, `DEFAULT_CRYPTO`, `UNLABELED_UNDER_TRADFI_COLLISION`, `CONFLICTING_CONTRACT_EVIDENCE`, ...) |
| `admitted` | whether the contract reached the crypto universe (since Phase 3: with crypto execution identity) |
| `exp_state`, `in_record` | Phase 3: the exposure's identity state (`VERIFIED_CRYPTO`, `VERIFIED_TRADFI`, `AMBIGUOUS`, `UNVERIFIED`) and whether the contract is part of the coin record (an `UNVERIFIED` coin keeps its record without being admitted) |
| `evidence` | Phase 3: every piece of the contract's own evidence, `[class, reason, authority]` |
| `parsed`, `link` | Phase 3: the parsed underlying candidate of a quote-suffixed symbol on a base-only-symbol venue (`["SAMSUNG", "QUOTE_SUFFIX:USD"]`) and its link to the candidate ticker's exposures (coherent exposure, its class, the evidence it gave, if any) |
| `vmeta` | Phase 3: the identity-relevant raw fields the venue sent for this market (Aster `baseAsset`, `quoteAsset`, `marginAsset`, `underlyingType`, `underlyingSubType`; Extended `category`, `assetName`, `description`; Variational `name`; Lighter `market_flags`, `strategy_index`, `trading_hours`, `insurance_fund_account_index`). Recorded, not evidence, except the fields named in the identity rules |
| `inherited_from` | for a contract without evidence of its own in a tradfi exposure: the contract whose evidence it inherited |

## What the universe did (`legacy`)

| State | Meaning |
|---|---|
| `SELECTED` | kept by the adapter and chosen as the asset's market on this venue |
| `DUPLICATE_NOT_SELECTED` | kept by the adapter, but another market of the same asset on this venue had more volume |
| `PRICE_CONFLICT_DROPPED` | kept, then left out because its price is more than 20% from the asset's main market |
| `EXPOSURE_NOT_ADMITTED` | Phase 2: kept by the adapter, but part of a separate exposure of its ticker (another price level) that is tradfi or ambiguous; not merged into the admitted crypto coin |
| `UNVERIFIED_EXPOSURE_NOT_ADMITTED` | Phase 3: kept by the adapter, but part of a separate exposure without any identity evidence next to a verified crypto exposure; not merged into the crypto coin |
| `HL_BUILDER_MARKET`, `DELISTED`, `NOT_TRADING`, `NOT_PERPETUAL`, `EMPTY_SYMBOL` | skipped by the adapter |
| `ADAPTER_FAILED` | the venue's adapter raised an error this scan, so legacy used none of its markets |
| `AUDIT_ADAPTER_MISMATCH` | the registry's reading disagrees with the adapter (an audit defect; tested to be zero) |

The registry re-reads every raw market with the same conditions as the adapter, then reconciles with the rows the
adapter actually returned and the coins `build_universe()` actually built (matched by object identity, so a
duplicate and a selected row are never confused). Every scan checks the two agree; a disagreement shows up as
`AUDIT_ADAPTER_MISMATCH` in the registry counts and in the snapshot.

## Assets

`registry.assets` lists every canonical asset with its contracts and venues and:

* `legacy`: `CRYPTO`, `TRADFI`, `AMBIGUOUS` or (Phase 3) `UNVERIFIED` (the coin exists; only `CRYPTO`, which since
  Phase 3 means `VERIFIED_CRYPTO`, reaches the engines),
  `NO_ACTIVE_PERP_CONTRACT` (every contract skipped by the adapters), `PRICE_CONFLICT_ALL_VENUES`, or
  `VENUE_ADAPTER_FAILED` (listed only where the adapter failed);
* `identity` (Phase 2): the decision (`CRYPTO`, `CRYPTO_EXPOSURE_SELECTED`, `TRADFI_CLASSIFIED`,
  `TRADFI_EXPOSURE_EXCLUDED`, `AMBIGUOUS_EXPOSURE`), the ticker list that applied (`TICKER_KNOWN_CRYPTO`,
  `TICKER_TRADFI_LIST`, `TICKER_FX_PAIR`), `phase1` (what the Phase 1 ticker-level OR decided on the same market
  lists: the before/after), and every exposure: id, class, reason, authority, anchor market and price, price range,
  members, admitted; since Phase 3 also `state` (the four identity states), `authority` and `reason` of the deciding
  exposure, `evidence` (every piece, per contract and from the ticker lists), `discovery_eligible`,
  `execution_identity_eligible`, `promotion` (what would resolve an `UNVERIFIED` asset), `links`,
  `excluded_unverified`, and `phase2` / `phase2_reasons` (what the Phase 2 identity decided on the same lists);
* `collision`: the ticker's own markets disagree - some carry tradfi or ambiguous evidence, others none - and no
  ticker list settles it. Phase 1 excluded every such ticker (`TRADFI_TICKER_COLLISION`, retired); since Phase 2
  each exposure is decided on its own (see [phase2-universe-identity.md](phase2-universe-identity.md));
* `aliases`: the different raw symbols that map to the asset (multipliers, aliases), when there is more than one.

## Universe built three times

The scanner, the quant desk and the coin picks each build the universe from the market lists in their own process,
minutes apart (legacy behaviour, unchanged). The registry is built from the scanner's fetch. The quant and picks
ledgers cover their own universes; the snapshot reports any difference between them and the scanner's under
`coverage.summary.engine_universe_differences`.
