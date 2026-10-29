import subprocess
import unittest
from unittest.mock import patch
from tools.v9 import control_retention_remote as R
from tests import test_v9_control_retention_commit as fixture


class RemoteRetention(unittest.TestCase):
    def setUp(self):
        self.f=fixture.RetentionCommit();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.g=self.f.f;self.remote=self.g.repo/'remote.git'
        self.g.git('init','--bare','--template=',str(self.remote))
        self.g.git('remote','add','retention',str(self.remote))
        # Copy unreachable synthetic objects into the local bare fixture only.
        self.g.git('update-ref','refs/heads/synthetic-reservation',self.g.root)
        self.remote_git('fetch',str(self.g.repo),'refs/heads/synthetic-reservation')
        self.remote_git('update-ref',R.BRANCH,self.g.root)
        (self.f.attempt/'partial.log').write_bytes(b'failure bytes\x00')
        self.result=self.f.prepare()['commit']

    def remote_git(self,*args):
        return subprocess.check_output(['git','-c','safe.directory=*','--git-dir='+str(self.remote),*args],
                                       env=self.g.env,stderr=subprocess.PIPE)

    def publish(self):return R.publish(self.g.repo,self.g.root,self.result,'retention')

    def test_publish_and_recover_identical_commit_without_study_retry(self):
        first=self.publish();self.assertFalse(first['already_published'])
        self.assertEqual(self.remote_git('show',self.result+':partial.log'),b'failure bytes\x00')
        second=self.publish();self.assertTrue(second['already_published'])
        self.assertFalse(second['promotion_authority'])

    def test_missing_or_changed_tip_refused(self):
        self.remote_git('update-ref','-d',R.BRANCH)
        with self.assertRaisesRegex(ValueError,'missing'):self.publish()
        other=self.g.commit({'reservation.json':self.g.raw,'other':b'writer'},[self.g.root])
        self.g.git('update-ref','refs/heads/other',other)
        self.remote_git('fetch',str(self.g.repo),'refs/heads/other')
        self.remote_git('update-ref',R.BRANCH,other)
        with self.assertRaisesRegex(ValueError,'tip changed'):self.publish()

    def test_concurrent_writer_rejects_push_and_preserves_both_results(self):
        other=self.g.commit({'reservation.json':self.g.raw,'other':b'writer'},[self.g.root])
        self.g.git('update-ref','refs/heads/other',other)
        self.remote_git('fetch',str(self.g.repo),'refs/heads/other')
        original=subprocess.run
        def race(args,**kwargs):
            if 'push' in args:self.remote_git('update-ref',R.BRANCH,other)
            return original(args,**kwargs)
        with patch.object(R.subprocess,'run',side_effect=race):
            with self.assertRaises(subprocess.CalledProcessError):self.publish()
        self.assertEqual(self.remote_git('rev-parse',R.BRANCH).decode().strip(),other)
        self.assertEqual(self.g.git('show',self.result+':partial.log'),b'failure bytes\x00')

    def test_different_push_destination_refused(self):
        self.g.git('config','remote.retention.pushurl',str(self.g.repo/'other.git'))
        with self.assertRaisesRegex(ValueError,'identical fetch/push'):self.publish()
