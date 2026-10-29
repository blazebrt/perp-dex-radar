"""Independent A6 output inventory, signal accounting and pair-arithmetic checks.

Does not import matching, execution, aggregation or driver implementations.
Selection ranks, price paths and descriptive statistics need separate audits.
"""
from collections import Counter
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path, PurePosixPath
from tools.v9 import verify_control_storage as T


def require(ok,message):
    if not ok:raise ValueError(message)


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def load(raw):
    def unique(items):
        d={}
        for k,v in items:
            require(k not in d,'duplicate JSON key');d[k]=v
        return d
    def invalid(value):raise ValueError('invalid JSON number: '+value)
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)


def safe(root,name):
    p=PurePosixPath(name)
    require(isinstance(name,str) and '\\' not in name and not p.is_absolute() and
            p.as_posix()==name and all(x not in ('.','..') for x in p.parts),'unsafe inventory path')
    path=root.joinpath(*p.parts)
    require(path.resolve().is_relative_to(root.resolve()),'artifact escapes directory')
    require(path.is_file() and not any(p.is_symlink() for p in [path,*path.parents]),'unsafe artifact')
    return path


def records(root,names):
    for name in names:
        with gzip.open(safe(root,name),'rb') as stream:
            for line in stream:yield load(line)


def pair_records(root,names,manifest):
    schema=manifest['schema']
    require(schema in ('v9.a6-outcomes/1','v9.a6-outcomes/2'),'unknown outcome schema')
    if schema=='v9.a6-outcomes/2':
        require(manifest.get('pair_encoding')=='v9.a6-packed-pair/1','unknown pair encoding')
    else:require('pair_encoding' not in manifest,'legacy encoding mismatch')
    for row in records(root,names):
        if schema=='v9.a6-outcomes/2':yield T.unpack(row)
        else:
            require('schema' not in row,'packed record in legacy package')
            yield row


def known(outcome,signal):
    require(outcome['net_R'] is None and outcome['funding_path_known'] is False and
            outcome['full_matched_authority'] is False and outcome['promotion_authority'] is False,'invented outcome authority')
    require(outcome['geometry']==signal['geometry'] and outcome['direction']==signal['direction'] and
            outcome['decision_time']==signal['decision_time'] and outcome['entry_time']==signal['decision_time'],
            'outcome geometry/clock changed')
    status=outcome['status']
    require(status in ('UNEXECUTED','UNRESOLVED_PRICE','PRICE_OBSERVED_FUNDING_UNKNOWN'),'unknown outcome status')
    observed=status=='PRICE_OBSERVED_FUNDING_UNKNOWN'
    require(outcome['price_path_known'] is observed,'price availability mismatch')
    value=outcome['price_after_cost_R']
    require((type(value) in (int,float) and math.isfinite(value)) if observed else value is None,'invalid price result')
    return observed


