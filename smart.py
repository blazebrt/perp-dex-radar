#!/usr/bin/env python3
"""Smart money: what Hyperliquid's proven traders are doing now, and how often following them was right.

    python smart.py --out site [--pages-url URL] [--journal smart_journal.json]

Each scan:
  1. the public leaderboard gives the proven traders: $100k+ made over their whole history, not losing more than
     15% of the account over the last 30 days, a real directional trader (not a market maker), $25k+ account;
  2. their open positions are read (public account state, read-only) and compared with the last scan: new and
     added positions are entries, the rest are exits or holds;
  3. per coin: how many proven traders are long and short (one vote each, weighted by size against their account,
     so one whale cannot outvote everyone), what they opened in the last 24 hours, their average entries;
  4. signals follow the rule that held up in the test (tools/research/smart_backtest.py, results in
     smart_research.json). Every signal is paper-traded with the tested rule, so a live record builds up next to
     the tested one;
  5. (v8 Phase 3) only a coin with crypto execution identity (VERIFIED_CRYPTO in the identity authority the scanner
     wrote for this scan) can be a signal, an information-only crowd or a paper trade. Any other coin stays visible
     with its positioning and an identity_block; without a same-scan authority nothing gets signal authority.

Writes site/data/smart.json (the page and the dashboard) and site/data/smart_journal.json (read back next scan).
Trader addresses are never published: they are replaced by a short hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import sys
import time

import scanner as sc
from v8 import identity as IDENTITY

VERSION = "1.0.0"
ENGINE = 1
H, DAY = 3600, 86400
LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO = "https://api.hyperliquid.xyz/info"

CFG = {
    # who counts as proven (the same rules as the test)
    "min_all_pnl": 100_000,       # made this much over the whole account history
    "max_month_loss": 0.15,       # and lost at most this share of the account over the last 30 days
    "min_account": 25_000,
    "mm_ratio": 150,              # 30-day volume above this many times the account: a market maker, left out
    "max_traders": 200,           # the most profitable first
    # positions
    "min_position_usd": 10_000,   # smaller positions do not count
    "conv_cap": 2.0,              # a position counts at most twice the account (leverage beyond that adds nothing)
    "entry_min_usd": 25_000,      # an entry this size or more
    "entry_min_conv": 0.05,       # and at least 5% of the trader's account
    "keep_entries_h": 72,
    # signals (set from the test; see smart_research.json and tools/research/smart_backtest.py)
    "signal": "entries",          # "entries": proven traders opening the same side; "consensus"; "none"
    "signal_window_h": 24,        # entries in the last 24 hours
    "signal_min_traders": 2,      # by at least this many different proven traders, net of the other side
    "signal_sides": ("short",),   # the side that held up in the test; the other side is shown as information
    "consensus_min_traders": 3,
    "consensus_share": 0.6,
    # the follow trade (paper): in at the price when the signal appears, stop 1.5 typical daily moves away
    # (at least 1.5%), out at the stop or after hold_h hours
    "hold_h": 24,
    "stop_k": 1.5,
    "min_stop": 0.015,
    "cost": 0.0009,               # fees and slippage, round trip
    "max_open": 12,
}


def hid(addr):
    return hashlib.sha1(str(addr).lower().encode()).hexdigest()[:12]


def fnum(x, d=0.0):
    v = sc.fnum(x)
    return d if v is None else v


def perf(row):
    out = {}
    for w in row.get("windowPerformances") or []:
        if isinstance(w, (list, tuple)) and len(w) == 2 and isinstance(w[1], dict):
            out[str(w[0])] = {k: fnum(w[1].get(k)) for k in ("pnl", "roi", "vlm")}
    return out


# --------------------------------------------------------------------------- who is proven
def select_traders(board, cfg=CFG):
    """Leaderboard rows -> proven traders, most profitable first: [{addr, id, av, all, month, week, roi30}]."""
    out = []
    for r in (board or {}).get("leaderboardRows") or []:
        addr = r.get("ethAddress")
        if not isinstance(addr, str) or not addr.startswith("0x"):
            continue
        av = fnum(r.get("accountValue"))
        p = perf(r)
        z = {"pnl": 0.0, "roi": 0.0, "vlm": 0.0}
        a, m, w = p.get("allTime", z), p.get("month", z), p.get("week", z)
        if av < cfg["min_account"] or a["pnl"] < cfg["min_all_pnl"]:
            continue
        if m["pnl"] < -cfg["max_month_loss"] * av:
            continue
        if m["vlm"] > cfg["mm_ratio"] * max(av, 1.0) or m["vlm"] <= 0:
            continue                      # market makers, and accounts that did not trade this month
        out.append({"addr": addr, "id": hid(addr), "av": round(av, 2), "all": round(a["pnl"], 2),
                    "month": round(m["pnl"], 2), "week": round(w["pnl"], 2), "roi30": round(m["roi"], 4)})
    out.sort(key=lambda t: -t["all"])
    return out[:cfg["max_traders"]]


# --------------------------------------------------------------------------- positions and what changed
def read_positions(traders, fetch=None):
    """{id: {"av": account, "pos": {coin: [size, usd, entry, upnl]}}} for the traders that could be read."""
    fetch = fetch or sc.FETCH

    def state(addr):
        return fetch(INFO, {"type": "clearinghouseState", "user": addr})

    states = sc.parallel(state, [t["addr"] for t in traders], workers=4)
    snap = {}
    for t in traders:
        st = states.get(t["addr"])
        if not isinstance(st, dict):
            continue
        av = fnum((st.get("marginSummary") or {}).get("accountValue")) or t["av"]
        pos = {}
        for ap in st.get("assetPositions") or []:
            p = ap.get("position") if isinstance(ap, dict) else None
            if not isinstance(p, dict):
                continue
            name = str(p.get("coin", ""))
            if ":" in name or name.startswith("@"):
                continue
            szi, val = fnum(p.get("szi")), abs(fnum(p.get("positionValue")))
            if not szi or not val:
                continue
            pos[name] = [szi, round(val if szi > 0 else -val, 2), fnum(p.get("entryPx")), round(fnum(p.get("unrealizedPnl")), 2)]
        snap[t["id"]] = {"av": round(av, 2), "pos": pos}
    return snap


def changes(prev, cur, now, cfg=CFG):
    """New and added positions since the last scan: [t, coin, side, usd added, share of the account, trader id].
    Sizes are compared, not dollar values, so a price move is not mistaken for an entry. Traders who were not in
    the last snapshot give no entries (their positions are not new to us)."""
    out = []
    for tid, c in cur.items():
        p = (prev or {}).get(tid)
        if p is None:
            continue
        av = max(c.get("av") or 0.0, 1.0)
        for coin, x in c["pos"].items():
            sz, usd = x[0], x[1]
            sz0 = (((p.get("pos") or {}).get(coin)) or [0.0])[0]
            if sz * sz0 < 0 or not sz0:
                added = abs(usd)                                    # a new position, or flipped to this side
            elif abs(sz) > abs(sz0) * 1.0001:
                added = (abs(sz) - abs(sz0)) * abs(usd) / abs(sz)   # added to the position
            else:
                continue
            if added >= cfg["entry_min_usd"] and added / av >= cfg["entry_min_conv"]:
                out.append([now, coin, 1 if sz > 0 else -1, round(added), round(added / av, 3), tid])
    return out


def aggregate(snap, traders, mids, entries, now, cfg=CFG):
    """Per coin: votes, conviction-weighted share, money, average entries, profit, and the last 24 hours."""
    info = {t["id"]: t for t in traders}
    agg = {}
    for tid, s in snap.items():
        av = max(s.get("av") or 0.0, 1.0)
        for name, (szi, usd, entry, upnl) in s["pos"].items():
            if abs(usd) < cfg["min_position_usd"]:
                continue
            coin, mult = sc.canon(name)
            a = agg.setdefault(coin, {"coin": coin, "hl": name, "n_long": 0, "n_short": 0, "w_long": 0.0,
                                      "w_short": 0.0, "usd_long": 0.0, "usd_short": 0.0, "upnl": 0.0,
                                      "in_profit": 0, "_el": 0.0, "_es": 0.0, "_tr": []})
            w = min(cfg["conv_cap"], abs(usd) / av)
            side = "long" if usd > 0 else "short"
            a["n_" + side] += 1
            a["w_" + side] += w
            a["usd_" + side] += abs(usd)
            a["_el" if usd > 0 else "_es"] += entry * abs(usd)
            a["upnl"] += upnl
            a["in_profit"] += 1 if upnl > 0 else 0
            a["_tr"].append({"id": tid[:6], "side": side, "usd": round(abs(usd)), "conv": round(w, 2),
                             "all": round((info.get(tid) or {}).get("all") or 0)})
    since = now - cfg["signal_window_h"] * H
    for e in entries:
        if e[0] < since:
            continue
        coin, _ = sc.canon(e[1])
        a = agg.setdefault(coin, {"coin": coin, "hl": e[1], "n_long": 0, "n_short": 0, "w_long": 0.0, "w_short": 0.0,
                                  "usd_long": 0.0, "usd_short": 0.0, "upnl": 0.0, "in_profit": 0, "_el": 0.0,
                                  "_es": 0.0, "_tr": []})
        k = "e_long" if e[2] > 0 else "e_short"
        a.setdefault(k, set()).add(e[5])
        a[k + "_usd"] = a.get(k + "_usd", 0.0) + e[3]
    out = []
    for coin, a in agg.items():
        tot = a["w_long"] + a["w_short"]
        mid = fnum(mids.get(a["hl"])) or None
        _, mult = sc.canon(a["hl"])
        row = {"coin": coin, "hl": a["hl"], "n_long": a["n_long"], "n_short": a["n_short"],
               "traders": a["n_long"] + a["n_short"], "long_share": round(a["w_long"] / tot, 3) if tot else None,
               "usd_long": round(a["usd_long"]), "usd_short": round(a["usd_short"]), "upnl": round(a["upnl"]),
               "in_profit": round(a["in_profit"] / max(1, a["n_long"] + a["n_short"]), 2),
               "entry_long": sc.sig6(a["_el"] / a["usd_long"] / mult) if a["usd_long"] else None,
               "entry_short": sc.sig6(a["_es"] / a["usd_short"] / mult) if a["usd_short"] else None,
               "price": sc.sig6(mid / mult) if mid else None,
               "new_long": len(a.get("e_long", ())), "new_short": len(a.get("e_short", ())),
               "new_long_usd": round(a.get("e_long_usd", 0.0)), "new_short_usd": round(a.get("e_short_usd", 0.0)),
               "top": sorted(a["_tr"], key=lambda x: -x["usd"])[:5]}
        out.append(row)
    out.sort(key=lambda r: -(r["usd_long"] + r["usd_short"]))
    return out


def crowd_of(row, cfg=CFG):
    """(side, text) when proven traders crowd into one side under the rule, else (None, text). Whether that side
    is a tested signal or information only is decided by signal_sides (see signal_of)."""
    if cfg["signal"] == "entries":
        nl, ns = row["new_long"], row["new_short"]
        if nl - ns >= cfg["signal_min_traders"]:
            return "long", f"{nl} proven trader{'s' if nl > 1 else ''} opened longs in 24 h" + (f", {ns} short{'s' if ns > 1 else ''}" if ns else "")
        if ns - nl >= cfg["signal_min_traders"]:
            return "short", f"{ns} proven trader{'s' if ns > 1 else ''} opened shorts in 24 h" + (f", {nl} long{'s' if nl > 1 else ''}" if nl else "")
    elif cfg["signal"] == "consensus" and row["long_share"] is not None and row["traders"] >= cfg["consensus_min_traders"]:
        if row["long_share"] >= cfg["consensus_share"]:
            return "long", f"{row['n_long']} of {row['traders']} proven traders long ({row['long_share'] * 100:.0f}% of the weight)"
        if row["long_share"] <= 1 - cfg["consensus_share"]:
            return "short", f"{row['n_short']} of {row['traders']} proven traders short ({(1 - row['long_share']) * 100:.0f}% of the weight)"
    if row["traders"]:
        return None, f"{row['n_long']} long, {row['n_short']} short"
    return None, f"{row['new_long']} new long, {row['new_short']} new short"


def signal_of(row, cfg=CFG):
    """(side, text, tested): tested is True for the side that held up in the test (a signal), False for the
    other side (information only), None when there is no crowd."""
    side, text = crowd_of(row, cfg)
    if not side:
        return None, text, None
    return side, text, side in cfg["signal_sides"]


# --------------------------------------------------------------------------- the follow trade (paper)
def vol24(candles):
    """Mean absolute 24-hour move over the last 7 days from hourly candles [{t, c}, ...] (oldest first)."""
    cl = {int(fnum(c.get("t")) / 1000) // H * H: fnum(c.get("c")) for c in candles or [] if fnum(c.get("c")) > 0}
    if not cl:
        return None
    last = max(cl)
    xs = []
    for d in range(1, 8):
        a, b = cl.get(last - d * DAY), cl.get(last - (d - 1) * DAY)
        if a and b:
            xs.append(abs(b / a - 1))
    return statistics.fmean(xs) if len(xs) >= 4 else None


def hl_candles(hl_coin, start, end, fetch=None):
    fetch = fetch or sc.FETCH
    return fetch(INFO, {"type": "candleSnapshot", "req": {"coin": hl_coin, "interval": "1h",
                                                          "startTime": int(start * 1000), "endTime": int(end * 1000)}})


def open_trade(sig, mids, now, fetch=None, cfg=CFG):
    px = fnum(mids.get(sig["hl"]))
    if not px:
        return None
    try:
        v = vol24(hl_candles(sig["hl"], now - 8 * DAY, now, fetch))
    except Exception:  # noqa: BLE001
        v = None
    stop = max(cfg["min_stop"], cfg["stop_k"] * v) if v is not None else 2 * cfg["min_stop"]
    d = 1 if sig["side"] == "long" else -1
    return {"id": f"{sig['coin']}-{now}", "coin": sig["coin"], "hl": sig["hl"], "d": d, "t_in": now, "px": px,
            "stop_pct": round(stop, 5), "stop": sc.sig6(px * (1 - d * stop)), "why": sig["text"],
            "t_out_by": now + cfg["hold_h"] * H}


def update_trades(J, mids, now, fetch=None, cfg=CFG):
    """Close paper trades at the stop (hourly highs and lows since entry) or at the time limit."""
    still = []
    for tr in J["open"]:
        exit_px, why = None, None
        try:
            cs = hl_candles(tr["hl"], tr["t_in"], now, fetch) or []
        except Exception:  # noqa: BLE001
            cs = []
        for c in cs:
            t = int(fnum(c.get("t")) / 1000)
            if t < tr["t_in"] // H * H or t >= tr["t_out_by"]:
                continue
            lo, hi = fnum(c.get("l")), fnum(c.get("h"))
            if tr["d"] > 0 and lo and lo <= tr["px"] * (1 - tr["stop_pct"]):
                exit_px, why = tr["px"] * (1 - tr["stop_pct"]), "stop"
                break
            if tr["d"] < 0 and hi and hi >= tr["px"] * (1 + tr["stop_pct"]):
                exit_px, why = tr["px"] * (1 + tr["stop_pct"]), "stop"
                break
        if exit_px is None and now >= tr["t_out_by"]:
            closes = [c for c in cs if int(fnum(c.get("t")) / 1000) + H <= tr["t_out_by"]]
            exit_px = fnum(closes[-1].get("c")) if closes else fnum(mids.get(tr["hl"])) or None
            why = "time"
        if exit_px:
            ret = tr["d"] * (exit_px / tr["px"] - 1) - cfg["cost"]
            J["closed"].append(dict(tr, t_out=now, exit_px=sc.sig6(exit_px), why=why, ret=round(ret, 5),
                                    r=round(ret / tr["stop_pct"], 3)))
        else:
            px = fnum(mids.get(tr["hl"]))
            if px:
                tr["last_px"] = px
                tr["r_now"] = round((tr["d"] * (px / tr["px"] - 1) - cfg["cost"]) / tr["stop_pct"], 3)
            still.append(tr)
    J["open"] = still
    J["closed"] = J["closed"][-600:]


def live_stats(closed):
    rs = [t["r"] for t in closed if t.get("r") is not None]
    if not rs:
        return {"n": 0}
    sd = statistics.stdev(rs) if len(rs) > 2 else None
    return {"n": len(rs), "win": round(sum(1 for r in rs if r > 0) / len(rs), 3), "r": round(statistics.fmean(rs), 3),
            "ret": round(statistics.fmean(t["ret"] for t in closed if t.get("r") is not None), 5),
            "t": round(statistics.fmean(rs) / (sd / len(rs) ** 0.5), 2) if sd else None}


# --------------------------------------------------------------------------- accuracy shown on the page
LIVE_MIN = 40      # live trades of the signal before the live record can change the verdict


def accuracy(research, J, cfg=CFG):
    """The tested record (smart_research.json, a test without hindsight) and the live paper record of the same
    rule, with a plain verdict. The test sets the verdict ("Promising" when positive but too small to be sure);
    after LIVE_MIN live trades the live record decides: Proven (positive, t 2+), No edge (not positive), or the
    test's verdict while it is still unclear. Paper trades of the information side are reported separately."""
    t = (research or {}).get("tested") or {}
    closed = J.get("closed") or []
    live = live_stats([x for x in closed if x.get("kind", "signal") == "signal"])
    info = live_stats([x for x in closed if x.get("kind") == "info"])
    if research and research.get("verdict"):
        verdict, tone = research["verdict"], research.get("tone") or "warn"
    elif t.get("n"):
        good = (t.get("r") or 0) > 0 and (t.get("t") or 0) >= 2 and t.get("halves_positive")
        verdict, tone = ("Proven", "good") if good else (("Mixed", "warn") if (t.get("r") or 0) > 0 else ("No edge", "bad"))
    else:
        verdict, tone = "Testing", "warn"
    why = (research or {}).get("why") or ""
    if live.get("n", 0) >= LIVE_MIN:
        if (live.get("r") or 0) > 0 and (live.get("t") or 0) >= 2:
            verdict, tone = "Proven", "good"
            why = f"Confirmed live: {live['n']} paper trades of the rule, {round(live['win'] * 100)}% winners. " + why
        elif (live.get("r") or 0) <= 0:
            verdict, tone = "No edge", "bad"
            why = f"Not confirmed live: {live['n']} paper trades of the rule lost money after fees. " + why
    return {"verdict": verdict, "tone": tone, "why": why, "why_short": (research or {}).get("why_short") or why,
            "sub": (research or {}).get("sub") or "Hyperliquid's proven traders",
            "tested": {k: t.get(k) for k in ("n", "win", "r", "ret", "hit", "excess", "period", "note")},
            "live": live, "live_info": info, "rule": (research or {}).get("rule"),
            "longs": (research or {}).get("longs"), "full_window": (research or {}).get("full_window")}


