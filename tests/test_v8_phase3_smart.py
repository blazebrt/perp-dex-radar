"""v8 Phase 3 closure: smart money obeys the same crypto execution identity as every other engine.

A qualifying crowd of proven Hyperliquid traders is a smart-money signal (or an information-only crowd) and a paper
trade only when the coin is VERIFIED_CRYPTO in this scan's identity authority - the file the scanner writes with the
universe it resolved (data/v8/identity_authority.json). For VERIFIED_TRADFI, AMBIGUOUS, UNVERIFIED or a coin no
same-scan authority names, the crowd stays observable but gains no authority anywhere downstream: not in smart.json
as a signal, not as a paper trade, not in the dashboard's signal aggregation, not as an Analyzer trade signal, and
the audit names the identity reason (never SMART_NO_CROWD). For a verified crypto coin nothing changes.

Run from the repository root:  python -m unittest tests.test_v8_phase3_smart -v"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import dashboard as D  # noqa: E402
import scanner as sc  # noqa: E402
import smart as SM  # noqa: E402
from fake_exchange import FakeExchange, install  # noqa: E402
from test_smart import T0, Fake, addr, hourly  # noqa: E402
from v8 import identity as ID  # noqa: E402
from v8 import parts  # noqa: E402

NODE = shutil.which("node")
VC, VT, AM, UV = ID.VERIFIED_CRYPTO, ID.VERIFIED_TRADFI, ID.AMBIGUOUS, ID.UNVERIFIED
NO_GH = {"GITHUB_RUN_ID": "", "V8_SCAN_ID": ""}       # offline scan ids (the time-window rule), in CI too


def offline_env():
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "V8_SCAN_ID")}
    return mock.patch.dict(os.environ, env, clear=True)


def crowd_run(tmp, identity=None):
    """Two scans of the smart-money engine: a snapshot, then two proven traders open ETH shorts (the tested side: a
    signal) and two open SOL longs (the untested side: information only). Returns the second scan's output."""
    f = Fake()
    for c in ("SOL", "ETH"):
        f.candles[c] = hourly(float(f.mids[c]), T0 - 8 * 86400, 8 * 24 + 40)
    jp = os.path.join(tmp, "j.json")
    SM.run(tmp, journal_path=jp, fetch=f, now=T0, identity=identity)
    shutil.copyfile(os.path.join(tmp, "data", "smart_journal.json"), jp)
    f.pos[addr(0)] = [("SOL", 1000.0, 120.0), ("ETH", -20.0, 2500.0)]
    f.pos[addr(1)] = [("SOL", 500.0, 120.0)]
    f.pos[addr(2)] = [("ETH", -20.0, 2500.0)]
    return SM.run(tmp, journal_path=jp, fetch=f, now=T0 + 1200, identity=identity), f


def node_signals(smart_out, coin):
    """analyze.js: testedSignals(coin, {smart}) sources and signalCoins({smart}) coins."""
    js = ("const TA = require(process.argv[1]); const S = JSON.parse(require('fs').readFileSync(process.argv[2]));"
          f"const t = TA.testedSignals({json.dumps(coin)}, {{smart: S}});"
          "console.log(JSON.stringify({signals: t.signals.map((s) => s.src), notes: t.notes.map((n) => n.text),"
          f" coins: TA.signalCoins({{smart: S}}, {T0 + 1300}).map((c) => c.coin)}}));")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        with open(p, "w") as fh:
            json.dump(smart_out, fh)
        r = subprocess.run([NODE, "-e", js, os.path.join(ROOT, "analyze.js"), p], capture_output=True, text=True,
                           timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr[-2000:])
    return json.loads(r.stdout)


class SmartIdentityGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v8smart")
        self.saved = sc.FETCH

    def tearDown(self):
        sc.FETCH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def records(self):
        return {r["a"]: r for r in parts.read(self.tmp, "smart")["records"]}

    # ---- VERIFIED_CRYPTO: unchanged
    def test_verified_crypto_signal_and_paper_trade_unchanged(self):
        out, f = crowd_run(self.tmp, ID.Authority.from_states({"ETH": VC, "SOL": VC}))
        rows = {r["coin"]: r for r in out["coins"]}
        eth, sol = rows["ETH"], rows["SOL"]
        # exactly what the rule (signal_of) says on the observed crowd
        for r in (eth, sol):
            side, text, tested = SM.signal_of(r)
            self.assertEqual((r["side"], r["text"], r["signal"], r["info"]),
                             (side, text, bool(side) and bool(tested), bool(side) and tested is False))
            self.assertEqual(r["identity"], VC)
            self.assertNotIn("identity_block", r)
        self.assertEqual((eth["side"], eth["signal"], sol["side"], sol["info"]), ("short", True, "long", True))
        self.assertEqual(out["coins"][0]["coin"], "ETH", "signals first, as before")
        self.assertEqual(sorted((t["coin"], t["kind"]) for t in out["open"]), [("ETH", "signal"), ("SOL", "info")])
        tr = next(t for t in out["open"] if t["coin"] == "ETH")
        want = SM.open_trade(eth, f.mids, T0 + 1200, f)              # the same stop and holding period
        self.assertEqual({k: tr[k] for k in want}, want)
        self.assertEqual(self.records()["ETH"]["c"], "SMART_CROWD_SIGNAL")
        self.assertEqual(self.records()["SOL"]["c"], "SMART_CROWD_INFO")
        self.assertIn("ETH", D.signals(None, None, None, out))
        if NODE:
            a = node_signals(out, "ETH")
            self.assertEqual((a["signals"], a["coins"]), (["smart"], ["ETH"]))

    # ---- UNVERIFIED, VERIFIED_TRADFI, AMBIGUOUS, missing: observable, never actionable
    def check_blocked(self, out, reason, state):
        rows = {r["coin"]: r for r in out["coins"]}
        eth = rows["ETH"]
        self.assertEqual((eth["n_short"], eth["new_short"], eth["traders"]), (2, 2, 2), "positioning stays observable")
        self.assertGreater(eth["usd_short"], 0)
        self.assertEqual((eth["side"], eth["signal"], eth["info"], eth["tested"], eth["proven"]),
                         (None, False, False, False, False))
        self.assertEqual(eth["identity"], state)
        blk = eth["identity_block"]
        self.assertEqual((blk["reason"], blk["state"], blk["crowd_side"], blk["crowd_signal"]),
                         (reason, state, "short", True))
        self.assertNotIn("ETH", {t["coin"] for t in out["open"]}, "no paper trade on a blocked crowd")
        with open(os.path.join(self.tmp, "data", "smart_journal.json")) as fh:
            J = json.load(fh)
        self.assertNotIn("ETH", {t["coin"] for t in J["open"] + J["closed"]})
        r = self.records()["ETH"]
        self.assertEqual(r["c"], reason)
        self.assertIn("SMART_CROWD_IDENTITY_BLOCKED", r.get("x") or [])
        self.assertNotEqual(r["c"], "SMART_NO_CROWD")
        self.assertEqual((r["o"]["crowd_side"], r["o"]["identity"]), ("short", state))
        self.assertNotIn("ETH", D.signals(None, None, None, out), "not an actionable dashboard signal")
        if NODE:
            a = node_signals(out, "ETH")
            self.assertEqual((a["signals"], a["coins"]), ([], []), "no Analyzer smart signal")
            self.assertIn("not verified as a crypto coin", a["notes"][0])
        part = parts.read(self.tmp, "smart")
        self.assertEqual(part["coverage"]["unaccounted"], 0)
        self.assertIn("ETH", part["stages"]["identity_blocked"])

    def test_unverified_crowd_is_blocked(self):
        out, _ = crowd_run(self.tmp, ID.Authority.from_states({"ETH": UV, "SOL": VC}))
        self.check_blocked(out, "IDENTITY_UNVERIFIED", UV)
        sol = {r["coin"]: r for r in out["coins"]}["SOL"]
        self.assertTrue(sol["info"], "a verified coin next to it is unaffected")
        self.assertIn(("SOL", "info"), {(t["coin"], t["kind"]) for t in out["open"]})

    def test_tradfi_crowd_is_blocked(self):
        out, _ = crowd_run(self.tmp, ID.Authority.from_states({"ETH": [VT, "TRADFI_CLASSIFIED"], "SOL": VC}))
        self.check_blocked(out, "TRADFI_CLASSIFIED", VT)

    def test_inherited_tradfi_crowd_is_blocked(self):
        out, _ = crowd_run(self.tmp, ID.Authority.from_states({"ETH": [VT, "TRADFI_EXPOSURE_EXCLUDED"], "SOL": VC}))
        self.check_blocked(out, "TRADFI_EXPOSURE_EXCLUDED", VT)

    def test_ambiguous_crowd_is_blocked(self):
        out, _ = crowd_run(self.tmp, ID.Authority.from_states({"ETH": [AM, "AMBIGUOUS_EXPOSURE"], "SOL": VC}))
        self.check_blocked(out, "AMBIGUOUS_EXPOSURE", AM)
        self.assertEqual(self.records()["ETH"]["h"], "CONFLICTED")

    def test_coin_missing_from_the_authority_fails_closed(self):
        out, _ = crowd_run(self.tmp, ID.Authority.from_states({"SOL": VC}))
        self.check_blocked(out, "IDENTITY_AUTHORITY_MISSING", None)
        self.assertEqual({r["coin"]: r for r in out["coins"]}["ETH"]["identity_block"]["in_authority"], False)

    def test_no_authority_at_all_fails_closed(self):
        with offline_env():
            out, _ = crowd_run(self.tmp)                      # no scanner file in this folder
        self.check_blocked(out, "IDENTITY_AUTHORITY_MISSING", None)
        sol = {r["coin"]: r for r in out["coins"]}["SOL"]
        self.assertEqual((sol["info"], sol["identity_block"]["reason"]), (False, "IDENTITY_AUTHORITY_MISSING"))
        self.assertEqual(out["open"], [])
        self.assertEqual((out["identity_authority"]["ok"], out["identity_authority"]["why"]), (False, "NO_AUTHORITY_FILE"))


