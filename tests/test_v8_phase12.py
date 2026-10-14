"""v8 Phase 12: the production desk (Today, Analyzer, Funding, Portfolio, Research) presents the governed Phase 11
decision (data/v8/decision.json) and never re-decides it.

The shared presentation core (desk.js) and the Analyzer's call (analyze.js) are run under node on decision documents
built by the real engine (v8/decision.py), on tampered copies of them and on hostile strings; the HTML they return is
what the pages insert. The fifteen adversarial checks of the Phase 12 brief are test_01 ... test_15; the rest cover
escaping, copy, navigation, script order and the published pages. Skipped (the node part) when node is not installed.

Run from the repository root:  python -m unittest tests.test_v8_phase12 -v"""
from __future__ import annotations

import copy
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import test_v8_phase11 as P  # noqa: E402
from v8 import decision as DE  # noqa: E402
from v8 import portfolio_risk as PR  # noqa: E402

NODE = shutil.which("node")
DAY, H = 86400, 3600
NOW = P.AS_OF + 60
EVIL = 'AL"><img src=x onerror=alert(1)><script>alert(2)</script>'
DESK_PAGES = ["today.html", "analyze.html", "funding.html", "portfolio.html", "research.html"]
LEGACY_PAGES = ["index.html", "picks.html", "quant.html", "smart.html"]
NAV = [("./", "Today"), ("analyze.html", "Analyzer"), ("funding.html", "Funding"), ("portfolio.html", "Portfolio"),
       ("research.html", "Research")]

RUNNER = r"""
const D = require(process.argv[2]), TA = require(process.argv[3]);
const F = JSON.parse(require("fs").readFileSync(process.argv[4], "utf8"));
const ref = (x) => Array.isArray(x) ? x.map(ref) : x && typeof x === "object" ?
  ("$doc" in x ? F.docs[x.$doc] : "$cand" in x ? D.index(F.docs[x.$cand[0]]).byId.get(x.$cand[1]) :
   Object.fromEntries(Object.entries(x).map(([k, v]) => [k, ref(v)]))) : x;
const fn = (p) => p.split(".").reduce((o, k) => o[k], {D, TA});
const brief = (r) => ({verdict: r.verdict, side: r.side, tier: r.tier, plan: r.plan,
  lead: r.lead && {src: r.lead.src, side: r.lead.side, planError: r.lead.planError || null},
  status: r.authority.status, state: r.authority.state, headline: r.headline,
  signals: r.signals.map((s) => [s.src, s.side, s.tier, s.plan ? "plan" : null])});
const out = {};
for (const op of F.ops) {
  try {
    if (op.analyze) {          // the Analyzer's call and its decision panel, exactly as analyze.html renders them
      const a = ref(op.analyze), call = TA.decide(a);
      out[op.k] = {call: brief(call), panel: D.views.assetPanel(a.src.decision, a.coin, a.now, call)};
    } else out[op.k] = fn(op.fn).apply(null, ref(op.args));
  } catch (e) { out[op.k] = {__error: String(e && e.stack || e)}; }
}
process.stdout.write(JSON.stringify(out));
"""


# --------------------------------------------------------------------------- decision documents (the real engine)
def pair(asset, long_fund=-0.003, short_fund=0.003):
    return [P.contract(asset, "hyperliquid", fund=long_fund), P.contract(asset, "lighter", fund=short_fund, npx=100.1)]


def mixed(signals=None, **kw):
    """TRADE (HI, a requalified strategy), WATCH (LO, a legacy holdover; ALPHA and LO emerging), AVOID (NEG, a disabled
    strategy) and a qualified funding spread (TWIN, two healthy legs)."""
    recs = [P.rec("HI"), P.rec("LO"), P.rec("NEG"), P.rec("ALPHA", flags=["STAGE1_EXTREME", "MULTI_VENUE"]), P.rec("TWIN")]
    sigs = {"HI": [P.sig("REQ")], "LO": [P.sig("TSMOM", kind="ACTIVE")], "NEG": [P.sig("DIS")]} if signals is None else signals
    cons = [P.contract(a) for a in ("HI", "LO", "NEG", "ALPHA")] + pair("TWIN")
    return DE.build(P.snapshot(recs, sigs, contracts=cons, **kw))


def seven():
    names = P.NAMES[:10]
    sigs = {a: [P.sig("REQ", age=100 + k)] for k, a in enumerate(names[:7])}
    sigs.update({a: [P.sig("TSMOM", age=10)] for a in names[7:]})
    return DE.build(P.snapshot([P.rec(a) for a in names], sigs))


BIG = [P.book_position(f"B{k}", a, notional=400.0) for k, a in enumerate(["BTC", "TWIN", "ALPHA", "BRAVO"])]
BLOCKED = P.book_position("X", "LO", notional=20.0, actionability="IDENTITY_BLOCKED")
SMALL = [P.book_position("A", "BTC", notional=50.0), BLOCKED]


def funding_doc():
    """HI: a healthy pair and a degraded extreme-rate venue; TWIN: one healthy and one degraded leg (no spread); LO: a
    healthy pair."""
    legs = pair("HI") + [P.contract("HI", "aster", fund=0.09, npx=100.05, health="STALE")]
    twin = pair("TWIN")
    twin[1]["health"] = "DEGRADED"
    legs += twin + pair("LO", -0.002, 0.002)
    return DE.build(P.snapshot([P.rec(a) for a in ("HI", "TWIN", "LO")], {}, contracts=legs))


def cand_id(doc, asset, typ=DE.DIRECTIONAL):
    return next(c["id"] for c in doc["candidates"] if c["asset"] == asset and c["type"] == typ)


def evil(x):
    """Every string (and key) with ALPHA in it carries a hostile payload."""
    if isinstance(x, str):
        return x.replace("ALPHA", EVIL)
    if isinstance(x, list):
        return [evil(v) for v in x]
    if isinstance(x, dict):
        return {evil(k): evil(v) for k, v in x.items()}
    return x


