#!/usr/bin/env python3
"""The dashboard: all three versions, smart money and one accuracy scorecard in a single look.

    python dashboard.py --out site

Runs last in the scan. Reads what the scan just wrote in site/data (latest.json from the 15-minute radar,
quant.json from the quant desk, picks.json from the coin picks, smart.json from the smart-money engine) and the
tested records (picks_research.json, quant_research.json), then writes site/data/dashboard.json and publishes the
pages: the dashboard becomes the front page (index.html) and the coin picks move to picks.html. Every number comes
from those files; nothing is fetched. If this step fails, the front page stays the coin picks page.

Accuracy uses one unit everywhere: the average result per trade for each $100 risked, after fees (+$29 means a
trade made 0.29 times its risk on average), next to the share of winning trades and the number of trades.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = ("dashboard.html", "picks.html", "quant.html", "analyze.html", "analyze.js", "smart.html")


def load(path):
    try:
        with open(path) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x else None


def rnd(x, k=4):
    return round(x, k) if num(x) is not None else None


def month_year(t):
    return time.strftime("%b %Y", time.gmtime(t)) if num(t) else None


def per100(r):
    """R multiple -> dollars per $100 risked."""
    return round(r * 100) if num(r) is not None else None


def usd100(r):
    """R multiple as text: +$29 / −$7 per $100 risked."""
    p = per100(r)
    return "–" if p is None else ("+$" if p > 0 else "−$" if p < 0 else "$") + str(abs(p))


def combine(*recs):
    """Trade-weighted average of several records with n, win, R and ret."""
    recs = [r for r in recs if r and num(r.get("n"))]
    n = sum(r["n"] for r in recs)
    if not n:
        return {"n": 0}

    def w(k):
        xs = [(r[k], r["n"]) for r in recs if num(r.get(k)) is not None]
        m = sum(c for _, c in xs)
        return sum(v * c for v, c in xs) / m if m else None
    return {"n": n, "win": rnd(w("win")), "r": rnd(w("R")), "ret": rnd(w("ret"), 5)}


def rec(n=0, win=None, r=None, ret=None, period=None, note=None):
    out = {"n": int(n or 0), "win": rnd(win, 3), "r": rnd(r, 3), "per100": per100(r), "ret": rnd(ret, 5)}
    if period:
        out["period"] = period
    if note:
        out["note"] = note
    return out


# --------------------------------------------------------------------------- accuracy per version
def picks_accuracy(P, PR):
    """Swing picks scoring 80+ (tested on three years) and day trades scoring 80+ (tested on one year)."""
    sw = (PR or {}).get("swing") or {}
    lo, sh = (sw.get("long") or {}).get("ready"), (sw.get("short") or {}).get("ready")
    t = combine(lo, sh)
    years_ok = years_n = 0
    for x in (lo, sh):
        for y in ((x or {}).get("years") or {}).values():
            years_n += 1
            r = num(y.get("R"))
            years_ok += 1 if (r if r is not None else (num(y.get("ret")) or 0)) > 0 else 0
    tested = rec(t["n"], t.get("win"), t.get("r"), t.get("ret"), (PR or {}).get("period"))
    rp = (P or {}).get("record") or {}
    ls = rp.get("swing") or {}
    live = rec(ls.get("n"), ls.get("wr"), ls.get("avg"), ls.get("avg_ret"),
               f"since {month_year(rp.get('since'))}" if rp.get("since") else None)
    if t["n"] and (t.get("r") or 0) > 0 and years_n and years_ok == years_n:
        verdict, tone = "Proven", "good"
        why = (f"Positive after fees in every test year, longs and shorts ({years_ok} of {years_n}). "
               "Only picks scoring 80+ count; lower scores show what is setting up.")
    elif t["n"]:
        verdict, tone = ("Mixed", "warn") if (t.get("r") or 0) > 0 else ("No edge", "bad")
        why = f"Positive in {years_ok} of {years_n} test years." if years_n else ""
    else:
        verdict, tone, why = "Not tested", "muted", "No test results on this site yet."
    swing = {"name": "Coin picks · swing", "sub": "Scores of 80+, days to weeks", "page": "picks.html",
             "tested": tested, "live": live, "verdict": verdict, "tone": tone, "why": why}

    dy = (PR or {}).get("day") or {}
    bands = [b for side in ("long", "short") for b in ((dy.get(side) or {}).get("bands") or [])
             if num(b.get("lo")) is not None and b["lo"] >= 80]
    d = combine(*bands)
    per = dy.get("period")
    period = f"{month_year(per[0])} to {month_year(per[1])}" if isinstance(per, list) and len(per) == 2 else None
    ld = rp.get("day") or {}
    day = {"name": "Coin picks · day trades", "sub": "Scores of 80+, hours", "page": "picks.html#day",
           "tested": rec(d["n"], d.get("win"), d.get("r"), d.get("ret"), period),
           "live": rec(ld.get("n"), ld.get("wr"), ld.get("avg"), ld.get("avg_ret"),
                       f"since {month_year(rp.get('since'))}" if rp.get("since") else None)}
    if d["n"] and (d.get("r") or 0) <= 0:
        day.update(verdict="No edge", tone="bad",
                   why="Lost money after fees in the test at every score, longs and shorts. The day-trade score "
                       "shows conditions, not a proven edge: treat it as information.")
    elif d["n"]:
        day.update(verdict="Mixed", tone="warn", why="Positive in the test; not yet confirmed live.")
    else:
        day.update(verdict="Not tested", tone="muted", why="")
    return swing, day


def quant_accuracy(Q, QR):
    pf = (QR or {}).get("portfolio") or {}
    a = pf.get("all_trades") or {}
    w3 = (QR or {}).get("window_3y")
    period = f"{month_year(w3[0])} to {month_year(w3[1])}" if isinstance(w3, list) and len(w3) == 2 else None
    ret = a["avg"] * a["stop_pct"] if num(a.get("avg")) is not None and num(a.get("stop_pct")) else None
    tested = rec(a.get("n"), a.get("wr"), a.get("avg"), ret, period)
    if num(a.get("edge")) is not None:
        tested["vs_random"] = per100(a["edge"])
    la = (Q or {}).get("live_all") or {}
    live = rec(la.get("n"), la.get("wr"), la.get("avg"))
    if a.get("n") and (a.get("avg") or 0) > 0 and (a.get("t") or 0) >= 2:
        verdict, tone = "Proven", "good"
        why = (f"{len(pf.get('strategies') or [])} strategies that made money after fees, slippage and funding over "
               "three years and beat random entries taken at the same moments.")
    elif a.get("n"):
        verdict, tone, why = "Mixed", "warn", "Positive but not clearly above chance."
    else:
        verdict, tone, why = "Not tested", "muted", "No test results on this site yet."
    return {"name": "Quant desk", "sub": "Trend strategies, long and short", "page": "quant.html",
            "tested": tested, "live": live, "verdict": verdict, "tone": tone, "why": why}


def radar_accuracy(R):
    j = (R or {}).get("journal") or {}
    pk = j.get("picks") or {}
    rp, al = pk.get("replay") or {}, pk.get("all") or {}
    bt = j.get("bt") or {}
    tested = rec(rp.get("closed"), rp.get("win_rate"), rp.get("avg_r"), None,
                 f"last {bt.get('days')} days" if bt.get("days") else None)
    live = rec(al.get("closed"), al.get("win_rate"), al.get("avg_r"))
    st = j.get("strategies") or []
    passed = [s for s in st if s.get("status") == "passed" and not s.get("variant")]
    base = [s for s in st if not s.get("variant")]
    if passed:
        verdict, tone = "Passed", "good"
        why = f"{len(passed)} of {len(base)} strategies passed live paper trading; only those are published."
    elif base:
        verdict, tone = "Not proven", "warn"
        why = (f"0 of {len(base)} strategies have passed (40+ live paper trades on 10+ days that make money after "
               "costs and beat random entries). Nothing is published until one does.")
    else:
        verdict, tone, why = "Not proven", "muted", ""
    return {"name": "15m radar", "sub": "Fast long setups on 15-minute charts", "page": "radar.html",
            "tested": tested, "live": live, "verdict": verdict, "tone": tone, "why": why,
            "strategies": {"passed": len(passed), "total": len(base),
                           "testing": sum(1 for s in base if s.get("status") == "testing"),
                           "rejected": sum(1 for s in base if s.get("status") == "rejected")}}


def smart_accuracy(S, R):
    """The smart-money engine's own test (smart.json) when it exists; otherwise what the radar measured."""
    acc = (S or {}).get("accuracy") or {}
    if acc:
        t, lv = acc.get("tested") or {}, acc.get("live") or {}
        return {"name": "Smart money", "sub": acc.get("sub") or "Hyperliquid's proven traders", "page": "smart.html",
                "tested": rec(t.get("n"), t.get("win"), t.get("r"), t.get("ret"), t.get("period"), t.get("note")),
                "live": rec(lv.get("n"), lv.get("win"), lv.get("r"), lv.get("ret"), lv.get("period"), lv.get("note")),
                "verdict": acc.get("verdict") or "Testing", "tone": acc.get("tone") or "warn",
                "why": acc.get("why_short") or acc.get("why") or ""}
    j = (R or {}).get("journal") or {}
    les = next((x for x in j.get("lessons") or [] if x.get("bucket") == "sm_long"), None)
    st = next((x for x in j.get("strategies") or [] if x.get("id") == "SMF"), None)
    why = "The old method (the biggest money among last month's top traders) has no test history."
    if les and les.get("n") and per100(les.get("avg")) is not None:
        why = (f"When top traders were 65%+ long, the radar's long trades averaged {usd100(les['avg'])} per "
               f"$100 risked over {les['n']} trades: worse than without them.")
    return {"name": "Smart money", "sub": "Old method: last month's top traders", "page": "smart.html",
            "tested": rec(0), "live": rec(st.get("n"), st.get("wr"), st.get("exp")) if st else rec(0),
            "verdict": "No edge" if les and (les.get("avg") or 0) <= 0 else "Not tested", "tone": "bad" if les else "muted",
            "why": why}


