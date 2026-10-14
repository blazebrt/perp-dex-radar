"""Phase D1 definitions (tools/v9/d1.py): the pre-registered rankings, the panel's taker volume and settlement counts,
and no look-ahead (a settlement or a bar after the daily close never changes that close's signals, while the same
change inside the window does).

Needs the research libraries (numpy, pandas, numba; or PYTHONPATH=tools/v9/devstub for a smoke run)."""
from __future__ import annotations

import csv
import gzip
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "research"))
sys.path.insert(0, str(ROOT / "tools" / "v9"))

try:
    import numpy as np
    import qstrat
    import d1
    HAVE = True
except Exception:  # noqa: BLE001 - the research stack is optional outside the research job
    HAVE = False

LOOK = 3 * 24 // 4          # the 3-day window in 4h bars


def fake(folder):
    subprocess.run([sys.executable, str(ROOT / "tools" / "v9" / "make_fake_archive.py"), folder], check=True,
                   capture_output=True)


def rewrite(path, fn):
    with gzip.open(path, "rt") as fh:
        rows = list(csv.reader(fh))
    rows = fn(rows)
    with gzip.open(path, "wt") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)


def add_settlement(folder, coin, t, rate):
    def fn(rows):
        body = sorted(rows[1:] + [[str(t), str(rate), "8"]], key=lambda r: int(r[0]))
        return rows[:1] + body
    rewrite(os.path.join(folder, "fund_bn", f"{coin}.csv.gz"), fn)


def set_taker_buy(folder, coin, t, times_volume):
    """Taker-buy volume of the bar opening at t set to times_volume x its quote volume (column 6 = tbqv)."""
    def fn(rows):
        for r in rows[1:]:
            if int(r[0]) == t:
                r[6] = f"{float(r[5]) * times_volume:.2f}"
        return rows
    rewrite(os.path.join(folder, "h4", f"{coin}.csv.gz"), fn)


def distinct_shares(folder):
    """Give every coin its own constant taker-buy share (the fake archive writes exactly one half everywhere), so the
    flow ranking is known: a coin later in the sorted file list buys more."""
    names = sorted(f[:-7] for f in os.listdir(os.path.join(folder, "h4")) if f.endswith(".csv.gz"))
    share = {c: 0.30 + 0.03 * k for k, c in enumerate(names)}
    for c in names:
        def fn(rows, s=share[c]):
            for r in rows[1:]:
                r[6] = f"{float(r[5]) * s:.2f}"
            return rows
        rewrite(os.path.join(folder, "h4", f"{c}.csv.gz"), fn)
    return share


def day_signals(sig, i):
    m = sig["i"] == i
    return sorted(zip(sig["j"][m].tolist(), sig["d"][m].tolist()))


def up_to(sig, i):
    m = sig["i"] <= i
    return sorted(zip(sig["i"][m].tolist(), sig["j"][m].tolist(), sig["d"][m].tolist()))


