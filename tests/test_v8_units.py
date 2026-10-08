"""v8 Phase 1 unit tests: the audit's mirrors of legacy rules agree with the legacy code, the ledger's accounting,
data-health bases, provenance hashing, and that the audit can never break a scan.

Run from the repository root:  python -m unittest tests.test_v8_units -v"""
from __future__ import annotations

import json
import math
import os
import random
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "v8"))

import scanner as sc  # noqa: E402
import quant as Q  # noqa: E402
import smart as SM  # noqa: E402
from v8 import audit_quant, audit_radar, audit_smart, health as H, ledger as LG, parts, provenance  # noqa: E402
from v8 import identity as ID, registry as R, snapshot as SN, taxonomy as T  # noqa: E402
from v8.trace import TRACE, Recorder  # noqa: E402


class Mirrors(unittest.TestCase):
    """Where the audit re-derives a legacy rule, it must agree with the legacy function on every input."""

    def test_explain_plan_matches_build_plan(self):
        rng = random.Random(5)
        n_rej = 0
        for i in range(4000):
            mid = math.exp(rng.uniform(-6, 9))
            atr = mid * rng.uniform(0.001, 0.08)
            w = mid * rng.uniform(0, 0.02)
            lo, hi = mid - w, mid + w
            if rng.random() < 0.1:
                lo, hi = hi, lo
            stop = mid - mid * rng.uniform(-0.01, 0.12)
            trig = mid * rng.uniform(0.98, 1.05) if rng.random() < 0.3 else None
            tp_r = (rng.uniform(0.5, 3), 3.0, 5.0)
            sk = rng.choice([1.0, 0.8, 1.3, None])
            last = mid * rng.uniform(0.85, 1.25)
            px = last * rng.uniform(0.98, 1.02) if rng.random() < 0.5 else None
            sp = {"id": "X", "base": "PB", "name": "x", "short": "x"}
            if rng.random() < 0.3:
                sp["stop_atr"] = (rng.uniform(0.5, 1.5), rng.uniform(2, 5))
            if rng.random() < 0.3:
                sp["max_risk"] = rng.uniform(0.01, 0.1)
            a = {"atr": atr, "last": last}
            plan = sc.build_plan(sp, a, lo, hi, stop, trig, tp_r=tp_r, sk=sk, px=px)
            info = {"lv": [lo, hi, stop, trig], "tp_r": list(tp_r), "sk": sk, "px": px, "atr": atr, "last": last,
                    "stop_atr": sp.get("stop_atr"), "max_risk": sp.get("max_risk")}
            code, _, _ = audit_radar.explain_plan(info, sc.CFG)
            self.assertEqual(plan is None, code is not None, (i, info, code))
            n_rej += plan is None
        self.assertGreater(n_rej, 200)

    def test_tradfi_reason_matches_is_tradfi(self):
        names = [None, "Apple Inc", "Bitcoin", "SPDR S&P 500 ETF", "Gold Token", "Quant", "Purr", "Acme Holdings",
                 "Natural Gas", "Uranium Trust", "Dogecoin", "Class A shares"]
        tickers = sorted(sc.TRADFI)[:40] + sorted(sc.KNOWN_CRYPTO)[:60] + ["EURUSD", "USDJPY", "FOO", "BAR", "QNT",
                                                                          "QNTX", "BB", "PURR", "ACME", "XAU"]
        for t in tickers:
            for n in names:
                self.assertEqual(R.tradfi_reason(t, n)[0], sc.is_tradfi(t, n), (t, n))

    def test_canon_reason_matches_canon(self):
        for s in ["kPEPE", "1000PEPE", "1000000MOG", "1MBABYDOGE", "BBIT", "VANATOKEN", "btc", "ETH", "1000BONK",
                  "kBONK", "LIGHTER", "1INCH", "0G", "X"]:
            t, m, why = R.canon_reason(s)
            self.assertEqual((t, m), sc.canon(s), s)
            self.assertTrue(why)
        self.assertEqual(R.canon_reason("kPEPE")[2], "MULTIPLIER:x1000")
        self.assertEqual(R.canon_reason("BBIT")[2], "ALIAS:BBIT")

    def test_quant_why_not_matches_signals(self):
        fx_mod = __import__("fake_exchange")
        fx = fx_mod.FakeExchange(n_coins=8, days=120, seed=3)
        for coin in fx.coins:
            c4 = sc.agg_tf(fx.c15[coin], 4 * 3600)[:-1]
            tf = Q.trend_feats(c4)
            for i in range(60, len(c4)):
                s = Q.sig_trend_ema(tf, i)
                w = audit_quant._why_not_trend(Q, tf, i)
                if s:
                    self.assertIsNone(w)
            cd = Q.to_daily(c4)
            f = Q.daily_feats(cd)
            for k in range(len(cd)):
                s = Q.sig_tsmom(f, k)
                w = audit_quant._why_not_tsmom(Q, f, k)
                self.assertFalse(s and w is not None)
                if w is not None:
                    self.assertGreater(w, Q.CFG["max_stop"])

    def test_trader_reasons_match_select_traders(self):
        rng = random.Random(9)
        for trial in range(30):
            rows = []
            for i in range(rng.randint(0, 60)):
                av = rng.choice([5e3, 3e4, 4e5, 2e6])
                rows.append({"ethAddress": rng.choice(["0x%040x" % i, None, "abc"]), "accountValue": str(av),
                             "windowPerformances": [
                                 ["month", {"pnl": str(rng.uniform(-0.3, 0.3) * av), "roi": "0",
                                            "vlm": str(rng.choice([0, 1e5, 1e6, 1e9]))}],
                                 ["allTime", {"pnl": str(rng.uniform(-1e5, 3e6)), "roi": "0", "vlm": "1"}]]})
            board = {"leaderboardRows": rows}
            cfg = dict(SM.CFG, max_traders=rng.choice([3, 200]))
            traders = SM.select_traders(board, cfg)
            snap = {t["id"]: {"av": 1.0, "pos": {}} for t in traders}
            counts, ok = audit_smart.trader_reasons(board, traders, snap, cfg)
            self.assertTrue(ok, trial)
            self.assertEqual(sum(counts.values()), len(rows))
            self.assertEqual(counts["TRADER_SELECTED"], len(traders))