# --------------------------------------------------------------------------- market now
def market_now(P, R, S):
    m = (P or {}).get("market") or {}
    btc = m.get("btc") or {}
    up = btc.get("up")
    daily = {"label": "Uptrend" if up else "Downtrend" if up is False else None, "up": up, "text": m.get("mood"),
             "btc": btc.get("price"), "btc_30d": rnd(btc.get("mom30")), "btc_7d": rnd(btc.get("mom7")),
             "above": m.get("above"), "total": m.get("total")}
    rg = (R or {}).get("regime") or {}
    short = {"label": rg.get("label"), "btc_3h": rnd(rg.get("btc3")), "btc_24h": rnd(rg.get("btc24")),
             "breadth": rnd(rg.get("breadth"), 3)}
    lab = rg.get("label")
    if up and lab == "Risk-on":
        v = "Tailwind on every timeframe: longs are favored."
    elif up and lab == "Risk-off":
        v = "Uptrend with a soft patch: swing longs keep the wind; fast 15-minute longs wait for the tape to firm up."
    elif up:
        v = "Uptrend, choppy last hours: swing longs favored; be picky with fast trades."
    elif up is False and lab == "Risk-on":
        v = "Bounce inside a downtrend: shorts on the daily, only quick longs."
    elif up is False and lab == "Risk-off":
        v = "Downtrend on every timeframe: shorts are favored; longs wait."
    elif up is False:
        v = "Downtrend, choppy last hours: shorts favored on the daily."
    else:
        v = None
    sm = (S or {}).get("market") or {}
    return {"daily": daily, "short": short, "fng": m.get("fng"), "verdict": v,
            "smart": {k: sm.get(k) for k in ("long_share", "traders", "label")} if sm else None}


