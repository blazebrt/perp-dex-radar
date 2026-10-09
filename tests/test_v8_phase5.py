"""v8 Phase 5: economic exposure safety and tokenized-RWA hardening (v8.identity/3).

A venue can label the traded wrapper "Crypto" while the economic exposure is gold, a stock, an index or a rate. The
identity follows the economic exposure:

* wrapper evidence (Extended category Crypto) is recorded apart and never decides; a crypto wrapper beside tradfi
  economic evidence is VERIFIED_TRADFI (not a conflict), a crypto wrapper with no economic evidence is UNVERIFIED
  (WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE) unless the known-crypto list verifies the ticker; two economic sources that
  disagree inside one exposure are still AMBIGUOUS;
* Lighter's documented token-list asset_type RWA is tradfi evidence on its own contract; asset_type CRYPTO is none;
* the token list is one bulk request with explicit health, and its failure never makes a market crypto: an exposure
  seen only through markets whose check did not run is not verified by the ticker list (EXPOSURE_CHECK_UNAVAILABLE);
* the version is v8.identity/3: v2 authority files fail, the config hash changes, entry-time proof written under v2
  stays qualified (no hindsight), and the current gates block a coin the new version downgrades;
* PAXG and XAUT are regression controls, never rules: nothing in v8.identity names them, and the synthetic unknown
  tokenized gold, equity, index and rate fixtures resolve by their exposure.

Section 42 of the Phase 5 brief: the ScanGateInvariants class is cheap enough for every scheduled scan.

Run from the repository root:  python -m unittest tests.test_v8_phase5 -v"""
from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import dashboard as D  # noqa: E402
import quant as Q  # noqa: E402
import scanner as sc  # noqa: E402
import smart as SM  # noqa: E402
from test_v8_phase3 import LISTS, aster, ext, hl, row, row_of, var  # noqa: E402
from v8 import evidence as EV  # noqa: E402
from v8 import identity as ID  # noqa: E402
from v8 import provenance  # noqa: E402
from v8 import registry as R  # noqa: E402
from v8.trace import Recorder  # noqa: E402

PHASE4_IDENTITY_CONFIG_HASH = "c4d023f62fd5c8d40f0fa5a1e32c64a250d907604632096e27c02a30ae826878"
NEG_CONTROLS = ("PAXG", "XAUT", "SPY", "NVDA", "TSLA", "XAU", "US500", "US10Y", "BYD", "SAMSUNGUSD", "HYUNDAIUSD",
                "XIAOMI")
POS_CONTROLS = ("BTC", "ETH", "SOL", "QNT", "PURR", "BB")


# --------------------------------------------------------------------------- rows shaped like the adapters' output
def lt(sym, price, vol, asset_type="CRYPTO", cats=(), xcheck="OK"):
    """A Lighter market as dex_lighter() returns it: the token-list check result beside the market fields."""
    r = row("lighter", sym, sym, price, vol)
    if xcheck == "OK":
        r.update(xcheck="OK", asset_type=asset_type, asset_categories=list(cats))
    elif xcheck is not None:
        r["xcheck"] = xcheck
    return r


def ex(name, asset, price, vol, cat="Crypto", sub=None, desc=None):
    r = ext(name, asset, price, vol, cat=cat, desc=desc)
    if sub is not None:
        r["subCategory"] = sub          # recorded by the registry as candidate evidence; the resolver never reads it
    return r


def res(*rows, lists=LISTS):
    out = {d: [] for d in sc.DEXES}
    for r in rows:
        out[r["dex"]].append(r)
    return ID.resolve(out, sc.DEXES, lists, sc.in_my_dexes)


def st(r, t):
    return r.coins[t]["identity"]


def no_ticker_lists(*drop):
    """The repository lists without the given tickers: proves a result does not come from a ticker rule."""
    return ID.Lists(sc.TRADFI - set(drop), sc.KNOWN_CRYPTO - set(drop), sc.is_fx, sc.TRADFI_NAME)


