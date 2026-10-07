"""Download market history for strategy research: 1h and 4h candles, funding rates and futures
statistics (open interest, liquidations, long/short ratios) for the coins that trade on your DEXs.

Runs on GitHub Actions (see .github/workflows/data.yml): most cloud sandboxes cannot reach the
exchanges. Writes one gzip CSV per coin and data set under --out, plus universe.json and meta.json.

    python tools/fetch_history.py --out md --coins 220 --h1-days 400 --h4-days 1100
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import scanner as sc  # noqa: E402

STEP = {"1h": 3600, "4h": 14400}
MEXC_IV = {"1h": "Min60", "4h": "Hour4"}
GATE_IV = {"1h": "1h", "4h": "4h"}
HL_IV = {"1h": "1h", "4h": "4h"}
MEXC_FUND = ("https://contract.mexc.com/api/v1/contract/funding_rate/history?symbol={sym}"
             "&page_num={page}&page_size=100")
GATE_STATS = ("https://api.gateio.ws/api/v4/futures/usdt/contract_stats?contract={sym}&interval=4h"
              "&from={start}&limit=100")
STAT_FIELDS = ("lsr_taker", "lsr_account", "long_liq_usd", "short_liq_usd", "open_interest_usd",
               "top_lsr_account", "top_lsr_size", "mark_price")

LOG_LOCK = threading.Lock()


def hl_wait(weight):
    """Hyperliquid allows 1200 weight a minute per IP; stay near 900 across all threads."""
    sc.throttle_key("hl_weight", weight / 15.0)
META = {"started": None, "finished": None, "coins": {}, "errors": []}


def log(msg):
    with LOG_LOCK:
        print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


def err(msg):
    with LOG_LOCK:
        if len(META["errors"]) < 400:
            META["errors"].append(msg)


def write_gz(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    with open(path, "wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
            gz.write(buf.getvalue().encode())


def fmt(x):
    """Numbers to 9 significant digits (prices and volumes do not need more)."""
    if x is None:
        return ""
    return f"{x:.9g}" if isinstance(x, float) else str(x)


# ---------------------------------------------------------------- candles
def _page_back(fetch_chunk, tf, days, page=1000):
    """Walk back from now in pages until `days` are covered or the exchange has no older data."""
    step = STEP[tf]
    end = sc.now_ts()
    limit = end - days * 86400
    rows, e = [], end
    while e > limit:
        st = max(limit, e - step * page)
        chunk = fetch_chunk(st, e)
        if not chunk:
            break
        rows = chunk + rows
        oldest = min(r[0] for r in chunk)
        if oldest > st + step * 3:  # the exchange has nothing older
            break
        e = st - 1
    return sc._clean(rows)


def mexc_candles(coin, tf, days):
    sym = sc.exchange_symbol("mexc", coin["t"])
    return _page_back(lambda st, e: sc._mexc_rows(sc.FETCH(sc.MEXC_KLINE.format(
        sym=sym, iv=MEXC_IV[tf], start=st, end=e))), tf, days), sym


def gate_candles(coin, tf, days):
    sym = sc.exchange_symbol("gate", coin["t"])
    return _page_back(lambda st, e: sc._gate_rows(sc.FETCH(sc.GATE_KLINE_RANGE.format(
        sym=sym, iv=GATE_IV[tf], start=st, end=e))), tf, days), sym


def hl_candles(coin, tf, days):
    v = (coin.get("venues") or {}).get("hyperliquid")
    if not v:
        return [], None
    sym = v["sym"]
    end = sc.now_ts() * 1000
    start = end - min(days * 86400, STEP[tf] * 4990) * 1000
    hl_wait(20 + min(days * 86400 // STEP[tf], 5000) / 60)
    d = sc.FETCH(sc.HL_INFO, {"type": "candleSnapshot", "req": {"coin": sym, "interval": HL_IV[tf],
                                                                "startTime": start, "endTime": end}})
    rows = []
    for x in d if isinstance(d, list) else []:
        if isinstance(x, dict) and "t" in x:
            c = sc.fnum(x.get("c"))
            rows.append((int(x["t"]) // 1000, sc.fnum(x.get("o")), sc.fnum(x.get("h")), sc.fnum(x.get("l")), c,
                         (sc.fnum(x.get("v"), 0.0) or 0.0) * (c or 0.0)))
    return sc._clean(rows), sym


SOURCES = (("mexc", mexc_candles), ("gate", gate_candles), ("hyperliquid", hl_candles))


def candles(coin, tf, days):
    """The longest history from the first source that has the same asset (prices per 1 coin)."""
    best = None
    want = days * 86400 / STEP[tf]
    for name, fn in SOURCES:
        if name == "hyperliquid" and best is not None and len(best["candles"]) >= want * 0.6:
            break
        try:
            c, sym = fn(coin, tf, days)
        except Exception as e:  # noqa: BLE001
            if not (isinstance(e, sc.HttpError) and e.code in (400, 404)):
                err(f"{coin['t']} {tf} {name}: {e}")
            continue
        if len(c) < 60:
            continue
        ref = coin.get("ref_price")
        if not ref and name == "hyperliquid":
            ref = c[-1]["c"] / coin["venues"]["hyperliquid"]["mult"]
        scale, ok = sc.detect_scale(ref, c)
        if not ok:
            err(f"{coin['t']} {tf} {name}: price does not match the DEX price (different asset?)")
            continue
        if scale != 1.0:
            for x in c:
                for k in ("o", "h", "l", "c"):
                    x[k] *= scale
        got = {"src": name, "sym": sym, "scale": scale, "candles": c}
        if best is None or len(c) > len(best["candles"]) * 1.2:
            best = got
        if len(c) >= want * 0.95:
            break
    return best


# ---------------------------------------------------------------- funding
def mexc_funding(coin, days):
    sym = sc.exchange_symbol("mexc", coin["t"])
    limit_ms = (sc.now_ts() - days * 86400) * 1000
    rows, page = [], 1
    while page < 80:
        d = sc.FETCH(MEXC_FUND.format(sym=sym, page=page))
        data = (d or {}).get("data") or {}
        lst = data.get("resultList") or []
        if not lst:
            break
        for x in lst:
            t, r = x.get("settleTime"), sc.fnum(x.get("fundingRate"))
            if t is not None and r is not None:
                rows.append((int(t) // 1000, r, x.get("collectCycle")))
        if min(int(x.get("settleTime") or 0) for x in lst) < limit_ms:
            break
        if page >= int(data.get("totalPage") or page):
            break
        page += 1
    rows = sorted(set(r for r in rows if r[0] * 1000 >= limit_ms))
    return rows


def hl_funding(coin, days):
    v = (coin.get("venues") or {}).get("hyperliquid")
    if not v:
        return []
    start = (sc.now_ts() - days * 86400) * 1000
    end = sc.now_ts() * 1000
    rows = []
    while start < end:
        hl_wait(45)  # fundingHistory: 20 + 1 per 20 rows returned (up to 500)
        d = sc.FETCH(sc.HL_INFO, {"type": "fundingHistory", "coin": v["sym"], "startTime": start, "endTime": end})
        if not isinstance(d, list) or not d:
            break
        for x in d:
            rows.append((int(x["time"]) // 1000, sc.fnum(x.get("fundingRate")), sc.fnum(x.get("premium"))))
        last = max(int(x["time"]) for x in d)
        if last <= start or len(d) < 2:
            break
        start = last + 1
    return sorted(set(rows))


# ---------------------------------------------------------------- Gate.io futures statistics
def gate_stats(coin, days):
    sym = sc.exchange_symbol("gate", coin["t"])
    start = sc.now_ts() - days * 86400
    rows, seen = [], set()
    for _ in range(40):
        d = sc.FETCH(GATE_STATS.format(sym=sym, start=start))
        if not isinstance(d, list) or not d:
            break
        for x in d:
            t = int(x.get("time") or 0)
            if t and t not in seen:
                seen.add(t)
                rows.append([t] + [sc.fnum(x.get(k)) for k in STAT_FIELDS])
        last = max(int(x.get("time") or 0) for x in d)
        if last <= start or len(d) < 100:
            break
        start = last + 1
    return sorted(rows)


# ---------------------------------------------------------------- main
def pick_coins(n, min_vol):
    universe, status, ok = sc.build_universe()
    if not ok:
        raise SystemExit("no DEX market list could be loaded")
    rows = []
    for t, c in universe.items():
        if c.get("tradfi"):
            continue
        if sc.liquid_enough(c, min_vol):        # a KNOWN volume on your trade DEXs (v8.liquidity)
            rows.append(c)
    rows.sort(key=lambda c: -sc.liq_rank_value(c))
    if "BTC" in universe and all(c["t"] != "BTC" for c in rows[:n]):
        rows.insert(0, universe["BTC"])
    return rows[:n], status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="md")
    ap.add_argument("--coins", type=int, default=220)
    ap.add_argument("--min-vol", type=float, default=300_000)
    ap.add_argument("--h1-days", type=int, default=400)
    ap.add_argument("--h4-days", type=int, default=1100)
    ap.add_argument("--fund-days", type=int, default=400)
    ap.add_argument("--hl-funding-coins", type=int, default=30)
    ap.add_argument("--stats-coins", type=int, default=100)
    a = ap.parse_args()
    t0 = time.time()
    META["started"] = sc.now_ts()
    coins, status = pick_coins(a.coins, a.min_vol)
    log(f"{len(coins)} coins with at least ${a.min_vol:,.0f} a day on "
        f"{', '.join(sc.CFG['trade_dexes'])}")
    uni = [{"t": c["t"], "name": c.get("name"), "trade_vol": c.get("trade_vol"), "best_vol": c.get("best_vol"),
            "ref_price": c.get("ref_price"),
            "venues": {d: {"sym": v.get("sym"), "mult": v.get("mult"), "vol": v.get("vol"), "oi": v.get("oi"),
                           "funding8h": v.get("funding8h")} for d, v in (c.get("venues") or {}).items()}}
           for c in coins]
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "universe.json"), "w") as fh:
        json.dump({"time": sc.now_ts(), "min_vol": a.min_vol, "trade_dexes": list(sc.CFG["trade_dexes"]),
                   "dex_status": status, "coins": uni}, fh, indent=1)

    by_t = {c["t"]: c for c in coins}

    def one(t):
        c = by_t[t]
        m = META["coins"].setdefault(t, {})
        for tf, days in (("1h", a.h1_days), ("4h", a.h4_days)):
            got = candles(c, tf, days)
            if not got:
                m[tf] = None
                continue
            cs = got["candles"]
            write_gz(os.path.join(a.out, "h1" if tf == "1h" else "h4", f"{t}.csv.gz"), ["t", "o", "h", "l", "c", "qv"],
                     [[x["t"], fmt(x["o"]), fmt(x["h"]), fmt(x["l"]), fmt(x["c"]), fmt(x["qv"])] for x in cs])
            m[tf] = {"src": got["src"], "sym": got["sym"], "scale": got["scale"], "n": len(cs),
                     "first": cs[0]["t"], "last": cs[-1]["t"]}
        try:
            f = mexc_funding(c, a.fund_days)
            if f:
                write_gz(os.path.join(a.out, "fund_mexc", f"{t}.csv.gz"), ["t", "rate", "cycle_h"],
                         [[x[0], fmt(x[1]), x[2] if x[2] is not None else ""] for x in f])
            m["fund_mexc"] = len(f)
        except Exception as e:  # noqa: BLE001
            if not (isinstance(e, sc.HttpError) and e.code in (400, 404)):
                err(f"{t} mexc funding: {e}")
        return t

    def stats(t):
        c = by_t[t]
        try:
            s = gate_stats(c, a.fund_days)
            if s:
                write_gz(os.path.join(a.out, "stats_gate", f"{t}.csv.gz"), ["t"] + list(STAT_FIELDS),
                         [[r[0]] + [fmt(x) for x in r[1:]] for r in s])
            META["coins"].setdefault(t, {})["stats_gate"] = len(s)
        except Exception as e:  # noqa: BLE001
            if not (isinstance(e, sc.HttpError) and e.code in (400, 404)):
                err(f"{t} gate stats: {e}")

    def hlf(c):
        t = c["t"]
        try:
            f = hl_funding(c, a.fund_days)
            if f:
                write_gz(os.path.join(a.out, "fund_hl", f"{t}.csv.gz"), ["t", "rate", "premium"],
                         [[x[0], fmt(x[1]), fmt(x[2])] for x in f])
            META["coins"].setdefault(t, {})["fund_hl"] = len(f)
        except Exception as e:  # noqa: BLE001
            err(f"{t} hl funding: {e}")

    hl_top = sorted([c for c in coins if (c.get("venues") or {}).get("hyperliquid")],
                    key=lambda c: -((c["venues"]["hyperliquid"].get("vol")) or 0))[:a.hl_funding_coins]
    side = threading.Thread(target=lambda: [hlf(c) for c in hl_top], daemon=True)
    side.start()
    sc.parallel(one, list(by_t), workers=6)
    done = sum(1 for c in coins if (META["coins"].get(c["t"]) or {}).get("1h"))
    log(f"candles and funding: {done} of {len(coins)} coins with 1h history ({time.time() - t0:.0f}s)")
    sc.parallel(stats, [c["t"] for c in coins[:a.stats_coins]], workers=4)
    log(f"Gate.io statistics done ({time.time() - t0:.0f}s)")
    side.join(timeout=max(60.0, 5400 - (time.time() - t0)))
    log(f"Hyperliquid funding done for {sum(1 for c in hl_top if META['coins'].get(c['t'], {}).get('fund_hl'))} "
        f"coins ({time.time() - t0:.0f}s)")
    META["finished"] = sc.now_ts()
    META["scanner_errors"] = sc.ERRORS[:80]
    with open(os.path.join(a.out, "meta.json"), "w") as fh:
        json.dump(META, fh, indent=1, sort_keys=True)
    log(f"done in {time.time() - t0:.0f}s, {len(META['errors'])} errors")


if __name__ == "__main__":
    main()
