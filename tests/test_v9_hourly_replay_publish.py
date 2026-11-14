import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from tools.v9 import hourly_replay_publish as P
from tools.v9 import record_run as RR


def fake_run(archive,out):
    out=Path(out);out.mkdir()
    shard=out/'LIQ_FLUSH.jsonl.gz';shard.write_bytes(gzip.compress(b'{"kind":"attempt","status":"UNRESOLVED_FUNDING"}\n'))
    trial=dict(status='REPLAYED',failed_segments=0,attempt_counts={'UNRESOLVED_FUNDING':1},net_series_available=False)
    evidence=dict(trials={'LIQ_FLUSH':trial})
    P.R.write_json(out/'evidence_a5.json',evidence)
    return evidence


class Publication(unittest.TestCase):
    def test_success_retains_artifacts_and_never_claims_net_qualification(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            with mock.patch.object(P.R,'run',side_effect=fake_run):result=P.retain(Path(tmp)/'archive',out)
            self.assertEqual(result['status'],'COMPLETED_WITH_UNAVAILABLE_RESULTS')
            self.assertEqual(result['confirmed'],[])
            self.assertFalse(result['promotion_authority'])
            for name,digest in result['artifacts_sha256'].items():self.assertEqual(P.R.sha(out/name),digest)
            self.assertIn('unavailable',(out/'REPORT_A5.md').read_text())
            with self.assertRaises(FileExistsError):P.retain('unused',out)

    def test_fatal_failure_keeps_partial_stream_and_no_driver_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            def fail(archive,out):
                Path(out).mkdir();(Path(out)/'partial.jsonl.gz').write_bytes(b'partial')
                raise RuntimeError('interrupted writer')
            with mock.patch.object(P.R,'run',side_effect=fail):result=P.retain('missing',out)
            self.assertEqual(result['status'],'FAILED')
            self.assertFalse(result['driver_manifest_retained'])
            self.assertTrue((out/'failure.json').exists())
            self.assertFalse((out/'evidence_a5.json').exists())
            self.assertIn('partial.jsonl.gz',result['artifacts_sha256'])

    def test_partial_segment_failure_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            def partial(archive,out):
                result=fake_run(archive,out);result['trials']['LIQ_FLUSH']['failed_segments']=1
                return result
            with mock.patch.object(P.R,'run',side_effect=partial):result=P.retain('missing',Path(tmp)/'out')
            self.assertEqual(result['status'],'PARTIAL_FAILURE')

    def test_completed_attempt_requires_driver_binding_and_valid_shards(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            with mock.patch.object(P.R,'run',side_effect=fake_run):result=P.retain('missing',out)
            result['actual_manifest_sha256']=P.R.MANIFEST_SHA
            files={p.name:p.read_bytes() for p in out.iterdir()}
            files['replay_run.json']=json.dumps(result).encode()
            files['run_meta.txt']=b'v9/census-evidence '+b'a'*40+b' 2026-10-20T00:00:00Z'
            files['dataset_ref.txt']=b''
            def git(repo,*args):
                return b'b'*40 if args[0]=='rev-parse' else files[args[1].split(':',1)[1]]
            with mock.patch.object(RR,'_git',side_effect=git):
                self.assertEqual(RR.build('A5',repo='unused',ref='results')['status'],result['status'])
                original=files['LIQ_FLUSH.jsonl.gz'];files['LIQ_FLUSH.jsonl.gz']=b'corrupt'
                with self.assertRaisesRegex(ValueError,'hash mismatch'):RR.build('A5',repo='unused',ref='results')
                files['LIQ_FLUSH.jsonl.gz']=original
                result['driver_manifest_retained']=False;files['replay_run.json']=json.dumps(result).encode()
                with self.assertRaisesRegex(ValueError,'driver evidence'):RR.build('A5',repo='unused',ref='results')

    def test_failed_attempt_records_hashes_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            with mock.patch.object(P.R,'run',side_effect=RuntimeError('preflight')):P.retain('missing',out)
            files={p.name:p.read_bytes() for p in out.iterdir()}
            files['run_meta.txt']=b'v9/census-evidence '+b'a'*40+b' 2026-10-20T00:00:00Z\n'
            files['dataset_ref.txt']=('hourly-a5-quality-results '+P.R.DATA_COMMIT+'\n').encode()
            def git(repo,*args):
                return b'b'*40 if args[0]=='rev-parse' else files[args[1].split(':',1)[1]]
            with mock.patch.object(RR,'_git',side_effect=git):
                record=RR.build('A5',repo='unused',ref='results')
                self.assertEqual(record['dataset_sha256'],P.R.MANIFEST_SHA)
                self.assertEqual(record['status'],'FAILED')
                self.assertEqual(record['confirmed'],[])
                history=Path(tmp)/'history.jsonl';RR.append(record,str(history))
                self.assertEqual(RR.verify(RR.read(str(history))),[])
                files['failure.json']=b'changed'
                with self.assertRaisesRegex(ValueError,'hash mismatch'):RR.build('A5',repo='unused',ref='results')


if __name__=='__main__':unittest.main()
