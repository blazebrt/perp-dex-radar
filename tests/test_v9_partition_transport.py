import concurrent.futures
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from tests import test_v9_control_outcomes as F
from tools.v9 import control_partition_transport as T
from tools.v9 import control_partition_plan as P


class Transport(unittest.TestCase):
    match=F.Outcomes.match

    def setUp(self):
        F.Outcomes.setUp(self)
        self.plan=P.build((self.source/'manifest.json').read_bytes(),self.digest)
        self.ids=[u['unit_id'] for u in self.plan['units']]
        self.remote=self.root/'shared.git';self.remote.mkdir()
        T.git(self.remote,'init','--bare','-q')
        T.initialize(self.remote,self.root/'init',self.source,self.plan,self.digest)

    def state(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=T.checkout(self.remote,Path(tmp)/'read')
            return T.C.snapshot(w/'reservation')

    def test_full_run_survives_loss_of_all_worker_checkouts(self):
        for n,job in enumerate(self.ids):
            w=self.root/f'worker{n}'
            self.assertEqual(T.run_one(self.remote,w,self.source,job,lambda:(self.context,self))['status'],
                             'RETAINED_SYNTHETIC_UNIT')
            shutil.rmtree(w)
        w=self.root/'merge'
        self.assertEqual(T.merge_once(self.remote,w,self.source,self.context)['status'],'RETAINED_MERGE_NOT_PRICE_AUDITED')
        shutil.rmtree(w);shutil.rmtree(self.root/'init')
        with patch.object(T.C.E,'run_unit',side_effect=AssertionError('recomputed')), \
             patch.object(T.C.M,'merge',side_effect=AssertionError('reconstructed')):
            report=T.verify_retained(self.remote,self.root/'recovered',self.source)
        self.assertTrue(all(r['state']=='RECORDED' for r in report['jobs']))
        with self.assertRaises(ValueError):T.claim(self.remote,self.root/'rerun',self.source,self.ids[0])

    def test_competing_checkouts_allow_one_computation(self):
        barrier=threading.Barrier(2);push=T.push;worker=T.C.E.run_unit
        def concurrent_push(w,message):
            if message=='Claim synthetic work':barrier.wait(timeout=30)
            return push(w,message)
        def run(n):
            try:return T.run_one(self.remote,self.root/f'c{n}',self.source,self.ids[0],lambda:(self.context,self))['status']
            except subprocess.CalledProcessError:return 'CLAIM_CONFLICT'
        with patch.object(T,'push',side_effect=concurrent_push),patch.object(T.C.E,'run_unit',wraps=worker) as execute:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
        self.assertCountEqual(results,['RETAINED_SYNTHETIC_UNIT','CLAIM_CONFLICT'])
        self.assertEqual(execute.call_count,1)

    def test_process_dies_after_remote_claim_blocks_new_worker(self):
        w=self.root/'lost'
        code='import os,sys;from tools.v9 import control_partition_transport as T;T.claim(*sys.argv[1:]);os._exit(19)'
        result=subprocess.run([sys.executable,'-c',code,str(self.remote),str(w),str(self.source),self.ids[0]],
            cwd=Path(T.__file__).resolve().parents[2],capture_output=True)
        self.assertEqual(result.returncode,19,result.stderr)
        shutil.rmtree(w)
        with patch.object(T.C.E,'run_unit',side_effect=AssertionError('recomputed')):
            with self.assertRaises(ValueError):T.run_one(self.remote,self.root/'restart',self.source,self.ids[0],lambda:None)
        self.assertEqual(next(r for r in self.state() if r['id']==self.ids[0])['state'],'CLAIMED')

    def test_completed_unpublished_output_can_be_retained_without_rerun(self):
        w=self.root/'interrupted';job=self.ids[0]
        r,token,_=T.claim(self.remote,w,self.source,job)
        T.C.E.run_unit(self.source,T.C.output(w/'reservation',job),self.plan,job,lambda:(self.context,self),self.digest)
        with patch.object(T,'push',side_effect=subprocess.CalledProcessError(1,['git'])):
            with self.assertRaises(subprocess.CalledProcessError):T.publish(self.remote,w,self.source,job,token)
        self.assertEqual(next(r for r in self.state() if r['id']==job)['state'],'CLAIMED')
        with patch.object(T.C.E,'run_unit',side_effect=AssertionError('recomputed')):
            T.publish(self.remote,w,self.source,job,token)
            T.publish(self.remote,w,self.source,job,token)
        (T.C.output(w/'reservation',job)/'receipt.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'differs'):T.publish(self.remote,w,self.source,job,token)

    def test_lost_publication_ack_and_unrelated_claim_are_preserved(self):
        w=self.root/'unit';job=self.ids[0];r,token,_=T.claim(self.remote,w,self.source,job)
        T.C.E.run_unit(self.source,T.C.output(w/'reservation',job),self.plan,job,lambda:(self.context,self),self.digest)
        push=T.push;calls=[]
        def interference(path,message):
            if message=='Retain synthetic result' and not calls:
                calls.append(True)
                T.claim(self.remote,self.root/'other',self.source,self.ids[1])
            return push(path,message)
        with patch.object(T,'push',side_effect=interference):T.publish(self.remote,w,self.source,job,token)
        states={r['id']:r['state'] for r in self.state()}
        self.assertEqual(states[job],'RECORDED');self.assertEqual(states[self.ids[1]],'CLAIMED')
        # A separate unit simulates an accepted remote update whose acknowledgement is lost.
        other=self.root/'other';_,record=T.row(other/'reservation',self.source,self.ids[1])
        T.C.E.run_unit(self.source,T.C.output(other/'reservation',self.ids[1]),self.plan,self.ids[1],lambda:(self.context,self),self.digest)
        def lost_ack(path,message):
            push(path,message)
            raise subprocess.CalledProcessError(1,['git'],'lost acknowledgement')
        with patch.object(T,'push',side_effect=lost_ack):T.publish(self.remote,other,self.source,self.ids[1],record['token'])

    def test_failed_output_is_retained_and_cannot_be_retried(self):
        def bad():raise RuntimeError('synthetic preparation failed')
        w=self.root/'failed'
        self.assertEqual(T.run_one(self.remote,w,self.source,self.ids[0],bad)['status'],'RETAINED_FAILED')
        shutil.rmtree(w)
        recovered=self.root/'failure-read';T.verify_retained(self.remote,recovered,self.source)
        artifact=T.C.output(recovered/'reservation',self.ids[0])
        self.assertTrue((artifact/'attempt.json').is_file());self.assertTrue((artifact/'receipt.json').is_file())
        with self.assertRaises(ValueError):T.claim(self.remote,self.root/'retry',self.source,self.ids[0])
        with self.assertRaises(ValueError):T.merge_once(self.remote,self.root/'blocked',self.source,self.context)

    def test_wrong_token_source_and_network_destinations_refused(self):
        w=self.root/'claim';_,token,_=T.claim(self.remote,w,self.source,self.ids[0])
        with self.assertRaisesRegex(ValueError,'token'):T.publish(self.remote,w,self.source,self.ids[0],'wrong',failed=True)
        source=self.source/'manifest.json';source.write_bytes(source.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'input'):T.publish(self.remote,w,self.source,self.ids[0],token,failed=True)
        for url in ('https://github.com/blazebrt/perp-dex-radar','git@example.com:repo','relative.git'):
            with self.assertRaises(ValueError):T.remote_path(url)
        with self.assertRaises(ValueError):T.initialize(self.remote,self.root/'duplicate',self.source,self.plan,self.digest)

    def test_ambiguous_claim_ack_never_invokes_worker(self):
        push=T.push
        def lost_ack(w,message):
            push(w,message);raise subprocess.CalledProcessError(1,['git'])
        with patch.object(T,'push',side_effect=lost_ack),patch.object(T.C.E,'run_unit') as worker:
            with self.assertRaises(subprocess.CalledProcessError):
                T.run_one(self.remote,self.root/'unknown',self.source,self.ids[0],lambda:None)
            worker.assert_not_called()
        self.assertEqual(next(r for r in self.state() if r['id']==self.ids[0])['state'],'CLAIMED')

    def test_merge_publication_recovers_without_reconstruction(self):
        for n,job in enumerate(self.ids):
            T.run_one(self.remote,self.root/f'w{n}',self.source,job,lambda:(self.context,self))
        w=self.root/'merge';r,token,_=T.claim(self.remote,w,self.source,'__merge__');root=w/'reservation'
        T.C.M.merge(self.source,T.C.output(root,'__merge__'),self.plan,
                    [T.C.output(root,i) for i in self.ids],self.context,self.digest)
        with patch.object(T,'push',side_effect=subprocess.CalledProcessError(1,['git'])):
            with self.assertRaises(subprocess.CalledProcessError):T.publish(self.remote,w,self.source,'__merge__',token)
        with patch.object(T.C.M,'merge',side_effect=AssertionError('reconstructed')):
            T.publish(self.remote,w,self.source,'__merge__',token)
            T.verify_retained(self.remote,self.root/'verify-merge',self.source)

    def test_changed_shared_result_is_not_accepted_on_recovery(self):
        T.run_one(self.remote,self.root/'worker',self.source,self.ids[0],lambda:(self.context,self))
        changed=T.checkout(self.remote,self.root/'changed')
        path=T.C.output(changed/'reservation',self.ids[0])/'receipt.json'
        path.write_bytes(path.read_bytes()+b' ')
        T.push(changed,'Injected corruption in test')
        with self.assertRaisesRegex(ValueError,'changed'):
            T.verify_retained(self.remote,self.root/'reject-corruption',self.source)

    def test_transfer_limit_and_symlinks_fail_without_terminal_transition(self):
        w=self.root/'limit';_,token,_=T.claim(self.remote,w,self.source,self.ids[0])
        out=T.C.output(w/'reservation',self.ids[0]);out.mkdir(parents=True);(out/'partial').write_bytes(b'12')
        with patch.object(T,'MAX_BYTES',1):
            with self.assertRaisesRegex(ValueError,'byte limit'):T.publish(self.remote,w,self.source,self.ids[0],token,failed=True)
        if sys.platform.startswith('linux'):
            (out/'link').symlink_to(self.source/'manifest.json')
            with self.assertRaisesRegex(ValueError,'unsafe'):T.publish(self.remote,w,self.source,self.ids[0],token,failed=True)
        self.assertEqual(next(r for r in self.state() if r['id']==self.ids[0])['state'],'CLAIMED')
