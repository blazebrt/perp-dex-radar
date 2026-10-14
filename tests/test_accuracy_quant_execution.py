"""A05: elapsed deadlines, continuous execution path, explicit funding and immutable legacy closes."""
from __future__ import annotations

import copy
import json
import math
import pathlib
import tempfile
import unittest
from unittest import mock

import quant as Q
from v8 import audit_quant
from v8 import evidence as EV
from v8 import identity as ID

H = Q.H
T0 = 1_700_006_400


def trade(hold=2, trail=0.0):
    return {"id": "TEST-TSMOM", "s": "TSMOM", "c": "TEST", "d": 1, "t_in": T0,
            "px": 100.0, "stop_pct": 0.05, "trail_pct": trail, "hold_h": hold, "slip": 0.0}


def bar(hour, o=100.0, h=101.0, low=99.0, c=100.0):
    return {"t": T0 + hour * H, "o": o, "h": h, "l": low, "c": c}


def observed_zero(candles):
    return {x["t"]: 0.0 for x in candles}


def old_complete_result(tr, candles, fund):
    """The prior accounting formula on a proved continuous complete path (no assumed missing observations)."""
    d, entry = tr["d"], tr["px"]
    risk, trail = entry * tr["stop_pct"], entry * tr["trail_pct"]
    stop = stop0 = entry - d * risk
    best, fsum, mfe, mae = entry, 0.0, 0.0, 0.0
    state, px, ts = "open", None, None
    for i, x in enumerate(candles):
        if i:
            fsum += fund[x["t"]]
        o, h, low, c = x["o"], x["h"], x["l"], x["c"]
        fav = (h - entry if d > 0 else entry - low) / risk
        adv = (entry - low if d > 0 else h - entry) / risk
        hit = None
        if d > 0:
            if i and o <= stop:
                hit, px = "gap", o
            elif low <= stop:
                hit, px = ("trail" if stop > stop0 else "stop"), stop
        else:
            if i and o >= stop:
                hit, px = "gap", o
            elif h >= stop:
                hit, px = ("trail" if stop < stop0 else "stop"), stop
        if hit:
            mae, state, ts = max(mae, adv), hit, x["t"] + H
            break
        mfe, mae = max(mfe, fav), max(mae, adv)
        if trail:
            best = max(best, c) if d > 0 else min(best, c)
            stop = max(stop, best - trail) if d > 0 else min(stop, best + trail)
        if i == tr["hold_h"] - 1:
            state, px, ts = "time", c, x["t"] + H
            break
    gross = d * (px - entry) / entry
    fcost = d * fsum
    return {"state": state, "exit_px": px, "exit_t": ts, "stop_now": stop, "mfe": round(mfe, 3),
            "mae": round(mae, 3), "gross": gross / tr["stop_pct"],
            "r": (gross - 2 * (Q.CFG["fee_taker"] + tr["slip"]) - fcost) / tr["stop_pct"],
            "fund": fcost / tr["stop_pct"]}


