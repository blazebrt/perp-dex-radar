"""v8 Phase 4 (Stage A): positive crypto identity evidence qualification.

Phase 4 asked which deterministic venue metadata fields can safely be POSITIVE CRYPTO EVIDENCE. Stage A censused every
candidate field against the verified identity of the retained and live scans and put every value through the
qualification gate (tools/v8/candidate_census.py). None qualified, so Stage B promoted nothing: the identity rules
and v8.identity/2 are unchanged. These tests pin that outcome and the new audit trace:

* the regression matrix: explicit Extended crypto and the known-crypto list still verify; an Aster stock sent with
  underlyingType COIN and the Aster tradfi subtypes stay tradfi; every candidate value (every Aster subtype that is not
  a tradfi class, every Lighter strategy_index / insurance fund / market flag value), a missing field and an unknown
  value all leave a coin UNVERIFIED and discovery-visible; trusted tradfi + crypto evidence is AMBIGUOUS; a candidate
  value on an unpriced contract or on a price-separated exposure changes nothing else;
* candidate evidence is recorded per contract and per asset apart from the authoritative evidence, marked as not
  authority, and counted per scan;
* the census gate end to end on a scan built by the real adapters: a data-clean theme tag fails gate A only, a value
  that sits on a tradfi-list ticker fails gate B, a tradfi class tag used as crypto fails gate D, the projection
  promotes nothing outside the selected exposure, and no rule qualifies;
* the identity version, config hash inputs and authority compatibility are unchanged.

Run from the repository root:  python -m unittest tests.test_v8_phase4 -v"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "v8"))

import candidate_census as CC  # noqa: E402
import scanner as sc  # noqa: E402
from test_v8_phase3 import aster, ext, hl, lighter, resolve, row_of, state, var  # noqa: E402
from v8 import identity as ID  # noqa: E402
from v8 import provenance  # noqa: E402
from v8 import registry as R  # noqa: E402
from v8 import snapshot as SN  # noqa: E402

ASTER_CANDIDATES = (["AI"], ["Meme"], ["Top"], ["AOS2"], ["pre-launch"], ["AI", "Meme"], ["Top", "AOS2"],
                    ["NEWTAG"], [])      # Semiconductor is a Phase 3 tradfi subtype, not a candidate


def ast(base, subs, px=1.0, vol=1e5, ut="COIN"):
    r = aster(f"{base}USDT", base, px, vol, ut=ut)
    if subs:
        r["subtypes"] = list(subs)
    return r


def lit(sym, px, vol, **fields):
    r = lighter(sym, px, vol)
    r.update(fields)                # raw Lighter fields on the row: the resolver must ignore them
    return r


class NoRuleQualified(unittest.TestCase):
    def test_outcome_pinned(self):
        self.assertEqual(ID.QUALIFIED_CRYPTO_RULES, ())
        # Phase 4 changed no authoritative rule (it stayed v8.identity/2). Phase 5 did - Extended Crypto is wrapper
        # evidence, Lighter token-list RWA is tradfi evidence - so the version became v8.identity/3
        # (tests.test_v8_phase5), and Phase 6 bound the known-crypto list to one exposure: v8.identity/4
        # (tests.test_v8_phase6). Every version stays reproducible by its own rules.
        self.assertEqual((ID.VERSION, ID.PREVIOUS_VERSION), ("v8.identity/4", "v8.identity/3"))
        self.assertEqual(ID.VERSION_RULES, {"v8.identity/2": 2, "v8.identity/3": 3, "v8.identity/4": 4})
        cfg = provenance.identity_config()
        # candidates never enter the identity config hash (min_candidate_len is the Phase 3 parsed-symbol rule)
        self.assertFalse({"candidate_fields", "qualified_crypto_rules", "candidate_status"} & set(cfg))
        self.assertEqual(cfg["aster_tradfi_subtypes"], sorted(ID.ASTER_TRADFI_SUBTYPES))
        self.assertEqual(cfg["extended_crypto_wrapper"], ["Crypto"])


class Matrix(unittest.TestCase):
    """Phase 4 regression matrix (section 21): nothing a candidate field says is crypto evidence."""

    def test_explicit_extended_crypto_still_verified(self):
        # Phase 4 pinned Extended Crypto as verifying; Phase 5 demoted it to wrapper evidence, and a candidate tag
        # beside it still verifies nothing: UNVERIFIED (v8.identity/2: VERIFIED_CRYPTO, CRYPTO_VENUE_METADATA)
        r = resolve(ext("ZNOV-USD", "ZNOV", 1.0, 2e6, cat="Crypto"), ast("ZNOV", ["AI"], px=1.01))
        self.assertEqual(state(r, "ZNOV"), ID.UNVERIFIED)
        self.assertEqual(r.asset("ZNOV")["reason"], "WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE")
        v2 = resolve(ext("ZNOV-USD", "ZNOV", 1.0, 2e6, cat="Crypto"), ast("ZNOV", ["AI"], px=1.01),
                     version="v8.identity/2")
        self.assertEqual(v2.asset("ZNOV")["reason"], "CRYPTO_VENUE_METADATA")

    def test_known_crypto_still_verified(self):
        r = resolve(hl("SOL", 150.0, 5e6), ast("SOL", ["Meme"], px=150.1))
        self.assertEqual(state(r, "SOL"), ID.VERIFIED_CRYPTO)

    def test_aster_stock_sent_as_coin_is_not_crypto(self):
        r = resolve(ast("ZSTK", ["STOCK"], px=220.0))
        self.assertEqual(state(r, "ZSTK"), ID.VERIFIED_TRADFI)
        r = resolve(ast("ZUNK", [], px=220.0))                   # COIN alone: still no evidence
        self.assertEqual(state(r, "ZUNK"), ID.UNVERIFIED)
        r = resolve(ast("ZSTK", ["STOCK", "AI"], px=220.0))      # a theme tag beside a class tag changes nothing
        self.assertEqual(state(r, "ZSTK"), ID.VERIFIED_TRADFI)

    def test_aster_tradfi_subtypes_still_tradfi(self):
        for sub in sorted(ID.ASTER_TRADFI_SUBTYPES):
            r = resolve(ast("ZETF", [sub]))
            self.assertEqual(state(r, "ZETF"), ID.VERIFIED_TRADFI, sub)

    def test_every_aster_candidate_value_stays_unverified(self):
        for subs in ASTER_CANDIDATES:
            r = resolve(ast("ZCND", subs, px=0.02, vol=3e6))
            self.assertEqual(state(r, "ZCND"), ID.UNVERIFIED, subs)
            self.assertTrue(ID.discovery_eligible(r.coins["ZCND"]), subs)
            self.assertFalse(ID.execution_identity_eligible(r.coins["ZCND"]), subs)
            self.assertEqual(row_of(r, "aster")["evidence"], None, subs)       # no authoritative evidence at all

    def test_every_lighter_candidate_value_stays_unverified(self):
        for si in (0, 2, 3, 4, 5, 6, 7, 99):
            for ifund in (281474976710654, 281474976710655):
                r = resolve(lit("ZLT", 0.5, 2e6, strategy_index=si, insurance_fund_account_index=ifund,
                                market_flags=0))
                self.assertEqual(state(r, "ZLT"), ID.UNVERIFIED, (si, ifund))

    def test_missing_and_unknown_values_fail_closed(self):
        self.assertEqual(state(resolve(ast("ZMIS", None)), "ZMIS"), ID.UNVERIFIED)
        self.assertEqual(state(resolve(ast("ZNEW", ["SOMETHING_NEW"])), "ZNEW"), ID.UNVERIFIED)
        self.assertEqual(state(resolve(lit("ZMIS2", 1.0, 1e5)), "ZMIS2"), ID.UNVERIFIED)

    def test_trusted_tradfi_plus_crypto_is_ambiguous(self):
        # Phase 5: Extended Crypto is a wrapper label, not crypto exposure evidence, so wrapper + tradfi exposure
        # evidence is tradfi, not ambiguous (v8.identity/2: AMBIGUOUS). Two economic sources that disagree are still
        # AMBIGUOUS (tests.test_v8_phase5.TrueConflict)
        r = resolve(ext("ZAMB-USD", "ZAMB", 10.0, 1e6, cat="Crypto", desc="Zamb Holdings Inc"))
        self.assertEqual(state(r, "ZAMB"), ID.VERIFIED_TRADFI)
        v2 = resolve(ext("ZAMB-USD", "ZAMB", 10.0, 1e6, cat="Crypto", desc="Zamb Holdings Inc"), version="v8.identity/2")
        self.assertEqual(v2.asset("ZAMB")["state"], ID.AMBIGUOUS)
        r = resolve(ext("ZAM2-USD", "ZAM2", 10.0, 1e6, cat="Crypto"), ast("ZAM2", ["STOCK", "AI"], px=10.05))
        self.assertEqual(state(r, "ZAM2"), ID.VERIFIED_TRADFI)

    def test_price_separated_collision_keeps_both_sides(self):
        # a crypto token at ~1 (Extended Crypto wrapper), a stock tagged STOCK (+ a theme tag) at ~240 under the same
        # ticker. Phase 5: the wrapper side of an unlisted ticker has no economic evidence, the stock stays tradfi
        r = resolve(ext("ZQN-USD", "ZQN", 1.0, 2e6, cat="Crypto"), ast("ZQN", ["STOCK", "AI"], px=240.0, vol=5e6),
                    lit("ZQN", 241.0, 1e6, strategy_index=2))
        self.assertEqual(state(r, "ZQN"), ID.AMBIGUOUS)          # unlabeled beside tradfi: the Phase 3 collision rule
        self.assertFalse(ID.execution_identity_eligible(r.coins["ZQN"]))
        cls = {g["id"]: g["class"] for g in r.asset("ZQN")["exposures"]}
        self.assertEqual(sorted(cls.values()), [ID.AMBIGUOUS, ID.TRADFI])
        # under a known-crypto ticker both sides keep their own class: crypto by the list, the stock tradfi
        r = resolve(ext("SOL-USD", "SOL", 1.0, 2e6, cat="Crypto"), ast("SOL", ["STOCK", "AI"], px=240.0, vol=5e6),
                    lit("SOL", 241.0, 1e6, strategy_index=2))
        self.assertEqual(state(r, "SOL"), ID.VERIFIED_CRYPTO)
        a = r.asset("SOL")
        self.assertEqual(a["decision"], ID.D_SELECTED)
        cls = {g["id"]: g["class"] for g in a["exposures"]}
        self.assertIn(ID.TRADFI, cls.values())                    # the stock exposure stays tradfi
        self.assertEqual(sorted(r.coins["SOL"]["venues"]), ["extended"])
        self.assertEqual(r.coins["SOL"]["ref_price"], 1.0)

    def test_new_tiny_coin_is_unverified_and_visible(self):
        r = resolve(hl("ZTINY", 0.0004, 812.0))
        self.assertEqual(state(r, "ZTINY"), ID.UNVERIFIED)
        self.assertTrue(ID.discovery_eligible(r.coins["ZTINY"]))

    def test_candidate_on_unpriced_contract_poisons_nothing(self):
        r = resolve(var("ZUP", 0.3, 1e6, "Zup"), ast("ZUP", ["AI"], px=None, vol=None))
        self.assertEqual(state(r, "ZUP"), ID.UNVERIFIED)
        r = resolve(ext("ZUQ-USD", "ZUQ", 2.0, 1e6, cat="RWA"), ast("ZUQ", ["Meme"], px=None, vol=None))
        self.assertEqual(state(r, "ZUQ"), ID.VERIFIED_TRADFI)
        r = resolve(ext("ZUR-USD", "ZUR", 2.0, 1e6, cat="Crypto"), ast("ZUR", ["Top"], px=None, vol=None))
        self.assertEqual(state(r, "ZUR"), ID.UNVERIFIED)                 # Phase 5: a wrapper alone verifies nothing
        r = resolve(ext("SOL-USD", "SOL", 2.0, 1e6, cat="Crypto"), ast("SOL", ["Top"], px=None, vol=None))
        self.assertEqual(state(r, "SOL"), ID.VERIFIED_CRYPTO)


class CandidateTrace(unittest.TestCase):
    """Candidate evidence is recorded, apart from authoritative evidence, and is never authority (section 11)."""

    def test_candidate_evidence_values(self):
        vm = {"underlyingType": "COIN", "underlyingSubType": ["AI", "STOCK"]}
        self.assertEqual(ID.candidate_evidence("aster", vm), [["underlyingType", "COIN"], ["underlyingSubType", "AI"]])
        self.assertEqual(ID.candidate_evidence("aster", {"underlyingType": "INDEX"}), [])     # authority already
        self.assertEqual(ID.candidate_evidence("lighter", {"strategy_index": 2, "market_flags": 0,
                                                           "insurance_fund_account_index": 7, "trading_hours": "x"}),
                         [["strategy_index", "2"], ["insurance_fund_account_index", "7"], ["market_flags", "0"]])
        self.assertEqual(ID.candidate_evidence("aster", None), [])
        self.assertEqual(ID.candidate_evidence("hyperliquid", {"strategy_index": 2}), [])

    def test_registry_keeps_candidates_apart(self):
        scan = Scan()
        try:
            reg = scan.registry
        finally:
            scan.close()
        c = next(x for x in reg["contracts"] if x["id"] == "aster:ZAIUSDT")
        self.assertEqual(c["candidate"], [["underlyingType", "COIN"], ["underlyingSubType", "AI"]])
        self.assertIsNone(c["evidence"])                                       # nothing authoritative
        a = reg["assets"]["ZAI"]
        self.assertEqual(a["identity"]["state"], ID.UNVERIFIED)
        self.assertEqual(a["identity"]["evidence"], [])
        self.assertEqual(a["candidate_evidence"]["authority"], False)
        self.assertEqual(a["candidate_evidence"]["status"], "OBSERVED_NOT_AUTHORITY")
        self.assertEqual(a["candidate_evidence"]["qualified_rules"], [])
        self.assertIn(["aster:ZAIUSDT", "underlyingSubType", "AI"], a["candidate_evidence"]["observed"])
        lt = reg["assets"]["ZLT"]["candidate_evidence"]["observed"]
        self.assertIn(["lighter:ZLT", "strategy_index", "2"], lt)
        cc = R.counts(reg)["candidate_evidence"]
        self.assertEqual(cc["qualified_rules"], [])
        self.assertEqual(cc["by_value_and_exposure_state"]["aster.underlyingSubType=Meme"],
                         {ID.UNVERIFIED: 1, ID.VERIFIED_TRADFI: 1})
        self.assertIn("ZAI", cc["unverified_with_candidate"])
        self.assertIn("candidate", SN.CONTRACT_FIELDS)          # Phase 5 appended wrapper and xcheck after it
        self.assertEqual(SN.CONTRACT_FIELDS[SN.CONTRACT_FIELDS.index("candidate"):], ("candidate", "wrapper", "xcheck"))


# --------------------------------------------------------------------------- a scan built by the real adapters
class Scan:
    """build_universe() over Aster and Lighter payloads (every other venue down), its registry, and the snapshot a
    census reads: ZAI (AI tag, data-clean), ZMEME (Meme), CAT (Meme on a tradfi-list ticker, like the live memecoin
    CAT), ZSTK (STOCK), ZLT and PAXG (Lighter strategy_index 2; PAXG is on the tradfi list, as it is live)."""

    ASTER = [("ZAIUSDT", "ZAI", ["AI"], 0.5, 2e6), ("ZMEMEUSDT", "ZMEME", ["Meme"], 0.01, 3e5),
             ("1000CATUSDT", "1000CAT", ["Meme"], 0.002, 4e5), ("ZSTKUSDT", "ZSTK", ["STOCK"], 220.0, 9e5)]
    LIGHTER = [("ZLT", 2, 1.2, 5e5), ("PAXG", 2, 4190.0, 1e6)]

    def __init__(self):
        info = {"symbols": [{"symbol": s, "baseAsset": b, "quoteAsset": "USDT", "marginAsset": "USDT",
                             "contractType": "PERPETUAL", "status": "TRADING", "underlyingType": "COIN",
                             "underlyingSubType": subs} for s, b, subs, _, _ in self.ASTER]}
        tick = [{"symbol": s, "lastPrice": str(p), "quoteVolume": str(v)} for s, _, _, p, v in self.ASTER]
        prem = [{"symbol": s, "markPrice": str(p), "lastFundingRate": "0.0001"} for s, _, _, p, _ in self.ASTER]
        books = {"order_book_details": [
            {"symbol": s, "market_type": "perp", "status": "active", "mark_price": str(p),
             "daily_quote_token_volume": v, "market_flags": 0, "strategy_index": si,
             "market_config": {"trading_hours": "", "insurance_fund_account_index": 281474976710655}}
            for s, si, p, v in self.LIGHTER]}
        answers = {sc.ASTER_INFO: info, sc.ASTER_TICKER: tick, sc.ASTER_PREMIUM: prem, sc.LIGHTER_BOOKS: books}

        def fetch(url, body=None, timeout=25):
            if url in answers:
                return answers[url]
            raise sc.HttpError(503, "down")
        old = sc.FETCH
        sc.FETCH = fetch
        try:
            coins, status, ok = sc.build_universe()
            self.registry = R.build(sc.V8, coins, status, ok, 1791500000)
        finally:
            sc.FETCH = old
        self.coins = coins
        snap = {"manifest": {"scan_id": "local-test", "git_sha": "test", "ts": 1791500000,
                             "identity_version": ID.VERSION},
                "registry": {"contracts": SN.columns(self.registry["contracts"]), "assets": self.registry["assets"]}}
        self.tmp = tempfile.mkdtemp(prefix="v8p4")
        self.path = os.path.join(self.tmp, "audit_latest.json")
        with open(self.path, "w") as fh:
            json.dump(snap, fh)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class CensusGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = Scan()
        cls.rep = CC.report([cls.scan.path])
        cls.rules = {r["rule"]: r for r in cls.rep["rules"]}

    @classmethod
    def tearDownClass(cls):
        cls.scan.close()

    def obs(self, rule):
        return self.rules[rule]["observations"]["local-test"]

    def test_scan_states(self):
        st = {t: c["identity"] for t, c in self.scan.coins.items()}
        self.assertEqual(st, {"ZAI": ID.UNVERIFIED, "ZMEME": ID.UNVERIFIED, "CAT": ID.VERIFIED_TRADFI,
                              "ZSTK": ID.VERIFIED_TRADFI, "ZLT": ID.UNVERIFIED, "PAXG": ID.VERIFIED_TRADFI})

    def test_reproduction_is_exact(self):
        self.assertEqual(self.rep["reproduction"]["local-test"]["state_differences"], [])

    def test_clean_theme_tag_fails_semantics_only(self):
        r = self.rules["aster.underlyingSubType == only AI AND underlyingType == COIN"]
        self.assertEqual(r["gate"], {"A": False, "B": True, "C": True, "D": True, "E": True})
        self.assertFalse(r["qualified"])
        self.assertIn("sector / theme tag", r["semantics"]["note"])
        # its impact is known before activation: exactly its own unverified exposure
        p = self.obs(r["rule"])["projection"]
        self.assertEqual([(c["asset"], c["from"], c["to"]) for c in p["changed"]],
                         [("ZAI", ID.UNVERIFIED, ID.VERIFIED_CRYPTO)])

    def test_value_on_a_tradfi_list_ticker_fails_contamination(self):
        r = self.rules["aster.underlyingSubType == only Meme"]
        self.assertFalse(r["gate"]["B"])
        self.assertEqual([e["asset"] for e in self.obs(r["rule"])["tradfi_examples"]], ["CAT"])
        # the tradfi list still settles CAT: the projection cannot flip it
        self.assertNotIn("CAT", [c["asset"] for c in self.obs(r["rule"])["projection"]["changed"]])

    def test_lighter_strategy_index_fails_semantics_and_contamination(self):
        r = self.rules["lighter.strategy_index==2"]
        self.assertFalse(r["gate"]["A"])
        self.assertFalse(r["gate"]["B"])
        self.assertIn("absent from Lighter's OpenAPI schema", r["semantics"]["note"])
        self.assertEqual([e["asset"] for e in self.obs(r["rule"])["tradfi_examples"]], ["PAXG"])

    def test_tradfi_class_tag_as_crypto_fails_negative_controls(self):
        r = self.rules["aster.underlyingSubType contains STOCK"]
        self.assertFalse(r["gate"]["D"])
        leaks = self.obs(r["rule"])["projection_leaks"]
        self.assertEqual([(c["asset"], c["from"], c["to"]) for c in leaks],
                         [("ZSTK", ID.VERIFIED_TRADFI, ID.AMBIGUOUS)])

    def test_nothing_qualifies(self):
        self.assertEqual(self.rep["qualified_rules"], [])
        for r in self.rep["rules"]:
            self.assertFalse(r["qualified"], r["rule"])

    def test_inventory_lists_every_unverified_asset(self):
        inv = {x["asset"]: x for x in self.rep["unverified_inventory"]["local-test"]}
        self.assertEqual(sorted(inv), ["ZAI", "ZLT", "ZMEME"])
        self.assertIn("aster.underlyingSubType == only AI", inv["ZAI"]["matching_rules"])
        self.assertTrue(inv["ZAI"]["liquid_1m"])


if __name__ == "__main__":
    unittest.main()
