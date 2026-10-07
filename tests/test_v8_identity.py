"""v8 Phase 2: universe identity (v8.identity) and liquidity semantics (v8.liquidity), unit level.

* the collision regression matrix, cases A-K (crypto + unrelated stock, a stock one venue forgot to label, a wrong
  tradfi row, two exposures under one ticker, no price, multiplier aliases, only ambiguous evidence, and the live
  shapes of QNT, PURR, BB and the ten Phase 1 stock collisions);
* the mandatory stock-leakage gate: no coherent stock enters the crypto universe because a venue left it unlabeled;
* parity where nothing collides: for random market lists without tradfi evidence the coin records are exactly the
  legacy build_universe() records (a verbatim copy of the Phase 1 algorithm below is the reference);
* missing liquidity is not zero: observed zero, missing, not on a trade DEX, sorting, storing, the gate;
* no ticker is hard-coded in the classifier.

Run from the repository root:  python -m unittest tests.test_v8_identity -v"""
from __future__ import annotations

import ast
import inspect
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import scanner as sc  # noqa: E402
from v8 import identity as ID  # noqa: E402
from v8 import liquidity as LQ  # noqa: E402

LISTS = ID.Lists(sc.TRADFI, sc.KNOWN_CRYPTO, sc.is_fx, sc.TRADFI_NAME)
MINE = sc.CFG["trade_dexes"]


# --------------------------------------------------------------------------- rows shaped like the adapters' output
def hl(sym, price, vol):
    t, m = sc.canon(sym)
    return sc._venue(t, "hyperliquid", sym, m, price=price, vol=vol)


def lighter(sym, price, vol):
    t, m = sc.canon(sym)
    return sc._venue(t, "lighter", sym, m, price=price, vol=vol)


def dydx(sym, price, vol):
    t, m = sc.canon(sym.split("-")[0])
    return sc._venue(t, "dydx", sym, m, price=price, vol=vol)


def var(sym, price, vol, name=None):
    t, m = sc.canon(sym)
    return sc._venue(t, "variational", sym, m, price=price, vol=vol, name=name or sym)


def aster(sym, base, price, vol, ut="COIN"):
    t, m = sc.canon(base)
    return sc._venue(t, "aster", sym, m, price=price, vol=vol, tradfi=True if ut and ut != "COIN" else None,
                     underlying=ut)


def ext(name, asset, price, vol, cat="RWA", desc=None):
    t, m = sc.canon(asset)
    return sc._venue(t, "extended", name, m, price=price, vol=vol,
                     tradfi=True if (cat and cat != "Crypto") or "_24_5" in name else None, name=desc, category=cat)


def edgex(sym):
    t, m = sc.canon(sym.replace("USD", ""))
    return sc._venue(t, "edgex", sym, m)


def resolve(*rows):
    res = {d: [] for d in sc.DEXES}
    for r in rows:
        res[r["dex"]].append(r)
    return ID.resolve(res, sc.DEXES, LISTS, sc.in_my_dexes)


def admitted(res, t):
    c = res.coins.get(t)
    return c is not None and not c["tradfi"]


