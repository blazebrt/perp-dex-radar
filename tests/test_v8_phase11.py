"""v8 Phase 11: the unified decision engine - TRADE / WATCH / AVOID semantics, every authority gate, Phase 9 and Phase 10
integration, sections, ranking, Top-5 behaviour, emerging and funding opportunities, the Analyzer's same-engine contract,
the Decision Trace, change explanation, empty states, determinism, authority hashing and the live audit integration."""
import ast
import copy
import glob
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from v8 import decision as DE  # noqa: E402
from v8 import portfolio_risk as PR  # noqa: E402

DAY = 86400
T0 = 1_780_012_800 // DAY * DAY
N_BARS = 50
AS_OF = T0 + N_BARS * DAY
NAMES = ["BTC", "HI", "TWIN", "LO", "NEG", "ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF"]


def make_returns(n=N_BARS, seed=7):
    """Deterministic daily closes: BTC is the market; HI/TWIN co-move with it; the rest are independent."""
    rng = random.Random(seed)
    px = {a: 100.0 for a in NAMES}
    out = {a: [] for a in NAMES}
    for k in range(n):
        m = rng.gauss(0, .03)
        common = rng.gauss(0, .01)
        for a in NAMES:
            if a == "BTC":
                r = m
            elif a in ("HI", "TWIN"):
                r = 1.2 * m + common + rng.gauss(0, .004)
            elif a == "NEG":
                r = -m + rng.gauss(0, .01)
            else:
                r = rng.gauss(0, .03)
            px[a] *= math.exp(r)
            out[a].append([T0 + k * DAY, px[a]])
    return out


RET = make_returns()
STRATS = {
    "TSMOM": {"tf": "1d", "hold_h": 504, "deployment_state": "LEGACY_HOLDOVER", "research_state": "INSUFFICIENT_EVIDENCE"},
    "REQ": {"tf": "1d", "hold_h": 48, "deployment_state": "ACTIVE_REQUALIFIED", "research_state": "REQUALIFIED"},
    "REQ4H": {"tf": "4h", "hold_h": 24, "deployment_state": "ACTIVE_REQUALIFIED", "research_state": "REQUALIFIED"},
    "DIS": {"tf": "1d", "hold_h": 48, "deployment_state": "DISABLED", "research_state": "INSUFFICIENT_EVIDENCE"},
    "REJ": {"tf": "1d", "hold_h": 48, "deployment_state": "LEGACY_HOLDOVER", "research_state": "REJECTED"},
    "PAPER": {"tf": "1d", "hold_h": 48, "deployment_state": "PAPER_ONLY", "research_state": "REQUALIFIED"},
}


def rec(asset, identity="VERIFIED_CRYPTO", liq=("KNOWN", 5e6, True), flags=(), dq="HEALTHY", price=100.0, **kw):
    r = {"asset": asset, "name": asset, "identity": identity, "identity_reason": None, "anomaly_flags": list(flags),
         "exposure_check_state": "OK", "data_quality": dq, "discovery_visible": True,
         "contracts": [[f"hyperliquid:{asset}", "SELECTED"]], "venues": ["hyperliquid"], "discovery_stage": "CHARTED_1H",
         "price": price, "priority_lane": "CORE", "first_seen": None, "listing_age": {"state": "UNKNOWN"},
         "execution_liquidity": {"state": liq[0], "observed_value": liq[1], "threshold": 1e6, "passes": liq[2]}}
    r.update(kw)
    return r


def contract(asset, venue="hyperliquid", fund=0.0001, vol=5e6, npx=100.0, health="HEALTHY", admitted=True,
             rcv=AS_OF - 60):
    return {"id": f"{venue}:{asset}", "venue": venue, "asset": asset, "type": "perp", "active": True, "price": npx,
            "npx": npx, "vol": vol, "fund8h": fund, "fund_iv_h": 8, "src_ts": rcv, "rcv_ts": rcv, "health": health,
            "admitted": admitted, "legacy": "SELECTED"}


def sig(strategy="REQ", d=1, kind="NEW", age=3600, stop=0.05, trade_id=None):
    return {"strategy": strategy, "direction": d, "stop_pct": stop, "trail_pct": 0.0, "bar_close_t": AS_OF - age,
            "kind": kind, "trade_id": trade_id}


def book_position(pid, asset, d=1, notional=50.0, strategy="TSMOM", rate=0.0, **kw):
    p = {"id": pid, "asset": asset, "strategy": strategy, "direction": d, "mark": 100.0,
         "stop": 100.0 * (1 - d * 0.05), "notional": notional, "entered": True, "actionability": "ACTIONABLE",
         "liquidity": {"state": "KNOWN", "volume": 5e6}, "funding": {"state": "OBSERVED_ZERO", "rate_8h": 0.0}
         if rate == 0 else {"state": "OBSERVED", "rate_8h": rate}, "hold_hours_remaining": 24.0}
    p.update(kw)
    return p


def portfolio(positions=(), equity=500.0):
    return {"equity": equity, "as_of": AS_OF, "positions": list(positions), "returns": copy.deepcopy(RET),
            "sizing": {"basis": "PAGE_DEFAULT_SIZING", "account": equity, "risk_per_trade": .005}}


def snapshot(records, signals=None, contracts=None, book=(), prov=None, strategies=None, previous=None, pf="default"):
    contracts = contracts if contracts is not None else [contract(r["asset"]) for r in records]
    pv = {"schema": "v8.discovery/1", "fallback_universe": False, "available_venue_discovery_qualified": True, "venues_failed_names": [],
          "coverage_state": "FULL", "generated_at": AS_OF, "identity_version": "v8.identity/4"}
    pv.update(prov or {})
    p = portfolio(book) if pf == "default" else pf
    return {"as_of": AS_OF, "discovery": {"assets": records, "provenance": pv, "venues": {}},
            "contracts": contracts, "trade_dexes": ["hyperliquid", "lighter", "aster", "variational"],
            "signals": signals or {}, "strategies": copy.deepcopy(strategies or STRATS), "portfolio": p,
            "sizing": (p or {}).get("sizing") or {"basis": "PAGE_DEFAULT_SIZING", "account": 500.0, "risk_per_trade": .005},
            "phase10_state": PR.evaluate(p)["state"] if p else None,
            "inputs_as_of": {"discovery": AS_OF, "quant": AS_OF, "portfolio": AS_OF},
            "authorities": {"identity_config_hash": "i" * 64, "strategy_policy_hash": "s" * 64}, "previous": previous}


def one(asset="HI", signal=None, **kw):
    """A one-asset snapshot and the decision of its directional candidate."""
    s = snapshot([rec(asset, **kw.pop("rec", {}))], {asset: [signal or sig()]}, **kw)
    doc = DE.build(s)
    return doc, next(c for c in doc["candidates"] if c["type"] == DE.DIRECTIONAL)


def canon(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False)


def steps(c):
    return {g["step"]: g for g in c["trace"]}


# The reviewed Phase 11 policy values (states, gates, sections, ranking rules): the independent review approved them
# unchanged. Only the review status and its statement changed in the correction; any value change fails here.
REVIEWED_VALUES_DIGEST = "2c788403b1f4f65f4d591a1075aeebceba24782d94d28a725a47f9cb19df8914"


