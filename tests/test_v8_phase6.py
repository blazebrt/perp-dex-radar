"""v8 Phase 6: exposure-local positive crypto authority (v8.identity/4).

The repository's known-crypto list is ticker-level knowledge: one crypto asset exists under the ticker. The universe is
exposure-level: one ticker can carry several price-coherent exposures. Since v8.identity/4 the list is bound to at
most one exposure of its ticker:

* deterministic contract evidence first (tradfi, ambiguous, direct crypto) - those exposures are never candidates;
* an exposure blocked by a failed exposure check (Phase 5) and an unpriced exposure are never candidates and never
  take or compete for the binding;
* exactly one candidate left: CRYPTO, TICKER_KNOWN_CRYPTO_BOUND (authority TICKER_LIST);
* more than one: every candidate UNVERIFIED, TICKER_CRYPTO_EXPOSURE_UNBOUND - never AMBIGUOUS, never a winner chosen by
  volume, venue count, open interest, order or majority;
* a candidate beside a direct-crypto exposure: UNVERIFIED (the direct one is the ticker's asset).

Also pinned: the collision matrix of the Phase 6 brief (section 35), ZKNOWN, the QNT / PURR / BB live shapes, the
positive and negative controls, the ticker_authority audit record and its counts (unaccounted 0), the Decision Trace,
the known-crypto list audit, the version (v4; previous v3; v2 and v3 reproducible), the same-scan authority, entry-time
proofs (no hindsight), every current gate reacting to a downgrade, and the fallback universe.

Section 50 of the Phase 6 brief: the ScanGateInvariants class is cheap enough for every scheduled scan.

Run from the repository root:  python -m unittest tests.test_v8_phase6 -v"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "v8"))

import dashboard as D  # noqa: E402
import quant as Q  # noqa: E402
import scanner as sc  # noqa: E402
import smart as SM  # noqa: E402
from test_v8_phase3 import aster, ext, hl, row, var  # noqa: E402
from test_v8_phase5 import NEG_CONTROLS, POS_CONTROLS, ex, lt  # noqa: E402
from v8 import evidence as EV  # noqa: E402
from v8 import identity as ID  # noqa: E402
from v8 import provenance  # noqa: E402
from v8 import registry as R  # noqa: E402

PHASE5_IDENTITY_CONFIG_HASH = "3ceec43ead7a6874427920c3f3412059334288415186931bfea068729ca1968f"
KNOWN = sc.KNOWN_CRYPTO | {"ZKNOWN"}            # the test world's known-crypto list: ZKNOWN is a known crypto ticker
LISTS = ID.Lists(sc.TRADFI, KNOWN, sc.is_fx, sc.TRADFI_NAME)
NODE = shutil.which("node")


def dydx(sym, base, price, vol):
    return row("dydx", sym, base, price, vol)


def para(sym, base, price, vol):
    return row("paradex", sym, base, price, vol)


def res(*rows, lists=LISTS, version=None):
    out = {d: [] for d in sc.DEXES}
    for r in rows:
        out[r["dex"]].append(r)
    if version is not None:
        return ID.resolve_version(version, out, sc.DEXES, lists, sc.in_my_dexes)
    return ID.resolve(out, sc.DEXES, lists, sc.in_my_dexes)


def st(r, t):
    return r.coins[t]["identity"]


def xs(r, t):
    """{exposure id: (class, reason)} of one asset."""
    return {x["id"]: (x["class"], x["reason"]) for x in r.asset(t)["exposures"]}


def ta(r, t):
    return r.asset(t)["ticker_authority"]


def with_direct_crypto():
    """Direct crypto economic evidence on a row marked test_crypto_economic. No source produces it today
    (QUALIFIED_CRYPTO_RULES is empty), so it is simulated, as the Phase 5 true-conflict test does."""
    orig = ID.exposure_field_evidence

    def patched(row_):
        if row_.get("test_crypto_economic"):
            return [(ID.CRYPTO, "TEST_QUALIFIED_CRYPTO", ID.VENUE_METADATA)]
        return orig(row_)
    return mock.patch.object(ID, "exposure_field_evidence", patched)


# ZKNOWN, section 9: exposure A at 0.25 on two venues, exposure B at 80 on a third, no evidence on either
ZA = (hl("ZKNOWN", 0.25, 4e6), var("ZKNOWN", 0.251, 1e6))
ZB = (dydx("ZKNOWN-USD", "ZKNOWN", 80.0, 2e5),)


# --------------------------------------------------------------------------- the rule
class Binding(unittest.TestCase):
    def test_version(self):
        self.assertEqual((ID.VERSION, ID.PREVIOUS_VERSION, ID.RULES, ID.PREVIOUS_RULES),
                         ("v8.identity/4", "v8.identity/3", 4, 3))
        self.assertEqual(ID.QUALIFIED_CRYPTO_RULES, ())                       # no positive rule is added
        self.assertEqual((ID.R_BOUND, ID.R_UNBOUND), ("TICKER_KNOWN_CRYPTO_BOUND", "TICKER_CRYPTO_EXPOSURE_UNBOUND"))

    def test_zknown_two_unlabeled_exposures_are_both_unverified(self):
        """Section 9, the critical test."""
        r = res(*ZA, *ZB)
        a = r.asset("ZKNOWN")
        self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.UNVERIFIED, ID.R_UNBOUND),
                                           "ZKNOWN#2": (ID.UNVERIFIED, ID.R_UNBOUND)})
        self.assertEqual((a["state"], a["decision"], a["authority"]), (ID.UNVERIFIED, ID.D_UNVERIFIED, ID.NONE))
        c = r.coins["ZKNOWN"]
        self.assertFalse(ID.execution_identity_eligible(c))                    # crypto execution NO
        self.assertFalse(sc.crypto_authorized(c))
        self.assertTrue(ID.discovery_eligible(c))                              # discovery YES
        self.assertFalse(c["tradfi"])                                          # unknown is not tradfi
        self.assertNotEqual(a["state"], ID.AMBIGUOUS)                          # no economic evidence conflicts
        self.assertEqual(ta(r, "ZKNOWN"), {
            "ticker": "ZKNOWN", "known_crypto": True, "rules_version": "v8.identity/4",
            "bindable_exposures": ["ZKNOWN#1", "ZKNOWN#2"], "candidate_prices": {"ZKNOWN#1": 0.25, "ZKNOWN#2": 80.0},
            "selected_exposure": None, "result": "UNBOUND_MULTIPLE_CANDIDATES", "excluded": [],
            "direct_crypto_exposures": [], "check_blocked_exposures": [], "tradfi_exposures": [],
            "ambiguous_exposures": [], "unpriced_exposures": [], "statement": "NO UNIQUE EXPOSURE BINDING",
            "effect": ID.UNVERIFIED})
        self.assertIn("unique binding", a["promotion"])
        # v8.identity/3 verified both from the list alone (recorded as `previous`)
        self.assertEqual((a["previous"]["version"], a["previous"]["state"], a["previous"]["reason"]),
                         ("v8.identity/3", ID.VERIFIED_CRYPTO, "TICKER_KNOWN_CRYPTO"))
        # the coin record is the record of its UNVERIFIED exposures (rule 5): the legacy price check keeps the most
        # traded market's exposure, exactly as before
        self.assertEqual(sorted(c["venues"]), ["hyperliquid", "variational"])

    def test_nothing_chooses_between_candidates(self):
        """Sections 15-16: no volume, venue count, open interest, order or majority decides. Every permutation of the
        volumes, the open interests and the market-list order gives the same result."""
        base = [hl("ZKNOWN", 0.25, 4e6), var("ZKNOWN", 0.251, 1e6), aster("ZKNOWNUSDT", "ZKNOWN", 0.249, 3e6),
                dydx("ZKNOWN-USD", "ZKNOWN", 80.0, 2e5)]
        vols = (5e2, 4e6, 1e7, 3e3)
        for perm in itertools.permutations(vols):
            rows_ = [dict(r_, vol=v, oi=v / 10) for r_, v in zip(base, perm)]
            for order in (rows_, list(reversed(rows_))):
                r = res(*order)
                self.assertEqual(st(r, "ZKNOWN"), ID.UNVERIFIED, perm)
                self.assertEqual(ta(r, "ZKNOWN")["result"], ID.T_UNBOUND_MULTI, perm)
                self.assertIsNone(ta(r, "ZKNOWN")["selected_exposure"])
        # three crypto-looking venues against one: still no majority vote
        r = res(*base[:3], dydx("ZKNOWN-USD", "ZKNOWN", 80.0, 2e5))
        self.assertEqual(st(r, "ZKNOWN"), ID.UNVERIFIED)

    def test_same_price_multi_venue_is_one_candidate(self):
        """Section 36: three venues within the 20% tolerance are one exposure and one candidate."""
        r = res(hl("ZKNOWN", 0.25, 4e6), var("ZKNOWN", 0.26, 1e6), aster("ZKNOWNUSDT", "ZKNOWN", 0.24, 2e6),
                dydx("ZKNOWN-USD", "ZKNOWN", 0.252, 1e5))
        self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.CRYPTO, ID.R_BOUND)})
        a = r.asset("ZKNOWN")
        self.assertEqual((a["state"], a["authority"], a["reason"]), (ID.VERIFIED_CRYPTO, ID.TICKER_LIST, ID.R_BOUND))
        self.assertEqual((ta(r, "ZKNOWN")["bindable_exposures"], ta(r, "ZKNOWN")["selected_exposure"],
                          ta(r, "ZKNOWN")["result"]), (["ZKNOWN#1"], "ZKNOWN#1", "BOUND"))
        self.assertEqual(sorted(r.coins["ZKNOWN"]["venues"]), ["aster", "dydx", "hyperliquid", "variational"])

    def test_list_alone_is_still_ticker_level_input(self):
        """The ticker-level assertion stays in the evidence (the input); the binding is the separate result."""
        r = res(hl("SOL", 150.0, 5e6))
        self.assertIn(["ticker:SOL", ID.CRYPTO, "TICKER_KNOWN_CRYPTO", ID.TICKER_LIST], r.asset("SOL")["evidence"])
        self.assertEqual(r.asset("SOL")["reason"], ID.R_BOUND)
        self.assertIsNone(res(hl("ZNOTLISTED", 1.0, 5e6)).asset("ZNOTLISTED")["ticker_authority"])


# --------------------------------------------------------------------------- the collision matrix (section 35)
class CollisionMatrix(unittest.TestCase):
    def test_01_one_priced_unlabeled_exposure_is_crypto(self):
        r = res(*ZA)
        self.assertEqual((st(r, "ZKNOWN"), xs(r, "ZKNOWN")), (ID.VERIFIED_CRYPTO, {"ZKNOWN#1": (ID.CRYPTO, ID.R_BOUND)}))

    def test_02_two_price_separated_unlabeled_exposures_are_unverified(self):
        r = res(*ZA, *ZB)
        self.assertEqual(st(r, "ZKNOWN"), ID.UNVERIFIED)
        self.assertEqual({c for c, _ in xs(r, "ZKNOWN").values()}, {ID.UNVERIFIED})

    def test_03_one_unlabeled_plus_one_tradfi_binds_the_unlabeled(self):
        """Section 10: the generic QNT / PURR / BB architecture, with each deterministic tradfi source."""
        for neg in (ext("ZKNOWN-USD", "ZKNOWN", 125.0, 3e6, cat="RWA"),
                    lt("ZKNOWN", 125.0, 3e6, "RWA", ["STOCK"]),
                    dict(aster("ZKNOWNUSDT", "ZKNOWN", 125.0, 3e6), subtypes=["STOCK"]),
                    aster("ZKNOWNUSDT", "ZKNOWN", 125.0, 3e6, ut="EQUITY")):
            r = res(hl("ZKNOWN", 0.5, 1e6), neg)
            self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.TRADFI, "TRADFI_CONTRACT_EVIDENCE"),
                                               "ZKNOWN#2": (ID.CRYPTO, ID.R_BOUND)}, neg["dex"])
            a = r.asset("ZKNOWN")
            self.assertEqual((a["state"], a["decision"]), (ID.VERIFIED_CRYPTO, ID.D_SELECTED), neg["dex"])
            self.assertEqual(list(r.coins["ZKNOWN"]["venues"]), ["hyperliquid"])      # the stock stays out
            self.assertEqual((ta(r, "ZKNOWN")["selected_exposure"], ta(r, "ZKNOWN")["excluded"]),
                             ("ZKNOWN#2", [["ZKNOWN#1", "TRADFI_EVIDENCE"]]))
            self.assertEqual(ta(r, "ZKNOWN")["tradfi_exposures"], ["ZKNOWN#1"])

    def test_04_two_unlabeled_plus_one_tradfi_are_unverified(self):
        """Section 11: after the tradfi exposure is removed two candidates are left; do not choose."""
        r = res(hl("ZKNOWN", 0.5, 1e6), dydx("ZKNOWN-USD", "ZKNOWN", 30.0, 5e5),
                ext("ZKNOWN-USD", "ZKNOWN", 125.0, 3e6, cat="RWA"))
        self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.TRADFI, "TRADFI_CONTRACT_EVIDENCE"),
                                           "ZKNOWN#2": (ID.UNVERIFIED, ID.R_UNBOUND),
                                           "ZKNOWN#3": (ID.UNVERIFIED, ID.R_UNBOUND)})
        self.assertEqual(st(r, "ZKNOWN"), ID.UNVERIFIED)
        self.assertFalse(r.coins["ZKNOWN"]["tradfi"])
        self.assertEqual(ta(r, "ZKNOWN")["result"], ID.T_UNBOUND_MULTI)

    def test_05_failed_check_never_consumes_the_binding(self):
        """Section 12: a Lighter-only exposure whose token-list check failed stays EXPOSURE_CHECK_UNAVAILABLE and is
        not a candidate; the one normal candidate binds."""
        for xc in ("FAILED", "UNAVAILABLE", "MALFORMED", "NO_ENTRY", "MALFORMED_ENTRY", None):
            r = res(hl("ZKNOWN", 0.5, 1e6), aster("ZKNOWNUSDT", "ZKNOWN", 0.51, 1e6), lt("ZKNOWN", 80.0, 9e6, xcheck=xc))
            self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.UNVERIFIED, ID.R_CHECK_UNAVAILABLE),
                                               "ZKNOWN#2": (ID.CRYPTO, ID.R_BOUND)}, xc)
            self.assertEqual(st(r, "ZKNOWN"), ID.VERIFIED_CRYPTO, xc)
            t = ta(r, "ZKNOWN")
            self.assertEqual((t["bindable_exposures"], t["check_blocked_exposures"], t["excluded"]),
                             (["ZKNOWN#2"], ["ZKNOWN#1"], [["ZKNOWN#1", ID.R_CHECK_UNAVAILABLE]]), xc)
            self.assertEqual(sorted(r.coins["ZKNOWN"]["venues"]), ["aster", "hyperliquid"])   # never merged in
        # section 13: two failed-check exposures are not turned into candidates; A still binds alone
        r = res(hl("ZKNOWN", 0.5, 1e6), lt("ZKNOWN", 80.0, 9e6, xcheck="FAILED"),
                lt("1000ZKNOWN", 300000.0, 2e6, xcheck="FAILED"))
        self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.UNVERIFIED, ID.R_CHECK_UNAVAILABLE),
                                           "ZKNOWN#2": (ID.UNVERIFIED, ID.R_CHECK_UNAVAILABLE),
                                           "ZKNOWN#3": (ID.CRYPTO, ID.R_BOUND)})
        # a failed check never acquires crypto on its own either
        r = res(lt("ZKNOWN", 80.0, 9e6, xcheck="FAILED"))
        self.assertEqual((st(r, "ZKNOWN"), ta(r, "ZKNOWN")["result"]), (ID.UNVERIFIED, ID.T_NO_CANDIDATE))
        # a checked Lighter market in a multi-venue exposure is a normal member (Phase 5: not all members unchecked)
        r = res(hl("ZKNOWN", 0.5, 1e6), lt("ZKNOWN", 0.501, 9e6, xcheck="FAILED"))
        self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.CRYPTO, ID.R_BOUND)})

    def test_06_two_normal_candidates_plus_failed_check_are_unbound(self):
        r = res(hl("ZKNOWN", 0.5, 1e6), dydx("ZKNOWN-USD", "ZKNOWN", 30.0, 5e5), lt("ZKNOWN", 80.0, 9e6, xcheck="FAILED"))
        self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.UNVERIFIED, ID.R_CHECK_UNAVAILABLE),
                                           "ZKNOWN#2": (ID.UNVERIFIED, ID.R_UNBOUND),
                                           "ZKNOWN#3": (ID.UNVERIFIED, ID.R_UNBOUND)})
        self.assertEqual((st(r, "ZKNOWN"), ta(r, "ZKNOWN")["result"]), (ID.UNVERIFIED, ID.T_UNBOUND_MULTI))

    def test_07_direct_crypto_plus_extra_unlabeled_is_direct_only(self):
        """Section 14: direct qualified crypto evidence needs no binding, and the list cannot verify a second,
        price-separated exposure beside it."""
        with with_direct_crypto():
            r = res(dict(lt("ZKNOWN", 0.5, 1e6), test_crypto_economic=True), dydx("ZKNOWN-USD", "ZKNOWN", 30.0, 5e5))
            self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.CRYPTO, "CRYPTO_VENUE_METADATA"),
                                               "ZKNOWN#2": (ID.UNVERIFIED, ID.R_UNBOUND)})
            self.assertEqual(st(r, "ZKNOWN"), ID.VERIFIED_CRYPTO)
            self.assertEqual(list(r.coins["ZKNOWN"]["venues"]), ["lighter"])       # the direct exposure only
            t = ta(r, "ZKNOWN")
            self.assertEqual((t["result"], t["direct_crypto_exposures"], t["bindable_exposures"], t["selected_exposure"]),
                             (ID.T_UNBOUND_DIRECT, ["ZKNOWN#1"], ["ZKNOWN#2"], None))
            self.assertEqual(r.asset("ZKNOWN")["excluded_unverified"], ["ZKNOWN#2"])
            # direct evidence alone: nothing to bind
            r = res(dict(lt("ZKNOWN", 0.5, 1e6), test_crypto_economic=True))
            self.assertEqual((st(r, "ZKNOWN"), ta(r, "ZKNOWN")["result"]), (ID.VERIFIED_CRYPTO, ID.T_NO_CANDIDATE))

    def test_08_only_tradfi_exposures_give_no_crypto(self):
        r = res(ext("ZKNOWN-USD", "ZKNOWN", 125.0, 3e6, cat="RWA"), lt("ZKNOWN", 40.0, 1e6, "RWA"))
        self.assertEqual(st(r, "ZKNOWN"), ID.VERIFIED_TRADFI)
        self.assertTrue(r.coins["ZKNOWN"]["tradfi"])
        self.assertEqual((ta(r, "ZKNOWN")["result"], ta(r, "ZKNOWN")["bindable_exposures"]), (ID.T_NO_CANDIDATE, []))

    def test_09_unpriced_only_is_unverified(self):
        """Section 17: an unpriced contract cannot bind the list (v8.identity/3 verified it)."""
        r = res(hl("ZKNOWN", None, 1e6), var("ZKNOWN", None, 5e5))
        self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.UNVERIFIED, ID.R_UNPRICED)})
        self.assertEqual((st(r, "ZKNOWN"), ta(r, "ZKNOWN")["result"], ta(r, "ZKNOWN")["unpriced_exposures"]),
                         (ID.UNVERIFIED, ID.T_NO_CANDIDATE, ["ZKNOWN#1"]))
        self.assertEqual(r.asset("ZKNOWN")["previous"]["state"], ID.VERIFIED_CRYPTO)
        # an unpriced contract beside a priced exposure never redefines it and is never a candidate
        r = res(hl("ZKNOWN", 0.5, 1e6), dydx("ZKNOWN-USD", "ZKNOWN", None, 1e3))
        self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.CRYPTO, ID.R_BOUND),
                                           "ZKNOWN#u1": (ID.UNVERIFIED, ID.R_UNPRICED)})
        self.assertEqual(ta(r, "ZKNOWN")["excluded"], [["ZKNOWN#u1", "UNPRICED"]])

    def test_10_true_economic_conflict_stays_ambiguous(self):
        with with_direct_crypto():
            r = res(dict(lt("ZKNOWN", 10.0, 1e6), test_crypto_economic=True),
                    dict(aster("ZKNOWNUSDT", "ZKNOWN", 10.02, 5e5), subtypes=["STOCK"]))
            self.assertEqual((st(r, "ZKNOWN"), xs(r, "ZKNOWN")),
                             (ID.AMBIGUOUS, {"ZKNOWN#1": (ID.AMBIGUOUS, "CONFLICTING_CONTRACT_EVIDENCE")}))
            self.assertEqual(ta(r, "ZKNOWN")["excluded"], [["ZKNOWN#1", "AMBIGUOUS_EVIDENCE"]])
        # an ambiguous exposure is never a candidate; the other one binds
        r = res(ext("ZKNOWN-USD", "ZKNOWN", 2.0, 5e5, cat="L1"), hl("ZKNOWN", 40.0, 1e6))
        self.assertEqual(xs(r, "ZKNOWN"), {"ZKNOWN#1": (ID.CRYPTO, ID.R_BOUND),
                                           "ZKNOWN#2": (ID.AMBIGUOUS, "AMBIGUOUS_CONTRACT_EVIDENCE")})

    def test_11_qnt(self):
        r = res(var("QNT", 242.78, 3e5), aster("QNTUSDT", "QNT", 243.55, 2e6), lt("QNT", 243.45, 5e4, "CRYPTO", ["NEW"]),
                ext("QNT-USD", "QNT", 41.37, 1.6e5, cat="RWA"), lists=ID.Lists(sc.TRADFI, sc.KNOWN_CRYPTO, sc.is_fx,
                                                                              sc.TRADFI_NAME))
        self.assertEqual(xs(r, "QNT"), {"QNT#1": (ID.CRYPTO, ID.R_BOUND), "QNT#2": (ID.TRADFI, "TRADFI_CONTRACT_EVIDENCE")})
        self.assertEqual((st(r, "QNT"), sorted(r.coins["QNT"]["venues"])), (ID.VERIFIED_CRYPTO,
                                                                            ["aster", "lighter", "variational"]))
        self.assertEqual((ta(r, "QNT")["result"], ta(r, "QNT")["selected_exposure"]), ("BOUND", "QNT#1"))

    def test_12_purr(self):
        r = res(hl("PURR", 0.112, 2e6), ext("PURR-USD", "PURR", 11.11, 2.6e4, cat="RWA"))
        self.assertEqual(xs(r, "PURR"), {"PURR#1": (ID.CRYPTO, ID.R_BOUND),
                                         "PURR#2": (ID.TRADFI, "TRADFI_CONTRACT_EVIDENCE")})
        self.assertEqual((st(r, "PURR"), list(r.coins["PURR"]["venues"])), (ID.VERIFIED_CRYPTO, ["hyperliquid"]))

    def test_13_bb(self):
        """BounceBit (crypto) and BlackBerry (stock: Lighter token-list RWA, Extended RWA) share the ticker. The
        BlackBerry exposure is the more traded one: a volume heuristic would have picked it."""
        bb = (row("variational", "BBIT", "BBIT", 0.00896, 4e3), aster("BBUSDT", "BB", 0.00899, 5e3),
              lt("BB", 8.886, 5e4, "RWA", ["STOCK"]), ext("BB-USD", "BB", 8.871, 1.7e4, cat="RWA"))
        r = res(*bb)
        self.assertEqual(xs(r, "BB"), {"BB#1": (ID.TRADFI, "TRADFI_CONTRACT_EVIDENCE"), "BB#2": (ID.CRYPTO, ID.R_BOUND)})
        self.assertEqual((st(r, "BB"), sorted(r.coins["BB"]["venues"])), (ID.VERIFIED_CRYPTO, ["aster", "variational"]))
        # an Extended outage and a token-list outage together: the BlackBerry market is blocked, BounceBit still binds
        r = res(bb[0], bb[1], lt("BB", 8.886, 5e4, xcheck="FAILED"))
        self.assertEqual(xs(r, "BB"), {"BB#1": (ID.UNVERIFIED, ID.R_CHECK_UNAVAILABLE), "BB#2": (ID.CRYPTO, ID.R_BOUND)})
        # without any negative evidence on the BlackBerry exposure the list cannot choose: fail closed, never by volume
        r = res(bb[0], bb[1], dydx("BB-USD", "BB", 8.88, 5e4))
        self.assertEqual((st(r, "BB"), ta(r, "BB")["result"]), (ID.UNVERIFIED, ID.T_UNBOUND_MULTI))


# --------------------------------------------------------------------------- controls
class Controls(unittest.TestCase):
    def test_positive_controls_bind_their_one_exposure(self):
        px = {"BTC": 82000.0, "ETH": 3100.0, "SOL": 150.0}
        for t, p in px.items():
            r = res(hl(t, p, 3e9), var(t, p * 1.001, 1e9), aster(f"{t}USDT", t, p * 0.999, 2e9),
                    lt(t, p * 1.0005, 5e8), ex(f"{t}-USD", t, p, 1e8), dydx(f"{t}-USD", t, p, 1e8))
            self.assertEqual((st(r, t), xs(r, t), ta(r, t)["result"]),
                             (ID.VERIFIED_CRYPTO, {f"{t}#1": (ID.CRYPTO, ID.R_BOUND)}, "BOUND"), t)
            self.assertTrue(sc.crypto_authorized(r.coins[t]), t)
        self.assertTrue(set(POS_CONTROLS) <= sc.KNOWN_CRYPTO)

    def test_negative_controls_never_acquire_crypto(self):
        self.assertFalse(set(NEG_CONTROLS) & sc.KNOWN_CRYPTO)
        for t in NEG_CONTROLS:
            r = res(hl(t, 100.0, 1e6), ex(f"{t}-USD", t, 100.2, 1e6), aster(f"{t}USDT", t, 99.9, 1e6))
            self.assertNotEqual(st(r, t), ID.VERIFIED_CRYPTO, t)
            self.assertFalse(sc.crypto_authorized(r.coins[t]), t)
            self.assertIsNone(r.asset(t)["ticker_authority"], t)
        # nothing in v8.identity names a control ticker or the ZKNOWN test ticker
        with open(os.path.join(ROOT, "v8", "identity.py")) as fh:
            src = fh.read()
        for t in NEG_CONTROLS + ("QNT", "PURR", "BB", "ZKNOWN"):
            self.assertNotIn(f'"{t}"', src, t)


# --------------------------------------------------------------------------- audit, trace, counts
def _assets(r):
    """The registry's asset identity blocks of a resolution (what R.asset_summary writes for each coin)."""
    return {t: {"identity": R._identity_block(a, r.coins.get(t)), "contracts": []} for t, a in r.assets.items()}