# The ten Phase 1 live collisions that are real stocks, with the prices, volumes and labels the live scan
# gh-37475517788-1 recorded (docs/v8/phase2-universe-identity.md). Aster sent underlyingType COIN for every one.
STOCKS = {
    "ASTS": [aster("ASTSUSDT", "ASTS", 64.46, 9929.47), ext("ASTS-USD", "ASTS", 64.655214, 321833.84)],
    "COHR": [aster("COHRUSDT", "COHR", 339.14, 12184.65), ext("COHR-USD", "COHR", 336.55931, 318889.41)],
    "FLNC": [var("FLNC", 8.0444771, 11517.35, "Fluence Energy Inc"), aster("FLNCUSDT", "FLNC", 7.68, 100.07),
             ext("FLNC-USD", "FLNC", 8.1282927, 356553.3)],
    "GLW": [aster("GLWUSDT", "GLW", 163.66, 4631.38), ext("GLW-USD", "GLW", 164.8182, 0.0)],
    "KIOXIA": [lighter("KIOXIA", 118.44, 0.0), ext("KIOXIA-USD", "KIOXIA", 119.02363, 0.0)],
    "KORU": [aster("KORUUSDT", "KORU", 22.12, 108556.54), lighter("KORU", 22.104, 0.0),
             ext("KORU-USD", "KORU", 22.106764, 279020.93)],
    "MINIMAX": [aster("MINIMAXUSDT", "MINIMAX", 31.71, 19814.14), lighter("MINIMAX", 31.686, 228.89366),
                ext("MINIMAX-USD", "MINIMAX", 31.683345, 0.0)],
    "ONDS": [var("ONDS", 7.477514, 105184.77, "Ondas Holdings Inc."), aster("ONDSUSDT", "ONDS", 7.561, 425.19)],
    "SKHYNIX": [aster("SKHYNIXUSDT", "SKHYNIX", 1333.93, 1732477.1), aster("SKHYNIXUSD1", "SKHYNIX", 1335.4, 18491441.0),
                ext("SKHYNIX-USD", "SKHYNIX", 1334.1498, 245150.55)],
    # the stock quoted in HKD on Extended (24.19) and in USD (3.1) on Aster and Lighter
    "XIAOMI": [aster("XIAOMIUSDT", "XIAOMI", 3.114, 3570.65), lighter("XIAOMI", 3.0886, 841827.9),
               ext("XIAOMI-USD", "XIAOMI", 24.187487, 0.0)],
}


