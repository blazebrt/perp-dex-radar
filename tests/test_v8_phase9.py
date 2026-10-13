"""Phase 9 independent arithmetic, adversarial authority and deployment separation tests."""
import copy
import itertools
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/research"))
from v8 import strategy_policy as SP, strategy_authority as SA
import strategy_census as SC

try:
    import numpy as np
    import multiple_testing as MT
    import matched_controls as MC
    import strategy_adjudication as AD
except ImportError:
    np = None


class Policy(unittest.TestCase):
    def test_policy_order_and_no_verdict_shortcut(self):
        import quant
        policy = SP.load(quant.STRATS)
        self.assertEqual(policy["runtime_order"], ["TSMOM", "TREND_EMA", "XSMOM"])
        self.assertEqual(quant.RUNTIME_ORDER, tuple(policy["runtime_order"]))
        self.assertFalse(hasattr(quant, "ORDER"))
        self.assertEqual({r["deployment_state"] for r in policy["strategies"]}, {"LEGACY_HOLDOVER"})
        self.assertEqual({r["research_state"] for r in policy["strategies"]}, {"INSUFFICIENT_EVIDENCE"})

    def test_bad_policy_fails_closed(self):
        import quant
        good = SP.load(quant.STRATS)
        variants = [None, {}, {**good, "schema": "bad"}, {**good, "runtime_order": ["TSMOM", "TSMOM"]},
                    {**good, "runtime_order": []}, {**good, "strategies": good["strategies"] * 2}]
        for key, value in (("strategy_id", "BOGUS"), ("deployment_state", "bad"), ("research_state", "bad"),
                           ("deployment_state", "ACTIVE_REQUALIFIED"), ("deployment_state", "DISABLED")):
            p = copy.deepcopy(good)
            p["strategies"][0][key] = value
            variants.append(p)
        for p in variants:
            with self.subTest(p=p), self.assertRaises(ValueError):
                SP.validate(p, quant.STRATS)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                SP.load(quant.STRATS, Path(d) / "absent")

    def test_active_without_evidence_is_invalid(self):
        import quant
        p = SP.load(quant.STRATS)
        p["strategies"][0].update(deployment_state="ACTIVE_REQUALIFIED", research_state="REQUALIFIED")
        with self.assertRaises(ValueError):
            SP.validate(p, quant.STRATS, ROOT)

    def test_holdover_can_have_requalified_research_without_promotion(self):
        import quant
        p = SP.load(quant.STRATS)
        p["strategies"][0]["research_state"] = "REQUALIFIED"
        self.assertEqual(SP.validate(p, quant.STRATS)["strategies"][0]["deployment_state"], "LEGACY_HOLDOVER")

    def test_census_and_canonical_parameters(self):
        cat = SC.catalog()
        self.assertEqual(len(cat), 24)
        self.assertEqual(len({r["strategy_id"] for r in cat}), 24)
        self.assertEqual(next(r for r in cat if r["strategy_id"] == "TSMOM")["params"]["look"], 30)
        for r in cat:
            self.assertEqual(SC.digest(r["params"]), r["parameter_hash"])

    def test_historical_census_deduplication_and_uncertainty(self):
        c = SC.build()
        self.assertEqual(c["known_lower_bound"], 199)
        self.assertEqual(sum(c["grid_settings"].values()), 180)
        self.assertEqual(len({r["trial_id"] for r in c["trials"]}), 199)
        self.assertFalse(c["complete"])
        self.assertIsNone(c["upper_bound"])
        self.assertEqual(len(c["reported_runs_without_code_binding"]), 24)
        self.assertTrue(any({"XSMOM_14D", "XSMOM_14D_7"}.issubset(r["aliases"]) for r in c["trials"]))

    def test_zero_trades_and_missing_values_never_qualify(self):
        for sid in ("TSMOM", "TREND_EMA", "XSMOM", "RANDOM"):
            e = {"strategy_id": sid, "pit_calendar_days": 0, "qualified_closed_trades": 0}
            self.assertEqual(SA.adjudicate(e)["research_state"], "INSUFFICIENT_EVIDENCE")

    def test_complete_gate_and_missing_method(self):
        e = {k: True for k in ("trial_census_complete", "trial_return_universe_complete", "pit_integrity_ok",
                              "prospective_registration_valid", "full_feature_authority", "robustness_slices_complete")}
        e.update(pit_calendar_days=400, qualified_closed_trades=1000, mean_R=.5, mean_R_lower_95=.3,
                 matched_edge=.2, matched_lower_95=.1, full_matched_fraction=.95, controls_per_signal=50, dsr_probability=.99,
                 pbo=.1, spa_p=.01, white_rc_p=.01, by_q=.01, oos_mean_R=.4, stress_1_5_mean_R=.3,
                 top1_positive_fraction=.01, top5_positive_fraction=.05, top10_positive_fraction=.1,
                 month_positive_fraction=.1, leave_one_asset_out_min_mean_R=.2)
        self.assertEqual(SA.adjudicate(e)["research_state"], "REQUALIFIED")
        for key in list(e):
            bad = dict(e)
            del bad[key]
            self.assertNotEqual(SA.adjudicate(bad)["research_state"], "REQUALIFIED", key)
        e["trial_census_complete"] = False
        self.assertEqual(SA.adjudicate(e)["research_state"], "INSUFFICIENT_EVIDENCE")


