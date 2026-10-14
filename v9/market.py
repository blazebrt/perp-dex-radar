"""Live market context for the desk (v9.market/1): regime, cross-venue funding and positioning, from free public APIs.

    python -m v9.market --out site [--history-branch v9-market-history] [--top-n 30]

CONTEXT ONLY. No engine and no decision reads this file. Whether any of it deserves decision authority is a research
question (docs/v9/HANDOVER.md, phase D) for the survivorship-free evidence engine; it is never assumed here.

Sources (each verified from the GitHub Actions runner, docs/v9/data-sources.md; free, no login, no order capability):

    hl.ctx         Hyperliquid metaAndAssetCtxs: mark, oracle, funding, open interest, premium and 24h volume per perp
    hl.predicted   Hyperliquid predictedFundings: the next funding on Hyperliquid, Binance and Bybit for each coin
                   (Binance and Bybit refuse US cloud runners, so this is how their funding is seen)
    hl.oicap       Hyperliquid perps at their open-interest cap
    gate.stats     Gate contract_stats, hourly, for the most traded coins: open interest and its 24h change, account and
                   top-trader long/short ratios, taker buy/sell ratio, long and short liquidations over 24h
    deribit.dvol   Deribit DVOL for BTC and ETH: the 30-day implied-volatility index
    alt.fng        alternative.me Crypto Fear & Greed (daily)
    llama.stable   DefiLlama total stablecoin supply (daily)
    cb.btc, bn.btc, upbit.btc, fx.usd   Coinbase and Korea premiums on BTC (Binance spot via data-api.binance.vision)
    bfx.longs, bfx.shorts               Bitfinex BTC margin longs and shorts
    cg.global      CoinGecko global: total market cap, dominance (demo key from the COINGECKO_API_KEY secret, optional)
    farside.etf    US spot bitcoin ETF daily net flows, from Farside's public table (best effort: an HTML page)

Rules: every source reports its status, latency and fetch time; a failed or malformed source leaves its fields missing
(never zero) and never affects another source; units are explicit (funding as a rate per 8 hours, money in USD);
nothing is labelled bullish or bearish (no evidence says what these mean for a trade); the collector never raises."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import html as htmllib
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = "v9.market/1"
HISTORY_VERSION = "v9.market-history/1"
FILE = "data/v9/market.json"
HISTORY_DIR = "market"
UA = "perp-dex-radar/v9 (+https://github.com/blazebrt/perp-dex-radar)"
HL = "https://api.hyperliquid.xyz/info"
LIQUID_USD = 1e6          # a coin counts in funding and breadth summaries with at least this 24h volume
TOP_USD = 5e6             # extremes are listed among coins with at least this 24h volume
HISTORY_MIN_USD = 1e6     # coins kept in the hourly history record
FRESH_S = 2 * 3600        # the producer's own horizon: after fresh_until a reader shows the context as stale


# --------------------------------------------------------------------------- helpers
def _num(x):
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)


def _f(x):
    """A finite float or None (strings from the APIs are parsed; '', None, NaN and junk are missing)."""
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _sig(x, n=6):
    """Round to n significant digits (prices, sizes); None stays None."""
    if not _num(x) or x == 0:
        return x if _num(x) else None
    return float(f"{x:.{n}g}")


def _rate(x):
    return round(x, 8) if _num(x) else None


def _pct(x):
    return round(x, 6) if _num(x) else None


def _usd(x):
    return round(x) if _num(x) else None


def _ratio(a, b):
    return a / b if _num(a) and _num(b) and b != 0 else None


def fetch_default(url, body=None, headers=None, kind="json", timeout=15):
    """GET (or POST a JSON body) and parse: JSON by default, text for kind="text"."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"User-Agent": UA, "Accept-Encoding": "gzip",
                                          **({"Content-Type": "application/json"} if body is not None else {}),
                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    text = raw.decode("utf-8", errors="replace")
    return json.loads(text) if kind == "json" else text