# --------------------------------------------------------------------------- the three versions
def picks_card(P, acc_swing, acc_day):
    sw = ((P or {}).get("swing") or {}).get("all") or []
    dy = ((P or {}).get("daytrade") or {}).get("all") or []
    st = (P or {}).get("settings") or {}
    ready_at = st.get("ready") or 80
    ready = [r for r in sw if (r.get("score") or 0) >= ready_at]
    items = [{"coin": r["coin"], "side": r["side"], "score": r.get("score"), "label": r.get("label"),
              "kind": "swing", "ready": (r.get("score") or 0) >= ready_at, "setup": r.get("setup"),
              "chg24": rnd(r.get("chg24"))} for r in sw[:5]]
    if ready:
        status = {"tone": "good", "text": f"{len(ready)} swing pick{'s' if len(ready) > 1 else ''} ready (80+)"}
    else:
        status = {"tone": "wait", "text": "No swing setup ready (80+); the closest are below"}
    good_day = [r for r in dy if (r.get("score") or 0) >= 80]
    open_n = len(((P or {}).get("record") or {}).get("open") or [])
    return {"id": "picks", "name": "Coin picks", "page": "picks.html", "logo": "P",
            "what": "Swing and day-trade scores for every coin on your DEXs, with a trade plan",
            "updated": (P or {}).get("generated"), "status": status, "items": items,
            "day": [{"coin": r["coin"], "side": r["side"], "score": r.get("score")} for r in good_day[:5]],
            "open_paper": open_n, "accuracy": [acc_swing, acc_day]}


def quant_actionable(Q):
    """Open quant positions that may count as signals: the coin is VERIFIED_CRYPTO in the scan that published them
    (v8 Phase 3 closure; quant.py already keeps every other one out of "open" - this is defense in depth, and an
    "open" entry without an identity fails closed)."""
    return [o for o in (Q or {}).get("open") or [] if o.get("identity") == "VERIFIED_CRYPTO"]


