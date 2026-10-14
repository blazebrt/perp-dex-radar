# v9 data sources (verified from the GitHub Actions runner)

Every source below was called by `tools/v9/probe_sources.py` from a GitHub-hosted runner (US, Azure), where the scans run, on 2026-10-14 10:53 UTC. Status is what came back. Re-run the probe (push to a v9 branch, or Actions > Data source probe) to refresh; results land on the `probe-results` branch.

Rules: official free public endpoints first; respect rate limits and terms; never scrape behind a login; a source that needs a key is used only when its key is a repository secret.

| Source | Group | Status | Provides | History | Access | v9 use |
|---|---|---|---|---|---|---|
| `binance.fapi.exchangeInfo` | Binance | blocked/failed (451) | USD-M symbols, filters, onboard dates | live | free, no key | blocked for US runners (451): use the archive and other venues |
| `binance.fapi.premiumIndex` | Binance | blocked/failed (451) | mark, index, live funding | live | free | blocked (451) |
| `binance.fapi.fundingRate` | Binance | blocked/failed (451) | funding settlements | since listing | free | blocked (451): archive fundingRate instead |
| `binance.futures.openInterestHist` | Binance | blocked/failed (451) | OI 5m-1d | 30 days | free | blocked (451): archive metrics instead |
| `binance.futures.topLongShortAccountRatio` | Binance | blocked/failed (451) | top-trader L/S | 30 days | free | blocked (451): archive metrics instead |
| `binance.futures.takerlongshortRatio` | Binance | blocked/failed (451) | taker buy/sell ratio | 30 days | free | blocked (451): archive klines taker volume instead |
| `binance.spot.data-api.klines` | Binance | OK | spot candles (market data only) | full | free, no key | spot reference prices, Coinbase premium |
| `binance.vision.s3.list.um.monthly.klines` | Binance archive | OK | listing of every USD-M symbol ever traded | 2019+ | free, no key | point-in-time universe incl. delisted |
| `binance.vision.um.monthly.klines.1d` | Binance archive | OK | candles 1m-1mo, quote and taker volume | 2019/2020+ | free, no key | evidence engine (survivorship-free history) |
| `binance.vision.um.monthly.klines.delisted` | Binance archive | OK | candles of delisted symbols | listing to delisting | free, no key | evidence engine: no survivorship |
| `binance.vision.um.monthly.fundingRate` | Binance archive | OK | every funding settlement | since listing | free, no key | observed funding in backtests |
| `binance.vision.um.daily.metrics` | Binance archive | OK | 5-min OI, OI value, top-trader and account L/S, taker L/S ratio | daily files; start date per symbol to be measured | free, no key | positioning signals research (OI, crowding) |
| `binance.vision.um.monthly.premiumIndexKlines` | Binance archive | OK | premium index candles (basis) | since listing | free, no key | basis/premium signals |
| `binance.vision.um.daily.bookDepth` | Binance archive | OK | order-book depth snapshots by % band | recent years | free, no key | slippage model calibration |
| `bybit.v5.tickers` | Bybit | blocked/failed (403) | tickers, OI, funding | live | free | blocked for cloud IPs (403 CDN) |
| `bybit.v5.open-interest` | Bybit | blocked/failed (403) | OI history | limited | free | blocked (403) |
| `bybit.v5.account-ratio` | Bybit | blocked/failed (403) | account L/S | limited | free | blocked (403) |
| `bybit.bytick.tickers` | Bybit | blocked/failed (403) | alternate domain | live | free | blocked (403) |
| `bybit.public.archive` | Bybit archive | OK | daily trade files per symbol | 2020+ | free, no key | trade-level history (heavy); optional |
| `okx.instruments.swap` | OKX | OK | swap instruments | live | free, no key | venue universe |
| `okx.funding-rate-history` | OKX | OK | funding settlements | 3 months | free, no key | multi-venue funding |
| `okx.history-candles` | OKX | OK | candles | years | free, no key | cross-venue price check |
| `okx.rubik.oi-history` | OKX | OK | OI history | days to months by period | free, no key | OI signals (live) |
| `okx.rubik.long-short-account-ratio-contract` | OKX | OK | account L/S per contract | 1,440 points | free, no key | crowding signals (live) |
| `okx.rubik.taker-volume-contract` | OKX | OK | taker buy/sell volume | 1,440 points | free, no key | order-flow signals (live) |
| `okx.liquidation-orders` | OKX | OK | public liquidation orders | recent | free, no key | liquidation signals (live, record forward) |
| `hl.meta` | Hyperliquid | OK | Hyperliquid perps incl. isDelisted | live | free, no key | execution venue universe |
| `hl.metaAndAssetCtxs` | Hyperliquid | OK | mark, OI, funding, premium, volume per perp | live | free, no key | execution venue state |
| `hl.candleSnapshot.BTC.1d` | Hyperliquid | OK | candles (last 5,000 per interval) | 1d since 2022; 4h ~830 days | free, no key | execution-venue backtests (delisted included) |
| `hl.fundingHistory.BTC` | Hyperliquid | OK | hourly funding | since listing (500/page) | free, no key | execution-venue funding |
| `hl.predictedFundings` | Hyperliquid | OK | predicted funding across venues (HL, Binance, Bybit) | live | free, no key | cross-venue funding without Binance/Bybit access |
| `hl.perpsAtOpenInterestCap` | Hyperliquid | OK | perps at OI cap | live | free, no key | crowding flag |
| `hl.leaderboard` | Hyperliquid | OK | trader leaderboard (8 MB) | live | free, no key | smart money |
| `gate.contracts` | Gate.io | OK | contracts, funding, OI | live | free, no key | venue data |
| `gate.contract_stats` | Gate.io | OK | OI, L/S, liquidations per contract | months | free, no key | positioning + liquidations history |
| `gate.liq_orders` | Gate.io | OK | liquidation orders | recent | free, no key | liquidations |
| `gate.candles.1d` | Gate.io | OK | candles | years | free, no key | cross-venue history |
| `mexc.contract.detail` | MEXC | OK | contracts | live | free, no key | venue data |
| `mexc.funding.history` | MEXC | OK | funding settlements | long | free, no key | funding history |
| `bitget.tickers` | Bitget | OK | tickers, funding | live | free, no key | venue data |
| `bitget.history-fund-rate` | Bitget | OK | funding settlements | long | free, no key | funding history |
| `bitget.open-interest` | Bitget | OK | OI | live | free, no key | OI |
| `bitget.account-long-short` | Bitget | OK | account L/S | recent | free, no key | crowding |
| `kucoin.futures.contracts` | KuCoin | OK | contracts, funding, OI | live | free, no key | venue data |
| `htx.linear.contract_info` | HTX | OK | contracts | live | free, no key | venue data |
| `htx.linear.his_open_interest` | HTX | OK | OI history | recent | free, no key | OI |
| `htx.linear.elite_account_ratio` | HTX | OK | top-account L/S | recent | free, no key | crowding |
| `kraken.futures.tickers` | Kraken | OK | tickers, funding, OI | live | free, no key | venue data |
| `deribit.dvol` | Deribit | OK | DVOL implied-volatility index | years | free, no key | volatility regime |
| `deribit.book_summary.options` | Deribit | OK | options book summary (IV, OI) | live | free, no key | options positioning, put/call |
| `deribit.funding_rate_history` | Deribit | OK | perp funding | long | free, no key | BTC/ETH funding |
| `dydx.perpetualMarkets` | dYdX | OK | markets, OI, funding | live | free, no key | venue data |
| `dydx.historicalFunding` | dYdX | OK | funding history | long | free, no key | funding |
| `aster.premiumIndex` | Aster | OK | mark, funding | live | free, no key | execution venue |
| `aster.openInterestHist` | Aster | blocked/failed (404) | OI history | - | free | not available (404) |
| `bitfinex.status.deriv` | Bitfinex | OK | perp funding, OI | live | free, no key | venue data |
| `bitfinex.stats.pos.size.long` | Bitfinex | OK | BTC margin longs/shorts | years | free, no key | BTC positioning signal |
| `coinbase.spot.candles` | Coinbase | OK | Coinbase spot candles | years | free, no key | Coinbase premium (US demand) |
| `coinbase.intl.instruments` | Coinbase | OK | Coinbase International perps | live | free, no key | venue data |
| `upbit.market.all` | Korea | OK | Upbit markets (new KRW listings) | live | free, no key | listing events, Korea premium |
| `upbit.ticker.btc` | Korea | OK | Upbit ticker | live | free, no key | Korea premium |
| `bithumb.ticker.all` | Korea | OK | Bithumb tickers | live | free, no key | Korea premium |
| `coingecko.global` | CoinGecko | OK | total market cap, dominance | live | free demo key (secret present) | regime |
| `coingecko.markets` | CoinGecko | OK | market cap, supply, ATH | 365 days on demo | free demo key | fundamentals, unlock proxy |
| `coingecko.derivatives` | CoinGecko | OK | derivatives tickers across exchanges incl. Binance/Bybit funding and OI | live | free demo key | cross-venue funding/OI where Binance/Bybit APIs are blocked |
| `coinpaprika.global` | CoinPaprika | OK | global market data | live | free, no key | backup fundamentals |
| `coinpaprika.tickers` | CoinPaprika | OK | tickers | live | free, no key | backup fundamentals |
| `coinlore.tickers` | CoinLore | OK | tickers | live | free, no key | backup fundamentals |
| `cryptocompare.histoday` | CryptoCompare | blocked/failed (401) | history | - | key required | not used (401) |
| `defillama.oi.overview` | DefiLlama | OK | open interest across protocols | years | free, no key | DEX perp OI |
| `defillama.derivatives.overview` | DefiLlama | blocked/failed (402) | perp volumes | - | pro only (402) | not used |
| `defillama.dexs.overview` | DefiLlama | OK | DEX volumes | years | free, no key | on-chain activity |
| `defillama.stablecoincharts.all` | DefiLlama | OK | total stablecoin supply | years | free, no key | liquidity regime (stablecoin flows) |
| `defillama.coins.current` | DefiLlama | OK | token prices | live | free, no key | backup prices |
| `defillama.emissions` | DefiLlama | blocked/failed (402) | token unlocks | - | pro only (402) | not used; CoinGecko supply growth instead |
| `dexscreener.boosts` | DEX | OK | boosted/trending tokens | live | free, no key | early-trend discovery (context only) |
| `geckoterminal.trending` | DEX | OK | trending pools | live | free, no key | early-trend discovery (context only) |
| `polymarket.markets` | Prediction | OK | prediction-market odds | live | free, no key | event risk context |
| `alternative.fng` | Sentiment | OK | Crypto Fear & Greed | since 2018 | free, no key | sentiment regime |
| `cnn.fear-greed` | Sentiment | blocked/failed (418) | stock Fear & Greed | - | blocked (418) | not used |
| `apewisdom.crypto` | Sentiment | OK | social mention ranks | live | free, no key | sentiment |
| `stocktwits.btc` | Sentiment | OK | Stocktwits stream | live | free, no key | sentiment |
| `reddit.cryptocurrency` | Sentiment | blocked/failed (403) | Reddit posts | - | blocked (403) | not used without OAuth |
| `cryptopanic.posts` | News | needs key | news with votes | recent | free key (developer plan) | news events (needs CRYPTOPANIC_API_KEY) |
| `rss.coindesk` | News | OK | news RSS | recent | free | news |
| `rss.cointelegraph` | News | OK | news RSS | recent | free | news |
| `rss.theblock` | News | OK | news RSS | recent | free | news |
| `rss.decrypt` | News | OK | news RSS | recent | free | news |
| `mempool.fees` | On-chain | OK | BTC fee market | live | free, no key | on-chain activity |
| `mempool.hashrate` | On-chain | OK | BTC hashrate | years | free, no key | on-chain context |
| `blockchain.charts.hashrate` | On-chain | OK | BTC charts | years | free, no key | on-chain context |
| `farside.btc.etf` | ETF flows | OK | US spot BTC ETF daily flows (HTML table) | Jan 2024+ | free page (no stated terms) | institutional flow regime |
| `yahoo.dxy` | Macro | OK | DXY | years | free (unofficial) | macro regime |
| `yahoo.spx` | Macro | OK | S&P 500 | years | free (unofficial) | macro regime |
| `fx.open-er-api` | Macro | OK | FX rates | live | free, no key | KRW for Korea premium |
| `tardis.free.derivative_ticker` | Tardis (free 1st of month) | OK | tick-level funding/OI/mark (1st of each month free) | 2019+ | free sample days | model validation only |
| `tardis.free.liquidations` | Tardis (free 1st of month) | OK | liquidations (1st of each month free) | 2019+ | free sample days | liquidation model validation |
| `coinalyze.future-markets` | Coinalyze (free key) | needs key | aggregated OI, funding, predicted funding, liquidations, L/S across exchanges; daily history kept | intraday ~1,500-2,000 points; daily unlimited | free with a key (40 calls/min) | the best free liquidation history: needs COINALYZE_API_KEY |
| `cmc.global-metrics` | CoinMarketCap (free key) | needs key | global metrics | live | free key | optional |
| `fred.dgs10` | FRED (free key) | needs key | US 10y yield and macro series | decades | free key | macro regime (optional) |
| `etherscan.ethsupply` | Etherscan (free key) | needs key | ETH on-chain data | full | free key | optional |
| `ipinfo` | Runner | OK | runner location | - | free | the probe ran from a US (Azure) runner |

## Survivorship-free history

- Binance archive: 1056 USD-M symbols listed in the archive, 900 USDT perpetuals, including delisted ones (sample first/last months in sources.json).
- Hyperliquid: 234 perps in `meta`, 56 flagged `isDelisted`; their daily candles still load (e.g. FTM 861 days, MATIC 736 days, RNDR 535 days).

