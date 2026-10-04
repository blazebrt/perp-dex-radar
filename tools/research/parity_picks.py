"""Parity check: the live picks engine (picks.py, standard library) must give the same swing scores as the
research code (pk_score.py, numpy/pandas) on the same candles.

    python tools/research/parity_picks.py <market-data folder>
"""
from __future__ import annotations

import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import picks  # noqa: E402
from pk_data import daily_panel, factors, regimes  # noqa: E402
from pk_score import scores  # noqa: E402


def main():
    md = sys.argv[1]
    p, d = daily_panel(md)
    F = factors(d)
    btc_up, _ = regimes(d)
    SL, SS, _, _ = scores(F, btc_up)
    K, N = SL.shape
    rng = random.Random(7)
    cells = [(k, j) for k in range(150, K) for j in range(1, N) if np.isfinite(SL[k, j]) and d["elig"][k, j]]
    cells = rng.sample(cells, min(500, len(cells)))
    t4 = p.t
    bad = done = 0
    worst = 0.0
    for k, j in cells:
        col = d["c"][: k + 1, j]
        first = int(np.argmax(np.isfinite(col)))
        if np.isnan(col[first:]).any():
            continue  # the live code drops incomplete days; compare coins without gaps after listing
        cd = [{"t": int(d["t"][i]), "o": float(d["o"][i, j]), "h": float(d["h"][i, j]), "l": float(d["l"][i, j]),
               "c": float(d["c"][i, j]), "qv": float(d["v"][i, j])} for i in range(first, k + 1)]
        end = int(d["t"][k]) + 86400
        m4 = (t4 < end) & np.isfinite(p.c[:, j])
        c4 = [{"t": int(t4[i]), "o": float(p.o[i, j]), "h": float(p.h[i, j]), "l": float(p.l[i, j]),
               "c": float(p.c[i, j]), "qv": float(p.v[i, j])} for i in np.where(m4)[0]]
        bc = d["c"][: k + 1, 0]
        e50 = picks.q.ema([float(x) for x in bc], 50)[-1]
        x = picks.swing_values(cd, c4, {"mom30": float(bc[-1] / bc[-31] - 1), "up": bool(e50 and bc[-1] > e50)})
        if x is None:
            continue
        sl = picks.points(picks.long_checks(x), picks.LONG_W)
        ss = picks.points(picks.short_checks(x), picks.SHORT_W)
        diff = max(abs(sl - SL[k, j]), abs(ss - SS[k, j]))
        done += 1
        worst = max(worst, diff)
        if diff > 0.01:
            bad += 1
            if bad <= 8:
                print(f"  differs: {d['coins'][j]} day {k}: live {sl:.1f}/{ss:.1f} research {SL[k, j]:.1f}/{SS[k, j]:.1f}")
    print(f"{done} of {len(cells)} sampled coin-days compared, {bad} differ (largest difference {worst:.2f} points)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
