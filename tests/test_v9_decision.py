"""v9 phase B: the probation tier, the governed book and entered signals.

    the decision policy invariants (only ACTIVE_REQUALIFIED/REQUALIFIED or ACTIVE_PROBATION/PROBATION can TRADE)
    the strategy policy's fail-closed probation binding (evidence, verdict, runtime, forward-test registration, size)
    the engine: the confirmed side at half size, the unconfirmed side WATCH, the entry window, the forward test's
    registered start and demotion band, the governed book (legacy holdovers no longer gate), entered signals
    the quant-side inputs (ENTERED signals, the forward-test record) and the desk's presentation

Run from the repository root:  python -m unittest tests.test_v9_decision -v"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import test_v8_phase11 as P  # noqa: E402
from v8 import decision as DE  # noqa: E402
from v8 import portfolio_risk as PR  # noqa: E402
from v8 import strategy_policy as SP  # noqa: E402
import quant  # noqa: E402

NODE = shutil.which("node")
DAY = 86400
REAL_POLICY = SP.load(quant.STRATS)
REAL_ROW = next(r for r in REAL_POLICY["strategies"] if r["strategy_id"] == "XSMOM")
REAL_TERMS = SP.probation_terms(REAL_ROW)
EID = REAL_TERMS["sides"]["long"]["forward_test"]["experiment_id"]
BAND = {b["trades"]: b["p05_mean_R"] for b in REAL_TERMS["sides"]["long"]["demotion_band"]["table"]}


def prob_strategy(effective=P.AS_OF - 10 * DAY, window=None, mult=None):
    """A probation strategy with the real bound terms (evidence, band, expectation), started inside the fixture."""
    terms = copy.deepcopy(REAL_TERMS)
    for side in terms["sides"].values():
        side["forward_test"] = dict(side["forward_test"], effective_from=effective)
        if window is not None:
            side["entry_window_s"] = window
    if mult is not None:
        terms["risk_multiplier"] = mult
    return {"tf": "1d", "hold_h": 336, "deployment_state": "ACTIVE_PROBATION", "research_state": "PROBATION",
            "probation": terms}


def strats(**kw):
    s = copy.deepcopy(P.STRATS)
    s["PROB"] = prob_strategy(**kw)
    return s


def forward(n=0, mean=None):
    return {EID: {"closed": n, "mean_R": mean, "open": 0}}


def snap(signals, book=(), strategies=None, ft="default", recs=None, contracts=None):
    s = P.snapshot(recs or [P.rec(a) for a in sorted(signals)], signals, book=book,
                   strategies=strategies or strats(), contracts=contracts)
    s["forward_tests"] = forward() if ft == "default" else ft
    return s


def cand(doc, asset, sid="PROB", d=1):
    return next(c for c in doc["candidates"] if c["type"] == DE.DIRECTIONAL and c["asset"] == asset
                and c["strategy"] == sid and c["direction"] == d)


def gate(c, step):
    return next(g for g in c["trace"] if g["step"] == step)


def codes(c):
    return c["blockers"] + c["caps"] + c["missing_authorities"]


# --------------------------------------------------------------------------- the decision policy
class DecisionPolicy(unittest.TestCase):
    def test_probation_lists_are_invariant(self):
        good = DE.load_policy()
        for section, key, value, why in (
                ("strategy_authority", "probation_deployment_states", ["ACTIVE_PROBATION", "LEGACY_HOLDOVER"], "ACTIVE_PROBATION"),
                ("strategy_authority", "probation_research_states", ["PROBATION", "INSUFFICIENT_EVIDENCE"], "PROBATION"),
                ("strategy_authority", "trade_deployment_states", ["ACTIVE_REQUALIFIED", "ACTIVE_PROBATION"], "ACTIVE_REQUALIFIED"),
                ("strategy_authority", "probation_deployment_states", [], "mapped"),
                ("portfolio", "gating_book", "FULL_PAPER_BOOK", "gating_book")):
            p = copy.deepcopy(good)
            p[section][key]["value"] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(DE.PolicyError, why):
                DE.validate_policy(p)
        p = copy.deepcopy(good)
        p["strategy_authority"]["watch_deployment_states"]["value"].append("ACTIVE_PROBATION")
        with self.assertRaisesRegex(DE.PolicyError, "disjoint"):
            DE.validate_policy(p)

    def test_only_the_two_authorized_tiers_can_trade(self):
        """Every fixture strategy, both sides, all other gates passing: TRADE only for a requalified strategy (both
        sides) and for the probation strategy's confirmed side."""
        sigs = {}
        names = [a for a in P.NAMES if a != "BTC"]
        k = 0
        for sid in ("TSMOM", "REQ", "REQ4H", "DIS", "REJ", "PAPER", "PROB"):
            for d in (1, -1):
                sigs.setdefault(names[k % len(names)], []).append(P.sig(sid, d=d, age=600))
                k += 1
        doc = DE.build(snap(sigs))
        trades = sorted({(c["strategy"], c["direction"]) for c in doc["candidates"] if c["state"] == DE.TRADE})
        self.assertEqual(trades, [("PROB", 1), ("REQ", -1), ("REQ", 1), ("REQ4H", -1), ("REQ4H", 1)])
        for c in doc["candidates"]:
            if c["state"] == DE.TRADE:
                self.assertEqual(c["authority_tier"], "PROBATION" if c["strategy"] == "PROB" else "FULL")


