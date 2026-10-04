"""Trade simulation on hourly bars, long and short. Conservative: a bar that touches both the stop and
the target counts as the stop; the trailing stop moves at the bar close and applies from the next bar;
gaps through the stop exit at the open. Costs: taker fee + slippage for market orders (entries, stops,
time exits), maker fee for take-profit limits, funding while held (longs pay positive funding)."""
from __future__ import annotations

import numba as nb
import numpy as np

REASONS = ("stop", "target", "trail", "time", "end", "gap")
FEE_T, FEE_M = 0.00045, 0.00015

# result columns
R_EXIT, R_REASON, R_GROSS, R_NET, R_COST, R_FUND, R_MFE, R_MAE, R_HOLD, R_ENTRY, R_STOPP, R_EXITPX = range(12)
NCOL = 12


@nb.njit(cache=True)
def _sim_one(o, h, l, c, fund, j, i0, d, stop_pct, target_r, trail_pct, be_r, max_hold, slip, fee_t, fee_m,
             out, k):
    T = o.shape[0]
    entry = o[i0, j]
    if not (entry > 0) or not (stop_pct > 0):
        return -1
    risk = entry * stop_pct
    stop = entry - d * risk
    stop0 = stop
    target = entry + d * target_r * risk
    trail = entry * trail_pct
    best = entry
    fund_sum = 0.0
    mfe = 0.0
    mae = 0.0
    exit_px = np.nan
    reason = 4
    exit_i = -1
    last = i0 + max_hold - 1
    if last > T - 1:
        last = T - 1
    for i in range(i0, last + 1):
        ci = c[i, j]
        if np.isnan(ci):
            exit_i = i - 1
            exit_px = c[i - 1, j]
            reason = 4
            break
        if i > i0:
            fund_sum += fund[i, j]
        oi, hi, li = o[i, j], h[i, j], l[i, j]
        if d > 0:
            fav = (hi - entry) / risk
            adv = (entry - li) / risk
        else:
            fav = (entry - li) / risk
            adv = (hi - entry) / risk
        # stop first
        if d > 0:
            if i > i0 and oi <= stop:
                exit_px = oi
                reason = 5
            elif li <= stop:
                exit_px = stop
                reason = 2 if stop > stop0 else 0
            elif target_r > 0 and hi >= target:
                exit_px = target
                reason = 1
        else:
            if i > i0 and oi >= stop:
                exit_px = oi
                reason = 5
            elif hi >= stop:
                exit_px = stop
                reason = 2 if stop < stop0 else 0
            elif target_r > 0 and li <= target:
                exit_px = target
                reason = 1
        if reason != 4:
            if reason == 1:
                if fav > mfe:
                    mfe = fav
            elif adv > mae:
                mae = adv
            exit_i = i
            break
        if fav > mfe:
            mfe = fav
        if adv > mae:
            mae = adv
        # end of bar: move the trailing stop / breakeven for the next bar
        if trail > 0:
            if d > 0:
                if ci > best:
                    best = ci
                if best - trail > stop:
                    stop = best - trail
            else:
                if ci < best:
                    best = ci
                if best + trail < stop:
                    stop = best + trail
        if be_r > 0 and fav >= be_r:
            if d > 0 and entry > stop:
                stop = entry
            elif d < 0 and entry < stop:
                stop = entry
        if i == last:
            exit_px = ci
            exit_i = i
            reason = 3 if i == i0 + max_hold - 1 else 4
            break
    if exit_i < 0:
        return -1
    gross = d * (exit_px - entry) / entry
    cost = fee_t + slip
    if reason == 1:
        cost += fee_m
    else:
        cost += fee_t + slip
    fcost = d * fund_sum
    out[k, R_EXIT] = exit_i
    out[k, R_REASON] = reason
    out[k, R_GROSS] = gross / stop_pct
    out[k, R_NET] = (gross - cost - fcost) / stop_pct
    out[k, R_COST] = (cost + fcost) / stop_pct
    out[k, R_FUND] = fcost / stop_pct
    out[k, R_MFE] = mfe
    out[k, R_MAE] = mae
    out[k, R_HOLD] = exit_i - i0 + 1
    out[k, R_ENTRY] = entry
    out[k, R_STOPP] = stop_pct
    out[k, R_EXITPX] = exit_px
    return exit_i


