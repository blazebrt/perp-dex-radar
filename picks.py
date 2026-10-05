"""Coin picks: every coin on your DEXs scored 0-100 for a swing trade (days to weeks) and a day trade
(hours), long or short, with every check in plain words, a trade plan and a paper record.

Runs after scanner.py and quant.py in every scan (see .github/workflows/scan.yml) and writes:
    site/index.html              the picks page (picks.html); the 15-minute radar moves to site/radar.html
    site/data/picks.json         the scores, the reasons, the trade plans and the paper record
    site/data/picks_journal.json the paper trades (read back from the published site next run)
    site/data/picks_research.json the test results behind the scores (copied from picks_research.json)

Swing score (tested on three years of daily candles of the coins that trade on your DEXs):
    Long  "Coiled bottom"     near the 90-day low, momentum back (daily RSI above 45), volatility squeezed,
                              a tight 90-day range, calm daily moves, plus four smaller checks
    Short "Downtrend bounce"  below the 50-day EMA, down over 30 days, bounced (RSI above 50), not near the
                              90-day low, plus five smaller checks
    Tested trade: enter at the next daily open, stop 2 daily ATRs away (5% to 25%), then a trailing stop
    3 ATRs behind the best price, out after 30 days at the latest. Scores of 80+ are "ready" setups.
Extra checks move the score by up to 10 points: Hyperliquid top traders (read by scanner.py), funding,
open interest and top-trader positioning (Gate.io), and fundamentals (CoinGecko: market cap, unlocked
supply, distance from the all-time high, trading interest), plus liquidity on your DEXs.
Day-trade score: ten hourly and daily checks including the swing score. In a one-year test of hourly
trades no selection rule beat the trading costs; the page says so next to the list.

Standard library only. Educational tool, not financial advice.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time

import quant as q
import scanner as sc

VERSION = "1.2.0"
ENGINE = 1
H = 3600
B4 = 4 * H
DAY = 24 * H

CFG = {
    "min_dex_vol": 1_000_000,   # 24h volume on one of your DEXs (scanner.CFG["trade_dexes"])
    "min_ref_vol": 5_000_000,   # volume of the last full day on the reference exchange (the tested universe)
    "min_days": 90,             # daily candles needed for the swing checks
    "bars_4h": 1000,            # 4-hour candles per coin (about 166 days)
    "bars_1h": 220,             # hourly candles per coin for the day-trade checks
    "day_coins": 50,            # coins that get the hourly checks (most liquid + best swing scores)
    "stats_coins": 40,          # coins that get the Gate.io open-interest and liquidation checks
    "cg_every_h": 6,            # CoinGecko fundamentals are refreshed this often (hours)
    "cg_pages": 4,              # CoinGecko market pages of 250 coins
    "top_n": 10,                # picks per list
    "watch": 60, "ready": 80, "strong": 90,
    "extra_max": 10,            # extra checks move the score by at most this many points
    "account": 500.0,           # default account on the page (each visitor can change it)
    "risk": 0.02,               # default risk per trade on the page
    "swing": {"stop_k": 2.0, "trail_k": 3.0, "min_stop": 0.05, "max_stop": 0.25, "days": 30},
    "day": {"stop_k": 1.5, "trail_k": 2.5, "min_stop": 0.015, "max_stop": 0.06, "hours": 24},
    "paper_swing_min": 80,      # swing picks with this score or more are paper traded
    "paper_day_min": 85,        # day picks with this score or more are paper traded
    "paper_day_max_new": 3,     # new day paper trades per closed hour at most
    "keep_closed": 600,
    "gap_stocktwits": 1.2,      # seconds between Stocktwits requests (about 200 an hour are allowed)
    "gap_coingecko": 3.0,       # seconds between CoinGecko requests without a key (2.2 with one)
    "notes_top": 5,             # AI desk notes for this many top swing picks (needs the GEMINI_API_KEY secret)
    "notes_every_h": 12,        # a note is rewritten after this long, or when its pick's side or score changes
    "notes_per_run": 3,         # new notes per scan at most: the free tier allows few requests a day
    "news_ai_every_h": 3,       # headline tone by Gemini at most this often (one batched request)
    "gemini_gap": 7.0,          # seconds between Gemini requests
}

LONG_W = {"near_low": 25, "rsi": 20, "squeeze": 15, "tight": 10, "calm": 10, "mom30": 5, "higher_low": 5,
          "btc_up": 5, "volume": 5}
SHORT_W = {"below_ema": 15, "down30": 15, "bounce": 25, "off_low": 20, "lower_high": 5, "down4h": 5,
           "weaker_btc": 5, "down_volume": 5, "below_vwap": 5}
DAY_W = {"swing": 25, "trend1d": 10, "trend4h": 10, "trend1h": 10, "near_edge": 10, "no_chase": 10, "calm": 10,
         "trend30": 5, "funding": 5, "volume": 5}
SETUP = {"long": "Coiled bottom", "short": "Downtrend bounce"}


def log(msg):
    sc.log("picks: " + msg)


# --------------------------------------------------------------------------- indicators (research-equivalent)
def sma_last(xs, n, minp=None):
    w = [x for x in xs[-n:] if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if len(w) < (minp or n):
        return None
    return sum(w) / len(w)


def rsi(c, n=14):
    up, dn = [None], [None]
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        up.append(d if d > 0 else 0.0)
        dn.append(-d if d < 0 else 0.0)
    au, ad = q.wilder(up, n), q.wilder(dn, n)
    out = []
    for a, b in zip(au, ad):
        if a is None or b is None:
            out.append(None)
        elif b == 0:
            out.append(100.0 if a > 0 else None)
        else:
            out.append(100 - 100 / (1 + a / b))
    return out


def bb_width(c, n=20, k=2.0):
    """4 standard deviations (sample) over the mean of the last n closes, for every index."""
    out = []
    for i in range(len(c)):
        if i < n - 1:
            out.append(None)
            continue
        w = c[i - n + 1: i + 1]
        m = sum(w) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / (n - 1))
        out.append(2 * k * sd / m if m else None)
    return out


def pct_rank_last(xs, n, minp):
    """pandas rolling(n, min_periods=minp).rank(pct=True) at the last index (average rank of ties)."""
    w = [x for x in xs[-n:] if x is not None]
    if len(w) < minp or xs[-1] is None:
        return None
    x = xs[-1]
    below = sum(1 for v in w if v < x)
    same = sum(1 for v in w if v == x)
    return (below + (same + 1) / 2) / len(w)


def fmt_pct(x, d=0):
    return f"{x * 100:+.{d}f}%"


# --------------------------------------------------------------------------- swing checks (daily)
def swing_values(cd, c4, btc):
    """Raw values of the swing checks at the last complete day. cd: daily bars (oldest first), c4: closed
    4h bars, btc: {"mom30", "up"} for the same day. None when there is not enough history."""
    n = len(cd)
    if n < CFG["min_days"]:
        return None
    c = [x["c"] for x in cd]
    h = [x["h"] for x in cd]
    lo = [x["l"] for x in cd]
    v = [x["qv"] for x in cd]
    last = c[-1]
    lo90, hi90 = min(lo[-90:]), max(h[-90:])
    r = rsi(c, 14)[-1]
    sq = pct_rank_last(bb_width(c, 20), 90, 45)
    a = q.atr(h, lo, c, 14)[-1]
    e50 = q.ema(c, 50)[-1]
    if not (lo90 and hi90 and last and r is not None and sq is not None and a):
        return None
    dr = [None] + [c[i] / c[i - 1] - 1 for i in range(1, n)]
    upv = [v[i] if (dr[i] is not None and dr[i] > 0) else 0.0 for i in range(n)]
    dnv = [v[i] if (dr[i] is not None and dr[i] < 0) else 0.0 for i in range(n)]
    up_s, dn_s = sma_last(upv, 14, 10), sma_last(dnv, 14, 10)
    vw_den = sum(v[-30:])
    vwap = sum(c[i] * v[i] for i in range(n - 30, n)) / vw_den if vw_den else None
    v7, v30 = sma_last(v, 7), sma_last(v, 30)
    # 4-hour trend at the close of the same day (EMA 20 vs EMA 100 on 4h closes)
    end = cd[-1]["t"] + DAY - B4
    k4 = next((i for i in range(len(c4) - 1, -1, -1) if c4[i]["t"] == end), None)
    t4 = None
    if k4 is not None:
        cc = [x["c"] for x in c4[: k4 + 1]]
        e20, e100 = q.ema(cc, 20)[-1], q.ema(cc, 100)[-1]
        t4 = (e20 / e100 - 1) if (e20 and e100) else None
    mom30 = last / c[-31] - 1 if n > 30 and c[-31] else None
    return {
        "t": cd[-1]["t"], "price": last, "up90": last / lo90 - 1, "dd90": last / hi90 - 1, "lo90": lo90, "hi90": hi90,
        "rsi": r, "squeeze": sq, "atr": a, "atrp": a / last, "mom30": mom30,
        "mom7": last / c[-8] - 1 if c[-8] else None,
        "higher_low": min(lo[-10:]) / min(lo[-20:-10]) - 1 if min(lo[-20:-10]) else None,
        "lower_high": max(h[-10:]) < max(h[-20:-10]),
        "volup": v7 / v30 if (v7 is not None and v30) else None,
        "updown": up_s / dn_s if (up_s is not None and dn_s) else None,
        "vwap30": last / vwap - 1 if vwap else None,
        "trend50": last / e50 - 1 if e50 else None, "ema50": e50,
        "trend4h": t4,
        "rs30": (mom30 - btc["mom30"]) if (mom30 is not None and btc.get("mom30") is not None) else None,
        "btc_up": bool(btc.get("up")),
        "vol_day": v[-1], "hi30": max(h[-30:]), "lo30": min(lo[-30:]),
    }


def _ok(cond, half=False):
    return 1.0 if cond else (0.5 if half else 0.0)


def long_checks(x):
    """{key: credit 0..1} for the long score (research fx_final.long_checks)."""
    u, r, s = x["up90"], x["rsi"], x["squeeze"]
    return {
        "near_low": 1.0 if u <= 0.30 else 0.4 if u <= 0.45 else 0.0,
        "rsi": 1.0 if r > 45 else 0.4 if r > 40 else 0.0,
        "squeeze": 1.0 if s <= 0.2 else 0.4 if s <= 0.35 else 0.0,
        "tight": _ok(x["dd90"] >= -0.30),
        "calm": 1.0 if x["atrp"] <= 0.05 else 0.5 if x["atrp"] <= 0.065 else 0.0,
        "mom30": _ok(x["mom30"] is not None and x["mom30"] > 0),
        "higher_low": _ok(x["higher_low"] is not None and x["higher_low"] > 0),
        "btc_up": _ok(x["btc_up"]),
        "volume": _ok(x["volup"] is not None and x["volup"] >= 1.2),
    }


def short_checks(x):
    r = x["rsi"]
    return {
        "below_ema": _ok(x["trend50"] is not None and x["trend50"] < 0),
        "down30": _ok(x["mom30"] is not None and x["mom30"] < 0),
        "bounce": 1.0 if r > 50 else 0.4 if r > 45 else 0.0,
        "off_low": _ok(x["up90"] > 0.25),
        "lower_high": _ok(x["lower_high"]),
        "down4h": _ok(x["trend4h"] is not None and x["trend4h"] < 0),
        "weaker_btc": _ok(x["rs30"] is not None and x["rs30"] < 0),
        "down_volume": _ok(x["updown"] is not None and x["updown"] < 1),
        "below_vwap": _ok(x["vwap30"] is not None and x["vwap30"] < 0),
    }


def points(credits, weights):
    return sum(weights[k] * credits[k] for k in weights)


def swing_explain(side, x, cr):
    """Plain-language lines for the core swing checks: (key, title, detail)."""
    if side == "long":
        return [
            ("near_low", "Near its 90-day low",
             f"{x['up90'] * 100:.0f}% above the 90-day low of {sig(x['lo90'])} (wanted: within 30%)"),
            ("rsi", "Momentum is back", f"Daily RSI {x['rsi']:.0f} (wanted: above 45)"),
            ("squeeze", "Volatility squeezed",
             f"Bollinger width in the lowest {max(1, round(x['squeeze'] * 100))}% of 90 days (wanted: lowest 20%)"),
            ("tight", "Tight 90-day range", f"{-x['dd90'] * 100:.0f}% below the 90-day high (wanted: within 30%)"),
            ("calm", "Calm daily moves", f"Moves about {x['atrp'] * 100:.1f}% a day (wanted: 5% or less)"),
            ("mom30", "Up over 30 days", f"30-day change {fmt_pct(x['mom30'] or 0)}"),
            ("higher_low", "Higher low", "The last 10-day low is above the previous one" if cr["higher_low"]
             else "The last 10-day low is below the previous one"),
            ("btc_up", "Bitcoin in an uptrend", "BTC is above its 50-day EMA" if cr["btc_up"]
             else "BTC is below its 50-day EMA"),
            ("volume", "Volume waking up",
             f"7-day volume {x['volup']:.1f}x the 30-day average (wanted: 1.2x)" if x["volup"] else "No volume data"),
        ]
    return [
        ("below_ema", "Below its 50-day EMA", f"{fmt_pct(x['trend50'] or 0, 1)} vs the 50-day EMA ({sig(x['ema50'])})"),
        ("down30", "Down over 30 days", f"30-day change {fmt_pct(x['mom30'] or 0)}"),
        ("bounce", "Bounced into resistance", f"Daily RSI {x['rsi']:.0f} (wanted: above 50 inside a downtrend)"),
        ("off_low", "Not sitting on its low",
         f"{x['up90'] * 100:.0f}% above the 90-day low (wanted: more than 25%, room to fall)"),
        ("lower_high", "Lower high", "The last 10-day high is below the previous one" if cr["lower_high"]
         else "The last 10-day high is above the previous one"),
        ("down4h", "4-hour trend down", "4h EMA 20 below EMA 100" if cr["down4h"] else "4h EMA 20 above EMA 100"),
        ("weaker_btc", "Weaker than Bitcoin", f"30 days: {fmt_pct(x['rs30'] or 0)} vs BTC"),
        ("down_volume", "Selling volume heavier",
         f"Up-day volume {x['updown']:.2f}x down-day volume (14 days)" if x["updown"] else "No volume data"),
        ("below_vwap", "Below the 30-day VWAP", f"{fmt_pct(x['vwap30'] or 0, 1)} vs the 30-day VWAP"),
    ]


def sig(x, d=6):
    if x is None:
        return "-"
    return f"{x:.{d}g}"


# --------------------------------------------------------------------------- day-trade checks (hourly)
def day_values(c1, x, fund8h):
    """Hourly values at the last closed hour. c1: closed 1h bars, x: the coin's swing values."""
    if len(c1) < 170:
        return None
    c = [b["c"] for b in c1]
    h = [b["h"] for b in c1]
    lo = [b["l"] for b in c1]
    v = [b["qv"] for b in c1]
    last = c[-1]
    e9, e21 = q.ema(c, 9)[-1], q.ema(c, 21)[-1]
    a = q.atr(h, lo, c, 14)[-1]
    v24, v168 = sma_last(v, 24), sma_last(v, 168)
    hi24, lo24 = max(h[-24:]), min(lo[-24:])
    r1 = rsi(c, 14)[-1]
    # 30-day high / low from the daily bars plus the hours since the last daily close
    hi30 = max([x["hi30"]] + [b["h"] for b in c1 if b["t"] >= x["t"] + DAY])
    lo30 = min([x["lo30"]] + [b["l"] for b in c1 if b["t"] >= x["t"] + DAY])
    return {
        "t": c1[-1]["t"], "price": last, "ema9_21": (e9 / e21 - 1) if (e9 and e21) else None,
        "brk24": last / hi24 - 1, "dist_low24": last / lo24 - 1, "hi24": hi24, "lo24": lo24,
        "r4h": last / c[-5] - 1, "r24h": last / c[-25] - 1, "atr": a, "atrp": a / last if a else None,
        "vol24_7d": v24 / v168 if (v24 is not None and v168) else None, "rsi1h": r1,
        "dd30d": last / hi30 - 1, "up30d": last / lo30 - 1, "trend1d": last / x["ema50"] - 1 if x.get("ema50") else None,
        "trend4h": x.get("trend4h_now"), "funding": fund8h,
    }


