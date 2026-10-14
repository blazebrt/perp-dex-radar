"""Survivorship-free market history from the Binance public archive (data.binance.vision), for research only.

    python tools/v9/archive_fetch.py --out md_bn --cache bn_cache [--interval 4h] [--workers 48]

Every USD-M perpetual that ever traded on Binance Futures is in the archive, including the ones that were later
delisted (900 USDT perpetuals in October 2026, about 400 of them no longer listed). A coin is in the research
universe exactly while it has candles: from its listing to its delisting. That is a point-in-time universe without a
hand-picked coin list, so a backtest on it does not inherit survivorship bias.

Writes, in the legacy research layout that tools/research/qdata.Panel reads:
  md_bn/h4/{COIN}.csv.gz        t (UTC seconds, bar open), o, h, l, c, qv (quote volume, USDT), tbqv (taker buy qv)
  md_bn/fund_bn/{COIN}.csv.gz   t (settlement, UTC seconds), rate (paid by longs), interval_h
  md_bn/universe.json           every coin: symbol, first/last bar, listed or delisted, excluded (TradFi/index/stable)
  md_bn/meta.json               provenance: every archive file used with its S3 ETag and size, counts, timing

A symbol relisted after a gap of more than 7 days is split into separate coins (NAME, NAME~2, ...), so a delisting
gap is never filled with flat prices. TradFi perpetuals (stocks, commodities, FX), indices and stablecoins are
excluded from the crypto research universe and listed in universe.json with the reason.

Runs on GitHub Actions (data.binance.vision answers there; fapi.binance.com is geo-blocked for US runners)."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import gzip
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL = "https://data.binance.vision/"
UA = "perp-dex-radar-research/1.0 (+https://github.com/blazebrt/perp-dex-radar)"
VERSION = "v9.binance-archive/1"
STABLE = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "USDE", "PYUSD", "EUR", "AEUR", "USD1", "RLUSD", "XUSD",
          "BFUSD", "USDS"}
INDEX = {"BTCDOM", "DEFI", "FOOTBALL", "BLUEBIRD", "ALL"}
GAP_SPLIT_S = 7 * 86400
LOCK = threading.Lock()


def log(msg):
    with LOCK:
        print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


def http(url, tries=4, timeout=40):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.5 * (k + 1))
    raise last


def s3_list(prefix, delimiter=None):
    """All keys (with ETag and size) or common prefixes under `prefix`, following pagination."""
    keys, prefixes, marker = [], [], ""
    while True:
        q = {"prefix": prefix}
        if delimiter:
            q["delimiter"] = delimiter
        if marker:
            q["marker"] = marker
        text = http(S3 + "?" + urllib.parse.urlencode(q)).decode()
        for m in re.finditer(r"<Contents>(.*?)</Contents>", text, re.S):
            block = m.group(1)
            key = re.search(r"<Key>([^<]+)</Key>", block).group(1)
            etag = re.search(r"<ETag>([^<]+)</ETag>", block)
            size = re.search(r"<Size>(\d+)</Size>", block)
            keys.append({"key": key, "etag": etag.group(1).replace("&quot;", "").strip('"') if etag else None,
                         "size": int(size.group(1)) if size else None})
        page_prefixes = re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix></CommonPrefixes>", text)
        prefixes += page_prefixes
        if "<IsTruncated>true</IsTruncated>" not in text:
            break
        nxt = re.search(r"<NextMarker>([^<]+)</NextMarker>", text)
        marker = nxt.group(1) if nxt else (keys[-1]["key"] if keys and not page_prefixes else page_prefixes[-1])
    return keys, prefixes


def cached(cache, item):
    """The archive file's bytes, from the cache when the same ETag was downloaded before."""
    path = os.path.join(cache, item["key"])
    tag = path + ".etag"
    if os.path.exists(path) and os.path.exists(tag) and open(tag).read().strip() == (item["etag"] or ""):
        with open(path, "rb") as fh:
            return fh.read(), True
    raw = http(DL + item["key"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(raw)
    with open(tag, "w") as fh:
        fh.write(item["etag"] or "")
    return raw, False


def rows_of(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    text = z.read(z.namelist()[0]).decode()
    out = []
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0] or not row[0][0].isdigit():
            continue  # header line (newer files have one)
        out.append(row)
    return out


def ts_s(x):
    v = int(float(x))
    return v // 1000 if v < 10 ** 14 else v // 1_000_000   # ms (or µs in some newer files) -> s


def classify(base):
    from scanner import TRADFI, is_fx
    if base in STABLE:
        return "STABLECOIN"
    if base in INDEX:
        return "INDEX"
    if base in TRADFI or is_fx(base):
        return "TRADFI"
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="md_bn")
    ap.add_argument("--cache", default="bn_cache")
    ap.add_argument("--interval", default="4h")
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--limit", type=int, default=0, help="first N symbols only (testing)")
    a = ap.parse_args(argv)
    t0 = time.time()
    folder = {"4h": "h4", "1h": "h1", "1d": "d1"}[a.interval]
    for sub in (folder, "fund_bn"):
        os.makedirs(os.path.join(a.out, sub), exist_ok=True)
    _, prefixes = s3_list("data/futures/um/monthly/klines/", "/")
    symbols = sorted(p.rstrip("/").split("/")[-1] for p in prefixes)
    symbols = [s for s in symbols if s.endswith("USDT") and "_" not in s]
    if a.limit:
        symbols = symbols[:a.limit]
    log(f"{len(symbols)} USDT perpetual symbols in the archive")

    # 1. per symbol: list its monthly kline and funding files (ETag and size are the provenance), download them
    #    (cached by ETag) and write its research files at once, so memory stays flat across 900 symbols.
    stats = {"downloaded": 0, "from_cache": 0, "failed": []}

    def fetch(item):
        try:
            raw, hit = cached(a.cache, item)
            with LOCK:
                stats["from_cache" if hit else "downloaded"] += 1
            return rows_of(raw)
        except Exception as e:  # noqa: BLE001
            with LOCK:
                stats["failed"].append([item["key"], f"{type(e).__name__}: {str(e)[:120]}"])
            return None

    def write(name, seg, fund):
        with gzip.open(os.path.join(a.out, folder, f"{name}.csv.gz"), "wt", compresslevel=6) as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["t", "o", "h", "l", "c", "qv", "tbqv"])
            for r in seg:
                w.writerow([r[0]] + [f"{x:.10g}" for x in r[1:]])
        first, last = seg[0][0], seg[-1][0]
        with gzip.open(os.path.join(a.out, "fund_bn", f"{name}.csv.gz"), "wt", compresslevel=6) as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["t", "rate", "interval_h"])
            for x in fund:
                if first <= x[0] <= last + 14400:
                    w.writerow([x[0], f"{x[1]:.10g}", x[2] if x[2] is not None else ""])

    def process(sym):
        k, _ = s3_list(f"data/futures/um/monthly/klines/{sym}/{a.interval}/")
        f, _ = s3_list(f"data/futures/um/monthly/fundingRate/{sym}/")
        klines = sorted((x for x in k if x["key"].endswith(".zip")), key=lambda x: x["key"])
        funding = sorted((x for x in f if x["key"].endswith(".zip")), key=lambda x: x["key"])
        bars = {}
        for item in klines:
            for r in fetch(item) or []:
                t = ts_s(r[0])
                bars[t] = (t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[7]), float(r[10]))
        fund = []
        for item in funding:
            for r in fetch(item) or []:
                try:
                    fund.append((ts_s(r[0]), float(r[2]), int(float(r[1])) if r[1] else None))
                except (ValueError, IndexError):
                    continue
        fund = sorted(set(fund))
        series = [bars[t] for t in sorted(bars)]
        segs = []
        if series:
            cur = [series[0]]
            for prev, row in zip(series, series[1:]):
                if row[0] - prev[0] > GAP_SPLIT_S:
                    segs.append(cur)
                    cur = []
                cur.append(row)
            segs.append(cur)
        base = sym[:-4]
        reason = classify(base)
        out = []
        for i, seg in enumerate(segs):
            name = base if i == 0 else f"{base}~{i + 1}"
            last7 = seg[-42:]
            out.append({"t": name, "symbol": sym, "first_bar": seg[0][0], "last_bar": seg[-1][0], "bars": len(seg),
                        "segment": i + 1, "segments": len(segs), "excluded": reason,
                        "funding_settlements": sum(1 for x in fund if seg[0][0] <= x[0] <= seg[-1][0] + 14400),
                        "trade_vol": sum(r[5] for r in last7) / max(1.0, len(last7) / 6.0)})
            if not reason:
                write(name, seg, fund)
        months = [x["key"][-11:-4] for x in klines]
        return sym, klines + funding, months, out

    results = []
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for n, res in enumerate(ex.map(process, symbols), 1):
            results.append(res)
            if n % 100 == 0:
                log(f"  {n}/{len(symbols)} symbols ({stats['downloaded']} files downloaded, "
                    f"{stats['from_cache']} cached, {len(stats['failed'])} failed)")
    log(f"downloaded {stats['downloaded']}, cached {stats['from_cache']}, failed {len(stats['failed'])} "
        f"({time.time() - t0:.0f}s)")
    latest_month = max((m for r in results for m in r[2]), default=None)
    total = sum(len(r[1]) for r in results)

    # 2. the universe: listed at the archive's end, or delisted (a later segment of a relisted symbol is the listed one)
    coins, used = [], {}
    for sym, items, months, out in results:
        for c in out:
            c["listed_at_archive_end"] = bool(c["segment"] == c["segments"] and months and months[-1] == latest_month)
            c["delisted"] = not c["listed_at_archive_end"]
            coins.append(c)
            used[c["t"]] = items
    research = [c for c in coins if not c["excluded"]]
    uni = {"schema": VERSION, "source": "data.binance.vision (Binance USD-M futures public archive)",
           "interval": a.interval, "archive_end_month": latest_month, "time": int(time.time()),
           "min_vol": None, "trade_dexes": [], "coins": coins,
           "counts": {"symbols": len(symbols), "coins": len(coins), "research_coins": len(research),
                      "delisted_research_coins": sum(c["delisted"] for c in research),
                      "excluded": {r: sum(c["excluded"] == r for c in coins) for r in ("TRADFI", "INDEX", "STABLECOIN")}}}
    with open(os.path.join(a.out, "universe.json"), "w") as fh:
        json.dump(uni, fh, indent=1, sort_keys=True)
    meta = {"schema": VERSION, "built_at": int(time.time()), "seconds": round(time.time() - t0, 1),
            "interval": a.interval, "files": {k: [[x["key"], x["etag"], x["size"]] for x in v] for k, v in used.items()},
            "download": {k: (v if k != "failed" else v[:200]) for k, v in stats.items()}, "failed_count": len(stats["failed"])}
    with open(os.path.join(a.out, "meta.json"), "w") as fh:
        json.dump(meta, fh, sort_keys=True)
    log(f"wrote {len(research)} research coins ({uni['counts']['delisted_research_coins']} delisted), "
        f"excluded {uni['counts']['excluded']} ({time.time() - t0:.0f}s)")
    return 0 if len(stats["failed"]) < max(50, total // 100) else 1


if __name__ == "__main__":
    sys.exit(main())