@nb.njit(cache=True)
def sim_batch(o, h, l, c, fund, slip, si, sj, sd, sstop, starget, strail, sbe, shold, one_at_a_time, fee_t, fee_m):
    """Signals must be sorted by time. Entry at the open of the bar after the signal bar."""
    n = si.shape[0]
    N = o.shape[1]
    T = o.shape[0]
    out = np.full((n, NCOL), np.nan)
    busy = np.full(N, -1)
    for k in range(n):
        i0 = si[k] + 1
        j = sj[k]
        if i0 >= T:
            continue
        if one_at_a_time and i0 <= busy[j]:
            continue
        e = _sim_one(o, h, l, c, fund, j, i0, sd[k], sstop[k], starget[k], strail[k], sbe[k], shold[k], slip[j],
                     fee_t, fee_m, out, k)
        if e >= 0:
            busy[j] = e
    return out


@nb.njit(cache=True)
def sim_twins(o, h, l, c, fund, slip, elig, si, sj, sd, sstop, starget, strail, sbe, shold, seed, fee_t, fee_m):
    """The same order (direction, stop %, target, trail, hold) on a random other eligible coin at the same time."""
    np.random.seed(seed)
    n = si.shape[0]
    N = o.shape[1]
    T = o.shape[0]
    out = np.full((n, NCOL), np.nan)
    twin_j = np.full(n, -1)
    for k in range(n):
        i0 = si[k] + 1
        if i0 >= T:
            continue
        cnt = 0
        for jj in range(N):
            if jj != sj[k] and elig[si[k], jj] and o[i0, jj] > 0:
                cnt += 1
        if cnt == 0:
            continue
        pick = np.random.randint(cnt)
        jj2 = -1
        for jj in range(N):
            if jj != sj[k] and elig[si[k], jj] and o[i0, jj] > 0:
                if pick == 0:
                    jj2 = jj
                    break
                pick -= 1
        twin_j[k] = jj2
        _sim_one(o, h, l, c, fund, jj2, i0, sd[k], sstop[k], starget[k], strail[k], sbe[k], shold[k], slip[jj2],
                 fee_t, fee_m, out, k)
    return out, twin_j


def run(p, sig, one_at_a_time=True, twins=True, elig=None, seed=7):
    """sig: dict of arrays i, j, d, stop, target, trail, be, hold (any order). Returns (signals_sorted, res, twin_res)."""
    order = np.lexsort((sig["j"], sig["i"]))
    s = {k: np.asarray(v)[order] for k, v in sig.items()}
    args = (s["i"].astype(np.int64), s["j"].astype(np.int64), s["d"].astype(np.float64),
            s["stop"].astype(np.float64), s["target"].astype(np.float64), s["trail"].astype(np.float64),
            s["be"].astype(np.float64), s["hold"].astype(np.int64))
    res = sim_batch(p.o, p.h, p.l, p.c, p.fund, p.slip(), *args, one_at_a_time, FEE_T, FEE_M)
    taken = ~np.isnan(res[:, R_EXIT])
    s = {k: v[taken] for k, v in s.items()}
    res = res[taken]
    tw = None
    if twins and len(res):
        targs = (s["i"].astype(np.int64), s["j"].astype(np.int64), s["d"].astype(np.float64),
                 s["stop"].astype(np.float64), s["target"].astype(np.float64), s["trail"].astype(np.float64),
                 s["be"].astype(np.float64), s["hold"].astype(np.int64))
        tw, tj = sim_twins(p.o, p.h, p.l, p.c, p.fund, p.slip(), elig, *targs, seed, FEE_T, FEE_M)
        s["twin_j"] = tj
    return s, res, tw