# --------------------------------------------------------------------------- the strategy policy binding
def copy_bound(policy, root):
    for row in policy["strategies"]:
        prob = row.get("probation")
        if prob:
            for rel in [prob["evidence"]["path"]] + [f["path"] for f in prob["forward_tests"].values()]:
                dst = Path(root) / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / rel, dst)


class StrategyPolicyBinding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.policy = copy.deepcopy(REAL_POLICY)
        copy_bound(self.policy, self.root)
        self.row = next(r for r in self.policy["strategies"] if r["strategy_id"] == "XSMOM")
        self.prob = self.row["probation"]

    def valid(self):
        return SP.validate(self.policy, quant.STRATS, self.root)

    def invalid(self, why="STRATEGY_POLICY_INVALID"):
        with self.assertRaisesRegex(ValueError, why):
            self.valid()

    def rewrite(self, ref, change):
        path = self.root / ref["path"]
        doc = json.loads(path.read_bytes())
        change(doc)
        raw = (json.dumps(doc, sort_keys=True, indent=1) + "\n").encode()
        path.write_bytes(raw)
        ref["sha256"] = hashlib.sha256(raw).hexdigest()

    def test_real_policy_is_valid_and_bound(self):
        self.assertIs(self.valid(), self.policy)
        t = SP.probation_terms(self.row, self.root)
        self.assertEqual((t["risk_multiplier"], sorted(t["sides"])), (0.5, ["long"]))
        self.assertEqual(t["sides"]["long"]["entry_window_s"], 24 * 3600)
        self.assertGreater(t["sides"]["long"]["expectation"]["out_of_sample_mean_R"], 0)
        self.assertEqual(t["sides"]["long"]["forward_test"]["effective_from"], 1792022400)   # 2026-10-15 00:00 UTC

    def test_size_and_sides_are_bounded(self):
        for value in (0.6, 1.0, 0, -0.1, True, "0.5", None):
            with self.subTest(risk_multiplier=value):
                self.setUp()
                self.prob["risk_multiplier"] = value
                self.invalid()
        for sides in ([], ["long", "long"], ["sideways"], ["long", "short"], "long"):
            with self.subTest(sides=sides):
                self.setUp()
                self.prob["sides"] = sides
                self.invalid()

    def test_evidence_binding_fails_closed(self):
        mutations = {
            "hash": lambda: self.prob["evidence"].update(sha256="0" * 64),
            "bytes": lambda: (self.root / self.prob["evidence"]["path"]).open("ab").write(b" "),
            "missing": lambda: (self.root / self.prob["evidence"]["path"]).unlink(),
            "outside": lambda: self.prob["evidence"].update(path="../outside.json"),
            "verdict": lambda: self.rewrite(self.prob["evidence"], lambda d: [h.update(verdict="NOT_CONFIRMED") for h in d["hypotheses"]]),
            "failing": lambda: self.rewrite(self.prob["evidence"], lambda d: [h.update(failing=["b_holdout_holm"]) for h in d["hypotheses"]]),
            "check": lambda: self.rewrite(self.prob["evidence"], lambda d: [h["checks"].update(j_late_entry=False) for h in d["hypotheses"]]),
            "runtime": lambda: self.rewrite(self.prob["evidence"], lambda d: d["code"].update(runtime_implementation_hash="a" * 64)),
            "definition": lambda: self.rewrite(self.prob["evidence"], lambda d: [h.update(runtime_definition_hash="b" * 64) for h in d["hypotheses"]]),
            "window": lambda: self.rewrite(self.prob["evidence"], lambda d: [h["late_entry"].update(trade_window_hours=0) for h in d["hypotheses"]]),
            "band": lambda: self.rewrite(self.prob["evidence"], lambda d: [h.pop("demotion_band", None) for h in d["hypotheses"]]),
            "schema": lambda: self.rewrite(self.prob["evidence"], lambda d: d.update(schema="v9.probation-evidence/0")),
        }
        for label, mutate in mutations.items():
            with self.subTest(mutation=label):
                self.setUp()
                mutate()
                self.invalid()

    def test_forward_test_registration_fails_closed(self):
        ft = lambda: self.prob["forward_tests"]["long"]   # noqa: E731
        mutations = {
            "absent": lambda: self.prob.update(forward_tests={}),
            "hash": lambda: ft().update(sha256="0" * 64),
            "id": lambda: ft().update(experiment_id="V9-OTHER-1"),
            "start": lambda: ft().update(effective_from=ft()["effective_from"] + 1),
            "not in the ledger": lambda: ft().update(path=self.prob["evidence"]["path"], sha256=self.prob["evidence"]["sha256"]),
            "other side": lambda: self.rewrite(ft(), lambda d: d["params"].update(side="short")),
            "other size": lambda: self.rewrite(ft(), lambda d: d["params"].update(risk_multiplier=0.25)),
            "other strategy": lambda: self.rewrite(ft(), lambda d: d["params"].update(strategy_id="TSMOM")),
            "status": lambda: self.rewrite(ft(), lambda d: d.update(status="RUNNING")),
            "authority": lambda: self.rewrite(ft(), lambda d: d.update(authority="TRADE")),
            "registered after start": lambda: self.rewrite(ft(), lambda d: d.update(registered_at=d["evaluation_start"] + 1)),
            "extra key": lambda: ft().update(note="x"),
        }
        for label, mutate in mutations.items():
            with self.subTest(mutation=label):
                self.setUp()
                mutate()
                self.invalid()

    def test_states_and_records_must_agree(self):
        for label, change in (("research state", {"research_state": "INSUFFICIENT_EVIDENCE"}),
                              ("requalified research", {"research_state": "REQUALIFIED"})):
            with self.subTest(label):
                self.setUp()
                self.row.update(change)
                self.invalid()
        self.setUp()
        del self.row["probation"]
        self.invalid()
        self.setUp()
        self.row["probation"]["extra"] = 1
        self.invalid()
        self.setUp()      # a probation record on a row that is not on probation
        legacy = next(r for r in self.policy["strategies"] if r["strategy_id"] == "TSMOM")
        legacy["probation"] = copy.deepcopy(self.prob)
        self.invalid("not ACTIVE_PROBATION")
        self.setUp()      # the probation strategy must stay in the runtime order (it is deployment-enabled)
        self.policy["runtime_order"] = ["TSMOM", "TREND_EMA"]
        self.invalid("order")


