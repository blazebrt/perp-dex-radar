"""Tests for the analyzer's call (analyze.js decide). v8 Phase 11: the call is governed by the Phase 11 decision
(data/v8/decision.json, v8.decision/1) alone. Run through node with synthetic scans and candles, and with decision
documents built by the real Python engine (v8/decision.py). Run from the repository root:

    python -m unittest discover -s tests -v

Skipped when node is not installed.

AnalyzerCall: the legacy sources are context only. Without a decision every coin is a wait; each legacy signal keeps
its own levels (a ready swing score: stop 2 daily ATR from the open, 3 ATR trailing stop, 30 days; a quant desk
position at its own stop; a smart-money short at its paper trade's stop), never sized; identity-blocked legacy
signals are notes; prices quoted per 1,000 coins line up; signalCoins never lists a coin from legacy signals.

Phase11Authority: only a current Phase 11 TRADE makes LONG or SHORT, in its own direction, with a plan sized at the
chosen risk; WATCH and AVOID keep the engine's reasons and get no plan; no Phase 11 directional decision, or a
missing, stale or malformed document, fails closed; no legacy source (a "Proven" swing record, a "Proven" smart-money
record, a legacy-holdover quant position, several of them agreeing) can make, promote, flip or size a call."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
NODE = shutil.which("node")

RUNNER = r"""
const TA = require(process.argv[2]);
const DAY = 86400, H = 3600;
const T0 = 1789000000 - (1789000000 % DAY);
const SIG_DAY = T0 + 59 * DAY, TODAY = T0 + 60 * DAY, NOW = TODAY + 5 * H;
// 60 calm days (daily range 4%, so ATR 4 at a price of 100) and today's candle, still forming
function d1(today) {
  const out = [];
  for (let i = 0; i < 60; i++) out.push({t: T0 + i * DAY, o: 100, h: 102, l: 98, c: 100, v: 1e6});
  out.push(Object.assign({t: TODAY, o: 100, h: 101, l: 99, c: 100.5, v: 3e5}, today || {}));
  return out;
}
const years = (a, b, c) => ({"2024": {R: a, ret: a / 10, n: 400}, "2025": {R: b, ret: b / 10, n: 400}, "2026": {R: c, ret: c / 10, n: 400}});
const band = (lo, hi, R, win, y) => ({lo, hi, n: 1000 + lo, R, ret: R / 10, win, years: y});
const picksResearch = {period: "Oct 2023 to Oct 2026", swing: {
  long: {bands: [band(60, 70, 0.02, 0.36, years(0.05, -0.11, 0.17)), band(70, 80, 0.223, 0.409, years(0.33, -0.06, 0.39)), band(80, 90, 0.378, 0.458, years(0.36, 0.23, 0.48))]},
  short: {bands: [band(80, 90, 0.142, 0.469, years(0.03, 0.17, 0.28))]}}};
const picks = (scores) => ({day: SIG_DAY, settings: {ready: 80}, scores});
const quantResearch = {window_3y: [1703793600, 1791072000], strategies: {
  TSMOM: {verdict: "live", three_year: {n: 1181, wr: 0.4141, avg: 0.0564}, years: [{from: 1759536000, to: 1791072000, n: 483, avg: 0.0977}, {from: 1728000000, to: 1759536000, n: 430, avg: 0.0249}]},
  OLD: {verdict: "rejected", three_year: {n: 900, wr: 0.4, avg: -0.02}, years: []}}};
const qpos = (o) => Object.assign({s: "TSMOM", c: "AAA", d: 1, t_sig: T0 + 58 * DAY, t_in: T0 + 58 * DAY, px: 95, stop_pct: 0.1, trail_pct: 0.1, hold_h: 504, identity: "VERIFIED_CRYPTO",
  res: {state: "open", stop_now: 90, last_px: 100, r: 0.3}, stop: 85.5}, o);
const quant = (open) => ({strategies: {TSMOM: {name: "Daily trend rider", desc: "trend"}, OLD: {name: "Old one"}}, open});
const smart = (row, trade, verdict) => ({generated: NOW - 3 * H, traders_n: 200,
  accuracy: {verdict: verdict || "Promising", tested: {n: 31, win: 0.613, r: 0.145, period: "Sep 05 to Oct 02 2026"}, live: {n: 0}},
  coins: row ? [Object.assign({coin: "AAA", hl: "AAA", side: "short", signal: true, info: false, proven: false, text: "3 proven traders opened shorts in 24 h",
    traders: 10, n_long: 4, n_short: 6, identity: "VERIFIED_CRYPTO"}, row)] : [],
  open: trade ? [Object.assign({coin: "AAA", hl: "AAA", d: -1, t_in: NOW - 3 * H, px: 101, last_px: 100.4, stop_pct: 0.03, t_out_by: NOW + 21 * H, kind: "signal"}, trade)] : []});
