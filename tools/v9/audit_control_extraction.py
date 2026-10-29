"""Source-bound independent A6 audit; no matching, execution or outcomes."""
import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9 import verify_control_artifacts as A, verify_control_population as P

ARCHIVE = '4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7'
ORIGINAL = 'ad2374fa4d25f03c204ce7c0cdbecac95cba6246'
PLAN_SHA = '7910cb5678771db32e2ebfe162a916c5cd7ff209987a598f6be6c4f470551af1'
INVENTORY_SHA = 'bcab567507ccee4e26112f39835bdfe5df6c1248f7e40fd049d5cdbfa04d3ea1'
CODE = ('tools/v9/evidence.py','tools/v9/archive_fetch.py','tools/research/qstrat.py',
        'tools/research/qdata.py','tools/research/qind.py','tools/research/qsim.py')
ADAPTERS = ('control_extract.py','control_signals.py','control_sources.py','control_features.py')


def git_bytes(commit, name):
    A.check(isinstance(commit,str) and re.fullmatch('[0-9a-f]{40}',commit), 'full source commit required')
    return subprocess.check_output(['git','-c','safe.directory=*','-C',str(ROOT),'show',commit+':'+name])


def bound(raw, expected):
    A.check(A.digest(raw)==expected,'source bytes mismatch')
    return raw


def read_sources(md, inventory):
    """Read original candles independently of the extraction source loader."""
    md=Path(md)
    A.check(inventory['archive_commit']==ARCHIVE,'wrong archive')
    hashes=inventory['source_files_sha256']
    universe=A.load(bound((md/'universe.json').read_bytes(),hashes['universe.json']))
    rows=universe['coins']
    A.check(len({r['t'] for r in rows})==len(rows),'duplicate universe identity')
    coins={r['t']:r for r in rows if not r['excluded']}
    A.check(all(isinstance(a,str) and a and a not in ('.','..') and
                not any(c in a for c in ('/','\\',':','\x00')) for a in coins),
            'unsafe asset')
    names={'h4/'+a+'.csv.gz' for a in coins}
    A.check(names==set(hashes)-{'universe.json'} and {p.name for p in (md/'h4').iterdir()}=={a+'.csv.gz' for a in coins},
            'broad source roster mismatch')
    sources={}
    for asset,meta in coins.items():
        raw=bound((md/'h4'/(asset+'.csv.gz')).read_bytes(),hashes['h4/'+asset+'.csv.gz'])
        reader=csv.DictReader(io.StringIO(gzip.decompress(raw).decode('utf8')))
        A.check(reader.fieldnames is not None and {'t','qv'}<=set(reader.fieldnames),'source columns missing')
        times=[];volumes=[]
        for row in reader:
            times.append(int(row['t']));volumes.append(float(row['qv']))
        A.check(times and times[0]==meta['first_bar'] and times[-1]==meta['last_bar'] and len(times)==meta['bars'],
                'source bounds/count mismatch')
        disputes=[r['open'] for r in inventory['disputed_blocks'] if r['asset']==asset]
        sources[asset]=P.Source(dict(asset=asset,source_symbol=meta['symbol'],first_bar=meta['first_bar']),
                               times,volumes,disputes,A.digest(raw))
    return sources


