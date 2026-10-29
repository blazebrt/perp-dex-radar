"""Disk-backed A6 descriptive summaries; every inferential slot stays unavailable."""
from collections import Counter
from pathlib import Path
import sqlite3
import math
from tools.v9.control_pairs import require, observed
from tools.v9.control_cohort import number


class Summary:
    def __init__(self,path,trials):
        path=Path(path)
        require(not path.exists(),'preserve existing aggregation database')
        self.trials={t['trial_id']:t for t in trials}
        require(len(self.trials)==len(trials),'duplicate trial roster')
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.execute('PRAGMA cache_size=-8192')
        self.db.executescript('''
          CREATE TABLE pairs(id TEXT PRIMARY KEY,trial TEXT,direction INTEGER,day INTEGER,matched INTEGER,
            candidate REAL,control REAL,difference REAL);
          CREATE INDEX side_values ON pairs(trial,direction,difference);
          CREATE TABLE reuse(trial TEXT,direction INTEGER,asset TEXT,time INTEGER,n INTEGER,
            PRIMARY KEY(trial,direction,asset,time));
        ''')
        self.counts={}

    def add(self,row):
        tid,direction=row['trial_id'],row['direction']
        require(tid in self.trials and self.trials[tid]['archive_requirement']=='4h' and
                type(direction) is int and direction in (-1,1),'unknown/unavailable trial side')
        require(row['net_difference_R'] is None and row['promotion_authority'] is False
                and row['full_matched_authority'] is False,'unsupported inference')
        cohort=row['cohort'];controls=row['controls']
        require([r['asset'] for r in controls]==[r['asset'] for r in cohort['controls']],'control identity mismatch')
        require(len(controls)==cohort['control_count'] and len({r['asset'] for r in controls})==len(controls),'control count mismatch')
        paired=cohort['status']=='DIAGNOSTIC_COHORT_50'
        require(not paired or len(controls)==50,'incomplete full cohort')
        resolved=row['pair_status']=='PRICE_PAIR_OBSERVED'
        observation_flags=[observed(row['candidate'])]+[observed(r['outcome']) for r in controls]
        known=all(observation_flags)
        expected_status='PRICE_PAIR_OBSERVED' if paired and known else ('UNRESOLVED_PAIR' if paired else 'NO_FIFTY_CONTROL_COHORT')
        require(row['pair_status']==expected_status,'pair disposition mismatch')
        require((row['price_difference_R'] is not None)==resolved and (not resolved or paired),'pair value mismatch')
        values=(row['candidate_price_R'],row['control_mean_price_R'],row['price_difference_R'])
        require(all(v is None for v in values) if not resolved else all(number(v) for v in values),'pair values missing')
        if resolved:
            expected=math.fsum(r['outcome']['price_after_cost_R'] for r in controls)/50
            require(values[0]==row['candidate']['price_after_cost_R'] and values[1]==expected and
                    values[2]==values[0]-expected,'paired arithmetic mismatch')
        # A duplicate signal fails before counters/reuse are mutated.
        self.db.execute('INSERT INTO pairs VALUES(?,?,?,?,?,?,?,?)',
            (row['signal_id'],tid,direction,row['decision_time']//86400,int(paired),*values))
        key=(tid,direction)
        counts=self.counts.setdefault(key,Counter())
        counts['matching:'+cohort['status']]+=1
        counts['pair:'+row['pair_status']]+=1
        for prefix,outcomes in (('candidate',[row['candidate']]),('control',[r['outcome'] for r in controls])):
            for outcome in outcomes:
                counts[prefix+':status:'+outcome['status']]+=1
                counts[prefix+':reason:'+str(outcome['reason'])]+=1
        self.db.executemany('INSERT INTO reuse VALUES(?,?,?,?,1) ON CONFLICT(trial,direction,asset,time) DO UPDATE SET n=n+1',
            ((tid,direction,r['asset'],row['decision_time']) for r in controls))

    def finish(self,emit_day,emit_reuse):
        self.db.commit()
        result=[]
        for tid,trial in self.trials.items():
            for direction in (-1,1):
                total,matched,resolved,cm,tm,mean,low,high=self.db.execute('''
                  SELECT count(*),coalesce(sum(matched),0),count(difference),avg(candidate),avg(control),
                         avg(difference),min(difference),max(difference) FROM pairs WHERE trial=? AND direction=?
                ''',(tid,direction)).fetchone()
                median=None
                if resolved:
                    central=[r[0] for r in self.db.execute('''SELECT difference FROM pairs WHERE trial=? AND direction=?
                      AND difference IS NOT NULL ORDER BY difference LIMIT ? OFFSET ?''',
                      (tid,direction,2 if resolved%2==0 else 1,(resolved-1)//2))]
                    median=sum(v/len(central) for v in central)
                require(all(v is None or number(v) for v in (cm,tm,mean,low,high,median)),'nonfinite aggregate')
                result.append(dict(trial_id=tid,direction=direction,
                    status='UNAVAILABLE_HOURLY_POPULATION' if trial['archive_requirement']=='hourly' else ('DESCRIPTIVE' if total else 'EMPTY_SIDE'),
                    signals=total,matched_fifty=matched,resolved_pairs=resolved,unresolved_pairs=matched-resolved,
                    matching_coverage=matched/total if total else None,
                    counts=dict(self.counts.get((tid,direction),{})),
                    conditional_price=dict(candidate_mean=cm,control_mean=tm,difference_mean=mean,
                        difference_median=median,difference_min=low,difference_max=high,count=resolved,
                        interpretation='CONDITIONAL_ON_ALL_51_OBSERVABLE_PRICE_OUTCOMES'),
                    complete_pair_population_price_mean=mean if matched and matched==resolved else None,
                    net_mean=None,confidence_interval=None,p_value=None,dsr=None,pbo=None,bootstrap=None,
                    inference_reason='UNAVAILABLE_FUNDING_AND_REGISTERED_NO_INFERENCE',
                    full_matched_authority=False,promotion_authority=False))
                if trial['archive_requirement']=='hourly':
                    result[-1].update(signals=None,matched_fifty=None,resolved_pairs=None,unresolved_pairs=None)
                    result[-1]['conditional_price']['count']=None
        for row in self.db.execute('''SELECT trial,direction,day,count(*),sum(matched),count(difference),sum(difference)
          FROM pairs GROUP BY trial,direction,day ORDER BY trial,direction,day'''):
            emit_day(dict(zip(('trial_id','direction','day','signals','matched_fifty','resolved_pairs','price_difference_sum'),row)))
        for row in self.db.execute('SELECT trial,direction,asset,time,n FROM reuse ORDER BY trial,direction,asset,time'):
            emit_reuse(dict(zip(('trial_id','direction','asset','decision_time','uses'),row)))
        return result

    def close(self):self.db.close()
