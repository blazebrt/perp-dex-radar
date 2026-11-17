"""Independent synthetic unit transport verification, not execution/price verification."""
import gzip
import hashlib
import json
import math
from pathlib import Path
from tools.v9 import verify_control_outcomes as O, verify_control_storage as S


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def verify(source,plan,directories,input_hash,expected_implementation,expected_protocol):
    source=Path(source)
    O.require(O.sha(source/'manifest.json')==input_hash,'input manifest mismatch')
    manifest=O.load((source/'manifest.json').read_bytes())
    O.require(manifest.get('provenance',{}).get('synthetic') is True,'synthetic source required')
    expected=[]
    for trial in manifest['trials']:
        offset=0
        for i,shard in enumerate(trial['shards']):
            expected.append(dict(unit_id=f"{trial['trial_id']}:{i:05d}",trial_id=trial['trial_id'],source=shard,
                                 retained_row_start=offset,retained_row_end=offset+shard['records']))
            offset+=shard['records']
        O.require(offset==trial.get('retained_records',0),'original trial count mismatch')
    O.require(canonical(plan['units'])==canonical(expected) and plan['signals']==sum(u['source']['records'] for u in expected)
              and plan['trial_count']==len(manifest['trials']) and plan['unit_count']==len(expected),'plan conservation mismatch')
    inventory=[dict(trial_id=t['trial_id'],status=t['status'],retained_records=t.get('retained_records',0),units=len(t['shards'])) for t in manifest['trials']]
    O.require(canonical(plan['trials'])==canonical(inventory) and plan.get('input_manifest_sha256')==input_hash
              and all(plan.get(k) is False for k in ('source_shards_reverified','resource_qualified','execution_authorized','promotion_authority')), 'invalid plan inventory/authority')
    O.require(len(directories)==len(expected),'missing or extra units')
    roots=[Path(p).resolve() for p in directories]
    O.require(len(set(roots))==len(roots),'duplicate unit directory')
    receipts=[]
    for unit,root in zip(expected,roots):
        receipt=O.load(O.safe(root,'receipt.json').read_bytes())
        O.require(receipt.get('schema')=='v9.a6-synthetic-unit/1' and receipt.get('status')=='COMPLETED_SYNTHETIC_UNIT'
                  and receipt.get('synthetic_only') is True,'incomplete unit')
        O.require(receipt.get('input_manifest_sha256')==input_hash
                  and receipt.get('plan_sha256')==hashlib.sha256(canonical(plan)).hexdigest()
                  and canonical(receipt.get('unit'))==canonical(unit) and receipt.get('unit_id')==unit['unit_id'],'unit binding/order mismatch')
        O.require(receipt.get('protocol_sha256')==expected_protocol and receipt.get('implementation_sha256')==expected_implementation
                  and receipt.get('provenance')==manifest['provenance'],'unit implementation/source mismatch')
        O.require(all(receipt.get(k) is False for k in ('resource_qualified','execution_authorized','promotion_authority')),'unit authority invented')
        attempt=O.load(O.safe(root,'attempt.json').read_bytes())
        O.require(attempt.get('status')=='STARTED' and all(attempt.get(k)==receipt.get(k) for k in
                  ('schema','unit_id','input_manifest_sha256','plan_sha256','protocol_sha256','synthetic_only','limits')), 'unit start receipt mismatch')
        limits=receipt.get('limits',{})
        O.require(type(limits.get('output_uncompressed_bytes')) is int and 0<limits['output_uncompressed_bytes']<=256*1024*1024
                  and type(receipt.get('output_uncompressed_bytes')) is int
                  and receipt['output_uncompressed_bytes']<=limits['output_uncompressed_bytes'],'invalid unit output budget')
        O.require(type(limits.get('wall_seconds')) is int and 0<limits['wall_seconds']<=600
                  and type(receipt.get('elapsed_seconds')) in (int,float) and math.isfinite(receipt['elapsed_seconds'])
                  and 0<=receipt['elapsed_seconds']<limits['wall_seconds'],'unit elapsed budget mismatch')
        O.require(type(receipt.get('processed_signals')) is int,'invalid processed count')
        refs=receipt.get('files');O.require(isinstance(refs,list),'invalid output inventory')
        names=[r['path'] for r in refs]
        O.require(names==[unit['trial_id']+f'-{i:05d}.jsonl.gz' for i in range(len(refs))],'unit output sequence')
        O.require({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}==set(names)|{'attempt.json','receipt.json'},'unlisted unit file')
        signals=O.safe(source,unit['source']['path'])
        O.require(O.sha(signals)==unit['source']['sha256'],'source shard mismatch')
        count=expanded=0
        with gzip.open(signals,'rb') as inputs:
            for ref in refs:
                path=O.safe(root,ref['path'])
                O.require(path.stat().st_size==ref['bytes'] and O.sha(path)==ref['sha256'],'unit hash mismatch')
                local_count=local_size=0
                with gzip.open(path,'rb') as stream:
                    while True:
                        line=stream.readline(16*1024*1024+1)
                        if not line:break
                        local_size+=len(line);local_count+=1
                        O.require(local_size<=16*1024*1024 and local_count<=25000 and line.endswith(b'\n'),'unit shard bounds')
                        original=inputs.readline(16*1024*1024+1)
                        O.require(original and len(original)<=16*1024*1024 and original.endswith(b'\n'),'extra unit record')
                        signal=O.load(original);pair=S.unpack(O.load(line))
                        O.require(pair['trial_id']==signal['trial_id']==unit['trial_id'] and pair['signal_id']==signal['signal_id']
                                  and pair['source_ordinal']==signal['source_ordinal'],'unit signal order/identity mismatch')
                O.require(local_count==ref['records'] and local_size==ref['uncompressed_bytes'],'unit shard accounting')
                count+=local_count;expanded+=local_size
            O.require(not inputs.read(1),'missing unit record')
        O.require(count==unit['source']['records']==receipt['processed_signals'] and expanded==receipt['output_uncompressed_bytes'],'unit count mismatch')
        receipts.append(dict(root=root,receipt=receipt,receipt_sha256=O.sha(root/'receipt.json')))
    return receipts


def pairs(verified):
    for item in verified:
        root,receipt=item['root'],item['receipt']
        O.require(O.sha(root/'receipt.json')==item['receipt_sha256'],'unit receipt changed after verification')
        for ref in receipt['files']:
            path=O.safe(root,ref['path']);O.require(O.sha(path)==ref['sha256'],'unit changed after verification')
            with gzip.open(path,'rb') as stream:
                for line in stream:yield S.unpack(O.load(line))
