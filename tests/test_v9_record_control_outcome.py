import json
from unittest.mock import patch
import unittest
from tests import test_v9_control_outcome_publish as fixture
from tools.v9 import record_control_outcome as R, record_run as H


class History(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Publish();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.retain()
        self.files={p.relative_to(self.f.out).as_posix():p.read_bytes() for p in self.f.out.rglob('*') if p.is_file()}
        self.original=self.files['reservation.json']

    def inspect(self):
        with patch.object(R,'INPUT_HASH',self.f.digest):
            return R.inspect(self.files.__getitem__,lambda p:R.sha(self.files[p]),list(self.files),
                lambda p:(fixture.P.ROOT/p).read_bytes(),'b'*40,'c'*40,self.original,'2026-10-24T00:00:00Z')

    def test_verified_attempt_still_has_no_strategy_authority(self):
        record=self.inspect()
        self.assertEqual(record['study'],'A6');self.assertEqual(record['confirmed'],[])
        self.assertFalse(record['retained_result_independently_verified'])
        self.assertEqual(record['file_paths']['report'],'audit/audit.json')
        self.assertEqual(record['retained_files_sha256']['reservation.json'],R.sha(self.original))

    def test_reservation_only_and_started_are_recordable(self):
        files=self.files;self.files={'reservation.json':self.original}
        record=self.inspect();self.assertEqual(record['status'],'INCOMPLETE_RESERVED');self.assertIsNone(record['files']['trades'])
        self.files=files;attempt=json.loads(self.files['attempt.json']);attempt['status']='STARTED';attempt.pop('artifacts_sha256')
        self.files['attempt.json']=json.dumps(attempt).encode()
        self.assertEqual(self.inspect()['status'],'STARTED')

    def test_partial_failure_retained_without_confirmation(self):
        attempt=json.loads(self.files['attempt.json']);attempt['status']='FAILED_OR_PARTIAL';attempt['audit_exit']=1
        self.files['attempt.json']=json.dumps(attempt).encode()
        record=self.inspect();self.assertEqual(record['status'],'FAILED_OR_PARTIAL');self.assertEqual(record['confirmed'],[])

    def test_changed_reservation_artifact_and_authority_rejected(self):
        original=dict(self.files)
        for target in ('reservation','artifact','authority'):
            self.files=dict(original)
            if target=='reservation':self.files['reservation.json']+=b' '
            if target=='artifact':self.files['outcomes.log']+=b'changed'
            if target=='authority':
                attempt=json.loads(self.files['attempt.json']);attempt['promotion_authority']=True
                self.files['attempt.json']=json.dumps(attempt).encode()
            with self.subTest(target=target),self.assertRaises(ValueError):self.inspect()

    def test_append_preserves_chain_and_refuses_duplicate(self):
        record=self.inspect();path=str(self.f.root/'history.jsonl')
        H.append(record,path);self.assertEqual(H.verify(H.read(path)),[])
        before=(self.f.root/'history.jsonl').read_bytes()
        with self.assertRaises(SystemExit):H.append(record,path)
        self.assertEqual(before,(self.f.root/'history.jsonl').read_bytes())

    def test_record_run_routes_a6_to_its_builder(self):
        with patch.object(R,'build',return_value={'synthetic':True}) as build:
            self.assertEqual(H.build('A6','repo'),{'synthetic':True})
            build.assert_called_once_with('repo','origin/evidence-a6-outcome-results')
