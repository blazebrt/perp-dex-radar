"""Tests for the coin analyzer engine (analyze.js), run through node. Run from the repository root:

    python -m unittest discover -s tests -v

Skipped when node is not installed. Uses synthetic candles (a steady uptrend, a downtrend, a choppy range) and
real SOL candles captured from Binance (tests/fixtures/candles_SOL.json). The checks are the invariants every
plan must meet: the stop on the losing side of the entry, targets on the winning side and in order, the size
set by the risk, and the order type matching where the entry sits against the price."""
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
const fs = require("fs");
function rng(seed) { let s = seed >>> 0; return () => ((s = (1664525 * s + 1013904223) >>> 0) / 4294967296); }
function walk(n, sec, drift, vol, seed, start) {
  const r = rng(seed), out = [];
  let p = start || 100, t = 1790000000 - n * sec;
  for (let i = 0; i < n; i++) {
    const o = p, ch = drift + vol * (r() - 0.5) * 2 + 0.3 * vol * Math.sin(i / 9);
    p = Math.max(0.0001, p * (1 + ch));
    const h = Math.max(o, p) * (1 + vol * r() * 0.6), l = Math.min(o, p) * (1 - vol * r() * 0.6);
    out.push({t: t + i * sec, o, h, l, c: p, v: 1e6 * (1 + r())});
  }
  return out;
}
function scaleTo(bars, last) { const k = last / bars[bars.length - 1].c; return bars.map((b) => ({t: b.t, o: b.o * k, h: b.h * k, l: b.l * k, c: b.c * k, v: b.v})); }
const res = {};
for (const [name, drift, vol] of [["up", 0.004, 0.01], ["down", -0.004, 0.01], ["range", 0, 0.012]]) {
  const h1 = walk(500, 3600, drift, vol, 7);
  const px = h1[h1.length - 1].c;
  const h4 = scaleTo(walk(300, 14400, drift * 1.2, vol * 1.5, 11), px), d1 = scaleTo(walk(300, 86400, drift * 1.5, vol * 2.5, 13), px);
  const all = TA.analyzeAll({coin: name.toUpperCase(), bars: {"1h": h1, "4h": h4, "1d": d1}, deriv: {}}, {account: 1000, risk: 0.01});
  res[name] = Object.fromEntries(Object.entries(all).map(([tf, a]) => [tf, {verdict: a.verdict, bias: a.bias, price: a.price, plans: a.plans, alt: a.alt,
    zones: a.zones, summary: a.text.summary, checks: a.checks.length, labels: a.labels.length}]));
}
const fx = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const bars = (rows) => rows.map((r) => ({t: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5]}));
const sol = TA.analyzeAll({coin: "SOL", bars: {"1h": bars(fx.h1), "4h": bars(fx.h4), "1d": bars(fx.d1)}, deriv: fx.deriv},
  {account: 500, risk: 0.02, market: {mood: "Mixed: test", fng: {value: 50, label: "Neutral"}}, picks: {side: "long", core: 82, score: 85, label: "Ready", sentiment: {score: 70, label: "Bullish"}}});
res.sol = Object.fromEntries(Object.entries(sol).map(([tf, a]) => [tf, {verdict: a.verdict, bias: a.bias, price: a.price, plans: a.plans, alt: a.alt, zones: a.zones,
  summary: a.text.summary, parts: a.parts, checks: a.checks}]));
