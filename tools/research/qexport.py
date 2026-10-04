"""Build quant_research.json for the dashboard: every strategy tested (1-year on 1h bars, 3-year on 4h bars),
the verdicts, equity curves, and the account simulation / growth planner for the strategies that passed."""
from __future__ import annotations

import json
import math
import sys
import time

import numpy as np
import pandas as pd

import qport
import qsim
import qstats
import qstrat
from qdata import Panel

FINAL = ("TSMOM", "TREND_EMA", "XSMOM")

TESTED = {
    # id: (function, kwargs, name, family, timeframe, description)
    "TSMOM": (qstrat.tsmom, dict(look=30, short_look=7, stop_k=3.0, trail_k=3.0, hold_days=21),
              "Daily trend rider", "trend", "1d",
              "Long when the 30-day and 7-day returns are positive and price is above the 50-day EMA; short when all three point down. Trailing stop."),
    "TREND_EMA": (qstrat.trend_ema, dict(fast=20, slow=100, adx_min=20, stop_k=2.5, trail_k=3.0, hold_days=30),
                  "4-hour trend crossover", "trend", "4h",
                  "EMA 20 crosses EMA 100 on 4-hour bars with ADX above 20; long or short; trailing stop."),
    "XSMOM": (qstrat.xs_momentum, dict(look=14, hold_days=14, top=5, stop_k=2.5),
              "Momentum rotation", "momentum", "1d",
              "Every day the 5 strongest coins of the last 14 days (per unit of volatility) are bought and the 5 weakest sold short, for 14 days."),
    "XSMOM_7D": (qstrat.xs_momentum, dict(look=7, hold_days=3, top=5, stop_k=2.5),
                 "Momentum rotation, fast", "momentum", "1d", "7-day ranking, 3-day hold."),
    "XSMOM_14D_7": (qstrat.xs_momentum, dict(look=14, hold_days=7, top=5, stop_k=2.5),
                    "Momentum rotation, 7-day hold", "momentum", "1d", "14-day ranking, 7-day hold."),
    "TREND_DC55": (qstrat.trend_donchian, dict(n=55), "4h 55-bar breakout", "trend", "4h",
                   "Turtle-style breakout of the 55-bar high or low on 4-hour bars; trailing stop."),
    "TREND_DC20": (qstrat.trend_donchian, dict(n=20), "4h 20-bar breakout", "trend", "4h",
                   "Breakout of the 20-bar high or low on 4-hour bars; trailing stop."),
    "DC20_D": (qstrat.trend_donchian, dict(n=20, tf=24, stop_k=2.0, trail_k=3.0, hold_days=60),
               "Daily 20-day breakout", "trend", "1d", "Breakout of the 20-day high or low; trailing stop."),
    "DC55_D": (qstrat.trend_donchian, dict(n=55, tf=24, stop_k=2.0, trail_k=3.0, hold_days=90),
               "Daily 55-day breakout", "trend", "1d", "Breakout of the 55-day high or low; trailing stop."),
    "EMA5_20_D": (qstrat.trend_ema, dict(fast=5, slow=20, tf=24, adx_min=0, stop_k=2.0, trail_k=3.0, hold_days=30),
                  "Daily fast EMA cross", "trend", "1d", "EMA 5 crosses EMA 20 on daily bars; trailing stop."),
    "EMA10_50_D": (qstrat.trend_ema, dict(fast=10, slow=50, tf=24, adx_min=0, stop_k=2.0, trail_k=3.0, hold_days=60),
                   "Daily EMA 10/50 cross", "trend", "1d", "EMA 10 crosses EMA 50 on daily bars; trailing stop."),
    "TSMOM_FAST": (qstrat.tsmom, dict(look=14, short_look=3, stop_k=2.5, trail_k=2.5, hold_days=14),
                   "Daily trend rider, fast", "trend", "1d", "14-day and 3-day returns agree."),
    "TSMOM_SLOW": (qstrat.tsmom, dict(look=90, short_look=30, stop_k=3.0, trail_k=4.0, hold_days=45),
                   "Daily trend rider, slow", "trend", "1d", "90-day and 30-day returns agree."),
    "SQZ_4H": (qstrat.squeeze_breakout, {}, "4h volatility squeeze", "breakout", "4h",
               "Bollinger bands at their narrowest in 30 days, then a close outside them with volume."),
    "SQZ_D": (qstrat.squeeze_breakout, dict(tf=24, pct=0.15, look=90, vol_mult=1.2, stop_k=2.0, trail_k=3.0, hold_days=30),
              "Daily volatility squeeze", "breakout", "1d", "Daily version of the squeeze breakout."),
    "RS_BRK": (qstrat.rs_breakout, {}, "Relative-strength breakout", "trend", "4h",
               "Coins beating BTC break a 10-bar high while BTC trends up (long); laggards break down while BTC trends down (short)."),
    "XSREV_1D": (qstrat.xs_reversal, {}, "1-day reversal", "mean reversion", "1d",
                 "Buy the biggest 1-day losers, short the biggest winners, hold 1 day."),
    "LIQ_FLUSH": (qstrat.liq_flush, {}, "Liquidation flush reversal", "mean reversion", "1h",
                  "After a 3-ATR one-hour crash (or spike) on heavy volume, trade the snap-back."),
    "PULLBACK": (qstrat.pullback, {}, "Trend pullback", "trend", "1h",
                 "4-hour trend, 1-hour RSI pullback that turns back; target 2.5R."),
    "FAIL_BRK": (qstrat.failed_breakout, {}, "Stop-hunt fade", "mean reversion", "1h",
                 "A new 48-hour high (low) that closes back inside with a long wick: trade against it."),
    "VOL_SPIKE": (qstrat.volume_spike, {}, "Volume spike follow-through", "momentum", "1h",
                  "An hour with 5x normal volume and a big body closing near its extreme: follow it."),
    "BTC_LEAD": (qstrat.btc_lead, {}, "BTC lead, alts catch up", "momentum", "1h",
                 "After a big 1-hour BTC move, alts that have not followed yet (for their beta) catch up."),
    "FUND_FADE": (qstrat.funding_fade, {}, "Crowded funding fade", "positioning", "1h",
                  "Very positive funding while price stalls: short; very negative funding while price holds: long."),
    "FUND_CARRY": (qstrat.funding_carry, {}, "Funding carry", "positioning", "1h",
                   "Short the coins paying the highest funding, long the most negative, 24 hours."),
}
FOUR_H_OK = {k for k, v in TESTED.items() if v[4] in ("4h", "1d")}


