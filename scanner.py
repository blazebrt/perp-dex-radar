#!/usr/bin/env python3
"""
Perp DEX Radar - hourly 15-minute scanner for every crypto perp listed on the
major decentralised perp exchanges (Hyperliquid, Variational, Aster, edgeX,
Lighter, dYdX, Paradex, Extended), with nine strategies, a paper-trading
journal with trading costs, a strategy tournament that learns from its own
mistakes, a 30-day backtest and a daily search for better strategy variants.

It runs on GitHub Actions (see .github/workflows/scan.yml) and writes a static
dashboard to ./site:
    site/index.html          the dashboard (copied from ./index.html)
    site/data/latest.json    the newest scan, with the journal summary
    site/data/journal.json   every paper trade and what was learned (read back next run)
    site/data/journal.csv    the same trades as a spreadsheet

Pipeline
    1. Universe      the market list of every DEX, merged into one coin list.
                     Symbols are normalised (1000PEPE, kPEPE and PEPE are one
                     coin), stocks/FX/commodities are removed, and each coin
                     keeps its per-DEX symbol, price multiplier, 24h volume,
                     open interest and funding.
    2. Stage 1       300 1-hour candles for every coin (MEXC futures, then
                     Gate.io, Bitget, Hyperliquid or Aster) -> momentum score
                     and the 4-hour trend
    3. Stage 2       24h of 15-minute candles for the strongest ~40 coins with
                     real DEX liquidity, plus dipping uptrends and coins the
                     smart money holds -> EMA 9/21/50, RSI, MACD, ADX, ATR,
                     Bollinger squeeze, VWAP, swing structure, volume surges
    4. Strategies    nine long-only strategies with adjustable rules, each with
                     its own entry zone, stop and targets (see STRATEGIES and
                     PARAMS), plus the variants found by strategy discovery
    5. Smart money   open positions of Hyperliquid's most profitable traders
                     (public leaderboard + public account state), plus Gate.io
                     top-trader ratios and open-interest change
    6. Scoring       conviction score 0-100 with a written technical case,
                     adjusted by what the journal has learned
    7. Journal       every signal is paper-traded after fees, slippage and
                     funding; closed trades decide which strategies pass or are
                     rejected, which trade traits get penalised or blocked, and
                     how targets and stops are tuned. A new journal starts with
                     a 30-day backtest of every strategy.
    8. Discovery     once a day new variants of the strategies are generated,
                     backtested over 30 days against their parent, and the best
                     go to a live forward test; they are published only after
                     passing on live trades, and retired when they fail.
    9. Alerts        optional Telegram / Discord message for new strong picks.

Prices and levels are per 1 unit of the coin. Where a DEX lists a multiple
(1000PEPE, kPEPE) the page shows the multiplier.

Standard library only. Educational tool, not financial advice.
"""
from __future__ import annotations

import argparse
import bisect
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import random
import re
import shutil
import statistics
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

VERSION = "4.0.0"

# --------------------------------------------------------------------------- settings
CFG = {
    "stage2_n": 40,            # coins that get the 15m deep dive
    "stage2_extra": 16,        # extra deep dives: uptrend dips and smart-money coins outside the top 40
    "positioning_n": 24,       # leaders that get the Gate.io top-trader check
    "smart_traders": 150,      # Hyperliquid leaderboard accounts whose positions are read
    "smart_min_account": 50_000,   # min account value (USD) for a smart trader
    "top_n": 10,               # picks published (the page shows top 5 / top 10)
    "watch_n": 8,              # runners-up shown on the watchlist
    "min_pick_score": 50,      # final score (after the journal's adjustments) needed to be a pick
    "min_dex_vol": 20_000,     # a pick needs at least one DEX with this 24h volume (USD)
    "max_risk": 0.05,          # setups with a stop further than 5% away are dropped
    "h1_bars": 300,            # 1h candles per coin in stage 1 (12.5 days: also gives the 4h trend)
    "m15_bars": 96,            # 15m candles per coin in stage 2 (24h)
    "chart_bars": 64,          # 15m candles shipped to the page per pick (16h)
    "workers": 8,              # parallel HTTP requests
    "valid_hours": 3,          # an unfilled setup expires after this (the fill window)
    "track_hours": 12,         # a filled trade is closed at market after this
    "hunt_hours": 3,           # after a stop, how long to watch for price reaching TP1 (stop hunt)
    # trading costs taken off every paper trade (Hyperliquid base-tier fees; the other DEXs are similar or cheaper)
    "costs": True,
    "fee_taker": 0.00045,      # market orders: entries at market, buy-stops, stop-losses, closing at market
    "fee_maker": 0.00015,      # limit orders: pullback entries and take-profits
    "slip": ((1e6, 0.0005), (2e5, 0.001), (0, 0.002)),  # slippage on market orders by best DEX 24h volume
    "fund_default": 0.0001,    # funding per 8h (longs pay) when a coin has no DEX funding data
    # journal, tournament and learning
    "journal_days": 30,        # rolling window used for strategy stats and lessons
    "journal_keep_days": 32,   # closed trades older than this are dropped from journal.json
    "journal_max": 40000,      # closed trades kept in journal.json (the oldest go first)
    "strategy_window": 250,    # most recent closed trades per strategy that count for its status
    "min_trades": 15,          # closed trades before a strategy can pass or be rejected
    "lesson_min": 12,          # trades in a bucket before it can become a lesson
    "publish": ("passed", "watch", "testing"),  # strategy statuses whose signals can become picks
    "bt_days": 30,             # days of history the backtest walks through (first run and discovery)
    "bt_universe": 150,        # coins in the backtest (the most traded on the DEXs)
    # strategy discovery
    "discovery": True,         # invent, backtest and live-test new strategy variants
    "discovery_every_h": 24,   # hours between discovery rounds
    "discovery_batch": 16,     # new variants backtested per round
    "forward_slots": 12,       # variants in a live test at the same time
    "forward_min_trades": 20,  # live trades before a variant can be promoted
    "forward_min_days": 5,     # ... and days of live testing (with trades on at least this many days minus one)
    "forward_max_days": 21,    # a variant not promoted by then is retired
    "variants_max": 16,        # promoted variants kept (the weakest is retired beyond this)
    # alerts (optional): set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID and/or DISCORD_WEBHOOK_URL as repository secrets
    "alert_min_score": 62,     # new picks at or above this final score are sent
    "alert_max": 5,            # at most this many picks per message
    "schedule_minute": int(os.environ.get("SCAN_MINUTE", "7")),        # set in scan.yml
    "schedule_every_min": int(os.environ.get("SCAN_EVERY_MIN", "60")),  # set in scan.yml
}

# DEX market lists
VAR_STATS = "https://omni-client-api.prod.ap-northeast-1.variational.io/metadata/stats"
HL_INFO = "https://api.hyperliquid.xyz/info"
HL_LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
ASTER_INFO = "https://fapi.asterdex.com/fapi/v1/exchangeInfo"
ASTER_TICKER = "https://fapi.asterdex.com/fapi/v1/ticker/24hr"
ASTER_PREMIUM = "https://fapi.asterdex.com/fapi/v1/premiumIndex"
ASTER_KLINE = "https://fapi.asterdex.com/fapi/v1/klines?symbol={sym}&interval={iv}&limit={limit}"
EDGEX_META = "https://pro.edgex.exchange/api/v1/public/meta/getMetaData"
LIGHTER_BOOKS = "https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails"
DYDX_MARKETS = "https://indexer.dydx.trade/v4/perpetualMarkets"
PARADEX_SUMMARY = "https://api.prod.paradex.trade/v1/markets/summary?market=ALL"
EXTENDED_MARKETS = "https://api.starknet.extended.exchange/api/v1/info/markets"
# Reference candles and CEX positioning
MEXC_KLINE = "https://contract.mexc.com/api/v1/contract/kline/{sym}?interval={iv}&start={start}&end={end}"
GATE_KLINE = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={sym}&interval={iv}&limit={limit}"
GATE_KLINE_RANGE = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={sym}&interval={iv}&from={start}&to={end}"
BITGET_KLINE = ("https://api.bitget.com/api/v2/mix/market/candles?symbol={sym}&productType=usdt-futures"
                "&granularity={iv}&limit={limit}")
GATE_STATS = "https://api.gateio.ws/api/v4/futures/usdt/contract_stats?contract={sym}&interval=1h&limit=12"

DEXES = ("hyperliquid", "variational", "aster", "edgex", "lighter", "dydx", "paradex", "extended")
DEX_NAME = {"hyperliquid": "Hyperliquid", "variational": "Variational", "aster": "Aster", "edgex": "edgeX",
            "lighter": "Lighter", "dydx": "dYdX", "paradex": "Paradex", "extended": "Extended"}

# Tickers that are not crypto: stocks, ETFs, indices, FX, commodities, pre-IPO
# companies and gold tokens. DEX metadata (category, underlying type) and a
# name check catch new ones as well, see is_tradfi().
TRADFI = set("""
XAU CL US500 SPCX XAG BZ QQQ SNDK MU NVDA INTC AMAT SOXL GOOGL META EWY CRCL AAPL AMZN MSTR MSFT TSLA SKHY
RDDT CRWD XPT COIN COPPER XAUT ANTHROPIC CSCO AMD AVGO DELL TSM SMCI NBIS BBX DRAM ARM ALAB STRC BABA GME
OPENAI NATGAS PLTR CRM CRDO IREN KLAC HPE WMT TER ZM MRNA NOK PAXG BX XBI NFLX XPD HOOD CIEN HD JPM DKNG
SNOW BMNR LITE TXN AAOI IWM RKLB USAR BOT COST SHAZ ORCL PAYP IBM STXX CRWV SOXS SONY FWDI QCOM DIS RIVN
WEN MRVL CBRS BRKB LLY EWZ TMF EBAY EWT TZA UBER GPRO CAT EWJ KSTR URNM TTWO UVXY BNC NVO HIMS QNTX XLE
SMIC GEV AXTI SHEIN UNITREE ZHIPU OURA ASML BE XCU BRENTOIL WTI NG GOLD SILVER SPACEX STRIPE DATABRICKS
BYTEDANCE KALSHI POLYMARKET SHOP INTU SAMSUNG WDC CLSK MSTU MSTX TSLL NVDL SPY DIA_ETF VIX US30 US100
NAS100 SPX500 DJI GER40 UK100 JP225 HK50 USOIL UKOIL XNG PLAT PALL WHEAT SOYBEAN COFFEE SUGAR COCOA
""".split())
FX_CODES = {"USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "CNH", "CNY", "HKD", "SGD", "MXN", "KRW",
            "INR", "TRY", "ZAR", "SEK", "NOK", "DKK", "PLN", "BRL"}
TRADFI_NAME = re.compile(
    r"\b(inc|corp|corporation|holdings|etf|trust|fund|index|ltd|plc|group|technologies|shares|class [ab]|"
    r"s&p|nasdaq|treasury|crude|brent|natural gas|gold|silver|platinum|palladium|copper|uranium|"
    r"semiconductor|bond|volatility|msci|ishares|spdr|proshares|direxion|equity|stock)\b", re.I)

# Crypto tickers known when this tool was written; they skip the name check.
KNOWN_CRYPTO_TXT = """
BTC ETH SOL HYPE NEAR ENA ZEC XRP BNB XPL WLD TAO DOGE LTC LIT ONDO SUI AERO PUMP PONS ZRO UNI PHA ADA JUP
ARB CASHCAT AVAX LINK LDO USELESS 2Z STRK AAVE JTO NIL QNT FARTCOIN MON CHIP PEPE CAKE ETHFI TRUMP PENGU
MET XMR ACE INJ CC VVV RARE EIGEN GRASS ARK APT RAY SHELL MORPHO AVNT AEVO PENDLE FET OPG MNT VIRTUAL ASTER
DASH CRV MUBARAK BCH AXS EDGE RUNE BR ZAMA SPX KAITO XLM POL BONK AKE DOT SAGA LSK PEAQ SYRUP RENDER SEI
VELODROME RPL ICP TIA KAVA SPK XTZ REZ PLUME KMNO MOODENG OP MEGA ALGO ATH GRVT OKB BROCCOLI714 ROSE ONE W SKY
FLOCK ETC PYTH OVERTAKE PTB H ALICE RAVE ZETA SNX DEEP MANA HBAR ZORA AR ENS POPCAT CRO METIS TRX GRT FLOKI FLR
MEW 0G ZK IOTA STX BITLIGHT PROVE B3 ORCA SONIC KITE HUMA FF ORDI ZBT WAL WIF Q KAS FIL MINA ME RED AKT TNSR
COMP SAND STG AGI DRIFT ZEN UAI BEAT COTI ONG ANIME DBR NXPC EUL ATOM TLM PUNDIX TRADOOR BIO GIGGLE CLANKER
PROMPT PIEVERSE GALA COOKIE TUT SPELL IO ORDER SUSHI AIXBT CETUS PEOPLE CHILLGUY CHZ 4 TWT JASMY KSM PNUT
1INCH DIA HNT CFX POLYX SKRS AZTEC ALT UB NAORIS APE RIVER STBL SUPER ENSO C ZKC DUSK EDU BERA ALLO CVX GMT
KOMA SIGN LINEA POWR RLC AXL MAGMA NEO COW SQD BEAM STEEM WOO ARKM WLFI AIOZ ALCH BLAST US SSV BABY EGLD CAP
CVC BB PUFFER SXT APEX T BTR LUNA CYS WCT MYX CYBER ZEREBRO MELANIA IOTX IOST ZRX IN WAVES GMX ENJ INIT BAT
ILV USUAL AVA TOWNS CROSS POWER SANTOS IRYS VELO HEI JST THETA RECALL GOAT LPT BASED DOLO F TURTLE IMX MITO
FOLKS SENTIENT SFP QTUM DYM XAN ACH GLM BIGTIME CGPT WET KAIA ESP SAFE LA CARV BOME ZIL ONT CKB
ANKR SOON OG USTC HAEDAL ICNT MMT HOLO ARPA ASTR VET XPIN CATI BREV MOVR XDC LQTY C98 FLUID ELSA MOVE STORJ API3
HEMI TRUST MAVIA BAND BANANAS31 PORTAL HMSTR CELO PIXEL LAB M B2 GPS ESPORTS SOMI XCN STABLE RVN BLUR CORE GWEI
MAGIC XVG PARTI DEXE STO KGEN FLUX YFI YGG RSR BLESS MASK ZBCN ID NEIRO NOT HOME BICO IDOL FIDA FOGO AIOT SLP
ERA TAIKO SKL HYPER KNC BMT AUCTION TREE NMR TA TRB O KERNEL UMA TAG GAS ON BOBA BRETT VELVET MANTA XNY AGLD
VANA FLOW ASR S MAV YB CTC ALPINE A SOSO BSB LRC MERL CHR BEL SAPIEN SUN GENIUS SAHARA LUMIA DOOD BARD
ARIA SNT GUA BAN TAC MOG ARC SOPH SHIB DYDX MTL OGN BLUR JUP WIF PURR HFUN LAYER
"""
KNOWN_CRYPTO = set(KNOWN_CRYPTO_TXT.split())
# Fallback coin list (Variational tickers) if no DEX answers at all.
FALLBACK_CRYPTO = sorted(KNOWN_CRYPTO)

# DEX ticker quirks -> the common base symbol used by exchanges.
ALIAS = {
    "1NEIRO": "NEIRO", "BBIT": "BB", "FF0": "FF", "LUNA2": "LUNA", "VANATOKEN": "VANA", "PUMPFUN": "PUMP",
    "BABYL": "BABY", "LAGRANGE": "LA", "ALLORA": "ALLO", "METEORA": "MET", "TUTORIAL": "TUT", "SOPHON": "SOPH",
    "BTR0": "BTR", "HUMIDIFI": "WET", "ARCSOL": "ARC", "ESPRESSO": "ESP", "BROCCOLI": "BROCCOLI714",
    "LIGHTER": "LIT", "1MBABYDOGE": "BABYDOGE",
}
# Exchange symbols that differ from "<coin>_USDT" / "<coin>USDT".
SYMBOL_OVERRIDE = {
    ("mexc", "PUMP"): "PUMPFUN_USDT",
}
CEX_SOURCES = ("mexc", "gate", "bitget")
SOURCES = CEX_SOURCES + ("hyperliquid", "aster")
SOURCE_NAME = {"mexc": "MEXC futures", "gate": "Gate.io futures", "bitget": "Bitget futures",
               "hyperliquid": "Hyperliquid", "aster": "Aster"}