# --------------------------------------------------------------------------- journal
def new_journal(now):
    return {"engine": ENGINE, "version": VERSION, "created": now, "updated": now, "scans": 0, "snap": None,
            "entries": [], "open": [], "closed": []}


def load_journal(pages_url, path, now):
    if path:
        if os.path.exists(path):
            with open(path) as fh:
                return json.load(fh), "file"
        return new_journal(now), "new"
    if not pages_url:
        return new_journal(now), "new"
    try:
        J = sc.FETCH(f"{pages_url.rstrip('/')}/data/smart_journal.json?ts={now}", timeout=60)
    except sc.HttpError as e:
        if e.code == 404:
            return new_journal(now), "new"
        raise SystemExit(f"smart: could not read the published journal ({e}); stopping")
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"smart: could not read the published journal ({e}); stopping")
    if not isinstance(J, dict) or J.get("engine", 0) < ENGINE or not isinstance(J.get("open"), list):
        return new_journal(now), "new"
    return J, "site"


# --------------------------------------------------------------------------- crypto execution identity (v8 Phase 3)
def identity_block(row, auth):
    """None when the coin has crypto execution identity (VERIFIED_CRYPTO in this scan's identity authority), else
    the reason a crowd on it cannot be a signal: the coin's identity state as the scanner resolved it this scan, or
    IDENTITY_AUTHORITY_MISSING when no same-scan authority names it (fail closed)."""
    st = auth.state(row["coin"])
    if st == IDENTITY.VERIFIED_CRYPTO:
        return None
    if st == IDENTITY.UNVERIFIED:
        reason = "IDENTITY_UNVERIFIED"
    elif st == IDENTITY.AMBIGUOUS:
        reason = "AMBIGUOUS_EXPOSURE"
    elif st == IDENTITY.VERIFIED_TRADFI:
        dec = auth.decision(row["coin"])
        reason = dec if dec in ("TRADFI_CLASSIFIED", "TRADFI_EXPOSURE_EXCLUDED") else "TRADFI_CLASSIFIED"
    else:
        reason = "IDENTITY_AUTHORITY_MISSING"
    return {"reason": reason, "state": st,
            "authority": "SAME_SCAN" if auth.ok else auth.why, "in_authority": st is not None}


