# Disposition taxonomy (v8 Phase 1)

Every asset an engine receives ends with exactly **one final disposition** in that engine's ledger, with a
stable **reason code**, the observed input, the rule it was compared with, the data health of the inputs and the
venue contracts involved. Codes are stable identifiers: new ones may be added, existing ones are never renamed
or reused. There is deliberately no generic `FILTERED` code; an audit that cannot name a reason writes
`AUDIT_UNCLASSIFIED`, and the tests fail on it.

Source of truth: `v8/taxonomy.py`. `tests/test_v8_units.py` checks that every code below is in that module and
the other way round.

## Final dispositions

| Disposition | Meaning |
|---|---|
| `SURFACED` | published as an actionable item: a radar pick, a new or open quant position, a Ready/Strong swing or Good/Best day-trade listing, a smart-money signal |
| `WATCHED` | published for watching, not as an actionable call: radar watch list, Setting-up listings, smart-money information-only crowds |
| `REJECTED` | evaluated by the engine and not surfaced: no setup, blocked, below a score, cut by the number of published slots |
| `NOT_EXECUTABLE` | not tradable enough on the DEXs the engine trades: volume below the legacy minimum, not on a trade DEX, no active perp contract |
| `INSUFFICIENT_DATA` | the engine could not evaluate it: candles, history or a value missing or conflicting |
| `MODEL_INELIGIBLE` | outside what the engine's model covers: tradfi tickers, reference volume below the minimum, smart money outside Hyperliquid |

## Engines

| Engine | Input (every asset gets one record) | Written by |
|---|---|---|
| `universe` | registry assets the legacy universe never kept (all contracts skipped, every venue dropped as a price conflict, or only on venues whose adapter failed) | scanner.py |
| `radar` | every coin of the scanner's legacy universe, tradfi included | scanner.py |
| `quant` | every coin of the quant desk's own universe | quant.py |
| `swing` | every coin of the coin-picks universe (swing scores) | picks.py |
| `day` | every coin of the coin-picks universe (day-trade scores) | picks.py |
| `smart` | every coin proven traders hold, plus (at snapshot time) every other registry asset | smart.py, snapshot |

## Reason codes

Contract states (disposition column empty) describe what the legacy universe did with one raw market; they
appear in the registry, never as an asset's final disposition.

