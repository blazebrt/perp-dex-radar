# Data health

Phase 1 only **observes** data health. No state below is fed back into any engine.

## How a value was observed

| Basis | Meaning |
|---|---|
| `OBSERVED` | the venue sent a number other than zero |
| `OBSERVED_ZERO` | the venue sent exactly 0 |
| `MISSING` | the venue sent nothing (field absent, null or unparsable) |
| `MISSING_LEGACY_ZERO` | missing, and the legacy engine uses 0 in its place |
| `ASSUMED_DEFAULT` | missing, and the legacy engine uses a configured default |
| `NOT_ON_TRADE_DEX` | the asset is listed only on DEXs outside your trade DEXs, so legacy has no volume for it |

### Missing volume is not zero volume

The legacy liquidity check is `(liq_of(coin) or 0) >= $1M`. `liq_of` keeps only truthy venue volumes, so a venue
that reports **exactly 0** and a venue that reports **nothing** both become 0. Phase 1 leaves that line unchanged and
tells the cases apart from the venue rows:

* reported 0: `DEX_VOLUME_BELOW_LEGACY_MIN`, observed `trade_vol 0`, basis `OBSERVED_ZERO` (the data is fine, the
  market is not executable);
* reported nothing: `DEX_VOLUME_MISSING_LEGACY_ZERO`, disposition `INSUFFICIENT_DATA`, health `MISSING`, with
  `legacy_used: 0` so the silent substitution is visible.

### Funding defaults

When no DEX sends funding for a coin, legacy radar paper costs assume `fund_default` (0.01% per 8 hours). Those
records carry the step `FUNDING_ASSUMED_DEFAULT`, and the registry marks the contract's `fund8h` basis `MISSING`.
The quant desk counts a missing funding settlement as 0 in its paper costs (legacy behaviour, listed in
[known-legacy-behavior.md](known-legacy-behavior.md)).

## Record states

| State | Contract (registry) | Engine record (ledger `h`) |
|---|---|---|
| `HEALTHY` | price and volume observed, no conflict | inputs present and consistent |
| `STALE` | venue timestamp older than 15 minutes at receipt (none of the eight lists sends one today) | candles whose last complete day lags the scan's (`LAST_DAY_NOT_SYNCED`) |
| `MISSING` | price or volume missing | candles, history or volume missing |
| `CONFLICTED` | dropped as a price conflict (more than 20% from the main market) | candle prices do not match the DEX price (`PRICE_SCALE_CONFLICT`) |

## In the snapshot

`data_health` holds: contract states per venue; the basis counts of price, volume, open interest and funding over
all contracts; record states per engine; step counts per engine (paper trades opened, funding assumed, ...); the
legacy candle-source counts and DEX status; per-venue registry reconciliation counts; and any audit consistency
problem (expected empty).
