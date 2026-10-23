import gzip
import json
import unittest
from tests import test_v9_control_outcomes as fixture
from tools.v9 import verify_control_outcomes as V


class Verification(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Outcomes();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.doc=self.f.run_study()
        self.bindings={k:self.doc[k] for k in ('input_commit','provenance','implementation_sha256','protocol_sha256')}

    def verify(self):return V.verify(self.f.out,self.f.source,self.f.digest,self.bindings)

    def rehash(self,path):
        for row in self.doc['files']:
            if row['path']==path.relative_to(self.f.out).as_posix():
                row.update(sha256=V.sha(path),bytes=path.stat().st_size)
        (self.f.out/'manifest.json').write_text(json.dumps(self.doc),encoding='utf8')

    def pair_change(self,fn):
        path=next(self.f.out.glob('0*.jsonl.gz'))
        rows=[json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()]
        fn(rows)
        path.write_bytes(gzip.compress((''.join(json.dumps(r)+'\n' for r in rows)).encode()))
        self.rehash(path)

    def test_success_is_limited_accounting_authority(self):
        result=self.verify();self.assertEqual(result['signals'],8);self.assertEqual(result['sides'],6)
        self.assertFalse(result['execution_paths_verified']);self.assertFalse(result['selection_verified'])

    def test_missing_outcome_rejected_even_after_rehash(self):
        self.pair_change(lambda rows:rows.pop())
        with self.assertRaises(ValueError):self.verify()

    def test_changed_geometry_rejected_even_after_rehash(self):
        self.pair_change(lambda rows:rows[0]['candidate']['geometry'].update(hold=999))
        with self.assertRaises(ValueError):self.verify()

    def test_sparse_pair_cannot_gain_contrast(self):
        self.pair_change(lambda rows:rows[0].update(price_difference_R=5))
        with self.assertRaises(ValueError):self.verify()

    def test_full_pair_arithmetic_rejected_after_rehash(self):
        from tools.v9 import control_pairs as P, control_execution as E
        import copy
        self.f.out=self.f.root/'full'
        def match(signal):
            candidates=[]
            for i in range(60):
                row=copy.deepcopy(signal['features']);row.update(asset=str(i),source_symbol=str(i))
                candidates.append(row)
            def execute(asset,t,d,g,eligible):
                return E.simulate({t+k*E.BAR:dict(o=100,h=101,l=99,c=100,qv=1) for k in range(g['hold'])},t,d,g,eligible,[],t+g['hold']*E.BAR)
            return P.match(signal,candidates,execute)
        self.f.match=match;self.doc=self.f.run_study()
        self.bindings={k:self.doc[k] for k in self.bindings}
        self.verify()
        def change(rows):
            self.assertEqual(rows[0]['pair_status'],'PRICE_PAIR_OBSERVED')
            rows[0]['control_mean_price_R']=999
        self.pair_change(change)
        with self.assertRaises(ValueError):self.verify()

    def test_summary_counts_and_inference_rejected(self):
        path=self.f.out/'sides.json';original=path.read_bytes()
        for key,value in [('signals',999),('p_value',.01)]:
            with self.subTest(key=key):
                rows=json.loads(original);rows[0][key]=value
                path.write_text(json.dumps(rows),encoding='utf8');self.rehash(path)
                with self.assertRaises(ValueError):self.verify()

    def test_hash_binding_and_unlisted_artifact_rejected(self):
        self.bindings['protocol_sha256']='wrong'
        with self.assertRaises(ValueError):self.verify()
        self.bindings['protocol_sha256']=self.doc['protocol_sha256']
        (self.f.out/'unlisted').write_text('bad')
        with self.assertRaises(ValueError):self.verify()