| Code | Disposition | Meaning |
|---|---|---|
| `SELECTED` |  | kept by the legacy adapter and chosen as the asset's market on this venue |
| `HL_BUILDER_MARKET` |  | Hyperliquid builder-deployed market (name contains ':'); the adapter skips it |
| `DELISTED` |  | the venue marks the market delisted; the adapter skips it |
| `NOT_PERPETUAL` |  | not a perpetual contract (dated future, option, spot); the adapter skips it |
| `NOT_TRADING` |  | the venue reports the market inactive or not trading; the adapter skips it |
| `EMPTY_SYMBOL` |  | the venue sent no usable symbol; the adapter skips it |
| `DUPLICATE_NOT_SELECTED` |  | another market of the same canonical asset on this venue had more volume; build_universe() keeps one market per asset and venue |
| `PRICE_CONFLICT_DROPPED` |  | price more than 20% away from the asset's main market; build_universe() treats it as a different asset under the same ticker and leaves it out |
| `ADAPTER_FAILED` |  | the venue's legacy adapter raised an error this scan, so legacy used none of its markets |
| `AUDIT_ADAPTER_MISMATCH` |  | the registry's reading of the raw market disagrees with the legacy adapter (an observability defect; legacy output is unaffected) |
| `TRADFI_CLASSIFIED` | `MODEL_INELIGIBLE` | classified tradfi (stock, index, FX, commodity); legacy engines are crypto only |
| `TRADFI_TICKER_COLLISION` | `MODEL_INELIGIBLE` | venues disagree: a tradfi listing shares the ticker of a market listed as crypto; legacy marks the whole ticker tradfi (a real crypto coin is excluded when known_crypto is true) |
| `NO_ACTIVE_PERP_CONTRACT` | `NOT_EXECUTABLE` | every contract for this asset was skipped by the legacy adapters (delisted, inactive, builder, non-perpetual) |
| `PRICE_CONFLICT_ALL_VENUES` | `INSUFFICIENT_DATA` | every venue's price was dropped as a price conflict |
| `VENUE_ADAPTER_FAILED` | `INSUFFICIENT_DATA` | listed only on venues whose legacy adapter failed this scan |
| `FALLBACK_UNIVERSE` | `INSUFFICIENT_DATA` | no DEX market list loaded; legacy used its built-in coin list without DEX data |
| `DEX_VOLUME_BELOW_LEGACY_MIN` | `NOT_EXECUTABLE` | 24h volume on your trade DEXs below the legacy minimum |
| `DEX_VOLUME_MISSING_LEGACY_ZERO` | `INSUFFICIENT_DATA` | no 24h volume reported on your trade DEXs; legacy treats the missing value as 0 |
| `NOT_ON_TRADE_DEX` | `NOT_EXECUTABLE` | listed only on DEXs outside your trade DEXs; legacy treats its volume as 0 |
| `NO_SUPPORTED_CANDLES` | `INSUFFICIENT_DATA` | no candle source (MEXC, Gate.io, Bitget, Hyperliquid, Aster) returned candles for this asset |
| `PRICE_SCALE_CONFLICT` | `INSUFFICIENT_DATA` | candle prices do not match the DEX price (another asset under the same symbol); the source was skipped |
| `INSUFFICIENT_1H_HISTORY` | `INSUFFICIENT_DATA` | fewer closed 1h candles than the radar's stage 1 needs |
| `INSUFFICIENT_15M_HISTORY` | `INSUFFICIENT_DATA` | fewer closed 15m candles than the radar's deep dive needs |
| `INSUFFICIENT_4H_HISTORY` | `INSUFFICIENT_DATA` | fewer closed 4h candles than the engine needs |
| `INSUFFICIENT_30D_HISTORY` | `INSUFFICIENT_DATA` | less than 30 days of history (quant eligibility) |
| `INSUFFICIENT_90D_HISTORY` | `INSUFFICIENT_DATA` | less than 90 daily candles (swing checks) |
| `LAST_DAY_NOT_SYNCED` | `INSUFFICIENT_DATA` | the asset's last complete day is older than the scan's last day (stale candles) |
| `SWING_INPUTS_UNAVAILABLE` | `INSUFFICIENT_DATA` | a swing input (range, RSI, squeeze, ATR) could not be computed |
| `NO_HOURLY_CANDLES` | `INSUFFICIENT_DATA` | not enough closed hourly candles for the day-trade checks |
| `REF_VOLUME_BELOW_LEGACY_MIN` | `MODEL_INELIGIBLE` | reference (CEX candle) volume below the legacy minimum |
| `RADAR_STAGE2_NOT_SELECTED` | `REJECTED` | liquid, but outside the stage-1 top N and not an extra |
| `NO_STRATEGY_SIGNAL` | `REJECTED` | evaluated; no strategy fired on the latest closed candles |
| `STOP_TOO_WIDE` | `REJECTED` | a strategy fired but its stop is wider than the maximum risk allowed |
| `STOP_ABOVE_PRICE` | `REJECTED` | a strategy fired but the price is already at or below the stop |
| `PAST_TARGET` | `REJECTED` | a strategy fired but the price is already past the first target |
| `VARIANT_FILTER_NOT_MET` | `REJECTED` | a strategy variant fired but its own filter did not pass |
| `MARKET_GATE_BLOCKED` | `REJECTED` | signals blocked by the market gate |
| `STRATEGY_NOT_PASSED` | `REJECTED` | signals come from strategies that have not passed their test; paper only |
| `VARIANT_FORWARD_TEST` | `REJECTED` | signal from a new variant in its live test; paper only |
| `ADJUSTMENT_BLOCKED` | `REJECTED` | a learned adjustment blocked the signal |
| `SCORE_BELOW_THRESHOLD` | `REJECTED` | score below the publishing threshold and not in the watch slots |
| `OUTPUT_TOP_N_CUTOFF` | `REJECTED` | qualified, but cut by the number of published slots |
| `RADAR_PICK` | `SURFACED` | published as a radar pick |
| `RADAR_WATCH` | `WATCHED` | published on the radar watch list |
| `QUANT_NEW_SIGNAL` | `SURFACED` | new quant signal this scan (paper trade opened) |
| `QUANT_POSITION_OPEN` | `SURFACED` | an open quant position is published |
| `QUANT_SIGNAL_NOT_ACTED` | `REJECTED` | a strategy is in signal state but no trade was opened: the bar was processed in an earlier scan (quant acts on new bars only) or the strategy's last trade on this coin is too recent |
| `SWING_READY` | `SURFACED` | listed with a Ready or Strong swing score |
| `SWING_SETTING_UP` | `WATCHED` | listed with a Setting-up swing score |
| `DAY_READY` | `SURFACED` | listed with Good or Best day-trade conditions |
| `DAY_SETTING_UP` | `WATCHED` | listed with Setting-up day-trade conditions |
| `LISTED_BELOW_WATCH` | `REJECTED` | listed in a top list, but with a Weak score |
| `DAY_CANDIDATE_NOT_SELECTED` | `REJECTED` | not among the most liquid coins and swing score below 60 |
| `SMART_CROWD_SIGNAL` | `SURFACED` | proven traders crowd into the tested side: a smart-money signal |
| `SMART_CROWD_INFO` | `WATCHED` | proven traders crowd into the untested side: information only |
| `SMART_NO_CROWD` | `REJECTED` | held by proven traders, no crowd of new entries under the rule |
| `SMART_POSITIONS_BELOW_MIN` | `REJECTED` | proven traders hold it only in positions below the minimum size |
| `SMART_NOT_HELD` | `REJECTED` | listed on Hyperliquid, not held by any proven trader read this scan |
| `SMART_VENUE_NOT_COVERED` | `MODEL_INELIGIBLE` | not listed on Hyperliquid; the smart-money engine reads Hyperliquid accounts only |
| `AUDIT_UNCLASSIFIED` | `INSUFFICIENT_DATA` | the audit could not classify this asset (an audit defect) |

