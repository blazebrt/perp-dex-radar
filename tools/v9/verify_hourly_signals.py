"""Reconcile complete signal populations with original strategies, not the new adapter."""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import numpy as np

HOUR=3600


def sessions(rows,btc=None):
    keys=sorted(t for t,r in rows.items() if r['qv']>0 and (btc is None or t in btc and btc[t]['qv']>0))
    result=[]
    for t in keys:
        if not result or t!=result[-1][-1]+HOUR:result.append([])
        result[-1].append(t)
    return result


def expected_signals(qstrat,alias,trial,coin,rows,btc,funding,first,start,end):
    if alias=='BTC_LEAD' and coin=='BTC':return {}
    found={}
    own={t:r for t,r in rows.items() if t<end}
    for times in sessions(own,btc if alias=='BTC_LEAD' else None):
        if len(times)<720:continue
        columns=[btc,own] if alias=='BTC_LEAD' else [own]
        p=SimpleNamespace(t=np.array(times,dtype=np.int64),T=len(times),N=len(columns),bar=HOUR,bar_h=1)
        for field,attr in [('o','o'),('h','h'),('l','l'),('c','c'),('qv','v')]:
            setattr(p,attr,np.array([[float(column[t][field]) for column in columns] for t in times]))
        p.fund=np.zeros((p.T,p.N))
        for i,t in enumerate(times):p.fund[i,-1]=funding.get(t,0.)
        f=qstrat.Feat(p)
        # Count completed UTC four-hour groups independently from readiness.py.
        full_four=0;group=[];allowed=[]
        for i,t in enumerate(times):
            if t%(4*HOUR)==0:group=[]
            group.append(t)
            if t%(4*HOUR)==3*HOUR:
                if len(group)==4 and group[0]%(4*HOUR)==0:full_four+=1
                group=[]
            ok=i+1>=720 and t+HOUR-first>=30*86400
            if alias=='PULLBACK':ok=ok and full_four>=200
            if alias=='FUND_FADE':ok=ok and t in funding and funding[t]!=0
            allowed.append(ok)
        f.elig[:,-1]&=np.array(allowed,dtype=bool)
        if alias=='BTC_LEAD':f.elig[:,0]=False
        signals=getattr(qstrat,trial['implementation'])(f,**trial['params'])
        for k,i in enumerate(signals['i']):
            t=int(p.t[int(i)])
            if t<start-HOUR:continue
            assert int(signals['j'][k])==len(columns)-1
            key=(t,int(signals['d'][k]));assert key not in found
            found[key]=dict(direction=int(signals['d'][k]),hold=int(signals['hold'][k]),
                           **{a:float(signals[a][k]) for a in ('stop','target','trail','be')})
    return found


def verify(repo,commit,source,archive):
    repo=Path(repo);archive=Path(archive)
    def cmd(*args):return ['git','-c','safe.directory=*','-C',str(repo),*args]
    for name in ('qstrat.py','qdata.py','qind.py'):
        path='tools/research/'+name
        assert (repo/path).read_bytes()==subprocess.check_output(cmd('show',f'{source}:{path}'))
    sys.path.insert(0,str(repo/'tools/research'));import qstrat
    manifest_raw=(archive/'quality_candidate_manifest.json').read_bytes()
    assert hashlib.sha256(manifest_raw).hexdigest()=='d9eaba6b1a190d86529b01362a665f83c1c52d2a88e04f4cd71f4d333e8527b2'
    manifest=json.loads(manifest_raw)
    def checked(path):
        p=archive/path;assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest['artifacts_sha256'][path],path
        return p
    def candles(coin):
        with gzip.open(checked(f'h1/{coin}.csv.gz'),'rt') as fh:
            return {int(r['t']):{k:float(r[k]) for k in ('o','h','l','c','qv')} for r in csv.DictReader(fh)}
    def rates(coin):
        with gzip.open(checked(f'fund_bn/{coin}.csv.gz'),'rt') as fh:
            return {int(r['t']):float(r['rate']) for r in csv.DictReader(fh)}
    plan=json.loads(checked('hourly_plan.json').read_bytes());start,end=plan['window']
    coins={r['t']:r for r in plan['fetch_coins']};btc=candles('BTC')
    census=json.loads(subprocess.check_output(cmd('show',f'{source}:research/v9/census_replay_plan.json')))
    trials={a:t for t in census['trials'] if t['archive_requirement']=='hourly' for a in t['aliases']}
    results={}
    for alias,trial in sorted(trials.items()):
        if alias=='FUND_CARRY':continue
        expected={};seen=set();current=None;count=0;segments=0;unavailable=0;failed=0
        p=subprocess.Popen(cmd('show',f'{commit}:{alias}.jsonl.gz'),stdout=subprocess.PIPE)
        try:
            with gzip.GzipFile(fileobj=p.stdout) as stream:
                for line in stream:
                    row=json.loads(line)
                    if row['kind']=='segment':
                        if current:assert seen==set(expected),(alias,current,'signal population mismatch')
                        current=row['coin'];expected={};seen=set()
                        if row['status']=='FAILED_SEGMENT':failed+=1;continue
                        funding=rates(current)
                        if row['status']=='UNAVAILABLE_OFF_GRID_FUNDING':
                            assert alias=='FUND_FADE' and any(start-HOUR<=t<end and t%HOUR for t in funding)
                            unavailable+=1;continue
                        assert row['status']=='REPLAYED'
                        expected=expected_signals(qstrat,alias,trial,current,candles(current),btc,
                                                  {t:r for t,r in funding.items() if t%HOUR==0},
                                                  coins[current]['first_bar'],start,end)
                        segments+=1
                    else:
                        assert row['kind']=='attempt' and row['coin']==current
                        key=(row['signal_time'],row['parameters']['direction']);assert key not in seen
                        assert key in expected,(alias,current,key,'unexpected signal')
                        seen.add(key);count+=1
                        for k,value in expected[key].items():
                            assert math.isclose(row['parameters'][k],value,rel_tol=1e-10,abs_tol=1e-12),(alias,current,key,k)
            if current:assert seen==set(expected),(alias,current,'terminal population mismatch')
        finally:
            p.stdout.close();assert p.wait()==0
        results[alias]=dict(signals=count,reconciled_segments=segments,unavailable_segments=unavailable,failed_segments=failed)
        print(alias,results[alias],flush=True)
    return dict(schema='v9.a5-independent-signal-reconciliation/1',result_commit=commit,source_commit=source,
                original_strategy_code_reused=True,new_signal_adapter_imported=False,
                every_successfully_generated_segment_population_reconciled=True,trials=results,
                full_family_complete=False,promotion_authority=False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--commit',required=True)
    p.add_argument('--source',required=True);p.add_argument('--archive',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();r=verify(a.repo,a.commit,a.source,a.archive)
    Path(a.out).write_text(json.dumps(r,sort_keys=True,indent=2)+'\n',encoding='utf8')
