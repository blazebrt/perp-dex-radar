import unittest
from tools.v9.hourly_execution import simulate, HOUR


def candles(n=3):
    return {i * HOUR: dict(o=100, h=101, l=99, c=100, qv=1000) for i in range(1, n + 1)}


def run(rows, **kwargs):
    options = dict(signal_time=0, direction=1, stop=.05, hold=3,
                   funding={t: 0. for t in rows}, funding_complete={t: True for t in rows})
    options.update(kwargs)
    return simulate(rows, **options)


class HourlyExecutionTests(unittest.TestCase):
    def test_observed_zero_funding_and_time_exit_cost(self):
        result = run(candles())
        self.assertEqual(result['status'], 'RESOLVED')
        self.assertEqual(result['exit_time'], 4 * HOUR)
        self.assertAlmostEqual(result['net_R'], -0.0029 / .05)

    def test_absent_funding_is_not_zero_even_for_one_hour(self):
        for hold in (1, 3):
            result = run(candles(), funding={}, funding_complete={}, hold=hold)
            self.assertEqual(result['status'], 'UNRESOLVED_FUNDING')
            self.assertTrue(result['price_path_known'])
            self.assertEqual(result['gross_R'], 0)
            self.assertIsNone(result['net_R'])
            self.assertEqual(result['uncertainty_time'], HOUR)

    def test_gap_zero_volume_and_archive_end_never_fabricate_exit(self):
        for kind in ('missing', 'zero', 'end'):
            rows = candles()
            if kind == 'zero': rows[2 * HOUR]['qv'] = 0
            else: del rows[2 * HOUR]
            if kind == 'end': del rows[3 * HOUR]
            result = run(rows)
            self.assertEqual(result['status'], 'UNRESOLVED')
            self.assertIsNone(result['exit_price'])
            self.assertIsNone(result['gross_R'])
            self.assertIsNone(result['net_R'])
            self.assertEqual(result['uncertainty_time'], 2 * HOUR)

    def test_entry_rejection_and_no_delayed_entry(self):
        rows = candles()
        self.assertEqual(run(rows, entry_allowed=False)['reason'], 'ENTRY_GATE')
        del rows[HOUR]
        result = run(rows)
        self.assertEqual(result['status'], 'UNEXECUTED')
        self.assertEqual(result['reason'], 'UNOBSERVABLE_ENTRY')
        self.assertIsNone(result['entry_price'])

    def test_stop_before_target_and_gap_fill(self):
        for direction in (1, -1):
            rows = candles()
            rows[HOUR].update(h=110, l=90)
            result = run(rows, direction=direction, target=1)
            self.assertEqual(result['reason'], 'STOP')
            self.assertAlmostEqual(result['gross_R'], -1)
        rows = candles()
        rows[2 * HOUR].update(o=90, h=92, l=89, c=91)
        result = run(rows)
        self.assertEqual(result['reason'], 'GAP_STOP')
        self.assertEqual(result['exit_price'], 90)

    def test_trail_and_breakeven_take_effect_next_bar(self):
        rows = candles()
        rows[HOUR].update(h=110, l=99, c=108)
        rows[2 * HOUR].update(o=108, h=109, l=103, c=105)
        result = run(rows, trail=.04)
        self.assertEqual(result['exit_price'], 104)
        self.assertEqual(result['exit_time'], 3 * HOUR)
        result = run(rows, be=1)
        self.assertEqual(result['exit_price'], 100)
        self.assertEqual(result['exit_time'], 4 * HOUR)

    def test_funding_direction_and_entry_instant_exclusion(self):
        funding = {HOUR: .1, 2 * HOUR: .001, 3 * HOUR: -.0002}
        for direction in (1, -1):
            result = run(candles(), direction=direction, funding=funding)
            self.assertAlmostEqual(result['funding_R'], direction * .0008 / .05)
        result = run(candles(), funding=funding, funding_complete={HOUR: True, 3 * HOUR: True})
        self.assertIsNone(result['funding_R'])

    def test_future_missing_bar_does_not_cancel_observed_early_exit(self):
        rows = candles(1)
        rows[HOUR].update(h=106)
        result = run(rows, target=1)
        self.assertEqual(result['status'], 'RESOLVED')
        self.assertEqual(result['reason'], 'TARGET')
        self.assertAlmostEqual(result['net_R'], (0.05 - .0016) / .05)


if __name__ == '__main__':
    unittest.main()
