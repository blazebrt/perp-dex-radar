"""Integrate independent A6 outcome audits against pinned source data."""
import argparse
from collections import OrderedDict
import csv
import gzip
import io
import itertools
import json
from pathlib import Path
import sys
import sqlite3
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9 import audit_control_extraction as B
from tools.v9 import verify_control_outcomes as O, verify_control_selection as C
from tools.v9 import verify_control_prices as P, verify_control_statistics as S

INPUT_COMMIT='eb785a908dce572958336649291b8feeb4ee9575'
INPUT_HASH='ea45d68a337ab682406748f2b94c833a5ca00b8e495aa7bdd38fe9b1f5d02a5e'
EXTRACTION_SOURCE='269cb2b0360310ac6bac9fd5ef8b102505c6d997'
IMPLEMENTATIONS=('control_outcomes.py','control_adapter.py','control_pairs.py','control_execution.py','control_summary.py')


class Prices:
    """Independently index bound sources, retaining at most eight price windows."""
    def __init__(self,md,sources):
        self.md,self.sources,self.cache=Path(md),sources,OrderedDict()
        self.loaded=set()
        self.temporary=tempfile.TemporaryDirectory(prefix='a6-audit-prices-')
        self.db=sqlite3.connect(Path(self.temporary.name)/'audit.sqlite')
        self.db.execute('PRAGMA cache_size=-8192')
        self.db.execute('CREATE TABLE candles(asset TEXT,t INTEGER,o REAL,h REAL,l REAL,c REAL,qv REAL,PRIMARY KEY(asset,t)) WITHOUT ROWID')

    def close(self):
        if getattr(self,'db',None) is not None:
            self.db.close();self.db=None
        if getattr(self,'temporary',None) is not None:
            self.temporary.cleanup();self.temporary=None
        if hasattr(self,'cache'):self.cache.clear()

    def __del__(self):self.close()

    def get(self,asset,start,end):
        O.require(self.db is not None,'audit price index is closed')
        source=self.sources[asset]
        if asset not in self.loaded:
            raw=B.bound((self.md/'h4'/(asset+'.csv.gz')).read_bytes(),source.sha)
            reader=csv.DictReader(io.StringIO(gzip.decompress(raw).decode('utf8')))
            O.require(reader.fieldnames is not None and {'t','o','h','l','c','qv'}<=set(reader.fieldnames),'missing price fields')
            rows={}
            for row in reader:
                t=int(row['t']);O.require(t not in rows,'duplicate candle')
                values={}
                for key in ('o','h','l','c','qv'):
                    try:values[key]=float(row[key])
                    except (TypeError,ValueError):values[key]=None
                rows[t]=values
            O.require(list(rows)==source.times and all(rows[t]['qv']==v for t,v in source.rows.items()),'price/source mismatch')
            with self.db:
                self.db.executemany('INSERT INTO candles VALUES(?,?,?,?,?,?,?)',
                    ((asset,t,row['o'],row['h'],row['l'],row['c'],row['qv']) for t,row in rows.items()))
            self.loaded.add(asset)
        key=(asset,start,end)
        if key not in self.cache:
            self.cache[key]={t:dict(o=o,h=h,l=l,c=c,qv=v) for t,o,h,l,c,v in self.db.execute(
                'SELECT t,o,h,l,c,qv FROM candles WHERE asset=? AND t>=? AND t<? ORDER BY t',(asset,start,end))}
            if len(self.cache)>8:self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key]


def prepare(md,evidence,source_commit):
    context=B.prepare(md,evidence,EXTRACTION_SOURCE)
    bindings=dict(input_commit=INPUT_COMMIT,provenance=context['provenance'],
        implementation_sha256={name:B.A.digest(B.git_bytes(source_commit,'tools/v9/'+name)) for name in IMPLEMENTATIONS},
        protocol_sha256=B.A.digest(B.git_bytes(source_commit,'docs/v9/phase-a6-execution-inference.md')))
    return context,Prices(md,context['sources']),bindings


