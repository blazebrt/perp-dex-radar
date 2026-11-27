"""Plan source-shard work units without reading signals or executing a study."""
import argparse
import hashlib
import json
from pathlib import Path
import re

INPUT_COMMIT='eb785a908dce572958336649291b8feeb4ee9575'
INPUT_SHA='ea45d68a337ab682406748f2b94c833a5ca00b8e495aa7bdd38fe9b1f5d02a5e'


def check(value,message):
    if not value:raise ValueError(message)


def build(raw,expected_sha=INPUT_SHA):
    check(isinstance(raw,bytes) and len(raw)<=4*1024*1024,'manifest size')
    digest=hashlib.sha256(raw).hexdigest()
    check(digest==expected_sha,'manifest binding mismatch')
    def unique(pairs):
        out={}
        for key,value in pairs:
            check(key not in out,'duplicate manifest key');out[key]=value
        return out
    def invalid(_):raise ValueError('nonfinite JSON')
    manifest=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
    check(isinstance(manifest,dict) and manifest.get('schema')=='v9.a6-extraction/1'
          and manifest.get('status')=='COMPLETED_WITH_UNAVAILABLE_HOURLY_POPULATIONS','manifest contract')
    check(all(manifest.get(k) is False for k in ('promotion_authority','outcomes_computed','full_matched_authority')),'unexpected input authority')
    trials=manifest.get('trials');check(isinstance(trials,list) and 0<len(trials)<=199,'trial inventory')
    ids=set();paths=set();units=[];inventory=[];total=0
    for trial in trials:
        check(isinstance(trial,dict),'trial contract')
        tid=trial.get('trial_id')
        check(isinstance(tid,str) and re.fullmatch('[a-f0-9]{64}',tid) and tid not in ids,'trial identity')
        ids.add(tid)
        check(isinstance(trial.get('definition'),dict) and trial['definition'].get('trial_id')==tid
              and trial.get('promotion_authority') is False,'trial binding')
        shards=trial.get('shards');check(isinstance(shards,list),'shard inventory')
        state=trial.get('status');check(state in ('EXTRACTED','UNAVAILABLE_HOURLY_POPULATION'),'trial status')
        if state=='UNAVAILABLE_HOURLY_POPULATION':
            check(not shards and trial.get('retained_records',0)==0,'unavailable trial has rows')
        offset=0
        for number,shard in enumerate(shards):
            check(isinstance(shard,dict),'shard contract')
            path=shard.get('path')
            check(path==f'{tid}-{number:05d}.jsonl.gz' and path not in paths,'shard identity/order')
            paths.add(path)
            n=shard.get('records')
            check(type(n) is int and 0<n<=25000,'shard row count')
            for key in ('bytes','uncompressed_bytes'):
                check(type(shard.get(key)) is int and 0<shard[key]<=16*1024*1024,'shard byte count')
            check(isinstance(shard.get('sha256'),str) and re.fullmatch('[a-f0-9]{64}',shard['sha256']),'shard hash')
            units.append(dict(unit_id=f'{tid}:{number:05d}',trial_id=tid,source=dict(shard),
                              retained_row_start=offset,retained_row_end=offset+n))
            offset+=n
        if state=='EXTRACTED':
            check(type(trial.get('retained_records')) is int and trial['retained_records']==offset,'trial accounting')
        inventory.append(dict(trial_id=tid,status=state,retained_records=offset,units=len(shards)))
        total+=offset
    return dict(schema='v9.a6-partition-plan/1',status='METADATA_PLAN_ONLY',input_manifest_sha256=digest,
                input_commit=INPUT_COMMIT if digest==INPUT_SHA else None,
                signals=total,trial_count=len(trials),unit_count=len(units),trials=inventory,units=units,
                source_shards_reverified=False,resource_qualified=False,execution_authorized=False,
                promotion_authority=False,
                interpretation='Source-order row offsets are not regenerated signal ordinals; retain original signal identities.',
                limitations=['A plan is not an executed, audited, resumable or resource-qualified study.',
                             'Original shard bytes and all source observations must be verified before any execution.',
                             'Global day/reuse/statistics reconciliation and one-attempt failure semantics remain required.'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path);parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args(argv)
    with args.manifest.open('rb') as stream:raw=stream.read(4*1024*1024+1)
    result=build(raw)
    check(result['signals']==4263580 and result['trial_count']==199 and
          sum(t['status']=='UNAVAILABLE_HOURLY_POPULATION' for t in result['trials'])==7,'registered population mismatch')
    with args.out.open('xb') as stream:
        stream.write((json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())
    return 0


if __name__=='__main__':raise SystemExit(main())