def quant_card(Q, acc):
    op = quant_actionable(Q)
    names = {k: v.get("name") for k, v in ((Q or {}).get("strategies") or {}).items()}
    items = []
    for o in sorted(op, key=lambda o: -(o.get("t_in") or 0)):
        res = o.get("res") or {}
        items.append({"coin": o.get("c"), "side": "long" if (o.get("d") or 0) > 0 else "short",
                      "strategy": names.get(o.get("s"), o.get("s")), "r": rnd(res.get("r"), 3),
                      "move": rnd(res.get("gross")), "since": o.get("t_in")})
    sig = (Q or {}).get("signals") or []
    nl = sum(1 for o in op if (o.get("d") or 0) > 0)
    status = {"tone": "good" if op else "wait",
              "text": (f"{len(op)} open: {nl} long, {len(op) - nl} short" if op else "No open positions") +
                      (f" · {len(sig)} new this scan" if sig else "")}
    return {"id": "quant", "name": "Quant desk", "page": "quant.html", "logo": "Q",
            "what": "Three trend strategies, long and short, that passed a 3-year test",
            "updated": (Q or {}).get("generated"), "status": status, "items": items[:6], "open_n": len(op),
            "accuracy": [acc]}


def radar_card(R, acc):
    picks, watch = (R or {}).get("picks") or [], (R or {}).get("watch") or []
    gate = (R or {}).get("gate") or {}

    def item(p, kind):
        conv = p.get("conv") or {}
        return {"coin": p.get("coin"), "side": "long", "setup": p.get("short") or p.get("setup_name"),
                "status": p.get("status_text"), "score": conv.get("score"), "kind": kind}
    if picks:
        status = {"tone": "good", "text": f"{len(picks)} published pick{'s' if len(picks) > 1 else ''}"}
    elif gate.get("closed"):
        status = {"tone": "wait", "text": f"Standing aside: {gate.get('why') or 'the market gate is closed'}"}
    else:
        status = {"tone": "wait", "text": "No setup has passed its test; nothing published"}
    return {"id": "radar", "name": "15m radar", "page": "radar.html", "logo": "R",
            "what": "Fast long setups on 15-minute charts, paper-traded until a strategy proves itself",
            "updated": (R or {}).get("scan_t"), "status": status,
            "items": [item(p, "pick") for p in picks[:5]] + [item(w, "watch") for w in watch[:max(0, 5 - len(picks))]],
            "accuracy": [acc]}


# --------------------------------------------------------------------------- where the signals line up
def signals(P, Q, R, S):
    """Every current signal per coin: [{src, side, text, proven}]. One entry per source and coin."""
    out = {}

    def add(coin, src, side, text, proven):
        if not coin or side not in ("long", "short"):
            return
        lst = out.setdefault(coin, [])
        if any(x["src"] == src for x in lst):
            return
        lst.append({"src": src, "side": side, "text": text, "proven": bool(proven)})

    st = (P or {}).get("settings") or {}
    ready_at = st.get("ready") or 80
    for r in (((P or {}).get("swing") or {}).get("all") or [])[:10]:
        if (r.get("score") or 0) >= (st.get("watch") or 60):
            add(r.get("coin"), "swing", r.get("side"), f"{r.get('side')} {r.get('score', 0):.0f}"
                + (" ready" if r["score"] >= ready_at else ""), r["score"] >= ready_at)
    for r in (((P or {}).get("daytrade") or {}).get("all") or [])[:10]:
        if (r.get("score") or 0) >= 80:
            add(r.get("coin"), "day", r.get("side"), f"{r.get('side')} {r.get('score', 0):.0f}", False)
    names = {k: v.get("name") for k, v in ((Q or {}).get("strategies") or {}).items()}
    for o in quant_actionable(Q):
        side = "long" if (o.get("d") or 0) > 0 else "short"
        add(o.get("c"), "quant", side, f"{side} · {names.get(o.get('s'), o.get('s'))}", True)
    for p in (R or {}).get("picks") or []:
        add(p.get("coin"), "radar", "long", f"long · {p.get('short') or 'setup'}", True)
    for w in ((R or {}).get("watch") or [])[:5]:
        add(w.get("coin"), "radar", "long", f"watch · {w.get('short') or 'setup'}", False)
    for c in (S or {}).get("coins") or []:
        side = c.get("side")
        if side in ("long", "short") and c.get("signal"):
            add(c.get("coin"), "smart", side, c.get("text") or f"Smart money {side}", bool(c.get("proven")))
    return out


