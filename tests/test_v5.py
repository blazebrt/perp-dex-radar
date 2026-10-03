"""Tests for the version 5 rules. Run from the repository root:

    python -m unittest discover -s tests -v

No network is needed: tests/fake_exchange.py stands in for the exchanges."""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scanner as sc  # noqa: E402
from fake_exchange import FakeExchange  # noqa: E402


def candles(closes, t0=1_700_000_000, bar=900, vol=1000.0):
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        out.append({"t": t0 + i * bar, "o": prev, "h": max(prev, c) * 1.001, "l": min(prev, c) * 0.999, "c": c,
                    "qv": vol})
        prev = c
    return out


def trade(t, r, gross=None, bt=0, s="BRK", state="win"):
    return {"t": t, "s": s, "bt": bt, "c": "X", "f": {},
            "res": {"r": r, "gross": r if gross is None else gross, "state": state, "done": True, "tph": [None]}}


class ClosedCandles(unittest.TestCase):
    def test_live_spike_in_forming_candle_is_ignored(self):
        # a flat range, then the candle still forming spikes far above the 8-hour high
        closes = [100 + 0.05 * ((i % 7) - 3) for i in range(120)]
        c = candles(closes)
        spike = dict(c[-1], c=103.0, h=103.2)
        live = c[:-1] + [spike]
        now = live[-1]["t"] + 300  # 5 minutes into the forming candle
        old_way = sc.m15_analysis(live[-96:], chart=False)  # version 4: the forming candle counts
        self.assertIsNotNone(old_way["breakout"], "the old live view sees a breakout")
        closed = sc.closed_part(live, 900, now)
        new_way = sc.m15_analysis(sc.as_backtest(closed[-95:], 900), chart=False)
        self.assertIsNone(new_way["breakout"], "closed candles only: no breakout yet")
        # identical to what the backtest sees at the same moment
        T = live[-1]["t"]
        i15 = sc._bar_index(live, T)
        bt_view = sc.m15_analysis(live[i15 - 95:i15] + [sc._forming(live[i15 - 1]["c"], T)], chart=False)
        for k in ("last", "e9", "e21", "e50", "rsi", "atr", "vwap", "breakout", "brk24"):
            self.assertEqual(new_way[k], bt_view[k], k)


class Plan(unittest.TestCase):
    def test_stop_floor(self):
        a = {"atr": 0.2, "last": 100.0}
        s = sc.build_plan(sc.base_spec("BRK"), a, 99.9, 100.1, 99.8, None, (1.2, 2.2, 3.5))
        self.assertAlmostEqual(s["risk"], sc.CFG["min_stop_pct"], places=6)

    def test_floor_survives_tighter_stop_factor(self):
        a = {"atr": 0.2, "last": 100.0}
        s = sc.build_plan(sc.base_spec("BRK"), a, 99.9, 100.1, 99.8, None, (1.2, 2.2, 3.5), sk=0.8)
        self.assertGreaterEqual(s["risk"], sc.CFG["min_stop_pct"] - 1e-9)

    def test_live_price_sets_order_type_only(self):
        a = {"atr": 0.5, "last": 100.0}
        sp = sc.base_spec("BRK")
        self.assertEqual(sc.build_plan(sp, a, 99.8, 100.2, 99.0, None, (1.2, 2.2, 3.5))["status"], "in_zone")
        self.assertEqual(sc.build_plan(sp, a, 99.8, 100.2, 99.0, None, (1.2, 2.2, 3.5), px=100.9)["status"], "above")
        # a trigger needs a closed candle above it: a live spike through it does not count
        self.assertEqual(sc.build_plan(sp, a, 99.8, 100.2, 99.0, 100.1, (1.2, 2.2, 3.5), px=100.15)["status"],
                         "trigger")
        self.assertIsNone(sc.build_plan(sp, a, 99.8, 100.2, 99.0, None, (1.2, 2.2, 3.5), px=98.0))


class Gate(unittest.TestCase):
    def test_gate(self):
        self.assertIsNone(sc.market_gate({"label": "Neutral"}, "up"))
        self.assertIn("risk-off", sc.market_gate({"label": "Risk-off"}, "up"))
        self.assertIn("4-hour", sc.market_gate({"label": "Risk-on"}, "down"))
        self.assertIn("4-hour", sc.market_gate(None, "down"))


