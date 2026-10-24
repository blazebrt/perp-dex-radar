"""Stream the registered A6 outcomes; no retry, promotion or inference authority."""
import argparse
import gzip
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9 import control_extract as X, control_adapter as A, control_summary as S
from tools.v9 import verify_control_artifacts as V

INPUT_COMMIT='eb785a908dce572958336649291b8feeb4ee9575'
INPUT_MANIFEST='ea45d68a337ab682406748f2b94c833a5ca00b8e495aa7bdd38fe9b1f5d02a5e'


def run(directory,out,prepare,expected_manifest=INPUT_MANIFEST,max_rows=25000):
    """Injected preparation is for synthetic checks; CLI uses bound preparation.

    No generator is called: only the immutable A6.2 signal rows are executed.
    Independent outcome verification and durable reservation remain caller gates.
    """
    source,out=Path(directory).resolve(),Path(out).resolve()
    V.check(source!=out and source not in out.parents and out not in source.parents,
            'input and output directories must be separate')
    V.check(not out.exists(),'preserve earlier outcome attempt')
    out.mkdir(parents=True)
    result=dict(schema='v9.a6-outcomes/1',status='STARTED',input_commit=INPUT_COMMIT,
                input_manifest_sha256=expected_manifest,completed_trials=[],processed_signals=0,
                full_matched_authority=False,promotion_authority=False,independently_verified=False)
    X.write_json(out/'attempt.json',result)
    summary=None;adapter=None
    try:
        V.check(X.sha(source/'manifest.json')==expected_manifest,'unregistered signal inventory')
        context,adapter=prepare()
        manifest=V.load((source/'manifest.json').read_bytes())
        verification=V.verify(source,dict(trials=context['trials']),context['provenance'])
        V.check(verification['failed']==0 and manifest['window']==[context['start'],context['end']],
                'incomplete or changed input population')
        result['input_verification']=verification
        result['provenance']=context['provenance']
        result['implementation_sha256']={p.name:X.sha(p) for p in
            (Path(__file__),Path(A.__file__),Path(A.P.__file__),Path(A.E.__file__),Path(S.__file__))}
        result['protocol_sha256']=X.sha(ROOT/'docs/v9/phase-a6-execution-inference.md')
        summary=S.Summary(out/'summary.sqlite',context['trials'])
        for trial in manifest['trials']:
            sink=X.Shards(out,trial['trial_id'],max_rows=max_rows)
            count=0
            try:
                for shard in trial['shards']:
                    path=source/shard['path']
                    V.check(X.sha(path)==shard['sha256'],'input changed after preflight')
                    with gzip.open(path,'rb') as stream:
                        for line in stream:
                            signal=V.load(line)
                            pair=adapter.match(signal)
                            summary.add(pair)
                            sink.emit(pair)
                            count+=1
                            result['processed_signals']+=1
                if trial['status']=='EXTRACTED':
                    V.check(count==trial['retained_records'],'outcome population mismatch')
                result['completed_trials'].append(dict(trial_id=trial['trial_id'],signals=count,
                    status='UNAVAILABLE_HOURLY_POPULATION' if trial['status']=='UNAVAILABLE_HOURLY_POPULATION' else 'PROCESSED'))
            finally:sink.close()
        (out/'days').mkdir();(out/'reuse').mkdir()
        days=X.Shards(out/'days','d'*64,max_rows=max_rows)
        reuse=X.Shards(out/'reuse','e'*64,max_rows=max_rows)
        try: sides=summary.finish(days.emit,reuse.emit)
        finally:
            days.close();reuse.close()
        X.write_json(out/'sides.json',sides)
        result.update(status='COMPLETED_PRICE_DIAGNOSTICS_NET_UNAVAILABLE',day_shards=days.files,reuse_shards=reuse.files)
    except Exception as error:
        result.update(status='FAILED_OR_PARTIAL',error=dict(type=type(error).__name__,message=str(error)))
    finally:
        if summary is not None:summary.close()
        if adapter is not None and callable(getattr(adapter,'close',None)):adapter.close()
    result['files']=[dict(path=p.relative_to(out).as_posix(),sha256=X.sha(p),bytes=p.stat().st_size)
                     for p in sorted(out.rglob('*')) if p.is_file() and p.name not in ('attempt.json','manifest.json')]
    X.write_json(out/'manifest.json',result)
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--md',required=True);ap.add_argument('--phase-b-evidence',required=True)
    ap.add_argument('--signals',required=True);ap.add_argument('--out',required=True)
    args=ap.parse_args()
    def prepare():
        context=X.prepare(args.md,args.phase_b_evidence)
        return context,A.Adapter(args.md,context)
    result=run(args.signals,args.out,prepare)
    if result['status']=='FAILED_OR_PARTIAL':raise SystemExit(1)