# --------------------------------------------------------------------------- the engine
class ProbationTier(unittest.TestCase):
    def test_confirmed_side_trades_at_half_size(self):
        doc = DE.build(snap({"HI": [P.sig("PROB", d=1, age=600)], "LO": [P.sig("REQ", d=1, age=600)]}))
        c, full = cand(doc, "HI"), cand(doc, "LO", "REQ")
        self.assertEqual((c["state"], c["authority_tier"], full["authority_tier"]), (DE.TRADE, "PROBATION", "FULL"))
        self.assertEqual(c["proposal"]["risk_fraction"], 0.0025)               # the page's 0.5% at 0.5x
        self.assertEqual(c["proposal"]["size_multiplier"], 0.5)
        self.assertAlmostEqual(c["proposal"]["notional"], full["proposal"]["notional"] / 2)
        # the exit besides the stop is the strategy's own hold, for either tier
        self.assertEqual((c["proposal"]["time_exit_hours"], full["proposal"]["time_exit_hours"]), (336, 48))
        self.assertEqual(gate(c, "STRATEGY_AUTHORITY")["result"], DE.PASS)
        self.assertIn("probation", gate(c, "STRATEGY_AUTHORITY")["rule"].lower())
        self.assertEqual(c["probation"]["expectation"], REAL_TERMS["sides"]["long"]["expectation"])
        self.assertEqual(doc["best_trades_now"]["count"], 2)
        self.assertEqual(doc["market_summary"]["trade_by_tier"], {"FULL": 1, "PROBATION": 1})

    def test_time_exit_is_stated_only_when_the_strategy_has_one(self):
        s = snap({"HI": [P.sig("PROB", age=600)]})
        for bad in (None, 0.5, "336", True, 0, -24):
            with self.subTest(hold_h=bad):
                s2 = json.loads(json.dumps(s))
                s2["strategies"]["PROB"]["hold_h"] = bad
                c = cand(DE.build(s2), "HI")
                self.assertIsNone(c["proposal"]["time_exit_hours"])

    def test_unconfirmed_side_is_watch_at_half_size(self):
        doc = DE.build(snap({"HI": [P.sig("PROB", d=-1, age=600)]}))
        c = cand(doc, "HI", d=-1)
        self.assertEqual((c["state"], c["caps"]), (DE.WATCH, ["STRATEGY_SIDE_NOT_CONFIRMED"]))
        self.assertIsNone(c["authority_tier"])
        self.assertEqual(c["proposal"]["size_multiplier"], 0.5)
        # ... and it is not positive evidence for an emerging observation (a legacy-holdover WATCH signal still is)
        self.assertFalse([x for x in doc["candidates"] if x["type"] == DE.EMERGING])
        doc = DE.build(snap({"HI": [P.sig("TSMOM", d=-1, age=600)]}))
        self.assertTrue([x for x in doc["candidates"] if x["type"] == DE.EMERGING])

    def test_entry_window_and_valid_until(self):
        c = cand(DE.build(snap({"HI": [P.sig("PROB", age=600)]})), "HI")
        bar = gate(c, "SIGNAL")["input"]["bar_close_t"]
        self.assertEqual(c["state"], DE.TRADE)
        self.assertEqual(c["valid_until"], min(bar + 24 * 3600, P.AS_OF + 3600, bar + 90000, P.AS_OF - 60 + 3600))
        c = cand(DE.build(snap({"HI": [P.sig("PROB", age=86400 + 60)]})), "HI")   # past 24h, before max_age 25h
        self.assertEqual((c["state"], c["caps"]), (DE.WATCH, ["PROBATION_ENTRY_WINDOW_PASSED"]))
        c = cand(DE.build(snap({"HI": [P.sig("PROB", age=3 * 3600)]}, strategies=strats(window=2 * 3600))), "HI")
        self.assertEqual(c["caps"], ["PROBATION_ENTRY_WINDOW_PASSED"])
        c = cand(DE.build(snap({"HI": [P.sig("PROB", age=600)]}, strategies=strats(window=1800))), "HI")
        self.assertEqual((c["state"], c["valid_until"]), (DE.TRADE, P.AS_OF - 600 + 1800))   # the window ends it

    def test_no_probation_trade_before_the_registered_start(self):
        bar = P.AS_OF - 600
        c = cand(DE.build(snap({"HI": [P.sig("PROB", age=600)]}, strategies=strats(effective=bar + 1))), "HI")
        self.assertEqual((c["state"], c["caps"]), (DE.WATCH, ["PROBATION_NOT_YET_EFFECTIVE"]))
        c = cand(DE.build(snap({"HI": [P.sig("PROB", age=600)]}, strategies=strats(effective=bar))), "HI")
        self.assertEqual(c["state"], DE.TRADE)

    def test_forward_test_record_and_demotion_band(self):
        c = cand(DE.build(snap({"HI": [P.sig("PROB")]}, ft={})), "HI")
        self.assertEqual((c["state"], c["missing_authorities"]), (DE.WATCH, ["FORWARD_TEST_RECORD_MISSING"]))
        cases = ((29, -5.0, DE.TRADE), (30, BAND[30] + 1e-9, DE.TRADE), (30, BAND[30] - 1e-9, DE.WATCH),
                 (49, BAND[30] - 1e-9, DE.WATCH), (100, BAND[100] - 1e-9, DE.WATCH), (100, BAND[100] + 1e-9, DE.TRADE),
                 (500, 0.05, DE.WATCH), (500, 0.2, DE.TRADE), (40, None, DE.WATCH))
        for n, mean, state in cases:
            with self.subTest(n=n, mean=mean):
                c = cand(DE.build(snap({"HI": [P.sig("PROB")]}, ft=forward(n, mean))), "HI")
                self.assertEqual(c["state"], state)
                if state == DE.WATCH:
                    self.assertEqual(c["caps"], ["PROBATION_FORWARD_TEST_FAILED"])
                self.assertEqual(gate(c, "STRATEGY_AUTHORITY")["input"]["forward_test"]["closed"], n)

    def test_probation_terms_must_be_present_and_bounded(self):
        s = strats()
        del s["PROB"]["probation"]
        c = cand(DE.build(snap({"HI": [P.sig("PROB")]}, strategies=s)), "HI")
        self.assertEqual((c["state"], c["missing_authorities"]), (DE.WATCH, ["PROBATION_TERMS_MISSING"]))
        c = cand(DE.build(snap({"HI": [P.sig("PROB")]}, strategies=strats(mult=0.9))), "HI")
        self.assertEqual(c["missing_authorities"], ["PROBATION_TERMS_MISSING"])
        self.assertEqual(c["proposal"]["size_multiplier"], 1.0)     # an out-of-bounds multiplier is never applied


