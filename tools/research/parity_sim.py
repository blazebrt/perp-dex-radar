"""Parity of the paper-trade simulator: quant.sim_trade (stdlib) vs qsim (numba) on the same hourly candles."""
import os, sys, time, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import numpy as np
import quant as Q
import qsim, qstrat
from qdata import Panel
md = sys.argv[1]
p = Panel(md)  # hourly
F = qstrat.Feat(p)
end = int(p.t[-1]) + 3600; w0 = end - 365 * 86400
rows = []
for name, fn, kw in (("TREND_EMA", qstrat.trend_ema, dict(fast=20, slow=100, adx_min=20, stop_k=2.5, trail_k=3.0, hold_days=30)),
                     ("TSMOM", qstrat.tsmom, dict(look=30, short_look=7, stop_k=3.0, trail_k=3.0, hold_days=21)),
                     ("XSMOM", qstrat.xs_momentum, dict(look=14, hold_days=14, top=5, stop_k=2.5))):
    sig = fn(F, **kw)
    keep = p.t[sig["i"]] + 3600 >= w0
    sig = {k: v[keep] for k, v in sig.items()}
    s, res, _ = qsim.run(p, sig, elig=F.elig, twins=False)
    for k in range(len(res)):
        rows.append((name, int(s["j"][k]), int(s["i"][k]) + 1, int(s["d"][k]), float(s["stop"][k]), float(s["trail"][k]),
                     int(s["hold"][k]), res[k]))
random.seed(1)
sample = random.sample(rows, min(600, len(rows)))
slip = p.slip()
fund_maps = {}
diffs, states = [], {"same": 0, "diff": 0}
t0 = time.time()
for name, j, i0, d, stop, trail, hold, r in sample:
    coin = p.coins[j]
    c1 = [{"t": int(p.t[i]), "o": float(p.o[i, j]), "h": float(p.h[i, j]), "l": float(p.l[i, j]), "c": float(p.c[i, j])}
          for i in range(i0, min(p.T, i0 + hold + 2)) if not np.isnan(p.c[i, j])]
    if j not in fund_maps:
        fund_maps[j] = {int(p.t[i]): float(p.fund[i, j]) for i in range(p.T) if p.fund[i, j] != 0}
    tr = {"d": d, "px": float(p.o[i0, j]), "t_in": int(p.t[i0]), "stop_pct": stop, "trail_pct": trail, "hold_h": hold, "slip": float(slip[j])}
    res = Q.sim_trade(tr, c1, fund_maps[j], now=int(p.t[-1]) + 3600)
    if res["state"] == "open":
        continue
    reason = qsim.REASONS[int(r[qsim.R_REASON])]
    if reason == "end":
        continue
    same_state = res["state"] == reason
    states["same" if same_state else "diff"] += 1
    diffs.append(abs(res["r"] - r[qsim.R_NET]))
    if not same_state and states["diff"] <= 5:
        print("state differs", name, coin, d, reason, res["state"], round(r[qsim.R_NET], 4), round(res["r"], 4))
print(f"{len(diffs)} trades compared in {time.time()-t0:.0f}s; exit reason same {states}; max |R difference| {max(diffs):.2e}; mean {np.mean(diffs):.2e}")