# --------------------------------------------------------------------------- parsers (pure: payload -> values)
def parse_hl_ctx(payload):
    """{coin: {...}} for every listed Hyperliquid perp. Hyperliquid funding is hourly; it is reported per 8 hours."""
    meta, ctxs = payload[0], payload[1]
    out = {}
    for u, c in zip(meta["universe"], ctxs):
        if not isinstance(u, dict) or not isinstance(c, dict) or u.get("isDelisted") or not u.get("name"):
            continue
        mark, prev = _f(c.get("markPx")), _f(c.get("prevDayPx"))
        fund, oi = _f(c.get("funding")), _f(c.get("openInterest"))
        out[u["name"]] = {
            "mark": _sig(mark), "oracle": _sig(_f(c.get("oraclePx"))),
            "chg_24h": _pct(mark / prev - 1) if _num(mark) and _num(prev) and prev > 0 else None,
            "funding_8h": _rate(fund * 8) if _num(fund) else None,
            "oi_usd": _usd(oi * mark) if _num(oi) and _num(mark) else None,
            "vol_24h_usd": _usd(_f(c.get("dayNtlVlm"))),
            "premium": _rate(_f(c.get("premium"))),
            "max_leverage": u.get("maxLeverage") if isinstance(u.get("maxLeverage"), int) else None}
    return out


VENUE_NAMES = {"HlPerp": "hyperliquid", "BinPerp": "binance", "BybitPerp": "bybit"}


def parse_hl_predicted(payload):
    """{coin: {venue: next funding per 8 hours}}: each venue's rate scaled from its own funding interval."""
    out = {}
    for row in payload:
        if not (isinstance(row, list) and len(row) == 2 and isinstance(row[1], list)):
            continue
        coin, venues = row
        rates = {}
        for v in venues:
            if not (isinstance(v, list) and len(v) == 2 and isinstance(v[1], dict)):
                continue
            name, info = VENUE_NAMES.get(v[0]), v[1]
            rate, hours = _f(info.get("fundingRate")), _f(info.get("fundingIntervalHours"))
            if name and _num(rate) and _num(hours) and hours > 0:
                rates[name] = _rate(rate * 8 / hours)
        if rates:
            out[coin] = rates
    return out


def parse_gate_stats(rows, hours=24):
    """Gate contract_stats rows (hourly, oldest first): the latest open interest and its change over `hours`, the
    latest account / top-trader long-short ratios, the taker buy/sell ratio and long/short liquidations over `hours`."""
    rows = [r for r in rows if isinstance(r, dict) and _num(_f(r.get("time")))]
    rows.sort(key=lambda r: r["time"])
    if not rows:
        raise ValueError("no rows")
    last = rows[-1]
    window = rows[-hours:]
    oi_now, oi_then = _f(last.get("open_interest_usd")), (_f(rows[-hours - 1].get("open_interest_usd"))
                                                          if len(rows) > hours else None)
    lt = [_f(r.get("long_taker_size")) for r in window]
    st = [_f(r.get("short_taker_size")) for r in window]
    taker = (_ratio(sum(lt), sum(st)) if all(_num(x) for x in lt + st) and lt else _f(last.get("lsr_taker")))
    liq_l = [_f(r.get("long_liq_usd")) for r in window]
    liq_s = [_f(r.get("short_liq_usd")) for r in window]
    full = len(window) == hours
    return {"as_of": int(last["time"]), "oi_usd": _usd(oi_now),
            "oi_chg_24h": _pct(oi_now / oi_then - 1) if _num(oi_now) and _num(oi_then) and oi_then > 0 else None,
            "lsr_account": _sig(_f(last.get("lsr_account")), 4), "lsr_top_account": _sig(_f(last.get("top_lsr_account")), 4),
            "lsr_taker_24h": _sig(taker, 4),
            "liq_long_24h_usd": _usd(sum(liq_l)) if full and all(_num(x) for x in liq_l) else None,
            "liq_short_24h_usd": _usd(sum(liq_s)) if full and all(_num(x) for x in liq_s) else None}


