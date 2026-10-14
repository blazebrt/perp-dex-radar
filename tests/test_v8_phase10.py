"""v8 Phase 10: governed portfolio and risk realism - arithmetic, limits, fail-closed inputs, what-if, stress,
dependence, point-in-time, determinism, audit integration and isolation from every earlier authority."""
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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))
from v8 import portfolio_risk as PR  # noqa: E402

DAY = 86400
T0 = 1_780_012_800 // DAY * DAY
N_BARS = 50
AS_OF = T0 + N_BARS * DAY
EQUITY = 1000.0


def make_returns(n=N_BARS, seed=7):
    """Deterministic daily closes: BTC (market), HI and TWIN (beta ~1.2, highly correlated with each other), LO
    (independent), NEG (negatively correlated with the market)."""
    rng = random.Random(seed)
    px = {a: 100.0 for a in ("BTC", "HI", "TWIN", "LO", "NEG")}
    out = {a: [] for a in px}
    for k in range(n):
        m = rng.gauss(0, .03)
        common = rng.gauss(0, .01)
        moves = {"BTC": m, "HI": 1.2 * m + common + rng.gauss(0, .004), "TWIN": 1.2 * m + common + rng.gauss(0, .004),
                 "LO": rng.gauss(0, .03), "NEG": -m + rng.gauss(0, .01)}
        for a, r in moves.items():
            px[a] *= math.exp(r)
            out[a].append([T0 + k * DAY, px[a]])
    return out


RET = make_returns()


def pos(pid, asset="HI", d=1, notional=100.0, strategy="TSMOM", vol=5e6, rate=0.0, hours=24.0, stop_pct=0.05,
        entered=True, **kw):
    p = {"id": pid, "asset": asset, "strategy": strategy, "direction": d, "mark": 100.0,
         "stop": 100.0 * (1 - d * stop_pct), "notional": notional, "entered": entered,
         "liquidity": {"state": "KNOWN", "volume": vol},
         "funding": {"state": "OBSERVED" if rate else "OBSERVED_ZERO", "rate_8h": rate},
         "hold_hours_remaining": hours}
    p.update(kw)
    return p


def portfolio(positions, returns=None, equity=EQUITY, as_of=AS_OF, **kw):
    return {"equity": equity, "as_of": as_of, "positions": positions,
            "returns": copy.deepcopy(RET if returns is None else returns), **kw}


def base_positions():
    return [pos("a", "HI", 1, 100.0, "TSMOM", rate=0.0001), pos("b", "TWIN", 1, 80.0, "XSMOM"),
            pos("c", "LO", -1, 60.0, "TREND_EMA", rate=0.0002), pos("d", "HI", 1, 40.0, "XSMOM")]


def policy(**limits):
    p = copy.deepcopy(PR.load_policy())
    for k, v in limits.items():
        p["limits"][k]["value"] = v
    return p


def permissive():
    return policy(**{k: 1e6 for k in PR.SECTIONS["limits"]})


def canon(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Policy(unittest.TestCase):
    def test_policy_is_governed_and_labelled(self):
        p = PR.load_policy()
        self.assertEqual(p["schema"], "v8.portfolio-risk-policy/1")
        self.assertEqual(p["review_status"], "POLICY_REVIEWED_INITIAL_V1")
        self.assertEqual(PR.REVIEW_STATUS, "POLICY_REVIEWED_INITIAL_V1")
        for word in ("empirically validated", "statistically validated", "optimized", "backtested", "proven"):
            self.assertNotIn("is " + word, p["statement"].lower())
        self.assertIn("None is an empirically validated quantity", p["statement"])
        entries = [p["approach_fraction"]] + [e for sec in PR.SECTIONS for e in p[sec].values()]
        self.assertEqual({e["basis"] for e in entries}, {"POLICY", "GOVERNED_CONSTANT"})
        self.assertTrue(all(e["rationale"].strip() for e in entries))
        self.assertEqual({k for k, e in p["costs"].items() if e["basis"] == "GOVERNED_CONSTANT"},
                         {"fee_taker", "slippage_tiers"})
        self.assertTrue(all(e["basis"] == "POLICY" for e in p["limits"].values()))
        self.assertEqual(PR.policy_hash(p), PR.policy_hash(PR.load_policy()))

    def test_empirical_basis_and_malformed_policy_fail_closed(self):
        good = PR.load_policy()
        bad = []
        b = copy.deepcopy(good)
        b["limits"]["max_gross_leverage"]["basis"] = "EMPIRICALLY_VALIDATED"
        bad.append(("empirical basis", b))
        for label, mutate in (
                ("schema", lambda q: q.update(schema="v8.portfolio-risk-policy/0")),
                ("missing limit", lambda q: q["limits"].pop("max_net_leverage")),
                ("extra limit", lambda q: q["limits"].update(max_vibes={"value": 1, "unit": "", "basis": "POLICY",
                                                                         "rationale": "x"})),
                ("extra section", lambda q: q.update(other={})),
                ("negative limit", lambda q: q["limits"]["max_gross_leverage"].update(value=-1)),
                ("nan limit", lambda q: q["limits"]["max_gross_leverage"].update(value=float("nan"))),
                ("bool limit", lambda q: q["limits"]["max_gross_leverage"].update(value=True)),
                ("approach above 1", lambda q: q["approach_fraction"].update(value=1.2)),
                ("tiers ascending", lambda q: q["costs"]["slippage_tiers"].update(value=[[0.0, .002], [1e6, .0005]])),
                ("tiers no zero", lambda q: q["costs"]["slippage_tiers"].update(value=[[1e6, .0005]])),
                ("tier slip falls", lambda q: q["costs"]["slippage_tiers"].update(value=[[1e6, .002], [0.0, .001]])),
                ("overlap above lookback", lambda q: q["dependence"]["min_overlap_bars"].update(value=61)),
                ("regime above lookback", lambda q: q["dependence"]["min_regime_bars"].update(value=61)),
                ("market move 1", lambda q: q["stress"]["market_move"].update(value=1.0)),
                ("cost multiplier < 1", lambda q: q["stress"]["cost_multiplier"].update(value=.5)),
                ("float steps", lambda q: q["stress"]["liquidity_tier_steps"].update(value=1.5)),
                ("no rationale", lambda q: q["stress"]["stop_gap_fraction"].update(rationale=" ")),
                ("extra field", lambda q: q["stress"]["stop_gap_fraction"].update(source="x")),
                ("pending status", lambda q: q.update(review_status="POLICY_DEFAULT_PENDING_REVIEW")),
                ("free-form status", lambda q: q.update(review_status="reviewed")),
                ("validated status", lambda q: q.update(review_status="EMPIRICALLY_VALIDATED")),
                ("status case", lambda q: q.update(review_status="policy_reviewed_initial_v1")),
                ("status not str", lambda q: q.update(review_status=None)),
                ("empty statement", lambda q: q.update(statement=" "))):
            b = copy.deepcopy(good)
            mutate(b)
            bad.append((label, b))
        for label, b in bad:
            with self.subTest(policy=label):
                with self.assertRaises(PR.PolicyError):
                    PR.validate_policy(b)
                r = PR.evaluate(portfolio(base_positions()), b)
                self.assertEqual(r["state"], PR.UNEVALUABLE)
                self.assertEqual(r["missing_authorities"], ["PORTFOLIO_RISK_POLICY_INVALID"])

    def test_costs_match_the_governed_cost_constants(self):
        import quant
        p = PR.load_policy()
        self.assertEqual(p["costs"]["fee_taker"]["value"], quant.CFG["fee_taker"])
        self.assertEqual([tuple(t) for t in p["costs"]["slippage_tiers"]["value"]],
                         [(float(a), b) for a, b in quant.CFG["slip"]])
        tree = ast.parse((ROOT / "tools/research/pit_cost.py").read_text(encoding="utf-8"))
        consts = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
                  if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                  and n.targets[0].id in ("SLIP_TIERS", "FEE_SCHEDULE")}
        self.assertEqual([tuple(t) for t in p["costs"]["slippage_tiers"]["value"]], list(consts["SLIP_TIERS"]))
        self.assertEqual(p["costs"]["fee_taker"]["value"], consts["FEE_SCHEDULE"]["taker"])

    def test_no_threshold_literal_in_the_authority(self):
        """Every threshold is read from the policy: the module's numeric literals are only arithmetic/definitional
        (counts, the 8-hour funding period, hours, the top-3/top-5 definitions, truncation sizes)."""
        tree = ast.parse((ROOT / "v8/portfolio_risk.py").read_text(encoding="utf-8"))
        allowed = {0, 1, 2, 3, 5, 8.0, 0.0, 1.0, 1e-15, 50, 300, 3600, 3600.0}
        validation = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_check_value")
        skip = {id(n) for n in ast.walk(validation)}
        found = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and id(n) not in skip
                 and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)}
        self.assertLessEqual(found, allowed, found - allowed)


