#!/usr/bin/env python3
"""Smart money research data from Hyperliquid's public, read-only API.

    python tools/research/smart_collect.py --out smartdata [--days 90] [--pool 450] [--max-minutes 200]

Runs on GitHub Actions (the Smart money research workflow): the Hyperliquid API is not reachable from everywhere.
Saves under --out:

  meta.json             when it ran, the window, the groups, request counts
  leaderboard.json.gz   every account with $10k+ (or $100k+ all-time PnL): id, account value, PnL/ROI/volume by window
  traders_<n>.json.gz   per trader: leaderboard numbers, groups, account value and PnL history (portfolio), open
                        positions now, and every perp fill in the window (at most the 10,000 most recent)
  candles.json.gz       hourly candles of every perp with $300k+ a day and every coin the traders hold or trade

Addresses are replaced by a short hash (the analysis does not need them and the data branch is public).
The pool is chosen so the test can avoid hindsight: traders who were good BEFORE the last month ("pre"), the current
top of the last month ("hot", the set the live radar follows today), formerly good traders who lost money this month
("fallen", so blow-ups are not left out), and busy accounts with no profit condition ("active", a neutral control).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

INFO = "https://api.hyperliquid.xyz/info"
LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
UA = "Mozilla/5.0 (compatible; perp-dex-radar smart-money research)"
DIR = {"Open Long": "OL", "Close Long": "CL", "Open Short": "OS", "Close Short": "CS",
       "Long > Short": "LS", "Short > Long": "SL"}
STATS = {"requests": 0, "weight": 0, "errors": 0, "retries": 0}
T_START = time.time()


def log(msg):
    print(f"[{time.time() - T_START:7.0f}s] {msg}", flush=True)


def fnum(x, default=0.0):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else default
    except (TypeError, ValueError):
        return default


def hid(addr):
    return hashlib.sha1(addr.lower().encode()).hexdigest()[:12]


class Pace:
    """Keeps the request weight under the per-minute limit (Hyperliquid allows 1200 per IP; we use less)."""

    def __init__(self, per_min=1000):
        self.per_min, self.log = per_min, []

    def _trim(self):
        now = time.time()
        self.log = [(t, w) for t, w in self.log if now - t < 60]
        return now

    def wait(self, w):
        while True:
            now = self._trim()
            if sum(x for _, x in self.log) + w <= self.per_min or not self.log:
                self.log.append((now, w))
                return
            time.sleep(max(0.2, 60.05 - (now - self.log[0][0])))

    def add(self, w):
        """Weight charged after the answer (per item returned)."""
        self.log.append((time.time(), w))


PACE = Pace()
SLEEP = time.sleep


def http(url, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def info(body, weight, per_items=0, tries=6, timeout=60):
    """One info request within the weight budget; 429 and server errors are retried with backoff."""
    for k in range(tries):
        PACE.wait(weight)
        try:
            out = http(INFO, body, timeout)
            STATS["requests"] += 1
            STATS["weight"] += weight
            if per_items and isinstance(out, list) and len(out) >= per_items:
                extra = len(out) // per_items
                PACE.add(extra)
                STATS["weight"] += extra
            return out
        except urllib.error.HTTPError as e:
            STATS["errors"] += 1
            if e.code == 429 or e.code >= 500:
                STATS["retries"] += 1
                SLEEP(min(90, 5 * 2 ** k))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError):
            STATS["errors"] += 1
            STATS["retries"] += 1
            SLEEP(3 + 4 * k)
    raise RuntimeError(f"gave up on {body.get('type')}")


# --------------------------------------------------------------------------- leaderboard and the pool
def perf(row):
    out = {}
    for w in row.get("windowPerformances") or []:
        if isinstance(w, (list, tuple)) and len(w) == 2 and isinstance(w[1], dict):
            out[str(w[0])] = {k: fnum(w[1].get(k)) for k in ("pnl", "roi", "vlm")}
    return out


def board_rows(board):
    """Leaderboard rows as dicts: addr, av, and day/week/month/allTime pnl, roi, vlm."""
    out = []
    for r in (board or {}).get("leaderboardRows") or []:
        addr = r.get("ethAddress")
        if not isinstance(addr, str) or not addr.startswith("0x"):
            continue
        p = perf(r)
        z = {"pnl": 0.0, "roi": 0.0, "vlm": 0.0}
        out.append({"addr": addr, "av": fnum(r.get("accountValue")), "d": p.get("day", z), "w": p.get("week", z),
                    "m": p.get("month", z), "a": p.get("allTime", z)})
    return out


def is_mm(r):
    """Market makers and high-frequency books: huge volume against the account, no directional view."""
    return r["m"]["vlm"] > 150 * max(r["av"], 1.0)


def choose_pool(rows, size, mix=(0.5, 0.25, 0.12, 0.13)):
    """Groups (each trader can be in several): pre, hot, fallen, active. Returns [(row, [groups])], pre first."""
    live = [r for r in rows if not is_mm(r)]
    pre = sorted((r for r in live if r["m"]["vlm"] >= 1e6 and r["a"]["pnl"] - r["m"]["pnl"] >= 50_000),
                 key=lambda r: -(r["a"]["pnl"] - r["m"]["pnl"]))
    hot = sorted((r for r in live if r["av"] >= 50_000 and r["m"]["pnl"] > 0 and r["a"]["pnl"] > 0
                  and r["m"]["roi"] >= 0.05), key=lambda r: -(r["m"]["pnl"] + 0.5 * r["w"]["pnl"]))
    fallen = sorted((r for r in live if r["a"]["pnl"] - r["m"]["pnl"] >= 100_000 and r["m"]["pnl"] < 0),
                    key=lambda r: r["m"]["pnl"])
    active = sorted((r for r in live if r["av"] >= 100_000 and r["m"]["vlm"] >= 5e6), key=lambda r: -r["m"]["vlm"])
    want = {"pre": int(size * mix[0]), "hot": max(150, int(size * mix[1])), "fallen": int(size * mix[2]),
            "active": int(size * mix[3])}
    picked, order = {}, []
    for name, lst in (("pre", pre), ("hot", hot), ("fallen", fallen), ("active", active)):
        n = 0
        for r in lst:
            if n >= want[name]:
                break
            n += 1
            if r["addr"] not in picked:
                picked[r["addr"]] = (r, [])
                order.append(r["addr"])
            picked[r["addr"]][1].append(name)
    # tag the other groups too, so every trader knows all the lists it is on
    for name, lst in (("pre", pre[:want["pre"]]), ("hot", hot[:want["hot"]]), ("fallen", fallen[:want["fallen"]]),
                      ("active", active[:want["active"]])):
        for r in lst:
            if r["addr"] in picked and name not in picked[r["addr"]][1]:
                picked[r["addr"]][1].append(name)
    return [picked[a] for a in order[:max(size, want["hot"])]]


# --------------------------------------------------------------------------- per trader
def compact_portfolio(p):
    out = {}
    for item in p if isinstance(p, list) else []:
        if not (isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], dict)):
            continue
        w, d = item
        if w not in ("allTime", "perpAllTime", "month", "perpMonth", "week", "perpWeek"):
            continue
        out[w] = {"av": [[int(fnum(t) / 1000), round(fnum(v), 2)] for t, v in d.get("accountValueHistory") or []],
                  "pnl": [[int(fnum(t) / 1000), round(fnum(v), 2)] for t, v in d.get("pnlHistory") or []],
                  "vlm": round(fnum(d.get("vlm")), 2)}
    return out


def perp_coin(name):
    return isinstance(name, str) and name and not name.startswith("@") and "/" not in name and ":" not in name


def compact_state(st):
    """Open perp positions now: [coin, size (+ long / - short), entry, value, unrealized PnL, leverage]."""
    if not isinstance(st, dict):
        return None
    pos = []
    for ap in st.get("assetPositions") or []:
        p = ap.get("position") if isinstance(ap, dict) else None
        if not isinstance(p, dict) or not perp_coin(p.get("coin")):
            continue
        szi = fnum(p.get("szi"))
        if not szi:
            continue
        lev = p.get("leverage") if isinstance(p.get("leverage"), dict) else {}
        pos.append([p["coin"], szi, fnum(p.get("entryPx")), round(fnum(p.get("positionValue")), 2),
                    round(fnum(p.get("unrealizedPnl")), 2), fnum(lev.get("value"))])
    ms = st.get("marginSummary") or {}
    return {"t": int(fnum(st.get("time")) / 1000) or int(time.time()), "av": round(fnum(ms.get("accountValue")), 2),
            "ntl": round(fnum(ms.get("totalNtlPos")), 2), "pos": pos}


def compact_fill(f):
    coin = f.get("coin")
    if not perp_coin(coin):
        return None
    d = f.get("dir") or ""
    return [int(fnum(f.get("time")) / 1000), coin, 1 if f.get("side") == "B" else -1, fnum(f.get("sz")),
            fnum(f.get("px")), fnum(f.get("startPosition")), round(fnum(f.get("closedPnl")), 4),
            round(fnum(f.get("fee")), 4), DIR.get(d, d[:16]), 1 if f.get("crossed") else 0,
            1 if f.get("liquidation") else 0, f.get("tid")]


def fills_for(addr, start_ms, end_ms, max_pages=6):
    """Every fill from start_ms (oldest first). The API returns at most 2000 per answer and only the 10,000 most
    recent, so a very busy trader's history starts later; 'complete' says whether it covers the whole window."""
    seen, out, t0, pages = set(), [], start_ms, 0
    while pages < max_pages:
        pages += 1
        batch = info({"type": "userFillsByTime", "user": addr, "startTime": int(t0), "endTime": int(end_ms),
                      "aggregateByTime": True}, 20, per_items=20)
        if not isinstance(batch, list) or not batch:
            break
        new = 0
        for f in batch:
            key = (f.get("tid"), f.get("hash"), f.get("time"), f.get("coin"), f.get("sz"))
            if key in seen:
                continue
            seen.add(key)
            new += 1
            out.append(f)
        last = max(fnum(f.get("time")) for f in batch)
        if len(batch) < 2000 or not new or last <= t0:
            break
        t0 = last
    out.sort(key=lambda f: (fnum(f.get("time")), f.get("tid") or 0))
    rows = [x for x in (compact_fill(f) for f in out) if x]
    complete = len(out) < 9900
    return rows, complete, pages


