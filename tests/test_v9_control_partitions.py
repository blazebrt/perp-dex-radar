import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests import test_v9_control_outcomes as F
from tools.v9 import control_extract as X, control_outcomes as O, control_partition_plan as P
from tools.v9 import control_partition_execute as E, control_partition_merge as M
from tools.v9 import verify_control_outcomes as V, control_pipeline_probe as Pipeline


class Partitions(unittest.TestCase):
    match=F.Outcomes.match
    run_study=F.Outcomes.run_study
    # Reuse only the fixture setup/matcher, not inherited test methods.
    def setUp(self):
        F.Outcomes.setUp(self)
        import shutil
        shutil.rmtree(self.source)
        X.extract(self.source,lambda:self.context,max_rows=2)
        self.digest=X.sha(self.source/'manifest.json')
        self.plan=P.build((self.source/'manifest.json').read_bytes(),self.digest)
        self.units=[]

    def workers(self):
        for i,u in enumerate(self.plan['units']):
            path=self.root/f'unit-{i}'
            r=E.run_unit(self.source,path,self.plan,u['unit_id'],lambda:(self.context,self),self.digest)
            self.assertEqual(r['status'],'COMPLETED_SYNTHETIC_UNIT')
            self.units.append(path)

    def test_partitioned_records_and_global_summaries_equal_monolithic(self):
        baseline=self.run_study();self.workers()
        merged=self.root/'merged';result=M.merge(self.source,merged,self.plan,self.units,self.context,self.digest,max_rows=2)
        self.assertEqual(result['status'],baseline['status'])
        for key in ('completed_trials','processed_signals','day_shards','reuse_shards'):
            self.assertEqual(result[key],baseline[key])
        def pairs(root,doc):
            return list(V.pair_records(root,sorted(p.name for p in root.glob('*.jsonl.gz')),doc))
        self.assertEqual(E.canonical(pairs(merged,result)),E.canonical(pairs(self.out,baseline)))
        self.assertEqual((merged/'sides.json').read_bytes(),(self.out/'sides.json').read_bytes())
        bindings={k:result[k] for k in ('input_commit','provenance','implementation_sha256','protocol_sha256')}
        self.assertEqual(V.verify(merged,self.source,self.digest,bindings)['signals'],8)

    def test_incomplete_duplicate_reordered_and_corrupt_units_rejected(self):
        self.workers()
        cases=[self.units[:-1],self.units+[self.units[0]],list(reversed(self.units)),[self.units[0]]*len(self.units)]
        for units in cases:
            with self.assertRaises(ValueError):M.merge(self.source,self.root/'rejected',self.plan,units,self.context,self.digest)
            self.assertFalse((self.root/'rejected').exists())
        p=next(self.units[0].glob('*.gz'));p.write_bytes(b'broken')
        with self.assertRaises(ValueError):M.merge(self.source,self.root/'rejected',self.plan,self.units,self.context,self.digest)

    def test_failure_budget_and_exclusive_attempt(self):
        unit=self.plan['units'][0];path=self.root/'failed'
        original=self.match
        def fail(signal):
            if self.calls==1:raise RuntimeError('injected')
            return original(signal)
        self.match=fail
        receipt=E.run_unit(self.source,path,self.plan,unit['unit_id'],lambda:(self.context,self),self.digest)
        self.assertEqual(receipt['status'],'FAILED_OR_PARTIAL');self.assertEqual(receipt['processed_signals'],1)
        self.assertTrue(receipt['files']);before=(path/'receipt.json').read_bytes()
        with self.assertRaises(ValueError):E.run_unit(self.source,path,self.plan,unit['unit_id'],lambda:None,self.digest)
        self.assertEqual(before,(path/'receipt.json').read_bytes())
        self.match=original
        receipt=E.run_unit(self.source,self.root/'budget',self.plan,unit['unit_id'],lambda:(self.context,self),self.digest,max_output_bytes=1)
        self.assertEqual(receipt['status'],'FAILED_OR_PARTIAL');self.assertEqual(receipt['processed_signals'],0)

    def test_rehashed_wrong_signal_and_failed_receipt_rejected(self):
        self.workers();root=self.units[0];receipt=json.loads((root/'receipt.json').read_bytes())
        path=root/receipt['files'][0]['path']
        rows=[json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()]
        pair=V.T.unpack(rows[0]);pair['signal_id']='f'*64;rows[0]=E.W.pack(pair)
        raw=b''.join(E.canonical(row)+b'\n' for row in rows);path.write_bytes(gzip.compress(raw,mtime=0))
        receipt['files'][0].update(sha256=X.sha(path),bytes=path.stat().st_size,uncompressed_bytes=len(raw))
        receipt['output_uncompressed_bytes']=sum(x['uncompressed_bytes'] for x in receipt['files'])
        (root/'receipt.json').write_bytes(E.canonical(receipt))
        with self.assertRaisesRegex(ValueError,'identity'):M.merge(self.source,self.root/'bad-id',self.plan,self.units,self.context,self.digest)
        receipt['status']='FAILED_OR_PARTIAL';(root/'receipt.json').write_bytes(E.canonical(receipt))
        with self.assertRaisesRegex(ValueError,'incomplete unit'):M.merge(self.source,self.root/'bad-status',self.plan,self.units,self.context,self.digest)

    def test_cooperative_deadline_and_merged_output_are_exclusive(self):
        unit=self.plan['units'][0]
        with patch.object(E.time,'monotonic',side_effect=[0,2,3]):
            receipt=E.run_unit(self.source,self.root/'timeout',self.plan,unit['unit_id'],lambda:(self.context,self),self.digest,max_seconds=1)
        self.assertEqual(receipt['status'],'FAILED_OR_PARTIAL');self.assertEqual(receipt['processed_signals'],0)
        self.workers();out=self.root/'merged'
        M.merge(self.source,out,self.plan,self.units,self.context,self.digest)
        before=(out/'manifest.json').read_bytes()
        with self.assertRaises(ValueError):M.merge(self.source,out,self.plan,self.units,self.context,self.digest)
        self.assertEqual(before,(out/'manifest.json').read_bytes())

    def test_registered_input_and_bad_plan_refused_before_matching(self):
        with self.assertRaisesRegex(ValueError,'registered market'):
            E.run_unit(self.source,self.root/'forbidden',self.plan,'x',lambda:None,P.INPUT_SHA)
        with self.assertRaisesRegex(ValueError,'registered market'):
            M.merge(self.source,self.root/'forbidden',self.plan,[],self.context,P.INPUT_SHA)
        changed=copy.deepcopy(self.plan);changed['units'][0]['retained_row_end']+=1
        r=E.run_unit(self.source,self.root/'changed',changed,changed['units'][0]['unit_id'],lambda:None,self.digest)
        self.assertEqual(r['status'],'FAILED_OR_PARTIAL');self.assertEqual(self.calls,0)


