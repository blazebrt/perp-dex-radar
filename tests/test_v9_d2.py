"""Phase D2 definitions (tools/v9/d2.py) on the synthetic archive with synthetic metrics:
- the rankings;
- the one-day lag: a day's own metrics never reach its own close, while the previous day's do;
- the 12-of-18-bar rule;
- the panel's metrics loading.

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
    import d2
    HAVE = True
except Exception:  # noqa: BLE001 - the research stack is optional outside the research job
    HAVE = False

COLS = ["t", "oi", "oi_usd", "top_acct_ls", "top_pos_ls", "acct_ls", "taker_ls", "n"]


def fake(folder):
    subprocess.run([sys.executable, str(ROOT / "tools" / "v9" / "make_fake_archive.py"), folder], check=True,
                   capture_output=True)


def coins_of(md):
    return sorted(f[:-7] for f in os.listdir(os.path.join(md, "h4")) if f.endswith(".csv.gz"))


def write_metrics(md, out, acct, top, skip=None):
    """m4 files on every h4 bar of every coin: constant ratios per coin (acct[c], top[c]); skip(c, t) drops a bar."""
    os.makedirs(os.path.join(out, "m4"), exist_ok=True)
    for c in coins_of(md):
        with gzip.open(os.path.join(md, "h4", f"{c}.csv.gz"), "rt") as fh:
            ts = [int(r[0]) for r in list(csv.reader(fh))[1:]]
        with gzip.open(os.path.join(out, "m4", f"{c}.csv.gz"), "wt") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(COLS)
            for t in ts:
                if skip and skip(c, t):
                    continue
                w.writerow([t, 1000, 100000, 1.1, top[c](t) if callable(top[c]) else top[c],
                            acct[c](t) if callable(acct[c]) else acct[c], 1.0, 48])


def day_signals(sig, i):
    m = sig["i"] == i
    return sorted(zip(sig["j"][m].tolist(), sig["d"][m].tolist()))


def up_to(sig, i):
    m = sig["i"] <= i
    return sorted(zip(sig["i"][m].tolist(), sig["j"][m].tolist(), sig["d"][m].tolist()))


@unittest.skipUnless(HAVE, "research libraries unavailable")
class D2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.md = os.path.join(cls.tmp, "md")
        fake(cls.md)
        names = coins_of(cls.md)
        cls.acct = {c: 0.6 + 0.1 * k for k, c in enumerate(names)}        # later coins: crowd more long
        cls.top = {c: 2.0 - 0.05 * k for k, c in enumerate(names)}        # later coins: top traders less long
        cls.mx = os.path.join(cls.tmp, "mx")
        write_metrics(cls.md, cls.mx, cls.acct, cls.top)
        cls.p = d2.D2Panel(cls.md, cls.mx)
        cls.F = qstrat.Feat(cls.p)
        b = cls.F.bd
        cls.stop = qstrat._stop_from_atr(b["c"], b["atr"], 2.5)
        cls.k = len(b["end"]) // 2
        cls.e = int(b["end"][cls.k])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def emittable(self, k):
        s = self.stop[k]
        return np.isfinite(s) & (s > 0) & (s <= qstrat.MAX_STOP)

    def test_panel_loads_the_metrics_on_the_grid(self):
        p = self.p
        self.assertEqual(p.metrics_coins, p.N)
        alive = np.isfinite(p.c) & (p.v > 0)
        for j, c in enumerate(p.coins):
            col = p.m["acct_ls"][:, j]
            self.assertTrue(np.allclose(col[np.isfinite(col)], self.acct[c]))
        self.assertTrue(np.isfinite(p.m["acct_ls"][alive]).all())

    def test_lagged_mean_uses_the_previous_day_and_needs_12_of_18_bars(self):
        x = np.arange(40, dtype=float).reshape(-1, 1)
        m = d2.lagged_mean(None, x)
        self.assertTrue(np.isnan(m[: d2.LAG_BARS + d2.MIN_BARS - 1]).all())
        self.assertAlmostEqual(m[30, 0], np.mean(np.arange(30 - 6 - 17, 30 - 6 + 1)))     # bars 7..24
        y = x.copy()
        y[20:27] = np.nan                                                    # 7 of the 18 bars missing at row 32
        self.assertTrue(np.isnan(d2.lagged_mean(None, y)[32, 0]))
        y[20] = 20.0                                                         # 12 present
        self.assertAlmostEqual(d2.lagged_mean(None, y)[32, 0], np.nanmean(y[9:27, 0]))

    def test_crowd_fade_longs_the_most_short_crowds_every_day(self):
        p, F, b = self.p, self.F, self.F.bd
        sig = d2.xs_crowd_fade(F)
        has = np.isfinite(d2.lagged_mean(p, d2._ln(p.m["acct_ls"])))
        seen = {1: 0, -1: 0}
        for k, i in enumerate(b["end"]):
            elig = [j for j in range(p.N) if F.elig[i, j] and has[i, j]]
            ranked = sorted(elig, key=lambda j: self.acct[p.coins[j]])
            for j, d in day_signals(sig, i):
                self.assertIn(j, ranked[:5] if d == 1 else ranked[-5:])
                seen[d] += 1
        self.assertGreater(min(seen.values()), 100)

    def test_top_divergence_longs_where_top_traders_lead_the_crowd(self):
        p, F, b = self.p, self.F, self.F.bd
        sig = d2.xs_top_divergence(F)
        div = {c: np.log(self.top[c]) - np.log(self.acct[c]) for c in p.coins}
        seen = {1: 0, -1: 0}
        for k, i in enumerate(b["end"]):
            elig = [j for j in range(p.N) if F.elig[i, j]]
            ranked = sorted(elig, key=lambda j: div[p.coins[j]])
            for j, d in day_signals(sig, i):
                self.assertIn(j, ranked[-5:] if d == 1 else ranked[:5])
                seen[d] += 1
        self.assertGreater(min(seen.values()), 100)

    def test_a_days_own_metrics_never_reach_its_close(self):
        """Raising a long's crowd ratio over day D (published only after D ends) leaves every signal up to D's close
        unchanged; the same change over day D-1 turns it into a short at D's close."""
        p, F, k, e = self.p, self.F, self.k, self.e
        base = d2.xs_crowd_fade(F)
        elig = [j for j in range(p.N) if F.elig[e, j] and self.emittable(k)[j]]
        j = min(elig, key=lambda x: self.acct[p.coins[x]])
        coin = p.coins[j]
        self.assertIn((j, 1.0), day_signals(base, e))
        day_d = int(p.t[e]) - 20 * 3600                                       # 00:00 UTC of day D
        for lo, flips in ((day_d, False), (day_d - 86400, True)):
            with self.subTest(day_start=lo):
                mx = os.path.join(self.tmp, f"mx_{lo}")
                acct = dict(self.acct)
                acct[coin] = lambda t, lo=lo, v=self.acct[coin]: 50.0 if lo <= t < lo + 86400 else v
                write_metrics(self.md, mx, acct, self.top)
                sig = d2.xs_crowd_fade(qstrat.Feat(d2.D2Panel(self.md, mx)))
                if flips:
                    self.assertIn((j, -1.0), day_signals(sig, e))
                    self.assertEqual(up_to(sig, e - 6), up_to(base, e - 6))
                else:
                    self.assertEqual(up_to(sig, e), up_to(base, e))

    def test_too_few_metric_bars_give_no_signal(self):
        p, F, k, e = self.p, self.F, self.k, self.e
        elig = [j for j in range(p.N) if F.elig[e, j] and self.emittable(k)[j]]
        j = min(elig, key=lambda x: self.acct[p.coins[x]])
        coin = p.coins[j]
        hi = int(p.t[e]) - 20 * 3600                                          # the window ends at day D's start
        for missing, has_signal in ((6, True), (7, False)):
            with self.subTest(missing_bars=missing):
                mx = os.path.join(self.tmp, f"mx_skip{missing}")
                write_metrics(self.md, mx, self.acct, self.top,
                              skip=lambda c, t, m=missing: c == coin and hi - m * 14400 <= t < hi)
                sig = d2.xs_crowd_fade(qstrat.Feat(d2.D2Panel(self.md, mx)))
                self.assertEqual(any(jj == j for jj, _ in day_signals(sig, e)), has_signal)


if __name__ == "__main__":
    unittest.main()