class CollisionMatrix(unittest.TestCase):
    def test_A_crypto_and_unrelated_stock_price_divergent(self):
        r = resolve(hl("PURR", 0.1536, 3.08e6), ext("PURR-USD", "PURR", 12.77, 3031.0, desc="Hyperliquid Strategies Inc."))
        self.assertTrue(admitted(r, "PURR"))
        c = r.coins["PURR"]
        self.assertEqual(list(c["venues"]), ["hyperliquid"])
        self.assertIsNone(c["name"])                       # the company name no longer labels the coin
        a = r.asset("PURR")
        self.assertEqual(a["decision"], ID.D_SELECTED)
        self.assertEqual([x["class"] for x in a["exposures"]], [ID.CRYPTO, ID.TRADFI])
        self.assertEqual(r.rows[("extended", 0)]["state"], ID.NOT_ADMITTED)

    def test_B_stock_labeled_on_one_venue_unlabeled_on_another_coherent(self):
        r = resolve(aster("ASTSUSDT", "ASTS", 64.46, 9929.47), ext("ASTS-USD", "ASTS", 64.655214, 321833.84))
        self.assertFalse(admitted(r, "ASTS"))
        self.assertTrue(r.coins["ASTS"]["tradfi"])
        self.assertEqual(r.asset("ASTS")["decision"], ID.D_TRADFI_EXPOSURE)
        info = r.rows[("aster", 0)]
        self.assertEqual((info["cls"], info["exp_cls"]), (ID.UNLABELED, ID.TRADFI))
        self.assertEqual(info["inherited_from"], "extended:ASTS-USD")
        # also when the unlabeled venue is the most traded one (it anchors the exposure)
        r = resolve(aster("ASTSUSDT", "ASTS", 64.46, 9e6), ext("ASTS-USD", "ASTS", 64.655214, 1.0))
        self.assertFalse(admitted(r, "ASTS"))

    def test_C_crypto_on_several_venues_one_wrong_tradfi_row(self):
        r = resolve(var("QNT", 257.88566, 1483308.0, "Quant"), aster("QNTUSDT", "QNT", 255.93, 2432646.9),
                    lighter("QNT", 255.944, 336238.72), ext("QNT-USD", "QNT", 46.030332, 386135.13))
        self.assertTrue(admitted(r, "QNT"))
        c = r.coins["QNT"]
        self.assertEqual(sorted(c["venues"]), ["aster", "lighter", "variational"])
        self.assertAlmostEqual(c["trade_vol"], 2432646.9)
        self.assertEqual(r.rows[("extended", 0)]["exp_cls"], ID.TRADFI)
        self.assertFalse(r.rows[("extended", 0)]["admitted"])

    def test_D_two_valid_exposures_under_one_ticker_do_not_contaminate(self):
        # an unlisted ticker: crypto by Extended's own category on one side, a stock by its name on the other
        r = resolve(ext("NOVA-USD", "NOVA", 0.5, 2e6, cat="Crypto", desc="Nova"),
                    var("NOVA", 30.0, 4e5, "Nova Holdings Inc"), aster("NOVAUSDT", "NOVA", 30.2, 1e5))
        a = r.asset("NOVA")
        cls = {x["id"]: x["class"] for x in a["exposures"]}
        self.assertEqual(sorted(cls.values()), [ID.CRYPTO, ID.TRADFI])
        self.assertTrue(admitted(r, "NOVA"))
        self.assertEqual(list(r.coins["NOVA"]["venues"]), ["extended"])
        self.assertEqual(r.rows[("aster", 0)]["exp_cls"], ID.TRADFI)       # inherited inside its own exposure
        self.assertEqual(r.rows[("extended", 0)]["exp_cls"], ID.CRYPTO)     # never inherited across exposures

    def test_E_contract_without_price_cannot_poison(self):
        # an unpriced RWA market next to a priced coin: it neither joins nor reclassifies it
        r = resolve(hl("FOO", 2.0, 5e6), ext("FOO-USD", "FOO", None, 1000.0))
        self.assertTrue(admitted(r, "FOO"))
        self.assertEqual(list(r.coins["FOO"]["venues"]), ["hyperliquid"])
        self.assertEqual(r.rows[("extended", 0)]["state"], ID.NOT_ADMITTED)
        self.assertEqual(r.rows[("extended", 0)]["exp_cls"], ID.TRADFI)
        # an unpriced, unlabeled market rides along with an admitted coin, as it always did
        r = resolve(hl("FOO", 2.0, 5e6), edgex("FOOUSD"))
        self.assertEqual(sorted(r.coins["FOO"]["venues"]), ["edgex", "hyperliquid"])
        # ... but never with a stock
        r = resolve(aster("ASTSUSDT", "ASTS", 64.46, 9929.47), ext("ASTS-USD", "ASTS", 64.655214, 321833.84),
                    edgex("ASTSUSD"))
        self.assertFalse(admitted(r, "ASTS"))
        # with no price anywhere, the ticker is one exposure: tradfi evidence keeps it out (as legacy did)
        r = resolve(edgex("BARUSD"), ext("BAR-USD", "BAR", None, None))
        self.assertFalse(admitted(r, "BAR"))

    def test_F_multiplier_aliases_compare_per_coin(self):
        r = resolve(hl("kPEPE", 0.0110, 5e6), var("1000PEPE", 0.01105, 1e6), lighter("PEPE", 0.0000111, 3e5),
                    ext("PEPE-USD", "PEPE", 0.0110, 1e5))   # an RWA quoted like the x1000 contract: another asset
        a = r.asset("PEPE")
        self.assertTrue(admitted(r, "PEPE"))
        self.assertEqual(sorted(r.coins["PEPE"]["venues"]), ["hyperliquid", "lighter", "variational"])
        x = a["exposures"][0]
        self.assertEqual(sorted(x["members"]), ["hyperliquid:kPEPE", "lighter:PEPE", "variational:1000PEPE"])
        self.assertAlmostEqual(r.rows[("hyperliquid", 0)]["npx"], 0.000011)
        self.assertEqual(r.rows[("extended", 0)]["exp_cls"], ID.TRADFI)
        # the same shape under a ticker that is not a known crypto coin: without positive crypto evidence the
        # unlabeled exposure of a ticker that is a real-world asset elsewhere is held back as ambiguous
        r = resolve(hl("kFOO", 2000.0, 5e6), var("1000FOO", 2010.0, 1e6), ext("FOO-USD", "FOO", 2000.0, 1e5))
        self.assertFalse(admitted(r, "FOO"))
        self.assertEqual(r.asset("FOO")["decision"], ID.D_AMBIGUOUS)
        self.assertEqual(r.rows[("hyperliquid", 0)]["exp_why"], "UNLABELED_UNDER_TRADFI_COLLISION")
        self.assertAlmostEqual(r.rows[("hyperliquid", 0)]["npx"], 2.0)

    def test_G_only_ambiguous_contracts_are_not_admitted(self):
        r = resolve(ext("SECT-USD", "SECT", 2.0, 5e5, cat="L1"))
        self.assertFalse(admitted(r, "SECT"))
        self.assertEqual(r.asset("SECT")["decision"], ID.D_AMBIGUOUS)
        # crypto and tradfi evidence in one price-coherent exposure
        r = resolve(ext("ZED-USD", "ZED", 5.0, 1e6, cat="Crypto", desc="Zed"), var("ZED", 5.05, 1e6, "Zed Holdings Inc"))
        self.assertFalse(admitted(r, "ZED"))
        self.assertEqual(r.asset("ZED")["exposures"][0]["reason"], "CONFLICTING_CONTRACT_EVIDENCE")

    def test_H_qnt_live_shape(self):
        self.test_C_crypto_on_several_venues_one_wrong_tradfi_row()

    def test_I_purr_live_shape(self):
        self.test_A_crypto_and_unrelated_stock_price_divergent()

    def test_J_bb_live_shape(self):
        # live: BounceBit on Aster (COIN) and Variational (BBIT) near $0.0097; a stock on Lighter (unlabeled, the
        # most traded) and Extended (RWA) near $9.6
        r = resolve(var("BBIT", 0.0097188683, 75.930625, "BounceBit"), aster("BBUSDT", "BB", 0.00976, 5889.81),
                    lighter("BB", 9.6408, 261799.05), ext("BB-USD", "BB", 9.6065788, 40.051))
        self.assertTrue(admitted(r, "BB"))
        c = r.coins["BB"]
        self.assertEqual(sorted(c["venues"]), ["aster", "variational"])
        self.assertAlmostEqual(c["trade_vol"], 5889.81)       # still below $1M: NOT_EXECUTABLE in the engines
        self.assertFalse(LQ.passes(c, 1e6, MINE))
        self.assertEqual(r.rows[("lighter", 0)]["exp_cls"], ID.TRADFI)
        self.assertEqual(r.rows[("lighter", 0)]["inherited_from"], "extended:BB-USD")

    def test_K_phase1_stock_collisions_stay_excluded(self):
        for t, rows in STOCKS.items():
            r = resolve(*rows)
            self.assertTrue(r.asset(t)["phase1_tradfi"], t)          # excluded before, excluded now
            self.assertIn(t, r.coins, t)
            self.assertTrue(r.coins[t]["tradfi"], t)
            self.assertIn(r.asset(t)["decision"], (ID.D_TRADFI_EXPOSURE, ID.D_AMBIGUOUS, ID.D_TRADFI), t)
            self.assertTrue(r.asset(t)["collision"], t)
        self.assertEqual(resolve(*STOCKS["XIAOMI"]).asset("XIAOMI")["decision"], ID.D_AMBIGUOUS)

    def test_known_crypto_list_only_counts_where_no_contract_evidence(self):
        # a known crypto ticker whose only priced exposure carries tradfi evidence stays out
        r = resolve(ext("QNT-USD", "QNT", 46.0, 1e5))
        self.assertFalse(admitted(r, "QNT"))
        # the tradfi list still wins for the whole ticker (unchanged legacy list)
        r = resolve(hl("AAPL", 230.0, 1e6), var("AAPL", 231.0, 1e6, "Apple"))
        self.assertFalse(admitted(r, "AAPL"))
        self.assertEqual(r.asset("AAPL")["decision"], ID.D_TRADFI)


