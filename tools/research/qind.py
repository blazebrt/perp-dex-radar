"""Indicators on [T, N] numpy panels (NaN-aware). Every value at row i uses data up to row i only."""
from __future__ import annotations

import numpy as np
import pandas as pd


def df(a):
    return pd.DataFrame(a)


def ema(x, n):
    return df(x).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()


def sma(x, n, minp=None):
    return df(x).rolling(n, min_periods=minp or n).mean().to_numpy()


def rstd(x, n, minp=None):
    return df(x).rolling(n, min_periods=minp or n).std().to_numpy()


def rmax(x, n):
    return df(x).rolling(n, min_periods=n).max().to_numpy()


def rmin(x, n):
    return df(x).rolling(n, min_periods=n).min().to_numpy()


def shift(x, k=1):
    out = np.full_like(x, np.nan)
    if k > 0:
        out[k:] = x[:-k]
    elif k < 0:
        out[:k] = x[-k:]
    else:
        out[:] = x
    return out


def wilder(x, n):
    return df(x).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy()


def atr(h, l, c, n=14):
    pc = shift(c)
    tr = np.fmax(h - l, np.fmax(np.abs(h - pc), np.abs(l - pc)))
    tr[np.isnan(pc)] = (h - l)[np.isnan(pc)]
    return wilder(tr, n)


def rsi(c, n=14):
    d = c - shift(c)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    up[np.isnan(d)] = np.nan
    dn[np.isnan(d)] = np.nan
    au, ad = wilder(up, n), wilder(dn, n)
    with np.errstate(all="ignore"):
        rs = au / ad
        return 100 - 100 / (1 + rs)


def adx(h, l, c, n=14):
    up = h - shift(h)
    dn = shift(l) - l
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(h, l, c, n)
    with np.errstate(all="ignore"):
        pdi = 100 * wilder(pdm, n) / a
        ndi = 100 * wilder(ndm, n) / a
        dx = 100 * np.abs(pdi - ndi) / (pdi + ndi)
    return wilder(dx, n), pdi, ndi


def boll_width(c, n=20, k=2.0):
    m = sma(c, n)
    s = rstd(c, n)
    with np.errstate(all="ignore"):
        return (2 * k * s) / m, m + k * s, m - k * s


def pct_rank(x, n, minp=None):
    """Rank of the current value inside the last n values (0..1)."""
    return df(x).rolling(n, min_periods=minp or n).rank(pct=True).to_numpy()


def ret(c, k):
    with np.errstate(all="ignore"):
        return c / shift(c, k) - 1


def xs_rank(x):
    """Cross-sectional rank per row (0..1), NaN-aware."""
    return df(x).rank(axis=1, pct=True).to_numpy()


def ffill(x):
    return df(x).ffill().to_numpy()
