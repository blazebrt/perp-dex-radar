import copy
import gzip
import hashlib
from pathlib import Path
import tempfile
import unittest
from tools.v9 import control_adapter as A, control_signals as S
from tests import test_v9_control_signals as fixture


class Adapter(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.Population();self.fixture.setUp()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'h4').mkdir()
        self.write()

    def write(self,bad=False):
        f=self.fixture
        text='t,o,h,l,c,qv\n'+''.join(f'{t},100,101,99,{"bad" if bad else "100"},2000000\n' for t in f.times)
        raw=gzip.compress(text.encode(),mtime=0)
        (self.root/'h4/A.csv.gz').write_bytes(raw)
        f.loaded['source_sha256']=hashlib.sha256(raw).hexdigest();f.view=S.SegmentView(f.loaded)
        _,self.rows=f.run_rows()
        self.context=dict(trials=[dict(trial_id='trial',archive_requirement='4h')],times=f.times,
                          assets=['A'],eligibility=f.elig,segments={'A':f.view},start=30*86400,end=60*86400)
        self.adapter=A.Adapter(self.root,self.context,1)

    def test_bound_prices_and_sparse_candidate_attempt(self):
        result=self.adapter.match(self.rows[0])
        self.assertEqual(result['candidate']['status'],'PRICE_OBSERVED_FUNDING_UNKNOWN')
        self.assertEqual(result['cohort']['status'],'INSUFFICIENT_CONTROLS')
        self.assertIsNone(result['net_difference_R'])
        self.assertEqual(len(self.adapter.prices),1)

    def test_corrupt_price_bytes_rejected(self):
        (self.root/'h4/A.csv.gz').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.adapter.match(self.rows[0])

    def test_retained_identity_features_and_history_rejected(self):
        for key,value in [('signal_id','wrong'),('panel_i',0),('source_sha256','wrong'),
                          ('original_eligible',False),('history',{}),('features',{}),('promotion_authority',True)]:
            with self.subTest(key=key):
                row=copy.deepcopy(self.rows[0]);row[key]=value
                with self.assertRaises(ValueError):self.adapter.match(row)

    def test_ineligible_and_terminal_preserved(self):
        self.assertEqual(self.adapter.match(self.rows[1])['candidate']['reason'],'ENTRY_INELIGIBLE')
        self.assertEqual(self.adapter.match(self.rows[-1])['candidate']['reason'],'ARCHIVE_END')

    def test_malformed_price_remains_unobservable(self):
        self.write(bad=True)
        self.assertEqual(self.adapter.match(self.rows[0])['candidate']['reason'],'MALFORMED_BAR')

    def test_disputed_price_rejected_and_cache_bounded(self):
        t=self.rows[0]['decision_time'];self.fixture.view.disputed=[t]
        # The execution quarantine is independent from the past feature window.
        self.rows[0]['history']=self.fixture.view.history(t)
        result=self.adapter.match(self.rows[0])
        self.assertEqual(result['candidate']['reason'],'DISPUTED_BAR')
        with self.assertRaises(ValueError):A.Adapter(self.root,self.context,0)
