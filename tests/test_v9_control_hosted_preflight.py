import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from tools.v9 import control_hosted_preflight as P


class Preflight(unittest.TestCase):
    def check(self,identity,capacity):
        with tempfile.TemporaryDirectory() as directory:
            env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='blazebrt/perp-dex-radar',
                     GITHUB_REF='refs/heads/v9/census-evidence',RUNNER_ENVIRONMENT='github-hosted',
                     RUNNER_OS='Linux',RUNNER_ARCH='X64',ImageOS='ubuntu24',GITHUB_SHA='a'*40,RUNNER_TEMP=directory)
            with patch.object(P.Identity,'collect',return_value={'status':identity}),patch.object(P.Gate,'memory_capacity',**capacity),patch.object(P.shutil,'disk_usage',return_value=SimpleNamespace(free=1000)):
                return P.inspect(env)

    def test_consistent_claims_do_not_qualify_or_authorize(self):
        report=self.check('CONSISTENT_CLAIMS_NOT_ATTESTED',{'return_value':{'available_memory_bytes':1000}})
        self.assertEqual(report['status'],'PREREQUISITES_OBSERVED_NOT_QUALIFIED')
        self.assertFalse(report['resource_qualified']);self.assertFalse(report['promotion_authority'])
        self.assertEqual(report['required_workload']['signals'],4263580)

    def test_conflict_or_missing_identity_blocks(self):
        for status in ('CONFLICTING_IDENTITY_CLAIMS','UNAVAILABLE'):
            report=self.check(status,{'return_value':{'available_memory_bytes':1000}})
            self.assertEqual(report['blockers'],['RUNNER_IDENTITY_UNAVAILABLE_OR_CONFLICTING'])
            self.assertEqual(report['status'],'BLOCKED_PREREQUISITES')

    def test_capacity_failure_retains_identity_without_error_secrets(self):
        report=self.check('CONSISTENT_CLAIMS_NOT_ATTESTED',{'side_effect':ValueError('private details')})
        self.assertEqual(report['blockers'],['LIVE_CAPACITY_UNAVAILABLE'])
        self.assertEqual(report['capacity_error_type'],'ValueError')
        self.assertNotIn('private',str(report))

    def test_wrong_environment_refused_before_inspection(self):
        with patch.object(P.Identity,'collect') as collect:
            with self.assertRaises(ValueError):P.inspect({})
        collect.assert_not_called()
