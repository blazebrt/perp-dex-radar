"""Phase 9 independent arithmetic, adversarial authority and deployment separation tests."""
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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


REQUIRED_TRUE = ("trial_census_complete", "trial_return_universe_complete", "pit_integrity_ok",
                 "prospective_registration_valid", "full_feature_authority", "robustness_slices_complete")
BOTH = {"params": {"sides": "both"}}


def side_row(n=500, mean=.5, upper=.7):
    return {"n": n, "mean_R": mean, "upper_95": upper}


def passing_evidence(sides=("long", "short")):
    """A synthetic evidence record that clears every gate check for a definition trading `sides`."""
    e = {k: True for k in REQUIRED_TRUE}
    e.update(pit_calendar_days=400, qualified_closed_trades=1000, mean_R=.5, mean_R_lower_95=.3,
             matched_edge=.2, matched_lower_95=.1, full_matched_fraction=.95, controls_per_signal=50,
             dsr_probability=.99, pbo=.1, spa_p=.01, white_rc_p=.01, by_q=.01, oos_mean_R=.4,
             stress_1_5_mean_R=.3, top1_positive_fraction=.01, top5_positive_fraction=.05,
             top10_positive_fraction=.1, month_positive_fraction=.1, leave_one_asset_out_min_mean_R=.2,
             sides={s: side_row() for s in sides})
    return e


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

    def test_audit_exposes_current_and_adjudicated_definition_bindings(self):
        import quant
        from v8 import provenance
        audit = provenance.strategy_authority()
        self.assertEqual(audit["runtime_definition_hashes"],
                         {sid: SP.digest(quant.STRATS[sid]) for sid in quant.RUNTIME_ORDER})
        self.assertEqual(len(audit["adjudicated_definition_bindings"]), 24)
        for sid, binding in audit["adjudicated_definition_bindings"].items():
            self.assertTrue(binding["stored_definition_hash_matches"], sid)
            self.assertEqual(binding["runtime_definition_hash"],
                             SP.digest(quant.STRATS[sid]) if sid in quant.STRATS else None)

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
        cat = {r["strategy_id"]: r for r in SC.catalog()}
        for sid in ("TSMOM", "TREND_EMA", "XSMOM", "RANDOM"):
            e = {"strategy_id": sid, "pit_calendar_days": 0, "qualified_closed_trades": 0}
            self.assertEqual(SA.adjudicate(e, cat.get(sid, BOTH))["research_state"], "INSUFFICIENT_EVIDENCE")

    def test_complete_gate_and_missing_method(self):
        definition = next(r for r in SC.catalog() if r["strategy_id"] == "TSMOM")
        e = passing_evidence()
        self.assertEqual(SA.adjudicate(e, definition)["research_state"], "REQUALIFIED")
        for key in list(e):
            bad = dict(e)
            del bad[key]
            self.assertNotEqual(SA.adjudicate(bad, definition)["research_state"], "REQUALIFIED", key)
        e["trial_census_complete"] = False
        self.assertEqual(SA.adjudicate(e, definition)["research_state"], "INSUFFICIENT_EVIDENCE")