# --------------------------------------------------------------------------- the model
class WrapperVsEconomicExposure(unittest.TestCase):
    def test_version_and_rules(self):
        self.assertEqual((ID.VERSION, ID.PREVIOUS_VERSION), ("v8.identity/3", "v8.identity/2"))
        self.assertEqual(ID.QUALIFIED_CRYPTO_RULES, ())                       # Phase 5 adds no positive rule
        self.assertEqual(ID.wrapper_evidence(ex("N-USD", "N", 1.0, 1e5)),
                         [(ID.CRYPTO_WRAPPER, "VENUE_CATEGORY:Crypto", ID.VENUE_METADATA)])
        self.assertEqual(ID.wrapper_evidence(ex("N-USD", "N", 1.0, 1e5, cat="RWA")), [])
        # Extended Crypto is no economic evidence under /3, crypto evidence under /2 (the before/after only)
        self.assertEqual(ID.contract_evidence(ex("N-USD", "N", 1.0, 1e5), LISTS), [])
        self.assertEqual(ID.contract_evidence(ex("N-USD", "N", 1.0, 1e5), LISTS, rules=2),
                         [(ID.CRYPTO, "VENUE_CATEGORY:Crypto", ID.VENUE_METADATA)])

    def test_newtoken_crypto_wrapper_without_exposure_proof_is_unverified(self):
        """Section 20, the key false-positive prevention test."""
        r = res(ex("NEWTOKEN-USD", "NEWTOKEN", 0.42, 2.5e6, sub="AI"))
        self.assertEqual(st(r, "NEWTOKEN"), ID.UNVERIFIED)
        c = r.coins["NEWTOKEN"]
        self.assertTrue(ID.discovery_eligible(c))                              # discovery YES
        self.assertFalse(ID.execution_identity_eligible(c))                    # execution NO
        self.assertFalse(sc.crypto_authorized(c))
        self.assertFalse(c["tradfi"])                                          # unknown is not tradfi
        a = r.asset("NEWTOKEN")
        self.assertEqual((a["decision"], a["reason"], a["authority"], a["wrapper_only"]),
                         (ID.D_UNVERIFIED, "WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE", ID.NONE, True))
        self.assertEqual(a["evidence"], [])
        tr = a["exposure_trace"]
        self.assertEqual(tr["wrapper"], [{"source": "extended:NEWTOKEN-USD", "evidence": "VENUE_CATEGORY:Crypto",
                                          "effect": "WRAPPER_ONLY"}])
        self.assertEqual((tr["economic"], tr["final"], tr["crypto_execution"]), ([], ID.UNVERIFIED, "BLOCKED"))
        # v8.identity/2 would have made it VERIFIED_CRYPTO from the wrapper label alone: the latent path is closed
        self.assertEqual((a["previous"]["state"], a["previous"]["reason"]), (ID.VERIFIED_CRYPTO, "CRYPTO_VENUE_METADATA"))
        # a crypto-looking sector subCategory changes nothing (undocumented: candidate evidence, never authority)
        for sub in ("L1", "L2", "DeFi", "Meme", "Infra", None):
            self.assertEqual(st(res(ex("NEWTOKEN-USD", "NEWTOKEN", 0.42, 2.5e6, sub=sub)), "NEWTOKEN"), ID.UNVERIFIED)

    def test_newgold_crypto_wrapper_plus_commodity_exposure_is_tradfi(self):
        """Section 18: venue A wraps it as Crypto, venue B's documented exposure metadata says commodity; same
        coherent price -> VERIFIED_TRADFI, not crypto, not ambiguous."""
        r = res(ex("NEWGOLD-USD", "NEWGOLD", 4190.0, 3e6, sub="Commodity", desc="Newgold"),
                lt("NEWGOLD", 4185.5, 1.2e6, "RWA", ["COMMODITIES"]))
        self.assertEqual(st(r, "NEWGOLD"), ID.VERIFIED_TRADFI)
        self.assertTrue(r.coins["NEWGOLD"]["tradfi"])
        a = r.asset("NEWGOLD")
        self.assertEqual(len(a["exposures"]), 1)                               # one coherent exposure
        x = a["exposures"][0]
        self.assertEqual((x["class"], x["reason"], x["wrapper"]),
                         (ID.TRADFI, "TRADFI_CONTRACT_EVIDENCE", ["VENUE_CATEGORY:Crypto"]))
        self.assertEqual(a["evidence"], [["lighter:NEWGOLD", ID.TRADFI, "VENUE_ASSET_TYPE:RWA", ID.VENUE_METADATA]])
        self.assertEqual(row_of(r, "extended")["inherited_from"], "lighter:NEWGOLD")
        self.assertEqual(a["exposure_trace"]["economic_classes"], [ID.TRADFI])
        self.assertEqual(a["exposure_trace"]["crypto_execution"], "BLOCKED")
        # v8.identity/2 (no token list; Extended Crypto as crypto evidence) would have called it crypto
        self.assertEqual(a["previous"]["state"], ID.VERIFIED_CRYPTO)

    def test_newstock_crypto_wrapper_plus_equity_exposure_is_tradfi(self):
        """Section 19, with each documented equity source: Lighter token-list RWA, an Aster STOCK subtype, an Aster
        underlyingType other than COIN."""
        for other in (lt("NEWSTOCK", 101.0, 5e5, "RWA", ["STOCK"]),
                      dict(aster("NEWSTOCKUSDT", "NEWSTOCK", 101.0, 5e5), subtypes=["STOCK"]),
                      aster("NEWSTOCKUSDT", "NEWSTOCK", 101.0, 5e5, ut="EQUITY")):
            r = res(ex("NEWSTOCK-USD", "NEWSTOCK", 100.0, 2e6, sub="Equity", desc="Newstock"), other)
            self.assertEqual(st(r, "NEWSTOCK"), ID.VERIFIED_TRADFI, other["dex"])
            self.assertEqual(r.asset("NEWSTOCK")["exposures"][0]["class"], ID.TRADFI)

    def test_unknown_tokenized_index_and_rate(self):
        r = res(ex("NEWIDX-USD", "NEWIDX", 6500.0, 2e6, sub="ETF/Index", desc="Newidx"),
                lt("NEWIDX", 6490.0, 8e5, "RWA", ["ETF", "MAJOR"]))
        self.assertEqual(st(r, "NEWIDX"), ID.VERIFIED_TRADFI)
        r = res(lt("NEWRATE", 95.1, 7000.0, "RWA", ["BONDS"]))               # a rate: the token list alone
        self.assertEqual(st(r, "NEWRATE"), ID.VERIFIED_TRADFI)
        self.assertEqual(r.asset("NEWRATE")["previous"]["state"], ID.UNVERIFIED)
        r = res(ex("NEWRATE-USD", "NEWRATE", 95.0, 1e5, desc="Newrate"), lt("NEWRATE", 95.1, 7000.0, "RWA", ["BONDS"]))
        self.assertEqual(st(r, "NEWRATE"), ID.VERIFIED_TRADFI)                 # a wrapper beside it changes nothing

    def test_undocumented_subcategory_alone_is_not_evidence(self):
        """Extended's subCategory is not in Extended's documented market schema: an unknown gold token seen only on
        Extended (Crypto / Commodity) is UNVERIFIED - never crypto - not tradfi either."""
        r = res(ex("ONLYGOLD-USD", "ONLYGOLD", 4190.0, 3e6, sub="Commodity", desc="Onlygold"))
        self.assertEqual(st(r, "ONLYGOLD"), ID.UNVERIFIED)
        self.assertFalse(ID.execution_identity_eligible(r.coins["ONLYGOLD"]))
        self.assertEqual(ID.candidate_evidence("extended", {"subCategory": "Commodity"}), [["subCategory", "Commodity"]])

    def test_true_conflict_of_two_economic_sources_is_ambiguous(self):
        """Section 13: AMBIGUOUS stays for two trusted economic sources that disagree inside one exposure. No source
        produces crypto economic evidence today (QUALIFIED_CRYPTO_RULES is empty), so one is simulated."""
        orig = ID.exposure_field_evidence

        def with_crypto(row_):
            if row_.get("test_crypto_economic"):
                return [(ID.CRYPTO, "TEST_QUALIFIED_CRYPTO", ID.VENUE_METADATA)]
            return orig(row_)
        with mock.patch.object(ID, "exposure_field_evidence", with_crypto):
            r = res(dict(lt("ZCONF", 10.0, 1e6, "CRYPTO"), test_crypto_economic=True),
                    lt("ZCONFUSD", 10.0, 1e6, "RWA"))      # another ticker: no conflict
            self.assertEqual(st(r, "ZCONF"), ID.VERIFIED_CRYPTO)
            r = res(dict(lt("ZCONF", 10.0, 1e6, "CRYPTO"), test_crypto_economic=True),
                    dict(aster("ZCONFUSDT", "ZCONF", 10.02, 5e5), subtypes=["STOCK"]))
            self.assertEqual(st(r, "ZCONF"), ID.AMBIGUOUS)
            self.assertEqual(r.asset("ZCONF")["exposures"][0]["reason"], "CONFLICTING_CONTRACT_EVIDENCE")
        # a wrapper and tradfi economic evidence are never that conflict (section 12)
        r = res(ex("ZWRP-USD", "ZWRP", 10.0, 1e6), dict(aster("ZWRPUSDT", "ZWRP", 10.02, 5e5), subtypes=["STOCK"]))
        self.assertEqual(st(r, "ZWRP"), ID.VERIFIED_TRADFI)

    def test_a_wrapper_on_one_exposure_never_reclassifies_another(self):
        """Section 22: price-separated exposures keep their own class."""
        r = res(ex("ZSEP-USD", "ZSEP", 1.0, 2e6), lt("ZSEP", 240.0, 1e6, "RWA", ["STOCK"]),
                hl("ZSEP", 241.0, 5e5))
        cls = {x["id"]: (x["class"], x.get("wrapper")) for x in r.asset("ZSEP")["exposures"]}
        stock = next(v for k, v in cls.items() if v[0] == ID.TRADFI)
        self.assertIsNone(stock[1])                                            # the wrapper stays on its exposure
        self.assertEqual(row_of(r, "hyperliquid")["inherited_from"], "lighter:ZSEP")
        self.assertNotEqual(row_of(r, "extended")["exp_cls"], ID.TRADFI)       # nothing inherited across exposures
        self.assertFalse(ID.execution_identity_eligible(r.coins["ZSEP"]))

    def test_trading_schedule_and_rfq_are_never_evidence(self):
        """Section 36: CONTINUOUS, WEEKDAYS, RFQ and off-hours flags are execution metadata, not asset class."""
        for extra in ({"tradingHours": "CONTINUOUS"}, {"tradingHours": "WEEKDAYS"}, {"isRfq": True},
                      {"isOffHours": True}, {"trading_hours": "WEEKDAYS"}):
            r = res(dict(ex("ZHRS-USD", "ZHRS", 3.0, 1e6), **extra))
            self.assertEqual(st(r, "ZHRS"), ID.UNVERIFIED, extra)
            r = res(dict(ex("ZHRS-USD", "ZHRS", 3.0, 1e6, cat="RWA"), **extra))
            self.assertEqual((st(r, "ZHRS"), r.asset("ZHRS")["evidence"][0][2]), (ID.VERIFIED_TRADFI,
                                                                                   "VENUE_CATEGORY:RWA"), extra)
            r = res(dict(lt("ZHRL", 3.0, 1e6, "CRYPTO"), **extra))
            self.assertEqual(st(r, "ZHRL"), ID.UNVERIFIED, extra)
        src = inspect.getsource(ID)
        for word in ("tradingHours", "isRfq", "isOffHours", "CONTINUOUS", "WEEKDAYS", "referenceMarket"):
            self.assertNotIn(word, src, word)