class Arithmetic(unittest.TestCase):
    def ev(self, positions, pol=None, **kw):
        return PR.evaluate(portfolio(positions, **kw), pol or permissive())

    def test_trade_level_risk(self):
        r = self.ev([pos("a", notional=200.0, rate=0.0003, hours=48.0, vol=5e5, entered=False)])
        p = r["positions"][0]
        self.assertEqual(p["status"], "VALID")
        self.assertAlmostEqual(p["stop_distance"], .05)
        self.assertAlmostEqual(p["leverage"], .2)
        self.assertAlmostEqual(p["account_risk"], .01)
        self.assertAlmostEqual(p["notional_usd"], 200.0)
        self.assertEqual(p["orders_to_pay"], 2)
        self.assertAlmostEqual(p["expected_fees"], 2 * .00045 * .2)
        self.assertEqual(p["liquidity"]["slippage_rate"], .001)
        self.assertAlmostEqual(p["expected_slippage"], 2 * .001 * .2)
        self.assertAlmostEqual(p["funding"]["expected"], .0003 * 6 * .2)
        self.assertAlmostEqual(p["risk"]["expected_executable"], .01 + 2 * .00045 * .2 + 2 * .001 * .2 + .0003 * 6 * .2)
        self.assertEqual(p["risk"]["nominal_R"], 1.0)
        self.assertEqual(p["risk"]["stressed_stop_R"], 1.5)
        self.assertAlmostEqual(p["risk"]["gap_slippage"], .005)
        self.assertEqual(p["hold_hours_remaining"], 48.0)

    def test_sizing_inputs_agree(self):
        rows = [self.ev([{**pos("a"), "notional": None, k: v}])["positions"][0]
                for k, v in (("quantity", 2.0), ("notional", 200.0), ("risk_fraction", .01))]
        for row in rows:
            self.assertAlmostEqual(row["leverage"], .2)
            self.assertAlmostEqual(row["account_risk"], .01)

    def test_slippage_tiers_and_observed_zero_volume(self):
        for vol, rate in ((5e6, .0005), (1e6, .0005), (999_999.0, .001), (2e5, .001), (1e5, .002), (0.0, .002)):
            self.assertEqual(self.ev([pos("a", vol=vol)])["positions"][0]["liquidity"]["slippage_rate"], rate, vol)

    def test_long_only_short_only_and_offset(self):
        cases = {"long": [pos("a", "HI", 1), pos("b", "LO", 1)], "short": [pos("a", "HI", -1), pos("b", "LO", -1)],
                 "offset": [pos("a", "HI", 1), pos("b", "LO", -1)]}
        expect = {"long": (.2, .2, 0.0, .2), "short": (.2, 0.0, .2, -.2), "offset": (.2, .1, .1, 0.0)}
        for name, ps in cases.items():
            x = self.ev(ps)["exposure"]
            g, l, s, n = expect[name]
            self.assertAlmostEqual(x["gross_leverage"], g, msg=name)
            self.assertAlmostEqual(x["long_leverage"], l, msg=name)
            self.assertAlmostEqual(x["short_leverage"], s, msg=name)
            self.assertAlmostEqual(x["net_leverage"], n, msg=name)
            self.assertAlmostEqual(x["gross_notional_usd"], 200.0, msg=name)
            self.assertAlmostEqual(x["net_usd"], n * EQUITY, msg=name)
            self.assertIsInstance(x["short_leverage"], float)
        r = self.ev(cases["short"])
        self.assertAlmostEqual(r["limits"]["max_net_leverage"]["metric"], .2)   # |net| is limited, not signed net

    def test_same_asset_duplicates_and_multiple_strategies(self):
        r = self.ev([pos("a", "HI", 1, strategy="TSMOM"), pos("b", "HI", 1, strategy="XSMOM"),
                     pos("c", "HI", -1, strategy="TREND_EMA"), pos("d", "LO", 1, strategy="TSMOM")])
        c = r["concentration"]
        self.assertAlmostEqual(c["asset"]["HI"]["stop_risk"], .015)     # opposite directions still add (conservative)
        self.assertAlmostEqual(c["asset"]["HI"]["notional"], .3)
        self.assertAlmostEqual(c["asset"]["HI"]["net"], .1)
        self.assertEqual(c["shared_assets"], ["HI"])
        self.assertEqual(c["offsetting_assets"], ["HI"])
        self.assertEqual(c["multi_strategy_assets"], ["HI"])
        self.assertEqual(c["strategy_overlap"], {"TREND_EMA|TSMOM": ["HI"], "TREND_EMA|XSMOM": ["HI"],
                                                  "TSMOM|XSMOM": ["HI"]})
        self.assertAlmostEqual(r["limits"]["max_asset_stop_risk"]["metric"], .015)
        self.assertAlmostEqual(r["limits"]["max_strategy_stop_risk"]["metric"], .01)
        clusters = r["dependence"]["clusters"]
        self.assertIn(["a", "b"], [cl["positions"] for cl in clusters])     # same asset, same direction = one cluster
        self.assertNotIn("c", next(cl for cl in clusters if "a" in cl["positions"])["positions"])

    def test_largest_top3_top5_concentration(self):
        sizes = [500.0, 400.0, 300.0, 200.0, 100.0, 100.0]
        assets = ["HI", "TWIN", "LO", "NEG", "BTC", "LO"]
        r = self.ev([pos(f"p{k}", a, 1, s) for k, (a, s) in enumerate(zip(assets, sizes))])
        c = r["concentration"]
        total = sum(sizes)
        for kind in ("nominal_share", "stop_risk_share"):
            self.assertAlmostEqual(c[kind]["largest"], 500 / total)
            self.assertAlmostEqual(c[kind]["top3"], 1200 / total)
            self.assertAlmostEqual(c[kind]["top5"], 1500 / total)
        self.assertAlmostEqual(c["asset_nominal_share"]["largest"], 500 / total)
        self.assertAlmostEqual(c["asset_stop_risk_share"]["top3"], 1300 / total)     # LO's two positions merge
        self.assertAlmostEqual(r["limits"]["max_position_leverage"]["metric"], .5)
        self.assertEqual(self.ev([])["concentration"]["nominal_share"], {"largest": None, "top3": None, "top5": None})

    def test_gross_versus_net_and_beta_weighting(self):
        r = self.ev([pos("a", "HI", 1, 300.0), pos("b", "NEG", 1, 300.0)])
        self.assertAlmostEqual(r["exposure"]["net_leverage"], .6)
        beta = r["dependence"]["beta"]
        self.assertGreater(beta["HI"]["value"], 1)
        self.assertLess(beta["NEG"]["value"], 0)
        self.assertAlmostEqual(r["dependence"]["beta_weighted_net_leverage"],
                               .3 * beta["HI"]["value"] + .3 * beta["NEG"]["value"])

    def test_funding_direction_and_credits_never_reduce_risk(self):
        r = self.ev([pos("a", "HI", 1, rate=.0002), pos("b", "LO", -1, rate=.0002)])
        a, b = r["positions"]
        self.assertGreater(a["funding"]["expected"], 0)        # a long pays positive funding
        self.assertLess(b["funding"]["expected"], 0)           # a short receives it
        self.assertAlmostEqual(b["risk"]["expected_executable"], b["account_risk"] + b["expected_fees"]
                               + b["expected_slippage"])       # the credit is not netted against risk
        self.assertAlmostEqual(r["funding"]["known_adverse"], a["funding"]["expected"])

    def test_accrued_funding_known_and_unknown(self):
        r = self.ev([pos("a", funding_accrued={"state": "OBSERVED", "amount_usd": 2.5}), pos("b", "LO")])
        a, b = r["positions"]
        self.assertAlmostEqual(a["funding"]["accrued"], .0025)
        self.assertEqual(b["funding"]["accrued_state"], "UNKNOWN")
        self.assertIsNone(b["funding"]["accrued"])
        self.assertEqual(r["funding"]["accrued_unknown_positions"], ["b"])


class Limits(unittest.TestCase):
    """Exactly at, immediately below and immediately above every governed limit."""
    def setUp(self):
        self.pf = portfolio(base_positions())
        self.base = PR.evaluate(self.pf, permissive())
        self.assertEqual(self.base["state"], PR.WITHIN)
        self.assertEqual(self.base["missing_authorities"], [])

    def test_every_limit_at_below_above(self):
        for key in PR.SECTIONS["limits"]:
            m = self.base["limits"][key]["metric"]
            self.assertGreater(m, 0, key)
            with self.subTest(limit=key):
                at = PR.evaluate(self.pf, dict(permissive(), limits={**permissive()["limits"],
                                                                     key: {**permissive()["limits"][key], "value": m}}))
                self.assertEqual(at["limits"][key]["status"], "APPROACHING")
                self.assertEqual(at["state"], PR.APPROACHING)
                self.assertEqual(at["approaching"], [key])
                below = self.with_limit(key, math.nextafter(m, 0))       # the limit immediately below the metric
                self.assertEqual(below["limits"][key]["status"], "BREACHED")
                self.assertEqual(below["state"], PR.BREACHED)
                self.assertEqual(below["breached"], [key])
                above = self.with_limit(key, math.nextafter(m, math.inf))
                self.assertEqual(above["limits"][key]["status"], "APPROACHING")
                self.assertEqual(above["state"], PR.APPROACHING)
                far = self.with_limit(key, m / .8 * 1.5)
                self.assertEqual(far["limits"][key]["status"], "OK")
                self.assertEqual(far["state"], PR.WITHIN)

    def with_limit(self, key, value):
        p = permissive()
        p["limits"][key]["value"] = value
        return PR.evaluate(self.pf, p)

    def test_approach_fraction_moves_the_band(self):
        key = "max_gross_leverage"
        m = self.base["limits"][key]["metric"]
        p = permissive()
        p["limits"][key]["value"] = 2 * m
        for frac, status in ((.5, "APPROACHING"), (math.nextafter(.5, 1), "OK"), (.6, "OK"), (.4, "APPROACHING")):
            p["approach_fraction"]["value"] = frac
            self.assertEqual(PR.evaluate(self.pf, p)["limits"][key]["status"], status, frac)

    def test_mutating_every_governed_value_changes_the_result(self):
        """Every numeric policy value is consumed: changing any one changes the governed result."""
        positions = base_positions() + [pos("u", "LO", 1, 50.0, "TSMOM", liquidity={"state": "MISSING"})]
        pf = portfolio(positions, closed_trade_r=[(-1.0 if k % 3 else .5) for k in range(50)])
        base = canon(PR.evaluate(pf))
        mutations = {("approach_fraction", None): .01,
                     ("costs", "fee_taker"): .001,
                     ("costs", "slippage_tiers"): [[1e6, .0007], [2e5, .0012], [0.0, .0025]],
                     ("dependence", "bar_seconds"): 43200, ("dependence", "lookback_bars"): 40,
                     ("dependence", "min_overlap_bars"): 50, ("dependence", "cluster_correlation"): .99,
                     ("dependence", "market_asset"): "ETH", ("dependence", "min_regime_bars"): 45,
                     ("stress", "market_move"): .2, ("stress", "stop_gap_fraction"): 1.0,
                     ("stress", "cost_multiplier"): 3.0, ("stress", "liquidity_tier_steps"): 0,
                     ("stress", "unknown_liquidity_multiplier"): 3.0, ("stress", "adverse_funding_8h"): .002,
                     ("empirical", "tail_min_closed_trades"): 10}
        for key in PR.SECTIONS["limits"]:
            mutations[("limits", key)] = PR.load_policy()["limits"][key]["value"] * 1e-6
        every = {("approach_fraction", None)} | {(s, k) for s, keys in PR.SECTIONS.items() for k in keys}
        self.assertEqual(set(mutations), every)
        for (section, key), value in sorted(mutations.items(), key=str):
            with self.subTest(value=f"{section}.{key}"):
                p = copy.deepcopy(PR.load_policy())
                (p[section] if key is None else p[section][key])["value"] = value
                self.assertNotEqual(canon(PR.evaluate(pf, p)), base)

    def test_each_limit_value_decides_the_state(self):
        for key in PR.SECTIONS["limits"]:
            with self.subTest(limit=key):
                tight = self.with_limit(key, self.base["limits"][key]["metric"] / 2)
                self.assertIn(key, tight["breached"])
                self.assertEqual(tight["state"], PR.BREACHED)