class SideGate(unittest.TestCase):
    """Required sides come from the adjudicated definition, never from the evidence flag, the ID or runtime metadata."""
    def assert_not_requalified(self, e, definition, reason):
        verdict = SA.adjudicate(e, definition)
        self.assertNotEqual(verdict["research_state"], "REQUALIFIED")
        self.assertIn(reason, verdict["blocking_reasons"])

    def test_catalog_definitions_state_their_sides(self):
        for row in SC.catalog():
            self.assertEqual(SA.required_sides(row), ("long", "short"), row["strategy_id"])

    def test_both_sided_definition_requires_both_sides(self):
        definition = next(r for r in SC.catalog() if r["strategy_id"] == "TSMOM")
        long_only = passing_evidence(("long",))
        cases = []
        e = dict(long_only)                                   # the original exploit: no flag, no short evidence
        cases.append(("both_sides missing", e, "SHORT_SAMPLE_INSUFFICIENT"))
        cases.append(("both_sides false", {**passing_evidence(), "both_sides": False},
                      "BOTH_SIDES_FLAG_DISAGREES_WITH_DEFINITION"))
        cases.append(("both_sides false and short missing", {**long_only, "both_sides": False},
                      "SHORT_SAMPLE_INSUFFICIENT"))
        cases.append(("long evidence missing", passing_evidence(("short",)), "LONG_SAMPLE_INSUFFICIENT"))
        cases.append(("short evidence missing", {**long_only, "both_sides": True}, "SHORT_SAMPLE_INSUFFICIENT"))
        e = passing_evidence()
        e["sides"]["short"] = side_row(n=SA.GATE["minimum_side_trades"] - 1)
        cases.append(("short sample below minimum", e, "SHORT_SAMPLE_INSUFFICIENT"))
        e = passing_evidence()
        e["sides"]["short"] = side_row(mean=-.3, upper=-.1)
        cases.append(("short materially negative", e, "SHORT_MATERIAL_NEGATIVE_EDGE"))
        e = passing_evidence()
        e["sides"]["short"] = side_row(mean=None)
        cases.append(("short inference unavailable", e, "SHORT_INFERENCE_UNAVAILABLE"))
        e = passing_evidence()
        e["sides"] = None
        cases.append(("sides not a mapping", e, "LONG_SAMPLE_INSUFFICIENT"))
        for label, e, reason in cases:
            with self.subTest(case=label):
                self.assert_not_requalified(e, definition, reason)
        # The flag is not the authority: complete side evidence passes with or without an agreeing flag.
        self.assertEqual(SA.adjudicate(passing_evidence(), definition)["research_state"], "REQUALIFIED")
        self.assertEqual(SA.adjudicate({**passing_evidence(), "both_sides": True}, definition)["research_state"],
                         "REQUALIFIED")
        rejected = passing_evidence()
        rejected["sides"]["short"] = side_row(mean=-.3, upper=-.1)
        self.assertEqual(SA.adjudicate(rejected, definition)["research_state"], "REJECTED")

    def test_one_sided_definitions_do_not_require_the_other_side(self):
        for side, other in (("long", "short"), ("short", "long")):
            with self.subTest(side=side):
                definition = {"strategy_id": "SYNTHETIC_" + side.upper(), "params": {"sides": side}}
                e = passing_evidence((side,))
                self.assertEqual(SA.adjudicate(e, definition)["research_state"], "REQUALIFIED")
                self.assertEqual(SA.adjudicate({**e, "both_sides": False}, definition)["research_state"], "REQUALIFIED")
                self.assert_not_requalified({**e, "both_sides": True}, definition,
                                            "BOTH_SIDES_FLAG_DISAGREES_WITH_DEFINITION")
                bad = passing_evidence((side,))
                bad["sides"][side] = side_row(n=SA.GATE["minimum_side_trades"] - 1)
                self.assert_not_requalified(bad, definition, side.upper() + "_SAMPLE_INSUFFICIENT")
                # The other side's evidence is not consulted, even when it is bad.
                extra = passing_evidence((side,))
                extra["sides"][other] = side_row(n=0, mean=-9, upper=-8)
                self.assertEqual(SA.adjudicate(extra, definition)["research_state"], "REQUALIFIED")

    def test_sides_never_come_from_id_flag_or_runtime_metadata(self):
        import quant
        e = {**passing_evidence(("long",)), "both_sides": False}
        # Runtime metadata (no canonical sides) and missing/unknown definitions fail closed whatever the flag says.
        for definition in (quant.STRATS["TSMOM"], {}, None, {"params": {}}, {"params": {"sides": "sideways"}},
                           {"strategy_id": "TSMOM"}, {"params": {"sides": True}}):
            with self.subTest(definition=definition):
                self.assert_not_requalified(e, definition, "STRATEGY_SIDE_DEFINITION_UNAVAILABLE")
        # The strategy ID in the evidence or the definition never changes a verdict.
        definition = {"params": {"sides": "both"}}
        base = SA.adjudicate(passing_evidence(), definition)
        for sid in ("TSMOM", "XSMOM", "RANDOM", None):
            self.assertEqual(SA.adjudicate({**passing_evidence(), "strategy_id": sid},
                                           {**definition, "strategy_id": sid}), base)


class GateSingleSource(unittest.TestCase):
    """Tightening any GATE value changes the outcome, so no check can hide a duplicated literal."""
    TIGHTEN = {">=": lambda v: v * 10 + 1e6, ">": lambda v: v + 1e6, "<=": lambda v: v - 1e6}

    def test_every_gate_value_is_consumed(self):
        checked = {gate_key for _, gate_key, _, _ in SA.CHECKS}
        side = {"minimum_side_trades", "side_mean_floor_R", "side_upper_95_max_R"}
        methods = {"oos_fraction", "bootstrap_replications", "block_days", "cscv_segments", "cscv_min_segment_days"}
        self.assertEqual(set(SA.GATE), checked | side | methods)
        self.assertEqual(SA.GATE["leave_one_asset_out_min_mean_R"], 0)
        self.assertTrue(any(k == "leave_one_asset_out_min_mean_R" for k, _, _, _ in SA.CHECKS))

    def test_tightening_each_checked_gate_value_flips_the_verdict(self):
        definition = next(r for r in SC.catalog() if r["strategy_id"] == "TSMOM")
        for key, gate_key, op, kind in SA.CHECKS:
            with self.subTest(gate=gate_key):
                e = passing_evidence()
                self.assertEqual(SA.adjudicate(e, definition)["research_state"], "REQUALIFIED")
                with mock.patch.dict(SA.GATE, {gate_key: self.TIGHTEN[op](SA.GATE[gate_key])}):
                    verdict = SA.adjudicate(e, definition)
                self.assertNotEqual(verdict["research_state"], "REQUALIFIED")
                self.assertIn(key.upper() + ("_INSUFFICIENT" if kind == SA.INSUFFICIENT else "_FAILED"),
                              verdict["blocking_reasons"])
                # Exactly at the threshold: >= and <= pass, a strict > fails.
                at = dict(e, **{key: SA.GATE[gate_key]})
                self.assertEqual(SA.adjudicate(at, definition)["research_state"] == "REQUALIFIED", op != ">")

    def test_tightening_each_side_gate_value_flips_the_verdict(self):
        definition = next(r for r in SC.catalog() if r["strategy_id"] == "TSMOM")
        e = passing_evidence()
        e["sides"]["short"] = side_row(n=SA.GATE["minimum_side_trades"], mean=-.01, upper=-.001)
        self.assertEqual(SA.adjudicate(e, definition)["research_state"], "REQUALIFIED")
        for gate_key, value, reason in (("minimum_side_trades", SA.GATE["minimum_side_trades"] + 1,
                                         "SHORT_SAMPLE_INSUFFICIENT"),
                                        ("side_mean_floor_R", 0, "SHORT_MATERIAL_NEGATIVE_EDGE"),
                                        ("side_upper_95_max_R", .01, None)):
            with self.subTest(gate=gate_key), mock.patch.dict(SA.GATE, {gate_key: value}):
                verdict = SA.adjudicate(e, definition)
                if reason is None:      # upper bound alone (mean above the floor) still passes; both are required
                    self.assertEqual(verdict["research_state"], "REQUALIFIED")
                    with mock.patch.dict(SA.GATE, {"side_mean_floor_R": 0}):
                        self.assertIn("SHORT_MATERIAL_NEGATIVE_EDGE", SA.adjudicate(e, definition)["blocking_reasons"])
                    with mock.patch.dict(SA.GATE, {"side_mean_floor_R": 0, "side_upper_95_max_R": -.01}):
                        self.assertEqual(SA.adjudicate(e, definition)["research_state"], "REQUALIFIED")
                else:
                    self.assertIn(reason, verdict["blocking_reasons"])

    def test_verdict_reports_the_gate_it_applied(self):
        with mock.patch.dict(SA.GATE, {"pbo": .123}):
            self.assertEqual(SA.adjudicate({}, BOTH)["gate"]["pbo"], .123)


