| Source | Group | Status | ms | Bytes | Shape |
|---|---|---|---|---|---|
| binance.fapi.exchangeInfo | Binance | 451 | 171 | 224 | {"dict_keys": ["code", "msg"], "first": "int"} |
| binance.fapi.premiumIndex | Binance | 451 | 149 | 224 | {"dict_keys": ["code", "msg"], "first": "int"} |
| binance.fapi.fundingRate | Binance | 451 | 150 | 224 | {"dict_keys": ["code", "msg"], "first": "int"} |
| binance.futures.openInterestHist | Binance | 451 | 149 | 224 | {"dict_keys": ["code", "msg"], "first": "int"} |
| binance.futures.topLongShortAccountRatio | Binance | 451 | 145 | 224 | {"dict_keys": ["code", "msg"], "first": "int"} |
| binance.futures.takerlongshortRatio | Binance | 451 | 160 | 224 | {"dict_keys": ["code", "msg"], "first": "int"} |
| binance.spot.data-api.klines | Binance | 200 | 555 | 923 | {"list_len": 5, "first": {"list_len": 12, "first": "int"}} |
| binance.vision.s3.list.um.monthly.klines | Binance archive | 200 | 849 | 90809 | {"prefixes": 1000, "truncated": true, "sample": ["data/futures/um/monthly/klines/0GUSDT/", "data/futures/um/monthly/klines/1000000BOBUSDT/", "data/futures/um/mo |
| binance.vision.um.monthly.klines.1d | Binance archive | 200 | 477 | 2139 | {"zip_files": ["BTCUSDT-1d-2024-01.csv"], "rows": 32, "head": ["open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_qu |
| binance.vision.um.monthly.klines.delisted | Binance archive | 200 | 481 | 1693 | {"zip_files": ["SRMUSDT-1d-2022-06.csv"], "rows": 31, "head": ["open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_qu |
| binance.vision.um.monthly.fundingRate | Binance archive | 200 | 471 | 696 | {"zip_files": ["BTCUSDT-fundingRate-2024-01.csv"], "rows": 94, "head": ["calc_time,funding_interval_hours,last_funding_rate", "1704067200000,8,0.00037409", "170 |
| binance.vision.um.daily.metrics | Binance archive | 200 | 244 | 11639 | {"zip_files": ["BTCUSDT-metrics-2024-01-15.csv"], "rows": 289, "head": ["create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short |
| binance.vision.um.monthly.premiumIndexKlines | Binance archive | 200 | 344 | 1103 | {"zip_files": ["BTCUSDT-1d-2024-01.csv"], "rows": 32, "head": ["open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_qu |
| binance.vision.um.daily.bookDepth | Binance archive | 200 | 766 | 477151 | {"zip_files": ["BTCUSDT-bookDepth-2024-01-15.csv"], "rows": 28801, "head": ["timestamp,percentage,depth,notional", "2024-01-15 00:00:12,-5,12251.47300000,499565 |
| bybit.v5.tickers | Bybit | 403 | 50 | 96 | {"text_bytes": 96, "title": null, "cloudflare": false, "items": 0} |
| bybit.v5.open-interest | Bybit | 403 | 49 | 96 | {"text_bytes": 96, "title": null, "cloudflare": false, "items": 0} |
| bybit.v5.account-ratio | Bybit | 403 | 32 | 96 | {"text_bytes": 96, "title": null, "cloudflare": false, "items": 0} |
| bybit.bytick.tickers | Bybit | 403 | 35 | 96 | {"text_bytes": 96, "title": null, "cloudflare": false, "items": 0} |
| bybit.public.archive | Bybit archive | 200 | 543 | 175089 | {"text_bytes": 175089, "title": "Directory listing for /trading/BTCUSDT", "cloudflare": false, "items": 0} |
| okx.instruments.swap | OKX | 200 | 189 | 541147 | {"dict_keys": ["code", "data", "msg"], "first": "str"} |
| okx.funding-rate-history | OKX | 200 | 153 | 1015 | {"dict_keys": ["code", "data", "msg"], "first": "str"} |
| okx.history-candles | OKX | 200 | 150 | 563 | {"dict_keys": ["code", "data", "msg"], "first": "str"} |
| okx.rubik.oi-history | OKX | 200 | 283 | 474 | {"dict_keys": ["code", "data", "msg"], "first": "str"} |
| okx.rubik.long-short-account-ratio-contract | OKX | 200 | 228 | 225 | {"dict_keys": ["code", "data", "msg"], "first": "str"} |
| okx.rubik.taker-volume-contract | OKX | 200 | 247 | 356 | {"dict_keys": ["code", "data", "msg"], "first": "str"} |
| okx.liquidation-orders | OKX | 200 | 221 | 776 | {"dict_keys": ["code", "data", "msg"], "first": "str"} |
| hl.meta | Hyperliquid | 200 | 246 | 17628 | {"dict_keys": ["universe", "marginTables", "collateralToken"], "first": {"list_len": 234, "first": {"dict_keys": ["szDecimals", "name", "maxLeverage", "marginTa |
| hl.metaAndAssetCtxs | Hyperliquid | 200 | 249 | 72271 | {"list_len": 2, "first": {"dict_keys": ["universe", "marginTables", "collateralToken"], "first": {"list_len": 234}}} |
| hl.candleSnapshot.BTC.1d | Hyperliquid | 200 | 559 | 305965 | {"list_len": 2248, "first": {"dict_keys": ["t", "T", "s", "i", "o", "c", "h", "l", "v", "n"], "first": "int"}} |
| hl.fundingHistory.BTC | Hyperliquid | 200 | 242 | 44343 | {"list_len": 500, "first": {"dict_keys": ["coin", "fundingRate", "premium", "time"], "first": "str"}} |
| hl.predictedFundings | Hyperliquid | 200 | 184 | 64100 | {"list_len": 234, "first": {"list_len": 2, "first": "str"}} |
| hl.perpsAtOpenInterestCap | Hyperliquid | 200 | 175 | 53 | {"list_len": 7, "first": "str"} |
| hl.leaderboard | Hyperliquid | 200 | 39 | 8000000 | {"text_bytes": 7999950, "title": null, "cloudflare": false, "items": 0} |
| gate.contracts | Gate.io | 200 | 1524 | 1337676 | {"list_len": 1038, "first": {"dict_keys": ["funding_rate_indicative", "mark_price_round", "funding_offset", "in_delisting", "risk_limit_base", "interest_rate",  |
| gate.contract_stats | Gate.io | 200 | 589 | 3265 | {"list_len": 5, "first": {"dict_keys": ["time", "lsr_taker", "lsr_account", "long_liq_size", "short_liq_size", "open_interest", "short_liq_usd", "mark_price", " |
| gate.liq_orders | Gate.io | 200 | 470 | 652 | {"list_len": 5, "first": {"dict_keys": ["contract", "left", "size", "order_size", "fill_price", "order_price", "time"], "first": "str"}} |
| gate.candles.1d | Gate.io | 200 | 470 | 547 | {"list_len": 5, "first": {"dict_keys": ["o", "v", "t", "c", "l", "h", "sum"], "first": "str"}} |
| mexc.contract.detail | MEXC | 200 | 197 | 2307621 | {"dict_keys": ["success", "code", "data"], "first": "bool"} |
| mexc.funding.history | MEXC | 200 | 189 | 558 | {"dict_keys": ["success", "code", "data"], "first": "bool"} |
| bitget.tickers | Bitget | 200 | 277 | 420518 | {"dict_keys": ["code", "msg", "requestTime", "data"], "first": "str"} |
| bitget.history-fund-rate | Bitget | 200 | 261 | 449 | {"dict_keys": ["code", "msg", "requestTime", "data"], "first": "str"} |
| bitget.open-interest | Bitget | 200 | 287 | 161 | {"dict_keys": ["code", "msg", "requestTime", "data"], "first": "str"} |
| bitget.account-long-short | Bitget | 200 | 153 | 3451 | {"dict_keys": ["code", "msg", "requestTime", "data"], "first": "str"} |
| kucoin.futures.contracts | KuCoin | 200 | 254 | 1436618 | {"dict_keys": ["code", "data"], "first": "str"} |
| htx.linear.contract_info | HTX | 200 | 442 | 526 | {"dict_keys": ["status", "data", "ts"], "first": "str"} |
| htx.linear.his_open_interest | HTX | 200 | 410 | 713 | {"dict_keys": ["status", "data", "ts"], "first": "str"} |
| htx.linear.elite_account_ratio | HTX | 200 | 414 | 2620 | {"dict_keys": ["status", "data", "ts"], "first": "str"} |
| kraken.futures.tickers | Kraken | 200 | 197 | 134495 | {"dict_keys": ["result", "serverTime", "tickers"], "first": "str"} |
| deribit.dvol | Deribit | 200 | 190 | 3017 | {"dict_keys": ["jsonrpc", "result", "usIn", "usOut", "usDiff", "testnet"], "first": "str"} |
| deribit.book_summary.options | Deribit | 200 | 252 | 397724 | {"dict_keys": ["jsonrpc", "result", "usIn", "usOut", "usDiff", "testnet"], "first": "str"} |
| deribit.funding_rate_history | Deribit | 200 | 160 | 3586 | {"dict_keys": ["jsonrpc", "result", "usIn", "usOut", "usDiff", "testnet"], "first": "str"} |
| dydx.perpetualMarkets | dYdX | 200 | 32 | 167173 | {"dict_keys": ["markets"], "first": {"dict_keys": ["BTC-USD", "ETH-USD", "LINK-USD", "MATIC-USD", "CRV-USD", "SOL-USD", "ADA-USD", "AVAX-USD", "FIL-USD", "LTC-U |
| dydx.historicalFunding | dYdX | 200 | 340 | 677 | {"dict_keys": ["historicalFunding"], "first": {"list_len": 5, "first": {"dict_keys": ["ticker", "rate", "price", "effectiveAtHeight", "effectiveAt"]}}} |
| aster.premiumIndex | Aster | 200 | 522 | 170510 | {"list_len": 784, "first": {"dict_keys": ["symbol", "markPrice", "indexPrice", "estimatedSettlePrice", "lastFundingRate", "interestRate", "nextFundingTime", "ti |
| aster.openInterestHist | Aster | 404 | 199 | 4000 | {"text_bytes": 4000, "title": null, "cloudflare": false, "items": 0} |
| bitfinex.status.deriv | Bitfinex | 200 | 115 | 198 | {"list_len": 1, "first": {"list_len": 24, "first": "str"}} |
| bitfinex.stats.pos.size.long | Bitfinex | 200 | 489 | 156 | {"list_len": 5, "first": {"list_len": 2, "first": "int"}} |
| coinbase.spot.candles | Coinbase | 200 | 47 | 21466 | {"list_len": 350, "first": {"list_len": 6, "first": "int"}} |
| coinbase.intl.instruments | Coinbase | 200 | 1215 | 447585 | {"list_len": 310, "first": {"dict_keys": ["instrument_id", "instrument_uuid", "symbol", "type", "mode", "base_asset_id", "base_asset_uuid", "base_asset_name", " |
| upbit.market.all | Korea | 200 | 840 | 67455 | {"list_len": 869, "first": {"dict_keys": ["market", "korean_name", "english_name"], "first": "str"}} |
| upbit.ticker.btc | Korea | 200 | 582 | 829 | {"list_len": 1, "first": {"dict_keys": ["market", "trade_date", "trade_time", "trade_date_kst", "trade_time_kst", "trade_timestamp", "opening_price", "high_pric |
| bithumb.ticker.all | Korea | 200 | 910 | 170653 | {"dict_keys": ["status", "data"], "first": "str"} |
| coingecko.global | CoinGecko | 200 | 118 | 3358 | {"dict_keys": ["data"], "first": {"dict_keys": ["active_cryptocurrencies", "upcoming_icos", "ongoing_icos", "ended_icos", "markets", "total_market_cap", "total_ |
| coingecko.markets | CoinGecko | 200 | 330 | 3925 | {"list_len": 5, "first": {"dict_keys": ["id", "symbol", "name", "image", "current_price", "market_cap", "market_cap_rank", "fully_diluted_valuation", "total_vol |
| coingecko.derivatives | CoinGecko | 200 | 149 | 8000000 | {"text_bytes": 7999576, "title": null, "cloudflare": false, "items": 0} |
| coinpaprika.global | CoinPaprika | 200 | 116 | 455 | {"dict_keys": ["market_cap_usd", "volume_24h_usd", "bitcoin_dominance_percentage", "cryptocurrencies_number", "market_cap_ath_value", "market_cap_ath_date", "vo |
| coinpaprika.tickers | CoinPaprika | 200 | 214 | 4054 | {"list_len": 5, "first": {"dict_keys": ["id", "name", "symbol", "rank", "total_supply", "max_supply", "beta_value", "first_data_at", "last_updated", "quotes"],  |
| coinlore.tickers | CoinLore | 200 | 564 | 1886 | {"dict_keys": ["data", "info"], "first": {"list_len": 5, "first": {"dict_keys": ["id", "symbol", "name", "nameid", "rank", "price_usd", "percent_change_24h", "p |
| cryptocompare.histoday | CryptoCompare | 401 | 191 | 273 | {"dict_keys": ["Data", "Err"], "first": {"dict_keys": []}} |
| defillama.oi.overview | DefiLlama | 200 | 110 | 1070208 | {"dict_keys": ["totalDataChart", "totalDataChartBreakdown", "breakdown24h", "breakdown30d", "chain", "allChains", "total24h", "total48hto24h", "total7d", "total |
| defillama.derivatives.overview | DefiLlama | 402 | 77 | 66 | {"text_bytes": 66, "title": null, "cloudflare": false, "items": 0} |
| defillama.dexs.overview | DefiLlama | 200 | 138 | 2222024 | {"dict_keys": ["totalDataChart", "totalDataChartBreakdown", "breakdown24h", "breakdown30d", "chain", "allChains", "total24h", "total48hto24h", "total7d", "total |
| defillama.stablecoincharts.all | DefiLlama | 200 | 39 | 1316562 | {"list_len": 3242, "first": {"dict_keys": ["date", "totalCirculating", "totalCirculatingUSD"], "first": "str"}} |
| defillama.coins.current | DefiLlama | 200 | 46 | 221 | {"dict_keys": ["coins"], "first": {"dict_keys": ["coingecko:bitcoin", "coingecko:ethereum"], "first": {"dict_keys": ["price", "symbol", "timestamp", "confidence |
| defillama.emissions | DefiLlama | 402 | 43 | 66 | {"text_bytes": 66, "title": null, "cloudflare": false, "items": 0} |
| dexscreener.boosts | DEX | 200 | 38 | 22975 | {"list_len": 30, "first": {"dict_keys": ["url", "chainId", "tokenAddress", "description", "icon", "header", "openGraph", "links", "totalAmount", "amount"], "fir |
| geckoterminal.trending | DEX | 200 | 47 | 31644 | {"dict_keys": ["data"], "first": {"list_len": 20, "first": {"dict_keys": ["id", "type", "attributes", "relationships"]}}} |
| polymarket.markets | Prediction | 200 | 46 | 28708 | {"list_len": 5, "first": {"dict_keys": ["id", "question", "conditionId", "slug", "resolutionSource", "endDate", "liquidity", "startDate", "image", "icon", "desc |
| alternative.fng | Sentiment | 200 | 226 | 577 | {"dict_keys": ["name", "data", "metadata"], "first": "str"} |
| cnn.fear-greed | Sentiment | 418 | 184 | 27 | {"text_bytes": 27, "title": null, "cloudflare": false, "items": 0} |
| apewisdom.crypto | Sentiment | 200 | 579 | 10374 | {"dict_keys": ["count", "pages", "current_page", "results"], "first": "int"} |
| stocktwits.btc | Sentiment | 200 | 146 | 90933 | {"dict_keys": ["symbol", "cursor", "regions", "filters", "messages", "response"], "first": {"dict_keys": ["id", "symbol", "symbol_mic", "symbol_display", "excha |
| reddit.cryptocurrency | Sentiment | 403 | 14 | 4000 | {"text_bytes": 4000, "title": null, "cloudflare": false, "items": 0} |
| cryptopanic.posts | News | NEEDS_KEY |  |  | "set CRYPTOPANIC_API_KEY to probe" |
| rss.coindesk | News | 200 | 118 | 30261 | {"text_bytes": 30242, "title": "CoinDesk: Bitcoin, Ethereum, Crypto News and Price Data", "cloudflare": false, "items": 25} |
| rss.cointelegraph | News | 200 | 43 | 52041 | {"text_bytes": 51913, "title": "Cointelegraph.com News", "cloudflare": false, "items": 30} |
| rss.theblock | News | 200 | 48 | 32674 | {"text_bytes": 32655, "title": "The Block", "cloudflare": false, "items": 19} |
| rss.decrypt | News | 200 | 49 | 36526 | {"text_bytes": 36500, "title": "Decrypt", "cloudflare": false, "items": 33} |
| mempool.fees | On-chain | 200 | 320 | 74 | {"dict_keys": ["fastestFee", "halfHourFee", "hourFee", "economyFee", "minimumFee"], "first": "int"} |
| mempool.hashrate | On-chain | 200 | 278 | 2132 | {"dict_keys": ["hashrates", "difficulty", "currentHashrate", "currentDifficulty"], "first": {"list_len": 30, "first": {"dict_keys": ["timestamp", "avgHashrate"] |
| blockchain.charts.hashrate | On-chain | 200 | 197 | 1457 | {"dict_keys": ["status", "name", "unit", "period", "description", "values"], "first": "str"} |
| farside.btc.etf | ETF flows | 200 | 1364 | 828522 | {"text_bytes": 828522, "title": "Bitcoin ETF Flow &#8211; All Data (US$m) &#8211; Farside Investors", "cloudflare": false, "items": 0} |
| yahoo.dxy | Macro | 200 | 58 | 3754 | {"dict_keys": ["chart"], "first": {"dict_keys": ["result", "error"], "first": {"list_len": 1}}} |
| yahoo.spx | Macro | 200 | 109 | 3423 | {"dict_keys": ["chart"], "first": {"dict_keys": ["result", "error"], "first": {"list_len": 1}}} |
| fx.open-er-api | Macro | 200 | 47 | 2963 | {"dict_keys": ["result", "provider", "documentation", "terms_of_use", "time_last_update_unix", "time_last_update_utc", "time_next_update_unix", "time_next_updat |
| tardis.free.derivative_ticker | Tardis (free 1st of month) | 200 | 981 | 1721805 | {"rows": 107024, "head": ["exchange,symbol,timestamp,local_timestamp,funding_timestamp,funding_rate,predicted_funding_rate,open_interest,last_price,index_price, |
| tardis.free.liquidations | Tardis (free 1st of month) | 200 | 781 | 20106 | {"rows": 1207, "head": ["exchange,symbol,timestamp,local_timestamp,id,side,price,amount", "binance-futures,BTCUSDT,1704067303193000,1704067303198088,,buy,42514. |
| coinalyze.future-markets | Coinalyze (free key) | NEEDS_KEY |  |  | "set COINALYZE_API_KEY to probe" |
| cmc.global-metrics | CoinMarketCap (free key) | NEEDS_KEY |  |  | "set CMC_API_KEY to probe" |
| fred.dgs10 | FRED (free key) | NEEDS_KEY |  |  | "set FRED_API_KEY to probe" |
| etherscan.ethsupply | Etherscan (free key) | NEEDS_KEY |  |  | "set ETHERSCAN_API_KEY to probe" |
| ipinfo | Runner | 200 | 92 | 268 | {"dict_keys": ["ip", "city", "region", "country", "loc", "org", "postal", "timezone", "readme"], "first": "str"} |

```json
{
 "hyperliquid_delisted": {
  "delisted": 56,
  "total": 234,
  "delisted_sample": [
   "MATIC",
   "RNDR",
   "FTM",
   "MKR",
   "FXS",
   "HPOS",
   "RLB",
   "UNIBOT",
   "OX",
   "FRIEND",
   "SHIA",
   "CYBER",
   "BLZ",
   "FTT",
   "LOOM"
  ],
  "delisted_candles": {
   "MATIC": {
    "n": 736,
    "first": 1662336000000,
    "last": 1725840000000
   },
   "RNDR": {
    "n": 535,
    "first": 1675382400000,
    "last": 1721520000000
   },
   "FTM": {
    "n": 861,
    "first": 1662336000000,
    "last": 1736640000000
   }
  }
 },
 "binance_archive": {
  "symbols": 1056,
  "perpetual": 1003,
  "usdt_perpetual": 900,
  "delivery": 53,
  "sample": [
   "0GUSDT",
   "1000000BOBUSDT",
   "1000000MOGUSDT",
   "1000BONKUSDT",
   "1000BTTCUSDT",
   "1000CATUSDT",
   "1000CHEEMSUSDT",
   "1000FLOKIUSDT",
   "1000LUNCUSDT",
   "1000PEPEUSDT",
   "1000RATSUSDT",
   "1000SATSUSDT",
   "1000SHIBUSDT",
   "1000WHYUSDT",
   "1000XECUSDT",
   "1000XUSDT",
   "1INCHUSDT",
   "1MBABYDOGEUSDT",
   "2ZUSDT",
   "42USDT"
  ],
  "sample_first_last_month": {
   "0GUSDT": [
    "2025-09",
    "2026-09"
   ],
   "AAOIUSDT": [
    "2026-06",
    "2026-09"
   ],
   "AIOTUSDT": [
    "2025-04",
    "2026-09"
   ],
   "ANCUSDT": [
    "2022-03",
    "2022-05"
   ],
   "ASRUSDT": [
    "2025-05",
    "2026-09"
   ],
   "B3USDT": [
    "2025-02",
    "2026-09"
   ],
   "BERAUSDT": [
    "2025-02",
    "2026-09"
   ],
   "BONDUSDT": [
    "2023-10",
    "2026-09"
   ],
   "BXUSDT": [
    "2026-06",
    "2026-09"
   ],
   "CHZUSDT": [
    "2021-01",
    "2026-09"
   ],
   "CRMLUSDT": [
    "2026-09",
    "2026-09"
   ],
   "DARUSDT": [
    "2022-04",
    "2026-09"
   ],
   "DOLOUSDT": [
    "2025-05",
    "2026-09"
   ],
   "EOSUSDT": [
    "2020-01",
    "2025-05"
   ],
   "FILUSDT": [
    "2020-10",
    "2026-09"
   ],
   "FXSUSDT": [
    "2023-01",
    "2026-09"
   ],
   "GRIFFAINUSDT": [
    "2025-01",
    "2026-09"
   ],
   "HIVEUSDT": [
    "2024-12",
    "2026-09"
   ],
   "ICXUSDT": [
    "2020-09",
    "2026-09"
   ],
   "JASMYUSDT": [
    "2022-04",
    "2026-09"
   ],
   "KNCUSDT": [
    "2020-06",
    "2026-09"
   ],
   "LLYUSDT": [
    "2026-06",
    "2026-09"
   ],
   "MATICUSDT": [
    "2020-10",
    "2024-09"
   ],
   "MITOUSDT": [
    "2025-08",
    "2026-09"
   ],
   "MVLLUSDT": [
    "2026-06",
    "2026-09"
   ],
   "NOTUSDT": [
    "2024-05",
    "2026-09"
   ],
   "ONTUSDT": [
    "2020-02",
    "2026-09"
   ],
   "PENGUSDT": [
    "2026-07",
    "2026-09"
   ],
   "POWERUSDT": [
    "2025-12",
    "2026-09"
   ],
   "RAREUSDT": [
    "2024-08",
    "2026-09"
   ],
   "ROBOUSDT": [
    "2026-02",
    "2026-09"
   ],
   "SENTUSDT": [
    "2025-11",
    "2026-09"
   ],
   "SNOWUSDT": [
    "2026-07",
    "2026-09"
   ],
   "SQQQUSDT": [
    "2026-06",
    "2026-09"
   ],
   "SWARMSUSDT": [
    "2025-01",
    "2026-09"
   ],
   "TLMUSDT": [
    "2021-07",
    "2026-09"
   ],
   "TSTUSDT": [
    "2025-02",
    "2026-09"
   ],
   "USELESSUSDT": [
    "2025-08",
    "2026-09"
   ],
   "WALUSDT": [
    "2025-03",
    "2026-09"
   ],
   "XLMUSDT": [
    "2020-01",
    "2026-09"
   ]
  }
 }
}
```
