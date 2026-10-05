"""Tests for the coin picks (picks.py). Run from the repository root:

    python -m unittest discover -s tests -v

No network is needed: tests/fake_exchange.py stands in for the exchanges. The swing scores were checked
against the research code on three years of real candles (tools/research/parity_picks.py): identical."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import picks as P  # noqa: E402
import scanner as sc  # noqa: E402
from fake_exchange import FakeExchange  # noqa: E402

DAY = 86400
T0 = 86400 * 19700


def days(rows, t0=T0, step=DAY):
    return [{"t": t0 + i * step, "o": o, "h": h, "l": l, "c": c, "qv": 1e7} for i, (o, h, l, c) in enumerate(rows)]


def x_long_perfect():
    return {"up90": 0.10, "rsi": 55.0, "squeeze": 0.1, "dd90": -0.2, "atrp": 0.04, "mom30": 0.05, "higher_low": 0.02,
            "btc_up": True, "volup": 1.5, "trend50": 0.02, "lower_high": False, "trend4h": 0.01, "rs30": 0.03,
            "updown": 1.3, "vwap30": 0.01}


class Indicators(unittest.TestCase):
    def test_rsi_extremes(self):
        up = [float(i) for i in range(1, 40)]
        self.assertAlmostEqual(P.rsi(up, 14)[-1], 100.0)
        down = list(reversed(up))
        self.assertAlmostEqual(P.rsi(down, 14)[-1], 0.0)
        self.assertIsNone(P.rsi(up, 14)[5], "needs 14 changes first")

    def test_rsi_matches_wilder_by_hand(self):
        c = [10, 11, 10.5, 11.5, 12, 11, 11.2, 12.5, 12, 13, 12.8, 13.5, 14, 13.2, 13.8, 14.5]
        n = 3
        ups = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
        dns = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
        au, ad = ups[0], dns[0]
        for u, d in zip(ups[1:], dns[1:]):
            au, ad = au + (u - au) / n, ad + (d - ad) / n
        self.assertAlmostEqual(P.rsi(c, n)[-1], 100 - 100 / (1 + au / ad))

    def test_pct_rank_matches_pandas_average_rank(self):
        xs = [None] * 5 + [3.0, 1.0, 2.0, 2.0, 5.0, 2.0]
        # last value 2.0 among [3,1,2,2,5,2]: one below, three equal -> (1 + (3 + 1) / 2) / 6
        self.assertAlmostEqual(P.pct_rank_last(xs, 90, 3), (1 + 2) / 6)
        self.assertIsNone(P.pct_rank_last(xs, 90, 10))

    def test_bollinger_width_of_a_flat_line_is_zero(self):
        self.assertEqual(P.bb_width([5.0] * 25)[-1], 0.0)


class Scores(unittest.TestCase):
    def test_perfect_long_scores_100(self):
        x = x_long_perfect()
        self.assertEqual(P.points(P.long_checks(x), P.LONG_W), 100)

    def test_partial_credit(self):
        x = dict(x_long_perfect(), up90=0.40, rsi=42.0, squeeze=0.3, atrp=0.06)
        cr = P.long_checks(x)
        self.assertEqual((cr["near_low"], cr["rsi"], cr["squeeze"], cr["calm"]), (0.4, 0.4, 0.4, 0.5))

    def test_short_mirror(self):
        x = dict(x_long_perfect(), trend50=-0.1, mom30=-0.2, rsi=56.0, up90=0.5, lower_high=True, trend4h=-0.01,
                 rs30=-0.1, updown=0.7, vwap30=-0.03, squeeze=0.8, atrp=0.09, dd90=-0.5, volup=0.8,
                 higher_low=-0.05, btc_up=False)
        self.assertEqual(P.points(P.short_checks(x), P.SHORT_W), 100)
        self.assertLess(P.points(P.long_checks(x), P.LONG_W), 60)

    def test_weights_add_to_100(self):
        for W in (P.LONG_W, P.SHORT_W, P.DAY_W):
            self.assertEqual(sum(W.values()), 100)

    def test_extra_checks_are_capped(self):
        ex = [("a", "A", True, 6, "", "g", True), ("b", "B", True, 6, "", "g", True)]
        self.assertEqual(P.extra_points(ex), P.CFG["extra_max"])
        ex = [("a", "A", False, 6, "", "g", True), ("b", "B", False, 6, "", "g", True)]
        self.assertEqual(P.extra_points(ex), -P.CFG["extra_max"])

    def test_smart_money_direction(self):
        sm = [5, 1, 900_000, 100_000, None]
        lg = {e[0]: e for e in P.extra_checks("long", {}, sm, None, 0.00005, None, 2e6)}
        sh = {e[0]: e for e in P.extra_checks("short", {}, sm, None, 0.00005, None, 2e6)}
        self.assertIs(lg["smart"][2], True)
        self.assertIs(sh["smart"][2], False)
        self.assertIsNone(lg["lev"][2], "no Gate.io data: no points either way")

    def test_tested_extra_checks_follow_the_evidence(self):
        gs = {"oi7": 0.12, "px7": 0.08, "liq3": 0.7, "top0": 1.0, "top1": 1.1, "top7": 0.1}
        lg = {e[0]: e for e in P.extra_checks("long", {}, None, gs, 0.0005, {"mc": 1e9, "vol": 4e8}, 2e6, 0.03)}
        self.assertIs(lg["lev"][2], False, "leverage piling into a rise is a minus for longs")
        self.assertIs(lg["flush"][2], True)
        self.assertIs(lg["supply"][2], False, "3% more supply in 30 days is a minus for longs")
        self.assertIs(lg["turnover"][2], False, "volume 40% of the market cap: overheated")
        self.assertIsNone(lg["funding"][2], "funding is information only for longs")
        sh = {e[0]: e for e in P.extra_checks("short", {}, None, gs, 0.0005, {"mc": 1e9, "vol": 4e8}, 2e6, 0.03)}
        self.assertIs(sh["supply"][2], True, "unlocks help shorts")
        self.assertIs(sh["funding"][2], False, "shorting into high funding did worse")
        pts = P.extra_points(list(P.extra_checks("long", {}, None, gs, 0.0005, {"mc": 1e9, "vol": 4e8}, 2e6, 0.03)))
        self.assertLess(pts, 0)

    def test_every_extra_check_has_seven_fields(self):
        for side in ("long", "short"):
            for e in P.extra_checks(side, {}, None, None, None, None, 2e6):
                self.assertEqual(len(e), 7)


class Supply(unittest.TestCase):
    def test_growth_over_thirty_days(self):
        now = T0 + 40 * DAY + 3600
        J = {"supply": {"ABC": [[T0 + i * DAY, 100.0 + i] for i in range(41)]}}
        g = P.supply_growth(J, "ABC", now)
        self.assertAlmostEqual(g, 140.0 / 105.0 - 1)  # 35 days back is the oldest snapshot used
        self.assertIsNone(P.supply_growth(J, "XYZ", now))

    def test_update_keeps_one_snapshot_a_day(self):
        J = {"supply": {"ABC": [[T0, 100.0]]}}
        cg = {"coins": {"ABC": {"circ": 101.0}}}
        P.supply_update(J, cg, T0 + 3600)
        P.supply_update(J, {"coins": {"ABC": {"circ": 102.0}}}, T0 + 7200)
        self.assertEqual(J["supply"]["ABC"], [[T0, 102.0]])
        P.supply_update(J, cg, T0 + DAY + 60)
        self.assertEqual(len(J["supply"]["ABC"]), 2)


FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
NOW_FIX = 1791106800  # 2026-10-04 09:40 UTC, when the fixtures were saved

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Plasma (XPL) price surges as stablecoin deposits jump</title><description>XPL rallies</description>
<pubDate>Sun, 04 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Bitcoin slides as ETF outflows grow</title><description>BTC drops</description>
<pubDate>Sun, 04 Oct 2026 07:00:00 GMT</pubDate></item>
<item><title>NEAR protocol upgrade goes live</title><description>near</description>
<pubDate>Sun, 04 Oct 2026 06:00:00 GMT</pubDate></item>
<item><title>Old story about Plasma</title><description>x</description>
<pubDate>Mon, 21 Sep 2026 06:00:00 GMT</pubDate></item>
</channel></rss>"""


