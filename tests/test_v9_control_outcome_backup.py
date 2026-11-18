import json
import subprocess
import unittest
from tools.v9 import control_outcome_backup as B
from tests import test_v9_record_control_outcome as fixture


class Backup(unittest.TestCase):
    def setUp(self):
        self.f=fixture.RetainedAncestry();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.work=self.f.repo/'work';self.work.mkdir();self.bundle=self.work/'recovery.bundle'
        self.commit=self.f.commit({'reservation.json':self.f.raw,'partial.log':b'partial\x00'},[self.f.root])
        self.doc=dict(reservation_commit=self.f.root,retained_commit=self.commit)

    def write(self):(self.work/'job.json').write_text(json.dumps(self.doc))

    def test_bundle_restores_partial_bytes_and_preserves_refs(self):
        self.write();before=self.f.git('for-each-ref');result=B.backup(self.f.repo,self.work,self.bundle)
        self.assertEqual(result['commit'],self.commit);self.assertFalse(result['remote_backup_verified'])
        self.assertEqual(self.f.git('for-each-ref'),before)
        restored=self.f.repo/'restored';self.f.git('init','--quiet','--template=',str(restored))
        subprocess.check_output(['git','-c','safe.directory=*','-C',str(restored),'bundle','unbundle',str(self.bundle)],env=self.f.env,stderr=subprocess.PIPE)
        raw=subprocess.check_output(['git','-c','safe.directory=*','-C',str(restored),'show',self.commit+':partial.log'],env=self.f.env)
        self.assertEqual(raw,b'partial\x00')
        with self.assertRaises(FileExistsError):B.backup(self.f.repo,self.work,self.bundle)

    def test_reservation_only_bundle_is_recoverable(self):
        self.doc.pop('retained_commit');self.write()
        self.assertEqual(B.backup(self.f.repo,self.work,self.bundle)['commit'],self.f.root)

    def test_missing_or_unverified_record_does_not_invent_backup(self):
        self.assertEqual(B.backup(self.f.repo,self.work,self.bundle)['status'],'NO_JOB_RECORD')
        self.doc={};self.write()
        self.assertEqual(B.backup(self.f.repo,self.work,self.bundle)['status'],'NO_VERIFIED_COMMIT_RECORDED')
        self.assertFalse(self.bundle.exists())

    def test_wrong_reservation_refused_without_ref_changes(self):
        self.doc['reservation_commit']='a'*40;self.write();before=self.f.git('for-each-ref')
        with self.assertRaisesRegex(ValueError,'ancestry'):B.backup(self.f.repo,self.work,self.bundle)
        self.assertEqual(self.f.git('for-each-ref'),before);self.assertFalse(self.bundle.exists())