class SameScanAuthority(unittest.TestCase):
    """The mechanism: the scanner writes the authority; smart reads it only when it belongs to the same scan."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v8auth")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, states, ts, scan_id, version=ID.VERSION):
        coins = {t: {"identity": st} for t, st in states.items()}
        ID.write_authority(self.tmp, coins, ts, scan_id)
        if version != ID.VERSION:
            p = os.path.join(self.tmp, ID.AUTHORITY_FILE)
            rec = json.load(open(p))
            rec["identity_version"] = version
            json.dump(rec, open(p, "w"))

    def test_rules(self):
        with offline_env():
            self.assertEqual(ID.load_authority(self.tmp, T0, "local-1").why, "NO_AUTHORITY_FILE")
            self.write({"ETH": VC, "XYZ": UV}, T0, "local-%d" % T0)
            a = ID.load_authority(self.tmp, T0 + 1200, "local-%d" % (T0 + 1200))
            self.assertEqual((a.ok, a.why, a.state("ETH"), a.state("XYZ"), a.state("NOPE")), (True, "SAME_SCAN", VC, UV, None))
            b = ID.load_authority(self.tmp, T0 + ID.AUTHORITY_MAX_AGE_S + 1, "local-x")
            self.assertEqual((b.ok, b.why, b.state("ETH")), (False, "STALE", None))
        # GitHub Actions: the same workflow run, or nothing
        self.write({"ETH": VC}, T0, "gh-77-1")
        self.assertEqual(ID.load_authority(self.tmp, T0, "gh-77-1").why, "SAME_SCAN")
        c = ID.load_authority(self.tmp, T0, "gh-78-1")
        self.assertEqual((c.ok, c.why, c.state("ETH")), (False, "OTHER_SCAN", None))
        self.assertEqual(ID.load_authority(self.tmp, T0, "local-%d" % T0).why, "OTHER_SCAN")
        self.write({"ETH": VC}, T0, "gh-77-1", version="v8.identity/1")
        self.assertEqual(ID.load_authority(self.tmp, T0, "gh-77-1").why, "OTHER_IDENTITY_VERSION:v8.identity/1")
        with open(os.path.join(self.tmp, ID.AUTHORITY_FILE), "w") as fh:
            fh.write("{not json")
        self.assertFalse(ID.load_authority(self.tmp, T0, "gh-77-1").ok)

    def test_smart_reads_the_scanners_file_from_its_own_scan(self):
        with offline_env():
            self.write({"ETH": VC, "SOL": UV}, T0, "local-%d" % T0)
            out, _ = crowd_run(self.tmp)
        rows = {r["coin"]: r for r in out["coins"]}
        self.assertEqual((rows["ETH"]["signal"], rows["ETH"]["identity"]), (True, VC))
        self.assertEqual((rows["SOL"]["info"], rows["SOL"]["identity_block"]["reason"]), (False, "IDENTITY_UNVERIFIED"))
        self.assertEqual((out["identity_authority"]["ok"], out["identity_authority"]["why"]), (True, "SAME_SCAN"))
        self.assertEqual(out["identity_authority"]["source"], "data/v8/identity_authority.json")

    def test_scanner_writes_every_universe_coin(self):
        fx = FakeExchange(n_coins=24, days=4, seed=2)
        restore = install(fx)
        sc.KNOWN_CRYPTO = sc.KNOWN_CRYPTO - {"FAKE03"}          # one coin without identity evidence
        try:
            with offline_env():
                sc.run(self.tmp, replay_days=0)
                coins, _, _ = sc.build_universe()
        finally:
            restore()
        with open(os.path.join(self.tmp, ID.AUTHORITY_FILE)) as fh:
            rec = json.load(fh)
        self.assertEqual((rec["schema"], rec["identity_version"]), (ID.AUTHORITY_SCHEMA, ID.VERSION))
        self.assertEqual(set(rec["states"]), set(coins))
        self.assertEqual(rec["states"]["FAKE03"], [UV, "IDENTITY_UNVERIFIED"])
        self.assertEqual(rec["states"]["BTC"], [VC, "CRYPTO"])
        self.assertTrue(rec["scan_id"].startswith("local-"))


if __name__ == "__main__":
    unittest.main()
