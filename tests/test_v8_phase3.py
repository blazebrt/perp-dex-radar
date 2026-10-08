"""v8 Phase 3: identity coverage hardening and discovery/execution separation, unit level.

* the regression matrix A-P (explicit crypto and tradfi metadata, the known-crypto list, inheritance, conflicting
  evidence, unlabeled single- and multi-venue perps, a new small coin, QNT, PURR, BB, XIAOMI, and the SAMSUNGUSD,
  HYUNDAIUSD, US10Y and BYD classes - none solved by naming a ticker);
* "no evidence" never means crypto: on random market lists no exposure is crypto by default, and every coin with
  crypto execution identity carries positive evidence;
* the mandatory small-coin case: a brand-new unknown perp (low volume, no candles, no list, no label) is in the
  contract registry, the asset registry, the discovery universe and the Decision Trace, as UNVERIFIED;
* the mandatory execution-safety case: the same coin, once every other gate passes (proven by a control run in which
  it is published), is never published by the radar, the quant desk, swing or day picks when it is UNVERIFIED;
* the gate fails closed (a coin record without an identity has no execution authority).

The end-to-end versions (whole pipeline, snapshot, differential parity) are in tests/test_v8_audit.py and CI.

Run from the repository root:  python -m unittest tests.test_v8_phase3 -v"""
from __future__ import annotations

import json
import math
import os
import random
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import picks as P  # noqa: E402
import quant as Q  # noqa: E402
import scanner as sc  # noqa: E402
from fake_exchange import FakeExchange, install  # noqa: E402
from test_picks import RSS  # noqa: E402
from v8 import identity as ID  # noqa: E402
from v8 import parts  # noqa: E402
from v8 import registry as R  # noqa: E402
from v8.trace import Recorder  # noqa: E402

LISTS = ID.Lists(sc.TRADFI, sc.KNOWN_CRYPTO, sc.is_fx, sc.TRADFI_NAME)


# --------------------------------------------------------------------------- rows shaped like the adapters' output
def row(dex, sym, base, price, vol, **kw):
    t, m = sc.canon(base)
    return sc._venue(t, dex, sym, m, price=price, vol=vol, **kw)


def hl(sym, price, vol):
    return row("hyperliquid", sym, sym, price, vol)


def lighter(sym, price, vol):
    return row("lighter", sym, sym, price, vol)


def var(sym, price, vol, name=None):
    return row("variational", sym, sym, price, vol, name=name or sym)


def aster(sym, base, price, vol, ut="COIN"):
    return row("aster", sym, base, price, vol, tradfi=True if ut and ut != "COIN" else None, underlying=ut)


def ext(name, asset, price, vol, cat="RWA", desc=None):
    return row("extended", name, asset, price, vol, tradfi=True if (cat and cat != "Crypto") else None, name=desc,
               category=cat)


def resolve(*rows):
    res = {d: [] for d in sc.DEXES}
    for r in rows:
        res[r["dex"]].append(r)
    return ID.resolve(res, sc.DEXES, LISTS, sc.in_my_dexes)


def state(res, t):
    return res.coins[t]["identity"]


def row_of(res, dex, i=0):
    return res.rows[(dex, i)]


class FourStates(unittest.TestCase):
    def test_states_and_gate(self):
        self.assertEqual(ID.STATES, ("VERIFIED_CRYPTO", "VERIFIED_TRADFI", "AMBIGUOUS", "UNVERIFIED"))
        self.assertTrue(ID.execution_identity_eligible({"identity": "VERIFIED_CRYPTO", "tradfi": False}))
        for st in ("VERIFIED_TRADFI", "AMBIGUOUS", "UNVERIFIED", None):
            self.assertFalse(ID.execution_identity_eligible({"identity": st, "tradfi": False}), st)
        self.assertFalse(ID.execution_identity_eligible({"tradfi": False}))           # no identity: fails closed
        self.assertFalse(ID.execution_identity_eligible({"identity": "VERIFIED_CRYPTO", "tradfi": True}))
        self.assertFalse(ID.execution_identity_eligible(None))
        self.assertTrue(ID.discovery_eligible({"venues": {"aster": {}}, "identity": "UNVERIFIED"}))
        self.assertIs(sc.crypto_authorized, sc.crypto_authorized)
        self.assertTrue(sc.crypto_authorized({"identity": "VERIFIED_CRYPTO", "tradfi": False}))
        self.assertFalse(sc.crypto_authorized({"identity": "UNVERIFIED", "tradfi": False}))

    def test_fallback_universe_is_the_known_crypto_list(self):
        old = sc.FETCH

        def down(url, body=None, timeout=25):
            raise sc.HttpError(503, "down")
        sc.FETCH = down
        try:
            coins, _, ok = sc.build_universe()
        finally:
            sc.FETCH = old
        self.assertFalse(ok)
        self.assertTrue(all(c["identity"] == ID.VERIFIED_CRYPTO and c["t"] in sc.KNOWN_CRYPTO for c in coins.values()))


