#!/usr/bin/env python3
"""Smart money test: does following Hyperliquid's proven traders predict the next hours and days?

    python tools/research/smart_backtest.py <smart-data folder> [--json out.json]

Reads the data from smart_collect.py (the smart-data branch) and tests, without hindsight:

  * who counts as smart is decided from what was known at that moment: each trader's PnL history up to the start of
    the day (the account histories), never from later results;
  * prices: Hyperliquid hourly candles. A signal at time t is entered at the open of the next full hour and judged
    at the close h hours later (4, 24 and 72 hours), in the signal's direction ("hit" = it moved that way).
    "Excess" removes the market: the same coins' average move over the same hours is subtracted;
  * results are split by halves of the window and the error bars cluster by day, because signals on the same day
    are not independent.

Methods compared:
  old      the radar's method today: dollar-weighted share among the top accounts of the last 30 days
  entries  every new or added position by a proven trader (copy their entries)
  consensus  per coin, proven traders counted one each (not by dollars), weighted by conviction (size against
           their account), long when 3+ traders and 60%+ of the weight is long, short when 60%+ is short
  callers  traders whose own past entries were right most often (scored only on entries already judged)
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict

H, DAY = 3600, 86400
HORIZONS = (4, 24, 72)


# --------------------------------------------------------------------------- data
def load(folder):
    with open(os.path.join(folder, "meta.json")) as fh:
        meta = json.load(fh)
    traders = []
    for name in sorted(os.listdir(folder)):
        if name.startswith("traders_") and name.endswith(".json.gz"):
            with gzip.open(os.path.join(folder, name), "rt") as fh:
                traders += json.load(fh)
    with gzip.open(os.path.join(folder, "candles.json.gz"), "rt") as fh:
        candles = json.load(fh)
    return meta, traders, candles


class Prices:
    """Hourly opens and closes per coin, and the market's average move over any span (cached)."""

    def __init__(self, candles):
        self.o, self.c, self.h, self.l = {}, {}, {}, {}
        for coin, rows in candles.items():
            if len(rows) < 48:
                continue
            self.o[coin] = {int(r[0]) // H * H: r[1] for r in rows if r[1] > 0}
            self.c[coin] = {int(r[0]) // H * H: r[4] for r in rows if r[4] > 0}
            self.h[coin] = {int(r[0]) // H * H: r[2] for r in rows if r[2] > 0}
            self.l[coin] = {int(r[0]) // H * H: r[3] for r in rows if r[3] > 0}
        self.coins = sorted(self.o)
        self._mkt, self._vol = {}, {}

    def ret(self, coin, start, hours):
        """Open of the hour `start` to the close of the hour that ends `hours` later."""
        o = self.o.get(coin, {}).get(start)
        c = self.c.get(coin, {}).get(start + (hours - 1) * H)
        return c / o - 1 if o and c else None

    def market(self, start, hours):
        k = (start, hours)
        if k not in self._mkt:
            xs = [x for x in (self.ret(c, start, hours) for c in self.coins) if x is not None]
            self._mkt[k] = statistics.fmean(xs) if len(xs) >= 10 else None
        return self._mkt[k]

    def close(self, coin, hour):
        return self.c.get(coin, {}).get(hour)

    def vol24(self, coin, start):
        """Typical 24-hour move before `start`: the mean absolute 24-hour return over the previous 7 days."""
        k = (coin, start // DAY)
        if k not in self._vol:
            c = self.c.get(coin, {})
            xs = []
            for d in range(1, 8):
                a, b = c.get(start - d * DAY - H), c.get(start - (d - 1) * DAY - H)
                if a and b:
                    xs.append(abs(b / a - 1))
            self._vol[k] = statistics.fmean(xs) if len(xs) >= 4 else None
        return self._vol[k]

    def trade(self, coin, start, side, hours, stop_k=1.5, min_stop=0.015, cost=0.0009):
        """The follow trade: in at the open of `start`, stop stop_k typical daily moves away (at least 1.5%),
        out at the stop or at the close `hours` later. Returns (R, return after cost) or None."""
        v = self.vol24(coin, start)
        o = self.o.get(coin, {}).get(start)
        if not v or not o:
            return None
        stop = max(min_stop, stop_k * v)
        hi, lo, cl = self.h.get(coin, {}), self.l.get(coin, {}), self.c.get(coin, {})
        for k in range(hours):
            t = start + k * H
            if t not in cl:
                return None
            if side > 0 and lo.get(t, cl[t]) <= o * (1 - stop):
                r = -stop
                break
            if side < 0 and hi.get(t, cl[t]) >= o * (1 + stop):
                r = -stop
                break
        else:
            r = side * (cl[start + (hours - 1) * H] / o - 1)
        r -= cost
        return r / stop, r


def next_hour(t):
    return (int(t) // H + 1) * H


# --------------------------------------------------------------------------- traders: history and positions
class Series:
    """A step-free (linearly interpolated) time series from [[t, v], ...]."""

    def __init__(self, pts):
        pts = sorted((int(t), float(v)) for t, v in pts or [] if t)
        self.t = [p[0] for p in pts]
        self.v = [p[1] for p in pts]

    def __bool__(self):
        return len(self.t) >= 2

    def at(self, t):
        if not self.t:
            return None
        if t <= self.t[0]:
            return self.v[0] if t == self.t[0] else None
        if t >= self.t[-1]:
            return self.v[-1]
        i = bisect.bisect_right(self.t, t)
        t0, t1, v0, v1 = self.t[i - 1], self.t[i], self.v[i - 1], self.v[i]
        return v0 + (v1 - v0) * (t - t0) / (t1 - t0) if t1 > t0 else v1


def chain_order(fills):
    """Fills that share a second can come back in any order. Within such a group (per coin), put them in the
    order their own 'position before' and 'position after' link up, so positions and entries follow the trades as
    they happened. A group that does not link up keeps its order."""
    out, i = [], 0
    while i < len(fills):
        j = i
        while j < len(fills) and fills[j][0] == fills[i][0]:
            j += 1
        group = fills[i:j]
        if len(group) > 1:
            by = defaultdict(list)
            for f in group:
                by[f[1]].append(f)
            for coin, fs in by.items():
                if len(fs) > 1:
                    by[coin] = _link(fs)
            group = [f for coin in dict.fromkeys(f[1] for f in group) for f in by[coin]]
        out += group
        i = j
    return out


def _link(fs):
    def close(a, b):
        return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))
    ends = [f[5] + f[2] * f[3] for f in fs]
    first = [k for k, f in enumerate(fs) if not any(close(f[5], e) for m, e in enumerate(ends) if m != k)]
    if len(first) != 1:
        return fs
    order, left = [first[0]], set(range(len(fs))) - {first[0]}
    while left:
        nxt = [k for k in left if close(fs[k][5], ends[order[-1]])]
        if not nxt:
            return fs
        order.append(nxt[0])
        left.discard(nxt[0])
    return [fs[k] for k in order]


class Trader:
    def __init__(self, d, w_start, w_end):
        self.id = d["id"]
        self.groups = d.get("groups") or []
        self.lb = d.get("lb") or {}
        self.av_now = d.get("av") or 0.0
        pf = d.get("portfolio") or {}
        hist = pf.get("perpAllTime") if pf.get("perpAllTime") and len(pf["perpAllTime"].get("pnl") or []) >= 2 \
            else pf.get("allTime") or {}
        self.pnl = Series(hist.get("pnl"))
        self.av = Series(((pf.get("allTime") or {}).get("av")) or hist.get("av"))
        self.fills = chain_order(d.get("fills") or [])
        complete = d.get("fills_complete")
        first = self.fills[0][0] if self.fills else None
        self.w_start = w_start
        self.cov_start = w_start if (complete or not first) else first
        self._entries = None
        self.has_fills = "fills" in d
        self.state = d.get("state") or {}
        self.paths = self._paths(w_end)
        m = (self.lb.get("m") or {})
        self.mm = (m.get("vlm") or 0) > 150 * max(self.av_now, 1.0)

    def _paths(self, w_end):
        """Per coin: fill times, the position before each fill (as the API reports it) and the position after the
        last one. The position at a moment is the 'before' of the next fill, which stays exact even when several
        fills share the same second; after the last fill it is the open position now (complete histories) or the
        last fill's result."""
        by = defaultdict(list)
        for f in self.fills:
            by[f[1]].append(f)
        now = {p[0]: p[1] for p in self.state.get("pos") or []}
        complete = self.cov_start == self.w_start
        out = {}
        for coin, fs in by.items():
            last = fs[-1][5] + fs[-1][2] * fs[-1][3]
            end = now.get(coin, 0.0) if complete and self.state else last
            out[coin] = ([f[0] for f in fs], [f[5] for f in fs], end)
        for coin, szi in now.items():
            if coin not in out and self.has_fills:
                out[coin] = ([], [], szi)
        return out

    def pos(self, coin, t):
        p = self.paths.get(coin)
        if not p or t < self.cov_start:
            return 0.0
        i = bisect.bisect_right(p[0], t)
        return p[1][i] if i < len(p[0]) else p[2]

    def pnl_between(self, t0, t1):
        a, b = self.pnl.at(t0), self.pnl.at(t1)
        return b - a if a is not None and b is not None else None

    def account(self, t):
        v = self.av.at(t)
        return v if v and v > 0 else None

    def entries(self):
        """New or added positions: one event per coin, hour and side, with the notional added."""
        if self._entries is not None:
            return self._entries
        ev = defaultdict(float)
        for f in self.fills:
            t, coin, side, sz, px, start = f[0], f[1], f[2], f[3], f[4], f[5]
            end = start + side * sz
            if abs(end) <= abs(start) and (start == 0 or end * start > 0):
                continue                                          # a reduction or a close
            if start * end < 0:                                   # a flip: the new side is opened
                added = abs(end) * px
            else:
                added = (abs(end) - abs(start)) * px
            if added <= 0:
                continue
            ev[(t // H * H, coin, 1 if end > 0 else -1)] += added
        self._entries = [(h, c, s, usd) for (h, c, s), usd in sorted(ev.items())]
        return self._entries


# --------------------------------------------------------------------------- who is smart, as of a day
def skill_table(traders, days):
    """For each day: {trader id: skill} using only PnL known by the start of that day."""
    out = {}
    for d in days:
        row = {}
        for tr in traders:
            if not tr.pnl or tr.mm:
                continue
            p_all = tr.pnl.at(d)
            p30, p90 = tr.pnl_between(d - 30 * DAY, d), tr.pnl_between(d - 90 * DAY, d)
            av = tr.account(d)
            if p_all is None or av is None:
                continue
            row[tr.id] = {"all": p_all, "p30": p30, "p90": p90, "av": av,
                          "roi30": (p30 / max(tr.account(d - 30 * DAY) or av, 1.0)) if p30 is not None else None}
        out[d] = row
    return out


PROVEN = {"min_all": 100_000, "max_month_loss": 0.15, "min_account": 25_000, "need_p90": False}


def proven(s, min_all=None):
    """The live rule (smart.py, from the leaderboard): $100k+ made over the whole history, at most 15% of the
    account lost over the last 30 days, a $25k+ account. need_p90 adds 'positive over 90 days' (stricter)."""
    m = PROVEN["min_all"] if min_all is None else min_all
    return (s["all"] >= m and s["av"] >= PROVEN["min_account"]
            and (s["p30"] is None or s["p30"] >= -PROVEN["max_month_loss"] * s["av"])
            and (not PROVEN["need_p90"] or (s["p90"] or 0) > 0))


def hot_set(row, n=150):
    """The radar's selection today: profitable last 30 days (5%+), all-time positive, $50k+, top by 30-day PnL."""
    c = [(k, s) for k, s in row.items() if (s["p30"] or 0) > 0 and s["all"] > 0 and (s["roi30"] or 0) >= 0.05
         and s["av"] >= 50_000]
    c.sort(key=lambda kv: -kv[1]["p30"])
    return {k for k, _ in c[:n]}


# --------------------------------------------------------------------------- statistics
def summary(rows, key="dir"):
    """rows: dicts with day, dir (direction-adjusted return) and exc (excess over the market)."""
    xs = [r[key] for r in rows if r.get(key) is not None]
    if not xs:
        return {"n": 0}
    by = defaultdict(list)
    for r in rows:
        if r.get(key) is not None:
            by[r["day"]].append(r[key])
    dm = [statistics.fmean(v) for v in by.values()]
    se = statistics.stdev(dm) / math.sqrt(len(dm)) if len(dm) > 2 else None
    m = statistics.fmean(xs)
    return {"n": len(xs), "days": len(dm), "mean": round(m, 5), "hit": round(sum(1 for x in xs if x > 0) / len(xs), 3),
            "t": round(statistics.fmean(dm) / se, 2) if se else None, "coins": len({r["coin"] for r in rows})}


def judge(sig_rows, prices, h, cost=0.0):
    """Adds the forward move to each signal: dir (in its direction, after cost) and exc (dir minus the market)."""
    out = []
    for r in sig_rows:
        start = r["start"]
        x = prices.ret(r["coin"], start, h)
        if x is None:
            continue
        mk = prices.market(start, h)
        d = r["side"] * x - cost
        tr = prices.trade(r["coin"], start, r["side"], h, cost=cost)
        out.append(dict(r, dir=d, exc=(d - r["side"] * mk) if mk is not None else None, day=start // DAY,
                        R=tr[0] if tr else None, tret=tr[1] if tr else None))
    return out


def halves(rows, w):
    """Earlier and later half of the signals' own period (split at the middle of their time span)."""
    if not rows:
        return [], []
    ts = [r["start"] for r in rows]
    mid = (min(ts) + max(ts)) / 2
    return [r for r in rows if r["start"] < mid], [r for r in rows if r["start"] >= mid]


def report(name, rows_by_h, w):
    out = {"method": name}
    for h, rows in rows_by_h.items():
        a, b = halves(rows, w)
        out[f"{h}h"] = {"all": summary(rows), "excess": summary(rows, "exc"), "first_half": summary(a),
                        "second_half": summary(b), "long": summary([r for r in rows if r["side"] > 0]),
                        "short": summary([r for r in rows if r["side"] < 0]), "R": summary(rows, "R"),
                        "R_first": summary(a, "R"), "R_second": summary(b, "R")}
    return out


# --------------------------------------------------------------------------- the methods
def signals_crowd(traders, skills, w, k=2, window_h=24, min_usd=25_000, min_conv=0.05, who="proven",
                  start_after=30 * DAY):
    """The live rule: a coin gets a signal when, within window_h hours, at least k more different proven traders
    opened (or added to) one side than the other. One signal per coin until window_h hours have passed."""
    ev = []
    for tr in traders:
        for hour, coin, side, usd in tr.entries():
            if hour < w[0] + start_after or usd < min_usd:
                continue
            day = hour // DAY * DAY
            s = skills.get(day, {}).get(tr.id)
            if not s or (who == "proven" and not proven(s)):
                continue
            if who == "hot" and tr.id not in skills.get(("hot", day), set()):
                continue
            if usd / max(s["av"], 1.0) < min_conv:
                continue
            ev.append((hour, coin, side, tr.id))
    ev.sort()
    rows, recent, last_sig = [], defaultdict(list), {}
    by_hour = defaultdict(list)
    for hour, coin, side, tid in ev:
        by_hour[hour].append((coin, side, tid))
    for hour in sorted(by_hour):
        touched = set()
        for coin, side, tid in by_hour[hour]:             # everything seen in this hour counts together
            recent[coin] = [e for e in recent[coin] if e[0] > hour - window_h * H] + [(hour, side, tid)]
            touched.add(coin)
        for coin in sorted(touched):
            if coin in last_sig and hour - last_sig[coin] < window_h * H:
                continue
            lst = recent[coin]
            lo = {t for h_, s_, t in lst if s_ > 0}
            sh = {t for h_, s_, t in lst if s_ < 0}
            net = len(lo) - len(sh)
            if abs(net) >= k:
                rows.append({"start": hour + H, "coin": coin, "side": 1 if net > 0 else -1, "n": abs(net)})
                last_sig[coin] = hour
    return rows


def signals_entries(traders, skills, w, min_usd=25_000, min_conv=0.05, who="proven"):
    rows = []
    for tr in traders:
        for hour, coin, side, usd in tr.entries():
            if hour < w[0] + 30 * DAY or usd < min_usd:
                continue
            day = hour // DAY * DAY
            s = skills.get(day, {}).get(tr.id)
            if not s:
                continue
            if who == "proven" and not proven(s):
                continue
            if who == "hot" and tr.id not in skills.get(("hot", day), set()):
                continue
            if usd / max(s["av"], 1.0) < min_conv:
                continue
            rows.append({"start": hour + H, "coin": coin, "side": side, "trader": tr.id, "usd": usd})
    return rows


def snapshot(traders, prices, t, ids, by_dollars=False, cap=2.0):
    """Per coin at time t: (weight long, weight short, traders long, traders short, usd long, usd short)."""
    agg = defaultdict(lambda: [0.0, 0.0, 0, 0, 0.0, 0.0])
    hour = t // H * H
    for tr in traders:
        if tr.id not in ids:
            continue
        av = tr.account(t) or tr.av_now
        for coin in tr.paths:
            p = tr.pos(coin, t)
            if not p:
                continue
            px = prices.close(coin, hour - H)
            if not px:
                continue
            usd = abs(p) * px
            if usd < 10_000:
                continue
            wgt = usd if by_dollars else min(cap, usd / max(av, 1.0))
            a = agg[coin]
            if p > 0:
                a[0] += wgt
                a[2] += 1
                a[4] += usd
            else:
                a[1] += wgt
                a[3] += 1
                a[5] += usd
    return agg


def signals_consensus(traders, prices, skills, w, step_h=24, min_traders=3, thr=0.6, who="proven"):
    rows = []
    t = (w[0] + 30 * DAY) // DAY * DAY
    while t < w[1] - 3 * DAY:
        day = t // DAY * DAY
        row = skills.get(day, {})
        ids = {k for k, s in row.items() if proven(s)} if who == "proven" else skills.get(("hot", day), set())
        snap = snapshot(traders, prices, t, ids, by_dollars=(who == "hot"))
        for coin, (wl, ws, nl, ns, ul, us) in snap.items():
            tot = wl + ws
            if not tot:
                continue
            share = wl / tot
            if who == "hot":
                if ul + us < 50_000:
                    continue
                side = 1 if share >= 0.65 else -1 if share <= 0.35 else 0
            else:
                if nl + ns < min_traders:
                    continue
                side = 1 if share >= thr else -1 if share <= 1 - thr else 0
            if side:
                rows.append({"start": t + H, "coin": coin, "side": side, "share": round(share, 3), "n": nl + ns})
        t += step_h * H
    return rows


def caller_scores(traders, prices, t_cut, lookback=45 * DAY, h=24, min_usd=25_000):
    """Each trader's hit rate on entries already judged by t_cut (entries before t_cut - h hours)."""
    out = {}
    for tr in traders:
        xs = []
        for hour, coin, side, usd in tr.entries():
            if usd < min_usd or not (t_cut - lookback <= hour < t_cut - h * H - H):
                continue
            x = prices.ret(coin, hour + H, h)
            mk = prices.market(hour + H, h)
            if x is not None and mk is not None:
                xs.append(side * (x - mk))
        if len(xs) >= 8:
            out[tr.id] = {"n": len(xs), "hit": sum(1 for x in xs if x > 0) / len(xs), "mean": statistics.fmean(xs)}
    return out


def signals_callers(traders, prices, w, top=30, h=24, min_usd=25_000, refresh_days=7):
    rows = []
    t = (w[0] + 45 * DAY) // DAY * DAY
    best = set()
    last = None
    while t < w[1] - 3 * DAY:
        if last is None or t - last >= refresh_days * DAY:
            sc = caller_scores(traders, prices, t, h=h, min_usd=min_usd)
            ranked = sorted(sc.items(), key=lambda kv: (-kv[1]["hit"], -kv[1]["mean"]))
            best = {k for k, v in ranked[:top] if v["hit"] > 0.5 and v["mean"] > 0}
            last = t
        for tr in traders:
            if tr.id not in best:
                continue
            for hour, coin, side, usd in tr.entries():
                if t <= hour < t + DAY and usd >= min_usd:
                    rows.append({"start": hour + H, "coin": coin, "side": side, "trader": tr.id, "usd": usd})
        t += DAY
    return rows


# --------------------------------------------------------------------------- run
def run(folder, cost=0.0009, groups=None, eval_days=None):
    """groups: only traders on these lists (e.g. {"pre", "fallen", "active"} leaves out traders picked for their
    results in the last month). eval_days: only signals in the last N days of the window."""
    meta, raw, candles = load(folder)
    w = meta["window"]
    prices = Prices(candles)
    traders = [Trader(d, w[0], w[1]) for d in raw if d.get("fills") is not None
               and (not groups or set(d.get("groups") or []) & set(groups))]
    days = list(range((w[0] // DAY + 1) * DAY, w[1], DAY))
    skills = skill_table(traders, days)
    for d in days:
        skills[("hot", d)] = hot_set(skills[d])
    info = {"traders": len(traders), "with_history": sum(1 for t in traders if t.pnl), "coins": len(prices.coins),
            "window_days": round((w[1] - w[0]) / DAY), "proven_per_day": round(statistics.fmean(
                [sum(1 for s in skills[d].values() if proven(s)) for d in days]), 1) if days else 0,
            "hot_per_day": round(statistics.fmean([len(skills[("hot", d)]) for d in days]), 1) if days else 0}
    results = [info]
    methods = {
        "old: dollar share of last month's top traders": signals_consensus(traders, prices, skills, w, who="hot"),
        "consensus of proven traders (one vote each, by conviction)": signals_consensus(traders, prices, skills, w),
        "entries of proven traders": signals_entries(traders, skills, w),
        "2+ proven traders opening the same side within 24 h": signals_crowd(traders, skills, w, k=2),
        "3+ proven traders opening the same side within 24 h": signals_crowd(traders, skills, w, k=3),
        "entries of last month's top traders": signals_entries(traders, skills, w, who="hot"),
        "entries of the best callers (own past hit rate)": signals_callers(traders, prices, w),
    }
    judged = {}
    for name, sig in methods.items():
        if eval_days:
            sig = [r for r in sig if r["start"] >= w[1] - eval_days * DAY]
        judged[name] = {h: judge(sig, prices, h, cost) for h in HORIZONS}
        results.append(report(name, judged[name], w))
    run.judged, run.meta = judged, meta
    return results


CHOSEN = {"method": "2+ proven traders opening the same side within 24 h", "hours": 24, "side": -1}


def side_record(rows, side=None):
    rr = [r for r in rows if side is None or r["side"] == side]
    rs = [r["R"] for r in rr if r.get("R") is not None]
    if not rs:
        return {"n": 0}
    a, b = halves(rr, None)
    sR, sx, sd = summary(rr, "R"), summary(rr, "exc"), summary(rr)
    ha, hb = summary(a, "R").get("mean"), summary(b, "R").get("mean")
    ts = [r["start"] for r in rr]
    return {"n": len(rs), "win": round(sum(1 for x in rs if x > 0) / len(rs), 3), "r": round(statistics.fmean(rs), 3),
            "t": sR.get("t"), "ret": round(statistics.fmean(r["tret"] for r in rr if r.get("tret") is not None), 5),
            "hit": sd.get("hit"), "excess": sx.get("mean"), "excess_t": sx.get("t"), "halves": [ha, hb],
            "halves_positive": (ha or 0) > 0 and (hb or 0) > 0, "coins": sd.get("coins"), "days": sd.get("days"),
            "period": f"{time.strftime('%b %d', time.gmtime(min(ts)))} to {time.strftime('%b %d %Y', time.gmtime(max(ts)))}"}


def half_up(x):
    """Rounds like the pages do (0.625 -> 63), so the text and the numbers agree."""
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def usd100(r):
    p = half_up((r or 0) * 100)
    return ("+$" if p > 0 else "−$" if p < 0 else "$") + str(abs(p))


def why_text(t, longs):
    """The plain explanation shown on the page, written from the numbers."""
    ha, hb = (t.get("halves") or [None, None])[:2]
    halves = (f"positive in both halves of the period ({usd100(ha)} and {usd100(hb)})" if t.get("halves_positive")
              else f"{usd100(ha)} in the first half of the period and {usd100(hb)} in the second")
    return (f"In a test without hindsight (the last 30 days; traders chosen only on what was known before), coins "
            f"that 2+ proven traders shorted together moved their way {half_up((t.get('hit') or 0) * 100)}% of the "
            f"time over the next day and did {abs((t.get('excess') or 0) * 100):.1f}% "
            f"{'better' if (t.get('excess') or 0) > 0 else 'worse'} than the market. Following them with the fixed "
            f"stop made {usd100(t.get('r'))} per $100 risked ({half_up((t.get('win') or 0) * 100)}% winners), {halves}. "
            f"{t.get('n')} trades on {t.get('coins')} coins is too few to call it proven: the live record decides. "
            f"Their longs did no better than the market ({half_up((longs.get('hit') or 0) * 100)}% right, "
            f"{(longs.get('excess') or 0) * 100:+.1f}% against the market), so long crowds are shown as information only.")


def export(folder, path):
    """smart_research.json: the clean test (no hindsight in who is looked at; last 30 days) of the rule the live
    engine trades, the same rule on the whole window (where the trader pool has some hindsight), the long side,
    and every method compared on the clean test."""
    m, h, side = CHOSEN["method"], CHOSEN["hours"], CHOSEN["side"]
    run(folder, groups={"pre", "active"}, eval_days=30)
    clean, meta = run.judged, run.meta
    run(folder)
    full = run.judged
    t = side_record(clean[m][h], side)
    out = {
        "generated": meta.get("t"), "window": meta["window"], "traders": meta.get("pool"), "method": m, "hours": h,
        "side": "short" if side < 0 else "long",
        "rule": ("When 2 or more proven Hyperliquid traders open or add to shorts on the same coin within 24 hours "
                 "(more of them than open longs), short it at the next hour: stop 1.5 typical daily moves away "
                 "(at least 1.5%), out after 24 hours."),
        "sub": "Proven traders shorting together",
        "verdict": "Promising", "tone": "warn",
        "why": why_text(t, side_record(clean[m][h], 1)),
        "why_short": (f"Shorts by 2+ proven traders were right {half_up((t.get('hit') or 0) * 100)}% of the time and "
                      f"{(t.get('excess') or 0) * 100:+.1f}% against the market over a day ({t.get('n')} trades, a "
                      "30-day test without hindsight): promising, too few to call proven. Their longs: no edge."),
        "tested": dict(t, note=f"{t.get('coins')} coins over {t.get('days')} days"),
        "full_window": side_record(full[m][h], side),
        "longs": side_record(clean[m][h], 1),
        "compared": [{"method": name, "hours": hh, "side": sd_name, **{k: v for k, v in side_record(rows, sd).items()
                                                                    if k in ("n", "hit", "excess", "r", "win")}}
                     for name, by in clean.items() for hh, rows in by.items() if hh == 24
                     for sd_name, sd in (("both", None), ("long", 1), ("short", -1))],
    }
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)
    return out


def fmt(results):
    lines = []
    info = results[0]
    lines.append(f"traders {info['traders']} (with history {info['with_history']}), coins {info['coins']}, "
                 f"window {info['window_days']} days, proven per day {info['proven_per_day']}, "
                 f"last month's top per day {info['hot_per_day']}")
    for r in results[1:]:
        lines.append("")
        lines.append(r["method"])
        for h in HORIZONS:
            x = r.get(f"{h}h") or {}
            a, e, f1, f2 = x.get("all", {}), x.get("excess", {}), x.get("first_half", {}), x.get("second_half", {})
            if not a.get("n"):
                lines.append(f"  {h:>2}h  no signals")
                continue
            rr, r1, r2 = x.get("R", {}), x.get("R_first", {}), x.get("R_second", {})
            lines.append(f"  {h:>2}h  n {a['n']:>6} ({a['days']} days, {a['coins']} coins)  hit {a['hit']:.1%}  "
                         f"mean {a['mean'] * 100:+.2f}% t {a['t']}  | excess {e.get('mean', 0) * 100:+.2f}% "
                         f"t {e.get('t')} hit {e.get('hit', 0):.1%} | halves {f1.get('mean', 0) * 100:+.2f}% / "
                         f"{f2.get('mean', 0) * 100:+.2f}% | trade {rr.get('mean', 0):+.3f}R t {rr.get('t')} "
                         f"win {rr.get('hit', 0):.0%} halves {r1.get('mean', 0):+.3f}/{r2.get('mean', 0):+.3f}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--json")
    ap.add_argument("--clean", action="store_true",
                    help="no hindsight in who is looked at: leave out traders chosen for their last-month results "
                         "and judge only the last 30 days")
    ap.add_argument("--export", help="write smart_research.json (the clean test of the live rule) to this path")
    a = ap.parse_args(argv)
    if a.export:
        out = export(a.folder, a.export)
        print(json.dumps({k: out[k] for k in ("verdict", "tested", "full_window", "longs")}, indent=1))
        return 0
    res = run(a.folder, groups={"pre", "fallen", "active"} if a.clean else None, eval_days=30 if a.clean else None)
    print(fmt(res))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(res, fh, indent=1)


if __name__ == "__main__":
    sys.exit(main())
