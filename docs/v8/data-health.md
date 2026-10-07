# Data health

Data health is observed: no state below is fed back into any engine. The one exception since Phase 2 is the
execution-liquidity evaluation (`v8/liquidity.py`, below), which the engines' $1M gates use.

## How a value was observed

| Basis | Meaning |
|---|---|
| `OBSERVED` | the venue sent a number other than zero |
| `OBSERVED_ZERO` | the venue sent exactly 0 |
| `MISSING` | the venue sent nothing (field absent, null or unparsable) |
| `MISSING_LEGACY_ZERO` | missing, and the legacy engine used 0 in its place (Phase 1 only; the liquidity gate no longer does) |
| `ASSUMED_DEFAULT` | missing, and the legacy engine uses a configured default |
| `NOT_ON_TRADE_DEX` | the asset is listed only on DEXs outside your trade DEXs, so legacy has no volume for it |

### Missing volume is not zero volume (Phase 2)

Phase 1 found the legacy check `(liq_of(coin) or 0) >= $1M` and a universe that kept only truthy venue volumes: a
venue that reports **exactly 0** and a venue that reports **nothing** both became 0. Phase 2 fixes the semantics
with one shared evaluation, `v8/liquidity.py`, used by every gate (radar stage 2 and backtest pool, quant desk, coin
picks, the research coin selection):

| State | Meaning | Gate | Reason when it fails |
|---|---|---|---|
| `KNOWN` | a trade DEX reported a 24h volume; an observed 0 is a known 0 | passes at $1M or more | `DEX_VOLUME_BELOW_LEGACY_MIN` (`NOT_EXECUTABLE`), basis `OBSERVED` or `OBSERVED_ZERO` |
| `MISSING` | listed on a trade DEX, no volume reported | **never passes**: missing evidence is not evidence of execution liquidity | `DEX_VOLUME_MISSING` (`INSUFFICIENT_DATA`, health `MISSING`) |
| `NOT_ON_TRADE_DEX` | listed only on DEXs you do not trade | never passes | `NOT_ON_TRADE_DEX` (`NOT_EXECUTABLE`) |

The gate gives the legacy yes/no for every coin (tested on random and edge values); what changed is that the
reason is true and the stored values are honest:

* the universe keeps an observed 0: `best_vol`, `tot_vol`, `trade_vol` are `0.0` for a 0, `None` only when no venue
  reported a volume;
* sorting by liquidity uses 0 for a missing volume internally (`liq_rank_value`), never stores it;
* published values keep the difference: the radar table's volume column is `null` (shown as "-") for a missing
  volume, not 0 ($0); paper-trade features and the picks records store `null` for a missing volume;
* cost models are unchanged (Phase 2 scope): slippage tiers still charge the highest tier when no volume is known
  (`scanner.slippage`, `quant.slip_of`, `tools/research/qdata.py`), and the learning tag "thin liquidity" still
  counts a missing volume as thin; paper trades need a known $1M+ volume anyway.

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