def apply_identity(row, auth):
    """The identity gate at the source. A crowd on a coin without crypto execution identity stays observable (traders,
    long and short counts, new positions, the crowd's text) but is not a signal, not information-only, not tested,
    has no side and opens no paper trade; the crowd it would have been is kept in identity_block. A verified crypto
    coin only gains its identity field."""
    row["identity"] = auth.state(row["coin"])
    blk = identity_block(row, auth)
    if blk is not None and row.get("side"):
        blk.update(crowd_side=row["side"], crowd_signal=row["signal"], crowd_info=row["info"])
        row["identity_block"] = blk
        row["side"] = None
        row["signal"] = row["info"] = row["tested"] = row["proven"] = False
    return row


def run(out_dir, pages_url=None, journal_path=None, fetch=None, now=None, cfg=CFG, identity=None):
    """identity: an IDENTITY.Authority (tests); by default this scan's authority written by the scanner into out_dir
    (data/v8/identity_authority.json). Without a usable one no crowd gets signal authority (fail closed)."""
    t0 = time.time()
    now = int(now or time.time())
    fetch = fetch or sc.FETCH
    if identity is None:
        from v8 import provenance
        identity = IDENTITY.load_authority(out_dir, now, provenance.scan_id(now))
    J, jsrc = load_journal(pages_url, journal_path, now)
    board = fetch(LEADERBOARD, timeout=120)
    traders = select_traders(board, cfg)
    if not traders:
        raise SystemExit("smart: no proven traders on the leaderboard")
    snap = read_positions(traders, fetch)
    mids = fetch(INFO, {"type": "allMids"}) or {}
    prev = (J.get("snap") or {}).get("traders") if J.get("snap") else None
    new = changes(prev, snap, now, cfg) if prev else []
    J["entries"] = [e for e in (J.get("entries") or []) if e[0] >= now - cfg["keep_entries_h"] * H] + new
    coins = aggregate(snap, traders, mids, J["entries"], now, cfg)
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, "smart_research.json")) as fh:
            research = json.load(fh)
    except (OSError, ValueError):
        research = None
    proven_rule = accuracy(research, J, cfg)["verdict"] == "Proven"
    crowds = []
    for row in coins:
        side, text, tested = signal_of(row, cfg)
        row["side"], row["text"] = side, text
        row["signal"] = bool(side) and bool(tested)           # the tested side: a signal
        row["info"] = bool(side) and tested is False           # the other side: shown as information only
        row["tested"] = row["proven"] = row["signal"] and proven_rule
        apply_identity(row, identity)                          # v8 Phase 3: VERIFIED_CRYPTO only
        if row["side"]:
            crowds.append(row)
    # paper trades: close what is due, then trade every new crowd with the tested rule (one trade per coin at a
    # time); the signal side builds the live record, the information side is kept apart to show what it is worth
    update_trades(J, mids, now, fetch, cfg)
    busy = {t["coin"] for t in J["open"]}
    for c in sorted(crowds, key=lambda r: (not r["signal"], -max(r["new_long"], r["new_short"]))):
        if len(J["open"]) >= cfg["max_open"]:
            break
        if c["coin"] in busy:
            continue
        tr = open_trade(c, mids, now, fetch, cfg)
        if tr:
            tr["kind"] = "signal" if c["signal"] else "info"
            J["open"].append(tr)
            busy.add(c["coin"])
    J["snap"] = {"t": now, "traders": snap}
    J["scans"] = J.get("scans", 0) + 1
    J["updated"] = now
    wl = sum(r["long_share"] * r["traders"] for r in coins if r["long_share"] is not None)
    wt = sum(r["traders"] for r in coins if r["long_share"] is not None)
    share = wl / wt if wt else None
    names = {t["id"]: t for t in traders}
    recent = sorted(J["entries"], key=lambda e: -e[0])[:40]
    out = {
        "version": VERSION, "generated": now, "duration_s": round(time.time() - t0, 1), "journal": jsrc,
        "rules": {k: cfg[k] for k in ("min_all_pnl", "max_month_loss", "min_account", "max_traders",
                                      "min_position_usd", "entry_min_usd", "entry_min_conv", "signal",
                                      "signal_window_h", "signal_min_traders", "hold_h", "stop_k", "min_stop")},
        "signal_sides": list(cfg["signal_sides"]),
        "compared": (research or {}).get("compared"),
        "traders_n": len(traders), "read": len(snap),
        "positions": sum(len(s["pos"]) for s in snap.values()),
        "market": {"long_share": round(share, 3) if share is not None else None, "traders": len(snap),
                   "label": ("Leaning long" if share >= 0.6 else "Leaning short" if share <= 0.4 else "Balanced")
                   if share is not None else None},
        "coins": sorted(coins, key=lambda r: (not r["signal"], not r["info"], -(r["usd_long"] + r["usd_short"])))[:60],
        "recent": [{"t": e[0], "coin": sc.canon(e[1])[0], "side": "long" if e[2] > 0 else "short", "usd": e[3],
                    "conv": e[4], "trader": e[5][:6], "trader_pnl": round((names.get(e[5]) or {}).get("all") or 0)}
                   for e in recent],
        "top_traders": [{"id": t["id"][:6], "all": t["all"], "month": t["month"], "av": t["av"],
                         "positions": len((snap.get(t["id"]) or {}).get("pos") or {})} for t in traders[:25]],
        "open": J["open"], "closed": J["closed"][-60:],
        "accuracy": accuracy(research, J, cfg),
        "identity_authority": identity.summary(),
    }
    data_dir = os.path.join(out_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "smart.json"), "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    with open(os.path.join(data_dir, "smart_journal.json"), "w") as fh:
        json.dump(J, fh, separators=(",", ":"))
    for name in ("smart.html",):
        p = os.path.join(here, name)
        if os.path.exists(p):
            shutil.copyfile(p, os.path.join(out_dir, name))
    rp = os.path.join(here, "smart_research.json")
    if os.path.exists(rp):
        shutil.copyfile(rp, os.path.join(data_dir, "smart_research.json"))
    try:  # v8 audit: trader selection and every held coin's disposition (never changes this run)
        from v8 import audit_smart
        audit_smart.audit(out_dir, now, cfg=cfg, board=board, traders=traders, snap=snap, coins=coins,
                          open_trades=J["open"], authority=identity.summary())
    except Exception as e:  # noqa: BLE001 - observability must never stop a run
        sc.log(f"v8 audit skipped: {type(e).__name__}: {e}")
    sc.log(f"smart money: {len(snap)} of {len(traders)} proven traders read, {len(new)} new entries, "
           f"{sum(1 for c in crowds if c['signal'])} signals and {sum(1 for c in crowds if c['info'])} long crowds, "
           f"{len(J['open'])} paper trades open, {len(J['closed'])} closed; "
           f"{sum(1 for c in coins if c.get('identity_block'))} crowds without crypto identity "
           f"(identity authority: {identity.why})")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Smart money: Hyperliquid's proven traders and how often they were right")
    ap.add_argument("--out", default="site")
    ap.add_argument("--pages-url", default=os.environ.get("PAGES_URL"))
    ap.add_argument("--journal", default=None)
    a = ap.parse_args(argv)
    run(a.out, pages_url=a.pages_url, journal_path=a.journal)
    return 0


if __name__ == "__main__":
    sys.exit(main())