class MissingData(unittest.TestCase):
    def assert_unevaluable(self, r, code):
        self.assertEqual(r["state"], PR.UNEVALUABLE)
        self.assertTrue(any(m == code or m.startswith(code) for m in r["missing_authorities"]),
                        (code, r["missing_authorities"]))

    def test_missing_liquidity_is_never_zero_slippage(self):
        for liq in ({"state": "MISSING"}, {"state": "NOT_ON_TRADE_DEX"}, {"state": "KNOWN", "volume": None},
                    {"state": "KNOWN", "volume": float("nan")}, {"state": "KNOWN", "volume": -1.0}, None, "KNOWN"):
            with self.subTest(liquidity=liq):
                r = PR.evaluate(portfolio([pos("a", liquidity=liq), pos("b", "LO")]))
                self.assert_unevaluable(r, "LIQUIDITY_UNKNOWN:a")
                p = r["positions"][0]
                self.assertIsNone(p["expected_slippage"])
                self.assertIsNone(p["risk"]["expected_executable"])
                self.assertGreater(p["risk"]["degraded_liquidity_bound"],
                                   p["account_risk"] + p["expected_fees"] + .002 * p["leverage"])
                self.assertIsNone(r["liquidity"]["expected_executable_risk"])
                self.assertEqual(r["limits"]["max_executable_risk"]["status"], "UNAVAILABLE")

    def test_missing_funding_is_never_zero(self):
        for f in ({"state": "MISSING"}, {"state": "OBSERVED"}, {"state": "OBSERVED", "rate_8h": float("inf")},
                  {"state": "OBSERVED_ZERO", "rate_8h": .001}, None):
            with self.subTest(funding=f):
                r = PR.evaluate(portfolio([pos("a", funding=f)]))
                self.assert_unevaluable(r, "FUNDING_UNKNOWN:a")
                self.assertIsNone(r["positions"][0]["funding"]["expected"])
                self.assertEqual(r["funding"]["unknown_positions"], ["a"])
        r = PR.evaluate(portfolio([pos("a", hours=None)]))
        self.assert_unevaluable(r, "HOLD_HORIZON_UNKNOWN:a")
        self.assertEqual(r["stress"]["scenarios"]["FUNDING_DETERIORATION"]["status"], "UNAVAILABLE")

    def test_missing_dependence_input(self):
        ret = copy.deepcopy(RET)
        del ret["LO"]
        r = PR.evaluate(portfolio([pos("a", "HI"), pos("b", "LO", -1)], returns=ret))
        self.assert_unevaluable(r, "DEPENDENCE_UNAVAILABLE:HI|LO")
        self.assertIn("BETA_UNAVAILABLE:LO", r["missing_authorities"])
        self.assertEqual(r["limits"]["max_cluster_stop_risk"]["status"], "UNAVAILABLE")
        self.assertIsNone(r["dependence"]["diversified_stop_risk"])
        self.assertEqual(r["stress"]["scenarios"]["CORRELATED_MARKET_MOVE"]["status"], "UNAVAILABLE")
        short = {a: v[-10:] for a, v in RET.items()}      # too few common bars: unavailable, never independence
        self.assert_unevaluable(PR.evaluate(portfolio([pos("a", "HI"), pos("b", "LO")], returns=short)),
                                "DEPENDENCE_UNAVAILABLE")
        ret = copy.deepcopy(RET)
        ret["LO"][5][1] = float("nan")                     # a non-finite close invalidates the series
        self.assert_unevaluable(PR.evaluate(portfolio([pos("a", "HI"), pos("b", "LO")], returns=ret)),
                                "DEPENDENCE_UNAVAILABLE")
        ret = copy.deepcopy(RET)
        ret["LO"] = [[t, 100.0] for t, _ in RET["LO"]]     # zero variance: no correlation
        self.assert_unevaluable(PR.evaluate(portfolio([pos("a", "HI"), pos("b", "LO")], returns=ret)),
                                "DEPENDENCE_UNAVAILABLE")
        ret = copy.deepcopy(RET)
        del ret["BTC"]
        self.assert_unevaluable(PR.evaluate(portfolio([pos("a", "HI")], returns=ret)), "BETA_UNAVAILABLE:HI")

    def test_missing_stop_and_malformed_trades(self):
        cases = {"stop missing": dict(stop=None), "stop wrong side": dict(stop=101.0), "stop zero": dict(stop=0.0),
                 "stop nan": dict(stop=float("nan")), "mark inf": dict(mark=float("inf")), "mark missing": dict(mark=None),
                 "direction 0": dict(direction=0), "direction bool": dict(direction=True),
                 "direction 2": dict(direction=2), "two sizes": dict(quantity=1.0), "no size": dict(notional=None),
                 "negative size": dict(notional=-5.0), "nan size": dict(notional=float("nan")),
                 "asset missing": dict(asset=""), "strategy missing": dict(strategy=None),
                 "entered not bool": dict(entered="yes"), "negative horizon": dict(hours=None, hold_hours_remaining=-1.0)}
        for label, change in cases.items():
            with self.subTest(case=label):
                p = pos("a")
                p.update(change)
                r = PR.evaluate(portfolio([p, pos("b", "LO")]))
                self.assert_unevaluable(r, "POSITION_MALFORMED:a")
                self.assertEqual(r["positions"][0]["status"], "MALFORMED")
                self.assertAlmostEqual(r["exposure"]["gross_leverage"], .1)    # excluded from every sum
                self.assertTrue(all(v["status"] == "UNAVAILABLE" or v["status"] == "OK" for v in r["limits"].values()))
        r = PR.evaluate(portfolio([dict(pos("a"), stop=None)]))
        self.assertIn("STOP_MISSING:a", r["missing_authorities"])
        r = PR.evaluate(portfolio([dict(pos("a"), stop=101.0)]))
        self.assertIn("STOP_WRONG_SIDE:a", r["missing_authorities"])
        for raw in ("x", None, 3, ["a"]):
            self.assert_unevaluable(PR.evaluate(portfolio([raw])), "POSITION_MALFORMED")
        self.assert_unevaluable(PR.evaluate(portfolio([pos("a"), pos("a", "LO")])), "POSITION_MALFORMED:a")
        self.assert_unevaluable(PR.evaluate(portfolio([dict(pos("a"), id=None)])), "POSITION_MALFORMED:?")

    def test_invalid_portfolio_envelope(self):
        for eq in (0, -5.0, float("nan"), float("inf"), None, True, "1000"):
            self.assertEqual(PR.evaluate(portfolio([pos("a")], equity=eq))["missing_authorities"], ["EQUITY_INVALID"])
        for t in (None, 1.5, "x", True):
            self.assertEqual(PR.evaluate(portfolio([pos("a")], as_of=t))["missing_authorities"], ["AS_OF_INVALID"])
        self.assertEqual(PR.evaluate({"equity": 1.0, "as_of": 1, "positions": "x"})["missing_authorities"],
                         ["POSITIONS_INVALID"])
        self.assertEqual(PR.evaluate(None)["state"], PR.UNEVALUABLE)

    def test_known_breach_is_reported_despite_missing_authority(self):
        r = PR.evaluate(portfolio([pos("a", notional=5000.0, funding={"state": "MISSING"})]))
        self.assertEqual(r["state"], PR.BREACHED)              # a proven breach is never hidden behind "unknown"
        self.assertIn("max_position_leverage", r["breached"])
        self.assertIn("FUNDING_UNKNOWN:a", r["missing_authorities"])

    def test_empty_portfolio_is_within_limits(self):
        r = PR.evaluate(portfolio([], returns={}))
        self.assertEqual(r["state"], PR.WITHIN)
        self.assertEqual(r["exposure"]["gross_leverage"], 0.0)


