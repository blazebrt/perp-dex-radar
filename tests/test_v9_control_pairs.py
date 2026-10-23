import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from tools.v9 import control_pairs as P, control_summary as S, control_execution as E
from tests.test_v9_control_cohort import row


class Pairs(unittest.TestCase):
    def setUp(self):
        self.feature=row()
        self.signal=dict(trial_id='trial',signal_id='s0',source_ordinal=0,asset='signal',decision_time=self.feature['decision_time'],
                         direction=1,original_eligible=True,features=self.feature,
                         geometry=dict(stop=.02,target=0.,trail=0.,be=0.,hold=1))
        self.candidates=[row(str(i)) for i in range(60)]
        self.calls=[]

    def execute(self,asset,t,d,g,eligible):
        self.calls.append((asset,t,d,dict(g),eligible))
        close=101 if asset=='signal' else 100
        return E.simulate({t:dict(o=100,h=101.5,l=99,c=close,qv=1000)},t,d,g,eligible,[],t+E.BAR)

    def matched(self):return P.match(self.signal,self.candidates,self.execute)

    def test_fifty_fixed_before_execution_and_equal_geometry(self):
        result=self.matched()
        self.assertEqual(len(self.calls),51)
        self.assertTrue(all(call[3]==self.signal['geometry'] for call in self.calls))
        self.assertAlmostEqual(result['price_difference_R'],.5)
        self.assertIsNone(result['net_difference_R'])
        def mutate(asset,t,d,g,eligible):
            self.candidates.clear()
            return self.execute(asset,t,d,g,eligible)
        again=P.match(self.signal,list(reversed(self.candidates)),mutate)
        self.assertEqual(result['cohort'],again['cohort'])

    def test_unresolved_selected_control_not_replaced(self):
        baseline=self.matched();bad=baseline['controls'][0]['asset'];self.calls=[]
        def execute(asset,t,d,g,eligible):
            return E.simulate({},t,d,g,eligible,[],t+E.BAR) if asset==bad else self.execute(asset,t,d,g,eligible)
        result=P.match(self.signal,self.candidates,execute)
        self.assertEqual(result['cohort'],baseline['cohort'])
        self.assertEqual(result['pair_status'],'UNRESOLVED_PAIR')
        self.assertIsNone(result['price_difference_R']);self.assertEqual(len(result['controls']),50)

    def test_sparse_and_ineligible_signals_remain(self):
        result=P.match(self.signal,self.candidates[:3],self.execute)
        self.assertEqual(len(result['controls']),3);self.assertIsNone(result['price_difference_R'])
        self.signal['original_eligible']=False;self.feature['eligible']=False
        result=self.matched()
        self.assertEqual(result['candidate']['status'],'UNEXECUTED')
        self.assertEqual(result['cohort']['status'],'UNAVAILABLE_SIGNAL_FEATURES')

    def test_descriptive_denominators_median_days_reuse_and_empty_slots(self):
        trials=[dict(trial_id='trial',archive_requirement='4h'),dict(trial_id='hour',archive_requirement='hourly')]
        with tempfile.TemporaryDirectory() as directory:
            summary=S.Summary(Path(directory)/'summary.db',trials)
            try:
                first=self.matched();summary.add(first)
                second=copy.deepcopy(first);second['signal_id']='s1';second['source_ordinal']=1;summary.add(second)
                sparse=P.match(dict(self.signal,signal_id='s2',source_ordinal=2),self.candidates[:2],self.execute);summary.add(sparse)
                days=[];reuse=[];result=summary.finish(days.append,reuse.append)
                side=next(r for r in result if r['trial_id']=='trial' and r['direction']==1)
                self.assertEqual((side['signals'],side['matched_fifty'],side['resolved_pairs']),(3,2,2))
                self.assertAlmostEqual(side['matching_coverage'],2/3)
                self.assertAlmostEqual(side['conditional_price']['difference_median'],.5)
                self.assertIsNone(side['p_value']);self.assertIsNone(side['net_mean'])
                self.assertEqual(days[0]['signals'],3)
                self.assertEqual(sum(r['uses'] for r in reuse),102)
                self.assertTrue(all(r['signals'] is None for r in result if r['trial_id']=='hour'))
                self.assertEqual(result[0]['status'],'EMPTY_SIDE')
                with self.assertRaises(sqlite3.IntegrityError):summary.add(first)
                with self.assertRaises(ValueError):S.Summary(Path(directory)/'summary.db',trials)
            finally:summary.close()

    def test_incomplete_pair_population_mean_not_resolved_subset(self):
        with tempfile.TemporaryDirectory() as directory:
            summary=S.Summary(Path(directory)/'s.db',[dict(trial_id='trial',archive_requirement='4h')])
            try:
                summary.add(self.matched())
                second=dict(self.signal,signal_id='s1',source_ordinal=1)
                def unknown(asset,t,d,g,eligible):return E.simulate({},t,d,g,eligible,[],t+E.BAR)
                summary.add(P.match(second,self.candidates,unknown))
                result=summary.finish(lambda r:None,lambda r:None)[1]
                self.assertEqual(result['unresolved_pairs'],1)
                self.assertIsNone(result['complete_pair_population_price_mean'])
                self.assertAlmostEqual(result['conditional_price']['difference_mean'],.5)
            finally:summary.close()

    def test_tampered_pair_or_funding_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            summary=S.Summary(Path(directory)/'s.db',[dict(trial_id='trial',archive_requirement='4h')])
            try:
                result=self.matched();result['price_difference_R']=999
                with self.assertRaises(ValueError):summary.add(result)
                result=self.matched();result['candidate']['net_R']=0
                with self.assertRaises(ValueError):summary.add(result)
            finally:summary.close()

    def test_all_398_sides_exist_even_with_no_records(self):
        trials=[dict(trial_id=str(i),archive_requirement='4h' if i<192 else 'hourly') for i in range(199)]
        with tempfile.TemporaryDirectory() as directory:
            summary=S.Summary(Path(directory)/'s.db',trials)
            try:
                result=summary.finish(lambda r:None,lambda r:None)
                self.assertEqual(len(result),398)
                self.assertEqual(sum(r['status']=='UNAVAILABLE_HOURLY_POPULATION' for r in result),14)
                self.assertTrue(all(r['p_value'] is None and r['net_mean'] is None for r in result))
            finally:summary.close()