class Policy(unittest.TestCase):
    def test_policy_is_governed_and_reviewed(self):
        p = DE.load_policy()
        self.assertEqual((p["schema"], p["review_status"]), ("v8.decision-policy/1", "POLICY_REVIEWED_INITIAL_V1"))
        self.assertEqual(DE.REVIEW_STATUS, "POLICY_REVIEWED_INITIAL_V1")
        for sec in DE.SECTION_KEYS:
            for k, e in p[sec].items():
                self.assertEqual(e["basis"], "POLICY", f"{sec}.{k}")
        st = p["statement"].lower()
        self.assertIn("none is learned, fitted, optimized or statistically validated", st)
        self.assertIn("reviewed policy choice", st)
        for claim in ("is validated", "is optimized", "is backtested", "is proven", "are validated", "empirically validated",
                      "statistically proven", "are optimized", "were backtested", "is optimal"):
            self.assertNotIn(claim, st)
        self.assertEqual(DE.policy_hash(p), DE.policy_hash(DE.load_policy()))

    def test_reviewed_values_are_unchanged(self):
        p = DE.load_policy()
        self.assertEqual(DE.digest({s: {k: e["value"] for k, e in p[s].items()} for s in DE.SECTION_KEYS}),
                         REVIEWED_VALUES_DIGEST)
        self.assertEqual(p["portfolio"]["after_state_effects"]["value"]["APPROACHING_LIMITS"], "CAP_WATCH")
        self.assertEqual(p["portfolio"]["after_state_effects"]["value"]["LIMIT_BREACHED"], "AVOID")

    def test_review_status_is_exactly_the_reviewed_value(self):
        good = DE.load_policy()
        DE.validate_policy(copy.deepcopy(good))
        for label, value in (("old pending", "POLICY_PROPOSED_PENDING_REVIEW"), ("arbitrary", "REVIEWED_BY_ME"),
                             ("fake validated", "VALIDATED"), ("empirically", "POLICY_EMPIRICALLY_VALIDATED"),
                             ("lower case", "policy_reviewed_initial_v1"), ("empty", ""), ("none", None), ("number", 1)):
            with self.subTest(status=label):
                p = copy.deepcopy(good)
                p["review_status"] = value
                with self.assertRaises(DE.PolicyError):
                    DE.validate_policy(p)
        p = copy.deepcopy(good)
        del p["review_status"]
        with self.assertRaises(DE.PolicyError):
            DE.validate_policy(p)

    def test_unsafe_or_malformed_policy_is_refused(self):
        good = DE.load_policy()
        cases = {
            "legacy can trade": lambda q: q["strategy_authority"]["trade_deployment_states"]["value"].append("LEGACY_HOLDOVER"),
            "insufficient research can trade": lambda q: q["strategy_authority"]["trade_research_states"]["value"].append(
                "INSUFFICIENT_EVIDENCE"),
            "disabled not avoided": lambda q: q["strategy_authority"]["avoid_deployment_states"].update(value=[]),
            "breach not avoid": lambda q: q["portfolio"]["after_state_effects"]["value"].update(LIMIT_BREACHED="CAP_WATCH"),
            "unevaluable passes": lambda q: q["portfolio"]["after_state_effects"]["value"].update(UNEVALUABLE="PASS"),
            "missing liquidity passes": lambda q: q["execution"]["effects"]["value"].update(MISSING="PASS"),
            "below gate passes": lambda q: q["execution"]["effects"]["value"].update(KNOWN_BELOW_GATE="PASS"),
            "emerging trade": lambda q: q["states"]["max_state_by_type"]["value"].update(EMERGING_OBSERVATION="TRADE"),
            "funding trade": lambda q: q["states"]["max_state_by_type"]["value"].update(FUNDING_SPREAD="TRADE"),
            "six trades": lambda q: q["sections"]["best_trades_now"]["value"].update(max=6),
            "watch in best": lambda q: q["sections"]["best_trades_now"]["value"].update(states=["TRADE", "WATCH"]),
            "unknown rank field": lambda q: q["ranking"]["best_trades_now"]["value"].insert(0, ["market_cap", "desc"]),
            "volume rank field": lambda q: q["ranking"]["emerging_opportunities"]["value"].insert(0, ["volume", "desc"]),
            "text desc": lambda q: q["ranking"]["best_trades_now"]["value"].__setitem__(4, ["asset", "desc"]),
            "no tie-break": lambda q: q["ranking"]["funding_opportunities"].update(value=[["net_carry", "desc"]]),
            "identity relaxed": lambda q: q["identity"]["trade_identity"].update(value="UNVERIFIED"),
            "conflict allowed": lambda q: q["exposure"]["conflict_flags"].update(value=[]),
            "precedence": lambda q: q["states"]["precedence"].update(value=["TRADE", "WATCH", "AVOID"]),
            "empirical basis": lambda q: q["signal"]["max_age_s"].update(basis="EMPIRICALLY_VALIDATED"),
            "status": lambda q: q.update(review_status="POLICY_PROPOSED_PENDING_REVIEW"),
            "extra key": lambda q: q["signal"].update(extra={"value": 1, "basis": "POLICY", "rationale": "x"}),
            "warning as evidence": lambda q: q["emerging"]["warning_flags"]["value"].append("NEW_LISTING"),
            "funding default": lambda q: q["funding"]["venue_rule"].update(value="FUND_DEFAULT"),
        }
        for label, mutate in cases.items():
            with self.subTest(policy=label):
                p = copy.deepcopy(good)
                mutate(p)
                with self.assertRaises(DE.PolicyError):
                    DE.validate_policy(p)

    def test_no_threshold_literal_in_the_engine(self):
        tree = ast.parse((ROOT / "v8/decision.py").read_text(encoding="utf-8"))
        allowed = {0, 1, 2, 5, 8.0, 10, 20, 300, 500}
        skip = {id(n) for f in tree.body if isinstance(f, ast.FunctionDef) and f.name == "validate_policy"
                for n in ast.walk(f)}
        found = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and id(n) not in skip
                 and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)}
        self.assertLessEqual(found, allowed, found - allowed)

    def test_rule_change_changes_policy_and_authority_hash(self):
        s = snapshot([rec("HI")], {"HI": [sig()]})
        a = DE.build(s)
        p = copy.deepcopy(DE.load_policy())
        p["ranking"]["best_trades_now"]["value"] = [["signal_age_s", "asc"], ["asset", "asc"]]
        b = DE.build(s, p)
        self.assertNotEqual(a["policy_hash"], b["policy_hash"])
        self.assertNotEqual(a["authority"]["authority_hash"], b["authority"]["authority_hash"])
        self.assertEqual(a["implementation_hash"], hashlib.sha256((ROOT / "v8/decision.py").read_bytes()).hexdigest())


