import gzip
import json
from pathlib import Path
import unittest
from tests import test_v9_control_adapter as fixture
from tools.v9 import control_extract as X, control_adapter as A, control_outcomes as O
from tools.v9 import audit_control_outcomes as B, verify_control_population as P


class Audit(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Adapter();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.root;c=self.f.context;view=c['segments']['A']
        c['trials']=[dict(trial_id='0'*64,archive_requirement='4h'),dict(trial_id='1'*64,archive_requirement='hourly')]
        c['provenance']={'synthetic':True};c['generate']=lambda t:self.f.fixture.raw
        self.signals=self.root/'signals';X.extract(self.signals,lambda:c)
        self.input_hash=X.sha(self.signals/'manifest.json')
        self.output=self.root/'outcomes'
        self.doc=O.run(self.signals,self.output,lambda:(c,A.Adapter(self.root,c)),self.input_hash)
        self.assertEqual(self.doc['status'],'COMPLETED_PRICE_DIAGNOSTICS_NET_UNAVAILABLE')
        source=P.Source(view.segment,view.times,view.volumes,view.disputed,view.source_sha256)
        self.context=dict(plan=dict(trials=c['trials']),times=c['times'],assets=c['assets'],eligibility=c['eligibility'],
                          start=c['start'],end=c['end'],sources={'A':source})
        self.bindings={k:self.doc[k] for k in ('input_commit','provenance','implementation_sha256','protocol_sha256')}
        self.out=self.root/'audit'

    def run_audit(self):
        return B.run(self.output,self.signals,self.out,
                     lambda:(self.context,B.Prices(self.root,self.context['sources']),self.bindings),self.input_hash)

    def rehash(self,path):
        for row in self.doc['files']:
            if row['path']==path.relative_to(self.output).as_posix():row.update(sha256=X.sha(path),bytes=path.stat().st_size)
        (self.output/'manifest.json').write_text(json.dumps(self.doc),encoding='utf8')

    def test_all_audit_layers_and_source_paths(self):
        result=self.run_audit()
        self.assertEqual(result['status'],'VERIFIED_REGISTERED_PRICE_DIAGNOSTICS')
        self.assertEqual(result['signals'],4);self.assertEqual(result['candidate_paths'],4)
        self.assertTrue(result['source_bound_selection_verified']);self.assertTrue(result['statistics']['descriptive_statistics_verified'])
        self.assertFalse(result['net_inference_available'])
        self.assertEqual({p.name for p in self.out.iterdir()},{'audit.json'})

    def test_source_corruption_and_failed_audit_retained(self):
        (self.root/'h4/A.csv.gz').write_bytes(b'bad')
        result=self.run_audit();self.assertEqual(result['status'],'FAILED')
        self.assertTrue((self.out/'failure.json').exists())

    def test_rehashed_wrong_exit_rejected(self):
        path=next(self.output.glob('0*.gz'))
        rows=[json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()]
        rows[0]['candidate']['exit_price']=999
        path.write_bytes(gzip.compress((''.join(json.dumps(r)+'\n' for r in rows)).encode()))
        self.rehash(path)
        result=self.run_audit();self.assertEqual(result['status'],'FAILED')
        self.assertIn('price audit mismatch',result['error']['message'])

    def test_source_eligibility_mismatch_rejected(self):
        self.context['eligibility'][179][0]=False
        result=self.run_audit();self.assertEqual(result['status'],'FAILED')
        self.assertIn('signal/source mismatch',result['error']['message'])

    def test_existing_and_overlapping_audits_never_overwritten(self):
        self.run_audit();before=(self.out/'audit.json').read_bytes()
        with self.assertRaises(ValueError):self.run_audit()
        self.assertEqual(before,(self.out/'audit.json').read_bytes())
        with self.assertRaises(ValueError):B.run(self.output,self.signals,self.output/'audit',lambda:None)