## Step codes

Noted on a record next to its final disposition (field `x`); never a final disposition themselves.

| Code | Meaning |
|---|---|
| `PAPER_LIMIT_REACHED` | a paper trade was not opened: the open-trade limit was reached |
| `PAPER_BUSY` | a paper trade was not opened: one is already open on this coin |
| `PAPER_NO_PRICE` | a paper trade was not opened: no live price for the coin |
| `PAPER_BELOW_MIN_SCORE` | listed, below the paper-trade score minimum |
| `PAPER_OPENED` | a paper trade was opened this scan |
| `FUNDING_ASSUMED_DEFAULT` | no DEX funding observed; legacy paper costs assume the default funding rate |
| `FUNDING_MISSING_AS_ZERO` | no funding settlement found; legacy quant paper costs count it as 0 |
| `NOT_IN_PUBLISHED_LIST` | kept out of the published list by its length limit |
| `PLAN_REJECTED` | a strategy fired but its trade plan was rejected (see the plan list) |
| `EXTRA_DEEP_DIVE` | deep-dived as a stage-2 extra (smart money long or dip in an uptrend) |

## Smart-money trader outcomes

Counts per scan in the smart part (`traders.by_reason`), one per leaderboard row.

| Code | Meaning |
|---|---|
| `TRADER_SELECTED` | proven trader, read this scan |
| `TRADER_UNREADABLE` | proven trader whose account state could not be read |
| `TRADER_BAD_ADDRESS` | leaderboard row without a usable address |
| `TRADER_ACCOUNT_BELOW_MIN` | account value below the minimum |
| `TRADER_PNL_BELOW_MIN` | all-time profit below the minimum |
| `TRADER_MONTH_LOSS` | lost more than the allowed share of the account this month |
| `TRADER_MARKET_MAKER_OR_INACTIVE` | 30-day volume like a market maker's, or no volume at all |
| `TRADER_BEYOND_MAX` | proven, but beyond the maximum number of traders read |

## Where each legacy filter is recorded

