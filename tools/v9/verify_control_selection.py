"""Independent registered-cohort audit over externally source-verified snapshots.

This checks selection, not snapshot provenance, original eligibility or outcomes.
It intentionally imports no production cohort/feature/matching implementation.
"""
import hashlib
import json
import math


def check(ok,message):
    if not ok:raise ValueError(message)


def bucket(snapshot,decision):
    first=snapshot.get('segment_first_bar');known=snapshot.get('first_bar_known_at')
    end=snapshot.get('volume_window_end');available=snapshot.get('volume_known_at')
    if snapshot.get('provenance')!='ARCHIVE_RECONSTRUCTION':return None
    if any(type(x) is not int or x<0 or x>decision for x in (first,known,end,available)):return None
    if known<first or available<end or end!=decision-decision%86400:return None
    if snapshot.get('volume_window_start')!=end-604800 or snapshot.get('volume_observations')!=42:return None
    volume=snapshot.get('mean_daily_quote_volume')
    if type(volume) not in (float,int) or not math.isfinite(volume) or volume<5000000:return None
    age=(decision-first)/86400
    if first>end-604800 or age<30:return None
    return dict(archive_age_bucket=sum(age>=edge for edge in (30,90,180,365,730))-1,
                liquidity_bucket=sum(volume>=edge for edge in (5000000,10000000,25000000,50000000,100000000))-1)


def verify(trial_id,signal,population,cohort):
    """Population must be the complete eligible-universe snapshot, not selected rows."""
    t,d=signal['decision_time'],signal['direction']
    check(type(t) is int and t>=0 and type(d) is int and d in (-1,1),'invalid decision')
    def identity(row):
        return all(isinstance(row.get(k),str) and row[k] and row[k]==row[k].strip() for k in ('asset','source_symbol'))
    check(isinstance(trial_id,str) and trial_id and identity(signal),'invalid identity')
    expected=dict(schema='v9.a6-cohort/1',trial_id=trial_id,signal_asset=signal['asset'],decision_time=t,direction=d,
        controls=[],required_controls=50,full_matched_authority=False,promotion_authority=False,
        age_interpretation='ARCHIVE_SEGMENT_AGE_NOT_VERIFIED_LISTING_AGE',eligible_candidates=0,
        feature_unavailable=0,bucket_mismatched=0,same_symbol_excluded=0,matching_candidates=0)
    target=bucket(signal,t)
    if target is None or signal.get('eligible') is not True:
        expected.update(status='UNAVAILABLE_SIGNAL_FEATURES',control_count=0)
    else:
        expected['signal_buckets']=target
        eligible=[r for r in population if type(r.get('decision_time')) is int and r['decision_time']==t and
                  type(r.get('direction')) is int and r['direction']==d and r.get('eligible') is True]
        check(all(identity(r) for r in eligible),'invalid population identity')
        check(len({r['asset'] for r in eligible})==len(eligible) and
              len({r['source_symbol'] for r in eligible})==len(eligible),'ambiguous population')
        expected['eligible_candidates']=len(eligible)
        ranked=[]
        for r in eligible:
            if r['asset']==signal['asset'] or r['source_symbol']==signal['source_symbol']:
                expected['same_symbol_excluded']+=1;continue
            bins=bucket(r,t)
            if bins is None:expected['feature_unavailable']+=1;continue
            if bins!=target:expected['bucket_mismatched']+=1;continue
            key=['v9.a6-cohort/1',trial_id,t,d,signal['asset'],r['asset']]
            digest=hashlib.sha256(json.dumps(key,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            retained={k:r[k] for k in ('asset','source_symbol','decision_time','direction','eligible','provenance',
                'segment_first_bar','first_bar_known_at','volume_window_start','volume_window_end','volume_known_at',
                'volume_observations','mean_daily_quote_volume')}
            ranked.append(dict(asset=r['asset'],rank_sha256=digest,features=retained,buckets=bins))
        ordered=sorted(ranked,key=lambda r:(r['rank_sha256'],r['asset']))
        expected.update(matching_candidates=len(ordered),controls=ordered[:50],control_count=min(50,len(ordered)),
                        status='DIAGNOSTIC_COHORT_50' if len(ordered)>=50 else 'INSUFFICIENT_CONTROLS')
    check(cohort==expected,'registered selection mismatch')
    return dict(selection_verified=True,snapshot_provenance_verified=False,execution_paths_verified=False,
                full_matched_authority=False,promotion_authority=False)
