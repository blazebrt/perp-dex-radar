"""Tests for the analyzer's call (analyze.js decide): only tested signals make it, each with the exits it was
tested with. Run through node with synthetic scans and candles. Run from the repository root:

    python -m unittest discover -s tests -v

Skipped when node is not installed. Checks: no scans means wait; a ready swing score gives the tested swing trade
(stop 2 daily ATR from the open, 3 ATR trailing stop, 30 days); a swing trade already stopped today is not
re-entered; a quant desk position is joined at its own stop; proven signals on both sides mean wait; a promising
signal trades at half size and only while most of its window is left; a promising signal against a proven one does
not change the call; prices quoted per 1,000 coins line up; every plan's stop costs exactly the chosen risk."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
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
const call = (src, o) => TA.decide(Object.assign({coin: "AAA", price: 100.5, d1: d1(), now: NOW, account: 500, risk: 0.02, src}, o || {}));
const brief = (r) => ({verdict: r.verdict, side: r.side, tier: r.tier, lead: r.lead && r.lead.src, plan: r.plan, conflict: r.conflict, headline: r.headline,
  signals: r.signals.map((s) => [s.src, s.side, s.tier]), expired: r.expired.map((s) => [s.src, s.why]), against: r.against.map((s) => s.src),
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

    def plan_ok(self, r, risk_usd):
        p = r["plan"]
        d = 1 if p["side"] == "long" else -1
        self.assertGreater(d * (p["entry"] - p["stop"]), 0, "the stop sits on the losing side")
        self.assertAlmostEqual(abs(p["entry"] - p["stop"]) / p["entry"], p["stopPct"], places=12)
        self.assertAlmostEqual(p["size"] * p["stopPct"], risk_usd, places=9, msg="the stop costs exactly the risk")
        self.assertAlmostEqual(p["lev"], p["size"] / 500, places=12)

    def test_no_scans_is_a_wait(self):
        r = self.R["none"]
        self.assertEqual((r["verdict"], r["side"], r["plan"], r["signals"]), ("WAIT", None, None, []))
        self.assertIn("No tested signal", r["headline"])

    def test_a_score_under_80_is_not_a_signal(self):
        r = self.R["notReady"]
        self.assertEqual(r["verdict"], "WAIT")
        notes = {n[0]: n for n in r["notes"]}
        self.assertEqual(set(notes), {"swing", "quant", "smart"})
        self.assertIn("the score reaching 80 (now 73 for a long)", notes["swing"][2])
        self.assertIn("none of them holds it", notes["smart"][2])

    def test_ready_swing_is_the_tested_swing_trade(self):
        R = self.R
        r = R["swing"]
        self.assertEqual((r["verdict"], r["tier"], r["lead"]), ("LONG", "Proven", "swing"))
        p = r["plan"]
        self.assertEqual(p["kind"], "swing")
        self.assertAlmostEqual(p["tested"]["entry"], 100.0)                  # today's open
        self.assertAlmostEqual(p["tested"]["stopPct"], 0.08, places=9)      # 2 x ATR 4% (between 5% and 25%)
        self.assertAlmostEqual(p["stop"], 92.0, places=9)
        self.assertFalse(p["raised"])
        self.assertAlmostEqual(p["trail"], 12.0, places=9)                  # 3 ATR, fixed at the entry
        self.assertEqual(p["exitBy"], R["TODAY"] + 30 * 86400)
        self.assertEqual(p["tested"]["t"], R["TODAY"])
        self.plan_ok(r, 10.0)
        self.assertEqual(r["lossRun"], 5)                                   # 46% winners

    def test_a_swing_trade_stopped_today_is_not_reentered(self):
        r = self.R["swingStopped"]
        self.assertEqual(r["verdict"], "WAIT")
        self.assertEqual(r["expired"][0][0], "swing")
        self.assertIn("already hit its stop", r["expired"][0][1])

    def test_the_trailing_stop_follows_the_best_price(self):
        r = self.R["swingTrailed"]
        p = r["plan"]
        self.assertAlmostEqual(p["stop"], 103.0, places=9)                   # best high 115 minus 3 ATR (12)
        self.assertTrue(p["raised"])
        self.plan_ok(r, 10.0)

    def test_a_mixed_record_trades_at_half_size(self):
        r = self.R["swingMixed"]                                            # score 81 from a chart score of 75
        self.assertEqual((r["verdict"], r["tier"]), ("LONG", "Mixed"))
        self.assertEqual(r["plan"]["riskShare"], 0.5)
        self.plan_ok(r, 5.0)

    def test_quant_position_is_joined_at_its_own_stop(self):
        R = self.R
        r = R["quantSmart"]
        self.assertEqual((r["verdict"], r["tier"], r["lead"]), ("LONG", "Proven", "quant"))
        self.assertEqual(r["against"], ["smart"], "the promising short is shown against the call")
        p = r["plan"]
        self.assertAlmostEqual(p["stop"], 90.0, places=9)
        self.assertTrue(p["raised"])
        self.assertAlmostEqual(p["trail"], 9.5, places=9)                   # 10% of the desk's entry
        self.assertEqual(p["exitBy"], R["T0"] + 58 * 86400 + 504 * 3600)
        self.assertAlmostEqual(p["desk"]["entry"], 95.0)
        self.plan_ok(r, 10.0)
        self.assertIn("Daily trend rider", r["headline"])
        self.assertIn("+$6 per $100 risked over 1,181 trades", r["headline"])

    def test_proven_signals_on_both_sides_mean_wait(self):
        r = self.R["conflict"]
        self.assertEqual((r["verdict"], r["conflict"], r["plan"]), ("WAIT", True, None))
        self.assertEqual(sorted(s[0] for s in r["signals"]), ["quant", "swing"])
        self.assertIn("disagree", r["headline"])

    def test_promising_smart_short_at_half_size(self):
        R = self.R
        r = R["smartOnly"]
        self.assertEqual((r["verdict"], r["tier"], r["lead"]), ("SHORT", "Promising", "smart"))
        p = r["plan"]
        self.assertAlmostEqual(p["stop"], 101 * 1.03, places=9)              # the paper trade's stop level
        self.assertEqual(p["exitBy"], R["NOW"] + 21 * 3600)
        self.plan_ok(r, 5.0)
        self.assertEqual(r["lossRun"], 3)
        late = R["smartLate"]
        self.assertEqual(late["verdict"], "WAIT")
        self.assertIn("too late", late["expired"][0][1])
        fresh = R["smartNoTrade"]["plan"]                                   # no paper trade yet: a fresh stop and window
        self.assertAlmostEqual(fresh["stopPct"], 0.015, places=9)           # flat daily closes: the 1.5% minimum
        self.assertEqual(fresh["exitBy"], R["NOW"] - 3 * 3600 + 24 * 3600)
        self.assertEqual(R["smartProvenLive"]["tier"], "Proven")

    def test_smart_signal_needs_verified_crypto_identity(self):
        """v8 Phase 3, defense in depth: whatever smart.json says, the Analyzer takes a smart-money signal only from a
        coin whose identity is VERIFIED_CRYPTO; an identity-blocked crowd is a note, never a trade."""
        R = self.R
        for r in R["blocked"] + R["forged"] + [R["noIdentity"]]:
            self.assertEqual((r["verdict"], r["signals"], r["plan"]), ("WAIT", [], None))
            self.assertIn("not verified as a crypto coin", r["notes"][0][1])
        self.assertEqual(R["coinsBlocked"], [[], [], [], []])
        self.assertEqual(R["smartOnly"]["verdict"], "SHORT", "a verified crypto smart signal is unchanged")

    def test_long_crowds_are_information(self):
        r = self.R["longCrowd"]
        self.assertEqual((r["verdict"], r["signals"]), ("WAIT", []))
        self.assertIn("information only", r["notes"][0][1])

    def test_quant_edge_cases(self):
        R = self.R
        self.assertEqual(R["quantThrough"]["verdict"], "WAIT")
        self.assertIn("through the desk's stop", R["quantThrough"]["expired"][0][1])
        self.assertEqual(R["quantRejected"]["signals"], [], "a rejected strategy is not a signal")
        pend = R["quantPending"]
        self.assertEqual(pend["verdict"], "LONG")
        self.assertTrue(pend["plan"]["desk"]["pending"])
        self.assertAlmostEqual(pend["plan"]["stopPct"], 0.1, places=9)
        k = R["quantK"]["plan"]
        self.assertAlmostEqual(k["stop"], 0.009, places=12)                  # per 1,000 coins, like the chart
        self.assertAlmostEqual(k["desk"]["entry"], 0.0095, places=12)
        mm = R["quantMismatch"]
        self.assertEqual((mm["verdict"], mm["plan"]), ("LONG", None), "no plan when the prices do not match")

    def test_signal_coins(self):
        coins = {c["coin"]: c for c in self.R["coins"]}
        self.assertEqual(set(coins), {"AAA", "DDD", "EEE"}, "BBB has proven signals on both sides; CCC is not ready; OLDQ is past its time limit")
        self.assertEqual(self.R["coinsLate"], [], "a smart-money signal near the end of its window is not offered")
        self.assertEqual(coins["AAA"]["side"], "long")
        self.assertEqual(coins["DDD"]["side"], "short")
        self.assertEqual(coins["EEE"]["tier"], "Promising")
        self.assertEqual(self.R["coins"][-1]["coin"], "EEE", "proven calls first")

    def test_helpers(self):
        self.assertEqual(self.R["lossRun"], [6, 3, 5])
        self.assertEqual(self.R["scale"], [1000, 1, None])


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