class Sentiment(unittest.TestCase):
    def test_stocktwits_thin_coin(self):
        with open(os.path.join(FIX, "stocktwits_XPL.json")) as fh:
            r = P.stocktwits_parse(json.load(fh), "XPL", NOW_FIX)
        self.assertEqual((r["bull"], r["bear"]), (7, 8))
        self.assertLess(r["posts_day"], 1)
        self.assertEqual(r["watchers"], 449)

    def test_stocktwits_busy_coin(self):
        with open(os.path.join(FIX, "stocktwits_BTC.json")) as fh:
            r = P.stocktwits_parse(json.load(fh), "BTC", NOW_FIX)
        self.assertGreater(r["posts_day"], 100)
        self.assertGreater(r["bull_share"], 0.8)
        self.assertTrue(r["week"])

    def test_apewisdom(self):
        with open(os.path.join(FIX, "apewisdom.json")) as fh:
            page = json.load(fh)
        old = sc.FETCH
        sc.FETCH = lambda url, body=None, timeout=25: page
        try:
            a = P.apewisdom(None, NOW_FIX)
        finally:
            sc.FETCH = old
        self.assertEqual(a["coins"]["BTC"]["rank"], 1)
        self.assertIn("mentions", a["coins"]["ETH"])

    def test_news_matching_and_tone(self):
        old = P.get_text
        P.get_text = lambda url, timeout=30: RSS
        try:
            feed = P.news(None, NOW_FIX)
        finally:
            P.get_text = old
        self.assertEqual(len(feed["items"]), 3, "same headline from 5 feeds counted once, old news dropped")
        xpl = P.news_for("XPL", "Plasma", feed)
        self.assertEqual(xpl["n"], 1)
        self.assertGreater(xpl["tone"], 0)
        self.assertIn("link", xpl["top"][0], "headlines keep their link for the analyzer")
        btc = P.news_for("BTC", "Bitcoin", feed)
        self.assertLess(btc["tone"], 0)
        self.assertIsNone(P.news_for("NEAR", None, feed), "NEAR as a word is too common to match by ticker")

    def test_combined_score_is_ranked_against_the_other_coins(self):
        st = {"coins": {
            "AAA": {"t": NOW_FIX, "bull": 30, "bear": 2, "posts_day": 20},
            "BBB": {"t": NOW_FIX, "bull": 10, "bear": 10, "posts_day": 5},
            "CCC": {"t": NOW_FIX, "bull": 2, "bear": 12, "posts_day": 3},
            "DDD": {"t": NOW_FIX, "bull": 15, "bear": 5, "posts_day": 8},
            "EEE": {"t": NOW_FIX, "bull": 3, "bear": 1, "posts_day": 1},
            "FFF": {"t": NOW_FIX, "bull": 1, "bear": 1, "posts_day": 1}}}
        sm = {"AAA": [3, 1, 900_000, 100_000, None], "BBB": [1, 1, 300_000, 300_000, None],
              "CCC": [1, 3, 100_000, 900_000, None], "DDD": [2, 1, 500_000, 200_000, None],
              "EEE": [1, 0, 30_000, 0, None], "FFF": [1, 1, 400_000, 100_000, None]}
        sents = {t: P.sentiment_of(t, None, {"coins": {"AAA": {"rank": 2}}}, None, st, None, None, sm[t]) for t in sm}
        P.sentiment_rank(sents)
        self.assertEqual(sents["AAA"]["trending"], 2)
        self.assertGreater(sents["AAA"]["score"], sents["BBB"]["score"])
        self.assertGreater(sents["BBB"]["score"], sents["CCC"]["score"])
        self.assertEqual(sents["AAA"]["label"], "Bullish")
        self.assertEqual(sents["CCC"]["label"], "Bearish")
        self.assertEqual([p[0] for p in sents["AAA"]["parts"]], ["Stocktwits", "Hyperliquid top traders"])
        self.assertIsNone(sents["EEE"]["score"], "one source (top traders under $50k) is not enough for a score")
        self.assertIsNone(sents["FFF"]["score"], "two tagged posts are not a Stocktwits reading")
        self.assertTrue(all("raw" not in v for v in sents.values()))
        empty = P.sentiment_of("ABC", None, None, None, None, None, None, None)
        P.sentiment_rank({"ABC": empty})
        self.assertIsNone(empty["score"])
        self.assertEqual(len(P.sentiment_checks(empty)), 4)


