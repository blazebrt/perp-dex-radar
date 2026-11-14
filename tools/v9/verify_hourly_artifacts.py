"""Independent artifact/accounting audit. No replay-module imports or new trials."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

EXPECTED_DATA='d9eaba6b1a190d86529b01362a665f83c1c52d2a88e04f4cd71f4d333e8527b2'
EXPECTED_COMMIT='0859e683910a7eea7ef446b27cf9773f33d9e9f8'
ALIASES={'FAIL_BRK','FUND_CARRY','PULLBACK','LIQ_FLUSH','BTC_LEAD','VOL_SPIKE','FUND_FADE'}


def verify(repo,commit,source,run_id):
    def command(*args):return ['git','-c','safe.directory=*','-C',str(repo),*args]
    def raw(name,ref=commit):return subprocess.check_output(command('show',f'{ref}:{name}'))
    def doc(name):return json.loads(raw(name))
    def digest(name):
        p=subprocess.Popen(command('show',f'{commit}:{name}'),stdout=subprocess.PIPE)
        h=hashlib.sha256()
        for b in iter(lambda:p.stdout.read(1024*1024),b''):h.update(b)
        p.stdout.close();assert p.wait()==0
        return h.hexdigest()
    ev=doc('replay_run.json'); assert ev['dataset_sha256']==EXPECTED_DATA
    assert ev['data_commit']==EXPECTED_COMMIT
    assert ev['confirmed']==[] and ev['promotion_authority'] is False
    assert ev['known_trial_return_matrix_complete'] is False
    assert raw('run_meta.txt').decode().split()[1]==source
    assert raw('actions_run.txt').decode().split()[0]==str(run_id)
    expected=set(ev['artifacts_sha256'])|{'replay_run.json','REPORT_A5.md','run_meta.txt','dataset_ref.txt','actions_run.txt'}
    actual=set(subprocess.check_output(command('ls-tree','-r','--name-only',commit)).decode().splitlines())
    assert actual==expected,actual^expected
    for name,want in ev['artifacts_sha256'].items():assert digest(name)==want,name
    for name,want in ev['preregistrations_sha256'].items():
        assert hashlib.sha256(raw(name,source)).hexdigest()==want,name
    assert hashlib.sha256(raw('tools/v9/hourly_replay_publish.py',source)).hexdigest()==ev['publisher_sha256']
    streams=doc('attempts_a5.json')
    assert streams=={k:v for k,v in ev['artifacts_sha256'].items() if k.endswith('.jsonl.gz')}
    result=dict(schema='v9.a5-independent-artifact-accounting/1',result_commit=commit,
                source_commit=source,actions_run=run_id,status=ev['status'],
                all_artifact_hashes_verified=True,all_preregistrations_match_source=True,
                independent_price_signal_reconciliation_complete=False,promotion_authority=False)
    if ev['status']=='FAILED':
        assert not ev['driver_manifest_retained']
        result['failure']=doc('failure.json');return result
    driver=doc('evidence_a5.json');assert set(driver['trials'])==ALIASES
    assert ev['trials']==driver['trials'];assert driver['dataset_sha256']==EXPECTED_DATA
    for name,want in driver['artifacts_sha256'].items():assert streams[name]==want,name
    for name,want in driver['source_sha256'].items():assert hashlib.sha256(raw(name,source)).hexdigest()==want,name
    plan=json.loads(raw('research/v9/census_replay_plan.json',source))
    registered={a:t for t in plan['trials'] if t['archive_requirement']=='hourly' for a in t['aliases']}
    for alias,trial in driver['trials'].items():
        assert trial['trial_id']==registered[alias]['trial_id']
        assert trial['params']==registered[alias]['params']
    totals={}
    for alias in sorted(ALIASES):
        name=alias+'.jsonl.gz'; assert name in streams
        summary=driver['trials'][alias];counts=Counter();segments=[];failed=0;unavailable=0
        current=None;seen=set();attempt_total=0;segment_attempts=0;last_time=None
        p=subprocess.Popen(command('show',f'{commit}:{name}'),stdout=subprocess.PIPE)
        try:
            with gzip.GzipFile(fileobj=p.stdout) as fh:
                for line in fh:
                    row=json.loads(line)
                    if row['kind']=='trial':
                        assert alias=='FUND_CARRY' and row['net_series_available'] is False
                        assert all(d['net_R'] is None for d in row['daily_net_R']);continue
                    if row['kind']=='segment':
                        if current and 'generated_signal_count' in current:
                            assert segment_attempts==current['generated_signal_count']
                        current=row;segments.append(row['coin']);segment_attempts=0;last_time=None;seen=set()
                        failed+=row['status']=='FAILED_SEGMENT';unavailable+=row['status'].startswith('UNAVAILABLE')
                    else:
                        assert row['kind']=='attempt' and row['coin']==current['coin']
                        t=row['signal_time'];assert last_time is None or t>=last_time;last_time=t
                        key=(t,row['parameters']['direction']);assert key not in seen;seen.add(key)
                        assert row['entry_time']==t+3600
                        assert row['net_R'] is None, 'Unproven funding became a net return'
                        assert row['status'] in ('UNEXECUTED','UNRESOLVED','UNRESOLVED_FUNDING')
                        counts[row['status']]+=1;attempt_total+=1;segment_attempts+=1
            if current and 'generated_signal_count' in current:assert segment_attempts==current['generated_signal_count']
        finally:
            p.stdout.close();assert p.wait()==0
        assert segments==sorted(set(segments))
        assert dict(counts)==summary['attempt_counts']
        assert len(segments)==summary['segments'] and failed==summary['failed_segments']
        assert unavailable==summary['unavailable_segments']
        unknown=counts['UNRESOLVED']+counts['UNRESOLVED_FUNDING']
        expect_available=not (unknown or failed or unavailable or alias=='FUND_CARRY')
        assert summary['net_series_available']==expect_available
        daily=summary['daily_net_R'];start,end=driver['window']
        assert [d['day'] for d in daily]==list(range(start,end+1,86400))
        assert all(d['net_R']==0 if expect_available else d['net_R'] is None for d in daily)
        totals[alias]=dict(attempts=attempt_total,counts=dict(counts),segments=len(segments),
                           failed_segments=failed,unavailable_segments=unavailable,net_series_available=expect_available)
    result.update(trial_accounting_verified=True,trials=totals)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--commit',required=True)
    p.add_argument('--source',required=True);p.add_argument('--run-id',required=True,type=int);p.add_argument('--out',required=True)
    a=p.parse_args();r=verify(a.repo,a.commit,a.source,a.run_id)
    Path(a.out).write_text(json.dumps(r,sort_keys=True,indent=2)+'\n',encoding='utf8')
    print(json.dumps(r,sort_keys=True))
