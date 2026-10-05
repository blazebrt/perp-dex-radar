"""Does the coin analyzer's chart read make the tested swing signals better? (the test behind the analyzer's gate)

    python tools/research/analyzer_gate.py <market-data folder> [out.json]

Every swing signal of the last three years (a chart score of 70+, long or short, on every coin with $5M+ a day) is
traded with the tested plan (next daily open, stop 2 daily ATR between 5% and 25%, trail 3 ATR, 30 days at most,
costs included), exactly as in picks_export.py. For each signal the analyzer reads the 4-hour and the daily chart
as they were at that day's close (analyzer_gate.js) and says long, short or wait. The trades are then split by
what the chart said: agrees, says wait, or disagrees. A filter is worth using only if the trades it keeps beat the
ones it drops in both halves of the period and on its own, after costs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import numpy as np

from pk_data import daily_panel, factors, regimes
from pk_score import scores
from pk_trades import COST, sim

HERE = os.path.dirname(os.path.abspath(__file__))


def signals(md, min_score=70):
    p, d = daily_panel(md)
    F = factors(d)
    btc_up, _ = regimes(d)
    SL, SS, _, _ = scores(F, btc_up)
    import qind as I
    atr = I.atr(d["h"], d["l"], d["c"], 14)
    t, elig, coins = d["t"], d["elig"], list(d["coins"])
    out = []
    for side, sgn, sc in (("long", 1, SL), ("short", -1, SS)):
        R, RET, _, BARS = sim(d["o"], d["h"], d["l"], d["c"], atr, sgn, 2.0, 3.0, 30, 0.05, 0.25, COST)
        K, N = sc.shape
        for k in range(K):
            for j in range(N):
                s = sc[k, j]
                if not (elig[k, j] and np.isfinite(s) and s >= min_score and np.isfinite(R[k, j])):
                    continue
                out.append({"coin": coins[j], "t": int(t[k]), "side": side, "score": float(s), "R": float(R[k, j]),
                            "ret": float(RET[k, j]), "days": float(BARS[k, j])})
    return out


def stats(rows):
    if not rows:
        return {"n": 0}
    R = np.array([r["R"] for r in rows])
    ret = np.array([r["ret"] for r in rows])
    days = np.array([r["t"] // 86400 for r in rows])
    ud = np.unique(days)
    dm = np.array([R[days == x].mean() for x in ud])
    se = dm.std(ddof=1) / np.sqrt(len(dm)) if len(dm) > 2 else np.nan
    return {"n": int(len(R)), "R": round(float(R.mean()), 3), "ret": round(float(ret.mean()), 4),
            "win": round(float((ret > 0).mean()), 3), "t": round(float(dm.mean() / se), 2) if se == se and se > 0 else None}


def split(rows):
    ts = sorted(r["t"] for r in rows)
    if not ts:
        return [], []
    mid = ts[len(ts) // 2]
    return [r for r in rows if r["t"] < mid], [r for r in rows if r["t"] >= mid]


def by_year(rows):
    out = {}
    for r in rows:
        y = str(np.datetime64(r["t"], "s").astype("datetime64[Y]"))
        out.setdefault(y, []).append(r)
    return {y: stats(v) for y, v in sorted(out.items())}


def main():
    md = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(tempfile.gettempdir(), "analyzer_gate.json")
    sig = signals(md)
    with tempfile.TemporaryDirectory() as tmp:
        sp, cp = os.path.join(tmp, "s.json"), os.path.join(tmp, "c.json")
        with open(sp, "w") as fh:
            json.dump([{"coin": s["coin"], "t": s["t"], "side": s["side"]} for s in sig], fh)
        subprocess.run(["node", os.path.join(HERE, "analyzer_gate.js"), md, sp, cp], check=True)
        with open(cp) as fh:
            reads = json.load(fh)
    for s, r in zip(sig, reads):
        for tf in ("h4", "d1"):
            x = (r or {}).get(tf)
            if not x:
                s[tf] = None
                continue
            s[tf] = "agree" if x["side"] == s["side"] else "wait" if not x["side"] else "disagree"
            s[tf + "_bias"] = x["bias"] * (1 if s["side"] == "long" else -1)
    res = {"signals": len(sig), "groups": {}}
    for band, lo, hi in (("80+", 80, 101), ("70-79", 70, 80)):
        for side in ("long", "short", "both"):
            base = [s for s in sig if lo <= s["score"] < hi and (side == "both" or s["side"] == side)]
            row = {"all": stats(base)}
            for tf in ("h4", "d1"):
                for g in ("agree", "wait", "disagree", "not_disagree"):
                    rows = [s for s in base if s.get(tf) and (s[tf] == g or (g == "not_disagree" and s[tf] != "disagree"))]
                    a, b = split(rows)
                    row[f"{tf}_{g}"] = dict(stats(rows), halves=[stats(a).get("R"), stats(b).get("R")])
            row["years_h4_agree"] = by_year([s for s in base if s.get("h4") == "agree"])
            row["years_all"] = by_year(base)
            res["groups"][f"{band} {side}"] = row
    with open(out_path, "w") as fh:
        json.dump(res, fh, indent=1)
    for name, row in res["groups"].items():
        print(f"\n{name}: all n {row['all']['n']} R {row['all'].get('R')} win {row['all'].get('win')}")
        for tf in ("h4", "d1"):
            line = []
            for g in ("agree", "wait", "disagree", "not_disagree"):
                x = row[f"{tf}_{g}"]
                if x["n"]:
                    line.append(f"{g} n {x['n']} R {x['R']:+.3f} win {x['win']:.0%} t {x['t']} halves {x['halves']}")
            print(f"  {tf}: " + " | ".join(line))


if __name__ == "__main__":
    main()
