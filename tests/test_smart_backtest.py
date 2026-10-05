"""The smart-money test engine: positions from fills, entries, the crowd rule, the follow trade, no hindsight."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools", "research"))

import smart_backtest as B  # noqa: E402

H, DAY = 3600, 86400
W0 = 1_780_000_000 // DAY * DAY
W = (W0, W0 + 90 * DAY)


def fill(t, coin, side, sz, px, start):
    return [t, coin, side, sz, px, start, 0.0, 0.1, "x", 1, 0, t]


def trader(tid, fills, pos_now=(), complete=True, pnl=None, av=400_000.0):
    pnl = pnl or [[W0 - 400 * DAY, 0.0], [W0 + 90 * DAY, 900_000.0]]
    return B.Trader({"id": tid, "groups": ["pre"], "av": av, "lb": {"m": {"vlm": 1e6}},
                     "state": {"pos": [list(p) for p in pos_now]},
                     "portfolio": {"perpAllTime": {"pnl": pnl, "av": [[W0 - 400 * DAY, av], [W0 + 90 * DAY, av]]}},
                     "fills": fills, "fills_complete": complete}, W[0], W[1])


class Positions(unittest.TestCase):
    def test_entries_open_add_reduce_flip(self):
        t0 = W0 + 40 * DAY
        tr = trader("a", [fill(t0, "SOL", 1, 100, 100.0, 0.0),           # open long $10k
                          fill(t0 + 60, "SOL", 1, 50, 100.0, 100.0),     # add $5k (same hour)
                          fill(t0 + 2 * H, "SOL", -1, 30, 110.0, 150.0),  # reduce: not an entry
                          fill(t0 + 5 * H, "SOL", -1, 200, 90.0, 120.0)])  # flip to short 80: $7.2k short
        self.assertEqual(tr.entries(), [(t0 // H * H, "SOL", 1, 15_000.0), ((t0 + 5 * H) // H * H, "SOL", -1, 7_200.0)])

    def test_position_is_the_next_fills_start(self):
        t0 = W0 + 40 * DAY
        # three fills in the same second, listed out of order: the position between fills comes from the API's own
        # "position before this fill", so the order inside the second does not matter
        tr = trader("a", [fill(t0, "ETH", -1, 1, 2500.0, 0.0), fill(t0 + 10, "ETH", -1, 2, 2500.0, -3.0),
                          fill(t0 + 10, "ETH", -1, 2, 2500.0, -1.0), fill(t0 + 3 * H, "ETH", 1, 5, 2400.0, -5.0)],
                    pos_now=[("ETH", 0.0)])
        self.assertEqual(tr.pos("ETH", t0 - 1), 0.0)
        self.assertEqual(tr.pos("ETH", t0 + 5), -1.0)
        self.assertEqual(tr.pos("ETH", t0 + H), -5.0)
        self.assertEqual(tr.pos("ETH", t0 + 4 * H), 0.0, "after the last fill: the position now")
        held = trader("b", [], pos_now=[("BTC", 2.0)])
        self.assertEqual(held.pos("BTC", W0 + DAY), 2.0, "held all along without a fill")


class NoHindsight(unittest.TestCase):
    def test_skill_uses_only_what_was_known(self):
        # made $900k over time, but all of it after day 60: not proven on day 50, proven on day 80
        pnl = [[W0 - 400 * DAY, 0.0], [W0 + 60 * DAY, 0.0], [W0 + 70 * DAY, 900_000.0], [W0 + 90 * DAY, 900_000.0]]
        tr = trader("late", [], pnl=pnl)
        sk = B.skill_table([tr], [W0 + 50 * DAY, W0 + 80 * DAY])
        self.assertFalse(B.proven(sk[W0 + 50 * DAY]["late"]))
        self.assertTrue(B.proven(sk[W0 + 80 * DAY]["late"]))

    def test_the_live_rule(self):
        s = {"all": 150_000, "p30": -50_000, "p90": None, "av": 400_000}
        self.assertTrue(B.proven(s))
        self.assertFalse(B.proven(dict(s, p30=-70_000)), "lost more than 15% of the account in 30 days")
        self.assertFalse(B.proven(dict(s, all=90_000)))
        self.assertFalse(B.proven(dict(s, av=20_000)))


class CrowdRule(unittest.TestCase):
    def test_two_traders_shorting_within_a_day(self):
        t0 = W0 + 40 * DAY
        a = trader("a", [fill(t0, "SOL", -1, 1000, 100.0, 0.0)])
        b = trader("b", [fill(t0 + 5 * H, "SOL", -1, 1000, 100.0, 0.0)])
        c = trader("c", [fill(t0 + 6 * H, "SOL", -1, 1000, 100.0, 0.0)])       # same window: no second signal
        d = trader("d", [fill(t0 + 2 * DAY, "SOL", -1, 1000, 100.0, 0.0)])     # alone, later: nothing
        skills = B.skill_table([a, b, c, d], [t0 // DAY * DAY, (t0 + 2 * DAY) // DAY * DAY])
        rows = B.signals_crowd([a, b, c, d], skills, W, k=2)
        self.assertEqual(rows, [{"start": (t0 + 5 * H) // H * H + H, "coin": "SOL", "side": -1, "n": 2}])
        e = trader("e", [fill(t0 + 5 * H + 60, "SOL", 1, 1000, 100.0, 0.0)])   # one long against them, same hour
        skills = B.skill_table([a, b, e], [t0 // DAY * DAY])
        self.assertEqual(B.signals_crowd([a, b, e], skills, W, k=2), [], "net of the other side, hour by hour")


class FollowTrade(unittest.TestCase):
    def prices(self, path, lows=None):
        start = W0 + 30 * DAY
        rows = []
        for k in range(8 * 24):                                   # a calm week before: 1% daily moves
            px = 100.0 * (1.01 if (k // 24) % 2 else 1.0)
            rows.append([start - 8 * DAY + k * H, px, px, px, px, 1.0])
        for k, px in enumerate(path):
            lo = (lows or {}).get(k, px)
            rows.append([start + k * H, px, max(px, 100.0), lo, px, 1.0])
        return B.Prices({"X": rows}), start

    def test_stop_then_time_exit(self):
        p, start = self.prices([100.0] * 30, lows={3: 97.0})
        r, ret = p.trade("X", start, 1, 24)
        self.assertAlmostEqual(ret, -0.015 - 0.0009, places=6, msg="stopped at the 1.5% minimum stop")
        self.assertAlmostEqual(r, ret / 0.015, places=6)
        p, start = self.prices([100.0] * 23 + [97.0] * 7)
        r, ret = p.trade("X", start, -1, 24)
        self.assertAlmostEqual(ret, 0.03 - 0.0009, places=6, msg="a short that fell 3% by the 24th hour")


if __name__ == "__main__":
    unittest.main()
