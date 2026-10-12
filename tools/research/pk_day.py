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


def hourly(md, end=None):
    """The hourly panel, its features and the day-pick inputs (`end`: no candle after it; None = all of them)."""
    p = Panel(md, end=end)
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


BANDS = ((0, 50), (50, 70), (70, 80), (80, 90), (90, 101))
FIRST = 24 * 40          # the first sampled hour (40 days of history for the features)
EVERY = 4                # a sample every 4 hours
MIN_ROWS = 30            # a band or a Top-5 sample needs 30+ rows
HOLD = 24                # a day trade is held 24 hours at most


def simulate(p, F):
    """Day-trade results for every coin and hour, long and short (1.5 ATR stop, 2.5 ATR trail, 24 hours, costs)."""
    out = {}
    for side, sgn in (("long", 1), ("short", -1)):
        R, RET, _, BARS = sim(p.o, p.h, p.l, p.c, F.atr1, sgn, 1.5, 2.5, HOLD, 0.015, 0.06, COST)
        out[side] = (R, RET, BARS)
    return out


def surfaces(p, F, x, swing_t, swing_coins, SL, SS, elig=None, sims=None, known=None):
    """The day-pick selection authority: per side the day score (DAY_W over day_checks, swing scores mapped to each
    hour), the 4-hour sample, the eligible base, the score bands (masks of 30+ rows) and the deterministic Top 5
    every 4 hours (score order, ties broken by a 1e-3 jitter seeded by the hour). run() reports these surfaces; the
    point-in-time research qualifies exactly these rows. `elig` defaults to the strategy's own eligibility (F.elig);
    `sims` reuses simulate().

    `known` (point-in-time research only; None = these legacy surfaces exactly): where x["funding"] is a known value
    at that hour. A row whose funding is unknown never enters the base or a band. A 4-hour Top 5 is selected among
    the same candidates and jitter as without it, from rows with known funding only, and only when no candidate with
    unknown funding could reach it even with the funding check's full points; otherwise that sample is undetermined
    (listed, never selected)."""
    elig = F.elig if elig is None else elig
    sims = simulate(p, F) if sims is None else sims
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
    out = {}
    for side, C in (("long", L), ("short", S)):
        R, RET, BARS = sims[side]
        sc = sum(DAY_W[k] * C[k] for k in DAY_W)
        sample = np.zeros((T, N), bool)
        sample[FIRST::EVERY] = True
        base = elig & np.isfinite(R) & sample
        if known is not None:
            base = base & known
        bands = []
        for lo, hi in BANDS:
            m = base & (sc >= lo) & (sc < hi)
            if m.sum() >= MIN_ROWS:
                bands.append((lo, hi, m))
        top, undetermined = [], []
        for k in range(FIRST, T - HOLD, EVERY):
            m = elig[k] & np.isfinite(R[k])
            if m.sum() < MIN_ROWS:
                continue
            idx = np.where(m)[0]
            if known is None:
                pk = idx[np.argsort(sc[k, idx] + 1e-3 * np.random.default_rng(k).random(len(idx)))][-5:]
            else:
                key = sc[k, idx] + 1e-3 * np.random.default_rng(k).random(len(idx))
                kn = known[k, idx]
                order = np.argsort(key[kn])
                # the best case of a row with unknown funding: its score without the funding check plus its full points
                best = key - DAY_W["funding"] * C["funding"][k, idx] + DAY_W["funding"]
                if kn.sum() < 5 or ((~kn).any() and (best[~kn] >= key[kn][order[-5]]).any()):
                    undetermined.append(k)
                    continue
                pk = idx[kn][order][-5:]
            top.append((k, pk, m))
        out[side] = {"R": R, "RET": RET, "BARS": BARS, "score": sc, "sample": sample, "base": base, "bands": bands,
                     "top": top}
        if known is not None:
            out[side]["undetermined"] = undetermined
    return out


def run(md, swing_t, swing_coins, SL, SS):
    """Day score bands and the Top 5 every 4 hours, long and short (swing scores mapped to each hour)."""
    p, F, x = hourly(md)
    th = p.t
    T, N = p.c.shape
    surf = surfaces(p, F, x, swing_t, swing_coins, SL, SS)
    out = {"period": [int(th[FIRST]), int(th[-1])], "coins": N}
    for side in ("long", "short"):
        s = surf[side]
        R, RET, base = s["R"], s["RET"], s["base"]
        bands = [{"lo": lo, "hi": hi, "n": int(m.sum()), "R": float(np.nanmean(R[m])),
                  "ret": float(np.nanmean(RET[m])), "win": float(np.mean(RET[m] > 0))} for lo, hi, m in s["bands"]]
        top = [(R[k, pk].mean(), RET[k, pk].mean(), R[k, m].mean(), RET[k, m].mean()) for k, pk, m in s["top"]]
        a = np.array(top)
        out[side] = {"bands": bands, "base": {"R": float(np.nanmean(R[base])), "ret": float(np.nanmean(RET[base]))},
                     "top5": {"R": float(a[:, 0].mean()), "ret": float(a[:, 1].mean()), "R_all": float(a[:, 2].mean()),
                              "ret_all": float(a[:, 3].mean()), "n": len(a)}}
    return out