class PromotionFixture(unittest.TestCase):
    """Synthetic passing evidence never changes the repository deployment policy."""
    def setUp(self):
        import quant
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.strats = copy.deepcopy(quant.STRATS)
        self.policy = SP.load(quant.STRATS)
        e = {**passing_evidence(), "both_sides": True}
        self.row = next(r for r in SC.catalog() if r["strategy_id"] == "TSMOM")
        self.row.update(SA.adjudicate(e, self.row), evidence=e, runtime_definition_hash=SP.digest(self.strats["TSMOM"]),
                        runtime_implementation_hash=SP.runtime_implementation_hash())
        self.row["adjudicated_definition_hash"] = SP.adjudicated_definition_hash(self.row)
        self.artifact = {"schema": SA.VERSION, "strategies": [self.row]}
        self.ev = {"schema": "v8.reviewed-strategy-evidence/1", "strategy_id": "TSMOM",
                   "research_state": "REQUALIFIED", "blocking_reasons": [], "review_decision": "APPROVED",
                   "review_url": "https://github.com/blazebrt/perp-dex-radar/pull/21",
                   "adjudication_path": "adjudication.json",
                   "runtime_definition_hash": self.row["runtime_definition_hash"],
                   "runtime_implementation_hash": self.row["runtime_implementation_hash"],
                   "adjudicated_definition_hash": self.row["adjudicated_definition_hash"]}
        self.policy["strategies"][0].update(deployment_state="ACTIVE_REQUALIFIED", research_state="REQUALIFIED")
        self.write_package()

    def write_package(self, rehash_artifact=True):
        raw = (json.dumps(self.artifact, sort_keys=True) + "\n").encode()
        (self.root / "adjudication.json").write_bytes(raw)
        if rehash_artifact:
            self.ev["adjudication_sha256"] = hashlib.sha256(raw).hexdigest()
        raw = (json.dumps(self.ev, sort_keys=True) + "\n").encode()
        (self.root / "review.json").write_bytes(raw)
        self.policy["strategies"][0]["reviewed_evidence"] = {
            "path": "review.json", "sha256": hashlib.sha256(raw).hexdigest()}

    def assert_invalid(self, runtime_root=None, message="STRATEGY_POLICY_INVALID"):
        with self.assertRaisesRegex(ValueError, message):
            SP.validate(self.policy, self.strats, self.root, runtime_root)