class RegistryAgainstAdapters(unittest.TestCase):
    """On every DEX payload of the parity fixture, the registry's reading of each raw market agrees with the
    legacy adapter: what the adapter keeps is SELECTED, a duplicate, a price conflict or (Phase 2) part of a separate
    exposure that was not admitted; what it skips has the adapter's own reason; nothing is lost or collapsed."""

    def test_registry_reconciles_with_build_universe(self):
        import legacy_parity as LP
        PX, _, _ = LP._make_exchange()
        fx = PX()
        old = sc.FETCH, sc.KNOWN_CRYPTO
        sc.FETCH = fx.fetch
        sc.KNOWN_CRYPTO = sc.KNOWN_CRYPTO | LP.fixture_known_crypto(fx)     # the fixture world (v8 Phase 3)
        try:
            coins, status, ok = sc.build_universe()
            reg = R.build(TRACE, coins, status, ok, fx.now)
        finally:
            sc.FETCH, sc.KNOWN_CRYPTO = old
        self.assertTrue(ok)
        cs = reg["contracts"]
        self.assertEqual(R.counts(reg)["adapter_mismatches"], 0)
        for dex in sc.DEXES:
            rows = TRACE.rows[dex]
            kept = sorted(f"{dex}:{r['sym']}" for r in rows)
            got = sorted(c["id"] for c in cs if c["venue"] == dex and c["legacy"] in ID.KEPT_STATES)
            self.assertEqual(kept, got, dex)
        for t, c in coins.items():
            for dex, v in c["venues"].items():
                cid = f"{dex}:{v['sym']}"
                self.assertEqual(next(x for x in cs if x["id"] == cid)["legacy"], "SELECTED", cid)
        self.assertEqual(len({c["id"] for c in cs}), len(cs))

    def test_failed_adapter_and_fallback(self):
        rec = Recorder()
        rec.payload("lighter", "books", {"order_book_details": [{"symbol": "ONLYLT", "mark_price": 1.0}]})
        rec.universe_rows({"lighter": None})             # the adapter raised after the fetch
        reg = R.build(rec, {}, {"lighter": {"ok": False}}, True, 0)
        self.assertEqual(reg["contracts"][0]["legacy"], "ADAPTER_FAILED")
        self.assertEqual(reg["assets"]["ONLYLT"]["legacy"], "VENUE_ADAPTER_FAILED")
        # no market list at all: the built-in coin list, every coin still accounted for
        old = sc.FETCH

        def down(url, body=None, timeout=25):
            raise sc.HttpError(503, "down")
        sc.FETCH = down
        try:
            coins, status, ok = sc.build_universe()
        finally:
            sc.FETCH = old
        self.assertFalse(ok)
        reg = R.build(TRACE, coins, status, ok, 0)
        self.assertTrue(reg["fallback"])
        self.assertEqual(set(reg["assets"]), set(coins))
        self.assertIn(["FALLBACK_UNIVERSE", {}], reg["events"])

    def test_duplicate_raw_symbols_are_not_collapsed(self):
        rec = Recorder()
        rec.payload("variational", "stats", {"listings": [
            {"ticker": "ABC", "mark_price": 1.0, "volume_24h": 5e6}, {"ticker": "ABC", "mark_price": 1.0, "volume_24h": 1e6}]})
        rows = [sc._venue("ABC", "variational", "ABC", 1.0, price=1.0, vol=5e6, name="ABC"),
                sc._venue("ABC", "variational", "ABC", 1.0, price=1.0, vol=1e6, name="ABC")]
        rec.universe_rows({"variational": rows})
        from v8 import identity as ID
        res = ID.resolve({"variational": rows}, sc.DEXES, ID.Lists(sc.TRADFI, sc.KNOWN_CRYPTO, sc.is_fx,
                                                                   sc.TRADFI_NAME), sc.in_my_dexes)
        rec.identity(res)
        coins = res.coins
        self.assertIs(coins["ABC"]["venues"]["variational"], rows[0])
        reg = R.build(rec, coins, {"variational": {"ok": True}}, True, 0)
        ids = [c["id"] for c in reg["contracts"]]
        self.assertEqual(ids, ["variational:ABC", "variational:ABC#2"])
        self.assertEqual([c["legacy"] for c in reg["contracts"]], ["SELECTED", "DUPLICATE_NOT_SELECTED"])