class Matrix(unittest.TestCase):
    """The Phase 3 regression matrix A-P."""

    def test_A_explicit_crypto_metadata(self):
        r = resolve(ext("NOVA-USD", "NOVA", 1.0, 2e6, cat="Crypto"), hl("NOVA", 1.01, 5e6))
        self.assertEqual(state(r, "NOVA"), ID.VERIFIED_CRYPTO)
        a = r.asset("NOVA")
        self.assertEqual((a["authority"], a["reason"]), (ID.VENUE_METADATA, "CRYPTO_VENUE_METADATA"))
        self.assertIn(["extended:NOVA-USD", "CRYPTO", "VENUE_CATEGORY:Crypto", "VENUE_METADATA"], a["evidence"])
        self.assertTrue(row_of(r, "hyperliquid")["admitted"])

    def test_B_known_crypto_without_metadata(self):
        r = resolve(hl("SOL", 150.0, 5e6), lighter("SOL", 150.2, 1e6))
        self.assertEqual(state(r, "SOL"), ID.VERIFIED_CRYPTO)
        self.assertEqual(r.asset("SOL")["authority"], ID.TICKER_LIST)
        # ... unless stronger contradictory evidence sits in the same price-coherent exposure
        r = resolve(hl("SOL", 150.0, 5e6), ext("SOL-USD", "SOL", 150.5, 1e6, cat="RWA"))
        self.assertNotEqual(state(r, "SOL"), ID.VERIFIED_CRYPTO)
        self.assertFalse(ID.execution_identity_eligible(r.coins["SOL"]))

    def test_C_explicit_rwa_metadata(self):
        r = resolve(ext("ACMX-USD", "ACMX", 50.0, 1e5, cat="RWA"))
        self.assertEqual(state(r, "ACMX"), ID.VERIFIED_TRADFI)
        self.assertTrue(r.coins["ACMX"]["tradfi"])
        r = resolve(aster("ACMYUSDT", "ACMY", 50.0, 1e5, ut="EQUITY"))
        self.assertEqual(state(r, "ACMY"), ID.VERIFIED_TRADFI)

    def test_D_coherent_unlabeled_next_to_verified_tradfi(self):
        r = resolve(aster("ACMXUSDT", "ACMX", 50.2, 1e4), ext("ACMX-USD", "ACMX", 50.0, 1e5, cat="RWA"))
        self.assertEqual(state(r, "ACMX"), ID.VERIFIED_TRADFI)
        self.assertEqual(row_of(r, "aster")["inherited_from"], "extended:ACMX-USD")
        self.assertEqual(row_of(r, "aster")["exp_state"], ID.VERIFIED_TRADFI)

    def test_E_contradictory_evidence(self):
        r = resolve(ext("MIXD-USD", "MIXD", 3.0, 1e6, cat="Crypto"), aster("MIXDUSDT", "MIXD", 3.01, 1e5, ut="EQUITY"))
        self.assertEqual(state(r, "MIXD"), ID.AMBIGUOUS)
        r = resolve(ext("SECX-USD", "SECX", 2.0, 5e5, cat="L1"))
        self.assertEqual(state(r, "SECX"), ID.AMBIGUOUS)
        for t in ("MIXD", "SECX"):
            self.assertFalse(ID.execution_identity_eligible(r.coins.get(t) or {"identity": "AMBIGUOUS"}))

    def test_F_unlabeled_single_venue_new_perp(self):
        r = resolve(lighter("ZQX", 0.5, 1e4))
        c = r.coins["ZQX"]
        self.assertEqual((c["identity"], c["tradfi"]), (ID.UNVERIFIED, False))       # not crypto, not tradfi
        a = r.asset("ZQX")
        self.assertEqual((a["decision"], a["discovery_eligible"], a["execution_identity_eligible"]),
                         (ID.D_UNVERIFIED, True, False))
        self.assertEqual((a["reason"], a["authority"], a["evidence"]), ("NO_POSITIVE_IDENTITY_EVIDENCE", ID.NONE, []))
        self.assertTrue(a["promotion"])
        self.assertEqual(a["phase2"], {"state": "CRYPTO", "reasons": ["DEFAULT_CRYPTO"]})

    def test_G_multi_venue_unlabeled_coherent_is_still_unverified(self):
        rows = [hl("ZQY", 2.0, 5e6), aster("ZQYUSDT", "ZQY", 2.01, 1e6), lighter("ZQY", 1.99, 1e6),
                var("ZQY", 2.0, 1e6), row("dydx", "ZQY-USD", "ZQY", 2.0, 1e6), row("paradex", "ZQY-USD-PERP", "ZQY",
                                                                                   2.0, 1e6)]
        r = resolve(*rows)
        self.assertEqual(state(r, "ZQY"), ID.UNVERIFIED)        # six unlabeled venues do not prove crypto
        self.assertEqual(sorted(r.coins["ZQY"]["venues"]), sorted({x["dex"] for x in rows}))
        # one member with positive crypto evidence verifies the coherent exposure; one with tradfi evidence makes it tradfi
        r = resolve(*rows, ext("ZQY-USD", "ZQY", 2.0, 1e5, cat="Crypto"))
        self.assertEqual(state(r, "ZQY"), ID.VERIFIED_CRYPTO)
        r = resolve(*rows, ext("ZQY-USD", "ZQY", 2.0, 1e5, cat="RWA"))
        self.assertEqual(state(r, "ZQY"), ID.VERIFIED_TRADFI)

    def test_H_new_small_coin_stays_visible(self):
        """The mandatory small-coin case at unit level: contract registry, asset registry, discovery universe,
        Decision Trace (the ledger record the engines write for it)."""
        rec = Recorder()
        rec.payload("lighter", "books", {"order_book_details": [
            {"symbol": "NEWCOIN", "market_type": "perp", "status": "active", "mark_price": 0.0512,
             "daily_quote_token_volume": 1850.0, "market_flags": 0, "strategy_index": 2,
             "market_config": {"trading_hours": "", "insurance_fund_account_index": 1}}]})
        rows = [lighter("NEWCOIN", 0.0512, 1850.0)]
        rec.universe_rows({"lighter": rows})
        res = ID.resolve({"lighter": rows}, sc.DEXES, LISTS, sc.in_my_dexes)
        rec.identity(res)
        coins = res.coins
        self.assertIn("NEWCOIN", coins)                                     # the discovery universe
        self.assertTrue(ID.discovery_eligible(coins["NEWCOIN"]))
        self.assertFalse(sc.crypto_authorized(coins["NEWCOIN"]))
        reg = R.build(rec, coins, {"lighter": {"ok": True}}, True, 0)
        c = reg["contracts"][0]                                             # the contract registry
        self.assertEqual((c["id"], c["legacy"], c["exp_state"], c["in_record"], c["admitted"]),
                         ("lighter:NEWCOIN", "SELECTED", ID.UNVERIFIED, True, False))
        self.assertEqual(c["vmeta"], {"market_flags": 0, "strategy_index": 2, "insurance_fund_account_index": 1})
        a = reg["assets"]["NEWCOIN"]                                        # the asset registry
        self.assertEqual((a["legacy"], a["identity"]["state"], a["identity"]["discovery_eligible"],
                          a["identity"]["execution_identity_eligible"]), ("UNVERIFIED", ID.UNVERIFIED, True, False))
        self.assertEqual(R.counts(reg)["unverified_assets"], ["NEWCOIN"])
        from v8 import common as C                                          # the Decision Trace
        code, o = C.excluded_code(coins["NEWCOIN"], trace=rec)
        self.assertEqual(code, "IDENTITY_UNVERIFIED")
        self.assertEqual((o["state"], o["discovery"], o["execution_identity"]), (ID.UNVERIFIED, True, False))
        self.assertTrue(o["promotion"])
        self.assertEqual(C.excluded_health(code), "MISSING")
        self.assertNotEqual(code, "TRADFI_CLASSIFIED")

    def test_I_qnt(self):
        r = resolve(var("QNT", 257.89, 1.48e6, "Quant"), aster("QNTUSDT", "QNT", 255.93, 2.43e6),
                    lighter("QNT", 255.94, 336238.72), ext("QNT-USD", "QNT", 46.030332, 386135.13))
        self.assertEqual(state(r, "QNT"), ID.VERIFIED_CRYPTO)
        self.assertEqual(r.asset("QNT")["decision"], ID.D_SELECTED)
        self.assertEqual(sorted(r.coins["QNT"]["venues"]), ["aster", "lighter", "variational"])

    def test_J_purr(self):
        r = resolve(hl("PURR", 0.1536, 3.09e6), ext("PURR-USD", "PURR", 12.772243, 3031.12, desc="Hyperliquid Strategies Inc."))
        self.assertEqual(state(r, "PURR"), ID.VERIFIED_CRYPTO)
        self.assertIsNone(r.coins["PURR"]["name"])

    def test_K_bb(self):
        r = resolve(hl("BB", 0.0098, 4e6), var("BBIT", 0.00972, 75.93, "BounceBit"),
                    aster("BBUSDT", "BB", 0.00976, 5889.81), lighter("BB", 9.6408, 261799.05),
                    ext("BB-USD", "BB", 9.6065788, 40.05))
        self.assertEqual(state(r, "BB"), ID.VERIFIED_CRYPTO)
        self.assertEqual(sorted(r.coins["BB"]["venues"]), ["aster", "hyperliquid", "variational"])
        self.assertEqual(row_of(r, "lighter")["inherited_from"], "extended:BB-USD")

    def test_L_xiaomi(self):
        r = resolve(aster("XIAOMIUSDT", "XIAOMI", 3.114, 3570.65), lighter("XIAOMI", 3.0886, 841827.9),
                    ext("XIAOMI-USD", "XIAOMI", 24.187487, 0.0))
        self.assertEqual(state(r, "XIAOMI"), ID.AMBIGUOUS)
        self.assertTrue(r.coins["XIAOMI"]["tradfi"])
        self.assertFalse(ID.execution_identity_eligible(r.coins["XIAOMI"]))

    def test_M_samsungusd_class(self):
        """A base-only-symbol venue's symbol ending in USD whose candidate is on the existing tradfi list."""
        r = resolve(lighter("SAMSUNGUSD", 200.628, 1834862.6))
        self.assertEqual(state(r, "SAMSUNGUSD"), ID.VERIFIED_TRADFI)
        x = row_of(r, "lighter")
        self.assertEqual((x["why"], x["auth"], x["parsed"]),
                         ("PARSED_SYMBOL_TRADFI_LIST:SAMSUNG", ID.PARSED_SYMBOL, ["SAMSUNG", "QUOTE_SUFFIX:USD"]))
        # the same rule for any listed underlying - the parser names no ticker
        r = resolve(lighter("NVDAUSD", 237.0, 1e6), var("TSLAUSD", 250.0, 1e6))
        self.assertEqual((state(r, "NVDAUSD"), state(r, "TSLAUSD")), (ID.VERIFIED_TRADFI, ID.VERIFIED_TRADFI))
        # an unknown candidate decides nothing: UNVERIFIED, never crypto
        r = resolve(lighter("ZORPUSD", 12.0, 1e6))
        self.assertEqual(state(r, "ZORPUSD"), ID.UNVERIFIED)
        # no blind suffix stripping: the ticker is unchanged, and venues that write a quote are not parsed
        self.assertIn("ZORPUSD", r.coins)
        self.assertEqual(ID.parse_symbol("aster", "SAMSUNGUSD"), (None, None))
        self.assertEqual(ID.parse_symbol("lighter", "USD"), (None, None))
        self.assertEqual(ID.parse_symbol("lighter", "SUSD"), (None, None))       # too short to be an underlying

    def test_N_hyundaiusd_class(self):
        r = resolve(lighter("HYUNDAIUSD", 252.403, 2579.88), aster("HYUNDAIUSDT", "HYUNDAI", 253.02, 241.98))
        self.assertEqual((state(r, "HYUNDAIUSD"), state(r, "HYUNDAI")), (ID.UNVERIFIED, ID.UNVERIFIED))
        link = row_of(r, "lighter")["link"]
        self.assertEqual((link["candidate"], link["coherent_exposure"], link["coherent_class"], link["evidence"]),
                         ("HYUNDAI", "HYUNDAI#1", ID.UNVERIFIED, None))
        self.assertNotIn("HYUNDAIUSD", r.coins["HYUNDAI"]["venues"].get("lighter", {}).get("sym", ""))   # not merged
        # the same shape where the candidate has verified tradfi evidence at a coherent price: tradfi (SKHYNIXUSD)
        r = resolve(lighter("HYUNDAIUSD", 252.403, 2579.88), ext("HYUNDAI-USD", "HYUNDAI", 253.0, 1e5, cat="RWA"))
        self.assertEqual(state(r, "HYUNDAIUSD"), ID.VERIFIED_TRADFI)
        self.assertEqual(row_of(r, "lighter")["why"], "PARSED_SYMBOL_EXPOSURE:HYUNDAI#1")
        # ... and not at an incoherent price
        r = resolve(lighter("HYUNDAIUSD", 25.0, 2579.88), ext("HYUNDAI-USD", "HYUNDAI", 253.0, 1e5, cat="RWA"))
        self.assertEqual(state(r, "HYUNDAIUSD"), ID.UNVERIFIED)

    def test_O_rates_style_instrument(self):
        r = resolve(lighter("US10Y", 94.75, 7392.47))
        self.assertEqual(state(r, "US10Y"), ID.UNVERIFIED)
        self.assertFalse(ID.execution_identity_eligible(r.coins["US10Y"]))

    def test_P_byd_class(self):
        r = resolve(lighter("BYD", 3.0212, 0.0))
        self.assertEqual(state(r, "BYD"), ID.UNVERIFIED)
        self.assertEqual(r.coins["BYD"]["best_vol"], 0.0)

    def test_parsed_symbol_never_grants_crypto(self):
        r = resolve(hl("BTC", 60000.0, 1e9), lighter("BTCUSD", 60010.0, 1e6))
        self.assertEqual(state(r, "BTC"), ID.VERIFIED_CRYPTO)
        self.assertEqual(state(r, "BTCUSD"), ID.UNVERIFIED)
        self.assertEqual(row_of(r, "lighter")["link"]["coherent_class"], ID.CRYPTO)

    def test_unverified_exposure_not_merged_into_crypto_coin(self):
        r = resolve(ext("PRLX-USD", "PRLX", 0.111, 232844.0, cat="Crypto"), aster("PRLXUSDT", "PRLX", 0.1122, 2646.9),
                    lighter("PRLX", 1.34, 196238.6))
        self.assertEqual(state(r, "PRLX"), ID.VERIFIED_CRYPTO)
        self.assertEqual(sorted(r.coins["PRLX"]["venues"]), ["aster", "extended"])
        self.assertEqual(row_of(r, "lighter")["state"], ID.NOT_ADMITTED_UNVERIFIED)
        self.assertEqual(r.asset("PRLX")["excluded_unverified"], ["PRLX#2"])
        # if the unverified exposure trades more, the verified one is still the coin (Phase 2 anchored on volume)
        r = resolve(ext("PRLX-USD", "PRLX", 0.111, 1e4, cat="Crypto"), lighter("PRLX", 1.34, 5e6))
        self.assertEqual(r.coins["PRLX"]["ref_price"], 0.111)


