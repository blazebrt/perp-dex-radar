import gzip
import json
from pathlib import Path
import tempfile
import unittest
from tests import test_v9_control_extract as fixtures
from tools.v9 import control_outcomes as O, control_extract as X, control_pairs as P, control_execution as E


class Outcomes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);f=fixtures.Extraction();f.setUp()
        self.context=f.context();self.source=self.root/'signals';self.out=self.root/'out'
        X.extract(self.source,lambda:self.context)
        self.digest=X.sha(self.source/'manifest.json');self.calls=0

    def match(self,signal):
        self.calls+=1
        def execute(asset,t,d,g,eligible):
            return E.simulate({t:dict(o=100,h=101,l=99,c=100,qv=1)},t,d,g,eligible,[],t+E.BAR)
        return P.match(signal,[],execute)

    def run_study(self,prepare=None,digest=None):
        return O.run(self.source,self.out,prepare or (lambda:(self.context,self)),digest or self.digest,max_rows=2)

    def test_complete_population_hourly_slots_and_file_hashes(self):
        result=self.run_study()
        self.assertEqual(result['status'],'COMPLETED_PRICE_DIAGNOSTICS_NET_UNAVAILABLE')
        self.assertEqual(result['processed_signals'],8);self.assertEqual(self.calls,8)
        self.assertEqual(len(result['completed_trials']),3)
        sides=json.loads((self.out/'sides.json').read_bytes())
        self.assertEqual(len(sides),6);self.assertTrue(all(r['net_mean'] is None for r in sides))
        for row in result['files']:self.assertEqual(X.sha(self.out/row['path']),row['sha256'])
        shards=list(self.out.glob('0*.jsonl.gz'))
        self.assertEqual(sum(len(gzip.decompress(p.read_bytes()).splitlines()) for p in shards),8)

    def test_unregistered_manifest_fails_before_preparation(self):
        def forbidden():raise AssertionError('must not prepare')
        result=self.run_study(forbidden,'0'*64)
        self.assertEqual(result['status'],'FAILED_OR_PARTIAL')
        self.assertEqual(result['error']['message'],'unregistered signal inventory')
        self.assertEqual(self.calls,0)

    def test_corrupt_shard_fails_before_outcomes(self):
        path=next(self.source.glob('*.gz'));path.write_bytes(b'bad')
        result=self.run_study()
        self.assertEqual(result['status'],'FAILED_OR_PARTIAL');self.assertEqual(self.calls,0)

    def test_partial_outputs_preserved_after_execution_failure(self):
        original=self.match
        def fail(signal):
            if self.calls==2:raise RuntimeError('synthetic interruption')
            return original(signal)
        self.match=fail
        result=self.run_study()
        self.assertEqual(result['status'],'FAILED_OR_PARTIAL')
        self.assertEqual(result['processed_signals'],2)
        self.assertEqual(result['completed_trials'],[])
        self.assertTrue(any(r['path'].endswith('.gz') for r in result['files']))
        self.assertFalse((self.out/'sides.json').exists())

    def test_existing_attempt_never_overwritten(self):
        with self.assertRaises(ValueError):O.run(self.source,self.source/'out',lambda:(self.context,self))
        self.assertFalse((self.source/'out').exists())
        self.run_study();before=(self.out/'manifest.json').read_bytes()
        with self.assertRaises(ValueError):self.run_study()
        self.assertEqual(before,(self.out/'manifest.json').read_bytes())

    def test_preparation_failure_retained(self):
        def fail():raise ValueError('unbound archive')
        result=self.run_study(fail)
        self.assertEqual(result['status'],'FAILED_OR_PARTIAL')
        self.assertEqual(result['error']['message'],'unbound archive')