# --------------------------------------------------------------------------- small helpers
def now_ts() -> int:
    return int(time.time())


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hhmm(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%H:%M")


def fnum(x, default=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def median(xs, default=0.0):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else default


def rnd(x, nd=4):
    return None if x is None else round(x, nd)


def fp(x) -> str:
    """Format a price with sensible precision for its magnitude."""
    if x is None:
        return "-"
    a = abs(x)
    if a >= 1000:
        return f"{x:,.1f}"
    if a >= 100:
        return f"{x:.2f}"
    if a >= 10:
        return f"{x:.3f}"
    if a >= 1:
        return f"{x:.4f}"
    if a >= 0.1:
        return f"{x:.4f}"
    if a >= 0.01:
        return f"{x:.5f}"
    if a >= 0.001:
        return f"{x:.6f}"
    return f"{x:.4g}"


def fps(values):
    """Format several prices with the precision of the largest one."""
    vals = [v for v in values if v is not None]
    if not vals:
        return ["-" for _ in values]
    ref = fp(max(abs(v) for v in vals))
    nd = len(ref.split(".")[1]) if "." in ref and "e" not in ref else None
    if nd is None:
        return [fp(v) for v in values]
    return [("-" if v is None else f"{v:,.{nd}f}" if abs(v) >= 1000 else f"{v:.{nd}f}") for v in values]


def pc(x, nd=1, sign=True) -> str:
    """Format a fraction (0.034) as a percent string (+3.4%)."""
    if x is None:
        return "-"
    s = f"{x * 100:+.{nd}f}%" if sign else f"{x * 100:.{nd}f}%"
    return s.replace("-", "−")


def usd(x) -> str:
    if x is None:
        return "-"
    if x >= 1e9:
        return f"${x / 1e9:.1f}B"
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    if x >= 1e3:
        return f"${x / 1e3:.0f}K"
    return f"${x:.0f}"


def log(msg):
    print(f"[{hhmm(time.time())}] {msg}", flush=True)




# --------------------------------------------------------------------------- HTTP layer
class HttpError(Exception):
    def __init__(self, code, msg=""):
        super().__init__(f"HTTP {code} {msg}".strip())
        self.code = code


UA = "Mozilla/5.0 (compatible; perp-dex-radar/%s)" % VERSION
_host_lock = threading.Lock()
_host_next = {}
HOST_GAP = {"contract.mexc.com": 0.11, "api.gateio.ws": 0.09, "api.bitget.com": 0.09,
            "api.hyperliquid.xyz": 0.12, "fapi.asterdex.com": 0.08}


def _throttle(url):
    host = url.split("/")[2]
    gap = HOST_GAP.get(host, 0.2)
    with _host_lock:
        t = time.monotonic()
        nxt = max(t, _host_next.get(host, 0.0))
        _host_next[host] = nxt + gap
    delay = nxt - t
    if delay > 0:
        time.sleep(delay)


def throttle_key(key, gap):
    """Extra spacing for expensive request types that share a host with cheap ones."""
    with _host_lock:
        t = time.monotonic()
        nxt = max(t, _host_next.get(key, 0.0))
        _host_next[key] = nxt + gap
    if nxt - t > 0:
        time.sleep(nxt - t)


def http_json(url, body=None, timeout=25, retries=3):
    """GET (or POST a JSON body) and parse JSON. 400/404 raise HttpError at once
    (no data); 429/5xx and network errors are retried with backoff."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries):
        _throttle(url)
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = HttpError(e.code, getattr(e, "reason", ""))
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1) + random.random())
                continue
            raise last
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.0 + attempt)
                continue
            raise
    raise last  # pragma: no cover


# Tests swap this for a fixture reader. Signature: FETCH(url, body=None, timeout=25)
FETCH = http_json


class Breaker:
    """Stops calling a source after repeated hard failures (blocked, down)."""

    def __init__(self, limit=12):
        self.limit, self.fails, self.lock = limit, 0, threading.Lock()

    @property
    def open(self):
        return self.fails >= self.limit

    def ok(self):
        with self.lock:
            self.fails = 0

    def fail(self):
        with self.lock:
            self.fails += 1


BREAKERS = {s: Breaker() for s in SOURCES + ("gate_stats", "smart")}
ERRORS: list[str] = []
_err_lock = threading.Lock()


def note_error(msg):
    with _err_lock:
        if len(ERRORS) < 80 and msg not in ERRORS:
            ERRORS.append(msg)


def is_hard_failure(e) -> bool:
    if isinstance(e, HttpError):
        return e.code not in (400, 404)
    return True


def parallel(fn, items, workers=None):
    out = {}
    with cf.ThreadPoolExecutor(max_workers=workers or CFG["workers"]) as ex:
        futs = {ex.submit(fn, it): it for it in items}
        for f in cf.as_completed(futs):
            it = futs[f]
            try:
                out[it] = f.result()
            except Exception as e:  # noqa: BLE001
                note_error(f"{it}: {e}")
                out[it] = None
    return out


# --------------------------------------------------------------------------- DEX universe
def mult_split(sym):
    """'1000PEPE' -> ('PEPE', 1000), 'kPEPE' -> ('PEPE', 1000), '1000000MOG' -> ('MOG', 1e6)."""
    s = str(sym).strip()
    if len(s) > 1 and s[0] == "k" and s[1:].isupper():
        return s[1:], 1000.0
    u = s.upper()
    for p, m in (("1000000", 1e6), ("1000", 1e3), ("1M", 1e6)):
        if u.startswith(p) and len(u) > len(p) and u[len(p)].isalpha():
            return u[len(p):], m
    return u, 1.0


def canon(sym):
    """DEX symbol -> (coin, multiplier)."""
    u = str(sym).strip()
    if u.upper() in ALIAS:
        return ALIAS[u.upper()], 1.0
    base, mult = mult_split(u)
    return ALIAS.get(base, base), mult


def is_fx(t):
    return len(t) == 6 and t[:3] in FX_CODES and t[3:] in FX_CODES


def is_tradfi(t, name=None):
    if t in TRADFI or is_fx(t):
        return True
    if t in KNOWN_CRYPTO:
        return False
    return bool(name and TRADFI_NAME.search(name))


def _venue(t, dex, sym, mult, price=None, vol=None, oi=None, funding8h=None, tradfi=None, **extra):
    v = {"t": t, "dex": dex, "sym": sym, "mult": mult, "price": price, "vol": vol, "oi": oi,
         "funding8h": funding8h, "tradfi": is_tradfi(t, extra.get("name")) if tradfi is None else tradfi}
    v.update(extra)
    return v


def dex_variational():
    d = FETCH(VAR_STATS)
    out = []
    for L in d.get("listings") or []:
        sym = str(L.get("ticker", "")).strip()
        if not sym:
            continue
        t, mult = canon(sym)
        oi = L.get("open_interest") or {}
        lo, so = fnum(oi.get("long_open_interest")), fnum(oi.get("short_open_interest"))
        apr = fnum(L.get("funding_rate"))
        out.append(_venue(t, "variational", sym, mult, price=fnum(L.get("mark_price")),
                          vol=fnum(L.get("volume_24h")), oi=(lo or 0) + (so or 0) if lo is not None else None,
                          funding8h=apr * 8 / 8760 if apr is not None else None, oi_long=lo, oi_short=so,
                          spread_bps=fnum(L.get("base_spread_bps")), name=L.get("name") or sym))
    return out


def dex_hyperliquid():
    d = FETCH(HL_INFO, {"type": "metaAndAssetCtxs"})
    meta, ctxs = d[0], d[1]
    out = []
    for asset, ctx in zip(meta.get("universe") or [], ctxs):
        name = str(asset.get("name", ""))
        if not name or ":" in name or asset.get("isDelisted"):
            continue
        t, mult = canon(name)
        px = fnum(ctx.get("markPx")) or fnum(ctx.get("oraclePx"))
        oi_base, fr = fnum(ctx.get("openInterest")), fnum(ctx.get("funding"))
        out.append(_venue(t, "hyperliquid", name, mult, price=px, vol=fnum(ctx.get("dayNtlVlm")),
                          oi=oi_base * px if oi_base is not None and px else None,
                          funding8h=fr * 8 if fr is not None else None))
    return out


def dex_aster():
    info = FETCH(ASTER_INFO)
    try:
        tick = {x["symbol"]: x for x in FETCH(ASTER_TICKER) if isinstance(x, dict)}
    except Exception as e:  # noqa: BLE001
        note_error(f"aster tickers: {e}")
        tick = {}
    try:
        prem = {x["symbol"]: x for x in FETCH(ASTER_PREMIUM) if isinstance(x, dict)}
    except Exception as e:  # noqa: BLE001
        note_error(f"aster funding: {e}")
        prem = {}
    out = []
    for s in info.get("symbols") or []:
        if s.get("contractType", "PERPETUAL") != "PERPETUAL" or s.get("status", "TRADING") != "TRADING":
            continue
        sym = s.get("symbol", "")
        base_asset = s.get("baseAsset") or re.sub(r"(USDT|USDC|USD)$", "", sym)
        t, mult = canon(base_asset)
        tk, pr = tick.get(sym, {}), prem.get(sym, {})
        ut = s.get("underlyingType")
        out.append(_venue(t, "aster", sym, mult, price=fnum(tk.get("lastPrice")) or fnum(pr.get("markPrice")),
                          vol=fnum(tk.get("quoteVolume")), funding8h=fnum(pr.get("lastFundingRate")),
                          tradfi=True if ut and ut != "COIN" else None))
    return out


def dex_edgex():
    d = FETCH(EDGEX_META)
    lst = ((d.get("data") or {}).get("contractList")) or []
    out = []
    for c in lst:
        if c.get("enableTrade") is False or c.get("enableDisplay") is False:
            continue
        name = str(c.get("contractName") or "")
        base = re.sub(r"(USDT|USDC|USD)$", "", name.upper().replace("-PERP", "").replace("-", "").replace("_", ""))
        if not base:
            continue
        t, mult = canon(base)
        out.append(_venue(t, "edgex", name, mult))
    return out


def dex_lighter():
    d = FETCH(LIGHTER_BOOKS)
    lst = d.get("order_book_details") or d.get("order_books") or []
    out = []
    for b in lst:
        if b.get("market_type", "perp") != "perp" or b.get("status", "active") != "active":
            continue
        sym = str(b.get("symbol", ""))
        if not sym:
            continue
        t, mult = canon(sym)
        out.append(_venue(t, "lighter", sym, mult, price=fnum(b.get("mark_price")) or fnum(b.get("last_trade_price")),
                          vol=fnum(b.get("daily_quote_token_volume"))))
    return out


def dex_dydx():
    d = FETCH(DYDX_MARKETS)
    out = []
    for tk, m in (d.get("markets") or {}).items():
        if m.get("status") != "ACTIVE":
            continue
        t, mult = canon(tk.split("-")[0])
        px, oi_base, fr = fnum(m.get("oraclePrice")), fnum(m.get("openInterest")), fnum(m.get("nextFundingRate"))
        out.append(_venue(t, "dydx", tk, mult, price=px, vol=fnum(m.get("volume24H")),
                          oi=oi_base * px if oi_base is not None and px else None,
                          funding8h=fr * 8 if fr is not None else None))
    return out


def dex_paradex():
    d = FETCH(PARADEX_SUMMARY, timeout=40)
    out = []
    for r in d.get("results") or []:
        sym = str(r.get("symbol", ""))
        if not sym.endswith("-PERP"):
            continue
        t, mult = canon(sym.split("-")[0])
        px = fnum(r.get("mark_price")) or fnum(r.get("last_traded_price"))
        oi_base = fnum(r.get("open_interest"))
        out.append(_venue(t, "paradex", sym, mult, price=px, vol=fnum(r.get("volume_24h")),
                          oi=oi_base * px if oi_base is not None and px else None,
                          funding8h=fnum(r.get("funding_rate"))))
    return out


def dex_extended():
    d = FETCH(EXTENDED_MARKETS)
    out = []
    for m in d.get("data") or []:
        if m.get("active") is False or m.get("status", "ACTIVE") != "ACTIVE":
            continue
        if m.get("type") and m["type"] != "PERPETUAL":
            continue
        name = str(m.get("name", ""))
        t, mult = canon(m.get("assetName") or name.split("-")[0])
        st = m.get("marketStats") or {}
        fr = fnum(st.get("fundingRate"))
        cat = m.get("category")
        out.append(_venue(t, "extended", name, mult, price=fnum(st.get("markPrice")) or fnum(st.get("lastPrice")),
                          vol=fnum(st.get("dailyVolume")), oi=fnum(st.get("openInterest")),
                          funding8h=fr * 8 if fr is not None else None,
                          tradfi=True if (cat and cat != "Crypto") or "_24_5" in name else None,
                          name=m.get("description")))
    return out


DEX_FETCHERS = {"hyperliquid": dex_hyperliquid, "variational": dex_variational, "aster": dex_aster,
                "edgex": dex_edgex, "lighter": dex_lighter, "dydx": dex_dydx, "paradex": dex_paradex,
                "extended": dex_extended}


def build_universe():
    """Merge every DEX's market list into one dict of coins."""
    status, coins = {}, {}
    results = parallel(lambda dex: DEX_FETCHERS[dex](), list(DEXES), workers=len(DEXES))
    for dex in DEXES:
        rows = results.get(dex)
        if rows is None:
            status[dex] = {"ok": False, "markets": 0, "crypto": 0}
            continue
        status[dex] = {"ok": True, "markets": len(rows), "crypto": sum(1 for r in rows if not r["tradfi"])}
        for r in rows:
            c = coins.setdefault(r["t"], {"t": r["t"], "venues": {}, "name": None, "tradfi": False})
            old = c["venues"].get(dex)
            if old is None or (r.get("vol") or 0) > (old.get("vol") or 0):
                c["venues"][dex] = r
            if r.get("name") and not c["name"] and dex in ("variational", "extended"):
                c["name"] = r["name"]
            c["tradfi"] = c["tradfi"] or r["tradfi"]
    for t, c in coins.items():
        priced = [(dex, v["price"] / v["mult"], v.get("vol") or 0) for dex, v in c["venues"].items() if v.get("price")]
        ref = None
        if priced:
            # anchor on the most traded venue; a venue far from it lists a different asset under this ticker
            anchor = max(priced, key=lambda x: x[2])
            ref = anchor[1] if anchor[2] > 0 else median([p for _, p, _ in priced], None)
            if len(priced) >= 2:
                for dex, p, _ in priced:
                    if abs(p / ref - 1) > 0.2:
                        note_error(f"{t}: {DEX_NAME[dex]} price {fp(p)} differs from the main market ({fp(ref)}); left out")
                        c["venues"].pop(dex, None)
                ref = median([v["price"] / v["mult"] for v in c["venues"].values() if v.get("price")], ref)
        c["ref_price"] = ref
        vols = [v["vol"] for v in c["venues"].values() if v.get("vol")]
        c["best_vol"] = max(vols) if vols else None
        c["tot_vol"] = sum(vols) if vols else None
        c["tradfi"] = c["tradfi"] or is_tradfi(t, c.get("name"))
    coins = {t: c for t, c in coins.items() if c["venues"]}
    any_ok = any(s["ok"] for s in status.values())
    if not any_ok:
        note_error("No DEX market list could be loaded; using the built-in coin list without DEX data")
        coins = {t: {"t": t, "venues": {}, "name": t, "tradfi": False, "ref_price": None, "best_vol": None,
                     "tot_vol": None} for t in FALLBACK_CRYPTO}
    return coins, status, any_ok


# --------------------------------------------------------------------------- candles
def exchange_symbol(src, coin):
    if (src, coin) in SYMBOL_OVERRIDE:
        return SYMBOL_OVERRIDE[(src, coin)]
    return f"{coin}USDT" if src == "bitget" else f"{coin}_USDT"


IV = {"mexc": {"15m": "Min15", "1h": "Min60"}, "gate": {"15m": "15m", "1h": "1h"},
      "bitget": {"15m": "15m", "1h": "1H"}, "hyperliquid": {"15m": "15m", "1h": "1h"},
      "aster": {"15m": "15m", "1h": "1h"}}
TF_SEC = {"15m": 900, "1h": 3600}


def _clean(rows):
    """rows: list of (t, o, h, l, c, quote_volume) -> sorted, de-duplicated, sane candles."""
    out, seen = [], set()
    for t, o, h, l, c, qv in sorted(rows, key=lambda r: r[0]):
        if t in seen or None in (o, h, l, c) or min(o, h, l, c) <= 0:
            continue
        seen.add(t)
        out.append({"t": int(t), "o": o, "h": max(o, h, l, c), "l": min(o, h, l, c), "c": c, "qv": qv or 0.0})
    return out


PAGE = 1000  # candles per request when a long history is needed (the exchanges cap requests at 1000-2000)


def _mexc_rows(d):
    if not isinstance(d, dict) or not d.get("success", True) or not isinstance(d.get("data"), dict):
        return []
    k = d["data"]
    t = k.get("time") or []
    rows = []
    for i in range(len(t)):
        try:
            rows.append((int(t[i]), fnum(k["open"][i]), fnum(k["high"][i]), fnum(k["low"][i]),
                         fnum(k["close"][i]), fnum(k.get("amount", [0] * len(t))[i], 0.0)))
        except (IndexError, KeyError, TypeError):
            break
    return rows


def fetch_mexc(sym, tf, bars):
    step, e = TF_SEC[tf], now_ts()
    rows, left = [], bars + 1
    while left > 0:
        n = min(left, PAGE)
        st = e - step * n
        chunk = _mexc_rows(FETCH(MEXC_KLINE.format(sym=sym, iv=IV["mexc"][tf], start=st, end=e)))
        rows = chunk + rows
        left -= n
        if len(chunk) < n // 2:  # no older history
            break
        e = st - 1
    return _clean(rows)[-bars:]


def _gate_rows(d):
    if not isinstance(d, list):
        return []
    return [(int(x["t"]), fnum(x.get("o")), fnum(x.get("h")), fnum(x.get("l")), fnum(x.get("c")),
             fnum(x.get("sum"), 0.0)) for x in d if isinstance(x, dict) and "t" in x]


def fetch_gate(sym, tf, bars):
    if bars <= PAGE:
        return _clean(_gate_rows(FETCH(GATE_KLINE.format(sym=sym, iv=IV["gate"][tf], limit=bars))))[-bars:]
    step, e = TF_SEC[tf], now_ts()
    rows, left = [], bars + 1
    while left > 0:
        n = min(left, PAGE)
        st = e - step * n
        chunk = _gate_rows(FETCH(GATE_KLINE_RANGE.format(sym=sym, iv=IV["gate"][tf], start=st, end=e)))
        rows = chunk + rows
        left -= n
        if len(chunk) < n // 2:
            break
        e = st - 1
    return _clean(rows)[-bars:]


def _bitget_rows(d):
    if not isinstance(d, dict) or str(d.get("code")) != "00000" or not isinstance(d.get("data"), list):
        return []
    return [(int(int(x[0]) / 1000), fnum(x[1]), fnum(x[2]), fnum(x[3]), fnum(x[4]), fnum(x[6], 0.0))
            for x in d["data"] if isinstance(x, list) and len(x) >= 7]


def fetch_bitget(sym, tf, bars):
    url = BITGET_KLINE.format(sym=sym, iv=IV["bitget"][tf], limit=min(bars, PAGE))
    rows = _bitget_rows(FETCH(url))
    while rows and len(rows) < bars:  # page back in time with endTime
        oldest = min(r[0] for r in rows)
        chunk = _bitget_rows(FETCH(url + f"&endTime={oldest * 1000 - 1}"))
        if not chunk or min(r[0] for r in chunk) >= oldest:
            break
        rows = chunk + rows
    return _clean(rows)[-bars:]


def fetch_hyperliquid(sym, tf, bars):
    throttle_key("hl_candles", 1.1)  # candleSnapshot costs 20 of Hyperliquid's 1200 weight/min
    end = now_ts() * 1000
    start = end - TF_SEC[tf] * 1000 * (bars + 1)  # up to 5000 candles in one request
    d = FETCH(HL_INFO, {"type": "candleSnapshot", "req": {"coin": sym, "interval": IV["hyperliquid"][tf],
                                                           "startTime": start, "endTime": end}})
    if not isinstance(d, list):
        return []
    rows = []
    for x in d:
        if isinstance(x, dict) and "t" in x:
            c = fnum(x.get("c"))
            rows.append((int(x["t"]) // 1000, fnum(x.get("o")), fnum(x.get("h")), fnum(x.get("l")), c,
                         (fnum(x.get("v"), 0.0) or 0.0) * (c or 0.0)))
    return _clean(rows)[-bars:]


def _aster_rows(d):
    if not isinstance(d, list):
        return []
    return [(int(x[0]) // 1000, fnum(x[1]), fnum(x[2]), fnum(x[3]), fnum(x[4]), fnum(x[7], 0.0))
            for x in d if isinstance(x, list) and len(x) >= 8]


def fetch_aster(sym, tf, bars):
    url = ASTER_KLINE.format(sym=sym, iv=IV["aster"][tf], limit=min(bars, PAGE))
    rows = _aster_rows(FETCH(url))
    while rows and len(rows) < bars:
        oldest = min(r[0] for r in rows)
        chunk = _aster_rows(FETCH(url + f"&endTime={oldest * 1000 - 1}"))
        if not chunk or min(r[0] for r in chunk) >= oldest:
            break
        rows = chunk + rows
    return _clean(rows)[-bars:]



FETCHERS = {"mexc": fetch_mexc, "gate": fetch_gate, "bitget": fetch_bitget, "hyperliquid": fetch_hyperliquid,
            "aster": fetch_aster}


def detect_scale(ref_price, candles):
    """Scale candles to price-per-coin units. Returns (scale, ok); ok=False means
    the exchange contract is a different asset. The price may have moved between
    requests, so the recent range counts too."""
    ex_price = candles[-1]["c"] if candles else None
    if not ref_price or not ex_price:
        return 1.0, True
    r = ref_price / ex_price
    k = round(math.log10(r))
    s = 10.0 ** k
    if abs(r / s - 1) < 0.05:
        return s, True
    recent = candles[-4:]
    lo, hi = min(x["l"] for x in recent) * s, max(x["h"] for x in recent) * s
    return s, lo * 0.97 <= ref_price <= hi * 1.03


def get_candles(coin, tf, bars, prefer=None):
    """Try each source until one returns enough candles for the same asset.
    Prices come back per 1 coin (DEX multipliers removed)."""
    t, venues = coin["t"], coin.get("venues") or {}
    order = list(SOURCES)
    if prefer in order:
        order.remove(prefer)
        order.insert(0, prefer)
    min_bars = min(bars, 30 if tf == "1h" else 60)
    mismatch = []
    for src in order:
        if BREAKERS[src].open:
            continue
        if src in ("hyperliquid", "aster"):
            v = venues.get(src)
            if not v:
                continue
            sym = v["sym"]
        else:
            sym = exchange_symbol(src, t)
        try:
            c = FETCHERS[src](sym, tf, bars)
            BREAKERS[src].ok()
        except Exception as e:  # noqa: BLE001 - any failure moves on to the next source
            if is_hard_failure(e):
                BREAKERS[src].fail()
                note_error(f"{src} {sym} {tf}: {e}")
            continue
        if len(c) < min_bars:
            continue
        ref = coin.get("ref_price")
        if not ref and src in ("hyperliquid", "aster"):
            ref = c[-1]["c"] / venues[src]["mult"]
        scale, ok = detect_scale(ref, c)
        if not ok:
            mismatch.append(src)
            continue
        if scale != 1.0:
            for x in c:
                for k in ("o", "h", "l", "c"):
                    x[k] *= scale
        return {"src": src, "sym": sym, "scale": scale, "candles": c, "fetched": now_ts()}
    if mismatch:
        note_error(f"{t}: {', '.join(mismatch)} price does not match the DEX price; skipped there")
    return None


# --------------------------------------------------------------------------- indicators
def ema(vals, n):
    k, out, e = 2 / (n + 1), [], None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def rsi_series(vals, n=14):
    out = [None] * len(vals)
    if len(vals) <= n:
        return out
    g = [max(vals[i] - vals[i - 1], 0) for i in range(1, len(vals))]
    l_ = [max(vals[i - 1] - vals[i], 0) for i in range(1, len(vals))]
    ag, al = sum(g[:n]) / n, sum(l_[:n]) / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + l_[i]) / n
        out[i + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def macd_hist(vals, f=12, s=26, sig=9):
    m = [a - b for a, b in zip(ema(vals, f), ema(vals, s))]
    return [a - b for a, b in zip(m, ema(m, sig))]


def true_ranges(c):
    tr = []
    for i, x in enumerate(c):
        if i == 0:
            tr.append(x["h"] - x["l"])
        else:
            pc_ = c[i - 1]["c"]
            tr.append(max(x["h"] - x["l"], abs(x["h"] - pc_), abs(x["l"] - pc_)))
    return tr


def atr_series(c, n=14):
    tr, out = true_ranges(c), [None] * len(c)
    if len(c) < n:
        return out
    a = sum(tr[:n]) / n
    out[n - 1] = a
    for i in range(n, len(c)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def adx(c, n=14):
    """Wilder ADX. Returns (adx, +DI, -DI) for the last bar, or None."""
    if len(c) < 2 * n + 2:
        return None
    tr, pdm, mdm = [0.0], [0.0], [0.0]
    for i in range(1, len(c)):
        up, dn = c[i]["h"] - c[i - 1]["h"], c[i - 1]["l"] - c[i]["l"]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
        pc_ = c[i - 1]["c"]
        tr.append(max(c[i]["h"] - c[i]["l"], abs(c[i]["h"] - pc_), abs(c[i]["l"] - pc_)))
    s_tr, s_p, s_m = sum(tr[1:n + 1]), sum(pdm[1:n + 1]), sum(mdm[1:n + 1])
    dxs, pdi, mdi = [], 0.0, 0.0
    for i in range(n + 1, len(c)):
        s_tr += tr[i] - s_tr / n
        s_p += pdm[i] - s_p / n
        s_m += mdm[i] - s_m / n
        pdi = 100 * s_p / s_tr if s_tr else 0.0
        mdi = 100 * s_m / s_tr if s_tr else 0.0
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
    if len(dxs) < n:
        return None
    a = sum(dxs[:n]) / n
    for d in dxs[n:]:
        a = (a * (n - 1) + d) / n
    return a, pdi, mdi


def bb_width(closes, n=20, k=2.0):
    out = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        w = closes[i - n + 1:i + 1]
        m = sum(w) / n
        sd = (sum((x - m) ** 2 for x in w) / n) ** 0.5
        out[i] = (2 * k * sd) / m if m else None
    return out


def swing_lows(c, lookback=40, k=2):
    """Fractal swing lows (index, price) within the last `lookback` bars."""
    out, n = [], len(c)
    for i in range(max(k, n - lookback), n - k):
        lo = c[i]["l"]
        if all(lo <= c[j]["l"] for j in range(i - k, i + k + 1) if j != i):
            out.append((i, lo))
    return out


def swing_highs(c, lookback=40, k=2):
    out, n = [], len(c)
    for i in range(max(k, n - lookback), n - k):
        hi = c[i]["h"]
        if all(hi >= c[j]["h"] for j in range(i - k, i + k + 1) if j != i):
            out.append((i, hi))
    return out


def higher_lows(lows):
    """Length of the rising run at the end of a swing-low list."""
    run = 1 if lows else 0
    for i in range(len(lows) - 1, 0, -1):
        if lows[i][1] > lows[i - 1][1]:
            run += 1
        else:
            break
    return run


def efficiency(closes, n=12):
    seg = closes[-(n + 1):]
    path = sum(abs(seg[i] - seg[i - 1]) for i in range(1, len(seg)))
    return abs(seg[-1] - seg[0]) / path if path else 0.0



def agg_tf(c, sec):
    """Merge candles into `sec`-second candles (aligned to UTC)."""
    out, cur = [], None
    for x in c:
        h = x["t"] - x["t"] % sec
        if cur is None or cur["t"] != h:
            if cur:
                out.append(cur)
            cur = {"t": h, "o": x["o"], "h": x["h"], "l": x["l"], "c": x["c"], "qv": x["qv"]}
        else:
            cur["h"] = max(cur["h"], x["h"])
            cur["l"] = min(cur["l"], x["l"])
            cur["c"] = x["c"]
            cur["qv"] += x["qv"]
    if cur:
        out.append(cur)
    return out


def htf_from(closes, px):
    """4-hour trend from 4h closes: up = price > EMA20 > EMA50, down = the reverse."""
    if len(closes) < 30:
        return None
    e20, e50 = ema(closes, 20)[-1], ema(closes, 50)[-1]
    r = rsi_series(closes, 14)[-1]
    trend = "up" if px > e20 > e50 else "down" if px < e20 < e50 else "mixed"
    return {"trend": trend, "e20": e20, "e50": e50, "rsi": r if r is not None else 50.0, "dist20": px / e20 - 1,
            "chg24": closes[-1] / closes[-7] - 1 if len(closes) > 7 else None}


def htf_metrics(h1c, px=None, now=None):
    """4-hour trend from 1h candles. With `now`, only 4h candles closed by then count (as in the backtest)."""
    h4 = agg_tf(h1c, 14400)
    if now is not None:
        h4 = [x for x in h4 if x["t"] + 14400 <= now]
    return htf_from([x["c"] for x in h4], px if px is not None else h1c[-1]["c"]) if h4 else None


# --------------------------------------------------------------------------- stage 1 (1h, every coin)
def h1_metrics(c, pre=None):
    """1h momentum metrics. `pre` = (closes, ema8, ema21, rsi of the last bar) computed on a
    longer series and cut to line up with `c` (the backtest reuses them)."""
    if pre:
        closes, e8, e21, rsi = pre
    else:
        closes = [x["c"] for x in c]
        e8, e21 = ema(closes, 8), ema(closes, 21)
        rsi = rsi_series(closes, 14)[-1]
    n, last = len(closes), closes[-1]
    ref24 = closes[-25] if n >= 25 else closes[0]
    win = c[-25:]
    hi24, lo24 = max(x["h"] for x in win), min(x["l"] for x in win)
    qv = [x["qv"] for x in c]
    comp = qv[:-1]  # the last bar is still forming
    base = comp[-25:-4] if len(comp) >= 29 else comp[:-3]
    med = median(base, 0.0)
    v3 = sum(comp[-3:]) / 3 if len(comp) >= 3 else 0.0
    return {
        "last": last,
        "r1": last / closes[-2] - 1, "r3": last / closes[-4] - 1, "r6": last / closes[-7] - 1,
        "r12": last / closes[-13] - 1, "r24": last / ref24 - 1,
        "hi24": hi24, "lo24": lo24,
        "pos": (last - lo24) / (hi24 - lo24) if hi24 > lo24 else 0.5,
        "trend": e8[-1] / e21[-1] - 1, "slope": e8[-1] / e8[-4] - 1,
        "rsi": rsi if rsi is not None else 50.0,
        "vr": v3 / med if med > 0 else 1.0,
        "turn": sum(comp[-24:]),
        "er": efficiency(closes, 12),
        "above": sum(1 for i in range(1, 7) if closes[-i] > e21[-i]),
        "spark": closes[-25:],
    }


def stage1_score(m):
    s = 0.0
    s += clamp(m["r3"] * 100, -6, 6) * 1.2
    s += clamp(m["r6"] * 100, -10, 10) * 0.8
    s += clamp(m["r24"] * 100, -15, 15) * 0.35
    s += clamp(m["rs6"] * 100, -8, 8) * 0.5
    s += (m["pos"] - 0.5) * 6
    s += clamp(m["trend"] * 100, -4, 4)
    s += clamp(m["slope"] * 100, -3, 3)
    s += clamp(math.log(max(m["vr"], 0.05)), -1.5, 2.0) * 2.0
    s += m["er"] * 3
    s += (m["above"] - 3) * 0.4
    if m["rsi"] > 78:
        s -= (m["rsi"] - 78) * 0.25
    if m["r24"] > 0.35:
        s -= 3
    return s


# --------------------------------------------------------------------------- stage 2 (15m deep dive)
def sig6(x):
    return None if x is None else float(f"{x:.6g}")


def m15_analysis(c, chart=True):
    """All 15m indicators and structure used for setups and write-ups (chart=False skips
    the candle arrays the page draws, for the backtest)."""
    closes = [x["c"] for x in c]
    n, last = len(c), closes[-1]
    e9s, e21s, e50s = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    rsis = rsi_series(closes, 14)
    hist = macd_hist(closes)
    atr = atr_series(c, 14)[-1] or last * 0.01
    ad = adx(c, 14)
    bw = bb_width(closes, 20, 2.0)
    bw_valid = [x for x in bw[-96:] if x is not None]
    bw_now = bw[-1]
    bw_pct = (100 * sum(1 for x in bw_valid if x <= bw_now) / len(bw_valid)) if bw_valid and bw_now else 50.0
    tp = [(x["h"] + x["l"] + x["c"]) / 3 for x in c]
    base_vol = [x["qv"] / t if t else 0.0 for x, t in zip(c, tp)]
    vwap = sum(x["qv"] for x in c) / sum(base_vol) if sum(base_vol) > 0 else None
    qv = [x["qv"] for x in c]
    closed = qv[:-1]
    med = median(closed, 0.0)
    v3 = sum(closed[-3:]) / 3 if len(closed) >= 3 else 0.0
    vr = v3 / med if med > 0 else 1.0
    vmax8 = (max(closed[-8:]) / med) if med > 0 and closed else 1.0
    win = c[-96:]
    hi24, lo24 = max(x["h"] for x in win), min(x["l"] for x in win)
    prior = c[-35:-3] if n >= 40 else c[:-3]
    prior_hi, prior_lo = max(x["h"] for x in prior), min(x["l"] for x in prior)
    lows, highs = swing_lows(c, 48), swing_highs(c, 48)
    hl = higher_lows(lows)
    last_low = lows[-1][1] if lows else None
    # the most recent swing low that is below the current price (real support)
    support = next((p for _, p in reversed(lows) if p < last), None)
    # breakout of the prior 8h range within the last 3 bars
    brk = None
    for j in range(n - 3, n):
        if c[j]["c"] > prior_hi:
            brk = {"idx": j, "ago": n - 1 - j, "level": prior_hi, "bar_low": c[j]["l"],
                   "vol": (c[j]["qv"] / med) if med > 0 else 1.0}
            break
    # new highs in the last 8 bars
    hh = 0
    for j in range(n - 8, n):
        if c[j]["h"] > max(x["h"] for x in c[max(0, j - 24):j]):
            hh += 1
    hist_up = 0
    for j in range(n - 1, 1, -1):
        if hist[j] > hist[j - 1]:
            hist_up += 1
        else:
            break
    last_bar = c[-1]
    rng = last_bar["h"] - last_bar["l"]

    def chg(k):
        return last / closes[-1 - k] - 1 if n > k else None

    hi_3h = max(x["h"] for x in c[-13:-1]) if n > 13 else max(x["h"] for x in c[:-1])
    lo_3h = min(x["l"] for x in c[-13:-1]) if n > 13 else min(x["l"] for x in c[:-1])
    lo_prev3h = min(x["l"] for x in c[-25:-13]) if n > 25 else lo_3h
    # position of the close inside the Bollinger band (0 = lower band, 1 = upper band)
    w20 = closes[-20:]
    m20 = sum(w20) / len(w20)
    sd20 = (sum((x - m20) ** 2 for x in w20) / len(w20)) ** 0.5
    bb_pos = (last - (m20 - 2 * sd20)) / (4 * sd20) if sd20 > 0 else 0.5
    # breakout of the prior 24h high within the last 3 bars
    hi24_prior = max(x["h"] for x in c[-96:-3]) if n > 12 else prior_hi
    brk24 = None
    for j in range(n - 3, n):
        if c[j]["c"] > hi24_prior:
            brk24 = {"ago": n - 1 - j, "level": hi24_prior, "bar_low": c[j]["l"],
                     "vol": (c[j]["qv"] / med) if med > 0 else 1.0}
            break
    # EMA9 crossing above EMA21 within the last 6 bars (the base rule uses the last 3)
    cross_up_ago = None
    for j in range(n - 1, max(0, n - 7), -1):
        if e9s[j] > e21s[j] and e9s[j - 1] <= e21s[j - 1]:
            cross_up_ago = n - 1 - j
            break
    k = CFG["chart_bars"]
    return {
        "last": last, "atr": atr, "atr_pct": atr / last,
        "e9": e9s[-1], "e21": e21s[-1], "e50": e50s[-1],
        "slope21": e21s[-1] / e21s[-5] - 1 if n > 5 else 0.0,
        "dist21": last / e21s[-1] - 1, "ext21_atr": (last - e21s[-1]) / atr,
        "rsi": rsis[-1] if rsis[-1] is not None else 50.0,
        "rsi_prev": rsis[-5] if n > 5 and rsis[-5] is not None else 50.0,
        "rsi_1": rsis[-2] if n > 2 and rsis[-2] is not None else 50.0,
        "bb_pos": bb_pos, "lo_2h": min(x["l"] for x in c[-8:]),
        "below_vwap_recent": bool(vwap) and any(x["c"] < vwap for x in c[-9:-1]),
        "hi24_prior": hi24_prior, "brk24": brk24, "cross_up_ago": cross_up_ago,
        "hist": hist[-1], "hist_prev": hist[-2], "hist_up": hist_up,
        "adx": ad[0] if ad else None, "pdi": ad[1] if ad else None, "mdi": ad[2] if ad else None,
        "bw": bw_now, "bw_pct": bw_pct,
        "vwap": vwap, "vwap_dist": (last / vwap - 1) if vwap else None,
        "vr": vr, "vmax8": vmax8, "med_qv": med, "qv24": sum(closed[-96:]),
        "hi24": hi24, "lo24": lo24, "pos24": (last - lo24) / (hi24 - lo24) if hi24 > lo24 else 0.5,
        "dist_hi24": last / hi24 - 1,
        "prior_hi": prior_hi, "prior_lo": prior_lo,
        "hi_3h": hi_3h, "lo_3h": lo_3h, "lo_prev3h": lo_prev3h,
        "lows": [p for _, p in lows[-6:]], "highs": [p for _, p in highs[-4:]],
        "hl": hl, "last_swing_low": last_low, "support": support, "hh": hh,
        "breakout": brk,
        "close_pos": (last_bar["c"] - last_bar["l"]) / rng if rng > 0 else 0.5,
        "chg_1h": chg(4), "chg_4h": chg(16), "chg_16h": chg(64), "chg_24h": chg(95),
        "chart": None if not chart else {
            "t": [x["t"] for x in c[-k:]],
            "o": [sig6(x["o"]) for x in c[-k:]], "h": [sig6(x["h"]) for x in c[-k:]],
            "l": [sig6(x["l"]) for x in c[-k:]], "c": [sig6(x["c"]) for x in c[-k:]],
            "v": [round(x["qv"]) for x in c[-k:]],
            "e9": [sig6(x) for x in e9s[-k:]], "e21": [sig6(x) for x in e21s[-k:]],
        },
    }


# --------------------------------------------------------------------------- strategies
# Nine long-only strategies read the same 15m charts. Each proposes an entry zone,
# a stop under the level that proves it wrong and three targets in R (multiples of
# the risk). Every signal is paper-traded in the journal; the strategy tournament
# decides which strategies may be published (see "journal and learning").
STRATEGIES = {
    "BRK": {"name": "Range breakout retest", "short": "Breakout", "kind": "breakout", "base": 7,
            "tp_r": (1.2, 2.2, 3.5),
            "desc": "A 15m close above the prior 8-hour range high on strong volume. Buy the retest of the broken "
                    "high; stop under the level and the breakout candle."},
    "SQZ": {"name": "Squeeze break", "short": "Squeeze", "kind": "breakout", "base": 5, "tp_r": (1.2, 2.2, 3.5),
            "desc": "Bollinger width in the tightest quarter of the day while price holds the top of a rising "
                    "3-hour range. Buy only after a 15m close above the range high."},
    "PB": {"name": "EMA21 trend pullback", "short": "Pullback", "kind": "trend", "base": 6, "tp_r": (1.2, 2.2, 3.5),
           "desc": "Bullish EMA 9/21/50 stack with a rising EMA21; price dips into the EMA9-EMA21 area with RSI "
                   "42-66. Stop under EMA50 or the last swing low."},
    "MOM": {"name": "Trend continuation (EMA9 dip)", "short": "Momentum", "kind": "trend", "base": 6,
            "tp_r": (1.2, 2.2, 3.5),
            "desc": "Strong trend (ADX 22+, +DI over -DI, RSI 58-80) within 2% of the 24h high. Buy dips to EMA9; "
                    "stop under EMA21 and the last swing low."},
    "VWAP": {"name": "VWAP reclaim", "short": "VWAP", "kind": "reversal", "base": 6, "tp_r": (1.2, 2.2, 3.5),
             "desc": "Price traded below the 24h VWAP in the last two hours and closes back above it on 1.3x+ "
                     "volume while the 1h trend is not down. Buy at VWAP; stop under the 2-hour low."},
    "MR": {"name": "Oversold bounce in an uptrend", "short": "Dip buy", "kind": "reversal", "base": 5,
           "tp_r": (1.0, 1.8, 2.6),
           "desc": "The 1h trend is up but the 15m RSI is 32 or lower (or price sits on the lower Bollinger band) "
                   "within 1.5 ATR of a swing low, and the candle is turning up. Quick targets; stop under the low."},
    "SMF": {"name": "Smart-money follow", "short": "Smart money", "kind": "flow", "base": 6, "tp_r": (1.2, 2.2, 3.5),
            "desc": "At least 70% of the money Hyperliquid's top traders hold in the coin is long ($250K+ from 5+ "
                    "traders, not reduced since the last scan) and price is above EMA50. Buy near EMA21."},
    "HI24": {"name": "24-hour high breakout", "short": "24h high", "kind": "breakout", "base": 7,
             "tp_r": (1.5, 2.5, 4.0),
             "desc": "A 15m close above the prior 24-hour high on 2x+ volume. Buy the retest of the old high; "
                     "stop 1 ATR under it. Wider targets for a fresh daily breakout."},
    "XOVER": {"name": "EMA9/21 bull cross", "short": "EMA cross", "kind": "trend", "base": 5, "tp_r": (1.2, 2.2, 3.5),
              "desc": "EMA9 crossed above EMA21 in the last three candles with +DI over -DI, price above VWAP and "
                      "RSI 50-72. Buy near EMA21; stop under the 2-hour low."},
}
SID_ORDER = ["BRK", "SQZ", "PB", "MOM", "VWAP", "MR", "SMF", "HI24", "XOVER"]


def _bull(a):
    return a["e9"] > a["e21"] > a["e50"]


def _dmi_up(a):
    return a["pdi"] is not None and a["mdi"] is not None and a["pdi"] > a["mdi"]


# Rule parameters of each strategy: name -> (default, low, high, step). The defaults
# are the rules described in STRATEGIES; strategy discovery mutates them within the
# bounds to create variants.
PARAMS = {
    "BRK": {"brk_vol": (1.8, 1.2, 3.0, 0.2), "vr_min": (1.5, 1.0, 2.5, 0.25), "retest_atr": (0.25, 0.0, 0.6, 0.05),
            "zone_atr": (0.35, 0.15, 0.6, 0.05), "stop_atr": (0.9, 0.6, 1.5, 0.1)},
    "SQZ": {"bw_max": (25, 10, 40, 5), "range_atr": (4.0, 2.5, 6.0, 0.5), "near_atr": (1.5, 0.75, 2.5, 0.25),
            "pos24_min": (0.65, 0.5, 0.85, 0.05)},
    "PB": {"rsi_lo": (42, 34, 50, 2), "rsi_hi": (66, 58, 74, 2), "near_atr": (0.35, 0.15, 0.6, 0.05)},
    "MOM": {"adx_min": (22, 15, 35, 1), "rsi_lo": (58, 50, 66, 2), "rsi_hi": (80, 72, 88, 2),
            "ext_max": (3.2, 2.0, 4.5, 0.2), "near_hi": (0.02, 0.005, 0.05, 0.005)},
    "VWAP": {"vr_min": (1.3, 1.0, 2.5, 0.1), "max_above_atr": (1.2, 0.5, 2.0, 0.1), "rsi_min": (50, 40, 60, 2)},
    "MR": {"rsi_max": (32, 22, 40, 2), "bb_max": (0.05, 0.0, 0.15, 0.025), "sup_atr": (1.5, 0.75, 2.5, 0.25)},
    "SMF": {"share_min": (0.7, 0.6, 0.9, 0.05), "usd_min": (250_000, 100_000, 1_000_000, 50_000),
            "n_min": (5, 3, 10, 1)},
    "HI24": {"vol_min": (2.0, 1.2, 4.0, 0.2), "retest_atr": (0.2, 0.0, 0.5, 0.05), "stop_atr": (1.0, 0.6, 1.8, 0.1)},
    "XOVER": {"rsi_lo": (50, 42, 58, 2), "rsi_hi": (72, 64, 80, 2), "cross_max": (2, 0, 5, 1)},
}
PARAM_LABEL = {
    "brk_vol": "breakout candle volume {v}x+", "vr_min": "3-candle volume {v}x+", "retest_atr": "retest within {v} ATR",
    "zone_atr": "entry zone {v} ATR deep", "stop_atr": "stop {v} ATR under the level", "bw_max": "band width in the "
    "tightest {v}%", "range_atr": "3h range under {v} ATR", "near_atr": "within {v} ATR", "pos24_min": "at least {v} "
    "up the 24h range", "rsi_lo": "RSI from {v}", "rsi_hi": "RSI up to {v}", "adx_min": "ADX {v}+", "ext_max": "at most {v} ATR "
    "above EMA21", "near_hi": "within {v} of the 24h high", "max_above_atr": "at most {v} ATR above VWAP",
    "rsi_min": "RSI {v}+", "rsi_max": "RSI {v} or lower", "bb_max": "Bollinger position {v} or lower",
    "sup_atr": "within {v} ATR of support", "share_min": "smart money {v}+ long", "usd_min": "smart money ${v}+ long",
    "n_min": "{v}+ smart traders long", "vol_min": "breakout volume {v}x+", "cross_max": "cross within {v} candles",
}


def P_default(base):
    return {k: v[0] for k, v in PARAMS[base].items()}


def det_brk(a, h1, sm, P):
    A, last, b = a["atr"], a["last"], a["breakout"]
    if b and last >= b["level"] - P["retest_atr"] * A and (b["vol"] >= P["brk_vol"] or a["vr"] >= P["vr_min"]):
        lvl = b["level"]
        return lvl, lvl + P["zone_atr"] * A, min(lvl - P["stop_atr"] * A, b["bar_low"] - 0.25 * A), None
    return None


def det_sqz(a, h1, sm, P):
    A, last, swing = a["atr"], a["last"], a["last_swing_low"]
    rising_base = a["hl"] >= 2 or a["lo_3h"] > a["lo_prev3h"]
    tight = (a["hi_3h"] - a["lo_3h"]) <= P["range_atr"] * A and (a["hi_3h"] - last) <= P["near_atr"] * A
    if a["bw_pct"] <= P["bw_max"] and tight and a["pos24"] >= P["pos24_min"] and last > a["e21"] and rising_base:
        trig = a["hi_3h"]
        ref = min(a["lo_3h"], swing) if swing else a["lo_3h"]
        return trig, trig + 0.25 * A, ref - 0.3 * A, trig
    return None


def det_pb(a, h1, sm, P):
    A, last, swing = a["atr"], a["last"], a["last_swing_low"]
    if (_bull(a) and a["slope21"] > 0 and a["e21"] - P["near_atr"] * A <= last <= a["e9"] + 0.25 * A
            and P["rsi_lo"] <= a["rsi"] <= P["rsi_hi"] and (a["chg_16h"] or 0) > 0):
        lo, hi = a["e21"] - 0.2 * A, max(a["e9"], a["e21"] + 0.1 * A)
        ref = min(a["e50"], swing) if swing and swing < lo else a["e50"]
        return lo, hi, max(ref - 0.3 * A, (lo + hi) / 2 - 3.0 * A), None
    return None


def det_mom(a, h1, sm, P):
    A, last, swing = a["atr"], a["last"], a["last_swing_low"]
    if (_bull(a) and a["adx"] is not None and a["adx"] >= P["adx_min"] and _dmi_up(a)
            and P["rsi_lo"] <= a["rsi"] <= P["rsi_hi"] and a["dist_hi24"] >= -P["near_hi"]
            and a["ext21_atr"] <= P["ext_max"]):
        e9 = a["e9"]
        lo, hi = (e9 - 0.25 * A, e9 + 0.1 * A) if last > e9 + 0.1 * A else (last - 0.3 * A, last)
        stop = min(a["e21"] - 0.5 * A, (swing if swing and swing < lo else a["e21"]) - 0.2 * A)
        return lo, hi, stop, None
    return None


def det_vwap(a, h1, sm, P):
    A, last, vw = a["atr"], a["last"], a["vwap"]
    if (vw and a["below_vwap_recent"] and vw < last <= vw + P["max_above_atr"] * A and a["vr"] >= P["vr_min"]
            and h1["trend"] > -0.002 and a["rsi"] >= P["rsi_min"] and a["close_pos"] >= 0.4):
        return vw, vw + 0.3 * A, min(a["lo_2h"], vw - 0.8 * A) - 0.2 * A, None
    return None


def det_mr(a, h1, sm, P):
    A, last, sup = a["atr"], a["last"], a["support"]
    if (h1["trend"] > 0 and h1["r24"] > -0.03 and (a["rsi"] <= P["rsi_max"] or a["bb_pos"] <= P["bb_max"])
            and sup is not None and last - sup <= P["sup_atr"] * A
            and (a["rsi"] > a["rsi_1"] or a["close_pos"] >= 0.5)):
        return last - 0.25 * A, last + 0.05 * A, sup - 0.5 * A, None
    return None


def det_smf(a, h1, sm, P):
    if not sm or sm["long_usd"] + sm["short_usd"] <= 0:
        return None
    A, last, swing = a["atr"], a["last"], a["last_swing_low"]
    if (sm["share"] >= P["share_min"] and sm["long_usd"] >= P["usd_min"] and sm["long_n"] >= P["n_min"]
            and (sm.get("d_net") is None or sm["d_net"] >= 0) and last > a["e50"]
            and (a["e9"] > a["e21"] or a["rsi"] >= 50)):
        lo, hi = a["e21"] - 0.2 * A, a["e21"] + 0.3 * A
        ref = min(a["e50"], swing) if swing and swing < lo else a["e50"]
        return lo, hi, ref - 0.3 * A, None
    return None


def det_hi24(a, h1, sm, P):
    A, last, b = a["atr"], a["last"], a["brk24"]
    if b and (b["vol"] >= P["vol_min"] or a["vr"] >= P["vol_min"]) and last >= b["level"] - P["retest_atr"] * A:
        lvl = b["level"]
        return lvl, lvl + 0.3 * A, lvl - P["stop_atr"] * A, None
    return None


def det_xover(a, h1, sm, P):
    A = a["atr"]
    if (a["cross_up_ago"] is not None and a["cross_up_ago"] <= P["cross_max"] and _dmi_up(a)
            and (a["vwap_dist"] or 0) > 0 and P["rsi_lo"] <= a["rsi"] <= P["rsi_hi"]):
        lo, hi = a["e21"], max(a["e9"], a["e21"] + 0.2 * A)
        return lo, hi, min(a["lo_2h"], a["e21"] - 1.0 * A) - 0.2 * A, None
    return None


DETECT = {"BRK": det_brk, "SQZ": det_sqz, "PB": det_pb, "MOM": det_mom, "VWAP": det_vwap, "MR": det_mr,
          "SMF": det_smf, "HI24": det_hi24, "XOVER": det_xover}

# Extra conditions a variant can add on top of its strategy's rules. Each takes the
# signal context and a value; the text is shown on the page.
FILTERS = {
    "no_risk_off": ("not in a risk-off market", lambda c, v: c["regime"] != "Risk-off"),
    "risk_on": ("only in a risk-on market", lambda c, v: c["regime"] == "Risk-on"),
    "htf_up": ("only when the 4h trend is up", lambda c, v: (c["a"].get("htf") or {}).get("trend") == "up"),
    "htf_not_down": ("not against a 4h downtrend", lambda c, v: (c["a"].get("htf") or {}).get("trend") != "down"),
    "vol_min": ("volume {v}x normal or more", lambda c, v: c["a"]["vr"] >= v),
    "rsi_max": ("RSI {v} or lower", lambda c, v: c["a"]["rsi"] <= v),
    "adx_min": ("ADX {v} or higher", lambda c, v: (c["a"]["adx"] or 0) >= v),
    "above_vwap": ("price above the 24h VWAP", lambda c, v: (c["a"]["vwap_dist"] or 0) > 0),
    "ext_max": ("at most {v} ATR above EMA21", lambda c, v: c["a"]["ext21_atr"] <= v),
    "trend_1h": ("only when the 1h trend is up", lambda c, v: c["h1"]["trend"] > 0),
    "btc_calm": ("only when BTC is not falling", lambda c, v: c["btc3"] > -0.003),
    "in_zone": ("only when price is already in the entry zone", lambda c, v: c["status"] == "in_zone"),
}
FILTER_VALUES = {"vol_min": (1.5, 2.0, 3.0), "rsi_max": (65, 70, 75), "adx_min": (20, 25, 30),
                 "ext_max": (1.5, 2.0, 2.5)}


def base_of(sid):
    """Spec id -> base strategy ("PB~7" -> "PB")."""
    return str(sid).split("~")[0]


def base_spec(sid):
    st = STRATEGIES[sid]
    return {"id": sid, "base": sid, "variant": False, "params": P_default(sid), "filters": {}, "tp_r": None,
            "sk": None, "name": st["name"], "short": st["short"], "kind": st["kind"], "desc": st["desc"],
            "stage": "base"}


# Every strategy the scanner knows (bases plus the variants discovery created). run()
# loads the variants from the journal; active_specs() lists the ones that trade.
SPECS = {sid: base_spec(sid) for sid in SID_ORDER}


def spec(sid):
    sp = SPECS.get(sid)
    if sp:
        return sp
    b = base_of(sid)
    sp = dict(SPECS.get(b) or base_spec(b)) if b in STRATEGIES else {
        "id": sid, "base": b, "name": sid, "short": sid, "kind": None, "desc": "", "params": {}, "filters": {}}
    sp.update(id=sid, variant=True, stage="retired")
    return sp


def active_specs():
    return [sp for sp in SPECS.values() if sp["stage"] in ("base", "forward", "promoted")]


def load_specs(J):
    """Bases plus every variant the journal knows (retired ones stay for their history)."""
    SPECS.clear()
    for sid in SID_ORDER:
        SPECS[sid] = base_spec(sid)
    for vid, v in (J.get("variants") or {}).items():
        b = v.get("base")
        if b not in STRATEGIES:
            continue
        params = P_default(b)
        params.update({k: x for k, x in (v.get("params") or {}).items() if k in PARAMS[b]})
        SPECS[vid] = {"id": vid, "base": b, "variant": True, "params": params,
                      "filters": {k: x for k, x in (v.get("filters") or {}).items() if k in FILTERS},
                      "tp_r": v.get("tp_r"), "sk": v.get("sk"), "name": v.get("name") or vid,
                      "short": v.get("short") or vid, "kind": STRATEGIES[b]["kind"], "desc": v.get("desc", ""),
                      "stage": v.get("stage", "retired")}


def build_plan(sp, a, lo, hi, stop, trig, tp_r, sk=1.0):
    """Shared risk rules: the stop is 0.9-3.5 ATR (and at least 0.5%) below the middle
    of the zone, then scaled by the stop factor (learned by the journal, or set by a
    variant). Setups risking more than max_risk, or already past TP1, are dropped."""
    A, last = a["atr"], a["last"]
    if hi < lo:
        lo, hi = hi, lo
    mid = (lo + hi) / 2
    min_risk = max(0.9 * A, mid * 0.005)
    if mid - stop < min_risk:
        stop = mid - min_risk
    if mid - stop > 3.5 * A:
        stop = mid - 3.5 * A
    if sk and sk != 1.0:
        stop = mid - (mid - stop) * sk
    risk = (mid - stop) / mid if mid > 0 else 1.0
    if stop <= 0 or risk > CFG["max_risk"] or last <= stop:
        return None
    R = mid - stop
    tps = [mid + R * k for k in tp_r]
    if trig is not None and last < trig:
        status = "trigger"
    elif lo <= last <= hi:
        status = "in_zone"
    elif last > hi:
        status = "extended" if last >= tps[0] else "above"
    else:
        status = "reclaim"
    if status == "extended":
        return None
    return {"sid": sp["id"], "base": sp["base"], "type": sp["id"], "name": sp["name"], "short": sp["short"],
            "elo": lo, "ehi": hi, "mid": mid, "stop": stop, "risk": risk, "R": R, "tps": tps,
            "tp_r": [round(x, 2) for x in tp_r], "sk": sk, "trigger": trig, "status": status,
            "above_r": (last - hi) / R if last > hi else 0.0}


def find_signals(a, h1, sm=None, learn=None, only=None, specs=None, ctx=None):
    """Every strategy (and active variant) that fires on this chart, each with its own
    levels. `ctx` (regime label, BTC 3h change) is needed for variant filters."""
    learn = learn or {}
    out = []
    for sp in (specs if specs is not None else [SPECS[s] for s in SID_ORDER]):
        if only and sp["id"] not in only:
            continue
        try:
            lv = DETECT[sp["base"]](a, h1, sm, sp["params"])
        except (TypeError, KeyError, ZeroDivisionError):
            lv = None
        if not lv:
            continue
        tp_r = tuple(sp.get("tp_r") or (learn.get("tp_r") or {}).get(sp["id"]) or STRATEGIES[sp["base"]]["tp_r"])
        sk = sp.get("sk") or (learn.get("sk") or {}).get(sp["id"], 1.0)
        s = build_plan(sp, a, *lv, tp_r=tp_r, sk=sk)
        if not s:
            continue
        if sp.get("filters"):
            c = {"a": a, "h1": h1, "regime": (ctx or {}).get("regime", "Neutral"),
                 "btc3": (ctx or {}).get("btc3", 0.0), "status": s["status"]}
            try:
                if not all(FILTERS[k][1](c, v) for k, v in sp["filters"].items()):
                    continue
            except (TypeError, KeyError):
                continue
        out.append(s)
    return out


# --------------------------------------------------------------------------- positioning (Gate.io)
def fetch_positioning(ticker):
    if BREAKERS["gate_stats"].open:
        return None
    sym = exchange_symbol("gate", ticker)
    try:
        d = FETCH(GATE_STATS.format(sym=sym))
        BREAKERS["gate_stats"].ok()
    except Exception as e:  # noqa: BLE001
        if is_hard_failure(e):
            BREAKERS["gate_stats"].fail()
            note_error(f"gate stats {sym}: {e}")
        return None
    if not isinstance(d, list):
        return None
    d = sorted([x for x in d if isinstance(x, dict) and "time" in x], key=lambda x: x["time"])
    if len(d) < 2:
        return None
    f, l_ = d[0], d[-1]
    oi0, oi1 = fnum(f.get("open_interest_usd")), fnum(l_.get("open_interest_usd"))
    m0, m1 = fnum(f.get("mark_price")), fnum(l_.get("mark_price"))
    out = {
        "top_size0": fnum(f.get("top_lsr_size")), "top_size1": fnum(l_.get("top_lsr_size")),
        "top_acc0": fnum(f.get("top_lsr_account")), "top_acc1": fnum(l_.get("top_lsr_account")),
        "retail0": fnum(f.get("lsr_account")), "retail1": fnum(l_.get("lsr_account")),
        "oi0": oi0, "oi1": oi1, "oi_ch": (oi1 / oi0 - 1) if oi0 and oi1 else None,
        "px_ch": (m1 / m0 - 1) if m0 and m1 else None,
        "funding": fnum(l_.get("last_funding_rate")),
        "hours": (int(l_["time"]) - int(f["time"])) / 3600,
    }
    if out["top_size1"] is None:
        return None
    return out




# --------------------------------------------------------------------------- smart money (Hyperliquid)
def _perf(row):
    out = {}
    for w in row.get("windowPerformances") or []:
        if isinstance(w, (list, tuple)) and len(w) == 2 and isinstance(w[1], dict):
            out[str(w[0])] = w[1]
    return out


def pick_smart_traders(rows, n, min_account):
    """Most profitable Hyperliquid accounts that look like directional traders."""
    cands = []
    for r in rows:
        addr = r.get("ethAddress")
        av = fnum(r.get("accountValue"), 0.0)
        if not addr or av < min_account:
            continue
        p = _perf(r)
        mo, wk, al = p.get("month", {}), p.get("week", {}), p.get("allTime", {})
        m_pnl, m_roi, m_vlm = fnum(mo.get("pnl"), 0.0), fnum(mo.get("roi"), 0.0), fnum(mo.get("vlm"), 0.0)
        w_pnl, a_pnl = fnum(wk.get("pnl"), 0.0), fnum(al.get("pnl"), 0.0)
        if m_pnl <= 0 or a_pnl <= 0 or m_roi < 0.05:
            continue
        if m_vlm > 150 * av:  # market makers and HFT books: huge volume, no directional view
            continue
        cands.append({"addr": addr, "account": av, "month_pnl": m_pnl, "month_roi": m_roi, "all_pnl": a_pnl,
                      "score": m_pnl + 0.5 * w_pnl})
    cands.sort(key=lambda x: -x["score"])
    return cands[:n]


def hl_smart_money(prev=None):
    """Aggregate the open positions of Hyperliquid's top traders per coin."""
    try:
        board = FETCH(HL_LEADERBOARD, timeout=90)
        rows = board.get("leaderboardRows") or []
    except Exception as e:  # noqa: BLE001
        note_error(f"Hyperliquid leaderboard unavailable: {e}")
        return None
    traders = pick_smart_traders(rows, CFG["smart_traders"], CFG["smart_min_account"])
    if not traders:
        note_error("Hyperliquid leaderboard returned no qualifying traders")
        return None

    def state(addr):
        return FETCH(HL_INFO, {"type": "clearinghouseState", "user": addr})

    states = parallel(state, [t["addr"] for t in traders], workers=4)
    by = {}
    n_pos, n_ok = 0, 0
    for tr in traders:
        st = states.get(tr["addr"])
        if not isinstance(st, dict):
            continue
        n_ok += 1
        for ap in st.get("assetPositions") or []:
            p = ap.get("position") if isinstance(ap, dict) else None
            if not isinstance(p, dict):
                continue
            szi, val = fnum(p.get("szi")), fnum(p.get("positionValue"))
            if not szi or not val:
                continue
            name = str(p.get("coin", ""))
            if ":" in name:
                continue
            coin, mult = canon(name)
            entry = fnum(p.get("entryPx"))
            entry = entry / mult if entry else None
            a = by.setdefault(coin, {"long_n": 0, "short_n": 0, "long_usd": 0.0, "short_usd": 0.0,
                                     "_le": 0.0, "_se": 0.0, "upnl": 0.0, "top": []})
            side = "long" if szi > 0 else "short"
            a[side + "_n"] += 1
            a[side + "_usd"] += abs(val)
            if entry:
                a["_le" if side == "long" else "_se"] += entry * abs(val)
            a["upnl"] += fnum(p.get("unrealizedPnl"), 0.0)
            lev = (p.get("leverage") or {}).get("value") if isinstance(p.get("leverage"), dict) else None
            a["top"].append({"side": side, "usd": round(abs(val)), "entry": sig6(entry), "lev": lev,
                             "trader": tr["addr"][:6] + "…" + tr["addr"][-4:],
                             "month_pnl": round(tr["month_pnl"])})
            n_pos += 1
    for coin, a in by.items():
        tot = a["long_usd"] + a["short_usd"]
        a["share"] = a["long_usd"] / tot if tot else 0.5
        a["long_entry"] = sig6(a["_le"] / a["long_usd"]) if a["long_usd"] else None
        a["short_entry"] = sig6(a["_se"] / a["short_usd"]) if a["short_usd"] else None
        a["top"] = sorted(a["top"], key=lambda x: -x["usd"])[:5]
        a["long_usd"], a["short_usd"], a["upnl"] = round(a["long_usd"]), round(a["short_usd"]), round(a["upnl"])
        del a["_le"], a["_se"]
        if prev and coin in prev:
            pl, ps = prev[coin][0], prev[coin][1]
            a["d_net"] = round((a["long_usd"] - a["short_usd"]) - (pl - ps))
        else:
            a["d_net"] = None
    log(f"smart money: {n_ok} of {len(traders)} top Hyperliquid traders read, {n_pos} open positions")
    return {"traders": len(traders), "read": n_ok, "positions": n_pos, "by_coin": by,
            "min_account": CFG["smart_min_account"]}


# --------------------------------------------------------------------------- scoring
def liquidity_tier(v):
    if v is None:
        return "unknown", 4
    if v >= 1e6:
        return "deep", 10
    if v >= 3e5:
        return "good", 8
    if v >= 1e5:
        return "fair", 6
    if v >= 5e4:
        return "moderate", 4
    if v >= 2e4:
        return "thin", 2
    return "very thin", 0


def funding_avg(coin):
    fs = [v["funding8h"] for v in (coin.get("venues") or {}).values() if v.get("funding8h") is not None]
    return sum(fs) / len(fs) if fs else None


def positioning_points(a, pos, coin, sm):
    """0-15: Hyperliquid smart money first, Gate.io top traders second, crowding last."""
    if sm and sm["long_usd"] + sm["short_usd"] >= 25_000:
        tot = sm["long_usd"] + sm["short_usd"]
        p = 5 + clamp((sm["share"] - 0.5) / 0.3, -1, 1) * 5
        if sm.get("d_net") is not None:
            p += clamp(sm["d_net"] / max(25_000, 0.2 * tot), -1, 1) * 2
        if sm["long_n"] >= 3 and sm["share"] >= 0.6:
            p += 1
        if pos and pos.get("top_size1") is not None:
            p += clamp((pos["top_size1"] - 1) / 0.15, -1, 1) * 2
    elif pos:
        p = 1 + clamp((pos["top_size1"] - 0.95) / 0.2, 0, 1) * 6
        if pos["top_size0"]:
            p += clamp((pos["top_size1"] - pos["top_size0"]) / 0.1, -1, 1) * 3
        if pos["oi_ch"] is not None and (a["chg_4h"] or 0) > 0:
            p += clamp(pos["oi_ch"] / 0.2, 0, 1) * 3
        if pos["retail1"] is not None:
            p += 2 if pos["retail1"] < 1 else (-2 if pos["retail1"] > 2 else 0)
    else:
        p = 6
    var = (coin.get("venues") or {}).get("variational") or {}
    if var.get("oi_long") and var.get("oi_short") is not None and var["oi_long"] / max(var["oi_short"], 1) > 8:
        p -= 1
    fa = funding_avg(coin)
    if fa is not None and fa > 0.0005:
        p -= 1
    return round(clamp(p, 0, 15), 1)


def grade_of(score):
    return "High" if score >= 75 else "Medium" if score >= 62 else "Low"


def conviction(a, h1, s, pos, coin, regime, sm=None):
    """0-100 score split into parts so the page can show why. The dip-buy strategy
    (MR) is scored on the 1h trend and on how oversold the 15m chart is."""
    parts = {}
    sid = s["base"]
    stack = a["e9"] > a["e21"] > a["e50"]
    if sid == "MR":
        t = 8 if h1["trend"] > 0.004 else 5 if h1["trend"] > 0 else 0
        t += clamp(h1["slope"] / 0.01, 0, 1) * 4
        t += 4 if a["last"] > a["e50"] else 0
        t += 4 if h1["pos"] >= 0.4 else 0
    else:
        t = 8 if stack else (4 if a["e9"] > a["e21"] else 0)
        t += clamp(a["slope21"] / 0.006, 0, 1) * 5
        t += clamp(h1["trend"] / 0.015, 0, 1) * 3
        t += 2 if (a["vwap_dist"] or 0) > 0 else 0
        t += 2 if a["adx"] and a["adx"] >= 25 and _dmi_up(a) else 0
    parts["trend"] = (t, 20)

    r = a["rsi"]
    if sid == "MR":
        m = 8 if r <= 30 else 6 if r <= 35 else 3
        m += 4 if r > a["rsi_1"] else 0
        m += 4 if a["hist"] > a["hist_prev"] else 0
        m += 4 if a["close_pos"] >= 0.6 else 0
    else:
        m = 9 if 55 <= r <= 70 else 7 if 70 < r <= 76 else 5 if 50 <= r < 55 else 4 if 76 < r <= 82 else 1
        m += 3 if r > a["rsi_prev"] else 0
        m += 4 if a["hist"] > 0 else 0
        m += 4 if a["hist"] > a["hist_prev"] else 0
    parts["momentum"] = (m, 20)

    v = clamp(math.log2(max(a["vr"], 1e-9)) / math.log2(6), 0, 1) * 11
    v += clamp((a["vmax8"] - 1.5) / 2.5, 0, 1) * 4
    parts["volume"] = (v, 15)

    st = STRATEGIES[sid]["base"]
    st += 4 if a["hl"] >= 3 else 3 if a["hl"] >= 2 else 0
    if sid == "MR":
        sup = a["support"]
        st += 4 if sup and a["last"] - sup <= 0.6 * a["atr"] else 2 if sup else 0
    else:
        st += 4 if a["dist_hi24"] >= -0.01 else 2 if a["dist_hi24"] >= -0.03 else 0
    parts["structure"] = (min(st, 15), 15)

    p = positioning_points(a, pos, coin, sm)
    parts["positioning"] = (p, 15)

    tier, L = liquidity_tier(coin.get("best_vol"))
    nv = len(coin.get("venues") or {})
    L = min(10, L + (1 if nv >= 4 else 0))
    var = (coin.get("venues") or {}).get("variational") or {}
    if (var.get("spread_bps") or 0) > 20 and coin.get("best_vol") == var.get("vol"):
        L = max(0, L - 2)
    parts["liquidity"] = (L, 10)
    parts["backdrop"] = ({"Risk-on": 5, "Neutral": 3, "Risk-off": 0}[regime["label"]], 5)

    pen = []
    if r > 82:
        pen.append(("RSI above 82", 6))
    if a["ext21_atr"] > 3:
        pen.append((f"price {a['ext21_atr']:.1f} ATR above EMA21", 6))
    elif a["ext21_atr"] > 2.5:
        pen.append((f"price {a['ext21_atr']:.1f} ATR above EMA21", 3))
    if h1["r24"] > 0.35:
        pen.append((f"already {pc(h1['r24'], 0)} in 24h", 6))
    if s["status"] == "above" and s["above_r"] > 0.8:
        pen.append(("price is well above the entry zone", 4))
    if regime["label"] == "Risk-off":
        pen.append(("market is risk-off", 5))
    if (a.get("htf") or {}).get("trend") == "down":
        pen.append(("against the 4h downtrend", 4))
    total = sum(x for x, _ in parts.values()) - sum(x for _, x in pen)
    total = clamp(total, 0, 100)
    grade = grade_of(total)
    return {"score": round(total, 1), "grade": grade,
            "parts": {k: [round(x, 1), mx] for k, (x, mx) in parts.items()},
            "penalties": [[t_, x] for t_, x in pen], "liq_tier": tier, "dexes": nv}


# --------------------------------------------------------------------------- the written case
ARROW = " \u2192 "


def _ago(bars):
    words = {1: "one", 2: "two", 3: "three"}
    if bars == 0:
        return "on the current candle"
    return f"{words.get(bars, bars)} candle{'s' if bars > 1 else ''} ago"


SM_META = {}


STOP_WHY = {
    "BRK": "under the broken range high and the breakout candle's low. Back below there, the breakout has failed",
    "MOM": "below EMA21 and the last swing low. Losing that area ends this trend leg",
    "PB": "below EMA50 and the last swing low, the level that defines the uptrend",
    "SQZ": "below the 3-hour range low. A drop there means the squeeze broke down instead of up",
    "VWAP": "under the 2-hour low and back below VWAP. There, the reclaim has failed",
    "MR": "under the last swing low. A break there means the uptrend is failing, not dipping",
    "SMF": "below EMA50 and the last swing low, where the trend the smart money is betting on would break",
    "HI24": "1 ATR under the broken 24h high. Back below it, the breakout has failed",
    "XOVER": "under EMA21 and the 2-hour low. A drop there cancels the cross",
}
LEAD = {"BRK": "breaking out of its 8-hour range", "MOM": "trending cleanly above rising EMAs",
        "PB": "pulling back inside a rising trend", "SQZ": "coiling tightly under its range high",
        "VWAP": "reclaiming its 24h VWAP on rising volume", "MR": "dipping to oversold inside a 1-hour uptrend",
        "SMF": "held long by Hyperliquid's top traders", "HI24": "breaking above its 24-hour high",
        "XOVER": "turning up with a fresh EMA9/21 cross"}


def write_case(coin, a, h1, s, pos, cdata, regime, conv, sm=None, lc=None):
    sm_meta = SM_META
    sid = s["base"]
    e9, e21, e50, A = a["e9"], a["e21"], a["e50"], a["atr"]
    last, mid, stop, R = a["last"], s["mid"], s["stop"], s["R"]
    tp1, tp2, tp3 = s["tps"]
    sections = []

    # Trend
    stack = e9 > e21 > e50
    if stack:
        t = f"Bullish EMA stack on the 15m chart: EMA9 {fp(e9)} > EMA21 {fp(e21)} > EMA50 {fp(e50)}"
    elif e9 > e21:
        t = f"EMA9 {fp(e9)} is above EMA21 {fp(e21)}, but EMA50 {fp(e50)} is not aligned yet"
    else:
        t = f"EMA9 {fp(e9)} is still below EMA21 {fp(e21)}, so the short-term trend has not turned up"
    t += f", and EMA21 is {'rising' if a['slope21'] > 0 else 'falling'} ({pc(a['slope21'], 2)} over the last hour). "
    t += f"Price is {pc(a['dist21'])} from EMA21 ({a['ext21_atr']:.1f} ATR)"
    if a["vwap"]:
        t += (f" and above the 24h VWAP ({fp(a['vwap'])}), so buyers are in control. " if a["vwap_dist"] > 0
              else f" but below the 24h VWAP ({fp(a['vwap'])}), so buyers are not fully in control. ")
    else:
        t += ". "
    if a["adx"] is not None:
        strength = "a strong" if a["adx"] >= 30 else "a developing" if a["adx"] >= 20 else "a weak"
        side = "buyers" if _dmi_up(a) else "sellers"
        t += f"ADX is {a['adx']:.0f} with {side} in charge (+DI {a['pdi']:.0f} vs -DI {a['mdi']:.0f}): {strength} trend. "
    t += (f"On the 1h chart EMA8 is {pc(h1['trend'])} versus EMA21 and price sits at {h1['pos'] * 100:.0f}% "
          f"of its 24h range.")
    trend_ok = (h1["trend"] > 0) if sid == "MR" else (stack and a["slope21"] > 0)
    sections.append({"id": "trend", "title": "Trend", "tone": "pos" if trend_ok else "neu", "text": t})

    # Higher timeframe
    hx = a.get("htf")
    if hx:
        e20_s, e50_s = fps([hx["e20"], hx["e50"]])
        if hx["trend"] == "up":
            t = (f"The 4-hour chart is in an uptrend: price is above EMA20 ({e20_s}), which is above EMA50 ({e50_s}), "
                 f"and 4h RSI is {hx['rsi']:.0f}. The bigger picture supports a long.")
            tone = "pos"
        elif hx["trend"] == "down":
            t = (f"The 4-hour chart is in a downtrend: price is under EMA20 ({e20_s}) and EMA50 ({e50_s}), 4h RSI "
                 f"{hx['rsi']:.0f}. This long goes against the bigger trend, so it is scored down; take profits "
                 f"quickly and respect the stop.")
            tone = "neg"
        else:
            where = "above" if hx["dist20"] > 0 else "below"
            t = (f"The 4-hour chart has no clear trend: price is {where} EMA20 ({e20_s}) with EMA50 at {e50_s} and "
                 f"4h RSI {hx['rsi']:.0f}. The 15m setup has to do the work on its own.")
            tone = "neu"
        sections.append({"id": "htf", "title": "Higher timeframe (4h)", "tone": tone, "text": t})

    # Momentum
    r, rp = a["rsi"], a["rsi_prev"]
    zone = ("overbought, so expect sharp pullbacks" if r > 80 else "strong but stretched" if r > 70 else
            "healthy bullish momentum" if r >= 55 else "neutral" if r >= 45 else
            "oversold, where dips in an uptrend often bounce" if r <= 32 else "weak")
    t = f"RSI(14) is {r:.0f}, {'up' if r > rp else 'down'} from {rp:.0f} an hour ago: {zone}. "
    if a["hist"] > 0:
        t += "The MACD histogram is positive"
        if a["hist_up"] >= 2:
            t += f" and has grown for {a['hist_up']} bars in a row, so momentum is accelerating."
        elif a["hist"] > a["hist_prev"]:
            t += " and rising."
        else:
            t += " but shrinking, so momentum is cooling."
    else:
        t += ("The MACD histogram is negative but turning up." if a["hist"] > a["hist_prev"] else
              "The MACD histogram is negative and falling, a warning sign.")
    if sid == "MR":
        tone = "pos" if r <= 35 and (r > a["rsi_1"] or a["hist"] > a["hist_prev"]) else "neu"
    else:
        tone = "pos" if 55 <= r <= 76 and a["hist"] > 0 else ("neg" if r > 82 or a["hist"] < 0 else "neu")
    sections.append({"id": "momentum", "title": "Momentum", "tone": tone, "text": t})

    # Volume
    t = (f"The last three closed 15m candles averaged {a['vr']:.1f}x the 24h median volume, and the biggest "
         f"candle of the last two hours was {a['vmax8']:.1f}x. ")
    t += ("Buyers are showing up with size, which backs the move. " if a["vr"] >= 2 else
          "Volume is above normal. " if a["vr"] >= 1.2 else
          "Volume is ordinary, so the move has less confirmation. ")
    t += f"24h turnover on {SOURCE_NAME.get(a.get('src'), 'the reference exchange')}: {usd(a['qv24'])}."
    sections.append({"id": "volume", "title": "Volume", "tone": "pos" if a["vr"] >= 1.5 else "neu", "text": t})

    # Structure
    run = a["lows"][-min(a["hl"], 3):] if a["hl"] >= 2 else []
    hl_txt = f" Swing lows are rising ({ARROW.join(fps(run))})." if len(run) >= 2 else ""
    if sid == "BRK":
        b = a["breakout"]
        if b["ago"] == 0:
            how = f"on the current, still-forming candle, with the last three candles at {a['vr']:.1f}x normal volume"
        else:
            how = f"{_ago(b['ago'])} on {b['vol']:.1f}x normal volume"
        hold = ("is holding above it" if last >= b["level"] else
                "is now retesting it from just below; it needs a 15m close back above that level")
        t = (f"Price broke above the prior 8-hour range high at {fp(b['level'])} {how}, and {hold}.{hl_txt} "
             f"The broken high is now the support to buy.")
    elif sid == "MOM":
        if a["hh"] >= 2:
            t = f"A clean trend leg: {a['hh']} new highs in the last 8 candles, and price is {pc(a['dist_hi24'])} "
        else:
            t = f"Price is consolidating near the top of the move, {pc(a['dist_hi24'])} "
        t += (f"from the 24h high ({fp(a['hi24'])}). Dips have been bought near EMA9, which is where the entry "
              f"sits.{hl_txt}")
    elif sid == "PB":
        sw = a["last_swing_low"]
        t = (f"The uptrend is intact and price has pulled back into the EMA9-EMA21 area "
             f"({' to '.join(fps([e21, e9]))}).{hl_txt}"
             + (f" The last swing low at {fp(sw)} held, so buyers are defending higher prices." if sw else ""))
    elif sid == "SQZ":
        t = (f"Bollinger Band width is in the tightest {a['bw_pct']:.0f}% of the last 24h while price holds "
             f"the top of its 3-hour range ({' to '.join(fps([a['lo_3h'], a['hi_3h']]))}).{hl_txt} Tight ranges near "
             f"the highs often resolve upward once volume arrives. The trade only triggers on a break of "
             f"{fp(s['trigger'])}.")
    elif sid == "VWAP":
        t = (f"Price traded below the 24h VWAP ({fp(a['vwap'])}) within the last two hours and has closed back above "
             f"it with volume at {a['vr']:.1f}x normal. Reclaiming VWAP means buyers have taken back the day's "
             f"average price, and it now acts as support.{hl_txt}")
    elif sid == "MR":
        sup = a["support"]
        why = f"RSI {r:.0f}" + (" with price on the lower Bollinger band" if a["bb_pos"] <= 0.05 else "")
        t = (f"The 1-hour trend is up (EMA8 {pc(h1['trend'])} over EMA21), but the 15m chart has dipped hard: {why}. "
             f"Price is {(last - sup) / A:.1f} ATR above the last swing low at {fp(sup)}, the level buyers need to "
             f"hold, and the latest candle is {'turning up' if r > a['rsi_1'] else 'closing off its low'}. A bounce "
             f"trade: quicker targets, and no reason to stay if the low breaks.")
    elif sid == "SMF":
        added = ", and they added since the last scan" if sm and (sm.get("d_net") or 0) > 0 else ""
        t = (f"{sm['share'] * 100:.0f}% of the money Hyperliquid's top traders hold in {coin} is long "
             f"({usd(sm['long_usd'])} from {sm['long_n']} traders){added}. The chart agrees: price is above EMA50 "
             f"({fp(e50)}). The entry is a dip toward EMA21 ({fp(e21)}), where trends usually find buyers.{hl_txt}")
    elif sid == "HI24":
        b = a["brk24"]
        how = ("on the current, still-forming candle" if b["ago"] == 0 else
               f"{_ago(b['ago'])} on {b['vol']:.1f}x normal volume")
        hold = ("is holding above it" if last >= b["level"] else
                "is retesting it from just below; it needs a 15m close back above that level")
        t = (f"Price closed above the prior 24-hour high at {fp(b['level'])} {how}, and {hold}. A new daily high "
             f"means everyone who bought in the last 24 hours is in profit; the old high is now the support to "
             f"buy.{hl_txt}")
    else:  # XOVER
        t = (f"EMA9 crossed above EMA21 {_ago(a['cross_up_ago'])}, with +DI {a['pdi']:.0f} over -DI {a['mdi']:.0f} "
             f"and price above the 24h VWAP. A fresh cross often starts a new up-leg; the entry is back near EMA21 "
             f"({fp(e21)}).{hl_txt}")
    lo24_s, hi24_s = fps([a["lo24"], a["hi24"]])
    t += f" The 24h range is {lo24_s} to {hi24_s}."
    if mid < a["hi24"] < tp2:
        t += f" The 24h high at {fp(a['hi24'])} sits below TP2, so expect some selling there."
    sections.append({"id": "structure", "title": "Structure and levels", "tone": "pos", "text": t})

    # Volatility / stop logic
    tr_ = s["tp_r"]
    t = (f"ATR(14) is {fp(A)}, about {a['atr_pct'] * 100:.1f}% of price per 15m candle. The stop at {fp(stop)} "
         f"is {R / A:.1f} ATR below the middle of the entry zone, {STOP_WHY[sid]}. Targets sit at "
         f"{tr_[0]:g}R, {tr_[1]:g}R and {tr_[2]:g}R")
    if lc and lc.get("tuned"):
        t += f", tuned to this strategy's record ({lc['tuned']})"
    t += "."
    sk = s.get("sk") or 1.0
    if abs(sk - 1.0) > 0.005:
        t += (f" The stop is {sk:.2f}x the base distance: " +
              ("recent stops on this strategy were often hunted before price went on to the target."
               if sk > 1 else "winners on this strategy rarely dip far, so a tighter stop costs little."))
    sections.append({"id": "risk", "title": "Volatility and stop", "tone": "neu", "text": t})

    # Positioning
    t, tone = "", "neu"
    if sm and sm["long_usd"] + sm["short_usd"] > 0:
        n_all = sm["long_n"] + sm["short_n"]
        share = sm["share"]
        t += (f"Hyperliquid smart money: {n_all} of the {sm_meta.get('traders', 0)} most profitable Hyperliquid "
              f"traders (last 30 days) hold {coin}. {sm['long_n']} are long ({usd(sm['long_usd'])}) and "
              f"{sm['short_n']} short ({usd(sm['short_usd'])}), so {share * 100:.0f}% of their money is on the "
              f"long side. ")
        if sm.get("long_entry") and share >= 0.5:
            le = sm["long_entry"]
            t += (f"Their average long entry is {fp(le)}, "
                  + ("below the current price, so they sit in profit and have no reason to bail. " if le < last else
                     "above the current price, so they are under water and could sell into strength. "))
        if sm.get("d_net") is not None and abs(sm["d_net"]) >= 10_000:
            t += (f"Since the last scan they {'added' if sm['d_net'] > 0 else 'cut'} "
                  f"{usd(abs(sm['d_net']))} of net long exposure. ")
        tone = "pos" if share >= 0.6 else ("neg" if share <= 0.4 else "neu")
    elif sm_meta.get("traders"):
        t += f"None of the {sm_meta['traders']} top Hyperliquid traders tracked holds {coin} right now. "
    if pos:
        top, top0 = pos["top_size1"], pos["top_size0"]
        t += f"On Gate.io, the largest accounts hold {top:.2f}x as much long as short by position size"
        if top0:
            t += f", {'up' if top > top0 else 'down'} from {top0:.2f} over {pos['hours']:.0f} hours"
        t += ". "
        if pos["retail1"] is not None:
            rr = pos["retail1"]
            t += (f"Retail accounts are {'net long' if rr > 1 else 'net short'} ({rr:.2f})"
                  + (", fuel for a squeeze if price keeps rising. " if rr < 1 else
                     ", a crowded long side. " if rr > 2 else ". "))
        if pos["oi_ch"] is not None:
            pxc = pos["px_ch"] if pos["px_ch"] is not None else (a["chg_4h"] or 0)
            if pos["oi_ch"] > 0.02 and pxc > 0:
                why = "new longs are opening, not just shorts covering"
            elif pos["oi_ch"] < -0.02 and pxc > 0:
                why = "part of the rise is short covering, which tends to fade faster"
            elif pos["oi_ch"] > 0.02:
                why = "shorts are adding into the dip"
            else:
                why = "positioning is roughly unchanged"
            t += f"Open interest is {pc(pos['oi_ch'], 0)} while price is {pc(pxc)}: {why}. "
        if tone == "neu" and not sm:
            tone = "pos" if top >= 1 and (not top0 or top >= top0) else ("neg" if top < 1 else "neu")
    if not t:
        t = "No smart-money data for this coin, so positioning counts as neutral in the score. "
    var = cdata["venues"].get("variational") or {}
    if var.get("oi_long") is not None and var.get("oi_short") is not None:
        lo_, so_ = var["oi_long"], var["oi_short"]
        ratio = lo_ / so_ if so_ else None
        t += f"Variational open interest is {usd(lo_)} long vs {usd(so_)} short"
        t += (" (heavily long-sided). " if ratio is not None and ratio > 5 else
              " (short-heavy, squeeze fuel). " if ratio is not None and ratio < 0.6 else ". ")
    fr = [(DEX_NAME[d], v["funding8h"]) for d, v in cdata["venues"].items() if v.get("funding8h") is not None]
    if fr:
        fa = sum(x for _, x in fr) / len(fr)
        t += (f"Funding averages {fa * 100:+.4f}% per 8h across {len(fr)} DEX{'es' if len(fr) > 1 else ''} "
              + ("(longs pay, so the long side is getting crowded)." if fa > 0.0003 else
                 "(longs get paid to hold)." if fa < 0 else "(neutral)."))
    sections.append({"id": "positioning", "title": "Smart money and positioning", "tone": tone, "text": t.strip()})

    # Liquidity and where to trade
    tier = conv["liq_tier"]
    vs = sorted(cdata["venues"].values(), key=lambda v: -(v.get("vol") or 0))
    names = [f"{DEX_NAME[v['dex']]} {usd(v['vol'])}" if v.get("vol") else DEX_NAME[v["dex"]] for v in vs]
    t = (f"Listed on {len(vs)} perp DEX{'es' if len(vs) != 1 else ''}. 24h volume: " + ", ".join(names) + ". "
         if vs else "No DEX volume data. ")
    mults = [f"{DEX_NAME[v['dex']]} ({v['sym']})" for v in vs if v.get("mult", 1) != 1]
    if mults:
        m0 = next(v["mult"] for v in vs if v.get("mult", 1) != 1)
        t += (f"Levels here are per 1 {coin}; on " + ", ".join(mults) +
              f" the contract is {m0:,.0f} coins, so multiply prices by {m0:,.0f}. ")
    t += ("Fills should be easy at normal size." if tier in ("deep", "good") else
          "Fine for moderate size." if tier in ("fair", "moderate") else
          "Trade small: slippage can eat the edge.")
    sections.append({"id": "liquidity", "title": "Liquidity and where to trade",
                     "tone": "pos" if tier in ("deep", "good") else "neg" if tier in ("thin", "very thin") else "neu",
                     "text": t})

    # Backdrop
    sections.append({"id": "backdrop", "title": "Market backdrop", "tone":
                     {"Risk-on": "pos", "Neutral": "neu", "Risk-off": "neg"}[regime["label"]],
                     "text": regime["text"]})

    # What the journal says
    if lc:
        sections.append(learning_section(s["sid"], lc))

    # Plan
    plan = []
    st = s["status"]
    if sid == "SQZ":
        plan.append(f"Entry: only after a 15m candle closes above {fp(s['trigger'])}; then buy between "
                    f"{fp(s['elo'])} and {fp(s['ehi'])}."
                    + (" Price is already through the trigger." if st in ("in_zone", "above") else ""))
    else:
        tail = {"in_zone": " Price is inside the zone now.",
                "above": f" Price is {pc(last / s['ehi'] - 1)} above the zone: wait for the pullback, don't chase.",
                "reclaim": f" Price is just under the zone: use a buy-stop at {fp(s['elo'])} so you only get in once it is reclaimed.",
                "trigger": ""}[st]
        plan.append(f"Entry: limit buys between {fp(s['elo'])} and {fp(s['ehi'])}.{tail}")
    plan.append(f"Stop-loss: {fp(stop)} ({pc(-s['risk'])} from the middle of the zone).")
    plan.append(f"Targets: TP1 {fp(tp1)} ({pc(tp1 / mid - 1)}), TP2 {fp(tp2)} ({pc(tp2 / mid - 1)}), "
                f"TP3 {fp(tp3)} ({pc(tp3 / mid - 1)}). Take a third at each and move the stop to breakeven "
                f"after TP1.")
    plan.append(f"Skip the trade if price reaches TP1 before you are filled, if it is not filled within "
                f"{CFG['valid_hours']} hours, or if BTC drops more than 1% within an hour.")
    plan.append(f"Sizing: to risk $10 on this setup, the position is about {usd(10 / s['risk'])} notional.")

    # Risks
    risks = []
    if r > 78:
        risks.append(f"RSI is stretched ({r:.0f}); pullbacks can be sharp, so favour the lower half of the zone.")
    if a["ext21_atr"] > 2.5:
        risks.append(f"Price is {a['ext21_atr']:.1f} ATR above EMA21, which is extended.")
    if h1["r24"] > 0.25:
        risks.append(f"Already {pc(h1['r24'], 0)} in 24h: late-stage pump risk.")
    if sid == "MR":
        risks.append("Buying weakness: if the swing low breaks, the dip becomes a trend change. Respect the stop.")
    if tier in ("thin", "very thin"):
        risks.append(f"Thin DEX volume (best {usd(cdata.get('best_vol'))}): expect slippage and trade small.")
    fa = funding_avg(cdata)
    if fa is not None and fa > 0.0005:
        risks.append(f"Longs pay high funding ({fa * 100:.3f}% per 8h on average): crowded long side.")
    var = cdata["venues"].get("variational") or {}
    if var.get("oi_long") and var.get("oi_short") is not None and var["oi_long"] / max(var["oi_short"], 1) > 8:
        risks.append("Variational open interest is very long-heavy, so a flush can hit fast.")
    if sm and sm["long_usd"] + sm["short_usd"] >= 25_000 and sm["share"] <= 0.4:
        risks.append(f"Hyperliquid's top traders lean short ({(1 - sm['share']) * 100:.0f}% of their money): "
                     f"the move lacks smart-money support.")
    if pos and pos["top_size1"] < 1 and not (sm and sm["share"] > 0.6):
        risks.append(f"Gate.io's largest accounts are net short ({pos['top_size1']:.2f}).")
    if not pos and not sm:
        risks.append("No smart-money data, so positioning could not be checked.")
    if a["hist"] > 0 and a["hist"] < a["hist_prev"]:
        risks.append("MACD momentum is fading on the latest candle.")
    if regime["label"] == "Risk-off":
        risks.append("The market is risk-off; long setups fail more often, so cut size.")
    if (a.get("htf") or {}).get("trend") == "down":
        risks.append("The 4-hour trend is down: this is a counter-trend long.")
    if s["status"] == "above":
        risks.append("Price is above the entry zone; if it never pulls back, let it go.")
    for label, pts in (lc or {}).get("adj") or []:
        if pts <= -3:
            first = label.split(" ")[0]
            keep = first[:2].isupper() or any(ch.isdigit() for ch in first)  # EMA21, RSI, 24h...
            risks.append(f"Journal warning: {label if keep else label[0].lower() + label[1:]}.")
    if lc and lc.get("status") == "testing":
        risks.append("This strategy is still being tested, so its real hit rate is not known yet.")
    if not risks:
        risks.append("No specific red flags beyond normal market risk.")

    # Thesis
    reasons = []
    if a["vr"] >= 1.8:
        reasons.append(f"{a['vr']:.1f}x normal volume")
    if sm and sm["long_usd"] + sm["short_usd"] >= 50_000 and sm["share"] >= 0.65 and sid != "SMF":
        reasons.append(f"Hyperliquid's top traders {sm['share'] * 100:.0f}% long")
    elif pos and pos["top_size1"] >= 1 and pos["top_size0"] and pos["top_size1"] > pos["top_size0"]:
        reasons.append("top traders adding longs")
    if stack and sid not in ("MOM", "MR"):
        reasons.append("a bullish EMA stack")
    if sid == "MR" and r <= 32:
        reasons.append(f"RSI {r:.0f} at a swing-low support")
    elif 55 <= r <= 76 and a["hist"] > 0:
        reasons.append(f"RSI {r:.0f} with positive MACD")
    if a["hl"] >= 3:
        reasons.append("a run of higher lows")
    if lc and lc.get("status") == "passed":
        reasons.append("a strategy with a proven record")
    if tier in ("deep", "good"):
        reasons.append(f"{tier} DEX liquidity")
    reasons = reasons[:2] or ["a steady structure"]
    entry_txt = (f"buy the break of {fp(s['trigger'])}" if sid == "SQZ" else
                 f"buy {fp(s['elo'])}-{fp(s['ehi'])}")
    thesis = (f"{coin}: {LEAD[sid]}, backed by {' and '.join(reasons)}. Plan: {entry_txt}, stop {fp(stop)}, "
              f"targets {fp(tp1)} / {fp(tp2)} / {fp(tp3)}.")
    return {"thesis": thesis, "sections": sections, "plan": plan, "risks": risks}


def learning_section(sid, lc):
    st, status = lc.get("stat") or {}, lc.get("status", "testing")
    name = spec(sid)["name"]
    n = st.get("n") or 0
    if status == "testing":
        t = f"{name} is still being tested: {n} of {CFG['min_trades']} closed paper trades so far"
        if n:
            t += f" ({st['wr'] * 100:.0f}% winners, {st['exp']:+.2f}R per trade)"
        t += ". Its signals are published so they can be judged, without a score bonus. "
    elif status == "passed":
        t = (f"{name} has passed the strategy tournament: {st['wr'] * 100:.0f}% winners, {st['exp']:+.2f}R per trade "
             f"and a profit factor of {fmt_pf(st.get('pf'))} over its last {n} closed trades. ")
    elif status == "watch":
        t = (f"{name} is on watch: {st['exp']:+.2f}R per trade and a profit factor of {fmt_pf(st.get('pf'))} over "
             f"{n} closed trades is not a clear edge yet, so its signals carry a penalty. ")
    else:
        t = f"{name} is rejected by the tournament ({st.get('exp', 0):+.2f}R per trade over {n} trades). "
    if lc.get("live_n") is not None and lc.get("bt_n"):
        t += f"({lc['bt_n']} of these trades come from the backtest on past candles, {lc['live_n']} are live.) "
    adj = lc.get("adj") or []
    if adj:
        t += "Journal adjustments to this score: " + "; ".join(f"{lab} ({pts:+d})" for lab, pts in adj) + "."
    else:
        t += "No lessons from past mistakes apply to this setup."
    tot = sum(p for _, p in adj)
    return {"id": "learning", "title": "What the journal says", "tone": "pos" if tot > 0 else "neg" if tot < 0 else "neu",
            "text": t}


def fmt_pf(pf):
    return "-" if pf is None else ("above 10" if pf >= 10 else f"{pf:.2f}")


# --------------------------------------------------------------------------- market regime
def market_regime(s1, btc15):
    btc, eth = s1.get("BTC"), s1.get("ETH")
    rows = list(s1.values())
    r24 = [m["r24"] for m in rows]
    breadth = sum(1 for x in r24 if x > 0) / len(r24) if r24 else 0.5
    med24 = median(r24, 0.0)
    trend_up = sum(1 for m in rows if m["trend"] > 0) / len(rows) if rows else 0.5
    b1, b3, b24 = (btc["r1"], btc["r3"], btc["r24"]) if btc else (0.0, 0.0, 0.0)
    btc15_up = None
    if btc15 and len(btc15) > 30:
        cl = [x["c"] for x in btc15]
        btc15_up = ema(cl, 9)[-1] > ema(cl, 21)[-1]
    if b3 < -0.01 or b24 < -0.03 or breadth < 0.35 or (btc15_up is False and b3 < -0.005):
        label = "Risk-off"
    elif (b3 > 0.003 and breadth > 0.55) or (breadth > 0.7 and b3 > -0.003):
        label = "Risk-on"
    else:
        label = "Neutral"
    t = f"{label}. BTC is {pc(b24)} over 24h and {pc(b3)} over the last 3 hours"
    if btc15_up is not None:
        t += ", trading above its 15m EMA21" if btc15_up else ", trading below its 15m EMA21"
    if eth:
        t += f"; ETH is {pc(eth['r24'])} on the day"
    t += (f". {breadth * 100:.0f}% of coins are up over 24h (median {pc(med24)}) and {trend_up * 100:.0f}% have a "
          f"rising 1h trend. ")
    t += {"Risk-on": "Alt breakouts have a tailwind.",
          "Neutral": "A selective market: stick to the strongest charts.",
          "Risk-off": "Long setups fail more often in this tape; cut size or wait."}[label]
    return {"label": label, "text": t, "btc": btc["last"] if btc else None, "btc1": b1, "btc3": b3, "btc24": b24,
            "eth24": eth["r24"] if eth else None, "breadth": breadth, "med24": med24, "trend_up": trend_up,
            "btc15_up": btc15_up}


# --------------------------------------------------------------------------- journal and learning
# Every signal from every strategy is paper-traded in the journal (data/journal.json).
# Closed trades feed three kinds of learning:
#   1. The strategy tournament. Each strategy is "testing" until it has min_trades
#      closed trades, then "passed", "watch" or "rejected" from its win rate, R per
#      trade (expectancy), profit factor and average win vs average loss. Rejected
#      strategies keep being paper-traded (so they can come back) but are never
#      published as picks.
#   2. Lessons from mistakes. Trades that share a trait (RSI 75+ at entry, low volume,
#      risk-off market, chasing above EMA21, thin liquidity, ...) and did clearly worse
#      or better than the rest change the score of new signals with that trait. The
#      worst patterns are blocked from the picks. Coins that just stopped out are put
#      on a cool-down so the scanner does not keep buying the same failing chart.
#   3. Tuning. Targets follow how far each strategy's trades usually run before
#      reversing (max favourable excursion), and the stop widens when stops keep
#      getting hunted (price hits the stop, then the target) or tightens when winners
#      never dip far.
ACTIVE = ("waiting", "open", "tp_open")
DONE = ("win", "tp_then_be", "loss", "expired")
REG_CODE = {"Risk-on": "on", "Neutral": "neu", "Risk-off": "off"}
STATUS_RANK = {"passed": 0, "watch": 1, "testing": 2, "rejected": 3}


def _bar_index(candles, ts):
    """Index of the first candle that ends after ts (candles sorted by open time)."""
    lo, hi = 0, len(candles)
    while lo < hi:
        m = (lo + hi) // 2
        if candles[m]["t"] + 900 <= ts:
            lo = m + 1
        else:
            hi = m
    return lo


def _px_at(candles, ts):
    """Last close known at time ts."""
    if not candles:
        return None
    i = _bar_index(candles, ts)
    return candles[i - 1]["c"] if i > 0 else None


def slippage(f):
    """Slippage on market orders, by the coin's best DEX 24h volume at signal time."""
    liq = (f or {}).get("liq") or 0
    for floor, cost in CFG["slip"]:
        if liq >= floor:
            return cost
    return CFG["slip"][-1][1]


def simulate_trade(tr, candles, now, btc=None):
    """Follow one paper trade through 15m candles up to `now`.
    Fills: in_zone fills at the scan price; above fills when a candle trades back into
    the zone (missed if TP1 prints first); reclaim is a buy-stop at the zone low;
    trigger fills on a 15m close above the trigger (or waits for a dip into the zone
    if that close is above it). Unfilled after valid_hours -> no_fill. Price through
    the stop before a fill -> invalid (no loss). After the fill a third comes off at
    each target, the stop moves to breakeven after TP1, a candle touching both the
    stop and a target counts as the stop, and targets do not count on the candle of
    a limit or stop fill (their order inside the candle is unknown). A candle that
    opens beyond the stop or a target (a gap) exits at its open. Anything still open
    after track_hours is closed at market (expired).
    R is net of costs: taker fee plus slippage for market entries, buy-stops,
    stop-losses and closing at market; maker fee for pullback entries and
    take-profits; funding while the position is held ("gross" and "cost" show the
    split).
    Only closed candles are used, so every verdict rests on complete data; the candle
    still forming is picked up by the next run.
    Also measured: MFE (how far price ran in R before the original stop or the end of
    the window), MAE (deepest dip in R before the exit), and for losses whether price
    reached TP1 within hunt_hours after the stop (a stop hunt).
    Returns None when the candles do not reach back to the scan (nothing to judge)."""
    t0 = tr["t"]
    lo, hi, tps, stop0, px = tr["lo"], tr["hi"], tr["tp"], tr["sl"], tr["px"]
    R0 = tr["m"] - stop0
    if R0 <= 0:
        return {"state": "invalid", "r": 0.0, "done": False, "final": True}
    if not candles or candles[0]["t"] > t0:
        return None
    fill_end = t0 + CFG["valid_hours"] * 3600
    track_end = t0 + CFG["track_hours"] * 3600
    horizon = t0 + (CFG["track_hours"] + CFG["hunt_hours"]) * 3600 + 900
    bars = []
    for x in candles[_bar_index(candles, t0):]:
        if x["t"] >= horizon or x["t"] + 900 > now:  # stop at the candle that is still forming
            break
        if x["t"] < t0:  # candle already running at scan time: only scan price -> close is known
            x = {"t": x["t"], "o": px, "h": max(px, x["c"]), "l": min(px, x["c"]), "c": x["c"]}
        bars.append(x)
    covered = bars[-1]["t"] + 900 if bars else t0
    slack = 7200  # after this long past a deadline, missing candles no longer hold a trade open

    def over(deadline):
        return covered >= deadline or now >= deadline + slack

    mode = tr["st"]
    fill = fill_t = fill_i = None
    same_bar_targets = True
    market_in = True  # market / stop entries pay taker fees and slippage; limit entries pay maker fees
    if mode == "in_zone":
        fill, fill_t, fill_i = px, t0, 0
    else:
        for i, x in enumerate(bars):
            if x["t"] >= fill_end:
                break
            if mode == "trigger":
                if x["l"] <= stop0:
                    return {"state": "invalid", "r": 0.0, "done": False, "final": True, "xt": x["t"]}
                if x["c"] > tr["tg"]:
                    if x["c"] <= hi:
                        fill, fill_t, fill_i = x["c"], x["t"] + 900, i + 1
                        break
                    mode = "above"  # closed beyond the zone: wait for a dip into it
                continue
            if mode == "reclaim":
                if x["h"] >= lo:
                    f_ = max(lo, x["o"])
                    if f_ >= tps[0]:
                        return {"state": "missed", "r": 0.0, "done": False, "final": True, "xt": x["t"]}
                    fill, fill_t, fill_i, same_bar_targets = f_, x["t"], i, False
                    break
                if x["l"] <= stop0:
                    return {"state": "invalid", "r": 0.0, "done": False, "final": True, "xt": x["t"]}
                continue
            # above the zone: a limit order waits in the zone
            if x["l"] <= hi:
                if min(hi, x["o"]) <= stop0:  # gapped straight through the stop: no trade
                    return {"state": "invalid", "r": 0.0, "done": False, "final": True, "xt": x["t"]}
                fill, fill_t, fill_i, same_bar_targets = min(hi, x["o"]), x["t"], i, False
                market_in = False
                break
            if x["h"] >= tps[0]:
                return {"state": "missed", "r": 0.0, "done": False, "final": True, "xt": x["t"]}
        if fill is None:
            if over(fill_end):
                return {"state": "no_fill", "r": 0.0, "done": False, "final": True}
            return {"state": "waiting", "r": 0.0, "done": False, "final": False}

    stop, hits, r, left = stop0, [None, None, None], 0.0, 3
    state = exit_t = exit_i = None
    mfe_hi = mae_lo = last_c = fill
    touched0 = False
    taker = CFG["fee_taker"] + slippage(tr.get("f"))
    xc = 0.0  # exit costs so far, as a fraction of the full position
    for j in range(fill_i, len(bars)):
        x = bars[j]
        if x["t"] >= track_end:
            break
        fill_bar = j == fill_i and not same_bar_targets
        if not touched0:
            if x["l"] <= stop0:
                touched0 = True
            elif not fill_bar:
                mfe_hi = max(mfe_hi, x["h"])
        if state is None:
            mae_lo = min(mae_lo, x["l"])
            last_c = x["c"]
            if x["l"] <= stop:
                out = stop if fill_bar else min(stop, x["o"])  # a gap below the stop exits at the open
                if hits[0] is None:
                    state, r = "loss", -(fill - out) / R0
                else:
                    state = "tp_then_be"
                    r += left / 3 * (out - fill) / R0
                xc += left / 3 * taker
                exit_t, exit_i = x["t"], j
            elif not fill_bar:
                for k in range(3):
                    if hits[k] is None and x["h"] >= tps[k]:
                        hits[k] = x["t"]
                        r += (max(tps[k], x["o"]) - fill) / R0 / 3
                        xc += CFG["fee_maker"] / 3
                        left -= 1
                        if k == 0:
                            stop = max(stop, fill)  # breakeven
                if left == 0:
                    state, exit_t, exit_i = "win", x["t"], j
        if state is not None and touched0:
            break
    if state is None:
        if over(track_end):
            state = "expired"
            r += left / 3 * (last_c - fill) / R0
            xc += left / 3 * taker
            exit_t = min(track_end, covered)
        else:
            state = "tp_open" if hits[0] else "open"
    is_open = state in ("open", "tp_open")
    ro = r + left / 3 * (last_c - fill) / R0 if is_open else r
    # costs in R: entry fee (+ slippage for market entries), exit fees, funding while held
    cost = 0.0
    if CFG["costs"]:
        f_ = tr.get("f") or {}
        fund = f_.get("fund")
        fund = CFG["fund_default"] if fund is None else fund
        held_h = max(0.0, ((exit_t if exit_t is not None else covered) - fill_t) / 3600)
        frac = (taker if market_in else CFG["fee_maker"]) + xc + fund * held_h / 8
        if is_open:
            frac += left / 3 * taker  # what closing the rest at market would cost
        cost = frac * fill / R0
    gross = r
    r -= cost
    ro -= cost
    hunt = None
    if state == "loss":
        hunt_end = exit_t + CFG["hunt_hours"] * 3600
        for x in bars[exit_i + 1:]:
            if x["t"] >= hunt_end:
                break
            if x["h"] >= tps[0]:
                hunt = True
                break
        if hunt is None and over(hunt_end):
            hunt = False
    done = state in DONE
    final = done and (touched0 or over(track_end)) and (state != "loss" or hunt is not None)
    btc_ch = None
    if btc and exit_t and fill_t:
        b0, b1 = _px_at(btc, fill_t), _px_at(btc, exit_t + (0 if state == "expired" else 900))
        btc_ch = (b1 / b0 - 1) if b0 and b1 else None
    return {"state": state, "r": round(r, 3), "ro": round(ro, 3), "gross": round(gross, 3), "cost": round(cost, 3),
            "done": done, "final": final,
            "fill": sig6(fill), "ft": fill_t, "xt": exit_t, "tph": hits,
            "mfe": round((mfe_hi - fill) / R0, 2), "mae": round((fill - mae_lo) / R0, 2), "hunt": hunt,
            "btc": rnd(btc_ch, 4), "hold": (exit_i - fill_i + 1) if exit_i is not None else None}


# ---- features, traits (lesson buckets) and mistake tags
def trade_features(a, h1, s, conv_raw, regime, coin, sm, btc3, t, live=True):
    return {"rsi": round(a["rsi"], 1), "adx": rnd(a["adx"], 1), "vr": round(a["vr"], 2),
            "ext": round(a["ext21_atr"], 2), "bw": round(a["bw_pct"]), "p24": round(a["pos24"], 2),
            "r24": round(h1["r24"], 4), "reg": REG_CODE.get(regime["label"], "neu"),
            "sm": round(sm["share"], 3) if live and sm and sm["long_usd"] + sm["short_usd"] >= 25_000 else None,
            "liq": round(coin.get("best_vol") or 0), "fund": rnd(funding_avg(coin), 6) if live else None,
            "btc3": round(btc3 or 0.0, 4), "vw": rnd(a["vwap_dist"], 4), "risk": round(s["risk"], 4),
            "hr": dt.datetime.fromtimestamp(t, dt.timezone.utc).hour, "cv": round(conv_raw, 1), "st": s["status"],
            "htf": (a.get("htf") or {}).get("trend")}


BUCKETS = [
    ("rsi_hot", "RSI 75+ at entry", lambda f, s: f["rsi"] >= 75 and s != "MR"),
    ("ext_high", "Price 2.5+ ATR above EMA21", lambda f, s: f["ext"] >= 2.5),
    ("vol_low", "Volume under 1.2x normal", lambda f, s: f["vr"] < 1.2),
    ("vol_high", "Volume 2.5x normal or more", lambda f, s: f["vr"] >= 2.5),
    ("late_pump", "Coin already up 25%+ in 24h", lambda f, s: f["r24"] >= 0.25),
    ("risk_off", "Risk-off market", lambda f, s: f["reg"] == "off"),
    ("risk_on", "Risk-on market", lambda f, s: f["reg"] == "on"),
    ("sm_short", "Hyperliquid smart money leaning short", lambda f, s: f.get("sm") is not None and f["sm"] <= 0.4),
    ("sm_long", "Hyperliquid smart money 65%+ long", lambda f, s: f.get("sm") is not None and f["sm"] >= 0.65),
    ("above", "Waiting for a pullback (price above the zone)", lambda f, s: f["st"] == "above"),
    ("reclaim", "Buy-stop entries under the zone", lambda f, s: f["st"] == "reclaim"),
    ("thin", "DEX volume under $100K a day", lambda f, s: (f.get("liq") or 0) < 100_000),
    ("crowded", "Funding above 0.03% per 8h", lambda f, s: (f.get("fund") or 0) > 0.0003),
    ("btc_weak", "BTC down 0.5%+ over the prior 3h", lambda f, s: (f.get("btc3") or 0) <= -0.005),
    ("adx_weak", "ADX under 20 (weak trend)", lambda f, s: f.get("adx") is not None and f["adx"] < 20),
    ("htf_down", "Against the 4h downtrend", lambda f, s: f.get("htf") == "down"),
    ("htf_up", "With the 4h uptrend", lambda f, s: f.get("htf") == "up"),
    ("below_vwap", "Price below the 24h VWAP", lambda f, s: (f.get("vw") or 0) < 0),
    ("wide_stop", "Stop more than 3% away", lambda f, s: f["risk"] > 0.03),
    ("asia", "Asia session (00-08 UTC)", lambda f, s: f["hr"] < 8),
    ("europe", "Europe session (08-14 UTC)", lambda f, s: 8 <= f["hr"] < 14),
    ("us", "US session (14-21 UTC)", lambda f, s: 14 <= f["hr"] < 21),
    ("late_us", "Late US session (21-24 UTC)", lambda f, s: f["hr"] >= 21),
]
BUCKET_FN = {b: fn for b, _, fn in BUCKETS}
BUCKET_LABEL = {b: lab for b, lab, _ in BUCKETS}
# traits that need data the backtest (or an API outage) cannot provide are only compared
# among trades where that data exists
BUCKET_NEED = {"sm_short": "sm", "sm_long": "sm", "crowded": "fund", "adx_weak": "adx", "below_vwap": "vw",
               "htf_down": "htf", "htf_up": "htf"}

MISTAKES = {
    "hunted": "Stopped out, then price hit TP1 within 3 hours (stop too tight)",
    "fast_fail": "Stopped within 30 minutes of the fill (failed breakout)",
    "btc_drag": "BTC fell 1%+ during the trade",
    "chased": "Chased: price far above EMA21 or above the zone",
    "rsi_hot": "Bought into overbought RSI (75+)",
    "low_vol": "No volume behind the move (under 1.2x normal)",
    "late_pump": "Late: the coin was already up 25%+ in 24h",
    "vs_smart": "Against Hyperliquid smart money (60%+ short)",
    "risk_off": "Long in a risk-off market",
    "thin": "Thin DEX liquidity (under $100K a day)",
    "crowded": "Crowded longs (funding above 0.03% per 8h)",
    "weak_trend": "Weak trend (ADX under 20)",
    "below_vwap": "Entry below the 24h VWAP",
    "vs_htf": "Against the 4h downtrend",
    "clean": "No red flags: a normal loss",
    "missed": "Ran to TP1 before the entry filled",
    "no_fill": "Entry zone never reached within the fill window",
    "gave_back": "Hit TP1, then the rest stopped at breakeven",
    "stalled": "Went nowhere and closed below entry after 12 hours",
}
TAG_BUCKET = {"chased": "ext_high", "rsi_hot": "rsi_hot", "low_vol": "vol_low", "late_pump": "late_pump",
              "vs_smart": "sm_short", "risk_off": "risk_off", "thin": "thin", "crowded": "crowded",
              "weak_trend": "adx_weak", "below_vwap": "below_vwap", "btc_drag": "btc_weak", "vs_htf": "htf_down"}


def trade_tags(tr):
    res, f, sid = tr["res"], tr.get("f") or {}, tr["s"]
    sid = base_of(sid)
    kind = STRATEGIES.get(sid, {}).get("kind")  # a strategy removed from the code keeps its old trades
    st = res.get("state")
    if st == "loss" and not f:
        return ["clean"]
    if st == "loss":
        tags = []
        if res.get("hunt"):
            tags.append("hunted")
        if (res.get("hold") or 99) <= 2 and kind == "breakout":
            tags.append("fast_fail")
        if (res.get("btc") or 0) <= -0.01:
            tags.append("btc_drag")
        if f["ext"] >= 2.5 or f["st"] == "above":
            tags.append("chased")
        if f["rsi"] >= 75 and sid != "MR":
            tags.append("rsi_hot")
        if f["vr"] < 1.2:
            tags.append("low_vol")
        if f["r24"] >= 0.25:
            tags.append("late_pump")
        if f.get("sm") is not None and f["sm"] <= 0.4:
            tags.append("vs_smart")
        if f["reg"] == "off":
            tags.append("risk_off")
        if (f.get("liq") or 0) < 100_000:
            tags.append("thin")
        if (f.get("fund") or 0) > 0.0003:
            tags.append("crowded")
        if f.get("adx") is not None and f["adx"] < 20 and kind == "trend":
            tags.append("weak_trend")
        if (f.get("vw") or 0) < 0 and sid != "MR":
            tags.append("below_vwap")
        if f.get("htf") == "down":
            tags.append("vs_htf")
        return tags or ["clean"]
    if st == "missed":
        return ["missed"]
    if st == "no_fill":
        return ["no_fill"]
    if st == "tp_then_be":
        return ["gave_back"]
    if st == "expired" and res.get("r", 0) < 0:
        return ["stalled"]
    return []


# ---- statistics and the tournament
def trade_stats(trs):
    """trs: filled, closed trades sorted by exit time."""
    rs = [t["res"]["r"] for t in trs]
    n = len(rs)
    if not n:
        return {"n": 0}
    wins = [x for x in rs if x > 0.02]
    losses = [x for x in rs if x < -0.02]
    gw, gl = sum(wins), -sum(losses)
    mean = sum(rs) / n
    sd = statistics.pstdev(rs) if n > 1 else 1.0
    cum = peak = dd = 0.0
    for x in rs:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    holds = [(t["res"]["xt"] - t["res"]["ft"]) / 3600 for t in trs if t["res"].get("xt") and t["res"].get("ft")]
    return {"n": n, "wr": len(wins) / n, "exp": mean, "se": (sd / math.sqrt(n)) if n > 1 else 1.0,
            "pf": (gw / gl) if gl > 0 else (99.0 if gw > 0 else None),
            "rr": ((gw / len(wins)) / (gl / len(losses))) if wins and losses else None,
            "avg_win": gw / len(wins) if wins else None, "avg_loss": -gl / len(losses) if losses else None,
            "net": sum(rs), "dd": dd,
            "tp1": sum(1 for t in trs if (t["res"].get("tph") or [None])[0]) / n,
            "stopped": sum(1 for t in trs if t["res"]["state"] == "loss") / n,
            "hold": median(holds, None)}


def decide_status(prev, st):
    """Pass: clearly positive R per trade, profit factor 1.2+, and either a 45%+ win
    rate or winners 1.5x the size of losers. Reject: clearly negative R per trade or
    a profit factor under 0.8. In between: watch. Hysteresis stops flip-flopping."""
    n = st.get("n", 0)
    if n < CFG["min_trades"]:
        return "testing", f"{n} of {CFG['min_trades']} closed trades so far"
    exp, se, wr = st["exp"], st.get("se") or 0.5, st["wr"]
    pf = st["pf"] if st.get("pf") is not None else 0.0
    rr = st.get("rr") or 0.0
    summary = (f"{wr * 100:.0f}% winners, {exp:+.2f}R per trade, profit factor {fmt_pf(st.get('pf'))} "
               f"over {n} trades")
    good = exp - 0.5 * se > 0 and pf >= 1.2 and (wr >= 0.45 or rr >= 1.5)
    bad = exp + 0.5 * se < 0 or pf < 0.8
    if prev == "passed" and not good and not bad and exp > 0 and pf >= 1.05:
        return "passed", summary + "; keeps its pass while it stays profitable (profit factor 1.05+)"
    if prev == "passed" and good:
        return "passed", summary
    if prev == "rejected" and not (exp > 0 and pf >= 1.05):
        return "rejected", summary + ("" if bad else "; stays rejected until it makes money again "
                                                    "(profit factor 1.05+)")
    if good:
        return "passed", summary
    if bad:
        return "rejected", summary
    return "watch", summary


def tune_targets(sid, ds):
    """Targets where 55%, 35% and 20% of this strategy's filled trades reached (MFE),
    blended with the default targets until 80 trades back them."""
    mf = []
    for t in ds:  # targets sit at middle + k*R, so measure the run from the middle too
        res = t["res"]
        if res.get("final") and res.get("mfe") is not None and res.get("fill"):
            mf.append(res["mfe"] + (res["fill"] - t["m"]) / max(t["m"] - t["sl"], 1e-12))
    mf.sort()
    n = len(mf)
    if n < 30:
        return None
    d = STRATEGIES[base_of(sid)]["tp_r"]

    def q(p):
        return mf[min(n - 1, int(p * n))]

    t1 = clamp(q(0.45), 0.8, 1.6)
    t2 = clamp(q(0.65), max(t1 + 0.4, 1.4), 3.2)
    t3 = clamp(q(0.80), max(t2 + 0.6, 2.2), 5.0)
    w = min(1.0, n / 80)
    tp = [round(w * x + (1 - w) * y, 1) for x, y in zip((t1, t2, t3), d)]
    tp[1] = round(max(tp[1], tp[0] + 0.4), 1)
    tp[2] = round(max(tp[2], tp[1] + 0.6), 1)
    reach = [round(sum(1 for m in mf if m >= x) / n, 2) for x in tp]
    return {"tp_r": tp, "n": n, "reach": reach, "default": list(d)}


def tune_stop(sk, ds):
    """Stop factor from the trades taken with the current factor: widen 10% when 35%+
    of recent losses were stop hunts, tighten 7% when under 12% were and winners
    rarely dipped past 0.4R. Bounded to 0.85-1.4."""
    cur = [t for t in ds if abs((t.get("sk") or 1.0) - sk) < 1e-6]
    losses = [t for t in cur if t["res"]["state"] == "loss" and t["res"].get("hunt") is not None][-30:]
    if len(losses) < 10:
        return sk, None
    hr = sum(1 for t in losses if t["res"]["hunt"]) / len(losses)
    maes = [t["res"]["mae"] for t in cur if t["res"]["r"] > 0.02 and t["res"].get("mae") is not None][-30:]
    if hr >= 0.35 and sk < 1.4:
        return round(min(1.4, sk * 1.1), 3), f"{hr * 100:.0f}% of the last {len(losses)} stops were hunted"
    if hr <= 0.12 and len(maes) >= 10 and median(maes) <= 0.4 and sk > 0.85:
        return round(max(0.85, sk * 0.93), 3), (f"only {hr * 100:.0f}% of the last {len(losses)} stops were hunted "
                                               f"and winners dipped {median(maes):.2f}R at most (median)")
    return sk, None


def compute_lessons(done):
    """Traits whose trades did clearly better or worse than the rest. A difference
    must be statistically clear (z-score of the difference in average R: 2.5 for all
    strategies together, 3 for a single strategy, because many traits are tested at
    once and some would look special by chance) and point the same way in the older
    and the newer half of the trades. Points are shrunk toward zero for small
    samples, and only the worst patterns (z of -3 / -3.5 or beyond, 25+ trades,
    -0.3R average, 30% winners or fewer) become hard blocks. `done` is sorted by
    exit time."""
    out = []
    mn = CFG["lesson_min"]
    done = [t for t in done if t.get("f")]

    def split(pop, fn):
        inb, outb = [], []
        for t in pop:
            (inb if fn(t["f"], base_of(t["s"])) else outb).append(t["res"]["r"])
        return inb, outb

    def one(pop, bid, label, fn, sid=None, min_b=mn, z_need=2.5, z_block=3.0):
        need = BUCKET_NEED.get(bid)
        if need:
            pop = [t for t in pop if t["f"].get(need) is not None]
        inb, outb = split(pop, fn)
        nb, no = len(inb), len(outb)
        if nb < min_b or no < min_b:
            return None
        mb, mo = sum(inb) / nb, sum(outb) / no
        vb = sum((x - mb) ** 2 for x in inb) / (nb - 1)
        vo = sum((x - mo) ** 2 for x in outb) / (no - 1)
        diff = mb - mo
        z = diff / max(math.sqrt(vb / nb + vo / no), 1e-9)
        wr = sum(1 for x in inb if x > 0.02) / nb
        pts = int(round(clamp(diff * nb / (nb + 25) * 12, -8, 4)))
        block = nb >= 25 and mb <= -0.3 and wr <= 0.3 and z <= -z_block
        if (abs(z) < z_need or pts == 0) and not block:
            return None
        # trades from the same hours move together, which flatters the z-score, so the
        # pattern must also show up (same direction) in the older and the newer half
        half = len(pop) // 2
        for part in (pop[:half], pop[half:]):
            a, b = split(part, fn)
            if len(a) < 5 or len(b) < 5 or (sum(a) / len(a) - sum(b) / len(b)) * diff <= 0:
                return None
        return {"id": bid + (":" + sid if sid else ""), "bucket": bid, "sid": sid, "label": label, "n": nb,
                "avg": round(mb, 3), "base": round(mo, 3), "wr": round(wr, 3), "pts": pts, "block": block,
                "z": round(z, 2)}

    if len(done) >= 2 * mn:
        for bid, label, fn in BUCKETS:
            lesson = one(done, bid, label, fn)
            if lesson:
                out.append(lesson)
    for sid in SID_ORDER:
        ds = [t for t in done if t["s"] == sid]
        if len(ds) < 40:
            continue
        for bid, label, fn in BUCKETS:
            lesson = one(ds, bid, label, fn, sid, min_b=15, z_need=3.0, z_block=3.5)
            if lesson:
                out.append(lesson)
    out.sort(key=lambda x: (not x["block"], x["pts"], -x["n"]))
    return out


def coin_cooldowns(trades, now):
    """Separate stop-outs per coin in the last 24h (stops within 2 hours of each other,
    e.g. several strategies caught in the same drop, count once). 2+ -> no picks on
    that coin for 12h after the last one; 1 in the last 4h -> -6 points."""
    by = {}
    for t in trades:
        res = t["res"]
        if res.get("state") == "loss" and res.get("xt") and 0 <= now - res["xt"] <= 24 * 3600:
            by.setdefault(t["c"], []).append(res["xt"])
    out = {}
    for c, xs in by.items():
        xs.sort()
        events = []  # latest stop of each cluster
        for x in xs:
            if events and x - events[-1] <= 7200:
                events[-1] = x
            else:
                events.append(x)
        last = events[-1]
        if len(events) >= 2 and now - last <= 12 * 3600:
            out[c] = {"block": True, "until": last + 12 * 3600, "n": len(events), "last": last}
        elif now - last <= 4 * 3600:
            out[c] = {"block": False, "until": last + 4 * 3600, "n": len(events), "last": last}
    return out


def learn(J, now):
    """Recompute statuses, tuned targets, stop factors, lessons and cool-downs from the
    journal. Returns the learning state used to score this scan's signals."""
    horizon = now - CFG["journal_days"] * 86400
    trades = [t for t in J["closed"] + J["open"] if t["t"] >= horizon and not t.get("dup")]
    done = sorted((t for t in trades if t["res"].get("done")), key=lambda t: t["res"].get("xt") or t["t"])
    status, lst = J.setdefault("status", {}), J.setdefault("learn", {})
    sks = lst.setdefault("sk", {})
    L = {"strat": {}, "tp_r": {}, "sk": {}, "n_done": len(done)}
    for sid in [sp["id"] for sp in active_specs()]:
        ds = [t for t in done if t["s"] == sid][-CFG["strategy_window"]:]
        st = trade_stats(ds)
        st["bt_n"] = sum(1 for t in ds if t.get("bt"))
        st["live_n"] = len(ds) - st["bt_n"]
        prev = (status.get(sid) or {}).get("s", "testing")
        new, why = decide_status(prev, st)
        if new != prev:
            J.setdefault("changes", []).append({"t": now, "sid": sid, "kind": "status", "from": prev, "to": new,
                                                "why": why})
        if sid not in status or new != prev:
            status[sid] = {"s": new, "since": now, "why": why}
        else:
            status[sid]["why"] = why
        info = {"status": new, "why": why, "stat": st, "since": status[sid]["since"]}
        tt = None if spec(sid).get("tp_r") else tune_targets(sid, ds)  # a variant's own targets stay fixed
        if tt:
            L["tp_r"][sid] = tt["tp_r"]
            info["tuned"] = tt
        if spec(sid).get("sk"):  # a variant's own stop factor stays fixed, like its targets
            L["sk"][sid] = spec(sid)["sk"]
            L["strat"][sid] = info
            continue
        old = sks.get(sid, 1.0)
        sk, why_sk = tune_stop(old, ds)
        if why_sk:
            sks[sid] = sk
            J.setdefault("changes", []).append({"t": now, "sid": sid, "kind": "stop", "from": f"{old:.2f}x",
                                                "to": f"{sk:.2f}x", "why": why_sk})
        L["sk"][sid] = sks.get(sid, 1.0)
        L["strat"][sid] = info
    J["changes"] = J.get("changes", [])[-40:]
    # variants repeat their parent's trades, so lessons and cool-downs use the base strategies only
    L["lessons"] = compute_lessons([t for t in done if "~" not in t["s"]])
    L["cool"] = coin_cooldowns([t for t in trades if "~" not in t["s"]], now)
    return L


def adjustments(sid, f, coin, L):
    """Score changes for one signal: strategy record, matching lessons (a strategy's
    own lesson beats the general one for the same trait) and coin cool-down."""
    adj, block = [], None
    info = L["strat"][sid]
    stat, name = info["stat"], spec(sid)["name"]
    base = base_of(sid)
    if info["status"] == "passed":
        adj.append((f"{name} passed the tournament ({stat['exp']:+.2f}R per trade)",
                    int(clamp(round(stat["exp"] * 20), 1, 8))))
    elif info["status"] == "watch":
        adj.append((f"{name} is on watch (no clear edge yet)", int(clamp(-4 + round(stat["exp"] * 20), -8, -2))))
    elif info["status"] == "rejected":
        block = f"{name} is rejected by the tournament"
    matched = {}
    for lesson in L.get("lessons") or []:
        if lesson["sid"] and lesson["sid"] != base:
            continue
        if not BUCKET_FN[lesson["bucket"]](f, base):
            continue
        cur = matched.get(lesson["bucket"])
        if cur is None or (lesson["sid"] and not cur["sid"]):
            matched[lesson["bucket"]] = lesson
    for lesson in sorted(matched.values(), key=lambda x: x["pts"]):
        if lesson["block"] and not block:
            block = f"Lesson: {lesson['label'].lower()} ({lesson['avg']:+.2f}R average over {lesson['n']} trades)"
    for lesson in sorted(matched.values(), key=lambda x: -abs(x["pts"]))[:4]:
        who = f"{STRATEGIES[base]['short']} trades" if lesson["sid"] else "trades"
        txt = (f"{lesson['label']}: {who} like this averaged {lesson['avg']:+.2f}R over {lesson['n']} "
               f"vs {lesson['base']:+.2f}R")
        if lesson["pts"]:
            adj.append((txt, lesson["pts"]))
    cd = (L.get("cool") or {}).get(coin)
    if cd:
        if cd["block"]:
            block = block or f"{cd['n']} stop-outs on {coin} in 24h: cooling down until {hhmm(cd['until'])} UTC"
        else:
            adj.append((f"Stopped out on {coin} at {hhmm(cd['last'])} UTC: cool-down", -6))
    return adj, block


# ---- journal state
ENGINE = 4  # journals written before version 4 have no trading costs in their results


def new_journal(now):
    return {"version": 1, "engine": ENGINE, "created": now, "updated": now, "scans": 0, "bt": None, "open": [],
            "closed": [], "status": {}, "changes": [], "learn": {"sk": {}}, "life": {}, "smart_prev": None}


def _upgrade(J, now, src):
    """A journal from before version 4 measured trades without costs, so its results cannot
    be mixed with the new ones: start a new journal (with a new backtest) instead."""
    if J.get("engine", 3) >= ENGINE:
        return J, src
    log("journal from an older version (no trading costs): starting a new one with a fresh backtest")
    K = new_journal(now)
    K["smart_prev"] = J.get("smart_prev")
    return K, "upgraded"


def _valid_journal(J):
    return isinstance(J, dict) and isinstance(J.get("open"), list) and isinstance(J.get("closed"), list)


def _site_has_journal(pages_url, now):
    """Whether the published latest.json comes from a version with a journal (3 or later)."""
    try:
        d = FETCH(pages_url.rstrip("/") + f"/data/latest.json?ts={now}", timeout=60)
    except HttpError as e:
        if e.code == 404:
            return False
        raise SystemExit(f"Could not check the published site ({e}). Stopping so the journal is not overwritten; "
                         f"the next run tries again.")
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Could not check the published site ({e}). Stopping so the journal is not overwritten; "
                         f"the next run tries again.")
    return isinstance(d, dict) and bool(d.get("journal"))


def load_journal(pages_url, journal_path, reset, now):
    """The journal lives on the published site. A missing file (404) starts a new one;
    any other failure stops the run so a good journal is never overwritten."""
    if reset:
        return new_journal(now), "reset"
    if journal_path:
        if os.path.exists(journal_path):
            with open(journal_path) as fh:
                J = json.load(fh)
            if not _valid_journal(J):
                raise SystemExit(f"{journal_path} is not a journal file")
            return _upgrade(J, now, "file")
        return new_journal(now), "new"
    if not pages_url:
        return new_journal(now), "new"
    url = pages_url.rstrip("/") + f"/data/journal.json?ts={now}"
    try:
        J = FETCH(url, timeout=90)
    except HttpError as e:
        if e.code == 404:
            if _site_has_journal(pages_url, now):
                raise SystemExit("journal.json is missing (404) although the published site shows a journal. "
                                 "Stopping so the journal is not replaced by an empty one; the next run tries "
                                 "again. If this keeps happening, run the workflow once with 'Start a new journal'.")
            return new_journal(now), "new"
        raise SystemExit(f"Could not read the published journal ({e}). Stopping so it is not overwritten; "
                         f"the next run tries again.")
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Could not read the published journal ({e}). Stopping so it is not overwritten; "
                         f"the next run tries again.")
    if not _valid_journal(J):
        raise SystemExit("The published journal.json is unreadable. Run the workflow with 'reset' to start over.")
    return _upgrade(J, now, "pages")


def new_trade(coin, s, a, t, f, conv_raw, final, rank=None, blk=None, bt=False):
    return {"id": f"{coin}-{s['sid']}-{t}", "c": coin, "s": s["sid"], "t": t, "bt": 1 if bt else 0,
            "px": sig6(a["last"]), "lo": sig6(s["elo"]), "hi": sig6(s["ehi"]), "m": sig6(s["mid"]),
            "sl": sig6(s["stop"]), "tp": [sig6(x) for x in s["tps"]],
            "tg": sig6(s["trigger"]) if s["trigger"] is not None else None, "st": s["status"],
            "tr": s["tp_r"], "sk": s["sk"], "cv": round(conv_raw, 1), "fs": round(final, 1), "rk": rank,
            "blk": blk, "f": f, "res": {"state": "open" if s["status"] == "in_zone" else "waiting", "r": 0.0,
                                        "done": False, "final": False}, "tags": []}


def _supersede(old, t, retire):
    old["res"] = {"state": "superseded", "r": 0.0, "done": False, "final": True, "xt": t}
    old["tags"] = []
    retire(old)


def log_signal(active, copies, tr, retire):
    """Add one signal. `active` and `copies` map coin+strategy to the trade that is
    still active. Returns "add", "copy" or "skip".
    - No active trade: the signal becomes the strategy's paper trade.
    - An unfilled order from an earlier scan is replaced by the newer signal, like
      moving a limit order (the old one is retired as "superseded").
    - A filled trade is kept and the new signal skipped. Exception: the new signal is
      published and the filled trade never was. Then the pick is tracked as a copy
      (dup=1) for the published-picks record only, so that record starts at the moment
      the pick was shown; copies never count for a strategy's stats, lessons or
      cool-downs. One copy at a time, handled like the originals."""
    key = (tr["c"], tr["s"])
    old = active.get(key)
    if old is None or old["res"].get("state") == "waiting":
        if old is not None:
            _supersede(old, tr["t"], retire)
        active[key] = tr
        return "add"
    if not tr.get("rk") or old.get("rk"):
        return "skip"
    cp = copies.get(key)
    if cp is not None:
        if cp["res"].get("state") != "waiting":
            return "skip"
        _supersede(cp, tr["t"], retire)
    tr["dup"] = 1
    copies[key] = tr
    return "copy"


def journal_add(J, trades):
    """Log this scan's signals (see log_signal); returns how many were added."""
    live = [t for t in J["open"] if t["res"].get("state") in ACTIVE]
    active = {(t["c"], t["s"]): t for t in live if not t.get("dup")}
    copies = {(t["c"], t["s"]): t for t in live if t.get("dup")}
    life = J.setdefault("life", {})
    retired = []
    n = 0
    for tr in trades:
        how = log_signal(active, copies, tr, retired.append)
        if how == "skip":
            continue
        J["open"].append(tr)
        if how == "add":
            life.setdefault(tr["s"], {"sig": 0, "n": 0, "win": 0, "loss": 0, "r": 0.0})["sig"] += 1
        n += 1
    if retired:
        gone = {id(t) for t in retired}
        J["open"] = [t for t in J["open"] if id(t) not in gone]
        J["closed"].extend(retired)
    return n


def journal_update(J, candles_by_coin, btc, now):
    """Re-simulate every open trade with fresh candles; move final ones to closed."""
    keep, moved = [], 0
    for t in J["open"]:
        c = candles_by_coin.get(t["c"])
        res = simulate_trade(t, c, now, btc) if c else None
        if res is not None:
            t["res"] = res
        elif now - t["t"] > 20 * 3600:
            res = t["res"]
            if res.get("done"):
                res["final"] = True
            else:
                res.update(state="no_data", final=True, r=0.0)
        t["tags"] = trade_tags(t)
        if t["res"].get("final"):
            _life_close(J, t)
            J["closed"].append(t)
            moved += 1
        else:
            keep.append(t)
    J["open"] = keep
    cutoff = now - CFG["journal_keep_days"] * 86400
    cut_sup = now - 2 * 86400  # orders replaced by a newer signal are kept briefly, unless they were picks

    def kept(t):
        return t["t"] >= cutoff and (t["t"] >= cut_sup or t.get("rk") or t["res"].get("state") != "superseded")

    # oldest first, so the cap drops the oldest trades of every strategy alike
    J["closed"] = sorted((t for t in J["closed"] if kept(t)), key=lambda t: t["t"])[-CFG["journal_max"]:]
    return moved


# ---- backtest: walk forward through past candles
def agg_1h(c15):
    return agg_tf(c15, 3600)


def fetch_history(crypto, dex_ok, days):
    """15m candles covering the last `days` days (plus a warm-up) for the most traded coins."""
    pool = sorted([t for t, c in crypto.items() if (not dex_ok) or (c.get("best_vol") or 0) >= CFG["min_dex_vol"]],
                  key=lambda t: -(crypto[t].get("best_vol") or 0))[:CFG["bt_universe"]]
    if "BTC" in crypto and "BTC" not in pool:
        pool.append("BTC")
    bars = days * 96 + 600  # warm-up: 150 hours, so the 4h trend exists from the first backtest hour
    got = parallel(lambda t: get_candles(crypto[t], "15m", bars), pool)
    return {t: r["candles"] for t, r in got.items() if r and len(r["candles"]) >= min(400, bars - 50)}


def bt_prepare(C):
    """Per coin: 1h candles with EMA8/21 and RSI, 4h closes with EMA20/50 and RSI, all computed
    once over the whole history (a live scan computes the same things on its own window)."""
    out = {}
    for t, c in C.items():
        h1 = agg_tf(c, 3600)
        cl = [x["c"] for x in h1]
        h4 = agg_tf(h1, 14400)
        c4 = [x["c"] for x in h4]
        out[t] = {"h1": h1, "h1t": [x["t"] for x in h1], "cl": cl, "e8": ema(cl, 8), "e21": ema(cl, 21),
                  "rsi": rsi_series(cl, 14), "h4t": [x["t"] for x in h4], "c4": c4, "e20": ema(c4, 20),
                  "e50": ema(c4, 50), "rsi4": rsi_series(c4, 14)}
    return out


def bt_htf(p, j, px):
    """4h trend from the first j closed 4h candles (see htf_from)."""
    if j < 30:
        return None
    e20, e50, r = p["e20"][j - 1], p["e50"][j - 1], p["rsi4"][j - 1]
    c4 = p["c4"]
    return {"trend": "up" if px > e20 > e50 else "down" if px < e20 < e50 else "mixed", "e20": e20, "e50": e50,
            "rsi": r if r is not None else 50.0, "dist20": px / e20 - 1,
            "chg24": c4[j - 1] / c4[j - 7] - 1 if j > 7 else None}


def _forming(last, t):
    """The candle that has just opened at scan time, as a live scan sees it (no range, no volume yet)."""
    return {"t": t, "o": last, "h": last, "l": last, "c": last, "qv": 0.0}


def backtest(C, crypto, now, days, specs, rank_specs=(), learn=None):
    """Walk-forward test of `specs` over the last `days` days of the 15m candles in C.
    Every hour it does what a live scan does, using only candles that had closed by
    then: rank the coins on 1h momentum, take the leaders plus dipping uptrends,
    analyse their 15m charts (with the 4h trend), run every spec and paper-trade the
    signals with the live rules and costs. Like a live scan, each hour's charts end
    with the candle that has just opened (flat, no volume). Smart-money data does not
    exist for the past, so smart-money follow cannot fire. `learn` holds the targets
    and stop factors to use (the live ones). The best signal per coin from
    `rank_specs` gets a pick rank, like the live page. Returns {spec id: [trades]},
    every trade evaluated up to `now`."""
    P_ = bt_prepare(C)
    end = (now // 3600) * 3600
    books = {sp["id"]: ({}, {}) for sp in specs}
    trades = {sp["id"]: [] for sp in specs}
    rank_specs = set(rank_specs)
    for T in range(end - days * 86400, end + 1, 3600):
        for sid, (active, copies) in books.items():
            for book in (active, copies):
                for key, tr in list(book.items()):
                    res = simulate_trade(tr, C[tr["c"]], T)
                    if res is not None:
                        tr["res"] = res
                    if tr["res"]["state"] not in ACTIVE:
                        trades[sid].append(book.pop(key))
        s1 = {}
        for t, p in P_.items():
            i1 = bisect.bisect_right(p["h1t"], T - 3600)  # 1h candles closed by T
            if i1 < 30 or p["h1t"][i1 - 1] < T - 7200:  # too little history, or no recent candles
                continue
            lo, last = i1 - 29, p["cl"][i1 - 1]
            e8, e21 = p["e8"][i1 - 1], p["e21"][i1 - 1]
            # the flat forming bar leaves Wilder's RSI unchanged and moves the EMAs one step toward the price
            s1[t] = h1_metrics(p["h1"][lo:i1] + [_forming(last, T)],
                               pre=(p["cl"][lo:i1] + [last], p["e8"][lo:i1] + [e8 + (last - e8) * 2 / 9],
                                    p["e21"][lo:i1] + [e21 + (last - e21) * 2 / 22], p["rsi"][i1 - 1]))
        if "BTC" not in s1 or len(s1) < 20:
            continue
        btc = s1["BTC"]
        for m in s1.values():
            m["rs6"] = m["r6"] - btc["r6"]
            m["score"] = stage1_score(m)
        ib = _bar_index(C["BTC"], T)
        regime = market_regime(s1, C["BTC"][max(0, ib - 95):ib] + [_forming(C["BTC"][ib - 1]["c"], T)]
                               if ib > 0 else None)
        ranked = sorted(s1, key=lambda t: -s1[t]["score"])
        cands = ranked[:CFG["stage2_n"]]
        dips = sorted([t for t in ranked[CFG["stage2_n"]:] if s1[t]["trend"] > 0 and s1[t]["r24"] > 0
                       and s1[t]["r3"] < 0], key=lambda t: -s1[t]["trend"])[:CFG["stage2_extra"]]
        ctx = {"regime": regime["label"], "btc3": btc["r3"]}
        found = []
        for t in cands + dips:
            c = C[t]
            i15 = _bar_index(c, T)
            if i15 < 96:
                continue
            a = m15_analysis(c[i15 - 95:i15] + [_forming(c[i15 - 1]["c"], T)], chart=False)
            p = P_[t]
            a["htf"] = bt_htf(p, bisect.bisect_right(p["h4t"], T - 14400), a["last"])
            # where the coin trades counts for liquidity; its funding and open interest then are unknown
            coin = {"venues": {d: {} for d in (crypto.get(t) or {}).get("venues") or {}},
                    "best_vol": (crypto.get(t) or {}).get("best_vol")}
            for s in find_signals(a, s1[t], None, learn=learn, specs=specs, ctx=ctx):
                found.append((conviction(a, s1[t], s, None, coin, regime)["score"], t, s, a))
        found.sort(key=lambda x: -x[0])
        rank, seen = {}, set()
        for score, t, s, _ in found:
            if s["sid"] in rank_specs and t not in seen and score >= CFG["min_pick_score"] \
                    and len(rank) < CFG["top_n"]:
                seen.add(t)
                rank[(t, s["sid"])] = len(rank) + 1
        for score, t, s, a in found:
            f = trade_features(a, s1[t], s, score, regime, crypto.get(t, {}), None, btc["r3"], T, live=False)
            active, copies = books[s["sid"]]
            log_signal(active, copies, new_trade(t, s, a, T, f, score, score, rank.get((t, s["sid"])), bt=True),
                       trades[s["sid"]].append)
    for sid, (active, copies) in books.items():
        trades[sid] += list(active.values()) + list(copies.values())
        for tr in trades[sid]:
            if tr["res"].get("state") != "superseded":
                res = simulate_trade(tr, C[tr["c"]], now, C.get("BTC"))
                if res is not None:
                    tr["res"] = res
                tr["tags"] = trade_tags(tr)
    return trades


def _life_close(J, t):
    """Lifetime counters for a strategy when one of its filled trades is closed for good."""
    if t["res"].get("done") and not t.get("dup"):
        lf = J.setdefault("life", {}).setdefault(t["s"], {"sig": 0, "n": 0, "win": 0, "loss": 0, "r": 0.0})
        lf["n"] += 1
        lf["r"] = round(lf["r"] + t["res"]["r"], 3)
        lf["win"] += 1 if t["res"]["r"] > 0.02 else 0
        lf["loss"] += 1 if t["res"]["state"] == "loss" else 0


def seed_journal(J, trades, now, days, n_coins, secs):
    """Put the base strategies' backtest trades into a new journal (marked bt=1). Only signals
    from before the journal started count, so a late seed never overlaps live trades."""
    life = J.setdefault("life", {})
    start = J.get("created", now)
    n = 0
    for sid, trs in trades.items():
        if "~" in sid:
            continue
        for tr in trs:
            if tr["t"] >= start:
                continue
            n += 1
            if not tr.get("dup"):
                life.setdefault(sid, {"sig": 0, "n": 0, "win": 0, "loss": 0, "r": 0.0})["sig"] += 1
            if tr["res"].get("final"):
                J["closed"].append(tr)
                _life_close(J, tr)
            else:
                J["open"].append(tr)
    J["bt"] = {"t": now, "days": days, "coins": n_coins, "trades": n, "from": (now // 3600) * 3600 - days * 86400,
               "secs": round(secs)}
    log(f"backtest: {days} days, {n_coins} coins, {n} paper trades seeded")


# ---- strategy discovery
# Once a day the scanner invents new variants of its strategies (different rule
# settings, an extra filter, other targets or a wider/tighter stop), backtests them over
# the last 30 days next to their parent, and sends the few that clearly beat the parent
# to a live forward test. A variant is published only after it passes the tournament on
# live trades it has never seen; one that loses money live, or has not passed after
# forward_max_days, is retired. Testing many variants on the same history always finds
# some that look good by luck, which is why the backtest only nominates and the live
# forward test decides.
TP_SETS = ((1.0, 1.8, 2.6), (1.2, 2.2, 3.5), (1.5, 2.5, 4.0), (0.8, 1.6, 2.4), (1.0, 2.0, 3.0), (2.0, 3.0, 5.0))
SK_SET = (0.8, 0.9, 1.1, 1.25, 1.5)
EXCLUSIVE = {"risk_on": "no_risk_off", "no_risk_off": "risk_on", "htf_up": "htf_not_down", "htf_not_down": "htf_up"}


PCT_PARAMS = ("pos24_min", "near_hi", "bb_max", "share_min")  # fractions shown as percentages


def _fmt_v(v, k=None):
    if isinstance(v, bool):
        return ""
    if k in PCT_PARAMS and isinstance(v, (int, float)):
        return f"{v * 100:g}%"
    if isinstance(v, (int, float)) and v >= 10000:
        return f"{v / 1000:,.0f}K"
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def variant_signature(base, params, filters, tp_r, sk):
    return json.dumps([base, sorted(params.items()), sorted(filters.items()), list(tp_r or []), sk], default=str)


def mutate(parent, rnd):
    """A child of `parent` (a spec) with one or two changes. Returns (params, filters, tp_r, sk, changes)."""
    base = parent["base"]
    params, filters = dict(parent["params"]), dict(parent.get("filters") or {})
    tp_r, sk = parent.get("tp_r"), parent.get("sk")
    changes = []
    for _ in range(rnd.choice((1, 1, 2))):
        kind = rnd.choices(("param", "filter", "targets", "stop"), weights=(5, 3, 1.5, 1))[0]
        if kind == "param":
            k = rnd.choice(list(PARAMS[base]))
            _, lo, hi, step = PARAMS[base][k]
            v = round(clamp(params[k] + step * rnd.choice((-2, -1, 1, 2)), lo, hi), 6)
            if isinstance(PARAMS[base][k][0], int) and float(v).is_integer():
                v = int(v)
            if v != params[k]:
                changes.append(PARAM_LABEL.get(k, k).format(v=_fmt_v(v, k)) + f" (was {_fmt_v(params[k], k)})")
                params[k] = v
        elif kind == "filter":
            if filters and rnd.random() < 0.25:
                k = rnd.choice(list(filters))
                changes.append("dropped: " + FILTERS[k][0].format(v=_fmt_v(filters.pop(k))))
                continue
            k = rnd.choice([f for f in FILTERS if f not in filters])
            v = rnd.choice(FILTER_VALUES[k]) if k in FILTER_VALUES else True
            filters.pop(EXCLUSIVE.get(k), None)
            filters[k] = v
            changes.append(FILTERS[k][0].format(v=_fmt_v(v)))
        elif kind == "targets":
            cur = tuple(tp_r or STRATEGIES[base]["tp_r"])
            new = rnd.choice([x for x in TP_SETS if x != cur])
            tp_r = list(new)
            changes.append("targets " + "/".join(f"{x:g}" for x in new) + "R (was " +
                           "/".join(f"{x:g}" for x in cur) + "R)")
        else:
            cur = sk or 1.0
            new = rnd.choice([x for x in SK_SET if x != cur])
            sk = new
            changes.append(f"stop {new:g}x the base distance (was {round(cur, 2):g}x)")
    return params, filters, tp_r, sk, changes


def disc_state(J):
    return J.setdefault("discovery", {"last": 0, "rounds": 0, "tested": 0, "next_id": 1, "seen": [], "log": []})


def discovery_due(J, now):
    d = J.get("discovery") or {}
    if now < (d.get("retry") or 0):  # the last attempt could not download the history
        return False
    return CFG["discovery"] and now - (d.get("last") or 0) >= CFG["discovery_every_h"] * 3600 - 600


def current_tuning(J, now):
    """The targets and stop factors the strategies trade with right now (as learn() sets them)."""
    horizon = now - CFG["journal_days"] * 86400
    done = sorted((t for t in J["closed"] + J["open"] if t["t"] >= horizon and not t.get("dup")
                   and t["res"].get("done")), key=lambda t: t["res"].get("xt") or t["t"])
    out = {"tp_r": {}, "sk": dict((J.get("learn") or {}).get("sk") or {})}
    for sp in active_specs():
        if sp.get("tp_r"):
            continue
        tt = tune_targets(sp["id"], [t for t in done if t["s"] == sp["id"]][-CFG["strategy_window"]:])
        if tt:
            out["tp_r"][sp["id"]] = tt["tp_r"]
    return out


def make_candidates(J, now, tune=None):
    """New variants to backtest this round (not yet in the journal). Parents are the base
    strategies (not smart-money follow, which cannot be backtested) and promoted variants,
    picked more often when they are doing well. A child starts from its parent's current
    targets and stop factor (`tune`) and keeps them fixed, so the backtest compares the
    two on equal terms and only the mutation differs."""
    tune = tune or {}
    d = disc_state(J)
    rnd = random.Random(now)
    seen = set(d.get("seen") or [])
    for v in (J.get("variants") or {}).values():
        seen.add(variant_signature(v["base"], spec(v["id"])["params"], v.get("filters") or {}, v.get("tp_r"),
                                   v.get("sk")))
    parents = [SPECS[s] for s in SID_ORDER if s != "SMF"]  # smart-money follow cannot be backtested
    parents += [sp for sp in SPECS.values() if sp["stage"] == "promoted" and sp["base"] != "SMF"]
    weight = {"passed": 3, "watch": 2, "testing": 2, "rejected": 1}
    w = [weight.get(((J.get("status") or {}).get(p["id"]) or {}).get("s", "testing"), 2) for p in parents]
    out, tries = [], 0
    while len(out) < CFG["discovery_batch"] and tries < CFG["discovery_batch"] * 20:
        tries += 1
        parent = rnd.choices(parents, weights=w)[0]
        eff = dict(parent, tp_r=list(parent.get("tp_r") or (tune.get("tp_r") or {}).get(parent["id"])
                                     or STRATEGIES[parent["base"]]["tp_r"]),
                   sk=parent.get("sk") or (tune.get("sk") or {}).get(parent["id"]) or 1.0)
        params, filters, tp_r, sk, changes = mutate(eff, rnd)
        if not changes:
            continue
        sig = variant_signature(parent["base"], params, filters, tp_r, sk)
        if sig in seen:
            continue
        seen.add(sig)
        n = d["next_id"]
        d["next_id"] = n + 1
        base = parent["base"]
        st = STRATEGIES[base]
        out.append({"id": f"{base}~{n}", "base": base, "variant": True, "params": params, "filters": filters,
                    "tp_r": tp_r, "sk": sk, "name": f"{st['name']} v{n}", "short": f"{st['short']} v{n}",
                    "kind": st["kind"], "desc": "", "stage": "candidate", "parent": parent["id"],
                    "changes": changes, "sig": sig})
    return out


def _bt_stats(trs):
    done = sorted((t for t in trs if t["res"].get("done") and not t.get("dup")),
                  key=lambda t: t["res"].get("xt") or t["t"])
    st = trade_stats(done)
    return {k: rnd(st.get(k), 3) for k in ("n", "exp", "se", "pf", "wr", "rr")} if st.get("n") else {"n": 0}


def select_forward(J, cands, res_bt, now):
    """Nominate the candidates that clearly beat their parent on the backtest."""
    d = J["discovery"]
    variants = J.setdefault("variants", {})
    slots = CFG["forward_slots"] - sum(1 for v in variants.values() if v["stage"] == "forward")
    parent_stats = {}
    scored = []
    for c in cands:
        st = _bt_stats(res_bt.get(c["id"], []))
        if c["parent"] not in parent_stats:
            parent_stats[c["parent"]] = _bt_stats(res_bt.get(c["parent"], []))
        ps = parent_stats[c["parent"]]
        c["bt"] = dict(st, parent_exp=ps.get("exp"), parent_n=ps.get("n"))
        good = (st["n"] >= 40 and st["exp"] - (st["se"] or 1) > 0 and (st["pf"] or 0) >= 1.3
                and st["exp"] >= (ps.get("exp") or 0) + 0.05)
        if good:
            scored.append((st["exp"] - st["se"], c))
    scored.sort(key=lambda x: -x[0])
    chosen = [c for _, c in scored[:max(0, slots)]]
    for c in chosen:
        pe = c["bt"]["parent_exp"]
        variants[c["id"]] = {
            "id": c["id"], "base": c["base"], "parent": c["parent"], "born": now, "since": now, "stage": "forward",
            "params": {k: x for k, x in c["params"].items() if x != PARAMS[c["base"]][k][0]},
            "filters": c["filters"], "tp_r": c["tp_r"], "sk": c["sk"], "name": c["name"], "short": c["short"],
            "changes": c["changes"], "bt": c["bt"],
            "desc": (f"Variant of {spec(c['parent'])['name']}: " + "; ".join(c["changes"]) + "."),
            "why": (f"Backtest {c['bt']['exp']:+.2f}R per trade over {c['bt']['n']} trades vs "
                    f"{(pe or 0):+.2f}R for its parent; now on a live test")}
    d["seen"] = (list(d.get("seen") or []) + [c["sig"] for c in cands])[-3000:]
    d["tested"] = d.get("tested", 0) + len(cands)
    d["rounds"] = d.get("rounds", 0) + 1
    d["last"] = now
    d.pop("retry", None)
    d.setdefault("log", []).append({"t": now, "tested": len(cands), "qualified": len(scored),
                                    "forward": [c["id"] for c in chosen]})
    d["log"] = d["log"][-30:]
    log(f"discovery: {len(cands)} variants backtested, {len(scored)} beat their parent, "
        f"{len(chosen)} sent to a live test")
    return chosen


def promotion_check(J, v, st, now):
    """Beyond passing the tournament on forward_min_trades live trades, a variant needs
    forward_min_days of live testing, trades on several different days (one market move
    can produce 20 correlated trades in a few hours), and results at least as good as its
    parent's over the same period. Returns (ok, what is still missing)."""
    age = (now - v["born"]) / 86400
    need = CFG["forward_min_days"]
    if age < need:
        return False, f"needs {need} days of live testing ({age:.1f} so far)"
    pool = J["closed"] + J["open"]
    days = len({t["t"] // 86400 for t in pool if t["s"] == v["id"] and t["res"].get("done") and not t.get("dup")})
    if days < need - 1:
        return False, f"its trades fall on only {days} different days (needs {need - 1})"
    par = [t["res"]["r"] for t in pool if t["s"] == v["parent"] and t["t"] >= v["born"] and t["res"].get("done")
           and not t.get("dup")]
    if len(par) >= 10 and (st.get("exp") or 0) < sum(par) / len(par):
        return False, (f"{(st.get('exp') or 0):+.2f}R per trade vs {sum(par) / len(par):+.2f}R for its parent over "
                       f"the same days")
    return True, ""


def manage_variants(J, L, now):
    """Promote variants that passed on live trades, retire the ones that failed or ran out of time."""
    variants = J.get("variants") or {}
    changed = False

    def move(v, stage, why):
        nonlocal changed
        J.setdefault("changes", []).append({"t": now, "sid": v["id"], "kind": "variant", "from": v["stage"],
                                            "to": stage, "why": why})
        v.update(stage=stage, since=now, why=why)
        if stage == "retired":
            v["ended"] = now
        changed = True

    for v in variants.values():
        info = (L.get("strat") or {}).get(v["id"])
        if not info or v["stage"] not in ("forward", "promoted"):
            continue
        st, status = info["stat"], info["status"]
        v["last_stat"] = {k: rnd(st.get(k), 3) for k in ("n", "wr", "exp", "pf")}  # kept after retirement
        if v["stage"] == "forward":
            ok, wait = (promotion_check(J, v, st, now) if status == "passed"
                        and st.get("n", 0) >= CFG["forward_min_trades"] else (False, ""))
            v["wait"] = wait
            if ok:
                v.pop("wait", None)
                move(v, "promoted", f"passed on live trades: {info['why']}")
            elif status == "rejected":
                move(v, "retired", f"lost money on live trades: {info['why']}")
            elif now - v["born"] > CFG["forward_max_days"] * 86400:
                move(v, "retired", f"did not pass within {CFG['forward_max_days']} days ({info['why']})")
        elif status == "rejected":
            move(v, "retired", f"stopped working: {info['why']}")
    # forget variants retired long ago once none of their trades are left in the journal
    cutoff = now - CFG["journal_keep_days"] * 86400
    used = {t["s"] for t in J["open"]} | {t["s"] for t in J["closed"]}
    for vid in [k for k, v in variants.items() if v["stage"] == "retired" and k not in used
                and (v.get("ended") or v.get("since") or 0) < cutoff]:
        variants.pop(vid)
        for k in ("life", "status"):
            (J.get(k) or {}).pop(vid, None)
        ((J.get("learn") or {}).get("sk") or {}).pop(vid, None)
        changed = True
    promoted = [v for v in variants.values() if v["stage"] == "promoted"]
    if len(promoted) > CFG["variants_max"]:
        exp = {v["id"]: ((L.get("strat") or {}).get(v["id"], {}).get("stat") or {}).get("exp") or 0 for v in promoted}
        for v in sorted(promoted, key=lambda v: exp[v["id"]])[:len(promoted) - CFG["variants_max"]]:
            move(v, "retired", "replaced by stronger variants")
    J["changes"] = (J.get("changes") or [])[-60:]
    return changed


def discovery_summary(J, L, now):
    d = J.get("discovery") or {}
    rows = []
    for v in sorted((J.get("variants") or {}).values(), key=lambda v: -v.get("since", 0)):
        info = (L.get("strat") or {}).get(v["id"]) or {}
        st = info.get("stat") or v.get("last_stat") or {}
        rows.append({"id": v["id"], "name": v["name"], "short": v["short"], "base": v["base"],
                     "parent": v["parent"], "stage": v["stage"], "since": v.get("since"), "born": v.get("born"),
                     "changes": v.get("changes") or [], "bt": v.get("bt") or {}, "why": v.get("why", ""),
                     "wait": v.get("wait") or "", "tp_r": v.get("tp_r"), "sk": v.get("sk"),
                     "status": info.get("status"), "n": st.get("n", 0), "wr": rnd(st.get("wr"), 3),
                     "exp": rnd(st.get("exp"), 3), "pf": rnd(st.get("pf"), 2)})
    order = {"promoted": 0, "forward": 1, "retired": 2}
    rows.sort(key=lambda r: (order.get(r["stage"], 3), -(r["since"] or 0)))
    counts = {k: sum(1 for r in rows if r["stage"] == k) for k in ("forward", "promoted", "retired")}
    return {"last": d.get("last"), "rounds": d.get("rounds", 0), "tested": d.get("tested", 0),
            "next": (d.get("last") or now) + CFG["discovery_every_h"] * 3600 if d.get("last") else None,
            "counts": counts, "rows": [r for r in rows if r["stage"] != "retired"] + [r for r in rows if r["stage"] == "retired"][:12],
            "log": list(reversed(d.get("log") or []))[:10],
            "rules": {"forward_slots": CFG["forward_slots"], "forward_min_trades": CFG["forward_min_trades"],
                      "forward_min_days": CFG["forward_min_days"],
                      "forward_max_days": CFG["forward_max_days"], "batch": CFG["discovery_batch"],
                      "every_h": CFG["discovery_every_h"]}}


# ---- page summary and CSV
def _curve(rs, k=60):
    cum, out = 0.0, [0.0]
    for x in rs:
        cum += x
        out.append(round(cum, 2))
    if len(out) > k:
        step = (len(out) - 1) / (k - 1)
        out = [out[round(i * step)] for i in range(k)]
    return out


def picks_stats(trs):
    trs = [t for t in trs if t["res"].get("state") != "superseded"]  # a newer signal took over the order
    filled = [t for t in trs if t["res"].get("done") or t["res"].get("state") in ("open", "tp_open")]
    closed = [t for t in trs if t["res"].get("done")]
    tp1 = [t for t in filled if (t["res"].get("tph") or [None])[0]]
    return {"picks": len(trs), "filled": len(filled), "closed": len(closed), "tp1": len(tp1),
            "stopped": sum(1 for t in closed if t["res"]["state"] == "loss"),
            "missed": sum(1 for t in trs if t["res"].get("state") in ("missed", "no_fill")),
            "tp1_rate": round(len(tp1) / len(filled), 3) if filled else None,
            "win_rate": round(sum(1 for t in closed if t["res"]["r"] > 0.02) / len(closed), 3) if closed else None,
            "total_r": round(sum(t["res"]["r"] for t in closed), 2),
            "avg_r": round(sum(t["res"]["r"] for t in closed) / len(closed), 3) if closed else None,
            "sd_r": round(statistics.pstdev([t["res"]["r"] for t in closed]), 3) if len(closed) > 1 else None}


def journal_summary(J, L, now, sig_now):
    horizon = now - CFG["journal_days"] * 86400
    everything = [t for t in J["closed"] + J["open"] if t["t"] >= horizon]
    trades = [t for t in everything if not t.get("dup")]  # copies of published picks count for the picks only
    done = sorted((t for t in trades if t["res"].get("done")), key=lambda t: t["res"].get("xt") or t["t"])
    strategies = []
    for sid in [sp["id"] for sp in active_specs() if sp["stage"] in ("base", "promoted")]:
        info, S_ = L["strat"][sid], spec(sid)
        st = info["stat"]
        ds = [t for t in done if t["s"] == sid][-CFG["strategy_window"]:]
        sig = [t for t in trades if t["s"] == sid]
        resolved = [t for t in sig if t["res"].get("done") or t["res"].get("state") in ("missed", "no_fill", "invalid")]
        filled = [t for t in resolved if t["res"].get("done")]
        live = [t["res"]["r"] for t in ds if not t.get("bt")]
        tuned = info.get("tuned")
        strategies.append({
            "id": sid, "name": S_["name"], "short": S_["short"], "desc": S_["desc"], "kind": S_["kind"],
            "base": S_["base"], "variant": S_["variant"],
            "status": info["status"], "why": info["why"], "since": info["since"],
            "n": st.get("n", 0), "wr": rnd(st.get("wr"), 3), "exp": rnd(st.get("exp"), 3), "pf": rnd(st.get("pf"), 2),
            "rr": rnd(st.get("rr"), 2), "net": rnd(st.get("net"), 2), "dd": rnd(st.get("dd"), 2),
            "tp1": rnd(st.get("tp1"), 3), "stopped": rnd(st.get("stopped"), 3), "hold": rnd(st.get("hold"), 1),
            "avg_win": rnd(st.get("avg_win"), 2), "avg_loss": rnd(st.get("avg_loss"), 2),
            "signals": len(sig), "fill_rate": rnd(len(filled) / len(resolved), 3) if resolved else None,
            "missed": rnd(sum(1 for t in resolved if t["res"]["state"] == "missed") / len(resolved), 3)
            if resolved else None,
            "live_n": len(live), "live_exp": rnd(sum(live) / len(live), 3) if live else None,
            "bt_n": len(ds) - len(live),
            "tp_r": S_.get("tp_r") or (tuned or {}).get("tp_r") or list(STRATEGIES[S_["base"]]["tp_r"]),
            "own_tp": bool(S_.get("tp_r")), "default_tp": list(STRATEGIES[S_["base"]]["tp_r"]),
            "reach": (tuned or {}).get("reach"), "tuned_n": (tuned or {}).get("n"),
            "sk": S_.get("sk") or L["sk"].get(sid, 1.0), "curve": _curve([t["res"]["r"] for t in ds]),
            "now": sig_now.get(sid, []), "life": (J.get("life") or {}).get(sid)})
    strategies.sort(key=lambda s: (STATUS_RANK[s["status"]], -(s["exp"] if s["exp"] is not None else -9)))

    base_done = [t for t in done if "~" not in t["s"]]
    losses = [t for t in base_done if t["res"]["state"] == "loss"]
    lesson_by_bucket = {}
    for lesson in L.get("lessons") or []:
        if not lesson["sid"]:
            lesson_by_bucket[lesson["bucket"]] = lesson
    counts = {}
    for t in losses:
        for g in t.get("tags") or []:
            counts[g] = counts.get(g, 0) + 1
    mistakes = []
    for g, k in sorted(counts.items(), key=lambda kv: -kv[1]):
        b = TAG_BUCKET.get(g)
        lesson = lesson_by_bucket.get(b) if b else None
        if g == "hunted":
            wide = [f"{STRATEGIES[s]['short']} {L['sk'][s]:.2f}x" for s in SID_ORDER if L["sk"].get(s, 1.0) > 1.0]
            fix = ("stops widened: " + ", ".join(wide)) if wide else \
                "watched per strategy: a stop widens 10% when 35%+ of its recent stops were hunted"
        elif g == "fast_fail":
            fix = "counted in each breakout strategy's record, which decides whether it stays published"
        elif lesson and lesson["block"]:
            fix = f"signals like this are blocked from the picks ({lesson['avg']:+.2f}R average)"
        elif lesson and lesson["pts"] < 0:
            fix = (f"{lesson['pts']} points on new signals like this ({lesson['avg']:+.2f}R average vs "
                   f"{lesson['base']:+.2f}R for the rest)")
        elif lesson:
            fix = (f"not a real mistake so far: these trades averaged {lesson['avg']:+.2f}R vs {lesson['base']:+.2f}R, "
                   f"so they get +{lesson['pts']} points")
        elif b:
            fix = "not a significant pattern yet"
        else:
            fix = ""
        mistakes.append({"tag": g, "label": MISTAKES[g], "n": k, "share": round(k / len(losses), 3), "fix": fix})

    calib = []
    for lo_, hi_, lab in ((0, 55, "under 55"), (55, 65, "55-65"), (65, 75, "65-75"), (75, 101, "75+")):
        g = [t["res"]["r"] for t in base_done if lo_ <= (t.get("fs") or 0) < hi_]
        calib.append({"band": lab, "n": len(g), "wr": rnd(sum(1 for x in g if x > 0.02) / len(g), 3) if g else None,
                      "avg": rnd(sum(g) / len(g), 3) if g else None})

    live_picks = [t for t in everything if t.get("rk") and not t.get("bt")]
    bt_picks = [t for t in everything if t.get("rk") and t.get("bt")]
    day = [t for t in live_picks if now - t["t"] <= 86400]
    shown = [t for t in everything if t["res"].get("state") != "superseded" or t.get("rk")]
    recent = sorted(shown, key=lambda t: (-t["t"], t.get("rk") or 99))[:240]
    rows = []
    for t in recent:
        res = t["res"]
        rows.append([t["t"], t["c"], t["s"], t["st"], t.get("fs"), t.get("rk"), res.get("state"),
                     res.get("ro") if res.get("state") in ("open", "tp_open") else res.get("r"),
                     res.get("mfe"), res.get("mae"), t.get("tags") or [], t.get("bt", 0), t.get("blk"),
                     t["lo"], t["hi"], t["sl"], t["tp"][0], res.get("hunt")])
    changes = sorted(J.get("changes") or [], key=lambda c: -c["t"])[:24]
    return {
        "since": J.get("created"), "scans": J.get("scans", 0), "bt": J.get("bt"),
        "counts": {"open": len(J["open"]), "closed": len(J["closed"]), "window": len(trades),
                   "done": len(done), "live": sum(1 for t in trades if not t.get("bt")),
                   "replay": sum(1 for t in trades if t.get("bt"))},
        "strategies": strategies,
        "lessons": (L.get("lessons") or [])[:30],
        "mistakes": mistakes, "losses": len(losses), "calib": calib,
        "cool": [{"coin": c, **v} for c, v in sorted((L.get("cool") or {}).items(), key=lambda kv: -kv[1]["last"])],
        "picks": {"day": picks_stats(day), "all": picks_stats(live_picks), "top5": picks_stats(
            [t for t in live_picks if t["rk"] <= 5]), "replay": picks_stats(bt_picks)},
        # R of every closed pick (latest last), for the goal tracker's projection on the page
        "picks_r": [round(t["res"]["r"], 3) for t in sorted((t for t in live_picks if t["res"].get("done")),
                                                               key=lambda t: t["res"].get("xt") or t["t"])][-400:],
        "bt_picks_r": [round(t["res"]["r"], 3) for t in sorted((t for t in bt_picks if t["res"].get("done")),
                                                                 key=lambda t: t["res"].get("xt") or t["t"])][-400:],
        "rows": rows, "changes": changes, "discovery": discovery_summary(J, L, now),
        "rules": {"min_trades": CFG["min_trades"], "window_days": CFG["journal_days"],
                  "strategy_window": CFG["strategy_window"], "lesson_min": CFG["lesson_min"],
                  "publish": list(CFG["publish"]), "valid_hours": CFG["valid_hours"],
                  "track_hours": CFG["track_hours"], "hunt_hours": CFG["hunt_hours"],
                  "costs": CFG["costs"], "fee_taker": CFG["fee_taker"], "fee_maker": CFG["fee_maker"],
                  "slip": [list(x) for x in CFG["slip"]], "fund_default": CFG["fund_default"]},
    }


CSV_COLS = ["id", "time_utc", "coin", "strategy", "source", "status_at_scan", "rank", "score_raw", "score_final",
            "blocked", "scan_price", "entry_low", "entry_high", "stop", "tp1", "tp2", "tp3", "tp_r", "stop_factor",
            "result", "r_net", "r_gross", "costs_r", "fill_price", "fill_time_utc", "exit_time_utc", "mfe_r", "mae_r",
            "stop_hunt",
            "btc_move", "tags", "rsi", "adx", "vol_ratio", "atr_above_ema21", "regime", "smart_long_share",
            "dex_vol_24h", "funding_8h"]


def journal_csv(J):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLS)
    for t in sorted(J["closed"] + J["open"], key=lambda t: t["t"]):
        res, f = t["res"], t.get("f") or {}
        src = ("backtest" if t.get("bt") else "live") + (" (copy of a published pick)" if t.get("dup") else "")
        w.writerow([t["id"], iso(t["t"]), t["c"], t["s"], src, t["st"],
                    t.get("rk") or "", t.get("cv"), t.get("fs"), t.get("blk") or "", t["px"], t["lo"], t["hi"],
                    t["sl"], *t["tp"], "/".join(str(x) for x in t.get("tr") or []), t.get("sk"),
                    res.get("state"), res.get("ro") if res.get("state") in ("open", "tp_open") else res.get("r"),
                    res.get("gross", ""), res.get("cost", ""),
                    res.get("fill") or "", iso(res["ft"]) if res.get("ft") else "",
                    iso(res["xt"]) if res.get("xt") else "", res.get("mfe", ""), res.get("mae", ""),
                    "" if res.get("hunt") is None else int(res["hunt"]), res.get("btc", ""),
                    " ".join(t.get("tags") or []), f.get("rsi"), f.get("adx"), f.get("vr"), f.get("ext"),
                    f.get("reg"), "" if f.get("sm") is None else f["sm"], f.get("liq"),
                    "" if f.get("fund") is None else f["fund"]])
    return buf.getvalue()


# --------------------------------------------------------------------------- alerts
def post_json(url, body, timeout=20):
    """POST a JSON body and ignore the reply (webhooks answer 204 with no body)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def alert_text(out, pages_url=None):
    new = [p for p in out["picks"] if p.get("new") and p["conv"]["score"] >= CFG["alert_min_score"]]
    new = new[:CFG["alert_max"]]
    if not new:
        return None
    lines = [f"Perp DEX Radar {hhmm(out['scan_t'])} UTC - {len(new)} new pick{'s' if len(new) > 1 else ''} "
             f"({out['regime']['label']} market)"]
    for p in new:
        tp = " / ".join(fp(x) for x in p["tps"])
        lines.append("")
        lines.append(f"#{p['rank']} {p['coin']}: {p['setup_name']}, score {p['conv']['score']:.0f} "
                     f"({p['conv']['grade']}), strategy {p['strategy']['status']}")
        if p.get("trigger"):
            lines.append(f"Only after a 15m close above {fp(p['trigger'])}")
        lines.append(f"Entry {fp(p['elo'])}-{fp(p['ehi'])}  Stop {fp(p['stop'])} ({pc(-p['risk'])})  TP {tp}")
        lines.append(p["status_text"] + f". Valid until {hhmm(p['valid_until'])} UTC.")
    if pages_url:
        lines.append("")
        lines.append(pages_url.rstrip("/") + "/")
    return "\n".join(lines)


def alerts_on():
    """Which alert channels are configured (names only, never the secrets)."""
    on = []
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        on.append("Telegram")
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        on.append("Discord")
    return on


def send_alerts(out, pages_url=None):
    """Telegram and/or Discord message for new picks, when the secrets are set."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    hook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not ((token and chat) or hook):
        return 0
    text = alert_text(out, pages_url)
    if not text:
        return 0
    sent = 0
    if token and chat:
        try:
            post_json(f"https://api.telegram.org/bot{token}/sendMessage",
                      {"chat_id": chat, "text": text, "disable_web_page_preview": True})
            sent += 1
        except Exception as e:  # noqa: BLE001 - never print the token
            note_error(f"Telegram alert failed ({type(e).__name__}: {getattr(e, 'code', '')})")
    if hook:
        try:
            post_json(hook, {"content": text[:1900]})
            sent += 1
        except Exception as e:  # noqa: BLE001
            note_error(f"Discord alert failed ({type(e).__name__}: {getattr(e, 'code', '')})")
    return sent


# --------------------------------------------------------------------------- pipeline
STATUS_TEXT = {"in_zone": "In the entry zone now", "above": "Above the zone: wait for the pullback",
               "reclaim": "Just under the zone: buy-stop at the zone low", "trigger": "Waiting for the breakout trigger"}
DEX_CODE = {"hyperliquid": "HL", "variational": "VR", "aster": "AS", "edgex": "EG", "lighter": "LT",
            "dydx": "DY", "paradex": "PX", "extended": "EX"}


def next_scan_ts(ts):
    base = dt.datetime.fromtimestamp(ts, dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    for k in range(0, 48 * 60 // CFG["schedule_every_min"] + 2):
        cand = base + dt.timedelta(minutes=CFG["schedule_minute"] + k * CFG["schedule_every_min"])
        if cand.timestamp() > ts + 120:
            return int(cand.timestamp())
    return ts + 3600


def venue_list(c):
    out = []
    for v in sorted(c["venues"].values(), key=lambda v: -(v.get("vol") or 0)):
        out.append({"dex": v["dex"], "name": DEX_NAME[v["dex"]], "sym": v["sym"], "mult": v["mult"],
                    "vol": round(v["vol"]) if v.get("vol") else None,
                    "funding8h": rnd(v.get("funding8h"), 7), "oi": round(v["oi"]) if v.get("oi") else None})
    return out


def pick_extras(ranked, s1, smc, liquid, taken):
    """Extra deep dives so the dip-buy and smart-money strategies see their charts:
    coins the top traders hold long, and 1h uptrends that are dipping."""
    k = CFG["stage2_extra"]
    rest = [t for t in ranked if t not in taken and liquid(t)]
    sm_c = sorted([t for t in rest if smc.get(t) and smc[t]["share"] >= 0.65 and smc[t]["long_usd"] >= 250_000],
                  key=lambda t: -smc[t]["long_usd"])[:k // 2]
    dips = sorted([t for t in rest if t not in sm_c and s1[t]["trend"] > 0 and s1[t]["r24"] > 0 and s1[t]["r3"] < 0],
                  key=lambda t: -s1[t]["trend"])[:k - len(sm_c)]
    return sm_c + dips


def run(out_dir, pages_url=None, journal_path=None, index_src=None, reset=False, replay_days=None):
    t0 = time.time()
    scan_t = now_ts()
    coins, dex_status, dex_ok = build_universe()
    crypto = {t: c for t, c in coins.items() if not c["tradfi"]}
    tradfi = sorted(t for t, c in coins.items() if c["tradfi"])
    log(f"universe: {len(coins)} coins across {sum(1 for s in dex_status.values() if s['ok'])} DEXs, "
        f"{len(crypto)} crypto, {len(tradfi)} excluded")

    J, jsrc = load_journal(pages_url, journal_path, reset, scan_t)
    load_specs(J)
    log(f"journal ({jsrc}): {len(J['open'])} open and {len(J['closed'])} closed trades, "
        f"{sum(1 for sp in SPECS.values() if sp['stage'] in ('forward', 'promoted'))} active variants")
    if jsrc in ("new", "upgraded") and pages_url and not J.get("smart_prev"):
        try:  # carry the smart-money snapshot over from version 2
            h = FETCH(pages_url.rstrip("/") + f"/data/history.json?ts={scan_t}")
            if isinstance(h, dict) and isinstance(h.get("smart_prev"), dict):
                J["smart_prev"] = h["smart_prev"]
        except Exception:  # noqa: BLE001
            pass
    smart = hl_smart_money(prev=J.get("smart_prev"))
    smc = smart["by_coin"] if smart else {}
    SM_META.clear()
    if smart:
        SM_META.update(traders=smart["traders"])

    # stage 1: every crypto coin on 1h candles
    res1 = parallel(lambda t: get_candles(crypto[t], "1h", CFG["h1_bars"]), list(crypto))
    s1, nodata, src_count = {}, [], {}
    for t in crypto:
        r = res1.get(t)
        if not r or len(r["candles"]) < 30:
            nodata.append(t)
            continue
        m = h1_metrics(r["candles"])
        m["src"] = r["src"]
        s1[t] = m
        src_count[r["src"]] = src_count.get(r["src"], 0) + 1
    btc = s1.get("BTC")
    for t, m in s1.items():
        m["rs6"] = m["r6"] - (btc["r6"] if btc else 0.0)
        m["score"] = stage1_score(m)
    ranked = sorted(s1, key=lambda t: -s1[t]["score"])
    log(f"stage 1: {len(s1)} charted, {len(nodata)} without data, sources {src_count}")
    if len(s1) < 20:
        raise SystemExit("Too few coins returned data; exchanges unreachable from this runner?")

    btc15 = get_candles(crypto["BTC"], "15m", CFG["m15_bars"], prefer=btc["src"] if btc else None) \
        if "BTC" in crypto else None
    regime = market_regime(s1, btc15["candles"] if btc15 else None)
    btc3 = btc["r3"] if btc else 0.0

    # backtest: a new journal starts with every strategy's last `days` days, and once a day
    # strategy discovery backtests new variants against their parents
    bt_c = {}
    days = CFG["bt_days"] if replay_days is None else replay_days
    bt0 = J.get("bt") or {}
    # a new journal gets its backtest; if the download failed, it is tried again for up to 3 days
    seed = days > 0 and (not J.get("bt") or (bt0.get("skipped") and scan_t >= (bt0.get("retry") or 0)
                                             and scan_t - J.get("created", scan_t) < 3 * 86400))
    disc = days > 0 and discovery_due(J, scan_t)
    if seed or disc:
        t_bt = time.time()

        seeded = False

        def skipped(why):
            note_error(why)
            if seed and not seeded:
                J["bt"] = {"t": scan_t, "days": 0, "coins": 0, "trades": 0, "skipped": True,
                           "retry": scan_t + 2 * 3600}
            if disc:
                disc_state(J)["retry"] = scan_t + 6 * 3600  # try the download again in 6 hours

        try:
            bt_c = fetch_history(crypto, dex_ok, days)
            if len(bt_c) >= 20 and "BTC" in bt_c:
                tune = current_tuning(J, scan_t)
                cands = make_candidates(J, scan_t, tune) if disc else []
                specs_bt = [SPECS[s] for s in SID_ORDER] + [sp for sp in SPECS.values() if sp["stage"] == "promoted"]
                res_bt = backtest(bt_c, crypto, scan_t, days, specs_bt + cands, rank_specs=SID_ORDER if seed else (),
                                  learn=tune)
                if seed:
                    seed_journal(J, res_bt, scan_t, days, len(bt_c), time.time() - t_bt)
                    seeded = True
                if disc:
                    select_forward(J, cands, res_bt, scan_t)
                    load_specs(J)
                log(f"backtest done in {time.time() - t_bt:.0f}s ({len(specs_bt) + len(cands)} strategies and "
                    f"variants)")
            else:
                skipped(f"Backtest skipped: only {len(bt_c)} coins returned enough 15m history")
                bt_c = {}
        except Exception as e:  # noqa: BLE001 - a backtest problem must never stop the hourly scan
            traceback.print_exc()
            skipped(f"Backtest failed ({type(e).__name__}); the scan went on without it")
            bt_c = {}

    # stage 2: 15m deep dive on the leaders that trade with real volume on a DEX, plus extras
    def liquid(t):
        return (not dex_ok) or (crypto[t].get("best_vol") or 0) >= CFG["min_dex_vol"]

    cands = [t for t in ranked if liquid(t)][:CFG["stage2_n"]]
    extras = pick_extras(ranked, s1, smc, liquid, set(cands))
    cands += extras
    res2 = parallel(lambda t: get_candles(crypto[t], "15m", CFG["m15_bars"], prefer=s1[t]["src"]), cands)
    A = {}
    for t in cands:
        r = res2.get(t)
        if not r or len(r["candles"]) < 60:
            continue
        a = m15_analysis(r["candles"])
        a.update(src=r["src"], sym=r["sym"], scale=r["scale"])
        a["htf"] = htf_metrics(res1[t]["candles"], a["last"], now=scan_t) if res1.get(t) else None
        a["_candles"] = r["candles"]
        a["_t"] = max(scan_t, r.get("fetched") or scan_t)  # trades start when their price was read
        A[t] = a

    # 1. follow the journal's open paper trades with fresh candles that reach back to each trade
    need = {}
    for tr in J["open"]:
        need[tr["c"]] = min(need.get(tr["c"], tr["t"]), tr["t"])
    have = {}
    for t, oldest in need.items():
        for c in (bt_c.get(t), A[t]["_candles"] if t in A else None):
            if c and c[0]["t"] <= oldest - 900:
                have[t] = c
                break
    missing = [t for t in need if t not in have and t in crypto]
    if missing:
        def cover(t):  # enough 15m candles to reach the oldest open trade on this coin
            return get_candles(crypto[t], "15m", min(1000, max(CFG["m15_bars"], (scan_t - need[t]) // 900 + 8)))

        more = parallel(cover, missing)
        for t, r in more.items():
            if r:
                have[t] = r["candles"]
    btc_c = bt_c.get("BTC") or (btc15["candles"] if btc15 else None)
    moved = journal_update(J, have, btc_c, scan_t)

    # 2. learn from everything that has closed; promote or retire strategy variants
    L = learn(J, scan_t)
    if manage_variants(J, L, scan_t):
        load_specs(J)

    # 3. run every strategy on this scan's charts, with the learned targets and stops
    prelim = {}
    ctx = {"regime": regime["label"], "btc3": btc3}
    specs_now = active_specs()
    for t, a in A.items():
        a["signals"] = find_signals(a, s1[t], smc.get(t), L, specs=specs_now, ctx=ctx)
        if a["signals"]:
            prelim[t] = max(conviction(a, s1[t], s, None, crypto[t], regime, smc.get(t))["score"]
                            for s in a["signals"])
    pos_list = sorted(prelim, key=lambda t: -prelim[t])[:CFG["positioning_n"]]
    POS = parallel(fetch_positioning, pos_list)
    sigs, sig_now = [], {}
    for t, a in A.items():
        for s in a["signals"]:
            conv = conviction(a, s1[t], s, POS.get(t), crypto[t], regime, smc.get(t))
            f = trade_features(a, s1[t], s, conv["score"], regime, crypto[t], smc.get(t), btc3, scan_t)
            adj, block = adjustments(s["sid"], f, t, L)
            status = L["strat"][s["sid"]]["status"]
            if not block and status not in CFG["publish"]:
                block = f"{s['name']} is {status}: paper-traded only"
            if not block and spec(s["sid"])["stage"] == "forward":
                block = "new variant in its live test: paper-traded only"
            final = round(clamp(conv["score"] + sum(p for _, p in adj), 0, 100), 1)
            sigs.append({"t": t, "s": s, "conv": conv, "f": f, "adj": adj, "block": block, "final": final})
            sig_now.setdefault(s["sid"], []).append({"coin": t, "score": final, "block": bool(block)})
    for v in sig_now.values():
        v.sort(key=lambda x: -x["score"])
    best = {}
    for x in sigs:
        if not x["block"] and (x["t"] not in best or x["final"] > best[x["t"]]["final"]):
            best[x["t"]] = x
    order = sorted(best.values(), key=lambda x: -x["final"])
    pick_sigs = [x for x in order if x["final"] >= CFG["min_pick_score"]][:CFG["top_n"]]
    chosen = {id(x) for x in pick_sigs}
    watch_sigs = [x for x in order if id(x) not in chosen][:CFG["watch_n"]]
    log(f"stage 2: {len(A)} deep dives ({len(extras)} extra), {len(sigs)} signals on {len({x['t'] for x in sigs})} "
        f"coins, {len(best)} publishable, Gate.io positioning for {sum(1 for v in POS.values() if v)}")

    prev_picks = set(J.get("last_picks") or [])

    def record(rank, x, full=True):
        t, s = x["t"], x["s"]
        a, c, pos, sm = A[t], crypto[t], POS.get(t), smc.get(t)
        sid = s["sid"]
        info = L["strat"][sid]
        st_ = info["stat"]
        tuned = info.get("tuned")
        conv = dict(x["conv"], raw=x["conv"]["score"], score=x["final"], grade=grade_of(x["final"]),
                    adj=[[lab, p] for lab, p in x["adj"]])
        lc = {"status": info["status"], "stat": st_, "adj": x["adj"], "live_n": st_.get("live_n"),
              "bt_n": st_.get("bt_n"),
              "tuned": (f"TP1 {tuned['tp_r'][0]:g}R is where {tuned['reach'][0] * 100:.0f}% of its last "
                        f"{tuned['n']} trades reached" if tuned else None)}
        rec = {
            "rank": rank, "coin": t, "name": c.get("name") or t, "sid": sid, "setup": sid,
            "setup_name": s["name"], "short": s["short"],
            "status": s["status"], "status_text": STATUS_TEXT[s["status"]],
            "price": sig6(a["last"]), "elo": sig6(s["elo"]), "ehi": sig6(s["ehi"]), "mid": sig6(s["mid"]),
            "stop": sig6(s["stop"]), "tps": [sig6(v) for v in s["tps"]],
            "trigger": sig6(s["trigger"]) if s["trigger"] else None, "tp_r": s["tp_r"], "sk": s["sk"],
            "risk": rnd(s["risk"], 5), "tp_pct": [rnd(v / s["mid"] - 1, 5) for v in s["tps"]],
            "conv": conv, "new": t not in prev_picks,
            "valid_until": scan_t + CFG["valid_hours"] * 3600,
            "src": a["src"], "sym": a["sym"], "venues": venue_list(c),
            "best_vol": round(c["best_vol"]) if c.get("best_vol") else None,
            "strategy": {"id": sid, "name": s["name"], "short": s["short"], "status": info["status"],
                         "why": info["why"], "n": st_.get("n", 0), "wr": rnd(st_.get("wr"), 3),
                         "exp": rnd(st_.get("exp"), 3), "pf": rnd(st_.get("pf"), 2)},
            "others": [{"sid": y["s"]["sid"], "short": y["s"]["short"], "name": y["s"]["name"], "score": y["final"],
                        "block": y["block"]} for y in sigs if y["t"] == t and y is not x],
        }
        case = write_case(t, a, s1[t], s, pos, c, regime, conv, sm, lc)
        rec["thesis"] = case["thesis"]
        if full:
            rec.update(case)
            rec["ind"] = {k: rnd(a[k], 5) for k in ("rsi", "adx", "atr_pct", "vr", "dist21", "ext21_atr",
                                                     "bw_pct", "vwap_dist", "chg_1h", "chg_4h", "chg_24h",
                                                     "dist_hi24")}
            rec["ind"].update(hi24=sig6(a["hi24"]), lo24=sig6(a["lo24"]), e9=sig6(a["e9"]), e21=sig6(a["e21"]),
                              e50=sig6(a["e50"]), vwap=sig6(a["vwap"]), atr=sig6(a["atr"]),
                              htf=(a.get("htf") or {}).get("trend"))
            rec["pos"] = {k: (rnd(v, 4) if isinstance(v, float) else v) for k, v in pos.items()} if pos else None
            rec["smart"] = sm
            rec["chart"] = a["chart"]
        return rec

    picks = [record(i + 1, x) for i, x in enumerate(pick_sigs)]
    watch = [record(CFG["top_n"] + i + 1, x, full=False) for i, x in enumerate(watch_sigs)]

    # 4. paper-trade this scan's signals (every strategy, published or not)
    rank_of = {(x["t"], x["s"]["sid"]): i + 1 for i, x in enumerate(pick_sigs)}
    added = journal_add(J, [new_trade(x["t"], x["s"], A[x["t"]], A[x["t"]]["_t"], x["f"], x["conv"]["score"],
                                      x["final"], rank_of.get((x["t"], x["s"]["sid"])), x["block"]) for x in sigs])
    J["last_picks"] = [x["t"] for x in pick_sigs]
    J["scans"] = J.get("scans", 0) + 1
    J["updated"] = scan_t
    J["version"] = 1
    if smart:
        J["smart_prev"] = {c: [a["long_usd"], a["short_usd"]] for c, a in smc.items()}
    journal = journal_summary(J, L, scan_t, sig_now)
    log(f"journal: {added} new paper trades, {moved} closed this scan, {len(J['open'])} open, "
        f"{len(J['closed'])} closed in total")

    # smart-money board: where the top Hyperliquid traders have the most money
    board = []
    for c, a in sorted(smc.items(), key=lambda kv: -(kv[1]["long_usd"] + kv[1]["short_usd"]))[:15]:
        m = s1.get(c)
        board.append({"coin": c, "long_n": a["long_n"], "short_n": a["short_n"], "long_usd": a["long_usd"],
                      "short_usd": a["short_usd"], "share": rnd(a["share"], 3), "d_net": a.get("d_net"),
                      "r24": rnd(m["r24"], 4) if m else None, "rank": (ranked.index(c) + 1) if c in s1 else None})

    # full table (every charted coin)
    flag = {p["coin"]: f"P{p['rank']}" for p in picks}
    flag.update({w["coin"]: "W" for w in watch})
    table = []
    for i, t in enumerate(ranked):
        m = s1[t]
        sp = m["spark"]
        lo_, hi_ = min(sp), max(sp)
        spark = [round((v - lo_) / (hi_ - lo_) * 99) if hi_ > lo_ else 50 for v in sp]
        a = A.get(t)
        cs = best[t]["final"] if t in best else None
        setups = " ".join(sorted({s["base"] for s in a["signals"]}, key=SID_ORDER.index)) \
            if a and a.get("signals") else None
        c = crypto[t]
        sm = smc.get(t)
        table.append([i + 1, t, round(m["score"], 1), rnd(m["r1"] * 100, 2), rnd(m["r3"] * 100, 2),
                      rnd(m["r6"] * 100, 2), rnd(m["r24"] * 100, 2), round(m["pos"] * 100), round(m["rsi"]),
                      round(m["vr"], 2), round(m["turn"]), round(c["best_vol"]) if c.get("best_vol") else 0, spark,
                      flag.get(t, "D" if a else ""), cs, setups,
                      m["src"], " ".join(DEX_CODE[d] for d in DEXES if d in c["venues"]),
                      rnd(sm["share"], 3) if sm else None])

    out = {
        "version": VERSION, "generated_at": iso(scan_t), "scan_t": scan_t, "next_scan_t": next_scan_ts(scan_t),
        "duration_s": round(time.time() - t0, 1), "regime": regime, "picks": picks, "watch": watch,
        "table": table, "journal": journal, "smart_board": board,
        "strategies": {sid: {"name": v["name"], "short": v["short"], "kind": v["kind"], "base": v["base"],
                             "stage": v["stage"]} for sid, v in SPECS.items()},
        "smart": {k: smart[k] for k in ("traders", "read", "positions", "min_account")} if smart else None,
        "coverage": {"coins": len(coins), "crypto": len(crypto), "scanned": len(s1), "nodata": sorted(nodata),
                     "tradfi": tradfi, "deep": len(A), "setups": len({x["t"] for x in sigs}), "signals": len(sigs),
                     "positioning": sum(1 for v in POS.values() if v), "sources": src_count,
                     "dexes": {d: dict(dex_status.get(d, {}), name=DEX_NAME[d], code=DEX_CODE[d]) for d in DEXES},
                     "dex_ok": dex_ok},
        "settings": {"min_dex_vol": CFG["min_dex_vol"], "valid_hours": CFG["valid_hours"],
                     "track_hours": CFG["track_hours"], "every_min": CFG["schedule_every_min"],
                     "min_pick_score": CFG["min_pick_score"], "top_n": CFG["top_n"]},
        "errors": ERRORS[:60],
    }
    n_alerts = send_alerts(out, pages_url)
    out["alerts"] = {"on": alerts_on(), "sent": n_alerts}
    out["errors"] = ERRORS[:60]
    data_dir = os.path.join(out_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "latest.json"), "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    with open(os.path.join(data_dir, "journal.json"), "w") as fh:
        json.dump(J, fh, separators=(",", ":"))
    with open(os.path.join(data_dir, "journal.csv"), "w", newline="") as fh:
        fh.write(journal_csv(J))
    src = index_src or os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if os.path.exists(src):
        shutil.copyfile(src, os.path.join(out_dir, "index.html"))
    log(f"done in {out['duration_s']}s: {len(picks)} picks, regime {regime['label']}, {len(ERRORS)} notes"
        + (f", {n_alerts} alert message(s) sent" if n_alerts else ""))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Perp DEX 15m scanner with a strategy journal")
    ap.add_argument("--out", default="site", help="output folder for the static site")
    ap.add_argument("--pages-url", default=os.environ.get("PAGES_URL"),
                    help="public URL of the dashboard; the journal is carried between runs through it")
    ap.add_argument("--journal", default=None, help="local journal.json to use instead of the published one")
    ap.add_argument("--reset", action="store_true", help="start a new journal (backtests the last days again)")
    ap.add_argument("--replay-days", type=int, default=None,
                    help=f"days backtested for a new journal and for strategy discovery "
                         f"(default {CFG['bt_days']}, 0 = no backtest and no discovery)")
    args = ap.parse_args(argv)
    run(args.out, pages_url=args.pages_url, journal_path=args.journal, reset=args.reset,
        replay_days=args.replay_days)


if __name__ == "__main__":
    main()
