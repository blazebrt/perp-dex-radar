"""Extra research data for the coin score: Gate.io futures statistics (open interest, long/short
ratios of all accounts and of top traders, liquidations, taker buy/sell) and CoinGecko fundamentals
(market cap, supply, FDV, all-time high, plus a year of daily market cap and volume) for the coins in
<out>/universe.json (written by fetch_history.py).

Runs on GitHub Actions after fetch_history.py (see .github/workflows/data.yml):

    python tools/fetch_extra.py --out md
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
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import scanner as sc  # noqa: E402

GATE = "https://api.gateio.ws/api/v4/futures/usdt/contract_stats"
CG_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
CG_PRO = os.environ.get("COINGECKO_PLAN", "").strip().lower() == "pro"
CG = "https://pro-api.coingecko.com/api/v3" if (CG_KEY and CG_PRO) else "https://api.coingecko.com/api/v3"

STAT_FIELDS = ("lsr_taker", "lsr_account", "long_liq_usd", "short_liq_usd", "open_interest_usd",
               "top_lsr_account", "top_lsr_size", "mark_price")
STEP = {"1d": 86400, "4h": 14400, "1h": 3600}
UA = "perp-dex-radar research (github.com)"
META = {"started": None, "finished": None, "gate": {}, "coingecko": {}, "errors": []}
LOCK = threading.Lock()
_next = {}


def log(msg):
    with LOCK:
        print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


def err(msg):
    with LOCK:
        if len(META["errors"]) < 300:
            META["errors"].append(msg)


def wait(key, gap):
    with LOCK:
        t = time.monotonic()
        nxt = max(t, _next.get(key, 0.0))
        _next[key] = nxt + gap
    if nxt > t:
        time.sleep(nxt - t)


def get(url, key, gap, tries=4, backoff=20.0, headers=None):
    """GET JSON. Returns (data, None) or (None, 'error text with the body the server sent')."""
    last = None
    if key == "cg" and CG_KEY:
        url += ("&" if "?" in url else "?") + ("x_cg_pro_api_key=" if CG_PRO else "x_cg_demo_api_key=") + CG_KEY
        gap = min(gap, 2.2)
    for i in range(tries):
        wait(key, gap)
        try:
            h = {"User-Agent": UA, "Accept": "application/json"}
            h.update(headers or {})
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                body = ""
            last = f"HTTP {e.code} {body}"
            if e.code == 429 or e.code >= 500:
                time.sleep(backoff * (i + 1))
                continue
            return None, last
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(3 * (i + 1))
    return None, last


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
    if x is None:
        return ""
    return f"{x:.9g}" if isinstance(x, float) else str(x)


# ---------------------------------------------------------------- Gate.io statistics
def gate_series(sym, interval, days):
    """Walk back from now in pages of 100 points until `days` are covered or Gate has no older data."""
    step = STEP[interval]
    now = int(time.time())
    oldest = now - days * 86400
    rows, seen, errs = {}, set(), []
    start = now - 100 * step
    for _ in range(int(days * 86400 / (100 * step)) + 3):
        q = urllib.parse.urlencode({"contract": sym, "interval": interval, "from": max(start, oldest), "limit": 100})
        d, e = get(f"{GATE}?{q}", "gate", 0.12)
        if e:
            errs.append(e)
            break
        if not isinstance(d, list) or not d:
            break
        new = 0
        for x in d:
            t = int(x.get("time") or 0)
            if t and t not in seen:
                seen.add(t)
                rows[t] = [t] + [sc.fnum(x.get(k)) for k in STAT_FIELDS]
                new += 1
        if new == 0 or start <= oldest:
            break
        start -= 100 * step
    return [rows[t] for t in sorted(rows)], errs


def gate_all(coins, out, days):
    def one(t):
        sym = sc.exchange_symbol("gate", t)
        info = {}
        for iv, dd in (("1d", days), ("4h", days), ("1h", 60)):
            rows, errs = gate_series(sym, iv, dd)
            if rows:
                write_gz(os.path.join(out, f"stats_gate_{iv}", f"{t}.csv.gz"), ["t"] + list(STAT_FIELDS),
                         [[r[0]] + [fmt(x) for x in r[1:]] for r in rows])
            info[iv] = {"n": len(rows), "first": rows[0][0] if rows else None, "err": errs[:1]}
            if errs and not rows:
                err(f"gate {iv} {sym}: {errs[0]}")
        with LOCK:
            META["gate"][t] = info
        return t

    sc.parallel(one, coins, workers=3)


# ---------------------------------------------------------------- CoinGecko
def cg_markets(pages):
    rows = []
    for p in range(1, pages + 1):
        q = urllib.parse.urlencode({"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": p,
                                    "price_change_percentage": "7d,30d,1y"})
        d, e = get(f"{CG}/coins/markets?{q}", "cg", 7.0, tries=5, backoff=30.0)
        if e:
            err(f"coingecko markets page {p}: {e}")
            continue
        if isinstance(d, list):
            rows.extend(x for x in d if isinstance(x, dict))
    return rows


def cg_match(uni, markets):
    """Symbol -> CoinGecko id: same symbol, price within 25% of the DEX price, biggest market cap."""
    by_sym = {}
    for m in markets:
        by_sym.setdefault(str(m.get("symbol", "")).upper(), []).append(m)
    out = {}
    for c in uni:
        t, px = c["t"], c.get("ref_price")
        cands = by_sym.get(t.upper(), [])
        good = []
        for m in cands:
            p = sc.fnum(m.get("current_price"))
            if px and p and abs(p / px - 1) > 0.25:
                continue
            good.append(m)
        if good:
            out[t] = max(good, key=lambda m: sc.fnum(m.get("market_cap"), 0.0) or 0.0)
    return out


def cg_history(cid, days):
    q = urllib.parse.urlencode({"vs_currency": "usd", "days": days, "interval": "daily"})
    d, e = get(f"{CG}/coins/{urllib.parse.quote(cid)}/market_chart?{q}", "cg", 7.0, tries=5, backoff=30.0)
    if e or not isinstance(d, dict):
        return None, e
    px = {int(a[0] // 1000): a[1] for a in d.get("prices") or [] if isinstance(a, list) and len(a) == 2}
    mc = {int(a[0] // 1000): a[1] for a in d.get("market_caps") or [] if isinstance(a, list) and len(a) == 2}
    vo = {int(a[0] // 1000): a[1] for a in d.get("total_volumes") or [] if isinstance(a, list) and len(a) == 2}
    rows = [[t, px.get(t), mc.get(t), vo.get(t)] for t in sorted(px)]
    return rows, None


KEEP = ("id", "symbol", "name", "current_price", "market_cap", "market_cap_rank", "fully_diluted_valuation",
        "total_volume", "circulating_supply", "total_supply", "max_supply", "ath", "ath_change_percentage",
        "ath_date", "atl", "atl_date", "price_change_percentage_7d_in_currency",
        "price_change_percentage_30d_in_currency", "price_change_percentage_1y_in_currency", "last_updated")


def coingecko_all(uni, out, days, pages):
    markets = cg_markets(pages)
    log(f"CoinGecko: {len(markets)} coins in the market list")
    match = cg_match(uni, markets)
    log(f"CoinGecko: {len(match)} of {len(uni)} coins matched")
    snap = {t: {k: m.get(k) for k in KEEP} for t, m in match.items()}
    os.makedirs(os.path.join(out, "cg"), exist_ok=True)
    with open(os.path.join(out, "cg", "markets.json"), "w") as fh:
        json.dump({"time": int(time.time()), "coins": snap,
                   "top": [{k: m.get(k) for k in ("id", "symbol", "market_cap_rank", "market_cap",
                                                    "fully_diluted_valuation", "total_volume")} for m in markets]},
                  fh, separators=(",", ":"))
    for t, m in match.items():
        rows, e = cg_history(m["id"], days)
        if rows:
            write_gz(os.path.join(out, "cg", "hist", f"{t}.csv.gz"), ["t", "price", "mcap", "vol"],
                     [[r[0]] + [fmt(x) for x in r[1:]] for r in rows])
        META["coingecko"][t] = {"id": m["id"], "n": len(rows or []), "err": e}
        if e:
            err(f"coingecko {t} ({m['id']}): {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="md")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--cg-pages", type=int, default=6)
    ap.add_argument("--skip-gate", action="store_true")
    ap.add_argument("--skip-cg", action="store_true")
    a = ap.parse_args()
    META["started"] = int(time.time())
    with open(os.path.join(a.out, "universe.json")) as fh:
        uni = json.load(fh)["coins"]
    coins = [c["t"] for c in uni]
    log(f"{len(coins)} coins")
    threads = []
    if not a.skip_cg:
        threads.append(threading.Thread(target=coingecko_all, args=(uni, a.out, a.days, a.cg_pages), daemon=True))
    for th in threads:
        th.start()
    if not a.skip_gate:
        gate_all(coins, a.out, a.days)
        ok = sum(1 for v in META["gate"].values() if (v.get("1d") or {}).get("n"))
        log(f"Gate.io statistics: {ok} of {len(coins)} coins with daily history")
    for th in threads:
        th.join(timeout=4800)
    META["finished"] = int(time.time())
    with open(os.path.join(a.out, "meta_extra.json"), "w") as fh:
        json.dump(META, fh, indent=1)
    log(f"done: {len(META['errors'])} notes")


if __name__ == "__main__":
    main()
