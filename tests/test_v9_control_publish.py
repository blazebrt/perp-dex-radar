import json
from pathlib import Path
import tempfile
import unittest
from tools.v9 import control_publish as P


class Publication(unittest.TestCase):
    def test_success_requires_exact_audited_counts(self):
        for count in (192,191):
            calls=[]
            def execute(args,log):
                calls.append(args[0]);log.write_bytes(b'log')
                out=Path(args[args.index('--out')+1]);out.mkdir()
                if 'control_extract.py' in args[0]:
                    P.write(out/'manifest.json',dict(status='COMPLETED_WITH_UNAVAILABLE_HOURLY_POPULATIONS'))
                else:P.write(out/'audit.json',dict(status='VERIFIED_AVAILABLE_TRIALS',verified_trials=count,
                    unavailable_or_failed_trials=7,promotion_authority=False))
                return 0
            with tempfile.TemporaryDirectory() as directory:
                result=P.retain('md','evidence',Path(directory)/'out','a'*40,execute)
                self.assertEqual(len(calls),2)
                self.assertEqual(result['status'],'EXTRACTED_AND_AUDITED_WITH_SEVEN_UNAVAILABLE' if count==192 else 'FAILED_OR_PARTIAL')
                for name,sha in result['artifacts_sha256'].items():self.assertEqual(P.sha(Path(directory)/'out'/name),sha)

    def test_fatal_or_partial_outputs_retained_without_repetition(self):
        for partial in (False,True):
            calls=[]
            def execute(args,log):
                calls.append(args[0]);log.write_bytes(b'failure log')
                out=Path(args[args.index('--out')+1]);out.mkdir()
                (out/'partial.gz').write_bytes(b'partial')
                if partial and len(calls)==1:P.write(out/'manifest.json',dict(status='PARTIAL'))
                return 1
            with tempfile.TemporaryDirectory() as directory:
                out=Path(directory)/'out'
                result=P.retain('md','evidence',out,'a'*40,execute)
                self.assertEqual(len(calls),2 if partial else 1)
                self.assertEqual(result['status'],'FAILED_OR_PARTIAL')
                self.assertIn('extraction/partial.gz',result['artifacts_sha256'])
                previous=(out/'attempt.json').read_bytes()
                with self.assertRaises(FileExistsError):P.retain('md','evidence',out,'a'*40,execute)
                self.assertEqual((out/'attempt.json').read_bytes(),previous)

    def test_exception_keeps_started_stage_and_failure_description(self):
        def execute(args,log):log.write_bytes(b'partial');raise OSError('runner error')
        with tempfile.TemporaryDirectory() as directory:
            result=P.retain('md','evidence',Path(directory)/'out','a'*40,execute)
            self.assertEqual(result['error']['type'],'OSError')
            self.assertEqual(result['status'],'FAILED_OR_PARTIAL')
            self.assertIn('extraction.log',result['artifacts_sha256'])

    def test_invalid_source_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'out'
            with self.assertRaises(ValueError):P.retain('md','evidence',out,'main')
            self.assertFalse(out.exists())
