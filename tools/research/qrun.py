"""Run the strategy library on the market data: one-year backtest, in-sample (first 8 months) vs
out-of-sample (last 4 months), random twins."""
from __future__ import annotations

import argparse
import json
import pickle
import time

import numpy as np
import pandas as pd

import qsim
import qstats
import qstrat
from qdata import Panel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="results")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--oos-days", type=int, default=122)
    a = ap.parse_args()
    t0 = time.time()
    p = Panel(a.md)
    F = qstrat.Feat(p)
    print(f"panel {p.T} hours x {p.N} coins ({time.time() - t0:.0f}s); eligible coin-hours "
          f"{F.elig.mean() * 100:.0f}%")
    end = int(p.t[-1]) + 3600
    w0 = end - a.days * 86400
    oos0 = end - a.oos_days * 86400
    print(f"window {pd.to_datetime(w0, unit='s')} .. {pd.to_datetime(end, unit='s')}; out-of-sample from "
          f"{pd.to_datetime(oos0, unit='s')}")
    names = [n for n in qstrat.LIBRARY if not a.only or n in a.only.split(",")]
    tables, summary = [], {}
    for name in names:
        fn, kw = qstrat.LIBRARY[name]
        t1 = time.time()
        sig = fn(F, **kw)
        keep = p.t[sig["i"]] + 3600 >= w0 if len(sig["i"]) else np.array([], dtype=bool)
        sig = {k: v[keep] for k, v in sig.items()}
        s, res, tw = qsim.run(p, sig, elig=F.elig)
        d = qstats.table(p, s, res, tw, name)
        tables.append(d)
        full = qstats.stats(d, w0, end)
        ins = qstats.stats(d, w0, oos0)
        oos = qstats.stats(d, oos0, end)
        summary[name] = {"full": full, "is": ins, "oos": oos}
        print(qstats.fmt_row(name + " FULL", full))
        print(qstats.fmt_row(name + " IS", ins))
        print(qstats.fmt_row(name + " OOS", oos), f" ({time.time() - t1:.0f}s)")
    allt = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()
    with open(f"{a.out}_trades.pkl", "wb") as fh:
        pickle.dump(allt, fh)
    with open(f"{a.out}_summary.json", "w") as fh:
        json.dump(summary, fh, indent=1, default=float)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
