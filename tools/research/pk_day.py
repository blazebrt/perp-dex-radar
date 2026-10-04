"""Day-trade research on hourly candles: the hourly checks used by picks.py, trade results (1.5 ATR stop,
2.5 ATR trail, 24 hours at most, costs) and the day score by band and the Top 5 every 4 hours."""
from __future__ import annotations

import numpy as np

import qind as I
import qstrat
from pk_trades import COST, sim
from qdata import Panel

DAY_W = {"swing": 25, "trend1d": 10, "trend4h": 10, "trend1h": 10, "near_edge": 10, "no_chase": 10, "calm": 10,
         "trend30": 5, "funding": 5, "volume": 5}


def hourly(md):
    p = Panel(md)
    F = qstrat.Feat(p)
    h, l, c, v = p.h, p.l, p.c, p.v
    with np.errstate(all="ignore"):
        x = {
            "r4h": I.ret(c, 4), "ema9_21": I.ema(c, 9) / I.ema(c, 21) - 1,
            "vol24_7d": I.sma(v, 24) / I.sma(v, 168), "brk24": c / I.rmax(h, 24) - 1,
            "dist_low24": c / I.rmin(l, 24) - 1, "trend4h": I.ema(c, 80) / I.ema(c, 400) - 1,
            "trend1d": c / I.ema(c, 50 * 24) - 1, "funding": I.ffill(np.where(p.fund != 0, p.fund, np.nan)),
            "atrp": F.atr1 / c, "dd30d": c / I.rmax(h, 720) - 1,
        }
    return p, F, x


def day_checks(x, sw_long, sw_short):
    with np.errstate(invalid="ignore"):
        L = {"swing": np.where(sw_long >= 70, 1.0, np.where(sw_long >= 50, 0.4, 0.0)),
             "trend1d": x["trend1d"] > 0, "trend4h": x["trend4h"] > 0, "trend1h": x["ema9_21"] > 0,
             "near_edge": x["brk24"] >= -0.03, "no_chase": x["r4h"] <= 0.02, "calm": x["atrp"] <= 0.015,
             "trend30": x["dd30d"] >= -0.15, "funding": x["funding"] <= 0.0001, "volume": x["vol24_7d"] >= 1.0}
        S = {"swing": np.where(sw_short >= 70, 1.0, np.where(sw_short >= 50, 0.4, 0.0)),
             "trend1d": x["trend1d"] < 0, "trend4h": x["trend4h"] < 0, "trend1h": x["ema9_21"] < 0,
             "near_edge": x["dist_low24"] <= 0.03, "no_chase": x["r4h"] >= -0.02, "calm": x["atrp"] <= 0.015,
             "trend30": x["dd30d"] <= -0.25, "funding": x["funding"] >= 0.0, "volume": x["vol24_7d"] >= 1.0}
    return ({k: np.asarray(v, float) for k, v in L.items()}, {k: np.asarray(v, float) for k, v in S.items()})


def run(md, swing_t, swing_coins, SL, SS):
    """Day score bands and the Top 5 every 4 hours, long and short (swing scores mapped to each hour)."""
    p, F, x = hourly(md)
    th = p.t
    T, N = p.c.shape
    day_idx = np.searchsorted(np.asarray(swing_t) + 86400, th, side="right") - 1
    col = [list(swing_coins).index(c) if c in swing_coins else -1 for c in p.coins]

    def to_h(a):
        out = np.full((T, N), np.nan)
        ok = day_idx >= 0
        for j, cj in enumerate(col):
            if cj >= 0:
                out[ok, j] = a[day_idx[ok], cj]
        return out

    L, S = day_checks(x, np.nan_to_num(to_h(SL)), np.nan_to_num(to_h(SS)))
    out = {"period": [int(th[24 * 40]), int(th[-1])], "coins": N}
    for side, sgn, C in (("long", 1, L), ("short", -1, S)):
        R, RET, _, _ = sim(p.o, p.h, p.l, p.c, F.atr1, sgn, 1.5, 2.5, 24, 0.015, 0.06, COST)
        sc = sum(DAY_W[k] * C[k] for k in DAY_W)
        sample = np.zeros((T, N), bool)
        sample[24 * 40::4] = True
        base = F.elig & np.isfinite(R) & sample
        bands = []
        for lo, hi in ((0, 50), (50, 70), (70, 80), (80, 90), (90, 101)):
            m = base & (sc >= lo) & (sc < hi)
            if m.sum() >= 30:
                bands.append({"lo": lo, "hi": hi, "n": int(m.sum()), "R": float(np.nanmean(R[m])),
                              "ret": float(np.nanmean(RET[m])), "win": float(np.mean(RET[m] > 0))})
        top = []
        for k in range(24 * 40, T - 24, 4):
            m = F.elig[k] & np.isfinite(R[k])
            if m.sum() < 30:
                continue
            idx = np.where(m)[0]
            pk = idx[np.argsort(sc[k, idx] + 1e-3 * np.random.default_rng(k).random(len(idx)))][-5:]
            top.append((R[k, pk].mean(), RET[k, pk].mean(), R[k, m].mean(), RET[k, m].mean()))
        a = np.array(top)
        out[side] = {"bands": bands, "base": {"R": float(np.nanmean(R[base])), "ret": float(np.nanmean(RET[base]))},
                     "top5": {"R": float(a[:, 0].mean()), "ret": float(a[:, 1].mean()), "R_all": float(a[:, 2].mean()),
                              "ret_all": float(a[:, 3].mean()), "n": len(a)}}
    return out
