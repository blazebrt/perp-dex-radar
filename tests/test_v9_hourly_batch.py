import copy
import unittest
from tools.v9 import hourly_batch as B


def setup():
    start, end = B.DAY, 3 * B.DAY
    rows = {c: {t: dict(o=100, h=101, l=99, c=100, qv=1000)
                for t in range(start, end, B.HOUR)} for c in ('A', 'B')}
    schedule = [dict(schedule=dict(known_at=t, valid_until=t + B.DAY,
                                  selected=[dict(coin='A'), dict(coin='B')]), new_entries_allowed=True)
                for t in range(start, end, B.DAY)]
    return rows, schedule, start, end


def signal(entry, coin='A', hold=1):
    return dict(signal_time=entry - B.HOUR, coin=coin, direction=1, stop=.05,
                target=0., trail=0., be=0., hold=hold)


def replay(signals, rows, schedule, start, end, complete=True):
    return B.replay(signals, rows, schedule, start, end,
                    funding={c: dict.fromkeys(data, 0.) for c, data in rows.items()},
                    funding_complete={c: dict.fromkeys(data, complete) for c, data in rows.items()})


class BatchTests(unittest.TestCase):
    def test_midnight_membership_and_embargo_without_backfill(self):
        rows, schedule, start, end = setup()
        schedule[1]['schedule']['selected'] = [dict(coin='B')]
        signals = [signal(2 * B.DAY), signal(2 * B.DAY, 'B')]
        result = replay(signals, rows, schedule, start, end)
        self.assertEqual([a['status'] for a in result['attempts']], ['UNEXECUTED', 'RESOLVED'])
        self.assertEqual(result['attempts'][0]['reason'], 'NOT_SELECTED_AT_ENTRY')
        schedule[1]['new_entries_allowed'] = False
        result = replay(signals, rows, schedule, start, end)
        self.assertTrue(all(a['reason'] == 'QUALITY_EMBARGO' for a in result['attempts']))

    def test_unknown_price_locks_segment_but_not_other_segment(self):
        rows, schedule, start, end = setup()
        del rows['A'][start + B.HOUR]
        signals = [signal(start, hold=3), signal(start + 4 * B.HOUR), signal(start + 4 * B.HOUR, 'B')]
        result = replay(signals, rows, schedule, start, end)
        self.assertEqual(result['attempts'][1]['reason'], 'BLOCKED_UNKNOWN_POSITION')
        self.assertEqual(result['attempts'][2]['status'], 'RESOLVED')
        self.assertFalse(result['net_series_available'])
        self.assertTrue(all(d['net_R'] is None for d in result['daily_net_R']))

    def test_unknown_funding_does_not_freeze_observed_closed_position(self):
        args = setup(); start = args[2]
        result = replay([signal(start), signal(start + B.HOUR)], *args, complete=False)
        self.assertEqual([a['status'] for a in result['attempts']], ['UNRESOLVED_FUNDING'] * 2)
        self.assertEqual(result['segments_locked_by_unknown_position'], [])
        self.assertFalse(result['net_series_available'])

    def test_busy_boundary_and_complete_daily_accounting(self):
        args = setup(); start = args[2]
        result = replay([signal(start, hold=2), signal(start + B.HOUR), signal(start + 2 * B.HOUR)], *args)
        self.assertEqual(result['attempts'][1]['reason'], 'POSITION_OPEN')
        self.assertEqual(result['attempts'][2]['status'], 'RESOLVED')
        self.assertAlmostEqual(sum(d['net_R'] for d in result['daily_net_R']), -2 * .0029 / .05)
        self.assertEqual(result['daily_net_R'][-1]['net_R'], 0.)

    def test_future_rows_cannot_resolve_archive_end_censoring(self):
        rows, schedule, start, end = setup()
        rows['A'][end] = dict(rows['A'][start])
        result = replay([signal(end - B.HOUR, hold=2)], rows, schedule, start, end)
        self.assertEqual(result['attempts'][0]['status'], 'UNRESOLVED')
        self.assertEqual(result['attempts'][0]['uncertainty_time'], end)

    def test_validation_and_input_preservation(self):
        rows, schedule, start, end = setup()
        before = copy.deepcopy((rows, schedule))
        replay([signal(start)], rows, schedule, start, end)
        self.assertEqual((rows, schedule), before)
        with self.assertRaisesRegex(ValueError, 'duplicate signal'):
            replay([signal(start), signal(start)], rows, schedule, start, end)
        with self.assertRaisesRegex(ValueError, 'exact study window'):
            replay([], rows, schedule[:1], start, end)
        bad = signal(start); bad['stop'] = float('nan')
        with self.assertRaises(ValueError):
            replay([bad], rows, schedule, start, end)


if __name__ == '__main__':
    unittest.main()
