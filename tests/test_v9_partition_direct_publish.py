from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from tests import test_v9_partition_objects as F
from tools.v9 import control_partition_transport as T, control_partition_objects as B


class DirectPublication(unittest.TestCase):
    match=F.ObjectTransport.match
    def setUp(self):F.ObjectTransport.setUp(self)

    def completed_unpublished(self,n=0):
        w=self.root/f'worker{n}';job=self.ids[n]
        r,token,_=T.claim(self.remote,w,self.source,job,objects=self.store)
        artifact=T.C.output(w/'reservation',job)
        T.C.E.run_unit(self.source,artifact,self.plan,job,lambda:(self.context,self),self.digest)
        return w,job,token,artifact

    def test_unit_and_merge_publication_never_copy_payload_and_preserve_originals(self):
        push=T.push;restore=B.restore
        def lost_ack(w,message):
            result=push(w,message)
            if message=='Retain synthetic result':raise subprocess.CalledProcessError(1,['git'])
            return result
        def no_merged_restore(bundle,store,destination):
            self.assertNotEqual(Path(destination).name,'merged','publication restored a full duplicate merge')
            return restore(bundle,store,destination)
        with patch.object(T.shutil,'copytree',side_effect=AssertionError('payload copy forbidden')), \
             patch.object(T,'push',side_effect=lost_ack),patch.object(B,'restore',side_effect=no_merged_restore):
            for n,job in enumerate(self.ids):
                w=self.root/f'w{n}'
                T.run_one(self.remote,w,self.source,job,lambda:(self.context,self),objects=self.store)
                self.assertTrue((T.C.output(w/'reservation',job)/'receipt.json').is_file())
            w=self.root/'merge';result=T.merge_once(self.remote,w,self.source,self.context,objects=self.store)
            self.assertEqual(result['status'],'RETAINED_MERGE_NOT_PRICE_AUDITED')
            original=T.inventory(w/'reservation/merged')
        recovered=self.root/'recovered';T.verify_retained(self.remote,recovered,self.source,objects=self.store)
        self.assertEqual(T.inventory(recovered/'reservation/merged'),original)
        self.assertEqual(T.inventory(w/'reservation/merged'),original)

    def test_mutation_after_verification_or_after_packing_cannot_publish_success(self):
        pack=B.pack
        for n,when in enumerate(('before','after')):
            w,job,token,artifact=self.completed_unpublished(n)
            receipt=artifact/'receipt.json';raw=receipt.read_bytes()
            def changed(directory,store,**kwargs):
                if when=='before':receipt.write_bytes(raw+b' ')
                result=pack(directory,store,**kwargs)
                if when=='after':receipt.write_bytes(raw+b' ')
                return result
            with self.subTest(when=when),patch.object(B,'pack',side_effect=changed):
                with self.assertRaisesRegex(ValueError,'changed during offload'):
                    T.publish(self.remote,w,self.source,job,token,objects=self.store)
            read=T.checkout(self.remote,self.root/f'read{n}')
            self.assertEqual(T.row(read/'reservation',self.source,job)[1]['state'],'CLAIMED')
            self.assertTrue(receipt.is_file());receipt.write_bytes(raw)
            T.publish(self.remote,w,self.source,job,token,objects=self.store)

    def test_changed_receipt_during_independent_verification_rolls_back_recording(self):
        w,job,token,artifact=self.completed_unpublished()
        read=T.checkout(self.remote,self.root/'read');root=read/'reservation';verify=T.C.V.verify
        path=artifact/'receipt.json';raw=path.read_bytes()
        def changed(*args,**kwargs):
            result=verify(*args,**kwargs);path.write_bytes(raw+b' ');return result
        with patch.object(T.C.V,'verify',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed during verification'):
                T.C.record_unit(root,self.source,job,artifact_dir=artifact)
        self.assertEqual(T.row(root,self.source,job)[1]['state'],'CLAIMED')
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'overlaps source'):
            T.C.record_unit(root,self.source,job,artifact_dir=self.source)
        self.assertEqual(T.row(root,self.source,job)[1]['state'],'CLAIMED')

    def test_receipt_swapped_around_verification_cannot_bind_a_different_snapshot(self):
        w,job,token,artifact=self.completed_unpublished()
        path=artifact/'receipt.json';raw=path.read_bytes();record=T.C.record_unit
        def swapped(*args,**kwargs):
            path.write_bytes(raw+b' ')
            result=record(*args,**kwargs)
            path.write_bytes(raw)
            return result
        with patch.object(T.C,'record_unit',side_effect=swapped):
            with self.assertRaisesRegex(ValueError,'differs from initial inventory'):
                T.publish(self.remote,w,self.source,job,token,objects=self.store)
        read=T.checkout(self.remote,self.root/'read')
        self.assertEqual(T.row(read/'reservation',self.source,job)[1]['state'],'CLAIMED')
        T.publish(self.remote,w,self.source,job,token,objects=self.store)

    def test_idempotent_recovery_rechecks_objects_without_materializing_output(self):
        w,job,token,artifact=self.completed_unpublished()
        T.publish(self.remote,w,self.source,job,token,objects=self.store)
        with patch.object(B,'restore',side_effect=AssertionError('recovery materialized result')):
            T.publish(self.remote,w,self.source,job,token,objects=self.store)
            blob=next(self.store.root.iterdir());blob.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):T.publish(self.remote,w,self.source,job,token,objects=self.store)
        self.assertTrue((artifact/'receipt.json').is_file())

    def test_failed_partial_publication_does_not_copy_or_remove_original_output(self):
        def bad():raise RuntimeError('synthetic failure')
        w=self.root/'failed'
        with patch.object(T.shutil,'copytree',side_effect=AssertionError('payload copy forbidden')):
            result=T.run_one(self.remote,w,self.source,self.ids[0],bad,objects=self.store)
        self.assertEqual(result['status'],'RETAINED_FAILED')
        original=T.inventory(T.C.output(w/'reservation',self.ids[0]))
        read=T.checkout(self.remote,self.root/'read');root=read/'reservation'
        self.assertEqual(T.row(root,self.source,self.ids[0])[1]['state'],'FAILED')
        bundle=T.C.O.load(T.reference(root,self.ids[0]).read_bytes())
        self.assertEqual(B.verify(bundle,self.store),original)

    def test_changed_merge_manifest_during_accounting_cannot_be_recorded(self):
        for n,job in enumerate(self.ids):
            T.run_one(self.remote,self.root/f'w{n}',self.source,job,lambda:(self.context,self),objects=self.store)
        w=self.root/'merge';r,token,_=T.claim(self.remote,w,self.source,'__merge__',objects=self.store)
        root=w/'reservation';out=T.C.output(root,'__merge__')
        T.C.M.merge(self.source,out,self.plan,[T.C.output(root,i) for i in self.ids],self.context,self.digest,
                    load_unit=T.loader(root,self.store))
        path=out/'manifest.json';raw=path.read_bytes();verify=T.C.O.verify
        def changed(*args,**kwargs):
            result=verify(*args,**kwargs);path.write_bytes(raw+b' ');return result
        with patch.object(T.C.O,'verify',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'manifest changed during verification'):
                T.publish(self.remote,w,self.source,'__merge__',token,objects=self.store)
        read=T.checkout(self.remote,self.root/'read')
        self.assertEqual(T.row(read/'reservation',self.source,'__merge__')[1]['state'],'CLAIMED')
        path.write_bytes(raw)
        T.publish(self.remote,w,self.source,'__merge__',token,objects=self.store)