class PromotionBinding(PromotionFixture):
    def test_positive_complete_promotion(self):
        self.assertEqual(SA.adjudicate(self.row["evidence"], self.row)["research_state"], "REQUALIFIED")
        self.assertEqual(self.row["runtime_implementation_hash"], SP.runtime_implementation_hash(ROOT))
        # Runtime hold_h/metadata and research hold_days/code are intentionally different representations.
        self.assertNotEqual(self.strats["TSMOM"]["params"], self.row["params"])
        self.assertIs(SP.validate(self.policy, self.strats, self.root), self.policy)

    def test_exact_old_acceptance_runtime_a_adjudication_with_runtime_b_review(self):
        self.assertEqual(self.strats["TSMOM"]["params"]["look"], 30)
        self.strats["TSMOM"]["params"]["look"] = 31
        self.ev["runtime_definition_hash"] = SP.digest(self.strats["TSMOM"])
        self.write_package()
        self.assert_invalid()

    def test_same_id_changed_research_definition_cannot_reuse_review(self):
        original = copy.deepcopy(self.row)
        for key, value in (("params", {**self.row["params"], "look": 60}), ("code_hash", "a" * 64)):
            with self.subTest(field=key):
                self.row.clear()
                self.row.update(copy.deepcopy(original))
                self.row[key] = value
                self.row["parameter_hash"] = SP.digest(self.row["params"])
                self.row["adjudicated_definition_hash"] = SP.adjudicated_definition_hash(self.row)
                self.write_package()  # Even a new artifact checksum cannot substitute for definition review.
                self.assert_invalid()

    def test_independent_tampering_matrix(self):
        originals = copy.deepcopy((self.strats, self.artifact, self.ev))
        changes = [
            ("runtime STRATS parameter", "runtime", "look", 31),
            ("adjudication params", "row", "params", {**self.row["params"], "look": 60}),
            ("adjudication parameter_hash", "row", "parameter_hash", "a" * 64),
            ("adjudication code_hash", "row", "code_hash", "a" * 64),
            ("adjudication implementation", "row", "implementation", "different_implementation"),
            ("adjudication code_files", "row", "code_files", {"different.py": "a" * 64}),
            ("reviewed runtime_definition_hash", "ev", "runtime_definition_hash", "a" * 64),
            ("reviewed adjudicated_definition_hash", "ev", "adjudicated_definition_hash", "a" * 64),
            ("reviewed runtime_implementation_hash", "ev", "runtime_implementation_hash", "a" * 64),
            ("adjudication runtime_implementation_hash", "row", "runtime_implementation_hash", "a" * 64),
            ("adjudication runtime_definition_hash", "row", "runtime_definition_hash", "a" * 64),
            ("adjudication adjudicated_definition_hash", "row", "adjudicated_definition_hash", "a" * 64),
            ("adjudication artifact bytes", "bytes", None, None),
            ("adjudication_sha256", "ev", "adjudication_sha256", "a" * 64),
            ("strategy_id", "row", "strategy_id", "TREND_EMA"),
            ("reviewed strategy_id", "ev", "strategy_id", "TREND_EMA"),
        ]
        for label, target, key, value in changes:
            with self.subTest(mutation=label):
                self.strats, self.artifact, self.ev = copy.deepcopy(originals)
                self.row = self.artifact["strategies"][0]
                if target != "bytes":
                    obj = self.strats["TSMOM"]["params"] if target == "runtime" else self.row if target == "row" else self.ev
                    obj[key] = value
                self.write_package(rehash_artifact=key != "adjudication_sha256")
                if target == "bytes":
                    with (self.root / "adjudication.json").open("ab") as f:
                        f.write(b" ")
                self.assert_invalid()

    def test_missing_definition_bindings_fail_closed(self):
        originals = copy.deepcopy((self.artifact, self.ev))
        for target, fields in (("ev", ("runtime_definition_hash", "adjudicated_definition_hash",
                                       "runtime_implementation_hash")),
                               ("row", ("runtime_definition_hash", "adjudicated_definition_hash",
                                        "runtime_implementation_hash", "implementation",
                                        "params", "parameter_hash", "code_hash", "code_files"))):
            for key in fields:
                for missing in (True, False):
                    with self.subTest(target=target, key=key, absent=missing):
                        self.artifact, self.ev = copy.deepcopy(originals)
                        obj = self.artifact["strategies"][0] if target == "row" else self.ev
                        if missing:
                            del obj[key]
                        else:
                            obj[key] = None
                        self.write_package()
                        self.assert_invalid()

    def test_intentionally_regenerated_review_package_can_promote_new_definition(self):
        self.strats["TSMOM"]["params"]["look"] = 31
        self.row["params"]["look"] = 31
        self.row["parameter_hash"] = SP.digest(self.row["params"])
        self.row["runtime_definition_hash"] = SP.digest(self.strats["TSMOM"])
        self.row["adjudicated_definition_hash"] = SP.adjudicated_definition_hash(self.row)
        for key in ("runtime_definition_hash", "adjudicated_definition_hash"):
            self.ev[key] = self.row[key]
        self.write_package()
        self.assertIs(SP.validate(self.policy, self.strats, self.root), self.policy)

    def test_bound_definition_side_gate_rechecked_at_promotion(self):
        """A stored REQUALIFIED row whose evidence lacks or fails the definition's short side cannot be promoted, even
        with a freshly hashed artifact and an untouched review."""
        originals = copy.deepcopy(self.artifact)
        mutations = {
            "both_sides missing, short missing": lambda e: (e.pop("both_sides"), e["sides"].pop("short")),
            "both_sides false": lambda e: e.update(both_sides=False),
            "long missing": lambda e: e["sides"].pop("long"),
            "short missing": lambda e: e["sides"].pop("short"),
            "short below minimum": lambda e: e["sides"].update(short=side_row(n=SA.GATE["minimum_side_trades"] - 1)),
            "short materially negative": lambda e: e["sides"].update(short=side_row(mean=-.3, upper=-.1)),
        }
        for label, mutate in mutations.items():
            with self.subTest(mutation=label):
                self.artifact = copy.deepcopy(originals)
                self.row = self.artifact["strategies"][0]
                mutate(self.row["evidence"])
                self.assertEqual(self.row["research_state"], "REQUALIFIED")       # the stored claim is stale
                self.write_package()
                self.assert_invalid(message="does not satisfy current gate")

    def test_promotion_rechecks_against_the_current_gate(self):
        with mock.patch.dict(SA.GATE, {"pbo": .05}):
            self.assert_invalid(message="does not satisfy current gate")
        self.assertIs(SP.validate(self.policy, self.strats, self.root), self.policy)


