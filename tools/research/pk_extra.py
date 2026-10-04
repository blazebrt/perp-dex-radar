"""Do the live extra checks (funding, open interest, top-trader and crowd positioning, liquidations, supply
unlocks, market cap, trading interest) improve the swing trade? Tested on the last year of daily data, for all
coins and inside the 80+ setups, long and short.

    python tools/research/pk_extra.py <market-data folder with stats_gate_1d/ and cg/hist/>
"""
from __future__ import annotations

import csv
import gzip
import os
import sys

import numpy as np
import pandas as pd

import qind as I
from pk_data import daily_panel, factors, regimes
from pk_score import scores
from pk_trades import COST, sim


def read_gz(path):
    with gzip.open(path, "rt") as fh:
        r = csv.reader(fh)
        head = next(r)
        rows = [[float(x) if x != "" else np.nan for x in row] for row in r]
    return head, np.array(rows) if rows else np.zeros((0, len(head)))


def panel_from(md, folder, t, coins, cols, sums=()):
    """Daily values of `cols` on the daily grid t, known at the close of each day: the last row stamped inside
    the day for snapshots (open interest, ratios, market cap), the sum over the day for `sums` (liquidations)."""
    K, N = len(t), len(coins)
    out = {c: np.full((K, N), np.nan) for c in cols}
    t0 = int(t[0])
    for j, coin in enumerate(coins):
        p = os.path.join(md, folder, f"{coin}.csv.gz")
        if not os.path.exists(p):
            continue
        head, a = read_gz(p)
        if not len(a):
            continue
        day = ((a[:, 0].astype(np.int64) - t0) // 86400).astype(int)
        for c in cols:
            v = a[:, head.index(c)]
            for k in np.unique(day):
                if k < 0 or k >= K:
                    continue
                m = day == k
                out[c][k, j] = np.nansum(v[m]) if c in sums else v[m][-1]
    return out


def terciles(name, x, lab, base, groups):
    m = base & np.isfinite(x) & np.isfinite(lab)
    if m.sum() < 150:
        return None
    q = np.nanquantile(x[m], [1 / 3, 2 / 3])
    lo, hi = m & (x <= q[0]), m & (x > q[1])
    row = {"check": name, "n": int(m.sum()), "low": np.nanmean(lab[lo]), "high": np.nanmean(lab[hi])}
    for g, gm in groups.items():
        a, b = lab[hi & gm], lab[lo & gm]
        row[g] = (np.nanmean(a) - np.nanmean(b)) if (len(a) > 40 and len(b) > 40) else np.nan
    return row


def main():
    md = sys.argv[1]
    p, d = daily_panel(md)
    F = factors(d)
    btc_up, _ = regimes(d)
    SL, SS, _, _ = scores(F, btc_up)
    t, coins, elig = d["t"], list(d["coins"]), d["elig"]
    K, N = elig.shape
    atr = I.atr(d["h"], d["l"], d["c"], 14)
    lab = {}
    for side, sgn in (("long", 1), ("short", -1)):
        R, RET, _, _ = sim(d["o"], d["h"], d["l"], d["c"], atr, sgn, 2.0, 3.0, 30, 0.05, 0.25, COST)
        lab[side] = R
    st = panel_from(md, "stats_gate_4h", t, coins, ["open_interest_usd", "top_lsr_size", "top_lsr_account",
                                                    "lsr_account", "lsr_taker", "long_liq_usd", "short_liq_usd"],
                    sums=("long_liq_usd", "short_liq_usd"))
    cg = panel_from(md, os.path.join("cg", "hist"), t, coins, ["mcap", "vol", "price"])
    with np.errstate(all="ignore"):
        c = d["c"]
        oi = st["open_interest_usd"]
        X = {
            "funding (3-day avg)": F["fund3"],
            "open interest change 7d": oi / I.shift(oi, 7) - 1,
            "OI up while price up (7d)": np.where(np.isfinite(oi / I.shift(oi, 7)),
                                                  ((oi / I.shift(oi, 7) - 1) > 0.05) & (I.ret(c, 7) > 0), np.nan),
            "top traders long/short (size)": st["top_lsr_size"],
            "top traders long/short change 7d": st["top_lsr_size"] / I.shift(st["top_lsr_size"], 7) - 1,
            "crowd long/short (accounts)": st["lsr_account"],
            "taker buy/sell": I.sma(st["lsr_taker"], 3),
            "long liquidations share (3d)": I.sma(st["long_liq_usd"], 3) / (I.sma(st["long_liq_usd"], 3) +
                                                                            I.sma(st["short_liq_usd"], 3)),
            "supply growth 30d": (cg["mcap"] / cg["price"]) / I.shift(cg["mcap"] / cg["price"], 30) - 1,
            "market cap (log)": np.log(cg["mcap"]),
            "volume / market cap": cg["vol"] / cg["mcap"],
        }
    # two halves of the period that has statistics (about five months) and of the CoinGecko year
    have_st = np.isfinite(st["open_interest_usd"]).any(axis=1)
    st_days = t[have_st]
    split = (st_days[0] + st_days[-1]) / 2 if len(st_days) else t[-1] - 182 * 86400
    first = np.repeat((t < split)[:, None], N, 1)
    groups = {"first_half": first, "second_half": ~first}
    print(f"statistics from {pd.to_datetime(st_days[0], unit='s'):%Y-%m-%d}, split at "
          f"{pd.to_datetime(split, unit='s'):%Y-%m-%d}")
    pd.set_option("display.width", 220)
    for side, sc in (("long", SL), ("short", SS)):
        rows_all, rows_set = [], []
        for name, x in X.items():
            r = terciles(name, x, lab[side], elig, groups)
            if r:
                rows_all.append(r)
            r = terciles(name, x, lab[side], elig & (sc >= 70), groups)
            if r:
                rows_set.append(r)
        print(f"\n=== {side.upper()} trades, every coin: avg R in the low and high third of each check, "
              "and high minus low in each half of the year")
        if rows_all:
            print(pd.DataFrame(rows_all).round(3).to_string(index=False))
        print(f"=== {side.upper()} trades inside setups scoring 70+")
        if rows_set:
            print(pd.DataFrame(rows_set).round(3).to_string(index=False))
    have = {k: int(np.isfinite(v).sum()) for k, v in X.items()}
    print("\nvalues available:", have)


if __name__ == "__main__":
    main()
