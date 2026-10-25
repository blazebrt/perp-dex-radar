import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.v9 import control_outcome_publish as P
from tests.test_v9_control_resource_gate import report,capacity


class Publish(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.signals=self.root/'signals';self.signals.mkdir();(self.signals/'manifest.json').write_text('{}')
        self.digest=P.sha(self.signals/'manifest.json');self.out=self.root/'out';self.reservation=self.root/'reservation.json'
        self.source='a'*40
        self.qualification=self.root/'qualification.json'
        self.qualification.write_text(json.dumps(report(self.source,self.digest,P.sha(P.ROOT/P.PROTOCOL))))
        self.capacity=capacity()
        self.record=dict(status='RESERVED',source_commit=self.source,run_attempt='1',run_id='123',input_commit=P.INPUT_COMMIT,
            input_manifest_sha256=self.digest,execution_protocol_sha256=P.sha(P.ROOT/P.PROTOCOL),
            publication_protocol_sha256=P.sha(P.ROOT/P.PUBLICATION),results_branch='evidence-a6-outcome-results',resource_gate_sha256=P.sha(Path(P.G.__file__)),
            resource_qualification_sha256=P.sha(self.qualification),promotion_authority=False)
        self.reservation.write_text(json.dumps(self.record));self.calls=[]

    def execute(self,args,log):
        self.calls.append(args);log.write_text('synthetic stage log')
        out=Path(args[args.index('--out')+1]);out.mkdir()
        if Path(args[0]).name=='control_outcomes.py':
            doc=dict(status='COMPLETED_PRICE_DIAGNOSTICS_NET_UNAVAILABLE',processed_signals=4263580,
                     completed_trials=[dict(status='PROCESSED')]*192+[dict(status='UNAVAILABLE_HOURLY_POPULATION')]*7)
            (out/'manifest.json').write_text(json.dumps(doc))
        else:
            doc=dict(status='VERIFIED_REGISTERED_PRICE_DIAGNOSTICS',signals=4263580,candidate_paths=4263580,
                accounting=dict(signals=4263580,sides=398),statistics=dict(signals=4263580,descriptive_statistics_verified=True,
                day_aggregates_verified=True,control_reuse_verified=True),input_manifest_sha256=self.digest,
                outcome_manifest_sha256=P.sha(self.out/'outcomes/manifest.json'),source_bound_selection_verified=True,
                source_bound_price_paths_verified=True,net_inference_available=False,full_matched_authority=False,promotion_authority=False)
            (out/'audit.json').write_text(json.dumps(doc))
        return 0

    def retain(self,execute=None):
        with patch.object(P,'INPUT_HASH',self.digest):
            return P.retain(self.root/'archive',self.root/'evidence.json',self.signals,self.out,self.source,self.reservation,execute or self.execute,qualification=self.qualification,capacity=self.capacity)

    def test_success_retains_both_stages_and_hashes(self):
        result=self.retain();self.assertEqual(result['status'],'PRICE_DIAGNOSTICS_INDEPENDENTLY_AUDITED_NET_UNAVAILABLE')
        self.assertEqual(len(self.calls),2)
        for name,digest in result['artifacts_sha256'].items():self.assertEqual(P.sha(self.out/name),digest)
        self.assertFalse(result['net_inference_available'])

    def test_incomplete_audit_never_claims_success(self):
        def execute(args,log):
            code=self.execute(args,log)
            if args[0].endswith('audit_control_outcomes.py'):
                p=self.out/'audit/audit.json';d=json.loads(p.read_bytes());d['signals']-=1;p.write_text(json.dumps(d))
            return code
        self.assertEqual(self.retain(execute)['status'],'FAILED_OR_PARTIAL')

    def test_failure_retains_partial_files(self):
        def fail(args,log):
            log.write_text('failed');(self.out/'partial.txt').write_text('retained');raise RuntimeError('synthetic failure')
        result=self.retain(fail)
        self.assertEqual(result['status'],'FAILED_OR_PARTIAL');self.assertIn('partial.txt',result['artifacts_sha256'])

    def test_interruption_leaves_started_and_blocks_retry(self):
        def interrupt(args,log):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.retain(interrupt)
        self.assertEqual(json.loads((self.out/'attempt.json').read_bytes())['status'],'STARTED')
        with self.assertRaises(FileExistsError):self.retain()

    def test_invalid_reservation_and_overlapping_inputs_rejected(self):
        self.record['run_attempt']='2';self.reservation.write_text(json.dumps(self.record))
        with self.assertRaises(ValueError):self.retain()
        self.assertFalse(self.out.exists())
        self.out=self.signals/'nested'
        with self.assertRaises(ValueError):self.retain()

    def test_wrong_input_fails_before_execution(self):
        (self.signals/'manifest.json').write_text('changed')
        result=self.retain();self.assertEqual(result['status'],'FAILED_OR_PARTIAL');self.assertEqual(self.calls,[])

    def test_resource_refusal_retained_before_any_outcome_execution(self):
        self.capacity['free_disk_bytes']=1
        result=self.retain()
        self.assertEqual(result['status'],'FAILED_OR_PARTIAL');self.assertEqual(self.calls,[])
        self.assertIn('disk budget',result['error']['message'])
        self.assertIn('resource-qualification.json',result['artifacts_sha256'])

    def test_missing_resource_evidence_never_executes(self):
        self.qualification=None
        result=self.retain()
        self.assertEqual(result['status'],'FAILED_OR_PARTIAL');self.assertEqual(self.calls,[])