@unittest.skipUnless(HAVE, "research libraries unavailable")
class D1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.md = os.path.join(cls.tmp, "md")
        fake(cls.md)
        cls.md_flow = os.path.join(cls.tmp, "md_flow")
        shutil.copytree(cls.md, cls.md_flow)
        cls.share = distinct_shares(cls.md_flow)
        cls.p = d1.D1Panel(cls.md)
        cls.F = qstrat.Feat(cls.p)
        cls.pf = d1.D1Panel(cls.md_flow)
        cls.Ff = qstrat.Feat(cls.pf)
        b = cls.F.bd
        cls.stop = qstrat._stop_from_atr(b["c"], b["atr"], 2.5)
        cls.k = len(b["end"]) // 2                        # a day in the middle of the archive
        cls.e = int(b["end"][cls.k])                      # its last 4h bar (20:00 UTC)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self, src, name):
        dst = os.path.join(self.tmp, name)
        shutil.copytree(src, dst)
        return dst

    def emittable(self, k):
        """Coins whose stop on day k is inside the 1.5%-20% rule (others never emit a signal)."""
        s = self.stop[k]
        return np.isfinite(s) & (s > 0) & (s <= qstrat.MAX_STOP)

    # ----------------------------------------------------------------------------------------- the panel
    def test_panel_reads_taker_volume_and_counts_settlements(self):
        p = self.p
        traded = np.isfinite(p.c) & (p.v > 0)
        self.assertTrue(np.allclose(p.tb[traded], p.v[traded] / 2, rtol=1e-6))       # the fake writes qv / 2
        self.assertTrue((p.tb[np.isfinite(p.c) & (p.v == 0)] == 0).all())               # a filled bar traded nothing
        expected = 0
        for c in p.coins:
            path = os.path.join(self.md, "fund_bn", f"{c}.csv.gz")
            if os.path.exists(path):
                with gzip.open(path, "rt") as fh:
                    rows = list(csv.reader(fh))[1:]
                expected += sum(1 for r in rows if r[1] != "" and 0 <= (int(r[0]) - int(p.t[0])) // p.bar < p.T)
        self.assertGreater(expected, 0)
        self.assertEqual(int(p.fund_n.sum()), expected)
        self.assertTrue(((p.fund != 0) <= (p.fund_n > 0)).all())                       # no funding without a settlement

    # ----------------------------------------------------------------------------------------- the rankings
    def test_funding_fade_longs_the_lowest_and_shorts_the_highest_every_day(self):
        p, F, b = self.p, self.F, self.F.bd
        end = b["end"]
        paid = d1._trailing_sum(p.fund, LOOK)[end]
        count = d1._trailing_sum(p.fund_n, LOOK)[end]
        s = np.where(F.elig[end] & (count >= d1.MIN_SETTLEMENTS), paid, np.nan)
        sig = d1.xs_funding_fade(F)
        self.assertTrue((sig["hold"] == 7 * 24 // p.bar_h).all())
        seen = {1: 0, -1: 0}
        for k, i in enumerate(end):
            got = day_signals(sig, i)
            ranked = [j for j in np.argsort(s[k], kind="stable") if np.isfinite(s[k][j])]
            for j, d in got:
                self.assertIn(j, ranked[:5] if d == 1 else ranked[-5:], f"day {k} coin {j} side {d}")
                seen[d] += 1
        self.assertGreater(seen[1], 100)
        self.assertGreater(seen[-1], 100)

    def test_funding_fade_needs_three_settlements(self):
        p, F, b = self.p, self.F, self.F.bd
        count = d1._trailing_sum(p.fund_n, LOOK)[b["end"]]
        sig = d1.xs_funding_fade(F)
        k_of = {int(i): k for k, i in enumerate(b["end"])}
        self.assertTrue(all(count[k_of[int(i)], j] >= d1.MIN_SETTLEMENTS for i, j in zip(sig["i"], sig["j"])))

    def test_flow_momentum_longs_the_highest_buy_share_every_day(self):
        p, F, b = self.pf, self.Ff, self.Ff.bd
        sig = d1.xs_flow_momentum(F)
        self.assertTrue((sig["hold"] == 3 * 24 // p.bar_h).all())
        seen = {1: 0, -1: 0}
        for k, i in enumerate(b["end"]):
            got = day_signals(sig, i)
            elig = [j for j in range(p.N) if F.elig[i, j]]
            ranked = sorted(elig, key=lambda j: self.share[p.coins[j]])             # known, distinct shares
            for j, d in got:
                self.assertIn(j, ranked[-5:] if d == 1 else ranked[:5], f"day {k} coin {p.coins[j]} side {d}")
                seen[d] += 1
        self.assertGreater(seen[1], 100)
        self.assertGreater(seen[-1], 100)

    # ----------------------------------------------------------------------------------------- no look-ahead
    def test_funding_fade_sees_nothing_after_the_daily_close(self):
        """A large settlement at the next 00:00 UTC (the close itself, the first instant after the last bar) leaves
        every signal up to that close unchanged. The same settlement at 16:00 the same day turns the day's
        lowest-funding long into a short."""
        p, b, k, e = self.p, self.F.bd, self.k, self.e
        end = b["end"]
        paid = d1._trailing_sum(p.fund, LOOK)[end]
        count = d1._trailing_sum(p.fund_n, LOOK)[end]
        s = np.where(self.F.elig[end] & (count >= d1.MIN_SETTLEMENTS), paid, np.nan)
        cand = [j for j in np.argsort(s[k], kind="stable") if np.isfinite(s[k][j]) and self.emittable(k)[j]]
        j = int(cand[0])
        base = d1.xs_funding_fade(self.F)
        self.assertIn((j, 1.0), day_signals(base, e))
        close_t = int(p.t[e]) + p.bar

        after = self.copy(self.md, "fund_after")
        add_settlement(after, p.coins[j], close_t, 0.5)
        p2 = d1.D1Panel(after)
        self.assertAlmostEqual(p2.fund[e + 1, j] - p.fund[e + 1, j], 0.5)      # it lands in the first bar after
        self.assertEqual(p2.fund_n[e + 1, j], p.fund_n[e + 1, j] + 1)
        self.assertTrue(np.array_equal(p2.fund[: e + 1], p.fund[: e + 1]))
        sig = d1.xs_funding_fade(qstrat.Feat(p2))
        self.assertEqual(up_to(sig, e), up_to(base, e))

        inside = self.copy(self.md, "fund_inside")
        add_settlement(inside, p.coins[j], close_t - 8 * 3600, 0.5)
        sig = d1.xs_funding_fade(qstrat.Feat(d1.D1Panel(inside)))
        self.assertIn((j, -1.0), day_signals(sig, e))
        self.assertEqual(up_to(sig, e - LOOK), up_to(base, e - LOOK))      # nothing before the window moves

    def test_flow_momentum_sees_nothing_after_the_daily_close(self):
        """Heavy buying in the 4h bar that opens at the close leaves every signal up to that close unchanged; the
        same buying in the day's last bar turns the day's weakest-flow short into a long."""
        p, F, k, e = self.pf, self.Ff, self.k, self.e
        elig = [j for j in range(p.N) if F.elig[e, j] and self.emittable(k)[j]]
        j = min(elig, key=lambda x: self.share[p.coins[x]])
        base = d1.xs_flow_momentum(F)
        self.assertIn((j, -1.0), day_signals(base, e))

        after = self.copy(self.md_flow, "flow_after")
        set_taker_buy(after, p.coins[j], int(p.t[e + 1]), 60)
        p2 = d1.D1Panel(after)
        self.assertGreater(p2.tb[e + 1, j], 50 * p.tb[e + 1, j])                 # it lands in the first bar after
        self.assertTrue(np.array_equal(p2.tb[: e + 1], p.tb[: e + 1], equal_nan=True))
        sig = d1.xs_flow_momentum(qstrat.Feat(p2))
        self.assertEqual(up_to(sig, e), up_to(base, e))

        inside = self.copy(self.md_flow, "flow_inside")
        set_taker_buy(inside, p.coins[j], int(p.t[e]), 60)
        sig = d1.xs_flow_momentum(qstrat.Feat(d1.D1Panel(inside)))
        self.assertIn((j, 1.0), day_signals(sig, e))
        self.assertEqual(up_to(sig, e - LOOK), up_to(base, e - LOOK))


if __name__ == "__main__":
    unittest.main()