class Stats(unittest.TestCase):
    def test_same_day_trades_are_one_block(self):
        day = 86400 * 20000
        spread = [trade(day + i * 86400, 1.0 if i % 2 else -1.0) for i in range(40)]
        bunched = [trade(day + (i // 20) * 86400, 1.0 if i < 20 else -1.0) for i in range(40)]
        a, b = sc.trade_stats(spread), sc.trade_stats(bunched)
        self.assertAlmostEqual(a["se"], b["se"])
        self.assertGreater(b["se_cl"], 3 * a["se_cl"], "40 trades on 2 days are worth far less than on 40 days")
        self.assertEqual(b["days"], 2)

    def test_edge_uses_results_before_costs(self):
        day = 86400 * 20000
        ds = [trade(day + i * 86400, -0.1, gross=0.3) for i in range(10)]
        tw = [trade(day + i * 86400, -0.1, gross=0.0, s="RAND:BRK") for i in range(10)]
        e = sc.edge_vs_twins(ds, tw)
        self.assertAlmostEqual(e["edge"], 0.3)

    def test_tournament_needs_live_proof_and_beating_twins(self):
        day = 86400 * 20000
        good = [trade(day + (i % 15) * 86400, 1.5 if i % 2 else -0.5) for i in range(60)]
        st = sc.trade_stats(good)
        live = sc.trade_stats(good)
        twins = [trade(day + (i % 15) * 86400, 1.0 if i % 2 else -1.0, s="RAND:BRK") for i in range(60)]
        edge = sc.edge_vs_twins(good, twins)
        self.assertEqual(sc.decide_status("testing", st, live=live, edge=edge)[0], "passed")
        # the same record from the backtest alone cannot pass
        self.assertNotEqual(sc.decide_status("testing", st, live={"n": 0}, edge=None)[0], "passed")
        # no better than random entries: no pass
        self.assertNotEqual(sc.decide_status("testing", st, live=live, edge=sc.edge_vs_twins(good, good))[0], "passed")

    def test_clear_loser_is_rejected(self):
        day = 86400 * 20000
        bad = [trade(day + (i % 20) * 86400, -0.6 if i % 3 else 0.4, state="loss") for i in range(60)]
        st = sc.trade_stats(bad)
        self.assertEqual(sc.decide_status("testing", st, live={"n": 0})[0], "rejected")


class Twins(unittest.TestCase):
    def test_twin_clones_the_order(self):
        s = sc.build_plan(sc.base_spec("BRK"), {"atr": 0.5, "last": 100.0}, 99.8, 100.2, 99.0, None, (1.2, 2.2, 3.5),
                          px=100.9)
        s.update(sid="BRK", name="Range breakout retest", vh=3, th=12)
        tw = sc.twin_signal(s, 100.9, 2.018)
        self.assertEqual(tw["sid"], "RAND:BRK")
        self.assertEqual(tw["status"], s["status"])
        self.assertAlmostEqual(tw["risk"], s["risk"])
        self.assertAlmostEqual(tw["stop"] / tw["mid"], s["stop"] / s["mid"])
        self.assertAlmostEqual(tw["tps"][2] / tw["ehi"], s["tps"][2] / s["ehi"])

    def test_twin_coin_is_another_coin_and_reproducible(self):
        pool = ["A", "B", "C", "D"]
        x = sc.twin_coin("A", "BRK", 123, pool)
        self.assertNotEqual(x, "A")
        self.assertEqual(x, sc.twin_coin("A", "BRK", 123, pool))


class EndToEnd(unittest.TestCase):
    """Two full scans on the fake exchange: a new journal with its backtest, then a second scan
    that reads the journal back. Checks the published files, not the trading results."""

    @classmethod
    def setUpClass(cls):
        cls.fx = FakeExchange(n_coins=60, days=16)
        cls.old_fetch = sc.FETCH
        sc.FETCH = cls.fx.fetch
        cls.tmp = tempfile.mkdtemp()
        cls.out1 = sc.run(os.path.join(cls.tmp, "s1"), replay_days=2)
        cls.journal = os.path.join(cls.tmp, "s1", "data", "journal.json")
        cls.out2 = sc.run(os.path.join(cls.tmp, "s2"), journal_path=cls.journal, replay_days=2)

    @classmethod
    def tearDownClass(cls):
        sc.FETCH = cls.old_fetch

    def test_version_and_files(self):
        self.assertEqual(self.out2["version"], sc.VERSION)
        for name in ("latest.json", "journal.json", "journal.csv"):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, "s2", "data", name)), name)
        with open(os.path.join(self.tmp, "s2", "data", "latest.json")) as fh:
            json.load(fh)

    def test_gate_and_rules_are_published(self):
        g = self.out2["gate"]
        self.assertIn("closed", g)
        self.assertEqual(self.out2["journal"]["rules"]["publish"], ["passed"])
        self.assertIn("gate", self.out2["journal"])

    def test_twins_in_journal_but_never_published(self):
        with open(self.journal) as fh:
            J = json.load(fh)
        tw = [t for t in J["closed"] + J["open"] if sc.is_twin(t["s"])]
        self.assertTrue(tw, "every signal gets a random twin")
        self.assertFalse(any(t.get("rk") for t in tw))
        self.assertFalse(any(sc.is_twin(r[2]) for r in self.out2["journal"]["rows"]))

    def test_only_passed_strategies_are_published(self):
        st = {s["id"]: s["status"] for s in self.out2["journal"]["strategies"]}
        for p in self.out2["picks"]:
            self.assertEqual(st.get(p["sid"]), "passed")

    def test_csv_has_gate_column(self):
        with open(os.path.join(self.tmp, "s2", "data", "journal.csv")) as fh:
            rows = list(csv.reader(io.StringIO(fh.read())))
        self.assertEqual(rows[0][-1], "market_gate")

    def test_strategy_rows_have_v5_fields(self):
        for s in self.out2["journal"]["strategies"]:
            for k in ("gross", "cost", "edge", "edge_se", "live_days"):
                self.assertIn(k, s)


class Studio(unittest.TestCase):
    def test_rule_strategy_test_reports_twins(self):
        fx = FakeExchange(n_coins=12, days=40)
        old = sc.FETCH
        sc.FETCH = fx.fetch
        try:
            tmp = tempfile.mkdtemp()
            req = {"id": "testv5a", "days": 30, "coins": 10, "strategy": {
                "id": "u1", "kind": "rule", "name": "RSI dip", "tf": "1h", "tp_r": [1.5, 2.5, 4], "vh": 3, "th": 24,
                "max_risk": 8, "rules": [{"f": "rsi", "op": "<", "v": 45}], "entry": {"type": "market"},
                "stop": {"type": "atr", "atr": 1.5}}}
            res = sc.run_study(json.dumps(req), tmp)
        finally:
            sc.FETCH = old
        self.assertTrue(res["ok"], res.get("error"))
        self.assertIn("twins", res)
        self.assertGreater(res["twins"]["n"], 0)
        self.assertIn("gated", res)


if __name__ == "__main__":
    unittest.main()
