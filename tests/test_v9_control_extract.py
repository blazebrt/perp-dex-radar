import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.v9 import control_extract as E
from tests import test_v9_control_signals as fixtures


class Extraction(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Population()
        self.fixture.setUp()
        self.calls = []

    def context(self, count=3):
        f = self.fixture
        trials = [dict(trial_id='%064x' % i, archive_requirement='hourly' if i==count-1 else '4h') for i in range(count)]
        def generate(trial):
            self.calls.append(trial['trial_id'])
            return f.raw
        return dict(trials=trials, times=f.times, assets=['A'], eligibility=f.elig,
                    segments={'A':f.view}, start=30*86400, end=60*86400,
                    provenance={'synthetic':True}, generate=generate)

    def test_all_199_identities_once_and_exact_shards(self):
        c = self.context(199)
        for t in c['trials'][-7:]: t['archive_requirement']='hourly'
        with tempfile.TemporaryDirectory() as directory:
            result = E.extract(directory, lambda:c, max_rows=3)
            self.assertEqual(len(result['trials']),199)
            self.assertEqual(len(self.calls),192)
            self.assertEqual(len(set(self.calls)),192)
            for trial in result['trials'][:192]:
                self.assertEqual(trial['population']['retained'],4)
                self.assertEqual([s['records'] for s in trial['shards']],[3,1])
                records=[]
                for shard in trial['shards']:
                    raw=(Path(directory)/shard['path']).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(),shard['sha256'])
                    decoded=gzip.decompress(raw)
                    self.assertEqual(len(decoded),shard['uncompressed_bytes'])
                    records.extend(json.loads(line) for line in decoded.splitlines())
                self.assertEqual([r['source_ordinal'] for r in records],[1,2,3,4])
            self.assertTrue(all(t['population'] is None for t in result['trials'][-7:]))
            self.assertFalse(result['outcomes_computed'])

    def test_partial_projection_kept_and_other_trials_continue(self):
        c=self.context()
        def generate(trial):
            raw={k:list(v) for k,v in self.fixture.raw.items()}
            if trial==c['trials'][0]: raw['hold'][-1]=0
            return raw
        c['generate']=generate
        with tempfile.TemporaryDirectory() as directory:
            result=E.extract(directory,lambda:c)
            self.assertEqual(result['status'],'PARTIAL')
            self.assertEqual(result['trials'][0]['retained_records'],3)
            self.assertIsNone(result['trials'][0]['population'])
            self.assertEqual(result['trials'][1]['status'],'EXTRACTED')

    def test_empty_generator_is_distinct_from_failure(self):
        c=self.context()
        c['generate']=lambda t:{k:[] for k in self.fixture.raw}
        with tempfile.TemporaryDirectory() as directory:
            result=E.extract(directory,lambda:c)
            self.assertEqual(result['trials'][0]['population']['generated'],0)
            self.assertEqual(result['trials'][0]['shards'],[])

    def test_preflight_failure_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            def bad(): raise ValueError('wrong archive')
            with self.assertRaises(ValueError): E.extract(directory,bad)
            failure=Path(directory)/'failure.json'
            before=failure.read_bytes()
            self.assertFalse((Path(directory)/'manifest.json').exists())
            with self.assertRaises(ValueError): E.extract(directory,lambda:self.context())
            self.assertEqual(failure.read_bytes(),before)

    def test_writer_failure_is_fatal_without_completion(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(E.Shards,'emit',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): E.extract(directory,lambda:self.context())
            self.assertFalse((Path(directory)/'manifest.json').exists())
            self.assertEqual(json.loads((Path(directory)/'failure.json').read_bytes())['type'],'OSError')

    def test_byte_limits_deterministic_and_oversize_rejected(self):
        results=[]
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                sink=E.Shards(directory,'a'*64,max_bytes=20)
                sink.emit({'n':1}); sink.emit({'n':2}); sink.emit({'n':3}); sink.close()
                self.assertEqual([s['records'] for s in sink.files],[2,1])
                results.append([s['sha256'] for s in sink.files])
                with self.assertRaises(ValueError): sink.emit({'large':'x'*100})
        self.assertEqual(*results)

    def test_invalid_roster_rejected_before_generation(self):
        for kind in ('duplicate','unsafe','resolution'):
            c=self.context()
            if kind=='duplicate': c['trials'][1]['trial_id']=c['trials'][0]['trial_id']
            if kind=='unsafe': c['trials'][0]['trial_id']='../escape'
            if kind=='resolution': c['trials'][0]['archive_requirement']='unknown'
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError): E.extract(directory,lambda:c)
                self.assertFalse((Path(directory)/'manifest.json').exists())
        self.assertEqual(self.calls,[])

    def test_changed_original_code_rejected_before_archive_access(self):
        with patch.object(E.subprocess,'check_output',return_value=b'changed original'):
            with self.assertRaisesRegex(ValueError,'source hash mismatch'):
                E.prepare('nonexistent','nonexistent')
