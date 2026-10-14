"""Phase D2 strategy definitions: Binance positioning (pre-registered in docs/v9/phase-d2-preregistration.md before
any test on market data).

    XS_TOP_DIV     daily: long the 5 eligible coins where top traders are most long relative to the crowd (the mean of
                   ln(top-trader position long/short ratio) - ln(all-accounts long/short ratio) over 3 days), short
                   the 5 where they are most short relative to it; 3-day hold
    XS_CROWD_FADE  daily: long the 5 eligible coins whose accounts are most short (the lowest 3-day mean of
                   ln(all-accounts long/short ratio)), short the 5 whose accounts are most long; 3-day hold

Both use the stop rule of every catalogue rotation: 2.5 daily ATRs (floor 1.5%, no trade above 20%), one trade per
coin at a time.

**One-day lag.** The metrics reach the live desk only through data.binance.vision's daily files, published after each
UTC day ends (fapi.binance.com is geo-blocked for the US runners). So the signal at the close of day D uses the
metrics through the end of day D-1: the 18 4-hour bars ending 6 bars (one day) before the decision bar. That is the
data a live implementation would have at the same moment. A coin needs at least 12 of those 18 bars.

The ranking, eligibility, trade rules, costs and simulator are the evidence engine's, as in D1 (tools/v9/d1.py).
Research only: nothing here reaches a live engine."""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "research"))
sys.path.insert(0, HERE)

import qdata  # noqa: E402
import qstrat  # noqa: E402
from d1 import _bottom, _top  # noqa: E402  (the same pandas average-rank rule as D1 and XSMOM)
from evidence import ArchivePanel  # noqa: E402

LAG_BARS = 6            # one UTC day of 4h bars: the daily file of day D is not out at day D's close
WINDOW_BARS = 18        # 3 days
MIN_BARS = 12           # of the 18
METRICS = ("oi", "oi_usd", "top_acct_ls", "top_pos_ls", "acct_ls", "taker_ls")


class D2Panel(ArchivePanel):
    """The archive panel plus Binance's metrics on the same grid (NaN where a coin has no metrics bar):
        m[name] for name in METRICS, [T, N], from md_metrics/m4/{COIN}.csv.gz (tools/v9/metrics_fetch.py)."""

    def __init__(self, md, metrics, **kw):
        super().__init__(md, **kw)
        T, N = len(self.t), len(self.coins)
        self.m = {k: np.full((T, N), np.nan) for k in METRICS}
        self.metrics_coins = 0
        for j, c in enumerate(self.coins):
            path = os.path.join(metrics, "m4", f"{c}.csv.gz")
            if not os.path.exists(path):
                continue
            head, rows = qdata._read(path)
            if not rows:
                continue
            self.metrics_coins += 1
            idx = (np.array([int(r[0]) for r in rows]) - int(self.t[0])) // self.bar
            ok = (idx >= 0) & (idx < T)
            for k in METRICS:
                if k not in head:
                    continue
                col = head.index(k)
                val = np.array([float(r[col]) if r[col] != "" else np.nan for r in rows])
                self.m[k][idx[ok], j] = val[ok]


def _lag(x, k):
    out = np.full_like(x, np.nan)
    out[k:] = x[:-k]
    return out


def _trailing_mean(x, n, minp):
    """Mean of the finite values among the trailing n rows; NaN with fewer than minp of them. [T, N]."""
    fin = np.isfinite(x)
    cs = np.cumsum(np.where(fin, x, 0.0), axis=0)
    cn = np.cumsum(fin, axis=0)
    s, c = cs.copy(), cn.copy()
    s[n:] = cs[n:] - cs[:-n]
    c[n:] = cn[n:] - cn[:-n]
    with np.errstate(all="ignore"):
        return np.where(c >= minp, s / np.where(c > 0, c, 1), np.nan)


def _ln(x):
    with np.errstate(all="ignore"):
        return np.where(np.isfinite(x) & (x > 0), np.log(np.where(x > 0, x, 1.0)), np.nan)


def lagged_mean(p, x):
    """The value a live desk would hold at each bar: the mean over the 18 bars that end one day earlier."""
    return _trailing_mean(_lag(x, LAG_BARS), WINDOW_BARS, MIN_BARS)


def xs_top_divergence(F, hold_days=3, top=5, stop_k=2.5, sides="both"):
    """Long where top traders are most long relative to the crowd, short where they are most short relative to it."""
    p, b = F.p, F.bd
    end = b["end"]
    div = lagged_mean(p, _ln(p.m["top_pos_ls"]) - _ln(p.m["acct_ls"]))[end]
    s = np.where(F.elig[end], div, np.nan)
    return qstrat._on_bars(F, b, _top(s, top), _bottom(s, top), stop_k, 0.0, hold_days * 24, sides=sides)


def xs_crowd_fade(F, hold_days=3, top=5, stop_k=2.5, sides="both"):
    """Long where the crowd's accounts are most short, short where they are most long."""
    p, b = F.p, F.bd
    end = b["end"]
    crowd = lagged_mean(p, _ln(p.m["acct_ls"]))[end]
    s = np.where(F.elig[end], crowd, np.nan)
    return qstrat._on_bars(F, b, _bottom(s, top), _top(s, top), stop_k, 0.0, hold_days * 24, sides=sides)


STRATEGIES = {"XS_TOP_DIV": (xs_top_divergence, {}), "XS_CROWD_FADE": (xs_crowd_fade, {})}
