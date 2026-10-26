import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.v9 import control_outcome_job as J

REAL_CHECKOUT=J.checkout


class OutcomeJob(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.repo=self.root/'repo';self.repo.mkdir();self.work=self.root/'work'
        self.qualification=self.root/'qualification';self.qualification.write_bytes(b'synthetic')
        self.events=[];self.raw=b'{"status":"RESERVED"}';self.source='a'*40;self.reservation='b'*40;self.commit='c'*40
        for target in ('checkout','fetch_reservation','R.reserve','P.retain','C.prepare','U.publish'):
            obj=J
            parts=target.split('.')
            for part in parts[:-1]:obj=getattr(obj,part)
            patcher=patch.object(obj,parts[-1]);mock=patcher.start();self.addCleanup(patcher.stop)
            setattr(self,target.replace('.','_'),mock)
        self.checkout.side_effect=lambda *a:self.events.append('checkout')
        self.R_reserve.side_effect=self.reserve
        self.fetch_reservation.side_effect=lambda *a:self.events.append('fetch')
        self.P_retain.side_effect=self.execute
        self.C_prepare.side_effect=self.prepare
        self.U_publish.side_effect=lambda *a:(self.events.append('publish') or dict(status='RETAINED_COMMIT_FETCH_VERIFIED',commit=self.commit))
        self.capacity_calls=0
        self.input_preparer=self.prepare_inputs

    def reserve(self,*a):
        self.events.append('reserve');return dict(reservation_commit=self.reservation,reservation_bytes=self.raw)

    def execute(self,md,evidence,signals,out,source,reservation,**kwargs):
        self.events.append('execute');out.mkdir();(out/'reservation.json').write_bytes(Path(reservation).read_bytes())
        (out/'partial.log').write_bytes(b'retained bytes')
        return dict(status='PRICE_DIAGNOSTICS_INDEPENDENTLY_AUDITED_NET_UNAVAILABLE')

    def prepare(self,repo,reservation,tip,attempt,identity):
        self.events.append('prepare');self.assertEqual((attempt/'reservation.json').read_bytes(),self.raw)
        return dict(commit=self.commit)

    def prepare_inputs(self,md,evidence,signals,log):
        self.events.append('inputs');md.mkdir();evidence.write_bytes(b'{}');signals.mkdir();log.write_bytes(b'input preparation complete')

    def cap(self):self.capacity_calls+=1;return {}

    def run_job(self):
        return J.run(self.repo,self.work,self.root/'md',self.root/'evidence',self.root/'signals',self.source,'123','1',
                     self.qualification,'d'*64,object(),self.cap,('Synthetic','synthetic@example.invalid'),self.input_preparer)

    def test_order_capacity_refresh_and_repeat_refusal(self):
        report=self.run_job();self.assertEqual(report['status'],'RETAINED_DIAGNOSTICS')
        self.assertEqual(self.events,['checkout','reserve','fetch','inputs','execute','prepare','publish'])
        self.assertEqual(self.capacity_calls,2)
        self.assertEqual(json.loads((self.work/'job.json').read_bytes()),report)
        with self.assertRaises(FileExistsError):self.run_job()
        self.assertEqual(self.R_reserve.call_count,1)

    def test_unverified_reservation_never_executes_or_publishes(self):
        self.R_reserve.side_effect=RuntimeError('ambiguous remote create')
        report=self.run_job();self.assertEqual(report['status'],'RESERVATION_UNVERIFIED_NO_EXECUTION')
        self.P_retain.assert_not_called();self.U_publish.assert_not_called()
        self.assertFalse(report['reservation_verified'])

    def test_fetch_failure_retains_reservation_without_execution(self):
        self.fetch_reservation.side_effect=RuntimeError('fetch failed')
        report=self.run_job();self.assertEqual(report['status'],'FAILED_OR_PARTIAL_RETAINED')
        self.P_retain.assert_not_called();self.U_publish.assert_called_once()

    def test_interruption_still_attempts_partial_publication(self):
        def interrupt(*a,**kw):self.execute(*a,**kw);raise KeyboardInterrupt()
        self.P_retain.side_effect=interrupt
        report=self.run_job();self.assertEqual(report['status'],'FAILED_OR_PARTIAL_RETAINED')
        self.assertEqual((self.work/'attempt/partial.log').read_bytes(),b'retained bytes')
        self.assertEqual(report['error_type'],'KeyboardInterrupt')

    def test_publication_failure_keeps_local_payload_and_commit(self):
        self.U_publish.side_effect=RuntimeError('remote failed')
        report=self.run_job();self.assertEqual(report['status'],'PUBLICATION_FAILED_LOCAL_FILES_RETAINED')
        self.assertEqual(report['retained_commit'],self.commit)
        self.assertTrue((self.work/'attempt/partial.log').exists())
        self.assertFalse(report['publication_verified']);self.U_publish.assert_called_once()

    def test_workspace_overlap_rejected_before_reservation(self):
        self.work=self.repo/'output'
        with self.assertRaisesRegex(ValueError,'overlaps'):self.run_job()
        self.R_reserve.assert_not_called()

    def test_checkout_rejects_wrong_source_dirty_tree_and_other_origin(self):
        url=b'https://github.com/blazebrt/perp-dex-radar.git\n'
        for responses in [(b'wrong\n',),(self.source.encode(),b' M file'),
                          (self.source.encode(),b'',b'https://elsewhere.invalid/repo'),
                          (self.source.encode(),b'',url,b'https://elsewhere.invalid/push')]:
            with patch.object(J.P,'ROOT',self.repo),patch.object(J,'git',side_effect=responses):
                with self.subTest(responses=responses),self.assertRaises(ValueError):REAL_CHECKOUT(self.repo,self.source)
        with patch.object(J.P,'ROOT',self.repo),patch.object(J,'git',side_effect=[self.source.encode(),b'',url,url]):
            REAL_CHECKOUT(self.repo,self.source)

    def test_preparation_failure_retains_log_and_never_executes(self):
        def fail(md,evidence,signals,log):
            self.events.append('inputs');log.write_bytes(b'partial download');raise RuntimeError('preparation failed')
        self.input_preparer=fail
        report=self.run_job();self.assertEqual(report['status'],'FAILED_OR_PARTIAL_RETAINED')
        self.P_retain.assert_not_called();self.U_publish.assert_called_once()
        self.assertEqual((self.work/'attempt/input-preparation.log').read_bytes(),b'partial download')
        self.assertFalse(json.loads((self.work/'attempt/preparation-failure.json').read_bytes())['execution_started'])
        self.assertEqual(self.capacity_calls,1)

    def test_preexisting_inputs_refused_before_reservation(self):
        (self.root/'md').mkdir()
        with self.assertRaisesRegex(FileExistsError,'after reservation'):self.run_job()
        self.R_reserve.assert_not_called();self.assertEqual(self.events,[])
