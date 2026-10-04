"""The swing scores shown on the picks page (picks.py computes the same numbers live, see parity_picks.py).

Long  'Coiled bottom'   : near the 90-day low, momentum back (RSI > 45), volatility squeezed, tight range,
                          calm daily moves, up over 30 days, higher low, BTC uptrend, volume waking up.
Short 'Downtrend bounce': below the 50-day EMA, down over 30 days, bounced (RSI > 50), not near the 90-day
                          low, lower high, 4h downtrend, weaker than BTC, heavier selling volume, below VWAP."""
from __future__ import annotations

import numpy as np

LONG_W = {"near_low": 25, "rsi": 20, "squeeze": 15, "tight": 10, "calm": 10, "mom30": 5, "higher_low": 5,
          "btc_up": 5, "volume": 5}
SHORT_W = {"below_ema": 15, "down30": 15, "bounce": 25, "off_low": 20, "lower_high": 5, "down4h": 5,
           "weaker_btc": 5, "down_volume": 5, "below_vwap": 5}


def long_checks(F, up):
    with np.errstate(invalid="ignore"):
        u90, rsi, sq = F["up90"], F["rsi14"], F["squeeze"]
        return {
            "near_low": np.where(u90 <= 0.30, 1.0, np.where(u90 <= 0.45, 0.4, 0.0)),
            "rsi": np.where(rsi > 45, 1.0, np.where(rsi > 40, 0.4, 0.0)),
            "squeeze": np.where(sq <= 0.2, 1.0, np.where(sq <= 0.35, 0.4, 0.0)),
            "tight": (F["dd90"] >= -0.30).astype(float),
            "calm": np.where(F["atrp"] <= 0.05, 1.0, np.where(F["atrp"] <= 0.065, 0.5, 0.0)),
            "mom30": (F["mom30"] > 0).astype(float),
            "higher_low": (F["higherlow"] > 0).astype(float),
            "btc_up": up.astype(float),
            "volume": (F["volup"] >= 1.2).astype(float),
        }


def short_checks(F, up):
    with np.errstate(invalid="ignore"):
        rsi = F["rsi14"]
        return {
            "below_ema": (F["trend50"] < 0).astype(float),
            "down30": (F["mom30"] < 0).astype(float),
            "bounce": np.where(rsi > 50, 1.0, np.where(rsi > 45, 0.4, 0.0)),
            "off_low": (F["up90"] > 0.25).astype(float),
            "lower_high": F["lower_high"],
            "down4h": (F["trend4h"] < 0).astype(float),
            "weaker_btc": (F["rs30"] < 0).astype(float),
            "down_volume": (F["updown"] < 1).astype(float),
            "below_vwap": (F["vwap30"] < 0).astype(float),
        }


def scores(F, btc_up):
    N = F["up90"].shape[1]
    up = np.repeat(btc_up[:, None], N, 1)
    valid = np.isfinite(F["up90"]) & np.isfinite(F["rsi14"]) & np.isfinite(F["squeeze"])
    CL, CS = long_checks(F, up), short_checks(F, up)
    SL = np.where(valid, sum(LONG_W[k] * CL[k] for k in LONG_W), np.nan)
    SS = np.where(valid, sum(SHORT_W[k] * CS[k] for k in SHORT_W), np.nan)
    return SL, SS, CL, CS


def account(scores_by_side, labs, elig, t, start, end, thr, max_pos, risk, sides=("long", "short")):
    """Each day open the best-scored setups (score >= thr, one position per coin) until max_pos are open;
    a stop loses `risk` of the account at entry; profits and losses are booked on the exit day.
    labs[side] = (R, bars_held). Returns (daily equity, trades)."""
    K, N = elig.shape
    eq = 1.0
    open_ = []
    curve = np.full(K, np.nan)
    trades = []
    for k in range(K):
        if t[k] < start or t[k] > end:
            continue
        keep = []
        for ex, pnl, j in open_:
            if ex <= k:
                eq += pnl
            else:
                keep.append((ex, pnl, j))
        open_ = keep
        curve[k] = eq
        held = {j for _, _, j in open_}
        cand = []
        for s in sides:
            sc, R = scores_by_side[s], labs[s][0]
            m = elig[k] & np.isfinite(sc[k]) & (sc[k] >= thr) & np.isfinite(R[k])
            cand += [(sc[k, j], s, j) for j in np.where(m)[0] if j not in held]
        cand.sort(key=lambda x: -x[0])
        for scv, s, j in cand:
            if len(open_) >= max_pos:
                break
            if j in held:
                continue
            R, bars = labs[s][0][k, j], labs[s][1][k, j]
            open_.append((k + 1 + int(bars), eq * risk * R, j))
            held.add(j)
            trades.append((k, j, s, scv, R))
    return curve, trades
