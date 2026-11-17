"""Exclusive synthetic partition workers; no CLI or registered-market activation."""
import gzip
import hashlib
import json
from pathlib import Path
import time
from tools.v9 import control_partition_plan as P, control_extract as X
from tools.v9 import verify_control_artifacts as V, control_adapter as A, control_storage as W


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def run_unit(source,out,plan,unit_id,prepare,input_hash,*,max_output_bytes=64*1024*1024,max_seconds=300):
    source,out=Path(source).resolve(),Path(out).resolve()
    V.check(input_hash!=P.INPUT_SHA,'registered market execution remains disabled')
    V.check(type(max_output_bytes) is int and 0<max_output_bytes<=256*1024*1024
            and type(max_seconds) is int and 0<max_seconds<=600,'invalid prototype budget')
    V.check(source!=out and source not in out.parents and out not in source.parents,'overlapping unit output')
    V.check(not out.exists(),'preserve existing unit attempt')
    out.mkdir(parents=True)
    receipt=dict(schema='v9.a6-synthetic-unit/1',status='STARTED',unit_id=unit_id,
                 input_manifest_sha256=input_hash,plan_sha256=hashlib.sha256(canonical(plan)).hexdigest(),
                 protocol_sha256=X.sha(Path(__file__).resolve().parents[2]/'docs/v9/phase-a6-execution-inference.md'),
                 processed_signals=0,output_uncompressed_bytes=0,synthetic_only=True,
                 resource_qualified=False,execution_authorized=False,promotion_authority=False,
                 limits=dict(output_uncompressed_bytes=max_output_bytes,wall_seconds=max_seconds))
    X.write_json(out/'attempt.json',receipt)
    adapter=None;sink=None;started=time.monotonic()
    try:
        V.check(canonical(P.build((source/'manifest.json').read_bytes(),input_hash))==canonical(plan),'partition plan mismatch')
        matches=[u for u in plan['units'] if u['unit_id']==unit_id]
        V.check(len(matches)==1,'unknown or ambiguous unit')
        unit=matches[0];receipt['unit']=unit
        context,adapter=prepare()
        V.check(context.get('provenance',{}).get('synthetic') is True,'synthetic preparation required')
        verified=V.verify(source,dict(trials=context['trials']),context['provenance'])
        manifest=V.load((source/'manifest.json').read_bytes())
        V.check(verified['failed']==0 and manifest['window']==[context['start'],context['end']],'invalid source preparation')
        receipt['provenance']=context['provenance']
        receipt['implementation_sha256']={p.name:X.sha(p) for p in
            (Path(__file__),Path(P.__file__),Path(A.__file__),Path(A.P.__file__),Path(A.E.__file__),Path(W.__file__))}
        ref=unit['source'];path=source/ref['path']
        V.check(X.sha(path)==ref['sha256'],'source changed after preflight')
        sink=X.Shards(out,unit['trial_id'])
        with gzip.open(path,'rb') as stream:
            for line in stream:
                V.check(time.monotonic()-started<max_seconds,'unit deadline exceeded')
                pair=adapter.match(V.load(line));packed=W.pack(pair)
                size=len(canonical(packed))+1
                V.check(receipt['output_uncompressed_bytes']+size<=max_output_bytes,'unit output budget exceeded')
                V.check(time.monotonic()-started<max_seconds,'unit deadline exceeded')
                sink.emit(packed)
                receipt['processed_signals']+=1;receipt['output_uncompressed_bytes']+=size
        V.check(receipt['processed_signals']==ref['records'],'unit accounting mismatch')
        sink.close()
        V.check(time.monotonic()-started<max_seconds,'unit deadline exceeded')
        receipt['status']='COMPLETED_SYNTHETIC_UNIT'
    except Exception as error:
        receipt.update(status='FAILED_OR_PARTIAL',error_type=type(error).__name__)
    finally:
        if sink is not None:sink.close()
        if adapter is not None and callable(getattr(adapter,'close',None)):adapter.close()
    receipt['files']=[] if sink is None else sink.files
    receipt['elapsed_seconds']=time.monotonic()-started
    if receipt['elapsed_seconds']>=max_seconds and receipt['status']=='COMPLETED_SYNTHETIC_UNIT':
        receipt.update(status='FAILED_OR_PARTIAL',error_type='DeadlineExceeded')
    # Exclusive creation prevents overwriting a prior terminal receipt.
    with (out/'receipt.json').open('xb') as stream:stream.write(canonical(receipt)+b'\n')
    return receipt
