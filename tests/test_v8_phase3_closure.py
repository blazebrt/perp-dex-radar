"""v8 Phase 3 production-evidence closure: legacy quant and radar evidence is quarantined, and a quant position on a coin
without crypto execution identity is never actionable.

Two separate questions are tested apart (v8/evidence.py):
  current identity    - may an open position be an actionable signal NOW (only VERIFIED_CRYPTO; missing fails closed)
  entry-time proof    - may a trade count as forward evidence when it closes (complete VERIFIED_CRYPTO proof written
                        when it was opened; never recomputed, in either direction)

Quant (quant.py, dashboard.py, analyze.js), on the fake exchange with crafted journals:
  * a legacy open position on a coin that is UNVERIFIED now (the production NIGHT case): kept in the journal, simulated
    exactly as without the gate, absent from quant.json "open", present in "blocked_open" with its identity, reason,
    entry, R and exits; the dashboard does not aggregate it; the Analyzer gives a note, never a signal;
  * a legacy open position on a coin that is VERIFIED_CRYPTO now: still actionable (the documented rule: current
    identity decides actionability), but without entry proof - its close never reaches the live record;
  * a new VERIFIED_CRYPTO position: complete entry proof, actionable, and its close counts as live evidence;
  * verified at entry, then the coin degrades: no longer actionable, its entry proof stays true, its close counts;
  * legacy closed winners and losers: stored, outside live n / R / PF, reported in legacy_unqualified;
  * a coin missing from this scan's universe: blocked (IDENTITY_AUTHORITY_MISSING) - fails closed.
Radar (scanner.py learn / journal_summary), on synthetic journals:
  * forty strong legacy live winners (with their losing twins) never make a strategy pass; the same forty trades with
    entry-time proof pass under the unchanged tournament rules;
  * legacy trades never feed lessons, tuned targets or stops, cool-downs, live edge or published live-picks stats;
  * a legacy trade and its twin are excluded together; a qualified trade and its twin stay paired; a broken pair is
    excluded as a whole;
  * backtest trades are untouched (never marked, still counted exactly as before).

Part of the Scan workflow's pre-publication gate (lightweight: about 10 seconds).

Run from the repository root:  python -m unittest tests.test_v8_phase3_closure -v"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import dashboard as D  # noqa: E402
import quant as Q  # noqa: E402
import scanner as sc  # noqa: E402
from fake_exchange import FakeExchange  # noqa: E402
from v8 import evidence as EV  # noqa: E402
from v8 import identity as ID  # noqa: E402

H = 3600
NODE = shutil.which("node")
LEG_UNVERIFIED, LEG_VERIFIED, NEW_CLOSES, DEGRADED_CLOSES, DEGRADED_OPEN, LEG_CLOSES, MISSING = (
    "FAKE03", "FAKE04", "FAKE05", "FAKE06", "FAKE07", "FAKE08", "FAKE09")


def universe(fx, states=None, drop=()):
    uni = {}
    for c in fx.coins:
        if c in drop:
            continue
        uni[c] = {"t": c, "venues": {"hyperliquid": {"sym": c, "mult": 1.0, "vol": fx.vol24[c], "funding8h": 0.0001}},
                  "trade_vol": fx.vol24[c] * 1.2, "best_vol": fx.vol24[c] * 1.2, "tradfi": False,
                  "ref_price": fx.c15[c][-1]["c"], "name": c, "identity": (states or {}).get(c, ID.VERIFIED_CRYPTO)}
    return uni


def qtrade(coin, t_in, hold_h, d=1, sid="TSMOM"):
    """A quant paper trade as quant.py writes it, entered at the open of the hour t_in. stop_pct 0.9: no stop."""
    return {"id": f"{coin}-{sid}-{t_in}", "s": sid, "c": coin, "d": d, "t_sig": t_in, "t_in": t_in, "stop_pct": 0.9,
            "trail_pct": 0.0, "hold_h": hold_h, "slip": 0.0005, "src": "mexc", "px": None, "res": None}


def proof(tr, coin, scan="gh-100-1"):
    return EV.stamp(tr, coin, ID.Authority.from_states({coin: ID.VERIFIED_CRYPTO}, scan_id=scan))


def run_node(script, *args):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(script)
        p = fh.name
    try:
        out = subprocess.run([NODE, p, os.path.join(ROOT, "analyze.js"), *args], capture_output=True, text=True,
                             timeout=120)
    finally:
        os.unlink(p)
    if out.returncode != 0:
        raise AssertionError("node failed: " + out.stderr[-2000:])
    return json.loads(out.stdout)


ANALYZER = r"""
const TA = require(process.argv[2]);
const fs = require("fs");
const quant = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const coins = JSON.parse(process.argv[4]), now = Number(process.argv[5]);
const out = {tested: {}, coins: TA.signalCoins({quant}, now)};
for (const c of coins) {
  const r = TA.testedSignals(c, {quant});
  out.tested[c] = {signals: r.signals.map((s) => [s.src, s.side, s.tier]), notes: r.notes.map((n) => [n.src, n.text])};
}
console.log(JSON.stringify(out));
"""


# --------------------------------------------------------------------------- quant
class QuantEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = FakeExchange(n_coins=16, days=130, seed=5)
        cls.old, cls.old_now = sc.FETCH, sc.now_ts
        sc.FETCH = cls.fx.fetch
        sc.now_ts = lambda: cls.fx.now          # both runs at the same instant: their simulations must be identical
        cls.tmp = tempfile.mkdtemp(prefix="v8closure")
        t0 = (cls.fx.now // H) * H - 72 * H
        opened = [qtrade(LEG_UNVERIFIED, t0, 10_000), qtrade(LEG_VERIFIED, t0, 10_000), qtrade(LEG_CLOSES, t0, 3),
                  qtrade(MISSING, t0, 10_000), proof(qtrade(NEW_CLOSES, t0, 3), NEW_CLOSES),
                  proof(qtrade(DEGRADED_CLOSES, t0, 3), DEGRADED_CLOSES),
                  proof(qtrade(DEGRADED_OPEN, t0, 10_000), DEGRADED_OPEN)]
        closed = [dict(qtrade("FAKE10", t0 - 200 * H, 5), px=1.0, t_out=t0 - 190 * H, r=3.0),     # legacy winner
                  dict(qtrade("FAKE11", t0 - 200 * H, 5), px=1.0, t_out=t0 - 190 * H, r=-1.0)]    # legacy loser
        J = {"engine": Q.ENGINE, "version": Q.VERSION, "created": t0 - 300 * H, "updated": t0, "scans": 5,
             "open": opened, "closed": closed, "done": {}}
        cls.J0 = copy.deepcopy(J)
        jp = os.path.join(cls.tmp, "journal.json")
        with open(jp, "w") as fh:
            json.dump(J, fh)
        states = {LEG_UNVERIFIED: ID.UNVERIFIED, DEGRADED_CLOSES: ID.UNVERIFIED, DEGRADED_OPEN: ID.AMBIGUOUS}
        cls.out = Q.run(os.path.join(cls.tmp, "gated"), journal_path=jp,
                        universe=universe(cls.fx, states, drop=(MISSING,)))
        with open(os.path.join(cls.tmp, "gated", "data", "quant_journal.json")) as fh:
            cls.J = json.load(fh)
        with open(os.path.join(cls.tmp, "gated", "data", "quant.json")) as fh:
            cls.pub = json.load(fh)
        # control: the same journal with every coin verified now (the gate must not change any simulation)
        cls.ctl = Q.run(os.path.join(cls.tmp, "control"), journal_path=jp, universe=universe(cls.fx))
        with open(os.path.join(cls.tmp, "control", "data", "quant_journal.json")) as fh:
            cls.Jc = json.load(fh)

    @classmethod
    def tearDownClass(cls):
        sc.FETCH, sc.now_ts = cls.old, cls.old_now
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def trade(self, coin, J=None):
        J = J or self.J
        hit = [t for t in J["open"] + J["closed"] if t["c"] == coin and t["s"] == "TSMOM"
               and t["id"] in {x["id"] for x in self.J0["open"] + self.J0["closed"]}]
        self.assertEqual(len(hit), 1, coin)
        return hit[0]

    def test_legacy_unverified_open_is_kept_simulated_and_blocked(self):
        tr = self.trade(LEG_UNVERIFIED)
        self.assertIn(tr, self.J["open"])                                      # preserved, still open
        self.assertEqual(tr["identity_unqualified_reason"], EV.LEGACY_NO_IDENTITY_PROOF)
        self.assertIs(tr["identity_qualified"], False)
        self.assertIsNone(tr["identity_state_at_entry"])                       # nothing inferred from today
        self.assertNotIn("identity", tr)                                       # current identity never journaled
        self.assertEqual(tr["res"], self.trade(LEG_UNVERIFIED, self.Jc)["res"])  # simulated exactly as ungated
        self.assertIsNotNone(tr["px"])
        self.assertNotIn(LEG_UNVERIFIED, {o["c"] for o in self.out["open"]})
        b = next(x for x in self.out["blocked_open"] if x["c"] == LEG_UNVERIFIED)
        self.assertEqual((b["identity"], b["identity_reason"], b["actionable"]),
                         (ID.UNVERIFIED, "IDENTITY_UNVERIFIED", False))
        self.assertEqual((b["id"], b["s"], b["d"], b["t_in"], b["px"], b["hold_h"]),
                         (tr["id"], "TSMOM", 1, tr["t_in"], tr["px"], 10_000))
        self.assertEqual(b["r_now"], tr["res"]["r"])
        self.assertEqual(b["exit_stop"], tr["res"]["stop_now"])
        self.assertEqual(b["exit_time"], tr["t_in"] + 10_000 * H)
        self.assertEqual(b["identity_unqualified_reason"], EV.LEGACY_NO_IDENTITY_PROOF)
        self.assertIn("not a trade signal", b["why"])
        self.assertEqual(self.pub["blocked_open"], self.out["blocked_open"])

    def test_dashboard_never_aggregates_a_blocked_position(self):
        sig = D.signals(None, self.out, None, None)
        for c in (LEG_UNVERIFIED, DEGRADED_OPEN, MISSING):
            self.assertNotIn("quant", [x["src"] for x in sig.get(c, [])], c)
        self.assertIn("quant", [x["src"] for x in sig.get(LEG_VERIFIED, [])])
        card = D.quant_card(self.out, {})
        self.assertNotIn(LEG_UNVERIFIED, [i["coin"] for i in card["items"]])
        self.assertEqual(card["open_n"], len(self.out["open"]))
        # defense in depth: an "open" entry that is not VERIFIED_CRYPTO (an older or altered file) is refused
        forged = dict(self.out, open=self.out["open"] + [dict(self.out["blocked_open"][0], identity=ID.UNVERIFIED)]
                      + [{k: v for k, v in self.out["open"][0].items() if k != "identity"} | {"c": "NOID"}])
        sig = D.signals(None, forged, None, None)
        self.assertNotIn("quant", [x["src"] for x in sig.get(LEG_UNVERIFIED, [])])
        self.assertNotIn("NOID", sig)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_analyzer_gives_a_note_never_a_signal(self):
        qp = os.path.join(self.tmp, "gated", "data", "quant.json")
        R = run_node(ANALYZER, qp, json.dumps([LEG_UNVERIFIED, DEGRADED_OPEN, MISSING, LEG_VERIFIED]),
                     str(self.fx.now))
        for c in (LEG_UNVERIFIED, DEGRADED_OPEN, MISSING):
            self.assertEqual(R["tested"][c]["signals"], [], c)
            note = [t for s, t in R["tested"][c]["notes"] if s == "quant"]
            self.assertEqual(len(note), 1, c)
            self.assertIn("The quant journal still contains this historical paper position", note[0])
            self.assertIn(f"{c} is not currently verified as crypto", note[0])
            self.assertIn("so it is not a trade signal", note[0])
        self.assertIn(["quant", "long", "Proven"], R["tested"][LEG_VERIFIED]["signals"])   # (the engine may hold more)
        coins = {x["coin"] for x in R["coins"]}
        self.assertTrue({LEG_UNVERIFIED, DEGRADED_OPEN, MISSING}.isdisjoint(coins), coins)
        self.assertTrue(coins <= {o["c"] for o in self.out["open"]}, coins)   # verified positions only
        # an altered file that lists the blocked position under "open" without verified identity is still refused
        bad = dict(self.pub, open=self.pub["open"] + [dict(self.pub["blocked_open"][0], identity=ID.UNVERIFIED)])
        bp = os.path.join(self.tmp, "forged_quant.json")
        with open(bp, "w") as fh:
            json.dump(bad, fh)
        R2 = run_node(ANALYZER, bp, json.dumps([LEG_UNVERIFIED]), str(self.fx.now))
        self.assertEqual(R2["tested"][LEG_UNVERIFIED]["signals"], [])
        self.assertNotIn(LEG_UNVERIFIED, {x["coin"] for x in R2["coins"]})

    def test_legacy_verified_open_is_actionable_but_never_evidence(self):
        tr = self.trade(LEG_VERIFIED)
        self.assertIs(tr["identity_qualified"], False)
        o = next(x for x in self.out["open"] if x["id"] == tr["id"])
        self.assertEqual(o["identity"], ID.VERIFIED_CRYPTO)              # current identity: actionable now
        self.assertFalse(EV.qualified(o))                                # no entry proof: never live evidence
        # the same kind of trade, closed: kept, but outside the live record (see test_live_record)
        leg = self.trade(LEG_CLOSES)
        self.assertIn(leg, self.J["closed"])
        self.assertEqual(leg["identity_unqualified_reason"], EV.LEGACY_NO_IDENTITY_PROOF)

    def test_new_verified_position_has_full_proof_and_counts(self):
        tr = self.trade(NEW_CLOSES)
        self.assertIn(tr, self.J["closed"])
        for k in EV.TRADE_IDENTITY_FIELDS:
            self.assertIn(k, tr)
        self.assertEqual((tr["identity_state_at_entry"], tr["identity_qualified"], tr["identity_scan_id"],
                          tr["identity_version"]), (ID.VERIFIED_CRYPTO, True, "gh-100-1", ID.VERSION))
        # every trade the engine opened this run carries the same complete proof
        new = [t for t in self.J["open"] + self.J["closed"] if t["id"] not in {x["id"] for x in self.J0["open"]}
               and t["id"] not in {x["id"] for x in self.J0["closed"]}]
        for t in new:                       # (how many depends on the fake market at this hour)
            self.assertTrue(EV.qualified(t), t["id"])
            self.assertTrue(EV.proof_complete(t))
            from v8 import provenance           # gh-<run>-<attempt> in GitHub Actions, local-<time> offline
            self.assertEqual(t["identity_scan_id"], provenance.scan_id(self.fx.now))

    def test_identity_degrades_after_entry(self):
        tr = self.trade(DEGRADED_OPEN)
        self.assertTrue(EV.qualified(tr))                                # entry proof stays true
        self.assertNotIn(DEGRADED_OPEN, {o["c"] for o in self.out["open"]})
        b = next(x for x in self.out["blocked_open"] if x["c"] == DEGRADED_OPEN)
        self.assertEqual((b["identity"], b["identity_reason"], b["identity_qualified"]),
                         (ID.AMBIGUOUS, "AMBIGUOUS_EXPOSURE", True))
        cl = self.trade(DEGRADED_CLOSES)
        self.assertIn(cl, self.J["closed"])
        self.assertTrue(EV.qualified(cl))                                # its close is qualified evidence
        self.assertEqual(cl, self.trade(DEGRADED_CLOSES, self.Jc))       # and identical to the ungated run

    def test_missing_current_identity_fails_closed(self):
        b = next(x for x in self.out["blocked_open"] if x["c"] == MISSING)
        self.assertEqual((b["identity"], b["identity_reason"]), (None, "IDENTITY_AUTHORITY_MISSING"))
        st, why = EV.current_identity({"t": "X", "tradfi": False})              # no identity field
        self.assertEqual((st, why), (None, "IDENTITY_AUTHORITY_MISSING"))
        self.assertEqual(EV.current_identity({"t": "X", "tradfi": True, "identity": ID.VERIFIED_TRADFI},
                                             "TRADFI_EXPOSURE_EXCLUDED")[1], "TRADFI_EXPOSURE_EXCLUDED")

    def test_live_record(self):
        live = self.out["live_all"]
        q = [t for t in self.J["closed"] if EV.qualified(t)]
        crafted = {t["id"] for t in self.J0["open"] + self.J0["closed"]}
        # the crafted qualified closes are in; trades the engine itself opened and closed this run (the fake market
        # follows the clock) are qualified too; no legacy trade is
        self.assertEqual({t["c"] for t in q if t["id"] in crafted}, {NEW_CLOSES, DEGRADED_CLOSES})
        self.assertTrue(all(t["id"] not in crafted or t["c"] in (NEW_CLOSES, DEGRADED_CLOSES) for t in q))
        self.assertEqual(live, Q.live_stats(q))
        self.assertEqual(live["n"], len(q))
        self.assertGreaterEqual(live["n"], 2)
        leg = self.out["legacy_unqualified"]
        self.assertEqual(leg["reason"], EV.LEGACY_NO_IDENTITY_PROOF)
        self.assertEqual(leg["live_all"]["n"], 3)                         # the closing legacy one, winner, loser
        self.assertEqual(leg["live_all"]["sum"], round(3.0 - 1.0 + self.trade(LEG_CLOSES)["r"], 2))
        # the stored legacy winner and loser are unchanged except for their legacy mark
        for c in ("FAKE10", "FAKE11"):
            got = next(t for t in self.J["closed"] if t["c"] == c)
            was = next(t for t in self.J0["closed"] if t["c"] == c)
            self.assertEqual({k: v for k, v in got.items() if not k.startswith("identity")}, was)
        ev = self.out["evidence"]
        self.assertEqual(ev["blocked_open"], 3)
        self.assertEqual(ev["blocked_coins"], sorted([LEG_UNVERIFIED, DEGRADED_OPEN, MISSING]))
        self.assertEqual(ev["unqualified_reasons"], {EV.LEGACY_NO_IDENTITY_PROOF: 6})
        self.assertEqual(ev["actionable_open"], len(self.out["open"]))
        for sid in Q.ORDER:
            self.assertEqual(self.out["strategies"][sid]["open"], sum(1 for t in self.out["open"] if t["s"] == sid))

    def test_every_journal_trade_is_kept(self):
        before = {t["id"] for t in self.J0["open"] + self.J0["closed"]}
        after = {t["id"] for t in self.J["open"] + self.J["closed"]}
        self.assertTrue(before <= after)
        self.assertEqual(len(self.J["open"]) + len(self.J["closed"]), len(after))
        # the published sets partition the journal's open trades
        self.assertEqual(sorted(t["id"] for t in self.J["open"]),
                         sorted([o["id"] for o in self.out["open"]] + [b["id"] for b in self.out["blocked_open"]]))


# --------------------------------------------------------------------------- radar
F = {"rsi": 55, "ext": 1.0, "vr": 1.5, "r24": 0.05, "reg": "mixed", "sm": None, "st": "in_zone", "liq": 5e6,
     "fund": 0.0001, "btc3": 0.0, "adx": 25, "htf": "up", "vw": 0.01, "risk": 0.02, "hr": 10, "gate": 0}


def rtrade(sid, t, r, coin="AAA", bt=0, rk=None, f=None, state=None, hunt=False):
    st = state or ("win" if r > 0.02 else "loss")
    return {"id": f"{coin}-{sid}-{t}", "c": coin, "s": sid, "t": t, "bt": bt, "px": 100.0, "lo": 99.0, "hi": 101.0,
            "m": 100.0, "sl": 98.0, "tp": [102.0, 104.0, 106.0], "tg": None, "st": "in_zone", "tr": [1.0, 2.0, 3.0],
            "sk": 1.0, "cv": 60.0, "fs": 60.0, "rk": rk, "blk": None, "f": dict(F, **(f or {})), "tags": [],
            "res": {"state": st, "r": r, "gross": r + 0.05, "cost": 0.05, "done": True, "final": True, "ft": t + 60,
                    "xt": t + 3 * H, "fill": 100.0, "mfe": max(r, 0) + 0.5, "mae": 0.3,
                    "tph": [t + H] if r > 0.02 else [None], "hunt": hunt}}


def pair_of(trade, coin="ZZZ", r=-0.4):
    tw = rtrade("RAND:" + trade["s"], trade["t"], r, coin=coin)
    return tw


def qualify(trade, twin=None, scan="gh-200-1"):
    auth = ID.Authority.from_states({trade["c"]: ID.VERIFIED_CRYPTO, (twin or {}).get("c", "ZZZ"): ID.VERIFIED_CRYPTO},
                                    scan_id=scan)
    EV.stamp(trade, trade["c"], auth)
    if twin is not None:
        EV.stamp_pair(twin, trade, twin["c"], auth)
    return trade


def strong_journal(now, n=40, days=12, sid="PB"):
    """n live winners of `sid` over `days` days, each with a losing random twin: enough for a pass under the
    unchanged tournament rules (40+ live trades on 10+ days, well above zero and above the twins)."""
    trades, twins = [], []
    for i in range(n):
        t = now - (days - i % days) * 86400 + (i // days) * 3 * H
        tr = rtrade(sid, t, 1.0 + 0.1 * (i % 3), coin=f"C{i:02d}")
        trades.append(tr)
        twins.append(pair_of(tr, coin=f"Z{i:02d}", r=-0.3 - 0.05 * (i % 3)))
    return trades, twins


def journal_of(rows, now):
    J = sc.new_journal(now - 20 * 86400)
    J["closed"] = sorted(rows, key=lambda t: t["t"])
    return J


class RadarEvidence(unittest.TestCase):
    def setUp(self):
        self.now = 1_791_014_400
        self.cfg = dict(sc.CFG)

    def tearDown(self):
        sc.CFG.clear()
        sc.CFG.update(self.cfg)

    def learn(self, rows):
        J = journal_of(copy.deepcopy(rows), self.now)
        sc.load_specs(J)
        EV.mark_legacy(t for t in J["open"] + J["closed"] if not t.get("bt"))
        return J, sc.learn(J, self.now)

    def test_forty_legacy_winners_never_pass_forty_qualified_ones_do(self):
        trades, twins = strong_journal(self.now)
        Jl, Ll = self.learn(trades + twins)                              # legacy: no entry proof
        self.assertEqual(Ll["strat"]["PB"]["status"], "testing")
        self.assertEqual(Ll["strat"]["PB"]["live"], {"n": 0})
        self.assertIsNone(Ll["strat"]["PB"]["edge_live"])
        q_tr, q_tw = copy.deepcopy(trades), copy.deepcopy(twins)
        for a, b in zip(q_tr, q_tw):
            qualify(a, b)
        Jq, Lq = self.learn(q_tr + q_tw)                                 # the same trades with entry proof
        self.assertEqual(Lq["strat"]["PB"]["status"], "passed", Lq["strat"]["PB"]["why"])
        self.assertEqual(Lq["strat"]["PB"]["live"]["n"], 40)
        self.assertGreater(Lq["strat"]["PB"]["edge_live"]["edge"], 0)
        # legacy rows are kept and marked, never dropped
        self.assertEqual(len(Jl["closed"]), 80)
        self.assertTrue(all(t["identity_unqualified_reason"] == EV.LEGACY_NO_IDENTITY_PROOF for t in Jl["closed"]))

    def test_legacy_rows_cannot_tip_a_qualified_record(self):
        """A qualified record one trade short of a pass stays short however many legacy winners sit beside it."""
        trades, twins = strong_journal(self.now, n=39)
        for a, b in zip(trades, twins):
            qualify(a, b)
        extra, extra_tw = strong_journal(self.now - 3600, n=40)
        _, L = self.learn(trades + twins + extra + extra_tw)
        self.assertEqual(L["strat"]["PB"]["live"]["n"], 39)
        self.assertNotEqual(L["strat"]["PB"]["status"], "passed")

    def test_legacy_rows_do_not_teach_lessons_tune_or_cool_down(self):
        sc.CFG["auto_tune"] = True
        rows = []
        for i in range(48):                     # a strong volume pattern: high-volume trades win, the rest lose
            hi = i % 2 == 0
            rows.append(rtrade("MOM", self.now - (12 - i % 12) * 86400 - i * 600, 1.4 + 0.05 * (i % 5) if hi
                               else -0.9 - 0.05 * (i % 4), coin=f"L{i:02d}", f={"vr": 3.0 if hi else 1.3},
                               hunt=not hi))
        loss = rtrade("MOM", self.now - 2 * H, -1.0, coin="COOL")      # a stop-out an hour ago
        loss["res"]["xt"] = self.now - H
        _, Ll = self.learn(rows + [loss])
        self.assertEqual(Ll["lessons"], [])
        self.assertNotIn("MOM", Ll["tp_r"])
        self.assertEqual(Ll["cool"], {})
        q = copy.deepcopy(rows + [loss])
        for t in q:
            qualify(t)
        Jq, Lq = self.learn(q)
        self.assertTrue(any(x["bucket"] == "vol_high" for x in Lq["lessons"]), Lq["lessons"])
        self.assertIn("MOM", Lq["tp_r"])
        self.assertIn("COOL", Lq["cool"])

    def test_pairs_are_kept_or_excluded_together(self):
        a = rtrade("PB", self.now - 86400, 1.0, coin="AAA")
        aw = pair_of(a, coin="ZA")                                      # legacy pair: both out
        b = qualify(rtrade("PB", self.now - 86000, 1.0, coin="BBB"))
        bw = pair_of(b, coin="ZB")
        EV.stamp_pair(bw, b, "ZB", ID.Authority.from_states({"ZB": ID.VERIFIED_CRYPTO}, scan_id="gh-200-1"))
        c = qualify(rtrade("PB", self.now - 85000, 1.0, coin="CCC"))   # qualified trade, twin forged legacy
        cw = pair_of(c, coin="ZC")
        cw.update(pair=c["id"])
        d = rtrade("PB", self.now - 84000, 1.0, coin="DDD")             # legacy trade, twin forged qualified
        dw = qualify(pair_of(d, coin="ZD"))
        dw["pair"] = d["id"]
        rows = [a, aw, b, bw, c, cw, d, dw]
        EV.mark_legacy(rows)
        kept = {t["id"] for t in sc.evidence_pool(rows)}
        self.assertEqual(kept, {b["id"], bw["id"]})
        self.assertEqual(bw["pair"], b["id"])
        self.assertTrue(EV.qualified(bw))
        J = journal_of(rows, self.now)
        ev = sc.journal_evidence(J)
        self.assertEqual(ev["pairs"]["pair_class_mismatch"], 2)
        self.assertEqual(ev["qualified_live"]["total"], 2)
        self.assertEqual(ev["legacy_live"]["total"], 4)
        self.assertEqual(ev["pair_excluded_live"]["total"], 2)
        edge = sc.edge_vs_twins([t for t in sc.evidence_pool(rows) if not sc.is_twin(t["s"])],
                                [t for t in sc.evidence_pool(rows) if sc.is_twin(t["s"])])
        self.assertIsNone(edge)             # one qualified pair is not yet an edge measurement (needs 2+)

    def test_backtest_rows_are_untouched(self):
        trades, twins = strong_journal(self.now, n=30)
        bt = []
        for t in trades + twins:
            x = copy.deepcopy(t)
            x["bt"] = 1
            x["id"] += "-bt"
            bt.append(x)
        J0, L0 = self.learn(bt)
        self.assertTrue(all("identity_qualified" not in t for t in J0["closed"]))          # never marked
        self.assertTrue(all(sc.evidence_class(t) == sc.EV_BACKTEST for t in J0["closed"]))
        legacy, legacy_tw = strong_journal(self.now - 1800, n=40)
        J1, L1 = self.learn(bt + legacy + legacy_tw)
        for sid in ("PB",):
            self.assertEqual(L1["strat"][sid]["stat"], L0["strat"][sid]["stat"])           # legacy adds nothing
            self.assertEqual(L1["strat"][sid]["edge"], L0["strat"][sid]["edge"])
            self.assertEqual(L1["strat"][sid]["status"], L0["strat"][sid]["status"])
        self.assertEqual(L0["strat"]["PB"]["stat"]["bt_n"], 30)

    def test_live_picks_record_and_summary(self):
        pk = [rtrade("PB", self.now - 86400 + i * H, 2.0, coin=f"P{i}", rk=1) for i in range(5)]
        qk = [qualify(rtrade("PB", self.now - 80000 + i * H, -0.5, coin=f"Q{i}", rk=2)) for i in range(3)]
        rows = pk + qk
        J = journal_of(copy.deepcopy(rows), self.now)
        sc.load_specs(J)
        EV.mark_legacy(t for t in J["closed"] if not t.get("bt"))
        L = sc.learn(J, self.now)
        js = sc.journal_summary(J, L, self.now, {}, ident={"P0": ID.UNVERIFIED})
        self.assertEqual(js["picks"]["all"]["closed"], 3)                 # qualified picks only
        self.assertEqual(js["picks"]["all"]["avg_r"], -0.5)
        self.assertEqual(js["legacy_unqualified"]["picks"]["closed"], 5)  # reported apart, not discarded
        self.assertEqual(js["counts"]["live"], 3)
        self.assertEqual(js["counts"]["legacy_live"], 5)
        self.assertEqual(js["evidence"]["legacy_live"]["total"], 5)
        self.assertEqual(js["evidence"]["legacy_coin_identity"]["UNVERIFIED"], {"n": 1, "coins": ["P0"]})
        self.assertEqual(sum(1 for r in js["rows"] if r[-1] == "legacy"), 5)    # still listed, marked
        st = next(s for s in js["strategies"] if s["id"] == "PB")
        self.assertEqual(st["live_n"], 3)
        csv_rows = sc.journal_csv(J).splitlines()
        self.assertEqual(sum(1 for r in csv_rows[1:] if ",legacy,," in r), 5)

    def test_new_live_trades_carry_proof(self):
        """What scanner.run() writes for a signal and its twin (the stamp and stamp_pair calls of step 4)."""
        coins = {"AAA": {"identity": ID.VERIFIED_CRYPTO, "tradfi": False}, "ZZZ": {"identity": ID.VERIFIED_CRYPTO,
                                                                                  "tradfi": False}}
        auth = EV.universe_authority(coins, self.now, "gh-300-1", {"AAA": {"decision": "CRYPTO"}})
        tr = EV.stamp(rtrade("PB", self.now, 0.0, coin="AAA"), "AAA", auth)
        tw = EV.stamp_pair(pair_of(tr), tr, "ZZZ", auth)
        self.assertTrue(EV.qualified(tr) and EV.qualified(tw))
        self.assertEqual((tr["identity_scan_id"], tr["identity_decision"], tw["pair"]), ("gh-300-1", "CRYPTO", tr["id"]))
        self.assertEqual(sc.evidence_class(tr), sc.EV_QUALIFIED)
        self.assertEqual(EV.mark_legacy([tr, tw]), 0)                    # proof is never overwritten
        un = EV.stamp(rtrade("PB", self.now, 0.0, coin="QQQ"), "QQQ", auth)       # not in the authority
        self.assertEqual((un["identity_qualified"], un["identity_unqualified_reason"]),
                         (False, EV.NOT_VERIFIED_AT_ENTRY))


# --------------------------------------------------------------------------- scan-gate invariants
class ScanGateInvariants(unittest.TestCase):
    """The critical invariants, cheap enough for every scan."""

    def test_non_verified_open_positions_cannot_become_actionable(self):
        uni = {"A": {"identity": ID.VERIFIED_CRYPTO, "tradfi": False}, "B": {"identity": ID.UNVERIFIED, "tradfi": False},
               "C": {"identity": ID.VERIFIED_TRADFI, "tradfi": True}, "D": {"identity": ID.AMBIGUOUS, "tradfi": True},
               "E": {"tradfi": False}}
        auth = EV.universe_authority(uni, 0, "gh-1-1")
        opens = [qtrade(c, 0, 10) for c in "ABCDEF"]
        act, blk = Q.split_open(opens, uni, auth)
        self.assertEqual([o["c"] for o in act], ["A"])
        self.assertEqual({b["c"]: b["identity_reason"] for b in blk},
                         {"B": "IDENTITY_UNVERIFIED", "C": "TRADFI_CLASSIFIED", "D": "AMBIGUOUS_EXPOSURE",
                          "E": "IDENTITY_AUTHORITY_MISSING", "F": "IDENTITY_AUTHORITY_MISSING"})
        self.assertEqual(list(D.signals(None, {"open": act + [dict(b, identity=b["identity"]) for b in blk]},
                                        None, None)), ["A"])

    def test_legacy_quant_trades_cannot_become_qualified(self):
        tr = dict(qtrade("A", 0, 10), r=5.0)
        self.assertEqual(EV.mark_legacy([tr]), 1)
        self.assertFalse(EV.qualified(tr))
        for k, v in (("identity_qualified", True), ("identity_state_at_entry", ID.VERIFIED_CRYPTO)):
            forged = dict(tr, **{k: v})
            self.assertFalse(EV.qualified(forged), k)                     # a partial proof never qualifies
        self.assertEqual(EV.mark_legacy([tr]), 0)                         # marked once, never re-qualified

    def test_legacy_radar_live_trades_cannot_grant_a_pass(self):
        trades, twins = strong_journal(1_791_014_400)
        J = journal_of(trades + twins, 1_791_014_400)
        sc.load_specs(J)
        EV.mark_legacy(t for t in J["closed"] if not t.get("bt"))
        self.assertEqual(sc.evidence_pool(J["closed"]), [])
        self.assertNotEqual(sc.learn(J, 1_791_014_400)["strat"]["PB"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
