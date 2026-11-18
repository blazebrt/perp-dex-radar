import concurrent.futures
import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tests import test_v9_control_outcomes as F
from tools.v9 import control_partition_objects as B, control_partition_transport as T


class Bundles(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'objects').mkdir()
        self.store=B.LocalObjects(self.root/'objects');self.source=self.root/'input';self.source.mkdir()
        (self.source/'a').write_bytes(b'x'*2048+b'last');(self.source/'b').write_bytes(b'x'*1024)
        (self.source/'empty').write_bytes(b'')

    def test_exact_roundtrip_dedup_and_concurrent_create_only_writes(self):
        bundle=B.pack(self.source,self.store,chunk_bytes=1024)
        self.assertEqual(len(list(self.store.root.iterdir())),2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            refs=list(pool.map(self.store.put,[b'x'*1024]*8))
        self.assertTrue(all(r==refs[0] for r in refs))
        out=B.restore(bundle,self.store,self.root/'restored')
        for p in self.source.iterdir():self.assertEqual(p.read_bytes(),(out/p.name).read_bytes())
        with self.assertRaises(ValueError):B.restore(bundle,self.store,out)

    def test_corruption_missing_objects_and_adapter_lies_are_rejected(self):
        bundle=B.pack(self.source,self.store,chunk_bytes=1024);part=bundle['files'][0]['chunks'][0]
        object_path=self.store.root/part['sha256'];object_path.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'hash/size'):B.restore(bundle,self.store,self.root/'corrupt')
        with self.assertRaisesRegex(ValueError,'hash/size'):self.store.put(b'x'*1024)
        object_path.unlink()
        with self.assertRaisesRegex(ValueError,'missing'):B.restore(bundle,self.store,self.root/'missing')
        with patch.object(self.store,'get',return_value=b'wrong'):
            with self.assertRaisesRegex(ValueError,'returned object'):B.restore(bundle,self.store,self.root/'lying')

    def test_manifest_paths_counts_hashes_and_budget_are_validated_before_output(self):
        bundle=B.pack(self.source,self.store,chunk_bytes=1024)
        variants=[]
        for name in ('../escape','/absolute','C:escape','a\\b','a/../x','NUL.json','a./x'):
            x=copy.deepcopy(bundle);x['files'][0]['path']=name;variants.append(x)
        x=copy.deepcopy(bundle);x['files'].append(x['files'][0]);variants.append(x)
        x=copy.deepcopy(bundle);x['files'][1]['path']='A';variants.append(x)
        x=copy.deepcopy(bundle);x['bytes']=True;variants.append(x)
        x=copy.deepcopy(bundle);x['files'][0]['chunks'].pop();variants.append(x)
        x=copy.deepcopy(bundle);x['files'][0]['sha256']='x'*64;variants.append(x)
        x=copy.deepcopy(bundle);x['files'][0]['bytes']=B.MAX_BYTES+1;variants.append(x)
        for n,x in enumerate(variants):
            out=self.root/str(n)
            with self.assertRaises(ValueError):B.restore(x,self.store,out)
            self.assertFalse(out.exists())

    def test_changed_files_and_wrong_put_references_do_not_form_valid_bundle(self):
        put=self.store.put;changed=[]
        def mutate(raw):
            if not changed:
                changed.append(True);(self.source/'a').write_bytes(b'changed')
            return put(raw)
        with patch.object(self.store,'put',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'changed'):B.pack(self.source,self.store,chunk_bytes=1024)
        with patch.object(self.store,'put',return_value=dict(sha256='0'*64,bytes=7)):
            with self.assertRaisesRegex(ValueError,'reference mismatch'):B.pack(self.source,self.store,chunk_bytes=1024)


