"""Account simulation and growth planner.

simulate(): replays trades in time order on a $ account with fixed-fractional risk, a cap on open positions
and on leverage. growth_planner(): bootstraps whole days of the backtest's results into thousands of
2-year paths for several risk levels and reports the odds of each outcome."""
from __future__ import annotations

import heapq
import math

import numpy as np
import pandas as pd


def simulate(trades, start=500.0, risk=0.01, max_open=12, max_per_strategy=4, max_lev_pos=5.0, max_lev_total=10.0,
             ruin=0.1):
    """trades: DataFrame with strategy, coin, t_entry, t_exit, r (net R per trade), stop_pct.
    Returns (equity events, summary, mask of the trades taken)."""
    x = trades.sort_values("t_entry")
    eq = start
    open_pos = []  # heap of (t_exit, id, risk_usd, r, notional, strategy, coin)
    rows = []
    peak, maxdd = eq, 0.0
    taken = skipped = 0
    lev_used = 0.0
    per = {}
    coins_open = set()
    took = np.zeros(len(x), dtype=bool)
    for k, t in enumerate(x.itertuples(index=False)):
        while open_pos and open_pos[0][0] <= t.t_entry:
            te, _, ru, r, notional, st, cn = heapq.heappop(open_pos)
            eq += ru * r
            lev_used -= notional
            per[st] -= 1
            coins_open.discard((st, cn))
            peak = max(peak, eq)
            maxdd = max(maxdd, 1 - eq / peak) if peak > 0 else 1.0
            rows.append((te, eq))
        if eq <= start * ruin:
            break
        if len(open_pos) >= max_open or per.get(t.strategy, 0) >= max_per_strategy:
            skipped += 1
            continue
        ru = risk * eq
        notional = ru / t.stop_pct
        notional = min(notional, max_lev_pos * eq, max(0.0, max_lev_total * eq - lev_used))
        if notional <= 0:
            skipped += 1
            continue
        ru = notional * t.stop_pct
        lev_used += notional
        per[t.strategy] = per.get(t.strategy, 0) + 1
        coins_open.add((t.strategy, t.coin))
        heapq.heappush(open_pos, (t.t_exit, k, ru, t.r, notional, t.strategy, t.coin))
        took[k] = True
        taken += 1
    while open_pos:
        te, _, ru, r, notional, _, _ = heapq.heappop(open_pos)
        eq += ru * r
        peak = max(peak, eq)
        maxdd = max(maxdd, 1 - eq / peak) if peak > 0 else 1.0
        rows.append((te, eq))
    ev = pd.DataFrame(rows, columns=["t", "equity"])
    mask = pd.Series(took, index=x.index).reindex(trades.index).to_numpy()
    return ev, {"final": eq, "maxdd": maxdd, "taken": taken, "skipped": skipped,
                "multiple": eq / start}, mask


def daily_r(trades, t0, t1):
    """Sum of R per calendar day (by exit time) over [t0, t1)."""
    nd = int((t1 - t0) // 86400)
    out = np.zeros(nd)
    x = trades[(trades["t_exit"] >= t0) & (trades["t_exit"] < t1)]
    idx = ((x["t_exit"].to_numpy() - t0) // 86400).astype(int)
    np.add.at(out, idx, x["r"].to_numpy())
    return out


def kelly(daily):
    """Growth-optimal fraction for daily R sums (continuous approximation, capped)."""
    m, v = daily.mean(), daily.var()
    return max(0.0, m / v) if v > 0 else 0.0


def growth_planner(daily, start=500.0, days=730, risks=(0.0025, 0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10),
                   paths=5000, haircut=0.0, targets=(1_000, 10_000, 100_000, 1_000_000), seed=1, block=5):
    """Block-bootstrap `block`-day chunks of daily R into `days`-day paths; compound at each risk level.
    haircut: subtract this share of the mean daily R (live results usually fall short of the backtest)."""
    rng = np.random.default_rng(seed)
    d = daily - haircut * daily.mean() if daily.mean() > 0 else daily.copy()
    n = len(d)
    nb = math.ceil(days / block)
    starts = rng.integers(0, n - block + 1, size=(paths, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(paths, -1)[:, :days]
    sims = d[idx]  # [paths, days]
    out = []
    for f in risks:
        g = np.clip(1 + f * sims, 0.0, None)
        logw = np.cumsum(np.log(np.where(g > 0, g, 1e-12)), axis=1)
        w = start * np.exp(logw)
        ruined = (g <= 0.0).any(axis=1) | (w.min(axis=1) <= start * 0.1)
        final = np.where(ruined, np.minimum(w[:, -1], start * 0.1), w[:, -1])
        peak = np.maximum.accumulate(np.concatenate([np.full((paths, 1), start), w], axis=1), axis=1)[:, 1:]
        dd = (1 - w / peak).max(axis=1)
        row = {"risk": f, "median": float(np.median(final)), "p10": float(np.percentile(final, 10)),
               "p90": float(np.percentile(final, 90)), "p_loss": float((final < start).mean()),
               "p_dd50": float((dd >= 0.5).mean()), "p_dd90": float((dd >= 0.9).mean()),
               "p_ruin": float(ruined.mean())}
        for tg in targets:
            row[f"p_{tg}"] = float((final >= tg).mean())
        out.append(row)
    return pd.DataFrame(out)
