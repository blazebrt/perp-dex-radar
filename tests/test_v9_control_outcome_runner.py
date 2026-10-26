import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from tools.v9 import control_outcome_runner as R


class Runner(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='blazebrt/perp-dex-radar',GITHUB_REF='refs/heads/v9/census-evidence',
            GITHUB_RUN_ATTEMPT='1',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Linux',RUNNER_ARCH='X64',ImageOS='ubuntu24',
            GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_SHA='a'*40,GITHUB_RUN_ID='123',GITHUB_TOKEN='synthetic-token',RUNNER_TEMP=str(self.root))
        self.qualification=self.root/'qualification.json';self.qualification.write_bytes(b'synthetic report')
        platform=patch.object(R.sys,'platform','linux');platform.start();self.addCleanup(platform.stop)

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
            R.run(self.env,self.qualification,'b'*64,1100)
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
            R.run(self.env,self.qualification,'b'*64,1100)
            with self.assertRaises(FileExistsError):R.run(self.env,self.qualification,'b'*64,1100)
            self.assertEqual(job.call_count,1)

    def test_success_requires_verified_retention_and_no_authority(self):
        good=dict(status='RETAINED_DIAGNOSTICS',reservation_verified=True,publication_verified=True,promotion_authority=False)
        self.assertEqual(R.exit_code(good),0)
        for key,value in [('status','FAILED_OR_PARTIAL_RETAINED'),('reservation_verified',False),('publication_verified',False),('promotion_authority',True)]:
            report=dict(good);report[key]=value;self.assertEqual(R.exit_code(report),1)

    def test_cli_failure_does_not_print_exception_secret(self):
        with patch.object(R,'run',side_effect=RuntimeError('synthetic-secret')),patch('builtins.print') as output:
            self.assertEqual(R.main(['--qualification','report','--qualification-sha256','b'*64,'--deadline-epoch','1100']),1)
            self.assertNotIn('synthetic-secret',str(output.call_args))
