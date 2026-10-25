"""Bounded synthetic A6 pipeline measurements; never qualifies a market run."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9 import control_extract as X, control_signals as S, control_adapter as A
from tools.v9 import control_outcomes as O, audit_control_outcomes as V, verify_control_population as P


def footprint(root):
    return {p.relative_to(root).as_posix():p.stat().st_size for p in sorted(root.rglob('*')) if p.is_file()}


def scenario(kind,signals=8,bars=1000,retain=None):
    if kind not in ('full','mixed','sparse','interrupted'):raise ValueError('unknown scenario')
    if type(signals) is not int or not 3<=signals<=100:raise ValueError('signals must be 3..100')
    if type(bars) is not int or not 400<=bars<=4000:raise ValueError('bars must be 400..4000')
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);(root/'h4').mkdir();started=time.perf_counter()
        assets=['SYNTH%03d'%i for i in range(8 if kind=='sparse' else 61)]
        times=list(range(0,bars*14400,14400));segments={};sources={}
        for j,asset in enumerate(assets):
            calendar=[];volumes=[];lines=['t,o,h,l,c,qv'];disputes=[]
            for i,t in enumerate(times):
                if kind=='mixed' and i==183 and j%5==1:continue
                price=100+j*.25+(i%11)*.03;volume=2e6
                close=str(price+.02)
                if kind=='mixed' and i==183:
                    if j%5==2:volume=0
                    if j%5==3:close='bad'
                    if j%5==4:disputes.append(t)
                lines.append(f'{t},{price},{price+1},{price-1},{close},{volume}')
                calendar.append(t);volumes.append(volume)
            raw=gzip.compress(('\n'.join(lines)+'\n').encode(),mtime=0)
            (root/'h4'/(asset+'.csv.gz')).write_bytes(raw)
            meta=dict(asset=asset,source_symbol=asset+'USDT',first_bar=0)
            digest=hashlib.sha256(raw).hexdigest()
            view=S.SegmentView(dict(segment=meta,times=calendar,volumes=volumes,disputed_opens=disputes,source_sha256=digest))
            segments[asset]=view;sources[asset]=P.Source(meta,calendar,volumes,disputes,digest)
        eligibility=[[True]*len(assets) for _ in times]
        if kind=='mixed':eligibility[181][0]=False
        trials=[dict(trial_id=str(i)*64,archive_requirement='hourly' if i==2 else '4h') for i in range(3)]
        indices=list(range(180,180+signals-1))+[bars-1]
        generated=dict(i=indices,j=[0]*signals,d=[1 if i%2==0 else -1 for i in range(signals)],
            stop=[.02]*signals,target=[2.]*signals,trail=[.01]*signals,be=[1.]*signals,
            hold=[6 if i%2==0 else 36 for i in range(signals)])
        context=dict(trials=trials,times=times,assets=assets,eligibility=eligibility,segments=segments,
            start=30*86400,end=times[-1]+14400,provenance={'synthetic':True},generate=lambda trial:generated)
        extraction=X.extract(root/'signals',lambda:context)
        if any(t['status']=='FAILED' for t in extraction['trials']):raise ValueError('synthetic extraction failed')
        preparation_seconds=time.perf_counter()-started
        digest=X.sha(root/'signals/manifest.json')
        class Adapter(A.Adapter):
            calls=0
            def match(self,signal):
                if kind=='interrupted' and self.calls==3:raise RuntimeError('synthetic interruption')
                self.calls+=1
                return super().match(signal)
        started=time.perf_counter()
        result=O.run(root/'signals',root/'outcomes',lambda:(context,Adapter(root,context)),digest,max_rows=4)
        outcome_seconds=time.perf_counter()-started
        independent=dict(plan=dict(trials=trials),times=times,assets=assets,eligibility=eligibility,
                         start=context['start'],end=context['end'],sources=sources)
        bindings={k:result[k] for k in ('input_commit','provenance','implementation_sha256','protocol_sha256')}
        started=time.perf_counter()
        audit=V.run(root/'outcomes',root/'signals',root/'audit',
            lambda:(independent,V.Prices(root,sources),bindings),digest)
        audit_seconds=time.perf_counter()-started
        expected='FAILED' if kind=='interrupted' else 'VERIFIED_REGISTERED_PRICE_DIAGNOSTICS'
        if audit['status']!=expected:raise ValueError('unexpected audit: '+json.dumps(audit))
        files=footprint(root/'outcomes');audit_files=footprint(root/'audit')
        side_counts=[] if kind=='interrupted' else json.loads((root/'outcomes/sides.json').read_text())
        return dict(publication=retain(root) if retain is not None else None,scenario=kind,assets=len(assets),bars_per_asset=bars,signals_per_available_trial=signals,
            preparation_seconds=preparation_seconds,outcome_seconds=outcome_seconds,audit_seconds=audit_seconds,
            processed_signals=result['processed_signals'],outcome_status=result['status'],audit_status=audit['status'],
            candidate_paths=audit.get('candidate_paths'),control_paths=audit.get('control_paths'),
            statistics=audit.get('statistics'),dispositions=[s['counts'] for s in side_counts],
            outcome_bytes=sum(files.values()),summary_database_bytes=files.get('summary.sqlite',0),
            pair_bytes=sum(v for k,v in files.items() if '/' not in k and k.endswith('.jsonl.gz')),
            reuse_bytes=sum(v for k,v in files.items() if k.startswith('reuse/')),
            day_bytes=sum(v for k,v in files.items() if k.startswith('days/')),
            largest_retained_file_bytes=max(files.values()),outcome_files=len(files),audit_files=audit_files,
            source_bytes=sum(footprint(root/'h4').values()),input_bytes=sum(footprint(root/'signals').values()),
            failure_retained=(root/'audit/failure.json').exists(),net_inference_available=False,promotion_authority=False)


def probe(signals=8,bars=1000):
    cases=[scenario(k,signals,bars) for k in ('full','mixed','sparse','interrupted')]
    modules=(Path(__file__),Path(X.__file__),Path(S.__file__),Path(A.__file__),Path(A.P.__file__),Path(A.E.__file__),
             Path(O.__file__),Path(O.S.__file__),Path(O.W.__file__),Path(V.__file__),Path(V.O.__file__),
             Path(V.O.T.__file__),Path(V.C.__file__),Path(V.P.__file__),Path(V.S.__file__),Path(P.__file__))
    return dict(schema='v9.a6-synthetic-pipeline-probe/1',status='NOT_RESOURCE_QUALIFIED',synthetic_only=True,
        market_data_loaded=False,cases=cases,source_sha256={p.name:X.sha(p) for p in modules},
        measured_scope='SYNTHETIC_PREPARATION_EXTRACTION_OUTCOMES_SUMMARIES_AND_ALL_OUTCOME_AUDITS',
        exclusions=['REAL_ARCHIVE_PREPARATION','PEAK_MEMORY','PEAK_SCRATCH_DISK','GIT_PUBLICATION','HOSTED_RUNNER_QUALIFICATION'],
        size_measurement='RETAINED_BYTES_NOT_PEAK_DISK',promotion_authority=False)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',required=True)
    ap.add_argument('--signals',type=int,default=8);ap.add_argument('--bars',type=int,default=1000)
    args=ap.parse_args();path=Path(args.out)
    if path.exists():raise FileExistsError('preserve previous pipeline probe')
    result=probe(args.signals,args.bars)
    with path.open('x',encoding='utf8',newline='\n') as stream:stream.write(json.dumps(result,sort_keys=True,indent=2)+'\n')
