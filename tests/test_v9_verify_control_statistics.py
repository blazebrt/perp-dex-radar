import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from tests import test_v9_control_pairs as fixture
from tools.v9 import control_summary as S, verify_control_statistics as V


class Statistics(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        f=fixture.Pairs();f.setUp();base=f.matched();self.pairs=[]
        for i,delta in enumerate((-3.,0.,2.,9.)):
            pair=copy.deepcopy(base);pair['signal_id']=str(i)
            pair['candidate']['price_after_cost_R']+=delta;pair['candidate_price_R']+=delta;pair['price_difference_R']+=delta
            self.pairs.append(pair)
        self.trials=[dict(trial_id='trial',archive_requirement='4h'),dict(trial_id='hour',archive_requirement='hourly')]
        self.build()

    def build(self):
        path=self.root/('production-'+str(len(list(self.root.iterdir())))+'.db')
        summary=S.Summary(path,self.trials);self.days=[];self.reuse=[]
        try:
            for pair in self.pairs:summary.add(pair)
            self.sides=summary.finish(self.days.append,self.reuse.append)
        finally:summary.close()

    def audit(self):
        return V.verify(iter(self.pairs),self.trials,self.sides,iter(self.days),iter(self.reuse),
                        self.root/('audit-'+str(len(list(self.root.iterdir())))+'.db'))

    def test_exact_median_means_and_reuse(self):
        result=self.audit();self.assertEqual(result['signals'],4)
        side=self.sides[1];self.assertAlmostEqual(side['conditional_price']['difference_median'],1.5)
        self.assertAlmostEqual(side['conditional_price']['difference_mean'],2.5)
        self.assertEqual(sum(r['uses'] for r in self.reuse),200)

    def test_each_statistic_tampering_rejected(self):
        for field in ('candidate_mean','control_mean','difference_mean','difference_median','difference_min','difference_max'):
            original=copy.deepcopy(self.sides)
            self.sides[1]['conditional_price'][field]+=1
            with self.subTest(field=field),self.assertRaises(ValueError):self.audit()
            self.sides=original

    def test_missing_day_and_changed_reuse_rejected(self):
        days=self.days;self.days=[]
        with self.assertRaises(ValueError):self.audit()
        self.days=days;self.reuse[0]['uses']+=1
        with self.assertRaises(ValueError):self.audit()

    def test_incomplete_population_does_not_gain_complete_mean(self):
        pair=self.pairs[-1];pair.update(pair_status='UNRESOLVED_PAIR',candidate_price_R=None,control_mean_price_R=None,price_difference_R=None)
        pair['candidate'].update(status='UNRESOLVED_PRICE',price_path_known=False,price_after_cost_R=None)
        self.build();self.audit()
        self.sides[1]['complete_pair_population_price_mean']=0.
        with self.assertRaises(ValueError):self.audit()

    def test_empty_sides_unavailable_hourly_and_duplicate_ids(self):
        pairs=self.pairs;self.pairs=[];self.build();self.audit()
        self.sides[-1]['conditional_price']['count']=0
        with self.assertRaises(ValueError):self.audit()
        self.pairs=pairs+[pairs[0]]
        with self.assertRaises(sqlite3.IntegrityError):self.audit()
