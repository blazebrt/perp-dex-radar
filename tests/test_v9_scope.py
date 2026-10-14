"""v9 phase B scope proof against main at the start of the phase: the probation tier changes only what it declares.

No runtime engine, signal, parameter, universe, identity, liquidity, limit or research method changes. The changes:

    v8/quant_strategy_policy.json   XSMOM: ACTIVE_PROBATION / PROBATION with its bound probation record (schema /2)
    v8/strategy_policy.py           the ACTIVE_PROBATION state, its fail-closed validation and probation_terms()
    v8/decision_policy.json         version 2: probation states and the governed gating book (v1 values unchanged)
    v8/decision.py                  the probation tier, the governed book, entered signals, tier counts
    v8/portfolio_risk.py            each paper position records its entry time (entered_at)
    v8/audit_quant.py               ENTERED signals and the forward-test record in the decision inputs
    v8/snapshot.py                  probation terms and forward tests passed to the decision engine
"""
import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = "fe68203d6f5b76eb68250192ffb638cd9079eeb2"      # main after PR #24, where v9 phase B starts
UNCHANGED = (
    "quant.py", "scanner.py", "picks.py", "smart.py",
    "v8/strategy_authority.py", "v8/portfolio_risk_policy.json", "v8/evidence.py", "v8/identity.py",
    "v8/liquidity.py", "v8/discovery.py", "v8/registry.py", "v8/history.py", "v8/pit.py", "v8/shadow_ledger.py",
    "tools/research/qstrat.py", "tools/research/qsim.py", "tools/research/qdata.py", "tools/research/qind.py",
    "tools/research/qexport.py", "tools/research/qgrid.py", "tools/research/qrun.py", "tools/research/qrun3y.py",
    "tools/research/strategy_census.py", "tools/research/strategy_adjudication.py",
    "tools/research/multiple_testing.py", "tools/research/matched_controls.py",
    "tools/research/production_publication.py", "research.html", ".github/workflows/research.yml",
    ".github/workflows/scan.yml",
)


def base(name):
    return subprocess.check_output(["git", "-c", "safe.directory=*", "-C", str(ROOT), "show", f"{BASE}:{name}"])


def head(name):
    return (ROOT / name).read_bytes()


def dump(node):
    return ast.dump(node, include_attributes=False)


def functions(source):
    return {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}


def assignments(source):
    return {t.id: n for n in ast.parse(source).body if isinstance(n, ast.Assign) for t in n.targets
            if isinstance(t, ast.Name)}


def changed_functions(name):
    old, new = functions(base(name).decode()), functions(head(name).decode())
    return ({k for k in old if k in new and dump(old[k]) != dump(new[k])}, set(new) - set(old), set(old) - set(new),
            old, new)