def verify(directory,signals,input_hash,expected_bindings):
    """Input hash and output provenance/code/protocol bindings are external anchors."""
    root,source=Path(directory),Path(signals)
    require(sha(source/'manifest.json')==input_hash,'input manifest mismatch')
    original=load((source/'manifest.json').read_bytes())
    doc=load((root/'manifest.json').read_bytes())
    require(doc['schema'] in ('v9.a6-outcomes/1','v9.a6-outcomes/2') and doc['status']=='COMPLETED_PRICE_DIAGNOSTICS_NET_UNAVAILABLE',
            'outcome attempt incomplete')
    require(doc['input_manifest_sha256']==input_hash and all(doc[k]==v for k,v in expected_bindings.items()),'source binding mismatch')
    require(set(expected_bindings)=={'input_commit','provenance','implementation_sha256','protocol_sha256'},'incomplete external bindings')
    require(all(doc[k] is False for k in ('full_matched_authority','promotion_authority','independently_verified')),'invented authority')
    files={r['path']:r for r in doc['files']}
    require(len(files)==len(doc['files']),'duplicate output inventory')
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    require(actual==set(files)|{'manifest.json','attempt.json'},'unlisted or missing output')
    for name,row in files.items():
        path=safe(root,name)
        require(path.stat().st_size==row['bytes'] and sha(path)==row['sha256'],'output hash mismatch')
    counts=Counter();dispositions={};completed=[];total=0
    recognized={'sides.json','summary.sqlite'}
    for folder,key in [('days','day_shards'),('reuse','reuse_shards')]:
        for row in doc[key]:
            name=folder+'/'+row['path'];recognized.add(name)
            require(name in files and files[name]['sha256']==row['sha256'] and files[name]['bytes']==row['bytes'],
                    'summary shard inventory mismatch')
    for trial in original['trials']:
        tid=trial['trial_id'];names=sorted(n for n in files if n.startswith(tid+'-') and n.endswith('.jsonl.gz'))
        recognized.update(names)
        require(names==[tid+'-%05d.jsonl.gz'%i for i in range(len(names))],'outcome shard sequence')
        for shard in trial['shards']:
            require(sha(safe(source,shard['path']))==shard['sha256'],'input shard hash mismatch')
        n=0
        for signal,pair in itertools.zip_longest(records(source,[s['path'] for s in trial['shards']]),pair_records(root,names,doc)):
            require(signal is not None and pair is not None,'missing or extra outcome')
            require(all(pair[k]==signal[k] for k in ('signal_id','source_ordinal','trial_id','decision_time','direction'))
                    and pair['signal_asset']==signal['asset'],'outcome identity/order mismatch')
            require(pair['net_difference_R'] is None and pair['promotion_authority'] is False and
                    pair['full_matched_authority'] is False,'invented pair authority')
            cohort=pair['cohort'];controls=pair['controls']
            require([c['asset'] for c in controls]==[c['asset'] for c in cohort['controls']] and
                    len(controls)==cohort['control_count'] and len({c['asset'] for c in controls})==len(controls),'control identity/count mismatch')
            flags=[known(pair['candidate'],signal)]+[known(c['outcome'],signal) for c in controls]
            matched=cohort['status']=='DIAGNOSTIC_COHORT_50'
            require(not matched or len(controls)==50,'incomplete fifty-control cohort')
            resolved=matched and all(flags)
            expected='PRICE_PAIR_OBSERVED' if resolved else ('UNRESOLVED_PAIR' if matched else 'NO_FIFTY_CONTROL_COHORT')
            require(pair['pair_status']==expected,'pair disposition mismatch')
            values=[pair[k] for k in ('candidate_price_R','control_mean_price_R','price_difference_R')]
            if resolved:
                mean=math.fsum(c['outcome']['price_after_cost_R'] for c in controls)/50
                require(values==[pair['candidate']['price_after_cost_R'],mean,pair['candidate']['price_after_cost_R']-mean],
                        'pair arithmetic mismatch')
            else:require(values==[None,None,None],'partial cohort contrast invented')
            key=(tid,signal['direction']);counts[key,'signals']+=1;counts[key,'matched']+=matched;counts[key,'resolved']+=resolved
            d=dispositions.setdefault(key,Counter());d['matching:'+cohort['status']]+=1;d['pair:'+expected]+=1
            for prefix,items in [('candidate',[pair['candidate']]),('control',[c['outcome'] for c in controls])]:
                for item in items:d[prefix+':status:'+item['status']]+=1;d[prefix+':reason:'+str(item['reason'])]+=1
            n+=1;total+=1
        hourly=trial['status']=='UNAVAILABLE_HOURLY_POPULATION'
        require(n==(0 if hourly else trial['retained_records']),'trial population mismatch')
        completed.append(dict(trial_id=tid,signals=n,status='UNAVAILABLE_HOURLY_POPULATION' if hourly else 'PROCESSED'))
    require(set(files)==recognized,'unexpected output artifact')
    require(doc['processed_signals']==total and doc['completed_trials']==completed,'completion accounting mismatch')
    sides=load((root/'sides.json').read_bytes())
    require([(s['trial_id'],s['direction']) for s in sides]==[(t['trial_id'],d) for t in original['trials'] for d in (-1,1)],'side roster mismatch')
    for trial,side in zip((t for t in original['trials'] for _ in (-1,1)),sides):
        key=(side['trial_id'],side['direction']);hourly=trial['status']=='UNAVAILABLE_HOURLY_POPULATION'
        n,m,r=(counts[key,k] for k in ('signals','matched','resolved'))
        require([side[k] for k in ('signals','matched_fifty','resolved_pairs','unresolved_pairs')]==([None]*4 if hourly else [n,m,r,m-r]),'side count mismatch')
        require(side['counts']==dict(dispositions.get(key,{})),'disposition counts mismatch')
        require(side['matching_coverage']==(m/n if n else None),'matching coverage mismatch')
        require(side['conditional_price']['count']==(None if hourly else r),'conditional count mismatch')
        require(all(side[k] is None for k in ('net_mean','confidence_interval','p_value','dsr','pbo','bootstrap')) and
                side['full_matched_authority'] is False and side['promotion_authority'] is False,'invented inference')
    return dict(status='ACCOUNTING_AND_PAIR_ARITHMETIC_VERIFIED',signals=total,sides=len(sides),
                selection_verified=False,execution_paths_verified=False,descriptive_statistics_verified=False,
                full_matched_authority=False,promotion_authority=False)