class WhatIf(unittest.TestCase):
    def setUp(self):
        self.pf = portfolio(base_positions())
        self.frozen = canon(self.pf)

    def tearDown(self):
        self.assertEqual(canon(self.pf), self.frozen)       # the current portfolio is never modified

    def test_reduce_lowers_risk(self):
        w = PR.what_if(self.pf, {"action": "REDUCE", "id": "a", "fraction": .5})
        self.assertEqual(w["effect"], "REDUCES_RISK")
        self.assertLess(w["delta"]["max_gross_leverage"], 0)
        self.assertAlmostEqual(w["delta"]["max_gross_leverage"], -.05)
        self.assertEqual(w["authority"], "DIAGNOSTIC_NO_EXECUTION_NO_RANKING")
        full = PR.what_if(self.pf, {"action": "REDUCE", "id": "c", "fraction": 1})
        self.assertNotIn("c", [p["id"] for p in full["after_result"]["positions"]])

    def test_add_raises_risk_and_reports_leverage_after(self):
        proposal = pos("n", "TWIN", 1, 20.0, "TSMOM")
        del proposal["entered"]                                 # a proposal has not been entered yet
        w = PR.what_if(self.pf, {"action": "ADD", "position": proposal})
        self.assertEqual(w["effect"], "INCREASES_RISK")
        self.assertAlmostEqual(w["after"]["metrics"]["max_gross_leverage"],
                               w["before"]["metrics"]["max_gross_leverage"] + .02)
        row = next(p for p in w["after_result"]["positions"] if p["id"] == "n")
        self.assertEqual(row["orders_to_pay"], 2)               # a proposal pays entry and exit
        cats = [t["category"] for t in w["trace"]]
        self.assertEqual(cats[0], "PROPOSAL")
        self.assertIn("PROPOSED_TRADE_RISK", cats)
        self.assertIn("LIMIT_DELTA", cats)
        self.assertEqual(cats[-1], "FINAL_PORTFOLIO_EFFECT")

    def test_add_that_breaches_a_limit(self):
        w = PR.what_if(self.pf, {"action": "ADD", "position": pos("big", "NEG", 1, 900.0, "TSMOM")})
        self.assertEqual(w["effect"], "BREACHES_LIMIT")
        self.assertEqual(w["before"]["state"], PR.WITHIN)
        self.assertEqual(w["after"]["state"], PR.BREACHED)
        self.assertIn("max_executable_risk", w["after"]["breached"])
        self.assertEqual(w["limit_changes"]["max_executable_risk"], ["OK", "BREACHED"])

    def test_add_without_authority(self):
        for label, p in (("funding", pos("n", "LO", funding={"state": "MISSING"})),
                         ("stop", dict(pos("n", "LO"), stop=None)),
                         ("liquidity", pos("n", "LO", liquidity={"state": "MISSING"})),
                         ("returns", pos("n", "UNSEEN"))):
            with self.subTest(missing=label):
                w = PR.what_if(self.pf, {"action": "ADD", "position": p})
                self.assertEqual(w["effect"], "INSUFFICIENT_AUTHORITY")
                self.assertEqual(w["after"]["state"], PR.UNEVALUABLE)

    def test_hedge_is_mixed_not_safe(self):
        w = PR.what_if(self.pf, {"action": "ADD", "position": pos("h", "NEG", 1, 60.0, "TSMOM")})
        self.assertGreater(w["delta"]["max_gross_leverage"], 0)
        w2 = PR.what_if(self.pf, {"action": "ADD", "position": pos("h", "TWIN", -1, 60.0, "TSMOM")})
        self.assertLess(w2["delta"]["max_net_leverage"], 0)
        self.assertGreater(w2["delta"]["max_gross_leverage"], 0)
        self.assertEqual(w2["effect"], "MIXED")

    def test_invalid_proposals(self):
        for prop in (None, {}, {"action": "SELL"}, {"action": "ADD", "position": "x"},
                     {"action": "ADD", "position": pos("a")}, {"action": "REDUCE", "id": "zz", "fraction": .5},
                     {"action": "REDUCE", "id": "a", "fraction": 0}, {"action": "REDUCE", "id": "a", "fraction": 1.5},
                     {"action": "REDUCE", "id": "a", "fraction": float("nan")}):
            with self.subTest(proposal=prop):
                w = PR.what_if(self.pf, prop)
                self.assertEqual(w["effect"], "PROPOSAL_INVALID")
                self.assertIsNone(w["after"])

    def test_no_change(self):
        w = PR.what_if(self.pf, {"action": "ADD", "position": pos("z", "LO", 1, 1e-300, "TSMOM")})
        self.assertIn(w["effect"], ("NO_CHANGE", "INCREASES_RISK"))

    def test_no_ranking_or_execution_surface(self):
        public = {n for n in dir(PR) if not n.startswith("_") and callable(getattr(PR, n))}
        self.assertFalse({n for n in public if re.search(r"rank|order|execute|submit|top", n, re.I)})


class Stress(unittest.TestCase):
    def test_diversification_appears_normal_but_fails_under_stress(self):
        r = PR.evaluate(portfolio([pos("a", "HI", 1), pos("b", "LO", 1)]))
        d = r["dependence"]
        self.assertLess(d["diversified_stop_risk"], d["no_diversification_stop_risk"])
        self.assertGreater(d["diversification_claimed"], .1)
        s = r["stress"]["scenarios"]["DIVERSIFICATION_FAILURE"]
        expect = sum(p["account_risk"] + p["expected_fees"] + p["expected_slippage"] for p in r["positions"])
        self.assertAlmostEqual(s["loss"], expect)
        self.assertGreater(s["loss"], d["diversified_stop_risk"])

    def test_correlation_spike_has_no_offset_for_hedges(self):
        r = PR.evaluate(portfolio([pos("a", "HI", 1), pos("b", "TWIN", -1)]))
        self.assertLess(r["dependence"]["diversified_stop_risk"], .003)     # looks hedged in normal correlation
        self.assertGreater(r["stress"]["scenarios"]["DIVERSIFICATION_FAILURE"]["loss"], .01)

    def test_adverse_slippage_cost_liquidity_and_funding(self):
        ps = [pos("a", "HI", 1, rate=.0001, hours=80.0), pos("b", "LO", -1, vol=3e5, rate=.0009, hours=16.0),
              pos("u", "TWIN", 1, liquidity={"state": "MISSING"})]
        r = PR.evaluate(portfolio(ps))
        a, b, u = r["positions"]
        sc = r["stress"]["scenarios"]
        known = [a, b]
        self.assertEqual(sc["STOP_SLIPPAGE"]["status"], "UNAVAILABLE")         # u has no known cost
        self.assertAlmostEqual(sc["STOP_SLIPPAGE"]["known_lower_bound"],
                               sum(p["account_risk"] * 1.5 + p["expected_fees"] + p["expected_slippage"] for p in known)
                               + u["account_risk"] * 1.5)
        self.assertAlmostEqual(sc["EXECUTION_COST"]["known_lower_bound"],
                               sum(p["account_risk"] + 2 * (p["expected_fees"] + p["expected_slippage"]) for p in known)
                               + u["account_risk"])
        self.assertEqual(sc["LIQUIDITY_DEGRADATION"]["status"], "AVAILABLE")
        self.assertAlmostEqual(sc["LIQUIDITY_DEGRADATION"]["loss"],
                               a["account_risk"] + (.00045 + .001) * a["leverage"]
                               + b["account_risk"] + (.00045 + .002) * b["leverage"]
                               + u["account_risk"] + (.00045 + .002 * 2) * u["leverage"])
        fd = sc["FUNDING_DETERIORATION"]
        self.assertAlmostEqual(fd["known_lower_bound"],
                               a["account_risk"] + a["expected_fees"] + a["expected_slippage"] + .0005 * 10 * a["leverage"]
                               + b["account_risk"] + b["expected_fees"] + b["expected_slippage"] + .0005 * 2 * b["leverage"]
                               + u["account_risk"] + .0005 * 3 * u["leverage"])
        r2 = PR.evaluate(portfolio([pos("s", "LO", -1, rate=-.002, hours=16.0)]))     # observed adverse > stress rate
        p = r2["positions"][0]
        self.assertAlmostEqual(r2["stress"]["scenarios"]["FUNDING_DETERIORATION"]["loss"],
                               p["account_risk"] + p["expected_fees"] + p["expected_slippage"] + .002 * 2 * p["leverage"])

    def test_correlated_market_move(self):
        r = PR.evaluate(portfolio([pos("a", "HI", 1, 100.0), pos("b", "LO", 1, 100.0), pos("c", "NEG", 1, 100.0)]))
        beta = {k: v["value"] for k, v in r["dependence"]["beta"].items()}
        stops = {p["asset"]: p["account_risk"] for p in r["positions"]}
        worst = max(sum(min(-(beta[a] * s * .1 * .1), stops[a]) for a in ("HI", "LO", "NEG")) for s in (-1, 1))
        self.assertAlmostEqual(r["stress"]["scenarios"]["CORRELATED_MARKET_MOVE"]["loss"], max(0.0, worst))

    def test_stress_scenarios_are_all_named_and_governed(self):
        r = PR.evaluate(portfolio(base_positions()))
        self.assertEqual(tuple(r["stress"]["scenarios"]), PR.SCENARIOS)
        self.assertTrue(r["stress"]["complete"])
        self.assertEqual(r["stress"]["worst_available_loss"],
                         max(v["loss"] for v in r["stress"]["scenarios"].values()))
        self.assertEqual(r["stress"]["basis"], "POLICY stress sizes; deterministic; no probability is attached")