class NoDefaultCrypto(unittest.TestCase):
    def test_no_exposure_is_crypto_by_default(self):
        """On random market lists: no exposure is crypto without positive evidence, every coin with crypto execution
        identity has a crypto exposure with venue or ticker-list evidence, and every asset is in one of the four
        states."""
        names = [f"Q{i}" for i in range(30)] + ["BTC", "ETH", "AAPL", "SAMSUNGUSD", "NVDAUSD", "FOOUSD"]
        for seed in range(30):
            rng = random.Random(seed)
            res = {d: [] for d in sc.DEXES}
            for t in names:
                px = math.exp(rng.uniform(-3, 6))
                for dex in sc.DEXES:
                    if rng.random() < 0.6:
                        continue
                    p = None if dex == "edgex" else px * rng.choice([1, 1, 1.05, 3.0])
                    kw = {}
                    if dex == "extended":
                        kw["category"] = rng.choice([None, "Crypto", "RWA", "L1"])
                    if dex == "aster":
                        kw["underlying"] = rng.choice(["COIN", "COIN", "EQUITY"])
                    res[dex].append(sc._venue(t, dex, t, 1.0, price=p, vol=rng.choice([None, 0.0, 1e6]), **kw))
            r = ID.resolve(res, sc.DEXES, LISTS, sc.in_my_dexes)
            for t, a in r.assets.items():
                self.assertIn(a["state"], ID.STATES, (seed, t))
                self.assertTrue(all(x["reason"] != "DEFAULT_CRYPTO" for x in a["exposures"]), (seed, t))
                c = r.coins.get(t)
                if c is not None:
                    self.assertEqual(c["identity"], a["state"], (seed, t))
                if c is not None and ID.execution_identity_eligible(c):
                    self.assertTrue(any(x["admitted"] and x["authority"] in (ID.VENUE_METADATA, ID.TICKER_LIST)
                                        for x in a["exposures"]), (seed, t))
                if a["state"] == ID.UNVERIFIED and c is not None:    # (None: every venue a price conflict, legacy)
                    self.assertFalse(c["tradfi"], (seed, t))                  # unknown is not tradfi