let threw = false;
try { TA.analyze({coin: "X", tf: "1h", main: bars(fx.h1).slice(0, 50)}); } catch (e) { threw = /not enough candles/.test(e.message); }
res.threw = threw;
res.fmt = [TA.fmtPrice(84994.9), TA.fmtPrice(121.07), TA.fmtPrice(0.58291), TA.fmtPrice(0.0042866), TA.fmtPrice(0.000004279), TA.fmtPrice(null)];
console.log(JSON.stringify(res));
"""


@unittest.skipUnless(NODE, "node is not installed")
class AnalyzerEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            js = os.path.join(tmp, "run.js")
            with open(js, "w") as fh:
                fh.write(RUNNER)
            out = subprocess.run([NODE, js, os.path.abspath(os.path.join(ROOT, "analyze.js")),
                                  os.path.join(ROOT, "tests", "fixtures", "candles_SOL.json")],
                                 capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise AssertionError("node failed: " + out.stderr[-2000:])
        cls.R = json.loads(out.stdout)

    def check_plan(self, p, price, where):
        L = p["side"] == "long"
        d = 1 if L else -1
        self.assertGreater(p["risk"], 0, where)
        self.assertGreater(d * (p["entry"] - p["stop"]), 0, where + ": stop must be on the losing side of the entry")
        prev = p["entry"]
        for t in p["targets"]:
            self.assertGreater(d * (t["price"] - prev), 0, where + ": targets beyond the entry and in order")
            prev = t["price"]
        self.assertEqual(len(p["targets"]), 3, where)
        self.assertGreaterEqual(p["targets"][0]["rr"], 0.99, where + ": first target at least 1x the risk")
        self.assertAlmostEqual(abs(p["entry"] - p["stop"]) / p["entry"], p["stopPct"], places=9)
        self.assertAlmostEqual(p["size"] * p["stopPct"], p["riskUsd"], places=6, msg=where + ": the stop costs exactly the risk")
        if p["order"] == "market":
            self.assertEqual(p["entry"], price, where)
        elif p["order"] == "limit":
            self.assertGreater(d * (price - p["entry"]), 0, where + ": a limit buys below / sells above the price")
        else:
            self.assertEqual(p["order"], "stop", where)
            self.assertGreater(d * (p["entry"] - price), 0, where + ": a stop order buys above / sells below the price")
        self.assertTrue(p["manage"] and p["timeStop"] and p["invalid"], where)

    def all_plans(self, case):
        for tf, a in self.R[case].items():
            plans = a["plans"] + ([a["alt"]] if a["alt"] else [])
            for p in plans:
                yield tf, a, p

    def test_plan_invariants_everywhere(self):
        n = 0
        for case in ("up", "down", "range", "sol"):
            for tf, a, p in self.all_plans(case):
                self.check_plan(p, a["price"], f"{case} {tf} {p['side']} {p['type']}")
                n += 1
        self.assertGreater(n, 20)

    def test_verdict_matches_the_score(self):
        for case in ("up", "down", "range", "sol"):
            for tf, a in self.R[case].items():
                v = "LONG" if a["bias"] >= 20 else "SHORT" if a["bias"] <= -20 else "WAIT"
                self.assertEqual(a["verdict"], v, f"{case} {tf}")
                self.assertEqual(len(a["plans"]), 1 if v != "WAIT" else 2)
                self.assertEqual(a["alt"] is None, v == "WAIT")
                if v != "WAIT":
                    self.assertEqual(a["plans"][0]["side"], v.lower())
                    self.assertNotEqual(a["alt"]["side"], a["plans"][0]["side"])

    def test_trends_read_as_trends(self):
        for tf in ("1h", "4h"):
            self.assertEqual(self.R["up"][tf]["verdict"], "LONG", tf)
            self.assertEqual(self.R["down"][tf]["verdict"], "SHORT", tf)
        # the synthetic daily downtrend ends in a bounce (higher swing low), so the daily read only leans short
        self.assertGreater(self.R["up"]["1d"]["bias"], 0)
        self.assertLess(self.R["down"]["1d"]["bias"], 0)

    def test_zones_sit_on_the_right_side(self):
        for case in ("up", "down", "range", "sol"):
            for tf, a in self.R[case].items():
                for z in a["zones"]["support"]:
                    self.assertLess(z["hi"], a["price"], f"{case} {tf}")
                for z in a["zones"]["resistance"]:
                    self.assertGreater(z["lo"], a["price"], f"{case} {tf}")
                sup = [z["mid"] for z in a["zones"]["support"]]
                self.assertEqual(sup, sorted(sup, reverse=True), "nearest support first")

    def test_real_candles_use_every_input(self):
        a = self.R["sol"]["1h"]
        names = {p["name"] for p in a["parts"]}
        self.assertIn("Daily trend", names)
        self.assertIn("Tested swing score", names)      # core 82 for a long: +10
        self.assertIn("Social sentiment", names)        # 70: +4
        groups = {c["group"] for c in a["checks"]}
        self.assertTrue({"Trend", "Momentum", "Volatility", "Volume", "Positioning", "Tested score", "Sentiment"} <= groups)
        self.assertIn("SOL on the 1-hour chart", a["summary"])
        self.assertEqual(set(self.R["sol"]), {"1h", "4h", "1d"})   # no 15-minute candles in the fixture

    def test_short_history_is_refused(self):
        self.assertTrue(self.R["threw"])

    def test_price_formatting(self):
        self.assertEqual(self.R["fmt"], ["84994.9", "121.07", "0.58291", "0.0042866", "0.000004279", "–"])


if __name__ == "__main__":
    unittest.main()
