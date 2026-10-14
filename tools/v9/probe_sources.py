"""Probe every candidate market-data source from where the scans run (GitHub Actions).

    python tools/v9/probe_sources.py --out probe

For each source: HTTP status, latency, bytes, content type, rate-limit headers, a short shape summary of the payload
(JSON keys / row counts) and a truncated sample. Sources that need a key are called only when the key is in the
environment (COINGECKO_API_KEY, COINALYZE_API_KEY, CRYPTOPANIC_API_KEY, CMC_API_KEY, FRED_API_KEY, ETHERSCAN_API_KEY,
DUNE_API_KEY); otherwise they are recorded as NEEDS_KEY. Read-only public market data; nothing is written anywhere
but --out. Results: probe/sources.json (machine) and probe/sources.md (a table)."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile

UA = "perp-dex-radar-probe/1.0 (+https://github.com/blazebrt/perp-dex-radar)"
NOW = int(time.time())
MS = NOW * 1000
DAY = 86400


def S(**kw):
    return kw


def sources():
    d1 = (NOW - 30 * DAY) * 1000
    hl = "https://api.hyperliquid.xyz/info"
    out = [
        # ---- Binance (USD-M futures API, spot data API, the public archive)
        S(id="binance.fapi.exchangeInfo", group="Binance", url="https://fapi.binance.com/fapi/v1/exchangeInfo"),
        S(id="binance.fapi.premiumIndex", group="Binance", url="https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"),
        S(id="binance.fapi.fundingRate", group="Binance", url="https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=5"),
        S(id="binance.futures.openInterestHist", group="Binance", url="https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=5"),
        S(id="binance.futures.topLongShortAccountRatio", group="Binance", url="https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=5"),
        S(id="binance.futures.takerlongshortRatio", group="Binance", url="https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=5"),
        S(id="binance.spot.data-api.klines", group="Binance", url="https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=5"),
        S(id="binance.vision.s3.list.um.monthly.klines", group="Binance archive", url="https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/monthly/klines/", kind="s3list"),
        S(id="binance.vision.um.monthly.klines.1d", group="Binance archive", url="https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01.zip", kind="zip"),
        S(id="binance.vision.um.monthly.klines.delisted", group="Binance archive", url="https://data.binance.vision/data/futures/um/monthly/klines/SRMUSDT/1d/SRMUSDT-1d-2022-06.zip", kind="zip"),
        S(id="binance.vision.um.monthly.fundingRate", group="Binance archive", url="https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-01.zip", kind="zip"),
        S(id="binance.vision.um.daily.metrics", group="Binance archive", url="https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2024-01-15.zip", kind="zip"),
        S(id="binance.vision.um.monthly.premiumIndexKlines", group="Binance archive", url="https://data.binance.vision/data/futures/um/monthly/premiumIndexKlines/BTCUSDT/1d/BTCUSDT-1d-2024-01.zip", kind="zip"),
        S(id="binance.vision.um.daily.bookDepth", group="Binance archive", url="https://data.binance.vision/data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2024-01-15.zip", kind="zip", head=True),
        # ---- Bybit
        S(id="bybit.v5.tickers", group="Bybit", url="https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"),
        S(id="bybit.v5.open-interest", group="Bybit", url="https://api.bybit.com/v5/market/open-interest?category=linear&symbol=BTCUSDT&intervalTime=1h&limit=5"),
        S(id="bybit.v5.account-ratio", group="Bybit", url="https://api.bybit.com/v5/market/account-ratio?category=linear&symbol=BTCUSDT&period=1h&limit=5"),
        S(id="bybit.bytick.tickers", group="Bybit", url="https://api.bytick.com/v5/market/tickers?category=linear&symbol=BTCUSDT"),
        S(id="bybit.public.archive", group="Bybit archive", url="https://public.bybit.com/trading/BTCUSDT/", kind="html"),
        # ---- OKX
        S(id="okx.instruments.swap", group="OKX", url="https://www.okx.com/api/v5/public/instruments?instType=SWAP"),
        S(id="okx.funding-rate-history", group="OKX", url="https://www.okx.com/api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP&limit=5"),
        S(id="okx.history-candles", group="OKX", url="https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT-SWAP&bar=1D&limit=5"),
        S(id="okx.rubik.oi-history", group="OKX", url="https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history?instId=BTC-USDT-SWAP&period=1D&limit=5"),
        S(id="okx.rubik.long-short-account-ratio-contract", group="OKX", url="https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio-contract?instId=BTC-USDT-SWAP&period=1H&limit=5"),
        S(id="okx.rubik.taker-volume-contract", group="OKX", url="https://www.okx.com/api/v5/rubik/stat/taker-volume-contract?instId=BTC-USDT-SWAP&period=1H&limit=5"),
        S(id="okx.liquidation-orders", group="OKX", url="https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&instFamily=BTC-USDT&state=filled&limit=5"),
        # ---- Hyperliquid
        S(id="hl.meta", group="Hyperliquid", url=hl, body={"type": "meta"}),
        S(id="hl.metaAndAssetCtxs", group="Hyperliquid", url=hl, body={"type": "metaAndAssetCtxs"}),
        S(id="hl.candleSnapshot.BTC.1d", group="Hyperliquid", url=hl, body={"type": "candleSnapshot", "req": {"coin": "BTC", "interval": "1d", "startTime": (NOW - 3000 * DAY) * 1000, "endTime": MS}}),
        S(id="hl.fundingHistory.BTC", group="Hyperliquid", url=hl, body={"type": "fundingHistory", "coin": "BTC", "startTime": d1}),
        S(id="hl.predictedFundings", group="Hyperliquid", url=hl, body={"type": "predictedFundings"}),
        S(id="hl.perpsAtOpenInterestCap", group="Hyperliquid", url=hl, body={"type": "perpsAtOpenInterestCap"}),
        S(id="hl.leaderboard", group="Hyperliquid", url="https://stats-data.hyperliquid.xyz/Mainnet/leaderboard", head=True),
        # ---- other perp venues
        S(id="gate.contracts", group="Gate.io", url="https://api.gateio.ws/api/v4/futures/usdt/contracts"),
        S(id="gate.contract_stats", group="Gate.io", url="https://api.gateio.ws/api/v4/futures/usdt/contract_stats?contract=BTC_USDT&interval=1h&limit=5"),
        S(id="gate.liq_orders", group="Gate.io", url="https://api.gateio.ws/api/v4/futures/usdt/liq_orders?contract=BTC_USDT&limit=5"),
        S(id="gate.candles.1d", group="Gate.io", url="https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract=BTC_USDT&interval=1d&limit=5"),
        S(id="mexc.contract.detail", group="MEXC", url="https://contract.mexc.com/api/v1/contract/detail"),
        S(id="mexc.funding.history", group="MEXC", url="https://contract.mexc.com/api/v1/contract/funding_rate/history?symbol=BTC_USDT&page_num=1&page_size=5"),
        S(id="bitget.tickers", group="Bitget", url="https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"),
        S(id="bitget.history-fund-rate", group="Bitget", url="https://api.bitget.com/api/v2/mix/market/history-fund-rate?symbol=BTCUSDT&productType=USDT-FUTURES&pageSize=5"),
        S(id="bitget.open-interest", group="Bitget", url="https://api.bitget.com/api/v2/mix/market/open-interest?symbol=BTCUSDT&productType=USDT-FUTURES"),
        S(id="bitget.account-long-short", group="Bitget", url="https://api.bitget.com/api/v2/mix/market/account-long-short?symbol=BTCUSDT&period=1h"),
        S(id="kucoin.futures.contracts", group="KuCoin", url="https://api-futures.kucoin.com/api/v1/contracts/active"),
        S(id="htx.linear.contract_info", group="HTX", url="https://api.hbdm.com/linear-swap-api/v1/swap_contract_info?contract_code=BTC-USDT"),
        S(id="htx.linear.his_open_interest", group="HTX", url="https://api.hbdm.com/linear-swap-api/v1/swap_his_open_interest?contract_code=BTC-USDT&period=60min&amount_type=2&size=5"),
        S(id="htx.linear.elite_account_ratio", group="HTX", url="https://api.hbdm.com/linear-swap-api/v1/swap_elite_account_ratio?contract_code=BTC-USDT&period=60min"),
        S(id="kraken.futures.tickers", group="Kraken", url="https://futures.kraken.com/derivatives/api/v3/tickers"),
        S(id="deribit.dvol", group="Deribit", url=f"https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp={(NOW - 3 * DAY) * 1000}&end_timestamp={MS}&resolution=3600"),
        S(id="deribit.book_summary.options", group="Deribit", url="https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option"),
        S(id="deribit.funding_rate_history", group="Deribit", url=f"https://www.deribit.com/api/v2/public/get_funding_rate_history?instrument_name=BTC-PERPETUAL&start_timestamp={(NOW - DAY) * 1000}&end_timestamp={MS}"),
        S(id="dydx.perpetualMarkets", group="dYdX", url="https://indexer.dydx.trade/v4/perpetualMarkets"),
        S(id="dydx.historicalFunding", group="dYdX", url="https://indexer.dydx.trade/v4/historicalFunding/BTC-USD?limit=5"),
        S(id="aster.premiumIndex", group="Aster", url="https://fapi.asterdex.com/fapi/v1/premiumIndex"),
        S(id="aster.openInterestHist", group="Aster", url="https://fapi.asterdex.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=5"),
        S(id="bitfinex.status.deriv", group="Bitfinex", url="https://api-pub.bitfinex.com/v2/status/deriv?keys=tBTCF0:USTF0"),
        S(id="bitfinex.stats.pos.size.long", group="Bitfinex", url="https://api-pub.bitfinex.com/v2/stats1/pos.size:1m:tBTCUSD:long/hist?limit=5"),
        S(id="coinbase.spot.candles", group="Coinbase", url="https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400"),
        S(id="coinbase.intl.instruments", group="Coinbase", url="https://api.international.coinbase.com/api/v1/instruments"),
        S(id="upbit.market.all", group="Korea", url="https://api.upbit.com/v1/market/all"),
        S(id="upbit.ticker.btc", group="Korea", url="https://api.upbit.com/v1/ticker?markets=KRW-BTC"),
        S(id="bithumb.ticker.all", group="Korea", url="https://api.bithumb.com/public/ticker/ALL_KRW", head=True),
        # ---- aggregators / fundamentals
        S(id="coingecko.global", group="CoinGecko", url="https://api.coingecko.com/api/v3/global", key="COINGECKO_API_KEY", key_header="x-cg-demo-api-key", optional_key=True),
        S(id="coingecko.markets", group="CoinGecko", url="https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&per_page=5", key="COINGECKO_API_KEY", key_header="x-cg-demo-api-key", optional_key=True),
        S(id="coingecko.derivatives", group="CoinGecko", url="https://api.coingecko.com/api/v3/derivatives?include_tickers=unexpired", key="COINGECKO_API_KEY", key_header="x-cg-demo-api-key", optional_key=True, head=True),
        S(id="coinpaprika.global", group="CoinPaprika", url="https://api.coinpaprika.com/v1/global"),
        S(id="coinpaprika.tickers", group="CoinPaprika", url="https://api.coinpaprika.com/v1/tickers?limit=5"),
        S(id="coinlore.tickers", group="CoinLore", url="https://api.coinlore.net/api/tickers/?start=0&limit=5"),
        S(id="cryptocompare.histoday", group="CryptoCompare", url="https://min-api.cryptocompare.com/data/v2/histoday?fsym=BTC&tsym=USD&limit=5"),
        S(id="defillama.oi.overview", group="DefiLlama", url="https://api.llama.fi/overview/open-interest", head=True),
        S(id="defillama.derivatives.overview", group="DefiLlama", url="https://api.llama.fi/overview/derivatives", head=True),
        S(id="defillama.dexs.overview", group="DefiLlama", url="https://api.llama.fi/overview/dexs?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true", head=True),
        S(id="defillama.stablecoincharts.all", group="DefiLlama", url="https://stablecoins.llama.fi/stablecoincharts/all", head=True),
        S(id="defillama.coins.current", group="DefiLlama", url="https://coins.llama.fi/prices/current/coingecko:bitcoin,coingecko:ethereum"),
        S(id="defillama.emissions", group="DefiLlama", url="https://api.llama.fi/emissions", head=True),
        S(id="dexscreener.boosts", group="DEX", url="https://api.dexscreener.com/token-boosts/latest/v1"),
        S(id="geckoterminal.trending", group="DEX", url="https://api.geckoterminal.com/api/v2/networks/trending_pools"),
        S(id="polymarket.markets", group="Prediction", url="https://gamma-api.polymarket.com/markets?limit=5&active=true"),
        # ---- sentiment, news, social
        S(id="alternative.fng", group="Sentiment", url="https://api.alternative.me/fng/?limit=5"),
        S(id="cnn.fear-greed", group="Sentiment", url="https://production.dataviz.cnn.io/index/fearandgreed/graphdata"),
        S(id="apewisdom.crypto", group="Sentiment", url="https://apewisdom.io/api/v1.0/filter/all-crypto"),
        S(id="stocktwits.btc", group="Sentiment", url="https://api.stocktwits.com/api/2/streams/symbol/BTC.X.json"),
        S(id="reddit.cryptocurrency", group="Sentiment", url="https://www.reddit.com/r/CryptoCurrency/hot.json?limit=5"),
        S(id="cryptopanic.posts", group="News", url="https://cryptopanic.com/api/developer/v2/posts/?public=true", key="CRYPTOPANIC_API_KEY", key_param="auth_token"),
        S(id="rss.coindesk", group="News", url="https://www.coindesk.com/arc/outboundfeeds/rss/", kind="html"),
        S(id="rss.cointelegraph", group="News", url="https://cointelegraph.com/rss", kind="html"),
        S(id="rss.theblock", group="News", url="https://www.theblock.co/rss.xml", kind="html"),
        S(id="rss.decrypt", group="News", url="https://decrypt.co/feed", kind="html"),
        # ---- on-chain, flows, macro
        S(id="mempool.fees", group="On-chain", url="https://mempool.space/api/v1/fees/recommended"),
        S(id="mempool.hashrate", group="On-chain", url="https://mempool.space/api/v1/mining/hashrate/1m", head=True),
        S(id="blockchain.charts.hashrate", group="On-chain", url="https://api.blockchain.info/charts/hash-rate?timespan=30days&format=json"),
        S(id="farside.btc.etf", group="ETF flows", url="https://farside.co.uk/bitcoin-etf-flow-all-data/", kind="html"),
        S(id="yahoo.dxy", group="Macro", url="https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=1mo&interval=1d"),
        S(id="yahoo.spx", group="Macro", url="https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=1mo&interval=1d"),
        S(id="fx.open-er-api", group="Macro", url="https://open.er-api.com/v6/latest/USD"),
        S(id="tardis.free.derivative_ticker", group="Tardis (free 1st of month)", url="https://datasets.tardis.dev/v1/binance-futures/derivative_ticker/2024/01/01/BTCUSDT.csv.gz", kind="gz", head=True),
        S(id="tardis.free.liquidations", group="Tardis (free 1st of month)", url="https://datasets.tardis.dev/v1/binance-futures/liquidations/2024/01/01/BTCUSDT.csv.gz", kind="gz", head=True),
        # ---- keyed (only called when the key is present)
        S(id="coinalyze.future-markets", group="Coinalyze (free key)", url="https://api.coinalyze.net/v1/future-markets", key="COINALYZE_API_KEY", key_param="api_key"),
        S(id="cmc.global-metrics", group="CoinMarketCap (free key)", url="https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest", key="CMC_API_KEY", key_header="X-CMC_PRO_API_KEY"),
        S(id="fred.dgs10", group="FRED (free key)", url="https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&file_type=json&limit=5&sort_order=desc", key="FRED_API_KEY", key_param="api_key"),
        S(id="etherscan.ethsupply", group="Etherscan (free key)", url="https://api.etherscan.io/v2/api?chainid=1&module=stats&action=ethsupply", key="ETHERSCAN_API_KEY", key_param="apikey"),
        S(id="ipinfo", group="Runner", url="https://ipinfo.io/json"),
    ]
    return out


def shape(raw, ctype, kind):
    """A short description of the payload."""
    if kind in ("zip",):
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
            names = z.namelist()
            first = z.read(names[0]).decode(errors="replace").splitlines()
            return {"zip_files": names[:3], "rows": len(first), "head": first[:3]}
        except Exception as e:  # noqa: BLE001
            return {"zip_error": str(e)[:200]}
    if kind == "gz":
        try:
            text = gzip.decompress(raw).decode(errors="replace").splitlines()
            return {"rows": len(text), "head": text[:3]}
        except Exception as e:  # noqa: BLE001
            return {"gz_error": str(e)[:200]}
    if kind == "s3list":
        text = raw.decode(errors="replace")
        pre = re.findall(r"<Prefix>([^<]+)</Prefix>", text)
        return {"prefixes": len(pre) - 1, "truncated": "<IsTruncated>true" in text, "sample": pre[1:8]}
    try:
        j = json.loads(raw)
    except Exception:  # noqa: BLE001
        text = raw.decode(errors="replace")
        title = re.search(r"<title>([^<]{0,120})", text, re.I)
        return {"text_bytes": len(text), "title": title.group(1) if title else None,
                "cloudflare": ("cf-chl" in text or "Just a moment" in text), "items": text.count("<item>")}
    def desc(x, depth=0):
        if isinstance(x, dict):
            return {"dict_keys": list(x)[:12], **({"first": desc(next(iter(x.values())), depth + 1)} if x and depth < 2 else {})}
        if isinstance(x, list):
            return {"list_len": len(x), **({"first": desc(x[0], depth + 1)} if x and depth < 2 else {})}
        return type(x).__name__
    return desc(j)


def call(s, timeout=25):
    rec = {k: s.get(k) for k in ("id", "group", "url")}
    key = s.get("key")
    url = s["url"]
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if key:
        val = os.environ.get(key)
        if not val and not s.get("optional_key"):
            rec.update(status="NEEDS_KEY", ok=False, note=f"set {key} to probe")
            return rec
        if val:
            if s.get("key_header"):
                headers[s["key_header"]] = val
            if s.get("key_param"):
                url += ("&" if "?" in url else "?") + f"{s['key_param']}={val}"
    data = None
    if s.get("body") is not None:
        data = json.dumps(s["body"]).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(8_000_000)
            rec["status"] = r.status
            hdr = {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        raw = e.read(4000) if hasattr(e, "read") else b""
        rec["status"] = e.code
        hdr = {k.lower(): v for k, v in (e.headers or {}).items()}
    except Exception as e:  # noqa: BLE001
        rec.update(status="ERROR", ok=False, error=f"{type(e).__name__}: {str(e)[:200]}", ms=int((time.time() - t0) * 1000))
        return rec
    rec["ms"] = int((time.time() - t0) * 1000)
    rec["bytes"] = len(raw)
    rec["content_type"] = hdr.get("content-type")
    rec["rate_headers"] = {k: v for k, v in hdr.items() if re.search(r"rate|limit|used-weight|retry|remaining|cf-ray|server", k)}
    rec["ok"] = isinstance(rec["status"], int) and 200 <= rec["status"] < 300
    try:
        rec["shape"] = shape(raw, rec["content_type"] or "", s.get("kind"))
    except Exception as e:  # noqa: BLE001
        rec["shape"] = {"error": str(e)[:200]}
    sample = raw[:1500].decode(errors="replace") if s.get("kind") not in ("zip", "gz") else ""
    if key and os.environ.get(key):
        sample = sample.replace(os.environ[key], "***")
    rec["sample"] = "" if s.get("head") else sample
    return rec


def hl_delisted(out):
    """Hyperliquid: how many perps are delisted in meta, and do their candles still load?"""
    hl = "https://api.hyperliquid.xyz/info"
    meta = next((r for r in out if r["id"] == "hl.meta"), None)
    res = {"delisted": None}
    try:
        req = urllib.request.Request(hl, data=json.dumps({"type": "meta"}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": UA})
        uni = json.loads(urllib.request.urlopen(req, timeout=20).read())["universe"]
        dl = [u["name"] for u in uni if u.get("isDelisted")]
        res.update(total=len(uni), delisted=len(dl), delisted_sample=dl[:15])
        for coin in dl[:3]:
            body = {"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": (NOW - 1500 * DAY) * 1000, "endTime": MS}}
            req = urllib.request.Request(hl, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "User-Agent": UA})
            try:
                c = json.loads(urllib.request.urlopen(req, timeout=20).read())
                res.setdefault("delisted_candles", {})[coin] = {"n": len(c), "first": c[0]["t"] if c else None, "last": c[-1]["t"] if c else None}
            except Exception as e:  # noqa: BLE001
                res.setdefault("delisted_candles", {})[coin] = {"error": str(e)[:120]}
    except Exception as e:  # noqa: BLE001
        res["error"] = str(e)[:200]
    return res


def binance_archive_census():
    """All USD-M symbols in the public archive (monthly klines), paginated, with a delisted estimate."""
    base = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/monthly/klines/"
    syms, marker = [], ""
    try:
        for _ in range(20):
            url = base + (f"&marker={urllib.request.quote(marker)}" if marker else "")
            text = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30).read().decode()
            pre = [p for p in re.findall(r"<Prefix>([^<]+)</Prefix>", text) if p.count("/") == 6]
            syms += [p.split("/")[-2] for p in pre]
            if "<IsTruncated>true" not in text:
                break
            marker = pre[-1]
        perps = [s for s in syms if "_" not in s]
        usdt = [s for s in perps if s.endswith("USDT")]
        out = {"symbols": len(syms), "perpetual": len(perps), "usdt_perpetual": len(usdt),
               "delivery": len(syms) - len(perps), "sample": usdt[:20]}
        # last available month for a sample, to separate live from delisted
        last = {}
        for s in usdt[:: max(1, len(usdt) // 40)][:40]:
            url = f"https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data/futures/um/monthly/klines/{s}/1d/"
            text = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30).read().decode()
            months = sorted(re.findall(r"-1d-(\d{4}-\d{2})\.zip<", text))
            last[s] = [months[0], months[-1]] if months else None
        out["sample_first_last_month"] = last
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:200]}", "symbols_so_far": len(syms)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="probe")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    src = sources()
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        out = list(ex.map(call, src))
    extra = {"hyperliquid_delisted": hl_delisted(out), "binance_archive": binance_archive_census()}
    doc = {"schema": "v9.probe/1", "run_at": NOW, "runner": os.environ.get("RUNNER_NAME"), "results": out, "extra": extra}
    with open(os.path.join(a.out, "sources.json"), "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    lines = ["| Source | Group | Status | ms | Bytes | Shape |", "|---|---|---|---|---|---|"]
    for r in out:
        sh = json.dumps(r.get("shape") or r.get("error") or r.get("note") or "")[:160].replace("|", "/")
        lines.append(f"| {r['id']} | {r['group']} | {r.get('status')} | {r.get('ms', '')} | {r.get('bytes', '')} | {sh} |")
    with open(os.path.join(a.out, "sources.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n\n```json\n" + json.dumps(extra, indent=1)[:20000] + "\n```\n")
    ok = sum(1 for r in out if r.get("ok"))
    print(f"{ok}/{len(out)} sources answered 2xx")
    for r in out:
        print(f"{str(r.get('status')):>9} {r.get('ms', ''):>6} {r['id']}")
    print(json.dumps(extra, indent=1)[:6000])


if __name__ == "__main__":
    sys.exit(main())
