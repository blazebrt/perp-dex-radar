"""v8 Phases 1 and 2, end to end: the whole pipeline (scanner, smart money twice, quant, picks, dashboard) runs
offline on the parity fixture (tools/v8/legacy_parity.py), each engine in its own process like the Scan workflow,
then the audit snapshot is assembled. Checks:

* no drift: every legacy output file is byte-identical (after dropping wall-clock durations and sorting error
  notes) to this branch's golden digests (tests/fixtures/v8/legacy_parity_golden_phase2.json). That file differs
  from the base commit's digests (legacy_parity_golden.json) only as tools/v8/delta_parity.py proves against the
  expected-delta manifest (phase2_expected_deltas.json); CI runs that proof;
* the contract registry keeps every market (also the ones the legacy adapters skip) under venue:raw_symbol;
* universe identity (Phase 2): the crypto coins of the BB, PURR, QNT collision class are admitted with their
  crypto exposure only, the unrelated tradfi markets stay out and stay in the registry, the stocks a venue did not
  label stay out, ambiguous identities are not admitted, and every decision is in the registry and the ledger;
* missing volume and observed zero volume are told apart (DEX_VOLUME_MISSING vs DEX_VOLUME_BELOW_LEGACY_MIN), the
  published table shows a missing volume as unavailable, a price conflict is CONFLICTED;
* small, thin and new coins each have a named reason in every engine;
* coverage: no asset disappears silently (unaccounted is zero everywhere);
* the snapshot is deterministic and compact.

Run from the repository root:  python -m unittest tests.test_v8_audit -v"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "v8"))

import legacy_parity as LP  # noqa: E402
from v8 import snapshot as SN  # noqa: E402
from v8 import taxonomy as T  # noqa: E402

GOLDEN = os.path.join(HERE, "fixtures", "v8", "legacy_parity_golden_phase2.json")
BASE_GOLDEN = os.path.join(HERE, "fixtures", "v8", "legacy_parity_golden.json")
MANIFEST = os.path.join(HERE, "fixtures", "v8", "phase2_expected_deltas.json")


class PipelineAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="v8audit")
        cls.out = os.path.join(cls.tmp, "site")
        LP.run_pipeline(cls.out)
        cls.summary = LP.summary(cls.out)            # legacy digests before the snapshot step adds anything
        keep = os.path.join(cls.tmp, "site_parts")
        shutil.copytree(cls.out, keep)
        cls.snap, cls.n_raw, cls.n_gz, _ = SN.write(cls.out, keep_parts=True)
        cls.keep = keep
        cls.recs = {e: {r["a"]: r for r in cls.snap["dispositions"].get(e, [])} for e in SN.ENGINES}
        cls.contracts = {c["id"]: c for c in SN.contract_records(cls.snap)}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- parity
    def test_legacy_outputs_identical_to_this_branch_golden(self):
        with open(GOLDEN) as fh:
            golden = json.load(fh)
        diffs = LP.compare(golden, self.summary)
        self.assertEqual(diffs, [], "legacy outputs changed:\n" + "\n".join(diffs))
        self.assertEqual(self.summary["combined"], golden["combined"])
        self.assertGreaterEqual(len(golden["files"]), 20)

    def test_base_golden_and_manifest_are_the_phase_base(self):
        with open(BASE_GOLDEN) as fh:
            base = json.load(fh)
        with open(MANIFEST) as fh:
            man = json.load(fh)
        self.assertEqual(man["base"]["sha"], "15a37944bc73ae531ea33998b899a562e51361ad")
        self.assertEqual(man["head_golden"], "tests/fixtures/v8/legacy_parity_golden_phase2.json")
        self.assertNotEqual(base["combined"], self.summary["combined"])   # Phase 2 changes outputs on purpose
        # narrow: every allowed delta names its ticker or file path and an approved rule
        for e in man["universe"]:
            self.assertIn(e["rule"], man["rules"])
            self.assertTrue(e["ticker"] and e["field"])
        for e in man["code"]:
            self.assertIn(e["rule"], man["rules"])
            self.assertGreaterEqual(len(e["path"]), 2)

    def test_snapshot_step_leaves_legacy_files_alone(self):
        after = LP.summary(self.out)
        self.assertEqual(after["files"], self.summary["files"])
        self.assertTrue(all(p.startswith("data/v8/") for p in after["audit_files"]))

    # ---- registry
    def test_same_ticker_on_two_venues_is_two_contracts(self):
        fake01 = [cid for cid, c in self.contracts.items() if c["asset"] == "FAKE01"]
        self.assertIn("hyperliquid:FAKE01", fake01)
        self.assertIn("variational:FAKE01", fake01)
        self.assertIn("aster:FAKE01USDT", fake01)
        self.assertEqual(len(set(fake01)), len(fake01))

    def test_every_returned_market_is_registered(self):
        c = self.contracts
        self.assertEqual(c["hyperliquid:xyz:TSLA"]["legacy"], "HL_BUILDER_MARKET")
        self.assertEqual(c["hyperliquid:OLDCOIN"]["legacy"], "DELISTED")
        self.assertEqual(c["aster:FAKE02USDT_260925"]["legacy"], "NOT_PERPETUAL")
        self.assertEqual(c["aster:FAKE03USDT"]["legacy"], "NOT_TRADING")
        self.assertEqual(c["edgex:FAKE04USD"]["legacy"], "NOT_TRADING")
        self.assertEqual(c["edgex:USD"]["legacy"], "EMPTY_SYMBOL")
        self.assertEqual(c["lighter:FAKE04"]["legacy"], "NOT_TRADING")
        self.assertEqual(c["lighter:FAKE05"]["legacy"], "NOT_PERPETUAL")
        self.assertEqual(c["dydx:FAKE08-USD"]["legacy"], "NOT_TRADING")
        self.assertEqual(c["paradex:FAKE09-USD-30OCT26-1-C"]["legacy"], "NOT_PERPETUAL")
        self.assertEqual(c["extended:FAKE11-USD"]["legacy"], "NOT_TRADING")
        self.assertEqual(c["hyperliquid:kFAKE05"]["legacy"], "DUPLICATE_NOT_SELECTED")
        self.assertEqual(c["variational:1000FAKE06"]["legacy"], "DUPLICATE_NOT_SELECTED")
        self.assertEqual(c["hyperliquid:kFAKE05"]["mult"], 1000.0)
        self.assertEqual(c["variational:VANATOKEN"]["asset"], "VANA")
        self.assertEqual(c["variational:VANATOKEN"]["canon"], "ALIAS:VANATOKEN")
        counts = self.snap["registry"]["counts"]
        self.assertEqual(counts["adapter_mismatches"], 0)
        self.assertEqual(counts["raw_contracts"], len(self.contracts))
        # the registry holds more than the legacy universe kept
        self.assertGreater(counts["raw_contracts"], counts["selected"])
        self.assertEqual(self.snap["registry"]["assets"]["XYZ:TSLA"]["legacy"], "NO_ACTIVE_PERP_CONTRACT")

    def test_first_seen_from_own_history(self):
        ts = self.snap["manifest"]["ts"]
        self.assertTrue(all(c["first_seen"] == ts for c in self.contracts.values()))
        with open(os.path.join(self.out, "data", "v8", "first_seen.json")) as fh:
            fs = json.load(fh)
        self.assertEqual(set(fs), set(self.contracts))
        # a later scan keeps the first sighting
        prev = os.path.join(self.tmp, "fs_prev.json")
        with open(prev, "w") as fh:
            json.dump({"hyperliquid:BTC": [ts - 86400, ts - 3600]}, fh)
        d = os.path.join(self.tmp, "again")
        shutil.copytree(self.keep, d)
        snap, _, _, _ = SN.write(d, first_seen_path=prev)
        btc = next(c for c in SN.contract_records(snap) if c["id"] == "hyperliquid:BTC")
        self.assertEqual(btc["first_seen"], ts - 86400)

    # ---- universe identity (Phase 2)
    def test_crypto_exposure_admitted_tradfi_exposure_kept_out(self):
        with open(os.path.join(self.out, "data", "latest.json")) as fh:
            legacy = json.load(fh)
        assets = self.snap["registry"]["assets"]
        for t, crypto, other in (("QNT", ["aster:QNTUSDT", "lighter:QNT", "variational:QNT"], ["extended:QNT-USD"]),
                                 ("PURR", ["hyperliquid:PURR"], ["extended:PURR-USD"]),
                                 ("BB", ["aster:BBUSDT", "hyperliquid:BB", "variational:BBIT"],
                                  ["extended:BB-USD", "lighter:BB"])):
            self.assertNotIn(t, legacy["coverage"]["tradfi"], t)
            a = assets[t]
            self.assertEqual((a["legacy"], a["identity"]["decision"], a["collision"]),
                             ("CRYPTO", "CRYPTO_EXPOSURE_SELECTED", True), t)
            for cid in crypto:
                c = self.contracts[cid]
                self.assertEqual((c["legacy"], c["exp_class"], c["admitted"]), ("SELECTED", "CRYPTO", True), cid)
            for cid in other:
                c = self.contracts[cid]
                self.assertEqual((c["legacy"], c["exp_class"], c["admitted"]),
                                 ("EXPOSURE_NOT_ADMITTED", "TRADFI", False), cid)
                self.assertNotEqual(c["exposure"], self.contracts[crypto[0]]["exposure"])
            for e in ("radar", "quant", "swing", "day"):
                r = self.recs[e][t]
                self.assertNotIn(r["c"], ("TRADFI_CLASSIFIED", "TRADFI_TICKER_COLLISION", "TRADFI_EXPOSURE_EXCLUDED",
                                          "AMBIGUOUS_EXPOSURE"), (e, t))
                self.assertIn("CRYPTO_EXPOSURE_SELECTED", r.get("x") or [], (e, t))
        # the decision trace: raw contracts, classifications, reasons, prices per coin, exposures
        q = self.contracts["extended:QNT-USD"]
        self.assertEqual((q["cls"], q["cls_reason"], q["cls_auth"]), ("TRADFI", "VENUE_CATEGORY:RWA", "VENUE_METADATA"))
        self.assertEqual(q["meta"], {"category": "RWA"})
        self.assertAlmostEqual(q["npx"], 46.030332)
        self.assertEqual(self.contracts["aster:QNTUSDT"]["cls"], "UNLABELED")
        self.assertEqual(self.contracts["aster:QNTUSDT"]["meta"], {"underlying": "COIN"})
        self.assertEqual(self.contracts["dydx:QNT-USD"]["legacy"], "NOT_TRADING")
        x = assets["QNT"]["identity"]["exposures"]
        self.assertEqual([(e["class"], e["admitted"]) for e in x], [("CRYPTO", True), ("TRADFI", False)])
        self.assertEqual(x[0]["reason"], "TICKER_KNOWN_CRYPTO")
        self.assertEqual(self.contracts["aster:FAKE01USDT"]["type"], "perp")
        self.assertEqual(self.snap["registry"]["contracts"]["fields"][0], "id")

    def test_stocks_stay_out(self):
        """The stock leakage gate, end to end: a stock one venue did not label never reaches an engine."""
        with open(os.path.join(self.out, "data", "latest.json")) as fh:
            legacy = json.load(fh)
        want = {"ASTS": "TRADFI_EXPOSURE_EXCLUDED", "ONDS": "TRADFI_EXPOSURE_EXCLUDED",
                "KORU": "TRADFI_EXPOSURE_EXCLUDED", "KIOXIA": "TRADFI_EXPOSURE_EXCLUDED",
                "XIAOMI": "AMBIGUOUS_EXPOSURE", "SECT": "AMBIGUOUS_EXPOSURE",
                "AAPL": "TRADFI_CLASSIFIED", "ACME": "TRADFI_CLASSIFIED", "EURUSD": "TRADFI_CLASSIFIED"}
        for t, code in want.items():
            self.assertIn(t, legacy["coverage"]["tradfi"], t)
            for e in ("radar", "quant", "swing", "day"):
                self.assertEqual(self.recs[e][t]["c"], code, (e, t))
        self.assertEqual(self.recs["radar"]["XIAOMI"]["h"], T.CONFLICTED)
        self.assertEqual(self.contracts["lighter:BB"]["inherited_from"], "extended:BB-USD")
        self.assertEqual(self.contracts["aster:ASTSUSDT"]["exp_class"], "TRADFI")
        self.assertEqual(self.contracts["variational:ONDS"]["cls_reason"], "NAME_PATTERN:holdings")
        self.assertEqual(self.contracts["lighter:XIAOMI"]["exp_reason"], "UNLABELED_UNDER_TRADFI_COLLISION")
        self.assertEqual(self.contracts["extended:SECT-USD"]["cls_reason"], "VENUE_CATEGORY_UNRECOGNIZED:L1")
        self.assertEqual(self.contracts["variational:ACME"]["tradfi_reason"], "NAME_PATTERN:holdings")
        # no excluded exposure's market is counted as a crypto market of its DEX
        dexes = legacy["coverage"]["dexes"]
        self.assertEqual((dexes["aster"]["markets"], dexes["aster"]["crypto"]), (8, 4))
        self.assertEqual((dexes["lighter"]["markets"], dexes["lighter"]["crypto"]), (8, 4))

    def test_unpriced_contract_does_not_poison(self):
        c = self.contracts["extended:FAKE13-USD"]
        self.assertEqual((c["price"], c["legacy"], c["exp_class"]), (None, "EXPOSURE_NOT_ADMITTED", "TRADFI"))
        self.assertEqual(self.snap["registry"]["assets"]["FAKE13"]["legacy"], "CRYPTO")

    # ---- data health
    def test_missing_and_zero_volume_are_different(self):
        self.assertEqual(self.contracts["lighter:LONLY"]["basis"].get("vol"), "MISSING")
        self.assertEqual(self.contracts["hyperliquid:ZEROV"]["basis"].get("vol"), "OBSERVED_ZERO")
        for e in ("radar", "quant", "swing", "day"):
            lonly, zerov = self.recs[e]["LONLY"], self.recs[e]["ZEROV"]
            self.assertEqual((lonly["d"], lonly["c"], lonly["h"]), (T.INSUFFICIENT_DATA, "DEX_VOLUME_MISSING", T.MISSING))
            self.assertIsNone(lonly["o"]["trade_vol"])
            self.assertEqual((zerov["d"], zerov["c"]), (T.NOT_EXECUTABLE, "DEX_VOLUME_BELOW_LEGACY_MIN"))
            self.assertEqual((zerov["o"]["basis"], zerov["o"]["trade_vol"]), ("OBSERVED_ZERO", 0.0))
        self.assertIn("FUNDING_ASSUMED_DEFAULT", self.recs["radar"]["LONLY"].get("x") or [])
        for e in ("quant", "swing", "day"):       # listed only on Extended, not one of your trade DEXs (the radar
                                                  # charts first: EXTONLY has no candles there)
            self.assertEqual((self.recs[e]["EXTONLY"]["d"], self.recs[e]["EXTONLY"]["c"]),
                             (T.NOT_EXECUTABLE, "NOT_ON_TRADE_DEX"), e)
        # published: the radar table shows a missing volume as unavailable (null -> "-"), an observed 0 as 0
        with open(os.path.join(self.out, "data", "latest.json")) as fh:
            table = {r[1]: r for r in json.load(fh)["table"]}
        self.assertIsNone(table["LONLY"][11])
        self.assertEqual(table["ZEROV"][11], 0)

    def test_price_conflict_is_conflicted(self):
        c = self.contracts["dydx:FAKE07-USD"]
        self.assertEqual((c["legacy"], c["health"]), ("PRICE_CONFLICT_DROPPED", T.CONFLICTED))
        ev = [e for e in self.snap["registry"]["events"] if e[0] == "PRICE_CONFLICT_DROPPED"]
        self.assertIn(["FAKE07", "dydx"], [[e[1]["t"], e[1]["dex"]] for e in ev])
        self.assertEqual(self.recs["radar"]["SCALEX"]["c"], "PRICE_SCALE_CONFLICT")
        self.assertEqual(self.recs["radar"]["SCALEX"]["h"], T.CONFLICTED)

    # ---- small and new coins: named, never silent
    def test_small_and_new_coins_have_a_reason(self):
        r = self.recs
        self.assertEqual(r["radar"]["TINY"]["c"], "DEX_VOLUME_BELOW_LEGACY_MIN")
        self.assertEqual(r["radar"]["TINY"]["o"]["trade_vol"], 300000.0)
        self.assertEqual(r["quant"]["THINREF"]["c"], "REF_VOLUME_BELOW_LEGACY_MIN")
        self.assertEqual(r["swing"]["THINREF"]["c"], "REF_VOLUME_BELOW_LEGACY_MIN")
        self.assertEqual(r["quant"]["NEW10"]["c"], "INSUFFICIENT_30D_HISTORY")
        self.assertEqual(r["swing"]["NEW10"]["c"], "INSUFFICIENT_90D_HISTORY")
        self.assertEqual(r["swing"]["NEW40"]["c"], "INSUFFICIENT_90D_HISTORY")
        self.assertNotEqual(r["quant"]["NEW40"]["c"], "INSUFFICIENT_30D_HISTORY")   # 40 days pass the 30-day gate
        self.assertEqual(r["radar"]["NOCAND"]["c"], "NO_SUPPORTED_CANDLES")
        self.assertEqual(r["radar"]["VANA"]["c"], "NO_SUPPORTED_CANDLES")

    # ---- coverage
    def test_no_silent_disappearance(self):
        s = self.snap["coverage"]["summary"]
        self.assertEqual(s["unaccounted"], {k: 0 for k in s["unaccounted"]})
        for e in SN.ENGINES:
            cov = self.snap["coverage"]["engines"][e]
            self.assertEqual(cov["status"], "OK", e)
            self.assertEqual(cov["unclassified"], 0, e)
            self.assertEqual(cov["duplicates"], [], e)
        # every registry asset has exactly one universe or radar record, and one smart record
        reg = set(self.snap["registry"]["assets"])
        self.assertEqual(set(self.recs["universe"]) | set(self.recs["radar"]), reg)
        self.assertTrue(set(self.recs["universe"]).isdisjoint(self.recs["radar"]))
        self.assertTrue(reg <= set(self.recs["smart"]))
        self.assertEqual(self.snap["data_health"]["audit_problems"], {})
        with open(os.path.join(self.out, "data", "latest.json")) as fh:
            legacy = json.load(fh)
        self.assertEqual(len(self.recs["radar"]), legacy["coverage"]["coins"])

    def test_records_use_the_taxonomy(self):
        for e, recs in self.recs.items():
            for a, r in recs.items():
                self.assertIn(r["c"], T.REASONS, (e, a))
                self.assertEqual(r["d"], T.REASONS[r["c"]][0], (e, a))
                self.assertIn(r["h"], T.HEALTH)
                for x in r.get("x") or []:
                    self.assertIn(x, T.STEPS)
                self.assertNotIn(r["c"], T.RETIRED, (e, a))
        self.assertNotIn("FILTERED", T.REASONS)
        self.assertEqual(self.snap["schema"], "v8.audit/2")
        self.assertEqual(self.snap["manifest"]["identity_version"], "v8.identity/1")
        self.assertEqual(self.snap["manifest"]["liquidity_version"], "v8.liquidity/1")

    def test_published_items_are_surfaced(self):
        with open(os.path.join(self.out, "data", "smart.json")) as fh:
            sm = json.load(fh)
        for c in sm["coins"]:
            if c["signal"]:
                self.assertEqual(self.recs["smart"][c["coin"]]["d"], T.SURFACED)
        with open(os.path.join(self.out, "data", "quant.json")) as fh:
            q = json.load(fh)
        for tr in q["open"]:
            self.assertEqual(self.recs["quant"][tr["c"]]["d"], T.SURFACED)
        with open(os.path.join(self.out, "data", "picks.json")) as fh:
            p = json.load(fh)
        for r in p["swing"]["all"]:
            self.assertIn(self.recs["swing"][r["coin"]]["c"], ("SWING_READY", "SWING_SETTING_UP", "LISTED_BELOW_WATCH"))

    # ---- snapshot
    def test_snapshot_is_deterministic_and_compact(self):
        d = os.path.join(self.tmp, "again2")
        shutil.copytree(self.keep, d)
        SN.write(d)
        a = os.path.join(self.out, "data", "v8", "audit_latest.json")
        b = os.path.join(d, "data", "v8", "audit_latest.json")
        with open(a, "rb") as fa, open(b, "rb") as fb:
            self.assertEqual(fa.read(), fb.read())
        with open(a + ".gz", "rb") as fa, open(b + ".gz", "rb") as fb:
            za, zb = fa.read(), fb.read()
        self.assertEqual(za, zb)
        self.assertEqual(json.loads(gzip.decompress(za)), self.snap)
        for k in ("manifest", "registry", "data_health", "dispositions", "coverage", "legacy_output_refs", "storage"):
            self.assertIn(k, self.snap)
        self.assertLess(self.n_gz, 200_000)
        # no candle arrays: every observed value is small
        for recs in self.recs.values():
            for r in recs.values():
                self.assertLess(len(json.dumps(r)), 1500, r["a"])
        m = self.snap["manifest"]
        self.assertTrue(m["scan_ids_consistent"])
        self.assertEqual(set(m["legacy_output_hashes"]), {r["path"] for r in self.snap["legacy_output_refs"]})
        self.assertEqual(len(m["config_hashes"]["radar"]), 64)
        self.assertTrue(m["strategy_authority"]["research_verdict_preassigned_live"])


if __name__ == "__main__":
    unittest.main()
