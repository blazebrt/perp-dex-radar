import unittest
from tools.v9 import control_features as F, control_cohort as C


class Features(unittest.TestCase):
    def setUp(self):
        self.t=100*F.DAY
        self.times=list(range(0,self.t+F.DAY,F.BAR))
        self.volumes=[2_000_000.0]*len(self.times)
        self.segment=dict(asset='A',source_symbol='AUSDT',first_bar=0)

    def row(self,**kw):
        args=dict(segment=self.segment,times=self.times,volumes=self.volumes,
                  decision=self.t,direction=1,eligible=True,disputed_opens=[])
        args.update(kw)
        return F.snapshot(**args)

    def test_exact_window_and_intraday_cutoff(self):
        a=self.row(decision=self.t+F.BAR)
        self.assertEqual(a['volume_observations'],42)
        self.assertEqual(a['mean_daily_quote_volume'],12_000_000)
        self.assertEqual(a['volume_window_end'],self.t)
        self.assertEqual(a['volume_window_start'],self.t-7*F.DAY)
        self.assertIsNotNone(C.features(a,a['decision_time']))
        self.assertFalse(a['signal_quality_qualified'])

    def test_missing_and_disputed_overlap_retained(self):
        missing=self.t-F.BAR
        times=[t for t in self.times if t!=missing]
        row=self.row(times=times,volumes=[2e6]*len(times),disputed_opens=[missing])
        self.assertEqual(len(row['reasons']),2)
        self.assertEqual(row['missing_opens'],[missing])
        self.assertEqual(row['disputed_opens'],[missing])
        self.assertIsNone(row['mean_daily_quote_volume'])
        self.assertIsNone(C.features(row,self.t))

    def test_zero_is_observed_and_future_is_excluded(self):
        values=self.volumes.copy();values[self.times.index(self.t-F.BAR)]=0
        row=self.row(volumes=values)
        self.assertEqual(row['volume_observations'],42)
        self.assertEqual(row['mean_daily_quote_volume'],82e6/7)
        baseline=self.row()
        self.assertEqual(baseline,self.row(times=self.times+[self.times[-1]+F.BAR],
                         volumes=self.volumes+[999999999],disputed_opens=[self.t]))

    def test_dispute_window_edges(self):
        start=self.t-7*F.DAY
        self.assertEqual(self.row(disputed_opens=[start-F.BAR,self.t])['reasons'],[])
        self.assertEqual(self.row(disputed_opens=[start])['reasons'],['UNAVAILABLE_DISPUTED_VOLUME_BAR'])

    def test_relisting_identity_and_eligibility_preserved(self):
        with self.assertRaises(ValueError): self.row(segment=dict(self.segment,first_bar=F.DAY))
        row=self.row(eligible=False)
        self.assertFalse(row['eligible'])
        self.assertEqual(C.select('trial',row,[])['status'],'UNAVAILABLE_SIGNAL_FEATURES')
        first=self.t-5*F.DAY;times=[t for t in self.times if t>=first]
        row=self.row(segment=dict(self.segment,asset='A~2',first_bar=first),times=times,volumes=[2e6]*len(times))
        self.assertIsNone(C.features(row,self.t))

    def test_invalid_inputs_rejected(self):
        changes=[dict(disputed_opens=None),dict(disputed_opens=[0,0]),dict(disputed_opens=[True]),
                 dict(times=[0,0],volumes=[1,1]),dict(times=[0,1],volumes=[1,1]),
                 dict(times=[0],volumes=[float('nan')]),dict(times=[0],volumes=[True]),
                 dict(decision=True),dict(direction=True),dict(eligible=1)]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):self.row(**change)
