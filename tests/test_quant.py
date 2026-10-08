"""Tests for the quant desk (quant.py). Run from the repository root:

    python -m unittest discover -s tests -v

No network is needed: tests/fake_exchange.py stands in for the exchanges. The same signals were checked
against the research engine (tools/research) on a year of real candles: identical trade for trade."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import quant as Q  # noqa: E402
import scanner as sc  # noqa: E402
from fake_exchange import FakeExchange  # noqa: E402

H = 3600


def bars(rows, t0=1_700_006_400, step=H):
    """rows: (o, h, l, c) tuples -> candles."""
    return [{"t": t0 + i * step, "o": o, "h": h, "l": l, "c": c, "qv": 1e6} for i, (o, h, l, c) in enumerate(rows)]


def trade(d, stop_pct, trail=0.0, hold=100, t_in=1_700_006_400, px=100.0):
    return {"d": d, "px": px, "t_in": t_in, "stop_pct": stop_pct, "trail_pct": trail, "hold_h": hold, "slip": 0.0}


class Indicators(unittest.TestCase):
    def test_ema_and_wilder_on_a_constant(self):
        xs = [5.0] * 40
        self.assertTrue(all(v is None for v in Q.ema(xs, 10)[:9]))
        self.assertAlmostEqual(Q.ema(xs, 10)[-1], 5.0)
        self.assertAlmostEqual(Q.wilder(xs, 14)[-1], 5.0)

    def test_ema_matches_the_recursion(self):
        xs = [1.0, 2.0, 3.0, 4.0]
        a = 2 / 3
        y = 1.0
        for x in xs[1:]:
            y = (1 - a) * y + a * x
        self.assertAlmostEqual(Q.ema(xs, 2)[-1], y)

    def test_adx_stays_in_range(self):
        c = [100 + (i % 7) - 3 + i * 0.3 for i in range(120)]
        h = [x + 1 for x in c]
        low = [x - 1 for x in c]
        a = [v for v in Q.adx(h, low, c) if v is not None]
        self.assertTrue(a and all(0 <= v <= 100 for v in a))

    def test_daily_bars_need_six_aligned_bars(self):
        day = 86400 * 19700
        c4 = bars([(1, 2, 0.5, 1.5)] * 13, t0=day, step=4 * H)
        d = Q.to_daily(c4)
        self.assertEqual(len(d), 2)  # the 13th bar starts a day that is not complete
        self.assertEqual(d[0]["h"], 2)
        self.assertEqual(d[0]["qv"], 6e6)

    def test_ranking_picks_the_extremes(self):
        scores = {f"C{i}": float(i) for i in range(20)}
        out = Q.xs_scores(scores)
        self.assertEqual(sorted(k for k, v in out.items() if v > 0), ["C15", "C16", "C17", "C18", "C19"])
        self.assertEqual(sorted(k for k, v in out.items() if v < 0), ["C0", "C1", "C2", "C3", "C4"])


class PaperTrades(unittest.TestCase):
    now = 1_700_006_400 + 50 * H

    def test_stop_first_when_both_are_touched(self):
        c1 = bars([(100, 104, 97, 100), (100, 101, 99, 100)])
        r = Q.sim_trade(trade(1, 0.02), c1, {}, self.now)
        self.assertEqual(r["state"], "stop")
        self.assertAlmostEqual(r["gross"], -1.0)

    def test_short_trailing_stop_moves_after_the_close(self):
        # short at 100, trail 3% (=3): closes 100, 94 -> stop moves to 97 from the third hour; high 97.5 hits it
        c1 = bars([(100, 100.5, 99.5, 100), (100, 100.2, 93.5, 94), (94, 97.5, 93.8, 96)])
        r = Q.sim_trade(trade(-1, 0.02, trail=0.03), c1, {}, self.now)
        self.assertEqual(r["state"], "trail")
        self.assertAlmostEqual(r["gross"], 1.5)

    def test_gap_through_the_stop_exits_at_the_open(self):
        c1 = bars([(100, 100.5, 99.5, 100), (95, 96, 94, 95)])
        r = Q.sim_trade(trade(1, 0.02), c1, {}, self.now)
        self.assertEqual(r["state"], "gap")
        self.assertAlmostEqual(r["gross"], -2.5)

    def test_time_exit_and_funding(self):
        t0 = 1_700_006_400
        c1 = bars([(100, 100.4, 99.6, 100)] * 4)
        fund = {t0 + H: 0.001}  # settles while the trade is open: longs pay, shorts receive
        lg = Q.sim_trade(trade(1, 0.02, hold=3), c1, fund, self.now)
        sh = Q.sim_trade(trade(-1, 0.02, hold=3), c1, fund, self.now)
        self.assertEqual(lg["state"], "time")
        self.assertAlmostEqual(lg["fund"], 0.05)
        self.assertAlmostEqual(sh["fund"], -0.05)

    def test_forming_hour_is_not_used(self):
        c1 = bars([(100, 100.4, 99.6, 100), (100, 120, 80, 100)])
        r = Q.sim_trade(trade(1, 0.02), c1, {}, now=1_700_006_400 + H + 600)  # second hour still forming
        self.assertEqual(r["state"], "open")


class EndToEnd(unittest.TestCase):
    """Two scans on the fake exchange (200 days of candles): signals, paper trades and the page data."""

    @classmethod
    def setUpClass(cls):
        cls.fx = FakeExchange(n_coins=24, days=200, seed=11)
        cls.old = sc.FETCH
        sc.FETCH = cls.fx.fetch
        cls.tmp = tempfile.mkdtemp()
        uni = {}
        for c in cls.fx.coins:
            uni[c] = {"t": c, "venues": {"hyperliquid": {"sym": c, "mult": 1.0, "vol": cls.fx.vol24[c]}},
                      "trade_vol": cls.fx.vol24[c] * 1.2, "best_vol": cls.fx.vol24[c] * 1.2, "tradfi": False,
                      "ref_price": cls.fx.c15[c][-1]["c"], "name": c, "identity": "VERIFIED_CRYPTO"}
        cls.uni = uni
        cls.out1 = Q.run(os.path.join(cls.tmp, "s1"), journal_path=os.path.join(cls.tmp, "none.json"), universe=uni)
        cls.j1 = os.path.join(cls.tmp, "s1", "data", "quant_journal.json")
        cls.out2 = Q.run(os.path.join(cls.tmp, "s2"), journal_path=cls.j1, universe=uni)

    @classmethod
    def tearDownClass(cls):
        sc.FETCH = cls.old

    def test_files_and_fields(self):
        for name in ("quant.json", "quant_journal.json"):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, "s2", "data", name)), name)
        o = self.out2
        self.assertEqual(set(o["strategies"]), {"TSMOM", "TREND_EMA", "XSMOM"})
        self.assertGreater(o["coins"], 10)
        with open(os.path.join(self.tmp, "s2", "data", "quant.json")) as fh:
            json.load(fh)

    def test_signals_are_valid_and_trades_are_unique(self):
        self.assertTrue(self.out1["signals"], "a fresh desk finds signals on 200 days of data")
        for s in self.out1["signals"]:
            self.assertIn(s["d"], (1, -1))
            self.assertTrue(Q.CFG["min_stop"] - 1e-9 <= s["stop_pct"] <= Q.CFG["max_stop"])
        keys = [(t["s"], t["c"]) for t in self.out2["open"]]
        self.assertEqual(len(keys), len(set(keys)), "one open trade per strategy and coin")

    def test_second_scan_does_not_repeat_signals(self):
        self.assertEqual(self.out2["signals"], [], "the same closed bars are not traded twice")

    def test_entries_are_filled_at_an_open(self):
        for t in self.out2["open"]:
            if t["t_in"] + H <= self.fx.now:
                self.assertIsNotNone(t["px"])


if __name__ == "__main__":
    unittest.main()