# --------------------------------------------------------------------------- controls (tests, never rules)
class Controls(unittest.TestCase):
    def test_controls_are_not_rules(self):
        src = inspect.getsource(ID)
        for t in NEG_CONTROLS + ("PAXG", "XAUT", "GOLD"):
            self.assertNotIn(f'"{t}"', src, t)
            self.assertNotIn(f"'{t}'", src, t)

    def test_paxg_and_xaut_by_exposure_not_by_ticker(self):
        """Section 17, live shapes: Extended files both under Crypto (subCategory Commodity) with their own names;
        Lighter lists PAXG as RWA (COMMODITIES); Hyperliquid lists PAXG without a label."""
        live = (ex("PAXG-USD", "PAXG", 4190.0, 9e5, sub="Commodity", desc="PAX Gold"),
                lt("PAXG", 4186.0, 2.1e6, "RWA", ["COMMODITIES"]), hl("PAXG", 4188.0, 3e6),
                ex("XAUT-USD", "XAUT", 4180.0, 4e5, sub="Commodity", desc="Tether Gold"))
        for lists in (LISTS, no_ticker_lists("PAXG", "XAUT")):
            r = res(*live, lists=lists)
            for t in ("PAXG", "XAUT"):
                self.assertEqual(st(r, t), ID.VERIFIED_TRADFI, (t, lists is LISTS))
                self.assertFalse(ID.execution_identity_eligible(r.coins[t]))
                self.assertEqual([w[2] for w in r.asset(t)["wrapper_evidence"]], ["VENUE_CATEGORY:Crypto"])
        r = res(*live, lists=no_ticker_lists("PAXG", "XAUT"))
        self.assertIn(["lighter:PAXG", ID.TRADFI, "VENUE_ASSET_TYPE:RWA", ID.VENUE_METADATA], r.asset("PAXG")["evidence"])
        self.assertIn(["extended:XAUT-USD", ID.TRADFI, "NAME_PATTERN:gold", ID.CONTRACT_NAME], r.asset("XAUT")["evidence"])
        # without any economic evidence (no list, no name, no token list) the wrapper alone still verifies nothing
        r = res(ex("XAUT-USD", "XAUT", 4180.0, 4e5, sub="Commodity"), lists=no_ticker_lists("PAXG", "XAUT"))
        self.assertEqual(st(r, "XAUT"), ID.UNVERIFIED)

    def test_negative_controls_never_crypto(self):
        live = [ex("PAXG-USD", "PAXG", 4190.0, 9e5, sub="Commodity", desc="PAX Gold"),
                lt("PAXG", 4186.0, 2.1e6, "RWA", ["COMMODITIES"]),
                ex("XAUT-USD", "XAUT", 4180.0, 4e5, sub="Commodity", desc="Tether Gold"),
                lt("SPY", 660.0, 3e6, "RWA", ["ETF", "MAJOR"]), lt("NVDA", 180.0, 4e6, "RWA", ["STOCK"]),
                lt("TSLA", 430.0, 5e6, "RWA", ["STOCK"]), ex("XAU-USD", "XAU", 4185.0, 2e7, cat="RWA", sub="Commodity"),
                lt("XAU", 4184.0, 9e6, "RWA", ["COMMODITIES", "MAJOR"]), lt("US500", 6650.0, 9e6, "RWA", ["ETF", "MAJOR"]),
                lt("US10Y", 95.1, 7000.0, "RWA", ["BONDS"]), lt("BYD", 2.95, 0.0, "RWA", ["NEW"]),
                lt("SAMSUNGUSD", 200.6, 1.8e6, "RWA", ["STOCK", "KRW"]), lt("HYUNDAIUSD", 252.4, 2600.0, "RWA", ["STOCK", "KRW"]),
                aster("XIAOMIUSDT", "XIAOMI", 3.11, 3570.0), lt("XIAOMI", 3.09, 8.4e5, "RWA", ["STOCK"]),
                ex("XIAOMI-USD", "XIAOMI", 24.19, 0.0, cat="RWA", sub="Equity")]
        r = res(*live)
        for t in NEG_CONTROLS:
            self.assertEqual(st(r, t), ID.VERIFIED_TRADFI, t)
            self.assertFalse(ID.execution_identity_eligible(r.coins[t]), t)

    def test_positive_controls_stay_crypto_with_collisions(self):
        """Sections 21 and 22, live shapes: crypto by the known-crypto list; the price-separated stock under the same
        ticker (QNT, PURR, BB) stays tradfi and out of the coin, also when its Lighter market is on the token list."""
        r = res(hl("BTC", 121000.0, 2e9), ex("BTC-USD", "BTC", 121010.0, 3e8, sub="L1"), lt("BTC", 121005.0, 9e8),
                hl("ETH", 4400.0, 1e9), ex("ETH-USD", "ETH", 4401.0, 2e8, sub="L1"), lt("ETH", 4400.5, 5e8),
                hl("SOL", 220.0, 5e8), lt("SOL", 220.1, 1e8),
                var("QNT", 257.89, 1.48e6, "Quant"), aster("QNTUSDT", "QNT", 255.93, 2.43e6), lt("QNT", 255.94, 336238.72),
                ex("QNT-USD", "QNT", 46.03, 386135.13, cat="RWA", sub="Equity"),
                hl("PURR", 0.1536, 3.09e6), ex("PURR-USD", "PURR", 12.77, 3031.12, cat="RWA", sub="Equity",
                                               desc="Hyperliquid Strategies Inc."),
                var("BBIT", 0.0088, 75.9, "BounceBit"), aster("BBUSDT", "BB", 0.0088, 5889.8),
                lt("BB", 8.72, 261799.05, "RWA", ["STOCK"]), ex("BB-USD", "BB", 8.72, 40.05, cat="RWA", sub="Equity"))
        for t in POS_CONTROLS:
            self.assertEqual(st(r, t), ID.VERIFIED_CRYPTO, t)
            self.assertTrue(ID.execution_identity_eligible(r.coins[t]), t)
        self.assertEqual(sorted(r.coins["QNT"]["venues"]), ["aster", "lighter", "variational"])
        self.assertEqual(sorted(r.coins["PURR"]["venues"]), ["hyperliquid"])
        self.assertEqual(sorted(r.coins["BB"]["venues"]), ["aster", "variational"])
        bb = {x["id"]: x for x in r.asset("BB")["exposures"]}
        self.assertEqual(sorted(x["class"] for x in bb.values()), [ID.CRYPTO, ID.TRADFI])
        self.assertEqual(r.asset("BTC")["wrapper_evidence"][0][2], "VENUE_CATEGORY:Crypto")      # recorded only

    def test_bb_stock_no_longer_depends_on_extended(self):
        """The live BB shape without Extended's market (an Extended outage or delisting): v8.identity/2 had nothing
        to tell the Lighter BlackBerry market from BounceBit and verified it as crypto by the ticker list; under /3
        its own token-list entry keeps it tradfi, and with the token list down it is UNVERIFIED - never crypto."""
        crypto = (var("BBIT", 0.0088, 75.9, "BounceBit"), aster("BBUSDT", "BB", 0.0088, 5889.8))
        r = res(*crypto, lt("BB", 8.72, 261799.05, "RWA", ["STOCK"]))
        self.assertEqual(st(r, "BB"), ID.VERIFIED_CRYPTO)
        self.assertEqual(sorted(r.coins["BB"]["venues"]), ["aster", "variational"])
        self.assertEqual(row_of(r, "lighter")["exp_cls"], ID.TRADFI)
        for down in ("FAILED", "UNAVAILABLE", "MALFORMED", "NO_ENTRY", "MALFORMED_ENTRY", None):
            r = res(*crypto, lt("BB", 8.72, 261799.05, xcheck=down))
            self.assertEqual(sorted(r.coins["BB"]["venues"]), ["aster", "variational"], down)
            self.assertEqual((row_of(r, "lighter")["exp_cls"], row_of(r, "lighter")["exp_why"]),
                             (ID.UNVERIFIED, "EXPOSURE_CHECK_UNAVAILABLE"), down)
            self.assertFalse(row_of(r, "lighter")["admitted"], down)