class RuntimeImplementationBinding(PromotionFixture):
    """Same-ID runtime code substitution: the metadata hash cannot see it, the implementation hash must."""
    MUTATIONS = ("sig_tsmom", "sig_trend_ema", "xs_scores", "_stop", "sim_trade", "trend_feats", "slip_of")

    def altered_copy(self, function):
        source = (ROOT / "quant.py").read_text(encoding="utf-8")
        self.assertIn("\ndef " + function + "(", source)
        # A trailing redefinition replaces the function the runtime calls; STRATS is untouched.
        altered = source + "\n\ndef " + function + "(*args, **kwargs):  # altered fixture copy\n    return None\n"
        folder = self.root / ("runtime_" + function.strip("_"))
        folder.mkdir()
        (folder / "quant.py").write_text(altered, encoding="utf-8")
        return folder

    def load_module(self, folder, name):
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, folder / "quant.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_manifest_and_current_hash(self):
        self.assertEqual(SP.RUNTIME_IMPLEMENTATION_FILES, ("quant.py",))
        expected = SP.digest({"quant.py": hashlib.sha256((ROOT / "quant.py").read_bytes()).hexdigest()})
        self.assertEqual(SP.runtime_implementation_hash(), expected)
        self.assertIs(SP.validate(self.policy, self.strats, self.root, ROOT), self.policy)

    def test_altered_runtime_code_same_metadata_fails_closed(self):
        import quant
        for function in self.MUTATIONS:
            with self.subTest(function=function):
                folder = self.altered_copy(function)
                altered = self.load_module(folder, "quant_altered_" + function.strip("_"))
                self.assertIsNot(getattr(altered, function), getattr(quant, function))
                self.assertIsNone(getattr(altered, function)())
                for sid in quant.STRATS:     # the metadata hash cannot see the substitution
                    self.assertEqual(SP.digest(altered.STRATS[sid]), SP.digest(quant.STRATS[sid]))
                self.assertNotEqual(SP.runtime_implementation_hash(folder), SP.runtime_implementation_hash(ROOT))
                self.assert_invalid(runtime_root=folder,
                                    message="runtime implementation differs between runtime, review and adjudication")

    def test_one_byte_change_and_missing_runtime_fail_closed(self):
        folder = self.root / "runtime_byte"
        folder.mkdir()
        (folder / "quant.py").write_bytes((ROOT / "quant.py").read_bytes() + b"\n")
        self.assert_invalid(runtime_root=folder)
        self.assert_invalid(runtime_root=self.root / "absent")

    def test_review_and_adjudication_must_agree_on_implementation(self):
        other = "b" * 64
        for targets in (("ev",), ("row",), ("ev", "row")):
            with self.subTest(targets=targets):
                self.setUp()
                for target in targets:
                    (self.ev if target == "ev" else self.row)["runtime_implementation_hash"] = other
                self.write_package()
                self.assert_invalid()

    def test_regenerated_review_for_new_implementation_can_promote(self):
        folder = self.altered_copy("sig_tsmom")
        new = SP.runtime_implementation_hash(folder)
        self.row["runtime_implementation_hash"] = self.ev["runtime_implementation_hash"] = new
        self.write_package()
        self.assertIs(SP.validate(self.policy, self.strats, self.root, folder), self.policy)
        self.assert_invalid()          # ... and that review does not authorize the repository's code


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
            self.assertNotEqual(SA.adjudicate(e, BOTH)["status"], "REQUALIFIED")

    def test_method_gate_values_drive_family_tests(self):
        x = np.random.default_rng(5).normal(size=(40, 3))
        names = ["A", "B", "C"]
        with mock.patch.object(AD.MT, "bootstrap_tests", return_value={"status": "AVAILABLE"}) as boot, \
                mock.patch.object(AD.MT, "pbo", return_value={"status": "AVAILABLE"}) as pbo:
            AD.family_tests(x, names, {"p": 1}, True)
            self.assertEqual(boot.call_args.args[2:], (SA.GATE["bootstrap_replications"], SA.GATE["block_days"]))
            self.assertEqual(pbo.call_args.args[2:], (SA.GATE["cscv_segments"], SA.GATE["cscv_min_segment_days"]))
            tightened = {"bootstrap_replications": 7, "block_days": 3, "cscv_segments": 4, "cscv_min_segment_days": 2}
            with mock.patch.dict(SA.GATE, tightened):
                AD.family_tests(x, names, {"p": 1}, True)
            self.assertEqual(boot.call_args.args[2:], (7, 3))
            self.assertEqual(pbo.call_args.args[2:], (4, 2))
            AD.family_tests(x, names, {"p": 1}, True, replications=11)
            self.assertEqual(boot.call_args.args[2], 11)
        stats, p = AD.family_tests(x, names, {"p": 1}, False)
        self.assertEqual((stats["status"], p["status"]), (MT.UNAVAILABLE, MT.UNAVAILABLE))

    def test_oos_fraction_gate_value_drives_out_of_sample_window(self):
        day = 86400
        rows = [{"decision_time": i * day, "net_R": 1.0, "direction": 1, "asset": "A" + str(i % 3),
                 "calendar_month": "2026-01", "adverse_cost_R": 0.0} for i in range(90)]
        base = AD.robustness(rows, 0, 90 * day)
        self.assertEqual(base["oos_start"], 90 * day * (1 - SA.GATE["oos_fraction"]))
        with mock.patch.dict(SA.GATE, {"oos_fraction": .5}):
            half = AD.robustness(rows, 0, 90 * day)
        self.assertEqual(half["oos_start"], 45 * day)
        self.assertNotEqual(half["oos"]["n"], base["oos"]["n"])

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

