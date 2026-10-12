"""Writes picks_research.json (the test results shown on the picks page) from the market data.

    python tools/research/picks_export.py <market-data folder> [out.json]
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

import pk_day
import qind as I
from pk_extra import panel_from
from pk_data import daily_panel, factors, forward, regimes
from pk_score import account, scores
from pk_trades import COST, sim

HERE = os.path.dirname(os.path.abspath(__file__))
BANDS = ((0, 40), (40, 60), (60, 70), (70, 80), (80, 90), (90, 101))
ACCOUNTS = (
    ("Longs and shorts scoring 90+, up to 5 trades at once, 2% risk each", ("long", "short"), 90, 5, 0.02),
    ("Longs and shorts scoring 90+, up to 5 trades at once, 3% risk each", ("long", "short"), 90, 5, 0.03),
    ("Longs and shorts scoring 80+, up to 10 trades at once, 2% risk each", ("long", "short"), 80, 10, 0.02),
    ("Longs only, scoring 90+, up to 5 at once, 2% risk", ("long",), 90, 5, 0.02),
    ("Shorts only, scoring 90+, up to 5 at once, 2% risk", ("short",), 90, 5, 0.02),
)


def band_stats(sc, R, RET, fw, elig, years, bands=BANDS):
    out = []
    Yg = np.repeat(years[:, None], sc.shape[1], 1)
    for lo, hi in bands:
        m = elig & np.isfinite(R) & np.isfinite(sc) & (sc >= lo) & (sc < hi) & np.isfinite(fw["max30"])
        if m.sum() < 30:
            continue
        ys = {}
        for y in sorted(set(years)):
            mm = m & (Yg == y)
            if mm.sum() >= 30:
                ys[str(y)] = {"ret": round(float(np.nanmean(RET[mm])), 4), "R": round(float(np.nanmean(R[mm])), 3),
                              "n": int(mm.sum())}
        out.append({"lo": lo, "hi": hi, "n": int(m.sum()), "R": round(float(np.nanmean(R[m])), 3),
                    "ret": round(float(np.nanmean(RET[m])), 4), "win": round(float(np.mean(RET[m] > 0)), 3),
                    "up50": round(float(np.mean(fw["max30"][m] >= 0.5)), 3),
                    "dbl": round(float(np.mean(fw["max30"][m] >= 1.0)), 3),
                    "dn30": round(float(np.mean(fw["min30"][m] <= -0.3)), 3), "years": ys})
    return out


def extras_evidence(md, d, F, labs):
    """R per trade with and without each tested extra condition (futures statistics since April 2026, CoinGecko
    and funding over the last year): every coin and day where the data exists."""
    t, coins, elig = d["t"], list(d["coins"]), d["elig"]
    st = panel_from(md, "stats_gate_4h", t, coins, ["open_interest_usd", "long_liq_usd", "short_liq_usd"],
                    sums=("long_liq_usd", "short_liq_usd"))
    cg = panel_from(md, os.path.join("cg", "hist"), t, coins, ["mcap", "vol", "price"])
    with np.errstate(all="ignore"):
        oi = st["open_interest_usd"]
        oi7, px7 = oi / I.shift(oi, 7) - 1, I.ret(d["c"], 7)
        liq3 = I.sma(st["long_liq_usd"], 3) / (I.sma(st["long_liq_usd"], 3) + I.sma(st["short_liq_usd"], 3))
        turn = cg["vol"] / cg["mcap"]
        sup = (cg["mcap"] / cg["price"]) / I.shift(cg["mcap"] / cg["price"], 30) - 1
        fund = F["fund3"]
        # funding history exists from about 400 days back; before that the research assumes 0.01% per 8 hours
        real_fund = np.repeat((t >= t[-1] - 380 * 86400)[:, None], len(coins), 1)
        tests = [
            ("long", "Open interest up 5%+ in 7 days while the price rose", np.isfinite(oi7), (oi7 >= 0.05) & (px7 > 0)),
            ("long", "Longs were 60%+ of liquidations over 3 days", np.isfinite(liq3), liq3 >= 0.6),
            ("long", "24h volume at most 10% of the market cap", np.isfinite(turn), turn <= 0.10),
            ("long", "Circulating supply up 2%+ in 30 days", np.isfinite(sup), sup >= 0.02),
            ("short", "Circulating supply up 2%+ in 30 days", np.isfinite(sup), sup >= 0.02),
            ("short", "Funding above 0.01% per 8 hours", np.isfinite(fund) & real_fund, fund > 0.0003),
        ]
    out = []
    for side, name, have, cond in tests:
        R = labs[side][0]
        base = elig & np.isfinite(R) & have
        yes, no = base & cond, base & ~cond
        out.append({"side": side, "check": name, "yes": round(float(np.nanmean(R[yes])), 3), "n_yes": int(yes.sum()),
                    "no": round(float(np.nanmean(R[no])), 3), "n_no": int(no.sum())})
        print(f"extra {side}: {name}: yes {out[-1]['yes']:+.3f} (n {out[-1]['n_yes']}) no {out[-1]['no']:+.3f}")
    return out


def extras_line(ex):
    e = {(x["side"], x["check"]): x for x in ex}
    a = e.get(("long", "Open interest up 5%+ in 7 days while the price rose"))
    b = e.get(("long", "Circulating supply up 2%+ in 30 days"))
    c = e.get(("short", "Circulating supply up 2%+ in 30 days"))
    f = e.get(("short", "Funding above 0.01% per 8 hours"))
    if not (a and b and c and f):
        return "Smart money and fundamentals were checked where history exists; they move the score by a few points."
    return (f"Smart money and fundamentals, where history exists: longs did worse when leverage piled in during the "
            f"rise (open interest up 5%+ in a week: {a['yes']:+.2f}R per trade vs {a['no']:+.2f}R) and when unlocks "
            f"added 2%+ supply in a month ({b['yes']:+.2f}R vs {b['no']:+.2f}R); the same unlocks helped shorts "
            f"({c['yes']:+.2f}R vs {c['no']:+.2f}R), and shorts did worse when funding was high ({f['yes']:+.2f}R vs "
            f"{f['no']:+.2f}R). These checks move the score by a few points; the Hyperliquid top traders have no "
            f"history to test and only nudge it.")


def write_seed(md, path, days=45):
    """The last weeks of CoinGecko circulating supply per coin: picks.py starts its 30-day supply growth from it."""
    folder = os.path.join(md, "cg", "hist")
    if not os.path.isdir(folder):
        return
    out = {}
    for f in sorted(os.listdir(folder)):
        import csv
        import gzip
        with gzip.open(os.path.join(folder, f), "rt") as fh:
            rows = list(csv.reader(fh))[1:]
        pts = [(int(r[0]), float(r[2]) / float(r[1])) for r in rows if r[1] and r[2] and float(r[1]) > 0 and int(r[0]) % 86400 == 0]
        if not pts:
            continue
        last = pts[-1][0]
        out[f[:-7]] = [[t_, float(f"{c:.6g}")] for t_, c in pts if t_ >= last - days * 86400]
    with open(path, "w") as fh:
        json.dump({"generated": int(time.time()), "supply": out}, fh, separators=(",", ":"))
    print(f"wrote {path} ({len(out)} coins)")


def main():
    md = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "..", "picks_research.json")
    p, d = daily_panel(md)
    F = factors(d)
    fw = forward(d)
    btc_up, breadth = regimes(d)
    SL, SS, _, _ = scores(F, btc_up)
    t = d["t"]
    elig = d["elig"]
    years = pd.to_datetime(t, unit="s").year.to_numpy()
    atr = I.atr(d["h"], d["l"], d["c"], 14)
    res = {"generated": int(time.time()), "coins": int(len(d["coins"])),
           "period": f"{pd.to_datetime(t[0], unit='s'):%b %Y} to {pd.to_datetime(t[-1], unit='s'):%b %Y}",
           "rules": {"entry": "next daily open", "stop": "2 daily ATR (5% to 25%)", "trail": "3 ATR behind the best price",
                     "max_days": 30, "costs": COST}, "swing": {}}
    labs = {}
    for side, sgn, sc in (("long", 1, SL), ("short", -1, SS)):
        R, RET, MFE, BARS = sim(d["o"], d["h"], d["l"], d["c"], atr, sgn, 2.0, 3.0, 30, 0.05, 0.25, COST)
        labs[side] = (R, BARS)
        base = elig & np.isfinite(R) & np.isfinite(fw["max30"])
        res["swing"][side] = {
            "bands": band_stats(sc, R, RET, fw, elig, years),
            "ready": band_stats(sc, R, RET, fw, elig, years, ((80, 101),))[0],
            "base": {"n": int(base.sum()), "R": round(float(np.nanmean(R[base])), 3),
                     "ret": round(float(np.nanmean(RET[base])), 4), "win": round(float(np.mean(RET[base] > 0)), 3),
                     "up50": round(float(np.mean(fw["max30"][base] >= 0.5)), 3),
                     "dn30": round(float(np.mean(fw["min30"][base] <= -0.3)), 3)}}
        for b in res["swing"][side]["bands"]:
            print(f"{side} {b['lo']:3d}-{b['hi']:3d}: n {b['n']:6d} R {b['R']:+.3f} trade {b['ret'] * 100:+.2f}% win "
                  f"{b['win'] * 100:.0f}% +50% {b['up50'] * 100:.0f}% -30% {b['dn30'] * 100:.0f}% | "
                  + " ".join(f"{y} {v['ret'] * 100:+.1f}%" for y, v in b["years"].items()))
    start = pd.Timestamp("2024-01-01").timestamp()
    end = t[-1] - 31 * 86400
    res["account"] = []
    for label, sides, thr, mp, risk in ACCOUNTS:
        curve, trades = account({"long": SL, "short": SS}, labs, elig, t, start, end, thr, mp, risk, sides)
        c = pd.Series(curve, index=pd.to_datetime(t, unit="s")).dropna()
        yr = c.resample("YE").last()
        prev, ys = 1.0, {}
        for idx, v in yr.items():
            ys[str(idx.year)] = round(float(v / prev), 3)
            prev = v
        Rs = np.array([x[4] for x in trades])
        res["account"].append({"label": label, "end": round(float(c.iloc[-1]), 3),
                               "dd": round(float((c / c.cummax() - 1).min()), 3), "trades": len(trades),
                               "avgR": round(float(Rs.mean()), 3), "win": round(float(np.mean(Rs > 0)), 3), "years": ys})
        print(f"account: {label}: {c.iloc[-1]:.2f}x, worst drop {(c / c.cummax() - 1).min() * 100:.0f}%, {len(trades)} trades")
    res["account_note"] = (f"January 2024 to {pd.to_datetime(end, unit='s'):%B %Y}: every pick taken with the tested plan, "
                           "sized so the stop loses the chosen share of the account, fees and slippage included. "
                           "Past results; the next years will differ.")
    # the coins you named: what the score said in the 30 days before their big months
    cases = []
    coins = list(d["coins"])
    for c_, day in (("WLD", "2026-05-05"), ("NIL", "2026-04-08"), ("NIL", "2026-08-25"), ("WLD", "2025-04-06")):
        if c_ not in coins:
            continue
        j = coins.index(c_)
        k = int(np.where(pd.to_datetime(t, unit="s") == pd.Timestamp(day))[0][0])
        w = SL[max(0, k - 30): k + 1, j]
        cases.append({"coin": c_, "day": day, "max_long_score_30d": float(np.nanmax(w)),
                      "gain_30d": round(float(fw["max30"][k, j]), 3)})
    res["cases"] = cases
    # day trades
    res["day"] = pk_day.run(md, t, coins, SL, SS)
    for side in ("long", "short"):
        x = res["day"][side]
        print(f"day {side}: top 5 every 4h R {x['top5']['R']:+.3f} ({x['top5']['ret'] * 100:+.2f}%) vs every coin "
              f"{x['top5']['R_all']:+.3f}; bands " + ", ".join(f"{b['lo']}+ {b['R']:+.3f}" for b in x["bands"]))
    res["extras"] = extras_evidence(md, d, F, labs)
    write_seed(md, os.path.join(os.path.dirname(out_path), "picks_seed.json"))
    L, S = res["swing"]["long"], res["swing"]["short"]
    top_l, top_s = L["bands"][-1], S["bands"][-1]
    res["findings"] = [
        f"Buying a coin near its 90-day low works when its momentum has come back and its volatility is squeezed "
        f"(the 'coiled bottom'). Longs scoring 90+ made {top_l['ret'] * 100:+.1f}% per trade on average after fees, "
        f"{top_l['win'] * 100:.0f}% winners, and were positive in " + ", ".join(
            y for y, v in top_l["years"].items() if v["ret"] > 0) + ".",
        "Buying a coin only because it is near its low did not work: those trades lost money on average. The "
        "turn has to show first (daily RSI back above 45, a squeeze, a higher low).",
        f"For 90+ longs the chance of a +50% move within 30 days stayed about the same as for any coin "
        f"({top_l['up50'] * 100:.0f}% vs {L['base']['up50'] * 100:.0f}%) while the chance of a 30% fall was "
        f"{top_l['dn30'] * 100:.0f}% instead of {L['base']['dn30'] * 100:.0f}%: the upside stays open, the downside shrinks.",
        f"Shorting coins that bounce inside a downtrend, away from their lows, made money every year: shorts "
        f"scoring 90+ made {top_s['ret'] * 100:+.1f}% per trade. Shorting coins that sit on their lows did not.",
        "The 2x to 3x months you named mostly started while the coin was still falling with weak momentum: WLD in "
        "May 2026 and NIL in April 2026 never scored above 65 in the month before. NIL did score 80 on 26 July 2026, "
        "days before its August run, but the tested exit took +3% and was out before the big move. No rule we tested "
        "could pick these in advance, because the same picture more often kept falling. The score aims for many "
        "good trades with small losses instead of one lucky one.",
        extras_line(res["extras"]),
        "Day trades on hourly candles lost money after fees with every selection we tried, and on 4-hour candles "
        "they were close to zero. The edge is in holding swing trades for days to weeks.",
        "Realistic growth: about 1.2x to 1.7x a year at 2% to 3% risk per trade, with drops of 20% to 35% along "
        "the way. $500 to $1M in two years would need about 2,000x; nothing tested comes close, and a bigger size "
        "mostly raises the chance of losing the account.",
    ]
    with open(out_path, "w") as fh:
        json.dump(res, fh, separators=(",", ":"))
    print(f"wrote {out_path} ({os.path.getsize(out_path):,} bytes)")


if __name__ == "__main__":
    main()
