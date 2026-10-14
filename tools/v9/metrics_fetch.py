"""Binance USD-M daily `metrics` files (open interest and long/short ratios, every 5 minutes) for the research coins
of the survivorship-free archive, reduced to the archive's 4-hour bars. Research only (phase D2).

    python tools/v9/metrics_fetch.py --md md_bn --out md_metrics [--workers 64] [--survey-only]

For every research coin in md_bn/universe.json (delisted coins included; TradFi, index and stablecoin contracts
excluded, as in the archive), it lists data/futures/um/daily/metrics/{SYMBOL}/ and downloads every daily file that
overlaps the coin's life. It then writes:

  md_metrics/m4/{COIN}.csv.gz   t (4h bar open, UTC s), oi (contracts), oi_usd, top_acct_ls (top traders, accounts),
                                top_pos_ls (top traders, positions), acct_ls (all accounts), taker_ls (taker buy/sell
                                volume ratio, mean over the bar), n (5-minute rows in the bar)
  md_metrics/meta.json          coverage per coin, header variants, failures, timing, and a provenance digest of every
                                file used (sha256 over "key etag size" lines, per symbol and overall)
  md_metrics/survey.json        what the archive holds: files and first/last day per symbol (also with --survey-only)

**Bars and look-ahead.** Bars use the archive's grid (00:00 UTC + 4h). The snapshot columns (oi, oi_usd and the
three long/short ratios) are the bar's last 5-minute row by create_time. A row stamped exactly at a bar's end belongs
to the next bar, as a funding settlement at the daily close does, so a bar never carries a value from after its
close. A day file maps to exactly six bars, so each file is reduced as soon as it is read and memory stays flat.

**Segments.** A symbol relisted after a gap is split into separate coins in the archive (NAME, NAME~2). A metrics row
belongs to the segment whose [first_bar, last_bar + 4h) holds it; rows outside every segment (no trading) are dropped.

Runs on GitHub Actions (data.binance.vision answers there). It imports the archive fetcher's helpers and does not
change it; tools/v9/archive_fetch.py is bound to the phase B evidence."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import gzip
import hashlib
import io
import json
import os
import sys
import threading
import time
import urllib.parse
import zipfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import archive_fetch as AF  # noqa: E402

VERSION = "v9.binance-metrics/1"
BAR = 14400
DAY = 86400
PREFIX = "data/futures/um/daily/metrics/"
COLS = ["create_time", "symbol", "sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]
OUT_COLS = ["t", "oi", "oi_usd", "top_acct_ls", "top_pos_ls", "acct_ls", "taker_ls", "n"]
SNAPSHOT = {"oi": "sum_open_interest", "oi_usd": "sum_open_interest_value", "top_acct_ls": "count_toptrader_long_short_ratio",
            "top_pos_ls": "sum_toptrader_long_short_ratio", "acct_ls": "count_long_short_ratio"}
LOCK = threading.Lock()


def _ts(v):
    """create_time as UTC seconds: "YYYY-MM-DD HH:MM:SS" (the archive's format) or epoch ms / s."""
    v = (v or "").strip()
    if not v:
        return None
    if "-" in v:
        try:
            return int(datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return None
    try:
        return AF.ts_s(v)
    except ValueError:
        return None


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def parse_day(raw):
    """One daily metrics zip -> ({bar_t: partial bar}, header tuple or None).

    A partial bar keeps its last row's time and snapshot columns and the taker ratio's sum and count, so two pieces of
    one bar (a day file that also holds the next day's 00:00 row) merge exactly (merge_bar)."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    text = z.read(z.namelist()[0]).decode("utf-8", "replace")
    rows = [r for r in csv.reader(io.StringIO(text)) if r and any(x.strip() for x in r)]
    head = None
    if rows and not rows[0][0].strip()[:1].isdigit():
        head = tuple(h.strip().lower() for h in rows[0])
        rows = rows[1:]
    cols = list(head) if head else COLS
    idx = {c: cols.index(c) for c in COLS if c in cols}
    if "create_time" not in idx:
        return {}, head
    bars = {}
    for r in rows:
        ts = _ts(r[idx["create_time"]]) if idx["create_time"] < len(r) else None
        if ts is None:
            continue
        b = ts - ts % BAR
        bar = bars.setdefault(b, {"_last": -1, "_tk": 0.0, "_tn": 0, "n": 0})
        bar["n"] += 1
        get = lambda c: _f(r[idx[c]]) if c in idx and idx[c] < len(r) else None  # noqa: E731
        tk = get("sum_taker_long_short_vol_ratio")
        if tk is not None:
            bar["_tk"] += tk
            bar["_tn"] += 1
        if ts >= bar["_last"]:
            bar["_last"] = ts
            for out, src in SNAPSHOT.items():
                bar[out] = get(src)
    out = {}
    for b, bar in bars.items():
        row = {k: bar.get(k) for k in SNAPSHOT}
        row.update(last=bar["_last"], tk=bar["_tk"], tn=bar["_tn"], n=bar["n"])
        out[b] = row
    return out, head


def merge_bar(a, b):
    """Two partial bars of the same 4h bar: snapshot from the later last row, the taker sums and row counts added."""
    if a is None:
        return dict(b)
    later = b if b["last"] >= a["last"] else a
    out = {k: later.get(k) for k in SNAPSHOT}
    out.update(last=later["last"], tk=a["tk"] + b["tk"], tn=a["tn"] + b["tn"], n=a["n"] + b["n"])
    return out


def finish(bar):
    """The written bar: the snapshot columns, the mean taker ratio and the row count."""
    out = {k: bar.get(k) for k in SNAPSHOT}
    out["taker_ls"] = bar["tk"] / bar["tn"] if bar["tn"] else None
    out["n"] = bar["n"]
    return out


def day_of(key):
    """data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2023-01-01.zip -> UTC seconds of that day, or None."""
    name = key.rsplit("/", 1)[-1]
    if not name.endswith(".zip"):
        return None
    try:
        return int(datetime.strptime(name[-14:-4], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def segments_by_symbol(universe):
    """{symbol: [(coin, first_bar, end)]} for the research coins, end = last_bar + one bar (exclusive)."""
    out = {}
    for c in universe.get("coins") or []:
        if c.get("excluded"):
            continue
        out.setdefault(c["symbol"], []).append((c["t"], int(c["first_bar"]), int(c["last_bar"]) + BAR))
    for v in out.values():
        v.sort(key=lambda x: x[1])
    return out


def wanted(day, segs):
    """Does the day [day, day + 1d) overlap a segment of the symbol?"""
    return any(day + DAY > lo and day < hi for _, lo, hi in segs)


def coin_of(t, segs):
    for name, lo, hi in segs:
        if lo <= t < hi:
            return name
    return None


def provenance(items):
    h = hashlib.sha256()
    for it in sorted(items, key=lambda x: x["key"]):
        h.update(f"{it['key']} {it.get('etag')} {it.get('size')}\n".encode())
    return h.hexdigest()


def write_coin(path, bars):
    with gzip.open(path, "wt", compresslevel=6) as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(OUT_COLS)
        for t in sorted(bars):
            b = finish(bars[t])
            w.writerow([t] + ["" if b.get(k) is None else f"{b[k]:.10g}" for k in OUT_COLS[1:-1]] + [b["n"]])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--md", default="md_bn", help="the archive layout (only universe.json is read)")
    ap.add_argument("--out", default="md_metrics")
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--survey-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="first N symbols only (testing)")
    ap.add_argument("--max-files", type=int, default=800000, help="stop after the survey above this many files")
    a = ap.parse_args(argv)
    t0 = time.time()
    uni = json.load(open(os.path.join(a.md, "universe.json")))
    segs = segments_by_symbol(uni)
    symbols = sorted(segs)[: a.limit] if a.limit else sorted(segs)
    os.makedirs(os.path.join(a.out, "m4"), exist_ok=True)
    AF.log(f"{len(symbols)} research symbols ({sum(len(segs[s]) for s in symbols)} coins)")

    # 1. list every symbol's daily files
    def listing(sym):
        try:
            keys, _ = AF.s3_list(f"{PREFIX}{sym}/")
            return sym, [k for k in keys if k["key"].endswith(".zip")], None
        except Exception as e:  # noqa: BLE001
            return sym, [], f"{type(e).__name__}: {str(e)[:120]}"
    listed, list_failed = {}, {}
    with cf.ThreadPoolExecutor(min(a.workers, 48)) as ex:
        for sym, keys, err in ex.map(listing, symbols):
            listed[sym] = keys
            if err:
                list_failed[sym] = err
    survey = {"schema": VERSION, "time": int(time.time()), "symbols": len(symbols),
              "symbols_with_files": sum(1 for s in symbols if listed[s]), "list_failed": list_failed,
              "files_listed": sum(len(v) for v in listed.values()), "per_symbol": {}}
    for s in symbols:
        days = sorted(d for d in (day_of(k["key"]) for k in listed[s]) if d is not None)
        use = [d for d in days if wanted(d, segs[s])]
        survey["per_symbol"][s] = {"files": len(days), "files_in_life": len(use),
                                   "first_day": days[0] if days else None, "last_day": days[-1] if days else None,
                                   "first_bar": segs[s][0][1], "last_bar": segs[s][-1][2] - BAR}
    firsts = sorted(v["first_day"] for v in survey["per_symbol"].values() if v["first_day"])
    survey["first_day_overall"] = firsts[0] if firsts else None
    survey["first_day_quartiles"] = [firsts[int(q * (len(firsts) - 1))] for q in (0.25, 0.5, 0.75)] if firsts else None
    survey["files_in_life"] = sum(v["files_in_life"] for v in survey["per_symbol"].values())
    with open(os.path.join(a.out, "survey.json"), "w") as fh:
        json.dump(survey, fh, indent=1, sort_keys=True)
    AF.log(f"listed {survey['files_listed']} files, {survey['files_in_life']} inside the coins' lives; "
           f"{len(list_failed)} listings failed ({time.time() - t0:.0f}s)")
    if a.survey_only:
        return 0
    if survey["files_in_life"] > a.max_files:
        AF.log(f"{survey['files_in_life']} files exceed --max-files {a.max_files}: stopping after the survey")
        return 2

    # 2. download and reduce every wanted file (each to its six bars at once)
    tasks = [(s, k) for s in symbols for k in listed[s] if (d := day_of(k["key"])) is not None and wanted(d, segs[s])]
    per_coin = {}
    heads, failed, done = {}, [], [0]

    def fetch(task):
        sym, item = task
        try:
            raw = AF.http(AF.DL + urllib.parse.quote(item["key"]))
            bars, head = parse_day(raw)
            return sym, item, bars, head, None
        except Exception as e:  # noqa: BLE001
            return sym, item, None, None, f"{type(e).__name__}: {str(e)[:120]}"

    with cf.ThreadPoolExecutor(a.workers) as ex:
        for sym, item, bars, head, err in ex.map(fetch, tasks):
            done[0] += 1
            if err:
                failed.append([item["key"], err])
            else:
                heads[head] = heads.get(head, 0) + 1
                for t, b in bars.items():
                    c = coin_of(t, segs[sym])
                    if c is not None:
                        coin = per_coin.setdefault(c, {})
                        coin[t] = merge_bar(coin.get(t), b)
            if done[0] % 20000 == 0:
                AF.log(f"  {done[0]}/{len(tasks)} files ({len(failed)} failed, {time.time() - t0:.0f}s)")
    AF.log(f"downloaded {len(tasks) - len(failed)} of {len(tasks)} files ({time.time() - t0:.0f}s)")

    # 3. write the coins and the provenance
    coverage = {}
    for c, bars in sorted(per_coin.items()):
        write_coin(os.path.join(a.out, "m4", f"{c}.csv.gz"), bars)
        ts = sorted(bars)
        coverage[c] = {"bars": len(ts), "first": ts[0], "last": ts[-1],
                       "oi_bars": sum(1 for t in ts if bars[t].get("oi") is not None),
                       "top_pos_bars": sum(1 for t in ts if bars[t].get("top_pos_ls") is not None),
                       "acct_bars": sum(1 for t in ts if bars[t].get("acct_ls") is not None),
                       "taker_bars": sum(1 for t in ts if bars[t]["tn"])}
    used = {}
    for s, item in tasks:
        used.setdefault(s, []).append(item)
    meta = {"schema": VERSION, "built_at": int(time.time()), "seconds": round(time.time() - t0, 1),
            "bar": BAR, "columns": OUT_COLS, "coins": len(coverage), "coverage": coverage,
            "headers": [{"header": list(h) if h else None, "files": n} for h, n in heads.items()],
            "failed_count": len(failed), "failed": failed[:300],
            "provenance": {"overall_sha256": provenance([it for s in used for it in used[s]]),
                           "files": sum(len(v) for v in used.values()),
                           "per_symbol_sha256": {s: provenance(v) for s, v in sorted(used.items())}}}
    with open(os.path.join(a.out, "meta.json"), "w") as fh:
        json.dump(meta, fh, sort_keys=True)
    AF.log(f"wrote {len(coverage)} coins; {len(failed)} files failed ({time.time() - t0:.0f}s)")
    return 0 if len(failed) <= max(50, len(tasks) // 200) else 1


if __name__ == "__main__":
    sys.exit(main())
