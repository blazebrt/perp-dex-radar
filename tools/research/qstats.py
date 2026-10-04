"""Trade tables and statistics: R per trade after costs, profit factor, daily Sharpe, drawdown,
day-clustered standard errors, edge against random twins, in-sample / out-of-sample split."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from qsim import (R_COST, R_EXIT, R_FUND, R_GROSS, R_HOLD, R_MAE, R_MFE, R_NET, R_REASON, R_STOPP, REASONS)

H = 3600


def table(p, s, res, tw=None, name=""):
    i0 = s["i"] + 1
    d = pd.DataFrame({
        "strategy": name,
        "t_entry": p.t[i0],
        "t_exit": p.t[res[:, R_EXIT].astype(int)] + H,
        "coin": np.array(p.coins)[s["j"]],
        "d": s["d"].astype(int),
        "stop_pct": res[:, R_STOPP],
        "r": res[:, R_NET],
        "gross": res[:, R_GROSS],
        "cost": res[:, R_COST],
        "fund": res[:, R_FUND],
        "mfe": res[:, R_MFE],
        "mae": res[:, R_MAE],
        "hold": res[:, R_HOLD],
        "reason": [REASONS[int(x)] for x in res[:, R_REASON]],
    })
    if tw is not None:
        d["tw_r"] = tw[:, R_NET]
        d["tw_gross"] = tw[:, R_GROSS]
    return d


def _cl_se(x, days):
    """Day-clustered standard error of the mean (never below the plain one)."""
    n = len(x)
    if n < 2:
        return float("nan")
    m = x.mean()
    g = pd.Series(x - m).groupby(days).sum().to_numpy()
    se_cl = math.sqrt((g ** 2).sum()) / n
    se = x.std(ddof=1) / math.sqrt(n)
    return max(se, se_cl)


def stats(d, t0=None, t1=None, days_total=None):
    """Statistics of closed trades entered in [t0, t1)."""
    x = d[d["reason"] != "end"]
    if t0 is not None:
        x = x[x["t_entry"] >= t0]
    if t1 is not None:
        x = x[x["t_entry"] < t1]
    n = len(x)
    if n == 0:
        return {"n": 0}
    r = x["r"].to_numpy()
    g = x["gross"].to_numpy()
    days = (x["t_entry"] // 86400).to_numpy()
    wins = r[r > 0].sum()
    losses = -r[r < 0].sum()
    out = {
        "n": n,
        "wr": float((r > 0).mean()),
        "avg": float(r.mean()),
        "gross": float(g.mean()),
        "cost": float(x["cost"].mean()),
        "fund": float(x["fund"].mean()),
        "pf": float(wins / losses) if losses > 0 else float("inf"),
        "sum": float(r.sum()),
        "se": _cl_se(r, days),
        "days": int(len(np.unique(days))),
        "hold_h": float(x["hold"].median()),
        "stop_pct": float(x["stop_pct"].median()),
        "long_n": int((x["d"] > 0).sum()),
        "short_n": int((x["d"] < 0).sum()),
        "long_avg": float(x.loc[x["d"] > 0, "r"].mean()) if (x["d"] > 0).any() else None,
        "short_avg": float(x.loc[x["d"] < 0, "r"].mean()) if (x["d"] < 0).any() else None,
    }
    out["t"] = out["avg"] / out["se"] if out["se"] and out["se"] > 0 else float("nan")
    # daily P&L in R by exit day -> Sharpe and drawdown
    lo = t0 if t0 is not None else int(x["t_entry"].min())
    hi = t1 if t1 is not None else int(x["t_exit"].max())
    nd = max(1, int((hi - lo) // 86400) + 1)
    daily = np.zeros(nd)
    ex = ((x["t_exit"].to_numpy() - lo) // 86400).clip(0, nd - 1).astype(int)
    np.add.at(daily, ex, r)
    out["sharpe"] = float(daily.mean() / daily.std() * math.sqrt(365)) if daily.std() > 0 else float("nan")
    eq = np.cumsum(daily)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    out["maxdd"] = float((peak - eq).max())
    out["r_per_day"] = float(daily.mean())
    out["trades_per_day"] = n / nd
    # random twins: same order on a random coin at the same moment
    if "tw_gross" in x:
        ok = ~x["tw_gross"].isna()
        if ok.sum() > 1:
            diff = (x.loc[ok, "gross"] - x.loc[ok, "tw_gross"]).to_numpy()
            out["edge"] = float(diff.mean())
            out["edge_se"] = _cl_se(diff, days[ok.to_numpy()])
            out["edge_t"] = out["edge"] / out["edge_se"] if out["edge_se"] > 0 else float("nan")
            out["twin_avg"] = float(x.loc[ok, "tw_r"].mean())
    # months
    mon = pd.to_datetime(x["t_exit"], unit="s").dt.strftime("%Y-%m")
    m = x.groupby(mon)["r"].sum()
    out["months"] = {k: float(v) for k, v in m.items()}
    out["months_pos"] = float((m > 0).mean()) if len(m) else None
    return out


def fmt_row(name, s):
    if not s or s.get("n", 0) == 0:
        return f"{name:28s}   no trades"
    e = s.get("edge")
    es = f"{e:+.3f}±{s['edge_se']:.3f}" if e is not None else "      -     "
    return (f"{name:28s} n={s['n']:5d} win={s['wr'] * 100:3.0f}% net={s['avg']:+.3f}R (t={s['t']:+.1f}) "
            f"gross={s['gross']:+.3f} cost={s['cost']:.3f} pf={s['pf']:.2f} sharpe={s['sharpe']:+.2f} "
            f"dd={s['maxdd']:.0f}R vsTwin={es} L/S={s['long_n']}/{s['short_n']}")
