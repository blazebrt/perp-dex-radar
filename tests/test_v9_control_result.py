import copy
import json
from pathlib import Path
import unittest
from tools.v9 import verify_control_result as V

ROOT=Path(__file__).resolve().parents[1]


class Package(unittest.TestCase):
    def setUp(self):
        self.files={}
        self.source='a'*40
        self.protocol=V.sha(self.read_source('docs/v9/phase-a6-publication.md'))
        self.put('reservation.json',dict(source_commit=self.source,run_id='123',run_attempt='1',status='RESERVED',
                                         promotion_authority=False,preregistration_sha256=self.protocol))
        self.attempt=dict(source_commit=self.source,preregistration_sha256=self.protocol,
            publisher_sha256=V.sha(self.read_source('tools/v9/control_publish.py')),promotion_authority=False,
            outcomes_computed=False,complete_family_population_verified=False,status='FAILED_OR_PARTIAL',
            extraction_exit=1,audit_exit=None,error=None)

    def read_source(self,name):return (ROOT/name).read_bytes()
    def put(self,name,value):self.files[name]=(json.dumps(value,sort_keys=True)+'\n').encode()
    def seal(self):
        self.attempt['artifacts_sha256']={n:V.sha(raw) for n,raw in self.files.items() if n not in ('attempt.json','reservation.json')}
        self.put('attempt.json',self.attempt)
    def inspect(self):return V.inspect(self.files.__getitem__,lambda n:V.sha(self.files[n]),list(self.files),self.read_source,self.source,'123')

    def success(self):
        plan=json.loads(self.read_source('research/v9/census_replay_plan.json'))
        binding=json.loads(self.read_source('research/v9/probation_evidence.json'))
        provenance=dict(archive_commit='4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7',source_commit='ad2374fa4d25f03c204ce7c0cdbecac95cba6246',
            verified_candle_files=781,panel_sha256=binding['inputs']['dataset_sha256'],phase_b_evidence_sha256=binding['inputs']['evidence_sha256'],
            plan_sha256=V.sha(self.read_source('research/v9/census_replay_plan.json')),
            inventory_sha256=V.sha(self.read_source('research/v9/a6_source_inventory.json')),
            protocol_sha256=V.sha(self.read_source('docs/v9/phase-a6-extraction-driver.md')),
            code_sha256=binding['code']['research'],adapter_sha256={n:V.sha(self.read_source('tools/v9/'+n)) for n in
                ('control_extract.py','control_signals.py','control_sources.py','control_features.py')})
        trials=[];reports=[]
        for definition in plan['trials']:
            tid=definition['trial_id'];hourly=definition['archive_requirement']=='hourly'
            population=dict(generated=0,before_window=0,after_window=0,retained=0,full_matched_authority=False,promotion_authority=False)
            trial=dict(trial_id=tid,definition=definition,status='UNAVAILABLE_HOURLY_POPULATION' if hourly else 'EXTRACTED',
                       population=None if hourly else population,retained_records=0,shards=[])
            report=dict(trial_id=tid,status='NOT_VERIFIED_UNAVAILABLE_HOURLY_POPULATION' if hourly else 'VERIFIED')
            if not hourly:report.update(population,generator_array_projection_verified=True,source_feature_values_verified=True,
                                      externally_bound_inputs_verified=True,original_generator_mathematics_verified=False)
            trials.append(trial);reports.append(report);self.put('extraction/'+tid+'.json',trial)
        self.put('extraction/manifest.json',dict(trials=trials,provenance=provenance,status='COMPLETED_WITH_UNAVAILABLE_HOURLY_POPULATIONS',
            window=[1588204800,1790812800],promotion_authority=False,full_matched_authority=False,outcomes_computed=False))
        self.put('audit/audit.json',dict(trials=reports,extraction_source_commit=self.source,status='VERIFIED_AVAILABLE_TRIALS',
            verified_trials=192,unavailable_or_failed_trials=7,promotion_authority=False,full_matched_authority=False,
            complete_family_population_verified=False,original_generator_mathematics_verified=False,
            verifier_sha256={n:V.sha(self.read_source('tools/v9/'+n)) for n in
                ('audit_control_extraction.py','verify_control_artifacts.py','verify_control_population.py')},
            artifact_verification=dict(manifest_sha256=V.sha(self.files['extraction/manifest.json']),artifact_accounting_verified=True,
                                       retained_records=0,extracted=192,hourly_unavailable=7,failed=0)))
        self.attempt.update(status='EXTRACTED_AND_AUDITED_WITH_SEVEN_UNAVAILABLE',extraction_exit=0,audit_exit=0)
        self.seal()

    def test_success_reconciles_all_identities_and_scope(self):
        self.success();result=self.inspect()
        self.assertEqual(result['verified_available_trials'],192)
        self.assertEqual(result['hourly_unavailable'],7)
        self.assertFalse(result['market_archive_reloaded_locally'])

    def test_failed_and_interrupted_are_never_success(self):
        self.assertFalse(self.inspect()['package_complete'])
        self.attempt['status']='STARTED';self.seal()
        self.assertEqual(self.inspect()['status'],'INCOMPLETE_STARTED')
        self.attempt['status']='FAILED_OR_PARTIAL';self.put('extraction/failure.json',{'error':'bad input'});self.seal()
        result=self.inspect();self.assertTrue(result['all_retained_artifact_hashes_verified'])
        self.assertIn('extraction/failure.json',result['available_failure_records'])

    def test_tampered_bytes_or_extra_files_rejected(self):
        self.put('extraction.log',{'log':'failure'});self.seal();self.files['extraction.log']+=b'changed'
        with self.assertRaises(ValueError):self.inspect()
        self.seal();self.files['extra']=b'extra'
        with self.assertRaises(ValueError):self.inspect()

    def test_rehashed_audit_or_source_tampering_rejected(self):
        for kind in ('count','identity','source','manifest','code'):
            self.setUp();self.success()
            name='audit/audit.json' if kind!='code' else 'extraction/manifest.json'
            doc=json.loads(self.files[name])
            if kind=='count':doc['verified_trials']=191
            if kind=='identity':doc['trials'].reverse()
            if kind=='source':doc['extraction_source_commit']='b'*40
            if kind=='manifest':doc['artifact_verification']['manifest_sha256']='0'*64
            if kind=='code':doc['provenance']['code_sha256']={}
            self.put(name,doc);self.seal()
            with self.assertRaises(ValueError):self.inspect()
