import tempfile
import hashlib
import json
from email.message import Message
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch
from tools.v9 import control_outcome_runner as R


class Runner(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='blazebrt/perp-dex-radar',GITHUB_REF='refs/heads/v9/census-evidence',
            GITHUB_RUN_ATTEMPT='1',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Linux',RUNNER_ARCH='X64',ImageOS='ubuntu24',
            GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_SHA='a'*40,GITHUB_RUN_ID='123',GITHUB_TOKEN='synthetic-token',RUNNER_TEMP=str(self.root),ImageVersion='synthetic-image')
        self.qualification=self.root/'qualification.json'
        self.report=dict(schema='v9.a6-resource-qualification/1',source_commit='a'*40,runner_profile=R.PROFILE,
                         python_version=R.sys.version.split()[0],runner_image_version='synthetic-image',
                         installed_distributions={'synthetic-package':'1.0'})
        self.qualification.write_bytes(json.dumps(self.report).encode())
        self.digest=hashlib.sha256(self.qualification.read_bytes()).hexdigest()
        platform=patch.object(R.sys,'platform','linux');platform.start();self.addCleanup(platform.stop)
        inventory=patch.object(R,'installed_distributions',return_value={'synthetic-package':'1.0'})
        inventory.start();self.addCleanup(inventory.stop)
        identity=patch.object(R.RI,'collect',return_value={'status':'CONSISTENT_CLAIMS_NOT_ATTESTED'})
        identity.start();self.addCleanup(identity.stop)

    def test_environment_source_trigger_and_rerun_refused(self):
        R.validate(self.env,1100,1000)
        for key,value in [('GITHUB_REPOSITORY','other/repo'),('GITHUB_REF','refs/heads/main'),('GITHUB_RUN_ATTEMPT','2'),
                          ('RUNNER_ENVIRONMENT','self-hosted'),('GITHUB_EVENT_NAME','pull_request'),('GITHUB_SHA','short'),
                          ('ImageOS','ubuntu22'),('GITHUB_TOKEN','')]:
            env=dict(self.env);env[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):R.validate(env,1100,1000)
        with patch.object(R.sys,'platform','win32'),self.assertRaises(ValueError):R.validate(self.env,1100,1000)

    def test_deadline_expired_excessive_or_boolean_refused(self):
        for deadline in (1000,999,22601,True):
            with self.subTest(deadline=deadline),self.assertRaises(ValueError):R.validate(self.env,deadline,1000)

    def test_wiring_refreshes_remaining_time_and_uses_pinned_adapter(self):
        with patch.object(R.time,'time',return_value=1000) as clock,patch.object(R,'GitHubReservationAPI') as api,patch.object(R.J,'run') as job,patch.object(R.G,'live_capacity',return_value={}) as capacity:
            R.run(self.env,self.qualification,self.digest,1100)
            args=job.call_args.args
            self.assertEqual(args[0],R.ROOT);self.assertEqual(args[5:8],('a'*40,'123','1'))
            self.assertIs(args[-1].func,R.I.prepare);self.assertEqual(args[-1].args,(R.ROOT,))
            args[11]();self.assertEqual(capacity.call_args.args[-1],100)
            clock.return_value=1040;args[11]();self.assertEqual(capacity.call_args.args[-1],60)
            clock.return_value=1100
            with self.assertRaisesRegex(ValueError,'exhausted'):args[11]()
            api.assert_called_once_with('synthetic-token')

    def test_workspace_reuse_and_missing_qualification_refused(self):
        with patch.object(R.time,'time',return_value=1000),patch.object(R,'GitHubReservationAPI'),patch.object(R.J,'run') as job:
            with self.assertRaises(ValueError):R.run(self.env,self.root/'missing','b'*64,1100)
            R.run(self.env,self.qualification,self.digest,1100)
            with self.assertRaises(FileExistsError):R.run(self.env,self.qualification,self.digest,1100)
            self.assertEqual(job.call_count,1)

    def test_runtime_mismatch_refuses_before_api_or_workspace(self):
        for key in self.report:
            if key=='installed_distributions':continue
            report=dict(self.report);report[key]='wrong'
            raw=json.dumps(report).encode();self.qualification.write_bytes(raw)
            with self.subTest(key=key),patch.object(R.time,'time',return_value=1000),patch.object(R,'GitHubReservationAPI') as api,patch.object(R.J,'run') as job:
                with self.assertRaisesRegex(ValueError,'runtime mismatch'):
                    R.run(self.env,self.qualification,hashlib.sha256(raw).hexdigest(),1100)
                api.assert_not_called();job.assert_not_called()
                self.assertFalse((self.root/'a6-outcome-123-1').exists())

    def test_dependency_drift_refuses_before_api_and_workspace(self):
        for inventory in ({},{'synthetic-package':'2.0'},{'synthetic-package':'1.0','extra':'1'}):
            with self.subTest(inventory=inventory),patch.object(R.time,'time',return_value=1000),patch.object(R,'installed_distributions',return_value=inventory),patch.object(R,'GitHubReservationAPI') as api,patch.object(R.J,'run') as job:
                with self.assertRaisesRegex(ValueError,'inventory mismatch'):
                    R.run(self.env,self.qualification,self.digest,1100)
                api.assert_not_called();job.assert_not_called()
                self.assertFalse((self.root/'a6-outcome-123-1').exists())

    def test_missing_or_noncanonical_reviewed_inventory_refused(self):
        for inventory in (None,{},[],{'Some_Package':'1'},{'package':True},{'package':' 1'}):
            report=dict(self.report);report['installed_distributions']=inventory
            raw=json.dumps(report).encode()
            with self.assertRaises(ValueError):R.verify_runtime(raw,hashlib.sha256(raw).hexdigest(),self.env)

    def test_missing_image_claim_and_changed_reviewed_bytes_refuse(self):
        raw=self.qualification.read_bytes()
        for image in (None,'','different'):
            env=dict(self.env);env['ImageVersion']=image
            with self.assertRaises(ValueError):R.verify_runtime(raw,self.digest,env)
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            R.verify_runtime(raw+b' ',self.digest,self.env)

    def test_identity_conflict_or_unavailable_refuses_before_api(self):
        for status in ('CONFLICTING_IDENTITY_CLAIMS','UNAVAILABLE',None):
            with self.subTest(status=status),patch.object(R.time,'time',return_value=1000),patch.object(R.RI,'collect',return_value={'status':status}),patch.object(R,'GitHubReservationAPI') as api,patch.object(R.J,'run') as job:
                with self.assertRaisesRegex(ValueError,'identity is unavailable or conflicting'):
                    R.run(self.env,self.qualification,self.digest,1100)
                api.assert_not_called();job.assert_not_called()
                self.assertFalse((self.root/'a6-outcome-123-1').exists())

    def test_duplicate_nonfinite_and_nonobject_runtime_report_refuse(self):
        for raw in (b'{"python_version":"a","python_version":"b"}',b'{"extra":NaN}',b'[]'):
            with self.assertRaises(ValueError):
                R.verify_runtime(raw,hashlib.sha256(raw).hexdigest(),self.env)

    def test_success_requires_verified_retention_and_no_authority(self):
        good=dict(status='RETAINED_DIAGNOSTICS',reservation_verified=True,publication_verified=True,promotion_authority=False)
        self.assertEqual(R.exit_code(good),0)
        for key,value in [('status','FAILED_OR_PARTIAL_RETAINED'),('reservation_verified',False),('publication_verified',False),('promotion_authority',True)]:
            report=dict(good);report[key]=value;self.assertEqual(R.exit_code(report),1)

    def test_cli_failure_does_not_print_exception_secret(self):
        with patch.object(R,'run',side_effect=RuntimeError('synthetic-secret')),patch('builtins.print') as output:
            self.assertEqual(R.main(['--qualification','report','--qualification-sha256','b'*64,'--deadline-epoch','1100']),1)
            self.assertNotIn('synthetic-secret',str(output.call_args))


class DistributionInventory(unittest.TestCase):
    def distribution(self,name,version):
        message=Message()
        if name is not None:message['Name']=name
        if version is not None:message['Version']=version
        return SimpleNamespace(metadata=message)

    def test_normalized_inventory(self):
        rows=[self.distribution('Some__Package','1.0'),self.distribution('Another.pkg','2.1')]
        with patch.object(R.metadata,'distributions',return_value=rows):
            self.assertEqual(R.installed_distributions(),{'another-pkg':'2.1','some-package':'1.0'})

    def test_ambiguous_missing_duplicate_and_empty_metadata_refused(self):
        duplicate=self.distribution('package','1');duplicate.metadata['Name']='another'
        cases=[[],[duplicate],[self.distribution(None,'1')],[self.distribution('pkg',None)],
               [self.distribution('some_pkg','1'),self.distribution('some-pkg','1')],
               [self.distribution('bad/name','1')],[self.distribution('pkg',' 1')]]
        for rows in cases:
            with self.subTest(rows=rows),patch.object(R.metadata,'distributions',return_value=rows),self.assertRaises(ValueError):
                R.installed_distributions()
