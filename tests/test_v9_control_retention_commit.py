import unittest
from tools.v9 import control_retention_commit as C
from tests import test_v9_record_control_outcome as history


class RetentionCommit(unittest.TestCase):
    def setUp(self):
        self.f=history.RetainedAncestry();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.attempt=self.f.repo/'attempt';self.attempt.mkdir()
        (self.attempt/'reservation.json').write_bytes(self.f.raw)

    def prepare(self,tip=None):
        return C.prepare(self.f.repo,self.f.root,tip or self.f.root,self.attempt,
                         ('Synthetic retention','synthetic@example.invalid'))

    def test_partial_bytes_retained_without_ref_or_index_changes(self):
        (self.attempt/'partial.log').write_bytes(b'failed\x00raw\r\n')
        before=self.f.git('for-each-ref')
        self.f.git('read-tree',self.f.root)
        index=(self.f.repo/'.git/index').read_bytes()
        result=self.prepare()
        self.assertEqual(self.f.git('show',result['commit']+':partial.log'),b'failed\x00raw\r\n')
        self.assertEqual(self.f.git('rev-parse',result['commit']+'^').decode().strip(),self.f.root)
        self.assertEqual((self.f.repo/'.git/index').read_bytes(),index)
        self.assertEqual(self.f.git('for-each-ref'),before)
        self.assertFalse(result['remote_publication_verified'])

    def test_reservation_only_failure_is_packaged(self):
        result=self.prepare();self.assertEqual(result['files'],1)
        self.assertEqual(self.f.git('show',result['commit']+':reservation.json'),self.f.raw)

    def test_changed_tip_and_changed_reservation_refused(self):
        with self.assertRaisesRegex(ValueError,'tip changed'):self.prepare('0'*40)
        (self.attempt/'reservation.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'reservation differs'):self.prepare()

    def test_nonroot_reservation_and_unsafe_payload_refused(self):
        child=self.f.commit({'reservation.json':self.f.raw},[self.f.root])
        with self.assertRaisesRegex(ValueError,'original reservation root'):
            C.prepare(self.f.repo,child,child,self.attempt,('Synthetic','synthetic@example.invalid'))
        (self.attempt/'.git').mkdir();(self.attempt/'.git/config').write_bytes(b'unsafe')
        with self.assertRaisesRegex(ValueError,'unsafe payload'):self.prepare()
