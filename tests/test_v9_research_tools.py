"""HANDOVER G3: the research tools behind the probation tier and phase D.

- tools/v9/confirm.py: the gate's statistics (Holm, day clustering, one-sided p, concentration, the demotion band) and
  every check (b) to (j), on hand-checked values.
- tools/v9/evidence_d1.py and evidence_d2.py: an end-to-end run on the synthetic archive, the dataset comparison with
  phase B, and outputs that confirm.load_trades reads back.

Needs the research libraries (numpy, pandas, numba; or PYTHONPATH=tools/v9/devstub locally)."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "research"))
sys.path.insert(0, str(ROOT / "tools" / "v9"))
sys.path.insert(0, str(ROOT / "tests"))

try:
    import numpy as np
    import confirm as C
    import evidence_d1 as E1
    import evidence_d2 as E2
    import test_v9_d1 as T1
    import test_v9_d2 as T2
    HAVE = True
except Exception:  # noqa: BLE001 - the research stack is optional outside the research job
    HAVE = False


def good_h():
    w = lambda m, p=0.001, n=300: {"mean_R": m, "p_one_sided": p, "n": n}  # noqa: E731
    pos = {"available": True, "all": {"mean_R": 0.1}, "holdout": {"mean_R": 0.1}, "design_window": {"mean_R": 0.1}}
    return {"windows": {"holdout": w(0.2), "design_window": w(0.2, 0.01), "recent_third": w(0.1), "all": w(0.2)},
            "cost_stress_1_5_mean_R": 0.1, "twin_edge": {"mean_R": 0.05}, "trades": 600,
            "concentration": {"top1_positive_fraction": 0.01, "top5_positive_fraction": 0.04,
                              "top10_positive_fraction": 0.07, "month_positive_fraction": 0.05,
                              "leave_one_asset_out_min_mean_R": 0.1},
            "variants": {k: copy.deepcopy(pos) for k in ("top80", "delay1", "delay2", "delay3", "delay6")}}


@unittest.skipUnless(HAVE, "research libraries unavailable")
class Statistics(unittest.TestCase):
    def test_holm_step_down(self):
        self.assertEqual([round(x, 6) for x in C.holm([0.01, 0.04, 0.03, 0.005])], [0.03, 0.06, 0.06, 0.02])
        self.assertEqual(C.holm([None, 0.01]), [1.0, 0.02])                  # a missing p counts as 1
        self.assertEqual(C.holm([0.6, 0.6]), [1.0, 1.0])                      # capped at 1

    def test_day_clustering_and_one_sided_p(self):
        few = C.clustered([0.1] * 50, [d % 29 for d in range(50)])
        self.assertIsNone(few["se"])                                          # fewer than 30 days: no interval
        rng = np.random.default_rng(3)
        v, days = rng.normal(0.1, 1, 600), np.repeat(np.arange(60), 10)
        st = C.clustered(v, days)
        self.assertAlmostEqual(st["mean_R"], float(v.mean()))
        self.assertEqual((st["n"], st["days"]), (600, 60))
        self.assertAlmostEqual(st["lower_95"], st["mean_R"] - 1.96 * st["se"])
        self.assertAlmostEqual(C.p_one_sided({"mean_R": 1.96, "se": 1.0}), 0.025, places=3)
        self.assertEqual((C.p_one_sided({"mean_R": 0.1, "se": 0}), C.p_one_sided({"mean_R": -0.1, "se": 0})), (0.0, 1.0))
        self.assertIsNone(C.p_one_sided({"mean_R": 0.1, "se": None}))

    def test_concentration(self):
        c = C.concentration(np.array([1.0, 2.0, -1.0, 3.0]), np.array(["A", "B", "A", "C"]),
                            ["2024-01", "2024-01", "2024-02", "2024-03"])
        self.assertAlmostEqual(c["top1_positive_fraction"], 0.5)
        self.assertAlmostEqual(c["month_positive_fraction"], 0.5)             # 2024-01 holds 3 of the 6
        self.assertAlmostEqual(c["leave_one_asset_out_min_mean_R"], 2 / 3)    # without C: (1 + 2 - 1) / 3
        self.assertEqual(c["assets"], 3)

    def test_demotion_band_is_seeded_and_ordered(self):
        saved = (C.BAND_TRADES, C.BAND_REPLICATIONS)
        C.BAND_TRADES, C.BAND_REPLICATIONS = (30, 100), 400
        try:
            rng = np.random.default_rng(1)
            net, days = rng.normal(0.15, 1.2, 900), np.repeat(np.arange(300), 3)
            a = C.demotion_band(net, days, np.random.default_rng(C.BAND_SEED))
            b = C.demotion_band(net, days, np.random.default_rng(C.BAND_SEED))
        finally:
            C.BAND_TRADES, C.BAND_REPLICATIONS = saved
        self.assertEqual(a, b)
        self.assertEqual([x["trades"] for x in a], [30, 100])
        for x in a:
            self.assertLess(x["p05_mean_R"], x["p50_mean_R"])
        self.assertLess(a[0]["p05_mean_R"], a[1]["p05_mean_R"])               # wider band at fewer trades

    def test_every_check_and_the_trade_window(self):
        ck, window, delays = C.checks(good_h(), {"pass": True}, 0.01)
        self.assertTrue(all(ck.values()), ck)
        self.assertEqual(window, 24)
        mutations = {
            "a_definition_frozen": lambda h: None,
            "b_holdout_holm": lambda h: None,
            "c_design_window": lambda h: h["windows"]["design_window"].update(p_one_sided=0.2),
            "d_recent_third": lambda h: h["windows"]["recent_third"].update(mean_R=-0.01),
            "e_cost_stress": lambda h: h.update(cost_stress_1_5_mean_R=-0.01),
            "f_twin_edge": lambda h: h["twin_edge"].update(mean_R=-0.01),
            "g_concentration": lambda h: h["concentration"].update(top1_positive_fraction=0.9),
            "h_sample_size": lambda h: h["windows"]["holdout"].update(n=99),
            "i_deployable_universe": lambda h: h["variants"]["top80"]["design_window"].update(mean_R=-0.01),
            "j_late_entry": lambda h: h["variants"]["delay1"]["all"].update(mean_R=-0.01),
        }
        for name, mutate in mutations.items():
            with self.subTest(check=name):
                h = good_h()
                mutate(h)
                ck, window, _ = C.checks(h, {"pass": name != "a_definition_frozen"},
                                         0.06 if name == "b_holdout_holm" else 0.01)
                self.assertEqual(sorted(k for k, v in ck.items() if not v), [name])
                if name == "j_late_entry":
                    self.assertEqual(window, 0)
        h = good_h()
        h["variants"]["delay3"]["holdout"]["mean_R"] = -0.01                  # 12h fails: the window stops at 8h
        ck, window, delays = C.checks(h, {"pass": True}, 0.01)
        self.assertEqual((window, ck["j_late_entry"], delays["delay6"]), (8, True, True))


@unittest.skipUnless(HAVE, "research libraries unavailable")
class Runners(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.md = os.path.join(cls.tmp, "md")
        T1.fake(cls.md)
        names = T2.coins_of(cls.md)
        cls.mx = os.path.join(cls.tmp, "mx")
        T2.write_metrics(cls.md, cls.mx, {c: 0.6 + 0.1 * k for k, c in enumerate(names)},
                         {c: 2.0 - 0.05 * k for k, c in enumerate(names)})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def phase_b(self, digest):
        path = os.path.join(self.tmp, f"pb_{digest[:6]}.json")
        Path(path).write_text(json.dumps({"provenance": {"dataset_sha256": digest}}))
        return path

    def check_doc(self, doc, out, report, trades, family):
        self.assertEqual(doc["family"], family)
        for h in doc["hypotheses"]:
            self.assertEqual(sorted(h["checks"]), sorted(C.checks(good_h(), {"pass": True}, 0.01)[0]))
            self.assertIn(h["verdict"], ("CONFIRMED", "NOT_CONFIRMED"))
            self.assertEqual(h["verdict"] == "CONFIRMED", not h["failing"])
            self.assertTrue(h["checks"]["a_definition_frozen"])
        self.assertTrue(Path(out, report).read_text().startswith("# Phase D"))
        loaded, sha = C.load_trades(os.path.join(out, trades))
        self.assertEqual(len(sha), 64)
        sid = family[0].split(":")[0]
        self.assertTrue({sid, f"{sid}@top80", f"{sid}@delay1", f"{sid}@delay6"} <= set(loaded))

    def test_d1_runner_end_to_end(self):
        out = os.path.join(self.tmp, "d1_a")
        doc = E1.run(self.md, out, self.phase_b("0" * 64))
        self.check_doc(doc, out, "REPORT_D1.md", "trades_d1.json.gz",
                       ["XS_FUND_FADE:long", "XS_FUND_FADE:short", "XS_FLOW_MOM:long", "XS_FLOW_MOM:short"])
        self.assertIs(doc["data"]["same_dataset_as_phase_b"], False)
        again = E1.run(self.md, os.path.join(self.tmp, "d1_b"), self.phase_b(doc["data"]["dataset_sha256"]))
        self.assertIs(again["data"]["same_dataset_as_phase_b"], True)
        self.assertEqual([h["trades"] for h in again["hypotheses"]], [h["trades"] for h in doc["hypotheses"]])

    def test_d2_runner_end_to_end(self):
        out = os.path.join(self.tmp, "d2")
        doc = E2.run(self.md, self.mx, out, None)
        self.check_doc(doc, out, "REPORT_D2.md", "trades_d2.json.gz",
                       ["XS_TOP_DIV:long", "XS_TOP_DIV:short", "XS_CROWD_FADE:long", "XS_CROWD_FADE:short"])
        self.assertIsNone(doc["data"]["same_dataset_as_phase_b"])
        self.assertEqual(doc["lag_bars"], 6)
        for c in doc["data"]["coverage"].values():
            self.assertGreater(c["share"], 0.5)


if __name__ == "__main__":
    unittest.main()