class States(unittest.TestCase):
    def test_trade_watch_avoid(self):
        _, c = one(signal=sig("REQ"))
        self.assertEqual(c["state"], DE.TRADE)
        self.assertEqual((c["blockers"], c["caps"], c["missing_authorities"]), ([], [], []))
        self.assertTrue({g["step"] for g in c["explanation"]["why_trade"]} >= {"IDENTITY", "STRATEGY_AUTHORITY",
                                                                            "EXECUTION_LIQUIDITY", "FUNDING",
                                                                            "PROPOSED_TRADE", "PORTFOLIO_AFTER"})
        _, c = one(signal=sig("TSMOM"))
        self.assertEqual(c["state"], DE.WATCH)
        self.assertEqual(c["caps"], ["STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT"])
        self.assertEqual(c["explanation"]["to_become_trade"][0]["step"], "STRATEGY_AUTHORITY")
        _, c = one(signal=sig("REQ"), rec={"identity": "UNVERIFIED"})
        self.assertEqual(c["state"], DE.AVOID)
        self.assertEqual((c["blocking_step"], c["blockers"]), ("IDENTITY", ["IDENTITY_NOT_VERIFIED"]))

    def test_unknown_never_becomes_trade(self):
        variants = {
            "funding missing": dict(contracts=[contract("HI", fund=None)]),
            "funding stale": dict(contracts=[contract("HI", rcv=AS_OF - 7200)]),
            "funding contract unhealthy": dict(contracts=[contract("HI", health="STALE")]),
            "funding contract not admitted": dict(contracts=[contract("HI", admitted=False)]),
            "liquidity missing": dict(rec={"execution_liquidity": {"state": "MISSING", "observed_value": None,
                                                                   "threshold": 1e6, "passes": False}}),
            "no coin record": dict(rec={"execution_liquidity": {"state": "NO_COIN_RECORD", "observed_value": None,
                                                                "threshold": 1e6, "passes": False}}),
            "price missing": dict(rec={"price": None}),
            "dependence missing": dict(pf=dict(portfolio(), returns={a: v for a, v in RET.items() if a != "HI"})),
            "portfolio missing": dict(pf=None),
            "exposure degraded": dict(rec={"anomaly_flags": ["EXPOSURE_METADATA_DEGRADED"]}),
            "venue degraded": dict(rec={"data_quality": "DATA_DEGRADED"}),
            "discovery fallback": dict(prov={"fallback_universe": True}),
        }
        for label, kw in variants.items():
            with self.subTest(missing=label):
                s = snapshot([rec("HI", **kw.get("rec", {}))], {"HI": [sig("REQ")]},
                             contracts=kw.get("contracts"), prov=kw.get("prov"), pf=kw.get("pf", "default"))
                c = next(c for c in DE.build(s)["candidates"] if c["type"] == DE.DIRECTIONAL)
                self.assertEqual(c["state"], DE.WATCH, c["missing_authorities"] + c["blockers"])
                self.assertTrue(c["missing_authorities"])
        # unknown identity is never crypto
        _, c = one(signal=sig("REQ"), rec={"identity": None})
        self.assertEqual((c["state"], c["blockers"]), (DE.AVOID, ["IDENTITY_NOT_VERIFIED"]))
        # The public boundary refuses a stale core snapshot instead of emitting any decision authority.
        s = snapshot([rec("HI")], {"HI": [sig("REQ")]})
        s["inputs_as_of"]["quant"] = AS_OF - 4 * 3600
        for evaluate in (lambda: DE.build(s), lambda: DE.evaluate_asset(s, "HI")):
            with self.assertRaisesRegex(ValueError, "DECISION_INPUT_INVALID: inputs_as_of freshness: quant"):
                evaluate()

    def test_future_inputs_are_refused(self):
        """An input or a funding receipt after the decision time is not knowledge at that time (the live skew found by
        the first exact-head Research run): the snapshot therefore decides at the latest input time."""
        s = snapshot([rec("HI")], {"HI": [sig("REQ")]}, contracts=[contract("HI", rcv=AS_OF + 1)])
        s["inputs_as_of"]["quant"] = AS_OF + 120
        for evaluate in (lambda: DE.build(s), lambda: DE.evaluate_asset(s, "HI")):
            with self.assertRaisesRegex(ValueError, "DECISION_INPUT_INVALID: inputs_as_of freshness: quant"):
                evaluate()
        s["as_of"] = AS_OF + 120                                       # the latest knowledge time
        s["portfolio"]["as_of"] = AS_OF + 120
        c = next(c for c in DE.build(s)["candidates"] if c["type"] == DE.DIRECTIONAL)
        self.assertEqual((c["state"], c["funding"]["state"]), (DE.TRADE, "OBSERVED"))

    def test_missing_values_never_default(self):
        _, c = one(signal=sig("REQ"), contracts=[contract("HI", fund=None)])
        self.assertEqual(c["funding"]["state"], "MISSING")
        self.assertIsNone(c["funding"]["rate_8h"])                          # not zero, not funded
        self.assertIn("FUNDING_UNKNOWN", c["missing_authorities"])
        _, c = one(signal=sig("REQ"), rec={"execution_liquidity": {"state": "MISSING", "observed_value": None,
                                                                   "threshold": 1e6, "passes": False}})
        self.assertIsNone(c["proposal"]["expected_slippage"])               # not liquid, not zero slippage
        self.assertIn("EXECUTION_LIQUIDITY_UNKNOWN", c["missing_authorities"])
        _, c = one(signal=sig("REQ"), pf=dict(portfolio(), returns={a: v for a, v in RET.items() if a != "HI"}))
        self.assertEqual(c["portfolio"]["after"]["state"], PR.UNEVALUABLE)  # not uncorrelated, not safe
        self.assertIn("PORTFOLIO_UNEVALUABLE", c["missing_authorities"])


class StrategyAuthority(unittest.TestCase):
    def test_requalified_legacy_disabled_and_others(self):
        expect = {"REQ": (DE.TRADE, None), "TSMOM": (DE.WATCH, "STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT"),
                  "PAPER": (DE.WATCH, "STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT"),
                  "DIS": (DE.AVOID, "STRATEGY_DISABLED"), "REJ": (DE.AVOID, "STRATEGY_RESEARCH_REJECTED"),
                  "UNKNOWN_SID": (DE.AVOID, "STRATEGY_UNGOVERNED")}
        for sid, (state, code) in expect.items():
            with self.subTest(strategy=sid):
                _, c = one(signal=sig(sid))
                self.assertEqual(c["state"], state)
                if code:
                    self.assertIn(code, c["blockers"] + c["caps"])

    def test_legacy_holdover_strong_signal_never_trade(self):
        """Excellent liquidity, a fresh new signal, an empty book: still WATCH. The identical requalified one trades."""
        strong = dict(rec={"execution_liquidity": {"state": "KNOWN", "observed_value": 9e9, "threshold": 1e6,
                                                   "passes": True}})
        _, legacy = one(signal=sig("TSMOM", kind="NEW", age=60), **copy.deepcopy(strong))
        _, req = one(signal=sig("REQ", kind="NEW", age=60), **copy.deepcopy(strong))
        self.assertEqual(legacy["state"], DE.WATCH)
        self.assertEqual(legacy["caps"], ["STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT"])
        self.assertEqual(legacy["portfolio"]["after"]["state"], PR.WITHIN)
        self.assertEqual(req["state"], DE.TRADE)
        self.assertEqual(steps(legacy)["STRATEGY_AUTHORITY"]["result"], DE.CAP)
        self.assertEqual(steps(req)["STRATEGY_AUTHORITY"]["result"], DE.PASS)
        differ = [g["step"] for g, h in zip(legacy["trace"], req["trace"]) if g["result"] != h["result"]]
        self.assertEqual(differ, ["STRATEGY_AUTHORITY"])          # the only gate that differs

    def test_real_policy_states_unchanged(self):
        import quant
        from v8 import strategy_policy as SP
        policy = SP.load(quant.STRATS)
        self.assertEqual({r["strategy_id"]: (r["deployment_state"], r["research_state"]) for r in policy["strategies"]},
                         {s: ("LEGACY_HOLDOVER", "INSUFFICIENT_EVIDENCE") for s in ("TSMOM", "TREND_EMA", "XSMOM")})
        sys.path.insert(0, str(ROOT / "tools" / "research"))
        import strategy_census as SC
        catalog = {r["strategy_id"] for r in SC.catalog()}
        self.assertEqual(len(catalog), 24)                   # the other 21 are disabled by absence (Phase 9 convention)
        self.assertEqual(len(catalog - {r["strategy_id"] for r in policy["strategies"]}), 21)
        self.assertEqual(SC.build()["known_lower_bound"], 199)
        _, c = one(signal=sig("TSMOM_FAST"))                # a catalog strategy absent from the reviewed policy
        self.assertEqual(c["state"], DE.AVOID)
        self.assertIn("STRATEGY_UNGOVERNED", c["blockers"])
        self.assertEqual(SP.digest(policy), "f2e10f9934a919543bbc2c5fa02e8823629fb9b78789cf6348c3e8cadb96e351")
        self.assertEqual(SP.runtime_implementation_hash(),
                         __import__("v8.strategy_policy", fromlist=["runtime_implementation_hash"]).runtime_implementation_hash())


class IdentityAndVenue(unittest.TestCase):
    def test_identity_and_exposure(self):
        for ident, code in (("VERIFIED_CRYPTO", None), ("UNVERIFIED", "IDENTITY_NOT_VERIFIED"),
                            ("AMBIGUOUS", "IDENTITY_NOT_VERIFIED"), ("VERIFIED_TRADFI", "IDENTITY_NON_CRYPTO")):
            with self.subTest(identity=ident):
                _, c = one(signal=sig("REQ"), rec={"identity": ident})
                self.assertEqual(c["state"], DE.TRADE if code is None else DE.AVOID)
                if code:
                    self.assertEqual(c["blockers"][0], code)
        _, c = one(signal=sig("REQ"), rec={"anomaly_flags": ["ECONOMIC_EXPOSURE_CONFLICT"]})
        self.assertEqual((c["state"], c["blocking_step"]), (DE.AVOID, "ECONOMIC_EXPOSURE"))

    def test_identity_is_not_inferred_from_popularity_or_score(self):
        """A famous ticker with huge volume and a strong requalified signal but no verified identity is AVOID."""
        _, c = one(asset="BTC", signal=sig("REQ"), rec={"identity": "AMBIGUOUS", "anomaly_flags": ["MULTI_VENUE"],
                                                        "execution_liquidity": {"state": "KNOWN", "observed_value": 5e10,
                                                                                "threshold": 1e6, "passes": True}})
        self.assertEqual((c["state"], c["blocking_step"]), (DE.AVOID, "IDENTITY"))

    def test_venue_health(self):
        _, c = one(signal=sig("REQ"))
        self.assertEqual(steps(c)["VENUE_HEALTH"]["result"], DE.PASS)
        _, c = one(signal=sig("REQ"), rec={"data_quality": "DATA_DEGRADED"})
        self.assertEqual((c["state"], c["missing_authorities"]), (DE.WATCH, ["VENUE_DATA_DEGRADED"]))
        doc, c = one(signal=sig("REQ"), prov={"venues_failed_names": ["lighter"], "coverage_state": "DEGRADED"})
        self.assertEqual(c["state"], DE.TRADE)                   # another venue down does not taint this asset...
        self.assertEqual(doc["market_summary"]["venue_degradation"]["venues_failed"], ["lighter"])     # ...but is shown
        doc = DE.build(snapshot([], {"HI": [sig("REQ")]}))       # a signal for an asset discovery does not list
        c = doc["candidates"][0]
        self.assertEqual((c["state"], c["blockers"][0]), (DE.AVOID, "NOT_IN_DISCOVERY"))


