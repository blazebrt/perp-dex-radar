import copy
import gzip
from pathlib import Path
import tempfile
import unittest
from tools.v9 import hourly_funding as F
from tools.v9.hourly_execution import simulate


class FundingCoverageTests(unittest.TestCase):
    def test_regular_schedule_never_invents_zero_or_completeness(self):
        rows = [dict(t=t*3600, rate=.001, interval_h=8) for t in (0, 8, 16)]
        original = copy.deepcopy(rows)
        result = F.prepare(rows)
        self.assertEqual(result['funding_complete'], {})
        self.assertEqual(set(result['hourly_events']), {0, 8*3600, 16*3600})
        self.assertEqual(result['completeness_status'], 'UNAVAILABLE_SOURCE_COVERAGE')
        self.assertEqual(rows, original)

    def test_observed_zero_and_off_grid_event_are_preserved_separately(self):
        result = F.prepare([dict(t=3600, rate=0), dict(t=3601, rate=-.002)])
        self.assertEqual(result['hourly_events'], {3600: 0.})
        self.assertEqual(result['off_grid_events'], {3601: -.002})
        self.assertEqual(result['observed_events'], {3600: 0., 3601: -.002})
        self.assertEqual(result['funding_complete'], {})

    def test_archive_rows_cannot_make_observable_trade_net_known(self):
        funding = F.prepare([dict(t=3600, rate=0, interval_h=8)])
        rows = {3600: dict(o=100, h=101, l=99, c=100, qv=1000)}
        result = simulate(rows, 0, 1, .1, hold=1,
                          funding=funding['hourly_events'], funding_complete=funding['funding_complete'])
        self.assertEqual(result['status'], 'UNRESOLVED_FUNDING')
        self.assertEqual(result['gross_R'], 0.)
        self.assertIsNone(result['net_R'])

    def test_strict_archive_parser_and_empty_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'fund.csv.gz'
            for text, expected in [('t,rate,interval_h\n', {}),
                                   ('t,rate,interval_h\n3600,0,\n', {3600: 0.})]:
                with gzip.open(p, 'wt') as fh: fh.write(text)
                result = F.read(p)
                self.assertEqual(result['observed_events'], expected)
                self.assertEqual(result['funding_complete'], {})
            for text in ('t,rate\n', 't,rate,interval_h\n3600,0,8,extra\n',
                         't,rate,interval_h\n3600,nan,8\n',
                         't,rate,interval_h\n3600,0\n'):
                with gzip.open(p, 'wt') as fh: fh.write(text)
                with self.assertRaises(ValueError): F.read(p)

    def test_invalid_and_duplicate_events_fail_closed(self):
        for rows in ([dict(t=0, rate=0), dict(t=0, rate=0)],
                     [dict(t=True, rate=0)], [dict(t=-1, rate=0)],
                     [dict(t=0, rate=float('inf'))], [dict(t=0, rate=True)],
                     [dict(t=0, rate=0, interval_h=0)], [dict(t=0, rate=0, interval_h=1.5)]):
            with self.assertRaises(ValueError): F.prepare(rows)


if __name__ == '__main__': unittest.main()
