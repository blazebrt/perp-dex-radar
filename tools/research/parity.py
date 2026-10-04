"""Parity: quant.py (stdlib, live engine) vs qstrat (numpy, research) signals on the same real candles."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import numpy as np, pandas as pd
import quant as Q
import qstrat
from qdata import Panel
md = sys.argv[1]
p = Panel(md, folder="h4", bar=14400, min_hours=24 * 60)
F = qstrat.Feat(p)
end = int(p.t[-1]) + 14400
w0 = end - 365 * 86400
# research signals
R = {}
for name, fn, kw in (("TREND_EMA", qstrat.trend_ema, dict(fast=20, slow=100, adx_min=20, stop_k=2.5, trail_k=3.0, hold_days=30)),
                     ("TSMOM", qstrat.tsmom, dict(look=30, short_look=7, stop_k=3.0, trail_k=3.0, hold_days=21)),
                     ("XSMOM", qstrat.xs_momentum, dict(look=14, hold_days=14, top=5, stop_k=2.5))):
    sig = fn(F, **kw)
    t_sig = p.t[sig["i"]] + 14400  # entry time (open of the next bar)
    keep = t_sig >= w0
    R[name] = {(p.coins[j], int(t), int(d)): (st, tr) for j, t, d, st, tr in zip(sig["j"][keep], t_sig[keep], sig["d"][keep], sig["stop"][keep], sig["trail"][keep])}
# live engine signals on the same candles (full history per coin)
L = {"TREND_EMA": {}, "TSMOM": {}, "XSMOM": {}}
t0 = time.time()
c4s = {}
for j, coin in enumerate(p.coins):
    rows = []
    for i in range(p.T):
        if not np.isnan(p.c[i, j]):
            rows.append({"t": int(p.t[i]), "o": float(p.o[i, j]), "h": float(p.h[i, j]), "l": float(p.l[i, j]), "c": float(p.c[i, j]), "qv": float(p.v[i, j])})
    c4s[coin] = rows
for coin, c4 in c4s.items():
    if len(c4) < 120:
        continue
    f = Q.trend_feats(c4)
    for i in range(len(c4)):
        if c4[i]["t"] + Q.B4 < w0 or not Q.eligible(c4, i, c4[i]["t"]):
            continue
        s = Q.sig_trend_ema(f, i)
        if s:
            L["TREND_EMA"][(coin, c4[i]["t"] + Q.B4, s[0])] = (s[1], s[2])
daily = {c: Q.to_daily(c4) for c, c4 in c4s.items()}
feats = {c: Q.daily_feats(cd) for c, cd in daily.items() if len(cd) > 30}
days = sorted({x["t"] for cd in daily.values() for x in cd if x["t"] + 86400 >= w0})
for day in days:
    xs = {}
    for coin, cd in daily.items():
        if coin not in feats:
            continue
        k = next((q for q in range(len(cd) - 1, -1, -1) if cd[q]["t"] == day), None)
        if k is None:
            continue
        c4 = c4s[coin]
        i4 = next((q for q in range(len(c4) - 1, -1, -1) if c4[q]["t"] == day + 86400 - Q.B4), None)
        if i4 is None or not Q.eligible(c4, i4, day):
            continue
        f = feats[coin]
        s = Q.sig_tsmom(f, k)
        if s:
            L["TSMOM"][(coin, day + 86400, s[0])] = (s[1], s[2])
        if f["r_x"][k] is not None and f["vol"][k]:
            xs[coin] = f["r_x"][k] / f["vol"][k]
    for coin, d in Q.xs_scores(xs).items():
        f = feats[coin]
        k = next(q for q in range(len(daily[coin]) - 1, -1, -1) if daily[coin][q]["t"] == day)
        st = Q._stop(f["c"][k], f["atr"][k], 2.5)
        if st:
            L["XSMOM"][(coin, day + 86400, d)] = (st, 0.0)
print(f"live engine replay {time.time()-t0:.0f}s")
for name in ("TREND_EMA", "TSMOM", "XSMOM"):
    a, b = set(R[name]), set(L[name])
    both = a & b
    dif = [abs(R[name][k][0] - L[name][k][0]) for k in both]
    print(f"{name}: research {len(a)}, live {len(b)}, same {len(both)}, only research {len(a - b)}, only live {len(b - a)}; "
          f"max stop difference {max(dif) if dif else 0:.2e}")
    for k in sorted(a - b)[:5]: print("   only research", k, pd.to_datetime(k[1], unit='s'))
    for k in sorted(b - a)[:5]: print("   only live", k, pd.to_datetime(k[1], unit='s'))