class Health(unittest.TestCase):
    def test_basis(self):
        self.assertEqual(H.basis(None), H.MISSING_VALUE)
        self.assertEqual(H.basis(0), H.OBSERVED_ZERO)
        self.assertEqual(H.basis("0"), H.OBSERVED_ZERO)
        self.assertEqual(H.basis(float("nan")), H.MISSING_VALUE)
        self.assertEqual(H.basis("x"), H.MISSING_VALUE)
        self.assertEqual(H.basis(3.5), H.OBSERVED)

    def test_liquidity_tells_missing_from_zero(self):
        """Phase 2 moved the liquidity states to v8.liquidity (tests/test_v8_identity.py covers them)."""
        from v8 import liquidity as LQ
        mine = sc.CFG["trade_dexes"]
        self.assertEqual(LQ.evaluate({"venues": {"hyperliquid": {"vol": 0.0}}, "trade_vol": 0.0}, mine)["basis"],
                         H.OBSERVED_ZERO)
        self.assertEqual(LQ.evaluate({"venues": {"lighter": {"vol": None}}}, mine)["state"], LQ.MISSING)
        self.assertEqual(LQ.evaluate({"venues": {"dydx": {"vol": 9e6}}}, mine)["state"], LQ.NOT_ON_TRADE_DEX)

    def test_funding_default_is_identifiable(self):
        self.assertEqual(H.funding({"venues": {"lighter": {}}}), (H.ASSUMED_DEFAULT, None))
        self.assertEqual(H.funding({"venues": {"hyperliquid": {"funding8h": 0.0}}}), (H.OBSERVED, 0.0))

    def test_worst_and_contract_state(self):
        self.assertEqual(H.worst([T.HEALTHY, T.STALE, T.MISSING]), T.MISSING)
        self.assertEqual(H.worst([T.CONFLICTED, T.MISSING]), T.CONFLICTED)
        self.assertEqual(H.contract_state(H.OBSERVED, H.OBSERVED, source_ts=0, receive_ts=10_000), T.STALE)
        self.assertEqual(H.contract_state(H.OBSERVED, H.MISSING_VALUE), T.MISSING)
        self.assertEqual(H.contract_state(H.OBSERVED, H.OBSERVED, conflicted=True), T.CONFLICTED)