def weekly_curve(d, t0, t1):
    x = d[(d.reason != "end") & (d.t_exit >= t0) & (d.t_exit < t1)]
    nw = int(math.ceil((t1 - t0) / (7 * 86400)))
    w = np.zeros(nw)
    idx = ((x.t_exit.to_numpy() - t0) // (7 * 86400)).astype(int).clip(0, nw - 1)
    np.add.at(w, idx, x.r.to_numpy())
    return [round(float(v), 2) for v in np.cumsum(w)]


def slim(s):
    if not s or not s.get("n"):
        return {"n": 0}
    keys = ("n", "wr", "avg", "gross", "cost", "fund", "pf", "sum", "se", "t", "sharpe", "maxdd", "days", "hold_h",
            "stop_pct", "long_n", "short_n", "long_avg", "short_avg", "edge", "edge_se", "edge_t", "twin_avg",
            "months_pos", "trades_per_day")
    out = {}
    for k in keys:
        v = s.get(k)
        if isinstance(v, float):
            v = None if not math.isfinite(v) else round(v, 4)
        out[k] = v
    return out


def _r(x):
    return f"{x:+.2f}R".replace("-", "\u2212")


VARIANTS = {"XSMOM_7D", "XSMOM_14D_7", "DC20_D", "DC55_D", "EMA5_20_D", "EMA10_50_D", "TSMOM_FAST", "TSMOM_SLOW",
            "SQZ_D", "TREND_DC20", "TREND_DC55"}


def verdict(sid, one, ins, oos, three):
    if sid in FINAL:
        return "live", ("Made money after costs in both halves of the last year and over three years, and did better "
                        "than random entries taken at the same moments. Settings are textbook defaults, not tuned "
                        "to this data.")
    if not one.get("n"):
        return "rejected", "Almost never triggers."
    a = one["avg"]
    if a < -0.02:
        w = f"Loses money after costs: {_r(a)} per trade over {one['n']:,} trades in the last year."
        if one["gross"] > 0:
            w += (f" It is slightly positive before costs ({_r(one['gross'])}), but fees, slippage and funding take "
                  f"{one['cost']:.2f}R of every trade.")
        return "rejected", w
    if a <= 0.02:
        if one["cost"] < 0.01:
            return "rejected", (f"Breaks even ({_r(a)} per trade over {one['n']:,} trades) even though funding "
                                f"payments work in its favour: no edge.")
        return "rejected", (f"Breaks even at best after costs ({_r(a)} per trade over {one['n']:,} trades): "
                            f"fees and slippage ({one['cost']:.2f}R a trade) eat whatever edge it has.")
    ia, oa = ins.get("avg") or 0, oos.get("avg") or 0
    if ia * oa < 0:
        return "rejected", (f"Made money in one part of the year and lost it in the other ({_r(ia)} vs {_r(oa)} "
                            f"per trade): not reliable.")
    if three and three.get("n") and three["avg"] <= 0.01:
        return "rejected", f"Positive in the last year ({_r(a)}) but not over three years ({_r(three['avg'])})."
    e3 = (three or {}).get("edge_t")
    if e3 is not None and e3 < 1.0:
        return "rejected", (f"Over three years it was no better than random entries at the same moments "
                            f"({_r(three['edge'])} \u00b1 {three['edge_se']:.2f}).")
    if three is None and one.get("edge_t") is not None and one["edge_t"] < 1.5:
        return "rejected", (f"Not clearly better than random entries at the same moments ({_r(one['edge'])} "
                            f"\u00b1 {one['edge_se']:.2f}).")
    if oa < 0.3 * ia:
        return "rejected", (f"Most of its profit came early in the year ({_r(ia)} per trade); in the last 4 months it "
                            f"made only {_r(oa)}, and a few big winners carry the total.")
    if sid in VARIANTS:
        return "rejected", "A close variant of a live strategy that did worse; keeping both would double the same bet."
    return "rejected", "Positive, but not consistent enough across the tests to trust yet."


def main():
    md, out_path = sys.argv[1], sys.argv[2]
    t0 = time.time()
    p1 = Panel(md)
    F1 = qstrat.Feat(p1)
    p4 = Panel(md, folder="h4", bar=14400, min_hours=24 * 60)
    F4 = qstrat.Feat(p4)
    end1 = int(p1.t[-1]) + 3600
    w0 = end1 - 365 * 86400
    oos0 = end1 - 122 * 86400
    end4 = int(p4.t[-1]) + 14400
    s4 = int(p4.t[0]) + 90 * 86400
    res = {"generated": int(time.time()), "window_1y": [w0, end1], "oos_from": oos0, "window_3y": [s4, end4],
           "coins_1y": p1.N, "coins_3y": p4.N,
           "costs": {"taker": qsim.FEE_T, "maker": qsim.FEE_M, "slippage": "0.05% ($1M+ a day on your DEXs), 0.1%, 0.2%",
                     "funding": "MEXC funding history (longs pay positive rates)"},
           "strategies": {}}
    finals_3y = []
    for sid, (fn, kw, name, fam, tf, desc) in TESTED.items():
        sig = fn(F1, **kw)
        keep = p1.t[sig["i"]] + 3600 >= w0
        sig = {k: v[keep] for k, v in sig.items()}
        s, r, tw = qsim.run(p1, sig, elig=F1.elig)
        d1 = qstats.table(p1, s, r, tw, sid)
        one, ins, oos = (qstats.stats(d1, w0, end1), qstats.stats(d1, w0, oos0), qstats.stats(d1, oos0, end1))
        lon = qstats.stats(d1[d1.d > 0], w0, end1)
        sho = qstats.stats(d1[d1.d < 0], w0, end1)
        three, curve3 = None, None
        if sid in FOUR_H_OK:
            sig4 = fn(F4, **kw)
            keep = p4.t[sig4["i"]] >= s4
            sig4 = {k: v[keep] for k, v in sig4.items()}
            s_, r_, tw_ = qsim.run(p4, sig4, elig=F4.elig)
            d4 = qstats.table(p4, s_, r_, tw_, sid)
            d4["t_exit"] = p4.t[r_[:, qsim.R_EXIT].astype(int)] + 14400
            three = qstats.stats(d4, s4, end4)
            curve3 = weekly_curve(d4, s4, end4)
            years = []
            for k in range(3):
                a, b = end4 - (k + 1) * 365 * 86400, end4 - k * 365 * 86400
                if a >= s4 - 120 * 86400:
                    years.append({"from": max(a, s4), "to": b, **slim(qstats.stats(d4, max(a, s4), b))})
            if sid in FINAL:
                finals_3y.append(d4)
        v, why = verdict(sid, one, ins, oos, three)
        res["strategies"][sid] = {
            "name": name, "family": fam, "tf": tf, "desc": desc, "params": kw, "verdict": v, "why": why,
            "one_year": slim(one), "in_sample": slim(ins), "out_of_sample": slim(oos), "long": slim(lon),
            "short": slim(sho), "three_year": slim(three) if three else None,
            "years": years if three else None,
            "curve_1y": weekly_curve(d1, w0, end1), "curve_3y": curve3,
            "months": {k: round(v_, 2) for k, v_ in (one.get("months") or {}).items()},
        }
        print(f"{sid:12s} {v:8s} 1y n={one.get('n')} avg={one.get('avg', 0):+.3f}  3y={three.get('avg') if three else None}")
    # combined account and growth planner for the strategies that went live (3 years, 4h bars)
    T = pd.concat(finals_3y, ignore_index=True)
    T = T[T.reason != "end"]
    comb = qstats.stats(T, s4, end4)
    accounts = []
    for f in (0.0025, 0.005, 0.0075, 0.01, 0.02):
        ev, sm, took = qport.simulate(T, start=500, risk=f, max_open=60, max_per_strategy=20)
        wk = []
        if len(ev):
            e = ev.copy()
            e["w"] = ((e.t - s4) // (7 * 86400)).astype(int)
            last = e.groupby("w").equity.last()
            cur = 500.0
            for wi in range(int(math.ceil((end4 - s4) / (7 * 86400)))):
                cur = float(last.get(wi, cur))
                wk.append(round(cur, 2))
        accounts.append({"risk": f, "final": round(sm["final"], 2), "multiple": round(sm["multiple"], 3),
                         "maxdd": round(sm["maxdd"], 3), "taken": sm["taken"], "curve": wk})
    ev, sm, took = qport.simulate(T, start=500, risk=0.005, max_open=60, max_per_strategy=20)
    TK = T[took]
    daily = qport.daily_r(TK, s4, end4)
    risks = (0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.10)
    planners = {}
    for hc in (0.0, 0.5):
        gp = qport.growth_planner(daily, start=500, days=730, risks=risks, paths=6000, haircut=hc,
                                  targets=(1_000, 10_000, 100_000, 1_000_000))
        planners[f"{hc:.1f}"] = [{k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else v)
                                  for k, v in row.items()} for row in gp.to_dict("records")]
    sharpe = float(daily.mean() / daily.std() * math.sqrt(365)) if daily.std() > 0 else None
    res["portfolio"] = {
        "strategies": list(FINAL), "all_trades": slim(comb), "taken": slim(qstats.stats(TK, s4, end4)),
        "max_open": 60, "max_per_strategy": 20,
        "daily_r_mean": round(float(daily.mean()), 4), "daily_r_sd": round(float(daily.std()), 4),
        "sharpe": round(sharpe, 3) if sharpe else None, "kelly": round(qport.kelly(daily), 4),
        "accounts": accounts, "planner": planners, "start": 500, "planner_days": 730,
    }
    with open(out_path, "w") as fh:
        json.dump(res, fh, separators=(",", ":"))
    print(f"wrote {out_path} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