class Liquidity(unittest.TestCase):
    def test_execution_states(self):
        cases = {"trade-ready": (("KNOWN", 5e6, True), DE.TRADE, None),
                 "below gate": (("KNOWN", 2e5, False), DE.WATCH, "EXECUTION_LIQUIDITY_BELOW_GATE"),
                 "missing": (("MISSING", None, False), DE.WATCH, "EXECUTION_LIQUIDITY_UNKNOWN"),
                 "not on trade dex": (("NOT_ON_TRADE_DEX", None, False), DE.AVOID, "NOT_ON_TRADE_DEX")}
        for label, (liq, state, code) in cases.items():
            with self.subTest(liquidity=label):
                _, c = one(signal=sig("REQ"), rec={"execution_liquidity": {"state": liq[0], "observed_value": liq[1],
                                                                           "threshold": 1e6, "passes": liq[2]}})
                self.assertEqual(c["state"], state)
                if code:
                    self.assertIn(code, c["blockers"] + c["caps"] + c["missing_authorities"])


class Portfolio(unittest.TestCase):
    def test_within_approaching_breached_unevaluable(self):
        _, c = one(signal=sig("REQ"))
        self.assertEqual((c["portfolio"]["after"]["state"], c["state"]), (PR.WITHIN, DE.TRADE))
        near = [book_position(f"n{k}", a, d, 50.0, strategy=st) for k, (a, d, st) in
                enumerate((("LO", 1, "TSMOM"), ("NEG", -1, "XSMOM"), ("ALPHA", 1, "TREND_EMA"), ("BRAVO", -1, "X1")))]
        _, c = one(signal=sig("REQ"), book=near)
        self.assertEqual(c["portfolio"]["after"]["state"], PR.APPROACHING)
        self.assertEqual((c["state"], c["caps"]), (DE.WATCH, ["PORTFOLIO_APPROACHING_LIMITS"]))
        _, c = one(signal=sig("REQ"), book=[book_position("missing", "LO", funding={"state": "MISSING"})])
        self.assertEqual(c["portfolio"]["after"]["state"], PR.UNEVALUABLE)
        self.assertEqual((c["state"], c["missing_authorities"]), (DE.WATCH, ["PORTFOLIO_UNEVALUABLE"]))

    def test_breach_is_avoid_and_traced_and_rank_cannot_override(self):
        big = [book_position(f"b{k}", a, 1, 100.0) for k, a in enumerate(("LO", "ALPHA", "BRAVO", "CHARLIE", "DELTA"))]
        s = snapshot([rec("HI"), rec("ECHO")], {"HI": [sig("REQ", age=10)], "ECHO": [sig("REQ", age=80000)]}, book=big)
        doc = DE.build(s)
        hi = next(c for c in doc["candidates"] if c["id"].startswith("DIRECTIONAL_STRATEGY:HI"))
        self.assertEqual(hi["state"], DE.AVOID)
        self.assertEqual(hi["blocking_step"], "PORTFOLIO_AFTER")
        st = steps(hi)
        self.assertEqual(st["PORTFOLIO_BEFORE"]["input"]["state"], PR.BREACHED)
        self.assertEqual(st["PROPOSED_TRADE"]["input"]["id"], "PROPOSED:HI:REQ:LONG")
        self.assertEqual(st["PORTFOLIO_AFTER"]["input"]["state"], PR.BREACHED)
        self.assertIn("max_side_stop_risk", st["RISK_LIMITS"]["input"]["breached"])
        self.assertEqual(st["PORTFOLIO_AFTER"]["code"], "PORTFOLIO_LIMIT_BREACHED")
        self.assertEqual(doc["best_trades_now"]["count"], 0)
        self.assertIn(hi["id"], [x["id"] for x in doc["best_trades_now"]["selection_trace"]["removed_by_gate"]])
        self.assertEqual(hi["placement"]["section"], None)

    def test_whole_open_book_including_blocked(self):
        blocked = book_position("blk", "TWIN", 1, 60.0, actionability="IDENTITY_BLOCKED")
        _, without = one(signal=sig("REQ"))
        _, withb = one(signal=sig("REQ"), book=[blocked])
        self.assertGreater(withb["portfolio"]["after"]["metrics"]["max_gross_leverage"],
                           without["portfolio"]["after"]["metrics"]["max_gross_leverage"])
        self.assertEqual(withb["portfolio"]["before"]["state"], PR.WITHIN)
        self.assertAlmostEqual(withb["portfolio"]["before"]["metrics"]["max_gross_leverage"], 60.0 / 500.0)

    def test_own_new_paper_position_is_excluded_and_duplicates_are_avoided(self):
        own = book_position("HI-REQ-1", "HI", 1, 50.0, strategy="REQ")
        _, c = one(signal=sig("REQ", trade_id="HI-REQ-1"), book=[own])
        self.assertEqual(c["state"], DE.TRADE)                        # marginal: the book without its own paper trade
        self.assertEqual(steps(c)["PORTFOLIO_BEFORE"]["input"]["own_paper_position_excluded"], "HI-REQ-1")
        older = book_position("HI-REQ-0", "HI", 1, 50.0, strategy="REQ")
        _, c = one(signal=sig("REQ", kind="ACTIVE"), book=[older])
        self.assertEqual((c["state"], c["blockers"][0], c["blocking_step"]), (DE.AVOID, "POSITION_ALREADY_OPEN", "SIGNAL"))


class Funding(unittest.TestCase):
    def test_observed_observed_zero_missing_and_most_adverse(self):
        _, c = one(signal=sig("REQ"), contracts=[contract("HI", fund=0.0002)])
        self.assertEqual((c["funding"]["state"], c["funding"]["rate_8h"]), ("OBSERVED", 0.0002))
        _, c = one(signal=sig("REQ"), contracts=[contract("HI", fund=0.0)])
        self.assertEqual((c["funding"]["state"], c["funding"]["rate_8h"], c["state"]), ("OBSERVED_ZERO", 0.0, DE.TRADE))
        _, c = one(signal=sig("REQ"), contracts=[contract("HI", fund=None)])
        self.assertEqual((c["funding"]["state"], c["state"]), ("MISSING", DE.WATCH))
        two = [contract("HI", "hyperliquid", fund=0.0003), contract("HI", "lighter", fund=-0.0004)]
        _, lng = one(signal=sig("REQ", d=1), contracts=copy.deepcopy(two))
        _, sht = one(signal=sig("REQ", d=-1), contracts=copy.deepcopy(two))
        self.assertEqual((lng["funding"]["venue"], lng["funding"]["rate_8h"]), ("hyperliquid", 0.0003))
        self.assertEqual((sht["funding"]["venue"], sht["funding"]["rate_8h"]), ("lighter", -0.0004))
        self.assertEqual(lng["funding"]["received_ts"], AS_OF - 60)
        _, c = one(signal=sig("REQ"), contracts=[contract("HI", "binance", fund=0.0001)])     # not a trade DEX
        self.assertEqual(c["funding"]["state"], "MISSING")

    def test_legacy_fund_default_is_never_used(self):
        src = (ROOT / "v8/decision.py").read_text(encoding="utf-8")
        self.assertNotIn("fund_default", src)
        self.assertNotIn("0.0001", src)


