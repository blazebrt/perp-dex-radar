"""Trade results for every coin and bar: enter at the next bar's open, stop k_stop ATR away (bounded),
trailing stop k_trail ATR (fixed at entry) behind the best high (low for shorts), applied from the next
bar, out at the close of bar entry+max_bars-1 at the latest. Stop first when a bar touches it; gaps exit
at the open. Costs are taken off every trade. Returns R multiples, returns, best excursion and bars held."""
from __future__ import annotations

import numba as nb
import numpy as np

COST = 0.0019  # 2 x (0.045% taker fee + 0.05% slippage)


@nb.njit(cache=True)
def sim(o, h, l, c, atr, side, k_stop, k_trail, max_bars, min_sd, max_sd, cost):
    K, N = c.shape
    R = np.full((K, N), np.nan)
    RET = np.full((K, N), np.nan)
    MFE = np.full((K, N), np.nan)
    BARS = np.full((K, N), np.nan)
    for j in range(N):
        for k in range(K - 2):
            if not (c[k, j] > 0) or not (atr[k, j] > 0) or not (o[k + 1, j] > 0):
                continue
            e = o[k + 1, j]
            sd = min(max(k_stop * atr[k, j] / c[k, j], min_sd), max_sd)
            a = atr[k, j] / c[k, j] * e
            stop = e * (1 - sd) if side > 0 else e * (1 + sd)
            best = e
            ex = np.nan
            last = min(K - 1, k + max_bars)
            mfe = 0.0
            n = 0
            i = k + 1
            for i in range(k + 1, last + 1):
                if not (h[i, j] > 0):
                    break
                n = i - k
                if side > 0:
                    if o[i, j] <= stop:
                        ex = o[i, j]
                        break
                    if l[i, j] <= stop:
                        ex = stop
                        break
                    mfe = max(mfe, h[i, j] / e - 1)
                    best = max(best, h[i, j])
                    stop = max(stop, best - k_trail * a)
                else:
                    if o[i, j] >= stop:
                        ex = o[i, j]
                        break
                    if h[i, j] >= stop:
                        ex = stop
                        break
                    mfe = max(mfe, 1 - l[i, j] / e)
                    best = min(best, l[i, j])
                    stop = min(stop, best + k_trail * a)
                if i == last:
                    ex = c[i, j]
            if np.isnan(ex) or (i == last and last < k + max_bars and ex == c[i, j]):
                continue  # data ended before the trade did
            r = ((ex / e - 1) if side > 0 else (1 - ex / e)) - cost
            RET[k, j] = r
            R[k, j] = r / sd
            MFE[k, j] = mfe
            BARS[k, j] = n
    return R, RET, MFE, BARS