def day_checks(side, y, swing_score):
    s = swing_score or 0.0
    if side == "long":
        return {
            "swing": 1.0 if s >= 70 else 0.4 if s >= 50 else 0.0,
            "trend1d": _ok(y["trend1d"] is not None and y["trend1d"] > 0),
            "trend4h": _ok(y["trend4h"] is not None and y["trend4h"] > 0),
            "trend1h": _ok(y["ema9_21"] is not None and y["ema9_21"] > 0),
            "near_edge": _ok(y["brk24"] >= -0.03),
            "no_chase": _ok(y["r4h"] <= 0.02),
            "calm": _ok(y["atrp"] is not None and y["atrp"] <= 0.015),
            "trend30": _ok(y["dd30d"] >= -0.15),
            "funding": _ok(y["funding"] is not None and y["funding"] <= 0.0001),
            "volume": _ok(y["vol24_7d"] is not None and y["vol24_7d"] >= 1.0),
        }
    return {
        "swing": 1.0 if s >= 70 else 0.4 if s >= 50 else 0.0,
        "trend1d": _ok(y["trend1d"] is not None and y["trend1d"] < 0),
        "trend4h": _ok(y["trend4h"] is not None and y["trend4h"] < 0),
        "trend1h": _ok(y["ema9_21"] is not None and y["ema9_21"] < 0),
        "near_edge": _ok(y["dist_low24"] <= 0.03),
        "no_chase": _ok(y["r4h"] >= -0.02),
        "calm": _ok(y["atrp"] is not None and y["atrp"] <= 0.015),
        "trend30": _ok(y["dd30d"] <= -0.25),
        "funding": _ok(y["funding"] is not None and y["funding"] >= 0.0),
        "volume": _ok(y["vol24_7d"] is not None and y["vol24_7d"] >= 1.0),
    }


def day_explain(side, y, cr, swing_score):
    L = side == "long"
    word = "long" if L else "short"
    return [
        ("swing", f"Swing setup for a {word}", f"Swing {word} score {swing_score:.0f} (wanted: 70+)"),
        ("trend1d", "Daily trend " + ("up" if L else "down"),
         f"{fmt_pct(y['trend1d'] or 0, 1)} vs the 50-day EMA"),
        ("trend4h", "4-hour trend " + ("up" if L else "down"),
         "4h EMA 20 " + ("above" if (y["trend4h"] or 0) > 0 else "below") + " EMA 100"),
        ("trend1h", "1-hour trend " + ("up" if L else "down"),
         "1h EMA 9 " + ("above" if (y["ema9_21"] or 0) > 0 else "below") + " EMA 21"),
        ("near_edge", "Near the 24h high" if L else "Near the 24h low",
         (f"{-y['brk24'] * 100:.1f}% below the 24h high" if L else f"{y['dist_low24'] * 100:.1f}% above the 24h low")
         + " (wanted: within 3%)"),
        ("no_chase", "Not chasing a spike",
         f"Last 4 hours {fmt_pct(y['r4h'], 1)} (wanted: " + ("not up more than 2%)" if L else "not down more than 2%)")),
        ("calm", "Calm hourly moves", f"Hourly ATR {(y['atrp'] or 0) * 100:.2f}% (wanted: 1.5% or less)"),
        ("trend30", "Near the 30-day high" if L else "Well below the 30-day high",
         f"{-y['dd30d'] * 100:.0f}% below the 30-day high (wanted: " + ("within 15%)" if L else "more than 25%)")),
        ("funding", "Funding not crowded" if L else "Longs are paying",
         ("Funding " + (f"{y['funding'] * 100:+.4f}% per 8h" if y["funding"] is not None else "unknown"))
         + (" (wanted: 0.01% or less)" if L else " (wanted: zero or positive)")),
        ("volume", "Volume above normal",
         f"24h volume {y['vol24_7d']:.1f}x the 7-day average" if y["vol24_7d"] else "No volume data"),
    ]