class StockLeakageGate(unittest.TestCase):
    """MANDATORY: a venue forgetting to label a coherent stock contract never lets the stock into the crypto
    universe. Each Phase 1 stock is tried as recorded, with every volume ranking (any market may anchor the
    exposure), with prices moved anywhere inside the exposure tolerance, and with each unlabeled market alone next
    to a labeled one."""

    def variants(self, rows):
        yield rows
        for i in range(len(rows)):                           # each market the most traded
            v = [dict(r) for r in rows]
            v[i]["vol"] = 1e9
            yield v
        rng = random.Random(7)
        for _ in range(20):                                  # prices jittered within +-9% (one exposure)
            v = [dict(r) for r in rows]
            base = v[0]["price"]
            for r in v:
                if r.get("price"):
                    r["price"] = base * (1 + rng.uniform(-0.09, 0.09))
            yield v
        labeled = [r for r in rows if ID.classify_contract(r, LISTS)[0] == ID.TRADFI]
        for r in rows:
            if ID.classify_contract(r, LISTS)[0] == ID.UNLABELED:
                for lab in labeled:
                    yield [dict(r), dict(lab)]

    def test_no_stock_leaks(self):
        n = 0
        for t, rows in STOCKS.items():
            for v in self.variants(rows):
                r = resolve(*v)
                self.assertFalse(admitted(r, t), (t, [(x["dex"], x["price"], x["vol"]) for x in v]))
                n += 1
        self.assertGreater(n, 200)

    def test_status_counts_no_stock_market_as_crypto(self):
        res = {d: [] for d in sc.DEXES}
        for rows in STOCKS.values():
            for r in rows:
                res[r["dex"]].append(r)
        out = ID.resolve(res, sc.DEXES, LISTS, sc.in_my_dexes)
        self.assertEqual(sum(out.crypto_rows.values()), 0)


