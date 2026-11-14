"""A4 accounting oracle, missing-trial handling and synthetic archive integration."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    import numpy as np
    from tools.v9 import census_replay as R
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
try:
    import numba
    import pandas
    HAVE_SCI = HAVE_NUMPY
except ImportError:
    HAVE_SCI = False


@unittest.skipUnless(HAVE_NUMPY, 'numpy required')
class Accounting(unittest.TestCase):
    def test_exit_day_sum_and_exact_endpoint(self):
        rows = [dict(decision_time=1, exit_time=100, net_R=2.),
                dict(decision_time=1, exit_time=200, net_R=-.5),
                dict(decision_time=2, exit_time=2*R.DAY, net_R=3.)]
        np.testing.assert_equal(R.daily_returns(rows, 0, 2*R.DAY), [1.5, 0., 3.])

    def test_invalid_trades_rejected(self):
        for change in (dict(exit_time=3*R.DAY), dict(exit_time=-1), dict(net_R=float('nan')),
                       dict(net_R=float('inf')), dict(decision_time=True), dict(exit_time=1.5)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                R.daily_returns([dict(dict(decision_time=0, exit_time=10, net_R=1.), **change)],
                                0, 2*R.DAY)

    def test_missing_hourly_column_is_not_an_empty_trial(self):
        plan = dict(trials=[dict(trial_id='empty', archive_requirement='4h'),
                           dict(trial_id='hourly', archive_requirement='hourly')])
        sink = mock.Mock()
        matrix, summaries = R.replay(None, None, {}, plan, 0, 2*R.DAY,
                                    lambda *args: (0, []), sink)
        np.testing.assert_equal(matrix[:, 0], [0., 0., 0.])
        self.assertTrue(np.isnan(matrix[:, 1]).all())
        self.assertEqual(summaries[0]['trades'], 0)
        self.assertIsNone(summaries[1]['trades'])
        sink.assert_called_once_with('empty', [])
        stats = R.family_statistics(matrix, ['empty', 'hourly'], {}, 10)
        self.assertNotEqual(stats['pbo']['status'], 'AVAILABLE')
        self.assertNotEqual(stats['dsr']['status'], 'AVAILABLE')

    def test_simulator_error_aborts(self):
        plan = dict(trials=[dict(trial_id='a', archive_requirement='4h')])
        with self.assertRaisesRegex(RuntimeError, 'simulation failed'):
            R.replay(None, None, {}, plan, 0, R.DAY,
                     mock.Mock(side_effect=RuntimeError('simulation failed')), mock.Mock())

    def test_measured_sharpe_variance_and_constant_column(self):
        x = np.array([[1., 3.], [-1., 1.], [2., -1.], [0., 2.]])
        stats = R.family_statistics(x, ['a', 'b'], {}, 10)
        expected = np.var([.5/np.sqrt(5/3), 1.25/np.sqrt(35/12)], ddof=1)
        self.assertAlmostEqual(stats['trial_sharpe_variance'], expected)
        self.assertFalse(stats['dsr']['a']['trial_count_complete'])
        x[:, 1] = 0
        stats = R.family_statistics(x, ['a', 'b'], {}, 10)
        self.assertIsNone(stats['trial_sharpe_variance'])
        self.assertNotEqual(stats['dsr']['a']['status'], 'AVAILABLE')


@unittest.skipUnless(HAVE_SCI, 'numpy, pandas, numba required')
class SyntheticArchive(unittest.TestCase):
    def test_all_trials_artifacts_and_binding(self):
        from tests.test_v9_evidence import synthetic
        from tools.v9 import evidence as EV
        import qstrat
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            md, out = root / 'md', root / 'out'
            synthetic(str(md), 0., days=240, coins=8)
            # A partial final day exposes resample's mutation of panel views.
            # Full-day synthetic lives alone cannot catch fingerprint ordering.
            partial = md / 'h4/C07.csv.gz'
            with gzip.open(partial, 'rt') as fh:
                lines = fh.readlines()
            with gzip.open(partial, 'wt', newline='') as fh:
                fh.writelines(lines[:-1])
            panel = EV.ArchivePanel(str(md))
            raw_digest = R.digest_panel(panel)
            qstrat.Feat(panel)
            self.assertNotEqual(raw_digest, R.digest_panel(panel))
            reference = root / 'phase_b.json'
            reference.write_text(json.dumps(dict(provenance=dict(dataset_sha256=R.digest_panel(panel)))))
            binding = root / 'binding.json'
            binding.write_text(json.dumps(dict(inputs=dict(
                evidence_sha256=hashlib.sha256(reference.read_bytes()).hexdigest()))))
            # Only the test fixture replaces phase B's evidence binding. Production
            # always reads the committed binding; there is no CLI bypass.
            with mock.patch.object(R, 'BINDING', binding):
                doc = R.run(md, out, reference, replications=10)
                with np.load(out / 'daily_returns.npz', allow_pickle=False) as arrays:
                    matrix = arrays['returns']
                    self.assertEqual(matrix.shape[1], 199)
                    self.assertEqual(int(np.isnan(matrix).all(axis=0).sum()), 7)
                    self.assertEqual(len(set(arrays['trial_ids'])), 199)
                    sums = dict(zip(arrays['trial_ids'], np.nansum(matrix, axis=0)))
                totals = {}
                trade_files = json.loads((out / 'trades_a4.json').read_text())
                self.assertEqual(len(trade_files), 192)
                for name, info in trade_files.items():
                    self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), info['sha256'])
                    with gzip.open(out / name, 'rt') as fh:
                        rows = [json.loads(line) for line in fh]
                    self.assertEqual(len(rows), info['trades'])
                    for row in rows:
                        totals[row['trial_id']] = totals.get(row['trial_id'], 0) + row['net_R']
                self.assertTrue(totals, 'fixture must execute trades')
                for row in doc['trials']:
                    if row['status'] == 'REPLAYED':
                        self.assertAlmostEqual(sums[row['trial_id']], totals.get(row['trial_id'], 0))
                for name, sha in doc['artifacts'].items():
                    self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), sha)
                self.assertFalse(doc['known_trial_return_matrix_complete'])
                self.assertFalse(doc['promotion_authority'])
                self.assertNotEqual(doc['all_known_trials']['dsr']['status'], 'AVAILABLE')
                with self.assertRaisesRegex(ValueError, 'empty'):
                    R.run(md, out, reference, 10)
                with mock.patch.object(R, 'digest_panel', return_value='0' * 64):
                    with self.assertRaisesRegex(ValueError, 'dataset does not match'):
                        R.run(md, root / 'wrong-dataset', reference, 10)
                self.assertFalse((root / 'wrong-dataset').exists())
                with mock.patch.object(R.census_plan, 'build', return_value={}):
                    with self.assertRaisesRegex(ValueError, 'plan no longer matches'):
                        R.run(md, root / 'wrong-plan', reference, 10)
                with mock.patch.object(EV, 'trades_of', side_effect=RuntimeError('interrupted')):
                    with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                        R.run(md, root / 'interrupted', reference, 10)
                self.assertFalse((root / 'interrupted' / 'evidence_a4.json').exists())
                before = R.digest_panel(panel)
                panel.c[0, 0] += 1
                self.assertNotEqual(before, R.digest_panel(panel))
                reference.write_text('{}')
                with self.assertRaisesRegex(ValueError, 'binding'):
                    R.run(md, root / 'bad', reference, 10)
                self.assertFalse((root / 'bad').exists())


if __name__ == '__main__':
    unittest.main()