@unittest.skipIf(np is None, "numpy research dependencies required")
class Statistics(unittest.TestCase):
    def test_exporter_cannot_choose_winners_by_id_or_legacy_profit(self):
        import qexport
        for sid in list(qexport.TESTED) + ["UNSEEN"]:
            for stats in ({}, {"n":10000, "avg":100, "edge_t":100}):
                self.assertEqual(qexport.verdict(sid, stats, stats, stats, stats)[0], "LEGACY_SURVIVORSHIP_UNQUALIFIED")

    def test_fdr_hand_arithmetic(self):
        # Sorted raw [.01,.03,.04,.20], BH [.04,.053333,.053333,.20]; H4=25/12.
        r = MT.fdr([.20, .01, .04, .03])
        np.testing.assert_allclose(r["bh_q"], [.20, .04, 4*.04/3, 4*.04/3])
        np.testing.assert_allclose(r["by_q"], np.array(r["bh_q"])*25/12)
        self.assertGreater(r["by_q"][1], .05)

    def test_dsr_single_trial_symmetric_reference(self):
        # [-1,0,1] mean SR=0, skew=0; one-trial benchmark=0 => Phi(0)=.5.
        r = MT.dsr([-1., 0., 1.], 1, .2, True)
        self.assertEqual(r["probability"], .5)
        self.assertAlmostEqual(r["excess_kurtosis"], -1.5)

    def test_more_trials_deflates_lucky_winner(self):
        x = np.random.default_rng(171).normal(size=(500, 200))
        sharpe = x.mean(0) / x.std(0, ddof=1)
        winner = x[:, int(sharpe.argmax())]
        one = MT.dsr(winner, 1, float(sharpe.var(ddof=1)))
        many = MT.dsr(winner, 200, float(sharpe.var(ddof=1)))
        self.assertLess(many["probability"], one["probability"])
        self.assertLess(many["probability"], .95)

    def test_dsr_reference_non_normal(self):
        # Explicit independent moments on [1,1,1,5]: mean2, variance4, SR1,
        # skew=2/sqrt(3), Pearson kurtosis=7/3. N1 benchmark0.
        r = MT.dsr([1, 1, 1, 5], 1, .1)
        z = math.sqrt(3 / (1 - 2/math.sqrt(3) + (7/3-1)/4))
        expected = .5 * (1 + math.erf(z/math.sqrt(2)))
        self.assertAlmostEqual(r["probability"], expected)

    def test_pbo_hand_constructed_overfit(self):
        x = np.array([[1, -3], [3, -1], [-3, 1], [-1, 3]], float)
        r = MT.pbo(x, ["a", "b"], segments=2, min_segment_days=2)
        self.assertEqual(r["combinations"], 2)
        self.assertEqual(r["pbo"], 1)
        self.assertEqual([s["selected_strategy"] for s in r["splits"]], ["a", "b"])
        for row in r["splits"]:
            self.assertAlmostEqual(row["lambda"], -math.log(2))

    def test_pbo_no_random_individual_trade_splits(self):
        self.assertEqual(MT.pbo(np.ones((180, 24)), list(map(str, range(24))))["status"], MT.UNAVAILABLE)
        with self.assertRaises(ValueError):
            MT.pbo(np.ones((180, 24)), list(map(str, range(24))), segments=3)

    def test_circular_block_structure(self):
        ix = MT.circular_indices(35, 7, np.random.default_rng(8))
        for block in ix.reshape(5, 7):
            np.testing.assert_array_equal(np.diff(block) % 35, np.ones(6))
        np.testing.assert_array_equal(ix, MT.circular_indices(35, 7, np.random.default_rng(8)))

    def test_bootstrap_independent_finite_enumeration(self):
        # Fixed blocks partitioning two 14-day halves. Explicit half means give four resamples.
        x = np.array([[1., -2.]]*14 + [[-1., 4.]]*14)
        indices = np.array([list(a)+list(b) for a,b in itertools.product((range(14), range(14,28)), repeat=2)])
        r = MT.bootstrap_tests(x, {"case": "enumeration"}, indices=indices)
        self.assertAlmostEqual(r["white_statistic"], math.sqrt(28))
        # RC centered maximum [sqrt28,0,0,3sqrt28] => 2 exceedances, plus-one => 3/5.
        self.assertEqual(r["white_rc_p"], .6)
        self.assertEqual(r["hansen_spa_p"], .6)

    def test_injected_edge_survives_family_tests(self):
        x = np.random.default_rng(451).normal(size=(730, 24))
        x[:, 7] += .6
        r = MT.bootstrap_tests(x, {"fixture": "edge"}, replications=5000)
        self.assertLessEqual(r["white_rc_p"], .1)
        self.assertLessEqual(r["hansen_spa_p"], .05)
        self.assertLessEqual(r["fdr"]["by_q"][7], .05)

    def test_random_family_does_not_qualify(self):
        x = np.random.default_rng(88).normal(size=(730, 24))
        r = MT.bootstrap_tests(x, {"fixture": "null"}, replications=1000)
        self.assertTrue(all(q > .05 for q in r["fdr"]["by_q"]))
        for j in range(24):
            e = {"by_q": r["fdr"]["by_q"][j], "mean_R": float(x[:,j].mean())}
            self.assertNotEqual(SA.adjudicate(e)["status"], "REQUALIFIED")

    def test_seed_and_bootstrap_byte_determinism(self):
        self.assertEqual(MT.seed({"a": 1, "b": 2}), MT.seed({"b": 2, "a": 1}))
        x = np.random.default_rng(4).normal(size=(80, 4))
        self.assertEqual(json.dumps(MT.bootstrap_tests(x, {"a":1}, 30), sort_keys=True),
                         json.dumps(MT.bootstrap_tests(x, {"a":1}, 30), sort_keys=True))

    def test_registration_is_plan_not_ledger(self):
        c = SC.catalog()
        plan = AD.registration_plan(c, {"known_lower_bound": 199, "complete": False}, 100)
        self.assertTrue(AD.validate_plan(plan, c))
        plan["entries"][0]["evaluation_start"] = 99
        with self.assertRaises(ValueError):
            AD.validate_plan(plan, c)

    def test_registration_tampering_fails_closed(self):
        c = SC.catalog()
        plan = AD.registration_plan(c, {"known_lower_bound": 199, "complete": False}, 100)
        changes = {"corrections_planned": [], "historical_trial_count": 24,
                   "minimum_qualified_closed_trades": 1, "evaluation_horizon_days": 179,
                   "evaluation_start": 99, "start_rule": "RETROSPECTIVE",
                   "multiple_testing_family": "WINNING_THREE", "primary_metric": "ordinary_sharpe",
                   "fail_rule": "promote regardless", "code_files": {}, "code_hash": "wrong",
                   "parameter_hash": "wrong", "family": "wrong", "data_cutoff": 99}
        for key, value in changes.items():
            bad = copy.deepcopy(plan)
            bad["entries"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                AD.validate_plan(bad, c)
        for key, value in (("authority", "ACTIVE"), ("state", "REGISTERED"), ("schema", "wrong")):
            bad = copy.deepcopy(plan)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                AD.validate_plan(bad, c)
        bad = copy.deepcopy(plan)
        bad["entries"][1] = copy.deepcopy(bad["entries"][0])
        with self.assertRaises(ValueError):
            AD.validate_plan(bad, c)

    def test_clustered_not_iid_trades(self):
        rows = [{"decision_time": d*86400, "net_R": (-1)**d} for d in range(30) for _ in range(10)]
        r = AD.clustered(rows)
        self.assertAlmostEqual(r["se"], 1/math.sqrt(29))


@unittest.skipIf(np is None, "numpy research dependencies required")
class Controls(unittest.TestCase):
    def row(self, asset, beta=1):
        return {"asset": asset, "decision_time": 100, "direction": 1, "eligible": True,
                "features": {k: MC.feature(beta if k == "btc_beta" else 1, 99, "PIT_OBSERVED") for k in MC.FEATURES}}

    def test_nearest_and_tie_break_independent(self):
        r = MC.match(self.row("signal"), [self.row("Z", 3), self.row("B", 2), self.row("A", 2)], limit=2, min_controls=2)
        self.assertEqual([x["asset"] for x in r["controls"]], ["A", "B"])
        self.assertEqual(r["status"], "FULL")

    def test_future_and_current_only_cannot_supply_missing_features(self):
        for name in ("market_cap", "pit_liquidity"):
            for change in ({"known_at": 101}, {"source": "CURRENT_ONLY"}):
                signal = self.row("signal")
                signal["features"][name].update(change)
                r = MC.match(signal, [self.row(str(i)) for i in range(55)])
                self.assertIn(name, r["missing_dimensions"])
                self.assertNotEqual(r["status"], "FULL")

    def test_future_candidates_cannot_change_past_normalization(self):
        signal = self.row("s")
        rows = [self.row("a", 2), self.row("b", 3)]
        initial = MC.match(signal, rows, limit=2, min_controls=1)
        future = self.row("future", 1e9)
        future["decision_time"] = 101
        self.assertEqual(initial, MC.match(signal, rows+[future], limit=2, min_controls=1))

    def test_beta_edge_removed_by_controls(self):
        rows = [self.row(str(i)) for i in range(50)]
        m = MC.match(self.row("signal"), rows)
        outcomes = [{"asset": r["asset"], "decision_time": 100, "direction": 1, "fully_qualified": True,
                     "same_geometry": True, "net_R": 2.0} for r in rows]
        self.assertEqual(MC.outcome(m, 2., outcomes)["matched_edge"], 0.)

    def test_missing_cap_and_duplicate_controls_fail(self):
        signal = self.row("signal")
        del signal["features"]["market_cap"]
        r = MC.match(signal, [self.row(str(i)) for i in range(50)])
        self.assertIn("MATCHED_CONTROL_MARKET_CAP_MISSING", r["reasons"])
        with self.assertRaises(ValueError):
            MC.match(signal, [self.row("a"), self.row("a")])

@unittest.skipUnless(np is not None, "research libraries")
class EndToEndCutoff(unittest.TestCase):
    def test_qualified_rows_and_future_append_invariance(self):
        import gzip
        import shutil
        from tests import test_v8_phase8 as B
        from v8 import history as H
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            md, hist = root / "md", root / "history"
            coins = ["BTC", "ETH", "ALT"]
            hours = 24 * 60
            cutoff = B.T0 + hours * B.HOUR
            funding = {c: [(B.T0 + h * B.HOUR, 0., 8) for h in range(0, hours + 1, 8)] for c in coins}
            B.synthetic_md(str(md), coins, B.T0, hours, funding=funding)
            store = H.DirStore(str(hist))
            contracts = [B.contract("hyperliquid:" + c, c, vol=5e6) for c in coins]
            for h in range(0, hours + 1, 6):
                B.append(store, B.snapshot(B.T0 + h * B.HOUR, "cutoff-" + str(h), contracts))
            out = root / "before"
            AD.run(str(md), str(hist), cutoff, out, replications=20)
            doc = json.loads((out / "research_strategy_adjudication.json").read_text())
            self.assertGreater(sum(r["sample_counts"]["fully_qualified_closed_trades"] for r in doc["strategies"]), 0)
            self.assertEqual(doc["provenance"]["history_cutoff_head_hash"], H.verify(store)["head_hash"])
            self.assertEqual(doc["requalified_count"], 0)
            first = {p.name: p.read_bytes() for p in out.glob("*.json")}
            # Append only after cutoff, including a new asset known only in the future.
            for c in coins:
                with gzip.open(md / "h1" / (c + ".csv.gz"), "at") as f:
                    f.write(f"{cutoff},100,110,90,105,2000000\n")
                with gzip.open(md / "fund_mexc" / (c + ".csv.gz"), "at") as f:
                    f.write(f"{cutoff + 8 * B.HOUR},0.1,8\n")
            with gzip.open(md / "h1" / "FUTURE.csv.gz", "wt") as f:
                f.write(f"t,o,h,l,c,v\n{cutoff},100,110,90,105,2000000\n")
            B.append(store, B.snapshot(cutoff + 6 * B.HOUR, "future", contracts + [B.contract("hyperliquid:FUTURE", "FUTURE")]))
            AD.run(str(md), str(hist), cutoff, root / "after", replications=20)
            second = {p.name: p.read_bytes() for p in (root / "after").glob("*.json")}
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