class Audit(unittest.TestCase):
    def test_decision_trace_explains_no_unique_binding(self):
        tr = res(*ZA, *ZB).asset("ZKNOWN")["exposure_trace"]
        b = tr["binding"]
        self.assertEqual((b["input"], b["candidates"], b["result"], b["selected"], b["effect"]),
                         ("KNOWN_CRYPTO ticker = true", ["ZKNOWN#1", "ZKNOWN#2"], "NO UNIQUE EXPOSURE BINDING", None,
                          ID.UNVERIFIED))
        self.assertIn("ZKNOWN#1: no economic evidence either way (candidate)", b["rules"])
        self.assertIn("ZKNOWN#2: no economic evidence either way (candidate)", b["rules"])
        self.assertIn("2 candidates are price-separated; ticker-level identity cannot distinguish them", b["rules"])
        self.assertEqual((tr["final"], tr["crypto_execution"]), (ID.UNVERIFIED, "BLOCKED"))
        b = res(hl("QNT", 243.0, 2e6), ext("QNT-USD", "QNT", 41.0, 1e5, cat="RWA")).asset("QNT")["exposure_trace"]["binding"]
        self.assertEqual((b["result"], b["selected"]), ("UNIQUE EXPOSURE BINDING", "QNT#1"))
        self.assertIn("QNT#2: excluded (TRADFI_EVIDENCE)", b["rules"])
        self.assertIsNone(res(hl("ZNOPE", 1.0, 1e6)).asset("ZNOPE")["exposure_trace"]["binding"])

    def test_registry_counts_account_for_every_candidate(self):
        rows_by_dex = {d: [] for d in sc.DEXES}
        for r_ in (*ZA, *ZB,                                                  # unbound: 2 candidates
                   hl("QNT", 243.0, 2e6), ext("QNT-USD", "QNT", 41.0, 1e5, cat="RWA"),   # bound + tradfi collision
                   hl("SOL", 150.0, 5e6), var("SOL", 150.1, 1e6),             # bound
                   hl("ETH", 3100.0, 5e6), lt("ETH", 80.0, 1e6, xcheck="FAILED"),          # bound + blocked
                   lt("BTC", 82000.0, 1e6, xcheck="FAILED"),                  # no candidate (blocked only)
                   hl("ZNOPE", 1.0, 1e6)):                                    # not on the list
            rows_by_dex[r_["dex"]].append(r_)
        r = ID.resolve(rows_by_dex, sc.DEXES, LISTS, sc.in_my_dexes)
        assets = _assets(r)
        self.assertEqual(assets["ZKNOWN"]["identity"]["ticker_authority"]["result"], ID.T_UNBOUND_MULTI)
        c = {"ticker_authority": R.ticker_authority_counts(assets), "exposure_safety": R.exposure_counts(assets, []),
             "known_crypto_list": R.known_crypto_list_audit(assets, r.known_crypto)}
        t = c["ticker_authority"]
        self.assertEqual((t["known_crypto_assets"], t["ticker_crypto_bindings"], t["ticker_crypto_unbound_assets"],
                          t["ticker_crypto_unbound_exposures"], t["ticker_crypto_no_bindable_exposure"]),
                         (5, 3, 1, 2, 1))
        self.assertEqual((t["ticker_crypto_blocked_by_exposure_check"], t["ticker_crypto_with_tradfi_collision"],
                          t["ticker_crypto_with_direct_crypto_evidence"]), (["BTC", "ETH"], ["QNT"], []))
        self.assertEqual(t["unbound"], {"ZKNOWN": ["ZKNOWN#1", "ZKNOWN#2"]})
        self.assertEqual(t["by_result"], {"BOUND": 3, "UNBOUND_MULTIPLE_CANDIDATES": 1,
                                          "UNBOUND_DIRECT_CRYPTO_EVIDENCE": 0, "NO_BINDABLE_EXPOSURE": 1})
        self.assertEqual((t["binding_candidates"], t["unaccounted"]), (5, 0))
        self.assertEqual(sorted(t["multi_exposure"]), ["ETH", "QNT", "ZKNOWN"])
        # the before/after against v8.identity/3 on the same contracts
        es = c["exposure_safety"]
        self.assertEqual((es["previous_version"], es["transitions_vs_previous"]),
                         ("v8.identity/3", {"VERIFIED_CRYPTO->UNVERIFIED": ["ZKNOWN"]}))     # BTC: blocked under /3 too
        # the known-crypto list audit (observability only)
        k = c["known_crypto_list"]
        self.assertEqual((k["entries"], k["in_live_universe"], k["one_priced_exposure"]), (len(KNOWN), 5, 2))
        self.assertEqual((k["multiple_priced_exposures"], k["unpriced_only"], k["all_live_exposures_tradfi"]),
                         (["ETH", "QNT", "ZKNOWN"], [], []))
        self.assertEqual(len(k["no_live_market"]), len(KNOWN) - 5)

    def test_v4_previous_v3_and_older_versions_replay(self):
        """Section 22/48: production resolves v4 with v3 as `previous`; v2, v3 and v4 replay by their own rules."""
        rows_ = (*ZA, *ZB, ex("ZW-USD", "ZW", 1.0, 1e6))
        v4 = res(*rows_)
        v3 = res(*rows_, version="v8.identity/3")
        v2 = res(*rows_, version="v8.identity/2")
        self.assertEqual((st(v4, "ZKNOWN"), st(v3, "ZKNOWN"), st(v2, "ZKNOWN")),
                         (ID.UNVERIFIED, ID.VERIFIED_CRYPTO, ID.VERIFIED_CRYPTO))
        self.assertEqual((st(v4, "ZW"), st(v3, "ZW"), st(v2, "ZW")),           # the Phase 5 change, untouched
                         (ID.UNVERIFIED, ID.UNVERIFIED, ID.VERIFIED_CRYPTO))
        for t in ("ZKNOWN", "ZW"):
            p = v4.asset(t)["previous"]
            self.assertEqual((p["version"], p["state"], p["reason"]), ("v8.identity/3", st(v3, t), v3.asset(t)["reason"]))
        self.assertIsNone(v3.asset("ZKNOWN")["ticker_authority"])               # no binding before /4
        self.assertEqual(xs(v3, "ZKNOWN"), {"ZKNOWN#1": (ID.CRYPTO, "TICKER_KNOWN_CRYPTO"),
                                            "ZKNOWN#2": (ID.CRYPTO, "TICKER_KNOWN_CRYPTO")})

    def test_census_tool_model2_matches_the_resolver(self):
        """The Stage A tool computes model 2 independently from the v8.identity/3 exposure classes; on every matrix
        shape it must give exactly what v8.identity/4 decides."""
        import ticker_binding as TB
        shapes = [ZA, ZA + ZB, (hl("ZKNOWN", 0.5, 1e6), ext("ZKNOWN-USD", "ZKNOWN", 125.0, 3e6, cat="RWA")),
                  (hl("ZKNOWN", 0.5, 1e6), dydx("ZKNOWN-USD", "ZKNOWN", 30.0, 5e5),
                   ext("ZKNOWN-USD", "ZKNOWN", 125.0, 3e6, cat="RWA")),
                  (hl("ZKNOWN", 0.5, 1e6), lt("ZKNOWN", 80.0, 9e6, xcheck="FAILED")),
                  (hl("ZKNOWN", 0.5, 1e6), dydx("ZKNOWN-USD", "ZKNOWN", 30.0, 5e5), lt("ZKNOWN", 80.0, 9e6, xcheck="FAILED")),
                  (hl("ZKNOWN", None, 1e6),), (lt("ZKNOWN", 40.0, 1e6, "RWA"),)]
        with mock.patch.object(sc, "KNOWN_CRYPTO", KNOWN):
            for rows_ in shapes:
                by = {d: [] for d in sc.DEXES}
                for r_ in rows_:
                    by[r_["dex"]].append(dict(r_))
                v3 = TB.resolve(by, 3)
                c = TB.census_ticker("ZKNOWN", v3.assets["ZKNOWN"], TB.exposure_details(v3, by)["ZKNOWN"])
                result, sel, changes = TB.model2(c)
                v4 = TB.resolve(by, 4)
                want = {g["id"]: changes.get(g["id"], (g["class"], g["reason"])) for g in v3.assets["ZKNOWN"]["exposures"]}
                self.assertEqual(xs(v4, "ZKNOWN"), want, [r_["dex"] for r_ in rows_])
                self.assertEqual(v4.assets["ZKNOWN"]["state"], TB.projected_state(v3.assets["ZKNOWN"], changes))
                self.assertEqual((ta(v4, "ZKNOWN")["result"], ta(v4, "ZKNOWN")["selected_exposure"]), (result, sel))