class Ledger(unittest.TestCase):
    def test_accounting(self):
        L = LG.Ledger("x")
        L.expect(["A", "B", "C"])
        L.final("A", "NO_STRATEGY_SIGNAL", "signal")
        L.final("A", "RADAR_PICK", "publish")          # a second final word is a defect, the first one stands
        L.final("Z", "RADAR_PICK", "publish")
        cov = L.coverage()
        self.assertEqual(cov["unaccounted"], 2)
        self.assertEqual(cov["unaccounted_assets"], ["B", "C"])
        self.assertEqual(cov["outside_input"], ["Z"])
        self.assertEqual(cov["duplicates"], [["A", "RADAR_PICK"]])
        self.assertEqual(L.records["A"]["c"], "NO_STRATEGY_SIGNAL")
        with self.assertRaises(ValueError):
            L.final("B", "SELECTED", "x")            # a contract state is not a disposition
        with self.assertRaises(KeyError):
            L.final("B", "FILTERED", "x")            # no generic code

    def test_expand_has_every_event_field(self):
        L = LG.Ledger("radar")
        L.expect(["A"])
        L.final("A", "DEX_VOLUME_BELOW_LEGACY_MIN", "stage2", o={"trade_vol": 5e5}, th={"min": 1e6},
                k=["hyperliquid:A"])
        hdr = {"scan_id": "s", "ts": 1, "git_sha": "g", "config_hashes": {"radar": "c"},
               "engine_versions": {"radar": "5"}}
        ev = list(LG.expand(L.to_part(), hdr))[0]
        for k in ("scan_id", "ts", "engine", "stage", "asset", "contracts", "disposition", "reason_code", "reason",
                  "observed", "rule", "health", "source", "git_sha", "config_hash", "engine_version"):
            self.assertIn(k, ev)
        self.assertEqual(ev["disposition"], T.NOT_EXECUTABLE)
        self.assertIn("500.0k", ev["reason"])


