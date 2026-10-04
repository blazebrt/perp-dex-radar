"""Long test on 4h bars (about 3 years): only the 4h / daily strategies. Results per year."""
import sys, time, pickle
import pandas as pd
import qsim, qstats, qstrat
from qdata import Panel

md, out = sys.argv[1], sys.argv[2]
names = sys.argv[3].split(",") if len(sys.argv) > 3 else ["TREND_DC55", "TREND_DC20", "TREND_EMA", "TSMOM", "XSMOM_7D",
                                                           "XSMOM_14D", "XSREV_1D", "SQZ_4H", "RS_BRK"]
t0 = time.time()
p = Panel(md, folder="h4", bar=14400, min_hours=24 * 60)
F = qstrat.Feat(p)
print(f"4h panel {p.T} bars x {p.N} coins ({time.time()-t0:.0f}s); from {pd.to_datetime(p.t[0], unit='s')}; eligible {F.elig.mean()*100:.0f}%")
end = int(p.t[-1]) + 14400
start = int(p.t[0]) + 90 * 86400
years = []
y = end
while y - 365 * 86400 >= start - 60 * 86400:
    years.append((y - 365 * 86400, y)); y -= 365 * 86400
years = years[::-1]
tables = []
for name in names:
    fn, kw = qstrat.LIBRARY[name]
    sig = fn(F, **kw)
    keep = p.t[sig["i"]] >= start
    sig = {k: v[keep] for k, v in sig.items()}
    s, res, tw = qsim.run(p, sig, elig=F.elig)
    d = qstats.table(p, s, res, tw, name)
    d["t_exit"] = p.t[res[:, qsim.R_EXIT].astype(int)] + 14400
    tables.append(d)
    print(qstats.fmt_row(name + " ALL", qstats.stats(d, start, end)))
    for a, b in years:
        lab = f"{pd.to_datetime(a, unit='s'):%Y-%m}..{pd.to_datetime(b, unit='s'):%Y-%m}"
        print(qstats.fmt_row(f"   {lab}", qstats.stats(d, a, b)))
pickle.dump(pd.concat(tables, ignore_index=True), open(out + "_trades.pkl", "wb"))
print(f"done {time.time()-t0:.0f}s")