def audit(directory,signals,context,prices,bindings,scratch,input_hash=INPUT_HASH):
    root,source=Path(directory),Path(signals)
    accounting=O.verify(root,source,input_hash,bindings)
    original=O.load((source/'manifest.json').read_bytes());manifest=O.load((root/'manifest.json').read_bytes())
    O.require([t['definition'] for t in original['trials']]==context['plan']['trials'] and
              original['window']==[context['start'],context['end']],'source roster/window mismatch')
    verified=dict(signals=0,candidate_paths=0,control_paths=0)
    cache_key=None;population=None

    def pairs():
        nonlocal cache_key,population
        for trial in original['trials']:
            tid=trial['trial_id']
            names=sorted(r['path'] for r in manifest['files'] if r['path'].startswith(tid+'-') and r['path'].endswith('.jsonl.gz'))
            for signal,pair in itertools.zip_longest(O.records(source,[r['path'] for r in trial['shards']]),O.records(root,names)):
                O.require(signal is not None and pair is not None,'outcome population changed')
                i,j=signal['panel_i'],signal['panel_j'];d=signal['direction'];t=signal['decision_time'];asset=signal['asset']
                O.require(type(i) is int and type(j) is int and 0<=i<len(context['times']) and 0<=j<len(context['assets']),
                          'invalid signal indices')
                O.require(t==int(context['times'][i])+14400 and asset==context['assets'][j],'signal panel mismatch')
                eligible=bool(context['eligibility'][i][j]);src=context['sources'][asset]
                feature,history=src.reconstruct(t,d,eligible)
                O.require(signal['features']==feature and signal['history']==history and signal['source_sha256']==src.sha
                          and signal['original_eligible'] is eligible,'signal/source mismatch')
                if cache_key!=(i,d):
                    population=[context['sources'][a].reconstruct(t,d,bool(context['eligibility'][i][k]))[0]
                                for k,a in enumerate(context['assets'])]
                    cache_key=(i,d)
                C.verify(tid,feature,population,pair['cohort'])
                hold=signal['geometry']['hold']
                O.require(type(hold) is int and hold>0,'invalid audit hold')
                window_end=min(context['end'],t+hold*14400)
                P.verify(prices.get(asset,t,window_end),t,d,signal['geometry'],eligible,src.disputes,
                         min(context['end'],src.times[-1]+14400),pair['candidate'])
                verified['candidate_paths']+=1
                for control in pair['controls']:
                    a=control['asset'];other=context['sources'][a]
                    P.verify(prices.get(a,t,window_end),t,d,signal['geometry'],True,other.disputes,
                             min(context['end'],other.times[-1]+14400),control['outcome'])
                    verified['control_paths']+=1
                verified['signals']+=1
                yield pair
    statistics=S.verify(pairs(),context['plan']['trials'],O.load((root/'sides.json').read_bytes()),
        O.records(root,['days/'+r['path'] for r in manifest['day_shards']]),
        O.records(root,['reuse/'+r['path'] for r in manifest['reuse_shards']]),scratch)
    O.require(verified['signals']==accounting['signals']==statistics['signals'],'audit count mismatch')
    return dict(status='VERIFIED_REGISTERED_PRICE_DIAGNOSTICS',input_manifest_sha256=input_hash,
        outcome_manifest_sha256=O.sha(root/'manifest.json'),bindings=bindings,accounting=accounting,statistics=statistics,
        **verified,source_bound_selection_verified=True,source_bound_price_paths_verified=True,
        original_generator_mathematics_verified=False,net_inference_available=False,
        full_matched_authority=False,promotion_authority=False)


def run(directory,signals,out,prepare_context,input_hash=INPUT_HASH):
    out=Path(out).resolve()
    O.require(not out.exists(),'preserve previous outcome audit')
    for path in (directory,signals):
        other=Path(path).resolve()
        O.require(out!=other and out not in other.parents and other not in out.parents,'audit output overlaps input')
    out.mkdir(parents=True)
    prices=None
    try:
        context,prices,bindings=prepare_context()
        with tempfile.TemporaryDirectory(dir=out) as temporary:
            result=audit(directory,signals,context,prices,bindings,Path(temporary)/'statistics.sqlite',input_hash)
        result['verifier_sha256']={p.name:O.sha(p) for p in (Path(__file__),Path(B.__file__),Path(B.A.__file__),
            Path(B.P.__file__),Path(O.__file__),Path(C.__file__),Path(P.__file__),Path(S.__file__))}
        name='audit.json'
    except Exception as error:
        result=dict(status='FAILED',error=dict(type=type(error).__name__,message=str(error)),promotion_authority=False)
        name='failure.json'
    finally:
        if prices is not None:prices.close()
    with (out/name).open('x',encoding='utf8',newline='\n') as stream:
        stream.write(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('directory','signals','out','md','evidence','source-commit'):ap.add_argument('--'+name,required=True)
    args=ap.parse_args()
    result=run(args.directory,args.signals,args.out,lambda:prepare(args.md,args.evidence,args.source_commit))
    if result['status']=='FAILED':raise SystemExit(1)
