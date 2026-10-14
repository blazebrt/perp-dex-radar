"""Phase D1 strategy definitions (pre-registered in docs/v9/phase-d1-preregistration.md before any test on market data).

    XS_FUND_FADE   daily: long the 5 eligible coins with the lowest funding paid by longs over the last 3 days,
                   short the 5 with the highest; 7-day hold; stop 2.5 daily ATRs (floor 1.5%, no trade above 20%);
                   one trade per coin at a time
    XS_FLOW_MOM    daily: long the 5 eligible coins with the highest taker-buy share of quote volume over the last
                   3 days, short the 5 with the lowest; 3-day hold; the same stop rule

XS_FUND_FADE is not the legacy 1-hour FUND_FADE (qstrat.funding_fade: absolute funding thresholds, 48-hour hold).
Both are cross-sectional rotations evaluated at the daily close on the evidence engine's point-in-time eligible
coins, built with the research library's own bar and signal helpers (qstrat._on_bars), so trade rules, costs and the
simulator are the ones every other candidate uses. Research only: nothing here reaches a live engine."""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "research"))
sys.path.insert(0, HERE)

import qdata  # noqa: E402
import qind as I  # noqa: E402
import qstrat  # noqa: E402
from evidence import ArchivePanel  # noqa: E402

MIN_SETTLEMENTS = 3


class D1Panel(ArchivePanel):
    """The archive panel plus two arrays the D1 definitions need, on the same grid:
        tb       taker-buy quote volume per bar (column tbqv of the archive's h4 files; 0 on a filled empty bar)
        fund_n   the number of observed funding settlements per bar (so a missing funding file is never zero funding)"""

    def __init__(self, md, **kw):
        super().__init__(md, **kw)
        T, N = len(self.t), len(self.coins)
        self.tb = np.full((T, N), np.nan)
        for j, c in enumerate(self.coins):
            head, rows = qdata._read(os.path.join(md, "h4", f"{c}.csv.gz"))
            if "tbqv" not in head or not rows:
                continue
            k = head.index("tbqv")
            idx = (np.array([int(r[0]) for r in rows]) - int(self.t[0])) // self.bar
            val = np.array([float(r[k]) if r[k] != "" else np.nan for r in rows])
            ok = (idx >= 0) & (idx < T)
            self.tb[idx[ok], j] = val[ok]
        self.tb = np.where(self.v == 0, 0.0, self.tb)        # a filled empty bar traded nothing

    def _funding(self, md):
        f = super()._funding(md)
        T, N = len(self.t), len(self.coins)
        self.fund_n = np.zeros((T, N))
        for j, c in enumerate(self.coins):
            path = os.path.join(md, "fund_bn", f"{c}.csv.gz")
            if not os.path.exists(path):
                continue
            _, rows = qdata._read(path)
            for row in rows:
                i = (int(row[0]) - int(self.t[0])) // self.bar
                if 0 <= i < T and row[1] != "":
                    self.fund_n[i, j] += 1
        return f


def _trailing_sum(x, n):
    """Sum over the trailing n rows (missing counts as nothing), [T, N]."""
    c = np.cumsum(np.nan_to_num(x), axis=0)
    out = c.copy()
    out[n:] = c[n:] - c[:-n]
    return out


def _bottom(s, top):
    return I.df(s).rank(axis=1, ascending=True).to_numpy() <= top


def _top(s, top):
    return I.df(s).rank(axis=1, ascending=False).to_numpy() <= top


def xs_funding_fade(F, look_days=3, hold_days=7, top=5, stop_k=2.5, sides="both"):
    """Long the lowest 3-day funding paid by longs, short the highest (crowded positioning mean-reverts)."""
    p, b = F.p, F.bd
    n = look_days * 24 // p.bar_h
    end = b["end"]
    paid = _trailing_sum(p.fund, n)[end]                 # settlements up to the daily close; none after it
    count = _trailing_sum(p.fund_n, n)[end]
    s = np.where(F.elig[end] & (count >= MIN_SETTLEMENTS), paid, np.nan)
    return qstrat._on_bars(F, b, _bottom(s, top), _top(s, top), stop_k, 0.0, hold_days * 24, sides=sides)


def xs_flow_momentum(F, look_days=3, hold_days=3, top=5, stop_k=2.5, sides="both"):
    """Long the highest 3-day taker-buy share of quote volume, short the lowest (order flow persists)."""
    p, b = F.p, F.bd
    n = look_days * 24 // p.bar_h
    end = b["end"]
    buy, vol = _trailing_sum(p.tb, n)[end], _trailing_sum(p.v, n)[end]
    with np.errstate(all="ignore"):
        share = np.where(vol > 0, buy / vol, np.nan)
    s = np.where(F.elig[end], share, np.nan)
    return qstrat._on_bars(F, b, _top(s, top), _bottom(s, top), stop_k, 0.0, hold_days * 24, sides=sides)


STRATEGIES = {"XS_FUND_FADE": (xs_funding_fade, {}), "XS_FLOW_MOM": (xs_flow_momentum, {})}