# --------------------------------------------------------------------------- the Lighter token list
TOKENS = {"code": 200, "tokens": [
    {"symbol": "ETH", "market": "PERPS", "asset_type": "CRYPTO", "categories": ["MAJOR"]},
    {"symbol": "kPEPE", "backend_symbol": "1000PEPE", "market": "PERPS", "asset_type": "CRYPTO", "categories": []},
    {"symbol": "US10Y", "market": "PERPS", "asset_type": "RWA", "categories": ["BONDS"]},
    {"symbol": "XAUT", "market": "SPOT", "asset_type": "CRYPTO", "categories": ["NEW"]},
    {"symbol": "ODD", "market": "PERPS", "asset_type": "COMMODITY", "categories": []},
    {"symbol": "TWICE", "market": "PERPS", "asset_type": "RWA", "categories": []},
    {"symbol": "TWICE", "market": "PERPS", "asset_type": "CRYPTO", "categories": []}]}


class TokenList(unittest.TestCase):
    def test_index_semantics(self):
        state, idx, det = ID.lighter_tokenlist_index(TOKENS)
        self.assertEqual(state, "OK")
        self.assertEqual(idx["ETH"]["asset_type"], "CRYPTO")
        self.assertEqual(idx["1000PEPE"]["asset_type"], "CRYPTO")              # backend_symbol is the market symbol
        self.assertNotIn("kPEPE", idx)
        self.assertEqual(idx["US10Y"], {"asset_type": "RWA", "categories": ["BONDS"]})
        self.assertNotIn("XAUT", idx)                                          # spot entries are not perp markets
        self.assertIsNone(idx["ODD"])                                          # outside the documented enum
        self.assertIsNone(idx["TWICE"])                                        # two entries that disagree
        self.assertEqual((det["malformed_entries"], det["duplicate_entries"]), (["ODD"], ["TWICE"]))
        for bad in (None, [], {"code": 200}, {"code": 500, "tokens": []}, {"tokens": "x"},
                    {"code": 200, "tokens": [{"symbol": "A", "market": "PERPS", "asset_type": "X"}]}):
            self.assertEqual(ID.lighter_tokenlist_index(bad)[0], "MALFORMED", bad)

    def test_market_fields(self):
        _, idx, _ = ID.lighter_tokenlist_index(TOKENS)
        self.assertEqual(ID.lighter_exposure_fields("US10Y", "OK", idx),
                         {"xcheck": "OK", "asset_type": "RWA", "asset_categories": ["BONDS"]})
        self.assertEqual(ID.lighter_exposure_fields("NEWMKT", "OK", idx), {"xcheck": "NO_ENTRY"})
        self.assertEqual(ID.lighter_exposure_fields("ODD", "OK", idx), {"xcheck": "MALFORMED_ENTRY"})
        for s in ("FAILED", "UNAVAILABLE", "MALFORMED"):
            self.assertEqual(ID.lighter_exposure_fields("US10Y", s, idx), {"xcheck": s})
        self.assertEqual(ID.lighter_exposure_fields("US10Y", None, idx), {"xcheck": "NOT_REQUESTED"})

    def test_only_rwa_is_evidence(self):
        self.assertEqual(ID.exposure_field_evidence(lt("ZR", 1.0, 1.0, "RWA")),
                         [(ID.TRADFI, "VENUE_ASSET_TYPE:RWA", ID.VENUE_METADATA)])
        self.assertEqual(ID.exposure_field_evidence(lt("ZC", 1.0, 1.0, "CRYPTO")), [])
        r = res(lt("ZCRY", 0.3, 5e6, "CRYPTO", ["MEMES"]))
        self.assertEqual(st(r, "ZCRY"), ID.UNVERIFIED)                         # CRYPTO is no evidence
        # an RWA entry with a check that did not run is no evidence either (stale fields are not trusted)
        stale = dict(lt("ZSTALE", 5.0, 1e5, "RWA"), xcheck="FAILED")
        self.assertEqual(ID.exposure_field_evidence(stale), [])
        self.assertEqual(ID.candidate_evidence("lighter", {"asset_type": "CRYPTO", "asset_categories": ["AI"]}),
                         [["asset_type", "CRYPTO"], ["asset_categories", "AI"]])
        self.assertEqual(ID.candidate_evidence("lighter", {"asset_type": "RWA"}), [])     # authority already

    def adapter(self, answer):
        """dex_lighter() with the market list answered and the token list answered by `answer` (a payload or an
        exception); returns (rows, recorder exposure state, token-list request count)."""
        books = {"order_book_details": [
            {"symbol": "ETH", "market_type": "perp", "status": "active", "mark_price": "4400", "daily_quote_token_volume": 5e8},
            {"symbol": "US10Y", "market_type": "perp", "status": "active", "mark_price": "95.1", "daily_quote_token_volume": 7e3},
            {"symbol": "1000PEPE", "market_type": "perp", "status": "active", "mark_price": "0.012", "daily_quote_token_volume": 1e6}]}
        calls = []

        def fetch(url, body=None, timeout=25):
            if url == sc.LIGHTER_BOOKS:
                return books
            if url == sc.LIGHTER_TOKENLIST:
                calls.append(url)
                if isinstance(answer, Exception):
                    raise answer
                return answer
            raise sc.HttpError(503, "down")
        old = sc.FETCH
        sc.FETCH = fetch
        try:
            sc.V8.begin_universe()
            rows = sc.dex_lighter()
            health = (getattr(sc.V8, "exposure", {}) or {}).get(ID.LIGHTER_TOKENLIST)
        finally:
            sc.FETCH = old
        return rows, health, len(calls)

    def test_adapter_one_bulk_request_and_health(self):
        rows, health, n = self.adapter(TOKENS)
        self.assertEqual(n, 1)                                                 # one request for every market
        self.assertEqual({r["sym"]: (r["xcheck"], r.get("asset_type")) for r in rows},
                         {"ETH": ("OK", "CRYPTO"), "US10Y": ("OK", "RWA"), "1000PEPE": ("OK", "CRYPTO")})
        self.assertEqual(health["state"], "OK")
        for answer, want in ((sc.HttpError(503, "down"), "FAILED"), (sc.HttpError(429, "slow down"), "FAILED"),
                             (sc.HttpError(404, "gone"), "UNAVAILABLE"), (sc.HttpError(403, "no"), "UNAVAILABLE"),
                             (ValueError("bad json"), "MALFORMED"), ({"code": 200}, "MALFORMED"),
                             (ConnectionError("reset"), "FAILED"), (TimeoutError(), "FAILED")):
            rows, health, n = self.adapter(answer)
            self.assertEqual(len(rows), 3, want)                               # the market list never fails with it
            self.assertEqual(n, 1, want)
            self.assertEqual(health["state"], want, answer)
            self.assertTrue(all(r["xcheck"] == want and "asset_type" not in r for r in rows), want)

    def test_failed_check_never_makes_a_market_crypto(self):
        """Section 28 / gate E: whatever the check's failure, a market seen only through it is never verified by the
        ticker list, and an RWA market loses only its tradfi evidence (it becomes UNVERIFIED, not crypto)."""
        for down in ("FAILED", "UNAVAILABLE", "MALFORMED", "NO_ENTRY", "MALFORMED_ENTRY", "NOT_REQUESTED", None):
            r = res(lt("SOL", 220.0, 1e8, xcheck=down))                        # a known-crypto ticker, Lighter only
            self.assertEqual(st(r, "SOL"), ID.UNVERIFIED, down)
            self.assertEqual(r.asset("SOL")["reason"], "EXPOSURE_CHECK_UNAVAILABLE", down)
            r = res(lt("US10Y", 95.1, 7000.0, xcheck=down))
            self.assertEqual(st(r, "US10Y"), ID.UNVERIFIED, down)
            # corroborated by another venue's coherent market, the known-crypto list still verifies the exposure
            r = res(lt("SOL", 220.0, 1e8, xcheck=down), hl("SOL", 220.1, 5e8))
            self.assertEqual(st(r, "SOL"), ID.VERIFIED_CRYPTO, down)
        r = res(lt("SOL", 220.0, 1e8))                                         # the check ran: CRYPTO entry, list
        self.assertEqual(st(r, "SOL"), ID.VERIFIED_CRYPTO)

    def test_registry_records_health_and_coverage(self):
        rec = Recorder()
        rec.begin_universe()
        rec.payload("lighter", "books", {"order_book_details": [
            {"symbol": "US10Y", "market_type": "perp", "status": "active", "mark_price": "95.1",
             "daily_quote_token_volume": 7000.0},
            {"symbol": "NEWMKT", "market_type": "perp", "status": "active", "mark_price": "1.0",
             "daily_quote_token_volume": 100.0}]})
        rec.payload("lighter", "tokenlist", TOKENS)
        rec.exposure_meta(ID.LIGHTER_TOKENLIST, "OK", {"tokens": 7})
        _, idx, _ = ID.lighter_tokenlist_index(TOKENS)
        rows = [dict(row("lighter", "US10Y", "US10Y", 95.1, 7000.0), **ID.lighter_exposure_fields("US10Y", "OK", idx)),
                dict(row("lighter", "NEWMKT", "NEWMKT", 1.0, 100.0), **ID.lighter_exposure_fields("NEWMKT", "OK", idx))]
        rec.universe_rows({"lighter": rows})
        r = ID.resolve({"lighter": rows}, sc.DEXES, LISTS, sc.in_my_dexes)
        rec.identity(r)
        reg = R.build(rec, r.coins, {"lighter": {"ok": True}}, True, 0)
        xm = reg["exposure_metadata"][ID.LIGHTER_TOKENLIST]
        self.assertEqual((xm["state"], xm["markets"], xm["markets_by_check"], xm["markets_without_check"],
                          xm["tradfi_evidence_markets"]),
                         ("OK", 2, {"NO_ENTRY": 1, "OK": 1}, ["lighter:NEWMKT"], ["lighter:US10Y"]))
        c = {x["id"]: x for x in reg["contracts"]}
        self.assertEqual((c["lighter:US10Y"]["vmeta"]["asset_type"], c["lighter:US10Y"]["xcheck"]), ("RWA", "OK"))
        self.assertEqual(c["lighter:NEWMKT"]["xcheck"], "NO_ENTRY")
        a = reg["assets"]["US10Y"]["identity"]
        self.assertEqual((a["state"], a["exposure_checks"]), (ID.VERIFIED_TRADFI,
                                                              [["lighter:US10Y", "LIGHTER_TOKENLIST", "OK"]]))
        counts = R.counts(reg)["exposure_safety"]
        self.assertEqual(counts["exposure_check_unavailable_assets"], ["NEWMKT"])
        self.assertEqual(counts["transitions_vs_previous"], {"UNVERIFIED->VERIFIED_TRADFI": ["US10Y"]})


