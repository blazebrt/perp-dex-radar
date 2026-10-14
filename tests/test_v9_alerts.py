"""v9 trade alerts (v9/alerts.py): one message per new TRADE, the engine's own plan, honest wording, no channel no send.

Run from the repository root:  python -m unittest tests.test_v9_alerts -v"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import test_v8_phase11 as P  # noqa: E402
import test_v9_decision as V  # noqa: E402
from v8 import decision as DE  # noqa: E402
from v9 import alerts as AL  # noqa: E402

ENV = {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42", "DISCORD_WEBHOOK_URL": "https://discord.example/hook"}


def docs():
    """A previous decision where HI's probation long was WATCH (outside its window), then the current one: TRADE."""
    prev = DE.build(V.snap({"HI": [P.sig("PROB", age=86400 + 60)], "LO": [P.sig("REQ")]}))
    cur_snap = V.snap({"HI": [P.sig("PROB", age=600)], "LO": [P.sig("REQ")]})
    cur_snap["previous"] = prev
    return prev, DE.build(cur_snap)


class Alerts(unittest.TestCase):
    def setUp(self):
        self.posts = []
        self.post = lambda url, body: self.posts.append((url, body))

    def test_one_message_per_new_trade_with_the_engines_plan(self):
        prev, cur = docs()
        self.assertEqual(V.cand(prev, "HI")["state"], DE.WATCH)
        r = AL.run(cur, "https://example.github.io/desk/", env=ENV, post=self.post)
        self.assertEqual(r["status"], "OK")
        self.assertEqual([a["id"] for a in r["alerts"]], ["DIRECTIONAL_STRATEGY:HI:PROB:LONG"])   # LO was TRADE already
        text = r["alerts"][0]["text"]
        c = V.cand(cur, "HI")
        for part in ("new TRADE", "HI LONG", "probation, reduced size", "Enter near", "stop", "risk 0.25% of the account",
                     "R per trade out of sample", "past results do not promise future ones", "You decide and place every order",
                     "https://example.github.io/desk/analyze.html?coin=HI"):
            self.assertIn(part, text)
        self.assertIn(AL._price(c["proposal"]["mark"]), text)
        for banned in ("guaranteed", "risk-free", "certain", "sure"):
            self.assertNotIn(banned, text.lower())
        self.assertEqual(r["alerts"][0]["channels"], {"telegram": "SENT", "discord": "SENT"})
        self.assertEqual(self.posts[0][0], "https://api.telegram.org/bot123:abc/sendMessage")
        self.assertEqual(self.posts[0][1]["chat_id"], "42")
        self.assertEqual(self.posts[1], ("https://discord.example/hook", {"content": text}))

    def test_nothing_without_a_channel_or_a_previous_decision(self):
        _, cur = docs()
        r = AL.run(cur, env={}, post=self.post)
        self.assertEqual((r["status"], len(r["alerts"]), self.posts), ("NO_CHANNEL_CONFIGURED", 1, []))
        first = DE.build(V.snap({"HI": [P.sig("PROB", age=600)]}))         # no previous decision: no alert storm
        self.assertEqual(AL.run(first, env=ENV, post=self.post)["alerts"], [])
        self.assertEqual(AL.run({"schema": "other"}, env=ENV, post=self.post)["status"], "NO_DECISION")
        self.assertEqual(self.posts, [])

    def test_a_persisting_trade_is_not_announced_again(self):
        _, cur = docs()
        again = V.snap({"HI": [P.sig("PROB", age=600)], "LO": [P.sig("REQ")]})
        again["previous"] = cur
        self.assertEqual(AL.run(DE.build(again), env=ENV, post=self.post)["alerts"], [])

    def test_a_failing_channel_never_raises_and_never_logs_the_token(self):
        _, cur = docs()

        def boom(url, body):
            raise RuntimeError("HTTP 401 for " + url)
        r = AL.run(cur, env=ENV, post=boom)
        ch = r["alerts"][0]["channels"]
        self.assertTrue(ch["telegram"].startswith("FAILED"))
        self.assertNotIn("123:abc", ch["telegram"])


if __name__ == "__main__":
    unittest.main()