def prepare(md, evidence, source_commit):
    hashes={}
    for name in CODE:
        original=git_bytes(ORIGINAL,name)
        bound((ROOT/name).read_bytes(),A.digest(original))
        bound(git_bytes(source_commit,name),A.digest(original))
        hashes[name]=A.digest(original)
    plan=A.load(bound(git_bytes(source_commit,'research/v9/census_replay_plan.json'),PLAN_SHA))
    inventory=A.load(bound(git_bytes(source_commit,'research/v9/a6_source_inventory.json'),INVENTORY_SHA))
    binding=A.load(git_bytes(source_commit,'research/v9/probation_evidence.json'))['inputs']['evidence_sha256']
    reference=A.load(bound(Path(evidence).read_bytes(),binding))
    sources=read_sources(md,inventory)
    # Reuse only the unchanged legacy scientific implementation, never A6 loaders/projection.
    sys.path.insert(0,str(ROOT/'tools/research'))
    from tools.v9 import evidence as EV
    import qstrat
    import numpy as np
    panel=EV.ArchivePanel(str(md))
    features=qstrat.Feat(panel)
    digest=hashlib.sha256()
    for array in (panel.t,panel.o,panel.h,panel.l,panel.c,panel.v,panel.fund):
        digest.update(np.ascontiguousarray(array).tobytes())
    panel_hash=digest.hexdigest()
    A.check(panel_hash==reference['provenance']['dataset_sha256'],'original panel mismatch')
    start,end=int(panel.t[0])+120*86400,int(panel.t[-1])+14400
    A.check([start,end]==[1588204800,1790812800] and set(panel.coins)<=set(sources),'window/assets mismatch')
    provenance=dict(archive_commit=ARCHIVE,source_commit=ORIGINAL,code_sha256=hashes,
        inventory_sha256=INVENTORY_SHA,plan_sha256=PLAN_SHA,phase_b_evidence_sha256=binding,
        panel_sha256=panel_hash,verified_candle_files=len(sources),
        adapter_sha256={name:A.digest(git_bytes(source_commit,'tools/v9/'+name)) for name in ADAPTERS},
        protocol_sha256=A.digest(git_bytes(source_commit,'docs/v9/phase-a6-extraction-driver.md')))
    return dict(plan=plan,provenance=provenance,times=panel.t,assets=panel.coins,eligibility=features.elig,
                sources=sources,start=start,end=end,source_commit=source_commit,
                generate=lambda trial:getattr(qstrat,trial['implementation'])(features,**trial['params']))


def audit(directory, context):
    directory=Path(directory)
    artifact=A.verify(directory,context['plan'],context['provenance'])
    manifest=A.load((directory/'manifest.json').read_bytes())
    A.check(manifest['window']==[context['start'],context['end']],'manifest window differs from original panel')
    reports=[]
    for trial in manifest['trials']:
        if trial['status']!='EXTRACTED':
            reports.append(dict(trial_id=trial['trial_id'],status='NOT_VERIFIED_'+trial['status']))
            continue
        def retained():
            for shard in trial['shards']:
                with gzip.open(directory/shard['path'],'rb') as stream:
                    for line in stream: yield A.load(line)
        raw=context['generate'](trial['definition'])
        report=P.verify_trial(trial['trial_id'],raw,context['times'],context['assets'],context['eligibility'],
            context['sources'],context['start'],context['end'],retained(),trial['population'])
        report.update(status='VERIFIED',externally_bound_inputs_verified=True)
        reports.append(report)
    return dict(schema='v9.a6-source-audit/1',status='VERIFIED_AVAILABLE_TRIALS',
        extraction_source_commit=context['source_commit'],artifact_verification=artifact,trials=reports,
        verified_trials=sum(r['status']=='VERIFIED' for r in reports),
        unavailable_or_failed_trials=sum(r['status']!='VERIFIED' for r in reports),
        verifier_sha256={p.name:A.digest(p.read_bytes()) for p in (Path(__file__),Path(A.__file__),Path(P.__file__))},
        complete_family_population_verified=False,original_generator_mathematics_verified=False,
        full_matched_authority=False,promotion_authority=False)


def run(directory, out, prepare_context):
    """Separate audit output preserves extraction bytes and failed audit evidence."""
    out=Path(out)
    A.check(not out.exists() or not any(out.iterdir()),'preserve previous audit')
    A.check(out.resolve()!=Path(directory).resolve() and Path(directory).resolve() not in out.resolve().parents,
            'audit output must be outside extraction directory')
    out.mkdir(parents=True,exist_ok=True)
    try:
        result=audit(directory,prepare_context())
    except Exception as error:
        (out/'failure.json').write_text(json.dumps(dict(status='FAILED',type=type(error).__name__,message=str(error),
            promotion_authority=False),sort_keys=True,indent=2)+'\n',encoding='utf8')
        raise
    with (out/'audit.tmp').open('x',encoding='utf8',newline='\n') as stream:
        stream.write(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    (out/'audit.tmp').replace(out/'audit.json')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('md','evidence','source-commit','directory','out'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    run(args.directory,args.out,lambda:prepare(args.md,args.evidence,args.source_commit))