class FundingSpread(unittest.TestCase):
    def spread(self, **over):
        legs = [contract("HI", "hyperliquid", fund=-0.003, vol=5e6, npx=100.0),
                contract("HI", "lighter", fund=0.003, vol=5e6, npx=100.1)]
        over = {("fund8h" if k == "fund" else k): v for k, v in over.items()}
        for k, v in over.items():
            legs[1][k] = v
        doc = DE.build(snapshot([rec("HI")], {}, contracts=legs))
        return doc, next((c for c in doc["candidates"] if c["type"] == DE.FUNDING), None)

    def test_qualified_spread_is_watch_never_trade_or_risk_free(self):
        doc, c = self.spread()
        self.assertEqual((c["state"], c["label"]), (DE.WATCH, "FUNDING_SPREAD_OPPORTUNITY"))
        self.assertEqual((c["legs"]["long"]["venue"], c["legs"]["short"]["venue"]), ("hyperliquid", "lighter"))
        self.assertAlmostEqual(c["spread_8h"], .006)
        self.assertIn("FUNDING_SPREAD_RESEARCH_AUTHORITY_MISSING", c["caps"])
        self.assertIn("PORTFOLIO_HEDGE_MODEL_UNAVAILABLE", c["missing_authorities"])
        self.assertTrue(any(w.startswith("NOT_RISK_FREE") for w in c["warnings"]))
        self.assertEqual(doc["funding_opportunities"]["count"], 1)
        self.assertNotIn("risk-free arbitrage", canon(doc).lower().replace("not_risk_free", ""))

    def test_spread_gates(self):
        for label, over, code in (("basis", {"npx": 103.0}, "BASIS_TOO_WIDE"),
                                  ("thin leg", {"vol": 1e5}, "LEG_LIQUIDITY_BELOW_GATE"),
                                  ("no carry", {"fund": -0.0029}, "CARRY_NOT_POSITIVE_AFTER_COSTS")):
            with self.subTest(gate=label):
                doc, c = self.spread(**over)
                self.assertEqual(c["state"], DE.AVOID)
                self.assertIn(code, c["blockers"])
                self.assertEqual(doc["funding_opportunities"]["count"], 0)
        _, c = self.spread(fund=None)                       # one leg's funding missing: no spread to evaluate
        self.assertIsNone(c)


class FundingSpreadHealthyLegs(unittest.TestCase):
    """Phase 11 correction: health is part of pair eligibility. Only active, admitted, trade-DEX perps with fresh
    venue-reported funding and a HEALTHY contract can be a leg; an unhealthy one is never chosen and then flagged."""
    def doc(self, legs, assets=("HI",)):
        return DE.build(snapshot([rec(a) for a in assets], {}, contracts=legs))

    def spread_of(self, doc, asset="HI"):
        return next((c for c in doc["candidates"] if c["type"] == DE.FUNDING and c["asset"] == asset), None)

    def healthy_pair(self, asset="HI"):
        return [contract(asset, "hyperliquid", fund=-0.003, vol=5e6, npx=100.0),
                contract(asset, "lighter", fund=0.003, vol=5e6, npx=100.1)]

    def test_two_healthy_legs_can_be_a_watch_funding_opportunity(self):
        doc = self.doc(self.healthy_pair())
        c = self.spread_of(doc)
        self.assertEqual(c["state"], DE.WATCH)
        self.assertEqual({c["legs"]["long"]["health"], c["legs"]["short"]["health"]}, {"HEALTHY"})
        self.assertEqual([i["id"] for i in doc["funding_opportunities"]["items"]], [c["id"]])
        self.assertIn("FUNDING_SPREAD_RESEARCH_AUTHORITY_MISSING", c["caps"])          # still capped at WATCH
        self.assertIn("PORTFOLIO_HEDGE_MODEL_UNAVAILABLE", c["missing_authorities"])
        self.assertTrue(any(w.startswith("NOT_RISK_FREE") for w in c["warnings"]))

    def test_one_healthy_and_one_degraded_venue_is_no_funding_opportunity(self):
        for bad in ("STALE", "DEGRADED", "ERROR", None):
            with self.subTest(health=bad):
                legs = self.healthy_pair()
                legs[1]["health"] = bad
                doc = self.doc(legs)
                self.assertIsNone(self.spread_of(doc))
                self.assertEqual(doc["funding_opportunities"]["count"], 0)
                self.assertNotIn("LEG_VENUE_DEGRADED", canon(doc))

    def test_a_degraded_extreme_rate_venue_cannot_hijack_the_pair(self):
        legs = self.healthy_pair() + [contract("HI", "aster", fund=0.09, vol=5e6, npx=100.05, health="STALE")]
        c = self.spread_of(self.doc(legs))
        self.assertEqual((c["legs"]["long"]["venue"], c["legs"]["short"]["venue"]), ("hyperliquid", "lighter"))
        self.assertAlmostEqual(c["spread_8h"], .006)
        sg = next(g for g in c["trace"] if g["step"] == "SIGNAL")
        self.assertEqual((sg["input"]["eligible_venues"], sg["input"]["unhealthy_excluded"]),
                         (["hyperliquid", "lighter"], ["aster"]))
        # the degraded venue on the long side (an extreme negative rate) is ignored the same way
        legs = self.healthy_pair() + [contract("HI", "aster", fund=-0.09, vol=5e6, npx=100.05, health="DEGRADED")]
        c = self.spread_of(self.doc(legs))
        self.assertEqual((c["legs"]["long"]["venue"], c["legs"]["short"]["venue"]), ("hyperliquid", "lighter"))

    def test_stale_or_degraded_funding_cannot_improve_rank(self):
        base = self.spread_of(self.doc(self.healthy_pair()))
        for extra in (contract("HI", "aster", fund=0.09, health="STALE"),                 # degraded contract
                      contract("HI", "aster", fund=0.09, rcv=AS_OF - 10 * 3600),          # stale rate, healthy contract
                      contract("HI", "variational", fund=-0.09, health="DEGRADED")):
            with self.subTest(extra=extra["venue"] + ":" + str(extra["health"]) + ":" + str(extra["rcv_ts"])):
                c = self.spread_of(self.doc(self.healthy_pair() + [extra]))
                self.assertEqual(c["ranking_inputs"], base["ranking_inputs"])
                self.assertEqual((c["net_carry"], c["spread_8h"]), (base["net_carry"], base["spread_8h"]))

    def test_a_degraded_leg_never_appears_in_funding_opportunities(self):
        assets = ["HI", "TWIN", "LO", "NEG", "ALPHA", "BRAVO"]
        legs = []
        for k, a in enumerate(assets):
            pair = self.healthy_pair(a)
            if k % 2:
                pair[k % 2]["health"] = "STALE"             # every other asset has one degraded leg
                pair.append(contract(a, "aster", fund=0.5, vol=5e6, npx=100.0, health="DEGRADED"))
            legs += pair
        doc = self.doc(legs, assets)
        health = {c["id"]: c["health"] for c in legs}
        by_id = {c["id"]: c for c in doc["candidates"]}
        self.assertEqual(doc["funding_opportunities"]["count"], 3)
        for item in doc["funding_opportunities"]["items"]:
            c = by_id[item["id"]]
            for leg in c["legs"].values():
                self.assertEqual(health[leg["contract"]], "HEALTHY", item["id"])
        for c in doc["candidates"]:
            if c["type"] == DE.FUNDING:
                self.assertEqual({health[leg["contract"]] for leg in c["legs"].values()}, {"HEALTHY"}, c["id"])

    def test_missing_healthy_second_venue_is_not_zero_or_no_spread(self):
        for label, second in (("degraded", {"health": "STALE"}), ("stale rate", {"rcv_ts": AS_OF - 10 * 3600}),
                              ("missing rate", {"fund8h": None}), ("not admitted", {"admitted": False}),
                              ("not a trade dex", {"venue": "binance", "id": "binance:HI"})):
            with self.subTest(second=label):
                legs = self.healthy_pair()
                legs[1].update(second)
                doc = self.doc(legs)
                self.assertIsNone(self.spread_of(doc))
                a = next(x for x in doc["assets"] if x["asset"] == "HI")
                self.assertFalse(any(o.startswith(DE.FUNDING) for o in a["opportunities"]))
                self.assertNotIn("NO_FUNDING_SPREAD", canon(doc))
                self.assertEqual(doc["market_summary"]["opportunity_states_by_type"][DE.FUNDING],
                                 {DE.TRADE: 0, DE.WATCH: 0, DE.AVOID: 0})