class GeminiNotes(unittest.TestCase):
    """AI desk notes and headline ratings with a fake Gemini: budget, caching, fallbacks, and nothing without a key."""

    def setUp(self):
        self.saved = (P.GEMINI_KEY, P.gemini_call, P.CFG["gemini_gap"])
        P.GEMINI_KEY, P.CFG["gemini_gap"] = "test-key", 0.0
        P.GEMINI_STATE.update(calls=0, errors=[], stopped=False, busy=set())
        self.calls = []
        self.fail = {}
        P.gemini_call = self.fake

    def tearDown(self):
        P.GEMINI_KEY, P.gemini_call, P.CFG["gemini_gap"] = self.saved
        P.GEMINI_STATE.update(calls=0, errors=[], stopped=False, busy=set())

    def fake(self, model, system, prompt, max_tokens=2048, json_out=False, timeout=60):
        import io
        import urllib.error
        self.calls.append(model)
        if model in self.fail:
            code = self.fail[model]
            if code == "cut":
                raise ValueError("answer cut off (MAX_TOKENS)")
            raise urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b'{"error": {"message": "nope"}}'))
        if json_out:
            return '[{"i": 0, "tone": 0.8}, {"i": 1, "tone": -1}, {"i": 7, "tone": 1}]'
        return "## Bottom line\nA test note.\n\nNot financial advice."

    @staticmethod
    def recs(n=6, score=85.0):
        out = []
        for i in range(n):
            out.append({"coin": f"C{i}", "kind": "swing", "side": "long" if i % 2 else "short", "score": score - i,
                        "core": 80.0, "extra": 5.0, "label": "Ready", "setup": "Coiled bottom", "price": 1.0 + i,
                        "chg24": 0.01, "why": "test", "plan": {"entry": 1.0, "stop": 0.9, "stop_pct": 0.1, "trail": 0.15,
                                                                 "trail_k": 3.0, "days": 30, "r1": 1.1, "r2": 1.2, "r3": 1.3},
                        "checks": [{"name": "RSI", "ok": 1.0, "pts": 20, "max": 20, "detail": "RSI 55"}],
                        "extras": [{"name": "Funding", "group": "Smart money", "detail": "calm", "ok": None}],
                        "sentiment": {"score": 60, "label": "Neutral", "parts": [["Stocktwits", 60]]}})
        return out

    def test_notes_are_capped_cached_and_refreshed(self):
        J, R = {}, self.recs()
        P.desk_notes(R, J, NOW_FIX, None, {"mood": "Mixed"})
        self.assertEqual(len(self.calls), 3, "at most notes_per_run new notes a scan")
        P.desk_notes(R, J, NOW_FIX + 3600, None, {})
        self.assertEqual(len(self.calls), 5, "the rest of the top 5 the next scan")
        self.assertEqual(sorted(J["notes"]), ["C0", "C1", "C2", "C3", "C4"])
        P.desk_notes(R, J, NOW_FIX + 7200, None, {})
        self.assertEqual(len(self.calls), 5, "unchanged picks keep their notes")
        R[2]["score"] += 6
        P.desk_notes(R, J, NOW_FIX + 7300, None, {})
        self.assertEqual(len(self.calls), 6, "a pick that moved 5+ points gets a new note")
        P.desk_notes(R, J, NOW_FIX + 14 * 3600, None, {})
        self.assertEqual(len(self.calls), 9, "stale notes are rewritten, still 3 a scan")
        self.assertIn("Bottom line", J["notes"]["C0"]["text"])
        self.assertEqual(J["notes"]["C0"]["model"], P.GEMINI_NOTES_MODEL)

    def test_quota_stops_the_run(self):
        self.fail[P.GEMINI_NOTES_MODEL] = 429
        J = {}
        P.desk_notes(self.recs(), J, NOW_FIX, None, {})
        self.assertEqual(self.calls, [P.GEMINI_NOTES_MODEL], "after a quota error no more requests this scan")
        self.assertTrue(P.GEMINI_STATE["stopped"])
        self.assertEqual(J["notes"], {})

    def test_missing_model_falls_back_to_the_other(self):
        self.fail[P.GEMINI_NOTES_MODEL] = 404
        J = {}
        P.desk_notes(self.recs(1), J, NOW_FIX, None, {})
        self.assertEqual(self.calls, [P.GEMINI_NOTES_MODEL, P.GEMINI_FAST_MODEL])
        self.assertEqual(J["notes"]["C0"]["model"], P.GEMINI_FAST_MODEL)

    def test_gemini_call_rejects_a_cut_off_answer(self):
        import io
        from unittest import mock

        def answer(parts, reason):
            body = json.dumps({"candidates": [{"content": {"parts": parts}, "finishReason": reason}]}).encode()
            return mock.MagicMock(__enter__=lambda s: io.BytesIO(body), __exit__=lambda *a: False)

        real = self.saved[1]
        cut = [{"text": "## Bottom line\nBTC is setting up a coiled bottom long.\n- Daily swings are calm"}]
        with mock.patch("urllib.request.urlopen", return_value=answer(cut, "MAX_TOKENS")):
            with self.assertRaisesRegex(ValueError, "cut off"):
                real("m", "sys", "prompt")
        done = [{"text": "thinking it over", "thought": True}, {"text": "A note.\n\nNot financial advice."}]
        with mock.patch("urllib.request.urlopen", return_value=answer(done, "STOP")):
            self.assertEqual(real("m", "sys", "prompt"), "A note.\n\nNot financial advice.")

    def test_cut_off_answer_asks_the_other_model(self):
        self.fail[P.GEMINI_NOTES_MODEL] = "cut"
        J = {}
        P.desk_notes(self.recs(1), J, NOW_FIX, None, {})
        self.assertEqual(self.calls, [P.GEMINI_NOTES_MODEL, P.GEMINI_FAST_MODEL])
        self.assertEqual(J["notes"]["C0"]["model"], P.GEMINI_FAST_MODEL)
        self.assertIn(f"{P.GEMINI_NOTES_MODEL}: answer cut off (MAX_TOKENS)", P.GEMINI_STATE["errors"])

    def test_cut_off_notes_are_not_kept_and_get_rewritten(self):
        good = self.fake
        self.fake_text = "## Bottom line\nBTC is setting up a coiled bottom long.\n\n## Why it scores\n- Daily swings are calm"
        P.gemini_call = lambda *a, **k: (self.calls.append(a[0]), self.fake_text)[1]
        J = {}
        P.desk_notes(self.recs(), J, NOW_FIX, None, {})
        self.assertEqual(J["notes"], {}, "a note without its closing line is not kept")
        self.assertEqual(len(self.calls), 3, "failed tries count toward the scan's budget")
        self.assertTrue(any("cut off" in e for e in P.GEMINI_STATE["errors"]))
        self.calls.clear()
        J["notes"]["C0"] = {"t": NOW_FIX, "side": "short", "score": 85.0, "model": "m", "text": self.fake_text}
        P.gemini_call = good
        P.desk_notes(self.recs(1), J, NOW_FIX + 60, None, {})
        self.assertIn("Not financial advice", J["notes"]["C0"]["text"], "a stored cut-off note is rewritten at once")

    def test_record_names_its_band(self):
        research = {"swing": {"long": {"bands": [{"lo": 60, "hi": 70, "n": 5174, "ret": -0.0034, "win": 0.36}]}}}
        r = self.recs(2)[1]
        r["core"], r["score"] = 65.0, 73.0
        rec = P.note_payload(r, research, {})["record"]
        self.assertEqual(rec["tested_chart_score_band"], "60-69")
        self.assertIn("never call it the record of the total score", P.NOTE_SYSTEM)

    def test_overloaded_model_hands_over_for_the_rest_of_the_scan(self):
        self.fail[P.GEMINI_NOTES_MODEL] = 503
        J = {}
        P.desk_notes(self.recs(), J, NOW_FIX, None, {})
        self.assertEqual(self.calls, [P.GEMINI_NOTES_MODEL, P.GEMINI_FAST_MODEL, P.GEMINI_FAST_MODEL, P.GEMINI_FAST_MODEL],
                         "after a 503 the busy model is skipped, and 3 notes are still written")
        self.assertEqual(len(J["notes"]), 3)
        self.assertFalse(P.GEMINI_STATE["stopped"])

    def test_headlines_rated_once_and_used(self):
        feed = {"items": [{"t": NOW_FIX, "src": "CoinDesk", "title": "Bitcoin ETF inflows hit a record", "desc": ""},
                          {"t": NOW_FIX, "src": "The Block", "title": "Bitcoin miners sell after the halving", "desc": ""}]}
        P.news_ai(feed, NOW_FIX)
        self.assertEqual([x.get("ai") for x in feed["items"]], [0.8, -1.0], "out-of-range answers are ignored")
        btc = P.news_for("BTC", "Bitcoin", feed)
        self.assertEqual(btc["ai"], 2)
        self.assertAlmostEqual(btc["tone"], -0.1)
        P.news_ai(feed, NOW_FIX + 3600)
        self.assertEqual(len(self.calls), 1, "one batched request at most every few hours")

    def test_nothing_without_a_key(self):
        P.GEMINI_KEY = ""
        J, feed = {}, {"items": [{"t": NOW_FIX, "src": "x", "title": "Bitcoin rallies", "desc": ""}]}
        P.desk_notes(self.recs(), J, NOW_FIX, None, {})
        P.news_ai(feed, NOW_FIX)
        self.assertEqual(self.calls, [])
        self.assertEqual(J["notes"], {})
        self.assertNotIn("ai", feed["items"][0])


