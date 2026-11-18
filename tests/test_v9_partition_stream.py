from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from tests import test_v9_control_partitions as Parity, test_v9_partition_objects as Fixtures
from tools.v9 import control_partition_transport as T, control_partition_objects as B


class StreamingParity(unittest.TestCase):
    def test_full_mixed_sparse_records_and_all_independent_audits_match(self):
        merge=Parity.M.merge;peaks=[]
        def streamed(source,out,plan,units,context,input_hash,**kwargs):
            with tempfile.TemporaryDirectory(dir=Path(out).parent) as temporary:
                root=Path(temporary);(root/'objects').mkdir();store=B.LocalObjects(root/'objects')
                bundles={u['unit_id']:B.pack(p,store) for u,p in zip(plan['units'],units)}
                active=[]
                @contextmanager
                def load(unit,path):
                    scratch=root/'scratch';self.assertFalse(scratch.exists())
                    B.restore(bundles[unit['unit_id']],store,scratch);active.append(unit['unit_id'])
                    peaks.append(len(active))
                    try:yield scratch
                    finally:active.pop();shutil.rmtree(scratch)
                result=merge(source,out,plan,units,context,input_hash,load_unit=load,**kwargs)
                self.assertEqual(active,[]);self.assertFalse((root/'scratch').exists())
                return result
        with patch.object(Parity.M,'merge',side_effect=streamed):
            Parity.FullAudit().test_full_and_mixed_cohorts_preserve_every_record_and_independent_audit()
        self.assertTrue(peaks);self.assertEqual(max(peaks),1)


class StreamTransport(unittest.TestCase):
    match=Fixtures.ObjectTransport.match
    def setUp(self):Fixtures.ObjectTransport.setUp(self)

    def units(self):
        for n,job in enumerate(self.ids):
            T.run_one(self.remote,self.root/f'w{n}',self.source,job,lambda:(self.context,self),objects=self.store)

    def test_merge_publication_and_recovery_have_one_restored_input_at_a_time(self):
        self.units();restore=B.restore;seen=[]
        def checked(bundle,store,destination):
            result=restore(bundle,store,destination);p=Path(destination)
            if p.parent.name=='units':
                count=sum(x.is_dir() for x in p.parent.iterdir());seen.append(count)
                self.assertEqual(count,1)
            return result
        with patch.object(B,'restore',side_effect=checked):
            w=self.root/'merge';T.merge_once(self.remote,w,self.source,self.context,objects=self.store)
            self.assertFalse(any((w/'reservation/units').iterdir()))
            recovered=self.root/'recovered';T.verify_retained(self.remote,recovered,self.source,objects=self.store)
            self.assertFalse(any((recovered/'reservation/units').iterdir()))
        self.assertTrue(seen);self.assertEqual(max(seen),1)

    def test_late_object_failure_retains_partial_merge_and_never_retries(self):
        self.units();restore=B.restore;counts={}
        def fail_second_pass(bundle,store,destination):
            name=Path(destination).name
            if Path(destination).parent.name=='units':
                counts[name]=counts.get(name,0)+1
                if name=='00001' and counts[name]==2:raise OSError('lost later input object')
            return restore(bundle,store,destination)
        w=self.root/'merge'
        with patch.object(B,'restore',side_effect=fail_second_pass):
            result=T.merge_once(self.remote,w,self.source,self.context,objects=self.store)
        self.assertEqual(result['status'],'RETAINED_FAILED')
        self.assertFalse(any((w/'reservation/units').iterdir()))
        manifest=T.C.O.load((w/'reservation/merged/manifest.json').read_bytes())
        self.assertEqual(manifest['status'],'FAILED_OR_PARTIAL');self.assertGreater(manifest['processed_signals'],0)
        read=T.checkout(self.remote,self.root/'read')
        self.assertEqual(T.row(read/'reservation',self.source,'__merge__')[1]['state'],'FAILED')
        with patch.object(T.C.M,'merge',side_effect=AssertionError('recomputed')):
            with self.assertRaises(ValueError):T.merge_once(self.remote,self.root/'retry',self.source,self.context,objects=self.store)

    def test_existing_working_output_is_never_deleted_by_stream_loader(self):
        read=T.checkout(self.remote,self.root/'read');root=read/'reservation'
        unit=self.plan['units'][0];out=T.C.output(root,unit['unit_id']);out.mkdir(parents=True)
        (out/'preserved').write_bytes(b'original')
        with self.assertRaisesRegex(ValueError,'preserve'):
            with T.loaded_unit(root,self.store,unit,out):pass
        self.assertEqual((out/'preserved').read_bytes(),b'original')

    def test_missing_bundle_fails_before_merge_output_creation(self):
        self.units();read=T.checkout(self.remote,self.root/'read');root=read/'reservation'
        T.reference(root,self.ids[-1]).unlink()
        out=self.root/'blocked'
        with self.assertRaisesRegex(ValueError,'missing unit bundle'):
            T.C.M.merge(self.source,out,self.plan,[T.C.output(root,i) for i in self.ids],self.context,self.digest,
                        load_unit=T.loader(root,self.store))
        self.assertFalse(out.exists());self.assertFalse(any((root/'units').iterdir()))
