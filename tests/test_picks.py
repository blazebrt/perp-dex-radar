"""Tests for the coin picks (picks.py). Run from the repository root:

    python -m unittest discover -s tests -v

No network is needed: tests/fake_exchange.py stands in for the exchanges. The swing scores were checked
against the research code on three years of real candles (tools/research/parity_picks.py): identical."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import picks as P  # noqa: E402
import scanner as sc  # noqa: E402
from fake_exchange import FakeExchange  # noqa: E402

DAY = 86400
T0 = 86400 * 19700


def days(rows, t0=T0, step=DAY):
    return [{"t": t0 + i * step, "o": o, "h": h, "l": l, "c": c, "qv": 1e7} for i, (o, h, l, c) in enumerate(rows)]


def x_long_perfect():
    return {"up90": 0.10, "rsi": 55.0, "squeeze": 0.1, "dd90": -0.2, "atrp": 0.04, "mom30": 0.05, "higher_low": 0.02,
            "btc_up": True, "volup": 1.5, "trend50": 0.02, "lower_high": False, "trend4h": 0.01, "rs30": 0.03,
            "updown": 1.3, "vwap30": 0.01}


class Indicators(unittest.TestCase):
    def test_rsi_extremes(self):
        up = [float(i) for i in range(1, 40)]
        self.assertAlmostEqual(P.rsi(up, 14)[-1], 100.0)
        down = list(reversed(up))
        self.assertAlmostEqual(P.rsi(down, 14)[-1], 0.0)
        self.assertIsNone(P.rsi(up, 14)[5], "needs 14 changes first")

    def test_rsi_matches_wilder_by_hand(self):
        c = [10, 11, 10.5, 11.5, 12, 11, 11.2, 12.5, 12, 13, 12.8, 13.5, 14, 13.2, 13.8, 14.5]
        n = 3
        ups = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
        dns = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
        au, ad = ups[0], dns[0]
        for u, d in zip(ups[1:], dns[1:]):
            au, ad = au + (u - au) / n, ad + (d - ad) / n
        self.assertAlmostEqual(P.rsi(c, n)[-1], 100 - 100 / (1 + au / ad))

    def test_pct_rank_matches_pandas_average_rank(self):
        xs = [None] * 5 + [3.0, 1.0, 2.0, 2.0, 5.0, 2.0]
        # last value 2.0 among [3,1,2,2,5,2]: one below, three equal -> (1 + (3 + 1) / 2) / 6
        self.assertAlmostEqual(P.pct_rank_last(xs, 90, 3), (1 + 2) / 6)
        self.assertIsNone(P.pct_rank_last(xs, 90, 10))

    def test_bollinger_width_of_a_flat_line_is_zero(self):
        self.assertEqual(P.bb_width([5.0] * 25)[-1], 0.0)


class Scores(unittest.TestCase):
    def test_perfect_long_scores_100(self):
        x = x_long_perfect()
        self.assertEqual(P.points(P.long_checks(x), P.LONG_W), 100)

    def test_partial_credit(self):
        x = dict(x_long_perfect(), up90=0.40, rsi=42.0, squeeze=0.3, atrp=0.06)
        cr = P.long_checks(x)
        self.assertEqual((cr["near_low"], cr["rsi"], cr["squeeze"], cr["calm"]), (0.4, 0.4, 0.4, 0.5))

    def test_short_mirror(self):
        x = dict(x_long_perfect(), trend50=-0.1, mom30=-0.2, rsi=56.0, up90=0.5, lower_high=True, trend4h=-0.01,
                 rs30=-0.1, updown=0.7, vwap30=-0.03, squeeze=0.8, atrp=0.09, dd90=-0.5, volup=0.8,
                 higher_low=-0.05, btc_up=False)
        self.assertEqual(P.points(P.short_checks(x), P.SHORT_W), 100)
        self.assertLess(P.points(P.long_checks(x), P.LONG_W), 60)

    def test_weights_add_to_100(self):
        for W in (P.LONG_W, P.SHORT_W, P.DAY_W):
            self.assertEqual(sum(W.values()), 100)

    def test_extra_checks_are_capped(self):
        ex = [("a", "A", True, 6, "", "g"), ("b", "B", True, 6, "", "g")]
        self.assertEqual(P.extra_points(ex), P.CFG["extra_max"])
        ex = [("a", "A", False, 6, "", "g"), ("b", "B", False, 6, "", "g")]
        self.assertEqual(P.extra_points(ex), -P.CFG["extra_max"])

    def test_smart_money_direction(self):
        sm = [5, 1, 900_000, 100_000, None]
        lg = {e[0]: e for e in P.extra_checks("long", {}, sm, None, 0.00005, None, 2e6)}
        sh = {e[0]: e for e in P.extra_checks("short", {}, sm, None, 0.00005, None, 2e6)}
        self.assertIs(lg["smart"][2], True)
        self.assertIs(sh["smart"][2], False)
        self.assertIsNone(lg["oi"][2], "no Gate.io data: no points either way")


class SwingValues(unittest.TestCase):
    def test_needs_ninety_days(self):
        cd = days([(1, 1.1, 0.9, 1)] * 80)
        self.assertIsNone(P.swing_values(cd, [], {"mom30": 0.0, "up": True}))

    def test_values_on_a_simple_series(self):
        rows = []
        p = 100.0
        for i in range(140):
            p = p * (0.995 if i < 100 else 1.004)
            rows.append((p, p * 1.01, p * 0.99, p))
        cd = days(rows)
        x = P.swing_values(cd, [], {"mom30": 0.0, "up": False})
        self.assertIsNotNone(x)
        lo90 = min(r[2] for r in rows[-90:])
        self.assertAlmostEqual(x["up90"], rows[-1][3] / lo90 - 1)
        self.assertGreater(x["rsi"], 50)
        self.assertGreater(x["higher_low"], 0)
        self.assertIsNone(x["trend4h"], "no 4h candles given")


class Replay(unittest.TestCase):
    def tr(self, d=1, stop=0.05, trail=0.0, bars=30):
        return {"d": d, "t_in": T0 + DAY, "px": None, "ref_px": 100.0, "stop_pct": stop, "trail_abs": trail,
                "bars": bars, "cost": 0.0}

    def test_stop_first_when_both_touched(self):
        b = days([(100, 100, 100, 100), (100, 120, 94, 110), (110, 111, 109, 110)])
        r = P.replay(self.tr(), b, DAY, T0 + 10 * DAY)
        self.assertEqual(r["state"], "stop")
        self.assertAlmostEqual(r["r"], -1.0)

    def test_trailing_stop_follows_highs_from_the_next_bar(self):
        b = days([(100, 100, 100, 100), (100, 110, 99, 109), (109, 109.5, 103.5, 104), (104, 105, 103, 104)])
        r = P.replay(self.tr(trail=6.0), b, DAY, T0 + 10 * DAY)
        self.assertEqual(r["state"], "trail")
        self.assertAlmostEqual(r["exit_px"], 104.0)  # best high 110 - 6

    def test_gap_exit_at_the_open(self):
        b = days([(100, 100, 100, 100), (100, 101, 99, 100), (90, 91, 88, 89)])
        r = P.replay(self.tr(), b, DAY, T0 + 10 * DAY)
        self.assertEqual((r["state"], r["exit_px"]), ("gap", 90))

    def test_time_exit_after_the_last_bar(self):
        b = days([(100, 100, 100, 100)] + [(100, 101, 99.5, 100.5)] * 5)
        r = P.replay(self.tr(bars=3), b, DAY, T0 + 10 * DAY)
        self.assertEqual(r["state"], "time")
        self.assertEqual(r["exit_t"], T0 + 4 * DAY)

    def test_short_side(self):
        b = days([(100, 100, 100, 100), (100, 101, 90, 91), (91, 97, 90, 96)])
        r = P.replay(self.tr(d=-1, trail=5.0), b, DAY, T0 + 10 * DAY)
        self.assertEqual(r["state"], "trail")
        self.assertAlmostEqual(r["exit_px"], 95.0)  # best low 90 + 5
        self.assertGreater(r["r"], 0)

    def test_open_until_the_bar_closes(self):
        b = days([(100, 100, 100, 100), (100, 101, 80, 90)])
        r = P.replay(self.tr(), b, DAY, T0 + DAY + 3600)  # entry day still forming
        self.assertEqual(r["state"], "open")


class EndToEnd(unittest.TestCase):
    """Two runs on the fake exchange (200 days of candles): scores, reasons, plans, paper trades, pages."""

    @classmethod
    def setUpClass(cls):
        cls.fx = FakeExchange(n_coins=24, days=200, seed=5)
        cls.old = sc.FETCH
        sc.FETCH = cls.fx.fetch
        cls.tmp = tempfile.mkdtemp()
        uni = {}
        for c in cls.fx.coins:
            uni[c] = {"t": c, "venues": {"hyperliquid": {"sym": c, "mult": 1.0, "vol": cls.fx.vol24[c], "funding8h": 0.0001}},
                      "trade_vol": cls.fx.vol24[c] * 1.2, "best_vol": cls.fx.vol24[c] * 1.2, "tradfi": False,
                      "ref_price": cls.fx.c15[c][-1]["c"], "name": c}
        cls.uni = uni
        old_min, P.CFG["paper_swing_min"] = P.CFG["paper_swing_min"], 0  # paper trade everything in the test
        cls.restore = old_min
        for run in ("s1", "s2"):
            d = os.path.join(cls.tmp, run, "data")
            os.makedirs(d)
            with open(os.path.join(d, "latest.json"), "w") as fh:
                json.dump({"smart_coins": {"ETH": [4, 1, 2_000_000, 300_000, None]}, "smart": {"read": 120}}, fh)
            with open(os.path.join(cls.tmp, run, "index.html"), "w") as fh:
                fh.write("<html>radar</html>")
        cls.out1 = P.run(os.path.join(cls.tmp, "s1"), journal_path=os.path.join(cls.tmp, "none.json"), universe=uni)
        cls.j1 = os.path.join(cls.tmp, "s1", "data", "picks_journal.json")
        cls.out2 = P.run(os.path.join(cls.tmp, "s2"), journal_path=cls.j1, universe=uni)

    @classmethod
    def tearDownClass(cls):
        sc.FETCH = cls.old
        P.CFG["paper_swing_min"] = cls.restore
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_files_and_pages(self):
        for name in ("picks.json", "picks_journal.json", "picks_research.json"):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, "s2", "data", name)), name)
        with open(os.path.join(self.tmp, "s2", "radar.html")) as fh:
            self.assertIn("radar", fh.read(), "the old front page moves to radar.html")
        with open(os.path.join(self.tmp, "s2", "index.html")) as fh:
            self.assertIn("Coin Picks", fh.read())

    def test_lists_and_scores(self):
        o = self.out1
        self.assertGreater(o["coins"], 10)
        for kind in ("swing", "daytrade"):
            for side in ("all", "long", "short"):
                L = o[kind][side]
                self.assertLessEqual(len(L), P.CFG["top_n"])
                scores = [r["score"] for r in L]
                self.assertEqual(scores, sorted(scores, reverse=True))
                for r in L:
                    self.assertTrue(0 <= r["score"] <= 100)
                    if side != "all":
                        self.assertEqual(r["side"], side)
        self.assertTrue(o["swing"]["all"], "200 days of candles give swing scores")
        self.assertTrue(o["daytrade"]["all"], "and day-trade scores")

    def test_every_pick_has_15_checks_and_a_plan(self):
        for kind in ("swing", "daytrade"):
            for r in self.out1[kind]["all"]:
                self.assertGreaterEqual(len(r["checks"]) + len(r["extras"]), 15, (kind, r["coin"]))
                pl = r["plan"]
                if r["side"] == "long":
                    self.assertLess(pl["stop"], pl["entry"])
                    self.assertGreater(pl["r2"], pl["entry"])
                else:
                    self.assertGreater(pl["stop"], pl["entry"])
                    self.assertLess(pl["r2"], pl["entry"])
                lim = P.CFG["swing" if kind == "swing" else "day"]
                self.assertTrue(lim["min_stop"] - 1e-9 <= pl["stop_pct"] <= lim["max_stop"] + 1e-9)
                self.assertTrue(r["why"])

    def test_one_side_per_coin(self):
        coins = [r["coin"] for r in self.out1["swing"]["all"]]
        self.assertEqual(len(coins), len(set(coins)))

    def test_smart_money_is_read_from_the_scan(self):
        recs = [r for r in self.out1["swing"]["long"] + self.out1["swing"]["short"] if r["coin"] == "ETH"]
        for r in recs:
            sm = next(e for e in r["extras"] if e["k"] == "smart")
            self.assertIn("4 long", sm["detail"])

    def test_paper_trades_are_not_repeated(self):
        with open(self.j1) as fh:
            j = json.load(fh)
        n1 = len(j["open"])
        self.assertGreater(n1, 0)
        o2 = self.out2["record"]["open"]
        keys = [(t["kind"], t["c"], t["d"]) for t in o2]
        self.assertEqual(len(keys), len(set(keys)), "one open paper trade per coin, side and kind")
        self.assertEqual(len([t for t in o2 if t["kind"] == "swing"]), len([t for t in j["open"] if t["kind"] == "swing"]),
                         "the same daily close is not traded twice")


if __name__ == "__main__":
    unittest.main()
