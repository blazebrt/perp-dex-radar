"""v8 Phases 1, 2 and 3, end to end: the whole pipeline (scanner, smart money twice, quant, picks, dashboard) runs
offline on the parity fixture (tools/v8/legacy_parity.py), each engine in its own process like the Scan workflow,
then the audit snapshot is assembled. Checks:

* no drift: every legacy output file is byte-identical (after dropping wall-clock durations and sorting error
  notes) to this branch's golden digests (tests/fixtures/v8/legacy_parity_golden_closure.json). That file differs
  from production main's digests (legacy_parity_golden_phase3.json: main f8648fe on the same fixture) only as
  tools/v8/delta_parity.py proves against the closure manifest (phase3_closure_expected_deltas.json); CI runs it.
  The Phase 3 manifest (base 82f8d35) is kept for the record;
* the contract registry keeps every market (also the ones the legacy adapters skip) under venue:raw_symbol;
* universe identity (Phase 2): the crypto coins of the BB, PURR, QNT collision class are admitted with their
  crypto exposure only, the unrelated tradfi markets stay out and stay in the registry, the stocks a venue did not
  label stay out, ambiguous identities are not admitted, and every decision is in the registry and the ledger;
* missing volume and observed zero volume are told apart (DEX_VOLUME_MISSING vs DEX_VOLUME_BELOW_LEGACY_MIN), the
  published table shows a missing volume as unavailable, a price conflict is CONFLICTED;
* small, thin and new coins each have a named reason in every engine;
* identity coverage (Phase 3): coins without positive identity evidence are UNVERIFIED, stay visible in the
  registry, the universe and every ledger, are never published by any engine, and are not called tradfi;
  venue-symbol parsing (SAMSUNGUSD, SKHYNIXUSD) is provenance-visible; identity transitions are recorded per scan;
* economic exposure (Phase 5): Extended's Crypto category is wrapper evidence only (EXTONLY and PRLX, verified by it
  alone before, are UNVERIFIED), Lighter token-list RWA markets carry their own tradfi evidence (US10Y, BYD,
  HYUNDAIUSD, the Lighter stocks), the audit keeps wrapper and economic evidence apart, records the token list's
  health and coverage, and compares every asset with the previous identity version;
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

# v8 Phase 5: this branch's golden; its base (main 3288b15 = the Phase 4 golden) and the Phase 5 manifest
# (phase5_expected_deltas.json) are checked by tools/v8/delta_parity.py in CI. The Phase 3, closure and Phase 4 manifests
# and their goldens are kept for the record and still checked for consistency below: their identity states are the
# v8.identity/2 states, which this run's audit reproduces per asset as `previous`.
GOLDEN = os.path.join(HERE, "fixtures", "v8", "legacy_parity_golden_phase5.json")
PHASE4_GOLDEN = os.path.join(HERE, "fixtures", "v8", "legacy_parity_golden_phase4.json")
PHASE5_MANIFEST = os.path.join(HERE, "fixtures", "v8", "phase5_expected_deltas.json")
CLOSURE_GOLDEN = os.path.join(HERE, "fixtures", "v8", "legacy_parity_golden_closure.json")
PHASE4_MANIFEST = os.path.join(HERE, "fixtures", "v8", "phase4_expected_deltas.json")
PHASE3_GOLDEN = os.path.join(HERE, "fixtures", "v8", "legacy_parity_golden_phase3.json")
CLOSURE_MANIFEST = os.path.join(HERE, "fixtures", "v8", "phase3_closure_expected_deltas.json")
BASE_GOLDEN = os.path.join(HERE, "fixtures", "v8", "legacy_parity_golden_phase3_base.json")
MANIFEST = os.path.join(HERE, "fixtures", "v8", "phase3_expected_deltas.json")
# the fixture's coins without positive identity evidence (v8 Phase 3; tools/v8/legacy_parity.py). Phase 5: EXTONLY and
# PRLX (Extended Crypto wrapper only) joined; BYD, HYUNDAIUSD and US10Y left (Lighter token-list RWA: tradfi)
UNVERIFIED = ("EXTONLY", "HYUNDAI", "MOONX", "NEWCOIN", "PRLX")
WRAPPER_ONLY = ("EXTONLY", "PRLX")


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

    def states(self, previous=False):
        """Identity state of every coin of this run, or (previous=True) what v8.identity/2 gives the same contracts."""
        out = {}
        for t, a in self.snap["registry"]["assets"].items():
            if a["legacy"] in ("CRYPTO", "TRADFI", "AMBIGUOUS", "UNVERIFIED"):
                out[t] = a["identity"]["previous"]["state"] if previous else a["identity"]["state"]
        return out

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
        self.assertEqual(man["base"]["sha"], "82f8d35a80e561384f2e8be0e1399dd4e5adb99b")
        self.assertEqual(man["base"]["tree"], "06d80f744401589f983ac52298650d182e0c2fa5")
        self.assertEqual(man["head_golden"], "tests/fixtures/v8/legacy_parity_golden_phase3.json")
        self.assertEqual(man["counterfactual_projection"], "exclude_without_execution_identity")
        self.assertNotEqual(base["combined"], self.summary["combined"])   # Phase 3 changes outputs on purpose
        for e in man.get("decisions") or []:
            self.assertIn(e["rule"], man["rules"])
        # every coin's identity state is pinned: the v8.identity/2 states, which this run reproduces as `previous`
        self.assertEqual(man["identity_states"], self.states(previous=True))
        # narrow: every allowed delta names its ticker or file path and an approved rule
        for e in man["universe"]:
            self.assertIn(e["rule"], man["rules"])
            self.assertTrue(e["ticker"] and e["field"])
        for e in man["code"]:
            self.assertIn(e["rule"], man["rules"])
            # one value of one row, or (Phase 3 closure) one new top-level provenance key that did not exist before
            self.assertTrue(len(e["path"]) >= 2 or (len(e["path"]) == 1 and e["base"] == "<absent>"), e)

    def test_phase4_manifest_allows_no_delta(self):
        """Phase 4 is measured from production main d011bcb (the closure merged), whose fixture golden is the closure
        golden. Stage A records candidate evidence in the audit trace only, so nothing may change: no universe, identity
        state, DEX status, note, engine decision, legacy file or code delta."""
        with open(PHASE4_MANIFEST) as fh:
            man = json.load(fh)
        with open(CLOSURE_GOLDEN) as fh:
            base = json.load(fh)
        with open(PHASE4_GOLDEN) as fh:
            head = json.load(fh)
        self.assertEqual(man["base"]["sha"], "d011bcb634f2e348b60f3d1317be2f9ec5d57767")
        self.assertEqual(man["base"]["tree"], "c08c2a006393001e8c7a82545642b0bb6ea38bd1")
        self.assertEqual(man["base"]["golden"], "tests/fixtures/v8/legacy_parity_golden_closure.json")
        self.assertEqual(man["head_golden"], "tests/fixtures/v8/legacy_parity_golden_phase4.json")
        self.assertIsNone(man["counterfactual_projection"])
        self.assertEqual((man["universe"], man["dex_status"], man["decisions"], man["code"], man["files"], man["rules"]),
                         ([], [], [], [], [], {}))
        self.assertEqual(man["notes"], {"removed": [], "added": []})
        self.assertEqual(base, head)                                          # the head golden is the base golden
        self.assertEqual(man["identity_states"], self.states(previous=True))    # the v8.identity/2 states

    def test_phase5_manifest_is_the_phase_base(self):
        """Phase 5 is measured from production main 3288b15 (Phase 4 merged), whose fixture golden is the Phase 4
        golden. Its manifest pins every identity state of this run, and the states it moves are exactly the ones
        whose v8.identity/2 state (`previous`) differs."""
        with open(PHASE5_MANIFEST) as fh:
            man = json.load(fh)
        with open(PHASE4_GOLDEN) as fh:
            base = json.load(fh)
        self.assertEqual(man["base"]["sha"], "3288b1587563045558ea42dec70301e61dc95a9e")
        self.assertEqual(man["base"]["tree"], "d56ef755e23827ba8e2910a6d69d4b6f61090c2f")
        self.assertEqual(man["head_golden"], "tests/fixtures/v8/legacy_parity_golden_phase5.json")
        self.assertNotEqual(base["combined"], self.summary["combined"])     # Phase 5 changes outputs on purpose
        self.assertEqual(man["identity_states"], self.states())
        prev, now = self.states(previous=True), self.states()
        self.assertEqual({e["ticker"] for e in man["universe"]}, {t for t in now if prev[t] != now[t]})
        es = self.snap["registry"]["counts"]["exposure_safety"]
        self.assertEqual(set(es["changed_vs_previous"]), {t for t in now if prev[t] != now[t]})

    def test_candidate_evidence_is_traced_never_authority(self):
        """v8 Phase 4: the snapshot carries every contract's observed candidate evidence apart from its authoritative
        evidence, and counts it; no candidate rule is qualified."""
        self.assertEqual(self.snap["manifest"]["audit_version"], "v8-phase5.0")
        self.assertIn("candidate", SN.CONTRACT_FIELDS)
        self.assertTrue({"wrapper", "xcheck"} <= set(SN.CONTRACT_FIELDS))
        cc = self.snap["registry"]["counts"]["candidate_evidence"]
        self.assertEqual(cc["qualified_rules"], [])
        self.assertEqual(cc["status"], "OBSERVED_NOT_AUTHORITY")
        for c in self.contracts.values():
            for f, v in c.get("candidate") or []:
                for e in c.get("evidence") or []:
                    self.assertNotIn(f"{f}:{v}", e[1])                       # a candidate never appears as authority
        for a in self.snap["registry"]["assets"].values():
            if a.get("candidate_evidence"):
                self.assertIs(a["candidate_evidence"]["authority"], False)

    def test_closure_manifest_is_pinned_to_production_main(self):
        """The closure is measured from production main f8648fe (Phase 3 merged), whose fixture golden is the Phase 3
        branch golden; universe, DEX status, notes, identity states and engine decisions may not change at all."""
        with open(CLOSURE_MANIFEST) as fh:
            man = json.load(fh)
        with open(PHASE3_GOLDEN) as fh:
            base = json.load(fh)
        self.assertEqual(man["base"]["sha"], "f8648fe9006a9409b9bd4ecde092e411f8de37a1")
        self.assertEqual(man["base"]["tree"], "bb296e427e06b246d9e30efd85961b826debec58")
        self.assertEqual(man["base"]["golden"], "tests/fixtures/v8/legacy_parity_golden_phase3.json")
        self.assertEqual(man["head_golden"], "tests/fixtures/v8/legacy_parity_golden_closure.json")
        self.assertIsNone(man["counterfactual_projection"])
        self.assertEqual((man["universe"], man["dex_status"], man["decisions"]), ([], [], []))
        self.assertEqual(man["notes"], {"removed": [], "added": []})
        with open(CLOSURE_GOLDEN) as fh:
            closure = json.load(fh)
        self.assertNotEqual(base["combined"], closure["combined"])         # the closure changes outputs on purpose
        self.assertEqual(base["decisions"], closure["decisions"])         # ... but no engine decision
        self.assertEqual(man["identity_states"], self.states(previous=True))    # the v8.identity/2 states
        # only quant and radar outputs (and the Analyzer source) change; smart money, picks and dashboard do not
        files = {e["file"] for e in man["code"]} | {f["file"] for f in man["files"]}
        self.assertEqual(files, {"data/quant.json", "data/quant_journal.json", "data/journal.json", "data/latest.json",
                                 "data/journal.csv", "analyze.js"})
        for e in man["code"] + man["files"]:
            self.assertIn(e["rule"], man["rules"])
        for f in ("data/smart.json", "data/smart_journal.json", "data/picks.json", "data/picks_journal.json",
                  "data/dashboard.json", "data/quant_research.json", "data/picks_research.json"):
            self.assertEqual(base["files"][f], closure["files"][f], f)

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
        # v8 Phase 5: the Lighter stocks carry their own token-list RWA evidence, so KIOXIA (Lighter + Extended RWA)
        # is classified on every contract and XIAOMI's Aster+Lighter exposure is tradfi, no longer ambiguous
        want = {"ASTS": "TRADFI_EXPOSURE_EXCLUDED", "ONDS": "TRADFI_EXPOSURE_EXCLUDED",
                "KORU": "TRADFI_EXPOSURE_EXCLUDED", "KIOXIA": "TRADFI_CLASSIFIED",
                "XIAOMI": "TRADFI_EXPOSURE_EXCLUDED", "SECT": "AMBIGUOUS_EXPOSURE",
                "AAPL": "TRADFI_CLASSIFIED", "ACME": "TRADFI_CLASSIFIED", "EURUSD": "TRADFI_CLASSIFIED",
                "BYD": "TRADFI_CLASSIFIED", "US10Y": "TRADFI_CLASSIFIED", "HYUNDAIUSD": "TRADFI_CLASSIFIED"}
        for t, code in want.items():
            self.assertIn(t, legacy["coverage"]["tradfi"], t)
            for e in ("radar", "quant", "swing", "day"):
                self.assertEqual(self.recs[e][t]["c"], code, (e, t))
        self.assertEqual(self.recs["radar"]["SECT"]["h"], T.CONFLICTED)
        # the Lighter BB stock no longer depends on Extended's RWA market for its class: its own token-list entry
        bb = self.contracts["lighter:BB"]
        self.assertEqual((bb["cls"], bb["cls_reason"], bb["inherited_from"], bb["xcheck"]),
                         ("TRADFI", "VENUE_ASSET_TYPE:RWA", None, "OK"))
        self.assertEqual(self.contracts["aster:ASTSUSDT"]["exp_class"], "TRADFI")
        self.assertEqual(self.contracts["variational:ONDS"]["cls_reason"], "NAME_PATTERN:holdings")
        self.assertEqual(self.contracts["lighter:XIAOMI"]["exp_reason"], "TRADFI_CONTRACT_EVIDENCE")
        self.assertEqual(self.contracts["aster:XIAOMIUSDT"]["inherited_from"], "lighter:XIAOMI")
        self.assertEqual(self.contracts["extended:SECT-USD"]["cls_reason"], "VENUE_CATEGORY_UNRECOGNIZED:L1")
        self.assertEqual(self.contracts["variational:ACME"]["tradfi_reason"], "NAME_PATTERN:holdings")
        # no excluded exposure's market is counted as a crypto market of its DEX
        dexes = legacy["coverage"]["dexes"]
        self.assertEqual((dexes["aster"]["markets"], dexes["aster"]["crypto"]), (13, 4))      # Phase 5: not PRLX
        self.assertEqual((dexes["extended"]["markets"], dexes["extended"]["crypto"]), (14, 1))  # FAKE10 only
        self.assertEqual((dexes["lighter"]["markets"], dexes["lighter"]["crypto"]), (14, 4))

    def test_unpriced_contract_does_not_poison(self):
        c = self.contracts["extended:FAKE13-USD"]
        self.assertEqual((c["price"], c["legacy"], c["exp_class"]), (None, "EXPOSURE_NOT_ADMITTED", "TRADFI"))
        self.assertEqual(self.snap["registry"]["assets"]["FAKE13"]["legacy"], "CRYPTO")

    # ---- identity coverage (Phase 3)
    def test_unknown_new_coin_stays_discoverable(self):
        """The mandatory small-coin case, end to end: a brand-new unknown perp (NEWCOIN: Aster only, $18.5k, no
        candles, on no list, no label) is in the contract registry, the asset registry, the discovery universe and
        every engine's Decision Trace - as UNVERIFIED, not TRADFI, and not deleted."""
        with open(os.path.join(self.out, "data", "latest.json")) as fh:
            legacy = json.load(fh)
        c = self.contracts["aster:NEWCOINUSDT"]
        self.assertEqual((c["legacy"], c["cls"], c["exp_class"], c["exp_state"], c["admitted"], c["in_record"]),
                         ("SELECTED", "UNLABELED", "UNVERIFIED", "UNVERIFIED", False, True))
        self.assertEqual(c["exp_reason"], "NO_POSITIVE_IDENTITY_EVIDENCE")
        a = self.snap["registry"]["assets"]["NEWCOIN"]
        i = a["identity"]
        self.assertEqual((a["legacy"], i["state"], i["decision"]), ("UNVERIFIED", "UNVERIFIED", "IDENTITY_UNVERIFIED"))
        self.assertEqual((i["discovery_eligible"], i["execution_identity_eligible"]), (True, False))
        self.assertEqual((i["phase2"], i["phase2_reasons"]), ("CRYPTO", ["DEFAULT_CRYPTO"]))
        self.assertEqual(i["evidence"], [])
        self.assertTrue(i["promotion"])
        for t in UNVERIFIED:
            self.assertIn(t, legacy["coverage"]["unverified"], t)
            self.assertNotIn(t, legacy["coverage"]["tradfi"], t)                 # unknown is not tradfi
            self.assertEqual(self.snap["registry"]["assets"][t]["identity"]["state"], "UNVERIFIED", t)
            for e in ("radar", "quant", "swing", "day"):
                r = self.recs[e][t]
                self.assertEqual((r["c"], r["d"], r["h"]), ("IDENTITY_UNVERIFIED", "INSUFFICIENT_DATA", "MISSING"),
                                 (e, t))
                self.assertEqual((r["o"]["state"], r["o"]["discovery"], r["o"]["execution_identity"]),
                                 ("UNVERIFIED", True, False), (e, t))
        idn = self.snap["coverage"]["summary"]["identity"]
        self.assertEqual(sorted(idn["unverified_assets"]), sorted(UNVERIFIED))
        self.assertEqual(idn["unverified_exclusions"], {e: len(UNVERIFIED) for e in ("radar", "quant", "swing", "day")})
        self.assertEqual(idn["states"]["UNVERIFIED"], len(UNVERIFIED))
        self.assertEqual(sum(idn["states"].values()), len(legacy["coverage"]["tradfi"]) + len(UNVERIFIED) +
                         legacy["coverage"]["crypto"])
        self.assertEqual(idn["execution_identity_eligible"], legacy["coverage"]["crypto"])

    def test_no_published_output_without_crypto_identity(self):
        """Nothing any engine published - radar picks, watch list and table, radar paper trades, quant signals and
        positions, swing and day lists - is an asset without VERIFIED_CRYPTO identity."""
        assets = self.snap["registry"]["assets"]
        data = os.path.join(self.out, "data")
        load = lambda n: json.load(open(os.path.join(data, n)))  # noqa: E731
        L, Q, P, J = load("latest.json"), load("quant.json"), load("picks.json"), load("journal.json")
        published = set()
        published |= {p["coin"] for p in L.get("picks") or []} | {p["coin"] for p in L.get("watch") or []}
        published |= {row[1] for row in L.get("table") or []}
        published |= {t.get("coin") for t in (J.get("open") or []) + (J.get("closed") or []) if t.get("coin")}
        published |= {t.get("c") for t in (Q.get("signals") or []) + (Q.get("open") or [])}
        for k in ("swing", "daytrade"):
            for side in ("all", "long", "short"):
                published |= {r.get("coin") for r in (P.get(k) or {}).get(side) or [] if isinstance(r, dict)}
        self.assertTrue(published)
        for t in sorted(x for x in published if x):
            self.assertEqual(assets[t]["identity"]["state"], "VERIFIED_CRYPTO", t)
        for t in UNVERIFIED:
            self.assertNotIn(t, published, t)
        # the base code surfaced MOONX (quant TSMOM and XSMOM) on this fixture: the identity gate removed it
        with open(BASE_GOLDEN) as fh:
            base = json.load(fh)
        self.assertIn("MOONX", {x[0] for x in base["decisions"]["quant"]["open"]})

    def test_tradfi_and_unknown_symbol_cases(self):
        """M-P and SKHYNIXUSD end to end: venue-symbol parsing at the venue boundary, with provenance."""
        C, A = self.contracts, self.snap["registry"]["assets"]
        s = C["lighter:SAMSUNGUSD"]
        self.assertEqual((s["cls"], s["parsed"]), ("TRADFI", ["SAMSUNG", "QUOTE_SUFFIX:USD"]))
        self.assertEqual(A["SAMSUNGUSD"]["identity"]["state"], "VERIFIED_TRADFI")
        k = C["lighter:SKHYNIXUSD"]
        self.assertEqual(k["cls"], "TRADFI")
        self.assertIn(["TRADFI", "PARSED_SYMBOL_EXPOSURE:SKHYNIX#1", "PARSED_SYMBOL"], k["evidence"])
        self.assertEqual((k["link"]["candidate"], k["link"]["coherent_exposure"], k["link"]["coherent_class"]),
                         ("SKHYNIX", "SKHYNIX#1", "TRADFI"))
        self.assertEqual(A["SKHYNIXUSD"]["identity"]["state"], "VERIFIED_TRADFI")
        h = C["lighter:HYUNDAIUSD"]
        self.assertEqual((h["link"]["coherent_exposure"], h["link"]["coherent_class"], h["link"]["evidence"]),
                         ("HYUNDAI#1", "UNVERIFIED", None))           # the parsed link still decides nothing
        # v8 Phase 5: the Lighter stocks and the rate carry their own token-list RWA evidence (VENUE_ASSET_TYPE:RWA),
        # beside the parsed-symbol evidence where there is one
        for cid in ("lighter:SAMSUNGUSD", "lighter:SKHYNIXUSD", "lighter:HYUNDAIUSD", "lighter:US10Y", "lighter:BYD"):
            self.assertIn(["TRADFI", "VENUE_ASSET_TYPE:RWA", "VENUE_METADATA"], C[cid]["evidence"], cid)
            self.assertEqual((C[cid]["cls"], C[cid]["xcheck"], C[cid]["meta"]["asset_type"]), ("TRADFI", "OK", "RWA"))
        self.assertIn(["TRADFI", "PARSED_SYMBOL_TRADFI_LIST:SAMSUNG", "PARSED_SYMBOL"], s["evidence"])
        for t in ("HYUNDAIUSD", "US10Y", "BYD"):
            self.assertEqual(A[t]["identity"]["state"], "VERIFIED_TRADFI", t)
            self.assertEqual(A[t]["identity"]["previous"]["state"], "UNVERIFIED", t)
        self.assertEqual(A["HYUNDAI"]["identity"]["state"], "UNVERIFIED")      # Aster COIN: still no evidence
        # same-venue fields, tradfi direction (the live venue field census): an Aster STOCK subtype, a Variational swap
        u = C["variational:US100S"]
        self.assertEqual((u["cls"], u["cls_reason"], u["vmeta"]),
                         ("TRADFI", "VENUE_NAME:swap on", {"name": "Swap on US Non-Financial 100"}))
        self.assertEqual(A["US100S"]["identity"]["state"], "VERIFIED_TRADFI")
        b = C["aster:ADBEUSDT"]
        self.assertEqual((b["cls"], b["cls_reason"], b["meta"]),
                         ("TRADFI", "VENUE_SUBTYPE:STOCK", {"underlying": "COIN", "subtypes": ["STOCK"]}))
        self.assertEqual(b["vmeta"]["underlyingSubType"], ["STOCK"])
        self.assertEqual(A["ADBE"]["identity"]["state"], "VERIFIED_TRADFI")
        self.assertIsNone(C["lighter:US10Y"]["parsed"])
        self.assertEqual(C["lighter:BYD"]["basis"].get("vol"), "OBSERVED_ZERO")
        for e in ("radar", "quant", "swing", "day"):
            self.assertIn(self.recs[e]["SAMSUNGUSD"]["c"], ("TRADFI_CLASSIFIED", "TRADFI_EXPOSURE_EXCLUDED"), e)
        self.assertIn("lighter:SKHYNIXUSD", self.snap["registry"]["counts"]["parsed_symbol_links"])

    def test_crypto_wrapper_alone_is_unverified(self):
        """v8 Phase 5, end to end: PRLX and EXTONLY were verified crypto by Extended's Crypto category alone. That
        label is wrapper evidence since v8.identity/3: both are UNVERIFIED (WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE),
        discovery-visible, blocked in every engine, and the trace shows the wrapper apart from the (empty) economic
        evidence. PRLX keeps the Phase 2 record of its two UNVERIFIED exposures (the Lighter one is dropped by the
        legacy price check); an unverified exposure beside a crypto one is still kept out (tests.test_v8_phase3)."""
        for t in WRAPPER_ONLY:
            a = self.snap["registry"]["assets"][t]
            i = a["identity"]
            self.assertEqual((a["legacy"], i["state"], i["reason"], i["wrapper_only"]),
                             ("UNVERIFIED", "UNVERIFIED", "WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE", True), t)
            self.assertEqual((i["previous"]["state"], i["previous"]["reason"]), ("VERIFIED_CRYPTO", "CRYPTO_VENUE_METADATA"))
            self.assertEqual(i["evidence"], [])
            self.assertEqual([w[2] for w in i["wrapper_evidence"]], ["VENUE_CATEGORY:Crypto"])
            tr = i["exposure_trace"]
            self.assertEqual(([w["effect"] for w in tr["wrapper"]], tr["economic"], tr["final"], tr["crypto_execution"]),
                             (["WRAPPER_ONLY"], [], "UNVERIFIED", "BLOCKED"))
            for e in ("radar", "quant", "swing", "day"):
                r = self.recs[e][t]
                self.assertEqual(r["c"], "IDENTITY_UNVERIFIED", (e, t))
                self.assertEqual([w[2] for w in r["o"]["wrapper"]], ["WRAPPER_ONLY"], (e, t))
        x = self.contracts["extended:PRLX-USD"]
        self.assertEqual((x["cls"], x["evidence"], x["wrapper"], x["exp_reason"]),
                         ("UNLABELED", None, [["CRYPTO_WRAPPER", "VENUE_CATEGORY:Crypto", "VENUE_METADATA"]],
                          "WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE"))
        self.assertEqual(x["vmeta"]["subCategory"], "AI")                       # recorded, never evidence
        self.assertIn(["subCategory", "AI"], x["candidate"])
        self.assertEqual((self.contracts["lighter:PRLX"]["legacy"], self.contracts["lighter:PRLX"]["exp_state"]),
                         ("PRICE_CONFLICT_DROPPED", "UNVERIFIED"))
        # a crypto wrapper on a known-crypto ticker: crypto by the list, the wrapper only recorded
        f = self.snap["registry"]["assets"]["FAKE10"]["identity"]
        self.assertEqual((f["state"], f["authority"]), ("VERIFIED_CRYPTO", "TICKER_LIST"))
        self.assertEqual([w[2] for w in f["wrapper_evidence"]], ["VENUE_CATEGORY:Crypto"])
        es = self.snap["registry"]["counts"]["exposure_safety"]
        self.assertEqual((es["wrapper_crypto_assets"], es["wrapper_only_unverified"], es["wrapper_with_ticker_list_crypto"],
                          es["economic_conflicts"], es["wrapper_unaccounted"]), (3, ["EXTONLY", "PRLX"], ["FAKE10"], [], 0))
        self.assertEqual(es["transitions_vs_previous"], {"AMBIGUOUS->VERIFIED_TRADFI": ["XIAOMI"],
                                                         "UNVERIFIED->VERIFIED_TRADFI": ["BYD", "HYUNDAIUSD", "US10Y"],
                                                         "VERIFIED_CRYPTO->UNVERIFIED": ["EXTONLY", "PRLX"]})

    def test_lighter_tokenlist_health_and_coverage(self):
        """v8 Phase 5: the token-list exposure check has explicit health and per-market coverage in the snapshot."""
        xm = self.snap["data_health"]["exposure_metadata"]["LIGHTER_TOKENLIST"]
        self.assertEqual((xm["state"], xm["venue"], xm["markets"], xm["markets_by_check"], xm["markets_without_check"]),
                         ("OK", "lighter", 14, {"OK": 14}, []))
        self.assertEqual(xm["markets_by_asset_type"], {"CRYPTO": 5, "RWA": 9})
        self.assertEqual(self.snap["manifest"]["data_sources"]["exposure_metadata"], {"LIGHTER_TOKENLIST": "OK"})
        self.assertIn("lighter:BB", xm["tradfi_evidence_markets"])
        self.assertNotIn("lighter:QNT", xm["tradfi_evidence_markets"])         # CRYPTO: no evidence either way
        q = self.contracts["lighter:QNT"]
        self.assertEqual((q["cls"], q["xcheck"], q["exp_class"]), ("UNLABELED", "OK", "CRYPTO"))
        self.assertIn(["asset_type", "CRYPTO"], q["candidate"])
        self.assertEqual(self.contracts["lighter:FAKE06"]["vmeta"].get("asset_type") if "lighter:FAKE06" in
                         self.contracts else self.contracts["lighter:1000FAKE06"]["vmeta"]["asset_type"], "CRYPTO")

    def test_smart_money_uses_the_same_scan_identity_authority(self):
        """The scanner wrote this scan's identity states; smart money read them (same scan) and every smart row
        carries its coin's state; on the fixture every smart coin is verified crypto, so nothing is blocked."""
        with open(os.path.join(self.out, "data", "v8", "identity_authority.json")) as fh:
            auth = json.load(fh)
        self.assertEqual(auth["identity_version"], "v8.identity/3")
        self.assertEqual({t: v[0] for t, v in auth["states"].items()},
                         {t: a["identity"]["state"] for t, a in self.snap["registry"]["assets"].items()
                          if a["legacy"] in ("CRYPTO", "TRADFI", "AMBIGUOUS", "UNVERIFIED")})
        self.assertEqual(auth["states"]["NEWCOIN"], ["UNVERIFIED", "IDENTITY_UNVERIFIED"])
        with open(os.path.join(self.out, "data", "smart.json")) as fh:
            sm = json.load(fh)
        self.assertEqual((sm["identity_authority"]["ok"], sm["identity_authority"]["why"]), (True, "SAME_SCAN"))
        self.assertTrue(sm["coins"])
        for c in sm["coins"]:
            self.assertEqual(c["identity"], "VERIFIED_CRYPTO", c["coin"])
            self.assertNotIn("identity_block", c)
            self.assertEqual(self.recs["smart"][c["coin"]]["o"]["identity"], "VERIFIED_CRYPTO")
        self.assertTrue(any(c["signal"] for c in sm["coins"]))
        part = self.snap["coverage"]["engines"]["smart"]["stages"]
        self.assertEqual(part["identity_blocked"], [])
        # final closure: every paper trade carries its entry-time identity proof, and the audit shows the boundary
        with open(os.path.join(self.out, "data", "smart_journal.json")) as fh:
            J = json.load(fh)
        self.assertTrue(J["open"])
        for tr in J["open"]:
            self.assertEqual((tr["identity_state_at_entry"], tr["identity_qualified"], tr["identity_version"],
                              tr["identity_scan_id"]), ("VERIFIED_CRYPTO", True, "v8.identity/3", "local-1791014833"))
        jn = self.snap["coverage"]["engines"]["smart"]["journal"]
        self.assertEqual(jn["evidence"]["qualified"]["open_signal"] + jn["evidence"]["qualified"]["open_info"],
                         len(J["open"]))
        self.assertEqual((jn["unqualified_n"], jn["unqualified_trades"]), (0, []))
        self.assertEqual(sm["accuracy"]["evidence"], jn["evidence"])
        self.assertEqual(sm["accuracy"]["legacy_unqualified"]["reason"], "LEGACY_NO_IDENTITY_PROOF")

    def test_quant_and_radar_journal_evidence_in_the_snapshot(self):
        """v8 Phase 3 closure: the quant and radar journal evidence reaches the snapshot; on the fixture every live
        trade is new, so all of it is qualified, and the published quant positions are the actionable ones."""
        with open(os.path.join(self.out, "data", "quant.json")) as fh:
            q = json.load(fh)
        jq = self.snap["coverage"]["engines"]["quant"]["journal"]
        self.assertEqual(jq["evidence"], q["evidence"])
        self.assertEqual((jq["evidence"]["actionable_open"], jq["evidence"]["blocked_open"]), (len(q["open"]), 0))
        self.assertEqual(jq["evidence"]["qualified"]["open"], len(q["open"]))
        self.assertEqual((jq["unqualified_n"], jq["blocked_open"]), (0, []))
        self.assertTrue(all(o["identity"] == "VERIFIED_CRYPTO" for o in q["open"]))
        jr = self.snap["coverage"]["engines"]["radar"]["journal"]
        with open(os.path.join(self.out, "data", "latest.json")) as fh:
            lt = json.load(fh)
        self.assertEqual(jr["evidence"]["legacy_live"], {"total": 0})
        self.assertGreater(jr["evidence"]["qualified_live"]["total"], 0)
        self.assertGreater(jr["evidence"]["backtest"]["total"], 0)
        self.assertEqual(jr["evidence"]["pairs"]["pair_class_mismatch"], 0)
        self.assertEqual(jr["evidence"]["qualified_live"], lt["journal"]["evidence"]["qualified_live"])
        for e in ("quant", "radar"):
            self.assertEqual(self.snap["coverage"]["engines"][e]["unaccounted"], 0)

    def test_identity_transitions_are_recorded_not_rewritten(self):
        ts = self.snap["manifest"]["ts"]
        prev = os.path.join(self.tmp, "id_prev.json")
        with open(prev, "w") as fh:
            json.dump({"NEWCOIN": ["UNVERIFIED", ts - 86400], "MOONX": ["VERIFIED_CRYPTO", ts - 3600],
                       "GONE": ["UNVERIFIED", ts - 100]}, fh)
        d = os.path.join(self.tmp, "again_id")
        shutil.copytree(self.keep, d)
        snap, _, _, _ = SN.write(d, identity_path=prev)
        moves = snap["coverage"]["summary"]["identity"]["transitions"]
        self.assertEqual([(m["asset"], m["from"], m["to"]) for m in moves], [("MOONX", "VERIFIED_CRYPTO", "UNVERIFIED")])
        with open(os.path.join(d, "data", "v8", "identity_state.json")) as fh:
            st = json.load(fh)
        self.assertEqual(st["NEWCOIN"], ["UNVERIFIED", ts - 86400])     # since the earlier scan, not rewritten
        self.assertEqual(st["MOONX"], ["UNVERIFIED", ts])
        self.assertEqual(st["GONE"], ["UNVERIFIED", ts - 100])          # not seen this scan: kept for a while
        with open(os.path.join(self.out, "data", "v8", "identity_state.json")) as fh:
            first = json.load(fh)
        self.assertEqual(first["QNT"], ["VERIFIED_CRYPTO", ts])

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
        # (EXTONLY, listed only on Extended, used to show NOT_ON_TRADE_DEX here; since Phase 5 its only evidence is
        # a crypto wrapper, so the identity gate stops it first: IDENTITY_UNVERIFIED. NOT_ON_TRADE_DEX is covered by
        # tests.test_v8_identity and tests.test_v8_units)
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
        self.assertEqual(self.snap["schema"], "v8.audit/4")
        self.assertEqual(self.snap["manifest"]["identity_version"], "v8.identity/3")
        self.assertEqual(len(self.snap["manifest"]["identity_config_hash"]), 64)
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