const call = (src, o) => TA.decide(Object.assign({coin: "AAA", price: 100.5, d1: d1(), now: NOW, src}, o || {}));
const brief = (r) => ({verdict: r.verdict, side: r.side, tier: r.tier, lead: r.lead && r.lead.src, plan: r.plan, conflict: r.conflict, headline: r.headline,
  signals: r.signals.map((s) => [s.src, s.side, s.tier]), sigPlans: r.signals.map((s) => s.plan), sigErrors: r.signals.map((s) => s.planError),
  expired: r.expired.map((s) => [s.src, s.why]), against: r.against.map((s) => s.src), status: r.authority.status,
  agree: r.agree.map((s) => s.src), notes: r.notes.map((n) => [n.src, n.text, n.want || null]), lossRun: r.lossRun, inScan: r.inScan});
const swingLong = {picks: picks({AAA: {side: "long", score: 84, core: 82, label: "Ready"}}), picksResearch};
const out = {T0, SIG_DAY, TODAY, NOW,
  none: brief(call({})),
  notReady: brief(call({picks: picks({AAA: {side: "long", score: 73, core: 65, label: "Setting up"}}), picksResearch, quant: quant([]), smart: smart(null)})),
  swing: brief(call(swingLong)),
  swingStopped: brief(call(swingLong, {d1: d1({l: 91})})),
  swingTrailed: brief(call(swingLong, {d1: d1({h: 115, c: 110}), price: 110})),
  swingMixed: brief(call({picks: picks({AAA: {side: "long", score: 81, core: 75, label: "Ready"}}), picksResearch})),
  quantSmart: brief(call({quant: quant([qpos()]), quantResearch, smart: smart({}, {})})),
  conflict: brief(call({picks: picks({AAA: {side: "short", score: 85, core: 83, label: "Ready"}}), picksResearch, quant: quant([qpos()]), quantResearch})),
  smartOnly: brief(call({smart: smart({}, {})})),
  smartLate: brief(call({smart: smart({}, {t_out_by: NOW + 5 * H})})),
  smartNoTrade: brief(call({smart: smart({}, null)})),
  longCrowd: brief(call({smart: smart({side: "long", signal: false, info: true, text: "3 proven traders opened longs in 24 h"}, null)})),
  smartProvenLive: brief(call({smart: smart({proven: true}, {})})),
  // v8 Phase 3: what smart.py publishes for a crowd on a coin without crypto execution identity, one per state
  blocked: ["UNVERIFIED", "VERIFIED_TRADFI", "AMBIGUOUS", null].map((st) => brief(call({smart: smart({side: null, signal: false, info: false,
    identity: st, identity_block: {reason: st === null ? "IDENTITY_AUTHORITY_MISSING" : st === "UNVERIFIED" ? "IDENTITY_UNVERIFIED"
      : st === "AMBIGUOUS" ? "AMBIGUOUS_EXPOSURE" : "TRADFI_CLASSIFIED", state: st, crowd_side: "short", crowd_signal: true, crowd_info: false}}, null)}))),
  // defense in depth: a row that claims a signal without verified identity (an older or altered file) is still refused
  forged: ["UNVERIFIED", "VERIFIED_TRADFI", "AMBIGUOUS", null].map((st) => brief(call({smart: smart({identity: st}, {})}))),
  noIdentity: brief(call({smart: (() => { const s = smart({}, {}); delete s.coins[0].identity; return s; })()})),
  coinsBlocked: ["UNVERIFIED", "VERIFIED_TRADFI", "AMBIGUOUS", null].map((st) => TA.signalCoins({smart: smart({identity: st}, {})}, NOW)),
  quantThrough: brief(call({quant: quant([qpos({res: {stop_now: 101, last_px: 100}})]), quantResearch})),
  quantRejected: brief(call({quant: quant([qpos({s: "OLD"})]), quantResearch})),
  quantPending: brief(call({quant: quant([qpos({px: null, res: null, t_in: NOW + H})]), quantResearch})),
  quantK: brief(TA.decide({coin: "PEPE", price: 0.01005, d1: [], now: NOW, account: 500, risk: 0.02,
    src: {quant: quant([qpos({c: "PEPE", px: 0.0000095, stop_pct: 0.1, res: {stop_now: 0.000009, last_px: 0.00001}})]), quantResearch}})),
  quantMismatch: brief(TA.decide({coin: "PEPE", price: 0.05, d1: [], now: NOW, account: 500, risk: 0.02,
    src: {quant: quant([qpos({c: "PEPE", px: 0.0000095, res: {stop_now: 0.000009, last_px: 0.00001}})]), quantResearch}})),
  coins: TA.signalCoins({picks: picks({AAA: {side: "long", score: 84, core: 82}, BBB: {side: "short", score: 90, core: 88}, CCC: {side: "long", score: 70, core: 66}}), picksResearch,
    quant: quant([qpos({c: "BBB", d: 1}), qpos({c: "DDD", d: -1}), qpos({c: "OLDQ", t_in: NOW - 600 * H})]), quantResearch,
    smart: Object.assign(smart({coin: "EEE"}, null), {})}, NOW),
  coinsLate: TA.signalCoins({smart: smart({}, {t_out_by: NOW + 2 * H})}, NOW),
  lossRun: [TA.lossRun(0.41, 20), TA.lossRun(0.613, 20), TA.lossRun(0.458, 20)],
  scale: [TA.scaleOf(0.0102, 0.0000102), TA.scaleOf(85930, 84709), TA.scaleOf(1, 0.5)],
};
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node is not installed")
class AnalyzerCall(unittest.TestCase):
    """Without a Phase 11 decision (none of these calls passes one) every coin is a wait: the legacy signals are
    context, with their own levels, and are never sized."""
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            js = os.path.join(tmp, "run.js")
            with open(js, "w") as fh:
                fh.write(RUNNER)
            out = subprocess.run([NODE, js, os.path.abspath(os.path.join(ROOT, "analyze.js"))], capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise AssertionError("node failed: " + out.stderr[-2000:])
        cls.R = json.loads(out.stdout)

    def no_call(self, r):
        self.assertEqual((r["verdict"], r["side"], r["tier"], r["plan"], r["lead"], r["status"]), ("WAIT", None, None, None, None, "MISSING"))

    def levels_ok(self, p):
        """A legacy signal's own levels, as context: the stop on the losing side, and no size of any kind."""
        d = 1 if p["side"] == "long" else -1
        self.assertGreater(d * (p["entry"] - p["stop"]), 0, "the stop sits on the losing side")
        self.assertAlmostEqual(abs(p["entry"] - p["stop"]) / p["entry"], p["stopPct"], places=12)
        for k in ("size", "riskShare", "riskUsd", "lev"):
            self.assertNotIn(k, p, "a legacy signal is never sized")

    def test_no_scans_is_a_wait(self):
        r = self.R["none"]
        self.no_call(r)
        self.assertEqual(r["signals"], [])
        self.assertIn("No call", r["headline"])
        self.assertIn("does not fall back to the legacy signals", r["headline"])

    def test_a_score_under_80_is_not_a_signal(self):
        r = self.R["notReady"]
        self.no_call(r)
        notes = {n[0]: n for n in r["notes"]}
        self.assertEqual(set(notes), {"swing", "quant", "smart"})
        self.assertIn("the score reaching 80 (now 73 for a long)", notes["swing"][2])
        self.assertIn("none of them holds it", notes["smart"][2])

    def test_ready_swing_keeps_its_tested_levels_as_context(self):
        R = self.R
        r = R["swing"]
        self.no_call(r)
        self.assertEqual(r["signals"], [["swing", "long", "Unqualified historical result"]])           # the picks research's own label
        p = r["sigPlans"][0]
        self.assertEqual(p["kind"], "swing")
        self.assertAlmostEqual(p["tested"]["entry"], 100.0)                  # today's open
        self.assertAlmostEqual(p["tested"]["stopPct"], 0.08, places=9)      # 2 x ATR 4% (between 5% and 25%)
        self.assertAlmostEqual(p["stop"], 92.0, places=9)
        self.assertFalse(p["raised"])
        self.assertAlmostEqual(p["trail"], 12.0, places=9)                  # 3 ATR, fixed at the entry
        self.assertEqual(p["exitBy"], R["TODAY"] + 30 * 86400)
        self.assertEqual(p["tested"]["t"], R["TODAY"])
        self.levels_ok(p)
        self.assertIsNone(r["lossRun"])

    def test_a_swing_trade_stopped_today_is_not_reentered(self):
        r = self.R["swingStopped"]
        self.no_call(r)
        self.assertEqual(r["expired"][0][0], "swing")
        self.assertIn("already hit its stop", r["expired"][0][1])

    def test_the_trailing_stop_follows_the_best_price(self):
        r = self.R["swingTrailed"]
        p = r["sigPlans"][0]
        self.assertAlmostEqual(p["stop"], 103.0, places=9)                   # best high 115 minus 3 ATR (12)
        self.assertTrue(p["raised"])
        self.levels_ok(p)

    def test_a_mixed_record_is_context_without_a_size(self):
        r = self.R["swingMixed"]                                            # score 81 from a chart score of 75
        self.no_call(r)
        self.assertEqual(r["signals"], [["swing", "long", "Mixed"]])
        self.levels_ok(r["sigPlans"][0])

    def test_quant_position_keeps_its_own_stop_as_context(self):
        R = self.R
        r = R["quantSmart"]
        self.no_call(r)
        self.assertEqual(sorted(r["signals"]), [["quant", "long", "Legacy holdover"], ["smart", "short", "Promising"]])
        self.assertEqual((r["against"], r["agree"]), ([], []), "no call: nothing is for or against it")
        p = r["sigPlans"][[x[0] for x in r["signals"]].index("quant")]
        self.assertAlmostEqual(p["stop"], 90.0, places=9)
        self.assertTrue(p["raised"])
        self.assertAlmostEqual(p["trail"], 9.5, places=9)                   # 10% of the desk's entry
        self.assertEqual(p["exitBy"], R["T0"] + 58 * 86400 + 504 * 3600)
        self.assertAlmostEqual(p["desk"]["entry"], 95.0)
        self.levels_ok(p)

    def test_legacy_signals_on_both_sides_are_not_a_phase11_conflict(self):
        r = self.R["conflict"]
        self.no_call(r)
        self.assertFalse(r["conflict"])
        self.assertEqual(sorted(s[0] for s in r["signals"]), ["quant", "swing"])

    def test_smart_short_keeps_its_paper_trade_levels_as_context(self):
        R = self.R
        r = R["smartOnly"]
        self.no_call(r)
        self.assertEqual(r["signals"], [["smart", "short", "Promising"]])
        p = r["sigPlans"][0]
        self.assertAlmostEqual(p["stop"], 101 * 1.03, places=9)              # the paper trade's stop level
        self.assertEqual(p["exitBy"], R["NOW"] + 21 * 3600)
        self.levels_ok(p)
        late = R["smartLate"]
        self.no_call(late)
        self.assertIn("too late", late["expired"][0][1])
        fresh = R["smartNoTrade"]["sigPlans"][0]                            # no paper trade yet: a fresh stop and window
        self.assertAlmostEqual(fresh["stopPct"], 0.015, places=9)           # flat daily closes: the 1.5% minimum
        self.assertEqual(fresh["exitBy"], R["NOW"] - 3 * 3600 + 24 * 3600)
        self.assertEqual(R["smartProvenLive"]["signals"], [["smart", "short", "Unqualified historical result"]])   # smart.json's own label
        self.no_call(R["smartProvenLive"])

    def test_smart_signal_needs_verified_crypto_identity(self):
        """v8 Phase 3, defense in depth: whatever smart.json says, the Analyzer takes a smart-money signal only from a
        coin whose identity is VERIFIED_CRYPTO; an identity-blocked crowd is a note, never a signal."""
        R = self.R
        for r in R["blocked"] + R["forged"] + [R["noIdentity"]]:
            self.assertEqual((r["verdict"], r["signals"], r["plan"]), ("WAIT", [], None))
            self.assertIn("not verified as a crypto coin", r["notes"][0][1])
        self.assertEqual(R["coinsBlocked"], [[], [], [], []])
        self.assertEqual(R["smartOnly"]["signals"], [["smart", "short", "Promising"]], "a verified crypto smart signal is unchanged")

    def test_long_crowds_are_information(self):
        r = self.R["longCrowd"]
        self.assertEqual((r["verdict"], r["signals"]), ("WAIT", []))
        self.assertIn("information only", r["notes"][0][1])

    def test_quant_edge_cases(self):
        R = self.R
        self.no_call(R["quantThrough"])
        self.assertIn("through the desk's stop", R["quantThrough"]["expired"][0][1])
        self.assertEqual(R["quantRejected"]["signals"], [], "a rejected strategy is not a signal")
        pend = R["quantPending"]
        self.no_call(pend)
        self.assertTrue(pend["sigPlans"][0]["desk"]["pending"])
        self.assertAlmostEqual(pend["sigPlans"][0]["stopPct"], 0.1, places=9)
        k = R["quantK"]["sigPlans"][0]
        self.assertAlmostEqual(k["stop"], 0.009, places=12)                  # per 1,000 coins, like the chart
        self.assertAlmostEqual(k["desk"]["entry"], 0.0095, places=12)
        mm = R["quantMismatch"]
        self.assertEqual((mm["verdict"], mm["sigPlans"]), ("WAIT", [None]), "no levels when the prices do not match")
        self.assertIn("another market", mm["sigErrors"][0])

    def test_signal_coins_never_come_from_legacy_signals(self):
        self.assertEqual(self.R["coins"], [], "ready swing scores, desk positions and smart crowds list no coin")
        self.assertEqual(self.R["coinsLate"], [])

    def test_helpers(self):
        self.assertEqual(self.R["lossRun"], [6, 3, 5])
        self.assertEqual(self.R["scale"], [1000, 1, None])


# --------------------------------------------------------------------------- v8 Phase 11: the call's only authority
AUTH_RUNNER = r"""
const TA = require(process.argv[2]);
const F = JSON.parse(require("fs").readFileSync(process.argv[3], "utf8"));
const DAY = 86400, H = 3600, NOW = F.now, COIN = "HI";
function d1() {   // 60 calm days (ATR 4 at a price of 100) and today's candle
  const T0 = Math.floor(NOW / DAY) * DAY - 60 * DAY, out = [];
  for (let i = 0; i < 60; i++) out.push({t: T0 + i * DAY, o: 100, h: 102, l: 98, c: 100, v: 1e6});
  out.push({t: T0 + 60 * DAY, o: 100, h: 101, l: 99, c: 100.5, v: 3e5});
  return out;
}
const yrs = {"2024": {R: 0.36, n: 400}, "2025": {R: 0.23, n: 400}, "2026": {R: 0.48, n: 400}};
const picksResearch = {period: "Oct 2023 to Oct 2026", swing: {long: {bands: [{lo: 80, hi: 90, n: 1080, R: 0.378, win: 0.458, years: yrs}]},
                                                         short: {bands: [{lo: 80, hi: 90, n: 1080, R: 0.378, win: 0.458, years: yrs}]}}};
const picks = (side) => ({day: Math.floor(NOW / DAY) * DAY - DAY, settings: {ready: 80}, scores: {[COIN]: {side, score: 88, core: 86, label: "Ready"}}});
const smart = (side) => ({generated: NOW - 3 * H, traders_n: 200, accuracy: {verdict: "Proven", tested: {n: 31, win: 0.613, r: 0.145}, live: {n: 50}},
  coins: [{coin: COIN, side, signal: true, info: false, proven: true, text: "5 proven traders together", traders: 10, n_long: 5, n_short: 5, identity: "VERIFIED_CRYPTO"}],
  open: [{coin: COIN, d: side === "long" ? 1 : -1, t_in: NOW - 3 * H, px: 100, last_px: 100.4, stop_pct: 0.03, t_out_by: NOW + 21 * H, kind: "signal"}]});
const pos = (s, d) => ({s, c: COIN, d, t_sig: NOW - 2 * DAY, t_in: NOW - 2 * DAY, px: d > 0 ? 95 : 106, stop_pct: 0.1, trail_pct: 0.1, hold_h: 504, identity: "VERIFIED_CRYPTO",
  res: {state: "open", stop_now: d > 0 ? 90 : 111, last_px: 100}, stop: d > 0 ? 85.5 : 116.6});
// quant.json as quant.py publishes it after Phase 9: the real policy states per strategy, plus the test-only REQ strategy
const quant = (open) => ({strategies: Object.assign({}, F.realStrategies, {REQ: {name: "Requalified test strategy", deployment_state: "ACTIVE_REQUALIFIED", research_state: "REQUALIFIED"}}), open});
// the legacy research says the old strategies are "live" (the old "Proven" source)
const quantResearch = {window_3y: [1703793600, 1791072000], strategies: Object.fromEntries(["TSMOM", "TREND_EMA", "XSMOM", "REQ"].map((k) =>
  [k, {verdict: "live", three_year: {n: 1181, wr: 0.4141, avg: 0.0564}, years: [{from: 1759536000, to: 1791072000, n: 483, avg: 0.0977}]}]))};
const excellent = (side, extra) => Object.assign({picks: picks(side), picksResearch, smart: smart(side), quantResearch,
  quant: quant([pos("TSMOM", side === "long" ? 1 : -1)].concat(extra || []))}, {});
const call = (src, o) => TA.decide(Object.assign({coin: COIN, price: 100.5, d1: d1(), now: NOW, src}, o || {}));
const all = (o) => JSON.stringify(o);
const brief = (r) => ({verdict: r.verdict, side: r.side, tier: r.tier, lead: r.lead && {src: r.lead.src, tier: r.lead.tier, side: r.lead.side,
    authority: r.lead.authority.id, planError: r.lead.planError || null}, plan: r.plan, conflict: r.conflict, headline: r.headline,
  status: r.authority.status, state: r.authority.state, candidates: r.authority.candidates,
  signals: r.signals.map((s) => ({src: s.src, side: s.side, tier: s.tier, rec: s.rec && s.rec.tier, plan: s.plan})),
  against: r.against.map((s) => s.src), agree: r.agree.map((s) => s.src), json: all(r)});
const D = F.docs, out = {now: NOW, riskShare: TA.RISK_SHARE};
// 1, 2: the real LEGACY_HOLDOVER quant position, with and without the real Phase 11 decision on it
out.legacyQuantNoDecision = brief(call({quant: quant([pos("TSMOM", 1)]), quantResearch}));
out.legacyQuantWatch = brief(call(Object.assign({quant: quant([pos("TSMOM", 1)]), quantResearch}, {decision: D.legacyWatch})));
out.legacyQuantAvoid = brief(call(Object.assign({quant: quant([pos("TSMOM", 1)]), quantResearch}, {decision: D.legacyAvoid})));
out.legacyRecord = TA.quantRecord(quantResearch, "TSMOM");
// 3, 4: "Proven" swing / smart-money records against a WATCH or an AVOID
for (const [k, doc] of [["Watch", D.legacyWatch], ["Avoid", D.disabledAvoid]]) {
  out["swing" + k] = brief(call({picks: picks("long"), picksResearch, decision: doc}));
  out["smart" + k] = brief(call({smart: smart("short"), decision: doc}));
}
// 5: a synthetic Phase 11 TRADE permits the matching direction, sized at the chosen risk
out.trade = brief(call({decision: D.tradeLong, quant: quant([pos("REQ", 1)]), quantResearch}));
out.tradeNoDesk = brief(call({decision: D.tradeLong}));
out.tradeStopped = brief(call({decision: D.tradeLong, quant: quant([Object.assign(pos("REQ", 1), {res: {stop_now: 101, last_px: 100}})])}));
out.tradeCoins = TA.signalCoins({decision: D.tradeLong}, NOW);
// 6: AVOID with every legacy input excellent
out.avoidExcellent = brief(call(Object.assign(excellent("long"), {decision: D.disabledAvoid})));
out.breachExcellent = brief(call(Object.assign(excellent("long"), {decision: D.breachAvoid})));
out.avoidCoins = TA.signalCoins(Object.assign(excellent("long"), {decision: D.disabledAvoid}), NOW);
// 7: WATCH with several legacy sources agreeing
out.watchAgree = brief(call(Object.assign(excellent("long"), {decision: D.legacyWatch})));
out.watchCoins = TA.signalCoins(Object.assign(excellent("long"), {decision: D.legacyWatch}), NOW);
// 8: missing, stale or malformed authority fails closed
const bad = (o) => Object.assign(JSON.parse(JSON.stringify(D.tradeLong)), o);
const badCand = (o) => { const d = JSON.parse(JSON.stringify(D.tradeLong)); Object.assign(d.candidates.find((c) => c.type === "DIRECTIONAL_STRATEGY"), o); return d; };
const failClosed = {missing: undefined, nul: null, stale: D.tradeLong, schema: bad({schema: "v8.decision/0"}), noValid: bad({valid_until: null}),
  noCands: bad({candidates: null}), noAssets: bad({assets: "x"}), notObject: "TRADE", noAuthority: bad({authority: null}),
  candState: badCand({state: "BUY"}), candDir: badCand({direction: 2}), candValid: badCand({valid_until: "later"}), candExpired: badCand({valid_until: NOW - 1}),
  candBlockers: badCand({blockers: null}),
  // the document's own horizon alone: a stale document whose candidate still claims to be current, and a stale WATCH
  staleDoc: (() => { const d = badCand({valid_until: NOW + 10 * DAY}); d.valid_until = NOW - 1; return d; })(),
  staleWatch: D.legacyWatch};
const NOW_OF = {stale: D.tradeLong.valid_until + 1, staleWatch: D.legacyWatch.valid_until + 1};
out.failClosed = {};
for (const [k, doc] of Object.entries(failClosed)) {
  const src = Object.assign(excellent("long", [pos("REQ", 1)]), {decision: doc});
  const now = NOW_OF[k] || NOW;
  out.failClosed[k] = Object.assign(brief(call(src, {now})), {coins: TA.signalCoins(src, now)});
}
out.none = brief(call(Object.assign(excellent("long"), {decision: D.noCandidate})));
out.notDiscovered = brief(call(Object.assign(excellent("long"), {decision: D.noCandidate}), {coin: "ZZZ"}));
// 9: opposite-direction legacy evidence cannot flip a TRADE
out.shortTradeLegacyLong = brief(call(Object.assign(excellent("long"), {decision: D.tradeShort, quant: quant([pos("TSMOM", 1), pos("REQ", -1)])})));
out.longTradeLegacyShort = brief(call(Object.assign(excellent("short"), {decision: D.tradeLong, quant: quant([pos("TSMOM", -1), pos("REQ", 1)])})));
out.opposed = brief(call({decision: D.opposed, quant: quant([pos("REQ", 1), pos("REQ4H", -1)])}));
out.opposedCoins = TA.signalCoins({decision: D.opposed}, NOW);
// 10: no full-risk sizing from a "Proven" legacy record
out.provenEverywhere = brief(call(Object.assign(excellent("long"), {decision: D.noCandidate})));
console.log(JSON.stringify(out));
"""


def _decision_docs():
    """Decision documents built by the real engine (v8/decision.py) on synthetic snapshots, and the real Phase 9 policy
    rows (v8/quant_strategy_policy.json) for the live strategies."""
    import importlib
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    P11 = importlib.import_module("test_v8_phase11")
    from v8 import decision as DE
    with open(os.path.join(ROOT, "v8", "quant_strategy_policy.json")) as fh:
        rows = {r["strategy_id"]: r for r in json.load(fh)["strategies"]}
    real = {sid: {"name": sid, "deployment_state": r["deployment_state"], "research_state": r["research_state"]}
            for sid, r in rows.items()}
    strategies = dict(P11.STRATS)
    for sid, r in rows.items():                              # the live strategies exactly as Phase 9 governs them
        strategies[sid] = {"tf": "1d", "hold_h": 504, "deployment_state": r["deployment_state"],
                           "research_state": r["research_state"]}
    def doc(signals, book=(), records=None):
        return DE.build(P11.snapshot(records or [P11.rec("HI")], {"HI": signals}, book=book, strategies=strategies))
    big = [P11.book_position(f"B{k}", a, notional=400.0) for k, a in enumerate(["BTC", "TWIN", "ALPHA", "BRAVO"])]
    docs = {"legacyWatch": doc([P11.sig("TSMOM", d=1, kind="ACTIVE")]),
            "legacyAvoid": doc([P11.sig("TSMOM", d=1, kind="ACTIVE")], book=big),
            "disabledAvoid": doc([P11.sig("DIS", d=1)]),
            "breachAvoid": doc([P11.sig("REQ", d=1)], book=big),
            "tradeLong": doc([P11.sig("REQ", d=1)]),
            "tradeShort": doc([P11.sig("REQ", d=-1)]),
            "opposed": doc([P11.sig("REQ", d=1), P11.sig("REQ4H", d=-1, age=3600)]),
            "noCandidate": doc([])}
    return docs, real, P11.AS_OF + 60, DE


@unittest.skipUnless(NODE, "node is not installed")
class Phase11Authority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        docs, real, now, DE = _decision_docs()
        cls.docs = docs
        st = {k: [c["state"] for c in d["candidates"] if c["type"] == DE.DIRECTIONAL] for k, d in docs.items()}
        want = {"legacyWatch": ["WATCH"], "legacyAvoid": ["AVOID"], "disabledAvoid": ["AVOID"], "breachAvoid": ["AVOID"],
                "tradeLong": ["TRADE"], "tradeShort": ["TRADE"], "opposed": ["TRADE", "TRADE"], "noCandidate": []}
        assert st == want, st                                   # the engine's own states, not the Analyzer's
        with tempfile.TemporaryDirectory() as tmp:
            fx = os.path.join(tmp, "fx.json")
            with open(fx, "w") as fh:
                json.dump({"docs": docs, "realStrategies": real, "now": now}, fh)
            js = os.path.join(tmp, "auth.js")
            with open(js, "w") as fh:
                fh.write(AUTH_RUNNER)
            out = subprocess.run([NODE, js, os.path.abspath(os.path.join(ROOT, "analyze.js")), fx],
                                 capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise AssertionError("node failed: " + out.stderr[-3000:])
        cls.R = json.loads(out.stdout)

    def no_call(self, r, verdict):
        self.assertEqual((r["verdict"], r["side"], r["tier"], r["plan"], r["lead"]), (verdict, None, None, None, None))
        self.assertEqual((r["agree"], r["against"]), ([], []))
        for s in r["signals"]:
            for k in ("size", "riskShare", "riskUsd", "lev"):
                self.assertNotIn(k, s["plan"] or {}, "a legacy signal is never sized")

    def test_1_real_legacy_holdover_quant_position_is_never_proven(self):
        R = self.R
        self.assertEqual(R["legacyRecord"]["tier"], "Legacy record", "the old research's 'live' verdict is not Proven")
        for case in ("legacyQuantNoDecision", "legacyQuantWatch", "legacyQuantAvoid"):
            r = R[case]
            q = [s for s in r["signals"] if s["src"] == "quant"]
            self.assertEqual([(s["side"], s["tier"], s["rec"]) for s in q], [("long", "Legacy holdover", "Legacy record")], case)
            self.assertNotIn('"Proven"', r["json"], case)
            self.assertNotEqual(r["tier"], "Proven", case)

    def test_2_legacy_holdover_quant_signal_cannot_create_long_or_short(self):
        R = self.R
        self.no_call(R["legacyQuantNoDecision"], "WAIT")
        self.assertEqual(R["legacyQuantNoDecision"]["status"], "MISSING")
        w = R["legacyQuantWatch"]
        self.no_call(w, "WATCH")
        self.assertEqual([c["state"] for c in w["candidates"]], ["WATCH"])
        self.assertIn("STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT", w["candidates"][0]["caps"])
        self.assertIn("strategy authority insufficient", w["headline"])
        a = R["legacyQuantAvoid"]
        self.no_call(a, "AVOID")
        self.assertEqual(a["candidates"][0]["blocking_step"], "PORTFOLIO_AFTER")
        self.assertIn("PORTFOLIO_LIMIT_BREACHED", a["candidates"][0]["blockers"])
        self.assertIn("rejected at PORTFOLIO_AFTER", a["headline"])

    def test_3_proven_swing_record_cannot_override_watch_or_avoid(self):
        for case, verdict in (("swingWatch", "WATCH"), ("swingAvoid", "AVOID")):
            r = self.R[case]
            self.assertEqual([(s["src"], s["side"], s["tier"]) for s in r["signals"]], [("swing", "long", "Unqualified historical result")], case)
            self.no_call(r, verdict)

    def test_4_proven_smart_money_record_cannot_override_watch_or_avoid(self):
        for case, verdict in (("smartWatch", "WATCH"), ("smartAvoid", "AVOID")):
            r = self.R[case]
            self.assertEqual([(s["src"], s["side"], s["tier"]) for s in r["signals"]], [("smart", "short", "Unqualified historical result")], case)
            self.no_call(r, verdict)

    def test_5_a_phase11_trade_permits_the_matching_direction(self):
        R = self.R
        r = R["trade"]
        trade_id = next(c["id"] for c in self.docs["tradeLong"]["candidates"] if c["state"] == "TRADE")
        self.assertEqual((r["verdict"], r["side"], r["tier"], r["status"], r["state"]), ("LONG", "long", "TRADE", "AVAILABLE", "TRADE"))
        self.assertEqual(r["lead"], {"src": "quant", "tier": "TRADE", "side": "long", "authority": trade_id, "planError": None})
        p = r["plan"]
        expected = next(c['proposal'] for c in self.docs['tradeLong']['candidates'] if c['state']=='TRADE')
        self.assertEqual((p['kind'],p['side'],p['riskShare']), ('governed','long',1))
        self.assertEqual(p['entry'], expected['mark'])
        self.assertEqual(p['stop'], expected['stop'])
        self.assertEqual(p['size'], expected['notional'])
        self.assertEqual(p['riskUsd'], expected['stop_risk_usd'])
        self.assertIn('Phase 11 decision: TRADE', r['headline'])
        nd=R['tradeNoDesk']
        self.assertEqual((nd['verdict'],nd['plan'],nd['lead']['src']), ('LONG',p,'phase11'))
        # A legacy paper position's newer stop cannot reprice the approved proposal.
        self.assertEqual(R['tradeStopped']['plan'],p)

    def test_6_avoid_blocks_even_when_every_legacy_input_looks_excellent(self):
        for case, code in (("avoidExcellent", "STRATEGY_DISABLED"), ("breachExcellent", "PORTFOLIO_LIMIT_BREACHED")):
            r = self.R[case]
            self.assertEqual(sorted((s["src"], s["side"]) for s in r["signals"]),
                             [("quant", "long"), ("smart", "long"), ("swing", "long")], case)
            self.no_call(r, "AVOID")
            self.assertIn(code, r["candidates"][0]["blockers"], case)
        self.assertEqual(self.R["avoidCoins"], [])

    def test_7_watch_is_not_promoted_by_agreeing_legacy_sources(self):
        r = self.R["watchAgree"]
        self.assertEqual(len(r["signals"]), 3)
        self.no_call(r, "WATCH")
        self.assertEqual(self.R["watchCoins"], [])

    def test_8_missing_stale_or_malformed_authority_fails_closed(self):
        R = self.R
        want = {"missing": "MISSING", "nul": "MISSING", "stale": "STALE", "schema": "MALFORMED", "noValid": "MALFORMED",
                "noCands": "MALFORMED", "noAssets": "MALFORMED", "notObject": "MALFORMED", "noAuthority": "MALFORMED",
                "candState": "MALFORMED", "candDir": "MALFORMED", "candValid": "MALFORMED", "candExpired": "STALE",
                "candBlockers": "MALFORMED", "staleDoc": "MALFORMED", "staleWatch": "STALE"}
        self.assertEqual(set(R["failClosed"]), set(want))
        for k, status in want.items():
            with self.subTest(authority=k):
                r = R["failClosed"][k]
                self.assertEqual(r["status"], status)
                self.no_call(r, "WAIT")
                self.assertEqual(r["coins"], [])
                self.assertGreaterEqual(len(r["signals"]), 3, "legacy diagnostics still display")
        for case in ("none", "notDiscovered"):                              # no Phase 11 directional decision on the coin
            r = R[case]
            self.assertEqual((r["status"], r["state"]), ("AVAILABLE", "NONE"))
            self.no_call(r, "WAIT")
        self.assertIn("not in this scan's discovery", R["notDiscovered"]["headline"])

    def test_9_opposite_legacy_evidence_cannot_flip_a_trade(self):
        R = self.R
        r = R["shortTradeLegacyLong"]
        self.assertEqual((r["verdict"], r["side"], r["plan"]["side"], r["lead"]["side"]), ("SHORT", "short", "short", "short"))
        self.assertEqual(sorted(r["against"]), ["quant", "smart", "swing"], "the legacy longs are context against it")
        r = R["longTradeLegacyShort"]
        self.assertEqual((r["verdict"], r["side"], r["plan"]["side"]), ("LONG", "long", "long"))
        self.assertEqual(sorted(r["against"]), ["quant", "smart", "swing"])
        o = R["opposed"]                                                     # Phase 11 TRADEs on both sides: no call
        self.assertTrue(o["conflict"])
        self.no_call(o, "WAIT")
        self.assertEqual(R["opposedCoins"], [])

    def test_10_full_risk_sizing_never_comes_from_a_proven_legacy_record(self):
        R = self.R
        self.assertEqual(R["riskShare"], {"TRADE": 1}, "only a Phase 11 TRADE has a risk share")
        r = R["provenEverywhere"]
        self.assertTrue(any(s["tier"] == "Unqualified historical result" for s in r["signals"]))
        self.no_call(r, "WAIT")
        sized = [k for k, v in R.items() if isinstance(v, dict) and v.get("plan")]
        self.assertEqual(sorted(sized), ["longTradeLegacyShort", "shortTradeLegacyLong", "trade", "tradeNoDesk", "tradeStopped"],
                         "a sized plan exists only for a current Phase 11 TRADE")
        for k in sized:
            self.assertEqual((R[k]["tier"], R[k]["plan"]["riskShare"]), ("TRADE", 1), k)


@unittest.skipUnless(NODE, "node is not installed")
class ContextRead(unittest.TestCase):
    def test_the_lean_read_has_no_trade_in_it(self):
        js = r"""
const TA = require(process.argv[2]);
const fs = require("fs");
const fx = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const bars = (rows) => rows.map((r) => ({t: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5]}));
const all = TA.analyzeAll({coin: "SOL", bars: {"1h": bars(fx.h1), "4h": bars(fx.h4), "1d": bars(fx.d1)}, deriv: fx.deriv}, {lean: true, account: 500, risk: 0.02});
console.log(JSON.stringify(Object.fromEntries(Object.entries(all).map(([tf, a]) => [tf, {side: a.side, summary: a.text.summary, change: a.text.change, parts: a.parts.map((p) => p.name)}]))));
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "lean.js")
            with open(p, "w") as fh:
                fh.write(js)
            out = subprocess.run([NODE, p, os.path.abspath(os.path.join(ROOT, "analyze.js")), os.path.join(ROOT, "tests", "fixtures", "candles_SOL.json")],
                                 capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        R = json.loads(out.stdout)
        for tf, a in R.items():
            self.assertNotIn("Plan:", a["summary"], tf)
            self.assertNotIn("take profits early", a["change"], tf)
            self.assertNotIn("Tested swing score", a["parts"], tf + ": the tested score is part of the call, not the read")
            self.assertTrue(("leans " + a["side"]) in a["summary"] if a["side"] else "has no lean" in a["summary"], tf)


if __name__ == "__main__":
    unittest.main()