# --------------------------------------------------------------------------- version, authority, entry proof
class VersionAndProvenance(unittest.TestCase):
    def test_config_hash_changed(self):
        cfg = provenance.identity_config()
        self.assertEqual((cfg["version"], cfg["rules"], cfg["previous_version"]), ("v8.identity/4", 4, "v8.identity/3"))
        self.assertEqual(cfg["ticker_binding"]["max_bound_exposures"], 1)
        self.assertNotEqual(provenance.identity_config_hash(), PHASE5_IDENTITY_CONFIG_HASH)
        self.assertEqual(cfg["known_crypto"], sorted(sc.KNOWN_CRYPTO))         # the list itself is unchanged

    def test_v3_authority_file_fails_a_v4_consumer(self):
        tmp = tempfile.mkdtemp(prefix="v8p6")
        try:
            ID.write_authority(tmp, {"BTC": {"identity": ID.VERIFIED_CRYPTO}}, 1000, "gh-7-1")
            a = ID.load_authority(tmp, 1000, "gh-7-1")
            self.assertEqual((a.ok, a.version, a.state("BTC")), (True, "v8.identity/4", ID.VERIFIED_CRYPTO))
            p = os.path.join(tmp, ID.AUTHORITY_FILE)
            for old in ("v8.identity/3", "v8.identity/2"):
                with open(p) as fh:
                    rec = json.load(fh)
                rec["identity_version"] = old
                with open(p, "w") as fh:
                    json.dump(rec, fh)
                a = ID.load_authority(tmp, 1000, "gh-7-1")
                self.assertEqual((a.ok, a.why, a.state("BTC")), (False, f"OTHER_IDENTITY_VERSION:{old}", None))
                row_ = SM.apply_identity({"coin": "BTC", "side": "long", "signal": True, "info": False}, a)
                self.assertFalse(row_["signal"])                               # a stale v3 file qualifies nothing
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_entry_proofs(self):
        """Sections 23, 41-43: new entries stamp v4; v2 and v3 proofs stay qualified (no hindsight)."""
        tr = EV.stamp({"id": "X"}, "BTC", ID.Authority.from_states({"BTC": ID.VERIFIED_CRYPTO}, scan_id="gh-9-1"))
        self.assertEqual((tr["identity_version"], EV.qualified(tr)), ("v8.identity/4", True))
        for old in ("v8.identity/2", "v8.identity/3"):
            proof = {"id": "ZKNOWN-TSMOM-1", "c": "ZKNOWN", "identity_state_at_entry": ID.VERIFIED_CRYPTO,
                     "identity_qualified": True, "identity_version": old, "identity_scan_id": "gh-38021619992-1",
                     "identity_decision": ID.D_CRYPTO}
            self.assertTrue(EV.qualified(proof), old)
            self.assertTrue(SM.trade_qualified(dict(proof, coin="ZKNOWN", kind="signal")), old)
            self.assertEqual(EV.mark_legacy([proof]), 0)                       # not re-marked, not rewritten


