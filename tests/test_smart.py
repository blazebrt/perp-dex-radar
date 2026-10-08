"""Smart money engine: who is proven, entries by size, one vote per trader, signals and the paper record."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import smart as SM  # noqa: E402
import scanner as sc  # noqa: E402
from v8 import identity as ID  # noqa: E402

# v8 Phase 3: the test world's coins are verified crypto (in a scan, the scanner's identity authority says so)
WORLD = ID.Authority.from_states({c: ID.VERIFIED_CRYPTO for c in ("BTC", "ETH", "SOL", "PEPE")})
# entry-time identity proof of a paper trade opened under that world (smart.stamp_identity)
QUALIFIED = {"identity_state_at_entry": ID.VERIFIED_CRYPTO, "identity_qualified": True, "identity_version": ID.VERSION,
             "identity_scan_id": "given", "identity_decision": ID.VERIFIED_CRYPTO}

T0 = 1791000000


def row(addr, av, all_pnl, month_pnl, month_vlm=5e6, week_pnl=0.0):
    return {"ethAddress": addr, "accountValue": str(av), "windowPerformances": [
        ["day", {"pnl": "0", "roi": "0", "vlm": "0"}], ["week", {"pnl": str(week_pnl), "roi": "0", "vlm": "1"}],
        ["month", {"pnl": str(month_pnl), "roi": str(month_pnl / av), "vlm": str(month_vlm)}],
        ["allTime", {"pnl": str(all_pnl), "roi": "1", "vlm": str(month_vlm * 5)}]]}


def addr(i):
    return "0x%040x" % i


class Fake:
    """The Hyperliquid API: a leaderboard, account states that can change, mids and hourly candles."""

    def __init__(self):
        self.board = {"leaderboardRows": [row(addr(i), 400_000, 1_000_000 - i * 10_000, 20_000) for i in range(6)]}
        self.pos = {addr(i): [] for i in range(6)}
        self.mids = {"BTC": "100000", "ETH": "2500", "kPEPE": "0.012", "SOL": "120"}
        self.candles = {}      # coin -> list of candle dicts

    def __call__(self, url, body=None, timeout=25):
        if url == SM.LEADERBOARD:
            return self.board
        t = body["type"]
        if t == "clearinghouseState":
            ps = [{"position": {"coin": c, "szi": str(sz), "positionValue": str(abs(sz) * px), "entryPx": str(px),
                                "unrealizedPnl": "100"}} for c, sz, px in self.pos.get(body["user"], [])]
            return {"marginSummary": {"accountValue": "400000"}, "assetPositions": ps}
        if t == "allMids":
            return self.mids
        if t == "candleSnapshot":
            return self.candles.get(body["req"]["coin"], [])
        raise ValueError(t)


def hourly(px, start, hours, low=None, high=None):
    return [{"t": (start + k * 3600) * 1000, "o": str(px), "h": str(high or px), "l": str(low or px), "c": str(px)}
            for k in range(hours)]


class Selection(unittest.TestCase):
    def test_proven_traders_only(self):
        board = {"leaderboardRows": [
            row(addr(1), 400_000, 2_000_000, 50_000),
            row(addr(2), 400_000, 50_000, 10_000),                    # not enough made over time
            row(addr(3), 10_000, 900_000, 1_000),                     # account too small
            row(addr(4), 400_000, 900_000, -100_000),                 # lost 25% of the account this month
            row(addr(5), 400_000, 900_000, 10_000, month_vlm=1e9),    # a market maker
            row(addr(6), 400_000, 900_000, 10_000, month_vlm=0),      # did not trade this month
            row(addr(7), 400_000, 3_000_000, -20_000),                # a small loss this month is fine
            {"ethAddress": None}]}
        got = SM.select_traders(board)
        self.assertEqual([t["addr"] for t in got], [addr(7), addr(1)], "most profitable first")
        self.assertEqual(got[0]["id"], SM.hid(addr(7)))
        self.assertNotIn(addr(7), json.dumps([{k: v for k, v in t.items() if k != "addr"} for t in got]))


class Changes(unittest.TestCase):
    def snap(self, **pos):
        return {"a": {"av": 400_000.0, "pos": {c: [sz, sz * px, px, 0.0] for c, (sz, px) in pos.items()}}}

    def test_entries_by_size_not_by_price(self):
        prev = self.snap(BTC=(1.0, 100_000), ETH=(-40.0, 2500), SOL=(1000.0, 120))
        cur = self.snap(BTC=(1.0, 130_000), ETH=(40.0, 2500), SOL=(2000.0, 120), kPEPE=(5e6, 0.012))
        got = {e[1]: e for e in SM.changes(prev, cur, T0)}
        self.assertNotIn("BTC", got, "the price rose; the size did not")
        self.assertEqual(got["ETH"][2:4], [1, 100_000], "a flip opens the new side in full")
        self.assertEqual(got["SOL"][3], 120_000, "only the added size counts")
        self.assertEqual(got["kPEPE"][2:4], [1, 60_000])
        self.assertEqual(got["SOL"][4], 0.3, "share of the account")

    def test_small_or_new_traders_give_no_entries(self):
        prev = self.snap(BTC=(0.1, 100_000))
        cur = self.snap(BTC=(0.2, 100_000), SOL=(100.0, 120))
        self.assertEqual(SM.changes(prev, cur, T0), [], "$10k and $12k are under the $25k entry size")
        self.assertEqual(SM.changes({}, self.snap(BTC=(5.0, 100_000)), T0), [], "first time seen: not an entry")


class Aggregate(unittest.TestCase):
    def test_one_vote_each_weighted_by_conviction(self):
        traders = [{"id": "w", "all": 5e6}, {"id": "x", "all": 1e6}, {"id": "y", "all": 1e6}]
        snap = {"w": {"av": 1_000_000.0, "pos": {"BTC": [100.0, 10_000_000.0, 100_000.0, 5.0]}},     # whale long
                "x": {"av": 100_000.0, "pos": {"BTC": [-1.0, -100_000.0, 100_000.0, -1.0]}},       # 1x short
                "y": {"av": 100_000.0, "pos": {"BTC": [-1.5, -150_000.0, 100_000.0, -1.0],
                                               "kPEPE": [1e7, 120_000.0, 0.012, 1.0]}}}
        mids = {"BTC": "101000", "kPEPE": "0.013"}
        rows = {r["coin"]: r for r in SM.aggregate(snap, traders, mids, [], T0)}
        b = rows["BTC"]
        self.assertEqual((b["n_long"], b["n_short"]), (1, 2))
        self.assertAlmostEqual(b["long_share"], 2.0 / (2.0 + 1.0 + 1.5), places=3, msg="the whale counts 2x at most")
        self.assertEqual(b["usd_long"], 10_000_000)
        p = rows["PEPE"]
        self.assertEqual(p["hl"], "kPEPE")
        self.assertAlmostEqual(p["price"], 0.000013, places=9, msg="kPEPE prices are per 1000")
        self.assertAlmostEqual(p["entry_long"], 0.000012, places=9)

    def test_entries_in_the_last_day_and_signals(self):
        traders = [{"id": "a", "all": 1e6}]
        entries = [[T0 - 3600, "SOL", 1, 50_000, 0.1, "a"], [T0 - 1800, "SOL", 1, 60_000, 0.1, "b"],
                   [T0 - 600, "SOL", 1, 70_000, 0.1, "b"], [T0 - 2 * 86400, "SOL", -1, 90_000, 0.2, "c"],
                   [T0 - 900, "ETH", -1, 50_000, 0.1, "a"]]
        rows = {r["coin"]: r for r in SM.aggregate({}, traders, {"SOL": "120"}, entries, T0)}
        self.assertEqual((rows["SOL"]["new_long"], rows["SOL"]["new_short"]), (2, 0), "two traders; the old short is out")
        self.assertEqual(rows["SOL"]["new_long_usd"], 180_000)
        self.assertEqual(SM.signal_of(rows["SOL"])[::2], ("long", False), "a long crowd is information only")
        self.assertIsNone(SM.signal_of(rows["ETH"])[0], "one trader is not enough")
        short = dict(rows["ETH"], new_short=3, new_long=1)
        self.assertEqual(SM.signal_of(short)[::2], ("short", True), "3 shorts against 1 long: the tested signal")
        self.assertIsNone(SM.signal_of(dict(short, new_long=2))[0], "net of the other side")
        cfg = dict(SM.CFG, signal="consensus", signal_sides=("long", "short"))
        r = {"traders": 4, "n_long": 3, "n_short": 1, "long_share": 0.7, "new_long": 0, "new_short": 0}
        self.assertEqual(SM.signal_of(r, cfg)[::2], ("long", True))
        self.assertIsNone(SM.signal_of(dict(r, long_share=0.55), cfg)[0])


class PaperTrades(unittest.TestCase):
    def test_stop_from_the_hourly_low_and_time_exit(self):
        f = Fake()
        f.candles["SOL"] = hourly(100.0, T0 - 8 * 86400, 8 * 24)          # flat: the minimum stop applies
        tr = SM.open_trade({"coin": "SOL", "hl": "SOL", "side": "long", "text": "x"}, {"SOL": "100"}, T0, f)
        self.assertEqual(tr["stop_pct"], SM.CFG["min_stop"])
        J = {"open": [tr], "closed": []}
        f.candles["SOL"] = hourly(100.0, T0, 3) + hourly(100.0, T0 + 3 * 3600, 1, low=98.0)
        SM.update_trades(J, {"SOL": "99"}, T0 + 4 * 3600, f)
        self.assertEqual(J["open"], [])
        c = J["closed"][0]
        self.assertEqual(c["why"], "stop")
        self.assertAlmostEqual(c["r"], -1 - SM.CFG["cost"] / SM.CFG["min_stop"], places=2)
        tr2 = SM.open_trade({"coin": "SOL", "hl": "SOL", "side": "short", "text": "x"}, {"SOL": "100"}, T0, f)
        J = {"open": [tr2], "closed": []}
        f.candles["SOL"] = hourly(99.0, T0, 30)
        SM.update_trades(J, {"SOL": "99"}, T0 + 10 * 3600, f)
        self.assertEqual(len(J["open"]), 1, "not due yet")
        self.assertGreater(J["open"][0]["r_now"], 0)
        SM.update_trades(J, {"SOL": "99"}, T0 + 25 * 3600, f)
        self.assertEqual(J["closed"][0]["why"], "time")
        self.assertAlmostEqual(J["closed"][0]["ret"], 0.01 - SM.CFG["cost"], places=5)

    def test_the_live_record_decides_after_enough_trades(self):
        research = {"verdict": "Promising", "tone": "warn", "why": "w", "tested": {"n": 31, "r": 0.14}}
        # v8 Phase 3: the live record is made of trades with entry-time identity proof
        win = [dict(QUALIFIED, kind="signal", r=0.6, ret=0.01), dict(QUALIFIED, kind="signal", r=-0.2, ret=-0.004)] * 25
        self.assertEqual(SM.accuracy(research, {"closed": win[:10]})["verdict"], "Promising", "too few live trades")
        self.assertEqual(SM.accuracy(research, {"closed": win})["verdict"], "Proven")
        lose = [dict(QUALIFIED, kind="signal", r=-0.3, ret=-0.01), dict(QUALIFIED, kind="signal", r=0.2, ret=0.004)] * 25
        self.assertEqual(SM.accuracy(research, {"closed": lose})["verdict"], "No edge")
        info = [dict(x, kind="info") for x in win]
        self.assertEqual(SM.accuracy(research, {"closed": info})["verdict"], "Promising", "information trades never count")
        legacy = [{k: v for k, v in x.items() if not k.startswith("identity")} for x in win]
        self.assertEqual(SM.accuracy(research, {"closed": legacy})["verdict"], "Promising",
                         "trades without entry-time identity proof never count")

    def test_live_stats(self):
        self.assertEqual(SM.live_stats([]), {"n": 0})
        s = SM.live_stats([{"r": 1.0, "ret": 0.02}, {"r": -1.0, "ret": -0.015}, {"r": 0.5, "ret": 0.01}])
        self.assertEqual((s["n"], s["win"], s["r"]), (3, 0.667, 0.167))
        self.assertIsNotNone(s["t"])


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = sc.FETCH

    def tearDown(self):
        sc.FETCH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_three_scans(self):
        f = Fake()
        sc.FETCH = f
        for c in ("SOL", "ETH"):
            f.candles[c] = hourly(float(f.mids[c]), T0 - 8 * 86400, 8 * 24 + 40)
        jp = os.path.join(self.tmp, "j.json")
        out1 = SM.run(self.tmp, journal_path=jp, fetch=f, now=T0, identity=WORLD)
        self.assertEqual(out1["traders_n"], 6)
        self.assertEqual(out1["recent"], [], "the first scan only takes a snapshot")
        shutil.copyfile(os.path.join(self.tmp, "data", "smart_journal.json"), jp)
        f.pos[addr(0)] = [("SOL", 1000.0, 120.0), ("ETH", -20.0, 2500.0)]
        f.pos[addr(1)] = [("SOL", 500.0, 120.0)]
        f.pos[addr(2)] = [("ETH", -20.0, 2500.0)]
        out2 = SM.run(self.tmp, journal_path=jp, fetch=f, now=T0 + 1200, identity=WORLD)
        coins = {c["coin"]: c for c in out2["coins"]}
        self.assertEqual((coins["ETH"]["side"], coins["ETH"]["signal"]), ("short", True), "two proven traders shorted")
        self.assertEqual((coins["SOL"]["side"], coins["SOL"]["signal"], coins["SOL"]["info"]), ("long", False, True))
        self.assertEqual(out2["coins"][0]["coin"], "ETH", "signals first")
        self.assertEqual(len(out2["recent"]), 4)
        self.assertEqual(sorted((t["coin"], t["kind"]) for t in out2["open"]), [("ETH", "signal"), ("SOL", "info")])
        self.assertNotIn(addr(0), json.dumps(out2), "addresses are never published")
        shutil.copyfile(os.path.join(self.tmp, "data", "smart_journal.json"), jp)
        out3 = SM.run(self.tmp, journal_path=jp, fetch=f, now=T0 + 1200 + 25 * 3600, identity=WORLD)
        self.assertEqual(out3["open"], [], "closed after the holding time")
        self.assertEqual((out3["accuracy"]["live"]["n"], out3["accuracy"]["live_info"]["n"]), (1, 1),
                         "the signal and the information side are counted apart")
        self.assertIn(out3["accuracy"]["verdict"], ("Testing", "Promising", "Proven", "Mixed", "No edge"))
        with open(os.path.join(self.tmp, "data", "smart.json")) as fh:
            self.assertEqual(json.load(fh)["version"], SM.VERSION)


if __name__ == "__main__":
    unittest.main()
