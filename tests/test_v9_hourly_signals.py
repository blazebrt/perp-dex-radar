import copy
import unittest
try:
    import numpy as np
    import pandas
    HAVE_RESEARCH = True
except ModuleNotFoundError as exc:
    if exc.name not in ('numpy', 'pandas'):
        raise
    HAVE_RESEARCH = False
if HAVE_RESEARCH:
    from tools.v9 import hourly_signals as A
from tools.v9 import hourly_feature_state as S


def candles(start=0, count=1200):
    rng = np.random.default_rng(23)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, .003, count)))
    result = {}
    for i, c in enumerate(prices):
        o = prices[i - 1] if i else c
        result[(start + i) * S.HOUR] = dict(o=o, h=max(o, c)*1.004, l=min(o, c)*.996, c=c, qv=1e6)
    for i in (850, 950, 1050):
        if i >= count: continue
        row = result[(start + i)*S.HOUR]
        row.update(c=row['o'] * .94, l=row['o'] * .935, h=row['o'] * 1.004, qv=1e8)
    return result


@unittest.skipUnless(HAVE_RESEARCH, 'numpy/pandas required; covered by research CI')
class HourlySignalTests(unittest.TestCase):
    def test_registered_code_runs_six_definitions_and_keeps_carry_unavailable(self):
        rows = candles(); btc = candles()
        funding = {t: .001 for t in rows if t % (8*S.HOUR) == 0}
        counts = {}
        for alias in sorted(S.ALIASES):
            result = A.generate(alias, 'X', rows, 0, btc, funding)
            if alias == 'FUND_CARRY':
                self.assertIsNone(result['signals'])
                self.assertEqual(result['status'], 'UNAVAILABLE_CAUSAL_QUORUM_MAPPING')
            else:
                self.assertEqual(result['status'], 'GENERATED')
                counts[alias] = len(result['signals'])
        self.assertGreater(counts['LIQ_FLUSH'], 0)
        self.assertGreater(counts['VOL_SPIKE'], 0)
        self.assertGreater(counts['FUND_FADE'], 0)

    def test_contiguous_signals_equal_unchanged_registered_function(self):
        rows = candles(); times = sorted(rows)
        f = A.features(times, [rows])
        trial = A.registered()['LIQ_FLUSH']
        raw = A.qstrat.liq_flush(f, **trial['params'])
        result = A.generate('LIQ_FLUSH', 'X', rows, 0)['signals']
        self.assertEqual([r['signal_time'] for r in result], [int(f.p.t[i]) for i in raw['i']])
        np.testing.assert_array_equal([r['stop'] for r in result], raw['stop'])
        self.assertEqual([r['direction'] for r in result], list(raw['d']))

    def test_gap_reset_matches_fresh_standalone_session(self):
        post = candles(1300)
        combined = candles()
        combined.update(post)
        standalone = A.generate('LIQ_FLUSH', 'X', post, 0)['signals']
        result = A.generate('LIQ_FLUSH', 'X', combined, 0)['signals']
        self.assertEqual([r for r in result if r['signal_time'] >= 1300*S.HOUR], standalone)
        self.assertTrue(standalone)

    def test_future_append_and_input_preservation(self):
        rows = candles(); before = copy.deepcopy(rows)
        original = A.generate('PULLBACK', 'X', rows, 0)['signals']
        self.assertEqual(rows, before)
        rows.update(candles(1200, 300))
        extended = A.generate('PULLBACK', 'X', rows, 0)['signals']
        self.assertEqual([r for r in extended if r['signal_time'] < 1200*S.HOUR], original)

    def test_nonempty_signal_prefix_is_causal_for_price_definitions(self):
        rows = candles()
        longer = dict(rows)
        longer.update(candles(1200, 300))
        for alias in ('LIQ_FLUSH', 'VOL_SPIKE'):
            original = A.generate(alias, 'X', rows, 0)['signals']
            self.assertTrue(original)
            extended = A.generate(alias, 'X', longer, 0)['signals']
            self.assertEqual([r for r in extended if r['signal_time'] < 1200*S.HOUR], original)

    def test_four_hour_features_discard_partial_edges_and_preserve_prefix(self):
        rows = candles(1, 1200)
        f = A.features(sorted(rows), [rows])
        self.assertEqual(int(f.b4['t'][0]), 4*S.HOUR)
        self.assertEqual(int(f.p.t[f.b4['end'][0]]), 7*S.HOUR)
        longer = dict(rows)
        longer.update(candles(1201, 300))
        extended = A.features(sorted(longer), [longer])
        np.testing.assert_array_equal(f.atr1, extended.atr1[:len(rows)])
        ema = A.qstrat.I.ema(f.b4['c'], 200)
        later = A.qstrat.I.ema(extended.b4['c'], 200)
        self.assertTrue(np.isfinite(ema[199:]).all())
        np.testing.assert_array_equal(ema, later[:len(ema)])

    def test_unknown_funding_never_reuses_prior_event_to_emit_signal(self):
        rows = candles()
        self.assertEqual(A.generate('FUND_FADE', 'X', rows, 0)['signals'], [])
        event = 850*S.HOUR
        result = A.generate('FUND_FADE', 'X', rows, 0, funding={event: .001})['signals']
        self.assertTrue(result)
        self.assertTrue(all(r['signal_time'] == event for r in result))
        observed_zero = A.generate('FUND_FADE', 'X', rows, 0, funding={event: .001, 950*S.HOUR: 0.})['signals']
        self.assertEqual(observed_zero, result)
        with self.assertRaisesRegex(ValueError, 'hour-aligned'):
            A.generate('FUND_FADE', 'X', rows, 0, funding={event+1: .001})

    def test_btc_gap_restarts_pair_and_context_cannot_trade(self):
        rows = candles(); btc = candles()
        del btc[700*S.HOUR]
        result = A.generate('BTC_LEAD', 'X', rows, 0, btc)
        self.assertEqual(result['ready_hours'], 0)
        self.assertEqual(result['signals'], [])
        self.assertEqual(A.generate('BTC_LEAD', 'BTC', rows, 0, rows)['status'], 'CONTEXT_ONLY')


if __name__ == '__main__':
    unittest.main()