# --------------------------------------------------------------------------- execution safety, engine by engine
def fake_universe(fx, unverified=()):
    uni = {}
    for c in fx.coins:
        uni[c] = {"t": c, "venues": {"hyperliquid": {"sym": c, "mult": 1.0, "vol": fx.vol24[c], "funding8h": 0.0001}},
                  "trade_vol": fx.vol24[c] * 1.2, "best_vol": fx.vol24[c] * 1.2, "tradfi": False,
                  "ref_price": fx.c15[c][-1]["c"], "name": c,
                  "identity": ID.UNVERIFIED if c in unverified else ID.VERIFIED_CRYPTO}
    return uni


def published_quant(out):
    return {t.get("c") for t in (out.get("signals") or []) + (out.get("open") or [])}


def published_picks(out):
    got = set()
    for k in ("swing", "daytrade"):
        for side in ("all", "long", "short"):
            got |= {r.get("coin") for r in (out.get(k) or {}).get(side) or [] if isinstance(r, dict)}
    return got


class ExecutionSafety(unittest.TestCase):
    """The mandatory execution-safety case. For each engine a control run on a fake market publishes a coin, proving
    every other gate (liquidity, history, strategy, score, slots) passes for it; the same run with only that coin's
    identity set to UNVERIFIED must not publish it anywhere and must record IDENTITY_UNVERIFIED for it."""

    @classmethod
    def setUpClass(cls):
        cls.fx = FakeExchange(n_coins=16, days=130, seed=11)
        cls.old = sc.FETCH
        sc.FETCH = cls.fx.fetch
        cls.tmp = tempfile.mkdtemp(prefix="v8p3")
        cls.saved = (P.CFG["gap_stocktwits"], P.CFG["gap_coingecko"], P.get_text, P.GEMINI_KEY)
        P.CFG["gap_stocktwits"] = P.CFG["gap_coingecko"] = 0.0
        P.get_text = lambda url, timeout=30: RSS
        P.GEMINI_KEY = ""

    @classmethod
    def tearDownClass(cls):
        sc.FETCH = cls.old
        P.CFG["gap_stocktwits"], P.CFG["gap_coingecko"], P.get_text, P.GEMINI_KEY = cls.saved
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def out_dir(self, name):
        d = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(d, "data"), exist_ok=True)
        with open(os.path.join(d, "data", "latest.json"), "w") as fh:
            json.dump({"smart_coins": {}, "smart": {"read": 0}}, fh)
        with open(os.path.join(d, "index.html"), "w") as fh:
            fh.write("<html>radar</html>")
        return d

    def record(self, d, engine, t):
        recs = {r["a"]: r for r in (parts.read(d, engine) or {}).get("records") or []}
        return recs.get(t)

    def test_quant(self):
        d = self.out_dir("q_control")
        ctl = Q.run(d, journal_path=os.path.join(self.tmp, "none.json"), universe=fake_universe(self.fx))
        shown = sorted(x for x in published_quant(ctl) if x != "BTC")
        self.assertTrue(shown, "the control run must publish a quant signal or position")
        t = shown[0]
        d2 = self.out_dir("q_unverified")
        got = Q.run(d2, journal_path=os.path.join(self.tmp, "none.json"), universe=fake_universe(self.fx, {t}))
        self.assertNotIn(t, published_quant(got))
        self.assertNotIn(t, json.dumps(got.get("live") or {}))
        self.assertEqual(self.record(d2, "quant", t)["c"], "IDENTITY_UNVERIFIED")

    def test_swing_and_day(self):
        d = self.out_dir("p_control")
        ctl = P.run(d, journal_path=os.path.join(self.tmp, "none.json"), universe=fake_universe(self.fx))
        sw = [r["coin"] for r in ctl["swing"]["all"] if r["coin"] != "BTC"]
        dy = [r["coin"] for r in ctl["daytrade"]["all"] if r["coin"] != "BTC"]
        self.assertTrue(sw and dy, "the control run must list swing and day-trade coins")
        block = {sw[0], dy[0]}
        d2 = self.out_dir("p_unverified")
        got = P.run(d2, journal_path=os.path.join(self.tmp, "none.json"), universe=fake_universe(self.fx, block))
        self.assertFalse(block & published_picks(got), block & published_picks(got))
        with open(os.path.join(d2, "data", "picks_journal.json")) as fh:
            J = json.load(fh)
        self.assertFalse(block & {tr.get("c") for tr in (J.get("open") or []) + (J.get("closed") or [])})
        for t in block:
            self.assertEqual(self.record(d2, "swing", t)["c"], "IDENTITY_UNVERIFIED", t)
            self.assertEqual(self.record(d2, "day", t)["c"], "IDENTITY_UNVERIFIED", t)

    def test_radar(self):
        fx = FakeExchange(n_coins=24, days=4, seed=2)
        restore = install(fx)
        try:
            d = self.out_dir("r_control")
            ctl = sc.run(d, replay_days=0)
            table = [row[1] for row in ctl.get("table") or []]
            cands = [p["coin"] for p in (ctl.get("picks") or []) + (ctl.get("watch") or [])] + table
            t = next(x for x in cands if x not in ("BTC", "ETH"))
        finally:
            restore()
        restore = install(fx)
        sc.KNOWN_CRYPTO = sc.KNOWN_CRYPTO - {t}           # the same market; only this coin loses its identity
        try:
            d2 = self.out_dir("r_unverified")
            got = sc.run(d2, replay_days=0)
        finally:
            restore()
        self.assertIn(t, got["coverage"]["unverified"])
        self.assertNotIn(t, got["coverage"]["tradfi"])
        self.assertNotIn(t, [row[1] for row in got.get("table") or []])
        self.assertNotIn(t, [p["coin"] for p in (got.get("picks") or []) + (got.get("watch") or [])])
        with open(os.path.join(d2, "data", "journal.json")) as fh:
            J = json.load(fh)
        self.assertNotIn(t, {tr.get("coin") for tr in (J.get("open") or []) + (J.get("closed") or [])})
        self.assertEqual(self.record(d2, "radar", t)["c"], "IDENTITY_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