def candles(coin, start_ms, end_ms):
    c = info({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": int(start_ms),
                                                 "endTime": int(end_ms)}}, 20, per_items=60)
    out = []
    for b in c if isinstance(c, list) else []:
        t = int(fnum(b.get("t")) / 1000)
        o, h, lo, cl, v = (fnum(b.get(k)) for k in ("o", "h", "l", "c", "v"))
        if t and cl > 0:
            out.append([t, o, h, lo, cl, round(v, 4)])
    return out


def save_gz(path, obj):
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(obj, fh, separators=(",", ":"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="smartdata")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--pool", type=int, default=450)
    ap.add_argument("--max-minutes", type=float, default=200.0)
    ap.add_argument("--min-coin-vol", type=float, default=300_000.0)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - a.days * 86400 * 1000
    deadline = T_START + a.max_minutes * 60

    log("leaderboard ...")
    board = None
    for k in range(4):
        try:
            board = http(LEADERBOARD, timeout=180)
            break
        except Exception as e:  # noqa: BLE001
            log(f"leaderboard failed ({e}); retrying")
            SLEEP(20 * (k + 1))
    rows = board_rows(board)
    log(f"leaderboard: {len(rows)} accounts")
    if not rows:
        sys.exit("no leaderboard")
    keep = [r for r in rows if r["av"] >= 10_000 or abs(r["a"]["pnl"]) >= 100_000]
    save_gz(os.path.join(a.out, "leaderboard.json.gz"),
            [[hid(r["addr"]), round(r["av"], 2)] + [round(r[w][k], 4 if k == "roi" else 2)
                                                    for w in ("d", "w", "m", "a") for k in ("pnl", "roi", "vlm")]
             for r in keep])
    pool = choose_pool(rows, a.pool)
    groups = {}
    for _, g in pool:
        for x in g:
            groups[x] = groups.get(x, 0) + 1
    log(f"pool: {len(pool)} traders {groups}")

    # the perp universe and hourly candles first (the test needs prices more than it needs every trader)
    meta_ctx = info({"type": "metaAndAssetCtxs"}, 20)
    universe = {}
    try:
        for asset, ctx in zip(meta_ctx[0]["universe"], meta_ctx[1]):
            if asset.get("isDelisted"):
                continue
            universe[asset["name"]] = fnum(ctx.get("dayNtlVlm"))
    except (KeyError, TypeError, IndexError):
        log("metaAndAssetCtxs: unexpected answer")
    want = [c for c, v in sorted(universe.items(), key=lambda kv: -kv[1]) if v >= a.min_coin_vol]
    for must in ("BTC", "ETH", "SOL", "HYPE"):
        if must in universe and must not in want:
            want.append(must)
    log(f"universe: {len(universe)} perps, {len(want)} with ${a.min_coin_vol:,.0f}+ a day")

    # open positions and account histories for the pool (cheap and expensive, in that order)
    traders = {}
    for i, (r, g) in enumerate(pool):
        st = None
        try:
            st = compact_state(info({"type": "clearinghouseState", "user": r["addr"]}, 2))
        except Exception as e:  # noqa: BLE001
            log(f"state {i}: {e}")
        traders[r["addr"]] = {"id": hid(r["addr"]), "groups": g, "av": round(r["av"], 2),
                              "lb": {w: r[w] for w in ("d", "w", "m", "a")}, "state": st}
    log(f"states read: {sum(1 for t in traders.values() if t['state'])}")
    held = {p[0] for t in traders.values() if t["state"] for p in t["state"]["pos"]}
    for c in sorted(held):
        if c in universe and c not in want:
            want.append(c)

    C = {}
    for i, c in enumerate(want):
        try:
            C[c] = candles(c, start_ms - 2 * 86400 * 1000, now_ms)
        except Exception as e:  # noqa: BLE001
            log(f"candles {c}: {e}")
        if i % 25 == 24:
            log(f"candles: {i + 1} of {len(want)}")
    save_gz(os.path.join(a.out, "candles.json.gz"), C)
    log(f"candles saved: {len(C)} coins")

    for i, (r, _) in enumerate(pool):
        if time.time() > deadline - 30 * 60:
            log("portfolio: stopping early to leave time for fills")
            break
        try:
            traders[r["addr"]]["portfolio"] = compact_portfolio(info({"type": "portfolio", "user": r["addr"]}, 20))
        except Exception as e:  # noqa: BLE001
            log(f"portfolio {i}: {e}")
        if i % 50 == 49:
            log(f"portfolios: {i + 1} of {len(pool)}")

    n_fills, done = 0, 0
    traded = set()
    for i, (r, _) in enumerate(pool):
        if time.time() > deadline:
            log(f"time budget reached after {done} traders' fills")
            break
        try:
            rows_f, complete, pages = fills_for(r["addr"], start_ms, now_ms)
        except Exception as e:  # noqa: BLE001
            log(f"fills {i}: {e}")
            continue
        t = traders[r["addr"]]
        t["fills"], t["fills_complete"], t["fills_pages"] = rows_f, complete, pages
        t["fills_from"] = rows_f[0][0] if rows_f else None
        n_fills += len(rows_f)
        traded.update(f[1] for f in rows_f)
        done += 1
        if i % 25 == 24:
            log(f"fills: {i + 1} of {len(pool)} traders, {n_fills} fills, weight {STATS['weight']}")

    extra = [c for c in sorted(traded) if c in universe and c not in C]
    for c in extra:
        if time.time() > deadline + 15 * 60:
            break
        try:
            C[c] = candles(c, start_ms - 2 * 86400 * 1000, now_ms)
        except Exception as e:  # noqa: BLE001
            log(f"candles {c}: {e}")
    if extra:
        save_gz(os.path.join(a.out, "candles.json.gz"), C)
        log(f"candles saved again: {len(C)} coins")

    items = [dict(v) for v in traders.values()]
    for k in range(0, len(items), 100):
        save_gz(os.path.join(a.out, f"traders_{k // 100}.json.gz"), items[k:k + 100])
    meta = {"t": now_ms // 1000, "window": [start_ms // 1000, now_ms // 1000], "days": a.days,
            "leaderboard_accounts": len(rows), "pool": len(pool), "groups": groups,
            "with_portfolio": sum(1 for t in items if t.get("portfolio")),
            "with_fills": sum(1 for t in items if "fills" in t), "fills": n_fills,
            "complete_fills": sum(1 for t in items if t.get("fills_complete")),
            "coins_with_candles": len(C), "stats": STATS, "minutes": round((time.time() - T_START) / 60, 1)}
    with open(os.path.join(a.out, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    log(f"done: {json.dumps(meta)}")


if __name__ == "__main__":
    main()
