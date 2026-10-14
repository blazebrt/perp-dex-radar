"""v9 evidence tooling: the Binance archive fetcher (against a fake S3 archive) and the survivorship-free evidence
engine (on a synthetic archive).

ArchiveFetch is standard library only. EvidenceEngine needs numpy, numba and pandas (the CI research-checks job
runs it): it runs the whole engine on a small synthetic universe and checks the no-edge property, that on a market
without drift no candidate passes the measured gate."""
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import os
import random
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "v9"))

import archive_fetch as AF  # noqa: E402

try:
    import numba  # noqa: F401
    import numpy  # noqa: F401
    import pandas  # noqa: F401
    HAVE_SCI = True
except ImportError:
    HAVE_SCI = False

DAY = 86400
T0 = 1609459200  # 2021-01-01


def kline_zip(rows, header=True):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if header:
        w.writerow(["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
                    "taker_buy_volume", "taker_buy_quote_volume", "ignore"])
    for t, px, qv in rows:
        w.writerow([t * 1000, px, px * 1.01, px * 0.99, px, qv / px if px else 0, t * 1000 + 14399999, qv, 10,
                    0, qv / 2, 0])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("k.csv", buf.getvalue())
    return out.getvalue()


def funding_zip(rows):
    buf = "calc_time,funding_interval_hours,last_funding_rate\n" + "".join(f"{t * 1000},8,{r}\n" for t, r in rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("f.csv", buf)
    return out.getvalue()


class FakeArchive:
    """An in-memory data.binance.vision: S3 listing XML with pagination and the zip files."""

    def __init__(self):
        self.files = {}

    def add(self, key, data):
        self.files[key] = data

    def listing(self, prefix, delimiter, marker, page=2):
        keys = sorted(k for k in self.files if k.startswith(prefix))
        if delimiter:
            items = sorted({prefix + k[len(prefix):].split(delimiter)[0] + delimiter for k in keys})
            items = [x for x in items if x > marker]
            body, more = items[:page], len(items) > page
            xml = "".join(f"<CommonPrefixes><Prefix>{x}</Prefix></CommonPrefixes>" for x in body)
            nxt = f"<NextMarker>{body[-1]}</NextMarker>" if more else ""
        else:
            items = [k for k in keys if k > marker]
            body, more = items[:page], len(items) > page
            xml = "".join(f"<Contents><Key>{k}</Key><ETag>&quot;{hash(self.files[k]) & 0xffff:x}&quot;</ETag>"
                          f"<Size>{len(self.files[k])}</Size></Contents>" for k in body)
            nxt = ""
        return (f"<ListBucketResult><Prefix>{prefix}</Prefix><IsTruncated>{'true' if more else 'false'}</IsTruncated>"
                f"{nxt}{xml}</ListBucketResult>").encode()

    def http(self, url, tries=4, timeout=40):
        from urllib.parse import parse_qs, unquote, urlparse
        if url.startswith(AF.S3):
            q = parse_qs(urlparse(url).query)
            return self.listing(q.get("prefix", [""])[0], q.get("delimiter", [None])[0], q.get("marker", [""])[0])
        key = unquote(url[len(AF.DL):])
        if key not in self.files:
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        return self.files[key]


def bars(start, n, px=100.0, qv=1e6, zero_from=None):
    out = []
    for k in range(n):
        t = start + k * 14400
        out.append((t, px * (1 + 0.001 * k), 0.0 if zero_from is not None and k >= zero_from else qv))
    return out


class ArchiveFetch(unittest.TestCase):
    def build(self):
        fa = FakeArchive()
        base = "data/futures/um/monthly/klines/"
        # BTC: listed throughout; DEAD: trades then flat zero-volume candles (delisted); RELIST: two lives; XAU: TradFi;
        # 牛来 (non-ASCII ticker)
        fa.add(base + "BTCUSDT/4h/BTCUSDT-4h-2021-01.zip", kline_zip(bars(T0, 180)))
        fa.add(base + "BTCUSDT/4h/BTCUSDT-4h-2021-02.zip", kline_zip(bars(T0 + 30 * DAY, 180), header=False))
        fa.add(base + "DEADUSDT/4h/DEADUSDT-4h-2021-01.zip", kline_zip(bars(T0, 180, zero_from=60)))
        fa.add(base + "DEADUSDT/4h/DEADUSDT-4h-2021-02.zip", kline_zip(bars(T0 + 30 * DAY, 180, qv=0)))
        fa.add(base + "RELISTUSDT/4h/RELISTUSDT-4h-2021-01.zip", kline_zip(bars(T0, 30)))
        fa.add(base + "RELISTUSDT/4h/RELISTUSDT-4h-2021-02.zip", kline_zip(bars(T0 + 40 * DAY, 120)))
        fa.add(base + "XAUUSDT/4h/XAUUSDT-4h-2021-02.zip", kline_zip(bars(T0 + 30 * DAY, 180)))
        fa.add(base + "牛来USDT/4h/牛来USDT-4h-2021-02.zip", kline_zip(bars(T0 + 30 * DAY, 180)))
        fa.add(base + "BTCUSDT_210326/4h/x.zip", kline_zip(bars(T0, 10)))
        fa.add("data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2021-01.zip",
               funding_zip([(T0 + 8 * 3600 * k, 0.0001) for k in range(90)]))
        return fa

    def test_layout_delisting_relisting_and_exclusions(self):
        fa = self.build()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(AF, "http", fa.http):
            rc = AF.main(["--out", os.path.join(tmp, "md"), "--cache", os.path.join(tmp, "c"), "--workers", "4"])
            self.assertEqual(rc, 0)
            with open(os.path.join(tmp, "md", "universe.json")) as fh:
                uni = json.load(fh)
            by = {c["t"]: c for c in uni["coins"]}
            self.assertEqual(sorted(by), ["BTC", "DEAD", "RELIST", "RELIST~2", "XAU", "牛来"])
            self.assertTrue(by["BTC"]["listed_at_archive_end"])
            self.assertFalse(by["BTC"]["delisted"])
            # flat zero-volume candles after trading stops are not a market: DEAD's life ends at its last traded bar
            self.assertEqual(by["DEAD"]["bars"], 60)
            self.assertTrue(by["DEAD"]["delisted"])
            self.assertEqual(by["DEAD"]["zero_volume_bars_dropped"], 300)
            # a 10-day pause splits the symbol into two coins: the first life is delisted, the second is the listed one
            self.assertEqual((by["RELIST"]["bars"], by["RELIST~2"]["bars"]), (30, 120))
            self.assertTrue(by["RELIST"]["delisted"] and not by["RELIST~2"]["delisted"])
            self.assertEqual(by["XAU"]["excluded"], "TRADFI")
            self.assertFalse(os.path.exists(os.path.join(tmp, "md", "h4", "XAU.csv.gz")))
            self.assertEqual(uni["counts"]["research_coins"], 5)
            # the research files: header, seconds, quote volume; funding observed
            with gzip.open(os.path.join(tmp, "md", "h4", "BTC.csv.gz"), "rt") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[0], ["t", "o", "h", "l", "c", "qv", "tbqv"])
            self.assertEqual(int(rows[1][0]), T0)
            self.assertEqual(len(rows) - 1, 360)
            with gzip.open(os.path.join(tmp, "md", "fund_bn", "BTC.csv.gz"), "rt") as fh:
                frows = list(csv.reader(fh))
            self.assertEqual(len(frows) - 1, 90)
            with open(os.path.join(tmp, "md", "meta.json")) as fh:
                meta = json.load(fh)
            self.assertEqual(meta["failed_count"], 0)
            self.assertIn("牛来", by)
            # a second run is served from the cache (same ETags), with the same output
            rc = AF.main(["--out", os.path.join(tmp, "md2"), "--cache", os.path.join(tmp, "c"), "--workers", "4"])
            with open(os.path.join(tmp, "md2", "meta.json")) as fh:
                self.assertEqual(json.load(fh)["download"]["downloaded"], 0)
            with open(os.path.join(tmp, "md2", "universe.json")) as fh:
                self.assertEqual(json.load(fh)["counts"], uni["counts"])

    def test_parsing_helpers(self):
        self.assertEqual(AF.ts_s("1704067200000"), 1704067200)
        self.assertEqual(AF.ts_s("1704067200000000"), 1704067200)
        self.assertEqual(len(AF.rows_of(kline_zip(bars(T0, 3)))), 3)
        self.assertEqual(len(AF.rows_of(kline_zip(bars(T0, 3), header=False))), 3)
        self.assertEqual((AF.classify("USDC"), AF.classify("BTCDOM"), AF.classify("TSLA"), AF.classify("SOL")),
                         ("STABLECOIN", "INDEX", "TRADFI", None))