def legacy_sources(side, decision, coin="LO"):
    """'Proven' legacy evidence on one coin: a swing score of 88 with a positive record, a smart-money crowd marked
    Proven, and a legacy-holdover quant position, all on the same side."""
    d = 1 if side == "long" else -1
    yrs = {"2024": {"R": 0.36, "n": 400}, "2025": {"R": 0.23, "n": 400}, "2026": {"R": 0.48, "n": 400}}
    band = [{"lo": 80, "hi": 90, "n": 1080, "R": 0.378, "win": 0.458, "years": yrs}]
    return {
        "decision": decision,
        "picks": {"day": NOW // DAY * DAY - DAY, "settings": {"ready": 80},
                  "scores": {coin: {"side": side, "score": 88, "core": 86, "label": "Ready"}}},
        "picksResearch": {"period": "Oct 2023 to Oct 2026", "swing": {"long": {"bands": band}, "short": {"bands": band}}},
        "smart": {"generated": NOW - 3 * H, "traders_n": 200,
                  "accuracy": {"verdict": "Proven", "tested": {"n": 31, "win": 0.613, "r": 0.145}, "live": {"n": 50}},
                  "coins": [{"coin": coin, "side": side, "signal": True, "info": False, "proven": True, "text": "proven traders",
                             "traders": 10, "n_long": 5, "n_short": 5, "identity": "VERIFIED_CRYPTO"}],
                  "open": [{"coin": coin, "d": d, "t_in": NOW - 3 * H, "px": 100, "last_px": 100.4, "stop_pct": 0.03,
                            "t_out_by": NOW + 21 * H, "kind": "signal"}]},
        "quant": {"strategies": {"TSMOM": {"name": "TSMOM", "deployment_state": "LEGACY_HOLDOVER",
                                           "research_state": "INSUFFICIENT_EVIDENCE"},
                                 "REQ": {"name": "REQ", "deployment_state": "ACTIVE_REQUALIFIED", "research_state": "REQUALIFIED"}},
                  "open": [{"s": "TSMOM", "c": coin, "d": d, "t_sig": NOW - 2 * DAY, "t_in": NOW - 2 * DAY, "px": 95 if d > 0 else 106,
                            "stop_pct": 0.1, "trail_pct": 0.1, "hold_h": 504, "identity": "VERIFIED_CRYPTO",
                            "res": {"state": "open", "stop_now": 90 if d > 0 else 111, "last_px": 100}, "stop": 85.5 if d > 0 else 116.6}]},
        "quantResearch": {"window_3y": [1703793600, 1791072000], "strategies": {"TSMOM": {"verdict": "live",
                          "three_year": {"n": 1181, "wr": 0.4141, "avg": 0.0564}, "years": []}}},
    }


def candles():
    t0 = NOW // DAY * DAY - 60 * DAY
    out = [{"t": t0 + i * DAY, "o": 100, "h": 102, "l": 98, "c": 100, "v": 1e6} for i in range(60)]
    return out + [{"t": t0 + 60 * DAY, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 3e5}]


# --------------------------------------------------------------------------- parsing the returned HTML
CARD = re.compile(r'<article class="opp([^"]*)" data-cand="([^"]*)" data-state="([^"]*)"[^>]*>(.*?)</article>', re.S)
CHIP = re.compile(r'<span class="chip (st-\w+)[^"]*"><span class="chip-mark" aria-hidden="true">[^<]*</span>([^<]*)</span>')


def cards(h):
    return [{"cls": m.group(1).strip(), "id": html.unescape(m.group(2)), "state": m.group(3), "body": m.group(4)}
            for m in CARD.finditer(h or "")]


def top_chip(card):
    m = CHIP.search(card["body"].split('<div class="opp-gates">')[0].split("</div>")[0])
    return (m.group(1), m.group(2)) if m else None


