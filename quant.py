"""Quant desk: long AND short trend and momentum strategies on 4-hour and daily bars.

Runs after scanner.py in every scan (see .github/workflows/scan.yml):

  1. Coins: every crypto perp with $1M+ a day on the DEXs you trade (scanner.CFG["trade_dexes"]) and
     $5M+ a day on the reference exchange, listed for 30+ days.
  2. Candles: 4-hour candles (about 83 days) from MEXC futures (Gate.io as a fallback); daily bars are
     built from them. Only closed bars are used, so live signals are exactly what the backtest saw.
  3. Signals: the strategies that passed the one-year and three-year tests (quant_research.json):
       TSMOM      Daily trend rider       30- and 7-day returns and the 50-day EMA agree (long or short)
       TREND_EMA  4-hour trend crossover  EMA 20 crosses EMA 100 with ADX above 20 (long or short)
       XSMOM      Momentum rotation       the 5 strongest coins of the last 14 days long, the 5 weakest short
  4. Paper trading: every signal is traded on paper at the open of the next hour with its stop, trailing
     stop and time limit, after taker fees, slippage and funding (the same rules as the backtest).
  5. Output: data/quant.json (signals, open and closed trades, live record) for quant.html, and
     data/quant_journal.json (the record, carried between runs through the published site).

Standard library only. Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time

import scanner as sc

VERSION = "1.0.0"
ENGINE = 1
H = 3600
B4 = 4 * H
DAY = 24 * H

CFG = {
    "min_dex_vol": 1_000_000,   # 24h volume on one of your DEXs
    "min_ref_vol": 5_000_000,   # average daily volume on the reference exchange over 7 days (the backtest rule)
    "min_days": 30,             # days of history before a coin is traded
    "bars_4h": 1000,            # 4-hour candles fetched per coin (about 166 days: long enough for daily EMAs)
    "catch_up_4h": 6,           # 4h bars re-checked for signals when scans were missed
    "catch_up_days": 2,         # days re-checked for signals when scans were missed
    "min_stop": 0.015,          # stops are never closer than 1.5%
    "max_stop": 0.20,           # signals that need a stop further than 20% away are skipped
    "fee_taker": 0.00045,       # market orders (entries, stops, time exits)
    "fee_maker": 0.00015,       # limit orders (not used by these strategies)
    "slip": ((1e6, 0.0005), (2e5, 0.001), (0, 0.002)),  # slippage by 24h volume on your DEXs
    "account": 500.0,           # default account size on the page (each visitor can change it)
    "risk": 0.005,              # default risk per trade on the page
    "keep_closed": 400,         # closed trades kept in the journal
}

STRATS = {
    "TSMOM": {
        "name": "Daily trend rider", "tf": "1d", "kind": "trend",
        "desc": "Each day at 00:00 UTC: long when the 30-day and 7-day returns are both positive and the price "
                "is above its 50-day EMA; short when all three point down. Stop 3 daily ATRs away (at least "
                "1.5%), trailing stop 3 ATRs behind the best close, out after 21 days at the latest.",
        "params": {"look": 30, "short_look": 7, "ema": 50, "stop_k": 3.0, "trail_k": 3.0, "hold_h": 21 * 24},
    },
    "TREND_EMA": {
        "name": "4-hour trend crossover", "tf": "4h", "kind": "trend",
        "desc": "On each 4-hour close: long when EMA 20 crosses above EMA 100 with ADX above 20 (a real trend), "
                "short when it crosses below. Stop 2.5 ATRs away (at least 1.5%), trailing stop 3 ATRs behind "
                "the best close, out after 30 days at the latest.",
        "params": {"fast": 20, "slow": 100, "adx_min": 20, "stop_k": 2.5, "trail_k": 3.0, "hold_h": 30 * 24},
    },
    "XSMOM": {
        "name": "Momentum rotation", "tf": "1d", "kind": "momentum",
        "desc": "Each day at 00:00 UTC every coin is ranked by its 14-day return divided by its daily "
                "volatility: the 5 strongest are bought and the 5 weakest sold short, each for 14 days. "
                "Stop 2.5 daily ATRs away (at least 1.5%). Long and short together, so it does not depend on "
                "the market going up.",
        "params": {"look": 14, "vol_days": 30, "top": 5, "stop_k": 2.5, "hold_h": 14 * 24},
    },
}
ORDER = ("TSMOM", "TREND_EMA", "XSMOM")


def log(msg):
    sc.log("quant: " + msg)


# --------------------------------------------------------------------------- indicators (pandas-equivalent)
def _ewm(xs, alpha, minp):
    """pandas .ewm(alpha=alpha, adjust=False, min_periods=minp).mean() for a list with leading None values."""
    out, y, n = [], None, 0
    for x in xs:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            out.append(y if (y is not None and n >= minp) else None)
            continue
        y = x if y is None else (1 - alpha) * y + alpha * x
        n += 1
        out.append(y if n >= minp else None)
    return out


def ema(xs, n):
    return _ewm(xs, 2.0 / (n + 1), n)


def wilder(xs, n):
    return _ewm(xs, 1.0 / n, n)


def atr(h, l, c, n=14):
    tr = []
    for i in range(len(c)):
        if i == 0:
            tr.append(h[0] - l[0])
        else:
            pc = c[i - 1]
            tr.append(max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc)))
    return wilder(tr, n)


def adx(h, l, c, n=14):
    pdm, ndm = [0.0], [0.0]
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        ndm.append(dn if (dn > up and dn > 0) else 0.0)
    a = atr(h, l, c, n)
    sp, sn = wilder(pdm, n), wilder(ndm, n)
    dx = []
    for i in range(len(c)):
        if a[i] is None or sp[i] is None or sn[i] is None or a[i] == 0:
            dx.append(None)
            continue
        pdi, ndi = 100 * sp[i] / a[i], 100 * sn[i] / a[i]
        dx.append(100 * abs(pdi - ndi) / (pdi + ndi) if pdi + ndi > 0 else None)
    return wilder(dx, n)


def ret(c, k):
    return [None if i < k or not c[i - k] else c[i] / c[i - k] - 1 for i in range(len(c))]


def rstd(xs, n, minp):
    out = []
    for i in range(len(xs)):
        w = [x for x in xs[max(0, i - n + 1): i + 1] if x is not None]
        if len(w) < minp or len(w) < 2:
            out.append(None)
            continue
        m = sum(w) / len(w)
        out.append(math.sqrt(sum((x - m) ** 2 for x in w) / (len(w) - 1)))
    return out


# --------------------------------------------------------------------------- data
def bars_4h(coin, n):
    """Closed and current 4-hour candles for a coin, prices per 1 coin. MEXC first, Gate.io as a fallback."""
    now = sc.now_ts()
    tries = []
    sym = sc.exchange_symbol("mexc", coin["t"])
    tries.append(("mexc", sym, lambda: sc._mexc_rows(sc.FETCH(sc.MEXC_KLINE.format(
        sym=sym, iv="Hour4", start=now - B4 * n, end=now)))))
    gsym = sc.exchange_symbol("gate", coin["t"])
    tries.append(("gate", gsym, lambda: sc._gate_rows(sc.FETCH(sc.GATE_KLINE_RANGE.format(
        sym=gsym, iv="4h", start=now - B4 * n, end=now)))))
    for src, s, fn in tries:
        if sc.BREAKERS[src].open:
            continue
        try:
            rows = sc._clean(fn())
            sc.BREAKERS[src].ok()
        except Exception as e:  # noqa: BLE001
            if sc.is_hard_failure(e):
                sc.BREAKERS[src].fail()
            continue
        if len(rows) < 60:
            continue
        scale, ok = sc.detect_scale(coin.get("ref_price"), rows)
        if not ok:
            continue
        if scale != 1.0:
            for x in rows:
                for k in ("o", "h", "l", "c"):
                    x[k] *= scale
        return {"src": src, "sym": s, "candles": rows}
    return None


def bars_1h(coin_t, src, start):
    """Hourly candles from `start` to now (for paper trades), from the same source as the 4h candles."""
    now = sc.now_ts()
    rows, e = [], now
    while e > start:
        st = max(start, e - H * 1000)
        if src == "gate":
            sym = sc.exchange_symbol("gate", coin_t)
            chunk = sc._gate_rows(sc.FETCH(sc.GATE_KLINE_RANGE.format(sym=sym, iv="1h", start=st, end=e)))
        else:
            sym = sc.exchange_symbol("mexc", coin_t)
            chunk = sc._mexc_rows(sc.FETCH(sc.MEXC_KLINE.format(sym=sym, iv="Min60", start=st, end=e)))
        if not chunk:
            break
        rows = chunk + rows
        if min(r[0] for r in chunk) > st + 3 * H:
            break
        e = st - 1
    return sc._clean(rows)


MEXC_FUND = ("https://contract.mexc.com/api/v1/contract/funding_rate/history?symbol={sym}"
             "&page_num={page}&page_size=100")


def funding_since(coin_t, start):
    """Funding settlements {time: rate} on MEXC since `start` (longs pay positive rates)."""
    sym = sc.exchange_symbol("mexc", coin_t)
    out, page = {}, 1
    while page < 6:
        d = sc.FETCH(MEXC_FUND.format(sym=sym, page=page))
        lst = ((d or {}).get("data") or {}).get("resultList") or []
        if not lst:
            break
        for x in lst:
            t, r = x.get("settleTime"), sc.fnum(x.get("fundingRate"))
            if t is not None and r is not None:
                out[int(t) // 1000] = r
        if min(int(x.get("settleTime") or 0) for x in lst) // 1000 < start:
            break
        page += 1
    return out


def to_daily(c4):
    """Complete UTC days from 4-hour candles (6 bars each, none missing)."""
    days, cur, key = [], [], None
    for x in c4:
        k = x["t"] // DAY
        if key is not None and k != key:
            if len(cur) == 6:
                days.append(cur)
            cur = []
        key = k
        cur.append(x)
    if len(cur) == 6:
        days.append(cur)
    out = []
    for g in days:
        if g[0]["t"] % DAY != 0 or any(g[i + 1]["t"] - g[i]["t"] != B4 for i in range(5)):
            continue
        out.append({"t": g[0]["t"], "o": g[0]["o"], "h": max(x["h"] for x in g), "l": min(x["l"] for x in g),
                    "c": g[-1]["c"], "qv": sum(x["qv"] for x in g)})
    return out


def slip_of(trade_vol):
    for lim, s in CFG["slip"]:
        if (trade_vol or 0) >= lim:
            return s
    return CFG["slip"][-1][1]


# --------------------------------------------------------------------------- signals
def eligible(c4, i, ref_t):
    """Coin tradable at 4h bar i: 30 days of history and $5M+ a day on average over the last 7 days."""
    if c4[i]["t"] - c4[0]["t"] < CFG["min_days"] * DAY - B4:
        return False
    w = [x["qv"] for x in c4[max(0, i - 41): i + 1]]
    return len(w) >= 6 and sum(w) / len(w) * 6 >= CFG["min_ref_vol"]


def _stop(price, a, k):
    if not price or a is None:
        return None
    s = max(CFG["min_stop"], k * a / price)
    return s if s <= CFG["max_stop"] else None


def trend_feats(c4):
    """Indicators on 4h bars for TREND_EMA (each value uses bars up to its own index only)."""
    p = STRATS["TREND_EMA"]["params"]
    h, l, c = [x["h"] for x in c4], [x["l"] for x in c4], [x["c"] for x in c4]
    return {"c": c, "ef": ema(c, p["fast"]), "es": ema(c, p["slow"]), "adx": adx(h, l, c, 14), "atr": atr(h, l, c, 14)}


def sig_trend_ema(f, i):
    """TREND_EMA at closed 4h bar i -> (direction, stop_pct, trail_pct) or None."""
    p = STRATS["TREND_EMA"]["params"]
    if i < 1:
        return None
    ef, es, a, at, c = f["ef"], f["es"], f["adx"], f["atr"], f["c"]
    if None in (ef[i], es[i], ef[i - 1], es[i - 1], a[i], at[i]) or a[i] <= p["adx_min"]:
        return None
    d = 1 if (ef[i] > es[i] and ef[i - 1] <= es[i - 1]) else -1 if (ef[i] < es[i] and ef[i - 1] >= es[i - 1]) else 0
    if not d:
        return None
    stop = _stop(c[i], at[i], p["stop_k"])
    return (d, stop, p["trail_k"] * at[i] / c[i]) if stop else None


def daily_feats(cd):
    """Indicators on daily bars for TSMOM and XSMOM."""
    c = [x["c"] for x in cd]
    h, l = [x["h"] for x in cd], [x["l"] for x in cd]
    pt, px = STRATS["TSMOM"]["params"], STRATS["XSMOM"]["params"]
    dr = ret(c, 1)
    return {"c": c, "atr": atr(h, l, c, 14), "r_long": ret(c, pt["look"]), "r_short": ret(c, pt["short_look"]),
            "ema": ema(c, pt["ema"]), "r_x": ret(c, px["look"]), "vol": rstd(dr, px["vol_days"], 20)}


def sig_tsmom(f, k):
    p = STRATS["TSMOM"]["params"]
    r1, r2, e, c = f["r_long"][k], f["r_short"][k], f["ema"][k], f["c"][k]
    if None in (r1, r2, e):
        return None
    d = 1 if (r1 > 0 and r2 > 0 and c > e) else -1 if (r1 < 0 and r2 < 0 and c < e) else 0
    if not d:
        return None
    stop = _stop(c, f["atr"][k], p["stop_k"])
    return (d, stop, p["trail_k"] * f["atr"][k] / c) if stop else None


def xs_scores(feats_at):
    """{coin: score} -> {coin: direction} for the top / bottom `top` coins (pandas average ranks)."""
    top = STRATS["XSMOM"]["params"]["top"]
    vals = sorted(feats_at.items(), key=lambda kv: kv[1])
    n = len(vals)
    if n == 0:
        return {}
    # average ranks with ties, as pandas rank(method="average")
    ranks_lo, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and vals[j + 1][1] == vals[i][1]:
            j += 1
        r = (i + j) / 2 + 1
        for q in range(i, j + 1):
            ranks_lo[vals[q][0]] = r
        i = j + 1
    out = {}
    for coin, r in ranks_lo.items():
        r_hi = n + 1 - r
        if r_hi <= top:
            out[coin] = 1
        elif r <= top:
            out[coin] = -1
    return out


# --------------------------------------------------------------------------- paper trades
def sim_trade(tr, c1, fund, now):
    """Replay a paper trade on hourly candles from its entry hour. Same rules as the backtest:
    stop first when a bar touches both, gaps exit at the open, the trailing stop moves at each close
    and applies from the next bar, time exit at the close of the last allowed hour."""
    i0 = next((i for i, x in enumerate(c1) if x["t"] >= tr["t_in"]), None)
    if i0 is None:
        return None
    d, entry = tr["d"], tr["px"]
    risk = entry * tr["stop_pct"]
    stop = stop0 = entry - d * risk
    trail = entry * (tr.get("trail_pct") or 0.0)
    best = entry
    fsum = 0.0
    mfe = mae = 0.0
    last = i0 + tr["hold_h"] - 1
    state, exit_px, exit_t = "open", None, None
    for i in range(i0, len(c1)):
        x = c1[i]
        if x["t"] + H > now:  # the hour still forming: wait for its close
            break
        if i > i0:
            fsum += fund.get(x["t"], 0.0)
        o, h, l, c = x["o"], x["h"], x["l"], x["c"]
        fav = ((h - entry) if d > 0 else (entry - l)) / risk
        adv = ((entry - l) if d > 0 else (h - entry)) / risk
        hit = None
        if d > 0:
            if i > i0 and o <= stop:
                hit, exit_px = "gap", o
            elif l <= stop:
                hit, exit_px = ("trail" if stop > stop0 else "stop"), stop
        else:
            if i > i0 and o >= stop:
                hit, exit_px = "gap", o
            elif h >= stop:
                hit, exit_px = ("trail" if stop < stop0 else "stop"), stop
        if hit:
            mae = max(mae, adv)
            state, exit_t = hit, x["t"] + H
            break
        mfe, mae = max(mfe, fav), max(mae, adv)
        if trail > 0:
            if d > 0:
                best = max(best, c)
                stop = max(stop, best - trail)
            else:
                best = min(best, c)
                stop = min(stop, best + trail)
        if i == last:
            state, exit_px, exit_t = "time", c, x["t"] + H
            break
    taker = CFG["fee_taker"] + tr["slip"]
    cur = exit_px if exit_px is not None else c1[-1]["c"]
    gross = d * (cur - entry) / entry
    fcost = d * fsum
    cost = 2 * taker  # entry and exit at market (an open trade is valued as if closed at market now)
    return {"state": state, "exit_px": exit_px, "exit_t": exit_t, "stop_now": stop, "mfe": round(mfe, 3),
            "mae": round(mae, 3), "gross": gross / tr["stop_pct"], "r": (gross - cost - fcost) / tr["stop_pct"],
            "fund": fcost / tr["stop_pct"], "last_px": c1[-1]["c"], "hours": len(c1) - i0}


def _tidy(key, v):
    """R values to 4 decimals; prices to 8 significant digits (some coins trade at 0.000004)."""
    if key in ("exit_px", "stop_now", "last_px"):
        return float(f"{v:.8g}")
    return round(v, 4)


# --------------------------------------------------------------------------- journal
def new_journal(now):
    return {"engine": ENGINE, "version": VERSION, "created": now, "updated": now, "scans": 0,
            "open": [], "closed": [], "done": {}}


def load_journal(pages_url, path, now):
    if path:
        if os.path.exists(path):
            with open(path) as fh:
                return json.load(fh), "file"
        return new_journal(now), "new"
    if not pages_url:
        return new_journal(now), "new"
    try:
        J = sc.FETCH(pages_url.rstrip("/") + f"/data/quant_journal.json?ts={now}", timeout=60)
    except sc.HttpError as e:
        if e.code == 404:
            try:  # a published quant.json without its journal means the journal went missing: do not start over
                sc.FETCH(pages_url.rstrip("/") + f"/data/quant.json?ts={now}", timeout=60)
            except sc.HttpError as e2:
                if e2.code == 404:
                    return new_journal(now), "new"
                raise SystemExit(f"quant: could not check the published site ({e2}); stopping")
            except Exception as e2:  # noqa: BLE001
                raise SystemExit(f"quant: could not check the published site ({e2}); stopping")
            raise SystemExit("quant: quant_journal.json is missing although quant.json is published; stopping so "
                             "the record is not replaced by an empty one")
        raise SystemExit(f"quant: could not read the published journal ({e}); stopping so it is not overwritten")
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"quant: could not read the published journal ({e}); stopping so it is not overwritten")
    if not isinstance(J, dict) or not isinstance(J.get("open"), list) or J.get("engine", 0) < ENGINE:
        return new_journal(now), "new"
    return J, "site"


def live_stats(closed):
    rs = [t["r"] for t in closed]
    n = len(rs)
    if not n:
        return {"n": 0}
    wins, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return {"n": n, "wr": round(sum(1 for r in rs if r > 0) / n, 3), "avg": round(sum(rs) / n, 3),
            "sum": round(sum(rs), 2), "pf": round(wins / losses, 2) if losses > 0 else None,
            "long_n": sum(1 for t in closed if t["d"] > 0), "short_n": sum(1 for t in closed if t["d"] < 0)}


# --------------------------------------------------------------------------- run
def run(out_dir, pages_url=None, journal_path=None, universe=None):
    t_start = time.time()
    now = sc.now_ts()
    J, jsrc = load_journal(pages_url, journal_path, now)
    log(f"journal ({jsrc}): {len(J['open'])} open, {len(J['closed'])} closed")
    if universe is None:
        universe, _, ok = sc.build_universe()
        if not ok:
            raise SystemExit("quant: no DEX market list could be loaded")
    coins = [c for c in universe.values() if not c.get("tradfi") and (sc.liq_of(c) or 0) >= CFG["min_dex_vol"]]
    coins.sort(key=lambda c: -(sc.liq_of(c) or 0))
    if "BTC" in universe and all(c["t"] != "BTC" for c in coins):
        coins.insert(0, universe["BTC"])
    got = sc.parallel(lambda t: bars_4h(universe[t], CFG["bars_4h"]), [c["t"] for c in coins])
    data = {}
    for c in coins:
        g = got.get(c["t"])
        if not g:
            continue
        closed = [x for x in g["candles"] if x["t"] + B4 <= now]
        if len(closed) >= 60:
            data[c["t"]] = {"c4": closed, "src": g["src"], "coin": c}
    log(f"{len(data)} of {len(coins)} coins with 4h candles")

    # 1) replay the open paper trades on hourly candles (new ones are filled at the open of their first hour)
    def replay(trades):
        keep, closed = [], []
        need = sorted({t["c"] for t in trades})
        starts = {c: min(t["t_in"] for t in trades if t["c"] == c) for c in need}
        srcs = {t["c"]: t.get("src", "mexc") for t in trades}
        c1s = sc.parallel(lambda c: bars_1h(c, srcs[c], starts[c] - H), need)
        funds = sc.parallel(lambda c: funding_since(c, starts[c] - 8 * H), need)
        for tr in trades:
            c1 = c1s.get(tr["c"]) or []
            if tr["px"] is None:
                first = next((x for x in c1 if x["t"] >= tr["t_in"]), None)
                if first is None:
                    if now - tr["t_in"] <= 6 * H:  # no candle yet: try again next scan
                        keep.append(tr)
                    continue
                tr["px"] = first["o"]
                tr["stop"] = tr["px"] * (1 - tr["d"] * tr["stop_pct"])
            res = sim_trade(tr, c1, funds.get(tr["c"]) or {}, now) if c1 else None
            if res is None:
                keep.append(tr)
                continue
            tr["res"] = {k: (_tidy(k, v) if isinstance(v, float) else v) for k, v in res.items()}
            if res["state"] != "open":
                tr["t_out"] = res["exit_t"]
                tr["r"] = round(res["r"], 4)
                closed.append(tr)
            else:
                keep.append(tr)
        return keep, closed

    J["open"], closed_now = replay(J["open"])

    # 2) signals on closed 4h bars and closed days not checked yet (a few bars back if scans were missed;
    #    a new journal starts from the latest bar only, so its first trades are not dated in the past)
    done = J.setdefault("done", {})
    fresh = not J.get("scans")
    back4 = 1 if fresh else CFG["catch_up_4h"]
    backd = 1 if fresh else CFG["catch_up_days"]
    signals = []
    last4 = max((v["c4"][-1]["t"] for v in data.values()), default=None)
    if last4 is not None:
        lo4 = max(done.get("TREND_EMA", 0), last4 - (back4 - 1) * B4 - 1)
        for t, v in data.items():
            c4 = v["c4"]
            tf = None
            for i in range(max(0, len(c4) - back4), len(c4)):
                if c4[i]["t"] <= lo4 or not eligible(c4, i, c4[i]["t"]):
                    continue
                tf = tf or trend_feats(c4)
                s = sig_trend_ema(tf, i)
                if s:
                    signals.append(("TREND_EMA", t, c4[i]["t"] + B4) + s)
        done["TREND_EMA"] = last4
    daily = {t: to_daily(v["c4"]) for t, v in data.items()}
    lastd = max((d[-1]["t"] for d in daily.values() if d), default=None)
    if lastd is not None:
        p = STRATS["XSMOM"]["params"]
        for day in range(lastd - (backd - 1) * DAY, lastd + 1, DAY):
            run_ts, run_xs = done.get("TSMOM", 0) < day, done.get("XSMOM", 0) < day
            if not (run_ts or run_xs):
                continue
            feats, xs = {}, {}
            for t, cd in daily.items():
                k = next((q for q in range(len(cd) - 1, -1, -1) if cd[q]["t"] == day), None)
                if k is None:
                    continue
                c4 = data[t]["c4"]
                i4 = next((q for q in range(len(c4) - 1, -1, -1) if c4[q]["t"] == day + DAY - B4), None)
                if i4 is None or not eligible(c4, i4, day):
                    continue
                f = daily_feats(cd[: k + 1])
                feats[t] = f
                if f["r_x"][-1] is not None and f["vol"][-1]:
                    xs[t] = f["r_x"][-1] / f["vol"][-1]
            if run_ts:
                for t, f in feats.items():
                    s = sig_tsmom(f, len(f["c"]) - 1)
                    if s:
                        signals.append(("TSMOM", t, day + DAY) + s)
            if run_xs:
                for t, d in xs_scores(xs).items():
                    f = feats[t]
                    stop = _stop(f["c"][-1], f["atr"][-1], p["stop_k"])
                    if stop:
                        signals.append(("XSMOM", t, day + DAY, d, stop, 0.0))
        done["TSMOM"] = done["XSMOM"] = lastd

    # 3) new paper trades: one at a time per strategy and coin, entry at the open after the signal bar
    busy = {}
    for tr in J["open"]:
        busy[(tr["s"], tr["c"])] = float("inf")
    for tr in J["closed"] + closed_now:
        k = (tr["s"], tr["c"])
        if busy.get(k, 0) != float("inf"):
            busy[k] = max(busy.get(k, 0), tr.get("t_out") or 0)
    new = []
    for sid, t, t_in, d, stop, trail in sorted(signals, key=lambda x: (x[2], x[0], x[1])):
        if t_in < busy.get((sid, t), 0):
            continue
        busy[(sid, t)] = float("inf")
        new.append({"id": f"{t}-{sid}-{t_in}", "s": sid, "c": t, "d": d, "t_sig": t_in, "t_in": t_in,
                    "stop_pct": round(stop, 6), "trail_pct": round(trail, 6), "hold_h": STRATS[sid]["params"]["hold_h"],
                    "slip": slip_of(sc.liq_of(data[t]["coin"])), "src": data[t]["src"], "px": None, "res": None})
    log(f"{len(signals)} signals, {len(new)} new paper trades")
    if new:
        opened, closed_new = replay(new)
        J["open"].extend(opened)
        closed_now += closed_new
    J["closed"] = (J["closed"] + closed_now)[-CFG["keep_closed"]:]
    J["updated"], J["scans"] = now, J.get("scans", 0) + 1
    log(f"{len(closed_now)} trades closed this scan, {len(J['open'])} open")

    # 4) market state for the page
    btc = daily.get("BTC") or []
    bf = daily_feats(btc) if len(btc) > 60 else None
    btc_state = None
    if bf:
        s = sig_tsmom(bf, len(bf["c"]) - 1)
        btc_state = {"price": bf["c"][-1], "r30": bf["r_long"][-1], "r7": bf["r_short"][-1], "ema50": bf["ema"][-1],
                     "trend": "up" if s and s[0] > 0 else "down" if s and s[0] < 0 else "mixed"}
    up = dn = 0
    for t, cd in daily.items():
        if len(cd) > 60:
            e = ema([x["c"] for x in cd], 50)[-1]
            if e:
                up += cd[-1]["c"] > e
                dn += cd[-1]["c"] < e
    out = {
        "version": VERSION, "generated": now, "duration_s": round(time.time() - t_start, 1),
        "coins": len(data), "settings": {k: CFG[k] for k in ("min_dex_vol", "min_ref_vol", "min_days", "min_stop",
                                                            "fee_taker", "account", "risk")},
        "trade_dexes": [sc.DEX_NAME.get(d, d) for d in sc.CFG["trade_dexes"]],
        "market": {"btc": btc_state, "above_ema50": up, "below_ema50": dn},
        "strategies": {sid: {k: v for k, v in STRATS[sid].items()} for sid in ORDER},
        "signals": [{"s": t["s"], "c": t["c"], "d": t["d"], "t": t["t_in"], "stop_pct": t["stop_pct"],
                     "trail_pct": t["trail_pct"]} for t in new],
        "open": J["open"], "closed": J["closed"][-150:],
        "live": {sid: live_stats([t for t in J["closed"] if t["s"] == sid]) for sid in ORDER},
        "live_all": live_stats(J["closed"]),
        "next_scan_min": sc.CFG["schedule_every_min"],
    }
    for sid in ORDER:
        out["strategies"][sid]["open"] = sum(1 for t in J["open"] if t["s"] == sid)
    data_dir = os.path.join(out_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "quant.json"), "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    with open(os.path.join(data_dir, "quant_journal.json"), "w") as fh:
        json.dump(J, fh, separators=(",", ":"))
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("quant.html",):
        if os.path.exists(os.path.join(here, name)):
            shutil.copyfile(os.path.join(here, name), os.path.join(out_dir, name))
    rp = os.path.join(here, "quant_research.json")
    if os.path.exists(rp):
        shutil.copyfile(rp, os.path.join(data_dir, "quant_research.json"))
    log(f"done in {out['duration_s']}s: {len(new)} new signals, {len(J['open'])} open trades")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Quant desk: long/short trend and momentum strategies")
    ap.add_argument("--out", default="site")
    ap.add_argument("--pages-url", default=os.environ.get("PAGES_URL"))
    ap.add_argument("--journal", default=None, help="local quant_journal.json instead of the published one")
    a = ap.parse_args(argv)
    run(a.out, pages_url=a.pages_url, journal_path=a.journal)


if __name__ == "__main__":
    sys.exit(main())
