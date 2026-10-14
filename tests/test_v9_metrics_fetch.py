"""Phase D2 data: tools/v9/metrics_fetch.py reduces Binance's daily 5-minute metrics files to the archive's 4h bars
without look-ahead, keeps relisted segments apart, and records coverage and provenance. Offline: the archive listing
and downloads are replaced by synthetic files.

Run from the repository root:  python -m unittest tests.test_v9_metrics_fetch -v"""
from __future__ import annotations

import csv
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "v9"))
import metrics_fetch as MF  # noqa: E402

D0 = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp())
HEAD = MF.COLS


def stamp(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def day_zip(day, header=True, epoch=False, rows=None, sym="AAAUSDT", extra=()):
    """A day of 5-minute rows: oi = minutes since midnight, the ratios fixed, taker = 1 + minute / 1000."""
    out = io.StringIO()
    w = csv.writer(out)
    if header:
        w.writerow(HEAD)
    for k in rows if rows is not None else range(288):
        t = day + 300 * k
        w.writerow([str(t * 1000) if epoch else stamp(t), sym, 5 * k, 50 * k, 1.5, 2.5, 0.8, 1 + 5 * k / 1000])
    for r in extra:
        w.writerow(r)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{sym}-metrics-{stamp(day)[:10]}.csv", out.getvalue())
    return buf.getvalue()


class Parse(unittest.TestCase):
    def test_six_bars_last_row_snapshot_and_mean_taker(self):
        bars, head = MF.parse_day(day_zip(D0))
        self.assertEqual(head, tuple(HEAD))
        self.assertEqual(sorted(bars), [D0 + MF.BAR * k for k in range(6)])
        first = MF.finish(bars[D0])
        self.assertEqual(first["n"], 48)
        self.assertEqual(first["oi"], 5 * 47)                          # the 03:55 row, the bar's last
        self.assertEqual(first["oi_usd"], 50 * 47)
        self.assertEqual((first["top_acct_ls"], first["top_pos_ls"], first["acct_ls"]), (1.5, 2.5, 0.8))
        self.assertAlmostEqual(first["taker_ls"], 1 + 5 * 23.5 / 1000)  # mean over minutes 0..235

    def test_a_row_at_the_bar_end_belongs_to_the_next_bar(self):
        bars, _ = MF.parse_day(day_zip(D0, rows=[47, 48]))            # 03:55 and exactly 04:00
        self.assertEqual(MF.finish(bars[D0])["oi"], 5 * 47)
        self.assertEqual(MF.finish(bars[D0 + MF.BAR])["oi"], 5 * 48)
        self.assertEqual(bars[D0]["n"] + bars[D0 + MF.BAR]["n"], 2)

    def test_headerless_epoch_files_and_bad_values(self):
        bars, head = MF.parse_day(day_zip(D0, header=False, epoch=True, rows=[0, 1],
                                          extra=[[str((D0 + 600) * 1000), "AAAUSDT", "", "x", "", "", "", ""],
                                                 ["not a time", "AAAUSDT", 1, 1, 1, 1, 1, 1]]))
        self.assertIsNone(head)
        b = MF.finish(bars[D0])
        self.assertEqual(b["n"], 3)                                     # the unparseable time is skipped
        self.assertIsNone(b["oi"])                                      # the last row (00:10) had no OI: missing
        self.assertAlmostEqual(b["taker_ls"], (1 + 1.005) / 2)          # mean over the rows that have it

    def test_unordered_rows_still_take_the_latest(self):
        bars, _ = MF.parse_day(day_zip(D0, rows=[10, 30, 20]))
        self.assertEqual(MF.finish(bars[D0])["oi"], 150)

    def test_merging_two_pieces_of_one_bar(self):
        a, _ = MF.parse_day(day_zip(D0, rows=[0, 1, 2]))
        b, _ = MF.parse_day(day_zip(D0, rows=[3, 4]))
        m = MF.finish(MF.merge_bar(MF.merge_bar(None, b[D0]), a[D0]))
        self.assertEqual((m["oi"], m["n"]), (20, 5))
        self.assertAlmostEqual(m["taker_ls"], 1 + 5 * 2 / 1000)


class Universe(unittest.TestCase):
    UNI = {"coins": [{"t": "AAA", "symbol": "AAAUSDT", "first_bar": D0, "last_bar": D0 + 2 * MF.DAY - MF.BAR, "excluded": None},
                     {"t": "AAA~2", "symbol": "AAAUSDT", "first_bar": D0 + 10 * MF.DAY, "last_bar": D0 + 11 * MF.DAY - MF.BAR, "excluded": None},
                     {"t": "SPX", "symbol": "SPXUSDT", "first_bar": D0, "last_bar": D0 + MF.DAY, "excluded": "TRADFI"}]}

    def test_segments_days_and_ownership(self):
        segs = MF.segments_by_symbol(self.UNI)
        self.assertEqual(list(segs), ["AAAUSDT"])                       # excluded contracts are not research coins
        s = segs["AAAUSDT"]
        self.assertEqual(MF.day_of("data/futures/um/daily/metrics/AAAUSDT/AAAUSDT-metrics-2023-01-02.zip"), D0 + MF.DAY)
        self.assertIsNone(MF.day_of("x/AAAUSDT-metrics-2023-01-02.CHECKSUM"))
        self.assertEqual([MF.wanted(D0 + k * MF.DAY, s) for k in (0, 1, 2, 5, 10, 11)], [True, True, False, False, True, False])
        self.assertEqual(MF.coin_of(D0 + MF.DAY, s), "AAA")
        self.assertEqual(MF.coin_of(D0 + 10 * MF.DAY + MF.BAR, s), "AAA~2")
        self.assertIsNone(MF.coin_of(D0 + 5 * MF.DAY, s))


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.md = os.path.join(self.tmp, "md")
        os.makedirs(self.md)
        with open(os.path.join(self.md, "universe.json"), "w") as fh:
            json.dump(Universe.UNI, fh)
        days = [D0 + k * MF.DAY for k in (0, 1, 2, 10)]
        self.files = {f"{MF.PREFIX}AAAUSDT/AAAUSDT-metrics-{stamp(d)[:10]}.zip": day_zip(d) for d in days}
        self.saved = (MF.AF.s3_list, MF.AF.http)
        MF.AF.s3_list = lambda prefix, delimiter=None: ([{"key": k, "etag": "e" + k[-14:-4], "size": len(v)}
                                                         for k, v in sorted(self.files.items()) if k.startswith(prefix)], [])
        MF.AF.http = lambda url, **kw: self.files[url[len(MF.AF.DL):]]

    def tearDown(self):
        MF.AF.s3_list, MF.AF.http = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_each_segment_with_coverage_and_provenance(self):
        out = os.path.join(self.tmp, "out")
        self.assertEqual(MF.main(["--md", self.md, "--out", out, "--workers", "4"]), 0)
        rows = {}
        for c in ("AAA", "AAA~2"):
            with gzip.open(os.path.join(out, "m4", f"{c}.csv.gz"), "rt") as fh:
                rows[c] = list(csv.reader(fh))
        self.assertEqual(rows["AAA"][0], MF.OUT_COLS)
        self.assertEqual(len(rows["AAA"]) - 1, 12)                      # two days of six bars; day 2 is outside life
        self.assertEqual(len(rows["AAA~2"]) - 1, 6)
        self.assertEqual(rows["AAA"][1][:2], [str(D0), "235"])
        meta = json.load(open(os.path.join(out, "meta.json")))
        survey = json.load(open(os.path.join(out, "survey.json")))
        self.assertEqual((meta["coins"], meta["failed_count"], meta["provenance"]["files"]), (2, 0, 3))
        self.assertEqual(meta["coverage"]["AAA"]["oi_bars"], 12)
        self.assertEqual(len(meta["provenance"]["overall_sha256"]), 64)
        self.assertEqual(survey["per_symbol"]["AAAUSDT"]["files"], 4)
        self.assertEqual(survey["per_symbol"]["AAAUSDT"]["files_in_life"], 3)
        self.assertEqual(survey["first_day_overall"], D0)

    def test_too_many_files_stop_after_the_survey(self):
        MF.AF.http = lambda url, **kw: self.fail("downloaded past the file limit")
        out = os.path.join(self.tmp, "out")
        self.assertEqual(MF.main(["--md", self.md, "--out", out, "--max-files", "2"]), 2)
        self.assertTrue(os.path.exists(os.path.join(out, "survey.json")))

    def test_survey_only_downloads_nothing(self):
        MF.AF.http = lambda url, **kw: self.fail("downloaded in survey mode")
        out = os.path.join(self.tmp, "out")
        self.assertEqual(MF.main(["--md", self.md, "--out", out, "--survey-only"]), 0)
        self.assertTrue(os.path.exists(os.path.join(out, "survey.json")))
        self.assertFalse(os.listdir(os.path.join(out, "m4")))


if __name__ == "__main__":
    unittest.main()