class V9Scope(unittest.TestCase):
    def test_runtime_engines_methods_limits_and_research_publication_unchanged(self):
        for name in UNCHANGED:
            with self.subTest(file=name):
                self.assertEqual(head(name), base(name))

    def test_strategy_policy_rows(self):
        old, new = json.loads(base("v8/quant_strategy_policy.json")), json.loads(head("v8/quant_strategy_policy.json"))
        self.assertEqual((old["schema"], new["schema"]), ("v8.quant-strategy-policy/1", "v8.quant-strategy-policy/2"))
        self.assertEqual(old["runtime_order"], new["runtime_order"])
        o = {r["strategy_id"]: r for r in old["strategies"]}
        n = {r["strategy_id"]: r for r in new["strategies"]}
        self.assertEqual(set(o), set(n))
        for sid in ("TSMOM", "TREND_EMA"):
            self.assertEqual(o[sid], n[sid])
        x = copy.deepcopy(n["XSMOM"])
        prob = x.pop("probation")
        self.assertEqual(x, {"strategy_id": "XSMOM", "deployment_state": "ACTIVE_PROBATION", "research_state": "PROBATION"})
        self.assertEqual((prob["sides"], prob["risk_multiplier"]), (["long"], 0.5))
        self.assertEqual(prob["evidence"]["sha256"], hashlib.sha256(head(prob["evidence"]["path"])).hexdigest())
        ft = prob["forward_tests"]["long"]
        self.assertEqual(ft["sha256"], hashlib.sha256(head(ft["path"])).hexdigest())
        reg = json.loads(head(ft["path"]))
        self.assertEqual((reg["kind"], reg["experiment_id"], reg["evaluation_start"]),
                         ("REGISTRATION", ft["experiment_id"], ft["effective_from"]))
        self.assertLessEqual(reg["registered_at"], ft["effective_from"])

    def test_strategy_policy_code_only_adds_the_probation_tier(self):
        changed, added, removed, old, new = changed_functions("v8/strategy_policy.py")
        self.assertEqual((changed, added, removed), ({"validate"}, {"_bound_file", "_validate_probation",
                                                                     "probation_terms"}, set()))
        # validate(): identical once the one added statement (the ACTIVE_PROBATION branch) is removed
        v = copy.deepcopy(new["validate"])
        loop = next(s for s in v.body if isinstance(s, ast.For))
        loop.body = [s for s in loop.body if not (isinstance(s, ast.If) and isinstance(s.test, ast.Compare)
                                                  and isinstance(s.test.comparators[0], ast.Constant)
                                                  and s.test.comparators[0].value == "ACTIVE_PROBATION")]
        self.assertEqual(dump(v), dump(old["validate"]))
        oa, na = assignments(base("v8/strategy_policy.py").decode()), assignments(head("v8/strategy_policy.py").decode())
        self.assertEqual({k for k in oa if dump(oa[k]) != dump(na[k])}, {"VERSION", "DEPLOYMENT", "ENABLED"})
        self.assertEqual(set(na) - set(oa), {"PROBATION_EVIDENCE_SCHEMA", "MAX_PROBATION_RISK_MULTIPLIER",
                                             "PROBATION_KEYS", "FORWARD_TEST_KEYS", "LEDGER_DIR"})
        from v8 import strategy_policy as SP
        self.assertEqual(SP.DEPLOYMENT - {"ACTIVE_PROBATION"}, {"LEGACY_HOLDOVER", "ACTIVE_REQUALIFIED", "PAPER_ONLY",
                                                               "DISABLED"})
        self.assertEqual(SP.ENABLED, {"LEGACY_HOLDOVER", "ACTIVE_REQUALIFIED", "ACTIVE_PROBATION"})
        self.assertEqual(SP.MAX_PROBATION_RISK_MULTIPLIER, 0.5)

    def test_decision_policy_only_adds_version_2_keys(self):
        old, new = json.loads(base("v8/decision_policy.json")), json.loads(head("v8/decision_policy.json"))
        self.assertEqual((old["review_status"], new["review_status"]),
                         ("POLICY_REVIEWED_INITIAL_V1", "POLICY_REVIEWED_V2_PROBATION"))
        added = {("strategy_authority", "probation_deployment_states"),
                 ("strategy_authority", "probation_research_states"), ("portfolio", "gating_book")}
        for section in old:
            if section in ("schema", "review_status", "statement"):
                continue
            for key, entry in new[section].items():
                if (section, key) in added:
                    continue
                with self.subTest(entry=f"{section}.{key}"):
                    self.assertEqual(entry["value"], old[section][key]["value"])
                    self.assertEqual(entry["basis"], old[section][key]["basis"])
            self.assertEqual(set(new[section]) - set(old[section]), {k for s, k in added if s == section})

    def test_decision_engine_changes_are_declared(self):
        changed, added, removed, _, _ = changed_functions("v8/decision.py")
        self.assertEqual(changed, {"validate_policy", "_valid_until", "_directional", "_emerging", "_context", "build"})
        self.assertEqual(added, {"_side_name", "_authorized_side", "_governed_book", "_forward_test"})
        self.assertEqual(removed, set())

    def test_portfolio_input_only_records_the_entry_time(self):
        changed, added, removed, old, new = changed_functions("v8/portfolio_risk.py")
        self.assertEqual((changed, added, removed), ({"live_open_position"}, set(), set()))
        fn = copy.deepcopy(new["live_open_position"])
        ret = next(s for s in fn.body if isinstance(s, ast.Return))
        keep = [(k, v) for k, v in zip(ret.value.keys, ret.value.values)
                if not (isinstance(k, ast.Constant) and k.value == "entered_at")]
        ret.value.keys, ret.value.values = [k for k, _ in keep], [v for _, v in keep]
        self.assertEqual(dump(fn), dump(old["live_open_position"]))

    def test_audit_and_snapshot_changes_are_declared(self):
        changed, added, removed, _, _ = changed_functions("v8/audit_quant.py")
        self.assertEqual((changed, added, removed), ({"signal_states", "decision_inputs_part"}, {"forward_tests"}, set()))
        changed, added, removed, _, _ = changed_functions("v8/snapshot.py")
        self.assertEqual((changed, added, removed), ({"_decision"}, set(), set()))


if __name__ == "__main__":
    unittest.main()
