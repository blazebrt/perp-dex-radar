#!/usr/bin/env python3
"""
No-edge check for Perp DEX Radar.

Builds a FAKE market where prices move at random (every coin is a martingale: its
expected next price is today's price), then runs scanner.py's own 30-day walk-forward
backtest on it with the live rules and costs.

Why: on a market like this no strategy can have a real edge, so
  * each strategy's result here is its "zero-skill baseline" (what it earns by luck,
    minus costs). A strategy only has an edge on real data if it clearly beats this;
  * "cost R" shows how much of the risk on every trade goes to fees, slippage and
    funding, i.e. the hurdle a strategy must clear just to break even;
  * if a change to scanner.py ever makes this fake market look profitable, that change
    peeks into the future (look-ahead bug). The script then exits with an error.

The fake market is realistic enough to exercise every rule: a common market factor
(BTC) with per-coin beta, volatility that clusters, fat-tailed moves, intrabar highs and
lows, and volume that rises with big moves.

Usage (from the repository root):
    python tools/no_edge_check.py                # 1 market, 120 coins, 30 days
    python tools/no_edge_check.py --seeds 5      # 5 different random markets
Standard library only, like scanner.py.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import statistics as S
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import scanner as sc  # noqa: E402

SUB = 6           # price steps inside each 15m candle (for realistic highs and lows)
BTC_DAILY = 0.023  # BTC daily volatility


def _t4(rng):
    """Student-t (4 degrees of freedom) scaled to unit variance: fat tails like crypto."""
    z = rng.gauss(0.0, 1.0)
    chi2 = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(4))
    return z / math.sqrt(chi2 / 4) / math.sqrt(2.0)


def _shocks(rng, n, daily_vol):
    """n return shocks with GARCH(1,1)-style clustering; returns (shocks, sigmas)."""
    base = daily_vol * math.sqrt(1.0 / (96 * SUB))
    a, b = 0.06, 0.93
    h, z_prev = 1.0, 0.0
    out, sig = [], []
    for i in range(n):
        if i:
            h = (1 - a - b) + a * z_prev * z_prev + b * h
        z = _t4(rng)
        s = base * math.sqrt(h)
        out.append(s * z)
        sig.append(s)
        z_prev = z
    return out, sig


def fake_market(n_coins, n_bars, seed, end_t):
    rng = random.Random(seed)
    steps = n_bars * SUB
    bar = 900
    t0 = (end_t // bar) * bar - n_bars * bar
    mkt, msig = _shocks(rng, steps, BTC_DAILY)
    coins = {}
    for k in range(n_coins):
        name = "BTC" if k == 0 else f"F{k:03d}"
        if k == 0:
            r, sig = mkt, msig
            p = 60000.0
        else:
            dvol = math.exp(rng.uniform(math.log(0.035), math.log(0.075)))  # 3.5%-7.5% a day
            beta = rng.uniform(0.8, 1.5)
            idio_daily = math.sqrt(max(dvol ** 2 - (beta * BTC_DAILY) ** 2, (0.4 * dvol) ** 2))
            idio, isig = _shocks(rng, steps, idio_daily)
            r = [beta * m + e for m, e in zip(mkt, idio)]
            sig = [math.sqrt((beta * a) ** 2 + b ** 2) for a, b in zip(msig, isig)]
            p = math.exp(rng.uniform(math.log(0.05), math.log(50.0)))
        base_qv = math.exp(rng.uniform(math.log(2e4), math.log(3e6)))
        candles, ar = [], 0.0
        moves = []
        for i in range(n_bars):
            o = hi = lo = p
            for j in range(i * SUB, (i + 1) * SUB):
                p *= math.exp(r[j] - 0.5 * sig[j] ** 2)  # martingale: no drift in price
                hi, lo = max(hi, p), min(lo, p)
            moves.append(abs(math.log(p / o)))
            candles.append({"t": t0 + i * bar, "o": o, "h": hi, "l": lo, "c": p, "qv": 0.0})
        med = S.median(moves) or 1e-12
        for x, mv in zip(candles, moves):
            ar = 0.7 * ar + rng.gauss(0.0, 0.35)
            x["qv"] = base_qv * math.exp(ar) * (0.6 + 0.4 * mv / med)
        coins[name] = candles
    return coins


def run_once(seed, n_coins, days):
    n_bars = days * 96 + 600
    end_t = 1_790_000_000
    C = fake_market(n_coins, n_bars, seed, end_t)
    rng = random.Random(seed + 1000)
    crypto = {}
    for t in C:
        vol = 5e8 if t == "BTC" else math.exp(rng.uniform(math.log(1e5), math.log(1e8)))
        crypto[t] = {"t": t, "venues": {"hyperliquid": {}}, "best_vol": vol, "trade_vol": vol, "tradfi": False}
    now = C["BTC"][-1]["t"] + 900
    specs = [sp for sp in sc.active_specs() if sp.get("tf", "15m") == "15m" and sp["base"] != "SMF"]
    res = sc.backtest(C, crypto, now, days, specs, rank_specs=[sp["id"] for sp in specs])
    rows = {}
    done_by = {}
    for sid, trs in res.items():
        done = sorted((t for t in trs if t["res"].get("done") and not t.get("dup") and not sc.gated(t)),
                      key=lambda t: t["res"].get("xt") or t["t"])
        done_by[sid] = done
        st = sc.trade_stats(done)
        if not st.get("n"):
            continue
        rows[sid] = {"n": st["n"], "wr": st["wr"], "exp": st["exp"], "se": st["se"],
                     "gross": S.mean(t["res"].get("gross", 0.0) for t in done),
                     "cost": S.mean(t["res"].get("cost", 0.0) for t in done),
                     "stop": S.median(t["f"]["risk"] for t in done) * 100}
    for sid in list(rows):
        if not sc.is_twin(sid) and "RAND:" + sid in done_by:
            e = sc.edge_vs_twins(done_by[sid], done_by["RAND:" + sid])
            if e:
                rows[sid]["edge"], rows[sid]["edge_se"] = e["edge"], e["se"]
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seeds", type=int, default=1, help="how many different fake markets to test")
    ap.add_argument("--coins", type=int, default=120)
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args(argv)
    allrows = []
    for k in range(args.seeds):
        t = time.time()
        rows = run_once(101 + k, args.coins, args.days)
        allrows.append(rows)
        print(f"\nFake market {k + 1} ({time.time() - t:.0f}s)")
        print(f"{'strategy':12s} {'trades':>6s} {'winners':>8s} {'R/trade':>8s} {'gross R':>8s} {'cost R':>7s} "
              f"{'stop %':>7s}  vs random twins")
        for sid, r in sorted(rows.items(), key=lambda kv: (sc.is_twin(kv[0]), kv[0])):
            vs = f"  {r['edge']:+.3f}R (+/- {r['edge_se']:.3f})" if "edge" in r else ""
            print(f"{sid:12s} {r['n']:6d} {r['wr'] * 100:7.0f}% {r['exp']:+8.3f} {r['gross']:+8.3f} {r['cost']:7.3f} "
                  f"{r['stop']:7.2f}{vs}")
    # look-ahead guard: on a no-edge market, gross results must hover around zero
    bad = []
    for rows in allrows:
        gs = [r["gross"] for sid, r in rows.items() if r["n"] >= 200 and not sc.is_twin(sid)]
        if gs and S.mean(gs) > 0.10:
            bad.append(f"average gross {S.mean(gs):+.3f}R across strategies")
        bad += [f"{sid} gross {r['gross']:+.3f}R over {r['n']} trades" for sid, r in rows.items()
                if r["n"] >= 200 and r["gross"] > 0.25]
        bad += [f"{sid} beats its random twins by {r['edge']:+.3f}R (+/- {r['edge_se']:.3f})"
                for sid, r in rows.items() if r.get("edge") is not None and r["n"] >= 200
                and r["edge"] - 3 * r["edge_se"] > 0]
    if args.seeds > 1:
        print("\nLuck check: spread of R/trade across the fake markets vs the standard error the tournament uses")
        for sid in [x for x in allrows[0] if not sc.is_twin(x)]:
            e = [rows[sid]["exp"] for rows in allrows if sid in rows]
            se = [rows[sid]["se"] for rows in allrows if sid in rows]
            if len(e) > 1:
                print(f"  {sid:10s} spread {S.stdev(e):.3f}R vs tournament SE {S.mean(se):.3f}R "
                      f"({S.stdev(e) / S.mean(se):.1f}x)")
    if bad:
        print("\nFAIL: a market with no edge looks profitable; something sees the future:\n  " + "\n  ".join(bad))
        sys.exit(1)
    print("\nOK: no strategy makes money on a market where that is impossible. Real-data results only count "
          "if they clearly beat these baselines.")


if __name__ == "__main__":
    main()