def parse_dvol(payload, now):
    """DVOL (hourly candles [t_ms, open, high, low, close]): the latest close and its change over 24h and 7 days."""
    data = sorted((r for r in payload["result"]["data"] if isinstance(r, list) and len(r) >= 5), key=lambda r: r[0])
    if not data:
        raise ValueError("no DVOL points")
    t_last, last = int(data[-1][0]) // 1000, _f(data[-1][4])

    def at(hours_ago):
        target = (t_last - hours_ago * 3600) * 1000
        prior = [r for r in data if r[0] <= target]
        return _f(prior[-1][4]) if prior and target - prior[-1][0] <= 2 * 3600 * 1000 else None
    d1, d7 = at(24), at(168)
    return {"value": _sig(last, 4), "as_of": t_last, "age_s": int(now - t_last),
            "chg_24h": _sig(last - d1, 4) if _num(last) and _num(d1) else None,
            "chg_7d": _sig(last - d7, 4) if _num(last) and _num(d7) else None}


def parse_fng(payload):
    data = [d for d in payload.get("data") or [] if isinstance(d, dict) and _num(_f(d.get("value")))]
    if not data:
        raise ValueError("no Fear & Greed points")
    data.sort(key=lambda d: int(d["timestamp"]), reverse=True)
    return {"value": int(_f(data[0]["value"])), "label": str(data[0].get("value_classification") or ""),
            "as_of": int(data[0]["timestamp"]),
            "last_7d": [int(_f(d["value"])) for d in data[:7]]}


def parse_stablecoins(payload):
    pts = []
    for p in payload:
        v = _f(((p or {}).get("totalCirculatingUSD") or {}).get("peggedUSD"))
        t = _f((p or {}).get("date"))
        if _num(v) and _num(t):
            pts.append((int(t), v))
    pts.sort()
    if not pts:
        raise ValueError("no stablecoin points")
    t_last, last = pts[-1]

    def back(days):
        prior = [v for t, v in pts if t <= t_last - days * 86400]
        return prior[-1] if prior else None
    w, m = back(7), back(30)
    return {"total_usd": _usd(last), "as_of": t_last,
            "chg_7d": _pct(last / w - 1) if _num(w) and w > 0 else None,
            "chg_30d": _pct(last / m - 1) if _num(m) and m > 0 else None}


def parse_cg_global(payload):
    d = payload["data"]
    mc = (d.get("total_market_cap") or {}).get("usd")
    pct = d.get("market_cap_percentage") or {}
    return {"total_mcap_usd": _usd(_f(mc)), "mcap_chg_24h": _pct(_f(d.get("market_cap_change_percentage_24h_usd")) / 100)
            if _num(_f(d.get("market_cap_change_percentage_24h_usd"))) else None,
            "btc_dominance": _pct(_f(pct.get("btc")) / 100) if _num(_f(pct.get("btc"))) else None,
            "eth_dominance": _pct(_f(pct.get("eth")) / 100) if _num(_f(pct.get("eth"))) else None,
            "as_of": int(d["updated_at"]) if _num(_f(d.get("updated_at"))) else None}


DATE_RE = re.compile(r"^(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})$")
MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def _cell(raw):
    return htmllib.unescape(re.sub(r"<[^>]+>", "", raw)).replace("\xa0", " ").strip()


def _flow(text):
    """A Farside flow cell in US$m: '12.3', '(12.3)' (an outflow), '0.0'; '-' or empty is missing (no data)."""
    t = text.replace(",", "").strip()
    neg = t.startswith("(") and t.endswith(")")
    v = _f(t.strip("()"))
    return -v if neg and _num(v) else v