# --------------------------------------------------------------------------- version, authority, provenance
class VersionAndProvenance(unittest.TestCase):
    def test_config_hash_changed_with_the_rules(self):
        cfg = provenance.identity_config()
        self.assertEqual(cfg["version"], "v8.identity/3")
        self.assertEqual(cfg["extended_crypto_wrapper"], ["Crypto"])
        self.assertEqual(cfg["lighter_tradfi_asset_types"], ["RWA"])
        self.assertEqual(cfg["exposure_checks"], {"lighter": "LIGHTER_TOKENLIST"})
        self.assertNotIn("extended_crypto", cfg)
        self.assertNotEqual(provenance.identity_config_hash(), PHASE4_IDENTITY_CONFIG_HASH)

    def test_v2_authority_files_fail(self):
        tmp = tempfile.mkdtemp(prefix="v8p5")
        try:
            ID.write_authority(tmp, {"BTC": {"identity": ID.VERIFIED_CRYPTO}}, 1000, "gh-7-1")
            self.assertTrue(ID.load_authority(tmp, 1000, "gh-7-1").ok)
            p = os.path.join(tmp, ID.AUTHORITY_FILE)
            with open(p) as fh:
                rec = json.load(fh)
            rec["identity_version"] = "v8.identity/2"
            with open(p, "w") as fh:
                json.dump(rec, fh)
            a = ID.load_authority(tmp, 1000, "gh-7-1")
            self.assertEqual((a.ok, a.why, a.state("BTC")), (False, "OTHER_IDENTITY_VERSION:v8.identity/2", None))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_new_proof_records_v3(self):
        tr = EV.stamp({"id": "X"}, "BTC", ID.Authority.from_states({"BTC": ID.VERIFIED_CRYPTO}, scan_id="gh-9-1"))
        self.assertEqual((tr["identity_version"], EV.qualified(tr)), ("v8.identity/3", True))

    def test_v2_entry_proof_stays_qualified(self):
        """Section 24: no hindsight. A trade entered while VERIFIED_CRYPTO under v8.identity/2 stays historically
        qualified after v8.identity/3 downgrades its coin; only its current actionability is blocked."""
        old = {"id": "GRAM-TSMOM-1", "c": "GRAM", "identity_state_at_entry": ID.VERIFIED_CRYPTO,
               "identity_qualified": True, "identity_version": "v8.identity/2", "identity_scan_id": "gh-37943330492-1",
               "identity_decision": ID.D_CRYPTO}
        self.assertTrue(EV.qualified(old))
        self.assertTrue(SM.trade_qualified(dict(old, coin="GRAM", kind="signal")))
        self.assertEqual(EV.mark_legacy([old]), 0)                             # not re-marked, not rewritten