class Provenance(unittest.TestCase):
    def test_config_hash_is_stable_and_ignores_schedule(self):
        h1 = provenance.config_hash("radar")
        self.assertEqual(h1, provenance.config_hash("radar"))
        old = dict(sc.CFG)
        try:
            sc.CFG["schedule_minute"], sc.CFG["schedule_every_min"] = 33, 5
            self.assertEqual(provenance.config_hash("radar"), h1)
            sc.CFG["min_dex_vol"] = 2e6
            self.assertNotEqual(provenance.config_hash("radar"), h1)
        finally:
            sc.CFG.clear()
            sc.CFG.update(old)
        for e in ("quant", "swing", "day", "smart", "universe"):
            self.assertEqual(len(provenance.config_hash(e)), 64, e)

    def test_no_secret_in_config(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "sekret-123", "TELEGRAM_BOT_TOKEN": "tok-456"}):
            for e in ("radar", "quant", "swing", "smart"):
                s = json.dumps(provenance.canonical(provenance.engine_config(e)))
                self.assertNotIn("sekret-123", s)
                self.assertNotIn("tok-456", s)
                self.assertNotIn(" at 0x", s)          # no memory addresses

    def test_hard_coded_quant_authority_is_exposed(self):
        a = provenance.strategy_authority()
        self.assertEqual(a["quant_runtime_order"], ["TSMOM", "TREND_EMA", "XSMOM"])
        self.assertEqual(a["research_final"], ["TSMOM", "TREND_EMA", "XSMOM"])
        self.assertTrue(a["research_verdict_preassigned_live"])
        self.assertEqual({a["research_file_verdicts"][k] for k in a["research_final"]}, {"live"})
        self.assertEqual(len(a["files"]["tools/research/qexport.py"]), 64)

    def test_scan_id(self):
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "2"}, clear=False):
            os.environ.pop("V8_SCAN_ID", None)
            self.assertEqual(provenance.scan_id(5), "gh-77-2")


class NeverBreaksTheScan(unittest.TestCase):
    def test_safe_audit_swallows_errors(self):
        tmp = tempfile.mkdtemp()
        try:
            def boom():
                raise RuntimeError("audit bug")
            body = parts.safe_audit("radar", tmp, boom, ts=1)
            self.assertFalse(body["ok"])
            self.assertIn("audit bug", body["error"])
            self.assertFalse(parts.read(tmp, "radar")["ok"])
            snap, _, _, _ = SN.write(tmp)
            self.assertEqual(snap["coverage"]["engines"]["radar"]["status"], "AUDIT_FAILED")
            self.assertEqual(snap["coverage"]["engines"]["quant"]["status"], "MISSING_PART")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_recorder_never_raises(self):
        r = Recorder()
        r.live = True
        r.plan_reject(None, None, None, None, None, None)
        r.filter_reject(None, None)
        r.universe_rows(None)
        r.candle_miss("X", "1h", None)
        self.assertEqual(r.plans, [])

    def test_scan_survives_a_broken_audit(self):
        fxm = __import__("fake_exchange")
        fx = fxm.FakeExchange(n_coins=24, days=4, seed=2)
        restore = fxm.install(fx)
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch("v8.audit_radar.radar_part", side_effect=RuntimeError("broken")):
                out = sc.run(os.path.join(tmp, "s"), replay_days=0)
            self.assertIn("picks", out)
            self.assertTrue(os.path.exists(os.path.join(tmp, "s", "data", "latest.json")))
            self.assertFalse(parts.read(os.path.join(tmp, "s"), "radar")["ok"])
            self.assertTrue(parts.read(os.path.join(tmp, "s"), "universe")["ok"])
        finally:
            restore()
            shutil.rmtree(tmp, ignore_errors=True)