| Legacy filter (unchanged in Phase 1) | Code(s) |
|---|---|
| Adapter skips: builder markets, delisted, inactive, non-perpetual, empty symbol | contract states `HL_BUILDER_MARKET`, `DELISTED`, `NOT_TRADING`, `NOT_PERPETUAL`, `EMPTY_SYMBOL`; asset `NO_ACTIVE_PERP_CONTRACT` |
| One market per asset and venue (highest volume kept) | contract state `DUPLICATE_NOT_SELECTED` |
| Price more than 20% from the main market | contract state `PRICE_CONFLICT_DROPPED` (CONFLICTED); asset `PRICE_CONFLICT_ALL_VENUES` |
| Tradfi tickers (lists, FX, venue category, name pattern) | `TRADFI_CLASSIFIED`, `TRADFI_TICKER_COLLISION` |
| No DEX market list at all (built-in coin list) | manifest `fallback_universe`, `FALLBACK_UNIVERSE` event |
| `liq_of(c) or 0 >= $1M` on your trade DEXs (radar stage 2, quant, picks) | `DEX_VOLUME_BELOW_LEGACY_MIN`, `DEX_VOLUME_MISSING_LEGACY_ZERO`, `NOT_ON_TRADE_DEX` |
| Candle source chain and price-scale check | `NO_SUPPORTED_CANDLES`, `PRICE_SCALE_CONFLICT` |
| Radar stage 1: 30 closed 1h candles | `INSUFFICIENT_1H_HISTORY` |
| Radar stage 2: top 40 liquid plus 16 extras | `RADAR_STAGE2_NOT_SELECTED`, step `EXTRA_DEEP_DIVE` |
| Radar deep dive: 60 closed 15m candles | `INSUFFICIENT_15M_HISTORY` |
| Strategy fired, plan rejected (stop too wide, below stop, past TP1) | `STOP_TOO_WIDE`, `STOP_ABOVE_PRICE`, `PAST_TARGET`, step `PLAN_REJECTED` |
| Variant filters | `VARIANT_FILTER_NOT_MET` |
| Market gate, strategy status, forward test, learned adjustments | `MARKET_GATE_BLOCKED`, `STRATEGY_NOT_PASSED`, `VARIANT_FORWARD_TEST`, `ADJUSTMENT_BLOCKED` |
| Minimum pick score, top 10, 8 watch slots | `SCORE_BELOW_THRESHOLD`, `OUTPUT_TOP_N_CUTOFF`, `RADAR_PICK`, `RADAR_WATCH` |
| Quant: 4h candles, 30 days, $5M reference volume, stop above 20%, XSMOM rank, new bars only | `INSUFFICIENT_4H_HISTORY`, `INSUFFICIENT_30D_HISTORY`, `REF_VOLUME_BELOW_LEGACY_MIN`, `STOP_TOO_WIDE`, `NO_STRATEGY_SIGNAL` (with the XSMOM rank), `QUANT_SIGNAL_NOT_ACTED`, `QUANT_NEW_SIGNAL`, `QUANT_POSITION_OPEN` |
| Picks: last-day sync, $5M last-day volume, 90 daily candles, swing inputs | `LAST_DAY_NOT_SYNCED` (STALE), `REF_VOLUME_BELOW_LEGACY_MIN`, `INSUFFICIENT_90D_HISTORY`, `SWING_INPUTS_UNAVAILABLE` |
| Picks: day candidates (top 50 liquid or swing 60+), hourly candles, top-10 lists, labels | `DAY_CANDIDATE_NOT_SELECTED`, `NO_HOURLY_CANDLES`, `SWING_READY`, `SWING_SETTING_UP`, `DAY_READY`, `DAY_SETTING_UP`, `LISTED_BELOW_WATCH`, `OUTPUT_TOP_N_CUTOFF`, `SCORE_BELOW_THRESHOLD` |
| Picks paper trades (80+ swing, 85+ day) | step `PAPER_OPENED` |
| Smart: trader eligibility, $10k position minimum, entry rule, 60 published rows, 12 open paper trades | trader outcomes above, `SMART_POSITIONS_BELOW_MIN`, `SMART_CROWD_SIGNAL`, `SMART_CROWD_INFO`, `SMART_NO_CROWD`, steps `NOT_IN_PUBLISHED_LIST`, `PAPER_LIMIT_REACHED`, `PAPER_BUSY`, `PAPER_NO_PRICE`, `PAPER_OPENED` |