class GovernedBook(unittest.TestCase):
    BIG = [P.book_position(f"L{k}", a, 1, 400.0, strategy="TSMOM") for k, a in enumerate(("LO", "ALPHA", "BRAVO", "CHARLIE"))]

    def test_legacy_holdovers_no_longer_gate(self):
        doc = DE.build(snap({"HI": [P.sig("PROB")]}, book=self.BIG))
        c = cand(doc, "HI")
        self.assertEqual(c["state"], DE.TRADE)
        pf = doc["portfolio"]
        self.assertEqual((pf["phase10"]["state"], pf["full_paper_book"]["state"]), (PR.WITHIN, PR.BREACHED))
        self.assertEqual((pf["governed"]["governed_positions"], pf["governed"]["excluded_paper_positions"]), (0, 4))
        self.assertTrue(pf["binding"]["consistent"])               # the audit binding is still the full book's
        self.assertEqual(gate(c, "PORTFOLIO_BEFORE")["input"]["book"]["gating_book"], DE.GOVERNED_BOOK)

    def test_authorized_positions_still_gate(self):
        big = [dict(p, strategy="REQ") for p in self.BIG]
        c = cand(DE.build(snap({"HI": [P.sig("PROB")]}, book=big)), "HI")
        self.assertEqual((c["state"], c["blocking_step"]), (DE.AVOID, "PORTFOLIO_AFTER"))

    def test_probation_positions_count_from_their_start(self):
        start = P.AS_OF - 10 * DAY
        before = P.book_position("old", "LO", 1, 50.0, strategy="PROB", entered_at=start - 1)
        after = P.book_position("new", "ALPHA", 1, 50.0, strategy="PROB", entered_at=start)
        short = P.book_position("sh", "BRAVO", -1, 50.0, strategy="PROB", entered_at=start)     # the unconfirmed side
        doc = DE.build(snap({"HI": [P.sig("PROB")]}, book=[before, after, short]))
        self.assertEqual([p["id"] for p in doc["portfolio"]["governed_positions"]], ["new"])
        self.assertEqual(doc["portfolio"]["governed"]["excluded_paper_positions"], 2)

    def test_governed_positions_take_the_current_observed_funding(self):
        start = P.AS_OF - 10 * DAY
        pos = P.book_position("new", "ALPHA", 1, 50.0, strategy="PROB", entered_at=start,
                              funding={"state": "MISSING", "reason": "NO_AUTHORITATIVE_LIVE_FUNDING"})
        with_rate = [P.contract("HI"), P.contract("ALPHA", fund=0.0002)]
        doc = DE.build(snap({"HI": [P.sig("PROB")]}, book=[pos], contracts=with_rate,
                            recs=[P.rec("HI"), P.rec("ALPHA")]))
        g = doc["portfolio"]["governed_positions"][0]
        self.assertEqual((g["funding"], g["funding_rate_8h"]), ("OBSERVED", 0.0002))
        self.assertEqual(cand(doc, "HI")["state"], DE.TRADE)
        doc = DE.build(snap({"HI": [P.sig("PROB")]}, book=[pos]))          # no fresh rate for ALPHA: never zero
        self.assertEqual(doc["portfolio"]["phase10"]["state"], PR.UNEVALUABLE)
        self.assertEqual(cand(doc, "HI")["missing_authorities"], ["PORTFOLIO_UNEVALUABLE"])

    def test_entered_signal_stays_the_same_opportunity(self):
        bar = P.AS_OF - 5 * 3600
        own = P.book_position("HI-PROB-1", "HI", 1, 50.0, strategy="PROB", entered_at=bar)
        c = cand(DE.build(snap({"HI": [P.sig("PROB", kind="ENTERED", age=5 * 3600, trade_id="HI-PROB-1")]}, book=[own])), "HI")
        self.assertEqual(c["state"], DE.TRADE)
        self.assertEqual(gate(c, "PORTFOLIO_BEFORE")["input"]["own_paper_position_excluded"], "HI-PROB-1")
        self.assertEqual(c["ranking_inputs"]["signal_kind_order"], 0)
        older = P.book_position("HI-PROB-0", "HI", 1, 50.0, strategy="PROB", entered_at=bar - 3 * DAY)
        c = cand(DE.build(snap({"HI": [P.sig("PROB", kind="ACTIVE", age=5 * 3600)]}, book=[older])), "HI")
        self.assertEqual((c["state"], c["blockers"]), (DE.AVOID, ["POSITION_ALREADY_OPEN"]))

    def test_strategy_tiers_are_published(self):
        doc = DE.build(snap({}, recs=[P.rec("HI")]))
        tiers = doc["strategy_tiers"]
        self.assertEqual(sorted(x["strategy"] for x in tiers["FULL"]), ["REQ", "REQ4H"])
        self.assertEqual([(x["strategy"], sorted(x["sides"]), x["risk_multiplier"]) for x in tiers["PROBATION"]],
                         [("PROB", ["long"], 0.5)])
        self.assertEqual(tiers["PROBATION"][0]["sides"]["long"]["forward_test_state"], "ACTIVE")
        self.assertTrue(doc["market_summary"]["zero_trade"])

    def test_evaluate_asset_is_the_same_engine(self):
        s = snap({"HI": [P.sig("PROB"), P.sig("PROB", d=-1)]}, book=self.BIG)
        market = DE.build(s)
        single = DE.evaluate_asset(s, "HI")
        mine = [{k: v for k, v in c.items() if k != "placement"} for c in market["candidates"] if c["asset"] == "HI"]
        self.assertEqual(P.canon(single["opportunities"]), P.canon(mine))


