"""v8 Phase 3, final closure: entry-time identity provenance of smart-money paper trades.

Current identity controls NEW execution authority (tests/test_v8_phase3_smart.py). Entry-time identity provenance
controls whether a paper trade belongs to the production live evidence record: a trade counts in accuracy.live /
live_info and the verdict only when VERIFIED_CRYPTO was proven by the same-scan identity authority when it was
opened. Trades opened before Phase 3 are kept, followed to their close and reported apart as
LEGACY_NO_IDENTITY_PROOF; nothing is decided from a later scan's identity, in either direction.

Cases: legacy closed signal (cannot make the rule Proven, cannot prevent No edge, cannot affect proven_rule), legacy
open signal (closes normally, stays out), new verified signal (carries its proof, counts exactly as before), identity
changing after entry (no new signal, the old trade stays qualified), new unverified crowd (no trade, no evidence),
missing authority (no new trade; legacy stays unqualified; qualified stays qualified), and a fresh verified run whose
trades are identical apart from the additive provenance.

Run from the repository root:  python -m unittest tests.test_v8_phase3_journal -v"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import dashboard as D  # noqa: E402
import scanner as sc  # noqa: E402
import smart as SM  # noqa: E402
from test_smart import T0, Fake, addr, hourly  # noqa: E402
from test_v8_phase3_smart import NODE, node_signals, offline_env  # noqa: E402
from v8 import identity as ID  # noqa: E402
from v8 import parts  # noqa: E402
from v8 import taxonomy as T  # noqa: E402

VC, UV = ID.VERIFIED_CRYPTO, ID.UNVERIFIED
H = 3600
with open(os.path.join(ROOT, "smart_research.json")) as _fh:
    RESEARCH = json.load(_fh)                   # the real tested record: verdict "Promising"


def legacy_trade(coin, kind, r, t_in, closed=True, d=-1, px=100.0):
    """A paper trade exactly as the pre-Phase-3 engine wrote it: no identity field at all."""
    tr = {"id": f"{coin}-{t_in}", "coin": coin, "hl": coin, "d": d, "t_in": t_in, "px": px, "stop_pct": 0.02,
          "stop": px * (1 - d * 0.02), "why": "2 proven traders opened shorts in 24 h", "t_out_by": t_in + 24 * H,
          "kind": kind}
    if closed:
        ret = round(r * 0.02, 5)
        tr.update(last_px=px, r_now=r, t_out=t_in + 24 * H, exit_px=px * (1 + d * ret), why="time", ret=ret, r=r)
    return tr


def qualified_trade(coin, kind, r, t_in, scan="gh-1-1", **kw):
    return dict(legacy_trade(coin, kind, r, t_in, **kw), identity_state_at_entry=VC, identity_qualified=True,
                identity_version=ID.VERSION, identity_scan_id=scan, identity_decision="CRYPTO")


class World:
    """The smart-money fake (test_smart.Fake) over several scans, with the journal carried from scan to scan."""

    def __init__(self, tmp):
        self.tmp, self.f = tmp, Fake()
        for c in ("SOL", "ETH"):
            self.f.candles[c] = hourly(float(self.f.mids[c]), T0 - 8 * 86400, 8 * 24 + 60)
        self.jp = os.path.join(tmp, "j.json")

    def scan(self, now, identity, seed=None):
        """One smart run at `now`. seed(J) may change the journal first (as the published file would carry it)."""
        if os.path.exists(os.path.join(self.tmp, "data", "smart_journal.json")):
            shutil.copyfile(os.path.join(self.tmp, "data", "smart_journal.json"), self.jp)
        if seed is not None:
            if os.path.exists(self.jp):
                with open(self.jp) as fh:
                    J = json.load(fh)
            else:
                J = SM.new_journal(now)
            seed(J)
            with open(self.jp, "w") as fh:
                json.dump(J, fh)
        return SM.run(self.tmp, journal_path=self.jp, fetch=self.f, now=now, identity=identity)

    def crowd(self):
        """Two proven traders open ETH shorts (the tested side: a signal); two open SOL longs (information)."""
        self.f.pos[addr(0)] = [("SOL", 1000.0, 120.0), ("ETH", -20.0, 2500.0)]
        self.f.pos[addr(1)] = [("SOL", 500.0, 120.0)]
        self.f.pos[addr(2)] = [("ETH", -20.0, 2500.0)]

    def journal(self):
        with open(os.path.join(self.tmp, "data", "smart_journal.json")) as fh:
            return json.load(fh)

    def part(self):
        return parts.read(self.tmp, "smart")


def base_accuracy(closed):
    """The pre-Phase-3 live record: every closed signal trade, whatever its provenance (what the defect counted)."""
    return SM.live_stats([x for x in closed if x.get("kind", "signal") == "signal"])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v8journal")
        self.saved = sc.FETCH

    def tearDown(self):
        sc.FETCH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class LegacyClosedSignal(Base):
    """Section 13: a pre-Phase-3 closed signal trade can never reach the production live record."""

    WINNERS = [legacy_trade("ETH", "signal", 2.0 + 0.1 * (i % 3), T0 - (60 - i) * H) for i in range(45)]

    def test_strong_legacy_winners_cannot_make_the_rule_proven(self):
        # strong enough that the pre-Phase-3 rule would have declared the strategy Proven
        b = base_accuracy(self.WINNERS)
        self.assertTrue(b["n"] >= SM.LIVE_MIN and b["r"] > 0 and b["t"] >= 2, b)
        J = {"open": [], "closed": copy.deepcopy(self.WINNERS)}
        SM.mark_legacy(J)
        a = SM.accuracy(RESEARCH, J)
        self.assertEqual(a["live"], {"n": 0})
        self.assertEqual(a["verdict"], RESEARCH["verdict"])               # the test decides, as with no live trades
        self.assertEqual(a["legacy_unqualified"]["signal"]["n"], 45)
        self.assertEqual(a["legacy_unqualified"]["reason"], "LEGACY_NO_IDENTITY_PROOF")
        self.assertEqual((a["evidence"]["unqualified"]["closed_signal"], a["evidence"]["qualified"]["closed_signal"]),
                         (45, 0))
        self.assertEqual(a["evidence"]["unqualified_reasons"], {"LEGACY_NO_IDENTITY_PROOF": 45})
        # kept, unchanged apart from the marking
        for old, new in zip(self.WINNERS, J["closed"]):
            self.assertEqual({k: v for k, v in new.items() if not k.startswith("identity")}, old)
            self.assertEqual((new["identity_qualified"], new["identity_unqualified_reason"],
                              new["identity_state_at_entry"]), (False, "LEGACY_NO_IDENTITY_PROOF", None))

    def test_legacy_winners_cannot_prevent_no_edge(self):
        losers = [qualified_trade("ETH", "signal", -0.4 + 0.1 * (i % 2), T0 - (100 - i) * H) for i in range(40)]
        J = {"open": [], "closed": copy.deepcopy(self.WINNERS) + losers}
        SM.mark_legacy(J)
        a = SM.accuracy(RESEARCH, J)
        self.assertEqual(a["verdict"], "No edge")
        self.assertEqual(a["live"], SM.live_stats(losers))               # R, win rate, t: qualified trades only
        self.assertEqual(a["legacy_unqualified"]["signal"]["n"], 45)
        mixed = base_accuracy(J["closed"])
        self.assertGreater(mixed["r"], 0, "mixed in, the legacy winners would have hidden the loss")

    def test_legacy_trades_cannot_affect_proven_rule(self):
        """proven_rule is decided before the scan's crowds: a qualified signal crowd is not 'proven' by legacy
        winners, and is by the same number of qualified winners."""
        for proof, proven in ((False, False), (True, True)):
            tmp = tempfile.mkdtemp(prefix="v8journal")
            try:
                w = World(tmp)
                w.scan(T0, ID.Authority.from_states({"ETH": VC, "SOL": VC}))
                w.crowd()
                trades = copy.deepcopy(self.WINNERS) if not proof else [
                    qualified_trade("ETH", "signal", x["r"], x["t_in"]) for x in self.WINNERS]
                out = w.scan(T0 + 1200, ID.Authority.from_states({"ETH": VC, "SOL": VC}),
                             seed=lambda J: J["closed"].extend(trades))
                eth = {r["coin"]: r for r in out["coins"]}["ETH"]
                self.assertEqual((eth["signal"], eth["proven"]), (True, proven), proof)
                self.assertEqual(out["accuracy"]["live"]["n"], 45 if proof else 0)
                self.assertEqual(out["accuracy"]["verdict"], "Proven" if proof else "Promising")
                self.assertEqual(len(w.journal()["closed"]), 45, "every trade is kept")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)


class LegacyOpenSignal(Base):
    """Section 14: a pre-Phase-3 open trade is followed to its close, then stays out of the live record."""

    def test_closes_normally_and_stays_unqualified(self):
        w = World(self.tmp)
        old = legacy_trade("SOL", "signal", None, T0 - 2 * H, closed=False, d=-1, px=120.0)
        auth = ID.Authority.from_states({"ETH": VC, "SOL": VC})      # SOL is verified crypto today: irrelevant
        out = w.scan(T0, auth, seed=lambda J: J["open"].append(copy.deepcopy(old)))
        tr = w.journal()["open"][0]
        self.assertEqual({k: v for k, v in tr.items() if not k.startswith("identity") and k not in ("last_px", "r_now")},
                         old, "kept as it was")
        self.assertEqual((tr["identity_qualified"], tr["identity_unqualified_reason"]), (False, "LEGACY_NO_IDENTITY_PROOF"))
        self.assertEqual(out["accuracy"]["evidence"]["unqualified"]["open_signal"], 1)
        jp = w.part()["journal"]
        self.assertEqual((jp["unqualified_n"], jp["unqualified_trades"][0]["state"],
                          jp["unqualified_trades"][0]["reason"]), (1, "open", "LEGACY_NO_IDENTITY_PROOF"))
        out = w.scan(T0 + 23 * H, auth)                                  # past its 24 hours: closed by the time limit
        J = w.journal()
        self.assertEqual(J["open"], [])
        c = J["closed"][0]
        self.assertEqual((c["coin"], c["why"], c["identity_qualified"]), ("SOL", "time", False))
        self.assertAlmostEqual(c["ret"], -1 * (120.0 / 120.0 - 1) - SM.CFG["cost"], places=9)
        self.assertEqual(c["r"], round(c["ret"] / c["stop_pct"], 3), "return and R are recorded")
        self.assertEqual(out["accuracy"]["live"], {"n": 0})
        self.assertEqual(out["accuracy"]["legacy_unqualified"]["signal"]["n"], 1)
        self.assertEqual(out["accuracy"]["evidence"]["unqualified"]["closed_signal"], 1)

    def test_audit_marks_a_coin_with_a_legacy_open_trade(self):
        w = World(self.tmp)
        auth = ID.Authority.from_states({"ETH": VC, "SOL": VC})
        w.scan(T0, auth)
        w.crowd()
        w.scan(T0 + 1200, auth, seed=lambda J: J["open"].append(legacy_trade("ETH", "signal", None, T0 - H,
                                                                              closed=False, px=2500.0)))
        recs = {r["a"]: r for r in w.part()["records"]}
        self.assertIn("PAPER_LEGACY_NO_IDENTITY_PROOF", recs["ETH"]["x"])
        self.assertIn("PAPER_BUSY", recs["ETH"]["x"], "the legacy trade still holds the coin's one slot")
        self.assertEqual(recs["ETH"]["c"], "SMART_CROWD_SIGNAL")
        self.assertIn("PAPER_LEGACY_NO_IDENTITY_PROOF", T.STEPS)


class NewVerifiedSignal(Base):
    """Section 15: a trade opened through the gate carries its proof and counts exactly as before."""

    def test_provenance_and_live_record(self):
        w = World(self.tmp)
        with offline_env():
            ID.write_authority(self.tmp, {"ETH": {"identity": VC}, "SOL": {"identity": VC}}, T0, "local-%d" % T0)
            w.scan(T0, None)                                             # the scanner's file of this scan
            w.crowd()
            ID.write_authority(self.tmp, {"ETH": {"identity": VC}, "SOL": {"identity": VC}}, T0 + 1200,
                               "local-%d" % (T0 + 1200))
            w.scan(T0 + 1200, None)
        tr = {t["coin"]: t for t in w.journal()["open"]}["ETH"]
        self.assertEqual((tr["identity_state_at_entry"], tr["identity_qualified"], tr["identity_version"],
                          tr["identity_scan_id"], tr["identity_decision"]),
                         (VC, True, ID.VERSION, "local-%d" % (T0 + 1200), VC))
        self.assertTrue(SM.trade_qualified(tr))
        out = w.scan(T0 + 1200 + 25 * H, ID.Authority.from_states({"ETH": VC, "SOL": VC}))
        closed = {t["coin"]: t for t in w.journal()["closed"]}
        c = closed["ETH"]
        self.assertTrue(SM.trade_qualified(c))
        self.assertEqual(out["accuracy"]["live"], SM.live_stats([c]))
        self.assertEqual(out["accuracy"]["live"], base_accuracy(w.journal()["closed"]), "as before: same R and count")
        self.assertEqual(out["accuracy"]["live_info"], SM.live_stats([closed["SOL"]]))
        self.assertEqual(out["accuracy"]["evidence"]["qualified"]["closed_signal"], 1)
        self.assertEqual(out["accuracy"]["legacy_unqualified"]["signal"], {"n": 0})


class IdentityChangesAfterEntry(Base):
    """Section 16: verified at entry, unverified later. No new signal; the old trade keeps its proof and counts."""

    def test_no_hindsight(self):
        w = World(self.tmp)
        w.scan(T0, ID.Authority.from_states({"ETH": VC, "SOL": VC}))
        w.crowd()
        w.scan(T0 + 1200, ID.Authority.from_states({"ETH": VC, "SOL": VC}))
        entry = copy.deepcopy({t["coin"]: t for t in w.journal()["open"]}["ETH"])
        self.assertTrue(SM.trade_qualified(entry))
        later = ID.Authority.from_states({"ETH": UV, "SOL": VC}, scan_id="later")
        out = w.scan(T0 + 1200 + 2 * H, later)                          # the crowd is still within its 24 hours
        eth = {r["coin"]: r for r in out["coins"]}["ETH"]
        self.assertEqual((eth["signal"], eth["side"], eth["identity_block"]["reason"]),
                         (False, None, "IDENTITY_UNVERIFIED"), "no new signal")
        self.assertNotIn("ETH", D.signals(None, None, None, out))
        if NODE:
            a = node_signals(out, "ETH")
            self.assertEqual((a["signals"], a["coins"]), ([], []), "no Analyzer signal")
        still = {t["coin"]: t for t in w.journal()["open"]}["ETH"]
        for k in SM.TRADE_IDENTITY_FIELDS:
            self.assertEqual(still[k], entry[k], k)                     # never rewritten from today's identity
        out = w.scan(T0 + 1200 + 25 * H, later)
        c = {t["coin"]: t for t in w.journal()["closed"]}["ETH"]
        self.assertEqual((c["identity_state_at_entry"], c["identity_qualified"]), (VC, True))
        self.assertEqual(out["accuracy"]["live"]["n"], 1, "it counts: the authority was valid when it was entered")


class NewUnverifiedCrowd(Base):
    """Section 17: an unverified crowd opens nothing and adds nothing to the evidence."""

    def test_no_trade_no_evidence(self):
        w = World(self.tmp)
        auth = ID.Authority.from_states({"ETH": UV, "SOL": UV})
        w.scan(T0, auth)
        w.crowd()
        out = w.scan(T0 + 1200, auth)
        self.assertEqual(w.journal()["open"], [])
        self.assertEqual(out["accuracy"]["evidence"]["qualified"],
                         {"closed_info": 0, "closed_signal": 0, "open_info": 0, "open_signal": 0})
        self.assertEqual(out["accuracy"]["evidence"]["unqualified"],
                         {"closed_info": 0, "closed_signal": 0, "open_info": 0, "open_signal": 0})
        out = w.scan(T0 + 1200 + 25 * H, auth)
        self.assertEqual((out["accuracy"]["live"], out["accuracy"]["live_info"]), ({"n": 0}, {"n": 0}))


class MissingAuthority(Base):
    """Section 18: no authority file. Nothing new opens; every trade keeps the class it had."""

    def test_fail_closed_without_rewriting_history(self):
        w = World(self.tmp)
        auth = ID.Authority.from_states({"ETH": VC, "SOL": VC})
        w.scan(T0, auth)
        w.crowd()
        q_closed = qualified_trade("ETH", "signal", 0.7, T0 - 40 * H)
        q_open = qualified_trade("SOL", "signal", None, T0 - 2 * H, closed=False, px=120.0)
        old = legacy_trade("ETH", "signal", 2.5, T0 - 70 * H)

        def seed(J):
            J["closed"] += [copy.deepcopy(q_closed), copy.deepcopy(old)]
            J["open"].append(copy.deepcopy(q_open))
        with offline_env():
            out = w.scan(T0 + 1200, None, seed=seed)                    # no data/v8/identity_authority.json
        self.assertEqual(out["identity_authority"]["why"], "NO_AUTHORITY_FILE")
        J = w.journal()
        self.assertEqual([t["coin"] for t in J["open"]], ["SOL"], "no new trade opens")
        cl = {t["id"]: t for t in J["closed"]}
        self.assertTrue(SM.trade_qualified(cl[q_closed["id"]]), "qualified history stays qualified")
        self.assertFalse(SM.trade_qualified(cl[old["id"]]), "legacy stays unqualified")
        self.assertEqual(out["accuracy"]["live"], SM.live_stats([q_closed]))
        self.assertEqual(out["accuracy"]["legacy_unqualified"]["signal"]["n"], 1)
        with offline_env():
            out = w.scan(T0 + 23 * H, None)                              # the qualified open trade closes
        sol = {t["coin"]: t for t in w.journal()["closed"]}["SOL"]
        self.assertTrue(SM.trade_qualified(sol))
        self.assertEqual(out["accuracy"]["live"]["n"], 2)


class FreshVerifiedRunUnchanged(Base):
    """Section 20: from an empty journal, verified crypto trades are what the rule always produced; the only
    difference is the additive provenance (the differential parity proves the same against main 82f8d35)."""

    def test_identical_apart_from_provenance(self):
        w = World(self.tmp)
        auth = ID.Authority.from_states({"ETH": VC, "SOL": VC, "BTC": VC})
        w.scan(T0, auth)
        w.crowd()
        out = w.scan(T0 + 1200, auth)
        rows = {r["coin"]: r for r in out["coins"]}
        J = w.journal()
        for tr in J["open"]:
            row = dict(rows[tr["coin"]])
            want = SM.open_trade(row, w.f.mids, T0 + 1200, w.f)
            self.assertEqual({k: v for k, v in tr.items() if k not in SM.TRADE_IDENTITY_FIELDS and k != "kind"}, want)
            self.assertEqual(tr["kind"], "signal" if row["signal"] else "info")
        # the same journal without provenance, closed by the same update_trades: identical closes
        bare = {"open": [{k: v for k, v in t.items() if k not in SM.TRADE_IDENTITY_FIELDS} for t in J["open"]],
                "closed": []}
        SM.update_trades(bare, w.f.mids, T0 + 1200 + 25 * H, w.f)
        out = w.scan(T0 + 1200 + 25 * H, auth)
        mine = [{k: v for k, v in t.items() if k not in SM.TRADE_IDENTITY_FIELDS} for t in w.journal()["closed"]]
        self.assertEqual(mine, bare["closed"])
        self.assertEqual(out["accuracy"]["live"], base_accuracy(bare["closed"]))
        self.assertEqual(out["accuracy"]["live_info"], SM.live_stats([x for x in bare["closed"] if x["kind"] == "info"]))
        self.assertEqual(out["accuracy"]["verdict"], RESEARCH["verdict"])


if __name__ == "__main__":
    unittest.main()
