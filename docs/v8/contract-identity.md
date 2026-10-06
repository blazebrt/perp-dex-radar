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
| `tradfi`, `tradfi_reason` | the legacy classification and the rule that decided it: `TRADFI_LIST`, `FX_PAIR`, `KNOWN_CRYPTO`, `NAME_PATTERN:<word>`, `DEFAULT_CRYPTO`, `VENUE_UNDERLYING:<type>`, `VENUE_CATEGORY:<category>`, `VENUE_24_5_MARKET` |
| `price`, `vol`, `oi`, `fund8h` | as the legacy adapter computes them (funding per 8 hours) |
| `fund_iv_h` | the venue's funding interval in hours where known (Hyperliquid and dYdX: 1), else null |
| `src_ts` | venue timestamp: none of the eight market lists sends one today, so it is null |
| `rcv_ts` | when the payload was received |
| `first_seen` | the first scan this contract was seen in, from our own registry history (`data/v8/first_seen.json`) |
| `basis` | how each value was observed when not simply `OBSERVED`: `OBSERVED_ZERO` or `MISSING` |
| `health` | `HEALTHY`, `MISSING` (price or volume missing), `CONFLICTED` (dropped as a price conflict), `STALE` (venue timestamp older than 15 minutes) |
| `legacy` | what the legacy universe did with it (below) |

## What the legacy universe did (`legacy`)

| State | Meaning |
|---|---|
| `SELECTED` | kept by the adapter and chosen as the asset's market on this venue |
| `DUPLICATE_NOT_SELECTED` | kept by the adapter, but another market of the same asset on this venue had more volume |
| `PRICE_CONFLICT_DROPPED` | kept, then left out because its price is more than 20% from the asset's main market |
| `HL_BUILDER_MARKET`, `DELISTED`, `NOT_TRADING`, `NOT_PERPETUAL`, `EMPTY_SYMBOL` | skipped by the adapter |
| `ADAPTER_FAILED` | the venue's adapter raised an error this scan, so legacy used none of its markets |
| `AUDIT_ADAPTER_MISMATCH` | the registry's reading disagrees with the adapter (an audit defect; tested to be zero) |

The registry re-reads every raw market with the same conditions as the adapter, then reconciles with the rows the
adapter actually returned and the coins `build_universe()` actually built (matched by object identity, so a
duplicate and a selected row are never confused). Every scan checks the two agree; a disagreement shows up as
`AUDIT_ADAPTER_MISMATCH` in the registry counts and in the snapshot.

## Assets

`registry.assets` lists every canonical asset with its contracts and venues and:

* `legacy`: `CRYPTO` or `TRADFI` (in the legacy universe), `NO_ACTIVE_PERP_CONTRACT` (every contract skipped by the
  adapters), `PRICE_CONFLICT_ALL_VENUES`, or `VENUE_ADAPTER_FAILED` (listed only where the adapter failed);
* `collision`: the legacy universe marks the ticker tradfi although a selected market of it is crypto - the
  BB / PURR / QNT class. Legacy keeps excluding these (Phase 1 does not change it); the registry and every engine's
  ledger now say so with `TRADFI_TICKER_COLLISION`, and the record names the rows that carried the tradfi flag;
* `aliases`: the different raw symbols that map to the asset (multipliers, aliases), when there is more than one.

## Universe built three times

The scanner, the quant desk and the coin picks each build the universe from the market lists in their own process,
minutes apart (legacy behaviour, unchanged). The registry is built from the scanner's fetch. The quant and picks
ledgers cover their own universes; the snapshot reports any difference between them and the scanner's under
`coverage.summary.engine_universe_differences`.
