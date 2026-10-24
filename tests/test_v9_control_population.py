import copy
import unittest
from tools.v9 import verify_control_population as V, control_signals as S
from tests import test_v9_control_signals as fixtures


class Reconciliation(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.Population();self.fixture.setUp()

    def verify(self, rows=None, population=None, loaded=None, raw=None):
        f=self.fixture
        loaded=loaded or f.loaded
        raw=f.raw if raw is None else raw
        source=V.Source(loaded['segment'],loaded['times'],loaded['volumes'],loaded['disputed_opens'],loaded['source_sha256'])
        summary,expected=f.run_rows(segments={'A':S.SegmentView(loaded)},raw=raw)
        return V.verify_trial('trial',raw,f.times,['A'],f.elig,{'A':source},30*86400,60*86400,
                              iter(expected if rows is None else rows),summary if population is None else population)

    def test_all_ordinals_geometry_and_terminal(self):
        result=self.verify()
        self.assertEqual((result['generated'],result['before_window'],result['retained']),(5,1,4))
        self.assertTrue(result['source_feature_values_verified'])
        self.assertFalse(result['original_generator_mathematics_verified'])
        self.assertFalse(result['externally_bound_inputs_verified'])

    def test_missing_extra_reordered_and_duplicate_rows(self):
        _,rows=self.fixture.run_rows()
        for changed in (rows[:-1],rows+[rows[-1]],list(reversed(rows)),[rows[0]]+rows[:-1]):
            with self.assertRaises(ValueError):self.verify(rows=changed)

    def test_signal_and_feature_tampering(self):
        changes=[lambda r:r['geometry'].update(stop=.03),lambda r:r.update(panel_i=0),
                 lambda r:r.update(next_entry_bar_observed=False),
                 lambda r:r['features'].update(mean_daily_quote_volume=1),
                 lambda r:r['features'].update(window_sha256='0'*64),
                 lambda r:r['history'].update(own_segment_missing_bars=1),
                 lambda r:r.update(original_eligible=1),lambda r:r.update(extra='unexpected'),
                 lambda r:r.update(source_sha256='b'*64)]
        for change in changes:
            _,rows=self.fixture.run_rows();change(rows[0])
            with self.assertRaises(ValueError):self.verify(rows=rows)

    def test_missing_disputed_zero_volume_and_history(self):
        f=self.fixture;loaded=copy.deepcopy(f.loaded)
        removed=loaded['times'].index(10*86400)
        loaded['times'].pop(removed);loaded['volumes'].pop(removed)
        loaded['disputed_opens']=[12*86400,29*86400]
        loaded['volumes'][loaded['times'].index(28*86400)]=0.
        self.assertEqual(self.verify(loaded=loaded)['retained'],4)
        removed=loaded['times'].index(28*86400)
        loaded['times'].pop(removed);loaded['volumes'].pop(removed)
        self.assertEqual(self.verify(loaded=loaded)['retained'],4)

    def test_hand_calculated_feature_window(self):
        times=list(range(0,8*86400,14400))
        source=V.Source(dict(asset='X',source_symbol='XUSDT',first_bar=0),times,[7.]*len(times),[], 'a'*64)
        feature,history=source.reconstruct(8*86400,1,False)
        self.assertEqual(feature['mean_daily_quote_volume'],42.)
        self.assertEqual(feature['volume_observations'],42)
        self.assertEqual((feature['volume_window_start'],feature['volume_window_end']),(86400,8*86400))
        self.assertEqual(history['own_segment_missing_bars'],0)

    def test_empty_counts_and_malformed_raw_rejected(self):
        self.assertEqual(self.verify(raw={k:[] for k in self.fixture.raw})['retained'],0)
        summary,_=self.fixture.run_rows();summary['generated']+=1
        with self.assertRaises(ValueError):self.verify(population=summary)
        for key,value in (('i',1.5),('stop',float('nan')),('hold',0)):
            raw=copy.deepcopy(self.fixture.raw);raw[key][0]=value
            f=self.fixture;loaded=f.loaded
            source=V.Source(loaded['segment'],loaded['times'],loaded['volumes'],[],loaded['source_sha256'])
            original,rows=f.run_rows()
            with self.assertRaises(ValueError):
                V.verify_trial('trial',raw,f.times,['A'],f.elig,{'A':source},30*86400,60*86400,rows,original)

    def test_source_validation(self):
        f=self.fixture;loaded=f.loaded
        for times,volumes,disputes in (([0,0],[1.,1.],[]),([0],[float('nan')],[]),([0],[1.],[0,0])):
            with self.assertRaises(ValueError):V.Source(loaded['segment'],times,volumes,disputes,'a'*64)