def parse_farside(text, keep=10):
    """US spot bitcoin ETF daily net flows (US$m) from Farside's table: the dated rows with a numeric total."""
    days = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = [_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        if len(cells) < 3:
            continue
        m = DATE_RE.match(cells[0])
        if not m or m.group(2) not in MONTHS:
            continue
        total = _flow(cells[-1])
        if _num(total):
            d = datetime(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)), tzinfo=timezone.utc)
            days.append((int(d.timestamp()), total))
    if not days:
        raise ValueError("no dated rows with a total")
    days = sorted(set(days))[-keep:]
    return {"unit": "USD millions", "last_date": days[-1][0], "last_total_musd": _sig(days[-1][1], 6),
            "sum_5d_musd": _sig(sum(v for _, v in days[-5:]), 6) if len(days) >= 5 else None,
            "days": [[t, _sig(v, 6)] for t, v in days]}


def parse_coinbase_last(rows):
    rows = [r for r in rows if isinstance(r, list) and len(r) >= 5]
    rows.sort(key=lambda r: r[0])
    return {"t": int(rows[-1][0]), "close": _f(rows[-1][4])}


def parse_binance_last(rows):
    rows = [r for r in rows if isinstance(r, list) and len(r) >= 5]
    rows.sort(key=lambda r: r[0])
    return {"t": int(rows[-1][0]) // 1000, "close": _f(rows[-1][4])}


# --------------------------------------------------------------------------- collection
def _job(sources, sid, fn):
    t0 = time.time()
    try:
        value = fn()
        sources[sid] = {"status": "OK", "ms": int((time.time() - t0) * 1000), "fetched_at": int(time.time())}
        return value
    except Exception as e:  # noqa: BLE001 - one source never stops another
        sources[sid] = {"status": "ERROR", "ms": int((time.time() - t0) * 1000), "fetched_at": int(time.time()),
                        "error": f"{type(e).__name__}: {str(e)[:160]}"}
        return None


def gate_contract(coin):
    """Hyperliquid's k-prefixed coins (kPEPE = 1000 PEPE) are quoted per coin on Gate."""
    base = coin[1:] if coin.startswith("k") and coin[1:].isupper() else coin
    return f"{base}_USDT"


def collect(now=None, fetch=fetch_default, cg_key=None, top_n=30, workers=16):
    """The whole market-context document. Never raises: a failed source is reported and its fields stay missing."""
    now = int(now if now is not None else time.time())
    sources = {}
    jobs = {
        "hl.ctx": lambda: parse_hl_ctx(fetch(HL, {"type": "metaAndAssetCtxs"})),
        "hl.predicted": lambda: parse_hl_predicted(fetch(HL, {"type": "predictedFundings"})),
        "hl.oicap": lambda: sorted(x for x in fetch(HL, {"type": "perpsAtOpenInterestCap"}) if isinstance(x, str)),
        "deribit.dvol.btc": lambda: parse_dvol(fetch(
            "https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&resolution=3600"
            f"&start_timestamp={(now - 8 * 86400) * 1000}&end_timestamp={now * 1000}"), now),
        "deribit.dvol.eth": lambda: parse_dvol(fetch(
            "https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=ETH&resolution=3600"
            f"&start_timestamp={(now - 8 * 86400) * 1000}&end_timestamp={now * 1000}"), now),
        "alt.fng": lambda: parse_fng(fetch("https://api.alternative.me/fng/?limit=8")),
        "llama.stable": lambda: parse_stablecoins(fetch("https://stablecoins.llama.fi/stablecoincharts/all")),
        "cb.btc": lambda: parse_coinbase_last(fetch("https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60")),
        "bn.btc": lambda: parse_binance_last(fetch("https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=3")),
        "upbit.btc": lambda: fetch("https://api.upbit.com/v1/ticker?markets=KRW-BTC")[0],
        "fx.usd": lambda: fetch("https://open.er-api.com/v6/latest/USD")["rates"],
        "bfx.longs": lambda: fetch("https://api-pub.bitfinex.com/v2/stats1/pos.size:1m:tBTCUSD:long/hist?limit=1441"),
        "bfx.shorts": lambda: fetch("https://api-pub.bitfinex.com/v2/stats1/pos.size:1m:tBTCUSD:short/hist?limit=1441"),
        "farside.etf": lambda: parse_farside(fetch("https://farside.co.uk/bitcoin-etf-flow-all-data/", kind="text")),
    }
    if cg_key:
        jobs["cg.global"] = lambda: parse_cg_global(fetch("https://api.coingecko.com/api/v3/global",
                                                          headers={"x-cg-demo-api-key": cg_key}))
    else:
        sources["cg.global"] = {"status": "MISSING_KEY", "ms": 0, "fetched_at": now}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {sid: ex.submit(_job, sources, sid, fn) for sid, fn in jobs.items()}
        got = {sid: f.result() for sid, f in futs.items()}
        ctx = got.get("hl.ctx") or {}
        liquid = [(c, v["vol_24h_usd"]) for c, v in ctx.items() if _num(v.get("vol_24h_usd")) and v["vol_24h_usd"] >= LIQUID_USD]
        top = [c for c, _ in sorted(liquid, key=lambda x: (-x[1], x[0]))][:top_n]
        stats = {}
        gate_errors = {}

        def one(coin):
            try:
                stats[coin] = parse_gate_stats(fetch("https://api.gateio.ws/api/v4/futures/usdt/contract_stats?"
                                                     + urllib.parse.urlencode({"contract": gate_contract(coin),
                                                                               "interval": "1h", "limit": 25})))
            except Exception as e:  # noqa: BLE001
                gate_errors[coin] = f"{type(e).__name__}: {str(e)[:80]}"
        t0 = time.time()
        list(ex.map(one, top))
    sources["gate.stats"] = {"status": "OK" if stats else ("ERROR" if top else "SKIPPED"), "ms": int((time.time() - t0) * 1000),
                             "fetched_at": int(time.time()), "requested": len(top), "answered": len(stats),
                             "errors": dict(sorted(gate_errors.items())[:10])}
    return build(now, got, stats, sources)


def build(now, got, stats, sources):
    """Assemble the document from parsed source values (pure; used by collect() and the tests)."""
    ctx = got.get("hl.ctx") or {}
    pred = got.get("hl.predicted") or {}
    cap = set(got.get("hl.oicap") or [])
    assets = {}
    for coin in sorted(set(ctx) | set(stats)):
        row = dict(ctx.get(coin) or {})
        p = pred.get(coin) or {}
        row["funding_8h_binance"] = p.get("binance")
        row["funding_8h_bybit"] = p.get("bybit")
        row["at_oi_cap"] = coin in cap if "hl.oicap" in got and got.get("hl.oicap") is not None else None
        if coin in stats:
            row["gate"] = stats[coin]
        assets[coin] = row
    doc = {"schema": VERSION, "as_of": int(now), "fresh_until": int(now) + FRESH_S,
           "authority": "CONTEXT_ONLY: no engine and no decision reads this file",
           "sources": dict(sorted(sources.items())), "regime": regime(got, ctx, stats, now), "assets": assets,
           "units": {"funding_8h": "funding rate per 8 hours (Hyperliquid's hourly rate x 8; Binance and Bybit from "
                                   "Hyperliquid's predicted-funding feed, scaled from their own interval)",
                     "chg_24h": "fraction (0.05 = +5%)", "oi_usd": "US dollars", "premium": "Hyperliquid mark vs oracle",
                     "lsr_account": "long/short accounts on Gate", "lsr_top_account": "top-trader long/short accounts on Gate",
                     "lsr_taker_24h": "taker buy volume / taker sell volume on Gate over 24h",
                     "dvol": "Deribit 30-day implied volatility index (annualised %)"},
           "notes": ["Context only: these numbers inform; none of them is a trade signal unless the evidence engine "
                     "confirms it (docs/v9/HANDOVER.md, phase D).",
                     "A missing value is missing because its source did not answer, never zero."]}
    return doc


def regime(got, ctx, stats, now):
    liquid = {c: v for c, v in ctx.items() if _num(v.get("vol_24h_usd")) and v["vol_24h_usd"] >= LIQUID_USD}
    funds = [v["funding_8h"] for v in liquid.values() if _num(v.get("funding_8h"))]
    top = {c: v for c, v in liquid.items() if v["vol_24h_usd"] >= TOP_USD and _num(v.get("funding_8h"))}
    chg = [v["chg_24h"] for v in liquid.values() if _num(v.get("chg_24h"))]
    ois = sorted(((c, v["oi_usd"]) for c, v in ctx.items() if _num(v.get("oi_usd"))), key=lambda x: (-x[1], x[0]))
    out = {"funding": ({"liquid_coins": len(funds), "median_8h": _rate(statistics.median(funds)),
                        "share_positive": _pct(sum(1 for f in funds if f > 0) / len(funds)),
                        "btc_8h": (ctx.get("BTC") or {}).get("funding_8h"), "eth_8h": (ctx.get("ETH") or {}).get("funding_8h"),
                        "highest": [[c, top[c]["funding_8h"]] for c in sorted(top, key=lambda c: (-top[c]["funding_8h"], c))[:5]],
                        "lowest": [[c, top[c]["funding_8h"]] for c in sorted(top, key=lambda c: (top[c]["funding_8h"], c))[:5]]}
                       if funds else None),
           "breadth": ({"liquid_coins": len(chg), "share_up_24h": _pct(sum(1 for x in chg if x > 0) / len(chg)),
                        "median_chg_24h": _pct(statistics.median(chg))} if chg else None),
           "open_interest": ({"hyperliquid_total_usd": _usd(sum(v for _, v in ois)),
                              "largest": [[c, v] for c, v in ois[:5]]} if ois else None),
           "at_oi_cap": sorted(got.get("hl.oicap")) if got.get("hl.oicap") is not None else None,
           "volatility": {"btc_dvol": got.get("deribit.dvol.btc"), "eth_dvol": got.get("deribit.dvol.eth")},
           "sentiment": got.get("alt.fng"), "stablecoins": got.get("llama.stable"), "etf_flows": got.get("farside.etf"),
           "global": got.get("cg.global"), "premiums": premiums(got, now), "btc_margin": btc_margin(got),
           "positioning": positioning(stats)}
    return out


def premiums(got, now):
    """Coinbase and Korea premiums on BTC against Binance spot (BTC/USDT; USDT is taken at par with USD, which is an
    approximation the reader should know)."""
    bn = got.get("bn.btc") or {}
    out = {"basis": "BTC: Coinbase BTC/USD and Upbit BTC/KRW (converted with open.er-api USD/KRW) vs Binance BTC/USDT"}
    cb = got.get("cb.btc") or {}
    if _num(cb.get("close")) and _num(bn.get("close")) and abs((cb.get("t") or 0) - (bn.get("t") or 0)) <= 180:
        out["coinbase"] = _pct(cb["close"] / bn["close"] - 1)
    else:
        out["coinbase"] = None
    up, fx = got.get("upbit.btc") or {}, got.get("fx.usd") or {}
    krw, rate = _f(up.get("trade_price")), _f(fx.get("KRW"))
    out["korea"] = _pct(krw / rate / bn["close"] - 1) if _num(krw) and _num(rate) and rate > 0 and _num(bn.get("close")) else None
    out["as_of"] = bn.get("t")
    return out


def btc_margin(got):
    """Bitfinex BTC margin longs and shorts (BTC) and their 24h change."""
    def series(x):
        pts = sorted((int(r[0]) // 1000, _f(r[1])) for r in x or [] if isinstance(r, list) and len(r) >= 2)
        return [(t, v) for t, v in pts if _num(v)]
    out = {}
    for side in ("longs", "shorts"):
        s = series(got.get(f"bfx.{side}"))
        if s:
            then = next((v for t, v in reversed(s) if t <= s[-1][0] - 24 * 3600), None)     # the latest point a day back
            out[side] = {"btc": _sig(s[-1][1], 6), "chg_24h": _pct(s[-1][1] / then - 1) if _num(then) and then > 0 else None,
                         "as_of": s[-1][0]}
        else:
            out[side] = None
    return out if any(out.values()) else None


def positioning(stats):
    if not stats:
        return None
    rows = {c: s for c, s in stats.items() if isinstance(s, dict)}
    ls = {c: s["lsr_account"] for c, s in rows.items() if _num(s.get("lsr_account"))}
    liq = {c: (s.get("liq_long_24h_usd"), s.get("liq_short_24h_usd")) for c, s in rows.items()
           if _num(s.get("liq_long_24h_usd")) and _num(s.get("liq_short_24h_usd"))}
    oi = {c: s["oi_chg_24h"] for c, s in rows.items() if _num(s.get("oi_chg_24h"))}
    return {"coins": len(rows),
            "most_long_accounts": [[c, ls[c]] for c in sorted(ls, key=lambda c: (-ls[c], c))[:5]],
            "most_short_accounts": [[c, ls[c]] for c in sorted(ls, key=lambda c: (ls[c], c))[:5]],
            "liquidations_24h_usd": ({"long": _usd(sum(v[0] for v in liq.values())), "short": _usd(sum(v[1] for v in liq.values())),
                                      "coins": len(liq)} if liq else None),
            "largest_oi_increase_24h": [[c, oi[c]] for c in sorted(oi, key=lambda c: (-oi[c], c))[:5]],
            "largest_oi_decrease_24h": [[c, oi[c]] for c in sorted(oi, key=lambda c: (oi[c], c))[:5]]}


# --------------------------------------------------------------------------- history (append-only, one record per hour)
HISTORY_FIELDS = ("mark", "chg_24h", "funding_8h", "funding_8h_binance", "funding_8h_bybit", "oi_usd", "vol_24h_usd",
                  "premium", "gate_oi_usd", "gate_oi_chg_24h", "gate_lsr_account", "gate_lsr_top_account",
                  "gate_lsr_taker_24h", "gate_liq_long_24h_usd", "gate_liq_short_24h_usd")


def history_record(doc):
    """The compact hourly record: the regime, every source's status, and one row per coin with >= $1M a day."""
    rows = {}
    for coin, a in doc["assets"].items():
        if not (_num(a.get("vol_24h_usd")) and a["vol_24h_usd"] >= HISTORY_MIN_USD):
            continue
        g = a.get("gate") or {}
        vals = {**a, **{f"gate_{k}": v for k, v in g.items()}}
        rows[coin] = [vals.get(k) for k in HISTORY_FIELDS]
    return {"schema": HISTORY_VERSION, "as_of": doc["as_of"], "source_status": {k: v.get("status") for k, v in doc["sources"].items()},
            "regime": doc["regime"], "fields": list(HISTORY_FIELDS), "assets": rows}


def history_path(as_of):
    d = datetime.fromtimestamp(as_of, timezone.utc)
    return f"{HISTORY_DIR}/{d:%Y/%m/%d/%H}.json.gz"


def _git(args, cwd, env=None, input_=None, timeout=90):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, input=input_, env=env, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {r.stderr.decode(errors='replace').strip()[-300:]}")
    return r.stdout


README = ("# v9 market history (append-only)\n\nOne gzipped JSON record per UTC hour (`market/YYYY/MM/DD/HH.json.gz`, "
          "schema v9.market-history/1), written by the Scan workflow from `python -m v9.market`. Files are only "
          "added, never changed. Context only: no engine reads this branch; phase D research may.\n")


def append_history(repo, branch, doc, remote="v9-market-history", url=None):
    """Add this hour's record to the history branch if the hour has none yet (first scan of the hour wins). Returns
    the written path or None. Push without --force: a concurrent writer makes this one skip, never overwrite."""
    path = history_path(doc["as_of"])
    url = url or _git(["remote", "get-url", "origin"], repo).decode().strip()
    have = _git(["remote"], repo).decode().split()
    _git(["remote", "set-url" if remote in have else "add", *([] if remote in have else ["--no-tags"]), remote, url], repo)
    ref = f"refs/{remote}/{branch}"
    heads = _git(["ls-remote", "--heads", remote, f"refs/heads/{branch}"], repo).decode().split()
    head = None
    if heads:
        _git(["fetch", "--no-tags", "--depth=1", "--filter=blob:none", remote, f"+refs/heads/{branch}:{ref}"], repo)
        head = _git(["rev-parse", ref], repo).decode().strip()
        exists = subprocess.run(["git", "cat-file", "-e", f"{head}:{path}"], cwd=repo, capture_output=True).returncode == 0
        if exists:
            return None
    data = gzip.compress(json.dumps(history_record(doc), sort_keys=True, separators=(",", ":"), allow_nan=False).encode(),
                         mtime=0)
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(td, "index"),
                   GIT_AUTHOR_NAME="perp-dex-radar", GIT_AUTHOR_EMAIL="actions@users.noreply.github.com",
                   GIT_COMMITTER_NAME="perp-dex-radar", GIT_COMMITTER_EMAIL="actions@users.noreply.github.com")
        _git(["read-tree", head] if head else ["read-tree", "--empty"], repo, env=env)
        if not head:
            blob = _git(["hash-object", "-w", "--stdin"], repo, input_=README.encode()).decode().strip()
            _git(["update-index", "--add", "--cacheinfo", f"100644,{blob},README.md"], repo, env=env)
        blob = _git(["hash-object", "-w", "--stdin"], repo, input_=data).decode().strip()
        _git(["update-index", "--add", "--cacheinfo", f"100644,{blob},{path}"], repo, env=env)
        tree = _git(["write-tree", "--missing-ok"], repo, env=env).decode().strip()
        commit = _git(["commit-tree", tree, "-m", f"Market context {path}"] + (["-p", head] if head else []),
                      repo, env=env).decode().strip()
    _git(["push", "--no-verify", remote, f"{commit}:refs/heads/{branch}"], repo)
    return path


# --------------------------------------------------------------------------- command line
def write(doc, out_dir):
    path = os.path.join(out_dir, FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with open(path, "w") as fh:
        fh.write(raw)
    return path, len(raw)


def summary_line(doc):
    ok = sum(1 for s in doc["sources"].values() if s.get("status") == "OK")
    r = doc["regime"]
    f = r.get("funding") or {}
    return (f"market context: {ok}/{len(doc['sources'])} sources OK, {len(doc['assets'])} coins; "
            f"median funding {f.get('median_8h')}/8h, fear & greed {(r.get('sentiment') or {}).get('value')}, "
            f"BTC DVOL {((r.get('volatility') or {}).get('btc_dvol') or {}).get('value')}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="site folder: writes <out>/data/v9/market.json")
    ap.add_argument("--history-branch", default=None, help="append this hour's record to this branch")
    ap.add_argument("--top-n", type=int, default=30)
    a = ap.parse_args(argv)
    doc = collect(cg_key=os.environ.get("COINGECKO_API_KEY") or None, top_n=a.top_n)
    path, n = write(doc, a.out)
    print(summary_line(doc) + f"; wrote {path} ({n} bytes)")
    for sid, s in doc["sources"].items():
        if s.get("status") != "OK":
            print(f"  {sid}: {s.get('status')} {s.get('error') or ''}".rstrip())
    if a.history_branch:
        try:
            written = append_history(os.getcwd(), a.history_branch, doc)
            print(f"history: {'wrote ' + written if written else 'this hour is already recorded'}")
        except Exception as e:  # noqa: BLE001 - the history never stops the scan
            print(f"history: not written ({type(e).__name__}: {str(e)[:200]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
