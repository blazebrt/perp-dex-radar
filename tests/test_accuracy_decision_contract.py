"""A06: public decision authority needs the complete, current production input contract."""
import copy
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import test_v8_phase11 as P  # noqa: E402
from v8 import decision as DE  # noqa: E402
from v8 import portfolio_risk as PR  # noqa: E402

REQUIRED_TIMES = ("discovery", "quant", "portfolio")


class DecisionInputContract(unittest.TestCase):
    def snapshot(self):
        return P.snapshot([P.rec("HI")], {"HI": [P.sig("REQ")]})

    def refused(self, snapshot, field):
        before = copy.deepcopy(snapshot)
        for name, evaluate in (("build", lambda: DE.build(snapshot)),
                               ("evaluate_asset", lambda: DE.evaluate_asset(snapshot, "HI"))):
            with self.subTest(api=name):
                with self.assertRaisesRegex(ValueError, "DECISION_INPUT_INVALID: " + field):
                    evaluate()
        self.assertEqual(snapshot, before)

    def test_complete_contract_can_trade_and_is_not_mutated(self):
        s = self.snapshot()
        before = copy.deepcopy(s)
        doc = DE.build(s)
        one = DE.evaluate_asset(s, "HI")
        self.assertEqual(doc["market_summary"]["opportunity_states"]["TRADE"], 1)
        self.assertEqual(one["opportunities"][0]["state"], DE.TRADE)
        self.assertEqual(s, before)

    def test_as_of_is_required_nonnegative_integer_not_bool(self):
        s = self.snapshot()
        del s["as_of"]
        self.refused(s, "as_of")
        for value in (None, True, False, "1780099200", 1.5, [], {}, math.inf, -1):
            with self.subTest(value=value):
                s = self.snapshot()
                s["as_of"] = value
                self.refused(s, "as_of")

    def test_missing_inputs_map_refuses_both_boundaries(self):
        s = self.snapshot()
        del s["inputs_as_of"]
        self.refused(s, "inputs_as_of")

    def test_inputs_map_must_be_present_dictionary(self):
        for value in (None, [], "current", True, 1):
            with self.subTest(value=value):
                s = self.snapshot()
                s["inputs_as_of"] = value
                self.refused(s, "inputs_as_of")
        s = self.snapshot()
        s["inputs_as_of"] = {}
        self.refused(s, "inputs_as_of.discovery")

    def test_each_required_input_timestamp_is_required(self):
        for name in REQUIRED_TIMES:
            with self.subTest(input=name):
                s = self.snapshot()
                del s["inputs_as_of"][name]
                self.refused(s, "inputs_as_of." + name)

    def test_each_required_input_timestamp_requires_integer_type(self):
        for name in REQUIRED_TIMES:
            for value in (None, True, False, str(P.AS_OF), float(P.AS_OF), 1.25, [], {}, math.inf, -1):
                with self.subTest(input=name, value=value):
                    s = self.snapshot()
                    s["inputs_as_of"][name] = value
                    self.refused(s, "inputs_as_of." + name)

    def test_each_future_required_input_refuses_document(self):
        for name in REQUIRED_TIMES:
            with self.subTest(input=name):
                s = self.snapshot()
                s["inputs_as_of"][name] = P.AS_OF + 1
                self.refused(s, "inputs_as_of freshness: " + name)

    def test_each_stale_required_input_refuses_document(self):
        age = DE.load_policy()["freshness"]["max_input_age_s"]["value"]
        for name in REQUIRED_TIMES:
            with self.subTest(input=name):
                s = self.snapshot()
                s["inputs_as_of"][name] = P.AS_OF - age - 1
                self.refused(s, "inputs_as_of freshness: " + name)

    def test_freshness_boundary_preserves_reviewed_policy(self):
        age = DE.load_policy()["freshness"]["max_input_age_s"]["value"]
        for name in REQUIRED_TIMES:
            with self.subTest(input=name):
                s = self.snapshot()
                s["inputs_as_of"][name] = P.AS_OF - age
                self.assertEqual(DE.build(s)["candidates"][0]["state"], DE.TRADE)
                self.assertEqual(DE.evaluate_asset(s, "HI")["opportunities"][0]["state"], DE.TRADE)

    def test_missing_discovery_provenance_refuses_document(self):
        s = self.snapshot()
        del s["discovery"]["provenance"]
        self.refused(s, "discovery.provenance")
        for value in (None, [], "qualified", True, 1, {}):
            with self.subTest(value=value):
                s = self.snapshot()
                s["discovery"]["provenance"] = value
                self.refused(s, "discovery.provenance")

    def test_each_required_provenance_field_is_required(self):
        for name in ("schema", "fallback_universe", "available_venue_discovery_qualified", "generated_at",
                     "identity_version", "coverage_state", "venues_failed_names"):
            with self.subTest(field=name):
                s = self.snapshot()
                del s["discovery"]["provenance"][name]
                self.refused(s, "discovery.provenance." + name)

    def test_discovery_flags_must_be_explicit_booleans(self):
        for name in ("fallback_universe", "available_venue_discovery_qualified"):
            for value in (None, 0, 1, "true", "false", [], {}):
                with self.subTest(field=name, value=value):
                    s = self.snapshot()
                    s["discovery"]["provenance"][name] = value
                    self.refused(s, "discovery.provenance." + name)

    def test_provenance_shape_and_time_are_required(self):
        age = DE.load_policy()["freshness"]["max_input_age_s"]["value"]
        cases = {"schema": (None, True, "v8.discovery/0", "v8.discovery/2", {}, []),
                 "generated_at": (None, True, float(P.AS_OF), "now", -1, P.AS_OF + 1, P.AS_OF - age - 1),
                 "identity_version": (None, "v8.identity/3", True),
                 "coverage_state": (None, "UNKNOWN", True, []),
                 "venues_failed_names": (None, "hyperliquid", {}, [None], [1], [""])}
        for name, values in cases.items():
            for value in values:
                with self.subTest(field=name, value=value):
                    s = self.snapshot()
                    s["discovery"]["provenance"][name] = value
                    self.refused(s, "discovery.provenance." + name)

    def test_explicitly_unqualified_discovery_keeps_existing_watch_policy(self):
        for changes in ({"fallback_universe": True}, {"available_venue_discovery_qualified": False}):
            with self.subTest(changes=changes):
                s = self.snapshot()
                s["discovery"]["provenance"].update(changes)
                for c in (DE.build(s)["candidates"][0], DE.evaluate_asset(s, "HI")["opportunities"][0]):
                    self.assertEqual(c["state"], DE.WATCH)
                    self.assertIn("DISCOVERY_DEGRADED", c["missing_authorities"])

    def test_empty_trade_dexes_keeps_documented_all_venues_behavior(self):
        s = self.snapshot()
        s["trade_dexes"] = []
        self.assertEqual(DE.build(s)["candidates"][0]["state"], DE.TRADE)
        self.assertEqual(DE.evaluate_asset(s, "HI")["opportunities"][0]["state"], DE.TRADE)

    def test_freshness_never_defaults_missing_required_inputs_to_empty(self):
        policy = DE.load_policy()
        for times in (None, {}, {"discovery": P.AS_OF}):
            with self.subTest(times=times):
                s = self.snapshot()
                s["inputs_as_of"] = times
                self.assertTrue(DE._freshness(s, policy))

    def test_additive_display_sizing_comes_from_phase10_result(self):
        s = self.snapshot()
        c = DE.build(s)["candidates"][0]
        proposal = c["proposal"]
        evaluated = PR.what_if(s["portfolio"], {"action": "ADD", "position": {
            "id": proposal["id"], "asset": "HI", "strategy": "REQ", "direction": 1,
            "mark": proposal["mark"], "stop": proposal["stop"], "risk_fraction": proposal["risk_fraction"],
            "entered": False, "actionability": PR.PROPOSED,
            "liquidity": {"state": "KNOWN", "volume": 5e6},
            "funding": {"state": c["funding"]["state"], "rate_8h": c["funding"]["rate_8h"]},
            "hold_hours_remaining": P.STRATS["REQ"]["hold_h"]}})["after_result"]
        row = next(p for p in evaluated["positions"] if p["id"] == proposal["id"])
        self.assertEqual(proposal["equity"], evaluated["equity"])
        self.assertEqual(proposal["quantity"], row["quantity"])
        self.assertEqual(proposal["notional"], row["notional_usd"])
        self.assertEqual(proposal["stop_risk_usd"], row["account_risk"] * evaluated["equity"])
        self.assertEqual(proposal["risk_fraction"], .005)
        self.assertAlmostEqual(proposal["stop_risk_usd"], 2.5)


if __name__ == "__main__":
    unittest.main()
