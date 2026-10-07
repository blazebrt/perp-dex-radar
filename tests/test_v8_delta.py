"""v8 Phase 2: the differential parity validator (tools/v8/delta_parity.py) fails on any delta outside its manifest.

The full BASE / HEAD / counterfactual run needs a checkout of the base commit and runs in CI ("Unit tests and
legacy parity"); these tests drive the comparison itself with small synthetic universes and output trees, so a
validator that accepts too much is caught without that checkout.

Run from the repository root:  python -m unittest tests.test_v8_delta -v"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "v8"))

import delta_parity as DP  # noqa: E402


def coin(t, tradfi=False, vol=1e6, venues=("hyperliquid",)):
    return {"t": t, "venues": {d: {"t": t, "dex": d, "sym": t, "mult": 1.0, "price": 1.0, "vol": vol, "oi": None,
                                   "funding8h": None, "tradfi": tradfi} for d in venues},
            "name": None, "tradfi": tradfi, "ref_price": 1.0, "best_vol": vol, "tot_vol": vol, "trade_vol": vol}


def universe(**over):
    u = {"coins": {"AAA": coin("AAA"), "QQQ1": coin("QQQ1", tradfi=True), "ZZZ": coin("ZZZ", vol=None)},
         "status": {"hyperliquid": {"ok": True, "markets": 3, "crypto": 2}}, "ok": True, "notes": ["n1"]}
    u.update(over)
    return u


MANIFEST = {
    "rules": {"R": "test rule"},
    "universe": [{"ticker": "QQQ1", "field": "tradfi", "base": True, "head": False, "rule": "R"}],
    "dex_status": [{"dex": "hyperliquid", "field": "crypto", "base": 2, "head": 3, "rule": "R"}],
    "notes": {"removed": ["n1"], "added": []},
    "code": [{"file": "data/latest.json", "path": ["table", {"match": [1, "ZZZ"]}, 2], "base": 0, "head": None,
              "rule": "R"}],
}


class Validator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v8delta")
        self.cf, self.head = os.path.join(self.tmp, "cf"), os.path.join(self.tmp, "head")
        self.latest = {"table": [[0, "AAA", 5], [1, "ZZZ", 0]], "coverage": {"coins": 3}}
        for d in (self.cf, self.head):
            os.makedirs(os.path.join(d, "data"))
        self.write(self.cf, self.latest)
        h = copy.deepcopy(self.latest)
        h["table"][1][2] = None
        self.write(self.head, h)
        self.ub = universe()
        self.uh = universe()
        self.uh["coins"] = copy.deepcopy(self.ub["coins"])
        self.uh["coins"]["QQQ1"]["tradfi"] = False
        self.uh["status"] = {"hyperliquid": {"ok": True, "markets": 3, "crypto": 3}}
        self.uh["notes"] = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, root, latest):
        with open(os.path.join(root, "data", "latest.json"), "w") as fh:
            json.dump(latest, fh)

    def run_check(self, man=MANIFEST):
        return DP.check(man, self.ub, self.uh, self.cf, self.head)

    def test_exact_manifest_passes(self):
        rep, fails = self.run_check()
        self.assertEqual(fails, [])
        self.assertEqual(len(rep["universe"]), 1)
        self.assertEqual(rep["code"][0]["path"], "table/1/2")

    def test_unexpected_universe_delta_fails(self):
        self.uh["coins"]["AAA"]["best_vol"] = 2e6
        _, fails = self.run_check()
        self.assertTrue(any("UNEXPECTED universe delta ('AAA', 'best_vol')" in f for f in fails), fails)

    def test_changed_venue_values_fail(self):
        self.uh["coins"]["AAA"]["venues"]["hyperliquid"]["price"] = 1.5
        _, fails = self.run_check()
        self.assertTrue(any("venues.hyperliquid" in f for f in fails), fails)

    def test_new_or_lost_coin_fails(self):
        del self.uh["coins"]["ZZZ"]
        _, fails = self.run_check()
        self.assertTrue(any("'present'" in f for f in fails), fails)

    def test_expected_delta_missing_fails(self):
        self.uh["coins"]["QQQ1"]["tradfi"] = True
        _, fails = self.run_check()
        self.assertTrue(any("expected universe delta not observed" in f for f in fails), fails)

    def test_wrong_value_fails(self):
        man = copy.deepcopy(MANIFEST)
        man["dex_status"][0]["head"] = 4
        _, fails = self.run_check(man)
        self.assertTrue(any("DEX status" in f for f in fails), fails)

    def test_unexpected_note_fails(self):
        self.uh["notes"] = ["something new"]
        _, fails = self.run_check()
        self.assertTrue(any("notes added" in f for f in fails), fails)

    def test_unexpected_code_delta_fails(self):
        h = copy.deepcopy(self.latest)
        h["table"][1][2] = None
        h["coverage"]["coins"] = 4                      # an engine change the manifest does not allow
        self.write(self.head, h)
        _, fails = self.run_check()
        self.assertTrue(any("UNEXPECTED code delta data/latest.json coverage/coins" in f for f in fails), fails)

    def test_code_delta_on_another_row_fails(self):
        h = copy.deepcopy(self.latest)
        h["table"][0][2] = None                         # AAA, not the ZZZ row the manifest names
        self.write(self.head, h)
        _, fails = self.run_check()
        self.assertTrue(any("table/0/2" in f for f in fails), fails)
        self.assertTrue(any("expected code delta not observed" in f for f in fails), fails)

    def test_coin_order_change_fails(self):
        self.uh["coins"] = dict(reversed(list(self.uh["coins"].items())))
        _, fails = self.run_check()
        self.assertTrue(any("coin order" in f for f in fails), fails)

    def test_repository_manifest_is_narrow(self):
        with open(os.path.join(ROOT, "tests", "fixtures", "v8", "phase2_expected_deltas.json")) as fh:
            man = json.load(fh)
        self.assertLessEqual(len(man["universe"]), 20)
        self.assertLessEqual(len(man["code"]), 5)
        for e in man["code"]:                            # every code delta names one value of one row
            self.assertTrue(any(isinstance(p, dict) for p in e["path"]), e)
            self.assertNotIn("*", json.dumps(e["path"]))
        tickers = {e["ticker"] for e in man["universe"]}
        self.assertTrue({"QNT", "PURR", "BB"} <= tickers)
        self.assertTrue(tickers <= {"QNT", "PURR", "BB", "FAKE13", "ZEROV", "KIOXIA"}, tickers)


if __name__ == "__main__":
    unittest.main()