def synthetic(folder, drift, seed=11, coins=10, days=900):
    random.seed(seed)
    os.makedirs(os.path.join(folder, "h4"), exist_ok=True)
    os.makedirs(os.path.join(folder, "fund_bn"), exist_ok=True)
    names = ["BTC"] + [f"C{k:02d}" for k in range(1, coins)]
    meta = []
    for k, n in enumerate(names):
        life = days if k < coins - 2 else days // 2
        px, rows, fund = 100.0, [], []
        for b in range(life * 6):
            t = T0 + b * 14400
            o = px
            px = max(0.01, px * math.exp(random.gauss(drift - 0.0002, 0.02)))   # -sigma^2/2: a martingale in price
            rows.append([t, o, max(o, px) * 1.003, min(o, px) * 0.997, px, 8e6, 4e6])
            if t % 28800 == 0:
                fund.append([t, 0.0001, 8])
        with gzip.open(os.path.join(folder, "h4", f"{n}.csv.gz"), "wt") as fh:
            w = csv.writer(fh)
            w.writerow(["t", "o", "h", "l", "c", "qv", "tbqv"])
            w.writerows(rows)
        with gzip.open(os.path.join(folder, "fund_bn", f"{n}.csv.gz"), "wt") as fh:
            w = csv.writer(fh)
            w.writerow(["t", "rate", "interval_h"])
            w.writerows(fund)
        meta.append({"t": n, "delisted": life < days, "excluded": None, "trade_vol": 8e6})
    json.dump({"schema": "test", "source": "synthetic", "coins": meta,
               "counts": {"research_coins": coins, "delisted_research_coins": 2}},
              open(os.path.join(folder, "universe.json"), "w"))


