"""Synthetic malformed-evidence and missing-return acceptance tests."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy as np
except ModuleNotFoundError:
    np = None
if np is not None:
    from tools.v9 import family_assembly as F


@unittest.skipIf(np is None, 'numpy required')
class Assembly(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((F.ROOT / F.PLAN).read_text())
        self.ids = [t['trial_id'] for t in self.plan['trials']]
        self.days = np.arange(3)
        self.values = np.zeros((3, 199))
        self.a4 = dict(window=[0, 172800], trials=[], promotion_authority=False,
                       historical_trial_census_complete=False, known_trial_return_matrix_complete=False,
                       confirmed=[], all_known_trials={k: dict(status='UNAVAILABLE_INSUFFICIENT_DATA',
                       reason='missing columns') for k in ('dsr', 'pbo', 'bootstrap')})
        self.a4['all_known_trials']['trial_sharpe_variance'] = None
        self.a5 = dict(window=[0, 172800], trials={}, funding_coverage='UNAVAILABLE_SOURCE_COVERAGE',
                       promotion_authority=False, historical_trial_census_complete=False,
                       known_trial_return_matrix_complete=False, confirmed=[])
        self.v = dict(result_commit=F.A5, full_family_complete=False, promotion_authority=False,
                      reports=dict(artifact=dict(all_artifact_hashes_verified=True,
                      trial_accounting_verified=True, trials={}),
                      price=dict(every_retained_attempt_reconciled=True),
                      signal=dict(every_successfully_generated_segment_population_reconciled=True)))
        for k, t in enumerate(self.plan['trials']):
            hourly = t['archive_requirement'] == 'hourly'
            self.a4['trials'].append(dict(trial_id=t['trial_id'],
                status='PENDING_A5_HOURLY_ARCHIVE' if hourly else 'REPLAYED'))
            if not hourly:
                self.values[1, k] = k / 10
                continue
            self.values[:, k] = np.nan
            alias = t['aliases'][0]
            status = ('UNAVAILABLE_CAUSAL_QUORUM_MAPPING' if alias == 'FUND_CARRY' else
                      'UNAVAILABLE_PARTIAL_REPLAY' if alias == 'FUND_FADE' else 'REPLAYED')
            h = dict(trial_id=t['trial_id'], params=t['params'], status=status,
                     net_series_available=False, daily_net_R=[dict(day=d*86400, net_R=None) for d in range(3)],
                     attempt_counts={'UNRESOLVED_FUNDING': 2}, segments=1, failed_segments=0,
                     unavailable_segments=0)
            self.a5['trials'][alias] = h
            self.v['reports']['artifact']['trials'][alias] = dict(counts=h['attempt_counts'].copy(),
                attempts=2, segments=1, failed_segments=0, unavailable_segments=0)

    def matrix(self):
        buf = io.BytesIO()
        np.savez_compressed(buf, days=self.days, trial_ids=self.ids, returns=self.values)
        return buf.getvalue()

    def check(self):
        return F.validate(self.plan, self.a4, self.a5, self.matrix(), self.v)

    def test_keeps_every_cell_and_unavailable_authority(self):
        columns, days = self.check()
        self.assertEqual((len(columns), days), (199, 3))
        self.assertEqual(sum(c['status'] == 'UNAVAILABLE_NET_RETURN_SERIES' for c in columns), 7)
        prepared = dict(matrix=self.matrix(), columns=columns, days=days,
                        inherited_statistics=self.a4['all_known_trials'])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            manifest = F.write_output(prepared, out)
            self.assertEqual((out/'daily_returns.npz').read_bytes(), prepared['matrix'])
            self.assertFalse(manifest['promotion_authority'])
            self.assertFalse(manifest['statistics_recomputed'])
            self.assertFalse(manifest['known_trial_return_matrix_complete'])
            self.assertEqual(manifest['confirmed'], [])
            with self.assertRaises(ValueError):
                F.write_output(prepared, out)

    def test_rejects_reordered_duplicate_or_missing_identity(self):
        for kind in ('order', 'duplicate', 'missing'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'order': self.ids = self.ids[::-1]
                if kind == 'duplicate': self.plan['trials'][1] = self.plan['trials'][0]
                if kind == 'missing': self.a4['trials'].pop()
                with self.assertRaises(ValueError): self.check()

    def test_rejects_dates_and_missing_value_substitutions(self):
        for kind in ('window', 'day', 'four_nan', 'hour_zero', 'hour_inf'):
            with self.subTest(kind=kind):
                self.setUp()
                hourly = next(k for k,t in enumerate(self.plan['trials']) if t['archive_requirement']=='hourly')
                four = next(k for k,t in enumerate(self.plan['trials']) if t['archive_requirement']=='4h')
                if kind == 'window': self.a5['window'][1] += 86400
                if kind == 'day': self.days[1] = 0
                if kind == 'four_nan': self.values[0,four] = np.nan
                if kind == 'hour_zero': self.values[0,hourly] = 0
                if kind == 'hour_inf': self.values[0,hourly] = np.inf
                with self.assertRaises(ValueError): self.check()

    def test_rejects_changed_hourly_definition_counts_or_availability(self):
        for kind in ('params', 'available', 'value', 'count', 'segment', 'identity'):
            with self.subTest(kind=kind):
                self.setUp()
                h=self.a5['trials']['BTC_LEAD']
                if kind == 'params': h['params'] = {'changed': True}
                if kind == 'available': h['net_series_available'] = True
                if kind == 'value': h['daily_net_R'][0]['net_R'] = 0
                if kind == 'count': h['attempt_counts']['UNRESOLVED_FUNDING'] = 3
                if kind == 'segment': h['failed_segments'] = 1
                if kind == 'identity': h['trial_id'] = 'changed'
                with self.assertRaises(ValueError): self.check()

    def test_rejects_authority_statistics_and_verification_claims(self):
        for kind in ('authority', 'statistic', 'verification'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'authority': self.a5['promotion_authority'] = True
                if kind == 'statistic': self.a4['all_known_trials']['pbo']['status'] = 'AVAILABLE'
                if kind == 'verification': self.v['result_commit'] = 'wrong'
                with self.assertRaises(ValueError): self.check()

    def test_hash_tamper_and_preflight_failure_retained(self):
        with self.assertRaises(ValueError): F.checked(b'changed', F.digest(b'original'), 'source')
        with tempfile.TemporaryDirectory() as tmp, patch.object(F, 'prepare', side_effect=ValueError('bad source')):
            out=Path(tmp)/'out'
            with self.assertRaises(ValueError): F.run(tmp,out)
            self.assertTrue((out/'failure.json').exists())
            self.assertFalse((out/'assembly.json').exists())

    def test_writer_failure_never_leaves_completion(self):
        columns,days=self.check()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            prepared=dict(matrix=self.matrix(), columns=columns, days=days, invalid=float('nan'))
            with self.assertRaises(ValueError): F.write_output(prepared,out)
            self.assertTrue((out/'failure.json').exists())
            self.assertFalse((out/'assembly.json').exists())