class GateStats(unittest.TestCase):
    def test_seven_day_values(self):
        rows = [{"time": T0 + i * 14400, "open_interest_usd": 100.0 + i, "mark_price": 10.0 + 0.1 * i,
                 "top_lsr_size": 1.0, "long_liq_usd": 3.0, "short_liq_usd": 1.0} for i in range(45)]
        old = sc.FETCH
        sc.FETCH = lambda url, body=None, timeout=25: rows
        try:
            g = P.gate_stats7("ABC")
        finally:
            sc.FETCH = old
        self.assertAlmostEqual(g["oi7"], 144.0 / 102.0 - 1)
        self.assertAlmostEqual(g["px7"], 14.4 / 10.2 - 1)
        self.assertAlmostEqual(g["liq3"], 0.75)


class SwingValues(unittest.TestCase):
    def test_needs_ninety_days(self):
        cd = days([(1, 1.1, 0.9, 1)] * 80)
        self.assertIsNone(P.swing_values(cd, [], {"mom30": 0.0, "up": True}))

    def test_values_on_a_simple_series(self):
        rows = []
        p = 100.0
        for i in range(140):
            p = p * (0.995 if i < 100 else 1.004)
            rows.append((p, p * 1.01, p * 0.99, p))
        cd = days(rows)
        x = P.swing_values(cd, [], {"mom30": 0.0, "up": False})
        self.assertIsNotNone(x)
        lo90 = min(r[2] for r in rows[-90:])
        self.assertAlmostEqual(x["up90"], rows[-1][3] / lo90 - 1)
        self.assertGreater(x["rsi"], 50)
        self.assertGreater(x["higher_low"], 0)
        self.assertIsNone(x["trend4h"], "no 4h candles given")