# --------------------------------------------------------------------------- parity where nothing collides
def legacy_build(results, in_my_dexes):
    """The Phase 1 (main 15a3794) build_universe() merge, verbatim except for the adapters and the notes."""
    coins = {}
    for dex in sc.DEXES:
        rows = results.get(dex)
        if rows is None:
            continue
        for r in rows:
            c = coins.setdefault(r["t"], {"t": r["t"], "venues": {}, "name": None, "tradfi": False})
            old = c["venues"].get(dex)
            if old is None or (r.get("vol") or 0) > (old.get("vol") or 0):
                c["venues"][dex] = r
            if r.get("name") and not c["name"] and dex in ("variational", "extended"):
                c["name"] = r["name"]
            c["tradfi"] = c["tradfi"] or r["tradfi"]
    for t, c in coins.items():
        priced = [(dex, v["price"] / v["mult"], v.get("vol") or 0) for dex, v in c["venues"].items() if v.get("price")]
        ref = None
        if priced:
            anchor = max(priced, key=lambda x: x[2])
            ref = anchor[1] if anchor[2] > 0 else sc.median([p for _, p, _ in priced], None)
            if len(priced) >= 2:
                for dex, p, _ in priced:
                    if abs(p / ref - 1) > 0.2:
                        c["venues"].pop(dex, None)
                ref = sc.median([v["price"] / v["mult"] for v in c["venues"].values() if v.get("price")], ref)
        c["ref_price"] = ref
        vols = [v["vol"] for v in c["venues"].values() if v.get("vol")]
        c["best_vol"] = max(vols) if vols else None
        c["tot_vol"] = sum(vols) if vols else None
        mine = [v["vol"] for d, v in c["venues"].items() if v.get("vol") and in_my_dexes(d)]
        c["trade_vol"] = max(mine) if mine else None
        c["tradfi"] = c["tradfi"] or sc.is_tradfi(t, c.get("name"))
    return {t: c for t, c in coins.items() if c["venues"]}


def zero_semantics(c):
    """The legacy volumes recomputed with Phase 2's rule (an observed 0 counts), for comparison."""
    vols = [v["vol"] for v in c["venues"].values() if v.get("vol") is not None]
    mine = [v["vol"] for d, v in c["venues"].items() if v.get("vol") is not None and sc.in_my_dexes(d)]
    return dict(c, best_vol=max(vols) if vols else None, tot_vol=sum(vols) if vols else None,
                trade_vol=max(mine) if mine else None)


