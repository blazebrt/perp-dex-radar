import unittest
from tools.v9 import control_cohort as C


def row(asset='signal', age=100, volume=15_000_000, **changes):
    t=1000*C.DAY
    result=dict(asset=asset, source_symbol=asset+'USDT', decision_time=t, direction=1,
                eligible=True, provenance='ARCHIVE_RECONSTRUCTION', segment_first_bar=t-age*C.DAY,
                first_bar_known_at=t-age*C.DAY, volume_window_start=t-7*C.DAY,
                volume_window_end=t, volume_known_at=t, volume_observations=42,
                mean_daily_quote_volume=volume)
    result.update(changes)
    return result


class Cohort(unittest.TestCase):
    def test_exact_boundaries_and_relisting_age(self):
        for age,index in [(30,0),(89,0),(90,1),(180,2),(365,3),(730,4)]:
            self.assertEqual(C.features(row(age=age),1000*C.DAY)['archive_age_bucket'],index)
        for volume,index in [(5e6,0),(10e6,1),(25e6,2),(50e6,3),(100e6,4)]:
            self.assertEqual(C.features(row(volume=volume),1000*C.DAY)['liquidity_bucket'],index)
        for r in (row(age=29),row(volume=4_999_999),row(asset='signal~2',age=5)):
            self.assertIsNone(C.features(r,1000*C.DAY))

    def test_fifty_unique_deterministic_controls_and_no_authority(self):
        candidates=[row(str(k)) for k in range(80)]
        a=C.select('trial',row(),candidates)
        self.assertEqual(a,C.select('trial',row(),list(reversed(candidates))))
        self.assertEqual(a['control_count'],50)
        self.assertEqual(len({x['asset'] for x in a['controls']}),50)
        self.assertEqual(a['status'],'DIAGNOSTIC_COHORT_50')
        self.assertFalse(a['full_matched_authority'])
        self.assertFalse(a['promotion_authority'])

    def test_future_outcomes_and_other_times_do_not_change_selection(self):
        candidates=[row(str(k)) for k in range(60)]
        expected=C.select('trial',row(),candidates)
        changed=[dict(r,net_R=999,exit_time=9999999999) for r in candidates]
        changed += [row('future',decision_time=1001*C.DAY),row('past',decision_time=999*C.DAY),row('short',direction=-1)]
        self.assertEqual(expected,C.select('trial',row(),changed))

    def test_sparse_no_widening_and_exact_accounting(self):
        candidates=[row('one'),row('two'),row('alias',source_symbol='signalUSDT'),
                    row('young',age=35),row('rich',volume=100e6),row('unknown',volume_known_at=1001*C.DAY)]
        result=C.select('trial',row(),candidates)
        self.assertEqual((result['control_count'],result['matching_candidates']), (2,2))
        self.assertEqual(result['status'],'INSUFFICIENT_CONTROLS')
        self.assertEqual((result['same_symbol_excluded'],result['bucket_mismatched'],result['feature_unavailable']),(1,2,1))

    def test_invalid_and_missing_features_never_gain_authority(self):
        changes=[dict(volume_observations=41),dict(mean_daily_quote_volume=True),dict(mean_daily_quote_volume=float('nan')),
                 dict(provenance='PIT_OBSERVED'),dict(volume_window_end=999*C.DAY),
                 dict(first_bar_known_at=1001*C.DAY),dict(volume_known_at=999*C.DAY),dict(segment_first_bar=True)]
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(C.select('trial',row(**change),[])['status'],'UNAVAILABLE_SIGNAL_FEATURES')

    def test_ambiguous_identities_and_bad_signal_rejected(self):
        for rows in ([row('a'),row('a')],[row('a'),row('b',source_symbol='aUSDT')],[row(' ')]):
            with self.assertRaises(ValueError): C.select('trial',row(),rows)
        for change in (dict(direction=True),dict(decision_time=True),dict(asset='')):
            with self.assertRaises(ValueError): C.select('trial',row(**change),[])