def agreement(sig, top=12):
    rows = []
    for coin, lst in sig.items():
        lo = [x for x in lst if x["side"] == "long"]
        sh = [x for x in lst if x["side"] == "short"]
        if len(lst) < 2:
            continue
        side = "long" if len(lo) > len(sh) else "short" if len(sh) > len(lo) else None
        agree = max(len(lo), len(sh))
        rows.append({"coin": coin, "side": side, "agree": agree, "against": min(len(lo), len(sh)),
                     "proven": sum(1 for x in (lo if side == "long" else sh if side == "short" else []) if x["proven"]),
                     "conflict": bool(lo and sh), "signals": lst})
    rows.sort(key=lambda r: (-(r["agree"] - r["against"]), -r["proven"], -r["agree"], r["coin"]))
    return rows[:top]


# --------------------------------------------------------------------------- smart money summary
def smart_card(S, R, acc):
    if S and S.get("coins") is not None:
        rows = S.get("coins") or []
        keep = ("coin", "side", "text", "long_share", "traders", "n_long", "n_short", "signal", "info")
        sig = [{k: c.get(k) for k in keep} for c in rows if c.get("signal")]
        info = [{k: c.get(k) for k in keep} for c in rows if c.get("info")]
        return {"source": "engine", "updated": S.get("generated"), "market": S.get("market"),
                "signals": sig[:6], "info": info[:6], "sides": S.get("signal_sides") or [],
                "long": [c for c in sig if c["side"] == "long"][:5], "short": [c for c in sig if c["side"] == "short"][:5],
                "traders": S.get("read") or S.get("traders_n"), "accuracy": [acc]}
    board = (R or {}).get("smart_board") or []
    rows = [{"coin": b.get("coin"), "long_n": b.get("long_n"), "short_n": b.get("short_n"),
             "long_usd": b.get("long_usd"), "short_usd": b.get("short_usd"), "share": b.get("share")} for b in board[:8]]
    return {"source": "radar", "updated": (R or {}).get("scan_t"), "board": rows,
            "traders": ((R or {}).get("smart") or {}).get("read"), "accuracy": [acc]}


# --------------------------------------------------------------------------- build and publish
def build(data_dir, research_dir=HERE):
    P = load(os.path.join(data_dir, "picks.json"))
    Q = load(os.path.join(data_dir, "quant.json"))
    R = load(os.path.join(data_dir, "latest.json"))
    S = load(os.path.join(data_dir, "smart.json"))
    PR = load(os.path.join(data_dir, "picks_research.json")) or load(os.path.join(research_dir, "picks_research.json"))
    QR = load(os.path.join(data_dir, "quant_research.json")) or load(os.path.join(research_dir, "quant_research.json"))
    sw, dy = picks_accuracy(P, PR)
    qa, ra, sa = quant_accuracy(Q, QR), radar_accuracy(R), smart_accuracy(S, R)
    times = [t for t in ((P or {}).get("generated"), (Q or {}).get("generated"), (R or {}).get("scan_t"),
                         (S or {}).get("generated")) if num(t)]
    nxt = (R or {}).get("next_scan_t")
    if not num(nxt) and P and num(P.get("generated")):
        nxt = P["generated"] + 60 * (P.get("next_scan_min") or 20)
    sig = signals(P, Q, R, S)
    return {
        "version": VERSION, "generated": int(time.time()), "updated": max(times) if times else None,
        "next_scan": nxt,
        "have": {"picks": bool(P), "quant": bool(Q), "radar": bool(R), "smart": bool(S)},
        "market": market_now(P, R, S),
        "versions": [picks_card(P, sw, dy), quant_card(Q, qa), radar_card(R, ra)],
        "agree": agreement(sig),
        "smart": smart_card(S, R, sa),
        "scorecard": [sw, qa, ra, dy, sa],
    }


def publish(out_dir, here=HERE):
    """The dashboard becomes the front page; the coin picks keep their own page (picks.html)."""
    for name in PAGES:
        src = os.path.join(here, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(out_dir, "index.html" if name == "dashboard.html" else name))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dashboard: all versions and their accuracy in one look")
    ap.add_argument("--out", default="site")
    a = ap.parse_args(argv)
    data_dir = os.path.join(a.out, "data")
    os.makedirs(data_dir, exist_ok=True)
    out = build(data_dir)
    with open(os.path.join(data_dir, "dashboard.json"), "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    publish(a.out)
    print(f"dashboard: {sum(out['have'].values())} of 4 sources, {len(out['agree'])} coins where signals meet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
