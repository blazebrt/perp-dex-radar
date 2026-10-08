"""Dashboard data: accuracy in one unit, the three versions, where signals meet, and graceful gaps."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import dashboard as D  # noqa: E402

T = 1791173711


def picks_json():
    def rec(coin, side, score, label, kind="swing"):
        return {"coin": coin, "kind": kind, "side": side, "score": score, "label": label, "setup": "Coiled bottom",
                "chg24": 0.01}
    return {
        "generated": T, "next_scan_min": 20, "settings": {"watch": 60, "ready": 80, "strong": 90},
        "market": {"btc": {"price": 86482.8, "up": True, "mom30": 0.086, "mom7": 0.024}, "above": 68, "total": 77,
                   "mood": "Risk-on: Bitcoin above its 50-day EMA.", "fng": {"value": 70, "label": "Greed"}},
        "swing": {"all": [rec("BTC", "long", 84.0, "Ready"), rec("HYPE", "long", 64.0, "Setting up"),
                          rec("XPL", "short", 61.0, "Setting up"), rec("DOGE", "long", 55.0, "Weak")]},
        "daytrade": {"all": [rec("SOL", "long", 87.0, "Good conditions", "day"), rec("BTC", "long", 86.0, "Good", "day")]},
        "record": {"swing": {"n": 4, "wr": 0.5, "avg": 0.4, "avg_ret": 0.02}, "day": {"n": 12, "wr": 0.667, "avg": 0.291},
                   "open": [{"c": "XPL"}], "since": T - 86400 * 3},
    }


def picks_research():
    return {"period": "Oct 2023 to Oct 2026", "swing": {
        "long": {"ready": {"n": 2449, "R": 0.459, "ret": 0.0331, "win": 0.486,
                           "years": {"2024": {"ret": 0.03}, "2025": {"ret": 0.01}, "2026": {"ret": 0.04}}}},
        "short": {"ready": {"n": 3004, "R": 0.158, "ret": 0.0282, "win": 0.476,
                            "years": {"2024": {"ret": 0.006}, "2025": {"ret": 0.04}, "2026": {"ret": 0.03}}}}},
        "day": {"period": [1759993200, 1791097200],
                "long": {"bands": [{"lo": 70, "hi": 80, "n": 9, "R": 0.5, "ret": 0.01, "win": 0.6},
                                   {"lo": 80, "hi": 90, "n": 6106, "R": -0.033, "ret": -0.0004, "win": 0.358}]},
                "short": {"bands": [{"lo": 80, "hi": 101, "n": 9950, "R": -0.065, "ret": -0.0015, "win": 0.343}]}}}


def quant_json():
    return {"generated": T, "strategies": {"TSMOM": {"name": "Daily trend rider"}, "XSMOM": {"name": "Momentum rotation"}},
            # v8 Phase 3 closure: quant.py publishes the coin's current identity with every actionable position
            "open": [{"c": "BTC", "s": "TSMOM", "d": 1, "t_in": T - 3600, "res": {"r": 0.15, "gross": 0.02},
                      "identity": "VERIFIED_CRYPTO"},
                     {"c": "HYPE", "s": "XSMOM", "d": -1, "t_in": T - 7200, "res": {"r": -0.05, "gross": -0.01},
                      "identity": "VERIFIED_CRYPTO"}],
            "signals": [], "live_all": {"n": 0}}


def quant_research():
    return {"window_3y": [1703793600, 1791072000], "portfolio": {
        "strategies": ["TSMOM", "TREND_EMA", "XSMOM"],
        "all_trades": {"n": 4514, "wr": 0.4067, "avg": 0.093, "t": 2.64, "stop_pct": 0.1109, "edge": 0.0726}}}


def radar_json():
    return {"scan_t": T - 60, "next_scan_t": T + 1140, "picks": [], "watch": [
        {"coin": "SOL", "short": "Dip buy", "status_text": "in the zone", "conv": {"score": 58}}],
        "gate": {"closed": True, "why": "the market is risk-off"},
        "regime": {"label": "Risk-off", "btc3": -0.006, "btc24": 0.015, "breadth": 0.47},
        "journal": {"bt": {"days": 30}, "picks": {"replay": {"closed": 2230, "win_rate": 0.514, "avg_r": 0.012},
                                                   "all": {"closed": 0}},
                    "strategies": [{"id": "MR", "status": "testing"}, {"id": "BRK", "status": "rejected"},
                                   {"id": "SMF", "status": "testing", "n": 18, "wr": 0.556, "exp": 0.059},
                                   {"id": "BRK~v2", "status": "passed", "variant": True}],
                    "lessons": [{"bucket": "sm_long", "n": 104, "avg": -0.072}]},
        "smart_board": [{"coin": "ETH", "long_n": 21, "short_n": 3, "long_usd": 7e8, "short_usd": 4e6, "share": 0.99}],
        "smart": {"read": 150}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, obj):
        with open(os.path.join(self.data, name), "w") as fh:
            json.dump(obj, fh)

    def full(self):
        self.write("picks.json", picks_json())
        self.write("picks_research.json", picks_research())
        self.write("quant.json", quant_json())
        self.write("quant_research.json", quant_research())
        self.write("latest.json", radar_json())
        return D.build(self.data, research_dir=self.tmp)


class Accuracy(Base):
    def test_one_unit_and_honest_verdicts(self):
        out = self.full()
        sc = {r["name"]: r for r in out["scorecard"]}
        sw = sc["Coin picks · swing"]
        self.assertEqual(sw["verdict"], "Proven")
        self.assertEqual(sw["tested"]["n"], 5453)
        self.assertEqual(sw["tested"]["per100"], 29, "R 0.293 is +$29 per $100 risked")
        self.assertAlmostEqual(sw["tested"]["win"], 0.48, places=2)
        self.assertEqual(sw["live"]["n"], 4)
        day = sc["Coin picks · day trades"]
        self.assertEqual(day["verdict"], "No edge", "every band of 80+ lost money after fees")
        self.assertEqual(day["tested"]["n"], 16056, "only bands of 80+ count")
        self.assertLess(day["tested"]["per100"], 0)
        q = sc["Quant desk"]
        self.assertEqual((q["verdict"], q["tested"]["per100"], q["tested"]["vs_random"]), ("Proven", 9, 7))
        self.assertAlmostEqual(q["tested"]["ret"], 0.093 * 0.1109, places=5)
        r = sc["15m radar"]
        self.assertEqual(r["verdict"], "Not proven", "a passed variant does not count as a passed strategy")
        self.assertEqual(r["strategies"], {"passed": 0, "total": 3, "testing": 2, "rejected": 1})
        sm = sc["Smart money"]
        self.assertEqual(sm["verdict"], "No edge")
        self.assertIn("−$7 per $100", sm["why"])

    def test_smart_money_engine_record_wins_when_present(self):
        self.write("smart.json", {"generated": T, "coins": [], "accuracy": {
            "verdict": "Proven", "tone": "good", "why": "w", "tested": {"n": 900, "win": 0.56, "r": 0.12},
            "live": {"n": 3, "win": 0.67, "r": 0.2}}})
        out = self.full()
        sm = out["scorecard"][-1]
        self.assertEqual((sm["verdict"], sm["tested"]["n"], sm["tested"]["per100"]), ("Proven", 900, 12))
        self.assertEqual(out["smart"]["source"], "engine")

    def test_per100_and_combine(self):
        self.assertEqual(D.per100(0.293), 29)
        self.assertEqual(D.usd100(-0.072), "−$7")
        self.assertEqual(D.usd100(None), "–")
        c = D.combine({"n": 1, "R": 1.0, "win": 1.0}, {"n": 3, "R": 0.0, "win": 0.0}, None, {"n": 0})
        self.assertEqual((c["n"], c["r"], c["win"]), (4, 0.25, 0.25))
        self.assertEqual(D.combine(), {"n": 0})


class Versions(Base):
    def test_cards_market_and_agreement(self):
        out = self.full()
        v = {x["id"]: x for x in out["versions"]}
        self.assertEqual(v["picks"]["status"]["text"], "1 swing pick ready (80+)")
        self.assertEqual([i["coin"] for i in v["picks"]["items"]], ["BTC", "HYPE", "XPL", "DOGE"])
        self.assertEqual(v["quant"]["status"]["text"], "2 open: 1 long, 1 short")
        self.assertEqual(v["quant"]["items"][0]["coin"], "BTC", "newest first")
        self.assertIn("Standing aside", v["radar"]["status"]["text"])
        self.assertEqual(v["radar"]["items"][0]["kind"], "watch")
        m = out["market"]
        self.assertTrue(m["verdict"].startswith("Uptrend with a soft patch"))
        self.assertEqual(m["short"]["label"], "Risk-off")
        ag = {r["coin"]: r for r in out["agree"]}
        self.assertEqual(ag["BTC"]["agree"], 3, "swing, day and quant all long")
        self.assertEqual(ag["BTC"]["proven"], 2, "swing 84 (ready) and the quant desk are proven methods")
        self.assertTrue(ag["HYPE"]["conflict"], "swing long against a quant short")
        self.assertNotIn("DOGE", ag, "a weak score is not a signal")
        self.assertEqual(out["agree"][0]["coin"], "BTC")
        self.assertEqual(out["next_scan"], T + 1140)
        self.assertEqual(out["have"], {"picks": True, "quant": True, "radar": True, "smart": False})

    def test_nothing_published_yet(self):
        out = D.build(self.data, research_dir=self.tmp)
        self.assertEqual(out["have"], {"picks": False, "quant": False, "radar": False, "smart": False})
        self.assertEqual([x["items"] for x in out["versions"]], [[], [], []])
        self.assertEqual(out["agree"], [])
        self.assertIsNone(out["market"]["verdict"])
        self.assertTrue(all(r["tested"]["n"] == 0 for r in out["scorecard"]))

    def test_main_writes_data_and_publishes_pages(self):
        self.full()
        D.main(["--out", self.tmp])
        with open(os.path.join(self.data, "dashboard.json")) as fh:
            d = json.load(fh)
        self.assertEqual(d["version"], D.VERSION)
        with open(os.path.join(self.tmp, "index.html")) as fh:
            self.assertIn("Dashboard · Perp DEX Radar", fh.read(), "the dashboard is the front page")
        with open(os.path.join(self.tmp, "picks.html")) as fh:
            self.assertIn("Coin Picks", fh.read())


class Pages(unittest.TestCase):
    """Every page carries the same tab bar, with its own tab marked."""

    def test_shared_tab_bar(self):
        root = os.path.dirname(HERE)
        want = {"dashboard.html": "./", "picks.html": "picks.html", "quant.html": "quant.html",
                "index.html": "radar.html", "analyze.html": "analyze.html", "smart.html": "smart.html"}
        bars = set()
        for name, current in want.items():
            path = os.path.join(root, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                s = fh.read()
            i = s.index('<nav class="apptabs"')
            nav = s[i:s.index("</nav>", i)]
            self.assertIn(f'<a href="{current}" aria-current="page">', nav, name)
            self.assertEqual(nav.count("aria-current"), 1, name)
            bars.add(nav.replace(' aria-current="page"', ""))
        self.assertEqual(len(bars), 1, "the same tabs on every page")


if __name__ == "__main__":
    unittest.main()