class NoCollisionParity(unittest.TestCase):
    def random_results(self, seed, with_tradfi=False):
        rng = random.Random(seed)
        tick = [f"C{i}" for i in range(25)] + ["BTC", "ETH", "SOL"]
        if with_tradfi:
            tick += ["AAPL", "TSLA", "ACME"]
        res = {d: [] for d in sc.DEXES}
        for t in tick:
            px = math_exp(rng.uniform(-4, 6))
            for dex in sc.DEXES:
                if rng.random() < 0.45:
                    continue
                for _ in range(1 + (rng.random() < 0.15)):
                    p = None if (dex == "edgex" or rng.random() < 0.05) else px * (1 + rng.choice([0, 0, 0.05, -0.1, 0.5, 3.0]))
                    vol = rng.choice([None, 0.0, rng.uniform(1e3, 5e7), rng.uniform(1e3, 5e7)])
                    mult = rng.choice([1.0, 1.0, 1.0, 1000.0])
                    sym = ("1000" + t) if mult == 1000.0 else t
                    name = "Acme Holdings Inc" if t == "ACME" else (t if dex in ("variational", "extended") else None)
                    row = sc._venue(t, dex, sym, mult, price=p * mult if p else None, vol=vol, name=name)
                    if dex == "extended":
                        row["category"] = "Crypto"
                    if dex == "aster":
                        row["underlying"] = "COIN"
                    res[dex].append(row)
        if rng.random() < 0.3:
            res["paradex"] = None       # an adapter that failed
        return res

    def test_identical_to_legacy_without_tradfi_evidence(self):
        for seed in range(40):
            res = self.random_results(seed)
            legacy = legacy_build(res, sc.in_my_dexes)
            got = ID.resolve(res, sc.DEXES, LISTS, sc.in_my_dexes).coins
            self.assertEqual(list(got), list(legacy), seed)
            for t in legacy:
                exp = zero_semantics(legacy[t])
                self.assertEqual(list(got[t]["venues"]), list(exp["venues"]), (seed, t))
                for k in exp:
                    if k == "venues":
                        self.assertTrue(all(got[t]["venues"][d] is exp["venues"][d] for d in exp["venues"]))
                    else:
                        self.assertEqual(got[t][k], exp[k], (seed, t, k))
                self.assertEqual(list(got[t]), list(legacy[t]))   # same keys, same order

    def test_tradfi_list_tickers_unchanged(self):
        for seed in range(20):
            res = self.random_results(seed, with_tradfi=True)
            legacy = legacy_build(res, sc.in_my_dexes)
            got = ID.resolve(res, sc.DEXES, LISTS, sc.in_my_dexes).coins
            for t in ("AAPL", "TSLA", "ACME"):
                if t in legacy:
                    self.assertTrue(got[t]["tradfi"])
                    self.assertEqual(list(got[t]["venues"]), list(legacy[t]["venues"]))
            # the audit's before/after field reproduces the Phase 1 decision for every ticker
            out = ID.resolve(res, sc.DEXES, LISTS, sc.in_my_dexes)
            for t in legacy:
                self.assertEqual(out.asset(t)["phase1_tradfi"], legacy[t]["tradfi"], (seed, t))


def math_exp(x):
    import math
    return math.exp(x)