# --------------------------------------------------------------------------- extra checks (live only)
def extra_checks(side, coin, sm, gs, fund8h, fdm, liq, supply_growth=None):
    """Smart money, derivatives, fundamentals and liquidity. Each: (key, title, ok, points, detail, group, tested).
    ok: True / False / None (no data or information only). Points are added when ok is True and taken off when
    it is False. 'tested' marks the checks that held up on past data (futures statistics since April 2026,
    CoinGecko and funding over the last year); the others are shown for information or as a small nudge."""
    L = side == "long"
    out = []
    # Hyperliquid top traders (scanner.py reads their open positions): no history to test, a small nudge
    if sm and (sm[2] + sm[3]) >= 50_000:
        ln, sn, lu, su = sm[0], sm[1], sm[2], sm[3]
        net = lu - su
        ok = (net > 0 and lu >= 1.5 * su) if L else (net < 0 and su >= 1.5 * lu)
        bad = (net < 0 and su >= 1.5 * lu) if L else (net > 0 and lu >= 1.5 * su)
        out.append(("smart", "Hyperliquid top traders agree", True if ok else False if bad else None, 2,
                    f"{ln} long ({usd_short(lu)}) vs {sn} short ({usd_short(su)})", "Smart money", False))
    else:
        out.append(("smart", "Hyperliquid top traders agree", None, 2, "No big positions from the top traders",
                    "Smart money", False))
    # Gate.io open interest over 7 days: leverage piling in while the price rises made longs worse
    if gs and gs.get("oi7") is not None and gs.get("px7") is not None:
        pile = gs["oi7"] >= 0.05 and gs["px7"] > 0
        d = f"Open interest {fmt_pct(gs['oi7'])} and price {fmt_pct(gs['px7'])} in 7 days"
        if L:
            out.append(("lev", "No leverage pile-up", not pile, 2, d + (" (leverage piling into the rise)" if pile else ""),
                        "Smart money", True))
        else:
            out.append(("lev", "Leverage piling into longs", True if pile else None, 0, d + " (information)",
                        "Smart money", False))
    else:
        out.append(("lev", "No leverage pile-up" if L else "Leverage piling into longs", None, 2 if L else 0,
                    "No open-interest data", "Smart money", L))
    # liquidations over 3 days: after longs were flushed out, longs did better
    if gs and gs.get("liq3") is not None:
        flushed = gs["liq3"] >= 0.6
        d = f"Longs were {gs['liq3'] * 100:.0f}% of liquidations in 3 days"
        out.append(("flush", "Longs already flushed out" if L else "Longs flushed out (information)",
                    (True if flushed else None) if L else None, 1 if L else 0, d, "Smart money", L))
    else:
        out.append(("flush", "Longs already flushed out" if L else "Longs flushed out (information)", None,
                    1 if L else 0, "No liquidation data", "Smart money", L))
    if gs and gs.get("top7") is not None:
        out.append(("top", "Top traders' long/short ratio (information)", None, 0,
                    f"Gate.io top traders {gs['top0']:.2f} -> {gs['top1']:.2f} in 7 days", "Smart money", False))
    # funding on your DEXs: very high funding made shorts worse (hype squeezes); for longs it was mixed
    if fund8h is not None:
        d = f"{fund8h * 100:+.4f}% per 8 hours on your DEXs"
        if L:
            out.append(("funding", "Funding (information)", None, 0, d, "Smart money", False))
        else:
            out.append(("funding", "No funding frenzy", True if fund8h <= 0.0001 else False if fund8h >= 0.0003 else None,
                        2, d + " (shorts did better when funding was 0.01% or less)", "Smart money", True))
    else:
        out.append(("funding", "Funding (information)" if L else "No funding frenzy", None, 0 if L else 2,
                    "No funding data", "Smart money", not L))
    # supply unlocks: coins whose supply grew 2%+ in 30 days were worse longs and better shorts
    if supply_growth is not None:
        g = supply_growth
        d = f"Circulating supply {fmt_pct(g, 1)} in 30 days"
        if L:
            out.append(("supply", "No unlock pressure", True if g < 0.005 else False if g >= 0.02 else None, 2, d,
                        "Fundamentals", True))
        else:
            out.append(("supply", "Unlocks adding supply", True if g >= 0.02 else None, 2, d, "Fundamentals", True))
    else:
        share = None
        if fdm:
            circ, tot, mc, fdv = fdm.get("circ"), fdm.get("total"), fdm.get("mc"), fdm.get("fdv")
            share = (circ / tot) if (circ and tot) else ((mc / fdv) if (mc and fdv) else None)
        out.append(("supply", "No unlock pressure" if L else "Unlocks adding supply", None, 2,
                    (f"{share * 100:.0f}% of the supply is circulating; 30-day supply growth not known yet" if share
                     else "Supply data unknown"), "Fundamentals", True))
    # fundamentals from CoinGecko
    mc = (fdm or {}).get("mc")
    vol = (fdm or {}).get("vol")
    if mc and vol:
        t = vol / mc
        d = f"24h volume is {t * 100:.0f}% of the market cap"
        if L:
            out.append(("turnover", "Not overheated", True if t <= 0.10 else False if t > 0.25 else None, 1,
                        d + " (longs did better at 10% or less)", "Fundamentals", True))
        else:
            out.append(("turnover", "Trading interest (information)", None, 0, d, "Fundamentals", False))
    else:
        out.append(("turnover", "Not overheated" if L else "Trading interest (information)", None, 1 if L else 0,
                    "Volume / market cap unknown", "Fundamentals", L))
    rank = (fdm or {}).get("rank")
    out.append(("mcap", "Market cap (information)", None, 0,
                (f"${mc / 1e6:,.0f}M" + (f" (#{rank})" if rank else "")) if mc else "Market cap unknown",
                "Fundamentals", False))
    ath_ch = (fdm or {}).get("ath_ch")
    if ath_ch is not None:
        dd = -ath_ch / 100.0
        if L:
            out.append(("ath", "Distance from the all-time high (information)", None, 0,
                        f"{dd * 100:.0f}% below the all-time high", "Fundamentals", False))
        else:
            out.append(("ath", "Far below its all-time high (weak coin)", True if dd >= 0.6 else None, 1,
                        f"{dd * 100:.0f}% below the all-time high", "Fundamentals", True))
    else:
        out.append(("ath", "Distance from the all-time high" if L else "Far below its all-time high (weak coin)", None,
                    0 if L else 1, "All-time high unknown", "Fundamentals", not L))
    out.append(("liq", "Liquid on your DEXs", True if liq >= 5e6 else None, 1,
                f"${liq / 1e6:,.1f}M traded in 24h on your DEXs (lower costs at $5M+)", "Liquidity", False))
    return out


def rsi_check(side, r):
    """Hourly RSI not stretched in the trade's direction (an extra check for day trades)."""
    if r is None:
        return ("rsi1h", "1-hour RSI not stretched", None, 1, "No hourly RSI", "Timing", False)
    if side == "long":
        ok, bad = 40 <= r <= 70, r > 80
    else:
        ok, bad = 30 <= r <= 60, r < 20
    return ("rsi1h", "1-hour RSI not stretched", True if ok else False if bad else None, 1,
            f"1h RSI {r:.0f} (wanted: " + ("40 to 70)" if side == "long" else "30 to 60)"), "Timing", False)


def extra_points(ex):
    s = 0.0
    for _, _, ok, p, _, _, _ in ex:
        if ok is True:
            s += p
        elif ok is False:
            s -= p
    return max(-CFG["extra_max"], min(CFG["extra_max"], s))


def label_of(score, kind="swing"):
    if score >= CFG["strong"]:
        return "Strong" if kind == "swing" else "Best conditions"
    if score >= CFG["ready"]:
        return "Ready" if kind == "swing" else "Good conditions"
    if score >= CFG["watch"]:
        return "Setting up"
    return "Weak"