NODE = shutil.which("node")
EMPTY_PORTFOLIO = {"label": "LEGACY_DIAGNOSTIC / NOT STRATEGY AUTHORITY", "status": "NO_ENABLED_STRATEGIES",
                   "strategies": [], "all_trades": {"n": 0}, "taken": {"n": 0}, "max_open": None,
                   "max_per_strategy": None, "daily_r_mean": None, "daily_r_sd": None, "sharpe": None, "kelly": None,
                   "accounts": [], "planner": {}, "start": None, "planner_days": None}
LEGACY_LABEL = ("Legacy holdover", "warn", "Unqualified legacy diagnostic; point-in-time evidence, full matched controls "
                "and multiple-testing correction have not established strategy authority.",
                "Legacy holdover strategies; historical results are unqualified diagnostics")


class QuantDisplay(unittest.TestCase):
    """Dashboard and quant.html labels derive from the serialized policy states; an empty portfolio is tolerated."""
    STATES = {
        "legacy": {"TSMOM": "LEGACY_HOLDOVER", "TREND_EMA": "LEGACY_HOLDOVER", "XSMOM": "LEGACY_HOLDOVER"},
        "requalified": {"TSMOM": "ACTIVE_REQUALIFIED", "XSMOM": "ACTIVE_REQUALIFIED"},
        "mixed": {"TSMOM": "ACTIVE_REQUALIFIED", "TREND_EMA": "LEGACY_HOLDOVER", "XSMOM": "LEGACY_HOLDOVER"},
        "none": {},
    }

    def quant_json(self, states):
        import quant
        from tests import test_dashboard as TD
        q = TD.quant_json()
        q["strategies"] = {sid: {**quant.STRATS[sid], "open": 0, "blocked_open": 0, "deployment_state": st,
                                 "research_state": "REQUALIFIED" if st == "ACTIVE_REQUALIFIED" else "INSUFFICIENT_EVIDENCE"}
                           for sid, st in states.items()}
        q["open"] = [o for o in q["open"] if o["s"] in states]
        q["strategy_authority"] = {"runtime_policy_schema": SP.VERSION, "runtime_policy_hash": "x" * 64,
                                   "runtime_order": list(states)}
        return q

    def build(self, states, portfolio=None):
        import dashboard as D
        from tests import test_dashboard as TD
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            qr = TD.quant_research()
            if portfolio is not None:
                qr["portfolio"] = portfolio
            for name, obj in (("picks.json", TD.picks_json()), ("picks_research.json", TD.picks_research()),
                              ("quant.json", self.quant_json(states)), ("quant_research.json", qr),
                              ("latest.json", TD.radar_json())):
                (data / name).write_text(json.dumps(obj))
            out = D.build(str(data), research_dir=tmp)
        quant_row = next(r for r in out["scorecard"] if r["name"] == "Quant desk")
        card = next(v for v in out["versions"] if v["id"] == "quant")
        return quant_row, card

    def test_dashboard_labels_follow_deployment_states(self):
        for portfolio in (None, EMPTY_PORTFOLIO):
            with self.subTest(portfolio=bool(portfolio)):
                row, card = self.build(self.STATES["legacy"], portfolio)
                self.assertEqual((row["verdict"], row["tone"], row["why"], card["what"]), LEGACY_LABEL)
                self.assertEqual(card["accuracy"][0], row)
                row, card = self.build(self.STATES["requalified"], portfolio)
                self.assertEqual((row["verdict"], row["tone"]), ("Requalified", "good"))
                self.assertIn("All 2 enabled strategies", row["why"])
                row, card = self.build(self.STATES["mixed"], portfolio)
                self.assertEqual((row["verdict"], row["tone"]), ("Mixed authority", "warn"))
                self.assertIn("1 requalified and 2 legacy holdover strategies", row["why"])
                self.assertIn("not requalified", row["why"])
                self.assertNotIn("Requalified", card["what"].split(":")[0])
                row, card = self.build(self.STATES["none"], portfolio)
                self.assertEqual((row["verdict"], row["tone"], card["what"]),
                                 ("Disabled", "muted", "No deployment-enabled strategies"))
                self.assertEqual(card["items"], [])
                if portfolio:
                    self.assertEqual(row["tested"]["n"], 0)

    def test_dashboard_missing_or_unknown_states_are_never_requalified(self):
        import dashboard as D
        from tests import test_dashboard as TD
        for q in (None, {}, TD.quant_json(), {"strategies": {"TSMOM": {}}}, {"strategies": {"TSMOM": None}},
                  {"strategies": {"TSMOM": {"deployment_state": "PAPER_ONLY"}}}):
            with self.subTest(q=q):
                auth = D.quant_authority(q)
                self.assertEqual((auth["verdict"], auth["tone"], auth["why"], auth["what"]), LEGACY_LABEL)

    def run_page(self, states, research):
        with tempfile.TemporaryDirectory() as tmp:
            q, r = Path(tmp) / "q.json", Path(tmp) / "r.json"
            q.write_text(json.dumps(self.quant_json(states)))
            r.write_text(json.dumps(research))
            out = subprocess.run([NODE, str(ROOT / "tests/quant_html_harness.js"), str(ROOT / "quant.html"), str(q),
                                  str(r)], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        page = json.loads(out.stdout)
        self.assertEqual(page["errors"], [])
        return page

    @unittest.skipUnless(NODE, "node is not installed")
    def test_quant_html_labels_follow_deployment_states_and_tolerate_empty_portfolio(self):
        research = json.loads((ROOT / "quant_research.json").read_text(encoding="utf-8"))
        empty = {**research, "portfolio": EMPTY_PORTFOLIO}
        for name, R in (("research", research), ("empty", empty)):
            with self.subTest(portfolio=name):
                legacy = self.run_page(self.STATES["legacy"], R)
                self.assertTrue(legacy["lede"].startswith("24 historical strategy diagnostics; 3 strategies remain "
                                                          "deployed as legacy holdovers. None is requalified"))
                self.assertEqual(legacy["stratTitle"], "Legacy holdover strategies")
                self.assertEqual(legacy["strats"].count("Legacy holdover"), 3)
                self.assertNotIn("Requalified", legacy["strats"] + legacy["all"])
                req = self.run_page(self.STATES["requalified"], R)
                self.assertEqual(req["stratTitle"], "Requalified strategies")
                self.assertEqual(req["strats"].count("Requalified"), 2)
                self.assertNotIn("Legacy holdover", req["strats"])
                mixed = self.run_page(self.STATES["mixed"], R)
                self.assertEqual(mixed["stratTitle"], "Mixed authority strategies")
                self.assertIn("1 requalified", mixed["lede"])
                self.assertIn("2 legacy holdovers that remain unqualified", mixed["lede"])
                self.assertIn("not requalified", mixed["lede"])
                self.assertEqual((mixed["strats"].count("Requalified"), mixed["strats"].count("Legacy holdover")),
                                 (1, 2))
                none = self.run_page(self.STATES["none"], R)
                self.assertEqual(none["stratTitle"], "No deployment-enabled strategies")
                self.assertIn("no strategy is deployment-enabled", none["lede"])
                self.assertNotIn("Requalified", none["strats"] + none["all"] + none["lede"])
                if name == "empty":
                    self.assertIn("Backtest, 3 years–", none["kpis"])
                    self.assertIn("Return / swings (Sharpe)–", none["kpis"])
                else:
                    self.assertNotIn("Backtest, 3 years–", legacy["kpis"])


def legacy_portfolio_reference(finals_3y, ids, s4, end4):
    """The pre-correction qexport portfolio block, verbatim (base b505b9e), for the unchanged-numbers proof."""
    import pandas as pd
    import qport
    import qstats
    from qexport import slim
    T = pd.concat(finals_3y, ignore_index=True)
    T = T[T.reason != "end"]
    comb = qstats.stats(T, s4, end4)
    accounts = []
    for f in (0.0025, 0.005, 0.0075, 0.01, 0.02):
        ev, sm, took = qport.simulate(T, start=500, risk=f, max_open=60, max_per_strategy=20)
        wk = []
        if len(ev):
            e = ev.copy()
            e["w"] = ((e.t - s4) // (7 * 86400)).astype(int)
            last = e.groupby("w").equity.last()
            cur = 500.0
            for wi in range(int(math.ceil((end4 - s4) / (7 * 86400)))):
                cur = float(last.get(wi, cur))
                wk.append(round(cur, 2))
        accounts.append({"risk": f, "final": round(sm["final"], 2), "multiple": round(sm["multiple"], 3),
                         "maxdd": round(sm["maxdd"], 3), "taken": sm["taken"], "curve": wk})
    ev, sm, took = qport.simulate(T, start=500, risk=0.005, max_open=60, max_per_strategy=20)
    TK = T[took]
    daily = qport.daily_r(TK, s4, end4)
    risks = (0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.10)
    planners = {}
    for hc in (0.0, 0.5):
        gp = qport.growth_planner(daily, start=500, days=730, risks=risks, paths=6000, haircut=hc,
                                  targets=(1_000, 10_000, 100_000, 1_000_000))
        planners[f"{hc:.1f}"] = [{k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else v)
                                  for k, v in row.items()} for row in gp.to_dict("records")]
    sharpe = float(daily.mean() / daily.std() * math.sqrt(365)) if daily.std() > 0 else None
    return {
        "label": "LEGACY_DIAGNOSTIC / NOT STRATEGY AUTHORITY",
        "strategies": list(ids), "all_trades": slim(comb), "taken": slim(qstats.stats(TK, s4, end4)),
        "max_open": 60, "max_per_strategy": 20,
        "daily_r_mean": round(float(daily.mean()), 4), "daily_r_sd": round(float(daily.std()), 4),
        "sharpe": round(sharpe, 3) if sharpe else None, "kelly": round(qport.kelly(daily), 4),
        "accounts": accounts, "planner": planners, "start": 500, "planner_days": 730,
    }


@unittest.skipIf(np is None, "numpy research dependencies required")
class EmptyPortfolio(unittest.TestCase):
    """qexport's combined portfolio for 0, 1, mixed and all deployment-enabled strategies."""
    S4, END4 = 1_700_006_400, 1_700_006_400 + 200 * 86400

    def frame(self, sid, seed, n=120):
        import pandas as pd
        rng = np.random.default_rng(seed)
        t_entry = np.sort(rng.integers(self.S4, self.END4 - 20 * 86400, n)) // 14400 * 14400
        hold = rng.integers(1, 12, n) * 14400
        r = rng.normal(.05, 1.2, n)
        d = rng.choice([-1, 1], n)
        reasons = ["stop"] * (n - 2) + ["end", "time"]
        return pd.DataFrame({"strategy": sid, "t_entry": t_entry, "t_exit": t_entry + hold,
                             "coin": [f"C{k % 7}" for k in range(n)], "d": d, "stop_pct": rng.uniform(.02, .08, n),
                             "r": r, "gross": r + .02, "cost": .01, "fund": .01, "mfe": 1.0, "mae": -1.0,
                             "hold": hold / 3600, "reason": reasons, "tw_r": r * .5, "tw_gross": r * .5 + .01})

    def frames(self, ids):
        return [self.frame(sid, k + 1) for k, sid in enumerate(ids)]

    def test_current_three_strategy_policy_numbers_unchanged(self):
        import qexport
        ids = qexport.legacy_portfolio_ids()
        self.assertEqual(ids, ["TSMOM", "TREND_EMA", "XSMOM"])
        finals = self.frames(ids)
        new = qexport.portfolio(finals, ids, self.S4, self.END4)
        old = legacy_portfolio_reference(self.frames(ids), ids, self.S4, self.END4)
        self.assertNotIn("status", new)
        self.assertEqual(json.dumps(new, sort_keys=True), json.dumps(old, sort_keys=True))
        self.assertGreater(new["all_trades"]["n"], 0)

    def test_zero_enabled_is_a_deterministic_diagnostic_without_simulation(self):
        import qexport
        with mock.patch.object(qexport.qport, "simulate", side_effect=AssertionError("simulated")), \
                mock.patch.object(qexport.qport, "growth_planner", side_effect=AssertionError("planned")), \
                mock.patch.object(qexport.pd, "concat", side_effect=AssertionError("concatenated")):
            out = qexport.portfolio([], [], self.S4, self.END4)
        self.assertEqual(out["status"], "NO_ENABLED_STRATEGIES")
        self.assertEqual(out["strategies"], [])
        self.assertEqual(out["all_trades"], {"n": 0})
        self.assertEqual(out["taken"], {"n": 0})
        self.assertEqual((out["accounts"], out["planner"]), ([], {}))
        for key in ("sharpe", "kelly", "daily_r_mean", "daily_r_sd", "start", "planner_days", "max_open"):
            self.assertIsNone(out[key], key)
        self.assertEqual(json.dumps(out, sort_keys=True),
                         json.dumps(qexport.portfolio([], [], self.S4, self.END4), sort_keys=True))
        self.assertEqual(out, qexport.empty_portfolio("NO_ENABLED_STRATEGIES", []))
        self.assertEqual(out, EMPTY_PORTFOLIO)      # the shape the dashboard and quant.html tests render

    def test_all_disabled_policy_reaches_the_diagnostic_through_the_runtime_order(self):
        import qexport
        import quant
        with mock.patch.object(quant, "RUNTIME_ORDER", ()):
            ids = qexport.legacy_portfolio_ids()
        self.assertEqual(ids, [])
        out = qexport.portfolio([], ids, self.S4, self.END4)
        self.assertEqual(out["status"], "NO_ENABLED_STRATEGIES")

    def test_one_and_mixed_enabled(self):
        import qexport
        for ids in (["TSMOM"], ["XSMOM"], ["TSMOM", "XSMOM"], ["TREND_EMA", "XSMOM"]):
            with self.subTest(ids=ids):
                out = qexport.portfolio(self.frames(ids), ids, self.S4, self.END4)
                self.assertEqual(out["strategies"], ids)
                self.assertNotIn("status", out)
                self.assertEqual(out["all_trades"]["n"], 119 * len(ids))
                self.assertEqual(len(out["accounts"]), 5)
                self.assertEqual(set(out["planner"]), {"0.0", "0.5"})
                self.assertEqual(json.dumps(out, sort_keys=True), json.dumps(
                    legacy_portfolio_reference(self.frames(ids), ids, self.S4, self.END4), sort_keys=True))

    def test_enabled_without_closed_portfolio_trades(self):
        import qexport
        only_open = self.frame("TSMOM", 9, n=3)
        only_open["reason"] = "end"
        for finals in ([], [only_open]):
            out = qexport.portfolio(finals, ["TSMOM"], self.S4, self.END4)
            self.assertEqual(out["status"], "NO_PORTFOLIO_TRADES")
            self.assertEqual(out["strategies"], ["TSMOM"])
            self.assertEqual(out["all_trades"], {"n": 0})


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
            import quant
            for row in doc["strategies"]:
                sid = row["strategy_id"]
                expected = SP.digest(quant.STRATS[sid]) if sid in quant.STRATS else None
                self.assertEqual(row["runtime_definition_hash"], expected)
                self.assertEqual(row["adjudicated_definition_hash"], SP.adjudicated_definition_hash(row))
                self.assertEqual(row["runtime_implementation_hash"],
                                 SP.runtime_implementation_hash() if sid in quant.STRATS else None)
                self.assertIs(row["evidence"]["both_sides"], SA.required_sides(row) == ("long", "short"))
                self.assertEqual(SA.adjudicate(row["evidence"], row)["research_state"], row["research_state"])
                for key in ("runtime_definition_hash", "adjudicated_definition_hash", "runtime_implementation_hash"):
                    self.assertEqual(row["trace"][key], row[key])
            self.assertEqual(doc["runtime_implementation_files"], ["quant.py"])
            self.assertEqual(doc["runtime_implementation_hash"], SP.runtime_implementation_hash())
            self.assertEqual(doc["gate"], SA.GATE)
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