class NoFabricatedSafety(unittest.TestCase):
    def test_flat_net_book_that_is_dangerous(self):
        """Net exposure is zero, so a naive desk calls it flat; gross, stop risk and stress say otherwise."""
        r = PR.evaluate(portfolio([pos("L", "HI", 1, 1400.0, "TSMOM"), pos("S", "NEG", -1, 1400.0, "XSMOM")]))
        self.assertAlmostEqual(r["exposure"]["net_leverage"], 0.0)
        self.assertEqual(r["limits"]["max_net_leverage"]["status"], "OK")
        self.assertEqual(r["limits"]["max_gross_leverage"]["status"], "APPROACHING")
        self.assertEqual(r["state"], PR.BREACHED)
        for key in ("max_executable_risk", "max_side_stop_risk", "max_stressed_loss", "max_asset_stop_risk"):
            self.assertIn(key, r["breached"])
        # NEG moves against the market: the "hedge" short adds to the long's beta instead of offsetting it
        self.assertGreater(r["dependence"]["beta_weighted_net_leverage"], 2.0)
        self.assertGreater(r["stress"]["scenarios"]["DIVERSIFICATION_FAILURE"]["loss"], .14)

    def test_small_positions_in_one_dependence_cluster(self):
        """Every asset, strategy and side is within its limit; the co-moving cluster is not."""
        ps = [pos("a", "HI", 1, 100.0, "TSMOM"), pos("b", "TWIN", 1, 100.0, "XSMOM"),
              pos("c", "HI", 1, 80.0, "TREND_EMA"), pos("d", "TWIN", 1, 80.0, "TSMOM"),
              pos("e", "LO", -1, 60.0, "XSMOM"), pos("f", "BTC", 1, 60.0, "TREND_EMA")]
        r = PR.evaluate(portfolio(ps))
        self.assertEqual(r["state"], PR.BREACHED)
        self.assertEqual(r["breached"], ["max_cluster_stop_risk"])
        self.assertEqual(r["dependence"]["clusters"][0]["positions"], ["a", "b", "c", "d", "f"])
        self.assertGreater(r["limits"]["max_cluster_stop_risk"]["metric"], .02)
        for key in ("max_asset_stop_risk", "max_strategy_stop_risk", "max_side_stop_risk"):
            self.assertNotEqual(r["limits"][key]["status"], "BREACHED")


class PointInTime(unittest.TestCase):
    def test_future_and_unclosed_bars_never_change_an_evaluation(self):
        ps = base_positions()
        base = canon(PR.evaluate(portfolio(ps)))
        ret = copy.deepcopy(RET)
        for a in ret:
            ret[a].append([AS_OF, 1e9])                     # the bar that opens at as_of has not closed
            ret[a].append([AS_OF + DAY, 1e-9])              # a future bar
        self.assertEqual(canon(PR.evaluate(portfolio(ps, returns=ret))), base)
        ret = copy.deepcopy(RET)
        ret["HI"][-1][1] *= 1.5                             # the last closed bar is visible
        self.assertNotEqual(canon(PR.evaluate(portfolio(ps, returns=ret))), base)

    def test_window_ends_at_as_of(self):
        ps = base_positions()
        long_ret = make_returns(n=120, seed=7)
        cut = {a: v[:N_BARS] for a, v in long_ret.items()}
        self.assertEqual(canon(PR.evaluate(portfolio(ps, returns=long_ret))),
                         canon(PR.evaluate(portfolio(ps, returns=cut))))
        p = copy.deepcopy(PR.load_policy())
        old = {a: v[:N_BARS] for a, v in make_returns(n=200, seed=9).items()}
        late = AS_OF + 100 * DAY                            # every visible bar is older than the window
        r = PR.evaluate(portfolio(ps, returns=old, as_of=late), p)
        self.assertEqual(r["state"], PR.UNEVALUABLE)
        self.assertTrue(any(m.startswith("DEPENDENCE_UNAVAILABLE") for m in r["missing_authorities"]))

    def test_historical_liquidity_comes_from_the_pit_history_only(self):
        import portfolio_risk_pit as PRP
        from v8 import pit as PIT

        class FakeHistory:
            def __init__(self, rec):
                self.rec, self.calls = rec, []

            def liquidity_at(self, t, asset):
                self.calls.append((t, asset))
                return dict(self.rec)
        ok = {"state": "KNOWN", "value": 1234567.8, "precision": PIT.PRECISION_REGISTRY_8SIG, "observed_at": 5,
              "health": "OK", "reason": None}
        h = FakeHistory(ok)
        out = PRP.historical_liquidity(h, 100, "HI")
        self.assertEqual(h.calls, [(100, "HI")])
        self.assertEqual((out["state"], out["volume"]), ("KNOWN", 1234567.8))
        for label, rec, state in (
                ("v1 precision", dict(ok, precision=PIT.PRECISION_LOST_V1), PIT.LIQUIDITY_PRECISION_UNQUALIFIED),
                ("on a threshold", dict(ok, value=1_000_000.0), PIT.LIQUIDITY_PRECISION_UNQUALIFIED),
                ("stale", {"state": PIT.LIQUIDITY_HISTORY_UNKNOWN, "value": None, "reason": "STALE"},
                 PIT.LIQUIDITY_HISTORY_UNKNOWN),
                ("missing", {"state": "MISSING", "value": None}, "MISSING")):
            with self.subTest(case=label):
                out = PRP.historical_liquidity(FakeHistory(rec), 100, "HI")
                self.assertEqual(out["state"], state)
                self.assertIsNone(out["volume"])
                r = PR.evaluate(portfolio([pos("a", liquidity=out)]))
                self.assertIn("LIQUIDITY_UNKNOWN:a", r["missing_authorities"])

    def test_live_adapter_uses_only_the_scan_inputs(self):
        tr = {"id": "BTC-TSMOM-1", "c": "BTC", "s": "TSMOM", "d": 1, "t_in": AS_OF - 10 * 3600, "hold_h": 504,
              "px": 100.0, "stop": 90.0, "stop_pct": .1, "res": {"last_px": 110.0, "stop_now": 99.0}}
        universe = {"BTC": {"t": "BTC", "venues": {"hyperliquid": {}}, "trade_vol": 5e6}}
        daily = {"BTC": [{"t": t, "c": c} for t, c in RET["BTC"]]}
        pf = PR.live_portfolio([tr], universe, daily, AS_OF, 500.0, .005, ("hyperliquid",), [1.0, -1.0], "BTC")
        p = pf["positions"][0]
        self.assertEqual((p["mark"], p["stop"], p["entered"]), (110.0, 99.0, True))
        self.assertAlmostEqual(p["quantity"], 500 * .005 / (.1 * 100))
        self.assertEqual(p["funding"]["state"], "MISSING")
        self.assertEqual(p["liquidity"], {"state": "KNOWN", "volume": 5e6})
        self.assertAlmostEqual(p["hold_hours_remaining"], 494.0)
        self.assertEqual(pf["sizing"]["basis"], "PAGE_DEFAULT_SIZING")
        r = PR.evaluate(pf)
        self.assertEqual(r["state"], PR.UNEVALUABLE)
        self.assertEqual(r["missing_authorities"], ["FUNDING_UNKNOWN:BTC-TSMOM-1"])
        self.assertEqual(r["stop_realism"]["empirical_tail"]["status"], "INSUFFICIENT")


class Determinism(unittest.TestCase):
    def test_byte_identical_results(self):
        pf = portfolio(base_positions() + [pos("u", "LO", 1, liquidity={"state": "MISSING"})])
        a, b = canon(PR.evaluate(pf)), canon(PR.evaluate(copy.deepcopy(pf)))
        self.assertEqual(a, b)
        shuffled = dict(reversed(list(pf["returns"].items())))
        self.assertEqual(canon(PR.evaluate(dict(pf, returns=shuffled))), a)
        w1 = canon(PR.what_if(pf, {"action": "ADD", "position": pos("n", "NEG", -1)}))
        w2 = canon(PR.what_if(pf, {"action": "ADD", "position": pos("n", "NEG", -1)}))
        self.assertEqual(w1, w2)

    def test_identical_across_processes_and_hash_seeds(self):
        code = ("import json,sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import test_v8_phase10 as T; "
                "from v8 import portfolio_risk as PR; "
                "print(T.canon(PR.evaluate(T.portfolio(T.base_positions()))))" % (str(ROOT), str(ROOT / "tests")))
        outs = set()
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120,
                                 cwd=str(ROOT))
            self.assertEqual(res.returncode, 0, res.stderr[-1500:])
            outs.add(hashlib.sha256(res.stdout.encode()).hexdigest())
        self.assertEqual(len(outs), 1)


class Trace(unittest.TestCase):
    def test_trace_contract(self):
        r = PR.evaluate(portfolio(base_positions()))
        for t in r["trace"]:
            self.assertEqual(set(t), {"category", "input", "rule", "result", "effect"})
        cats = [t["category"] for t in r["trace"]]
        self.assertEqual(cats[:2], ["POLICY", "EQUITY"])
        self.assertEqual(cats.count("POSITION"), 4)
        for c in ("GROSS_EXPOSURE", "CONCENTRATION", "DEPENDENCE", "LIQUIDITY", "FUNDING", "STRESS"):
            self.assertIn(c, cats)
        self.assertEqual(cats.count("LIMIT"), len(PR.SECTIONS["limits"]))
        self.assertEqual(cats[-1], "STATE")
        self.assertEqual(r["trace"][-1]["result"], r["state"])
        self.assertEqual(r["schema"], "v8.portfolio-risk/1")
        self.assertEqual(r["policy_hash"], PR.policy_hash(PR.load_policy()))

    def test_stop_realism_and_empirical_tail(self):
        r = PR.evaluate(portfolio(base_positions(), closed_trade_r=[-1.2, .4] * 30))
        s = r["stop_realism"]
        self.assertAlmostEqual(s["gap_slippage"], s["normal_stop"] * .5)
        self.assertAlmostEqual(s["adverse_cost"], r["liquidity"]["expected_executable_risk"] - s["normal_stop"])
        self.assertEqual(s["empirical_tail"]["status"], "INSUFFICIENT")
        self.assertNotIn("worst_r", s["empirical_tail"])
        r = PR.evaluate(portfolio(base_positions(), closed_trade_r=[-1.2, .4] * 60))
        t = r["stop_realism"]["empirical_tail"]
        self.assertEqual((t["status"], t["n"], t["worst_r"], t["beyond_stop_fraction"]), ("AVAILABLE", 120, -1.2, .5))
        self.assertEqual(t["basis"], "EMPIRICAL_DIAGNOSTIC")
        self.assertEqual(PR.evaluate(portfolio(base_positions()))["stop_realism"]["empirical_tail"]["status"],
                         "UNAVAILABLE")


class AuditIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "tools" / "v8"))
        import legacy_parity as LP
        from v8 import snapshot as SN
        cls.tmp = tempfile.mkdtemp(prefix="v8p10")
        out = os.path.join(cls.tmp, "site")
        LP.run_pipeline(out)
        cls.summary = LP.summary(out)
        with open(os.path.join(out, "data", "v8", "parts", "quant.json")) as fh:
            cls.part = json.load(fh)
        cls.snap = SN.write(out, keep_parts=True)[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_quant_part_carries_the_full_evaluation(self):
        pr = self.part["portfolio_risk"]
        self.assertTrue(self.part["ok"])
        self.assertEqual(pr["schema"], "v8.portfolio-risk/1")
        self.assertEqual(pr["policy_hash"], PR.policy_hash(PR.load_policy()))
        self.assertIn(pr["state"], PR.STATES)
        self.assertEqual(pr["inputs"]["sizing"]["basis"], "PAGE_DEFAULT_SIZING")
        self.assertTrue(pr["inputs"]["funding"].startswith("MISSING"))
        self.assertTrue(pr["trace"])
        self.assertEqual(len(pr["positions"]), pr["inputs"]["positions"])
        self.assertNotEqual(pr["state"], PR.WITHIN)          # funding is not an authority live: never "safe"

    def test_snapshot_manifest_and_health(self):
        m = self.snap["manifest"]
        self.assertEqual((self.snap["schema"], m["audit_version"]), ("v8.audit/10", "v8-phase11.0"))
        pr = m["portfolio_risk"]
        self.assertEqual(pr["version"], "v8.portfolio-risk/1")
        self.assertEqual(pr["policy_schema"], "v8.portfolio-risk-policy/1")
        self.assertEqual(pr["health"], "PORTFOLIO_RISK_POLICY_OK")
        self.assertEqual(pr["policy_hash"], PR.policy_hash(PR.load_policy()))
        self.assertEqual(pr["bases"], ["GOVERNED_CONSTANT", "POLICY"])
        for name in ("v8/portfolio_risk.py", "v8/portfolio_risk_policy.json", "v8/audit_quant.py"):
            self.assertEqual(pr["files"][name], hashlib.sha256((ROOT / name).read_bytes()).hexdigest())
        ev = pr["evaluation"]
        self.assertEqual(ev["state"], self.part["portfolio_risk"]["state"])
        self.assertEqual(ev["missing_authority_count"], len(self.part["portfolio_risk"]["missing_authorities"]))
        self.assertEqual(self.snap["data_health"]["portfolio_risk"], [ev["state"]])
        self.assertEqual(self.snap["portfolio_risk"], self.part["portfolio_risk"])     # full result and trace kept
        self.assertEqual(self.snap["portfolio_risk"]["trace"][-1]["category"], "STATE")

    def test_legacy_outputs_unchanged(self):
        sys.path.insert(0, str(ROOT / "tools" / "v8"))
        import legacy_parity as LP
        with open(ROOT / "tests/fixtures/v8/legacy_parity_golden_phase10.json") as fh:
            golden = json.load(fh)
        with open(ROOT / "tests/fixtures/v8/legacy_parity_golden_phase9.json") as fh:
            self.assertEqual(json.load(fh)["combined"], golden["combined"])      # historical: Phase 10 changed none
        # on this branch, only the Phase 11 Analyzer authority cutover and the Phase 12 desk pages (pinned in the Phase 12
        # manifest) differ from the Phase 10 golden
        p12 = sorted({e["file"] for category in ("files", "code") for e in json.loads((ROOT / "tests/fixtures/v8/phase12_expected_deltas.json").read_text())[category]})
        v9b = {e["file"] for category in ("files", "code") for e in json.loads((ROOT / "tests/fixtures/v8/v9b_expected_deltas.json").read_text())[category]}
        self.assertEqual(sorted(d.split(":")[0] for d in LP.compare(golden, self.summary)), sorted(set(p12) | v9b | {"analyze.html", "analyze.js"}))
        with open(ROOT / "tests/fixtures/v8/legacy_parity_golden_v9b.json") as fh:
            self.assertEqual(LP.compare(json.load(fh), self.summary), [])

    def test_audit_never_raises(self):
        from v8 import audit_quant as AQ
        with mock.patch.object(PR, "evaluate", side_effect=RuntimeError("boom")):
            out = AQ.portfolio_risk_part(AS_OF, {}, {}, [], [], None, {"account": 500.0, "risk": .005}, ())
        self.assertEqual((out["state"], out["missing_authorities"]), (PR.UNEVALUABLE, ["PORTFOLIO_RISK_ERROR"]))
        self.assertIn("boom", out["error"])
        self.assertEqual(PR.audit_summary(None)["state"], PR.UNEVALUABLE)


def blocked(pid, asset="HI", d=1, notional=100.0, strategy="TSMOM", **kw):
    return pos(pid, asset, d, notional, strategy, actionability="IDENTITY_BLOCKED", **kw)


def actionable(pid, asset="HI", d=1, notional=100.0, strategy="TSMOM", **kw):
    return pos(pid, asset, d, notional, strategy, actionability="ACTIONABLE", **kw)


class BlockedOpenExposure(unittest.TestCase):
    """Not actionable is not "no exposure": an identity-blocked open position is existing economic exposure."""
    def book(self):
        return [actionable("a1", "HI", 1, 100.0, "TSMOM"), actionable("a2", "LO", -1, 60.0, "XSMOM")]

    def test_A_blocked_exposure_changes_portfolio_risk(self):
        without = PR.evaluate(portfolio(self.book()))
        withb = PR.evaluate(portfolio(self.book() + [blocked("b1", "TWIN", 1, 120.0, "TSMOM")]))
        self.assertEqual(without["state"], PR.WITHIN)
        lw, lb = without["limits"], withb["limits"]
        for key, inc in (("max_gross_leverage", .12), ("max_executable_risk", None), ("max_side_stop_risk", .006),
                         ("max_strategy_stop_risk", .006), ("max_stressed_loss", None), ("max_cluster_stop_risk", None),
                         ("max_net_leverage", .12)):
            with self.subTest(metric=key):
                self.assertGreater(lb[key]["metric"], lw[key]["metric"])
                if inc is not None:
                    self.assertAlmostEqual(lb[key]["metric"] - lw[key]["metric"], inc)
        b = withb["exposure"]["by_actionability"]
        self.assertEqual((b["ACTIONABLE"]["positions"], b["IDENTITY_BLOCKED"]["positions"]), (2, 1))
        self.assertAlmostEqual(b["IDENTITY_BLOCKED"]["gross_leverage"], .12)
        self.assertAlmostEqual(b["IDENTITY_BLOCKED"]["stop_risk"], .006)
        self.assertEqual(next(p for p in withb["positions"] if p["id"] == "b1")["actionability"], "IDENTITY_BLOCKED")
        self.assertEqual(withb["concentration"]["strategy"]["TSMOM"]["positions"], 2)
        self.assertIn("b1", [i for c in withb["dependence"]["clusters"] for i in c["positions"]])

    def test_B_blocked_exposure_can_create_a_breach(self):
        cases = {
            "max_asset_stop_risk": ([actionable("a", "HI", 1, 100.0, "TSMOM")], blocked("b", "HI", 1, 120.0, "XSMOM")),
            "max_side_stop_risk": ([actionable(f"a{k}", a, 1, 90.0, s) for k, (a, s) in
                                    enumerate((("HI", "TSMOM"), ("LO", "XSMOM"), ("NEG", "TREND_EMA"), ("BTC", "X1")))],
                                   blocked("b", "TWIN", 1, 160.0, "X2")),
            "max_strategy_stop_risk": ([actionable("a", "HI", 1, 150.0, "TSMOM"), actionable("c", "LO", -1, 150.0, "TSMOM")],
                                       blocked("b", "NEG", -1, 150.0, "TSMOM")),
            "max_gross_leverage": ([actionable("a", "LO", 1, 1800.0, "TSMOM", stop_pct=.001),
                                    actionable("c", "NEG", -1, 900.0, "XSMOM", stop_pct=.001)],
                                   blocked("b", "HI", 1, 600.0, "TREND_EMA", stop_pct=.001)),
            "max_cluster_stop_risk": ([actionable("a", "HI", 1, 100.0, "TSMOM"), actionable("c", "TWIN", 1, 100.0, "XSMOM"),
                                       actionable("d", "BTC", 1, 100.0, "TREND_EMA")],
                                      blocked("b", "HI", 1, 100.0, "X1")),
        }
        for key, (act, blk) in cases.items():
            with self.subTest(limit=key):
                alone = PR.evaluate(portfolio(act))
                self.assertNotIn(key, alone["breached"])
                self.assertNotEqual(alone["limits"][key]["status"], "BREACHED")
                full = PR.evaluate(portfolio(act + [blk]))
                self.assertIn(key, full["breached"])
                self.assertEqual(full["state"], PR.BREACHED)

    def test_C_missing_liquidity_does_not_erase_exposure(self):
        withb = PR.evaluate(portfolio(self.book() + [blocked("b1", "TWIN", 1, 120.0, liquidity={"state": "MISSING"})]))
        p = next(x for x in withb["positions"] if x["id"] == "b1")
        self.assertEqual(p["status"], "VALID")
        self.assertAlmostEqual(p["notional_usd"], 120.0)
        self.assertAlmostEqual(p["leverage"], .12)
        self.assertAlmostEqual(p["risk"]["theoretical_stop"], .006)
        self.assertIsNone(p["risk"]["expected_executable"])
        self.assertIn("LIQUIDITY_UNKNOWN:b1", withb["missing_authorities"])
        self.assertEqual(withb["state"], PR.UNEVALUABLE)
        self.assertEqual(withb["limits"]["max_executable_risk"]["status"], "UNAVAILABLE")
        self.assertAlmostEqual(withb["exposure"]["gross_leverage"], .1 + .06 + .12)
        self.assertAlmostEqual(withb["liquidity"]["theoretical_stop_risk"], .005 + .003 + .006)

    def test_D_outside_the_current_universe(self):
        ret = {a: v for a, v in RET.items() if a != "TWIN"}             # the asset left the scan: no bars, no liquidity
        pf = portfolio(self.book() + [blocked("gone", "TWIN", 1, 120.0, liquidity={"state": "MISSING"},
                                              funding={"state": "MISSING"})], returns=ret)
        r = PR.evaluate(pf)
        p = next(x for x in r["positions"] if x["id"] == "gone")
        self.assertEqual(p["status"], "VALID")
        self.assertAlmostEqual(r["exposure"]["gross_leverage"], .28)
        for code in ("LIQUIDITY_UNKNOWN:gone", "FUNDING_UNKNOWN:gone", "BETA_UNAVAILABLE:TWIN",
                     "DEPENDENCE_UNAVAILABLE:HI|TWIN"):
            self.assertIn(code, r["missing_authorities"])
        self.assertEqual(r["state"], PR.UNEVALUABLE)

    def test_E_unquantifiable_open_position_blocks_a_safe_state(self):
        base = PR.evaluate(portfolio(self.book()))
        self.assertEqual(base["state"], PR.WITHIN)
        for label, change in (("mark", {"mark": None}), ("stop", {"stop": None}), ("size", {"notional": None}),
                              ("mark nan", {"mark": float("nan")}), ("stop wrong side", {"stop": 110.0})):
            with self.subTest(missing=label):
                b = dict(blocked("u1", "TWIN"), **change)
                r = PR.evaluate(portfolio(self.book() + [b]))
                self.assertEqual(r["state"], PR.UNEVALUABLE)
                self.assertIn("OPEN_POSITION_RISK_UNQUANTIFIABLE:u1", r["missing_authorities"])
                self.assertEqual(r["exposure"]["unquantified_open_positions"], ["u1"])
                self.assertEqual(r["exposure"]["by_actionability"]["IDENTITY_BLOCKED"]["unquantified"], ["u1"])
                self.assertEqual(len(r["positions"]), 3)                     # reported, never dropped
                self.assertFalse(r["concentration"]["complete"])
                for key in ("max_gross_leverage", "max_side_stop_risk", "max_asset_stop_risk", "max_stressed_loss"):
                    self.assertEqual(r["limits"][key]["status"], "UNAVAILABLE", key)
        # a known lower bound that already breaches is still reported
        r = PR.evaluate(portfolio([actionable("big", "HI", 1, 2500.0), dict(blocked("u1", "TWIN"), mark=None)]))
        self.assertEqual(r["state"], PR.BREACHED)
        self.assertIn("OPEN_POSITION_RISK_UNQUANTIFIABLE:u1", r["missing_authorities"])
        # a proposal (not entered) that cannot be quantified is malformed, not an open position
        prop = dict(pos("p", "TWIN", entered=False), mark=None)
        self.assertNotIn("OPEN_POSITION_RISK_UNQUANTIFIABLE:p", PR.evaluate(portfolio([prop]))["missing_authorities"])

    def test_actionability_is_metadata_only(self):
        rows = {}
        for act in ("ACTIONABLE", "IDENTITY_BLOCKED", "PROPOSED", None):
            p = pos("x", "HI", 1, 100.0)
            if act:
                p["actionability"] = act
            r = PR.evaluate(portfolio([p]))
            rows[act] = r
            self.assertEqual(r["positions"][0]["actionability"], act or "UNSPECIFIED")
        strip = lambda r: canon({k: v for k, v in r.items() if k not in ("positions", "trace", "exposure")})
        self.assertEqual(len({strip(r) for r in rows.values()}), 1)          # identical risk whatever the label
        self.assertEqual(len({r["exposure"]["gross_leverage"] for r in rows.values()}), 1)
        bad = PR.evaluate(portfolio([dict(pos("x"), actionability="TRADE_NOW")]))
        self.assertIn("POSITION_MALFORMED:x", bad["missing_authorities"])

    def test_G_what_if_baseline_is_the_whole_open_book(self):
        tr_a = {"id": "A", "c": "HI", "s": "TSMOM", "d": 1, "t_in": AS_OF - 3600, "hold_h": 48, "px": 100.0,
                "stop_pct": .05, "res": {"last_px": 100.0, "stop_now": 95.0}}
        tr_b = dict(tr_a, id="B", c="TWIN", s="XSMOM", res={"last_px": 100.0, "stop_now": 95.0})
        uni = {c: {"t": c, "venues": {"hyperliquid": {}}, "trade_vol": 5e6} for c in ("HI", "TWIN")}
        daily = {a: [{"t": t, "c": c} for t, c in RET[a]] for a in ("HI", "TWIN", "BTC")}
        live = PR.live_portfolio([tr_a], uni, daily, AS_OF, 1000.0, .005, ("hyperliquid",), None, "BTC",
                                 blocked_open=[tr_b])
        self.assertEqual(live["book"], {"ACTIONABLE": 1, "IDENTITY_BLOCKED": 1})
        self.assertEqual([p["actionability"] for p in live["positions"]], ["ACTIONABLE", "IDENTITY_BLOCKED"])
        only = PR.live_portfolio([tr_a], uni, daily, AS_OF, 1000.0, .005, ("hyperliquid",), None, "BTC")
        prop = pos("N", "LO", 1, 100.0)
        del prop["entered"]
        w = PR.what_if(live, {"action": "ADD", "position": prop})
        w_only = PR.what_if(only, {"action": "ADD", "position": prop})
        self.assertAlmostEqual(w["before"]["metrics"]["max_gross_leverage"], .2)        # both open positions
        self.assertAlmostEqual(w_only["before"]["metrics"]["max_gross_leverage"], .1)
        self.assertAlmostEqual(w["before"]["metrics"]["max_cluster_stop_risk"], .01)    # HI and TWIN co-move
        self.assertEqual({p["id"] for p in w["before_result"]["positions"]}, {"A", "B"})
        self.assertEqual(next(p for p in w["after_result"]["positions"] if p["id"] == "N")["actionability"], "PROPOSED")

    def test_live_mark_and_stop_are_never_fabricated(self):
        tr = {"id": "P", "c": "HI", "s": "TSMOM", "d": 1, "t_in": AS_OF - 3600, "hold_h": 48, "px": 100.0,
              "stop": 95.0, "stop_pct": .05, "res": None}
        p = PR.live_open_position(tr, "ACTIONABLE", {}, AS_OF, 1000.0, .005)
        self.assertIsNone(p["mark"])                   # no entry price stands in for the current mark
        self.assertIsNone(p["stop"])                   # no initial stop stands in for the current one
        self.assertEqual(p["liquidity"]["state"], "MISSING")
        r = PR.evaluate({"equity": 1000.0, "as_of": AS_OF, "positions": [p], "returns": {}})
        self.assertIn("OPEN_POSITION_RISK_UNQUANTIFIABLE:P", r["missing_authorities"])
        pending = dict(tr, px=None, res=None)          # a signal not yet filled has no size and no mark
        r = PR.evaluate({"equity": 1000.0, "as_of": AS_OF, "returns": {},
                         "positions": [PR.live_open_position(pending, "ACTIONABLE", {}, AS_OF, 1000.0, .005)]})
        self.assertIn("OPEN_POSITION_RISK_UNQUANTIFIABLE:P", r["missing_authorities"])


class BlockedOpenBookProduction(unittest.TestCase):
    """The real quant run (Phase 3 closure fixture): blocked positions are counted as exposure, stay blocked, and
    portfolio risk cannot change any quant output."""
    @classmethod
    def setUpClass(cls):
        import quant as Q
        import scanner as sc
        from tests import test_v8_phase3_closure as P3
        from v8 import identity as ID
        cls.P3 = P3
        cls.fx = P3.FakeExchange(n_coins=16, days=130, seed=5)
        cls.old = sc.FETCH, sc.now_ts
        sc.FETCH = cls.fx.fetch
        sc.now_ts = lambda: cls.fx.now
        cls.tmp = tempfile.mkdtemp(prefix="v8p10blk")
        t0 = (cls.fx.now // P3.H) * P3.H - 72 * P3.H
        opened = [P3.qtrade(P3.LEG_UNVERIFIED, t0, 10_000), P3.qtrade(P3.LEG_VERIFIED, t0, 10_000),
                  P3.qtrade(P3.MISSING, t0, 10_000), P3.proof(P3.qtrade(P3.DEGRADED_OPEN, t0, 10_000), P3.DEGRADED_OPEN),
                  P3.proof(P3.qtrade("FAKE12", t0, 10_000, d=-1), "FAKE12")]
        J = {"engine": Q.ENGINE, "version": Q.VERSION, "created": t0 - 300 * P3.H, "updated": t0, "scans": 5,
             "open": opened, "closed": [], "done": {}}
        cls.opened = {t["id"] for t in opened}
        jp = os.path.join(cls.tmp, "journal.json")
        with open(jp, "w") as fh:
            json.dump(J, fh)
        states = {P3.LEG_UNVERIFIED: ID.UNVERIFIED, P3.DEGRADED_OPEN: ID.AMBIGUOUS}
        uni = P3.universe(cls.fx, states, drop=(P3.MISSING,))
        cls.runs = {}
        for name, patch in (("gated", None), ("control", "all_verified"), ("no_risk", "disable")):
            out = os.path.join(cls.tmp, name)
            u = P3.universe(cls.fx) if patch == "all_verified" else copy.deepcopy(uni)
            if patch == "disable":
                with mock.patch.object(PR, "live_portfolio", side_effect=RuntimeError("disabled")):
                    Q.run(out, journal_path=jp, universe=u)
            else:
                Q.run(out, journal_path=jp, universe=u)
            data = os.path.join(out, "data")
            cls.runs[name] = {f: Path(data, f).read_bytes() for f in ("quant.json", "quant_journal.json")}
            cls.runs[name]["part"] = json.loads(Path(data, "v8", "parts", "quant.json").read_text())
            cls.runs[name]["pub"] = json.loads(cls.runs[name]["quant.json"])

    @classmethod
    def tearDownClass(cls):
        import scanner as sc
        sc.FETCH, sc.now_ts = cls.old
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_open_journal_position_is_in_portfolio_risk(self):
        g = self.runs["gated"]
        pub, pr = g["pub"], g["part"]["portfolio_risk"]
        open_ids = {o["id"] for o in pub["open"]}
        blocked_ids = {b["id"] for b in pub["blocked_open"]}
        self.assertEqual(len(blocked_ids), 3)              # unverified, ambiguous, and outside the universe
        self.assertEqual({p["id"] for p in pr["positions"]}, open_ids | blocked_ids)
        acts = {p["id"]: p["actionability"] for p in pr["positions"]}
        self.assertEqual({i for i, a in acts.items() if a == "IDENTITY_BLOCKED"}, blocked_ids)
        self.assertEqual({i for i, a in acts.items() if a == "ACTIONABLE"}, open_ids)
        self.assertEqual(pr["inputs"]["positions_by_actionability"],
                         {"ACTIONABLE": len(open_ids), "IDENTITY_BLOCKED": len(blocked_ids)})
        self.assertNotIn("identity_blocked_positions_not_evaluated", pr["inputs"])

    def test_D_outside_universe_position_keeps_its_exposure(self):
        pr = self.runs["gated"]["part"]["portfolio_risk"]
        gone = next(p for p in pr["positions"] if p["asset"] == self.P3.MISSING)
        self.assertEqual((gone["status"], gone["actionability"]), ("VALID", "IDENTITY_BLOCKED"))
        self.assertGreater(gone["leverage"], 0)
        self.assertEqual(gone["liquidity"]["state"], "MISSING")
        self.assertIn("LIQUIDITY_UNKNOWN:" + gone["id"], pr["missing_authorities"])
        self.assertIn("FUNDING_UNKNOWN:" + gone["id"], pr["missing_authorities"])
        self.assertNotEqual(pr["state"], PR.WITHIN)

    def test_blocked_exposure_equals_its_verified_exposure(self):
        """The same positions with every coin verified (control): identical exposure, only the label differs."""
        g = {p["id"]: p for p in self.runs["gated"]["part"]["portfolio_risk"]["positions"]}
        c = {p["id"]: p for p in self.runs["control"]["part"]["portfolio_risk"]["positions"]}
        # the journal's own positions (the control universe ranks XSMOM over more coins, so its new trades differ)
        self.assertLessEqual(self.opened, set(g) & set(c))
        for pid in sorted(self.opened):
            p = g[pid]
            if p["asset"] == self.P3.MISSING:
                continue                                    # the control universe also has its liquidity
            for key in ("leverage", "account_risk", "notional_usd", "direction", "mark", "stop"):
                self.assertEqual(p[key], c[pid][key], (pid, key))
        self.assertEqual({p["actionability"] for p in c.values()}, {"ACTIONABLE"})
        self.assertEqual({g[i]["actionability"] for i in self.opened if g[i]["asset"] in
                          (self.P3.LEG_UNVERIFIED, self.P3.DEGRADED_OPEN, self.P3.MISSING)}, {"IDENTITY_BLOCKED"})

    def test_F_phase3_separation_is_intact(self):
        g, n = self.runs["gated"], self.runs["no_risk"]
        # portfolio risk cannot change a quant output: byte-identical with the evaluation disabled
        strip = lambda raw: canon({k: v for k, v in json.loads(raw).items() if k != "duration_s"})   # wall clock
        self.assertEqual(strip(g["quant.json"]), strip(n["quant.json"]))
        self.assertEqual(g["quant_journal.json"], n["quant_journal.json"])
        self.assertEqual(n["part"]["portfolio_risk"]["missing_authorities"], ["PORTFOLIO_RISK_ERROR"])
        pub = g["pub"]
        blocked_ids = {b["id"] for b in pub["blocked_open"]}
        self.assertFalse(blocked_ids & {o["id"] for o in pub["open"]})          # still not actionable
        self.assertFalse(blocked_ids & {f"{s['c']}-{s['s']}-{s['t']}" for s in pub["signals"]})   # not an entry
        self.assertTrue(all(b["actionable"] is False for b in pub["blocked_open"]))
        self.assertTrue(all(o["identity"] == "VERIFIED_CRYPTO" for o in pub["open"]))
        import quant as Q
        from v8 import strategy_policy as SP
        self.assertEqual(SP.runtime_implementation_hash(),
                         __import__("v8.strategy_policy", fromlist=["runtime_implementation_hash"]).runtime_implementation_hash())
        src = (ROOT / "quant.py").read_text(encoding="utf-8")
        self.assertNotIn("portfolio_risk", src)
        self.assertTrue(callable(Q.split_open))


class EarlierAuthorityUnchanged(unittest.TestCase):
    def test_phase9_authority_and_runtime_code_unchanged(self):
        from v8 import strategy_policy as SP, strategy_authority as SA
        import quant
        self.assertEqual(SP.runtime_implementation_hash(),
                         __import__("v8.strategy_policy", fromlist=["runtime_implementation_hash"]).runtime_implementation_hash())
        policy = SP.load(quant.STRATS)
        # v9 phase B: the reviewed strategy policy now holds XSMOM's probation row (v8.quant-strategy-policy/2)
        self.assertEqual(SP.digest(policy), "67aa8122ae4a033af7352f0cf900e10d4bc1a2b744c545cc69c4c09b18ccf49e")
        self.assertEqual(policy["runtime_order"], ["TSMOM", "TREND_EMA", "XSMOM"])
        self.assertEqual({r["strategy_id"]: r["deployment_state"] for r in policy["strategies"]},
                         {"TSMOM": "LEGACY_HOLDOVER", "TREND_EMA": "LEGACY_HOLDOVER", "XSMOM": "ACTIVE_PROBATION"})
        self.assertEqual(SA.VERSION, "v8.strategy-research/1")
        import strategy_census as SC
        self.assertEqual(len(SC.catalog()), 24)
        self.assertEqual(SC.build()["known_lower_bound"], 199)

    def test_no_engine_reads_portfolio_risk(self):
        pat = re.compile(r"portfolio_risk")
        for name in ("scanner.py", "quant.py", "picks.py", "smart.py", "dashboard.py", "quant.html", "picks.html",
                     "smart.html", "index.html", "tools/research/qexport.py", "tools/research/qport.py"):
            self.assertIsNone(pat.search((ROOT / name).read_text(encoding="utf-8")), name)
        # v8 Phase 12: the Portfolio page shows the Phase 10 evaluation through the desk core only (the decision's
        # summary, and the audit snapshot's detail when it is the same evaluation); no other page reads it
        pages = sorted(f for f in os.listdir(ROOT) if f.endswith((".html", ".js")) and pat.search((ROOT / f).read_text(encoding="utf-8")))
        self.assertEqual(pages, ["desk.js"])
        users = sorted(os.path.relpath(f, ROOT) for f in glob.glob(str(ROOT / "v8" / "*.py"))
                       if pat.search(Path(f).read_text(encoding="utf-8")))
        # v8 Phase 11: the decision engine consumes Phase 10 what_if() (the brief requires it); no legacy engine does
        self.assertEqual(users, ["v8/__init__.py", "v8/audit_quant.py", "v8/decision.py", "v8/portfolio_risk.py",
                                 "v8/provenance.py", "v8/snapshot.py"])

    def test_legacy_planner_stays_a_labelled_diagnostic(self):
        text = (ROOT / "tools/research/qexport.py").read_text(encoding="utf-8")
        self.assertIn('PORTFOLIO_LABEL = "LEGACY_DIAGNOSTIC / NOT STRATEGY AUTHORITY"', text)
        research = json.loads((ROOT / "quant_research.json").read_text(encoding="utf-8"))
        self.assertNotIn("portfolio_risk", json.dumps(research))


if __name__ == "__main__":
    unittest.main()