class ObjectTransport(unittest.TestCase):
    match=F.Outcomes.match
    def setUp(self):
        F.Outcomes.setUp(self)
        self.plan=T.C.P.build((self.source/'manifest.json').read_bytes(),self.digest)
        self.ids=[u['unit_id'] for u in self.plan['units']]
        self.remote=self.root/'shared.git';self.remote.mkdir();T.git(self.remote,'init','--bare','-q')
        (self.root/'objects').mkdir();self.store=B.LocalObjects(self.root/'objects')
        T.initialize(self.remote,self.root/'init',self.source,self.plan,self.digest,objects=self.store)

    def test_complete_run_git_contains_only_metadata_and_restores_exact_outputs(self):
        for n,job in enumerate(self.ids):
            w=self.root/f'w{n}';T.run_one(self.remote,w,self.source,job,lambda:(self.context,self),objects=self.store)
            shutil.rmtree(w)
        w=self.root/'merge';T.merge_once(self.remote,w,self.source,self.context,objects=self.store)
        expected=T.inventory(T.C.output(w/'reservation','__merge__'));shutil.rmtree(w)
        listed=T.git(self.remote,'ls-tree','-r','--name-only',T.BRANCH).decode().splitlines()
        self.assertTrue(any('/object-refs/' in p for p in listed))
        self.assertFalse(any('/units/' in p or '/merged/' in p or p.endswith('.gz') for p in listed))
        recovered=self.root/'recovered'
        with patch.object(T.C.E,'run_unit',side_effect=AssertionError('rerun')),patch.object(T.C.M,'merge',side_effect=AssertionError('rerun')):
            result=T.verify_retained(self.remote,recovered,self.source,objects=self.store)
        self.assertTrue(all(r['state']=='RECORDED' for r in result['jobs']))
        self.assertEqual(T.inventory(T.C.output(recovered/'reservation','__merge__')),expected)
        with self.assertRaisesRegex(ValueError,'object store required'):
            T.claim(self.remote,self.root/'wrong-mode',self.source,self.ids[0])

    def test_object_upload_failure_keeps_claim_and_recovers_without_computation(self):
        w=self.root/'worker';job=self.ids[0]
        r,token,_=T.claim(self.remote,w,self.source,job,objects=self.store)
        T.C.E.run_unit(self.source,T.C.output(w/'reservation',job),self.plan,job,lambda:(self.context,self),self.digest)
        with patch.object(self.store,'put',side_effect=OSError('store unavailable')):
            with self.assertRaises(OSError):T.publish(self.remote,w,self.source,job,token,objects=self.store)
        read=T.checkout(self.remote,self.root/'read')
        self.assertEqual(T.row(read/'reservation',self.source,job)[1]['state'],'CLAIMED')
        with patch.object(T.C.E,'run_unit',side_effect=AssertionError('rerun')):
            T.publish(self.remote,w,self.source,job,token,objects=self.store)
            T.publish(self.remote,w,self.source,job,token,objects=self.store)
        with patch.object(self.store,'get',side_effect=OSError('object unavailable')):
            with self.assertRaises(OSError):T.verify_retained(self.remote,self.root/'missing',self.source,objects=self.store)

    def test_failed_partial_bytes_survive_metadata_publication_and_ack_loss(self):
        def bad():raise RuntimeError('preparation failed')
        push=T.push
        def lost_ack(w,message):
            result=push(w,message)
            if message=='Retain synthetic result':raise subprocess.CalledProcessError(1,['git'])
            return result
        with patch.object(T,'push',side_effect=lost_ack):
            result=T.run_one(self.remote,self.root/'failed',self.source,self.ids[0],bad,objects=self.store)
        self.assertEqual(result['status'],'RETAINED_FAILED')
        shutil.rmtree(self.root/'failed')
        out=self.root/'recovery';report=T.verify_retained(self.remote,out,self.source,objects=self.store)
        self.assertEqual(next(r for r in report['jobs'] if r['id']==self.ids[0])['state'],'FAILED')
        self.assertTrue((T.C.output(out/'reservation',self.ids[0])/'receipt.json').is_file())
