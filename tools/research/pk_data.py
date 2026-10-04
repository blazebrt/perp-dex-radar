"""Coin-score research data: daily bars built from the 4h market data, the coin checks (factors), what
happened next (forward returns, best gain and worst drop within 30 days) and the market state.

Every value at day k uses candles up to the close of day k only."""
from __future__ import annotations

import numpy as np
import pandas as pd

import qind as I
import qstrat
from qdata import Panel, resample

DAYB = 6  # 4h bars per day


def daily_panel(md):
    p = Panel(md, folder="h4", bar=14400, min_hours=24 * 60)
    F = qstrat.Feat(p)
    t, o, h, l, c, v, end = resample(p, DAYB)
    elig = F.elig[end]
    e20, e100 = I.ema(p.c, 20), I.ema(p.c, 100)
    with np.errstate(all="ignore"):
        trend4h = (e20 / e100 - 1)[end]
    f = p.fund
    K = len(end)
    fund_d = np.zeros((K, p.N))
    for k in range(K):
        a = end[k] - DAYB + 1
        fund_d[k] = f[a:end[k] + 1].sum(axis=0)
    return p, {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "elig": elig, "trend4h": trend4h, "fund": fund_d,
               "coins": p.coins}


def factors(d):
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    r1 = I.ret(c, 1)
    vol30 = I.rstd(r1, 30, minp=20)
    btc = c[:, 0:1]
    with np.errstate(all="ignore"):
        Fx = {}
        Fx["mom30"] = I.ret(c, 30)
        Fx["mom7"] = I.ret(c, 7)
        Fx["trend50"] = c / I.ema(c, 50) - 1
        Fx["rs30"] = I.ret(c, 30) - I.ret(btc, 30)
        Fx["vmom14"] = I.ret(c, 14) / vol30
        Fx["dd90"] = c / I.rmax(h, 90) - 1
        Fx["up90"] = c / I.rmin(l, 90) - 1
        Fx["ddall"] = c / pd.DataFrame(h).cummax().to_numpy() - 1
        w, _, _ = I.boll_width(c, 20, 2.0)
        Fx["squeeze"] = I.pct_rank(w, 90, minp=45)
        Fx["volup"] = I.sma(v, 7) / I.sma(v, 30)
        upv = np.where(r1 > 0, v, 0.0)
        dnv = np.where(r1 < 0, v, 0.0)
        Fx["updown"] = I.sma(upv, 14, minp=10) / I.sma(dnv, 14, minp=10)
        Fx["brk20"] = c / I.rmax(h, 20) - 1
        Fx["trend4h"] = d["trend4h"]
        Fx["rsi14"] = I.rsi(c, 14)
        f = d["fund"]
        Fx["fund3"] = I.sma(f, 3)
        Fx["higherlow"] = I.rmin(l, 10) / I.shift(I.rmin(l, 10), 10) - 1
        Fx["size"] = np.log(I.sma(v, 30))
        Fx["volat"] = vol30
        Fx["vwap30"] = c / (I.sma(c * v, 30) / I.sma(v, 30)) - 1
        Fx["atrp"] = I.atr(h, l, c, 14) / c
        Fx["lower_high"] = (I.rmax(h, 10) < I.shift(I.rmax(h, 10), 10)).astype(float)
    return Fx


def forward(d):
    c, h, l = d["c"], d["h"], d["l"]
    out = {}
    with np.errstate(all="ignore"):
        for hz in (1, 7, 30):
            out[f"fwd{hz}"] = I.shift(c, -hz) / c - 1
        hi30 = I.shift(pd.DataFrame(h[::-1]).rolling(30, min_periods=1).max().to_numpy()[::-1], -1)
        lo30 = I.shift(pd.DataFrame(l[::-1]).rolling(30, min_periods=1).min().to_numpy()[::-1], -1)
        out["max30"] = hi30 / c - 1
        out["min30"] = lo30 / c - 1
    return out


def regimes(d):
    """BTC above its 50-day EMA, and the share of eligible coins above theirs, per day."""
    c = d["c"]
    e50 = I.ema(c, 50)
    with np.errstate(all="ignore"):
        btc_up = c[:, 0] > e50[:, 0]
        above = (c > e50) & d["elig"]
        breadth = above.sum(1) / np.maximum(d["elig"].sum(1), 1)
    return btc_up, breadth