@unittest.skipUnless(HAVE_SCI, "numpy, numba and pandas (the CI research-checks job runs these)")
class EvidenceEngine(unittest.TestCase):
    def run_engine(self, drift):
        import evidence as EV
        tmp = tempfile.mkdtemp()
        synthetic(os.path.join(tmp, "md"), drift)
        EV.main(["--md", os.path.join(tmp, "md"), "--out", os.path.join(tmp, "ev"), "--replications", "200"])
        return json.load(open(os.path.join(tmp, "ev", "evidence.json"))), tmp

    def test_runs_and_reports_every_candidate(self):
        doc, tmp = self.run_engine(0.0)
        ids = [c["strategy_id"] for c in doc["candidates"]]
        self.assertIn("TSMOM", ids)
        self.assertIn("XSMOM", ids)
        self.assertTrue(all(c["timeframe"] in ("4h", "1d") for c in doc["candidates"]))
        for c in doc["candidates"]:
            self.assertIn("numeric_gate", c)
            self.assertEqual(c["governed_adjudication"]["research_state"], "INSUFFICIENT_EVIDENCE",
                             "the governed gate still needs a complete census and prospective registration")
        self.assertTrue(os.path.exists(os.path.join(tmp, "ev", "REPORT.md")))
        self.assertTrue(os.path.exists(os.path.join(tmp, "ev", "trades.json.gz")))
        self.assertIn("long", doc["swing_picks"])

    def test_no_edge_on_a_market_without_drift(self):
        doc, _ = self.run_engine(0.0)
        passing = [c["strategy_id"] for c in doc["candidates"] if c["archive_verdict"] == "PASSES_MEASURED_GATE"]
        self.assertEqual(passing, [], "a strategy cannot pass on a random walk; a pass here means look-ahead")
        # on a martingale the sample drift of a few coins can make raw R look good (a 10-coin market is dominated by
        # its luckiest coin); timing cannot beat a random twin taking the same order at the same moment
        for c in doc["candidates"]:
            if c["trades"] >= 200:
                lo = c["twin_edge"]["lower_95"]
                self.assertTrue(lo is None or lo < 0.05, c["strategy_id"])


if __name__ == "__main__":
    unittest.main()
