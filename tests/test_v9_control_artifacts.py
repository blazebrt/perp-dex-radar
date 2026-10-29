import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from tools.v9 import control_extract as E, verify_control_artifacts as V
from tests import test_v9_control_extract as fixtures


class Artifacts(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.Extraction()
        self.fixture.setUp()
        self.context=self.fixture.context()
        self.plan={'trials':copy.deepcopy(self.context['trials'])}

    def verify(self, directory):
        return V.verify(directory,self.plan,{'synthetic':True})

    def save(self, directory, result):
        for trial in result['trials']:
            E.write_json(Path(directory)/(trial['trial_id']+'.json'),trial)
        E.write_json(Path(directory)/'manifest.json',result)

    def test_valid_complete_and_partial_are_not_population_proofs(self):
        for failed in (False,True):
            if failed: self.fixture.fixture.raw['hold'][-1]=0
            with tempfile.TemporaryDirectory() as directory:
                E.extract(directory,lambda:self.context,max_rows=2)
                result=self.verify(directory)
                self.assertEqual(result['failed'],2 if failed else 0)
                self.assertEqual(result['hourly_unavailable'],1)
                self.assertEqual(result['retained_records'],6 if failed else 8)
                self.assertFalse(result['generator_population_verified'])
                self.assertFalse(result['source_feature_values_verified'])

    def test_roster_provenance_and_authority_tampering(self):
        changes=[lambda r:r['trials'].reverse(),
                 lambda r:r['provenance'].update(synthetic=False),
                 lambda r:r.update(promotion_authority=True),
                 lambda r:r.update(status='PARTIAL'),
                 lambda r:r['trials'][0]['population'].update(generated=999),
                 lambda r:r['trials'][-1].update(population={})]
        for change in changes:
            with tempfile.TemporaryDirectory() as directory:
                result=E.extract(directory,lambda:self.context)
                change(result);self.save(directory,result)
                with self.assertRaises(ValueError):self.verify(directory)

    def test_unlisted_missing_and_corrupt_artifacts(self):
        for kind in ('extra','missing','corrupt','trial'):
            with tempfile.TemporaryDirectory() as directory:
                result=E.extract(directory,lambda:self.context)
                shard=Path(directory)/result['trials'][0]['shards'][0]['path']
                if kind=='extra':(Path(directory)/'partial.tmp').write_bytes(b'partial')
                if kind=='missing':shard.unlink()
                if kind=='corrupt':shard.write_bytes(b'corrupt')
                if kind=='trial':E.write_json(Path(directory)/(result['trials'][0]['trial_id']+'.json'),{})
                with self.assertRaises((ValueError,FileNotFoundError)):self.verify(directory)

    def test_rehashed_signal_tampering_rejected(self):
        changes=[lambda rows:rows.__setitem__(1,rows[0]),
                 lambda rows:rows[0].update(signal_id='0'*64),
                 lambda rows:rows[0]['features'].update(asset='OTHER'),
                 lambda rows:rows[0]['history'].update(signal_quality_qualified=True)]
        for change in changes:
            with tempfile.TemporaryDirectory() as directory:
                result=E.extract(directory,lambda:self.context)
                shard=result['trials'][0]['shards'][0]
                path=Path(directory)/shard['path']
                rows=[json.loads(r) for r in gzip.decompress(path.read_bytes()).splitlines()]
                change(rows)
                decoded=b''.join((json.dumps(r)+'\n').encode() for r in rows)
                raw=gzip.compress(decoded,mtime=0);path.write_bytes(raw)
                shard.update(sha256=V.digest(raw),bytes=len(raw),uncompressed_bytes=len(decoded))
                self.save(directory,result)
                with self.assertRaises(ValueError):self.verify(directory)

    def test_ambiguous_json_and_invalid_limits(self):
        for raw in (b'{"n":1,"n":2}',b'{"n":NaN}',b'{"n":Infinity}'):
            with self.assertRaises(ValueError):V.load(raw)
        with tempfile.TemporaryDirectory() as directory:
            result=E.extract(directory,lambda:self.context)
            result['trials'][0]['shards'][0]['records']=25001
            self.save(directory,result)
            with self.assertRaises(ValueError):self.verify(directory)
