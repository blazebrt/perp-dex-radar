"""A03/A04: identity alone never qualifies a paper result; missing execution remains unknown."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest

import smart as SM
from v8 import identity as ID


def bar(t, close=100.0, low=99.0, high=101.0):
    return {"t": t * 1000, "l": str(low), "h": str(high), "c": str(close)}


def trade(entry=3600, side=1, hold=24):
    tr = SM.open_trade({"coin": "BTC", "hl": "BTC", "side": "long" if side > 0 else "short", "text": "x"},
                       {"BTC": 100}, entry, fetch=lambda *args, **kwargs: [],
                       cfg=dict(SM.CFG, min_stop=0.025, hold_h=hold))
    return SM.stamp_identity(tr, "BTC", ID.Authority.from_states({"BTC": ID.VERIFIED_CRYPTO}))


def update(tr, candles, now, mark=100, module=SM):
    J = {"open": [copy.deepcopy(tr)], "closed": []}
    module.update_trades(J, {"BTC": mark}, now, fetch=lambda *args, **kwargs: candles)
    return J


class SmartExecution(unittest.TestCase):
    def test_missing_deadline_history_does_not_realize_current_mid(self):
        tr = trade(entry=5400)
        J = update(tr, [], tr["t_out_by"] + 6 * SM.H, mark=150)
        self.assertEqual(J["open"], [])
        c = J["closed"][0]
        self.assertEqual(c["execution_quality"], "MISSING_HISTORY")
        self.assertEqual((c["ret"], c["r"]), (None, None))
        self.assertNotIn("exit_px", c)
        self.assertEqual(c["diagnostic_mark"], {"as_of": tr["t_out_by"] + 6 * SM.H,
                                                "price": 150, "qualified": False})
        self.assertFalse(SM.realized_qualified(c))
        self.assertEqual(SM.accuracy(None, J)["live"], {"n": 0})

    def test_missing_history_can_recover_before_deadline(self):
        tr = trade()
        J = update(tr, [], 2 * SM.H)
        self.assertEqual(len(J["open"]), 1)
        self.assertEqual(J["open"][0]["execution_quality"], "PENDING_HISTORY")
        self.assertFalse(SM.realized_qualified(J["open"][0]))
        SM.update_trades(J, {"BTC": 94}, 3 * SM.H,
                         fetch=lambda *args, **kwargs: [bar(SM.H), bar(2 * SM.H, low=94)])
        self.assertTrue(SM.realized_qualified(J["closed"][0]))

    def test_entry_hour_extreme_is_ambiguous_not_a_qualified_stop(self):
        tr = trade(entry=5400)
        c = update(tr, [bar(SM.H, low=90)], 5460)["closed"][0]
        self.assertEqual(c["execution_quality"], "ENTRY_PATH_AMBIGUOUS")
        self.assertEqual((c["ret"], c["r"]), (None, None))
        self.assertFalse(SM.realized_qualified(c))

    def test_short_entry_hour_extreme_is_also_ambiguous(self):
        c = update(trade(entry=5400, side=-1), [bar(SM.H, high=110)], 5460)["closed"][0]
        self.assertEqual(c["execution_quality"], "ENTRY_PATH_AMBIGUOUS")
        self.assertIsNone(c["r"])

    def test_partial_entry_bar_not_ignored_before_later_stop(self):
        tr = trade(entry=5400)
        # Both lows reach the stop. Omitting entry-hour ambiguity would manufacture an ordinary later stop.
        c = update(tr, [bar(SM.H, low=90), bar(2 * SM.H, low=90)], 3 * SM.H)["closed"][0]
        self.assertEqual(c["execution_quality"], "ENTRY_PATH_AMBIGUOUS")
        self.assertIsNone(c["r"])

    def test_safe_partial_entry_bar_and_known_later_stop_are_qualified(self):
        tr = trade(entry=5400)
        c = update(tr, [bar(SM.H), bar(2 * SM.H, low=94)], 3 * SM.H)["closed"][0]
        self.assertTrue(SM.realized_qualified(c))
        self.assertEqual((c["exit_px"], c["why"]), (95, "stop"))
        self.assertEqual(c["ret"], round(95 / 100 - 1 - SM.CFG["cost"], 5))
        self.assertEqual(c["r"], -1.018)

    def test_gap_before_stop_cannot_be_skipped(self):
        tr = trade(hold=3)
        c = update(tr, [bar(SM.H), bar(3 * SM.H, low=90)], 4 * SM.H)["closed"][0]
        self.assertEqual(c["execution_quality"], "MISSING_CANDLE_PATH")
        self.assertIsNone(c["r"])

    def test_gap_before_time_exit_cannot_be_skipped(self):
        tr = trade(hold=3)
        c = update(tr, [bar(SM.H), bar(3 * SM.H, close=120, high=121)], 5 * SM.H)["closed"][0]
        self.assertEqual(c["execution_quality"], "MISSING_CANDLE_PATH")
        self.assertIsNone(c["r"])

    def test_partial_deadline_has_no_exact_exit_observation(self):
        tr = trade(entry=5400, hold=2)
        cs = [bar(SM.H), bar(2 * SM.H), bar(3 * SM.H, close=120, high=121)]
        c = update(tr, cs, 4 * SM.H, mark=150)["closed"][0]
        self.assertEqual(c["execution_quality"], "DEADLINE_PRICE_UNAVAILABLE")
        self.assertEqual((c["ret"], c["r"]), (None, None))

    def test_deadline_bar_extreme_may_be_after_deadline(self):
        tr = trade(entry=5400, hold=2)
        c = update(tr, [bar(SM.H), bar(2 * SM.H), bar(3 * SM.H, low=90)], 4 * SM.H)["closed"][0]
        self.assertEqual(c["execution_quality"], "DEADLINE_PRICE_UNAVAILABLE")
        self.assertIsNone(c["r"])

    def test_stop_observed_during_deadline_hour_before_deadline_is_known(self):
        tr = trade(entry=5400, hold=2)
        c = update(tr, [bar(SM.H), bar(2 * SM.H), bar(3 * SM.H, low=94)],
                   3 * SM.H + 600)["closed"][0]
        self.assertTrue(SM.realized_qualified(c))
        self.assertEqual((c["why"], c["exit_px"], c["r"]), ("stop", 95, -1.018))

    def test_complete_observed_boundary_time_exit_keeps_prior_math(self):
        for side in (1, -1):
            with self.subTest(side=side):
                tr = trade(side=side, hold=2)
                c = update(tr, [bar(SM.H), bar(2 * SM.H, close=102, high=103)], 4 * SM.H)["closed"][0]
                self.assertTrue(SM.realized_qualified(c))
                # The old algorithm was well-defined here: same deadline close, costs, return and R.
                ret = side * (102 / 100 - 1) - SM.CFG["cost"]
                self.assertEqual((c["why"], c["exit_px"], c["t_out"]), ("time", 102, 4 * SM.H))
                self.assertEqual((c["ret"], c["r"]), (round(ret, 5), round(ret / 0.05, 3)))

    def test_unsorted_duplicate_and_malformed_history_fail_closed(self):
        tr = trade(hold=2)
        valid = [bar(2 * SM.H), bar(SM.H)]
        self.assertTrue(SM.realized_qualified(update(tr, valid, 3 * SM.H)["closed"][0]))
        for cs in ([bar(SM.H), bar(SM.H, low=90), bar(2 * SM.H)],
                   [bar(SM.H), dict(bar(2 * SM.H), c="nan")],
                   [bar(SM.H), dict(bar(2 * SM.H), t=True)]):
            with self.subTest(candles=cs):
                c = update(tr, cs, 3 * SM.H)["closed"][0]
                self.assertFalse(SM.realized_qualified(c))
                self.assertIsNone(c["r"])

    def test_identity_and_execution_required_independently(self):
        c = update(trade(hold=2), [bar(SM.H), bar(2 * SM.H)], 3 * SM.H)["closed"][0]
        self.assertTrue(SM.realized_qualified(c))
        for key in ("identity_qualified", "execution_quality", "execution_evidence"):
            bad = copy.deepcopy(c)
            bad.pop(key)
            self.assertFalse(SM.realized_qualified(bad), key)
            self.assertEqual(SM.accuracy(None, {"closed": [bad]})["live"], {"n": 0})
        for key in ("continuous_path", "entry_bar_checked", "exit_price_observed", "deadline_bound"):
            bad = copy.deepcopy(c)
            bad["execution_evidence"][key] = False
            self.assertFalse(SM.realized_qualified(bad), key)

    def test_legacy_identity_proof_does_not_qualify_old_returns(self):
        old = trade()
        for k in ("execution_quality", "execution_evidence"):
            old.pop(k)
        old.update(t_out=99, why="time", exit_px=150, ret=0.4991, r=9.982)
        original = copy.deepcopy(old)
        J = {"open": [], "closed": [old]}
        self.assertTrue(SM.trade_qualified(old), "identity authority is preserved independently")
        self.assertFalse(SM.realized_qualified(old))
        SM.mark_legacy(J)
        self.assertEqual({k: old[k] for k in original}, original)
        self.assertEqual(SM.execution_quality(old), SM.LEGACY_EXECUTION_UNQUALIFIED)
        self.assertEqual(SM.accuracy(None, J)["live"], {"n": 0})
        self.assertEqual(SM.journal_evidence(J)["execution_classes"]["closed"],
                         {SM.LEGACY_EXECUTION_UNQUALIFIED: 1})
        # Loading, metadata marking, serialization and following other trades never rewrite historic outcomes.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "journal.json")
            with open(path, "w") as fh:
                json.dump(J, fh)
            loaded, source = SM.load_journal(None, path, 100)
            SM.update_trades(loaded, {"BTC": 1}, 100, fetch=lambda *a, **kw: [])
            self.assertEqual(source, "file")
            self.assertEqual({k: loaded["closed"][0][k] for k in original}, original)

    def test_existing_closed_rows_are_not_pruned(self):
        J = {"open": [], "closed": [{"id": str(i), "r": i, "ret": i, "t_in": i, "t_out": i} for i in range(605)]}
        before = copy.deepcopy(J)
        SM.update_trades(J, {}, 999, fetch=lambda *a, **kw: [])
        self.assertEqual(J, before)


if __name__ == "__main__":
    unittest.main()
