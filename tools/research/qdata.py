"""Load the market-data branch (md/) into aligned numpy panels: hours x coins."""
from __future__ import annotations

import csv
import gzip
import json
import os

import numpy as np

H = 3600


def _read(path):
    with gzip.open(path, "rt") as fh:
        r = csv.reader(fh)
        head = next(r)
        rows = [row for row in r]
    return head, rows


class Panel:
    """Hourly OHLCV for many coins on one time grid. Arrays are [T, N]; NaN where a coin has no bar."""

    def __init__(self, md, min_hours=24 * 45, coins=None, start=None, end=None, folder="h1", bar=3600):
        H = bar
        self.bar = bar
        self.bar_h = bar // 3600
        min_bars = min_hours // self.bar_h
        with open(os.path.join(md, "universe.json")) as fh:
            self.universe = json.load(fh)
        info = {c["t"]: c for c in self.universe["coins"]}
        files = sorted(f[:-7] for f in os.listdir(os.path.join(md, folder)) if f.endswith(".csv.gz"))
        if coins:
            files = [c for c in files if c in coins]
        series = {}
        for c in files:
            _, rows = _read(os.path.join(md, folder, f"{c}.csv.gz"))
            if len(rows) < min_bars:
                continue
            a = np.array([[float(x) if x != "" else np.nan for x in row] for row in rows])
            series[c] = a
        t_end = max(int(a[-1, 0]) for a in series.values())
        t_start = min(int(a[0, 0]) for a in series.values())
        if start:
            t_start = max(t_start, start)
        if end:
            t_end = min(t_end, end)
        self.t = np.arange(t_start, t_end + H, H, dtype=np.int64)
        T = len(self.t)
        self.coins = sorted(series)
        if "BTC" in self.coins:  # BTC first: column 0
            self.coins.remove("BTC")
            self.coins.insert(0, "BTC")
        N = len(self.coins)
        self.o, self.h, self.l, self.c, self.v = (np.full((T, N), np.nan) for _ in range(5))
        for j, c in enumerate(self.coins):
            a = series[c]
            idx = ((a[:, 0].astype(np.int64) - t_start) // H)
            ok = (idx >= 0) & (idx < T)
            idx, a = idx[ok], a[ok]
            self.o[idx, j], self.h[idx, j], self.l[idx, j], self.c[idx, j], self.v[idx, j] = (
                a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])
        # fill single missing hours inside a coin's life with a flat bar (exchange gaps)
        for j in range(N):
            col = self.c[:, j]
            alive = np.where(~np.isnan(col))[0]
            if len(alive) == 0:
                continue
            for i in range(alive[0] + 1, alive[-1] + 1):
                if np.isnan(self.c[i, j]):
                    p = self.c[i - 1, j]
                    self.o[i, j] = self.h[i, j] = self.l[i, j] = self.c[i, j] = p
                    self.v[i, j] = 0.0
        # cost model input (unchanged in v8 Phase 2): a coin without a known volume pays the highest slippage tier
        self.trade_vol = np.array([(info.get(c) or {}).get("trade_vol") or 0.0 for c in self.coins])
        self.fund = self._funding(md)
        self.T, self.N = T, N

    def _funding(self, md):
        """Funding paid by longs at each hour (fraction of notional; 0 when nothing settles)."""
        T, N = len(self.t), len(self.coins)
        f = np.zeros((T, N))
        H = self.bar
        self.fund_src = []
        for j, c in enumerate(self.coins):
            src = None
            p = os.path.join(md, "fund_mexc", f"{c}.csv.gz")
            if os.path.exists(p):
                _, rows = _read(p)
                for row in rows:
                    i = (int(row[0]) - self.t[0]) // H
                    if 0 <= i < T and row[1] != "":
                        f[i, j] += float(row[1])
                src = "mexc"
            else:
                p = os.path.join(md, "fund_hl", f"{c}.csv.gz")
                if os.path.exists(p):
                    _, rows = _read(p)
                    for row in rows:
                        i = (int(row[0]) - self.t[0]) // H
                        if 0 <= i < T and row[1] != "":
                            f[i, j] += float(row[1])
                    src = "hl"
            # before the first known payment (and for coins without data) assume the usual 0.01% every 8 hours
            first = int(np.argmax(f[:, j] != 0)) if (f[:, j] != 0).any() else T
            base = (self.t % (8 * 3600)) == 0
            f[:first, j] = np.where(base[:first], 0.0001, 0.0)
            if src is None:
                src = "assumed"
            self.fund_src.append(src)
        return f

    def slip(self):
        """Slippage per market order by today's volume on your DEXs (same tiers as the scanner)."""
        tv = self.trade_vol
        return np.where(tv >= 1e6, 0.0005, np.where(tv >= 2e5, 0.001, 0.002))


def resample(p: Panel, hours: int):
    """Aggregate the panel to bars of `hours` base bars, aligned to UTC midnight. Returns (t, o, h, l, c, v, end_idx)
    where end_idx[k] is the base index of the last bar inside bar k (the bar is known at end_idx+1's open)."""
    start = int(np.argmax((p.t % (hours * p.bar)) == 0))
    K = (p.T - start) // hours
    sl = slice(start, start + K * hours)
    sh = (K, hours, p.N)
    o = p.o[sl].reshape(sh)[:, 0, :]
    c = p.c[sl].reshape(sh)[:, -1, :]
    with np.errstate(all="ignore"):
        h = np.nanmax(p.h[sl].reshape(sh), axis=1)
        l = np.nanmin(p.l[sl].reshape(sh), axis=1)
        v = np.nansum(p.v[sl].reshape(sh), axis=1)
    bad = np.isnan(p.c[sl].reshape(sh)).any(axis=1)
    o[bad] = h[bad] = l[bad] = c[bad] = np.nan
    t = p.t[sl][::hours]
    end_idx = np.arange(start, start + K * hours, hours) + hours - 1
    return t, o, h, l, c, v, end_idx
