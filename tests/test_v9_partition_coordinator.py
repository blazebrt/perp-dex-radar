import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from tests import test_v9_control_outcomes as F
from tools.v9 import control_partition_coordinator as C, control_partition_execute as E
from tools.v9 import control_partition_plan as P


class Coordinator(unittest.TestCase):
    match=F.Outcomes.match
    def setUp(self):
        F.Outcomes.setUp(self)
        self.plan=P.build((self.source/'manifest.json').read_bytes(),self.digest)
        self.registry=self.root/'reservation'
        C.initialize(self.registry,self.source,self.plan,self.digest)
        self.ids=[u['unit_id'] for u in self.plan['units']]

    def run_units(self):
        for job in self.ids:
            self.assertEqual(C.run_one(self.registry,self.source,job,lambda:(self.context,self))['status'],'UNIT_RECEIPT_RECORDED')

    def test_complete_recording_and_idempotent_read_only_recovery(self):
        self.run_units()
        for job in self.ids:
            result=C.record_unit(self.registry,self.source,job)
            self.assertEqual(result['status'],'UNIT_RECEIPT_RECORDED')
        result=C.merge_once(self.registry,self.source,self.context)
        self.assertEqual(result['status'],'MERGE_ACCOUNTING_RECORDED_NOT_PRICE_AUDITED')
        self.assertEqual(C.record_merge(self.registry,self.source),result)
        self.assertTrue(all(r['state']=='RECORDED' for r in C.snapshot(self.registry)))
        with patch.object(E,'run_unit',side_effect=AssertionError('recomputed')) as worker:
            with self.assertRaises(ValueError):C.run_one(self.registry,self.source,self.ids[0],lambda:None)
            worker.assert_not_called()
        with self.assertRaises(ValueError):C.merge_once(self.registry,self.source,self.context)
        with self.assertRaises(FileExistsError):C.initialize(self.registry,self.source,self.plan,self.digest)

    def test_concurrent_claims_have_exactly_one_winner(self):
        def attempt(_):
            try:C.claim(self.registry,self.source,self.ids[0]);return True
            except ValueError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt,range(8))),1)
        self.assertEqual(next(r for r in C.snapshot(self.registry) if r['id']==self.ids[0])['state'],'CLAIMED')

    def test_process_exit_after_committed_claim_never_restarts_unit(self):
        code="import os,sys;from tools.v9 import control_partition_coordinator as C;C.claim(sys.argv[1],sys.argv[2],sys.argv[3]);os._exit(17)"
        result=subprocess.run([sys.executable,'-c',code,str(self.registry),str(self.source),self.ids[0]],
                              cwd=Path(C.__file__).resolve().parents[2],capture_output=True)
        self.assertEqual(result.returncode,17,result.stderr)
        with self.assertRaises(ValueError):C.run_one(self.registry,self.source,self.ids[0],lambda:None)
        with self.assertRaises(ValueError):C.record_unit(self.registry,self.source,self.ids[0])
        self.assertEqual(next(r for r in C.snapshot(self.registry) if r['id']==self.ids[0])['state'],'CLAIMED')

    def test_complete_receipt_after_unrecorded_claim_recovers_without_execution(self):
        job=self.ids[0];r,_=C.claim(self.registry,self.source,job)
        E.run_unit(self.source,C.output(self.registry,job),self.plan,job,lambda:(self.context,self),self.digest)
        with patch.object(E,'run_unit',side_effect=AssertionError('recomputed')):
            self.assertEqual(C.record_unit(self.registry,self.source,job)['status'],'UNIT_RECEIPT_RECORDED')
        path=C.output(self.registry,job)/'receipt.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'changed'):C.record_unit(self.registry,self.source,job)

    def test_failed_worker_is_permanent_and_blocks_merge(self):
        def bad():raise RuntimeError('injected failure')
        result=C.run_one(self.registry,self.source,self.ids[0],bad)
        self.assertEqual(result['status'],'FAILED_OR_PARTIAL')
        self.assertEqual(next(r for r in C.snapshot(self.registry) if r['id']==self.ids[0])['state'],'FAILED')
        with self.assertRaises(ValueError):C.run_one(self.registry,self.source,self.ids[0],bad)
        with self.assertRaises(ValueError):C.merge_once(self.registry,self.source,self.context)

    def test_merge_receipt_recovers_without_reconstruction(self):
        self.run_units();r,_=C.claim(self.registry,self.source,'__merge__')
        paths=[C.output(self.registry,i) for i in self.ids]
        C.M.merge(self.source,C.output(self.registry,'__merge__'),self.plan,paths,self.context,self.digest)
        with patch.object(C.M,'merge',side_effect=AssertionError('reconstructed')):
            result=C.record_merge(self.registry,self.source)
        self.assertEqual(result['status'],'MERGE_ACCOUNTING_RECORDED_NOT_PRICE_AUDITED')

    def test_changed_code_input_or_retained_receipt_is_rejected(self):
        with patch.object(C,'code_bindings',return_value={}):
            with self.assertRaisesRegex(ValueError,'implementation'):C.claim(self.registry,self.source,self.ids[0])
        self.assertTrue(all(r['state']=='PENDING' for r in C.snapshot(self.registry)))
        original=(self.source/'manifest.json').read_bytes();(self.source/'manifest.json').write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError,'input'):C.claim(self.registry,self.source,self.ids[0])
        (self.source/'manifest.json').write_bytes(original)
        self.run_units();path=C.output(self.registry,self.ids[0])/'receipt.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'retention changed'):C.merge_once(self.registry,self.source,self.context)

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux symlink escape protection')
    def test_output_parent_escape_is_rejected_before_claim(self):
        outside=self.root/'outside';outside.mkdir()
        (self.registry/'units').symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'unsafe unit output'):C.claim(self.registry,self.source,self.ids[0])
        self.assertTrue(all(r['state']=='PENDING' for r in C.snapshot(self.registry)))

    def test_market_hash_and_overlapping_reservation_refused(self):
        with self.assertRaisesRegex(ValueError,'registered market'):C.initialize(self.root/'blocked',self.source,self.plan,P.INPUT_SHA)
        with self.assertRaisesRegex(ValueError,'overlaps'):C.initialize(self.source/'blocked',self.source,self.plan,self.digest)