# --------------------------------------------------------------------------- the quant-side inputs
class QuantInputs(unittest.TestCase):
    def test_entered_signals(self):
        from v8 import audit_quant as AQ
        lastd = P.T0
        q = types.SimpleNamespace(RUNTIME_ORDER=("XSMOM",), STRATS=quant.STRATS, _stop=quant._stop, DAY=quant.DAY)
        feats = {"AAA": {"c": [100.0], "atr": [4.0]}, "BBB": {"c": [50.0], "atr": [2.0]}}
        opened = [{"id": "AAA-XSMOM-1", "s": "XSMOM", "c": "AAA", "d": 1, "t_sig": lastd + quant.DAY},
                  {"id": "BBB-XSMOM-0", "s": "XSMOM", "c": "BBB", "d": 1, "t_sig": lastd - 5 * quant.DAY}]
        sig = AQ.signal_states(q, {}, feats, {"AAA": 1, "BBB": 1}, lastd, [], opened)
        self.assertEqual((sig["AAA"][0]["kind"], sig["AAA"][0]["trade_id"]), ("ENTERED", "AAA-XSMOM-1"))
        self.assertEqual((sig["BBB"][0]["kind"], sig["BBB"][0]["trade_id"]), ("ACTIVE", None))
        new = [{"id": "BBB-XSMOM-2", "s": "XSMOM", "c": "BBB", "d": 1, "t_sig": lastd + quant.DAY, "stop_pct": 0.1,
                "trail_pct": 0.0}]
        sig = AQ.signal_states(q, {}, feats, {"AAA": 1, "BBB": 1}, lastd, new, opened)
        self.assertEqual((sig["BBB"][0]["kind"], sig["BBB"][0]["trade_id"]), ("NEW", "BBB-XSMOM-2"))

    def test_forward_test_record(self):
        from v8 import audit_quant as AQ
        start = REAL_TERMS["sides"]["long"]["forward_test"]["effective_from"]
        closed = [{"id": "a", "s": "XSMOM", "c": "A", "d": 1, "t_in": start, "t_out": start + DAY, "r": 1.0},
                  {"id": "b", "s": "XSMOM", "c": "B", "d": 1, "t_in": start + DAY, "t_out": start + 2 * DAY, "r": -0.5},
                  {"id": "c", "s": "XSMOM", "c": "C", "d": 1, "t_in": start - 1, "t_out": start + DAY, "r": 9.0},
                  {"id": "d", "s": "XSMOM", "c": "D", "d": -1, "t_in": start, "t_out": start + DAY, "r": 9.0},
                  {"id": "e", "s": "TSMOM", "c": "E", "d": 1, "t_in": start, "t_out": start + DAY, "r": 9.0},
                  {"id": "f", "s": "XSMOM", "c": "F", "d": 1, "t_in": start + DAY, "t_out": None, "r": None}]
        q = types.SimpleNamespace(POLICY=REAL_POLICY, qualified_trade=lambda tr: tr["id"] == "a")
        rec = AQ.forward_tests(q, [{"s": "XSMOM", "d": 1, "t_in": start + 2 * DAY}], [], {"closed": closed})[EID]
        self.assertEqual((rec["closed"], rec["closed_without_r"], rec["mean_R"], rec["wins"], rec["open"]),
                         (2, 1, 0.25, 1, 1))
        self.assertEqual((rec["qualified_closed"], rec["qualified_mean_R"]), (1, 1.0))
        self.assertEqual(rec["side"], "long")