class ValidityHorizon(unittest.TestCase):
    """valid_until: the time after which the decision's own policy ages (freshness, signal age, funding age) would no
    longer hold, published so a consumer (the Analyzer) fails closed instead of re-deciding anything."""
    def test_document_and_candidate_horizons(self):
        pol = DE.load_policy()
        lim, rate_age = pol["freshness"]["max_input_age_s"]["value"], pol["funding"]["max_rate_age_s"]["value"]
        snap = snapshot([rec("HI")], {"HI": [sig("REQ", age=3600)]})
        snap["inputs_as_of"] = {"discovery": AS_OF - 120, "quant": AS_OF, "portfolio": AS_OF - 30}
        doc = DE.build(snap)
        self.assertEqual(doc["valid_until"], AS_OF - 120 + lim)
        c = next(x for x in doc["candidates"] if x["type"] == DE.DIRECTIONAL)
        self.assertEqual(c["state"], DE.TRADE)
        self.assertEqual(c["valid_until"], min(AS_OF - 120 + lim, AS_OF - 3600 + pol["signal"]["max_age_s"]["value"]["1d"],
                                               AS_OF - 60 + rate_age))
        one_asset = DE.evaluate_asset(snap, "HI")
        self.assertEqual(one_asset["valid_until"], doc["valid_until"])
        self.assertEqual(one_asset["opportunities"][0]["valid_until"], c["valid_until"])
        # an old signal expires before the document does
        doc = DE.build(snapshot([rec("HI")], {"HI": [sig("REQ", age=pol["signal"]["max_age_s"]["value"]["1d"] - 50)]}))
        c = next(x for x in doc["candidates"] if x["type"] == DE.DIRECTIONAL)
        self.assertEqual((c["state"], c["valid_until"]), (DE.TRADE, AS_OF + 50))
        self.assertTrue(all(isinstance(x["valid_until"], int) for x in doc["candidates"]))


class Sections(unittest.TestCase):
    def trades(self, n, watch=3):
        names = NAMES[:max(n, 1) + watch]
        recs = [rec(a) for a in names]
        sigs = {a: [sig("REQ", age=100 + k)] for k, a in enumerate(names[:n])}
        for a in names[n:n + watch]:
            sigs[a] = [sig("TSMOM", age=10)]                 # strong-looking legacy WATCH candidates
        return DE.build(snapshot(recs, sigs))

    def test_never_manufactures_five(self):
        for n, want in ((0, 0), (1, 1), (3, 3), (5, 5), (7, 5)):
            with self.subTest(trades=n):
                doc = self.trades(n)
                b = doc["best_trades_now"]
                self.assertEqual(b["count"], want)
                self.assertTrue(all(i["state"] == DE.TRADE for i in b["items"]))
                self.assertEqual(doc["market_summary"]["opportunity_states"]["TRADE"], n)
                self.assertEqual(b["selection_trace"]["fewer_than_max"], want < 5)
                if want < 5:
                    self.assertIn("nothing else is promoted", b["selection_trace"]["why_fewer"])

    def test_ranking_order_ties_and_cutoff(self):
        doc = self.trades(7, watch=0)
        b = doc["best_trades_now"]
        ages = [i["ranking_inputs"]["signal_age_s"] for i in b["items"]]
        self.assertEqual(ages, sorted(ages))
        self.assertEqual(len(b["selection_trace"]["order"]), 4)
        cut = b["selection_trace"]["cutoff"]
        self.assertEqual(cut["rule"], ["signal_age_s", "asc"])
        self.assertEqual(cut["above"]["id"], b["items"][-1]["id"])
        self.assertEqual(len(b["selection_trace"]["excluded_after_cutoff"]), 2)
        sixth = next(c for c in doc["candidates"] if c["id"] == b["selection_trace"]["excluded_after_cutoff"][0])
        self.assertEqual((sixth["placement"]["reason"], sixth["placement"]["rank"]), ("EXCLUDED_BY_SECTION_MAXIMUM", 6))
        # ties: identical ranking inputs fall back to the asset name
        tie = DE.build(snapshot([rec("ZED"), rec("ABE")], {"ZED": [sig("REQ", age=50)], "ABE": [sig("REQ", age=50)]},
                                contracts=[contract("ZED"), contract("ABE")],
                                pf=dict(portfolio(), returns=dict(copy.deepcopy(RET), ZED=RET["LO"], ABE=RET["ALPHA"]))))
        self.assertEqual([i["asset"] for i in tie["best_trades_now"]["items"]], ["ABE", "ZED"])
        self.assertEqual(tie["best_trades_now"]["selection_trace"]["order"][0]["rule"][0], "asset")

    def test_hard_gate_beats_best_ranking_inputs(self):
        recs = [rec("HI", identity="UNVERIFIED"), rec("LO")]
        sigs = {"HI": [sig("REQ", age=1)], "LO": [sig("REQ", age=80000, kind="ACTIVE")]}
        doc = DE.build(snapshot(recs, sigs))
        self.assertEqual([i["asset"] for i in doc["best_trades_now"]["items"]], ["LO"])
        removed = doc["best_trades_now"]["selection_trace"]["removed_by_gate"]
        self.assertEqual((removed[0]["step"], removed[0]["codes"][0]), ("IDENTITY", "IDENTITY_NOT_VERIFIED"))


class Emerging(unittest.TestCase):
    def test_small_coin_survives_discovery_watch_never_trade(self):
        small = rec("FOXTROT", liq=("KNOWN", 3e4, False), flags=["NEW_LISTING", "SINGLE_VENUE", "THIN_LIQUIDITY"],
                    first_seen=AS_OF - 2 * DAY, listing_age={"state": "KNOWN", "days": 2.0,
                                                             "basis": "FIRST_SEEN_AFTER_TRACKING_START"})
        big = [rec(a, liq=("KNOWN", 1e9, True)) for a in ("BTC", "HI", "TWIN", "LO", "NEG", "ALPHA", "BRAVO")]
        doc = DE.build(snapshot(big + [small], {"FOXTROT": [sig("REQ")]}))
        self.assertIn("FOXTROT", [a["asset"] for a in doc["assets"]])                 # discovered, never top-N cut
        self.assertEqual(doc["market_summary"]["discovered_assets"], 8)
        d = next(c for c in doc["candidates"] if c["id"].startswith("DIRECTIONAL_STRATEGY:FOXTROT"))
        self.assertEqual((d["state"], d["caps"]), (DE.WATCH, ["EXECUTION_LIQUIDITY_BELOW_GATE"]))
        e = next(c for c in doc["candidates"] if c["id"] == "EMERGING_OBSERVATION:FOXTROT")
        self.assertEqual(e["state"], DE.WATCH)
        self.assertEqual([i["asset"] for i in doc["emerging_opportunities"]["items"]], ["FOXTROT"])
        types = {x["type"] for x in e["positive_evidence"]}
        self.assertEqual(types, {"RECENTLY_OBSERVED_BY_DESK", "CURRENT_STRATEGY_SIGNAL"})
        self.assertNotIn("NEWLY_LISTED", canon(doc))
        self.assertIn("SINGLE_VENUE", e["warnings"])

    def test_no_fabricated_multiples_or_market_cap(self):
        doc = DE.build(snapshot([rec("FOXTROT", flags=["STAGE1_EXTREME"])], {}))
        blob = canon(doc).lower()
        for bad in ("market_cap", "marketcap", "target_multiple", "10x", "3x", "5x", "upside", "potential_return"):
            self.assertNotIn(bad, blob)

    def test_no_size_or_popularity_preference(self):
        pair = [rec("ZULU", flags=["STAGE1_EXTREME"], liq=("KNOWN", 9e10, True), price=60000.0,
                    best_volume=9e10, market_cap=1e12),
                rec("ABLE", flags=["STAGE1_EXTREME"], liq=("KNOWN", 4e4, False), price=0.0001, best_volume=4e4)]
        doc = DE.build(snapshot(pair, {}))
        items = doc["emerging_opportunities"]["items"]
        self.assertEqual([i["asset"] for i in items], ["ZULU", "ABLE"])     # ZULU has 0 outstanding blockers...
        pair[1]["execution_liquidity"] = dict(pair[0]["execution_liquidity"])
        doc = DE.build(snapshot(pair, {}))
        self.assertEqual([i["asset"] for i in doc["emerging_opportunities"]["items"]], ["ABLE", "ZULU"])   # ...else name
        for f in ("best_volume", "market_cap", "price"):
            self.assertNotIn(f, doc["emerging_opportunities"]["items"][0]["ranking_inputs"])

    def test_disqualified_assets_never_emerge(self):
        doc = DE.build(snapshot([rec("A1", identity="UNVERIFIED", flags=["NEW_LISTING"]),
                                 rec("A2", flags=["NEW_LISTING", "ECONOMIC_EXPOSURE_CONFLICT"]),
                                 rec("A3", flags=["NEW_LISTING"], liq=("NOT_ON_TRADE_DEX", None, False))], {}))
        self.assertEqual(doc["emerging_opportunities"]["count"], 0)
        self.assertEqual({c["state"] for c in doc["candidates"] if c["type"] == DE.EMERGING}, {DE.AVOID})

    def test_avoided_signal_is_not_emerging_evidence(self):
        big = [book_position(f"b{k}", a, 1, 100.0) for k, a in enumerate(("LO", "ALPHA", "BRAVO", "CHARLIE", "DELTA"))]
        doc = DE.build(snapshot([rec("HI")], {"HI": [sig("TSMOM")]}, book=big))
        self.assertEqual(next(c for c in doc["candidates"] if c["type"] == DE.DIRECTIONAL)["state"], DE.AVOID)
        self.assertFalse([c for c in doc["candidates"] if c["type"] == DE.EMERGING])


