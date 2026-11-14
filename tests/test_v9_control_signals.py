import copy
import unittest
from tools.v9 import control_signals as S, control_features as F


class Population(unittest.TestCase):
    def setUp(self):
        self.times=list(range(0,60*F.DAY,F.BAR))
        self.loaded=dict(segment=dict(asset='A',source_symbol='AUSDT',first_bar=0),
                         times=self.times,volumes=[2e6]*len(self.times),disputed_opens=[],source_sha256='a'*64)
        self.view=S.SegmentView(self.loaded)
        self.raw=dict(i=[0,179,180,180,359],j=[0]*5,d=[1.,1.,-1.,-1.,1.],
                      stop=[.02]*5,target=[2.]*5,trail=[.01]*5,be=[1.]*5,hold=[6]*5)
        self.elig=[[True] for _ in self.times];self.elig[180]=[False]

    def run_rows(self,**changes):
        rows=[]
        args=dict(trial_id='trial',raw=self.raw,panel_times=self.times,panel_assets=['A'],
                  eligibility=self.elig,segments={'A':self.view},start=30*F.DAY,end=60*F.DAY,emit=rows.append)
        args.update(changes)
        return S.project(**args),rows

    def test_complete_denominator_duplicates_and_terminal(self):
        summary,rows=self.run_rows()
        self.assertEqual((summary['generated'],summary['before_window'],summary['retained']),(5,1,4))
        self.assertEqual([r['source_ordinal'] for r in rows],[1,2,3,4])
        self.assertEqual(len({r['signal_id'] for r in rows}),4)
        self.assertFalse(rows[1]['original_eligible'])
        self.assertFalse(rows[-1]['next_entry_bar_observed'])
        self.assertTrue(rows[0]['next_entry_bar_observed'])
        self.assertEqual(rows[1]['geometry'],dict(stop=.02,target=2.,trail=.01,be=1.,hold=6))
        self.assertFalse(summary['promotion_authority'])

    def test_indexed_windows_equal_full_source(self):
        for t in (0,5*F.DAY,30*F.DAY,30*F.DAY+F.BAR,60*F.DAY):
            with self.subTest(t=t):
                expected=F.snapshot(self.loaded['segment'],self.times,self.loaded['volumes'],t,1,False,[])
                self.assertEqual(self.view.snapshot(t,1,False),expected)

    def test_history_gaps_not_hidden_by_clean_feature_window(self):
        gap=10*F.DAY
        loaded=dict(self.loaded,times=[t for t in self.times if t!=gap],
                    volumes=[2e6]*(len(self.times)-1),disputed_opens=[12*F.DAY])
        view=S.SegmentView(loaded)
        _,rows=self.run_rows(segments={'A':view})
        self.assertEqual(rows[0]['history']['own_segment_missing_bars'],1)
        self.assertEqual(rows[0]['history']['own_segment_disputed_bars'],1)
        self.assertEqual(rows[0]['features']['feature_status'],'DIAGNOSTIC_WINDOW_AVAILABLE')
        self.assertFalse(rows[0]['history']['signal_quality_qualified'])

    def test_unavailable_features_do_not_remove_signals(self):
        view=S.SegmentView(dict(self.loaded,disputed_opens=[29*F.DAY]))
        summary,rows=self.run_rows(segments={'A':view})
        self.assertEqual(summary['retained'],4)
        self.assertEqual(rows[0]['features']['feature_status'],'UNAVAILABLE')

    def test_future_append_preserves_existing_features_and_identity(self):
        _,before=self.run_rows()
        future=self.times+[60*F.DAY]
        view=S.SegmentView(dict(self.loaded,times=future,volumes=self.loaded['volumes']+[9e9]))
        _,after=self.run_rows(panel_times=future,eligibility=self.elig+[[True]],segments={'A':view})
        for a,b in zip(before,after):
            self.assertEqual(a['signal_id'],b['signal_id'])
            self.assertEqual(a['features'],b['features'])
            self.assertEqual(a['history'],b['history'])
        # A newly observed next bar legitimately changes terminal availability.
        self.assertTrue(after[-1]['next_entry_bar_observed'])

    def test_invalid_generated_arrays_rejected(self):
        for key,value in [('i',-1),('j',2),('d',0),('hold',1.5),('stop',0),('target',float('nan')),('be',-1)]:
            with self.subTest(key=key):
                raw=copy.deepcopy(self.raw);raw[key][1]=value
                with self.assertRaises(ValueError):self.run_rows(raw=raw)
        raw=copy.deepcopy(self.raw);raw['hold'].pop()
        with self.assertRaises(ValueError):self.run_rows(raw=raw)

    def test_empty_generator_and_after_window_accounting(self):
        summary,rows=self.run_rows(raw={k:[] for k in S.KEYS})
        self.assertEqual(summary['generated'],0);self.assertEqual(rows,[])
        summary,rows=self.run_rows(end=30*F.DAY)
        self.assertEqual((summary['retained'],summary['after_window']),(1,3))
