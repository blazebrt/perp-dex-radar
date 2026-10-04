import sys, itertools
import pandas as pd
import qsim, qstats, qstrat
from qdata import Panel
md = sys.argv[1]
p = Panel(md, folder="h4", bar=14400, min_hours=24 * 60)
F = qstrat.Feat(p)
end = int(p.t[-1]) + 14400; start = int(p.t[0]) + 90 * 86400
y1 = (end - 2 * 365 * 86400, end - 365 * 86400); y2 = (end - 365 * 86400, end)
grids = {
    "TSMOM": (qstrat.tsmom, dict(look=[20, 30, 60], short_look=[7, 14], trail_k=[2.5, 3.0, 4.0])),
    "TREND_EMA": (qstrat.trend_ema, dict(fast=[10, 20, 30, 50], slow=[50, 100, 150, 200], adx_min=[0, 20, 25], trail_k=[2.5, 3.0, 4.0])),
    "XSMOM": (qstrat.xs_momentum, dict(look=[7, 14, 30], hold_days=[3, 7, 14], top=[3, 5, 8])),
}
rows = []
for name, (fn, grid) in grids.items():
    keys = list(grid)
    for vals in itertools.product(*[grid[k] for k in keys]):
        kw = dict(zip(keys, vals))
        if name == "TREND_EMA" and kw["fast"] >= kw["slow"]:
            continue
        sig = fn(F, **kw)
        keep = p.t[sig["i"]] >= start
        sig = {k: v[keep] for k, v in sig.items()}
        s, res, tw = qsim.run(p, sig, elig=F.elig, twins=False)
        d = qstats.table(p, s, res, None, name)
        d["t_exit"] = p.t[res[:, qsim.R_EXIT].astype(int)] + 14400
        a = qstats.stats(d, start, end); b1 = qstats.stats(d, *y1); b2 = qstats.stats(d, *y2)
        rows.append(dict(strategy=name, **kw, n=a["n"], avg=a["avg"], sharpe=a["sharpe"], dd=a["maxdd"],
                         y1=b1.get("avg"), y2=b2.get("avg"), y1_sh=b1.get("sharpe"), y2_sh=b2.get("sharpe")))
df = pd.DataFrame(rows)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
for name in grids:
    x = df[df.strategy == name]
    print(f"\n{name}: {len(x)} settings; Sharpe>0 in {(x.sharpe>0).mean()*100:.0f}%; median Sharpe {x.sharpe.median():+.2f}; "
          f"both years positive in {((x.y1>0)&(x.y2>0)).mean()*100:.0f}%")
    print(x.sort_values("sharpe", ascending=False).round(3).to_string(index=False))
df.to_csv(sys.argv[2] + "_grid.csv", index=False)