class RadarMapping(unittest.TestCase):
    """The radar's later stages on hand-made inputs (the parity fixture is too small to hit every one)."""

    def run_part(self, n=6, stage2_n=2, gate=None, blocks=None, finals=None, picks=(), watch=(), extras=()):
        coins = {f"C{i}": {"t": f"C{i}", "venues": {"hyperliquid": {"sym": f"C{i}", "vol": 5e6, "tradfi": False,
                                                                    "funding8h": 1e-5}},
                           "tradfi": False, "trade_vol": 5e6, "best_vol": 5e6, "identity": "VERIFIED_CRYPTO"}
                 for i in range(n)}
        s1 = {t: {"score": 10 - i, "src": "mexc"} for i, t in enumerate(coins)}
        ranked = list(coins)
        cands = ranked[:stage2_n] + list(extras)
        A = {t: {"atr": 1.0, "last": 1.0} for t in cands}
        sigs, best = [], {}
        for t, blk in (blocks or {}).items():
            x = {"t": t, "s": {"sid": "PB"}, "final": (finals or {}).get(t, 60.0), "block": blk}
            sigs.append(x)
            if not blk:
                best[t] = x
        pick_sigs = [best[t] for t in picks]
        watch_sigs = [best[t] for t in watch]
        old = dict(sc.CFG)
        sc.CFG["stage2_n"] = stage2_n
        try:
            p = audit_radar.radar_part(0, coins, True, coins, {}, s1, ranked, cands, list(extras), {}, A, sigs, best,
                                       pick_sigs, watch_sigs, gate)
        finally:
            sc.CFG.clear()
            sc.CFG.update(old)
        return {r["a"]: r for r in p["records"]}, p

    def test_stages_and_blocks(self):
        g = "BTC's 4-hour trend is down"
        r, p = self.run_part(n=8, stage2_n=4, gate=g, extras=("C6",),
                             blocks={"C0": None, "C1": None, "C2": f"Market gate: {g}",
                                     "C3": "Pullback is testing: paper-traded only", "C6": None, "C7": None},
                             finals={"C0": 80.0, "C1": 75.0, "C6": 55.0, "C7": 40.0}, picks=("C0",), watch=("C6",))
        self.assertEqual(r["C0"]["c"], "RADAR_PICK")
        self.assertEqual(r["C1"]["c"], "OUTPUT_TOP_N_CUTOFF")
        self.assertEqual(r["C2"]["c"], "MARKET_GATE_BLOCKED")
        self.assertEqual(r["C3"]["c"], "STRATEGY_NOT_PASSED")
        self.assertEqual(r["C4"]["c"], "RADAR_STAGE2_NOT_SELECTED")
        self.assertEqual(r["C4"]["o"]["liquid_rank"], 5)
        self.assertEqual(r["C5"]["c"], "RADAR_STAGE2_NOT_SELECTED")
        self.assertEqual(r["C6"]["c"], "RADAR_WATCH")
        self.assertIn("EXTRA_DEEP_DIVE", r["C6"]["x"])
        self.assertEqual(r["C7"]["c"], "SCORE_BELOW_THRESHOLD")   # a 1h/4h-strategy signal outside stage 2
        self.assertEqual(p["coverage"]["unaccounted"], 0)
        self.assertEqual(p["problems"], [])

    def test_forward_variant_and_adjustment(self):
        r, _ = self.run_part(n=3, stage2_n=3, blocks={"C0": "new variant in its live test: paper-traded only",
                                                      "C1": "2 stop-outs on C1 in 24h: cooling down until 10:00 UTC"})
        self.assertEqual(r["C0"]["c"], "VARIANT_FORWARD_TEST")
        self.assertEqual(r["C1"]["c"], "ADJUSTMENT_BLOCKED")
        self.assertEqual(r["C2"]["c"], "NO_STRATEGY_SIGNAL")


class TaxonomyDoc(unittest.TestCase):
    def test_doc_lists_every_code(self):
        import re
        with open(os.path.join(ROOT, "docs", "v8", "disposition-taxonomy.md")) as fh:
            doc = fh.read()
        listed = set(re.findall(r"^\| `([A-Z0-9_]+)` \|", doc, re.M))
        codes = set(T.REASONS) | set(T.STEPS) | set(T.TRADER_REASONS) | set(T.DISPOSITIONS) | \
            set(T.IDENTITY_STATES) | set(T.RETIRED_IDENTITY_REASONS)
        self.assertEqual(listed, codes)
        self.assertEqual(set(T.DISPOSITIONS) <= set(re.findall(r"`([A-Z_]+)`", doc)), True)


class Archive(unittest.TestCase):
    def test_append_only(self):
        tmp = tempfile.mkdtemp()
        try:
            a = SN.ArchiveDir(tmp)
            p = a.append("gh-1-1", b"x")
            self.assertTrue(p and os.path.exists(p))
            self.assertIsNone(a.append("gh-1-1", b"y"))
            with open(p, "rb") as fh:
                self.assertEqual(fh.read(), b"x")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
