# v9 phase C: live market context

`v9/market.py` collects a market-context document (`v9.market/1`) on every scan and publishes it at
`data/v9/market.json`. Its rules:

- It is context only. No engine and no decision reads it, which `tests/test_v9_market.py` checks.
- Whether any of these numbers deserves decision authority is a phase D question for the survivorship-free evidence
  engine.

## Sources

All sources are free and public, need no login, and were verified from the Actions runner (`docs/v9/data-sources.md`).

| Field | Source | Note |
|---|---|---|
| Funding, open interest, premium, 24h volume and change for every Hyperliquid perp | Hyperliquid `metaAndAssetCtxs` | Hourly funding × 8, reported per 8 hours |
| Binance and Bybit next funding per coin | Hyperliquid `predictedFundings` | Binance and Bybit refuse US cloud runners; this feed carries their rates, scaled from each venue's interval |
| Perps at their open-interest cap | Hyperliquid `perpsAtOpenInterestCap` | |
| Open interest and its 24h change, account and top-trader long/short ratios, taker buy/sell ratio, long and short liquidations over 24h | Gate `contract_stats` (hourly) | For the 30 most traded coins |
| BTC and ETH implied volatility (DVOL), with 24h and 7-day change | Deribit | |
| Crypto Fear & Greed (daily) | alternative.me | |
| Total stablecoin supply, with 7-day and 30-day change | DefiLlama | |
| Coinbase and Korea premiums on BTC | Coinbase, Upbit and open.er-api, against Binance spot (`data-api.binance.vision`) | USDT is taken at par with USD |
| BTC margin longs and shorts | Bitfinex | |
| Total market cap and dominance | CoinGecko global | Uses the `COINGECKO_API_KEY` demo key secret |
| US spot BTC ETF daily net flows | Farside's public table | Best effort: an HTML page |

## Guarantees

- Every source reports its status, latency and fetch time.
- A failed source leaves only its own fields missing. Missing is never zero.
- The collector never raises, and a failure never stops the scan (`continue-on-error`).
- Nothing is labelled bullish or bearish.
- The file carries its own `fresh_until`. After that time the desk shows it as stale, and the desk keeps no TTL of its
  own.

## Where it shows

- **Today:** a "Market context" panel at the top of the right rail.
- **Analyzer:** each coin's funding on Hyperliquid, Binance and Bybit, its open interest, Gate positioning and
  liquidations, marked "context, not part of the call".

## History

The first scan of every UTC hour adds `market/YYYY/MM/DD/HH.json.gz` (`v9.market-history/1`) to the
`v9-market-history` branch. The branch is append-only and pushed without `--force`.

Each record holds:

- the regime;
- every source's status;
- one row per coin trading at least $1M a day.

This is the forward record that phase D research needs, for positioning, funding extremes and liquidations.

The "Market context check" workflow (`market.yml`) runs the collector on a v9 branch push. It saves the output on
`market-results`, and its history on `v9-market-history-dryrun`.
