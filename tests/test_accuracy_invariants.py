"""Independent scope proof against PR24's starting head: accounting corrections cannot tune strategies or policy."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
START = "5f1b0b2533cf9f6f4094023044650e41816077fb"
NODE = shutil.which("node")


def original(name):
    return subprocess.check_output(["git", "-c", "safe.directory=*", "-C", str(ROOT), "show", START + ":" + name])


def dump(node):
    return ast.dump(node, include_attributes=False)


def functions(source):
    return {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}


def assignments(source):
    return {target.id: node for node in ast.parse(source).body if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)}


def normalize_run(node):
    """Remove only the declared closed-execution evidence additions and the nested replay implementation."""
    node = copy.deepcopy(node)
    body = []
    for statement in node.body:
        if (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Name)
                and statement.value.func.id == "mark_legacy_execution"):
            continue
        if isinstance(statement, ast.FunctionDef) and statement.name == "replay":
            body.append(ast.Pass())
            continue
        if (isinstance(statement, ast.Assign)
                and any(dump(t) == dump(ast.parse('J["closed"] = []').body[0].targets[0]) for t in statement.targets)
                and isinstance(statement.value, ast.Subscript)
                and dump(statement.value.slice) == dump(ast.parse('rows[-CFG["keep_closed"]:]').body[0].value.slice)):
            # Removing the old destructive retention cap is an authorized record-preservation change only.
            statement.value = statement.value.value
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ("qual", "unq")
                                                    for t in statement.targets):
            for call in ast.walk(statement):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "qualified_trade":
                    call.func = ast.Attribute(value=ast.Name(id="EV", ctx=ast.Load()), attr="qualified", ctx=ast.Load())
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "out"
                                                    for t in statement.targets):
            for child in ast.walk(statement):
                if isinstance(child, ast.Constant) and child.value == "ENTRY_IDENTITY_OR_EXECUTION_UNQUALIFIED":
                    child.value = "ENTRY_EXECUTION_REASON_PLACEHOLDER"
                if isinstance(child, ast.Dict):
                    for i, (key, value) in enumerate(zip(child.keys, child.values)):
                        if isinstance(key, ast.Constant) and key.value == "legacy_unqualified":
                            for call in ast.walk(value):
                                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                                        and call.func.id == "live_stats"):
                                    call.keywords = [k for k in call.keywords if not
                                                     (k.arg == "include_unqualified" and
                                                      isinstance(k.value, ast.Constant) and k.value.value is True)]
                        if (isinstance(key, ast.Constant) and key.value == "reason"
                                and isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
                                and value.value.id == "EV" and value.attr == "LEGACY_NO_IDENTITY_PROOF"):
                            child.values[i] = ast.Constant(value="ENTRY_EXECUTION_REASON_PLACEHOLDER")
        body.append(statement)
    node.body = body
    return node


def normalize_directional(node):
    node = copy.deepcopy(node)
    body = []
    for statement in node.body:
        targets = statement.targets if isinstance(statement, ast.Assign) else []
        if any(isinstance(t, ast.Name) and t.id == "evaluated_equity" for t in targets):
            continue
        if (any(isinstance(t, ast.Name) and t.id == "pinp" for t in targets)
                and isinstance(statement.value, ast.Dict)):
            keep = [(key, value) for key, value in zip(statement.value.keys, statement.value.values)
                    if not (isinstance(key, ast.Constant) and key.value in
                            ("equity", "quantity", "notional", "stop_risk_usd"))]
            statement.value.keys = [key for key, _ in keep]
            statement.value.values = [value for _, value in keep]
        body.append(statement)
    node.body = body
    return node


class AccuracyScopeInvariants(unittest.TestCase):
    @unittest.skipUnless(NODE, "node unavailable")
    def test_analyzer_ai_export_keeps_exact_canonical_proposal(self):
        from tests import test_v8_phase11 as P
        from v8 import decision as DE
        doc = DE.build(P.snapshot([P.rec("HI")], {"HI": [P.sig()]}))
        proposal = next(c["proposal"] for c in doc["candidates"] if c["state"] == "TRADE")
        script = r'''
const fs=require("fs"),vm=require("vm"),TA=require(process.argv[1]+"/analyze.js");
const doc=JSON.parse(fs.readFileSync(0,"utf8"));
const call=TA.decide({coin:"HI",price:151,now:doc.as_of+60,src:{decision:doc}});
const html=fs.readFileSync(process.argv[1]+"/analyze.html","utf8");
const code=html.slice(html.indexOf("function aiPayload()"),html.indexOf("\nconst AI_SYSTEM"));
const read={price:151,chgDay:.01,side:null,bias:0,parts:[],zones:{support:[],resistance:[]},text:"context"};
const forbidden=()=>{throw new Error("governed export invented a legacy exit rule");};
const value=vm.runInNewContext(code+"; JSON.stringify(aiPayload());",{
  A:()=>read,S:{call,coin:"HI",tf:"1h",data:{exchange:"test"},all:{"1h":read}},TA,TFS:[],PK:null,
  sigName:s=>s.name,stopWhy:forbidden,trailWhy:forbidden,exitWhy:forbidden});
process.stdout.write(value);
'''
        payload = json.loads(subprocess.check_output([NODE, "-e", script, str(ROOT)],
                                                     input=json.dumps(doc).encode(), timeout=30))
        self.assertEqual(payload["plan"], {"authority": "EXACT_GOVERNED_PROPOSAL", "side": "long",
                                          "proposal": proposal})
        self.assertEqual(payload["call"]["verdict"], "LONG")

    def test_quant_signal_math_parameters_and_runtime_order_unchanged(self):
        old = original("quant.py").decode()
        new = (ROOT / "quant.py").read_text(encoding="utf8")
        old_assign, new_assign = assignments(old), assignments(new)
        for name, node in old_assign.items():
            with self.subTest(assignment=name):
                self.assertIn(name, new_assign)
                self.assertEqual(dump(node), dump(new_assign[name]))
        self.assertEqual(set(new_assign) - set(old_assign),
                         {"EXECUTION_VERSION", "EXECUTION_QUALIFIED", "LEGACY_EXECUTION_UNQUALIFIED"})
        old_fn, new_fn = functions(old), functions(new)
        accounting = {"funding_since", "sim_trade", "live_stats", "journal_evidence", "run"}
        for name, node in old_fn.items():
            if name not in accounting:
                with self.subTest(function=name):
                    self.assertIn(name, new_fn)
                    self.assertEqual(dump(node), dump(new_fn[name]))
        self.assertEqual(set(new_fn) - set(old_fn),
                         {"execution_qualified", "qualified_trade", "execution_class", "mark_legacy_execution",
                          "_valid_execution_bar", "_valid_execution_time"})
        self.assertEqual(dump(normalize_run(old_fn["run"])), dump(normalize_run(new_fn["run"])))

    # v9 phase B changes four of the files pinned below on purpose: the reviewed strategy policy and its validator (the
    # probation tier), the decision policy and engine (probation tier and governed book) and one field of the Phase 10
    # portfolio input (each paper position's entry time). tests/test_v9_scope.py proves each change against main at the
    # start of v9 phase B (the merge of this PR); everything else stays pinned to PR24's start here.
    def test_phase9_methods_candidate_definitions_and_policies_unchanged(self):
        paths = ("v8/strategy_authority.py",
                 "tools/research/strategy_adjudication.py", "tools/research/matched_controls.py",
                 "tools/research/multiple_testing.py", "tools/research/strategy_census.py",
                 "tools/research/qexport.py", "tools/research/qstrat.py", "tools/research/qind.py",
                 "tools/research/qdata.py", "tools/research/qsim.py", "tools/research/qgrid.py",
                 "tools/research/qrun.py", "tools/research/qrun3y.py")
        for name in paths:
            with self.subTest(file=name):
                self.assertEqual((ROOT / name).read_bytes(), original(name))

    def test_phase10_limits_and_risk_engine_unchanged(self):
        for name in ("v8/portfolio_risk_policy.json",):        # portfolio_risk.py: tests/test_v9_scope.py
            with self.subTest(file=name):
                self.assertEqual((ROOT / name).read_bytes(), original(name))

    def test_phase11_policy_state_and_ranking_unchanged(self):
        # decision_policy.json and the functions v9 phase B declares are proven in tests/test_v9_scope.py
        old_fn = functions(original("v8/decision.py").decode())
        new_fn = functions((ROOT / "v8/decision.py").read_text(encoding="utf8"))
        boundary_changes = {"_asset_gates", "_freshness", "_context", "_directional"}
        v9_changes = {"validate_policy", "_valid_until", "_emerging", "build"}
        v9_added = {"_side_name", "_authorized_side", "_governed_book", "_forward_test"}
        for name, node in old_fn.items():
            if name not in boundary_changes | v9_changes:
                with self.subTest(function=name):
                    self.assertEqual(dump(node), dump(new_fn[name]))
        self.assertEqual(set(new_fn) - set(old_fn), {"_validate_inputs"} | v9_added)

    def test_phase12_research_publication_logic_unchanged(self):
        for name in ("tools/research/production_publication.py", "research.html",
                     ".github/workflows/research.yml", ".github/workflows/scan.yml"):
            with self.subTest(file=name):
                self.assertEqual((ROOT / name).read_bytes(), original(name))
        def research_section(raw):
            start = raw.index("  /* RESEARCH:")
            end = raw.index("  /* What the pages re-render on", start)
            return raw[start:end]
        self.assertEqual(research_section((ROOT / "desk.js").read_text(encoding="utf8")),
                         research_section(original("desk.js").decode()))

    def test_trial_census_and_candidate_count_unchanged(self):
        from tools.research import strategy_census as C
        census = C.build()
        self.assertEqual(len(C.catalog()), 24)
        self.assertEqual(census["known_lower_bound"], 199)
        self.assertFalse(census["complete"])
        raw = (json.dumps(census, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "bb7b26ed0f072387b28faebc5ff329af02e722a28054c47231f2f8721509897d")


if __name__ == "__main__":
    unittest.main()