class FullAudit(unittest.TestCase):
    def test_full_and_mixed_cohorts_preserve_every_record_and_independent_audit(self):
        original_run=O.run;original_audit=Pipeline.V.run
        for kind in ('full','mixed','sparse'):
            captured={}
            def execute(source,out,prepare,digest,max_rows):
                baseline=original_run(source,out,prepare,digest,max_rows=max_rows)
                context,adapter=prepare();adapter.close()
                plan=P.build((Path(source)/'manifest.json').read_bytes(),digest);units=[]
                for i,unit in enumerate(plan['units']):
                    path=Path(out).parent/f'partition-{i}'
                    result=E.run_unit(source,path,plan,unit['unit_id'],prepare,digest)
                    self.assertEqual(result['status'],'COMPLETED_SYNTHETIC_UNIT');units.append(path)
                merged=Path(out).parent/'merged'
                with patch.object(O,'run',original_run):
                    result=M.merge(source,merged,plan,units,context,digest,max_rows=max_rows)
                self.assertEqual(result['status'],baseline['status'])
                for name in ('sides.json',):self.assertEqual((merged/name).read_bytes(),(Path(out)/name).read_bytes())
                for key in ('completed_trials','processed_signals','day_shards','reuse_shards'):
                    self.assertEqual(result[key],baseline[key])
                def logical(root,doc):return list(V.pair_records(root,sorted(p.name for p in root.glob('*.jsonl.gz')),doc))
                self.assertEqual(E.canonical(logical(merged,result)),E.canonical(logical(Path(out),baseline)))
                captured.update(directory=merged,manifest=result)
                return baseline
            def audit(directory,signals,out,prepare,digest):
                baseline=original_audit(directory,signals,out,prepare,digest)
                def context():
                    c,prices,bindings=prepare()
                    # Trusted local implementation hashes, not the merged manifest's claim.
                    bindings['implementation_sha256'].update({p.name:X.sha(p) for p in
                        (Path(E.__file__),Path(P.__file__),Path(M.__file__),Path(M.V.__file__))})
                    return c,prices,bindings
                result=original_audit(captured['directory'],signals,Path(out).parent/'partition-audit',context,digest)
                self.assertEqual(result['status'],'VERIFIED_REGISTERED_PRICE_DIAGNOSTICS',result)
                self.assertGreater(result['control_paths'],0)
                for key in ('signals','candidate_paths','control_paths','statistics','accounting'):
                    self.assertEqual(result[key],baseline[key])
                if kind=='full':
                    root=captured['directory'];doc=captured['manifest']
                    path=next(root.glob('*.jsonl.gz'))
                    rows=list(V.pair_records(root,[path.name],doc));rows[0]['candidate']['exit_price']=999
                    path.write_bytes(gzip.compress(b''.join(E.canonical(E.W.pack(row))+b'\n' for row in rows)))
                    for ref in doc['files']:
                        if ref['path']==path.name:ref.update(sha256=X.sha(path),bytes=path.stat().st_size)
                    (root/'manifest.json').write_bytes(E.canonical(doc))
                    rejected=original_audit(root,signals,Path(out).parent/'tampered-audit',context,digest)
                    self.assertEqual(rejected['status'],'FAILED')
                return baseline
            with self.subTest(kind=kind),patch.object(Pipeline.O,'run',side_effect=execute),patch.object(Pipeline.V,'run',side_effect=audit):
                Pipeline.scenario(kind,signals=4,bars=400,shard_rows=2,price_profile='diverse')