# --------------------------------------------------------------------------- the desk
RUN = r"""
const D = require(process.argv[1]);
const F = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));
const out = {};
for (const [k, doc] of Object.entries(F.docs)) {
  out[k] = {today: D.views.today(doc, F.now), portfolio: D.views.portfolio(doc, F.now, null, "unavailable")};
}
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node unavailable")
class Desk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start = P.AS_OF - 10 * DAY
        own = P.book_position("ALPHA-PROB-1", "ALPHA", 1, 50.0, strategy="PROB", entered_at=start)
        docs = {"trade": DE.build(snap({"HI": [P.sig("PROB", age=2 * 3600)]}, book=[own] + GovernedBook.BIG,
                                        contracts=[P.contract(a) for a in ("HI", "ALPHA")],
                                        recs=[P.rec("HI"), P.rec("ALPHA")])),
                "empty": DE.build(snap({}, recs=[P.rec("HI")], book=GovernedBook.BIG))}
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "in.json"
            f.write_text(json.dumps({"docs": docs, "now": P.AS_OF + 60}))
            cls.out = json.loads(subprocess.check_output([NODE, "-e", RUN, str(ROOT / "desk.js"), str(f)], timeout=60))

    def test_probation_trade_card(self):
        best = self.out["trade"]["today"]["best"]
        for text in ("Probation · reduced size", "Enter near", "Stop", "0.5× the page size", "Entry window",
                     "Exit at the stop or <b>14 days</b> after you enter",
                     "Archive evidence", "R per trade out of sample", "Live forward test",
                     "Past results do not promise future ones"):
            self.assertIn(text, best)
        for banned in ("guaranteed", "risk-free", "certain", "proven profit"):
            self.assertNotIn(banned, best.lower())

    def test_analyzer_governed_card_states_the_time_exit(self):
        html = (ROOT / "analyze.html").read_text(encoding="utf8")
        src = html[html.index("function govExitTxt("):html.index("const s = c.lead, p = c.plan, L = p.side")] + "}"
        js = ("const vm=require('vm');const ctx={esc:String,fp:String,money:String,money2:String};vm.createContext(ctx);"
              "vm.runInContext(process.argv[1],ctx);const base={kind:'governed',entry:1,stop:0.9,equity:1e4,size:100,"
              "lev:1,riskUsd:5,riskFraction:0.0025,costs:{fees:0,slippage:0},sizingBasis:'b'};"
              "const out=[336,24,30,null,0].map(h=>ctx.testedPlanCard({verdict:'LONG',plan:Object.assign({},base,"
              "{proposal:{time_exit_hours:h}})}));process.stdout.write(JSON.stringify(out));")
        out = json.loads(subprocess.check_output([NODE, "-e", js, src], timeout=60))
        self.assertIn("<b>Exit:</b> at the stop, or 14 days after you enter, whichever comes first.", out[0])
        self.assertIn("or 1 day after you enter", out[1])
        self.assertIn("or 30 hours after you enter", out[2])
        for html_out in out[3:]:
            self.assertNotIn("Exit:", html_out)
        self.assertIn("Exact governed proposal", out[0])

    def test_empty_state_says_what_can_trade(self):
        best = self.out["empty"]["today"]["best"]
        self.assertIn("No trade currently clears every desk gate.", best)
        self.assertIn("Authorized to trade: REQ (requalified); REQ4H (requalified); PROB long (probation, 0.5× size)", best)
        self.assertIn("Daily strategies decide at the 00:00 UTC close.", best)

    def test_governed_and_legacy_books_are_told_apart(self):
        pf = self.out["trade"]["today"]["pf"]
        self.assertIn("Governed book: 1 position of trade-authorized strategy sides.", pf)
        self.assertIn("4 legacy paper positions are a diagnostic only (that book: limits breached) and do not gate trades.", pf)
        body = self.out["trade"]["portfolio"]["body"]
        self.assertIn("Governed positions", body)
        self.assertIn("ALPHA", body)
        self.assertIn("Legacy paper book · diagnostic only", body)


if __name__ == "__main__":
    unittest.main()