class QuantExecutionAccuracy(unittest.TestCase):
    def test_two_hour_deadline_is_absolute_not_two_returned_candles(self):
        candles = [bar(0), bar(3)]
        res = Q.sim_trade(trade(), candles, observed_zero(candles), T0 + 4 * H)
        self.assertEqual(res["deadline"], T0 + 2 * H)
        self.assertEqual(res["state"], "pending_history")
        self.assertIsNone(res["exit_t"])
        self.assertIsNone(res["r"])
        self.assertEqual(res["execution"]["missing_candle_hour"], T0 + H)

    def test_stop_after_missing_hour_is_not_a_proved_stop(self):
        candles = [bar(0), bar(2, o=90, h=91, low=89, c=90)]
        res = Q.sim_trade(trade(hold=10), candles, observed_zero(candles), T0 + 3 * H)
        self.assertEqual(res["state"], "pending_history")
        self.assertIsNone(res["exit_px"])
        self.assertIsNone(res["r"])

    def test_trailing_stop_after_gap_is_not_proved(self):
        candles = [bar(0, h=111, c=110), bar(2, o=105, h=106, low=104, c=105)]
        res = Q.sim_trade(trade(hold=10, trail=0.03), candles, observed_zero(candles), T0 + 3 * H)
        self.assertEqual(res["state"], "pending_history")
        self.assertEqual(res["stop_now"], 107)
        self.assertIsNone(res["r"])

    def test_missing_history_at_tail_stays_pending(self):
        res = Q.sim_trade(trade(), [bar(0)], {}, T0 + 6 * H)
        self.assertEqual(res["state"], "pending_history")
        self.assertEqual(res["hours"], 1)
        self.assertIsNone(res["r"])

    def test_missing_entry_candle_cannot_shift_entry_to_a_later_hour(self):
        res = Q.sim_trade(trade(), [bar(1), bar(2)], {T0 + H: 0.0}, T0 + 4 * H)
        self.assertEqual(res["state"], "pending_history")
        self.assertIsNone(res["exit_t"])
        self.assertEqual(res["execution"]["missing_candle_hour"], T0)

    def test_invalid_hourly_price_path_cannot_supply_qualified_exit(self):
        invalid = [dict(bar(1), l=float("nan")), dict(bar(1), h=float("inf")),
                   dict(bar(1), o=0.0), dict(bar(1), c=-1.0), dict(bar(1), l=True),
                   dict(bar(1), h=98.0), dict(bar(1), l=102.0), dict(bar(1), c="100"),
                   dict(bar(1), t=T0 + H + 1), dict(bar(1), t=float(T0 + H)),
                   dict(bar(1), t=None), dict(bar(1), t=True)]
        for bad in invalid:
            with self.subTest(bar=bad):
                res = Q.sim_trade(trade(), [bar(0), bad], {T0 + H: 0.0}, T0 + 2 * H)
                self.assertEqual(res["state"], "pending_history")
                self.assertEqual(res["execution"]["state"], "MISSING_CANDLE_PATH")
                self.assertIsNone(res["r"])
                self.assertIsNone(res["exit_t"])

    def test_missing_funding_cannot_be_qualified_zero(self):
        res = Q.sim_trade(trade(), [bar(0), bar(1)], {}, T0 + 2 * H)
        self.assertEqual(res["state"], "time")
        self.assertEqual(res["execution"]["state"], "MISSING_FUNDING")
        self.assertIsNone(res["r"])
        self.assertIsNone(res["fund"])
        self.assertEqual(res["execution"]["funding_observations"]["MISSING"], 1)
        closed = dict(trade(), r=res["r"], execution=res["execution"])
        self.assertFalse(Q.execution_qualified(closed))

    def test_observed_zero_funding_is_distinct_from_missing_and_nonzero(self):
        candles = [bar(0), bar(1)]
        zero = Q.sim_trade(trade(), candles, {T0 + H: 0.0}, T0 + 2 * H)
        observed = Q.sim_trade(trade(), candles, {T0 + H: 0.001}, T0 + 2 * H)
        self.assertEqual(zero["execution"]["state"], "QUALIFIED")
        self.assertEqual(zero["execution"]["funding_observations"]["OBSERVED_ZERO"], 1)
        self.assertEqual(observed["execution"]["funding_observations"]["OBSERVED"], 1)
        self.assertAlmostEqual(zero["r"] - observed["r"], 0.001 / 0.05)

    def test_exchange_reported_cycle_covers_only_its_observed_interval(self):
        history = Q.FundingHistory({T0 + 8 * H: 0.0}, {T0 + 8 * H: 8})
        self.assertEqual(history.observation(T0 + H), ("NOT_SCHEDULED", 0.0))
        self.assertEqual(history.observation(T0 + 8 * H), ("OBSERVED_ZERO", 0.0))
        self.assertEqual(history.observation(T0 + 9 * H), ("MISSING", None))
        self.assertEqual(history.observation(T0), ("MISSING", None))
        res = Q.sim_trade(trade(), [bar(0), bar(1)], history, T0 + 8 * H)
        self.assertEqual(res["execution"]["state"], "QUALIFIED")
        future = Q.sim_trade(trade(), [bar(0), bar(1)], history, T0 + 2 * H)
        self.assertEqual(future["execution"]["state"], "MISSING_FUNDING")
        # No inferred 8h cadence can cover a missing settlement between two explicit cycles.
        gap = Q.FundingHistory({T0 + 8 * H: 0.001, T0 + 24 * H: 0.001},
                               {T0 + 8 * H: 8, T0 + 24 * H: 8})
        self.assertEqual(gap.observation(T0 + 16 * H), ("MISSING", None))

    def test_nonfinite_or_boolean_funding_never_qualifies(self):
        for value in (None, True, float("nan"), float("inf"), "0"):
            with self.subTest(value=value):
                res = Q.sim_trade(trade(), [bar(0), bar(1)], {T0 + H: value}, T0 + 2 * H)
                self.assertIsNone(res["r"])
                self.assertEqual(res["execution"]["state"], "MISSING_FUNDING")

    def test_complete_contiguous_path_matches_original_accounting(self):
        cases = [([bar(0), bar(1, c=101)], trade()),
                 ([bar(0, h=101, low=94)], trade(hold=1)),
                 ([bar(0), bar(1, o=90, h=91, low=89, c=90)], trade(hold=2)),
                 ([bar(0, h=111, c=110), bar(1, o=110, h=111, low=106, c=108)],
                  trade(hold=2, trail=0.03))]
        for candles, tr in cases:
            for direction in (1, -1):
                # Short cases have an intentionally wide stop, preserving the same formula in both directions.
                tr = dict(tr, d=direction)
                fund = {x["t"]: 0.0001 if i else 0.0 for i, x in enumerate(candles)}
                expected = old_complete_result(tr, candles, fund)
                actual = Q.sim_trade(tr, candles, fund, T0 + len(candles) * H)
                for key, value in expected.items():
                    with self.subTest(direction=direction, key=key):
                        self.assertEqual(actual[key], value)
                self.assertEqual(actual["execution"]["state"], "QUALIFIED")

    def test_legacy_closed_numbers_are_preserved_and_excluded(self):
        tr = EV.stamp(dict(trade(), r=9.982, t_out=T0 + 30 * H, px=100.0, ret=0.4991), "TEST",
                      ID.Authority.from_states({"TEST": ID.VERIFIED_CRYPTO}, scan_id="entry-proof"))
        before = copy.deepcopy(tr)
        Q.mark_legacy_execution([tr])
        self.assertEqual({k: v for k, v in tr.items() if k != "execution"}, before)
        self.assertEqual(Q.execution_class(tr), Q.LEGACY_EXECUTION_UNQUALIFIED)
        self.assertTrue(EV.qualified(tr))
        self.assertFalse(Q.qualified_trade(tr))
        self.assertEqual(Q.live_stats([tr]), {"n": 0})
        self.assertEqual(Q.live_stats([tr], include_unqualified=True)["n"], 1)
        part = audit_quant.journal_part({"open": [], "closed": [tr]}, [], [])
        self.assertEqual(part["qualified_closed_n"], 0)
        self.assertEqual(part["unqualified_n"], 1)
        self.assertEqual(part["unqualified_trades"][0]["r"], 9.982)
        self.assertEqual(part["evidence"]["execution_classes"]["closed"],
                         {Q.LEGACY_EXECUTION_UNQUALIFIED: 1})

    def test_qualified_execution_still_needs_entry_identity(self):
        candles = [bar(0), bar(1)]
        res = Q.sim_trade(trade(), candles, observed_zero(candles), T0 + 2 * H)
        tr = dict(trade(), r=res["r"], execution=res["execution"])
        self.assertTrue(Q.execution_qualified(tr))
        self.assertFalse(Q.qualified_trade(tr))
        EV.stamp(tr, "TEST", ID.Authority.from_states({"TEST": ID.VERIFIED_CRYPTO}, scan_id="proof"))
        self.assertTrue(Q.qualified_trade(tr))

    def test_audit_journal_does_not_trim_or_recompute_stored_history(self):
        rows = [dict(trade(), id=f"old-{i}", r=i / 100, t_out=T0 + H) for i in range(Q.CFG["keep_closed"] + 1)]
        journal = dict(Q.new_journal(T0), closed=rows, scans=1)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "journal.json"
            path.write_text(json.dumps(journal), encoding="utf-8")
            with mock.patch.object(Q.sc, "now_ts", return_value=T0 + 100 * H):
                out = Q.run(str(pathlib.Path(tmp) / "site"), journal_path=str(path), universe={})
            saved = json.loads((pathlib.Path(tmp) / "site/data/quant_journal.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["closed"]), len(rows))
        self.assertEqual(len(out["closed"]), 150)
        self.assertEqual(out["live_all"], {"n": 0})
        for before, after in zip(rows, saved["closed"]):
            self.assertEqual({key: after[key] for key in before}, before)
            self.assertEqual(after["execution"]["state"], Q.LEGACY_EXECUTION_UNQUALIFIED)


if __name__ == "__main__":
    unittest.main()