# --------------------------------------------------------------------------- current gates react to a downgrade
GRAM_LIKE = (ex("GRAMX-USD", "GRAMX", 1.53, 2e6, sub="L1"), hl("GRAMX", 1.531, 5.2e6), aster("GRAMXUSDT", "GRAMX", 1.529, 4e6))


class DowngradeGates(unittest.TestCase):
    """Section 25: a coin v8.identity/3 downgrades (the GRAM shape: Extended Crypto was its only crypto authority)
    stays in its paper lifecycle and stops being actionable at once - quant, dashboard, smart money, Analyzer."""

    @classmethod
    def setUpClass(cls):
        cls.r = res(*GRAM_LIKE, hl("BTC", 121000.0, 2e9))
        cls.auth = EV.universe_authority(cls.r.coins, 1000, "gh-11-1", cls.r.assets)

    def test_downgrade(self):
        self.assertEqual((st(self.r, "GRAMX"), self.r.asset("GRAMX")["previous"]["state"]),
                         (ID.UNVERIFIED, ID.VERIFIED_CRYPTO))
        self.assertEqual(st(self.r, "BTC"), ID.VERIFIED_CRYPTO)

    def test_quant_and_dashboard(self):
        opens = [dict({"id": f"{c}-TSMOM-1", "s": "TSMOM", "c": c, "d": 1, "t_sig": 1, "t_in": 1, "stop_pct": 0.9,
                       "trail_pct": 0.0, "hold_h": 100, "slip": 0.0005, "src": "mexc", "px": 1.0, "res": None},
                      identity_state_at_entry=ID.VERIFIED_CRYPTO, identity_qualified=True,
                      identity_version="v8.identity/2", identity_scan_id="gh-10-1", identity_decision=ID.D_CRYPTO)
                 for c in ("GRAMX", "BTC")]
        act, blk = Q.split_open(opens, self.r.coins, self.auth)
        self.assertEqual([o["c"] for o in act], ["BTC"])
        self.assertEqual([(b["c"], b["identity"], b["identity_reason"], b["actionable"]) for b in blk],
                         [("GRAMX", ID.UNVERIFIED, "IDENTITY_UNVERIFIED", False)])
        self.assertTrue(EV.qualified(blk[0]))                                  # its entry proof is kept
        self.assertEqual(list(D.signals(None, {"open": act + blk}, None, None)), ["BTC"])

    def test_smart_money(self):
        row_ = {"coin": "GRAMX", "side": "long", "signal": True, "info": False, "tested": True, "proven": True}
        out = SM.apply_identity(dict(row_), self.auth)
        self.assertEqual((out["identity"], out["signal"], out["side"], out["identity_block"]["reason"]),
                         (ID.UNVERIFIED, False, None, "IDENTITY_UNVERIFIED"))
        ok = SM.apply_identity(dict(row_, coin="BTC"), self.auth)
        self.assertEqual((ok["identity"], ok["signal"], ok["side"]), (ID.VERIFIED_CRYPTO, True, "long"))