def text(h):
    """The visible text, whitespace collapsed."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", h or "")).split())


class Fixtures:
    """Every document, every view call and one node run for the whole module."""
    _R = None

    @classmethod
    def build(cls):
        docs, ops = {}, []

        def op(k, fn, *args):
            ops.append({"k": k, "fn": fn, "args": list(args)})

        def analyze(k, coin, decision, now=NOW, price=100.5, d1=None, legacy=None):
            src = legacy_sources(legacy, {"$doc": decision}, coin) if legacy else {"decision": {"$doc": decision}}
            ops.append({"k": k, "analyze": {"coin": coin, "price": price, "d1": candles() if d1 is None else d1, "now": now,
                                            "src": src}})

        mx = mixed()
        docs["mixed"] = mx
        docs["zero"] = mixed(signals={"LO": [P.sig("TSMOM", kind="ACTIVE")], "NEG": [P.sig("DIS")]})
        docs["nosignal"] = mixed(signals={})
        docs["seven"] = seven()
        docs["breach"] = DE.build(P.snapshot([P.rec("HI")], {"HI": [P.sig("REQ")]}, book=BIG + [BLOCKED]))
        docs["within"] = mixed(book=SMALL)
        docs["uneval"] = mixed(pf=None)
        docs["funding"] = funding_doc()
        docs["degraded"] = mixed(prov={"fallback_universe": True})
        docs["none"] = None
        docs["evil"] = evil(mixed())
        ev_trace = next(c for c in docs["evil"]["candidates"] if c["type"] == DE.EMERGING)
        ev_trace["trace"][0]["rule"] = "<script>alert(3)</script> rule & 'quote'"
        ev_trace["trace"][0]["effect"] = '<img src=y onerror="alert(4)"> effect'
        # tampered copies: ineligible, duplicated, mislabelled and excess section items; a degraded funding leg
        hi, lo, neg = cand_id(mx, "HI"), cand_id(mx, "LO"), cand_id(mx, "NEG")
        t = copy.deepcopy(mx)
        t["best_trades_now"]["items"] += [{"rank": 2, "id": lo, "asset": "LO", "state": "WATCH"},
                                          {"rank": 3, "id": neg, "asset": "NEG", "state": "AVOID"},
                                          {"rank": 4, "id": lo, "asset": "LO", "state": "TRADE"},
                                          {"rank": 5, "id": hi, "asset": "HI", "state": "TRADE"},
                                          {"rank": 6, "id": "DIRECTIONAL_STRATEGY:GHOST:REQ:LONG", "asset": "GHOST", "state": "TRADE"}]
        t["emerging_opportunities"]["items"].append({"rank": 3, "id": neg, "asset": "NEG", "state": "AVOID"})
        docs["tampered"] = t
        t = copy.deepcopy(mx)                       # the file itself claims WATCH is eligible for Best trades now
        t["best_trades_now"]["selection_trace"]["eligible_states"] = ["TRADE", "WATCH"]
        t["best_trades_now"]["items"].append({"rank": 2, "id": lo, "asset": "LO", "state": "WATCH"})
        docs["eligibleWatch"] = t
        t = copy.deepcopy(docs["seven"])
        t["best_trades_now"]["items"] += [{"rank": 6 + k, "id": i, "asset": i.split(":")[1], "state": "TRADE"}
                                          for k, i in enumerate(t["best_trades_now"]["selection_trace"]["excluded_after_cutoff"])]
        docs["sevenTampered"] = t
        t = copy.deepcopy(mx)
        tw = next(c for c in t["candidates"] if c["type"] == DE.FUNDING)
        tw["legs"]["short"]["health"] = "STALE"
        docs["degradedLeg"] = t
        # validity: an old as_of with a current valid_until, and a TRADE whose own horizon has passed
        t = copy.deepcopy(mx)
        t["as_of"] = NOW - 30 * DAY
        docs["oldButValid"] = t
        t = copy.deepcopy(mx)
        next(c for c in t["candidates"] if c["id"] == hi)["valid_until"] = NOW - 1
        docs["tradeLapsed"] = t

        vu = mx["valid_until"]
        for name in ("mixed", "zero", "nosignal", "seven", "breach", "within", "uneval", "funding", "degraded", "none", "evil",
                     "tampered", "eligibleWatch", "sevenTampered", "degradedLeg", "oldButValid", "tradeLapsed"):
            d = {"$doc": name}
            op("today:" + name, "D.views.today", d, NOW)
            op("funding:" + name, "D.views.funding", d, NOW)
            op("portfolio:" + name, "D.views.portfolio", d, NOW, None, "unavailable")
        op("today:malformed", "D.views.today", "MALFORMED", NOW)
        op("today:schema", "D.views.today", dict(mx, schema="v8.decision/0"), NOW)
        for k, now in (("at", vu), ("after", vu + 1), ("long", vu + 30 * DAY)):
            op("today:stale:" + k, "D.views.today", {"$doc": "mixed"}, now)
            op("funding:stale:" + k, "D.views.funding", {"$doc": "mixed"}, now)
            op("portfolio:stale:" + k, "D.views.portfolio", {"$doc": "mixed"}, now, None, "unavailable")
            op("authority:stale:" + k, "D.authority", {"$doc": "mixed"}, now)
        op("authority:oldButValid", "D.authority", {"$doc": "oldButValid"}, NOW)
        for name in ("mixed", "funding", "evil", "degradedLeg"):
            op("market:" + name, "D.views.fundingMarket", {"$doc": name}, {"sort": "asset", "shown": 400, "open": True})
        # portfolio detail bound to the same evaluation, and an audit of another evaluation
        docs["breachAudit"] = {"portfolio_risk": PR.evaluate(P.portfolio(BIG + [BLOCKED]))}
        docs["withinAudit"] = {"portfolio_risk": PR.evaluate(P.portfolio(SMALL))}
        op("portfolio:breach:detail", "D.views.portfolio", {"$doc": "breach"}, NOW, {"$doc": "breachAudit"}, "loaded")
        op("portfolio:within:detail", "D.views.portfolio", {"$doc": "within"}, NOW, {"$doc": "withinAudit"}, "loaded")
        op("portfolio:within:foreign", "D.views.portfolio", {"$doc": "within"}, NOW, {"$doc": "breachAudit"}, "loaded")
        op("portfolio:within:loading", "D.views.portfolio", {"$doc": "within"}, NOW, None, "loading")
        # every candidate's trace, as the trace disclosure renders it
        for name in ("mixed", "breach", "funding", "evil"):
            for c in docs[name]["candidates"]:
                op("trace:" + name + ":" + c["id"], "D.html.traceTable", {"$cand": [name, c["id"]]}, {"$doc": name})
        # the Analyzer: every asset of the mixed decision, each failure of the authority, and the legacy sources
        for coin in ("HI", "LO", "NEG", "ALPHA", "TWIN", "ZZZ"):
            analyze("an:mixed:" + coin, coin, "mixed")
        for name in ("none", "seven", "breach", "uneval", "evil", "tradeLapsed"):
            for coin in sorted({c["asset"] for c in (docs[name] or {"candidates": []})["candidates"]} | {"HI"}):
                analyze("an:" + name + ":" + coin, coin, name)
        analyze("an:stale:HI", "HI", "mixed", now=vu + 1)
        analyze("an:malformed:HI", "HI", "eligibleWatch")      # a valid document: the panel stays truthful anyway
        for side in ("long", "short"):
            analyze("an:legacyWatch:" + side, "LO", "mixed", legacy=side)
            analyze("an:legacyAvoid:" + side, "NEG", "mixed", legacy=side)
            analyze("an:legacyNone:" + side, "LO", "none", legacy=side)
            analyze("an:legacyStale:" + side, "LO", "mixed", now=vu + 1, legacy=side)
            analyze("an:legacyZero:" + side, "LO", "zero", legacy=side)
        analyze("an:noPrice:HI", "HI", "mixed", price=None, d1=[])
        analyze("an:noPrice:LO", "LO", "mixed", price=0, d1=[], legacy="long")
        # Research: the committed Phase 9 record, a tampered one and a missing one
        rd = ROOT / "research" / "phase9"
        S = {"sum": json.loads((rd / "research_phase9_summary.json").read_text()),
             "mt": json.loads((rd / "research_multiple_testing.json").read_text()),
             "mc": json.loads((rd / "research_matched_controls.json").read_text()),
             "reg": json.loads((rd / "research_phase9_registration_plan.json").read_text()),
             "adj": json.loads((rd / "research_strategy_adjudication.json").read_text()), "dash": None}
        op("research:real", "D.views.research", S)
        T = copy.deepcopy(S)
        for x in T["sum"]["strategies"]:
            if x["deployment_state"] == "LEGACY_HOLDOVER":
                x["research_state"] = "REQUALIFIED"         # research says requalified; the runtime does not
        op("research:holdoverResearch", "D.views.research", T)
        op("research:missing", "D.views.research", {"sum": None})
        op("research:noOptional", "D.views.research", {"sum": S["sum"]})
        cls.docs, cls.S = docs, S
        with tempfile.TemporaryDirectory() as tmp:
            fx, js = os.path.join(tmp, "fx.json"), os.path.join(tmp, "run.js")
            with open(fx, "w") as fh:
                json.dump({"docs": docs, "ops": ops}, fh, allow_nan=False)
            with open(js, "w") as fh:
                fh.write(RUNNER)
            out = subprocess.run([NODE, js, str(ROOT / "desk.js"), str(ROOT / "analyze.js"), fx],
                                 capture_output=True, text=True, timeout=300)
        if out.returncode != 0:
            raise AssertionError("node failed: " + out.stderr[-4000:])
        R = json.loads(out.stdout)
        errors = {k: v["__error"] for k, v in R.items() if isinstance(v, dict) and "__error" in v}
        if errors:
            raise AssertionError("a view threw: " + json.dumps(errors)[:4000])
        cls._R = R
        return R

    @classmethod
    def get(cls):
        return cls._R if cls._R is not None else cls.build()


def everything(v):
    """Every HTML string a view returned, joined."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return "\n".join(everything(x) for x in v.values())
    if isinstance(v, list):
        return "\n".join(everything(x) for x in v)
    return ""