# --------------------------------------------------------------------------- live data
# Optional CoinGecko key, set as a GitHub secret (Settings > Secrets and variables > Actions) and passed in by
# scan.yml; without it the free public CoinGecko API is used (slower, sometimes rate limited).
CG_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
CG_PRO = os.environ.get("COINGECKO_PLAN", "").strip().lower() == "pro"
CG_BASE = "https://pro-api.coingecko.com/api/v3" if (CG_KEY and CG_PRO) else "https://api.coingecko.com/api/v3"
CG_MARKETS = CG_BASE + "/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}"
# free social sources (no key): Stocktwits posts with bullish / bearish tags, ApeWisdom mentions on Reddit and
# 4chan, crypto news headlines, the Fear & Greed index
ST_STREAM = "https://api.stocktwits.com/api/2/streams/symbol/{sym}.X.json"
APE = "https://apewisdom.io/api/v1.0/filter/all-crypto/page/{page}"
FNG = "https://api.alternative.me/fng/?limit=1"
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_NOTES_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.8-flash"
GEMINI_FAST_MODEL = os.environ.get("GEMINI_FAST_MODEL", "").strip() or "gemini-3.5-flash-lite"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_STATE = {"calls": 0, "errors": [], "stopped": False}
NEWS_FEEDS = (("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
              ("Cointelegraph", "https://cointelegraph.com/rss"),
              ("The Block", "https://www.theblock.co/rss.xml"),
              ("CryptoSlate", "https://cryptoslate.com/feed/"),
              ("Bitcoinist", "https://bitcoinist.com/feed/"))


def cg_url(url):
    """Add the CoinGecko key (demo or pro) to a request URL when one is set."""
    if not CG_KEY:
        return url
    return url + ("&" if "?" in url else "?") + ("x_cg_pro_api_key=" if CG_PRO else "x_cg_demo_api_key=") + CG_KEY


def cg_get(url, timeout=40):
    sc.throttle_key("coingecko", min(2.2, CFG["gap_coingecko"]) if CG_KEY else CFG["gap_coingecko"])
    return sc.FETCH(cg_url(url), timeout=timeout)


def coingecko(coins, cached, now):
    """Fundamentals per coin from CoinGecko's market list (refreshed every few hours, else the cached copy)."""
    if cached and now - cached.get("time", 0) < CFG["cg_every_h"] * H and cached.get("coins"):
        return cached, "cached"
    rows = []
    for page in range(1, CFG["cg_pages"] + 1):
        try:
            d = cg_get(CG_MARKETS.format(page=page))
        except Exception as e:  # noqa: BLE001
            sc.note_error(f"CoinGecko page {page}: {type(e).__name__} {getattr(e, 'code', '')}")
            break
        if not isinstance(d, list) or not d:
            break
        rows.extend(x for x in d if isinstance(x, dict))
    if not rows:
        return cached, ("stale" if cached else "none")
    by_sym = {}
    for m in rows:
        by_sym.setdefault(str(m.get("symbol", "")).upper(), []).append(m)
    out = {}
    for c in coins:
        t, px = c["t"], c.get("ref_price")
        good = []
        for m in by_sym.get(t.upper(), []):
            p = sc.fnum(m.get("current_price"))
            if px and p and abs(p / px - 1) > 0.25:
                continue
            good.append(m)
        if not good:
            continue
        m = max(good, key=lambda m: sc.fnum(m.get("market_cap"), 0.0) or 0.0)
        out[t] = {"id": m.get("id"), "name": m.get("name"), "mc": sc.fnum(m.get("market_cap")),
                  "fdv": sc.fnum(m.get("fully_diluted_valuation")),
                  "circ": sc.fnum(m.get("circulating_supply")), "total": sc.fnum(m.get("total_supply")),
                  "ath": sc.fnum(m.get("ath")), "ath_ch": sc.fnum(m.get("ath_change_percentage")),
                  "vol": sc.fnum(m.get("total_volume")), "rank": m.get("market_cap_rank")}
    return {"time": now, "coins": out}, "fresh"


def cg_trending(cached, now):
    """Coins people search for most on CoinGecko right now (top 15), refreshed every hour."""
    if cached and now - cached.get("time", 0) < H:
        return cached
    try:
        d = cg_get(CG_BASE + "/search/trending")
    except Exception as e:  # noqa: BLE001
        sc.note_error(f"CoinGecko trending: {type(e).__name__} {getattr(e, 'code', '')}")
        return cached
    out = {}
    for i, x in enumerate((d or {}).get("coins") or []):
        it = (x or {}).get("item") or {}
        sym = str(it.get("symbol", "")).upper()
        if sym and sym not in out:
            out[sym] = {"rank": i + 1, "id": it.get("id")}
    return {"time": now, "coins": out}


def cg_votes(ids, cached, now, budget):
    """CoinGecko community sentiment (share of bullish votes) per coin id, kept for a day; at most `budget`
    new requests per run so the free API is not overused."""
    C = dict((cached or {}).get("coins") or {})
    todo = [i for i in ids if i and (i not in C or now - C[i].get("t", 0) > DAY)][:budget]
    for cid in todo:
        try:
            d = cg_get(f"{CG_BASE}/coins/{cid}?localization=false&tickers=false&market_data=false"
                       "&community_data=true&developer_data=false&sparkline=false")
        except Exception as e:  # noqa: BLE001
            sc.note_error(f"CoinGecko coin {cid}: {type(e).__name__} {getattr(e, 'code', '')}")
            if getattr(e, "code", None) == 429:
                break
            continue
        up = sc.fnum((d or {}).get("sentiment_votes_up_percentage"))
        C[cid] = {"t": now, "up": up, "watch": (d or {}).get("watchlist_portfolio_users")}
    C = {k: v for k, v in C.items() if now - v.get("t", 0) < 3 * DAY}
    return {"time": now, "coins": C}


def get_text(url, timeout=30):
    """GET a text page (RSS) with the scanner's user agent; None on failure."""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": sc.UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        sc.note_error(f"news feed {url.split('/')[2]}: {type(e).__name__} {getattr(e, 'code', '')}")
        return None


def _iso_ts(x):
    try:
        import datetime as _dt
        return int(_dt.datetime.strptime(x[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_dt.timezone.utc).timestamp())
    except Exception:  # noqa: BLE001
        return None


def stocktwits_parse(d, sym, now):
    """Bullish / bearish tags, post rate and watchers from a Stocktwits symbol stream (its 30 newest posts)."""
    msgs = [m for m in ((d or {}).get("messages") or []) if isinstance(m, dict)]
    ts = [t for t in (_iso_ts(m.get("created_at") or "") for m in msgs) if t]
    if not msgs or not ts:
        return None
    week = [m for m, t in zip(msgs, ts) if now - t <= 7 * DAY]
    tag = lambda ms, v: sum(1 for m in ms if (((m.get("entities") or {}).get("sentiment") or {}).get("basic") == v))  # noqa: E731
    bull7, bear7 = tag(week, "Bullish"), tag(week, "Bearish")
    bull, bear = tag(msgs, "Bullish"), tag(msgs, "Bearish")
    span = max(now - min(ts), 3600)
    per_day = len(ts) / (span / DAY)
    info = {}
    for m in msgs[:3]:
        for x in m.get("symbols") or []:
            if str(x.get("symbol", "")).upper() == f"{sym}.X":
                info = x
                break
        if info:
            break
    wl = ((d or {}).get("symbol") or {}).get("watchlist_count") or info.get("watchlist_count")
    use_bull, use_bear = (bull7, bear7) if bull7 + bear7 >= 4 else (bull, bear)
    return {"t": now, "posts_day": round(per_day, 2), "posts_24h": sum(1 for t in ts if now - t <= DAY),
            "bull": use_bull, "bear": use_bear,
            "bull_share": round(use_bull / (use_bull + use_bear), 3) if (use_bull + use_bear) >= 4 else None,
            "watchers": wl, "sent_change": sc.fnum(info.get("sentiment_change")),
            "vol_change": sc.fnum(info.get("volume_change")), "week": bull7 + bear7 >= 4}


def stocktwits(syms, cached, now, budget=30):
    """Stocktwits for the given tickers, each refreshed at most once an hour (about 30 requests a run)."""
    C = dict((cached or {}).get("coins") or {})
    todo = [t for t in syms if t not in C or now - C[t].get("t", 0) > H][:budget]
    for t in todo:
        sc.throttle_key("stocktwits", CFG["gap_stocktwits"])
        try:
            d = sc.FETCH(ST_STREAM.format(sym=t), timeout=20)
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "code", None)
            if code in (404, 400):
                C[t] = {"t": now, "none": True}
                continue
            sc.note_error(f"Stocktwits {t}: {type(e).__name__} {code or ''}")
            if code in (403, 429):
                break
            continue
        r = stocktwits_parse(d, t, now)
        C[t] = r or {"t": now, "none": True}
    C = {k: v for k, v in C.items() if now - v.get("t", 0) < 2 * DAY}
    return {"time": now, "coins": C}


def apewisdom(cached, now):
    """Mentions per coin on Reddit and 4chan's crypto boards (ApeWisdom), with the change against 24 hours ago."""
    if cached and now - cached.get("time", 0) < H and cached.get("coins"):
        return cached
    out = {}
    for page in (1, 2):
        try:
            d = sc.FETCH(APE.format(page=page), timeout=20)
        except Exception as e:  # noqa: BLE001
            sc.note_error(f"ApeWisdom: {type(e).__name__} {getattr(e, 'code', '')}")
            break
        for x in (d or {}).get("results") or []:
            sym = str(x.get("ticker", "")).upper().replace(".X", "")
            if sym and sym not in out:
                out[sym] = {"rank": x.get("rank"), "mentions": x.get("mentions"), "prev": x.get("mentions_24h_ago"),
                            "upvotes": x.get("upvotes"), "rank_prev": x.get("rank_24h_ago")}
        if page >= ((d or {}).get("pages") or 1):
            break
    if not out:
        return cached
    return {"time": now, "coins": out}


POS_WORDS = ("surge", "surges", "soar", "soars", "rally", "rallies", "jump", "jumps", "climb", "climbs", "gain", "gains",
             "rise", "rises", "bullish", "record", "breakout", "inflow", "inflows", "approve", "approves", "approval",
             "launch", "launches", "partnership", "partners", "upgrade", "adopt", "adopts", "adoption", "buy", "buys",
             "accumulate", "accumulating", "rebound", "rebounds", "recover", "recovers", "listing", "lists", "etf")
NEG_WORDS = ("plunge", "plunges", "drop", "drops", "fall", "falls", "crash", "crashes", "bearish", "hack", "hacked",
             "exploit", "exploited", "lawsuit", "sues", "sued", "ban", "bans", "outflow", "outflows", "selloff", "sell-off",
             "dump", "dumps", "delist", "delists", "scam", "fraud", "liquidation", "liquidations", "decline", "declines",
             "slide", "slides", "tumble", "tumbles", "sink", "sinks", "warning", "risk", "fear", "unlock", "unlocks")
TICKER_WORDS = {"ONE", "NEAR", "US", "UP", "MET", "LIT", "GAS", "SUN", "ALL", "ANY", "FUN", "KEY", "MAX", "NOT", "CAT",
                "DOG", "ACT", "MOVE", "ME", "AI", "IO", "OM", "GO", "SAFE", "REAL", "TRUMP", "HYPE", "PUMP", "BIO",
                "PEOPLE", "BABY", "GOOD", "BANK", "ICE", "PRIME", "CORE", "ZERO", "OPEN", "EDGE", "ETF", "SEC", "USD",
                "CEO", "API", "NFT", "DEX", "CEX", "TVL", "ATH", "FED", "CPI", "GDP", "BTC", "ETH"}


def news(cached, now):
    """Headlines from the main crypto news sites (RSS), kept for 3 days, refreshed every hour."""
    import email.utils
    import re
    import xml.etree.ElementTree as ET
    if cached and now - cached.get("time", 0) < H:
        return cached
    items = [x for x in ((cached or {}).get("items") or []) if now - x["t"] < 3 * DAY]
    seen = {x["title"] for x in items}
    for src, url in NEWS_FEEDS:
        txt = get_text(url)
        if not txt:
            continue
        try:
            root = ET.fromstring(txt.encode("utf-8", "replace"))
        except ET.ParseError:
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
            try:
                t = int(email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").timestamp())
            except Exception:  # noqa: BLE001
                t = now
            if not title or title in seen or now - t > 3 * DAY:
                continue
            seen.add(title)
            link = (it.findtext("link") or "").strip()
            items.append({"t": t, "src": src, "title": title[:200], "desc": re.sub(r"\s+", " ", desc)[:300],
                          "link": link[:300] if link.startswith("https://") else ""})
    items.sort(key=lambda x: -x["t"])
    return {"time": now, "items": items[:400], "ai_time": (cached or {}).get("ai_time")}


def news_for(t, name, feed):
    """Headlines that mention the coin (by name, or by its ticker in capitals) and their tone (-1..1)."""
    import re
    pats = []
    if name and len(name) >= 4:
        pats.append(re.compile(r"\b" + re.escape(name) + r"\b", re.I))
    if len(t) >= 3 and t not in TICKER_WORDS:
        pats.append(re.compile(r"(?<![A-Za-z0-9$])\$?" + re.escape(t) + r"(?![A-Za-z0-9])"))
    if t == "BTC":
        pats.append(re.compile(r"\bbitcoin\b", re.I))
    if t == "ETH":
        pats.append(re.compile(r"\bethereum|\bether\b", re.I))
    if not pats:
        return None
    hits = []
    for x in (feed or {}).get("items") or []:
        text = x["title"] + " " + x["desc"]
        if any(p.search(text) for p in pats):
            if x.get("ai") is not None:      # rated by Gemini (news_ai)
                tone = x["ai"]
            else:
                words = re.findall(r"[a-z\-]+", x["title"].lower())
                pos = sum(1 for w in words if w in POS_WORDS)
                neg = sum(1 for w in words if w in NEG_WORDS)
                tone = (pos - neg) / (pos + neg) if (pos + neg) else 0.0
            hits.append({"t": x["t"], "src": x["src"], "title": x["title"], "link": x.get("link") or "",
                         "tone": tone, "ai": x.get("ai") is not None})
    if not hits:
        return {"n": 0}
    hits.sort(key=lambda h: -h["t"])
    return {"n": len(hits), "tone": round(sum(h["tone"] for h in hits) / len(hits), 2), "top": hits[:3],
            "ai": sum(1 for h in hits if h["ai"])}


def fear_greed(cached, now):
    if cached and now - cached.get("time", 0) < 3 * H:
        return cached
    try:
        d = sc.FETCH(FNG, timeout=20)
        x = ((d or {}).get("data") or [{}])[0]
        return {"time": now, "value": int(x.get("value")), "label": x.get("value_classification")}
    except Exception as e:  # noqa: BLE001
        sc.note_error(f"Fear & Greed: {type(e).__name__} {getattr(e, 'code', '')}")
        return cached


# --------------------------------------------------------------------------- Gemini (optional, GEMINI_API_KEY secret)
def gemini_call(model, system, prompt, max_tokens=2048, json_out=False, timeout=60):
    """One Gemini request with the GEMINI_API_KEY secret (sent in a header, never in the URL). Returns the text."""
    import urllib.request
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_out:
        body["generationConfig"]["responseMimeType"] = "application/json"
    req = urllib.request.Request(GEMINI_URL.format(model=model), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY,
                                          "User-Agent": sc.UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    c = (d.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in ((c.get("content") or {}).get("parts") or []) if not p.get("thought"))
    if not text.strip():
        raise ValueError(f"empty answer ({c.get('finishReason')})")
    return text


def gemini(kind, system, prompt, **kw):
    """gemini_call within the run's limits: (model, text) or None. Tries the other model when one is not available
    to the key, and stops asking for the rest of the run after a quota, key or access error."""
    import urllib.error
    G = GEMINI_STATE
    if not GEMINI_KEY or G["stopped"]:
        return None
    order = (GEMINI_NOTES_MODEL, GEMINI_FAST_MODEL) if kind == "notes" else (GEMINI_FAST_MODEL, GEMINI_NOTES_MODEL)
    busy = G.setdefault("busy", set())
    for m in [x for x in dict.fromkeys(order) if x not in busy]:
        sc.throttle_key("gemini", CFG["gemini_gap"])
        G["calls"] += 1
        try:
            return m, gemini_call(m, system, prompt, **kw)
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                body = ""
            G["errors"].append(f"{m}: HTTP {e.code}")
            if e.code == 404 or (e.code == 400 and "not found" in body.lower()):
                continue                       # this model is not open to the key: try the other one
            if e.code in (500, 502, 503, 504):
                busy.add(m)                    # overloaded right now: the other model for the rest of this scan
                continue
            if e.code in (401, 403, 429) or "API key" in body or "API_KEY" in body:
                G["stopped"] = True            # quota used up, or the key is wrong: try again next scan
            return None
        except Exception as e:  # noqa: BLE001
            G["errors"].append(f"{m}: {type(e).__name__}")
            return None
    return None


NOTE_SYSTEM = (
    "You are a senior crypto derivatives trader with 30 years of experience. Write a short desk note on one coin pick "
    "for a trader deciding today. Use ONLY the facts in the JSON; never invent prices, news or numbers. The score comes "
    "from rules tested on three years of data, and 'record' is how past picks with this score did after fees. The exits "
    "are fixed by that test: the stop, the trailing stop and the time limit in 'plan'; the R targets are reference "
    "levels only. Plain English, short sentences, no hype, no emojis. Markdown with these sections: '## Bottom line' "
    "(two sentences), '## Why it scores' (3 or 4 bullets: the strongest checks that pass, and what is missing), "
    "'## Risks' (2 or 3 bullets, including any conflict with sentiment, positioning or the market mood), "
    "'## How to trade it' (2 or 3 bullets with the entry, the stop, the trailing stop and the time limit). At most "
    "220 words. End with the line: Not financial advice.")

NEWS_SYSTEM = (
    "You rate crypto news headlines for traders. For each numbered headline give its likely effect on the price of the "
    "coin or coins it is about: -1 clearly bearish, -0.5 somewhat bearish, 0 neutral or unclear, 0.5 somewhat bullish, "
    "1 clearly bullish. Judge only from the headline. Answer with JSON only: a list of objects "
    "{\"i\": <headline number>, \"tone\": <number>}.")


def note_payload(r, research, market):
    """What the desk note may use: the pick's checks, plan, tested record, sentiment and the market mood."""
    band = None
    t = ((research or {}).get("swing") or {}).get(r["side"]) if r["kind"] == "swing" else None
    if t:
        band = next((b for b in t.get("bands", []) if b["lo"] <= r["core"] < b["hi"]), None)
    se = r.get("sentiment") or {}
    plan = r.get("plan") or {}
    return {
        "coin": r["coin"], "trade": "swing trade, days to weeks" if r["kind"] == "swing" else "day trade, hours",
        "side": r["side"], "score": r["score"], "tested_chart_score": r["core"], "live_extra_points": r["extra"],
        "label": r["label"], "setup": r.get("setup"), "price": r["price"], "change_24h": r.get("chg24"),
        "summary": r.get("why"),
        "checks": [{"name": c["name"], "passes": c["ok"], "points": c["pts"], "of": c["max"], "detail": c["detail"]}
                   for c in r.get("checks", [])],
        "extra_checks": [{"name": e["name"], "group": e["group"], "detail": e["detail"],
                          "counts": "for" if e["ok"] is True else "against" if e["ok"] is False else "information"}
                         for e in r.get("extras", [])],
        "plan": {k: plan.get(k) for k in ("entry", "stop", "stop_pct", "trail", "trail_k", "days", "hours", "r1", "r2", "r3")},
        "record": band and {"per_trade_after_fees": band.get("ret"), "winners": band.get("win"), "trades": band.get("n")},
        "sentiment": {"score": se.get("score"), "label": se.get("label"), "parts": se.get("parts"),
                      "headlines": [h["title"] for h in ((se.get("news") or {}).get("top") or [])]},
        "market": {"mood": (market or {}).get("mood"), "fear_greed": (market or {}).get("fng")},
    }


def desk_notes(recs, J, now, research, market):
    """Gemini desk notes for the top swing picks, kept in the journal. A note is rewritten only when its pick is new,
    changes side or moves 5+ points, or after notes_every_h hours; at most notes_per_run new notes a scan."""
    N = J.setdefault("notes", {})
    if GEMINI_KEY:
        made = 0
        for r in recs[:CFG["notes_top"]]:
            old = N.get(r["coin"])
            if old and old.get("side") == r["side"] and abs(old.get("score", 0) - r["score"]) < 5 \
                    and now - old.get("t", 0) < CFG["notes_every_h"] * H:
                continue
            if made >= CFG["notes_per_run"] or GEMINI_STATE["stopped"]:
                break
            res = gemini("notes", NOTE_SYSTEM, "Write the desk note for this pick.\n\n" +
                         json.dumps(note_payload(r, research, market), default=str), max_tokens=2048)
            if res:
                N[r["coin"]] = {"t": now, "side": r["side"], "score": r["score"], "model": res[0],
                                "text": res[1].strip()[:3000]}
                made += 1
    top = {r["coin"] for r in recs[:CFG["notes_top"] * 2]}
    for c in list(N):
        if c not in top and now - N[c].get("t", 0) > DAY:
            N.pop(c)
    return N


def news_ai(feed, now):
    """Gemini's tone for headlines that have none yet: one batched request at most every news_ai_every_h hours.
    Headlines it does not rate keep the word-list tone."""
    if not GEMINI_KEY or not feed or GEMINI_STATE["stopped"]:
        return feed
    if now - (feed.get("ai_time") or 0) < CFG["news_ai_every_h"] * H:
        return feed
    todo = [x for x in feed.get("items") or [] if x.get("ai") is None][:60]
    if not todo:
        return feed
    feed["ai_time"] = now
    res = gemini("fast", NEWS_SYSTEM, "Headlines:\n" + "\n".join(f"{i}. {x['title']}" for i, x in enumerate(todo)),
                 max_tokens=4096, json_out=True)
    if not res:
        return feed
    try:
        rows = json.loads(res[1].strip().removeprefix("```json").removesuffix("```"))
    except ValueError:
        GEMINI_STATE["errors"].append("headline ratings: not JSON")
        return feed
    for row in rows if isinstance(rows, list) else []:
        try:
            i, tone = int(row["i"]), float(row["tone"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= i < len(todo):
            todo[i]["ai"] = max(-1.0, min(1.0, tone))
    return feed


SENT_W = {"st": 35, "whales": 25, "votes": 20, "news": 20}
SENT_NAMES = {"st": "Stocktwits", "whales": "Hyperliquid top traders", "votes": "CoinGecko votes", "news": "News tone"}


def sentiment_of(t, fdm, trend, votes, st, ape, feed, sm):
    """The free sentiment inputs of one coin: Stocktwits bullish share, CoinGecko community votes, news tone and the
    Hyperliquid top traders' long share (each kept as a raw value for sentiment_rank), plus trending and Reddit
    buzz shown next to them. Small samples are pulled toward neutral. Not part of the tested score."""
    out = {"score": None, "label": None, "parts": [], "trending": None, "stocktwits": None, "reddit": None,
           "news": None, "votes": None, "whales": None, "raw": {}}
    trd = ((trend or {}).get("coins") or {}).get(t.upper())
    if trd:
        out["trending"] = trd["rank"]
    S = ((st or {}).get("coins") or {}).get(t)
    if S and not S.get("none"):
        out["stocktwits"] = {k: S.get(k) for k in ("bull", "bear", "bull_share", "posts_day", "posts_24h", "watchers",
                                                   "sent_change", "vol_change")}
        b, r = S.get("bull") or 0, S.get("bear") or 0
        if b + r >= 4:
            out["raw"]["st"] = (b + 1) / (b + r + 2)       # a few tagged posts say less than many
    cid = (fdm or {}).get("id")
    v = ((votes or {}).get("coins") or {}).get(cid) if cid else None
    if v and v.get("up") is not None:
        out["votes"] = round(v["up"])
        out["raw"]["votes"] = v["up"]
    A = ((ape or {}).get("coins") or {}).get(t.upper())
    if A:
        out["reddit"] = A
    N = news_for(t, (fdm or {}).get("name"), feed)
    if N and N.get("n"):
        out["news"] = N
        out["raw"]["news"] = N["tone"] * N["n"] / (N["n"] + 2)    # one headline counts for little
    if sm and (sm[2] + sm[3]) >= 50_000:
        share = sm[2] / (sm[2] + sm[3])
        out["whales"] = round(share * 100)
        out["raw"]["whales"] = 0.5 + (share - 0.5) * min(1.0, (sm[2] + sm[3]) / 1_000_000)   # small books count less
    return out


def sentiment_rank(all_sent, min_coins=5):
    """Score every coin 0-100 against the other coins of the same scan: each source becomes a percentile (50 = a
    typical coin today), weighted Stocktwits 35, top traders 25, CoinGecko votes 20, news 20. A coin needs two
    sources for a score. Ranking matters because crypto crowds lean bullish on almost everything: in a live run 69%
    of coins looked bullish on raw numbers."""
    import bisect
    pct = {}
    for k in SENT_W:
        vals = sorted(v["raw"][k] for v in all_sent.values() if k in v.get("raw", {}))
        if len(vals) < min_coins:
            continue
        for t, v in all_sent.items():
            x = v.get("raw", {}).get(k)
            if x is None:
                continue
            lo, hi = bisect.bisect_left(vals, x), bisect.bisect_right(vals, x)
            pct.setdefault(t, {})[k] = 100.0 * (lo + (hi - lo) / 2) / len(vals)
    for t, v in all_sent.items():
        p = pct.get(t, {})
        v["parts"] = [[SENT_NAMES[k], round(p[k])] for k in SENT_W if k in p]
        if len(p) >= 2:
            v["score"] = round(sum(p[k] * SENT_W[k] for k in p) / sum(SENT_W[k] for k in p))
            v["label"] = "Bullish" if v["score"] >= 65 else "Bearish" if v["score"] <= 35 else "Neutral"
        else:
            v["score"], v["label"] = None, None
        v.pop("raw", None)
    return all_sent


def sentiment_checks(sent):
    """Sentiment lines for a pick's checklist (information only: no free history to test them on)."""
    out = []
    S = sent.get("stocktwits")
    if S and S.get("bull_share") is not None:
        d = (f"{S['bull']} bullish vs {S['bear']} bearish posts ({S['bull_share'] * 100:.0f}% bullish), "
             f"about {S['posts_day']:.1f} posts a day")
        out.append(("st", "Traders on Stocktwits", None, 0, d, "Sentiment", False))
    elif S:
        out.append(("st", "Traders on Stocktwits", None, 0, f"Few tagged posts (about {S['posts_day']:.1f} posts a day)",
                    "Sentiment", False))
    else:
        out.append(("st", "Traders on Stocktwits", None, 0, "No Stocktwits posts found", "Sentiment", False))
    R = sent.get("reddit")
    if R:
        prev = R.get("prev")
        ch = (f", {'up' if (R['mentions'] or 0) >= (prev or 0) else 'down'} from {prev} a day before" if prev is not None else "")
        out.append(("reddit", "Reddit and 4chan buzz", None, 0,
                    f"#{R['rank']} most mentioned crypto ({R['mentions']} mentions in 24h{ch})", "Sentiment", False))
    else:
        out.append(("reddit", "Reddit and 4chan buzz", None, 0, "Not among the most mentioned coins", "Sentiment", False))
    N = sent.get("news")
    if N and N.get("n"):
        tone = "positive" if N["tone"] > 0.15 else "negative" if N["tone"] < -0.15 else "mixed"
        out.append(("news", "News headlines", None, 0, f"{N['n']} headlines in 3 days, tone {tone}: “{N['top'][0]['title'][:90]}”",
                    "Sentiment", False))
    else:
        out.append(("news", "News headlines", None, 0, "No headlines in the last 3 days", "Sentiment", False))
    if sent.get("votes") is not None:
        out.append(("votes", "CoinGecko community", None, 0, f"{sent['votes']}% bullish votes", "Sentiment", False))
    out.append(("trend", "Trending searches", None, 0,
                f"#{sent['trending']} most searched on CoinGecko right now" if sent.get("trending") else
                "Not among CoinGecko's 15 most searched coins", "Sentiment", False))
    return out


def hourly(coin, src, n, now):
    """The last n closed hourly candles, on the same price scale as the 4h candles."""
    try:
        rows = q.bars_1h(coin["t"], src, now - (n + 2) * H)
    except Exception as e:  # noqa: BLE001
        sc.note_error(f"{coin['t']} 1h: {e}")
        return None
    rows = [x for x in rows if x["t"] + H <= now]
    if len(rows) < 100:
        return None
    scale, ok = sc.detect_scale(coin.get("ref_price"), rows)
    if not ok:
        return None
    if scale != 1.0:
        for x in rows:
            for k in ("o", "h", "l", "c"):
                x[k] *= scale
    return rows[-n:]


GATE_STATS7 = "https://api.gateio.ws/api/v4/futures/usdt/contract_stats?contract={sym}&interval=4h&limit=45"


def gate_stats7(t):
    """Open interest, price and the top traders' ratio over 7 days, and the long share of liquidations over
    3 days, from Gate.io futures statistics (4-hour buckets)."""
    if sc.BREAKERS["gate_stats"].open:
        return None
    try:
        d = sc.FETCH(GATE_STATS7.format(sym=sc.exchange_symbol("gate", t)))
        sc.BREAKERS["gate_stats"].ok()
    except Exception as e:  # noqa: BLE001
        if sc.is_hard_failure(e):
            sc.BREAKERS["gate_stats"].fail()
            sc.note_error(f"gate stats {t}: {e}")
        return None
    rows = sorted([x for x in (d or []) if isinstance(x, dict) and "time" in x], key=lambda x: int(x["time"]))
    if len(rows) < 20:
        return None
    a, b = rows[max(0, len(rows) - 43)], rows[-1]
    oi0, oi1 = sc.fnum(a.get("open_interest_usd")), sc.fnum(b.get("open_interest_usd"))
    p0, p1 = sc.fnum(a.get("mark_price")), sc.fnum(b.get("mark_price"))
    t0, t1 = sc.fnum(a.get("top_lsr_size")), sc.fnum(b.get("top_lsr_size"))
    ll = sum(sc.fnum(x.get("long_liq_usd"), 0.0) or 0.0 for x in rows[-18:])
    sl = sum(sc.fnum(x.get("short_liq_usd"), 0.0) or 0.0 for x in rows[-18:])
    return {"oi7": (oi1 / oi0 - 1) if (oi0 and oi1) else None, "px7": (p1 / p0 - 1) if (p0 and p1) else None,
            "liq3": ll / (ll + sl) if (ll + sl) > 0 else None, "top0": t0, "top1": t1,
            "top7": (t1 / t0 - 1) if (t0 and t1) else None, "days": (int(b["time"]) - int(a["time"])) / DAY}


def supply_update(J, cg, now):
    """Keep a daily snapshot of every coin's circulating supply (CoinGecko) for the 30-day supply growth.
    A new journal starts from picks_seed.json (the last weeks of the research data)."""
    S = J.setdefault("supply", {})
    if not S:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "picks_seed.json")
        if os.path.exists(p):
            with open(p) as fh:
                S.update((json.load(fh) or {}).get("supply") or {})
    day = now // DAY * DAY
    for t, f in ((cg or {}).get("coins") or {}).items():
        c = f.get("circ")
        if not c:
            continue
        rows = S.setdefault(t, [])
        if rows and rows[-1][0] == day:
            rows[-1][1] = c
        else:
            rows.append([day, c])
        S[t] = [r for r in rows if r[0] >= day - 45 * DAY]


def supply_growth(J, t, now):
    rows = (J.get("supply") or {}).get(t) or []
    if len(rows) < 2:
        return None
    day = now // DAY * DAY
    old = [r for r in rows if day - 35 * DAY <= r[0] <= day - 27 * DAY]
    if not old or not rows[-1][1] or not old[0][1] or rows[-1][0] < day - 2 * DAY:
        return None
    return rows[-1][1] / old[0][1] - 1


def read_smart(out_dir):
    """Hyperliquid top traders per coin, from the scan that ran just before (data/latest.json)."""
    p = os.path.join(out_dir, "data", "latest.json")
    try:
        with open(p) as fh:
            d = json.load(fh)
    except Exception:  # noqa: BLE001
        return {}, None
    return d.get("smart_coins") or {}, d.get("smart")


# --------------------------------------------------------------------------- plans and records
def plan_of(side, price, atr_abs, kind):
    p = CFG[kind]
    d = 1 if side == "long" else -1
    stop_pct = min(p["max_stop"], max(p["min_stop"], p["stop_k"] * atr_abs / price))
    risk = price * stop_pct
    out = {"entry": price, "stop": price - d * risk, "stop_pct": stop_pct, "trail": p["trail_k"] * atr_abs,
           "trail_k": p["trail_k"], "atr": atr_abs, "r1": price + d * risk, "r2": price + 2 * d * risk,
           "r3": price + 3 * d * risk}
    if kind == "swing":
        out["days"] = p["days"]
    else:
        out["hours"] = p["hours"]
    return {k: (float(f"{v:.8g}") if isinstance(v, float) else v) for k, v in out.items()}


PROPER = ("Hyperliquid", "Bitcoin", "Gate.io", "CoinGecko")


def lc(name):
    """Lower-case the first letter of a check name, except acronyms (EMA, RSI) and names (Hyperliquid, Bitcoin)."""
    w = name.split(" ", 1)[0]
    if (len(w) > 1 and w[:2].isupper()) or w in PROPER:
        return name
    return name[:1].lower() + name[1:]


def usd_short(x):
    return f"${x / 1e6:,.1f}M" if x >= 1e6 else f"${x / 1e3:,.0f}k"


def summary(side, kind, label, checks, extras):
    """One plain sentence: what the setup is and the strongest reasons."""
    good = [lc(c["name"]) for c in checks if c["ok"] == 1][:3]
    bad = [lc(c["name"]) for c in checks if c["ok"] == 0][:2]
    plus = [lc(e["name"]) for e in extras if e["ok"] is True and e["max"] > 0 and e["k"] != "liq"][:2]
    what = (SETUP[side] if kind == "swing" else ("Day long" if side == "long" else "Day short"))
    s = f"{what} ({label.lower()}): " + (", ".join(good) if good else "few checks pass")
    if plus:
        s += ". Also for it: " + ", ".join(plus)
    if bad:
        s += ". Missing: " + ", ".join(bad)
    return s + "."


def record(kind, side, coin_t, coin, core, credits, weights, lines, extras, plan, price, extra_vals):
    checks = []
    for key, title, detail in lines:
        cr = credits[key]
        checks.append({"k": key, "name": title, "ok": cr, "pts": round(weights[key] * cr, 1), "max": weights[key],
                       "detail": detail, "group": "Setup", "tested": True})
    ex = [{"k": k, "name": t, "ok": ok, "pts": p if ok is True else (-p if ok is False else 0), "max": p,
           "detail": d, "group": g, "tested": tested} for k, t, ok, p, d, g, tested in extras]
    adj = extra_points(extras)
    final = max(0.0, min(100.0, core + adj))
    lab = label_of(final, kind)
    venues = " ".join(sc.DEX_CODE[d] for d in sc.DEXES if d in (coin.get("venues") or {}))
    return {"coin": coin_t, "kind": kind, "side": side, "score": round(final, 1), "core": round(core, 1),
            "extra": round(adj, 1), "label": lab, "setup": SETUP[side] if kind == "swing" else None,
            "price": float(f"{price:.8g}"), "venues": venues, "liq": round(sc.liq_of(coin) or 0),
            "checks": checks, "extras": ex, "plan": plan, "why": summary(side, kind, lab, checks, ex),
            **extra_vals}


# --------------------------------------------------------------------------- paper trades
def new_journal(now):
    return {"engine": ENGINE, "version": VERSION, "created": now, "updated": now, "scans": 0, "open": [],
            "closed": [], "done": {}, "cg": None}


def load_journal(pages_url, path, now):
    """The paper record from the published site. Stops (instead of starting over) when the site has the
    picks but the journal cannot be read, so a glitch never wipes the record."""
    if path:
        if os.path.exists(path):
            with open(path) as fh:
                return json.load(fh), "file"
        return new_journal(now), "new"
    if not pages_url:
        return new_journal(now), "new"
    base = pages_url.rstrip("/")
    try:
        J = sc.FETCH(f"{base}/data/picks_journal.json?ts={now}", timeout=60)
    except sc.HttpError as e:
        if e.code != 404:
            raise SystemExit(f"picks: could not read the published journal ({e}); stopping")
        try:
            sc.FETCH(f"{base}/data/picks.json?ts={now}", timeout=60)
        except sc.HttpError as e2:
            if e2.code == 404:
                return new_journal(now), "new"
            raise SystemExit(f"picks: could not check the published site ({e2}); stopping")
        except Exception as e2:  # noqa: BLE001
            raise SystemExit(f"picks: could not check the published site ({e2}); stopping")
        raise SystemExit("picks: picks_journal.json is missing although picks.json is published; stopping")
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"picks: could not read the published journal ({e}); stopping")
    if not isinstance(J, dict) or not isinstance(J.get("open"), list) or J.get("engine", 0) < ENGINE:
        return new_journal(now), "new"
    return J, "site"


def replay(tr, bars, step, now):
    """Replay a paper trade on bars (daily for swing, hourly for day trades) with the tested rules: stop
    first when a bar touches it, gaps exit at the open, the trailing stop follows the best high (low for
    shorts) at a fixed distance set at entry and applies from the next bar, out at the close of the last
    allowed bar. Returns the state, or None when the entry bar is not there yet."""
    i0 = next((i for i, b in enumerate(bars) if b["t"] >= tr["t_in"]), None)
    if i0 is None or bars[i0]["t"] != tr["t_in"]:
        return None
    d = tr["d"]
    if tr.get("px") is None:
        tr["px"] = bars[i0]["o"]
    e = tr["px"]
    stop = e * (1 - d * tr["stop_pct"])
    stop0 = stop
    best = e
    trail = tr["trail_abs"] * e / tr["ref_px"] if tr.get("trail_abs") else 0.0
    last_t = tr["t_in"] + (tr["bars"] - 1) * step
    state, exit_px, exit_t, mfe = "open", None, None, 0.0
    cur = e
    for i in range(i0, len(bars)):
        b = bars[i]
        if b["t"] + step > now:
            break
        o, h, l, c = b["o"], b["h"], b["l"], b["c"]
        if d > 0:
            if i > i0 and o <= stop:
                state, exit_px = "gap", o
            elif l <= stop:
                state, exit_px = ("trail" if stop > stop0 else "stop"), stop
        else:
            if i > i0 and o >= stop:
                state, exit_px = "gap", o
            elif h >= stop:
                state, exit_px = ("trail" if stop < stop0 else "stop"), stop
        if state != "open":
            exit_t = b["t"] + step
            break
        fav = (h / e - 1) if d > 0 else (1 - l / e)
        mfe = max(mfe, fav)
        if d > 0:
            best = max(best, h)
            stop = max(stop, best - trail) if trail else stop
        else:
            best = min(best, l)
            stop = min(stop, best + trail) if trail else stop
        cur = c
        if b["t"] >= last_t:
            state, exit_px, exit_t = "time", c, b["t"] + step
            break
    px = exit_px if exit_px is not None else (bars[-1]["c"] if bars else cur)
    gross = d * (px - e) / e
    r = (gross - tr["cost"]) / tr["stop_pct"]
    return {"state": state, "exit_px": float(f"{exit_px:.8g}") if exit_px is not None else None, "exit_t": exit_t,
            "stop_now": float(f"{stop:.8g}"), "last_px": float(f"{px:.8g}"), "r": round(r, 4),
            "ret": round(gross - tr["cost"], 5), "mfe": round(mfe, 4)}


def stats(closed):
    rs = [t["r"] for t in closed if t.get("r") is not None]
    n = len(rs)
    if not n:
        return {"n": 0}
    wins, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    rets = [t.get("ret") or 0.0 for t in closed if t.get("r") is not None]
    return {"n": n, "wr": round(sum(1 for r in rs if r > 0) / n, 3), "avg": round(sum(rs) / n, 3),
            "sum": round(sum(rs), 2), "pf": round(wins / losses, 2) if losses > 0 else None,
            "avg_ret": round(sum(rets) / n, 4),
            "long_n": sum(1 for t in closed if t["d"] > 0), "short_n": sum(1 for t in closed if t["d"] < 0)}


# --------------------------------------------------------------------------- run
def market_state(daily, btc_x):
    up = tot = 0
    for t, cd in daily.items():
        if len(cd) > 60:
            e = q.ema([x["c"] for x in cd], 50)[-1]
            if e:
                tot += 1
                up += cd[-1]["c"] > e
    share = up / tot if tot else None
    btc_up = bool(btc_x and btc_x.get("up"))
    if btc_up and share is not None and share >= 0.5:
        mood = "Risk-on: Bitcoin above its 50-day EMA and most coins in uptrends. Longs have the wind behind them."
    elif btc_up:
        mood = "Mixed: Bitcoin is above its 50-day EMA but most coins are still below theirs. Be picky with longs."
    elif share is not None and share >= 0.5:
        mood = "Mixed: Bitcoin is below its 50-day EMA while many coins hold up. Size down."
    else:
        mood = "Risk-off: Bitcoin below its 50-day EMA and most coins in downtrends. Shorts on bounces fit better."
    return {"btc": btc_x, "above": up, "total": tot, "share": round(share, 3) if share is not None else None,
            "mood": mood}


def run(out_dir, pages_url=None, journal_path=None, universe=None):
    t0 = time.time()
    now = sc.now_ts()
    J, jsrc = load_journal(pages_url, journal_path, now)
    log(f"journal ({jsrc}): {len(J['open'])} open, {len(J['closed'])} closed")
    if universe is None:
        universe, _, ok = sc.build_universe()
        if not ok:
            raise SystemExit("picks: no DEX market list could be loaded")
    coins = [c for c in universe.values() if not c.get("tradfi") and (sc.liq_of(c) or 0) >= CFG["min_dex_vol"]]
    coins.sort(key=lambda c: -(sc.liq_of(c) or 0))
    if "BTC" in universe and all(c["t"] != "BTC" for c in coins):
        coins.insert(0, universe["BTC"])
    got = sc.parallel(lambda t: q.bars_4h(universe[t], CFG["bars_4h"]), [c["t"] for c in coins])
    data = {}
    for c in coins:
        g = got.get(c["t"])
        if not g:
            continue
        closed = [x for x in g["candles"] if x["t"] + B4 <= now]
        if len(closed) >= 60:
            data[c["t"]] = {"c4": closed, "all4": g["candles"], "src": g["src"], "coin": c,
                            "cd": q.to_daily(closed)}
    log(f"{len(data)} of {len(coins)} coins with 4h candles")
    daily = {t: v["cd"] for t, v in data.items() if v["cd"]}
    last_day = max((cd[-1]["t"] for cd in daily.values()), default=None)
    btc_x = None
    if "BTC" in daily and len(daily["BTC"]) > 60 and daily["BTC"][-1]["t"] == last_day:
        bc = [x["c"] for x in daily["BTC"]]
        e50 = q.ema(bc, 50)[-1]
        btc_x = {"price": bc[-1], "ema50": e50, "up": bool(e50 and bc[-1] > e50),
                 "mom30": bc[-1] / bc[-31] - 1 if len(bc) > 30 else None, "mom7": bc[-1] / bc[-8] - 1}
    market = market_state(daily, btc_x)
    market["fng"] = None

    # 1) swing checks on the last complete day
    swing = {}
    for t, v in data.items():
        cd = v["cd"]
        if not cd or cd[-1]["t"] != last_day:
            continue
        if cd[-1]["qv"] < CFG["min_ref_vol"]:
            continue
        x = swing_values(cd, v["c4"], btc_x or {})
        if not x:
            continue
        c4 = [b["c"] for b in v["c4"]]
        e20, e100 = q.ema(c4, 20)[-1], q.ema(c4, 100)[-1]
        x["trend4h_now"] = (e20 / e100 - 1) if (e20 and e100) else None
        x["price_now"] = v["all4"][-1]["c"]
        cl, cs = long_checks(x), short_checks(x)
        swing[t] = {"x": x, "cl": cl, "cs": cs, "long": points(cl, LONG_W), "short": points(cs, SHORT_W)}
    log(f"swing checks for {len(swing)} coins (day {time.strftime('%Y-%m-%d', time.gmtime(last_day or 0))})")

    # 2) day-trade candidates: the most liquid coins plus every coin with a decent swing score
    by_liq = sorted(swing, key=lambda t: -(sc.liq_of(data[t]["coin"]) or 0))
    day_set = set(by_liq[: CFG["day_coins"]]) | {t for t, s in swing.items() if max(s["long"], s["short"]) >= 60}
    c1s = sc.parallel(lambda t: hourly(data[t]["coin"], data[t]["src"], CFG["bars_1h"], now), sorted(day_set))
    # 3) live extras: smart money (scanner), open interest (Gate.io), funding (DEXs), fundamentals (CoinGecko)
    smart, smart_meta = read_smart(out_dir)
    ranked = sorted(swing, key=lambda t: -max(swing[t]["long"], swing[t]["short"]))
    stat_set = set(ranked[: CFG["stats_coins"]]) | set(by_liq[:10])
    pos = sc.parallel(gate_stats7, sorted(stat_set), workers=4)
    cg, cg_state = coingecko([data[t]["coin"] for t in swing], J.get("cg"), now)
    J["cg"] = cg
    if cg_state == "fresh":
        supply_update(J, cg, now)
    trend = J["trend"] = cg_trending(J.get("trend"), now)
    cand = [((cg or {}).get("coins") or {}).get(t, {}).get("id") for t in ranked[:30]]
    votes = J["votes"] = cg_votes(cand, J.get("votes"), now, 25 if CG_KEY else 10)
    st_list = list(dict.fromkeys(ranked[:25] + by_liq[:10]))
    stw = J["st"] = stocktwits(st_list, J.get("st"), now)
    ape = J["ape"] = apewisdom(J.get("ape"), now)
    GEMINI_STATE.update(calls=0, errors=[], stopped=False, busy=set())
    feed = J["news"] = news_ai(news(J.get("news"), now), now)
    fng = J["fng"] = fear_greed(J.get("fng"), now)
    market["fng"] = {k: (fng or {}).get(k) for k in ("value", "label")} if fng else None
    J.pop("lc", None)
    fund = {t: sc.funding_avg(data[t]["coin"]) for t in swing}

    # free sentiment, ranked against the other coins of this scan
    SENT = sentiment_rank({t: sentiment_of(t, ((cg or {}).get("coins") or {}).get(t), trend, votes, stw, ape, feed, smart.get(t))
                           for t in swing})

    # 4) records
    sw_recs, day_recs = [], []
    for t, s in swing.items():
        coin, x = data[t]["coin"], s["x"]
        fdm = (cg or {}).get("coins", {}).get(t)
        liq = sc.liq_of(coin) or 0
        sent = SENT[t]
        best = None
        for side in ("long", "short"):
            core = s[side]
            cr = s["cl"] if side == "long" else s["cs"]
            W = LONG_W if side == "long" else SHORT_W
            ex = extra_checks(side, coin, smart.get(t), pos.get(t), fund.get(t), fdm, liq,
                              supply_growth(J, t, now)) + sentiment_checks(sent)
            plan = plan_of(side, x["price_now"], x["atr"] * x["price_now"] / x["price"], "swing")
            rec = record("swing", side, t, coin, core, cr, W, swing_explain(side, x, cr), ex, plan, x["price_now"],
                         {"chg24": round(x["price_now"] / data[t]["c4"][-6]["c"] - 1, 4) if len(data[t]["c4"]) > 6 else None,
                          "spark": spark([b["c"] for b in data[t]["cd"][-60:]]), "day": last_day,
                          "atrp": round(x["atrp"], 4), "fund": fdm and {k: fdm.get(k) for k in ("mc", "rank", "ath_ch")},
                          "sentiment": sent})
            if best is None or rec["score"] > best["score"]:
                best = rec
        sw_recs.append(best)
        c1 = c1s.get(t)
        if not c1:
            continue
        y = day_values(c1, x, fund.get(t))
        if not y:
            continue
        bestd = None
        for side in ("long", "short"):
            cr = day_checks(side, y, s[side])
            core = points(cr, DAY_W)
            ex = [e for e in extra_checks(side, coin, smart.get(t), pos.get(t), None, None, liq)
                  if e[0] in ("smart", "lev", "flush", "liq")] + [rsi_check(side, y["rsi1h"])]
            plan = plan_of(side, y["price"], y["atr"], "day")
            rec = record("day", side, t, coin, core, cr, DAY_W, day_explain(side, y, cr, s[side]), ex + sentiment_checks(sent),
                         plan, y["price"],
                         {"chg24": round(y["r24h"], 4), "spark": spark([b["c"] for b in c1[-48:]]), "hour": y["t"],
                          "rsi1h": round(y["rsi1h"], 1) if y["rsi1h"] is not None else None, "sentiment": sent})
            if bestd is None or rec["score"] > bestd["score"]:
                bestd = rec
        day_recs.append(bestd)
    # one sentiment snapshot per coin and day, kept for 400 days, so the free sentiment can be tested later
    hist = J.setdefault("sent_hist", {})
    day0 = now // DAY * DAY
    for r in sw_recs:
        se = r.get("sentiment") or {}
        st_ = se.get("stocktwits") or {}
        row = [day0, se.get("score"), st_.get("bull_share"), st_.get("posts_day"), (se.get("reddit") or {}).get("mentions"),
               (se.get("news") or {}).get("n"), (se.get("news") or {}).get("tone"), se.get("votes"), se.get("whales"),
               round(r["price"], 8)]
        rows = hist.setdefault(r["coin"], [])
        if rows and rows[-1][0] == day0:
            rows[-1] = row
        else:
            rows.append(row)
        hist[r["coin"]] = rows[-400:]
    sw_recs.sort(key=lambda r: (-r["score"], -r["liq"]))
    day_recs.sort(key=lambda r: (-r["score"], -r["liq"]))
    # AI desk notes for the top swing picks (only with the GEMINI_API_KEY secret)
    rp0 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "picks_research.json")
    try:
        with open(rp0) as fh:
            research = json.load(fh)
    except (OSError, ValueError):
        research = None
    notes = desk_notes(sw_recs, J, now, research, market)
    for r in sw_recs:
        n = notes.get(r["coin"])
        if n and n.get("side") == r["side"]:
            r["note"] = {k: n.get(k) for k in ("t", "model", "text")}
    n = CFG["top_n"]
    swing_out = {"all": sw_recs[:n], "long": [r for r in sw_recs if r["side"] == "long"][:n],
                 "short": [r for r in sw_recs if r["side"] == "short"][:n]}
    day_out = {"all": day_recs[:n], "long": [r for r in day_recs if r["side"] == "long"][:n],
               "short": [r for r in day_recs if r["side"] == "short"][:n]}

    # 5) paper trades: replay the open ones, then open new ones for ready picks
    closed_now = []
    need_d = sorted({tr["c"] for tr in J["open"] if tr["kind"] == "swing" and tr["c"] not in data})
    if need_d:
        extra4 = sc.parallel(lambda t: q.bars_4h(universe[t], 300) if t in universe else None, need_d)
        for t, g in extra4.items():
            if g:
                cl4 = [x for x in g["candles"] if x["t"] + B4 <= now]
                data.setdefault(t, {"c4": cl4, "all4": g["candles"], "src": g["src"], "coin": universe[t],
                                    "cd": q.to_daily(cl4)})
    day_need = sorted({tr["c"] for tr in J["open"] if tr["kind"] == "day"})
    day_bars = {}
    if day_need:
        def fetch1(t):
            tr0 = min((tr for tr in J["open"] if tr["kind"] == "day" and tr["c"] == t), key=lambda z: z["t_in"])
            coin = universe.get(t) or {"t": t, "ref_price": tr0.get("ref_px")}
            hrs = int((now - tr0["t_in"]) / H) + 30
            return hourly(coin, tr0.get("src", "mexc"), max(hrs, 120), now)
        day_bars = sc.parallel(fetch1, day_need)

    def bars_for(tr):
        if tr["kind"] == "swing":
            v = data.get(tr["c"])
            return (v or {}).get("cd") or [], DAY
        return day_bars.get(tr["c"]) or c1s.get(tr["c"]) or [], H

    keep = []
    for tr in J["open"]:
        bars, step = bars_for(tr)
        res = replay(tr, bars, step, now) if bars else None
        if res is None:
            if now - tr["t_in"] > (5 * DAY if tr["kind"] == "swing" else 12 * H) and tr.get("px") is None:
                continue  # never filled (no data): drop it
            if now - tr["t_in"] > (tr["bars"] + 5) * step:
                continue  # the coin's candles are gone (delisted): the trade cannot be valued, drop it
            keep.append(tr)
            continue
        tr["res"] = res
        if res["state"] != "open":
            tr["t_out"], tr["r"], tr["ret"] = res["exit_t"], res["r"], res["ret"]
            closed_now.append(tr)
        else:
            keep.append(tr)
    J["open"] = keep
    busy = {(tr["kind"], tr["c"], tr["d"]) for tr in J["open"]}
    new = []
    done = J.setdefault("done", {})
    if last_day and done.get("swing", 0) < last_day:
        for r in sw_recs:
            if r["score"] < CFG["paper_swing_min"]:
                break
            d = 1 if r["side"] == "long" else -1
            if ("swing", r["coin"], d) in busy:
                continue
            x = swing[r["coin"]]["x"]
            slip = q.slip_of(r["liq"])
            new.append({"id": f"S-{r['coin']}-{r['side']}-{last_day}", "kind": "swing", "c": r["coin"], "d": d,
                        "score": r["score"], "t_sig": last_day + DAY, "t_in": last_day + DAY, "px": None,
                        "ref_px": x["price"], "stop_pct": round(r["plan"]["stop_pct"], 6),
                        "trail_abs": CFG["swing"]["trail_k"] * x["atr"], "bars": CFG["swing"]["days"],
                        "cost": round(2 * (q.CFG["fee_taker"] + slip), 6), "src": data[r["coin"]]["src"]})
            busy.add(("swing", r["coin"], d))
        done["swing"] = last_day
    last_hour = max((v[-1]["t"] for v in c1s.values() if v), default=None)
    if last_hour and done.get("day", 0) < last_hour:
        k = 0
        for r in day_recs:
            if r["score"] < CFG["paper_day_min"] or k >= CFG["paper_day_max_new"]:
                break
            d = 1 if r["side"] == "long" else -1
            if ("day", r["coin"], d) in busy or r.get("hour") != last_hour:
                continue
            slip = q.slip_of(r["liq"])
            new.append({"id": f"D-{r['coin']}-{r['side']}-{last_hour}", "kind": "day", "c": r["coin"], "d": d,
                        "score": r["score"], "t_sig": last_hour + H, "t_in": last_hour + H, "px": None,
                        "ref_px": r["price"], "stop_pct": round(r["plan"]["stop_pct"], 6),
                        "trail_abs": CFG["day"]["trail_k"] * r["plan"]["atr"], "bars": CFG["day"]["hours"],
                        "cost": round(2 * (q.CFG["fee_taker"] + slip), 6), "src": data[r["coin"]]["src"]})
            busy.add(("day", r["coin"], d))
            k += 1
        done["day"] = last_hour
    for tr in new:  # fill from the candles already loaded when the entry bar has started
        if tr["kind"] == "swing":
            v = data.get(tr["c"])
            first = next((b for b in (v or {}).get("all4", []) if b["t"] >= tr["t_in"]), None)
            if first and first["t"] == tr["t_in"]:
                tr["px"] = first["o"]
        J["open"].append(tr)
    J["closed"] = (J["closed"] + closed_now)[-CFG["keep_closed"]:]
    J["updated"], J["scans"], J["version"] = now, J.get("scans", 0) + 1, VERSION
    log(f"paper: {len(new)} new, {len(closed_now)} closed, {len(J['open'])} open")

    def open_view(tr):
        res = tr.get("res") or {}
        return {"kind": tr["kind"], "c": tr["c"], "d": tr["d"], "score": tr["score"], "t_in": tr["t_in"],
                "px": tr.get("px"), "stop_pct": tr["stop_pct"], "r": res.get("r"), "last_px": res.get("last_px"),
                "stop_now": res.get("stop_now"), "bars": tr["bars"]}

    rec_sw = [t for t in J["closed"] if t["kind"] == "swing"]
    rec_day = [t for t in J["closed"] if t["kind"] == "day"]
    out = {
        "version": VERSION, "generated": now, "duration_s": round(time.time() - t0, 1),
        "next_scan_min": sc.CFG["schedule_every_min"], "day": last_day, "hour": last_hour,
        "coins": len(swing), "market": market,
        "settings": {k: CFG[k] for k in ("account", "risk", "watch", "ready", "strong", "extra_max", "min_dex_vol",
                                         "min_ref_vol", "paper_swing_min", "paper_day_min")},
        "rules": {"swing": CFG["swing"], "day": CFG["day"], "fee_taker": q.CFG["fee_taker"]},
        "weights": {"long": LONG_W, "short": SHORT_W, "day": DAY_W},
        "trade_dexes": [sc.DEX_NAME.get(d, d) for d in sc.CFG["trade_dexes"]],
        "swing": swing_out, "daytrade": day_out,
        "sources": {"smart": bool(smart), "smart_traders": (smart_meta or {}).get("read"),
                    "oi": sum(1 for v in pos.values() if v), "cg": cg_state,
                    "cg_time": (cg or {}).get("time"), "cg_coins": len((cg or {}).get("coins") or {}),
                    "hourly": sum(1 for v in c1s.values() if v), "cg_key": bool(CG_KEY),
                    "stocktwits": sum(1 for v in ((stw or {}).get("coins") or {}).values() if not v.get("none")),
                    "reddit": len((ape or {}).get("coins") or {}), "news": len((feed or {}).get("items") or []),
                    "trending": [k for k, _ in sorted(((trend or {}).get("coins") or {}).items(),
                                                      key=lambda kv: kv[1]["rank"])][:15],
                    "gemini": {"key": bool(GEMINI_KEY), "calls": GEMINI_STATE["calls"], "notes": len(notes),
                               "rated": sum(1 for x in (feed or {}).get("items") or [] if x.get("ai") is not None),
                               "errors": GEMINI_STATE["errors"][:6]}},
        "scores": {r["coin"]: {"side": r["side"], "score": r["score"], "core": r["core"], "label": r["label"],
                               "venues": r.get("venues"), "sentiment": r.get("sentiment"), "note": r.get("note")}
                   for r in sw_recs},
        "record": {"swing": stats(rec_sw), "day": stats(rec_day),
                   "swing_long": stats([t for t in rec_sw if t["d"] > 0]),
                   "swing_short": stats([t for t in rec_sw if t["d"] < 0]),
                   "open": [open_view(t) for t in J["open"]],
                   "closed": [{k: t.get(k) for k in ("kind", "c", "d", "score", "t_in", "t_out", "px", "r", "ret")}
                              for t in J["closed"][-120:]],
                   "since": J.get("created")},
        "errors": sc.ERRORS[:40],
    }
    data_dir = os.path.join(out_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "picks.json"), "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    with open(os.path.join(data_dir, "picks_journal.json"), "w") as fh:
        json.dump(J, fh, separators=(",", ":"))
    here = os.path.dirname(os.path.abspath(__file__))
    rp = os.path.join(here, "picks_research.json")
    if os.path.exists(rp):
        shutil.copyfile(rp, os.path.join(data_dir, "picks_research.json"))
    # the picks page becomes the front page; the 15-minute radar moves to radar.html
    src = os.path.join(here, "picks.html")
    idx = os.path.join(out_dir, "index.html")
    if os.path.exists(src):
        if os.path.exists(idx) and not os.path.exists(os.path.join(out_dir, "radar.html")):
            shutil.copyfile(idx, os.path.join(out_dir, "radar.html"))
        shutil.copyfile(src, idx)
    # the coin analyzer (runs in the browser and reads data/picks.json for the tested scores and sentiment)
    for name in ("analyze.html", "analyze.js"):
        p = os.path.join(here, name)
        if os.path.exists(p):
            shutil.copyfile(p, os.path.join(out_dir, name))
    log(f"done in {out['duration_s']}s: {len(sw_recs)} swing and {len(day_recs)} day-trade scores; "
        f"top swing {', '.join(r['coin'] + ' ' + r['side'] + ' ' + str(r['score']) for r in sw_recs[:3])}")
    return out


def spark(xs):
    xs = [x for x in xs if x]
    if len(xs) < 2:
        return []
    lo, hi = min(xs), max(xs)
    return [round((x - lo) / (hi - lo) * 99) if hi > lo else 50 for x in xs]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Coin picks: swing and day-trade scores with reasons")
    ap.add_argument("--out", default="site")
    ap.add_argument("--pages-url", default=os.environ.get("PAGES_URL"))
    ap.add_argument("--journal", default=None, help="local picks_journal.json instead of the published one")
    a = ap.parse_args(argv)
    run(a.out, pages_url=a.pages_url, journal_path=a.journal)


if __name__ == "__main__":
    sys.exit(main())