# --------------------------------------------------------------------------- the scheduled-scan gate (section 42)
class ScanGateInvariants(unittest.TestCase):
    """Critical Phase 5 invariants, cheap enough for every scan."""

    def test_crypto_wrapper_plus_tradfi_exposure_is_never_crypto_authorized(self):
        for other in (lt("ZGLD", 4185.0, 1e6, "RWA", ["COMMODITIES"]),
                      dict(aster("ZGLDUSDT", "ZGLD", 4186.0, 1e6), subtypes=["Commodities"])):
            r = res(ex("ZGLD-USD", "ZGLD", 4190.0, 2e6, sub="Commodity"), other)
            self.assertEqual(st(r, "ZGLD"), ID.VERIFIED_TRADFI)
            self.assertFalse(sc.crypto_authorized(r.coins["ZGLD"]))

    def test_wrapper_only_unknown_fails_closed(self):
        r = res(ex("ZWO-USD", "ZWO", 0.5, 9e6))
        self.assertEqual((st(r, "ZWO"), sc.crypto_authorized(r.coins["ZWO"]), ID.discovery_eligible(r.coins["ZWO"])),
                         (ID.UNVERIFIED, False, True))
        r = res(lt("ZWO", 0.5, 9e6, xcheck="FAILED"))
        self.assertFalse(sc.crypto_authorized(r.coins["ZWO"]))

    def test_current_gate_reacts_to_a_downgrade(self):
        r = res(ex("ZDG-USD", "ZDG", 2.0, 2e6), hl("ZDG", 2.01, 5e6))
        auth = EV.universe_authority(r.coins, 0, "gh-1-1", r.assets)
        tr = {"id": "ZDG-TSMOM-1", "s": "TSMOM", "c": "ZDG", "d": 1, "t_sig": 1, "t_in": 1, "stop_pct": 0.9,
              "trail_pct": 0.0, "hold_h": 100, "slip": 0.0005, "src": "mexc", "px": 1.0, "res": None}
        act, blk = Q.split_open([tr], r.coins, auth)
        self.assertEqual((act, [b["identity_reason"] for b in blk]), ([], ["IDENTITY_UNVERIFIED"]))

    def test_entry_proof_stays_historical(self):
        tr = {"identity_state_at_entry": ID.VERIFIED_CRYPTO, "identity_qualified": True,
              "identity_version": "v8.identity/2", "identity_scan_id": "gh-1-1"}
        self.assertTrue(EV.qualified(tr))
        self.assertEqual(EV.current_identity({"t": "ZDG", "tradfi": False, "identity": ID.UNVERIFIED})[1],
                         "IDENTITY_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