@unittest.skipUnless(NODE, "node is not installed")
class Adversarial(unittest.TestCase):
    """The fifteen adversarial frontend checks of the Phase 12 brief."""

    @classmethod
    def setUpClass(cls):
        cls.R = Fixtures.get()
        cls.D = Fixtures.docs
        cls.S = Fixtures.S
        cls.state = {name: {c["id"]: c["state"] for c in d["candidates"]} for name, d in cls.D.items()
                     if isinstance(d, dict) and "candidates" in d}

    def assert_truthful(self, name, h):
        """Every card shows its own candidate's engine state: the class, the data-state and the chip agree with it, a
        direction is shown as a call only on a TRADE."""
        view = {"TRADE": ("is-trade", "st-trade", "Trade"), "WATCH": ("is-watch", "st-watch", "Watch"),
                "AVOID": ("is-avoid", "st-avoid", "Avoid")}
        for c in cards(h):
            want = self.state[name][c["id"]]
            self.assertEqual(c["state"], want, c["id"])
            cls_, chip_cls, label = view[want]
            self.assertEqual(c["cls"], cls_, c["id"])
            self.assertEqual(top_chip(c), (chip_cls, label), c["id"])
            if want != "TRADE":
                self.assertNotIn('class="dir dir-', c["body"], "a direction is a call only on a TRADE: " + c["id"])
        return cards(h)

    def best(self, name):
        return cards(self.R["today:" + name]["best"])

    def test_01_watch_cannot_visually_become_a_trade(self):
        R, mx = self.R, self.D["mixed"]
        lo = cand_id(mx, "LO")
        self.assertEqual(self.state["mixed"][lo], DE.WATCH)
        for name in ("mixed", "zero", "seven", "tampered", "eligibleWatch", "within", "uneval"):
            v = R["today:" + name]
            for region in ("best", "emerging"):
                self.assert_truthful(name, v[region])
            self.assertEqual({c["state"] for c in self.best(name)} - {"TRADE"}, set(), name)
        # the WATCH card itself: Watch chip, no direction tag, "long signal, not a call", what needs to change
        card = next(c for c in cards(R["an:mixed:LO"]["panel"]["html"]) if c["id"] == lo)
        self.assertEqual(top_chip(card), ("st-watch", "Watch"))
        self.assertIn("long signal, not a call", card["body"])
        self.assertIn("What needs to change", card["body"])
        self.assertIn("STRATEGY_AUTHORITY", json.dumps(next(c for c in mx["candidates"] if c["id"] == lo)["explanation"]))
        # a tampered file: WATCH and AVOID items, a mislabelled duplicate and a missing candidate are never shown
        t = R["today:tampered"]
        self.assertEqual([c["id"] for c in cards(t["best"])], [cand_id(mx, "HI")])
        self.assertIn("5 items in this section were not shown", text(t["best"]))
        # even when the file claims WATCH is eligible there, Best trades now shows only TRADE
        self.assertEqual([c["id"] for c in cards(R["today:eligibleWatch"]["best"])], [cand_id(mx, "HI")])
        self.assertIn("1 item in this section was not shown", text(R["today:eligibleWatch"]["best"]))
        # the Analyzer's call on a WATCH: no side, no plan
        c = R["an:mixed:LO"]["call"]
        self.assertEqual((c["verdict"], c["side"], c["tier"], c["plan"]), ("WATCH", None, None, None))

    def test_02_avoid_cannot_visually_become_watch_or_trade(self):
        R, mx = self.R, self.D["mixed"]
        neg = cand_id(mx, "NEG")
        self.assertEqual(self.state["mixed"][neg], DE.AVOID)
        for name in ("mixed", "tampered", "breach", "zero"):
            v = R["today:" + name]
            shown = [c["id"] for region in ("best", "emerging") for c in self.assert_truthful(name, v[region])]
            self.assertNotIn(neg, shown, "an AVOID is summarised, never a Today card")
            self.assertTrue(all(self.state[name][i] != DE.AVOID for i in shown), name)
        self.assertIn("1 item in this section was not shown", text(R["today:tampered"]["emerging"]))
        # the AVOID card where it is shown (the Analyzer): Avoid chip, the engine's step and code, no direction
        card = next(c for c in cards(R["an:mixed:NEG"]["panel"]["html"]) if c["id"] == neg)
        self.assertEqual((card["cls"], top_chip(card)), ("is-avoid", ("st-avoid", "Avoid")))
        self.assertIn("Rejected at Strategy authority: strategy disabled", text(card["body"]))
        self.assertNotIn('class="dir dir-', card["body"])
        # Today summarises AVOID by the engine's step and code
        av = text(R["today:mixed"]["avoided"])
        self.assertIn("Strategy authority", av)
        self.assertIn("STRATEGY_DISABLED", av)
        self.assertEqual(R["today:mixed"]["avN"], "1 evaluated as Avoid")
        c = R["an:mixed:NEG"]["call"]
        self.assertEqual((c["verdict"], c["side"], c["plan"]), ("AVOID", None, None))

    def test_03_stale_decision_cannot_appear_actionable(self):
        R = self.R
        self.assertEqual(R["authority:stale:at"]["status"], "AVAILABLE", "valid until the second it says")
        for k in ("after", "long"):
            self.assertEqual(R["authority:stale:" + k]["status"], "STALE")
            for view in ("today", "funding", "portfolio"):
                v = R[view + ":stale:" + k]
                h = everything(v)
                self.assertEqual(cards(h), [], view)
                self.assertTrue(v["statusBad"], view)
                self.assertIn("Decision expired — waiting for the next governed scan.", text(h), view)
                self.assertNotIn("st-trade", h, view)
        a = R["an:stale:HI"]
        self.assertEqual((a["call"]["status"], a["call"]["verdict"], a["call"]["plan"]), ("STALE", "WAIT", None))
        self.assertEqual(cards(a["panel"]["html"]), [])
        self.assertIn("st-unavail", a["panel"]["html"])
        # a TRADE past its own valid_until inside a still-current document: not shown, not a call, said so
        t = R["today:tradeLapsed"]
        self.assertEqual(cards(t["best"]), [])
        self.assertIn("Decision expired — waiting for the next governed scan.", text(t["best"]))
        chip = re.search(r'<span class="chip st-trade([^"]*)"><span class="chip-mark" aria-hidden="true">[^<]*</span>Trade 1</span>', t["statusHtml"])
        self.assertIn("chip-quiet", chip.group(1), "the file's TRADE count is not loud when no current trade is on screen")
        live = re.search(r'<span class="chip st-trade([^"]*)"><span class="chip-mark" aria-hidden="true">[^<]*</span>Trade 1</span>', R["today:mixed"]["statusHtml"])
        self.assertNotIn("chip-quiet", live.group(1))
        a = R["an:tradeLapsed:HI"]
        self.assertEqual((a["call"]["status"], a["call"]["verdict"], a["call"]["plan"]), ("STALE", "WAIT", None))
        self.assertEqual(cards(a["panel"]["html"]), [])
        self.assertIn("Decision expired — waiting for the next governed scan.", text(a["panel"]["html"]))

    def test_04_missing_decision_cannot_fall_back_to_legacy(self):
        R = self.R
        for name in ("none", "malformed", "schema"):
            v = R["today:" + name]
            self.assertEqual(cards(everything(v)), [], name)
            self.assertTrue(v["statusBad"], name)
            self.assertIn("nothing on the desk is actionable", text(v["best"]), name)
        for side in ("long", "short"):
            a = R["an:legacyNone:" + side]
            self.assertEqual((a["call"]["status"], a["call"]["verdict"], a["call"]["side"], a["call"]["plan"]),
                             ("MISSING", "WAIT", None, None))
            self.assertEqual({s[0] for s in a["call"]["signals"]}, {"swing", "smart", "quant"}, "the legacy sources are loaded")
            self.assertIn("does not fall back to the legacy signals", a["call"]["headline"])
            self.assertEqual(cards(a["panel"]["html"]), [])
            self.assertIn("st-unavail", a["panel"]["html"])
            self.assertNotIn('class="dir dir-', a["panel"]["html"])

    def test_05_swing_proven_cannot_create_a_trade(self):
        self._legacy_cannot_trade("swing")

    def test_06_smart_money_proven_cannot_create_a_trade(self):
        self._legacy_cannot_trade("smart")

    def _legacy_cannot_trade(self, src):
        R = self.R
        for side in ("long", "short"):
            for case, verdict, state in (("legacyWatch", "WATCH", "WATCH"), ("legacyAvoid", "AVOID", "AVOID"),
                                         ("legacyZero", "WATCH", "WATCH"), ("legacyStale", "WAIT", None),
                                         ("legacyNone", "WAIT", None)):
                with self.subTest(case=case, side=side):
                    a = R[f"an:{case}:{side}"]
                    sig = [s for s in a["call"]["signals"] if s[0] == src]
                    self.assertEqual(len(sig), 1)
                    self.assertEqual(sig[0][1], side)
                    if src == "swing":
                        self.assertEqual(sig[0][2], "Unqualified historical result", "positive history does not prove governed authority")
                    self.assertEqual((a["call"]["verdict"], a["call"]["side"], a["call"]["tier"], a["call"]["plan"]),
                                     (verdict, None, None, None))
                    self.assertEqual(a["panel"]["state"], state)
                    self.assertNotIn("st-trade", a["panel"]["html"])
                    self.assertNotIn('class="dir dir-', a["panel"]["html"])

    def test_07_legacy_holdover_never_looks_requalified(self):
        R = self.R
        real = R["research:real"]
        holdovers = [x["strategy_id"] for x in self.S["sum"]["strategies"] if x["deployment_state"] == "LEGACY_HOLDOVER"]
        self.assertTrue(holdovers)
        for h in (real, R["research:holdoverResearch"]):
            rows = dict(re.findall(r"<tr class=\"[^\"]*\"><td>([^<]+)</td>(.*?)</tr>", h, re.S))
            for sid in holdovers:
                self.assertIn("Legacy holdover", rows[sid], sid)
                self.assertIn("No: watch at most", rows[sid], sid)
                self.assertNotIn("Eligible", rows[sid], sid)
            self.assertNotIn("st-trade", h, "no strategy is shown as able to trade")
        t = text(real)
        self.assertIn("0 of 24", t)
        self.assertIn("Incomplete", t)
        self.assertIn("≥ 199", t)
        # on Today and in the Analyzer a holdover signal is a WATCH capped by strategy authority
        lo = cand_id(self.D["mixed"], "LO")
        card = next(c for c in cards(R["today:zero"]["best"] + R["an:mixed:LO"]["panel"]["html"]) if c["id"] == lo)
        self.assertEqual(top_chip(card), ("st-watch", "Watch"))
        self.assertIn("strategy authority insufficient", text(card["body"]))
        z = text(R["today:zero"]["best"])
        self.assertIn("Capped: strategy authority insufficient", z)

    def test_08_portfolio_state_is_shown_truthfully(self):
        R, D = self.R, self.D
        self.assertEqual(D["breach"]["portfolio"]["phase10"]["state"], PR.BREACHED)
        self.assertEqual(D["within"]["portfolio"]["phase10"]["state"], PR.WITHIN)
        self.assertEqual(D["uneval"]["portfolio"]["phase10"]["state"], PR.UNEVALUABLE)
        b = R["today:breach"]
        self.assertIn("pf-breach", b["pf"])
        self.assertIn("Portfolio limits exceeded — a new directional trade is rejected", text(b["pf"]))
        self.assertIn("Limits breached", text(b["pf"]))
        line = re.search(r"Breached:\s*(.*?)\.", text(b["pf"]))
        self.assertIsNotNone(line, "Today names the breached limits")
        self.assertEqual(len(line.group(1).split(", ")), len(D["breach"]["portfolio"]["phase10"]["breached"]))
        self.assertIn("Executable risk", line.group(1))
        self.assertIn("Portfolio limits are currently breached.", text(b["best"]))
        self.assertIn("1 of 1 signals were rejected because the portfolio would still breach a limit", text(b["best"]))
        self.assertIn("pf-breach", b["statusHtml"])
        p = R["portfolio:breach"]
        self.assertIn("Breached:", text(p["body"]))
        self.assertIn("A new directional trade is rejected", text(p["body"]))
        for name, cls, label in (("within", "pf-ok", "Within limits"), ("uneval", "pf-unknown", "Cannot evaluate")):
            v = R["today:" + name]
            self.assertIn(cls, v["pf"], name)
            self.assertIn(label, text(v["pf"]), name)
            self.assertNotIn("pf-breach", v["pf"] + v["statusHtml"] + R["portfolio:" + name]["body"], name)
            self.assertNotIn("Breached:", text(R["portfolio:" + name]["body"]), name)
        self.assertIn("Missing authority keeps the state unevaluable", text(R["portfolio:uneval"]["body"]))
        # stress is deterministic, never a probability or value-at-risk claim
        for name in ("breach", "within"):
            t = text(R["portfolio:" + name]["body"])
            self.assertIn("not probabilities, value-at-risk or expected losses", t)
        # the bound detail: the identity-blocked position is distinguished and still counted
        for name in ("breach", "within"):
            h = R[f"portfolio:{name}:detail"]["body"]
            rows = re.findall(r'<tr class="([^"]*)" data-actionability="([^"]*)">', h)
            self.assertIn(("blocked", "IDENTITY_BLOCKED"), rows, name)
            self.assertTrue(all((c == "blocked") == (a != "ACTIONABLE") for c, a in rows), name)
            self.assertIn("1 identity-blocked (still counted in every risk figure above)", text(h), name)
        # an audit of another evaluation is never shown as this decision's detail
        f = text(R["portfolio:within:foreign"]["body"])
        self.assertIn("belongs to a different evaluation", f)
        self.assertNotIn("identity-blocked (still counted", f)
        self.assertIn("Loading position detail", text(R["portfolio:within:loading"]["body"]))

    def test_09_zero_trade_shows_no_fallback_cards(self):
        R = self.R
        for name in ("zero", "nosignal", "breach", "uneval", "degraded", "funding"):
            with self.subTest(doc=name):
                d = self.D[name]
                self.assertEqual(d["best_trades_now"]["count"], 0)
                v = R["today:" + name]
                self.assertEqual(cards(v["best"]), [])
                self.assertIn("No trade currently clears every desk gate.", text(v["best"]))
                self.assertEqual(v["bestN"], "0 of up to 5")
        # the reasons are counted from the document's own codes
        z = text(R["today:zero"]["best"])
        self.assertIn("2 current strategy signals, none trade-ready", z)
        self.assertIn("STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT", z)
        self.assertIn("Rejected at Strategy authority: strategy disabled", z)
        self.assertIn("No governed strategy has a current signal", text(R["today:nosignal"]["best"]))
        # degradation is distinguished from no opportunity
        self.assertIn("fallback universe", text(R["today:degraded"]["sys"]))
        self.assertIn("fallback universe", text(R["today:degraded"]["statusHtml"]))
        self.assertIn("No unavailable venue or degraded discovery", text(R["today:zero"]["sys"]))

    def test_10_decision_trace_is_rendered_verbatim(self):
        R = self.R
        cell = lambda cls, h: [html.unescape(x) for x in re.findall(r'<span class="' + cls + r'" role="cell"><span class="tlbl">[^<]*</span>(.*?)</span>(?=<span class="t|</div>)', h, re.S)]
        n = 0
        for name in ("mixed", "breach", "funding", "evil"):
            for c in self.D[name]["candidates"]:
                h = R["trace:" + name + ":" + c["id"]]
                entries = [g for g in c["trace"] + (c["placement"] or {}).get("trace", []) if isinstance(g, dict)]
                rows = re.findall(r'<div class="trow (r-\w+)" role="row">', h)
                self.assertEqual(len(rows), len(entries), c["id"])
                self.assertEqual(cell("trule", h), [str(g["rule"]) for g in entries], c["id"])
                self.assertEqual(cell("teff", h), [str(g["effect"]) for g in entries], c["id"])
                labels = {"PASS": "Pass", "CAP": "Watch cap", "MISSING": "Missing", "FAIL": "Fail", "INFO": "Info",
                          "NOT_APPLICABLE": "Not applicable"}
                res = re.findall(r'<span class="res r-\w+"><span aria-hidden="true">[^<]*</span> ([^<]*)</span>', h)
                self.assertEqual(res, [labels.get(g["result"], g["result"]) for g in entries], c["id"])
                self.assertEqual(re.findall(r"<code>([^<]*)</code></small>", h), [g["code"] for g in entries if g.get("code")], c["id"])
                self.assertIn(html.escape(c["id"], quote=True).replace("&#x27;", "&#39;"), h)
                n += 1
        self.assertGreaterEqual(n, 15)

    def test_11_degraded_funding_legs_never_appear_qualified(self):
        R, d = self.R, self.D["funding"]
        legs = {c["id"]: c["health"] for c in [*pair("HI"), *pair("TWIN"), *pair("LO", -0.002, 0.002)]}
        q = R["funding:funding"]["qualified"]
        shown = cards(q)
        self.assertEqual(sorted(c["id"] for c in shown), sorted(i["id"] for i in d["funding_opportunities"]["items"]))
        self.assertEqual({c["id"] for c in shown}, {"FUNDING_SPREAD:HI", "FUNDING_SPREAD:LO"})
        for c in shown:
            self.assertEqual(top_chip(c), ("st-watch", "Watch"))
            venues = re.findall(r"<tr><td>(?:Long|Short)</td><td>([^<]*)</td>", c["body"])
            self.assertEqual(sorted(venues), ["hyperliquid", "lighter"], c["id"])
            self.assertEqual(re.findall(r"<td>(HEALTHY|STALE|DEGRADED|ERROR)</td>", c["body"]), ["HEALTHY", "HEALTHY"])
            self.assertIn("Not risk-free.", text(c["body"]))
        self.assertNotIn("aster", q + R["market:funding"]["html"], "a degraded venue is never a leg")
        self.assertNotIn("TWIN", q, "one healthy and one degraded leg is no spread")
        # a tampered file with a degraded leg on the qualified spread: the item is not shown
        t = R["funding:degradedLeg"]
        self.assertEqual(cards(t["qualified"]), [])
        self.assertIn("1 item in this section was not shown", text(t["qualified"]))
        self.assertNotIn("FUNDING_SPREAD:TWIN", R["market:degradedLeg"]["html"])
        self.assertEqual(cards(R["today:degradedLeg"]["fund"]), [])
        self.assertNotIn("TWIN", text(R["today:degradedLeg"]["fund"]).split("evaluated this scan")[0])
        self.assertEqual(self.D["breach"]["funding_opportunities"]["count"], 0)
        self.assertIn("No funding spread currently clears the desk's qualification gates.", text(R["funding:breach"]["qualified"]))
        self.assertIn("No funding spread currently clears the desk's qualification gates.", text(R["today:breach"]["fund"]))

    def test_12_top_five_never_exceeds_five(self):
        R, d = self.R, self.D["seven"]
        self.assertEqual(d["market_summary"]["opportunity_states"]["TRADE"], 7)
        self.assertEqual(d["best_trades_now"]["count"], 5)
        for name in ("seven", "sevenTampered"):
            v = R["today:" + name]
            shown = cards(v["best"])
            self.assertEqual(len(shown), 5, name)
            self.assertEqual([c["id"] for c in shown], [i["id"] for i in d["best_trades_now"]["items"]], name)
            self.assertEqual(v["bestN"], "5 of up to 5")
        self.assertIn("More trades qualify than the section shows (at most five)", text(R["today:seven"]["best"]))
        self.assertIn("a fresher signal", text(R["today:seven"]["best"]))
        for name, d_ in self.D.items():
            if isinstance(d_, dict) and "candidates" in d_ and "today:" + name in R:
                v = R["today:" + name]
                self.assertLessEqual(len(cards(v["best"])), 5, name)
                self.assertLessEqual(len(cards(v["emerging"])), 5, name)
                self.assertLessEqual(len(cards(R["funding:" + name]["qualified"])), 5, name)

    def test_13_analyzer_and_today_show_the_same_state(self):
        R = self.R
        for name in ("mixed", "seven", "breach", "within", "uneval", "evil"):
            d = self.D[name]
            today = {c["id"]: c["state"] for region in ("best", "emerging") for c in cards(R["today:" + name][region])}
            today.update({c["id"]: c["state"] for c in cards(R["funding:" + name]["qualified"])})
            for asset in sorted({c["asset"] for c in d["candidates"]}):
                key = f"an:{name}:{asset}"
                if key not in R:
                    continue
                panel = {c["id"]: c["state"] for c in cards(R[key]["panel"]["html"])}
                rec = next((a for a in d["assets"] if a["asset"] == asset), None)
                self.assertEqual(R[key]["panel"]["state"], rec["state"] if rec else "NONE", key)
                for cid, st in panel.items():
                    self.assertEqual(st, self.state[name][cid], key)
                    if cid in today:
                        self.assertEqual(st, today[cid], key)
                # the Analyzer's verdict follows the same object
                c = R[key]["call"]
                dirs = [x["state"] for x in d["candidates"] if x["asset"] == asset and x["type"] == DE.DIRECTIONAL]
                if DE.TRADE in dirs:
                    self.assertIn(c["verdict"], ("LONG", "SHORT"), key)
                elif dirs:
                    self.assertEqual(c["verdict"], min(dirs, key=["TRADE", "WATCH", "AVOID"].index), key)
                else:
                    self.assertEqual(c["verdict"], "WAIT", key)
        hi = R["an:mixed:HI"]
        self.assertEqual((hi["call"]["verdict"], hi["call"]["side"], hi["call"]["tier"]), ("LONG", "long", "TRADE"))
        card = cards(hi["panel"]["html"])[0]
        self.assertEqual((card["cls"], top_chip(card)), ("is-trade", ("st-trade", "Trade")))
        self.assertIn('class="dir dir-long"', card["body"])
        why = next(x["rule"] for x in next(c for c in self.D["mixed"]["candidates"] if c["state"] == "TRADE")["explanation"]["why_trade"]
                   if x["step"] == "STRATEGY_AUTHORITY")
        self.assertIn("All required desk gates currently pass.", text(card["body"]))
        self.assertIn("Strategy authority: " + why, text(card["body"]), "the qualification is the engine's own rule")
        self.assertIn("outside the desk's governed discovery", text(R["an:mixed:ZZZ"]["panel"]["html"]))
        self.assertEqual(R["an:mixed:ZZZ"]["panel"]["state"], "NONE")

    def test_14_valid_until_fails_closed_without_a_local_ttl(self):
        R = self.R
        # an old decision that says it is still valid is shown (no age limit of the desk's own) ...
        self.assertEqual(R["authority:oldButValid"]["status"], "AVAILABLE")
        self.assertEqual(len(cards(R["today:oldButValid"]["best"])), 1)
        # ... and a decision expires at its own valid_until, to the second, however recent its as_of
        self.assertEqual(R["authority:stale:at"]["status"], "AVAILABLE")
        self.assertEqual(R["authority:stale:after"]["status"], "STALE")
        for page in ("desk.js", "today.html", "funding.html", "portfolio.html", "research.html", "analyze.html", "analyze.js"):
            src = (ROOT / page).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\b(TTL|MAX_AGE|maxAge|STALE_AFTER|staleAfter)\s*[=:]", src), page)
            self.assertIsNone(re.search(r"as_of\s*\+\s*\d", src), page + " adds its own horizon to as_of")
        core = (ROOT / "desk.js").read_text(encoding="utf-8")
        auth = core[core.index("function authority(doc, now)"):core.index("function candidateOk")]
        self.assertIn("now <= doc.valid_until", auth)
        self.assertNotIn("as_of +", auth)

    def test_15_optional_external_failure_keeps_the_core_decision(self):
        R = self.R
        # no live price and no candles: the decision panel is unchanged, the TRADE stays a TRADE without a guessed plan
        a, b = R["an:noPrice:HI"], R["an:mixed:HI"]
        self.assertEqual(a["panel"], b["panel"])
        self.assertEqual((a["call"]["verdict"], a["call"]["side"], a["call"]["plan"]), ("LONG", "long", b["call"]["plan"]))
        lo = R["an:noPrice:LO"]
        self.assertEqual((lo["call"]["verdict"], lo["call"]["plan"]), ("WATCH", None))
        self.assertTrue(all(s[3] is None for s in lo["call"]["signals"]), "no levels are guessed without a price")
        # the audit snapshot (position detail) unavailable: the governed summary still renders
        for state in ("unavailable", "loading"):
            v = R["portfolio:within"] if state == "unavailable" else R["portfolio:within:loading"]
            self.assertIn("Within limits", text(v["body"]))
            self.assertIn("Limits", text(v["body"]))
            self.assertFalse(v["statusBad"])
        self.assertIn("Position detail is unavailable", text(R["portfolio:within"]["body"]))
        # the optional research files missing: the governed summary still renders; the record missing fails closed
        self.assertIn("0 of 24", text(R["research:noOptional"]))
        self.assertIn("did not load", text(R["research:missing"]))
        self.assertIn("still gates every decision", text(R["research:missing"]))
        # the Analyzer page renders the decision before it loads candles, and a chart failure says the decision stands
        page = (ROOT / "analyze.html").read_text(encoding="utf-8")
        run = page[page.index("async function run("):]
        self.assertLess(run.index("renderDecision()"), run.index("await TA.load(coin)"))
        self.assertIn("The desk decision above does not depend on it.", page)