class AnalyzerParity(unittest.TestCase):
    def test_same_engine_for_one_asset_and_the_market(self):
        recs = [rec("HI"), rec("LO", liq=("KNOWN", 2e5, False), flags=["NEW_LISTING"]), rec("NEG", identity="UNVERIFIED"),
                rec("TWIN")]
        sigs = {"HI": [sig("REQ"), sig("TSMOM", d=-1)], "LO": [sig("REQ")], "NEG": [sig("REQ")]}
        contracts = [contract(r["asset"]) for r in recs] + [contract("TWIN", "lighter", fund=0.004)]
        s = snapshot(recs, sigs, contracts=contracts, book=[book_position("x", "ALPHA", -1)])
        market = DE.build(s)
        for a in ("HI", "LO", "NEG", "TWIN", "NOPE"):
            with self.subTest(asset=a):
                single = DE.evaluate_asset(s, a)
                mine = [{k: v for k, v in c.items() if k != "placement"} for c in market["candidates"] if c["asset"] == a]
                self.assertEqual(canon(single["opportunities"]), canon(mine))
                rec_m = next((x for x in market["assets"] if x["asset"] == a), None)
                if rec_m:
                    self.assertEqual(canon(single["asset"]), canon(rec_m))
                self.assertEqual(single["policy_hash"], market["policy_hash"])


class Trace(unittest.TestCase):
    def test_every_gate_and_placement_traced(self):
        recs = [rec("HI"), rec("LO", flags=["NEW_LISTING"]), rec("TWIN")]
        contracts = [contract("HI"), contract("LO"), contract("TWIN"), contract("TWIN", "lighter", fund=0.005)]
        doc = DE.build(snapshot(recs, {"HI": [sig("REQ"), sig("TSMOM", d=-1)]}, contracts=contracts))
        types = {c["type"] for c in doc["candidates"]}
        self.assertEqual(types, set(DE.TYPES))
        for c in doc["candidates"]:
            with self.subTest(candidate=c["id"]):
                got = [g["step"] for g in c["trace"]]
                self.assertEqual(set(got), set(DE.TRACE_STEPS))
                self.assertEqual(got[-1], "DECISION_STATE")
                self.assertEqual([g["step"] for g in c["placement"]["trace"]], list(DE.PLACEMENT_STEPS))
                for g in c["trace"] + c["placement"]["trace"]:
                    self.assertEqual(set(g), {"step", "input", "rule", "result", "code", "effect"})
                if c["state"] == DE.AVOID:
                    self.assertEqual(c["explanation"]["rejection_step"], c["blocking_step"])
                    self.assertEqual(c["blockers"][0], next(g["code"] for g in c["trace"] if g["result"] == DE.FAIL))
                if c["state"] == DE.WATCH:
                    self.assertTrue(c["explanation"]["why_interesting"])
                    self.assertTrue(c["explanation"]["why_not_trade"])
                    self.assertTrue(c["explanation"]["to_become_trade"])
                if c["state"] == DE.TRADE:
                    self.assertTrue(all(g["result"] in (DE.PASS, DE.INFO) for g in c["trace"]))
        for a in doc["assets"]:
            self.assertEqual([g["step"] for g in a["trace"]][:1], ["DISCOVERY"])


class EmptyStates(unittest.TestCase):
    def check(self, doc):
        for s in DE.SECTIONS:
            self.assertLessEqual(doc[s]["count"], 5)
        self.assertEqual(doc["best_trades_now"]["count"], doc["market_summary"]["best_trades_now"])
        json.dumps(doc, allow_nan=False)

    def test_empty_and_degraded_states(self):
        cases = {
            "no records": snapshot([], {}),
            "no signals": snapshot([rec("HI"), rec("LO")], {}),
            "no trades, only legacy": snapshot([rec("HI")], {"HI": [sig("TSMOM")]}),
            "no funding": snapshot([rec("HI")], {}, contracts=[contract("HI")]),
            "all identity blocked": snapshot([rec(a, identity="UNVERIFIED", flags=["NEW_LISTING"]) for a in NAMES[:4]],
                                             {a: [sig("REQ")] for a in NAMES[:4]}),
            "discovery degraded": snapshot([rec("HI")], {"HI": [sig("REQ")]}, prov={"fallback_universe": True}),
            "portfolio unevaluable": snapshot([rec("HI")], {"HI": [sig("REQ")]},
                                              book=[book_position("m", "LO", funding={"state": "MISSING"})]),
            "no portfolio": snapshot([rec("HI")], {"HI": [sig("REQ")]}, pf=None),
        }
        for label, s in cases.items():
            with self.subTest(case=label):
                doc = DE.build(s)
                self.check(doc)
                self.assertEqual(doc["best_trades_now"]["count"], 0)
                self.assertTrue(doc["market_summary"]["zero_trade"])
        self.assertEqual(DE.build(cases["no records"])["market_summary"]["evaluated_assets"], 0)
        doc = DE.build(cases["all identity blocked"])
        self.assertEqual(doc["market_summary"]["identity_blocked_assets"], 4)
        self.assertEqual(doc["emerging_opportunities"]["count"], 0)
        doc = DE.build(cases["no signals"])
        self.assertEqual(doc["market_summary"]["opportunities"], 0)
        self.assertTrue(all(a["blockers"] == ["NO_CURRENT_OPPORTUNITY"] for a in doc["assets"]))
        self.assertEqual(DE.build(cases["portfolio unevaluable"])["market_summary"]["portfolio_state"], PR.UNEVALUABLE)


