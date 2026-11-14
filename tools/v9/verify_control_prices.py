"""Independent registered A6 price-path audit over externally verified candles.

Uses direction-oriented prices and imports no production execution code.
This helper does not establish candle provenance or funding coverage.
"""
import math


def check(ok,message):
    if not ok:raise ValueError(message)


def finite(value):return type(value) in (int,float) and math.isfinite(value)


def verify(rows,decision,direction,geometry,eligible,disputes,end,outcome):
    check(type(decision) is int and decision>=0 and decision%14400==0 and
          type(end) is int and end>=0 and end%14400==0,'invalid clock')
    check(type(direction) is int and direction in (-1,1) and type(eligible) is bool,'invalid side')
    check(set(geometry)=={'stop','target','trail','be','hold'},'invalid geometry fields')
    check(all(finite(geometry[k]) for k in ('stop','target','trail','be')) and geometry['stop']>0 and
          min(geometry[k] for k in ('target','trail','be'))>=0 and type(geometry['hold']) is int and
          geometry['hold']>0,'invalid geometry')
    check(disputes is not None and all(type(t) is int and t>=0 and t%14400==0 for t in disputes),'invalid disputes')
    disputed=set(disputes)
    expected=dict(decision_time=decision,entry_time=decision,direction=direction,geometry=dict(geometry),
        status='UNEXECUTED',reason=None,entry_price=None,exit_time=None,exit_price=None,initial_risk=None,
        gross_R=None,cost_R=None,price_after_cost_R=None,net_R=None,funding_path_known=False,
        price_path_known=False,price_uncertainty_time=None,
        funding_reason='UNAVAILABLE_COVERAGE_AND_INTRABAR_ORDERING',full_matched_authority=False,promotion_authority=False)

    def candle(t):
        if t>=end:return None,'ARCHIVE_END'
        if t in disputed:return None,'DISPUTED_BAR'
        if t not in rows:return None,'MISSING_BAR'
        row=rows[t]
        if not isinstance(row,dict) or any(k not in row or not finite(row[k]) for k in ('o','h','l','c','qv')):
            return None,'MALFORMED_BAR'
        o,h,l,c,v=(float(row[k]) for k in ('o','h','l','c','qv'))
        if min(o,h,l,c)<=0 or not l<=min(o,c)<=max(o,c)<=h or v<0:return None,'MALFORMED_BAR'
        if v==0:return None,'ZERO_VOLUME_BAR'
        # Larger oriented prices always mean a more favorable price.
        return (direction*o,max(direction*h,direction*l),min(direction*h,direction*l),direction*c),None

    if not eligible:expected['reason']='ENTRY_INELIGIBLE'
    else:
        first,problem=candle(decision)
        if problem:expected.update(reason=problem,price_uncertainty_time=decision)
        else:
            entry=direction*first[0];risk=entry*geometry['stop'];origin=direction*entry
            stop=origin-risk;initial=stop;target=origin+geometry['target']*risk;best=origin
            check(all(math.isfinite(x) for x in (risk,stop,target)) and risk>0,'nonfinite geometry')
            expected.update(entry_price=entry,initial_risk=risk,status='UNRESOLVED_PRICE')
            for i in range(geometry['hold']):
                t=decision+i*14400;bar,problem=candle(t)
                if problem:
                    expected.update(reason=problem,price_uncertainty_time=t);break
                opening,high,low,close=bar;exit_value=None;reason=None
                if i>0 and opening<=stop:exit_value,reason=opening,'GAP_STOP'
                elif low<=stop:exit_value,reason=stop,('TIGHTENED_STOP' if stop>initial else 'STOP')
                elif geometry['target']>0 and high>=target:exit_value,reason=target,'TARGET'
                elif i+1==geometry['hold']:exit_value,reason=close,'TIME'
                if exit_value is not None:
                    price=direction*exit_value
                    gross=direction*(price/entry-1)/geometry['stop']
                    cost=(.00145+(.00015 if reason=='TARGET' else .00145))/geometry['stop']
                    check(all(math.isfinite(x) for x in (gross,cost,gross-cost)),'nonfinite return')
                    expected.update(status='PRICE_OBSERVED_FUNDING_UNKNOWN',reason=reason,exit_time=t+14400,
                        exit_price=price,gross_R=gross,cost_R=cost,price_after_cost_R=gross-cost,price_path_known=True)
                    break
                if geometry['trail']>0:
                    best=max(best,close);proposed=best-entry*geometry['trail']
                    check(math.isfinite(proposed),'nonfinite trailing threshold');stop=max(stop,proposed)
                excursion=(high-origin)/risk
                check(math.isfinite(excursion),'nonfinite favorable excursion')
                if geometry['be']>0 and excursion>=geometry['be']:stop=max(stop,origin)
    check(set(outcome)==set(expected),'outcome field mismatch')
    for key,value in expected.items():
        actual=outcome[key]
        if type(value) is float:
            check(finite(actual) and math.isclose(actual,value,rel_tol=1e-12,abs_tol=1e-12),'price audit mismatch: '+key)
        else:check(type(actual) is type(value) and actual==value,'price audit mismatch: '+key)
    return dict(price_path_verified=True,source_provenance_verified=False,funding_verified=False,
                full_matched_authority=False,promotion_authority=False)