@unittest.skipUnless(NODE, "node is not installed")
class Escaping(unittest.TestCase):
    """Strings from the artifact are untrusted: every view escapes them."""

    def test_hostile_strings_are_escaped_everywhere(self):
        R = Fixtures.get()
        keys = [k for k in R if k.endswith(":evil") or k.startswith("trace:evil:") or k.startswith("an:evil:")]
        self.assertGreater(len(keys), 8)
        seen = False
        for k in keys:
            h = everything(R[k]["panel"] if k.startswith("an:") else R[k])     # the call's text is escaped where it is shown
            for bad in ("<img", "<script", 'onerror="alert', 'AL"><'):
                self.assertNotIn(bad, h, k)
            seen = seen or "&lt;img src=x onerror=alert(1)&gt;" in h
        self.assertTrue(seen, "the hostile asset name is shown, escaped")
        tr = everything({k: R[k] for k in keys if k.startswith("trace:evil:EMERGING")})
        self.assertIn("&lt;script&gt;alert(3)&lt;/script&gt; rule &amp; &#39;quote&#39;", tr)
        self.assertIn("&lt;img src=y onerror=&quot;alert(4)&quot;&gt; effect", tr)

    def test_no_raw_html_insertion_of_artifact_strings(self):
        # the page binders insert only the views' escaped HTML and their own constants; analyze.html escapes with esc()
        for page in ("today.html", "funding.html", "portfolio.html", "research.html"):
            src = (ROOT / page).read_text(encoding="utf-8")
            script = src[src.rindex("<script>"):]
            for m in re.finditer(r"\.innerHTML\s*=\s*([^;]+);", script):
                rhs = m.group(1)
                self.assertTrue(re.match(r"\s*(v\.|D\.views\.|D\.html\.|'<)", rhs), page + ": " + rhs)
        self.assertIn("const esc = (s) =>", (ROOT / "analyze.html").read_text(encoding="utf-8"))