class ChangesAndDeterminism(unittest.TestCase):
    def test_first_scan_reports_no_previous_authority(self):
        doc = DE.build(snapshot([rec("HI")], {"HI": [sig("REQ")]}))
        self.assertEqual(doc["changes"], {"previous_available": False, "reason": "NO_PREVIOUS_PHASE11_AUTHORITY",
                                          "note": doc["changes"]["note"]})
        bad = DE.build(snapshot([rec("HI")], {"HI": [sig("REQ")]}, previous={"schema": "v8.decision/0", "index": {}}))
        self.assertFalse(bad["changes"]["previous_available"])

    def test_state_and_rank_changes_are_explained(self):
        s1 = snapshot([rec("HI"), rec("LO")], {"HI": [sig("REQ", age=10)], "LO": [sig("REQ", age=20)]})
        first = DE.build(s1)
        s2 = snapshot([rec("HI", identity="UNVERIFIED"), rec("LO")], {"HI": [sig("REQ", age=10)],
                                                                      "LO": [sig("REQ", age=20)]}, previous=first)
        second = DE.build(s2)
        ch = {c["id"]: c for c in second["changes"]["changes"]}
        hi, lo = ch["DIRECTIONAL_STRATEGY:HI:REQ:LONG"], ch["DIRECTIONAL_STRATEGY:LO:REQ:LONG"]
        self.assertEqual((hi["previous_state"], hi["current_state"]), (DE.TRADE, DE.AVOID))
        self.assertEqual(hi["state_change_reason"]["added"], ["IDENTITY_NOT_VERIFIED"])
        self.assertEqual((lo["previous_rank"], lo["current_rank"]), (2, 1))
        self.assertFalse(second["changes"]["policy_changed"])

    def test_byte_identical_and_order_independent(self):
        recs = [rec(a) for a in NAMES[:6]]
        sigs = {a: [sig("REQ", age=100 * k), sig("TSMOM", d=-1)] for k, a in enumerate(NAMES[:6])}
        a = canon(DE.build(snapshot(recs, sigs)))
        b = canon(DE.build(snapshot(list(reversed(recs)), dict(reversed(list(sigs.items()))))))
        self.assertEqual(a, b)

    def test_identical_across_hash_seeds(self):
        code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import test_v8_phase11 as T; "
                "from v8 import decision as DE; recs=[T.rec(a) for a in T.NAMES[:5]]; "
                "sigs={a: [T.sig('REQ', age=50*k)] for k, a in enumerate(T.NAMES[:5])}; "
                "print(T.canon(DE.build(T.snapshot(recs, sigs))))" % (str(ROOT), str(ROOT / "tests")))
        outs = set()
        for seed in ("0", "7", "4242"):
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300, cwd=str(ROOT),
                               env=dict(os.environ, PYTHONHASHSEED=seed))
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])
            outs.add(hashlib.sha256(r.stdout.encode()).hexdigest())
        self.assertEqual(len(outs), 1)


class LiveIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "tools" / "v8"))
        import legacy_parity as LP
        from v8 import snapshot as SN
        cls.tmp = tempfile.mkdtemp(prefix="v8p11")
        out = os.path.join(cls.tmp, "site")
        LP.run_pipeline(out)
        cls.summary = LP.summary(out)
        cls.snap = SN.write(out, keep_parts=True)[0]
        cls.doc = json.loads(Path(out, DE.FILE).read_text())
        cls.part = json.loads(Path(out, "data", "v8", "parts", "quant.json").read_text())
        cls.disc = json.loads(Path(out, "data", "v8", "discovery.json").read_text())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_decision_artifact_and_manifest(self):
        m = self.snap["manifest"]
        self.assertEqual((self.snap["schema"], m["audit_version"]), ("v8.audit/10", "v8-phase11.0"))
        d = m["decision"]
        self.assertEqual(d["status"], "OK")
        self.assertEqual(d["file"]["sha256"], hashlib.sha256(Path(self.tmp, "site", DE.FILE).read_bytes()).hexdigest())
        self.assertEqual(d["policy_hash"], DE.policy_hash(DE.load_policy()))
        self.assertEqual(d["implementation_hash"], DE.implementation_hash())
        self.assertTrue(d["trace_available"])
        self.assertTrue(d["portfolio_binding"]["consistent"])
        self.assertEqual(d["previous_decision_source"], "none")
        self.assertEqual(self.snap["data_health"]["decision"], ["OK"])
        a = self.doc["authority"]
        for k in ("identity_config_hash", "discovery_document_hash", "strategy_policy_hash",
                  "strategy_runtime_implementation_hash", "phase9_authority", "portfolio_policy_hash",
                  "portfolio_implementation_hash", "decision_policy_hash", "decision_implementation_hash",
                  "authority_hash"):
            self.assertIn(k, a)
        self.assertEqual(a["strategy_runtime_implementation_hash"],
                         __import__("v8.strategy_policy", fromlist=["runtime_implementation_hash"]).runtime_implementation_hash())
        self.assertEqual(a["discovery_document_hash"],
                         hashlib.sha256(Path(self.tmp, "site", "data", "v8", "discovery.json").read_bytes()).hexdigest())

    def test_universal_and_truthful(self):
        self.assertEqual(sorted(a["asset"] for a in self.doc["assets"]), sorted(r["asset"] for r in self.disc["assets"]))
        self.assertEqual(self.doc["market_summary"]["discovered_assets"], len(self.disc["assets"]))
        self.assertEqual(self.doc["market_summary"]["opportunity_states"]["TRADE"], 0)      # Phase 9: legacy holdovers
        self.assertEqual(self.doc["best_trades_now"]["count"], 0)
        sigs = self.part["decision_inputs"]["signals"]
        self.assertGreater(sum(len(v) for v in sigs.values()), 0)
        self.assertEqual({x["strategy"] for v in sigs.values() for x in v} - {"TSMOM", "TREND_EMA", "XSMOM"}, set())
        for c in self.doc["candidates"]:
            if c["type"] == DE.DIRECTIONAL:
                self.assertIn("STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT", c["caps"])
                self.assertNotEqual(c["state"], DE.TRADE)

    def test_inputs_are_current_and_funding_observed(self):
        """The decision time is the scan's latest knowledge time: no candidate is stale and observed funding is used."""
        for c in self.doc["candidates"]:
            self.assertNotIn("INPUT_STALE", c["missing_authorities"], c["id"])
        d = [c for c in self.doc["candidates"] if c["type"] == DE.DIRECTIONAL]
        self.assertTrue(d)
        self.assertTrue(all(c["funding"]["state"] in ("OBSERVED", "OBSERVED_ZERO") for c in d))
        self.assertGreaterEqual(self.doc["as_of"], self.snap["manifest"]["ts"])

    def test_decision_time_rule(self):
        from v8 import snapshot as SN
        self.assertEqual(SN.decision_as_of(100, 100, 160, 160, [{"rcv_ts": 101}, {"rcv_ts": None}]), 160)
        self.assertEqual(SN.decision_as_of(100, None, None, None, [{"rcv_ts": 103}]), 103)
        self.assertIsNone(SN.decision_as_of(None, None, None, None, []))
        self.assertEqual(SN.decision_as_of(100, True, None, None, []), 100)        # a bool is not a time

    def test_legacy_outputs_unchanged(self):
        sys.path.insert(0, str(ROOT / "tools" / "v8"))
        import legacy_parity as LP
        golden = json.loads((ROOT / "tests/fixtures/v8/legacy_parity_golden_phase12.json").read_text())
        self.assertEqual(LP.compare(golden, self.summary), [])
        # historical: against the Phase 11 golden only the Phase 12 desk pages differ, each pinned in its manifest
        p11 = json.loads((ROOT / "tests/fixtures/v8/legacy_parity_golden_phase11.json").read_text())
        p12 = sorted({e["file"] for category in ("files", "code") for e in json.loads((ROOT / "tests/fixtures/v8/phase12_expected_deltas.json").read_text())[category]})
        self.assertEqual(sorted(d.split(":")[0] for d in LP.compare(p11, self.summary)), p12)

    def test_no_engine_reads_the_decision(self):
        # The desk pages consume the published decision: since v8 Phase 12 through their shared core (desk.js), which
        # alone names the file, on Today, the Analyzer, Funding and Portfolio. No engine and no other page reads it.
        self.assertIn('file: "data/v8/decision.json"', (ROOT / "desk.js").read_text(encoding="utf-8"))
        self.assertIn('schema: "v8.decision/1"', (ROOT / "desk.js").read_text(encoding="utf-8"))
        for page in ("today.html", "funding.html", "portfolio.html", "analyze.html"):
            self.assertIn("D.loadDecision()", (ROOT / page).read_text(encoding="utf-8"), page)
        for name in ("scanner.py", "quant.py", "picks.py", "smart.py", "dashboard.py", "quant.html", "picks.html",
                     "smart.html", "index.html", "research.html", "tools/research/qexport.py"):
            self.assertNotIn("decision.json", (ROOT / name).read_text(encoding="utf-8"), name)
            self.assertIsNone(re.search(r"\bimport\s+[^\n]*\bdecision\b|from\s+v8\s+import\s+decision",
                                        (ROOT / name).read_text(encoding="utf-8")), name)
        users = sorted(os.path.relpath(f, ROOT) for f in glob.glob(str(ROOT / "v8" / "*.py"))
                       if re.search(r"import\s+decision\b|from \. import decision", Path(f).read_text(encoding="utf-8")))
        self.assertEqual(users, ["v8/snapshot.py"])


if __name__ == "__main__":
    unittest.main()