class Replay(unittest.TestCase):
    def tr(self, d=1, stop=0.05, trail=0.0, bars=30):
        return {"d": d, "t_in": T0 + DAY, "px": None, "ref_px": 100.0, "stop_pct": stop, "trail_abs": trail,
                "bars": bars, "cost": 0.0}

    def test_stop_first_when_both_touched(self):
        b = days([(100, 100, 100, 100), (100, 120, 94, 110), (110, 111, 109, 110)])
        r = P.replay(self.tr(), b, DAY, T0 + 10 * DAY)
        self.assertEqual(r["state"], "stop")
        self.assertAlmostEqual(r["r"], -1.0)

    def test_trailing_stop_follows_highs_from_the_next_bar(self):
        b = days([(100, 100, 100, 100), (100, 110, 99, 109), (109, 109.5, 103.5, 104), (104, 105, 103, 104)])
        r = P.replay(self.tr(trail=6.0), b, DAY, T0 + 10 * DAY)
        self.assertEqual(r["state"], "trail")
        self.assertAlmostEqual(r["exit_px"], 104.0)  # best high 110 - 6

    def test_gap_exit_at_the_open(self):
        b = days([(100, 100, 100, 100), (100, 101, 99, 100), (90, 91, 88, 89)])
        r = P.replay(self.tr(), b, DAY, T0 + 10 * DAY)
        self.assertEqual((r["state"], r["exit_px"]), ("gap", 90))

    def test_time_exit_after_the_last_bar(self):
        b = days([(100, 100, 100, 100)] + [(100, 101, 99.5, 100.5)] * 5)
        r = P.replay(self.tr(bars=3), b, DAY, T0 + 10 * DAY)
        self.assertEqual(r["state"], "time")
        self.assertEqual(r["exit_t"], T0 + 4 * DAY)

    def test_short_side(self):
        b = days([(100, 100, 100, 100), (100, 101, 90, 91), (91, 97, 90, 96)])
        r = P.replay(self.tr(d=-1, trail=5.0), b, DAY, T0 + 10 * DAY)
        self.assertEqual(r["state"], "trail")
        self.assertAlmostEqual(r["exit_px"], 95.0)  # best low 90 + 5
        self.assertGreater(r["r"], 0)

    def test_open_until_the_bar_closes(self):
        b = days([(100, 100, 100, 100), (100, 101, 80, 90)])
        r = P.replay(self.tr(), b, DAY, T0 + DAY + 3600)  # entry day still forming
        self.assertEqual(r["state"], "open")


