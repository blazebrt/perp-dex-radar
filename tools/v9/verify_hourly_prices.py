"""Independent candle/entry-ledger reconciliation; no strategy-engine imports."""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess


def price_outcome(rows, entry, direction, stop, target, trail, be, hold):
    first=rows.get(entry)
    if not first or first['qv']<=0:return {'status':'UNEXECUTED','reason':'UNOBSERVABLE_ENTRY'}
    price=first['o'];risk=price*stop
    initial=price-direction*risk;limit=initial;best=price
    goal=price+direction*target*risk
    for k in range(hold):
        t=entry+3600*k;r=rows.get(t)
        if not r or r['qv']<=0:
            return dict(status='UNRESOLVED',reason='UNOBSERVABLE_PRICE_PATH',entry_price=price,
                        price_uncertainty_time=t,uncertainty_time=entry,exit_price=None,gross_R=None)
        if k>0 and direction*(r['o']-limit)<=0:
            exit_price=r['o'];reason='GAP_STOP'
        elif (direction==1 and r['l']<=limit) or (direction==-1 and r['h']>=limit):
            exit_price=limit;reason='TRAIL_STOP' if direction*(limit-initial)>0 else 'STOP'
        elif target>0 and ((direction==1 and r['h']>=goal) or (direction==-1 and r['l']<=goal)):
            exit_price=goal;reason='TARGET'
        elif k+1==hold:
            exit_price=r['c'];reason='TIME'
        else:
            if trail>0:
                best=max(best,r['c']) if direction==1 else min(best,r['c'])
                proposed=best-direction*price*trail
                limit=max(limit,proposed) if direction==1 else min(limit,proposed)
            excursion=(r['h']-price)/risk if direction==1 else (price-r['l'])/risk
            if be>0 and excursion>=be:limit=max(limit,price) if direction==1 else min(limit,price)
            continue
        return dict(status='UNRESOLVED_FUNDING',reason=reason,entry_price=price,
                    exit_price=exit_price,exit_time=t+3600,
                    gross_R=direction*(exit_price-price)/(price*stop),uncertainty_time=entry)
    raise AssertionError('no terminal state')


def verify(repo,commit,archive):
    archive=Path(archive)
    manifest_path=archive/'quality_candidate_manifest.json'
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest()=='d9eaba6b1a190d86529b01362a665f83c1c52d2a88e04f4cd71f4d333e8527b2'
    manifest=json.loads(manifest_path.read_bytes())
    def checked(path):
        p=archive/path;assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest['artifacts_sha256'][path],path
        return p
    plan=json.loads(checked('hourly_plan.json').read_bytes());start,end=plan['window']
    schedule=json.loads(checked('quality_schedule.json').read_bytes())
    days={d['schedule']['known_at']:(d['new_entries_allowed'],{r['coin'] for r in d['schedule']['selected']}) for d in schedule}
    def cmd(*args):return ['git','-c','safe.directory=*','-C',str(repo),*args]
    outer=json.loads(subprocess.check_output(cmd('show',f'{commit}:replay_run.json')))
    assert outer['driver_manifest_retained']
    results={}
    for alias in sorted(outer['trials']):
        if alias=='FUND_CARRY':continue
        process=subprocess.Popen(cmd('show',f'{commit}:{alias}.jsonl.gz'),stdout=subprocess.PIPE)
        rows={};busy=start;locked=False;coin=None;counts=Counter()
        try:
            with gzip.GzipFile(fileobj=process.stdout) as stream:
                for line in stream:
                    item=json.loads(line)
                    if item['kind']=='segment':
                        coin=item['coin'];busy=start;locked=False;rows={}
                        if item['status']!='REPLAYED':continue
                        with gzip.open(checked(f'h1/{coin}.csv.gz'),'rt') as fh:
                            for raw in csv.DictReader(fh):
                                t=int(raw['t'])
                                if start<=t<end:rows[t]={k:float(raw[k]) for k in ('o','h','l','c','qv')}
                        continue
                    assert item['kind']=='attempt' and item['coin']==coin
                    entry=item['signal_time']+3600
                    if not start<=entry<end:reason='OUTSIDE_ENTRY_WINDOW'
                    elif locked:reason='BLOCKED_UNKNOWN_POSITION'
                    elif entry<busy:reason='POSITION_OPEN'
                    else:
                        allowed,members=days[entry//86400*86400]
                        reason='QUALITY_EMBARGO' if not allowed else ('NOT_SELECTED_AT_ENTRY' if coin not in members else None)
                    expected=dict(status='UNEXECUTED',reason=reason) if reason else price_outcome(rows,entry,**item['parameters'])
                    for key,want in expected.items():
                        actual=item.get(key)
                        if isinstance(want,float):assert actual is not None and math.isclose(actual,want,rel_tol=1e-11,abs_tol=1e-11),(alias,coin,entry,key,actual,want)
                        else:assert actual==want,(alias,coin,entry,key,actual,want)
                    assert item['net_R'] is None
                    if expected['status']=='UNRESOLVED':locked=True
                    elif expected['status']=='UNRESOLVED_FUNDING':busy=expected['exit_time']
                    counts[expected['status']]+=1
        finally:
            process.stdout.close();assert process.wait()==0
        results[alias]=dict(counts)
    return dict(schema='v9.a5-independent-price-reconciliation/1',result_commit=commit,
                every_retained_attempt_reconciled=True,counts=results,
                complete_signal_population_independently_verified=False,promotion_authority=False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--commit',required=True)
    p.add_argument('--archive',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();result=verify(a.repo,a.commit,a.archive)
    Path(a.out).write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,sort_keys=True))
