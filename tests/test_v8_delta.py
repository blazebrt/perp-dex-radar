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
    "universe": [{"ticker": "QQQ1", "field": "tradfi", "base": True, "head": False, "rule": "R"},
                 # the derived field (v8 Phase 3): a coin record without identity is executable when not tradfi
                 {"ticker": "QQQ1", "field": "execution_identity", "base": False, "head": True, "rule": "R"}],
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
        self.assertEqual(len(rep["universe"]), 2)
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


class Phase3Validator(unittest.TestCase):
    """The Phase 3 additions to the validator: identity states pinned, the derived execution_identity field, the
    counterfactual projection and set-valued code deltas - each fails closed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v8delta3")
        self.cf, self.head = os.path.join(self.tmp, "cf"), os.path.join(self.tmp, "head")
        for d in (self.cf, self.head):
            os.makedirs(os.path.join(d, "data"))
        self.write(self.cf, {"coverage": {"tradfi": ["AAPL", "UNK"]}})
        self.write(self.head, {"coverage": {"tradfi": ["AAPL"], "unverified": ["UNK"]}})
        self.ub = universe(coins={"AAA": coin("AAA"), "UNK": coin("UNK"), "AAPL": coin("AAPL", tradfi=True)})
        self.uh = copy.deepcopy(self.ub)
        for t, st in (("AAA", "VERIFIED_CRYPTO"), ("UNK", "UNVERIFIED"), ("AAPL", "VERIFIED_TRADFI")):
            self.uh["coins"][t]["identity"] = st
        self.man = {
            "rules": {"R": "r"}, "dex_status": [], "notes": {"removed": [], "added": []},
            "universe": [{"ticker": "UNK", "field": "execution_identity", "base": True, "head": False, "rule": "R"}],
            "code": [{"file": "data/latest.json", "path": ["coverage", "tradfi"], "kind": "set",
                      "base": ["AAPL", "UNK"], "head": ["AAPL"], "rule": "R"},
                     {"file": "data/latest.json", "path": ["coverage", "unverified"], "base": "<absent>",
                      "head": ["UNK"], "rule": "R"}],
            # the engines' decision summary (legacy_parity.decisions) reads the same lists: also enumerated
            "decisions": [{"path": ["radar", "tradfi"], "kind": "set", "base": ["AAPL", "UNK"], "head": ["AAPL"],
                           "rule": "R"},
                          {"path": ["radar", "unverified"], "base": None, "head": ["UNK"], "rule": "R"}],
            "identity_states": {"AAA": "VERIFIED_CRYPTO", "UNK": "UNVERIFIED", "AAPL": "VERIFIED_TRADFI"}}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, root, latest):
        with open(os.path.join(root, "data", "latest.json"), "w") as fh:
            json.dump(latest, fh)

    def test_exact_manifest_passes(self):
        rep, fails = DP.check(self.man, self.ub, self.uh, self.cf, self.head)
        self.assertEqual(fails, [])
        self.assertEqual(rep["code"][0]["removed"], ["UNK"])

    def test_identity_state_not_in_manifest_fails(self):
        self.uh["coins"]["AAA"]["identity"] = "UNVERIFIED"
        _, fails = DP.check(self.man, self.ub, self.uh, self.cf, self.head)
        self.assertTrue(any("identity state of AAA" in f for f in fails), fails)
        self.assertTrue(any("execution_identity" in f for f in fails), fails)   # AAA lost authority: unlisted

    def test_missing_identity_fails_closed(self):
        del self.uh["coins"]["AAA"]["identity"]
        self.assertTrue(DP.execution_identity(self.uh["coins"]["AAA"]))      # Phase 2 semantics: no identity field
        self.uh["coins"]["AAA"]["identity"] = None
        self.assertFalse(DP.execution_identity(self.uh["coins"]["AAA"]))     # an identity field that is not verified
        _, fails = DP.check(self.man, self.ub, self.uh, self.cf, self.head)
        self.assertTrue(fails)

    def test_set_delta_with_another_item_fails(self):
        self.write(self.head, {"coverage": {"tradfi": ["AAPL", "MSFT"], "unverified": ["UNK"]}})
        _, fails = DP.check(self.man, self.ub, self.uh, self.cf, self.head)
        self.assertTrue(any("set delta data/latest.json coverage/tradfi" in f for f in fails), fails)

    def test_unlisted_decision_difference_fails(self):
        man = copy.deepcopy(self.man)
        man["decisions"] = []
        _, fails = DP.check(man, self.ub, self.uh, self.cf, self.head)
        self.assertTrue(any("UNEXPECTED code delta decisions radar/tradfi" in f for f in fails), fails)

    def test_source_file_change_needs_its_exact_digests(self):
        for d, body in ((self.cf, "var a = 1;"), (self.head, "var a = 2;")):
            with open(os.path.join(d, "analyze.js"), "w") as fh:
                fh.write(body)
        _, fails = DP.check(self.man, self.ub, self.uh, self.cf, self.head)
        self.assertTrue(any("UNEXPECTED code delta in non-JSON file analyze.js" in f for f in fails), fails)
        import hashlib
        dg = lambda b: hashlib.sha256(b.encode()).hexdigest()  # noqa: E731
        man = copy.deepcopy(self.man)
        man["files"] = [{"file": "analyze.js", "base_sha256": dg("var a = 1;"), "head_sha256": dg("var a = 2;"), "rule": "R"}]
        _, fails = DP.check(man, self.ub, self.uh, self.cf, self.head)
        self.assertEqual(fails, [])
        man["files"][0]["head_sha256"] = dg("var a = 3;")
        _, fails = DP.check(man, self.ub, self.uh, self.cf, self.head)
        self.assertTrue(any("file delta analyze.js differs" in f for f in fails), fails)
        with open(os.path.join(self.head, "analyze.js"), "w") as fh:
            fh.write("var a = 1;")
        _, fails = DP.check(man, self.ub, self.uh, self.cf, self.head)
        self.assertTrue(any("expected code delta not observed: analyze.js" in f for f in fails), fails)

    def test_set_delta_not_observed_fails(self):
        self.write(self.cf, {"coverage": {"tradfi": ["AAPL"]}})
        man = copy.deepcopy(self.man)
        man["code"][0]["base"] = ["AAPL"]
        _, fails = DP.check(man, self.ub, self.uh, self.cf, self.head)
        self.assertTrue(any("expected set delta not observed" in f for f in fails), fails)

    def test_projection_excludes_only_coins_without_execution_identity(self):
        p = DP.project(self.uh, "exclude_without_execution_identity")
        self.assertEqual({t: c["tradfi"] for t, c in p["coins"].items()}, {"AAA": False, "UNK": True, "AAPL": True})
        self.assertFalse(self.uh["coins"]["UNK"]["tradfi"])                # the HEAD universe itself is untouched
        self.assertIs(DP.project(self.uh, None), self.uh)
        with self.assertRaises(SystemExit):
            DP.project(self.uh, "something else")

    def test_repository_phase3_manifest_is_narrow_and_pinned(self):
        with open(os.path.join(ROOT, "tests", "fixtures", "v8", "phase3_expected_deltas.json")) as fh:
            man = json.load(fh)
        self.assertEqual(man["base"]["sha"], "82f8d35a80e561384f2e8be0e1399dd4e5adb99b")
        self.assertEqual(man["schema"], "v8.delta/2")
        self.assertLessEqual(len(man["universe"]), 16)
        self.assertEqual({e["field"] for e in man["universe"]}, {"execution_identity", "tradfi"})
        prov = [e for e in man["code"] if e["rule"] == "SMART_TRADE_IDENTITY_PROVENANCE"]
        other = [e for e in man["code"] if e["rule"] != "SMART_TRADE_IDENTITY_PROVENANCE"]
        self.assertLessEqual(len(other), 8)
        # the smart-money closure only adds identity fields: every smart row's added identity is VERIFIED_CRYPTO
        smart = [e for e in other if e["file"] in ("data/smart.json", "data/smart_journal.json")]
        self.assertEqual({e["rule"] for e in smart}, {"SMART_IDENTITY_FIELDS", "SMART_EVIDENCE_BOUNDARY"})
        for e in smart:
            self.assertEqual(e["base"], "<absent>", e)
            if e["path"][-1] == "identity":
                self.assertEqual(e["head"], "VERIFIED_CRYPTO", e)
            if e["rule"] == "SMART_EVIDENCE_BOUNDARY":
                self.assertIn(e["path"], (["accuracy", "evidence"], ["accuracy", "legacy_unqualified"]))
                self.assertEqual(e["file"], "data/smart.json")
        # the journal closure: additive entry-time provenance, one field of one trade (by id) per entry, and every
        # fixture trade is a VERIFIED_CRYPTO, qualified trade - nothing else of a trade may change
        import smart as SM
        self.assertEqual(len(prov), 2 * 2 * len(SM.TRADE_IDENTITY_FIELDS))     # 2 files x 2 trades x 5 fields
        for e in prov:
            self.assertIn(e["file"], ("data/smart.json", "data/smart_journal.json"))
            self.assertEqual((e["base"], e["path"][0], list(e["path"][1])), ("<absent>", "open", ["key"]), e)
            self.assertEqual(e["path"][1]["key"][0], "id")
            self.assertIn(e["path"][2], SM.TRADE_IDENTITY_FIELDS)
            if e["path"][2] == "identity_state_at_entry":
                self.assertEqual(e["head"], "VERIFIED_CRYPTO")
            if e["path"][2] == "identity_qualified":
                self.assertIs(e["head"], True)
        self.assertEqual([f["file"] for f in man["files"]], ["analyze.js"])
        self.assertTrue(all(len(f["base_sha256"]) == len(f["head_sha256"]) == 64 for f in man["files"]))
        # every universe delta takes execution authority away; none grants it
        for e in man["universe"]:
            if e["field"] == "execution_identity":
                self.assertEqual((e["base"], e["head"]), (True, False), e)
        self.assertEqual({e["path"][0] for e in man["code"]}, {"coverage", "coins", "identity_authority", "open",
                                                              "accuracy"})
        self.assertNotIn("*", json.dumps(man))


class ClosureValidator(unittest.TestCase):
    """The v8 Phase 3 closure kinds: "each" (every matching element gains exactly these fields, with these values, an
    exact number of times) and "append" (every row gains one trailing value, with exact counts) - each fails closed:
    another field, another value, another count, any other change of an element or row."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v8delta4")
        self.cf, self.head = os.path.join(self.tmp, "cf"), os.path.join(self.tmp, "head")
        for d in (self.cf, self.head):
            os.makedirs(os.path.join(d, "data"))
        self.base_doc = {"open": [{"id": "AAA-PB-1", "c": "AAA", "s": "PB", "r": 1},
                                  {"id": "ZZZ-RAND:PB-1", "c": "ZZZ", "s": "RAND:PB", "r": 2},
                                  {"id": "BBB-PB-1", "c": "BBB", "s": "PB", "bt": 1, "r": 3}],
                         "rows": [[1, "AAA"], [2, "BBB"]]}
        h = copy.deepcopy(self.base_doc)
        h["open"][0].update(q=True, dec="CRYPTO")
        h["open"][1].update(q=True, dec="CRYPTO", pair="AAA-PB-1")
        h["rows"][0].append("qualified")
        h["rows"][1].append("backtest")
        self.head_doc = h
        self.u = universe()
        self.man = {"rules": {"R": "r"}, "universe": [], "dex_status": [], "notes": {"removed": [], "added": []},
                    "code": [{"file": "data/journal.json", "kind": "each", "path": ["open"],
                              "where": ["s", "not_prefix", "RAND:"],
                              "fields": {"q": True, "dec": {"one_of": ["CRYPTO", "CRYPTO_EXPOSURE_SELECTED"]}},
                              "count": 1, "rule": "R"},
                             {"file": "data/journal.json", "kind": "each", "path": ["open"],
                              "where": ["s", "prefix", "RAND:"],
                              "fields": {"q": True, "dec": "CRYPTO", "pair": {"twin_pair": True}}, "count": 1,
                              "rule": "R"},
                             {"file": "data/journal.json", "kind": "append", "path": ["rows"],
                              "counts": {"backtest": 1, "qualified": 1}, "rule": "R"}]}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, head=None, man=None):
        for root, doc in ((self.cf, self.base_doc), (self.head, head or self.head_doc)):
            with open(os.path.join(root, "data", "journal.json"), "w") as fh:
                json.dump(doc, fh)
        return DP.check(man or self.man, self.u, self.u, self.cf, self.head)

    def test_exact_manifest_passes(self):
        rep, fails = self.check()
        self.assertEqual(fails, [])
        self.assertEqual([c["kind"] for c in rep["code"]], ["each", "each", "append"])

    def test_another_field_or_value_fails(self):
        for change in (lambda h: h["open"][0].update(extra=1), lambda h: h["open"][0].update(dec="OTHER"),
                       lambda h: h["open"][1].update(pair="AAA-MOM-1"), lambda h: h["open"][1].update(pair="ZZZ-PB-1"),
                       lambda h: h["open"][2].update(q=True, dec="CRYPTO")):
            h = copy.deepcopy(self.head_doc)
            change(h)
            _, fails = self.check(h)
            self.assertTrue(fails, change)

    def test_a_changed_existing_value_fails(self):
        h = copy.deepcopy(self.head_doc)
        h["open"][0]["r"] = 9                       # the element also gained the allowed fields: still caught
        _, fails = self.check(h)
        self.assertTrue(any("UNEXPECTED code delta data/journal.json open/0/r" in f for f in fails), fails)

    def test_count_and_counts_are_exact(self):
        man = copy.deepcopy(self.man)
        man["code"][0]["count"] = 2
        _, fails = self.check(man=man)
        self.assertTrue(any("1 elements gained the fields, manifest 2" in f for f in fails), fails)
        man = copy.deepcopy(self.man)
        man["code"][2]["counts"] = {"qualified": 2}
        _, fails = self.check(man=man)
        self.assertTrue(any("appended values" in f for f in fails), fails)

    def test_append_requires_the_base_row_unchanged(self):
        h = copy.deepcopy(self.head_doc)
        h["rows"][0][1] = "XXX"
        _, fails = self.check(h)
        self.assertTrue(any("not its base row plus one value" in f for f in fails), fails)

    def test_each_entry_not_observed_fails(self):
        h = copy.deepcopy(self.head_doc)
        for k in ("q", "dec"):
            del h["open"][0][k]
        _, fails = self.check(h)
        self.assertTrue(any("0 elements gained the fields, manifest 1" in f for f in fails), fails)

    def test_repository_phase4_manifest_allows_nothing(self):
        with open(os.path.join(ROOT, "tests", "fixtures", "v8", "phase4_expected_deltas.json")) as fh:
            man = json.load(fh)
        self.assertEqual(man["base"]["sha"], "d011bcb634f2e348b60f3d1317be2f9ec5d57767")
        self.assertEqual(man["base"]["tree"], "c08c2a006393001e8c7a82545642b0bb6ea38bd1")
        self.assertEqual(man["schema"], "v8.delta/2")
        self.assertEqual((man["universe"], man["dex_status"], man["decisions"], man["code"], man["files"]),
                         ([], [], [], [], []))
        self.assertEqual(man["rules"], {})
        with open(os.path.join(ROOT, "tests", "fixtures", "v8", "phase3_closure_expected_deltas.json")) as fh:
            closure = json.load(fh)
        self.assertEqual(man["identity_states"], closure["identity_states"])    # no identity state may move

    def test_repository_phase5_manifest_is_narrow_and_pinned(self):
        """v8 Phase 5 is measured from production main 3288b15 (Phase 4 merged). It may change exactly the economic-
        exposure identity of six fixture coins - two lose crypto execution identity (Extended Crypto wrapper only),
        four Lighter token-list RWA markets become tradfi - and nothing may become crypto."""
        fx = os.path.join(ROOT, "tests", "fixtures", "v8")
        with open(os.path.join(fx, "phase5_expected_deltas.json")) as fh:
            man = json.load(fh)
        with open(os.path.join(fx, "phase4_expected_deltas.json")) as fh:
            p4 = json.load(fh)
        self.assertEqual(man["base"]["sha"], "3288b1587563045558ea42dec70301e61dc95a9e")
        self.assertEqual(man["base"]["tree"], "d56ef755e23827ba8e2910a6d69d4b6f61090c2f")
        self.assertEqual(man["base"]["golden"], "tests/fixtures/v8/legacy_parity_golden_phase4.json")
        self.assertEqual(man["head_golden"], "tests/fixtures/v8/legacy_parity_golden_phase5.json")
        self.assertEqual((man["schema"], man["counterfactual_projection"]),
                         ("v8.delta/2", "exclude_without_execution_identity"))
        self.assertEqual(man["files"], [])
        used = {e["rule"] for e in man["universe"] + man["dex_status"] + man["code"] + man["decisions"]}
        used.add(man["notes"]["rule"])
        self.assertEqual(set(man["rules"]), used)
        wrap, rwa = {"EXTONLY", "PRLX"}, {"BYD", "HYUNDAIUSD", "US10Y", "XIAOMI"}
        for e in man["universe"]:
            if e["ticker"] in wrap:
                self.assertEqual(e["rule"], "EXTENDED_CRYPTO_WRAPPER_ONLY")
                self.assertIn((e["field"], e["base"], e["head"]), {("identity", "VERIFIED_CRYPTO", "UNVERIFIED"),
                                                                   ("execution_identity", True, False)})
            else:
                self.assertIn(e["ticker"], rwa)
                self.assertEqual(e["rule"], "LIGHTER_TOKENLIST_RWA_TRADFI")
                self.assertIn((e["field"], e["head"]), {("identity", "VERIFIED_TRADFI"), ("tradfi", True)})
            self.assertNotEqual(e["head"], "VERIFIED_CRYPTO")                  # nothing becomes crypto
        self.assertEqual({e["ticker"] for e in man["universe"]}, wrap | rwa)
        moved = {t for t in set(man["identity_states"]) | set(p4["identity_states"])
                 if man["identity_states"].get(t) != p4["identity_states"].get(t)}
        self.assertEqual(moved, wrap | rwa)                                    # every other state is the Phase 4 one
        for e in man["code"]:
            if e["rule"] == "IDENTITY_VERSION_BUMP":
                self.assertEqual((e["path"][-1], e["base"], e["head"]), ("identity_version", "v8.identity/2",
                                                                          "v8.identity/3"))
                self.assertIn(e["path"][0], ("open", "closed"))
            else:
                self.assertEqual((e["rule"], e["kind"], e["path"][0]), ("UNVERIFIED_LISTED_SEPARATELY", "set",
                                                                        "coverage"))
        self.assertEqual({d["dex"] for d in man["dex_status"]}, {"aster", "extended"})
        self.assertTrue(all(d["head"] < d["base"] for d in man["dex_status"]))   # crypto counts only fall
        self.assertNotIn("*", json.dumps(man))

    def test_repository_closure_manifest_is_narrow_and_pinned(self):
        with open(os.path.join(ROOT, "tests", "fixtures", "v8", "phase3_closure_expected_deltas.json")) as fh:
            man = json.load(fh)
        self.assertEqual(man["base"]["sha"], "f8648fe9006a9409b9bd4ecde092e411f8de37a1")
        self.assertEqual(man["base"]["tree"], "bb296e427e06b246d9e30efd85961b826debec58")
        self.assertEqual(man["schema"], "v8.delta/2")
        self.assertEqual((man["universe"], man["dex_status"], man["decisions"]), ([], [], []))
        self.assertLessEqual(len(man["code"]), 16)
        self.assertEqual(set(man["rules"]), {e["rule"] for e in man["code"] + man["files"]})
        # every per-trade delta adds proof only: VERIFIED_CRYPTO, qualified, the identity version, the fixture scan
        from v8 import evidence as EV
        from v8 import identity as ID
        for e in man["code"]:
            if e.get("kind") == "each":
                f = e["fields"]
                self.assertTrue(set(EV.TRADE_IDENTITY_FIELDS) <= set(f), e)
                # the identity version of the closure's time (v8.identity/2; Phase 5 moved on to /3)
                self.assertEqual((f["identity_state_at_entry"], f["identity_qualified"], f["identity_version"]),
                                 (ID.VERIFIED_CRYPTO, True, ID.PREVIOUS_VERSION))
                self.assertLessEqual(set(f) - set(EV.TRADE_IDENTITY_FIELDS),
                                     {"identity", "pair", "identity_coin_state_at_entry"})
                if "identity" in f:
                    self.assertEqual(f["identity"], ID.VERIFIED_CRYPTO)
                self.assertGreater(e["count"], 0)
            elif e.get("kind") == "append":
                self.assertEqual(e["path"], ["journal", "rows"])
                self.assertLessEqual(set(e["counts"]), {"backtest", "qualified", "legacy"})
            else:
                self.assertEqual(e["base"], "<absent>", e)             # everything else is a new key
        self.assertEqual(sorted(f["file"] for f in man["files"]), ["analyze.js", "data/journal.csv"])
        self.assertTrue(all(len(f["base_sha256"]) == len(f["head_sha256"]) == 64 for f in man["files"]))
        self.assertNotIn("*", json.dumps(man))


if __name__ == "__main__":
    unittest.main()