class EndToEnd(unittest.TestCase):
    """Two runs on the fake exchange (200 days of candles): scores, reasons, plans, paper trades, pages."""

    @classmethod
    def setUpClass(cls):
        cls.fx = FakeExchange(n_coins=24, days=200, seed=5)
        cls.old = sc.FETCH
        sc.FETCH = cls.fx.fetch
        cls.tmp = tempfile.mkdtemp()
        uni = {}
        for c in cls.fx.coins:
            uni[c] = {"t": c, "venues": {"hyperliquid": {"sym": c, "mult": 1.0, "vol": cls.fx.vol24[c], "funding8h": 0.0001}},
                      "trade_vol": cls.fx.vol24[c] * 1.2, "best_vol": cls.fx.vol24[c] * 1.2, "tradfi": False,
                      "ref_price": cls.fx.c15[c][-1]["c"], "name": c}
        cls.uni = uni
        old_min, P.CFG["paper_swing_min"] = P.CFG["paper_swing_min"], 0  # paper trade everything in the test
        cls.restore = old_min
        cls.gaps = (P.CFG["gap_stocktwits"], P.CFG["gap_coingecko"])
        P.CFG["gap_stocktwits"] = P.CFG["gap_coingecko"] = 0.0
        cls.old_get_text = P.get_text
        P.get_text = lambda url, timeout=30: RSS   # no real news sites in the tests
        cls.old_gemini = P.GEMINI_KEY
        P.GEMINI_KEY = ""                          # and no AI requests
        for run in ("s1", "s2"):
            d = os.path.join(cls.tmp, run, "data")
            os.makedirs(d)
            with open(os.path.join(d, "latest.json"), "w") as fh:
                json.dump({"smart_coins": {"ETH": [4, 1, 2_000_000, 300_000, None]}, "smart": {"read": 120}}, fh)
            with open(os.path.join(cls.tmp, run, "index.html"), "w") as fh:
                fh.write("<html>radar</html>")
        cls.out1 = P.run(os.path.join(cls.tmp, "s1"), journal_path=os.path.join(cls.tmp, "none.json"), universe=uni)
        cls.j1 = os.path.join(cls.tmp, "s1", "data", "picks_journal.json")
        cls.out2 = P.run(os.path.join(cls.tmp, "s2"), journal_path=cls.j1, universe=uni)

    @classmethod
    def tearDownClass(cls):
        sc.FETCH = cls.old
        P.CFG["paper_swing_min"] = cls.restore
        P.CFG["gap_stocktwits"], P.CFG["gap_coingecko"] = cls.gaps
        P.get_text = cls.old_get_text
        P.GEMINI_KEY = cls.old_gemini
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_files_and_pages(self):
        for name in ("picks.json", "picks_journal.json", "picks_research.json"):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, "s2", "data", name)), name)
        with open(os.path.join(self.tmp, "s2", "radar.html")) as fh:
            self.assertIn("radar", fh.read(), "the old front page moves to radar.html")
        with open(os.path.join(self.tmp, "s2", "index.html")) as fh:
            self.assertIn("Coin Picks", fh.read())
        for name in ("analyze.html", "analyze.js"):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, "s2", name)), name + " is published with the picks")

    def test_scores_for_the_analyzer(self):
        sc = self.out1["scores"]
        self.assertEqual(len(sc), self.out1["coins"], "every scored coin is listed for the analyzer")
        for coin, x in sc.items():
            self.assertIn(x["side"], ("long", "short"))
            self.assertIn("venues", x)
            self.assertIn("sentiment", x)

    def test_lists_and_scores(self):
        o = self.out1
        self.assertGreater(o["coins"], 10)
        for kind in ("swing", "daytrade"):
            for side in ("all", "long", "short"):
                L = o[kind][side]
                self.assertLessEqual(len(L), P.CFG["top_n"])
                scores = [r["score"] for r in L]
                self.assertEqual(scores, sorted(scores, reverse=True))
                for r in L:
                    self.assertTrue(0 <= r["score"] <= 100)
                    if side != "all":
                        self.assertEqual(r["side"], side)
        self.assertTrue(o["swing"]["all"], "200 days of candles give swing scores")
        self.assertTrue(o["daytrade"]["all"], "and day-trade scores")

    def test_every_pick_has_15_checks_and_a_plan(self):
        for kind in ("swing", "daytrade"):
            for r in self.out1[kind]["all"]:
                self.assertGreaterEqual(len(r["checks"]) + len(r["extras"]), 15, (kind, r["coin"]))
                pl = r["plan"]
                if r["side"] == "long":
                    self.assertLess(pl["stop"], pl["entry"])
                    self.assertGreater(pl["r2"], pl["entry"])
                else:
                    self.assertGreater(pl["stop"], pl["entry"])
                    self.assertLess(pl["r2"], pl["entry"])
                lim = P.CFG["swing" if kind == "swing" else "day"]
                self.assertTrue(lim["min_stop"] - 1e-9 <= pl["stop_pct"] <= lim["max_stop"] + 1e-9)
                self.assertTrue(r["why"])

    def test_one_side_per_coin(self):
        coins = [r["coin"] for r in self.out1["swing"]["all"]]
        self.assertEqual(len(coins), len(set(coins)))

    def test_smart_money_is_read_from_the_scan(self):
        recs = [r for r in self.out1["swing"]["long"] + self.out1["swing"]["short"] if r["coin"] == "ETH"]
        for r in recs:
            sm = next(e for e in r["extras"] if e["k"] == "smart")
            self.assertIn("4 long", sm["detail"])

    def test_extra_points_stay_within_the_cap(self):
        for kind in ("swing", "daytrade"):
            for r in self.out1[kind]["all"]:
                self.assertLessEqual(abs(r["extra"]), P.CFG["extra_max"])
                self.assertAlmostEqual(r["score"], max(0, min(100, r["core"] + r["extra"])), places=1)

    def test_paper_trades_are_not_repeated(self):
        with open(self.j1) as fh:
            j = json.load(fh)
        n1 = len(j["open"])
        self.assertGreater(n1, 0)
        o2 = self.out2["record"]["open"]
        keys = [(t["kind"], t["c"], t["d"]) for t in o2]
        self.assertEqual(len(keys), len(set(keys)), "one open paper trade per coin, side and kind")
        self.assertEqual(len([t for t in o2 if t["kind"] == "swing"]), len([t for t in j["open"] if t["kind"] == "swing"]),
                         "the same daily close is not traded twice")


if __name__ == "__main__":
    unittest.main()