class StaticContract(unittest.TestCase):
    """The pages, their navigation, their copy and the published file set."""

    def test_navigation_is_exactly_the_five_surfaces(self):
        for page in DESK_PAGES + LEGACY_PAGES:
            src = (ROOT / page).read_text(encoding="utf-8")
            nav = re.search(r'<nav class="apptabs"[^>]*>(.*?)</nav>', src, re.S)
            self.assertIsNotNone(nav, page)
            links = re.findall(r'<a href="([^"]+)"( aria-current="page")?>([^<]+)</a>', nav.group(1))
            self.assertEqual([(h, t) for h, _, t in links], NAV, page)
            current = [t for _, c, t in links if c]
            if page in DESK_PAGES:
                want = {"today.html": "Today", "analyze.html": "Analyzer", "funding.html": "Funding",
                        "portfolio.html": "Portfolio", "research.html": "Research"}[page]
                self.assertEqual(current, [want], page)
            else:
                self.assertEqual(current, [], page + " is a diagnostic page, not a desk surface")
                self.assertIn("Diagnostic page.", src, page)
                self.assertIn("not desk decisions and are not trade-ready", src, page)

    def test_the_core_loads_before_every_page_script(self):
        for page in DESK_PAGES:
            src = (ROOT / page).read_text(encoding="utf-8")
            core = src.index('<script src="desk.js"></script>')
            self.assertEqual(src.count('<script src="desk.js"></script>'), 1, page)
            self.assertIn('<link rel="stylesheet" href="desk.css">', src, page)
            users = [m.start() for m in re.finditer(r"<script( src=\"analyze\.js\")?>(.*?)</script>", src, re.S)
                     if m.group(1) or "DESK" in m.group(2)]
            self.assertTrue(users, page)
            later = users
            self.assertTrue(all(i > core for i in later), page)
            self.assertIn('class="skip" href="#main"', src, page)
            self.assertIn('id="main"', src, page)
        an = (ROOT / "analyze.html").read_text(encoding="utf-8")
        self.assertLess(an.index('<script src="desk.js"></script>'), an.index('<script src="analyze.js"></script>'))

    def test_no_forbidden_or_overconfident_copy(self):
        forbidden = re.compile(r"guarantee[ds]?|risk[- ]free|\bcertain(ty)?\b|proven profit|guaranteed edge|sure thing|can't lose", re.I)
        negation = re.compile(r"(\bno|\bnot|\bnever|\bnone is|\bnot a)\s*(\w+\s*){0,2}$", re.I)
        for page in DESK_PAGES + ["desk.js"]:
            src = (ROOT / page).read_text(encoding="utf-8")
            for m in forbidden.finditer(src):
                before = re.sub(r"<[^>]+>", " ", src[max(0, m.start() - 40):m.start()])
                self.assertRegex(before, negation, f"{page}: {src[max(0, m.start() - 60):m.end() + 20]!r}")
        for page in DESK_PAGES + ["desk.js", "desk.css"]:
            src = (ROOT / page).read_text(encoding="utf-8").lower()
            for k in ("private_key", "privatekey", "api_secret", "apisecret", "mnemonic", "seed phrase", "walletconnect",
                      "eth_sendtransaction", "placeorder", "place_order", "/exchange"):
                self.assertNotIn(k, src, page)

    def test_the_core_decides_nothing(self):
        core = (ROOT / "desk.js").read_text(encoding="utf-8")
        for k in ("decision_policy.json", "portfolio_risk_policy", "quant_strategy_policy", "Math.random", "eval(", "new Function"):
            self.assertNotIn(k, core)
        # no threshold or score of its own: no comparison of a ranking input or gate input with a literal
        self.assertIsNone(re.search(r"(ranking_inputs|observed_value|net_carry|spread_8h|age_s)\s*[<>]=?\s*\d", core))
        self.assertNotIn("score", re.sub(r"//.*|/\*.*?\*/", "", core, flags=re.S).lower())
        # the Analyzer delegates its authority to the core
        an = (ROOT / "analyze.js").read_text(encoding="utf-8")
        self.assertIn("DESK.authority", an)
        self.assertIn("DESK.assetDecision(doc, coin, now)", an)

    def test_published_desk(self):
        import dashboard
        pages = dict(dashboard.DESK_PAGES)
        self.assertEqual(pages["today.html"], "index.html")
        for f in ("analyze.html", "analyze.js", "funding.html", "portfolio.html", "research.html", "desk.js", "desk.css"):
            self.assertEqual(pages[f], f)
        self.assertFalse((ROOT / "dashboard.html").exists(), "the old front page with legacy agreement calls is gone")
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            site.mkdir()
            dashboard.publish(str(site))
            idx = (site / "index.html").read_text(encoding="utf-8")
            self.assertIn("<title>Today · Perp Decision Desk</title>", idx)
            for f in ("desk.js", "desk.css", "funding.html", "portfolio.html", "research.html", "analyze.html", "analyze.js"):
                self.assertEqual((site / f).read_bytes(), (ROOT / f).read_bytes(), f)
            for f in ("research_phase9_summary.json", "research_strategy_adjudication.json", "research_multiple_testing.json",
                      "research_matched_controls.json", "research_phase9_registration_plan.json"):
                self.assertEqual((site / "data" / "v8" / "research" / "phase9" / f).read_bytes(),
                                 (ROOT / "research" / "phase9" / f).read_bytes(), f)

    def test_responsive_and_accessible_foundations(self):
        css = (ROOT / "desk.css").read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertRegex(css, r"@media \(max-width: ?\d+px\)")
        for page in DESK_PAGES:
            src = (ROOT / page).read_text(encoding="utf-8")
            self.assertIn('name="viewport" content="width=device-width, initial-scale=1"', src, page)
            self.assertIn('<html lang="en">', src, page)
            self.assertNotIn("user-scalable=no", src, page)


if __name__ == "__main__":
    unittest.main()