# --------------------------------------------------------------------------- liquidity
class Liquidity(unittest.TestCase):
    def coin(self, venues, trade_vol=None, best_vol=None):
        return {"venues": venues, "trade_vol": trade_vol, "best_vol": best_vol}

    def test_states(self):
        e = LQ.evaluate(self.coin({"hyperliquid": {"vol": 0.0}}, trade_vol=0.0, best_vol=0.0), MINE)
        self.assertEqual((e["state"], e["value"], e["basis"]), (LQ.KNOWN, 0.0, LQ.OBSERVED_ZERO))
        e = LQ.evaluate(self.coin({"lighter": {"vol": None}}), MINE)
        self.assertEqual((e["state"], e["value"], e["basis"]), (LQ.MISSING, None, "MISSING"))
        e = LQ.evaluate(self.coin({"dydx": {"vol": 9e6}}, best_vol=9e6), MINE)
        self.assertEqual((e["state"], e["value"]), (LQ.NOT_ON_TRADE_DEX, None))
        e = LQ.evaluate(self.coin({"hyperliquid": {"vol": 2e6}}, trade_vol=2e6, best_vol=2e6), MINE)
        self.assertEqual((e["state"], e["value"], e["basis"]), (LQ.KNOWN, 2e6, LQ.OBSERVED))
        e = LQ.evaluate(self.coin({}), MINE)                   # the built-in fallback list: no DEX data at all
        self.assertEqual(e["state"], LQ.MISSING)

    def test_merge_keeps_observed_zero_and_missing_apart(self):
        r = resolve(hl("ZEROV", 5.0, 0.0))
        self.assertEqual(r.coins["ZEROV"]["trade_vol"], 0.0)
        self.assertEqual(LQ.evaluate(r.coins["ZEROV"], MINE)["state"], LQ.KNOWN)
        r = resolve(lighter("LONLY", 4.0, None))
        self.assertIsNone(r.coins["LONLY"]["trade_vol"])
        self.assertEqual(LQ.evaluate(r.coins["LONLY"], MINE)["state"], LQ.MISSING)
        r = resolve(dydx("DONLY-USD", 4.0, 5e6))
        self.assertEqual(LQ.evaluate(r.coins["DONLY"], MINE)["state"], LQ.NOT_ON_TRADE_DEX)

    def test_missing_never_passes_the_gate(self):
        for c in (self.coin({"lighter": {"vol": None}}), self.coin({}), self.coin({"dydx": {"vol": 9e9}}, best_vol=9e9)):
            self.assertFalse(LQ.passes(c, 1e6, MINE))
            self.assertFalse(sc.liquid_enough(c))
        self.assertFalse(LQ.passes(self.coin({"hyperliquid": {"vol": 0.0}}, trade_vol=0.0), 1e6, MINE))
        self.assertTrue(LQ.passes(self.coin({"hyperliquid": {"vol": 2e6}}, trade_vol=2e6), 1e6, MINE))

    def test_gate_gives_the_legacy_answer_for_every_coin(self):
        rng = random.Random(3)
        for _ in range(2000):
            tv = rng.choice([None, 0.0, 0, float("nan"), rng.uniform(0, 3e6), 1e6, 999_999.9])
            c = self.coin({rng.choice(sc.DEXES): {"vol": tv}}, trade_vol=tv, best_vol=tv)
            legacy = (sc.liq_of(c) or 0) >= sc.CFG["min_dex_vol"]
            self.assertEqual(sc.liquid_enough(c), legacy, tv)

    def test_sorting_does_not_store_a_zero(self):
        c = self.coin({"lighter": {"vol": None}})
        self.assertEqual(LQ.sort_value(c, MINE), 0.0)
        self.assertIsNone(c["trade_vol"])                       # sorting changed nothing
        self.assertIsNone(LQ.stored(sc.liq_of(c)))
        self.assertEqual(LQ.stored(0.0), 0)
        self.assertEqual(LQ.stored(1234.6), 1235)

    def test_presentation_shows_missing_as_unavailable(self):
        with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('function usd(x){if(x==null)return"-"', html)     # null -> "-", never "$0"
        self.assertEqual(sc.usd(None), "-")
        src = inspect.getsource(sc.run)
        self.assertIn('LIQUIDITY.stored(c.get("best_vol"))', src)       # the radar table volume column

    def test_reason_codes(self):
        from v8 import common as C
        from v8 import ledger as LG
        L = LG.Ledger("t")
        C.liquidity_final(L, "A", self.coin({"hyperliquid": {"vol": 0.0}}, trade_vol=0.0), "x", 1e6, MINE)
        C.liquidity_final(L, "B", self.coin({"lighter": {"vol": None}}), "x", 1e6, MINE)
        C.liquidity_final(L, "C", self.coin({"dydx": {"vol": 9e6}}, best_vol=9e6), "x", 1e6, MINE)
        r = L.records
        self.assertEqual((r["A"]["d"], r["A"]["c"], r["A"]["o"]["basis"]),
                         ("NOT_EXECUTABLE", "DEX_VOLUME_BELOW_LEGACY_MIN", "OBSERVED_ZERO"))
        self.assertEqual((r["B"]["d"], r["B"]["c"], r["B"]["h"]), ("INSUFFICIENT_DATA", "DEX_VOLUME_MISSING", "MISSING"))
        self.assertEqual((r["C"]["d"], r["C"]["c"]), ("NOT_EXECUTABLE", "NOT_ON_TRADE_DEX"))


class NoHardcodedTickers(unittest.TestCase):
    def test_classifier_names_no_ticker(self):
        """The identity module decides from evidence; no ticker appears in its code (docstrings aside)."""
        tree = ast.parse(inspect.getsource(ID))
        doc_nodes = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and ast.get_docstring(node):
                doc_nodes.add(id(node.body[0].value))
        consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                  and id(n) not in doc_nodes]
        for t in ("QNT", "PURR", "BB", "XIAOMI", "ASTS", "BBIT"):
            self.assertFalse(any(t in c.split(":")[0].split() or c == t for c in consts), t)
        for t in sc.KNOWN_CRYPTO | sc.TRADFI:
            self.assertNotIn(t, [c for c in consts if c.isupper() and len(c) > 1 and c not in (
                "RWA", "COIN", ID.CRYPTO, ID.TRADFI, ID.AMBIGUOUS, ID.UNLABELED)], t)


if __name__ == "__main__":
    unittest.main()
