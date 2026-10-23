"""Reconcile A6 descriptive summaries from independently audited pair records.

No production aggregation imports. A separate scratch database bounds memory;
input accounting, cohort selection and price paths remain prerequisite audits.
"""
import itertools
import math
from pathlib import Path
import sqlite3


def check(ok,message):
    if not ok:raise ValueError(message)


def same(actual,expected):
    if expected is None:return actual is None
    return type(actual) in (int,float) and math.isfinite(actual) and math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-10)


def verify(pairs,trials,sides,days,reuse,scratch):
    check(not Path(scratch).exists(),'preserve existing statistics audit')
    roster={t['trial_id']:t for t in trials}
    check(len(roster)==len(trials),'duplicate trial roster')
    db=sqlite3.connect(scratch)
    try:
        db.executescript('''PRAGMA temp_store=FILE; PRAGMA cache_size=-8192;
          CREATE TABLE observations(id TEXT PRIMARY KEY,trial TEXT,side INTEGER,day INTEGER,matched INTEGER,
            candidate REAL,control REAL,value REAL);
          CREATE INDEX ordered_values ON observations(trial,side,value);
          CREATE INDEX daily ON observations(trial,side,day);
          CREATE TABLE uses(trial TEXT,side INTEGER,asset TEXT,time INTEGER,n INTEGER,
            PRIMARY KEY(trial,side,asset,time));''')
        n=0
        for pair in pairs:
            tid,d,t=pair['trial_id'],pair['direction'],pair['decision_time']
            check(tid in roster and roster[tid]['archive_requirement']=='4h' and type(d) is int and d in (-1,1)
                  and type(t) is int and t>=0,'invalid pair identity')
            values=[pair[k] for k in ('candidate_price_R','control_mean_price_R','price_difference_R')]
            resolved=pair['pair_status']=='PRICE_PAIR_OBSERVED';matched=pair['cohort']['status']=='DIAGNOSTIC_COHORT_50'
            check((all(type(v) in (int,float) and math.isfinite(v) for v in values) and matched) if resolved
                  else values==[None,None,None],'invalid pair values')
            check(pair['net_difference_R'] is None and pair['full_matched_authority'] is False and
                  pair['promotion_authority'] is False,'invented pair authority')
            db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)',(pair['signal_id'],tid,d,t//86400,int(matched),*values))
            db.executemany('INSERT INTO uses VALUES(?,?,?,?,1) ON CONFLICT(trial,side,asset,time) DO UPDATE SET n=n+1',
                           ((tid,d,c['asset'],t) for c in pair['controls']))
            n+=1
        db.commit()
        check([(s['trial_id'],s['direction']) for s in sides]==[(tid,d) for tid in roster for d in (-1,1)],'side roster mismatch')
        for side in sides:
            tid,d=side['trial_id'],side['direction'];key=(tid,d)
            total,matched,count=db.execute('SELECT count(*),coalesce(sum(matched),0),count(value) FROM observations WHERE trial=? AND side=?',key).fetchone()
            means=[]
            for column in ('candidate','control','value'):
                means.append(math.fsum(r[0]/count for r in db.execute('SELECT '+column+' FROM observations WHERE trial=? AND side=? AND value IS NOT NULL',key)) if count else None)
            median=low=high=None
            if count:
                centers=[]
                for index,(value,) in enumerate(db.execute('SELECT value FROM observations WHERE trial=? AND side=? AND value IS NOT NULL ORDER BY value',key)):
                    if index==0:low=value
                    if index in ((count-1)//2,count//2):centers.append(value)
                    high=value
                median=math.fsum(v/len(centers) for v in centers)
            expected=dict(candidate_mean=means[0],control_mean=means[1],difference_mean=means[2],
                          difference_median=median,difference_min=low,difference_max=high)
            hourly=roster[tid]['archive_requirement']=='hourly'
            conditional=side['conditional_price']
            check(all(same(conditional[k],v) for k,v in expected.items()),'conditional statistic mismatch')
            check(conditional['count']==(None if hourly else count) and
                  conditional['interpretation']=='CONDITIONAL_ON_ALL_51_OBSERVABLE_PRICE_OUTCOMES','conditional denominator/label mismatch')
            check(same(side['complete_pair_population_price_mean'],means[2] if matched and matched==count else None),'complete population mean mismatch')
            check(side['status']==('UNAVAILABLE_HOURLY_POPULATION' if hourly else ('DESCRIPTIVE' if total else 'EMPTY_SIDE')),'side availability mismatch')
            check(all(side[k] is None for k in ('net_mean','confidence_interval','p_value','dsr','pbo','bootstrap')) and
                  side['full_matched_authority'] is False and side['promotion_authority'] is False,'invented inference')
        daily=db.execute('''SELECT trial,side,day,count(*),sum(matched),count(value),sum(value) FROM observations
                           GROUP BY trial,side,day ORDER BY trial,side,day''')
        day_count=0
        for actual,expected in itertools.zip_longest(days,daily):
            check(actual is not None and expected is not None,'missing/extra daily row')
            keys=('trial_id','direction','day','signals','matched_fifty','resolved_pairs')
            check(tuple(actual[k] for k in keys)==expected[:6] and same(actual['price_difference_sum'],expected[6]),'daily aggregate mismatch')
            day_count+=1
        use_count=0
        for actual,expected in itertools.zip_longest(reuse,db.execute('SELECT trial,side,asset,time,n FROM uses ORDER BY trial,side,asset,time')):
            check(actual is not None and expected is not None,'missing/extra reuse row')
            check(tuple(actual[k] for k in ('trial_id','direction','asset','decision_time','uses'))==expected,'control reuse mismatch')
            use_count+=1
        return dict(descriptive_statistics_verified=True,day_aggregates_verified=True,control_reuse_verified=True,
                    signals=n,days=day_count,reuse_rows=use_count,source_provenance_verified=False,
                    full_matched_authority=False,promotion_authority=False)
    finally:db.close()