# --------------------------------------------------------------------------- current gates react to a downgrade
QUANT_TRADE = {"s": "TSMOM", "d": 1, "t_sig": 1, "t_in": 1, "stop_pct": 0.9, "trail_pct": 0.0, "hold_h": 10 ** 7,
               "slip": 0.0005, "src": "mexc", "px": 1.0, "res": None}


class DowngradeGates(unittest.TestCase):
    """Sections 24, 40-43: a coin v8.identity/4 downgrades (ZKNOWN: two candidates) stays in its paper lifecycle with
    its v3 entry proof and stops being actionable at once - radar, quant, swing/day, smart money, dashboard, Analyzer."""

    @classmethod
    def setUpClass(cls):
        cls.r = res(*ZA, *ZB, hl("BTC", 82000.0, 3e9))
        cls.auth = EV.universe_authority(cls.r.coins, 1000, "gh-11-1", cls.r.assets)
        cls.opens = [dict(QUANT_TRADE, id=f"{c}-TSMOM-1", c=c, identity_state_at_entry=ID.VERIFIED_CRYPTO,
                          identity_qualified=True, identity_version="v8.identity/3", identity_scan_id="gh-10-1",
                          identity_decision=ID.D_CRYPTO) for c in ("ZKNOWN", "BTC")]

    def test_radar_swing_day(self):
        self.assertFalse(sc.crypto_authorized(self.r.coins["ZKNOWN"]))         # radar, quant, picks all gate on it
        self.assertTrue(sc.crypto_authorized(self.r.coins["BTC"]))
        crypto = {t: c for t, c in self.r.coins.items() if sc.crypto_authorized(c)}
        self.assertEqual(sorted(crypto), ["BTC"])

    def test_quant_dashboard_and_analyzer(self):
        act, blk = Q.split_open(self.opens, self.r.coins, self.auth)
        self.assertEqual([o["c"] for o in act], ["BTC"])
        self.assertEqual([(b["c"], b["identity"], b["identity_reason"], b["actionable"]) for b in blk],
                         [("ZKNOWN", ID.UNVERIFIED, "IDENTITY_UNVERIFIED", False)])
        self.assertTrue(EV.qualified(blk[0]))                                  # the v3 entry proof is kept
        self.assertEqual(blk[0]["identity_version"], "v8.identity/3")
        self.assertEqual(list(D.signals(None, {"open": act + blk}, None, None)), ["BTC"])
        if not NODE:
            self.skipTest("node is not installed")
        tmp = tempfile.mkdtemp(prefix="v8p6a")
        try:
            qp = os.path.join(tmp, "quant.json")
            with open(qp, "w") as fh:
                json.dump({"open": act, "blocked_open": blk, "strategies": {}}, fh)
            script = ("const TA=require(process.argv[1]);const fs=require('fs');"
                      "const quant=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
                      "const r=TA.testedSignals('ZKNOWN',{quant});"
                      "console.log(JSON.stringify({coins:TA.signalCoins({quant},2).map(x=>x.coin),"
                      "signals:r.signals.length,notes:r.notes.map(n=>n.text)}));")
            out = subprocess.run([NODE, "-e", script, os.path.join(ROOT, "analyze.js"), qp], capture_output=True,
                                 text=True, timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr[-1000:])
            got = json.loads(out.stdout)
            self.assertNotIn("ZKNOWN", got["coins"])
            self.assertEqual(got["signals"], 0)
            self.assertTrue(any("ZKNOWN is not currently verified as crypto (UNVERIFIED)" in n for n in got["notes"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_smart_money_same_scan(self):
        row_ = {"coin": "ZKNOWN", "side": "long", "signal": True, "info": False, "tested": True, "proven": True}
        out = SM.apply_identity(dict(row_), self.auth)
        self.assertEqual((out["identity"], out["signal"], out["side"], out["identity_block"]["reason"]),
                         (ID.UNVERIFIED, False, None, "IDENTITY_UNVERIFIED"))
        ok = SM.apply_identity(dict(row_, coin="BTC"), self.auth)
        self.assertEqual((ok["identity"], ok["signal"]), (ID.VERIFIED_CRYPTO, True))
        self.assertEqual(self.auth.version, "v8.identity/4")


# --------------------------------------------------------------------------- fallback universe (section 44)
class Fallback(unittest.TestCase):
    def _build(self, fetchers):
        with mock.patch.dict(sc.DEX_FETCHERS, fetchers), mock.patch.object(sc, "KNOWN_CRYPTO", KNOWN), \
                mock.patch.object(sc, "FALLBACK_CRYPTO", sorted(KNOWN)):
            return sc.build_universe()

    def test_partly_degraded_scan_never_bypasses_the_binding(self):
        def fail():
            raise RuntimeError("venue down")
        fetchers = {d: fail for d in sc.DEXES}
        fetchers["hyperliquid"] = lambda: [hl("ZKNOWN", 0.25, 4e6), hl("BTC", 82000.0, 3e9)]
        fetchers["dydx"] = lambda: [dydx("ZKNOWN-USD", "ZKNOWN", 80.0, 2e5)]
        coins, status, ok = self._build(fetchers)
        self.assertTrue(ok)
        self.assertEqual((coins["ZKNOWN"]["identity"], coins["BTC"]["identity"]), (ID.UNVERIFIED, ID.VERIFIED_CRYPTO))
        self.assertNotIn("SOL", coins)                                         # no fallback list in a degraded scan

    def test_fallback_only_when_every_venue_failed(self):
        def fail():
            raise RuntimeError("venue down")
        coins, status, ok = self._build({d: fail for d in sc.DEXES})
        self.assertFalse(ok)
        self.assertEqual(coins["ZKNOWN"]["identity"], ID.VERIFIED_CRYPTO)     # unchanged existing fallback behaviour
        self.assertEqual(coins["ZKNOWN"]["venues"], {})


# --------------------------------------------------------------------------- the scheduled-scan gate (section 50)
class ScanGateInvariants(unittest.TestCase):
    """Critical Phase 6 invariants, cheap enough for every scan."""

    def test_one_known_crypto_exposure_binds(self):
        r = res(hl("ZKNOWN", 0.25, 4e6), var("ZKNOWN", 0.251, 1e6))
        self.assertEqual((st(r, "ZKNOWN"), r.asset("ZKNOWN")["reason"]), (ID.VERIFIED_CRYPTO, ID.R_BOUND))
        self.assertTrue(sc.crypto_authorized(r.coins["ZKNOWN"]))

    def test_two_unresolved_exposures_never_both_crypto(self):
        r = res(*ZA, *ZB)
        self.assertEqual(st(r, "ZKNOWN"), ID.UNVERIFIED)
        self.assertNotIn(ID.CRYPTO, {x["class"] for x in r.asset("ZKNOWN")["exposures"]})
        self.assertFalse(sc.crypto_authorized(r.coins["ZKNOWN"]))

    def test_tradfi_collision_leaves_one_bindable(self):
        r = res(hl("ZKNOWN", 0.5, 1e6), lt("ZKNOWN", 125.0, 3e6, "RWA", ["STOCK"]))
        self.assertEqual((st(r, "ZKNOWN"), list(r.coins["ZKNOWN"]["venues"])), (ID.VERIFIED_CRYPTO, ["hyperliquid"]))

    def test_failed_exposure_check_cannot_acquire_crypto(self):
        r = res(lt("ZKNOWN", 0.5, 1e6, xcheck="FAILED"))
        self.assertFalse(sc.crypto_authorized(r.coins["ZKNOWN"]))
        r = res(hl("ZKNOWN", 0.5, 1e6), lt("ZKNOWN", 80.0, 9e6, xcheck="FAILED"))
        self.assertEqual(list(r.coins["ZKNOWN"]["venues"]), ["hyperliquid"])

    def test_current_downgrade_blocks_actionability(self):
        r = res(*ZA, *ZB)
        auth = EV.universe_authority(r.coins, 0, "gh-1-1", r.assets)
        act, blk = Q.split_open([dict(QUANT_TRADE, id="ZKNOWN-TSMOM-1", c="ZKNOWN")], r.coins, auth)
        self.assertEqual((act, [b["identity_reason"] for b in blk]), ([], ["IDENTITY_UNVERIFIED"]))

    def test_prior_entry_proof_stays_historical(self):
        tr = {"identity_state_at_entry": ID.VERIFIED_CRYPTO, "identity_qualified": True,
              "identity_version": "v8.identity/3", "identity_scan_id": "gh-1-1"}
        self.assertTrue(EV.qualified(tr))


if __name__ == "__main__":
    unittest.main()
